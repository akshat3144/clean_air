"""Turning clean laps into something a model can identify degradation from.

The whole difficulty of this problem is in this file, so it is worth stating it
plainly.

Inside a single stint, tyre age and fuel burn move together, lap for lap. They
are perfectly collinear. No estimator can pull them apart from one stint, which
is exactly why the benchmark's single-driver fit could not tell a Hard from a
Medium. That is a property of the data, not of their statistics.

We break it differently in races and in practice.

RACES -- the clean case.
    Everything that varies with time in a race is COMMON to every car on that
    lap: fuel load, track evolution, air and track temperature, safety cars,
    the racing line rubbering in. So we subtract the (event, lap) mean from
    every variable and never model any of it. What survives is purely
    cross-sectional: at lap 34 of Hungary, some drivers are on a 22-lap-old
    tyre and others on a 4-lap-old one, and the difference in their lap times
    is the tyre.

    This is what pooling the field actually buys. One car cannot do it at all,
    because there is nobody to compare against at the same instant.

    It also makes the fuel coefficient irrelevant here. Fuel is identical
    across cars on a given lap, so the demeaning removes it whether or not we
    know its value. We cannot get it wrong.

PRACTICE -- the harder case.
    Cars run at different times, so there is no "same lap" to compare across.
    Fuel is unobserved and its coefficient is NOT identifiable from lap times
    (fuel and track evolution are both monotone in session time). So we do not
    pretend to fit it. We correct for fuel using the physical value and then
    run the whole analysis again across the plausible range, so that any
    conclusion which depends on the fuel assumption is visible as such.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..config import MASS_SENSITIVITY_S_PER_KG
from ..data.fuel import practice_fuel_correction_s
from ..data.traffic import add_gap_ahead

log = logging.getLogger(__name__)

#: kg of fuel burned per lap during a practice race simulation. Teams run
#: race-representative loads; the exact figure is private, so this is an
#: estimate and its influence is checked by sensitivity analysis.
PRACTICE_BURN_KG_PER_LAP = 1.7

#: A run whose median lap is at least this far off the session's best is doing
#: race work, not a qualifying simulation.
RACE_SIM_MIN_DELTA_S = 1.5

#: Laps slower than this multiple of the session's best are not representative
#: running and are dropped before runs are detected.
#:
#: This matters more than it sounds. In practice drivers repeatedly do one push
#: lap then a slow cool-down or preparation lap, giving sequences like
#: 84s, 112s, 85s, 121s, 84s. Those are consecutive green accurate laps, so a
#: naive "5 laps in a row" rule calls them a long run, and fitting a slope
#: through them produces nonsense -- it was the cause of practice degradation
#: estimates around 0.5 s/lap, roughly ten times any plausible value.
#:
#: 1.10 rather than FastF1's usual 1.07 because race simulations carry heavy
#: fuel and legitimately run several seconds off the ultimate pace.
PACE_THRESHOLD = 1.10

#: A genuine race simulation is consistent. Alternating push and cool-down laps
#: are not, so a run whose lap times scatter more than this is rejected even if
#: it survives the pace filter.
MAX_RUN_LAP_TIME_SD_S = 2.5


def add_physical_compound(df: pd.DataFrame) -> pd.DataFrame:
    """Map each lap's HARD/MEDIUM/SOFT label to its actual C1-C5 compound.

    The labels are relative to each weekend's nomination, so grouping by them
    pools physically different rubber. C3 is the HARD tyre at Monza, Monaco,
    Melbourne, Hungary and Austria; the MEDIUM at Barcelona, Spa and Madrid; and
    the SOFT at Suzuka. Same rubber, three different names.

    Reads the ALLOCATION STORE rather than the config constant. That matters:
    the store is what the API writes when somebody nominates a new race in the
    app, and a model still reading the constant would simply not see that race
    -- the front end and the fit would disagree, silently, about which tyre a
    lap was run on.

    Laps at events with no known allocation get NaN and should be dropped.
    """
    from ..data.allocation import all_allocations

    table = {e: a.compounds for e, a in all_allocations().items()}
    df = df.copy()
    df["C"] = [
        table.get(e, {}).get(c)
        for e, c in zip(df["event"], df["Compound"], strict=True)
    ]
    return df


def drop_stint_outliers(df: pd.DataFrame, z: float = 2.5) -> pd.DataFrame:
    """Remove laps that are wild relative to their own stint.

    Traffic, lock-ups, mistakes and off-track moments produce lap times that
    say nothing about the tyre. Judged within a driver's own stint so that a
    slow car is not mistaken for a bad lap.
    """
    keys = ["event", "session", "Driver", "Stint"]
    g = df.groupby(keys)["LapTimeSeconds"]
    spread = g.transform("std").replace(0, np.nan)
    score = (df["LapTimeSeconds"] - g.transform("median")).abs() / spread
    return df[score.lt(z) | score.isna()].copy()


def drop_non_representative_laps(df: pd.DataFrame, threshold: float = PACE_THRESHOLD) -> pd.DataFrame:
    """Drop cool-down and preparation laps, judged against the DRIVER's own best.

    Referenced to the driver rather than to the session, because a slower car's
    race simulation can legitimately be more than 10% off the fastest car's lap.
    Using the session best penalises slow teams and threw away a third of the
    usable long runs.

    Must run BEFORE runs are detected: dropping a lap breaks the consecutive-lap
    chain, so runs found earlier would stitch across the gap. See PACE_THRESHOLD.
    """
    best = df.groupby(["event", "session", "Driver"])["LapTimeSeconds"].transform("min")
    return df[df["LapTimeSeconds"] <= best * threshold].copy()


def classify_runs(df: pd.DataFrame, max_sd: float = MAX_RUN_LAP_TIME_SD_S) -> pd.DataFrame:
    """Label each practice run a race simulation or something else.

    Two conditions, and both are needed:

    1. Pace. Race work runs seconds off the ultimate pace; a qualifying
       simulation is within a few tenths.
    2. Consistency. A race simulation holds a steady lap time. Anything that
       scatters wildly is push-and-cool-down running, which the pace filter
       alone does not always catch.

    Adds ``run_pace_delta``, ``run_lap_time_sd`` and ``is_race_sim``.
    """
    df = df.copy()
    best = df.groupby(["event", "session"])["LapTimeSeconds"].transform("min")
    run = df.groupby("run_id")["LapTimeSeconds"]
    df["run_pace_delta"] = run.transform("median") - best
    df["run_lap_time_sd"] = run.transform("std").fillna(0.0)
    df["is_race_sim"] = (df["run_pace_delta"] >= RACE_SIM_MIN_DELTA_S) & (
        df["run_lap_time_sd"] <= max_sd
    )
    return df


def race_design(df: pd.DataFrame, min_cars_per_lap: int = 4, with_traffic: bool = True) -> pd.DataFrame:
    """Within-transform race laps by (event, lap).

    Subtracting the (event, lap) mean is algebraically identical to including a
    fixed effect for every event-lap cell, but far cheaper than 400 dummies.
    Everything shared by the field at that moment disappears; only differences
    between cars remain.

    Cells with too few cars are dropped -- a comparison needs somebody to
    compare against, and a two-car cell gives an unstable mean.

    Adds ``y`` (lap time), ``tl`` (tyre age) and ``tl2`` (tyre age squared),
    each demeaned within its cell.
    """
    df = df[df["session"] == "R"].copy()
    df["tyre_life_sq"] = df["TyreLife"] ** 2

    # Traffic is the one confounder the (event, lap) demeaning does NOT remove,
    # because it differs between cars at the same instant -- which is exactly
    # the variation this design uses. And it is correlated with tyre age through
    # pit stops: fresh tyres rejoin into the pack, old tyres are usually in clear
    # air. Measured: mean tyre age is 12.2 laps in dirty air against 16.0 in
    # clear, correlation -0.19. Leaving it out biases degradation toward zero.
    if with_traffic:
        if "LapStartTime" in df.columns:
            df = add_gap_ahead(df)
        else:
            # Degrade loudly rather than silently dropping a confounder.
            log.warning(
                "LapStartTime absent; fitting WITHOUT the traffic covariate. "
                "Degradation will be biased toward zero -- fresh tyres run in "
                "more traffic, so their laps look slow."
            )

    cell = df.groupby(["event", "LapNumber"])
    df["cars_on_lap"] = cell["LapTimeSeconds"].transform("size")
    df = df[df["cars_on_lap"] >= min_cars_per_lap].copy()

    cell = df.groupby(["event", "LapNumber"])
    df["y"] = df["LapTimeSeconds"] - cell["LapTimeSeconds"].transform("mean")
    df["tl"] = df["TyreLife"] - cell["TyreLife"].transform("mean")
    df["tl2"] = df["tyre_life_sq"] - cell["tyre_life_sq"].transform("mean")
    if with_traffic and "traffic" in df.columns:
        df["tr"] = df["traffic"] - cell["traffic"].transform("mean")
    return df


def practice_design(
    df: pd.DataFrame,
    s_per_kg: float = MASS_SENSITIVITY_S_PER_KG,
    burn_kg_per_lap: float = PRACTICE_BURN_KG_PER_LAP,
) -> pd.DataFrame:
    """Fuel-correct practice laps and centre them within their run.

    Fuel is unobserved in practice and its coefficient cannot be identified
    from lap times, because fuel load and track evolution both fall monotonically
    through a session. Rather than pretend to estimate it, we subtract the
    physical effect and expose the assumption:

        y = lap time + (fuel burned so far) x (seconds per kg)

    The sign is a plus because burning fuel makes the car FASTER. Adding the
    effect back removes that improvement, leaving the tyre's contribution.

    Centring within the run then removes the run's own baseline -- car, driver,
    track, session conditions and starting fuel load, all constant within a run.

    Run this across the plausible range of ``s_per_kg`` (0.030-0.035) and check
    that the conclusions do not move. If they do, say so.
    """
    df = df[df["session"] != "R"].copy()

    correction = practice_fuel_correction_s(df["run_lap"], burn_kg_per_lap, s_per_kg)
    df["fuel_burned_kg"] = (df["run_lap"] - 1) * burn_kg_per_lap
    df["y_fuel_corrected"] = df["LapTimeSeconds"] + correction

    df["tyre_life_sq"] = df["TyreLife"] ** 2
    run = df.groupby("run_id")
    df["y"] = df["y_fuel_corrected"] - run["y_fuel_corrected"].transform("mean")
    df["tl"] = df["TyreLife"] - run["TyreLife"].transform("mean")
    df["tl2"] = df["tyre_life_sq"] - run["tyre_life_sq"].transform("mean")
    return df


def prepare(
    laps: pd.DataFrame,
    context: str,
    *,
    race_sims_only: bool = True,
    min_runs_per_compound: int = 5,
    **kw,
) -> pd.DataFrame:
    """Full path from clean laps to a fittable frame.

    Args:
        laps: output of ``data.laps.tag_long_runs``.
        context: "race" or "practice".
        race_sims_only: in practice, drop qualifying simulations.
        min_runs_per_compound: drop compounds with too little support to
            estimate. C1 appears at one event only, so its estimate would be
            indistinguishable from that event's effect.
    """
    if context not in ("race", "practice"):
        raise ValueError(f"context must be 'race' or 'practice', got {context!r}")

    from ..data.laps import tag_long_runs

    df = add_physical_compound(laps)
    df = df[df["C"].notna()]
    df = df.dropna(subset=["TyreLife", "LapTimeSeconds"])

    if context == "race":
        df = drop_stint_outliers(df[df["is_long_run"]])
        df = race_design(df, **kw)
    else:
        # Order matters. Drop cool-down laps first, THEN re-detect runs: a
        # dropped lap breaks the chain, so runs found before filtering would
        # still span the gap and stitch push laps together across it.
        df = drop_non_representative_laps(df[df["session"] != "R"])
        df = tag_long_runs(df)
        df = df[df["is_long_run"]]
        df = drop_stint_outliers(df)
        df = classify_runs(df)
        if race_sims_only:
            df = df[df["is_race_sim"]]
        df = practice_design(df, **kw)

    runs = df.groupby("C")["run_id"].transform("nunique")
    return df[runs >= min_runs_per_compound].copy()
