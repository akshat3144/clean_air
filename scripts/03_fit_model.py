"""Fit the degradation model and write real artifacts.

    python scripts/03_fit_model.py
    python scripts/03_fit_model.py --context practice

Race is the default because it has ten times the usable laps. Practice is what
the brief asks for, and the two disagree -- which is itself a finding.
"""

from __future__ import annotations

import argparse
import warnings

import fastf1
import pandas as pd

from cleanair.artifacts import schema
from cleanair.config import PROCESSED, SEASON
from cleanair.models import ablation
from cleanair.models.design import prepare
from cleanair.models.mixed import fit_degradation, fuel_sensitivity, to_artifact

warnings.filterwarnings("ignore")


def report(fit, df) -> None:
    print(f"\n{'=' * 68}")
    print(f"{fit.context.upper()}   {len(df):,} laps · {df.run_id.nunique()} runs · "
          f"{df.Driver.nunique()} drivers · quadratic={fit.quadratic}")
    print("=" * 68)
    header = f"{'':5s}{'rate s/lap':>12s}{'95% interval':>22s}{'width':>9s}{'runs':>6s}"
    if fit.quadratic:
        header += f"{'@15 laps':>10s}{'20-lap loss':>13s}"
    print(header)
    for c in fit.ordered:
        r = fit.rates[c]
        line = (f"  {c:3s}{r.mean:12.4f}   [{r.lo:+.4f}, {r.hi:+.4f}]{r.hi - r.lo:9.4f}"
                f"{fit.n_runs.get(c, 0):6d}")
        if fit.quadratic:
            line += f"{fit.rate_at(c, 15):10.4f}{fit.total_loss(c, 20):13.2f}"
        print(line)
    print(f"\n  monotone (softer degrades faster): {fit.is_monotone()}")
    print(f"  separated pairs: {fit.separated_pairs() or 'none'}")
    print(f"  converged: {fit.converged}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--context", choices=["race", "practice", "both"], default="both")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    laps = pd.read_parquet(PROCESSED / "laps.parquet")
    contexts = ["race", "practice"] if args.context == "both" else [args.context]

    fits = {}
    for ctx in contexts:
        df = prepare(laps, ctx)
        # No quadratic in practice: runs average seven laps, over which tyre age
        # and its square correlate at 0.99, so the curvature is unidentifiable.
        # No compound offsets in practice. practice_design centres each lap
        # within its RUN, and a run is one compound, so the compound level is
        # differenced away before the model sees it -- statsmodels returns a
        # coefficient of exactly 0 with a NaN standard error. In the race design
        # the demeaning is by (event, lap), so cars on different compounds share
        # a cell and the offset IS identified.
        # Circuit effects in the race fit. Ignoring them does not just lose the
        # per-track detail -- it also makes the GLOBAL interval too narrow,
        # because 11,000 laps from 13 circuits are not 11,000 independent
        # observations. The intervals below are wider than they used to be and
        # that is a correction, not a regression.
        # NO QUADRATIC, in either context.
        #
        # This script used to fit one for the race, and it was the only place
        # in the project that did. api.py, 06_strategy.py, 09_playbook.py and
        # 04_validate.py all pass quadratic=False, so the curve published here
        # -- the Tyre Curves tab, and the headline table in the README -- was
        # the one number nobody planned on and nobody had validated.
        #
        # They disagree by a lot. C1 read 0.115 s/lap in the artifact against
        # 0.084 in every fit that makes a decision; C5 read 0.003 against
        # 0.011. Two models of the same tyre, shipped side by side.
        #
        # The linear one wins on three counts. Its rate is the average slope
        # over the ages we observed, which is what "s/lap lost" means to a
        # reader; a quadratic's rate is the tangent at age zero, which is not.
        # It is the fit the 80.6% coverage result was measured on. And the
        # fitted curvature is NEGATIVE -- degradation decelerating, which is
        # the opposite of a cliff and is more plausibly the warm-up and
        # management effects than tyre physics. Significant for C2 and C3
        # only; C1, C4 and C5 straddle zero.
        fit = fit_degradation(
            df,
            quadratic=False,
            context=ctx,
            with_offsets=(ctx == "race"),
            circuit_effects=(ctx == "race"),
        )
        report(fit, df)
        fits[ctx] = fit

    if "practice" in contexts:
        print(f"\n{'=' * 68}")
        print("FUEL SENSITIVITY — practice assumes s/kg rather than fitting it")
        print("=" * 68)
        s = fuel_sensitivity(laps)
        print(s.pivot(index="compound", columns="s_per_kg", values="rate").round(4).to_string())
        spread = s.groupby("compound")["rate"].agg(lambda x: x.max() - x.min()).max()
        print(f"\n  largest change across the 0.030-0.035 range: {spread:.4f} s/lap")
        print("  -> the fuel assumption is not driving the result"
              if spread < 0.01 else "  -> the fuel assumption MATTERS; report it")

    if not args.no_write and "race" in fits:
        art = to_artifact(fits["race"])
        path = schema.write("degradation", art)
        print(f"\nwrote {path}")

        # ablation.json is built from the SAME fit, in the same run. It used
        # to be written out of band, drifted a day and a half behind the
        # model, and the app ended up drawing C3 at 0.054 on the Method tab
        # and 0.091 on Tyre Curves. Two artifacts describing one quantity
        # have to come from one fit.
        abl = ablation.build(laps, fits["race"], context="race")
        path = schema.write("ablation", abl)
        print(f"wrote {path}")

        # meta.json too. It was written once on 3 Sep and never again, so the
        # app header still announced "7 events, 6,426 long-run laps" after the
        # dataset had grown to 13 events and 11,039 -- the same orphaned-file
        # failure ablation.json had. Anything describing the dataset is written
        # by the stage that reads the dataset.
        design = fits["race"]
        meta = schema.Meta.now(
            model_version="mixedlm-v2-circuit",
            season=SEASON,
            events=sorted({e for evs in design.events.values() for e in evs}),
            n_laps_clean=int(len(laps)),
            n_long_run_laps=int(design.n_obs),
            n_runs=int(sum(design.n_runs.values())),
            n_drivers=int(design.n_drivers),
            fastf1_version=fastf1.__version__,
            is_real=True,
        )
        path = schema.write("meta", meta)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
