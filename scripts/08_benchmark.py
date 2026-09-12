"""Score our model against the published benchmark, and write benchmark.json.

    python scripts/08_benchmark.py

Until now this artifact was the only one no script produced, which meant the
headline comparison table in the app could not be regenerated or checked. This
fixes that: every number in the table now comes from here.

Two comparisons are made, and they are not the same thing.

1. AUSTRIA 2025. The race in their paper, under their exact cross-validation
   scheme, scored with the same CRPS estimator. This is a direct, like-for-like
   comparison against their Table 1 and Table 2.

2. THE 2025 SEASON, RACE BY RACE. Their repo publishes per-race CRPS in
   ``Cross_Validation_Results/All_CV_results1.csv``, so this is a real
   head-to-head rather than a comparison of two season averages over different
   race sets.

   This docstring previously said their per-race numbers were not published and
   that a win/loss table therefore could not be built. That was wrong, and it
   was wrong in the direction that flattered us: the table says we win 2 of the
   15 races we both scored, where comparing our median against their mean had
   looked far closer. The file was in the repo the whole time.

We do not include a "reproduced" row for their state-space model. We verified
their published parameter estimates, not a re-run of their sampler, and a row
labelled "reproduced" with empty cells claims more than that and says less.
"""

from __future__ import annotations

import warnings

import pandas as pd

from cleanair.artifacts import schema
from cleanair.artifacts.schema import BenchmarkArtifact, BenchmarkScore, RaceScore
from cleanair.config import (
    BENCHMARK_CRPS,
    BENCHMARK_RMSPE,
    BENCHMARK_SEASON_2025,
    BENCHMARK_SEASON_2025_PER_RACE,
    PROCESSED,
)
from cleanair.data.cache import season_completeness
from cleanair.validation.benchmark import score
from cleanair.validation.scoring import crosscheck_against_r

warnings.filterwarnings("ignore")

#: The race their paper scored.
PAPER_RACE = "Austrian Grand Prix"
#: Their subject driver.
PAPER_DRIVER = "HAM"


