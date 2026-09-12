"""Is the uncertainty honest?

A model that says "80% confident" should be right 80% of the time. If it is
right 95% of the time the intervals are too wide and the model is useless for
decisions; if 50%, it is overconfident and will get someone's race wrong.

Neither the benchmark paper nor any public FastF1 tyre analysis we have seen
reports this. It is cheap to compute and it is the difference between a number
and a number you can act on.

Validation is leave-one-run-out: fit without a run, predict its laps, and check
whether the actual lap time falls inside the stated interval. Holding out a whole
run rather than scattered laps matters -- laps within a run are correlated, so
holding out single laps would let the model see almost the same information and
report coverage that flatters itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

#: Nominal levels to check. 80 is the headline because it is the level a
#: strategist would actually use -- 95% intervals on lap time are too wide to
#: separate strategies.
DEFAULT_LEVELS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99)


@dataclass
class Calibration:
    levels: np.ndarray
    empirical: np.ndarray
    n: int
    n_runs: int

    @property
    def coverage_80(self) -> float:
        return float(np.interp(0.80, self.levels, self.empirical))

    def miscalibration(self) -> float:
        """Mean absolute gap between nominal and empirical. Zero is perfect."""
        return float(np.mean(np.abs(self.levels - self.empirical)))

    def verdict(self) -> str:
        gap = self.coverage_80 - 0.80
        if abs(gap) <= 0.05:
            return "well calibrated"
        return "overconfident" if gap < 0 else "conservative"

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"nominal": self.levels, "empirical": self.empirical, "n": self.n}
        )


def leave_one_run_out(
    df: pd.DataFrame,
    levels=DEFAULT_LEVELS,
    max_runs: int | None = None,
    seed: int = 0,
) -> Calibration:
    """Coverage of prediction intervals, one run held out at a time.

    The model here is deliberately the same shape as the fitted one: a
    per-compound slope through the centred design. Refitting the full
    mixed-effects model for every run would take hours and change nothing about
    the coverage question, since the slope is what carries the prediction.

    Args:
        df: a prepared design frame with ``y``, ``tl``, ``C`` and ``run_id``.
        levels: nominal interval levels to check.
        max_runs: cap the number of folds, for speed.
    """
    levels = np.asarray(levels, dtype=float)
    runs = df["run_id"].unique()
    if max_runs is not None and len(runs) > max_runs:
        runs = np.random.default_rng(seed).choice(runs, max_runs, replace=False)

    hits = np.zeros(len(levels))
    total = 0

    for run in runs:
        train = df[df["run_id"] != run]
        test = df[df["run_id"] == run]
        compound = test["C"].iloc[0]

        fit_on = train[train["C"] == compound]
        if len(fit_on) < 30:
            continue

        # Slope through the origin on the centred design.
        x, y = fit_on["tl"].to_numpy(), fit_on["y"].to_numpy()
        denom = float(x @ x)
        if denom == 0:
            continue
        slope = float(x @ y / denom)

        # Predictive spread: residual scatter plus slope uncertainty carried
        # out to the tyre age being predicted. Ignoring the second term is the
        # usual way a model ends up overconfident far from its data.
        resid = y - slope * x
        sigma = float(resid.std(ddof=1))
        se_slope = sigma / np.sqrt(denom)

        xt, yt = test["tl"].to_numpy(), test["y"].to_numpy()
        pred = slope * xt
        spread = np.sqrt(sigma**2 + (se_slope * xt) ** 2)

        z = norm.ppf(0.5 + levels / 2)
        inside = np.abs(yt - pred)[:, None] <= (z[None, :] * spread[:, None])
        hits += inside.sum(axis=0)
        total += len(yt)

    if total == 0:
        raise ValueError("no runs had enough training data to validate")

    return Calibration(
        levels=levels,
        empirical=hits / total,
        n=total,
        n_runs=len(runs),
    )
