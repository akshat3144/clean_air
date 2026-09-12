"""Practice to race: predict Sunday's tyre behaviour from Friday's.

This is the deliverable the brief actually names -- "post-race validation tools
to compare predicted wear against actual race-day pace" -- and the benchmark
paper does not attempt it. Their model fits within a single race, so it never
has to generalise from one session to another.

Two predictions are compared, and the gap between them is the point.

NAIVE
    Assume Sunday degrades like Friday. This is what you get if you take a
    practice degradation curve at face value, and it is what every public
    FastF1 tyre analysis implicitly does.

CALIBRATED
    Learn the practice-to-race relationship from OTHER events and apply it.
    We already know from the pooled fits that the two differ systematically:
    race degradation is lower, and the gap widens for softer compounds. That is
    consistent with drivers managing fragile tyres rather than pushing them.
    If the effect is real and stable, correcting for it should beat the naive
    prediction out of sample.

Validation is leave-one-event-out. The calibration never sees the event it is
asked to predict, so a better score cannot come from fitting the answer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Minimum runs in an (event, compound) cell before we will estimate a rate.
#: Practice is thin -- some cells have two runs -- and a slope from two runs is
#: not worth predicting from.
MIN_RUNS = 3

#: Minimum tyre-age spread, in laps, among cars on the same compound at the same
#: lap of the same race.
#:
#: This is an identifiability requirement, not a quality preference. The race
#: design identifies degradation by comparing cars at the same instant, so it
#: needs them to be on DIFFERENT tyre ages. When a field runs a synchronised
#: strategy that variation disappears: at the 2026 Belgian GP every car on C3
#: was the same age on any given lap, spread exactly 0.00, and the fitted slope
#: was meaningless. Cells below this threshold produced race rates of -0.21 and
#: -0.41 s/lap -- tyres apparently getting faster as they wore out.
#:
#: Refusing to report those is the same discipline as the power analysis: do not
#: publish an estimate the design cannot support.
MIN_AGE_SPREAD_LAPS = 2.0


@dataclass
class TransferResult:
    table: pd.DataFrame
    mae_naive: float
    mae_calibrated: float
    factor: float
    n_events: int

    @property
    def improvement(self) -> float:
        """Fraction of the naive error removed by calibrating. Negative is worse."""
        if self.mae_naive == 0:
            return 0.0
        return (self.mae_naive - self.mae_calibrated) / self.mae_naive


def age_spread(g: pd.DataFrame) -> float:
    """Mean tyre-age spread among cars sharing a lap. The identifying variation.

    Zero means every car on this compound was the same age whenever they were
    on track together, and no slope can be recovered. See MIN_AGE_SPREAD_LAPS.
    """
    per_lap = g.groupby("LapNumber")["TyreLife"].agg(["size", "std"])
    multi = per_lap[per_lap["size"] >= 2]
    return float(multi["std"].mean()) if len(multi) else 0.0


def cell_rates(
    df: pd.DataFrame,
    min_runs: int = MIN_RUNS,
    min_age_spread: float | None = None,
) -> pd.DataFrame:
    """Degradation rate per (event, compound) from a prepared design frame.

    Ordinary least squares through the already-centred design rather than the
    mixed-effects model: a cell can hold as few as three runs, which will not
    support a random-effects variance. The slope is what transfers, and it is
    estimated the same way on both sides so the comparison stays fair.

    Args:
        min_age_spread: for race cells, the minimum tyre-age spread required
            before a rate is reported. Pass ``MIN_AGE_SPREAD_LAPS`` for race
            data; leave as None for practice, where the design identifies
            degradation within a run rather than across cars.

    Returns columns: event, C, rate, se, n_runs, n_laps, age_spread.
    """
    rows = []
    for (event, compound), g in df.groupby(["event", "C"], observed=True):
        n_runs = g["run_id"].nunique()
        if n_runs < min_runs:
            continue

        spread = age_spread(g)
        if min_age_spread is not None and spread < min_age_spread:
            continue

        y = g["y"].to_numpy()

        # Partial out traffic where it is available. Dirty air is correlated
        # with tyre age through pit stops -- fresh tyres rejoin into the pack --
        # so leaving it in the residual biases the slope. Least squares on
        # [tyre age, traffic] rather than tyre age alone.
        cols = ["tl"] + (["tr"] if "tr" in g.columns else [])
        X = g[cols].to_numpy(dtype=float)
        if not np.isfinite(X).all() or float(X[:, 0] @ X[:, 0]) <= 0:
            continue
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        slope = float(beta[0])

        resid = y - X @ beta

        # Standard error CLUSTERED BY RUN, not by lap.
        #
        # Laps inside a run are strongly correlated -- a driver managing a tyre
        # is slow on all of them, not independently on each -- and races average
        # 14 laps per run. Treating each lap as independent counts the same
        # information many times over and makes the interval far too narrow.
        #
        # Measured on the fleet transfer, which has the identical structure:
        # with ordinary errors, 95% intervals covered the truth 37% of the time
        # across 30 simulated fleets. Clustering brought that to 97%.
        try:
            bread = np.linalg.pinv(X.T @ X)
            clusters = g["run_id"].to_numpy()
            meat = np.zeros((X.shape[1], X.shape[1]))
            for c in np.unique(clusters):
                m = clusters == c
                sc = X[m].T @ resid[m]
                meat += np.outer(sc, sc)
            n_c = len(np.unique(clusters))
            corr = n_c / max(1, n_c - 1)
            se = float(np.sqrt(corr * (bread @ meat @ bread)[0, 0])) if n_c > 1 else np.nan
        except np.linalg.LinAlgError:
            se = np.nan
        rows.append(
            {
                "event": event,
                "C": compound,
                "rate": slope,
                "se": se,
                "n_runs": n_runs,
                "n_laps": len(g),
                "age_spread": spread,
            }
        )
    return pd.DataFrame(rows)


def leave_one_event_out(
    practice: pd.DataFrame,
    race: pd.DataFrame,
    min_runs: int = MIN_RUNS,
) -> TransferResult:
    """Predict each event's race degradation from its practice, honestly.

    For every event in turn:
      - the naive prediction is that event's practice rate, unchanged
      - the calibrated prediction multiplies it by a factor learned from the
        SIX OTHER events, so the held-out event never informs its own correction

    Args:
        practice: prepared practice design frame.
        race: prepared race design frame.

    Returns:
        A ``TransferResult`` with a per-cell table and both mean absolute errors.
    """
    # Practice identifies degradation within a run, so it needs no cross-car
    # age spread. Race identifies it across cars at the same lap, so it does.
    p = cell_rates(practice, min_runs).rename(columns={"rate": "practice_rate"})
    r = cell_rates(race, min_runs, min_age_spread=MIN_AGE_SPREAD_LAPS).rename(
        columns={"rate": "race_rate"}
    )
    joined = p.merge(r, on=["event", "C"], suffixes=("_p", "_r"))

    if joined.empty:
        raise ValueError("no (event, compound) cell has both practice and race data")

    # A factor, not a difference: management appears to suppress degradation
    # proportionally, and a ratio keeps the prediction positive.
    usable = joined[joined["practice_rate"].abs() > 1e-6]

    rows = []
    for event in joined["event"].unique():
        others = usable[usable["event"] != event]
        factor = (
            float(np.median(others["race_rate"] / others["practice_rate"]))
            if len(others) >= 2
            else 1.0
        )
        for _, cell in joined[joined["event"] == event].iterrows():
            naive = cell["practice_rate"]
            calibrated = naive * factor
            rows.append(
                {
                    "event": event,
                    "C": cell["C"],
                    "practice_rate": naive,
                    "race_rate": cell["race_rate"],
                    "naive_pred": naive,
                    "calibrated_pred": calibrated,
                    "naive_err": abs(naive - cell["race_rate"]),
                    "calibrated_err": abs(calibrated - cell["race_rate"]),
                    "factor_used": factor,
                    "n_runs_practice": int(cell["n_runs_p"]),
                    "n_runs_race": int(cell["n_runs_r"]),
                    "se_practice": cell["se_p"],
                }
            )

    table = pd.DataFrame(rows)
    return TransferResult(
        table=table,
        mae_naive=float(table["naive_err"].mean()),
        mae_calibrated=float(table["calibrated_err"].mean()),
        factor=float(np.median(usable["race_rate"] / usable["practice_rate"])),
        n_events=table["event"].nunique(),
    )


def forecast(
    practice: pd.DataFrame,
    factor: float,
    event: str,
    min_runs: int = MIN_RUNS,
) -> pd.DataFrame:
    """Predict a race that has not happened yet.

    Used for the live Challenge Day demo: feed in that morning's practice, apply
    the factor learned from completed events, and produce race predictions with
    no actuals to compare against. ``TransferArtifact.is_forecast`` marks these
    so the app never presents a forecast as a validated result.
    """
    p = cell_rates(practice[practice["event"] == event], min_runs)
    if p.empty:
        raise ValueError(f"no usable practice cells for {event!r}")
    p["predicted_race_rate"] = p["rate"] * factor
    # Practice is thin, so carry its uncertainty through rather than hiding it.
    p["lo"] = (p["rate"] - 1.96 * p["se"]) * factor
    p["hi"] = (p["rate"] + 1.96 * p["se"]) * factor
    return p
