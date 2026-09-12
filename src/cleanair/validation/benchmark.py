"""Scoring our model against the published benchmark, like for like.

The comparison has to be fair in both directions, and that takes some care.

SAME TEST LAPS
    Their cross-validation is rolling-origin recalibration on Hamilton's 2025
    Austrian GP, transcribed from their ``CV_Functions.R``: per stint, hold out
    the last ``round(stint_length/4)`` laps, predict one lap ahead, and expand
    the training window a lap at a time to the end of the stint. Training always
    starts at lap 1. That gives 16 predictions across his three stints, and we
    predict exactly those laps.

    This docstring used to say 35, because ``_folds`` was handed each stint's
    last global lap number where its length belongs. See ``_folds`` for what
    that cost.

SAME METRIC
    CRPS from ``scoringrules``, verified against R's ``scoringRules`` to 2.5e-11
    by ``test_our_crps_matches_r_scoring_rules``.
    Their per-stint totals are averaged, not summed (their RMSE total IS summed
    -- see validation/scoring).

NO PEEKING
    Their model sees Hamilton's laps 1..k. Ours sees the FIELD's laps 1..k. That
    is the whole point of pooling, and it is legitimate -- a pit wall sees every
    car's lap time. But it means we must NOT use anyone's lap k+1, including the
    field mean, or we would be forecasting with information their model could not
    have had. So the field's mean pace and mean tyre age at lap k+1 are
    extrapolated from laps up to k.

WHAT WE ARE NOT CLAIMING
    Our design needs several cars at the same lap, so it cannot be run on a
    single driver at all. This is not "the same model on the same data"; it is
    "a different model, scored on the same predictions". Said plainly, that is
    the honest framing and it is still the comparison that matters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scoring import crps_normal, crps_student_t, rmse_seconds, rolling_origin_folds
from .transfer import MIN_AGE_SPREAD_LAPS

#: Laps of recent history used to extrapolate the field's mean pace. Long enough
#: to be stable, short enough to track a safety car or a rain shower.
TREND_WINDOW = 8

#: Fraction of each stint used for training before the first prediction.
TRAIN_FRACTION = 0.75

#: Minimum mean tyre-age spread, in laps, among cars sharing a lap before an
#: in-race degradation rate is believed. Same value and same reasoning as
#: ``transfer.MIN_AGE_SPREAD_LAPS``; imported rather than redefined so the two
#: cannot drift apart. Sweeping it over 0-3 laps, the season score improves
#: sharply to 2 and is flat after, so this sits on the plateau rather than at a
#: point picked for its score.


@dataclass
class BenchmarkResult:
    per_stint_crps: list[float]
    per_stint_rmse: list[float]
    n_predictions: int
    driver: str
    event: str

    @property
    def crps(self) -> float:
        """Their Table 2 total: the MEAN across stints."""
        return float(np.mean(self.per_stint_crps))

    @property
    def rmse_total(self) -> float:
        """Their Table 1 total: the SUM across stints."""
        return float(np.sum(self.per_stint_rmse))


def _folds(subject: pd.DataFrame) -> list[tuple[int, int]]:
    """Their scheme: (train_up_to, test_lap) pairs, in global lap numbers.

    For each stint, train on its first 75% of laps and predict each remaining
    lap one step ahead, expanding the training window by a lap each time.

    ``rolling_origin_folds`` indexes WITHIN a stint, so it must be given the
    stint's own lap count and its output mapped back onto that stint's global
    lap numbers. Passing it a global lap number instead -- which this function
    used to do -- silently made the training fraction relative to the race
    rather than the stint, so late stints were tested on most of their laps and
    early ones on a handful. It produced 35 test laps at Austria where the
    scheme calls for 15.

    Laps inside a stint are not always contiguous, since pit and non-green laps
    are already filtered out, so positions come from the observed laps rather
    than from arithmetic on the first and last.
    """
    folds = []
    for _, g in subject.groupby("Stint", sort=True):
        laps = sorted(int(x) for x in g["LapNumber"])
        for i, _ in rolling_origin_folds(len(laps), TRAIN_FRACTION):
            test_lap = laps[i]
            folds.append((test_lap - 1, test_lap))
    return folds


def _extrapolate(series: pd.Series, target_lap: int, window: int = TREND_WINDOW) -> float:
    """Straight-line forecast of one more step from recent history.

    Used for the field's mean pace and mean tyre age. Deliberately simple: a
    cleverer forecaster here would be doing the benchmark's job for it, and the
    thing under test is the tyre model, not the pace model.
    """
    recent = series.dropna().tail(window)
    if len(recent) < 2:
        return float(recent.mean()) if len(recent) else np.nan
    laps = recent.index.to_numpy(dtype=float)
    vals = recent.to_numpy(dtype=float)
    slope, intercept = np.polyfit(laps, vals, 1)
    return float(slope * target_lap + intercept)


def score(
    laps: pd.DataFrame,
    driver: str = "HAM",
    event: str = "Austrian Grand Prix",
    compound_rates: dict[str, float] | None = None,
    mode: str = "hybrid",
    heavy_tails: bool = False,
) -> BenchmarkResult:
    """Score our pooled model on the benchmark's exact predictions.

    Args:
        laps: race laps for the whole field, with LapTimeSeconds, TyreLife,
            Compound, Stint, Driver, LapNumber.
        driver: whose laps are predicted. The benchmark used Hamilton.
        compound_rates: fixed degradation rates keyed by the timing feed's
            compound label. If None, they are refitted inside every fold from
            the field's laps up to that point, which is the honest version.
        heavy_tails: score against a Student-t predictive distribution rather
            than a normal one. Their best model gained from heavy-tailed errors,
            so this was worth trying. Across the 2025 season it wins 11 races of
            16 but moves the mean only from 0.6058 to 0.5982 -- consistent, and
            far too small to matter. The default stays normal: switching to
            whichever scored better would be tuning, and a 0.008 gain does not
            pay for the extra assumption. Kept so the negative result can be
            reproduced rather than taken on trust.
        mode: "hybrid" tracks the driver's own pace level and projects it at the
            field-fitted degradation rate. "field" extrapolates the field mean
            instead -- kept so the two can be compared, since the difference
            shows whether a poor score is the tyre model or the pace forecaster.

    Returns:
        Per-stint CRPS and RMSE, aggregated the way their tables do it.
    """
    df = laps.copy()
    df = df[df["LapTimeSeconds"].notna()]

    subject = df[df["Driver"] == driver].sort_values("LapNumber")
    if subject.empty:
        raise ValueError(f"no laps for {driver!r}")

    folds = _folds(subject)

    # Field aggregates per lap, indexed by lap number so they can be extrapolated.
    field_pace = df.groupby("LapNumber")["LapTimeSeconds"].mean()
    field_age = df.groupby("LapNumber")["TyreLife"].mean()

    stint_of = dict(zip(subject["LapNumber"], subject["Stint"], strict=True))
    results: dict[float, list[tuple[float, float, float]]] = {}

    for train_to, test_lap in folds:
        actual_row = subject[subject["LapNumber"] == test_lap]
        if actual_row.empty:
            continue
        actual = float(actual_row["LapTimeSeconds"].iloc[0])
        age = float(actual_row["TyreLife"].iloc[0])
        compound = str(actual_row["Compound"].iloc[0])

        # Everything below uses laps <= train_to only.
        hist = df[df["LapNumber"] <= train_to]
        if len(hist) < 40:
            continue

        rate = (
            compound_rates.get(compound)
            if compound_rates
            else _fit_rate(hist, compound)
        )
        if rate is None or not np.isfinite(rate):
            continue

        pace_hat = _extrapolate(field_pace.loc[:train_to], test_lap)
        age_hat = _extrapolate(field_age.loc[:train_to], test_lap)
        if not np.isfinite(pace_hat) or not np.isfinite(age_hat):
            continue

        if mode == "field":
            # Field pace plus the tyre-age difference between this driver and the
            # field, priced at the fitted rate. Simple, and it turned out to be
            # the weak link: extrapolating the field mean is a crude forecaster.
            pred = pace_hat + rate * (age - age_hat)
        else:
            # HYBRID. Their model's strength is a latent state tracking THIS
            # driver's pace; ours is a degradation rate estimated from the whole
            # field instead of from twenty laps. Combine them: strip the tyre
            # effect out of his recent laps to get a clean pace level, then
            # project that level forward at the field-fitted rate.
            own = subject[
                (subject["LapNumber"] <= train_to)
                & (subject["LapNumber"] > train_to - TREND_WINDOW)
            ]
            if len(own) < 3:
                continue
            level = float(np.mean(own["LapTimeSeconds"] - rate * own["TyreLife"]))
            # Carry the field's pace trend so fuel burn and track evolution,
            # which the level cannot see going forward, are still accounted for.
            drift = pace_hat - _extrapolate(field_pace.loc[:train_to], train_to)
            pred = level + rate * age + drift

        # Predictive spread: how far this driver's laps have sat from the same
        # construction over the training window. Empirical, not assumed.
        resid = _training_residuals(df, subject, driver, train_to, rate, field_pace, field_age)
        sigma = float(np.std(resid, ddof=1)) if len(resid) > 2 else 0.5
        sigma = max(sigma, 0.05)

        results.setdefault(stint_of[test_lap], []).append((actual, pred, sigma))

    per_crps, per_rmse = [], []
    n = 0
    for _, rows in sorted(results.items()):
        a = np.array([r[0] for r in rows])
        p = np.array([r[1] for r in rows])
        s = np.array([r[2] for r in rows])
        scorer = crps_student_t if heavy_tails else crps_normal
        per_crps.append(float(scorer(a, p, s).mean()))
        per_rmse.append(rmse_seconds(a, p))
        n += len(rows)

    if not per_crps:
        raise ValueError("no fold produced a prediction")

    return BenchmarkResult(per_crps, per_rmse, n, driver, event)


def _fit_rate(hist: pd.DataFrame, compound: str) -> float | None:
    """Degradation for one compound from the field's history, within-transformed.

    Same estimator as the production model: demean by (lap) so everything the
    field shares at that moment drops out, then regress on tyre age.

    IDENTIFIABILITY. The within-lap comparison only has something to compare
    when cars sharing a lap are on DIFFERENT tyre ages. Early in a race they are
    not -- everyone started together on a fresh set -- so the age spread is
    almost nothing and the slope is being read off numerical noise. A
    ``denom > 0`` check does not catch this: the denominator is small but not
    zero, which is precisely the case that explodes.

    It did explode. At Saudi 2025 this returned about 1.0 s/lap, twenty times
    any real tyre, and the predictor duly forecast Hamilton's laps 4.7 seconds
    slow for a whole stint. Requiring a real age spread first -- the same
    ``MIN_AGE_SPREAD_LAPS`` discipline used in ``transfer.py``, and the same one
    the power analysis argues for -- cut the season's mean CRPS from 0.82 to
    0.60.

    When the spread is too small we return 0.0 rather than ``None``. Returning
    ``None`` skips the fold, which would quietly drop the laps we predict worst
    and flatter the score; 0.0 says "no evidence of degradation yet", leaves the
    prediction at the driver's current pace level, and keeps the lap in the test
    set where it belongs.
    """
    h = hist[hist["Compound"] == compound]
    if len(h) < 25:
        return None
    cell = h.groupby("LapNumber")
    n_per = cell["LapTimeSeconds"].transform("size")
    h = h[n_per >= 2]
    if len(h) < 20:
        return None

    per_lap = h.groupby("LapNumber")["TyreLife"].agg(["size", "std"])
    shared = per_lap[per_lap["size"] >= 2]
    spread = float(shared["std"].mean()) if len(shared) else 0.0
    if not np.isfinite(spread) or spread < MIN_AGE_SPREAD_LAPS:
        return 0.0

    cell = h.groupby("LapNumber")
    y = (h["LapTimeSeconds"] - cell["LapTimeSeconds"].transform("mean")).to_numpy()
    x = (h["TyreLife"] - cell["TyreLife"].transform("mean")).to_numpy()
    denom = float(x @ x)
    return float(x @ y / denom) if denom > 1e-9 else 0.0


def _training_residuals(
    df: pd.DataFrame,
    subject: pd.DataFrame,
    driver: str,
    train_to: int,
    rate: float,
    field_pace: pd.Series,
    field_age: pd.Series,
) -> np.ndarray:
    """How well this construction fitted the driver's recent laps."""
    recent = subject[
        (subject["LapNumber"] <= train_to) & (subject["LapNumber"] > train_to - 15)
    ]
    out = []
    for _, r in recent.iterrows():
        lap = r["LapNumber"]
        if lap not in field_pace.index or lap not in field_age.index:
            continue
        pred = field_pace.loc[lap] + rate * (r["TyreLife"] - field_age.loc[lap])
        out.append(r["LapTimeSeconds"] - pred)
    return np.array(out)
