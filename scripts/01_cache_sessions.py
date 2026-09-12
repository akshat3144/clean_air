"""Download and cache every session we need, so Challenge Day needs no network.

Run this well before the event, and copy data/fastf1_cache/ to every laptop.

    python scripts/01_cache_sessions.py
    python scripts/01_cache_sessions.py --events "Italian Grand Prix"

Only conventional weekends are included by default. Sprint weekends run FP1 then
Sprint Qualifying, so they carry no race-simulation long runs.
"""

from __future__ import annotations

import argparse
import logging
import time

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

    # Tag long runs once, across everything. Doing it per session made run_id
    # restart at 0 for each one, so ids collided after concatenation.
    df = tag_long_runs(pd.concat(frames, ignore_index=True))

    PROCESSED.mkdir(parents=True, exist_ok=True)
    out = PROCESSED / out_name
    df.to_parquet(out, index=False)

    print(f"\nwrote {out}  ({len(df):,} clean laps)")
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
