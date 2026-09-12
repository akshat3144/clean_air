"""Do drivers manage softer tyres harder in races than in practice?

THE QUESTION

Our race fits keep saying softer compounds do NOT degrade faster, which
contradicts how tyres work. The leading explanation is behavioural: in a race a
driver nurses a fragile tyre to hit a target lap time, so the measured
degradation is suppressed. In practice, where the team is deliberately measuring
the tyre, they push it. The benchmark paper suggested the same mechanism without
testing it.

If that is right, the ratio of race degradation to practice degradation should
be smaller for softer compounds. That is a directional, ordered prediction, and
it was written down in Step 3 before any pre-2026 data was pulled -- which is why
a trend test rather than an omnibus test is the honest choice here.

WHY THE LABEL IS THE RIGHT KEY HERE, UNUSUALLY

Everywhere else in this project we insist on the physical compound, because
HARD/MEDIUM/SOFT is relative to each weekend's nomination and pooling the label
across events mixes different rubber.

A ratio is the exception. Within ONE event, the label is the same physical tyre
in practice and in the race, so practice-to-race ratios are comparable even
though the underlying compounds differ between events. That is what lets this
analysis use 2024 and 2025, for which we have no allocation table.

The ordering claim does still assume that within an event the SOFT nomination is
softer than the MEDIUM one, which is true by construction of the nomination.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

#: Hardest to softest. The rank used by the trend test.
LABELS = ("HARD", "MEDIUM", "SOFT")
LABEL_RANK = {lab: i for i, lab in enumerate(LABELS)}

#: A ratio needs a denominator that is actually a degradation rate. Cells whose
#: practice rate is near zero give explosive or meaningless ratios.
MIN_PRACTICE_RATE = 0.005

#: Minimum runs behind a cell's slope.
MIN_RUNS = 3


@dataclass
class ManagementResult:
    cells: pd.DataFrame
    median_ratio: dict[str, float]
    n_cells: int
    n_events: int
    n_seasons: int
    rho: float
    p_value: float
    #: Two-sided p as well, so the conclusion can be checked without relying on
    #: the one-sided choice. Reported alongside for exactly that reason.
    p_two_sided: float
    #: An omnibus alternative. Weaker here by design -- it ignores the ordering
    #: we predicted -- but shown so the choice of test is visible rather than
    #: something the reader has to take on trust.
    p_kruskal: float

    @property
    def ordered(self) -> bool:
        """Does the ratio fall monotonically as the tyre softens?"""
        present = [lab for lab in LABELS if lab in self.median_ratio]
        return all(
            self.median_ratio[present[i]] > self.median_ratio[present[i + 1]]
            for i in range(len(present) - 1)
        )

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05

    def verdict(self) -> str:
        if self.ordered and self.significant:
            return "supported: ratio falls with softness, and the trend is significant"
        if self.ordered:
            return f"suggestive: ordering holds but p = {self.p_value:.3f}, not significant"
        return "not supported: the ordering does not hold"


def cluster_slope(g: pd.DataFrame) -> tuple[float, float] | None:
    """Slope of the centred design with a standard error clustered by run.

    Laps within a run are correlated, so an unclustered error would be far too
    small -- see validation/transfer for the coverage evidence.
    """
    x, y = g["tl"].to_numpy(float), g["y"].to_numpy(float)
    denom = float(x @ x)
    if denom <= 1e-9:
        return None
    slope = float(x @ y / denom)
    resid = y - slope * x
    clusters = g["run_id"].to_numpy()
    uniq = np.unique(clusters)
    if len(uniq) < 2:
        return slope, float("nan")
    meat = sum(float(x[clusters == c] @ resid[clusters == c]) ** 2 for c in uniq)
    se = float(np.sqrt(len(uniq) / (len(uniq) - 1) * meat) / denom)
    return slope, se


def cell_slopes(df: pd.DataFrame, min_runs: int = MIN_RUNS) -> pd.DataFrame:
    """One slope per (event, label)."""
    out = []
    for (event, label), g in df.groupby(["event", "Compound"], observed=True):
        if g["run_id"].nunique() < min_runs:
            continue
        got = cluster_slope(g)
        if got is None:
            continue
        slope, se = got
        out.append(
            {
                "event": event,
                "Compound": label,
                "rate": slope,
                "se": se,
                "n_runs": g["run_id"].nunique(),
                "n_laps": len(g),
            }
        )
    return pd.DataFrame(out)


def analyse(per_season: dict[int, tuple[pd.DataFrame, pd.DataFrame]]) -> ManagementResult:
    """Compare practice and race degradation across seasons.

    Args:
        per_season: {season: (practice_design_frame, race_design_frame)}.

    Returns:
        A ``ManagementResult``. The trend test is a one-sided Spearman
        correlation between compound softness and the race/practice ratio,
        one-sided because the direction was predicted in advance.
    """
    frames = []
    for season, (prac, race) in per_season.items():
        p = cell_slopes(prac).rename(columns={"rate": "practice", "se": "se_practice"})
        r = cell_slopes(race).rename(columns={"rate": "race", "se": "se_race"})
        if p.empty or r.empty:
            continue
        j = p.merge(r, on=["event", "Compound"], suffixes=("_p", "_r"))
        j["season"] = season
        frames.append(j)

    if not frames:
        raise ValueError("no season produced cells with both practice and race data")

    cells = pd.concat(frames, ignore_index=True)
    cells = cells[cells["practice"] > MIN_PRACTICE_RATE].copy()
    cells["ratio"] = cells["race"] / cells["practice"]
    cells["softness"] = cells["Compound"].map(LABEL_RANK)

    if len(cells) < 6:
        raise ValueError(f"only {len(cells)} usable cells; not enough to test a trend")

    # One-sided: the prediction is that softer means LOWER, so a negative
    # correlation. Halving a two-sided p is valid only because the direction was
    # fixed in advance.
    rho, p_two = spearmanr(cells["softness"], cells["ratio"])
    p_one = p_two / 2 if rho < 0 else 1 - p_two / 2

    # The omnibus test, for comparison. It asks only "are these three groups
    # different at all" and throws away the ordering, so it is less powerful
    # here. Reported so that switching to a trend test is an argument the reader
    # can check, not a quiet improvement to the p-value.
    groups = [cells[cells["Compound"] == lab]["ratio"].to_numpy() for lab in LABELS]
    groups = [g for g in groups if len(g) >= 3]
    p_kw = float(kruskal(*groups).pvalue) if len(groups) >= 2 else float("nan")

    return ManagementResult(
        cells=cells,
        median_ratio={
            lab: float(cells[cells["Compound"] == lab]["ratio"].median())
            for lab in LABELS
            if (cells["Compound"] == lab).sum() >= 3
        },
        n_cells=len(cells),
        n_events=cells["event"].nunique(),
        n_seasons=cells["season"].nunique(),
        rho=float(rho),
        p_value=float(p_one),
        p_two_sided=float(p_two),
        p_kruskal=p_kw,
    )
