"""Compute the strategy call for every event, not just one.

    python scripts/09_playbook.py

WHY THIS EXISTS

``06_strategy.py`` answers one event, because it was written to show the
optimiser works. That is a proof, not a product. Nobody can use a tool that
answers for Hungary when they are at Monza, so this runs the same layer across
every event we have and writes it as one artifact the app can page through.

It also adds the two things that turn a correct recommendation into a usable
one.

WHAT IT COSTS TO BE WRONG
    The pit loss is measured, so it has error. ``crossover_pit_loss_s`` is the
    pit loss at which the recommendation would flip to a different stop count.
    If the circuit measures 22.3s and the crossover sits at 24.5s, the call
    survives 2.2s of error and a strategist knows exactly how much rope there
    is. Where there is no crossover between 15s and 35s, the answer is not
    close and we say so.

WHAT THE TEAMS ACTUALLY DID
    Every recommendation is reported next to the distribution of stop counts
    the field really ran. This is the only part of the strategy layer that is
    checkable against reality by someone who watched the race, so it is the
    part that earns or loses trust. When we disagree with fifteen cars, that is
    worth seeing rather than hiding behind a confidence number.
"""

from __future__ import annotations

import argparse
import logging
import warnings

import pandas as pd

from cleanair.artifacts import schema
from cleanair.artifacts.schema import (
    Interval,
    PlaybookArtifact,
    PlaybookCompound,
    PlaybookEvent,
    PlaybookPlan,
)
from cleanair.config import PROCESSED
from cleanair.data.allocation import compounds_for
from cleanair.models.design import prepare
from cleanair.models.mixed import fit_degradation
from cleanair.strategy.optimise import (
    best_per_stop_count,
    crossover,
    enumerate_plans,
    optimal_stint,
)
from cleanair.strategy.pitloss import estimate_all

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

#: Same assumed fresh-tyre pace gap 06_strategy uses. Imported rather than
#: redefined would be better, but it is a module-level constant in a script
#: rather than the library, so it is restated here and surfaced in the artifact
#: so a reader can see it is assumed.
PACE_STEP_S = 0.6


def actual_stops(race: pd.DataFrame, event: str) -> tuple[dict[str, int], int | None, int]:
    """How many stops each car actually made, from the timing data.

    A car's stint count is the number of distinct Stint values it recorded, so
    stops are that minus one.

    Cars showing ZERO stops are held out of the distribution. A dry race
    requires two compounds, so a car that never pitted retired before its first
    stop; it did not execute a strategy, and letting it vote on the median
    compares our recommendation against a DNF. Monaco has five such cars. They
    are returned as a count rather than dropped silently, because "five cars
    never pitted" is information about the race.
    """
    ev = race[race["event"] == event]
    if ev.empty:
        return {}, None, 0
    per_driver = ev.groupby("Driver")["Stint"].nunique() - 1
    per_driver = per_driver[per_driver >= 0]
    if per_driver.empty:
        return {}, None, 0

    retired = int((per_driver == 0).sum())
    ran = per_driver[per_driver >= 1]
    if ran.empty:
        return {}, None, retired
    counts = ran.value_counts().sort_index()
    return (
        {str(int(k)): int(v) for k, v in counts.items()},
        int(ran.median()),
        retired,
    )


