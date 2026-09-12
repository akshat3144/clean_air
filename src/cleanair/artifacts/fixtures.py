"""Fake artifacts in the real shape, so the web app can be built now.

Numbers are invented but plausible, and shaped by what Step 1 actually found:
practice and race disagree, the physical ordering shows up in practice, and our
intervals are far tighter than the benchmark's.

Every fixture sets ``meta.is_real = False``. The app shows a warning banner on
that flag, so fake numbers can never be demoed by accident.
"""

from __future__ import annotations

import random

from ..config import BENCHMARK_CRPS, BENCHMARK_RMSPE, CONVENTIONAL_2026, SEASON
from .schema import (
    AblationArtifact,
    AblationRow,
    BenchmarkArtifact,
    BenchmarkScore,
    CalibrationArtifact,
    CalibrationPoint,
    CompoundCurve,
    CurvePoint,
    DegradationArtifact,
    Interval,
    Meta,
    PowerArtifact,
    PowerPoint,
    RaceScore,
    StrategyArtifact,
    StrategyPlan,
    TransferArtifact,
    TransferRow,
)

RNG = random.Random(20260913)

#: Roughly what practice showed in Step 1: softer degrades faster.
PRACTICE_RATE = {"C1": 0.024, "C2": 0.031, "C3": 0.038, "C4": 0.052, "C5": 0.061}
#: Roughly what race showed: the ordering collapses under tyre management.
RACE_RATE = {"C1": 0.022, "C2": 0.062, "C3": 0.054, "C4": 0.024, "C5": 0.004}

LABEL_OF = {"C2": "HARD", "C3": "MEDIUM", "C4": "SOFT"}


def _iv(mean: float, halfwidth: float) -> Interval:
    return Interval(mean=round(mean, 4), lo=round(mean - halfwidth, 4), hi=round(mean + halfwidth, 4))


def _curve(rate: float, n: int = 26) -> list[CurvePoint]:
    """Degradation is concave here, not a cliff.

    Step 1 found slopes get steeper when restricted to young tyres, so the first
    laps lose most of the time and it flattens after. Shaped that way on purpose
    so the front end is not built against a curve of the wrong sign.
    """
    pts = []
    for life in range(1, n + 1):
        delta = rate * (life ** 0.85)
        pts.append(CurvePoint(tyre_life=life, delta=_iv(delta, 0.004 + 0.0012 * life)))
    return pts


def degradation(context: str = "practice", event: str | None = None) -> DegradationArtifact:
    rates = PRACTICE_RATE if context == "practice" else RACE_RATE
    events = [event] if event else list(CONVENTIONAL_2026)

    curves = []
    for c in ("C2", "C3", "C4"):
        r = rates[c]
        curves.append(
            CompoundCurve(
                compound=c,
                label=LABEL_OF[c],
                context=context,
                rate=_iv(r, 0.0045),
                curve=_curve(r),
                n_laps=RNG.randint(700, 1800),
                n_runs=RNG.randint(60, 170),
                events=events,
            )
        )

    sep, pairs = {}, []
    for a, b in (("C2", "C3"), ("C3", "C4")):
        ia = next(x.rate for x in curves if x.compound == a)
        ib = next(x.rate for x in curves if x.compound == b)
        # a probability, so it has to stay inside [0, 1]
        sep[f"{a}>{b}"] = round(min(0.999, max(0.001, 0.5 + (ib.mean - ia.mean) * 40)), 3)
        if not ia.overlaps(ib):
            pairs.append(f"{a}|{b}")

    return DegradationArtifact(
        event=event,
        curves=curves,
        fuel_coefficient=_iv(0.0331, 0.0021),
        track_evolution=_iv(-0.0089, 0.0014),
        separation=sep,
        separated_pairs=pairs,
    )


def ablation(context: str = "practice") -> AblationArtifact:
    rates = PRACTICE_RATE if context == "practice" else RACE_RATE
    rows = [
        AblationRow(
            compound=c,
            label=LABEL_OF[c],
            # The naive fit blends fuel burn and track evolution into the slope,
            # so it lands low and with a much wider band.
            naive=_iv(rates[c] * 0.55 + 0.012, 0.031),
            deconfounded=_iv(rates[c], 0.0045),
            published=_iv(0.054, 0.0645) if c == "C2" else None,
        )
        for c in ("C2", "C3", "C4")
    ]
    return AblationArtifact(
        context=context,
        rows=rows,
        caption=(
            "The naive slope blends tyre wear with fuel burn and track evolution. "
            "Removing them separates the compounds and shrinks the interval about sevenfold."
        ),
    )


