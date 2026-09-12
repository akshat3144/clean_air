"""Per-circuit reference: what we know before a race weekend starts.

    python scripts/11_circuits.py

WHY THIS EXISTS

The console can answer for a race that has already happened, because that race
supplies its own pit loss and its own distance. An UPCOMING race supplies
neither, and those are two of the three inputs the optimiser needs.

Both are properties of the circuit rather than of the weekend, and F1 returns to
the same circuits, so previous seasons have them. Monza is on the calendar in
2022, 2023, 2024 and 2025. That is the reference this builds.

WHY IT IS A SCRIPT AND NOT COMPUTED ON DEMAND

Pit loss needs RAW laps -- ``clean_laps`` drops pit in- and out-laps, which are
the entire signal -- so it means opening race sessions through FastF1. That is
slow and wants the network, which is exactly the work that belongs on a
scheduled pass rather than behind an HTTP request.

WHAT IS AND IS NOT CARRIED

Race distance is the MAXIMUM completed laps across seasons, not the mean. A race
shortened by a red flag records fewer laps than it was scheduled for, and Monza
shows 46, 51 and 53 across three seasons for that reason. The longest is the one
that ran to the flag.

Pit loss is the median across seasons, with the spread reported. A circuit whose
pit loss moved between seasons -- resurfacing, a pit-lane change -- shows it, and
a wide spread is a reason to distrust the number rather than something to hide.

MATCHING A 2026 ROUND TO ITS OWN PAST

Race names move between circuits. In 2026 the SPANISH Grand Prix is at Madrid, a
circuit that has never held a race, while the Barcelona track it used to name
appears as the BARCELONA Grand Prix. Keying history on the event name alone gave
Madrid four seasons of Barcelona's pit lane -- a confident, precise, wrong
number for the one race this system exists to forecast.

Location alone does not work either, because the strings drift: Monaco is
"Monaco" in 2022 and "Monte Carlo" in 2026, Abu Dhabi moves from "Yas Island" to
"Yas Marina", and the 2026 row for Bahrain reads "Kuala Lumpur", which is simply
wrong. Trusting it blindly would delete history from three circuits to fix one.

So: match on Location first, since that is the real identity of a pit lane. Fall
back to the event name -- but VETO that match if the circuit the old race was
held at belongs to a DIFFERENT round of the 2026 calendar. That is exactly the
rename case and nothing else. Madrid ends up with no history and says so, which
is the honest answer and the one the UI is built to show.
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings

import fastf1
import numpy as np
import pandas as pd

from cleanair.config import ARTIFACTS, PROCESSED, PUBLISHED_RACE_LAPS
from cleanair.data.cache import load_session
from cleanair.data.schedule import rounds
from cleanair.strategy.pitloss import estimate

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

#: Seasons to mine for circuit history, newest first. Newest first matters: a
#: circuit resurfaced last winter is better described by last year than by 2022.
HISTORY_SEASONS = (2025, 2024, 2023, 2022)

OUT = ARTIFACTS / "circuits.json"


def race_distance(season: int, event: str) -> int | None:
    """Longest completed distance for this event, from the processed laps."""
    path = PROCESSED / (f"laps_{season}.parquet")
    if not path.exists():
        return None
    try:
        d = pd.read_parquet(path, columns=["event", "session", "LapNumber"])
    except Exception:  # noqa: BLE001
        return None
    g = d[(d["event"] == event) & (d["session"] == "R")]
    return int(g["LapNumber"].max()) if not g.empty else None


def season_index(season: int) -> tuple[dict[str, str], dict[str, str]]:
    """One season's calendar, indexed both ways.

    Returns ``(event_at_location, location_of_event)``, both keyed casefolded.
    Two indexes because neither key is trustworthy on its own -- see the module
    docstring.
    """
    try:
        sched = fastf1.get_event_schedule(season, include_testing=False)
    except Exception:  # noqa: BLE001 -- no network is a normal state here
        return {}, {}
    at_location, of_event = {}, {}
    for _, r in sched.iterrows():
        name = str(r["EventName"])
        loc = str(r.get("Location", "")).strip()
        if loc:
            at_location[loc.casefold()] = name
            of_event[name.casefold()] = loc.casefold()
    return at_location, of_event


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    # Every round, not just conventional ones: pit loss and race distance are
    # properties of the circuit and the race, and a sprint weekend races too.
    # Keyed by 2026 event name, because that is what the API looks up -- but
    # resolved by location, because that is what a pit loss belongs to.
    wanted = {r.event: r.location for r in rounds(args.season)}
    print(f"{len(wanted)} events on the {args.season} calendar")

    history = {season: season_index(season) for season in HISTORY_SEASONS}

    # Which 2026 round owns which circuit. This is what vetoes a name match:
    # if an old race was held somewhere that a DIFFERENT 2026 round now
    # occupies, its history belongs to that round and not to this one.
    owner = {loc.strip().casefold(): ev for ev, loc in wanted.items() if loc.strip()}

    out: dict[str, dict] = {}
    for event in sorted(wanted):
        here = wanted[event].strip().casefold()
        losses, distances, seen = [], [], []
        for season in HISTORY_SEASONS:
            at_location, of_event = history[season]
            # The name this circuit raced under THAT season, which is often not
            # the name it carries now.
            past = at_location.get(here)
            if not past:
                past = next((n for n in at_location.values() if n.casefold() == event.casefold()), None)
                if past:
                    then = of_event.get(past.casefold(), "")
                    if owner.get(then, event) != event:
                        past = None  # the rename case: it is another round's past
            if not past:
                continue
            dist = race_distance(season, past)
            try:
                s = load_session(past, "R", season, telemetry=False, weather=False)
                pl = estimate(s.laps, past)
            except Exception:  # noqa: BLE001 -- a circuit we have never raced is normal
                s, pl = None, None

            # Distance from the SESSION when the parquet has none.
            #
            # The processed per-season files hold conventional weekends only,
            # so every sprint venue -- China, Sao Paulo, Qatar -- had a pit
            # loss and no race distance, and the console asked a human to type
            # a lap count we had already downloaded. The race session is
            # loaded here anyway for the pit loss, so this costs no extra
            # network.
            if not dist and s is not None:
                try:
                    dist = int(s.laps["LapNumber"].max())
                except Exception:  # noqa: BLE001
                    dist = None
            if dist:
                distances.append(dist)
            if pl:
                losses.append(round(pl.seconds, 2))
                seen.append(season)

        published = PUBLISHED_RACE_LAPS.get(event)
        if not losses and not distances and published is None:
            print(f"  {event:28s} no history  ({wanted[event] or 'unknown location'})")
            continue

        row: dict = {"event": event, "location": wanted[event], "seasons": seen}
        if losses:
            row["pit_loss_s"] = round(float(np.median(losses)), 2)
            row["pit_loss_spread_s"] = round(float(max(losses) - min(losses)), 2)
            row["pit_loss_by_season"] = dict(zip(seen, losses, strict=True))
        if distances:
            # Longest completed, not the mean: a shortened race is not the
            # circuit's distance.
            row["race_laps"] = int(max(distances))
            row["race_laps_seen"] = sorted(set(distances))
            row["race_laps_source"] = "measured"
        elif published is not None:
            # A circuit we have never raced still has a published distance --
            # the FIA fixes it and it is on the circuit page before anyone
            # drives. Having no history is not the same as the number being
            # unknown, and making someone type it suggested otherwise.
            # History wins wherever we have it; this only fills a genuine gap.
            row["race_laps"] = int(published)
            row["race_laps_source"] = "published"
        out[event] = row

        pit = f"{row['pit_loss_s']:.1f}s" if losses else "  -  "
        spread = f"±{row['pit_loss_spread_s']:.1f}" if len(losses) > 1 else ""
        laps = row.get("race_laps", "-")
        print(f"  {event:28s} pit {pit:>7s} {spread:>6s}   laps {laps}   from {seen or 'none'}")

    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}  ({len(out)} circuits)")

    thin = [e for e, r in out.items() if "pit_loss_s" not in r]
    if thin:
        print(f"\n{len(thin)} circuit(s) have no pit-loss history; the console must ask:")
        for e in thin:
            print(f"    {e}")


if __name__ == "__main__":
    main()
