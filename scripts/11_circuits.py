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
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings

import numpy as np
import pandas as pd

from cleanair.config import ARTIFACTS, PROCESSED
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    # Every round, not just conventional ones: pit loss and race distance are
    # properties of the circuit and the race, and a sprint weekend races too.
    wanted = sorted({r.event for r in rounds(args.season)})
    print(f"{len(wanted)} events on the {args.season} calendar")

    out: dict[str, dict] = {}
    for event in wanted:
        losses, distances, seen = [], [], []
        for season in HISTORY_SEASONS:
            dist = race_distance(season, event)
            if dist:
                distances.append(dist)
            try:
                s = load_session(event, "R", season, telemetry=False, weather=False)
                pl = estimate(s.laps, event)
            except Exception:  # noqa: BLE001 -- a circuit we have never raced is normal
                pl = None
            if pl:
                losses.append(round(pl.seconds, 2))
                seen.append(season)

        if not losses and not distances:
            print(f"  {event:28s} no history")
            continue

        row: dict = {"event": event, "seasons": seen}
        if losses:
            row["pit_loss_s"] = round(float(np.median(losses)), 2)
            row["pit_loss_spread_s"] = round(float(max(losses) - min(losses)), 2)
            row["pit_loss_by_season"] = dict(zip(seen, losses, strict=True))
        if distances:
            # Longest completed, not the mean: a shortened race is not the
            # circuit's distance.
            row["race_laps"] = int(max(distances))
            row["race_laps_seen"] = sorted(set(distances))
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