def benchmark() -> BenchmarkArtifact:
    austria = [
        BenchmarkScore("ARIMA(2,1,2)", BENCHMARK_RMSPE["arima"], BENCHMARK_CRPS["arima"], "published"),
        BenchmarkScore("SSM base", BENCHMARK_RMSPE["base"], BENCHMARK_CRPS["base"], "published"),
        BenchmarkScore("SSM compound-specific", BENCHMARK_RMSPE["ext1"], BENCHMARK_CRPS["ext1"], "published"),
        BenchmarkScore("SSM skew-t (their best)", BENCHMARK_RMSPE["skew_t"], BENCHMARK_CRPS["skew_t"], "published"),
        BenchmarkScore("SSM compound-specific", 1.191, 0.238, "reproduced"),
        BenchmarkScore("Clean Air pooled", 0.974, 0.181, "ours"),
    ]
    races = [
        "Chinese", "Japanese", "Bahrain", "Saudi Arabian", "Emilia Romagna", "Monaco",
        "Spanish", "Canadian", "Austrian", "Hungarian", "Italian", "Azerbaijan",
        "Singapore", "United States", "Mexico City", "Sao Paulo", "Las Vegas",
        "Qatar", "Abu Dhabi",
    ]
    season, wins = [], 0
    for r in races:
        theirs = round(RNG.uniform(0.13, 0.58), 4)
        ours = round(theirs * RNG.uniform(0.72, 1.08), 4)
        win = ours < theirs
        wins += win
        season.append(RaceScore(race=f"{r} Grand Prix", ours_crps=ours, theirs_crps=theirs, ours_wins=win))

    return BenchmarkArtifact(austria_2025=austria, season_2025=season, n_wins=wins, n_races=len(races))


def calibration() -> CalibrationArtifact:
    pts = [
        CalibrationPoint(nominal=n / 100, empirical=round(min(0.999, n / 100 + RNG.uniform(-0.04, 0.03)), 3), n=1400)
        for n in (50, 60, 70, 80, 90, 95, 99)
    ]
    return CalibrationArtifact(points=pts, coverage_80=0.787)


def power() -> PowerArtifact:
    pts, n = [], 4
    while n <= 512:
        pts.append(PowerPoint(n_driver_stints=n, power=round(min(0.999, 1 - 2.718 ** (-n / 60)), 3)))
        n *= 2
    return PowerArtifact(effect_size=0.006, points=pts, n_for_80pct=97, benchmark_n=3, ours_n=417)


def transfer(forecast: bool = False) -> TransferArtifact:
    rows, errs = [], []
    for ev in CONVENTIONAL_2026:
        for c in ("C2", "C3", "C4"):
            pred = PRACTICE_RATE[c] + RNG.uniform(-0.004, 0.004)
            if forecast:
                rows.append(TransferRow(ev, c, LABEL_OF[c], _iv(pred, 0.006), None, None))
            else:
                actual = round(pred + RNG.uniform(-0.008, 0.008), 4)
                err = round(abs(pred - actual), 4)
                errs.append(err)
                rows.append(TransferRow(ev, c, LABEL_OF[c], _iv(pred, 0.006), actual, err))
    mae = round(sum(errs) / len(errs), 4) if errs else None
    return TransferArtifact(rows=rows, mae=mae, is_forecast=forecast)


def strategy(event: str = "Hungarian Grand Prix") -> StrategyArtifact:
    plans = [
        StrategyPlan(1, ["C3", "C2"], [24, 46], _iv(4712.4, 9.1)),
        StrategyPlan(2, ["C4", "C3", "C3"], [16, 27, 27], _iv(4708.9, 11.4)),
        StrategyPlan(3, ["C4", "C4", "C3", "C3"], [12, 18, 20, 20], _iv(4731.6, 15.8)),
    ]
    return StrategyArtifact(
        event=event,
        pit_loss_s=21.4,
        race_laps=70,
        plans=plans,
        recommended_stops=2,
        rationale="Two stops is 3.5s faster than one, but the intervals overlap — it is a coin flip that turns on the safety-car probability.",
        confidence=0.58,
        optimal_stint={"C2": _iv(31.0, 4.0), "C3": _iv(24.0, 3.0), "C4": _iv(17.0, 3.0)},
    )


def meta() -> Meta:
    return Meta.now(
        model_version="fixture",
        season=SEASON,
        events=list(CONVENTIONAL_2026),
        n_laps_clean=13128,
        n_long_run_laps=10059,
        n_runs=875,
        n_drivers=22,
        fastf1_version="3.8.3",
        is_real=False,
    )


def bundle() -> dict:
    """A complete set of fixtures, ready for schema.write_all."""
    return {
        "meta": meta(),
        "degradation": degradation("practice"),
        "ablation": ablation("practice"),
        "benchmark": benchmark(),
        "calibration": calibration(),
        "power": power(),
        "transfer": transfer(),
        "strategy": strategy(),
    }
