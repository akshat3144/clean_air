"""Download and cache every session we need, so Challenge Day needs no network.

Run this well before the event, and copy data/fastf1_cache/ to every laptop.

    python scripts/01_cache_sessions.py
    python scripts/01_cache_sessions.py --events "Italian Grand Prix"

Only conventional weekends are included by default. Sprint weekends run FP1 then
Sprint Qualifying, so they carry no race-simulation long runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime

import pandas as pd

from cleanair.config import CONVENTIONAL_2026, PROCESSED, SEASON
from cleanair.data.cache import load_session
from cleanair.data.laps import clean_laps, summarise, tag_long_runs

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logging.getLogger("fastf1").setLevel(logging.ERROR)

SESSIONS = ("FP1", "FP2", "FP3", "R")


def _conventional_events(season: int) -> list[str]:
    """Conventional weekends for a season, from the schedule.

    Sprint weekends run only FP1 before Sprint Qualifying, so they carry no
    race-simulation long runs and are excluded.
    """
    import fastf1

    from cleanair.data.cache import enable_cache

    enable_cache()
    sched = fastf1.get_event_schedule(season, include_testing=False)
    return sched[sched["EventFormat"] == "conventional"]["EventName"].tolist()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", nargs="*", default=None)
    ap.add_argument("--sessions", nargs="*", default=list(SESSIONS))
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--out", default=None, help="parquet filename; defaults per season")
    args = ap.parse_args()

    # 2026 keeps writing laps.parquet so nothing downstream changes. Earlier
    # seasons go to their own file: their tyre construction differs, so their
    # degradation rates must never be pooled with 2026's by accident.
    if args.events is None:
        args.events = (
            list(CONVENTIONAL_2026)
            if args.season == SEASON
            else _conventional_events(args.season)
        )
    out_name = args.out or ("laps.parquet" if args.season == SEASON
                            else f"laps_{args.season}.parquet")

    frames, rows = [], []
    for event in args.events:
        for ses in args.sessions:
            t0 = time.time()
            try:
                s = load_session(event, ses, args.season)
                clean = clean_laps(s.laps, event=event, session=ses)
                frames.append(clean)
                print(
                    f"  ok   {event:24s} {ses:3s}  raw={len(s.laps):4d} "
                    f"clean={len(clean):4d}  ({time.time() - t0:4.1f}s)",
                    flush=True,
                )
            except Exception as exc:  # one bad session must not stop the batch
                print(f"  FAIL {event:24s} {ses:3s}  {type(exc).__name__}: {exc}"[:120], flush=True)
                rows.append({"event": event, "session": ses, "error": str(exc)[:200]})

    if not frames:
        print("\nnothing loaded")
        return

    fresh = pd.concat(frames, ignore_index=True)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    out = PROCESSED / out_name

    # MERGE, never replace.
    #
    # This used to write only what it had just pulled, which was fine while the
    # only caller asked for a whole season. It is catastrophic the moment
    # anything asks for one event: the poller fetching Monza on Friday would
    # have replaced seven complete events with one, and the failure looks like a
    # successful pull.
    #
    # Sessions we just fetched replace their previous copies; everything else is
    # kept. A pull that partially fails therefore degrades to "we still have
    # what we had", which is the right direction to fail in.
    if out.exists():
        try:
            existing = pd.read_parquet(out)
            pulled = set(zip(fresh["event"], fresh["session"], strict=True))
            keep = existing[
                ~pd.Series(
                    list(zip(existing["event"], existing["session"], strict=True)),
                    index=existing.index,
                ).isin(pulled)
            ]
            if not keep.empty:
                print(
                    f"\nmerging with {len(keep):,} existing laps "
                    f"across {keep['event'].nunique()} event(s)"
                )
                fresh = pd.concat([keep, fresh], ignore_index=True)
        except Exception as exc:  # noqa: BLE001 -- a corrupt old file must not block a good pull
            print(f"\ncould not read existing {out.name} ({type(exc).__name__}); writing fresh")

    # Tag long runs once, across everything. Doing it per session made run_id
    # restart at 0 for each one, so ids collided after concatenation. Re-tagging
    # the merged frame is safe because run_id is a readable composite key rather
    # than a per-call code.
    df = tag_long_runs(fresh)
    df.to_parquet(out, index=False)

    # A season that half-downloaded looks exactly like a complete one on disk:
    # the parquet holds whatever arrived and records nothing about what did not.
    # The F1 API caps at 500 calls/hour, so a truncated pull is a normal event,
    # not a rare one, and pooling one silently would drop whole events from an
    # analysis without anyone noticing. The manifest is what lets downstream
    # scripts refuse it.
    manifest = {
        "season": args.season,
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "parquet": out.name,
        "sessions_requested": len(args.events) * len(args.sessions),
        "sessions_loaded": len(frames),
        "sessions_failed": len(rows),
        "events_requested": sorted(args.events),
        "events_loaded": sorted(df["event"].unique().tolist()),
        "complete": not rows,
        "failures": rows,
        # What the MERGED file now holds, per event. `complete` above describes
        # this pull; this describes the artifact on disk, which after a merge
        # are different questions.
        "sessions_by_event": {
            str(ev): sorted(g["session"].unique().tolist())
            for ev, g in df.groupby("event", sort=True)
        },
    }
    man = out.with_name(f"{out.stem}.manifest.json")
    man.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"\nwrote {out}  ({len(df):,} clean laps)")
    print(f"wrote {man}  (complete={manifest['complete']})")
    print("\n" + summarise(df).to_string(index=False))

    long_runs = df[df.is_long_run]
    print(
        f"\nTOTAL long-run laps: {len(long_runs):,} "
        f"across {long_runs.run_id.nunique()} runs and {long_runs.Driver.nunique()} drivers"
    )
    if rows:
        print(f"\n{len(rows)} session(s) failed:")
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
