"""How much data does separating two compounds actually need?

This answers the open question the benchmark paper leaves behind. They could not
distinguish a Hard from a Medium and attributed it to "not much data to
differentiate what would likely be a small effect size" -- but they never said
how much data would have been enough.

We can say. Simulate races with the real design, inject a known difference
between two compounds, refit, and count how often it is detected. Repeat across
sample sizes and read off the point where power reaches 80%.

Two things fall out:

  1. Whether the benchmark's null result was inevitable given their three
     stints, or whether they were unlucky. If a design that size has 10% power,
     their finding says nothing about tyres and everything about sample size.

  2. Whether OUR result is trustworthy. A significant finding from an
     underpowered design is more likely to be noise than signal, so this is a
     check on ourselves as much as on them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

#: Difference we care about detecting, s/lap. Roughly the gap the benchmark
#: reported between Hard and Medium (0.054 vs 0.060), i.e. the effect size that
#: study was implicitly trying to resolve.
DEFAULT_EFFECT = 0.006

#: Residual lap-time scatter after the design removes shared effects, seconds.
#: Taken from our own race fit; a driver's lap times wobble by roughly this much
#: for reasons that are not the tyre.
DEFAULT_NOISE = 0.55

#: Laps per stint. The benchmark's stints were "around 20 laps".
DEFAULT_STINT_LAPS = 20


@dataclass
class PowerCurve:
    effect: float
    noise: float
    stint_laps: int
    n_stints: np.ndarray
    power: np.ndarray
    n_sims: int

    def n_for(self, target: float = 0.80) -> int | None:
        """Smallest number of stints reaching ``target`` power, if any."""
        hit = np.where(self.power >= target)[0]
        return int(self.n_stints[hit[0]]) if len(hit) else None

    def power_at(self, n: int) -> float:
        """Power at a given number of stints, interpolated."""
        return float(np.interp(n, self.n_stints, self.power))

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({"n_driver_stints": self.n_stints, "power": self.power})


def _one_trial(
    rng: np.random.Generator,
    n_stints: int,
    effect: float,
    noise: float,
    stint_laps: int,
) -> bool:
    """Simulate one experiment. Returns True if the difference was detected.

    Half the stints get compound A, half compound B, differing by ``effect``.
    Each stint has its own baseline pace, which the design removes by centring
    within the stint -- exactly what happens to the real data. So the test sees
    only within-stint slope information, as it does in practice.
    """
    per = max(1, n_stints // 2)
    tyre_age = np.arange(1, stint_laps + 1, dtype=float)
    centred_age = tyre_age - tyre_age.mean()

    slopes = []
    for rate in (0.0, effect):
        for _ in range(per):
            y = rate * centred_age + rng.normal(0, noise, stint_laps)
            # OLS slope through the centred design; no intercept needed.
            slopes.append(float(centred_age @ y / (centred_age @ centred_age)))

    a = np.array(slopes[:per])
    b = np.array(slopes[per:])

    # Two stints per group cannot support a variance estimate at all.
    if per < 2:
        return False

    # Welch's t-test: the two groups need not have equal variance.
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(va / per + vb / per)
    if se == 0:
        return False
    t = abs(b.mean() - a.mean()) / se

    # The critical value MUST come from the t distribution with Welch-
    # Satterthwaite degrees of freedom, not from 1.96. With two stints per group
    # there is 1 degree of freedom and the true critical value is 12.7, so the
    # normal approximation reports power that does not exist -- it made the
    # curve non-monotonic, showing more power at 4 stints than at 8.
    denom = va**2 / (per**2 * (per - 1)) + vb**2 / (per**2 * (per - 1))
    df = (va / per + vb / per) ** 2 / denom if denom > 0 else 1.0
    return bool(t > student_t.ppf(0.975, max(df, 1.0)))


def power_curve(
    n_stints_grid=(2, 4, 8, 16, 32, 64, 128, 256, 512),
    effect: float = DEFAULT_EFFECT,
    noise: float = DEFAULT_NOISE,
    stint_laps: int = DEFAULT_STINT_LAPS,
    n_sims: int = 600,
    seed: int = 0,
) -> PowerCurve:
    """Detection probability against number of driver-stints."""
    rng = np.random.default_rng(seed)
    powers = [
        np.mean([_one_trial(rng, n, effect, noise, stint_laps) for _ in range(n_sims)])
        for n in n_stints_grid
    ]
    return PowerCurve(
        effect=effect,
        noise=noise,
        stint_laps=stint_laps,
        n_stints=np.array(n_stints_grid),
        power=np.array(powers),
        n_sims=n_sims,
    )


def estimate_noise(df: pd.DataFrame, col: str = "y") -> float:
    """Residual scatter in a prepared design frame.

    Uses the within-run spread of the already-demeaned response, which is what
    the simulation needs: noise left after the confounders are removed.
    """
    return float(df.groupby("run_id")[col].std().median())


def detectable_effect(
    n_stints: int,
    noise: float = DEFAULT_NOISE,
    stint_laps: int = DEFAULT_STINT_LAPS,
    target: float = 0.80,
    grid=np.linspace(0.001, 0.10, 40),
    n_sims: int = 300,
    seed: int = 1,
) -> float | None:
    """Smallest effect detectable at ``target`` power with ``n_stints``.

    The inverse question, and often the more useful one: given the data we have,
    what size of difference could we have found?
    """
    rng = np.random.default_rng(seed)
    for eff in grid:
        p = np.mean([_one_trial(rng, n_stints, eff, noise, stint_laps) for _ in range(n_sims)])
        if p >= target:
            return float(eff)
    return None
