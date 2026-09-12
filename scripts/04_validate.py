"""Run every validation check and write the artifacts.

    python scripts/04_validate.py

Four questions, in order of how much they matter:

  1. How much data does this need?  (power)
  2. Is the uncertainty honest?     (calibration)
  3. Do we score the same way they do?  (CRPS cross-check against R)
  4. Can we separate the compounds? (from the fitted model)
"""

from __future__ import annotations

import warnings

import pandas as pd

from cleanair.artifacts import schema
from cleanair.artifacts.schema import CalibrationArtifact, CalibrationPoint, PowerArtifact, PowerPoint
from cleanair.config import PROCESSED
from cleanair.models.design import prepare
from cleanair.models.mixed import fit_degradation
from cleanair.validation.calibration import leave_one_run_out
from cleanair.validation.power import DEFAULT_EFFECT, detectable_effect, estimate_noise, power_curve
from cleanair.validation.scoring import crosscheck_against_r

warnings.filterwarnings("ignore")

#: The benchmark fitted one driver at one race: three stints.
BENCHMARK_STINTS = 3


def main() -> None:
    laps = pd.read_parquet(PROCESSED / "laps.parquet")
    race = prepare(laps, "race")
    practice = prepare(laps, "practice")

    n_race = race["run_id"].nunique()
    n_prac = practice["run_id"].nunique()
    noise_r = estimate_noise(race)
    noise_p = estimate_noise(practice)

    # ---- 1. power ----------------------------------------------------------
    print("=" * 70)
    print("1. POWER — how much data does separating two compounds need?")
    print("=" * 70)
    pc = power_curve(noise=noise_r, n_sims=1200)
    print(f"   effect {pc.effect:.3f} s/lap · noise {pc.noise:.2f}s · {pc.stint_laps}-lap stints\n")
    for n, p in zip(pc.n_stints, pc.power, strict=True):
        print(f"   {n:4d} stints  {p:5.1%}  {'#' * int(p * 40)}")

    n80 = pc.n_for(0.80)
    print(f"\n   80% power needs ~{n80} driver-stints")
    print(f"   benchmark  ({BENCHMARK_STINTS:3d} stints): power {pc.power_at(BENCHMARK_STINTS):5.1%}")
    print(f"   our race   ({n_race:3d} stints): power {pc.power_at(n_race):5.1%}")
    print(f"   our practice ({n_prac:3d} stints): power {pc.power_at(n_prac):5.1%}")

    e_race = detectable_effect(n_race, noise_r)
    e_prac = detectable_effect(n_prac, noise_p)
    e_bench = detectable_effect(BENCHMARK_STINTS, noise_r)
    print(f"\n   smallest detectable effect, benchmark: "
          f"{'nothing up to 0.10 s/lap' if e_bench is None else f'{e_bench:.4f} s/lap'}")
    print(f"   smallest detectable effect, race:      {e_race:.4f} s/lap")
    print(f"   smallest detectable effect, practice:  {e_prac:.4f} s/lap")

    # ---- 2. calibration ----------------------------------------------------
    print("\n" + "=" * 70)
    print("2. CALIBRATION — when it says 80%, is it right 80% of the time?")
    print("=" * 70)
    cals = {}
    for name, df in (("race", race), ("practice", practice)):
        cal = leave_one_run_out(df)
        cals[name] = cal
        print(f"\n   {name}: {cal.n:,} held-out laps, {cal.n_runs} runs")
        for nom, emp in zip(cal.levels, cal.empirical, strict=True):
            flag = "" if abs(nom - emp) < 0.05 else "  <-"
            print(f"     {nom:5.0%} -> {emp:6.1%}  ({emp - nom:+.1%}){flag}")
        print(f"     80% coverage {cal.coverage_80:.1%} · "
              f"miscalibration {cal.miscalibration():.3f} · {cal.verdict()}")

    # ---- 3. scoring --------------------------------------------------------
    print("\n" + "=" * 70)
    print("3. SCORING — do we compute CRPS the same way the benchmark did?")
    print("=" * 70)
    x = crosscheck_against_r()
    if x.get("available"):
        for k in ("normal", "ensemble"):
            d = x[k]
            print(f"   {k:9s} python {d['python']:.8f}  R {d['r']:.8f}  diff {d['diff']:.1e}")
        agree = all(x[k]["diff"] < 1e-6 for k in ("normal", "ensemble"))
        print(f"   identical to 1e-6: {agree}  -> the comparison is genuinely like-for-like")
    else:
        print(f"   R unavailable ({x.get('reason')}) — cross-check skipped")

    # ---- 4. separation -----------------------------------------------------
    print("\n" + "=" * 70)
    print("4. SEPARATION — can we tell the compounds apart?")
    print("=" * 70)
    fit = fit_degradation(race, quadratic=False, context="race")
    for c in fit.ordered:
        r = fit.rates[c]
        print(f"   {c}  {r.mean:+.4f} [{r.lo:+.4f}, {r.hi:+.4f}]  width {r.hi - r.lo:.4f}")
    print(f"\n   separated pairs: {fit.separated_pairs() or 'none'}")
    print("   benchmark, for scale: Hard 0.054 [0.004, 0.133], width 0.129")

    # ---- write -------------------------------------------------------------
    schema.write(
        "power",
        PowerArtifact(
            effect_size=DEFAULT_EFFECT,
            points=[PowerPoint(int(n), float(p)) for n, p in zip(pc.n_stints, pc.power, strict=True)],
            n_for_80pct=int(n80) if n80 else -1,
            benchmark_n=BENCHMARK_STINTS,
            ours_n=n_race,
        ),
    )
    cal = cals["race"]
    schema.write(
        "calibration",
        CalibrationArtifact(
            points=[
                CalibrationPoint(float(n), float(e), cal.n)
                for n, e in zip(cal.levels, cal.empirical, strict=True)
            ],
            coverage_80=round(cal.coverage_80, 4),
            context="race",
        ),
    )
    print("\nwrote power.json and calibration.json")


if __name__ == "__main__":
    main()
