"""How much practice data are we throwing away, and does keeping it help?

    python scripts/13_design_sweep.py

THE QUESTION

Madrid 2026 holds 663 practice laps across three sessions and the model uses
42 of them. FP1 and FP3 contribute nothing at all, on a new circuit where this
weekend's running is the only evidence that exists. That is either correct
strictness or wasted data, and the argument cannot be settled by preference.

So: build the practice frame several ways, and score each against the races
that have already run. The metric is the one the brief names -- mean absolute
error predicting race degradation from practice degradation, leave-one-event-
out, so no event contributes to its own correction.

THE VARIANTS

    current     filter laps, THEN detect runs, require 5 consecutive, race
                simulations only. What ships today.

    keep-runs   detect runs on the stint FIRST, then drop bad laps but keep the
                run together. A lap removed from the middle of a stint
                currently SHATTERS it into two sub-5-lap fragments and both are
                discarded -- even though the design regresses on tyre age,
                which a hole in the lap sequence does not disturb.

    +warmup     keep-runs, and additionally drop the first lap of every run.
                Cappello & Hoegh (arXiv:2512.00640, Figure 3) find degradation
                is NEGATIVE over the opening laps of every stint as the tyre
                comes up to temperature. A short run can sit entirely inside
                that region and return a negative slope, which is what Madrid's
                two-run soft does at -0.051 s/lap.

    all-runs    keep-runs without the race-simulation filter. Qualifying
                simulations are low fuel and short, so this should be WORSE;
                it is here to check that the filter earns its place rather
                than being assumed to.

    min4        keep-runs with a four-lap minimum instead of five. The five is
                analyst folklore -- a literature search found no published
                justification for any threshold -- so it is worth testing.

Nothing here is adopted on the strength of recovering more laps. More data that
predicts worse is worse.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from cleanair.config import PROCESSED
from cleanair.data.laps import tag_long_runs
from cleanair.models.design import (
    add_physical_compound,
    classify_runs,
    drop_non_representative_laps,
    drop_stint_outliers,
    practice_design,
)
from cleanair.validation.transfer import (
    MIN_AGE_SPREAD_LAPS,
    cell_rates,
    leave_one_event_out,
)
from cleanair.models.design import prepare

warnings.filterwarnings("ignore")

DEMO_EVENT = "Spanish Grand Prix"


def build(
    laps: pd.DataFrame,
    *,
    keep_runs: bool = False,
    drop_warmup: int = 0,
    max_gap: int | None = None,
    race_sims_only: bool = True,
    min_laps: int = 5,
    min_runs_per_compound: int = 5,
) -> pd.DataFrame:
    """One practice frame, built to the flags given.

    Mirrors ``design.prepare(context="practice")`` exactly when called with
    defaults, so the "current" row of the sweep is the shipping pipeline and
    not a reimplementation of it that might differ.
    """
    df = add_physical_compound(laps)
    df = df[df["C"].notna()].dropna(subset=["TyreLife", "LapTimeSeconds"])
    df = df[df["session"] != "R"]

    if keep_runs:
        # Detect the run on the stint, THEN drop unrepresentative laps, and
        # judge the length on what survives. The run keeps its identity across
        # the hole rather than being split by it.
        df = tag_long_runs(df, min_laps=1)
        df = drop_non_representative_laps(df)
        if max_gap is not None:
            # Bridge only SMALL holes. A run interrupted by one discarded lap
            # is still one piece of driving; a run with a five-lap hole in it
            # is two, and stitching those together is the mistake the original
            # filter-then-detect order was guarding against. Keeping the guard
            # but sizing it lets us recover the first case without the second.
            df = df.sort_values(["event", "session", "Driver", "LapNumber"])
            prev = df.groupby("run_id")["LapNumber"].shift(1)
            gap = (df["LapNumber"] - prev).fillna(1)
            df["run_id"] = (
                df["run_id"] + "#" + gap.gt(max_gap).groupby(df["run_id"]).cumsum().astype(str)
            )
        if drop_warmup:
            df = df[df.groupby("run_id").cumcount() >= drop_warmup]
        keep = df.groupby("run_id")["LapNumber"].transform("size") >= min_laps
        df = df[keep]
    else:
        df = drop_non_representative_laps(df)
        df = tag_long_runs(df, min_laps=min_laps)
        df = df[df["is_long_run"]]
        if drop_warmup:
            # Isolates the warm-up effect from the run-shattering one: same
            # shattering as today, warm-up laps removed. If this alone matches
            # the combined variant, keeping runs intact is not what helped.
            df = df[df.groupby("run_id").cumcount() >= drop_warmup]

    if df.empty:
        return df
    df = drop_stint_outliers(df)
    df = classify_runs(df)
    if race_sims_only:
        df = df[df["is_race_sim"]]
    if df.empty:
        return df
    df = practice_design(df)
    runs = df.groupby("C")["run_id"].transform("nunique")
    return df[runs >= min_runs_per_compound].copy()


VARIANTS: dict[str, dict] = {
    "current": {},
    "keep-runs": {"keep_runs": True},
    "warmup1": {"keep_runs": True, "drop_warmup": 1},
    "warmup2": {"keep_runs": True, "drop_warmup": 2},
    "warmup3": {"keep_runs": True, "drop_warmup": 3},
    "warmup1-min4": {"keep_runs": True, "drop_warmup": 1, "min_laps": 4},
    "warmup1-min6": {"keep_runs": True, "drop_warmup": 1, "min_laps": 6},
    "warmup1-noshape": {"keep_runs": False, "drop_warmup": 1},
    "warmup1-gap1": {"keep_runs": True, "drop_warmup": 1, "max_gap": 2},
    "warmup1-gap2": {"keep_runs": True, "drop_warmup": 1, "max_gap": 3},
    "warmup1-gap4": {"keep_runs": True, "drop_warmup": 1, "max_gap": 5},
    "all-runs": {"keep_runs": True, "race_sims_only": False},
    "min4": {"keep_runs": True, "min_laps": 4},
}


def score(practice: pd.DataFrame, race: pd.DataFrame):
    """Transfer accuracy for one practice frame, plus its per-cell errors.

    The table comes back because the headline MAE is NOT comparable between
    variants on its own: each scores whatever cells it happens to leave
    standing, and a variant that throws away the hard ones wins on average
    while knowing less. ``common_mae`` below fixes that.
    """
    if practice.empty:
        return {}, None
    try:
        loo = leave_one_event_out(practice, race)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:60]}, None
    return {
        "mae": round(loo.mae_calibrated, 4),
        "improvement": round(loo.improvement * 100, 1),
        "factor": round(loo.factor, 4),
        "n_events": loo.n_events,
        "n_cells": len(loo.table),
    }, loo.table


def common_mae(tables):
    """MAE for each variant over the cells EVERY variant can score.

    Without this the sweep rewards ignorance. ``warmup3`` posts the lowest raw
    MAE while scoring six cells against ``current``'s twelve, and it gets there
    by discarding every run short enough to be hard. A variant has only
    genuinely improved if it predicts better on the SAME questions.
    """
    usable = {k: t for k, t in tables.items() if t is not None and not t.empty}
    if not usable:
        return {}, 0
    cols = [c for c in ("event", "C") if all(c in t.columns for t in usable.values())]
    if not cols:
        return {}, 0
    shared = set.intersection(*[set(map(tuple, t[cols].values)) for t in usable.values()])
    if not shared:
        return {}, 0
    out = {}
    for name, t in usable.items():
        mask = t[cols].apply(lambda r: tuple(r) in shared, axis=1)
        out[name] = round(float(t.loc[mask, "calibrated_err"].mean()), 4)
    return out, len(shared)


def demo_coverage(practice: pd.DataFrame) -> dict:
    """What the demo race gets out of it -- the reason any of this matters."""
    m = practice[practice["event"] == DEMO_EVENT]
    if m.empty:
        return {"sessions": "-", "runs": 0, "laps": 0, "compounds": "-"}
    cells = cell_rates(m)
    return {
        "sessions": "+".join(sorted(m["session"].unique())),
        "runs": int(m["run_id"].nunique()),
        "laps": int(len(m)),
        "compounds": ",".join(sorted(cells["C"])) if not cells.empty else "-",
    }


def main() -> None:
    laps = pd.read_parquet(PROCESSED / "laps.parquet")
    race = prepare(laps, "race")

    # Sanity: the "current" variant must reproduce the shipping pipeline. If it
    # does not, every comparison below is against a straw man.
    shipped = prepare(laps, "practice")
    rebuilt = build(laps)
    same = len(shipped) == len(rebuilt)
    print(f"parity with design.prepare(): {'ok' if same else 'MISMATCH'} "
          f"({len(shipped)} vs {len(rebuilt)} laps)")
    if not same:
        print("  the sweep is not comparing like with like; fix build() first")

    rows, demo, tables = [], [], {}
    for name, kw in VARIANTS.items():
        frame = build(laps, **kw)
        stats, tbl = score(frame, race)
        tables[name] = tbl
        rows.append({"variant": name, "practice_laps": len(frame), **stats})
        demo.append({"variant": name, **demo_coverage(frame)})

    shared, n_shared = common_mae(tables)
    for r in rows:
        r["mae_common"] = shared.get(r["variant"])

    print("\n" + "=" * 78)
    print("TRANSFER ACCURACY -- practice to race, leave-one-event-out")
    print("Lower MAE is better. More laps that predict worse is worse.")
    print("=" * 78)
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n" + "=" * 78)
    print(f"WHAT {DEMO_EVENT.upper()} GETS -- the new circuit, the demo race")
    print("=" * 78)
    print(pd.DataFrame(demo).to_string(index=False))

    print(f"\nmae_common is scored over the {n_shared} cells EVERY variant can")
    print("answer. It is the only column in which these variants are comparable:")
    print("a variant that drops the hard cells wins the raw MAE while knowing less.")

    cur = next((r for r in rows if r["variant"] == "current"), None)
    scored = [r for r in rows if r.get("mae_common") is not None]
    if not (scored and cur and cur.get("mae_common") is not None):
        return

    raw_best = min(scored, key=lambda r: r["mae_common"])
    print("  lowest mae_common overall : "
          f"{raw_best['variant']} ({raw_best['mae_common']}) "
          f"over {raw_best['n_cells']} cells")
    if raw_best["n_cells"] < cur["n_cells"]:
        print("     ignored -- it answers fewer cells than we answer today.")
        print("     Predicting better by refusing the hard questions is not")
        print("     an improvement, it is a smaller product.")

    # The only candidates worth adopting: at least as much coverage as today.
    fair = [r for r in scored if r["n_cells"] >= cur["n_cells"]]
    best = min(fair, key=lambda r: r["mae_common"]) if fair else None
    print()
    if best is None or best["variant"] == "current":
        print("  VERDICT: current is still the best. Keep it.")
        return
    print(f"  VERDICT: adopt {best['variant']}")
    print(f"     mae_common  {cur['mae_common']} -> {best['mae_common']} "
          f"({best['mae_common'] - cur['mae_common']:+.4f})")
    print(f"     cells       {cur['n_cells']} -> {best['n_cells']}")
    d_cur = next(d for d in demo if d["variant"] == "current")
    d_new = next(d for d in demo if d["variant"] == best["variant"])
    print(f"     {DEMO_EVENT}: {d_cur['sessions']} / {d_cur['compounds']} "
          f"-> {d_new['sessions']} / {d_new['compounds']}")

if __name__ == "__main__":
    main()
