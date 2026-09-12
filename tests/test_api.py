"""Tests for the strategy console's backend.

The point of the API is that answers are COMPUTED from the request rather than
read from a precomputed table. So most of these tests are of the form "change
one input, assert the answer moved in the direction physics says it should".
A backend that returned the same plan regardless of its inputs would satisfy a
schema check and be worthless.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cleanair.api import NEUTRALISED_PIT_LOSS_FRACTION, app  # noqa: E402

EVENT = "Hungarian Grand Prix"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_reports_a_loaded_model(client):
    h = client.get("/health").json()
    assert h["ok"] is True
    assert h["n_laps"] > 1000
    assert EVENT in h["events"]


def test_events_says_which_are_ready(client):
    rows = client.get("/events").json()
    assert rows
    hungary = next(r for r in rows if r["event"] == EVENT)
    assert hungary["ready"] is True
    assert hungary["race_laps"] > 40
    assert hungary["allocation"]


def test_a_strategy_is_returned_for_a_known_event(client):
    r = client.post("/strategy", json={"event": EVENT, "step": 3}).json()
    assert r["recommended_stops"] >= 1
    assert r["plans"]
    # The recommendation must actually be the cheapest plan returned.
    assert min(p["delta_s"] for p in r["plans"]) == 0.0
    best = next(p for p in r["plans"] if p["delta_s"] == 0.0)
    assert best["n_stops"] == r["recommended_stops"]
    # Stint lengths must add up to the race.
    assert sum(best["stint_lengths"]) == r["race_laps"]


def test_an_unknown_event_is_refused(client):
    r = client.post("/strategy", json={"event": "Nürburgring Grand Prix"})
    assert r.status_code == 404


def test_raising_the_pit_loss_never_increases_the_stop_count(client):
    """The one monotonicity this layer must have.

    A more expensive pit lane can only make stopping less attractive. If a
    higher pit loss ever bought MORE stops, the optimiser would be wrong in a
    way no amount of interface polish would cover.
    """
    calls = []
    for pit in (16, 20, 24, 28, 34):
        r = client.post("/strategy", json={"event": EVENT, "pit_loss_s": pit, "step": 3}).json()
        calls.append((pit, r["recommended_stops"]))
    stops = [s for _, s in calls]
    assert stops == sorted(stops, reverse=True), calls


def test_the_call_flips_where_the_crossover_says_it_will(client):
    """Two independent calculations that have to agree.

    ``crossover`` solves for the pit loss at which the stop counts tie.
    Enumeration finds the best plan at a given pit loss. If the flip happened
    somewhere other than the reported crossover, one of them would be lying and
    the sensitivity panel would be decoration.
    """
    base = client.post("/strategy", json={"event": EVENT, "step": 3}).json()
    x = base["crossover_pit_loss_s"]
    assert x is not None, "Hungary has a crossover in range; the fixture assumes it"

    below = client.post(
        "/strategy", json={"event": EVENT, "pit_loss_s": x - 1.5, "step": 3}
    ).json()
    above = client.post(
        "/strategy", json={"event": EVENT, "pit_loss_s": x + 1.5, "step": 3}
    ).json()
    assert below["recommended_stops"] != above["recommended_stops"]
    assert below["recommended_stops"] > above["recommended_stops"]


def test_a_safety_car_makes_the_stop_cheaper(client):
    green = client.post("/strategy", json={"event": EVENT, "step": 3}).json()
    sc = client.post("/strategy", json={"event": EVENT, "safety_car": True, "step": 3}).json()
    assert sc["pit_loss_s"] < green["pit_loss_s"]
    assert sc["pit_loss_s"] == pytest.approx(
        green["pit_loss_s"] * NEUTRALISED_PIT_LOSS_FRACTION, abs=0.05
    )
    assert sc["safety_car_fraction"] == NEUTRALISED_PIT_LOSS_FRACTION
    # And it must be surfaced, not folded in silently.
    assert green["safety_car_fraction"] is None
    # The provenance travels with the answer: stop counts behind the fraction.
    assert sc["pit_loss_by_status"]["green"]["n_stops"] > 100
    assert sc["pit_loss_by_status"]["safety_car"]["usable"] is False


def test_the_neutralised_fraction_can_be_overridden(client):
    """Monaco queues under a safety car, so a caller must be able to disagree
    with the measured VSC default rather than being stuck with it."""
    default = client.post(
        "/strategy", json={"event": EVENT, "safety_car": True, "step": 3}
    ).json()
    dearer = client.post(
        "/strategy",
        json={"event": EVENT, "safety_car": True, "neutralised_fraction": 1.4, "step": 3},
    ).json()
    assert dearer["pit_loss_s"] > default["pit_loss_s"]
    assert dearer["safety_car_fraction"] == 1.4


def test_the_measured_green_reference_agrees_with_the_library(client):
    """A cross-check on the whole measurement.

    PIT_LOSS_BY_STATUS was measured against the non-pitting field; the
    library's own estimate uses each driver's green median. Two different
    constructions landing within a second of each other is evidence both are
    measuring a pit stop rather than an artefact.
    """
    from cleanair.api import PIT_LOSS_BY_STATUS

    r = client.post("/strategy", json={"event": EVENT, "step": 3}).json()
    assert abs(PIT_LOSS_BY_STATUS["green"]["median_s"] - r["pit_loss_measured_s"]) < 1.5


def test_overriding_a_rate_changes_the_answer(client):
    """The control that asks "what if the model is wrong"."""
    base = client.post("/strategy", json={"event": EVENT, "step": 3}).json()
    c3 = next(c for c in base["compounds"] if c["compound"] == "C3")
    assert c3["overridden"] is False

    # Triple the hard tyre's degradation: its best stint must shorten.
    worse = client.post(
        "/strategy",
        json={"event": EVENT, "rates": {"C3": c3["rate"] * 3}, "step": 3},
    ).json()
    w3 = next(c for c in worse["compounds"] if c["compound"] == "C3")
    assert w3["overridden"] is True
    assert w3["optimal_stint"] < c3["optimal_stint"]
    # The fitted interval is still reported, so the UI can show how far outside
    # its own model the caller has gone.
    assert w3["rate_lo"] == c3["rate_lo"]


def test_a_tyre_that_does_not_wear_is_excluded(client):
    """An optimiser handed a tyre that never wears runs it to the flag.

    C5 is revived to a positive rate in the same call, because Hungary only has
    C3 and C4 usable on the real fit -- knocking out C3 alone leaves one tyre
    and the request is refused for having no legal plan, which is a different
    behaviour tested separately.
    """
    r = client.post(
        "/strategy",
        json={"event": EVENT, "rates": {"C3": -0.01, "C5": 0.05}, "step": 3},
    ).json()
    c3 = next(c for c in r["compounds"] if c["compound"] == "C3")
    assert c3["excluded"] is True
    assert c3["optimal_stint"] == 0
    # And it must not appear in any plan the optimiser returns.
    assert all("C3" not in p["compounds"] for p in r["plans"])
    # The revived tyre is usable again, which proves the exclusion is driven by
    # the rate rather than by a hardcoded list of compounds.
    c5 = next(c for c in r["compounds"] if c["compound"] == "C5")
    assert c5["excluded"] is False
    assert c5["optimal_stint"] > 0


def test_fewer_than_two_usable_compounds_is_refused(client):
    """A dry race requires two compounds, so there is no legal plan."""
    r = client.post(
        "/strategy",
        json={"event": EVENT, "rates": {"C3": -0.01, "C4": -0.01}, "step": 3},
    )
    assert r.status_code == 422
    assert "two" in r.json()["detail"]


def test_a_coarse_step_agrees_on_the_stop_count(client):
    """What makes a live slider honest.

    The UI asks for step 3 while dragging because step 1 takes seconds. That is
    only acceptable if the coarse grid picks the same call, otherwise the answer
    would change when the user let go of the mouse.
    """
    exact = client.post("/strategy", json={"event": EVENT, "step": 1}).json()
    coarse = client.post("/strategy", json={"event": EVENT, "step": 3}).json()
    assert coarse["recommended_stops"] == exact["recommended_stops"]
    assert exact["approximate"] is False
    assert coarse["approximate"] is True


def test_whatif_prefers_a_lap_inside_the_safety_car_window(client):
    """The safety-car decision, and the bug this pins.

    The discount was first applied to every candidate lap, which models a race
    run entirely under safety car: it shifts every option by the same constant
    and cancels out of the comparison, so the answer was identical with and
    without a safety car. The cheap stop is a window that closes.
    """
    green = client.post(
        "/whatif",
        json={"event": EVENT, "current_lap": 34, "tyre_age": 18, "compound": "C4"},
    ).json()
    sc = client.post(
        "/whatif",
        json={
            "event": EVENT,
            "current_lap": 34,
            "tyre_age": 18,
            "compound": "C4",
            "safety_car": True,
            "safety_car_laps": 3,
        },
    ).json()

    assert sc["best_pit_lap"] != green["best_pit_lap"], "safety car changed nothing"
    assert sc["best_pit_lap"] < 34 + 3, "should stop inside the window"
    assert green["best_pit_lap"] >= 34 + 3, "no reason to rush under green"

    # Missing the window must cost something, or the urgency is not real.
    #
    # The threshold is 1s, not the 5s this test first asserted. That 5s was
    # calibrated against an INVENTED 0.45 fraction, which made missing the
    # window cost 12s. On the measured 0.84 it costs 3.35s. The urgency is real
    # and considerably milder than the folklore, which is the finding.
    missed = next(o for o in sc["options"] if o["pit_on_lap"] == 34 + 3)
    assert missed["delta_s"] > 1.0
    # And staying out past the window must be worse than taking it.
    inside = [o for o in sc["options"] if o["laps_from_now"] < 3]
    assert min(o["delta_s"] for o in inside) < missed["delta_s"]


def test_whatif_costs_are_relative_to_the_best_option(client):
    r = client.post(
        "/whatif",
        json={"event": EVENT, "current_lap": 30, "tyre_age": 14, "compound": "C4"},
    ).json()
    assert min(o["delta_s"] for o in r["options"]) == 0.0
    best = next(o for o in r["options"] if o["delta_s"] == 0.0)
    assert best["pit_on_lap"] == r["best_pit_lap"]


def test_whatif_refuses_a_compound_it_cannot_price(client):
    """C5 at Hungary has a non-positive fitted rate, so the cost of staying out
    on it is not something we can compute. Saying so beats inventing it."""
    r = client.post(
        "/whatif",
        json={"event": EVENT, "current_lap": 30, "tyre_age": 10, "compound": "C5"},
    )
    assert r.status_code == 422


def test_whatif_refuses_a_finished_race(client):
    r = client.post(
        "/whatif",
        json={"event": EVENT, "current_lap": 70, "tyre_age": 20, "compound": "C4"},
    )
    assert r.status_code == 422


def test_inputs_outside_physical_range_are_rejected_by_the_schema(client):
    assert client.post("/strategy", json={"event": EVENT, "pit_loss_s": 900}).status_code == 422
    assert client.post("/strategy", json={"event": EVENT, "step": 99}).status_code == 422
    assert (
        client.post(
            "/whatif", json={"event": EVENT, "current_lap": 0, "tyre_age": 5, "compound": "C4"}
        ).status_code
        == 422
    )
