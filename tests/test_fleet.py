"""Tests for the fleet transfer.

The interval-coverage test is the important one. It caught a real bug: without
clustering, our 95% intervals covered the truth 37% of the time. That same bug
was present in the F1 transfer code and is fixed there too.
"""

from __future__ import annotations

import numpy as np
import pytest

from cleanair.fleet import (
    FLEET_SCHEMA,
    FleetSchema,
    estimate_wear_rate,
    naive_wear_rate,
    synthetic_fleet,
)

TRUE = {"budget": -9e-5, "midrange": -6e-5, "premium": -4e-5}


def test_recovers_a_known_wear_rate():
    """A route-difficulty effect several times the wear signal must not leak
    into the estimate."""
    rates = {r.group: r for r in estimate_wear_rate(synthetic_fleet(), FLEET_SCHEMA)}
    for model, truth in TRUE.items():
        assert rates[model].rate == pytest.approx(truth, rel=0.25)


def test_ordering_is_recovered():
    r = {x.group: x.rate for x in estimate_wear_rate(synthetic_fleet(), FLEET_SCHEMA)}
    assert r["budget"] < r["midrange"] < r["premium"]


def test_intervals_cover_the_truth():
    """THE test. Without clustering by vehicle this sat at 37% instead of 95%,
    because 30 daily readings from one truck are not 30 independent facts."""
    hits = total = 0
    for seed in range(20):
        rates = {r.group: r for r in estimate_wear_rate(synthetic_fleet(seed=seed), FLEET_SCHEMA)}
        for model, truth in TRUE.items():
            hits += rates[model].lo <= truth <= rates[model].hi
            total += 1
    assert hits / total > 0.85, f"coverage {hits}/{total} -- intervals are too narrow"


def test_deconfounding_beats_the_odometer_method():
    """Regressing wear on odometer reading is how fleets actually decide, and it
    absorbs route difficulty into the wear estimate."""
    df = synthetic_fleet(seed=3)
    good = {r.group: r.rate for r in estimate_wear_rate(df, FLEET_SCHEMA)}
    naive = {r.group: r.rate for r in naive_wear_rate(df, FLEET_SCHEMA)}
    err_good = sum(abs(good[m] - t) for m, t in TRUE.items())
    err_naive = sum(abs(naive[m] - t) for m, t in TRUE.items())
    assert err_good < err_naive


def test_refuses_when_vehicles_share_an_age():
    """If every truck on a route replaces tyres on the same schedule there is
    nothing to compare -- the same condition that made the 2026 Belgian GP
    unidentifiable."""
    df = synthetic_fleet(seed=4)
    df["km_since_fitted"] = 10_000.0  # identical age everywhere
    rates = estimate_wear_rate(df, FLEET_SCHEMA)
    assert all(not r.identifiable for r in rates)
    assert all(np.isnan(r.rate) for r in rates)


def test_missing_columns_are_named():
    df = synthetic_fleet().drop(columns=["tread_depth_mm"])
    with pytest.raises(ValueError, match="tread_depth_mm"):
        estimate_wear_rate(df, FLEET_SCHEMA)


def test_cohorts_too_small_are_reported_clearly():
    df = synthetic_fleet(trucks_per_route=1)
    with pytest.raises(ValueError, match="no cohort has at least"):
        estimate_wear_rate(df, FLEET_SCHEMA)


def test_schema_is_domain_agnostic():
    """Nothing in the estimator knows about tyres. Rename every column and it
    still works -- that is what makes the transfer a real claim."""
    df = synthetic_fleet(seed=5).rename(
        columns={
            "tread_depth_mm": "efficiency_pct",
            "km_since_fitted": "hours_run",
            "route_id": "line_id",
            "tyre_model": "bearing_type",
            "unit_id": "machine_id",
        }
    )
    schema = FleetSchema(
        wear="efficiency_pct",
        age="hours_run",
        cohort=["line_id", "date"],
        group="bearing_type",
        unit="machine_id",
    )
    rates = {r.group: r for r in estimate_wear_rate(df, schema)}
    assert len(rates) == 3
    assert all(r.identifiable for r in rates.values())


def test_synthetic_fleet_has_the_confounding_it_claims_to():
    """The demo is only meaningful if the route effect really does dwarf the
    wear signal, so check rather than assume."""
    df = synthetic_fleet()
    route_spread = df.groupby("route_id")["tread_depth_mm"].mean().std()
    wear_over_20k = abs(TRUE["budget"]) * 20_000
    assert route_spread > wear_over_20k
