"""Why softer compounds do not appear to degrade faster.

    python scripts/07_management.py

Our race fits keep saying softer compounds degrade no faster than hard ones,
which contradicts how tyres work. This tests the leading explanation: a driver
nurses a fragile tyre in a race and pushes it in practice, so the race number is
suppressed most for the softest tyre.

Uses every season on disk, because the answer is limited by sample size and
nothing else. Also reports how the effect moved as seasons were added -- ours
shrank, and that belongs in the output rather than in a footnote.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from cleanair.artifacts import schema
from cleanair.artifacts.schema import ManagementArtifact, ManagementRow
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
    """Practice and race design frames for one season."""
    laps = pd.read_parquet(path)
    laps = laps[laps["Compound"].isin(LABELS)].dropna(subset=["TyreLife", "LapTimeSeconds"])

    prac = drop_non_representative_laps(laps[laps["session"] != "R"])
    prac = tag_long_runs(prac)
    prac = classify_runs(drop_stint_outliers(prac[prac["is_long_run"]]))
    prac = practice_design(prac[prac["is_race_sim"]])

    race = race_design(drop_stint_outliers(laps[laps["is_long_run"]]))
    return prac, race


def stability_table(per_season: dict) -> list[dict]:
    """How the effect moves as seasons are added, newest first.

    Included because our own effect got SMALLER with more data -- rho went from
    -0.40 at 26 cells to -0.27 at 50 -- and a result that weakens as evidence
    grows is exactly the thing a reader deserves to see.
    """
    rows = []
    newest_first = sorted(per_season, reverse=True)
    for k in range(1, len(newest_first) + 1):
        subset = {s: per_season[s] for s in newest_first[:k]}
        try:
            r = analyse(subset)
        except ValueError:
            continue
        rows.append(
            {
                "seasons": sorted(subset),
                "n_cells": r.n_cells,
                "rho": round(r.rho, 4),
                "p_one_sided": round(r.p_value, 4),
                "p_two_sided": round(r.p_two_sided, 4),
                "ordered": r.ordered,
            }
        )
    return rows


def main() -> None:
    sources = {2026: PROCESSED / "laps.parquet"}
    for season in (2025, 2024, 2023, 2022):
        path = PROCESSED / f"laps_{season}.parquet"
        if path.exists():
            sources[season] = path

    per_season = {}
    for season, path in sorted(sources.items(), reverse=True):
        per_season[season] = build(path)
        print(f"  {season}: loaded {path.name}")

    res = analyse(per_season)

    print()
    print("=" * 70)
    print(
        f"{res.n_cells} (event, compound) cells across {res.n_events} events, "
        f"{res.n_seasons} seasons"
    )
    print("=" * 70)
    print()
    header = f"{'label':9s}{'n':>4s}{'race/practice':>16s}{'median race':>14s}{'median practice':>18s}"
    print(header)
    for lab in LABELS:
        sub = res.cells[res.cells["Compound"] == lab]
        if len(sub) < 3:
            continue
        print(
            f"{lab:9s}{len(sub):4d}{sub['ratio'].median():16.3f}"
            f"{sub['race'].median():14.4f}{sub['practice'].median():18.4f}"
        )

    print()
    print(f"  ratio falls as the tyre softens   : {res.ordered}")
    print(f"  Spearman rho                      : {res.rho:+.3f}")
    print(f"  one-sided p (direction predicted) : {res.p_value:.4f}")
    print(f"  two-sided p (if you prefer)       : {res.p_two_sided:.4f}")
    print(f"  Kruskal-Wallis, ignoring ordering : {res.p_kruskal:.4f}")
    print()
    print(f"  {res.verdict()}")

    stability = stability_table(per_season)
    if len(stability) > 1:
        print()
        print("  HOW IT MOVED AS SEASONS WERE ADDED")
        print(f"  {'seasons':22s}{'cells':>7s}{'rho':>9s}{'p 1-sided':>12s}{'p 2-sided':>12s}")
        for row in stability:
            tag = "+".join(str(s) for s in row["seasons"])
            print(
                f"  {tag:22s}{row['n_cells']:7d}{row['rho']:9.3f}"
                f"{row['p_one_sided']:12.4f}{row['p_two_sided']:12.4f}"
            )

    schema.write(
        "management",
        ManagementArtifact(
            rows=[
                ManagementRow(
                    label=lab,
                    n_cells=int((res.cells["Compound"] == lab).sum()),
                    ratio=round(float(res.cells[res.cells["Compound"] == lab]["ratio"].median()), 4),
                    median_race=round(
                        float(res.cells[res.cells["Compound"] == lab]["race"].median()), 5
                    ),
                    median_practice=round(
                        float(res.cells[res.cells["Compound"] == lab]["practice"].median()), 5
                    ),
                )
                for lab in LABELS
                if (res.cells["Compound"] == lab).sum() >= 3
            ],
            n_cells=res.n_cells,
            n_events=res.n_events,
            n_seasons=res.n_seasons,
            seasons=sorted(per_season),
            rho=round(res.rho, 4),
            p_one_sided=round(res.p_value, 4),
            p_two_sided=round(res.p_two_sided, 4),
            p_kruskal=round(res.p_kruskal, 4),
            ordered=bool(res.ordered),
            significant=bool(res.significant),
            verdict=res.verdict(),
            stability=stability,
        ),
    )
    print()
    print("wrote management.json")


if __name__ == "__main__":
    main()
