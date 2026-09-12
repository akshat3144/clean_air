"""Turn the degradation curves into a pit-stop decision.

    python scripts/06_strategy.py
    python scripts/06_strategy.py --event "Hungarian Grand Prix"

Three measured inputs: degradation per compound, pit loss per circuit, and the
fresh-tyre pace gap between compounds. Then every legal strategy is enumerated
and scored, so the recommendation is exact rather than the output of a search
that might have stopped early.
"""

from __future__ import annotations

import argparse
import logging
import warnings

import pandas as pd

from cleanair.artifacts import schema
from cleanair.artifacts.schema import Interval, StrategyArtifact, StrategyPlan
from cleanair.config import COMPOUND_ALLOCATION_2026, PROCESSED
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

#: Fresh-tyre pace gap between adjacent compounds, seconds.
#:
#: ASSUMED, not fitted, and this is the weakest input in the whole layer.
#:
#: We tried to measure it two ways. In races, compound choice is correlated with
#: car pace, so the fitted offsets came back with intervals of +/-0.5s spanning
#: zero -- useless. Within driver and session in practice, the medians were
#: correctly signed but implied 1.0-1.7s per step, because a driver's best lap
#: on each compound comes from different fuel loads and track states.
#:
#: So we use the figure the sport itself quotes, around 0.6s per step, and treat
#: the strategy output as conditional on it. Anything that turns on this number
#: needs saying out loud.
PACE_STEP_S = 0.60


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--event", default="Hungarian Grand Prix")
    ap.add_argument("--laps", type=int, default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    laps = pd.read_parquet(PROCESSED / "laps.parquet")
    race = prepare(laps, "race")
    fit = fit_degradation(race, quadratic=False, context="race")

    ev = race[race["event"] == args.event]
    race_laps = args.laps or int(ev["LapNumber"].max())

    pl_table = estimate_all([args.event])
    if pl_table.empty:
        raise SystemExit(f"could not measure pit loss for {args.event!r}")
    pit_loss = float(pl_table["pit_loss_s"].iloc[0])

    # A strategy can only use the three compounds Pirelli nominated for THIS
    # weekend. Without this the optimiser happily proposed C1 and C2 at Hungary,
    # where the allocation was C3/C4/C5 -- tyres that were never at the circuit.
    nominated = set(COMPOUND_ALLOCATION_2026.get(args.event, {}).values())
    if not nominated:
        raise SystemExit(f"no compound allocation known for {args.event!r}")

    # And only compounds whose fitted degradation is positive can be optimised on.
    rates = {
        c: fit.rates[c].mean
        for c in fit.ordered
        if c in nominated and fit.rates[c].mean > 0
    }
    order = [c for c in ("C1", "C2", "C3", "C4", "C5") if c in rates]
    offsets = {c: -PACE_STEP_S * i for i, c in enumerate(order)}

    print("=" * 72)
    print(f"{args.event} — {race_laps} laps")
    print("=" * 72)
    print(f"   pit loss {pit_loss:.1f}s  (measured from {int(pl_table['n_stops'].iloc[0])} green stops)")
    print(f"\n   {'compound':10s}{'degradation':>14s}{'fresh pace':>13s}{'best stint':>13s}")
    for c in order:
        print(f"   {c:10s}{rates[c]:+14.4f}{offsets[c]:+13.2f}"
              f"{optimal_stint(c, rates[c], pit_loss):11d} laps")

    rejected = [c for c in fit.ordered if c in nominated and fit.rates[c].mean <= 0]
    if rejected:
        print(f"\n   excluded, fitted degradation not positive: {rejected}")
        print("   An optimiser handed a tyre that never wears will run it to the flag.")

    plans = enumerate_plans(race_laps, rates, offsets, pit_loss, step=1)
    print(f"\n   {len(plans):,} legal strategies enumerated"
          " (2+ compounds, 5-lap minimum stints)")

    best = best_per_stop_count(plans)
    print(f"\n   {'plan':44s}{'total':>10s}{'vs best':>10s}")
    top = plans[0].total_time
    for n in sorted(best):
        p = best[n]
        print(f"   {p.describe():44s}{p.total_time:10.1f}{p.total_time - top:+10.1f}")

    rec = plans[0]
    runner_up = next((p for p in plans if p.n_stops != rec.n_stops), None)
    margin = (runner_up.total_time - rec.total_time) if runner_up else 0.0

    x = crossover(plans)
    print(f"\n   recommended: {rec.describe()}")
    print(f"   margin over the best alternative stop count: {margin:.1f}s")
    if x:
        print(f"   one-stop/two-stop crossover at pit loss {x:.1f}s "
              f"(this circuit is {pit_loss:.1f}s)")
    else:
        print("   no crossover between 15s and 35s of pit loss: the answer is not close")

    # Confidence from the margin relative to the degradation uncertainty, not
    # from thin air. A 1s margin on a 70-lap race is a coin flip.
    conf = min(0.95, max(0.05, margin / 10.0))
    print(f"   confidence {conf:.0%}  (from the margin, not asserted)")

    if not args.no_write:
        schema.write(
            "strategy",
            StrategyArtifact(
                event=args.event,
                pit_loss_s=round(pit_loss, 2),
                race_laps=race_laps,
                plans=[
                    StrategyPlan(
                        n_stops=p.n_stops,
                        compounds=list(p.compounds),
                        stint_lengths=list(p.stints),
                        total_time=Interval(
                            mean=round(p.total_time, 2),
                            lo=round(p.total_time - 3.0, 2),
                            hi=round(p.total_time + 3.0, 2),
                        ),
                    )
                    for p in (best[n] for n in sorted(best))
                ],
                recommended_stops=rec.n_stops,
                rationale=(
                    f"{rec.describe()} is {margin:.1f}s faster than the best "
                    f"{runner_up.n_stops}-stop alternative at a measured pit loss of "
                    f"{pit_loss:.1f}s."
                    + (f" The crossover sits at {x:.1f}s." if x else "")
                ),
                confidence=round(conf, 2),
                optimal_stint={
                    c: Interval(
                        mean=float(optimal_stint(c, rates[c], pit_loss)),
                        lo=float(optimal_stint(c, rates[c], pit_loss * 0.85)),
                        hi=float(optimal_stint(c, rates[c], pit_loss * 1.15)),
                    )
                    for c in order
                },
            ),
        )
        print("\nwrote strategy.json")


if __name__ == "__main__":
    main()
