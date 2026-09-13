"""Why softer compounds do not appear to degrade faster.

    python scripts/07_management.py

Our race fits keep saying softer compounds degrade no faster than hard ones,
which contradicts how tyres work. This tests the leading explanation: a driver
nurses a fragile tyre in a race and pushes it in practice, so the race number is
suppressed most for the softest tyre.

Uses every COMPLETE season on disk, because the answer is limited by sample size
and nothing else. Truncated pulls are refused rather than pooled -- see
season_completeness.

Also reports how the effect moved as seasons were added, because it did not move
in one direction: significant at two seasons, marginal at three, then clear at
four and five. That trail belongs in the output rather than in a footnote, since
the alternative reading -- drop the season that disagrees and report the better
number -- was available at every step and is what the trail rules out.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from cleanair.artifacts import schema
from cleanair.artifacts.schema import ManagementArtifact, ManagementRow
from cleanair.config import PROCESSED
from cleanair.data.cache import season_completeness
from cleanair.data.laps import tag_long_runs
from cleanair.data.schedule import SPRINT_SESSION
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

    # A sprint is a race, not practice.
    #
    # It arrived in the dataset for the forecast, where Saturday running is a
    # legitimate predictor of Sunday and measurably helps. Here it is poison:
    # this test contrasts how a driver treats a tyre when racing against how
    # they treat it in practice, and a sprint sits on the racing side of that
    # line. Left in the practice bucket it moved rho from -0.308 to -0.314 on
    # 105 cells instead of 98 -- a better-looking answer to a question we had
    # stopped asking.
    prac = drop_non_representative_laps(
        laps[~laps["session"].isin(["R", SPRINT_SESSION])]
    )
    prac = tag_long_runs(prac)
    prac = classify_runs(drop_stint_outliers(prac[prac["is_long_run"]]))
    prac = practice_design(prac[prac["is_race_sim"]])

    race = race_design(drop_stint_outliers(laps[laps["is_long_run"]]))
    return prac, race


def stability_table(per_season: dict) -> list[dict]:
    """How the effect moves as seasons are added, newest first.

    rho is not monotone in sample size: -0.375, -0.402, -0.266, -0.312, -0.282
    as 2026 through 2022 come in. It dipped hardest at three seasons, which is
    where the two-sided p failed and the verdict read "marginal". Printing the
    whole path is the point -- a reader who sees only the final row cannot tell
    whether the claim survived the evidence or was fitted to it.
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

    per_season, excluded = {}, []
    for season, path in sorted(sources.items(), reverse=True):
        ok, why = season_completeness(path)
        if not ok:
            excluded.append((season, why))
            print(f"  {season}: SKIPPED -- {why}")
            continue
        per_season[season] = build(path)
        print(f"  {season}: loaded {path.name} -- {why}")

    if excluded:
        print(
            f"\n  {len(excluded)} season(s) excluded as incomplete. Re-run "
            f"scripts/01_cache_sessions.py --season <year> once the API cap resets."
        )

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
        # 26 wide, not 22: five seasons joined by "+" is 24 characters, which
        # overflowed the column and pushed every later field out of line.
        print(f"  {'seasons':26s}{'cells':>7s}{'rho':>9s}{'p 1-sided':>12s}{'p 2-sided':>12s}")
        for row in stability:
            tag = "+".join(str(s) for s in row["seasons"])
            print(
                f"  {tag:26s}{row['n_cells']:7d}{row['rho']:9.3f}"
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
