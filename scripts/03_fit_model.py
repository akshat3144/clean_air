"""Fit the degradation model and write real artifacts.

    python scripts/03_fit_model.py
    python scripts/03_fit_model.py --context practice

Race is the default because it has ten times the usable laps. Practice is what
the brief asks for, and the two disagree -- which is itself a finding.
"""

from __future__ import annotations

import argparse
import warnings

import pandas as pd

from cleanair.artifacts import schema
from cleanair.config import PROCESSED
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
        fit = fit_degradation(df, quadratic=(ctx == "race"), context=ctx)
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


if __name__ == "__main__":
    main()
