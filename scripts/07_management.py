"""Test whether drivers manage softer tyres harder in races than in practice.

    python scripts/07_management.py

Our race fits keep saying softer compounds do not degrade faster. This tests the
leading explanation: that a driver nurses a fragile tyre in a race and pushes it
in practice, so the race number is suppressed most for the softest tyre.

Uses every season available, because the answer is limited by sample size and
nothing else.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from cleanair.config import PROCESSED
from cleanair.data.laps import tag_long_runs
from cleanair.models.design import (
    classify_runs,
    drop_non_representative_laps,
    drop_stint_outliers,
    practice_design,
    race_design,
)
from cleanair.validation.management import LABELS, analyse

warnings.filterwarnings("ignore")


def build(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    laps = pd.read_parquet(path)
    laps = laps[laps["Compound"].isin(LABELS)].dropna(subset=["TyreLife", "LapTimeSeconds"])

    prac = drop_non_representative_laps(laps[laps["session"] != "R"])
    prac = tag_long_runs(prac)
    prac = classify_runs(drop_stint_outliers(prac[prac["is_long_run"]]))
    prac = practice_design(prac[prac["is_race_sim"]])

    race = race_design(drop_stint_outliers(laps[laps["is_long_run"]]))
    return prac, race


def main() -> None:
    sources = {2026: PROCESSED / "laps.parquet"}
    for season in (2025, 2024, 2023):
        p = PROCESSED / f"laps_{season}.parquet"
        if p.exists():
            sources[season] = p

    per_season = {}
    for season, path in sorted(sources.items(), reverse=True):
        per_season[season] = build(path)
        print(f"  {season}: loaded {path.name}")

    res = analyse(per_season)

    print(f"\n{'=' * 70}")
    print(f"{res.n_cells} (event, compound) cells across {res.n_events} events, "
          f"{res.n_seasons} seasons")
    print("=" * 70)
    print(f"\n{'label':9s}{'n':>4s}{'median ratio':>15s}{'median race':>14s}{'median practice':>18s}")
    for lab in LABELS:
        s = res.cells[res.cells["Compound"] == lab]
        if len(s) < 3:
            continue
        print(f"{lab:9s}{len(s):4d}{s['ratio'].median():15.3f}"
              f"{s['race'].median():14.4f}{s['practice'].median():18.4f}")

    print(f"\n  ratio falls as the tyre softens : {res.ordered}")
    print(f"  Spearman rho                    : {res.rho:+.3f}")
    print(f"  one-sided p  (direction predicted): {res.p_value:.4f}")
    print(f"  two-sided p  (if you prefer)      : {res.p_two_sided:.4f}")
    print(f"  Kruskal-Wallis, ignoring ordering : {res.p_kruskal:.4f}")
    print(f"\n  {res.verdict()}")

    if res.ordered and not res.significant:
        print("\n  More seasons would settle it. The direction has been stable at")
        print("  every sample size we have tried, which is encouraging but is not")
        print("  the same as evidence.")


if __name__ == "__main__":
    main()
