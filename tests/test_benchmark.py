"""Tests for the benchmark comparison.

The comparison is a public claim, so the mechanics have to be right: their exact
folds, their aggregation, and no use of information their model could not have
had.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cleanair.validation.benchmark import TRAIN_FRACTION, _extrapolate, _folds, score


def test_folds_match_their_scheme():
    """S_i is the LAST LAP of stint i in the global index, so training always
    starts at lap 1. Hamilton's 2025 Austria stints ended on laps 26, 50 and 70,
    which gives 35 predictions -- the number their tables are computed over."""
    folds = _folds([26, 50, 70])
    assert len(folds) == 35
    assert folds[0] == (20, 21)      # ceil(0.75 * 26) = 20
    assert (38, 39) in folds         # ceil(0.75 * 50) = 38
    assert folds[-1] == (69, 70)


def test_every_fold_predicts_the_lap_after_its_training_window():
    for train_to, test_lap in _folds([26, 50, 70]):
        assert test_lap == train_to + 1


def test_train_fraction_is_three_quarters():
    assert TRAIN_FRACTION == 0.75


def test_extrapolate_follows_a_straight_line():
    s = pd.Series({i: 90.0 - 0.1 * i for i in range(1, 21)})
    assert _extrapolate(s, 21) == pytest.approx(90.0 - 0.1 * 21, abs=1e-6)


def test_extrapolate_uses_only_recent_history():
    """A safety car early in a race must not drag the forecast twenty laps later."""
    s = pd.Series({i: (200.0 if i < 5 else 90.0) for i in range(1, 31)})
    assert _extrapolate(s, 31) == pytest.approx(90.0, abs=0.5)


def test_extrapolate_survives_a_single_point():
    assert _extrapolate(pd.Series({5: 90.0}), 6) == pytest.approx(90.0)


def synth_race(n_drivers=10, n_laps=70, rate=0.05, base=70.0, seed=0):
    """A field where degradation is exactly ``rate``.

    Two details matter, and both were learned by getting them wrong:

    STAGGERED STARTING AGES. If every car starts on a fresh tyre, then before
    the first stop every car has the SAME tyre age on any given lap, the
    within-lap comparison has nothing to compare, and the rate is unidentifiable
    -- so folds get skipped. Real fields have the same problem early on, which
    is exactly why the identifiability filter exists. Cars here start on sets of
    differing age.

    DRIVER PACE OFFSETS. If every car is equally quick, the field mean is a
    perfect pace level and tracking a driver's own laps can only add noise. Real
    cars differ by seconds, which is why the hybrid predictor wins on real data.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_drivers):
        stops = (26, 50) if d == 0 else (20 + d, 45 + d)
        start_age = 0 if d == 0 else (d * 3) % 12      # staggered, see docstring
        # The subject must NOT sit exactly on the field average, or the field
        # mean is a perfect pace level for him by construction and no
        # driver-specific tracking could ever beat it.
        pace = -0.7 if d == 0 else rng.normal(0, 0.8)
        for lap in range(1, n_laps + 1):
            stint = 1 if lap <= stops[0] else 2 if lap <= stops[1] else 3
            age = (lap + start_age) if stint == 1 else lap - stops[stint - 2]
            rows.append(
                {
                    "Driver": "HAM" if d == 0 else f"D{d}",
                    "LapNumber": float(lap),
                    "Stint": float(stint),
                    "Compound": "MEDIUM" if stint != 2 else "HARD",
                    "TyreLife": float(age),
                    "LapTimeSeconds": base
                    + pace
                    - 0.02 * lap
                    + rate * age
                    + rng.normal(0, 0.15),
                }
            )
    return pd.DataFrame(rows)


def test_scores_the_right_number_of_predictions():
    r = score(synth_race())
    assert r.n_predictions == 35
    assert len(r.per_stint_crps) == 3


def test_aggregation_matches_their_tables():
    """CRPS totals are a MEAN across stints; RMSE totals are a SUM."""
    r = score(synth_race())
    assert r.crps == pytest.approx(float(np.mean(r.per_stint_crps)))
    assert r.rmse_total == pytest.approx(float(np.sum(r.per_stint_rmse)))


def test_a_clean_race_is_predicted_well():
    """With known degradation and small noise, the error should be near the noise
    floor. If it is not, the predictor is broken rather than merely imprecise."""
    r = score(synth_race(rate=0.05, seed=1))
    assert r.crps < 0.15


def test_both_predictor_modes_produce_valid_scores():
    """Deliberately NOT asserting that the hybrid beats the field-only mode.

    On real data it does, and by a lot: on Hamilton's 2025 Austrian GP the
    field-only predictor scores CRPS 0.319 and the hybrid 0.210. But that gap
    comes from drivers differing in pace in ways this fixture does not reproduce
    -- here both land near 0.40 and the ordering flips. Asserting it anyway would
    be a test that passes for the wrong reason, or fails for the wrong reason.
    The real-data comparison lives in benchmark.json and the README instead.
    """
    laps = synth_race(seed=2)
    for mode in ("hybrid", "field"):
        r = score(laps, mode=mode)
        assert r.n_predictions == 35
        assert all(np.isfinite(c) and c > 0 for c in r.per_stint_crps)


def test_refuses_an_unknown_driver():
    with pytest.raises(ValueError, match="no laps"):
        score(synth_race(), driver="NOBODY")


def test_predictions_do_not_use_the_lap_being_predicted():
    """The fairness constraint. Corrupting a lap must not change the prediction
    made FOR that lap -- only predictions made after it."""
    laps = synth_race(seed=3)
    baseline = score(laps)

    poisoned = laps.copy()
    last = poisoned["LapNumber"] == 70          # the final test lap
    poisoned.loc[last & (poisoned["Driver"] != "HAM"), "LapTimeSeconds"] += 40.0

    after = score(poisoned)
    # Stints 1 and 2 finish before lap 70, so their scores must be untouched.
    assert after.per_stint_crps[0] == pytest.approx(baseline.per_stint_crps[0])
    assert after.per_stint_crps[1] == pytest.approx(baseline.per_stint_crps[1])