def build_event(
    race: pd.DataFrame,
    fit,
    event: str,
    pit_loss: float,
    n_green_stops: int,
) -> PlaybookEvent | None:
    """The full decision for one event, or None if it cannot be computed."""
    ev = race[race["event"] == event]
    if ev.empty:
        return None
    race_laps = int(ev["LapNumber"].max())

    allocation = compounds_for(event)
    if not allocation:
        return None
    label_of = {c: lab for lab, c in allocation.items()}
    nominated = set(allocation.values())

    # Only compounds with a positive fitted degradation can be optimised on.
    usable = {
        c: fit.rates[c].mean
        for c in fit.ordered
        if c in nominated and fit.rates[c].mean > 0
    }
    if len(usable) < 2:
        # Two compounds is the regulatory minimum for a dry race, so with fewer
        # than two usable rates there is no legal plan to enumerate.
        return None

    order = [c for c in ("C1", "C2", "C3", "C4", "C5") if c in usable]
    offsets = {c: -PACE_STEP_S * i for i, c in enumerate(order)}

    compounds = []
    for c in sorted(nominated, key=lambda x: ("C1", "C2", "C3", "C4", "C5").index(x)):
        if c not in fit.rates:
            continue
        r = fit.rates[c]
        excluded = c not in usable
        compounds.append(
            PlaybookCompound(
                compound=c,
                label=label_of.get(c, "MEDIUM"),
                rate=Interval(round(r.mean, 5), round(r.lo, 5), round(r.hi, 5)),
                optimal_stint=0 if excluded else int(optimal_stint(c, usable[c], pit_loss)),
                excluded=excluded,
            )
        )

    plans_all = enumerate_plans(race_laps, usable, offsets, pit_loss, step=1)
    if not plans_all:
        return None
    best = best_per_stop_count(plans_all)
    top = plans_all[0].total_time

    plans = [
        PlaybookPlan(
            n_stops=p.n_stops,
            compounds=list(p.compounds),
            stint_lengths=[int(x) for x in p.stints],
            total_time=round(p.total_time, 2),
            delta_s=round(p.total_time - top, 2),
        )
        for _, p in sorted(best.items(), key=lambda kv: kv[1].total_time)
    ]

    rec = plans_all[0]
    runner_up = next((p for p in plans_all if p.n_stops != rec.n_stops), None)
    margin = (runner_up.total_time - rec.total_time) if runner_up else 0.0
    x = crossover(plans_all)
    counts, median_stops, retired = actual_stops(race, event)

    return PlaybookEvent(
        event=event,
        race_laps=race_laps,
        pit_loss_s=round(pit_loss, 2),
        n_green_stops=n_green_stops,
        compounds=compounds,
        plans=plans,
        n_plans_enumerated=len(plans_all),
        recommended_stops=rec.n_stops,
        margin_s=round(margin, 2),
        # Confidence from the margin, not asserted. A 1s margin over a 70-lap
        # race is a coin flip and should read like one.
        confidence=round(min(0.95, max(0.05, margin / 10.0)), 3),
        crossover_pit_loss_s=round(x, 2) if x else None,
        actual_stop_counts=counts,
        actual_median_stops=median_stops,
        n_retired_before_stop=retired,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    laps = pd.read_parquet(PROCESSED / "laps.parquet")
    race = prepare(laps, "race")
    fit = fit_degradation(race, quadratic=False, context="race")

    events = sorted(race["event"].unique())
    print(f"measuring pit loss for {len(events)} events...", flush=True)
    pl = estimate_all(events)

    out: list[PlaybookEvent] = []
    for event in events:
        row = pl[pl["event"] == event] if not pl.empty else pd.DataFrame()
        if row.empty:
            print(f"  {event:28s} SKIPPED -- no pit-loss measurement")
            continue
        built = build_event(
            race,
            fit,
            event,
            float(row["pit_loss_s"].iloc[0]),
            int(row["n_stops"].iloc[0]),
        )
        if built is None:
            print(f"  {event:28s} SKIPPED -- no legal plan (fewer than 2 usable compounds)")
            continue
        out.append(built)

    if not out:
        raise SystemExit("no event produced a plan")

    print()
    print("=" * 78)
    print(f"{'event':26s}{'laps':>5s}{'pit':>7s}{'call':>7s}{'margin':>8s}{'flips at':>10s}{'field ran':>12s}")
    print("=" * 78)
    for e in out:
        flip = f"{e.crossover_pit_loss_s:.1f}s" if e.crossover_pit_loss_s else "not close"
        field = (
            f"{e.actual_median_stops} (median)" if e.actual_median_stops is not None else "unknown"
        )
        print(
            f"{e.event:26s}{e.race_laps:5d}{e.pit_loss_s:7.1f}"
            f"{e.recommended_stops:5d}{'':2s}{e.margin_s:8.1f}{flip:>10s}{field:>12s}"
        )

    agree = [e for e in out if e.actual_median_stops == e.recommended_stops]
    print()
    print(f"  we agree with the field's median call at {len(agree)} of {len(out)} events")
    print("  Disagreement is not automatically our error -- teams optimise for")
    print("  position and traffic, we optimise for total time -- but it is the")
    print("  number a reader should see first.")

    if not args.no_write:
        schema.write("playbook", PlaybookArtifact(events=out, pace_step_s=PACE_STEP_S))
        print("\nwrote playbook.json")


if __name__ == "__main__":
    main()
