"""Which practice session actually predicts the race.

    python scripts/12_session_skill.py

FP1, FP2 and FP3 were pooled as one bucket until now, on the unexamined
assumption that a practice lap is a practice lap. A mentor asked why FP2 was
not weighted more heavily, which turned out to be a question the data could
answer rather than a matter of convention.

For every (event, compound) cell we can measure in BOTH a practice session and
the race that followed, this scores the session's degradation against the
race's. Three sessions, one table, no tuning.

The numbers it prints are the ones hardcoded in ``api.SESSION_SKILL`` and used
to justify ``data.session_weight.SESSION_WEIGHTS``. ``tests`` re-runs the
comparison and fails if FP2 ever stops being the best predictor, so the weights
stay checked rather than assumed.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from cleanair.config import PROCESSED
from cleanair.data.session_weight import SESSION_WEIGHTS
from cleanair.models.design import prepare
from cleanair.validation.transfer import MIN_AGE_SPREAD_LAPS, cell_rates

warnings.filterwarnings("ignore")

#: Loosened from the pooled thresholds on purpose. One session holds a third of
#: the weekend's running, so the pooled bar would leave almost nothing to score
#: and the comparison would be decided by which session happened to clear it.
SESSION_MIN_RUNS = 2
SESSION_MIN_RUNS_PER_COMPOUND = 1


def paired_cells(laps: pd.DataFrame) -> pd.DataFrame:
    """Every cell measurable in one practice session and in its race."""
    race = prepare(laps, "race")
    truth = cell_rates(race, min_age_spread=MIN_AGE_SPREAD_LAPS).set_index(["event", "C"])["rate"]

    rows = []
    for ses in ("FP1", "FP2", "FP3"):
        sub = laps[laps["session"].isin([ses, "R"])]
        p = prepare(sub, "practice", min_runs_per_compound=SESSION_MIN_RUNS_PER_COMPOUND)
        if p.empty:
            continue
        for _, r in cell_rates(p, min_runs=SESSION_MIN_RUNS).iterrows():
            key = (r["event"], r["C"])
            if key in truth.index:
                rows.append(
                    {
                        "session": ses,
                        "event": r["event"],
                        "C": r["C"],
                        "n_runs": int(r["n_runs"]),
                        "n_laps": int(r["n_laps"]),
                        "practice": float(r["rate"]),
                        "race": float(truth.loc[key]),
                    }
                )
    return pd.DataFrame(rows)


def score(d: pd.DataFrame) -> pd.DataFrame:
    """Correlation, transfer factor and error, per session."""
    out = []
    for ses, g in d.groupby("session"):
        # The factor is the least-squares scaling from practice to race with no
        # intercept, which is what the forecast actually applies. A NEGATIVE
        # factor means the session points the wrong way: its steeper cells are
        # the race's flatter ones.
        denom = float((g["practice"] ** 2).sum())
        factor = float((g["race"] * g["practice"]).sum() / denom) if denom > 0 else np.nan
        corr = g["practice"].corr(g["race"]) if len(g) > 2 else np.nan
        out.append(
            {
                "session": ses,
                "n_cells": len(g),
                "median_runs": int(g["n_runs"].median()),
                "median_laps": int(g["n_laps"].median()),
                "correlation": round(float(corr), 3) if pd.notna(corr) else None,
                "factor": round(factor, 4) if pd.notna(factor) else None,
                "mae": round(float(np.abs(g["practice"] * factor - g["race"]).mean()), 4)
                if pd.notna(factor)
                else None,
            }
        )
    return pd.DataFrame(out).set_index("session")


def main() -> None:
    laps = pd.read_parquet(PROCESSED / "laps.parquet")
    d = paired_cells(laps)
    if d.empty:
        print("no paired practice/race cells; nothing to score")
        return

    tbl = score(d)
    print("=" * 72)
    print("WHICH PRACTICE SESSION PREDICTS THE RACE")
    print("Each cell is one (event, compound) measured in practice and again in")
    print("the race. Correlation is between the two. A session that predicts")
    print("nothing scores near zero however many laps it ran.")
    print("=" * 72)
    print(tbl.to_string())

    print("\nWEIGHTS IN USE:", SESSION_WEIGHTS)
    ranked = tbl["correlation"].dropna()
    if not ranked.empty:
        best = ranked.idxmax()
        print(f"best predictor: {best} (correlation {ranked.max():.3f})")
        top = max(SESSION_WEIGHTS, key=lambda k: SESSION_WEIGHTS[k])
        agree = "yes" if best == top else "NO -- the weights disagree with the data"
        print(f"heaviest weight: {top}   consistent: {agree}")

    print("\nPER-CELL DETAIL")
    print(d.sort_values(["session", "event"]).to_string(index=False))


if __name__ == "__main__":
    main()
