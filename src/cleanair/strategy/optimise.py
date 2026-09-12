"""Turning degradation curves into a decision.

A curve is an intermediate result. What a strategist needs is: how long do I
stay out, and is one stop faster than two?

Three inputs, and all three are measured rather than assumed:

  degradation   seconds lost per lap of tyre age, per compound (models/mixed)
  pace offset   how much faster a compound is when fresh (strategy/pitloss's
                sibling -- measured within driver and session in practice)
  pit loss      seconds lost by stopping, per circuit (strategy/pitloss)

Total race time for a stint of L laps on compound c has a closed form, so there
is no need to simulate lap by lap:

    time(c, L) = L * offset_c
               + rate_c  * L(L+1)/2            (sum of 1..L)
               + curv_c  * L(L+1)(2L+1)/6      (sum of squares)

Enumerating every split of the race across stints is then cheap enough to be
exact, which avoids an optimiser that might find a local minimum and report it
with unearned confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations_with_replacement, permutations

import numpy as np

#: A stint shorter than this is not a strategy, it is a mistake. Prevents the
#: enumeration proposing a two-lap stint to game the arithmetic.
MIN_STINT_LAPS = 5

#: Formula 1 sporting regulations: in a dry race a car must use at least two
#: different compounds. A one-compound strategy is not merely slow, it is
#: illegal, so it must never be recommended.
MIN_DISTINCT_COMPOUNDS = 2


@dataclass(frozen=True)
class Plan:
    compounds: tuple[str, ...]
    stints: tuple[int, ...]
    total_time: float
    #: Time from tyres alone, with the pit loss stripped out. Kept separately so
    #: pit loss can be varied without refitting anything -- which is exactly what
    #: the crossover calculation needs.
    tyre_time: float = 0.0

    @property
    def n_stops(self) -> int:
        return len(self.stints) - 1

    def describe(self) -> str:
        parts = [f"{c} x{n}" for c, n in zip(self.compounds, self.stints, strict=True)]
        return f"{self.n_stops}-stop: " + " -> ".join(parts)


def stint_time(
    laps: int,
    rate: float,
    offset: float = 0.0,
    curvature: float = 0.0,
) -> float:
    """Time lost over a stint, relative to a hypothetical fresh-tyre baseline.

    Closed form rather than a loop: exact, and fast enough to enumerate every
    strategy rather than search for one.
    """
    if laps <= 0:
        return 0.0
    n = float(laps)
    return (
        n * offset
        + rate * n * (n + 1) / 2
        + curvature * n * (n + 1) * (2 * n + 1) / 6
    )


def _splits(total: int, n_stints: int, min_laps: int, step: int = 1):
    """Every way to divide ``total`` laps into ``n_stints`` parts."""
    if n_stints == 1:
        if total >= min_laps:
            yield (total,)
        return
    for first in range(min_laps, total - min_laps * (n_stints - 1) + 1, step):
        for rest in _splits(total - first, n_stints - 1, min_laps, step):
            yield (first, *rest)


def enumerate_plans(
    race_laps: int,
    rates: dict[str, float],
    offsets: dict[str, float],
    pit_loss_s: float,
    curvature: dict[str, float] | None = None,
    max_stops: int = 3,
    min_stint: int = MIN_STINT_LAPS,
    step: int = 1,
) -> list[Plan]:
    """Every legal strategy, scored. Cheapest first.

    Args:
        race_laps: scheduled distance.
        rates: degradation, s/lap, keyed by compound.
        offsets: fresh-tyre pace, s/lap, keyed by compound. Lower is faster.
        pit_loss_s: seconds lost per stop.
        curvature: optional quadratic term per compound.
        max_stops: highest stop count to consider.

    Returns:
        Legal plans sorted by total time. Plans using fewer than two distinct
        compounds are excluded, because the regulations forbid them in the dry.
    """
    curvature = curvature or {}
    available = [c for c in rates if c in offsets]

    # Refuse compounds whose fitted degradation is not positive.
    #
    # This is not fastidiousness. Our C5 estimate came out at -0.004 s/lap --
    # statistically indistinguishable from zero, but the optimiser reads it as
    # a tyre that gets FASTER as it wears, and duly recommends fitting softs on
    # lap 5 and running 65 laps to the flag. An optimiser will always exploit a
    # non-physical input, and it will do so with total confidence.
    #
    # Same discipline as the identifiability filter in the transfer step: refuse
    # the input rather than dress up the output.
    unphysical = [c for c in available if rates[c] <= 0]
    available = [c for c in available if rates[c] > 0]

    if len(available) < MIN_DISTINCT_COMPOUNDS:
        raise ValueError(
            f"need at least {MIN_DISTINCT_COMPOUNDS} compounds with a positive "
            f"fitted degradation rate and a pace offset. "
            f"usable: {available}; rejected as non-physical: {unphysical}. "
            "A strategy cannot be optimised on a tyre the model thinks never wears."
        )

    plans: list[Plan] = []
    for n_stops in range(1, max_stops + 1):
        n_stints = n_stops + 1
        if race_laps < min_stint * n_stints:
            continue

        # combinations_with_replacement gives the multisets; permuting each one
        # then assigns compounds to slots. Two things here are easy to get wrong.
        #
        # First, sequence does not affect total_time. Every stint starts at age
        # zero, so the total is a sum over unordered (compound, laps) pairs --
        # across the 1.47M plans at Barcelona, not one pairing's orderings
        # disagree by more than 1e-12. The permutation loop survives anyway
        # because _splits is not permutation-closed once step > 1: it walks the
        # first stint along a lattice and lets the last absorb the remainder, so
        # permuting the compounds reaches pairings permuting the laps cannot.
        # Dropping it changes the step=2 optimum, which is the coarse grid the
        # console answers with while you drag.
        #
        # Second, sorted(). Set iteration follows the hash seed, and the best
        # plan is routinely an exact tie -- six ways at Barcelona. Unsorted, the
        # same data recommended "C2 x23 -> C3 x19 -> C2 x24" on one boot and
        # "C3 x19 -> C2 x23 -> C2 x24" on the next. The sequence we print is
        # therefore a stable convention, not a claim: the model ranks which
        # compound runs which stint length, and is indifferent to their order.
        for combo in combinations_with_replacement(available, n_stints):
            if len(set(combo)) < MIN_DISTINCT_COMPOUNDS:
                continue
            for perm in sorted(set(permutations(combo))):
                for stints in _splits(race_laps, n_stints, min_stint, step):
                    tyre_time = sum(
                        stint_time(laps, rates[c], offsets[c], curvature.get(c, 0.0))
                        for c, laps in zip(perm, stints, strict=True)
                    )
                    plans.append(
                        Plan(perm, stints, tyre_time + pit_loss_s * n_stops, tyre_time)
                    )

    plans.sort(key=lambda p: p.total_time)
    return plans


def best_per_stop_count(plans: list[Plan]) -> dict[int, Plan]:
    """The cheapest plan for each stop count. What the crossover chart needs."""
    out: dict[int, Plan] = {}
    for p in plans:
        if p.n_stops not in out or p.total_time < out[p.n_stops].total_time:
            out[p.n_stops] = p
    return out


def optimal_stint(
    compound: str,
    rate: float,
    pit_loss_s: float,
    curvature: float = 0.0,
    max_laps: int = 60,
) -> int:
    """Stint length that minimises average time per lap including the stop.

    The textbook trade-off: staying out longer spreads the pit loss over more
    laps, but every extra lap is slower than the last. The minimum of
    (stint time + pit loss) / laps is where those balance.
    """
    lengths = np.arange(MIN_STINT_LAPS, max_laps + 1)
    per_lap = [
        (stint_time(int(n), rate, 0.0, curvature) + pit_loss_s) / n for n in lengths
    ]
    return int(lengths[int(np.argmin(per_lap))])


def crossover(
    plans: list[Plan],
    pit_loss_range: tuple[float, float] = (15.0, 35.0),
    steps: int = 41,
) -> float | None:
    """Pit loss at which the best one-stop overtakes the best two-stop.

    The single most useful number in the whole strategy layer, because pit loss
    is the input a team can least control and most needs to plan around. Below
    the crossover, stopping twice is worth it; above it, stay out.

    Returns None if one option wins across the entire range.
    """
    one = [p for p in plans if p.n_stops == 1]
    two = [p for p in plans if p.n_stops == 2]
    if not one or not two:
        return None

    # Compare on TYRE time only, so pit loss can be swept independently.
    # Using total_time here would double-count it, since total_time already
    # includes the pit loss the plan was scored with.
    one_tyre = min(p.tyre_time for p in one)
    two_tyre = min(p.tyre_time for p in two)

    prev = None
    for pl in np.linspace(*pit_loss_range, steps):
        favours_two = (two_tyre + 2 * pl) < (one_tyre + 1 * pl)
        if prev is not None and favours_two != prev:
            return float(pl)
        prev = favours_two
    return None