def season_scores(races: pd.DataFrame) -> pd.DataFrame:
    """Score every race in the season on the benchmark's own scheme.

    A race is skipped rather than fudged when the driver's stints are too short
    for their cross-validation to produce any test laps.
    """
    rows = []
    for event, g in races.groupby("event", sort=True):
        try:
            r = score(g, driver=PAPER_DRIVER, event=str(event))
        except ValueError as exc:
            print(f"  skipped {event}: {exc}")
            continue
        if r.n_predictions == 0:
            print(f"  skipped {event}: no test laps under their CV scheme")
            continue
        rows.append(
            {
                "event": str(event),
                "crps": r.crps,
                "rmse_total": r.rmse_total,
                "n_stints": len(r.per_stint_crps),
                "n_predictions": r.n_predictions,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    path = PROCESSED / "laps_2025.parquet"

    # The season mean below is reported next to theirs, so a truncated pull
    # would compare a different number of races against a fixed 19 and call it
    # a comparison. Refuse instead: a wrong benchmark number is worse than none.
    ok, why = season_completeness(path)
    print(f"  2025 data: {why}")
    if not ok:
        raise SystemExit(
            "refusing to score an incomplete season. Re-run "
            "scripts/01_cache_sessions.py --season 2025 once the API cap resets."
        )

    laps = pd.read_parquet(path)
    races = laps[laps["session"] == "R"]

    print("=" * 72)
    print(f"1. {PAPER_RACE} 2025 -- their race, their CV scheme, their estimator")
    print("=" * 72)

    austria = score(races[races["event"] == PAPER_RACE], driver=PAPER_DRIVER, event=PAPER_RACE)
    print(f"  our CRPS       {austria.crps:.4f}   (their best, skew-t: {BENCHMARK_CRPS['skew_t']})")
    print(f"  our RMSE total {austria.rmse_total:.4f}   (their best: {BENCHMARK_RMSPE['skew_t']})")
    print(f"  {austria.n_predictions} predicted laps across {len(austria.per_stint_crps)} stints")

    beat_crps = austria.crps < BENCHMARK_CRPS["skew_t"]
    beat_rmse = austria.rmse_total < BENCHMARK_RMSPE["skew_t"]
    print(f"  beats their CRPS: {beat_crps}   beats their RMSE: {beat_rmse}")

    print()
    print("=" * 72)
    print("2. the 2025 season -- race by race, against their own published numbers")
    print("=" * 72)

    season = season_scores(races)
    ours_mean = float(season["crps"].mean())
    ours_median = float(season["crps"].median())
    theirs_mean = BENCHMARK_SEASON_2025["skewt_crps_mean"]

    # Their per-race CRPS, from All_CV_results1.csv in their repo. This section
    # used to print "season means, because per-race numbers are not published",
    # which was false -- the file was there and we had not opened it. The
    # comparison it enabled is considerably worse for us, which is the point.
    season["theirs"] = season["event"].map(
        lambda e: BENCHMARK_SEASON_2025_PER_RACE.get(e, (None, None))[0]
    )
    season["their_stints"] = season["event"].map(
        lambda e: BENCHMARK_SEASON_2025_PER_RACE.get(e, (None, None))[1]
    )
    matched = season[season["theirs"].notna()].copy()
    matched["win"] = matched["crps"] < matched["theirs"]

    print(f"  {'race':30s}{'ours':>8s}{'theirs':>9s}{'stints':>9s}{'win':>6s}")
    for _, r in matched.sort_values("crps").iterrows():
        stints = f"{int(r['n_stints'])}/{int(r['their_stints'])}"
        print(
            f"  {r['event']:30s}{r['crps']:8.4f}{r['theirs']:9.4f}"
            f"{stints:>9s}{'YES' if r['win'] else '':>6s}"
        )

    n_wins = int(matched["win"].sum())
    same_stints = int((matched["n_stints"] == matched["their_stints"]).sum())
    print()
    print(f"  WE WIN {n_wins} OF {len(matched)} races we both scored.")
    print(f"  ours   mean {matched['crps'].mean():.4f}  median {matched['crps'].median():.4f}")
    print(f"  theirs mean {matched['theirs'].mean():.4f}  median {matched['theirs'].median():.4f}")
    print()
    print("  Like-for-like check: our reconstructed stint count matches theirs at")
    print(f"  {same_stints} of {len(matched)} races, and their Austria figure here is")
    print(f"  {BENCHMARK_SEASON_2025_PER_RACE['Austrian Grand Prix'][0]} against the paper's 0.202.")
    print()
    print("  NOTE our mean is dominated by one race. At Singapore Hamilton lost 32s on a")
    print("       single green-flag lap while the field's median was unchanged, so it was")
    print("       his car, not the track. The lap is KEPT: dropping the laps we predict")
    print("       worst would flatter the score. The median is reported beside the mean.")
    print(f"  NOTE we scored {len(season)} races to their "
          f"{BENCHMARK_SEASON_2025['n_races']}; unmatched races are ours only.")

    print()
    print("=" * 72)
    print("3. is our CRPS the same number theirs is?")
    print("=" * 72)

    xc = crosscheck_against_r()
    max_diff = None
    if xc.get("available"):
        max_diff = max(xc["normal"]["diff"], xc["ensemble"]["diff"])
        print(f"  vs R scoringRules, closed form : {xc['normal']['diff']:.2e}")
        print(f"  vs R scoringRules, from draws  : {xc['ensemble']['diff']:.2e}")
        print(f"  worst disagreement             : {max_diff:.2e}")
    else:
        print(f"  R not available ({xc.get('reason')}) -- claim left out of the artifact")

    rows = [
        BenchmarkScore("ARIMA(2,1,2)", BENCHMARK_RMSPE["arima"], BENCHMARK_CRPS["arima"], "published"),
        BenchmarkScore("SSM base", BENCHMARK_RMSPE["base"], BENCHMARK_CRPS["base"], "published"),
        BenchmarkScore("SSM compound-specific", BENCHMARK_RMSPE["ext1"], BENCHMARK_CRPS["ext1"], "published"),
        BenchmarkScore("SSM skew-t (their best)", BENCHMARK_RMSPE["skew_t"], BENCHMARK_CRPS["skew_t"], "published"),
        BenchmarkScore(
            "Clean Air pooled",
            round(austria.rmse_total, 4),
            round(austria.crps, 4),
            "ours",
        ),
    ]

    # season_2025 was left empty for a long time on the belief that their side
    # of a per-race table did not exist. It does, so this is now populated and
    # the app can render the head-to-head instead of two season averages.
    per_race = [
        RaceScore(
            race=str(r["event"]),
            ours_crps=round(float(r["crps"]), 4),
            theirs_crps=round(float(r["theirs"]), 4),
            ours_wins=bool(r["win"]),
        )
        for _, r in matched.sort_values("crps").iterrows()
    ]

    schema.write(
        "benchmark",
        BenchmarkArtifact(
            austria_2025=rows,
            season_2025=per_race,
            n_wins=n_wins,
            n_races=len(matched),
            ours_season_crps=round(ours_mean, 4),
            ours_season_crps_median=round(ours_median, 4),
            theirs_season_crps=theirs_mean,
            ours_season_races=len(season),
            theirs_season_races=BENCHMARK_SEASON_2025["n_races"],
            r_crosscheck_max_diff=max_diff,
        ),
    )
    print()
    print("=" * 72)
    print("VERDICT")
    print("=" * 72)
    print("  We do NOT beat them at forecasting one driver's next lap:")
    print(f"    Austria  ours {austria.crps:.3f} vs their best {BENCHMARK_CRPS['skew_t']:.3f}")
    print(f"    season   we win {n_wins} of {len(matched)} races scored by both")
    print("  Their model is built for exactly that job and does it better.")
    print()
    print("  One qualifier that is real and is not an excuse: their scheme scores")
    print("  16 predictions at Austria, and a bootstrap over those laps puts our")
    print("  95% interval at [0.151, 0.365] -- their 0.202 sits inside it. One lap")
    print("  carries 28% of our score there. The race-by-race table above is the")
    print("  stronger evidence, and it is the one that says we lose.")
    print()
    print("  What it cannot do is separate the compounds. Their own compound-specific")
    print("  model scored WORSE than their base model, and their best model has no")
    print("  compound structure at all. That is the question we answer, and the power")
    print("  analysis shows their three-stint design could not have answered it.")

    print("\nwrote benchmark.json")


if __name__ == "__main__":
    main()
