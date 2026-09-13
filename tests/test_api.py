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
from cleanair.config import PROCESSED  # noqa: E402

# Every test here drives the real app over the real dataset, which is not in
# git. Skipped rather than failed where it is absent (CI, a fresh clone), the
# same way the other data-backed tests are.
pytestmark = pytest.mark.skipif(
    not (PROCESSED / "laps.parquet").exists(), reason="needs the cached season"
)

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
    # Lap 20 on a six-lap-old set, NOT lap 34 on an eighteen-lap-old one.
    #
    # The original inputs were chosen against the global degradation rate,
    # which had Hungary's C4 at 0.029 s/lap. The per-circuit rate is 0.069 --
    # Hungary's circuit slope is +0.040 -- and on that a tyre eighteen laps old
    # is already due a stop, so green and safety car both answer "box now" and
    # the test could no longer see the effect it exists to check. A fresher
    # tyre restores the contrast it was written for.
    LAP, AGE, WINDOW = 20, 6, 3
    base = {"event": EVENT, "current_lap": LAP, "tyre_age": AGE, "compound": "C4"}
    green = client.post("/whatif", json=base).json()
    sc = client.post(
        "/whatif",
        json={**base, "safety_car": True, "safety_car_laps": WINDOW},
    ).json()

    assert sc["best_pit_lap"] != green["best_pit_lap"], "safety car changed nothing"
    assert sc["best_pit_lap"] < LAP + WINDOW, "should stop inside the window"
    assert green["best_pit_lap"] >= LAP + WINDOW, "no reason to rush under green"

    # Missing the window must cost something, or the urgency is not real.
    #
    # The threshold is 1s, not the 5s this test first asserted. That 5s was
    # calibrated against an INVENTED 0.45 fraction, which made missing the
    # window cost 12s. On the measured 0.84 it costs 3.35s. The urgency is real
    # and considerably milder than the folklore, which is the finding.
    missed = next(o for o in sc["options"] if o["pit_on_lap"] == LAP + WINDOW)
    assert missed["delta_s"] > 1.0
    # And staying out past the window must be worse than taking it.
    inside = [o for o in sc["options"] if o["laps_from_now"] < WINDOW]
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
    """A compound with a non-positive fitted rate cannot be priced, and saying
    so beats inventing a number.

    The event moved from Hungary to Italy. Hungary's C5 was non-positive only
    under the global fit; its circuit slope is +0.040, which lifts the same
    tyre to 0.051 s/lap and makes it perfectly usable. Italy's slope is -0.019
    and its C5 lands at -0.008, so this now pins the behaviour at a cell that
    is genuinely unpriceable rather than at one the model was getting wrong.
    """
    r = client.post(
        "/whatif",
        json={
            "event": "Italian Grand Prix",
            "current_lap": 30,
            "tyre_age": 10,
            "compound": "C5",
        },
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


# ---------------------------------------------------------------------------
# one screen, one set of controls, one answer
# ---------------------------------------------------------------------------


def test_whatif_honours_the_race_distance_it_is_given(client):
    """`/whatif` and `/strategy` sit on one screen driven by one set of
    controls. This endpoint ignored `race_laps` entirely, so shortening the
    race moved the plan above and left "pit now or later" optimising the old
    distance underneath it.
    """
    base = {"event": EVENT, "current_lap": 20, "tyre_age": 10, "compound": "C4"}
    default = client.post("/whatif", json=base).json()
    short = client.post("/whatif", json={**base, "race_laps": 45}).json()

    assert short["race_laps"] == 45
    assert default["race_laps"] != 45, "the fixture event should not already be 45 laps"
    assert [o["total_time"] for o in short["options"]] != [
        o["total_time"] for o in default["options"]
    ], "race distance changed nothing"


def test_whatif_honours_rate_overrides(client):
    """The degradation sliders drive the plan. They must drive this too, or a
    strategist exploring the edge of the confidence interval sees half the
    screen move."""
    base = {"event": EVENT, "current_lap": 20, "tyre_age": 10, "compound": "C4"}
    fitted = client.post("/whatif", json=base).json()
    steep = client.post("/whatif", json={**base, "rates": {"C4": 0.25}}).json()

    assert [o["delta_s"] for o in steep["options"]] != [
        o["delta_s"] for o in fitted["options"]
    ], "rate override changed nothing"
    # A tyre falling apart makes waiting expensive fast.
    assert steep["options"][-1]["delta_s"] > fitted["options"][-1]["delta_s"]


def test_whatif_honours_the_pace_step(client):
    base = {"event": EVENT, "current_lap": 20, "tyre_age": 10, "compound": "C4"}
    a = client.post("/whatif", json=base).json()
    b = client.post("/whatif", json={**base, "pace_step_s": 0.0}).json()
    assert [o["delta_s"] for o in a["options"]] != [o["delta_s"] for o in b["options"]]


def test_whatif_reports_a_window_not_just_a_lap(client):
    """"Best stop is lap 20" reads as a decision and usually is not one. The
    window is what a pit wall can actually act on."""
    r = client.post(
        "/whatif",
        json={"event": EVENT, "current_lap": 20, "tyre_age": 6, "compound": "C4"},
    ).json()
    assert r["window_from"] <= r["best_pit_lap"] <= r["window_to"]
    laps = {o["pit_on_lap"]: o["delta_s"] for o in r["options"]}
    for lap in range(r["window_from"], r["window_to"] + 1):
        assert laps[lap] <= r["window_tolerance_s"], f"lap {lap} is outside the tolerance"


def test_the_pit_window_is_contiguous(client):
    """A cheap lap on the far side of an expensive one is not somewhere a car
    can drift to, so the window must not jump over a gap."""
    r = client.post(
        "/whatif",
        json={"event": EVENT, "current_lap": 20, "tyre_age": 6, "compound": "C4"},
    ).json()
    laps = {o["pit_on_lap"]: o["delta_s"] for o in r["options"]}
    before, after = r["window_from"] - 1, r["window_to"] + 1
    if before in laps:
        assert laps[before] > r["window_tolerance_s"]
    if after in laps:
        assert laps[after] > r["window_tolerance_s"]


def test_a_tight_window_collapses_to_one_lap(client):
    """When the call really is sharp the window must say so, or it is just a
    wider way of saying nothing."""
    r = client.post(
        "/whatif",
        json={
            "event": EVENT,
            "current_lap": 20,
            "tyre_age": 10,
            "compound": "C4",
            "rates": {"C4": 0.3},
            "window_tolerance_s": 0.5,
        },
    ).json()
    assert r["window_from"] == r["window_to"] == r["best_pit_lap"]


def test_strategy_uses_the_circuit_rate_not_the_season_average(client):
    """The bug that made every event a one-stop.

    Hungary's circuit slope is +0.040 s/lap. If the API is reading the global
    fit, its C4 comes back at the season average and matches every other
    circuit's.
    """
    hungary = client.post("/strategy", json={"event": EVENT}).json()
    italy = client.post("/strategy", json={"event": "Italian Grand Prix"}).json()

    def rate(res, c):
        return next((x["rate"] for x in res["compounds"] if x["compound"] == c), None)

    shared = {x["compound"] for x in hungary["compounds"]} & {
        x["compound"] for x in italy["compounds"]
    }
    assert shared, "the two events share no nominated compound to compare"
    assert any(
        rate(hungary, c) != rate(italy, c) for c in shared
    ), "two circuits report identical degradation, which is the season average leaking through"


# ---------------------------------------------------------------------------
# the practice-session breakdown
# ---------------------------------------------------------------------------


def test_practice_sessions_reports_all_three(client):
    r = client.get("/practice-sessions", params={"event": EVENT}).json()
    assert [s["session"] for s in r["sessions"]] == ["FP1", "FP2", "FP3"]
    assert r["weights"]["FP2"] > r["weights"]["FP1"]


def test_practice_sessions_ships_the_evidence_for_its_weights(client):
    """A weight a strategist cannot interrogate is a weight they will not use.

    The evidence is the SCHEME COMPARISON, not per-session correlations. This
    test used to assert FP2 correlated better than FP1 and it was right to
    fail: dropping the warm-up lap repaired FP1 and reversed that ordering,
    while the shipped blend still predicted best. Correlations across sessions
    are not comparable -- they score different cells -- so the response now
    carries the like-for-like comparison instead.
    """
    ev = client.get("/practice-sessions", params={"event": EVENT}).json()["weight_evidence"]
    schemes = ev["schemes"]
    assert len(schemes) >= 3, "one scheme is not a comparison"
    # Every scheme must be scored over the same cells, or the ranking is noise.
    assert len({s["n_cells"] for s in schemes}) == 1
    best = min(schemes, key=lambda s: s["mae"])
    assert "shipped" in best["scheme"], (
        f"{best['scheme']!r} beats the shipped weighting; SESSION_SKILL is stale"
    )


def test_a_sprint_weekend_says_its_sessions_do_not_exist(client):
    """Three different nothings, and calling them all "no data" lies about two.

    Silverstone 2026 is a sprint weekend: one practice session, no FP2, no FP3.
    Reporting those as "not run yet" sends someone looking for a session that
    is never coming.
    """
    r = client.get("/practice-sessions", params={"event": "British Grand Prix"}).json()
    assert r["sprint_weekend"] is True
    by_code = {s["session"]: s for s in r["sessions"]}
    assert by_code["FP1"]["exists"] is True
    assert by_code["FP2"]["exists"] is False
    assert by_code["FP3"]["exists"] is False


def test_a_conventional_weekend_has_all_three_sessions(client):
    r = client.get("/practice-sessions", params={"event": EVENT}).json()
    assert r["sprint_weekend"] is False
    assert all(s["exists"] for s in r["sessions"])


def test_practice_sessions_carries_the_race_actual_where_it_has_run(client):
    """Friday against Sunday on one screen -- the post-race comparison the
    brief asks for."""
    r = client.get("/practice-sessions", params={"event": EVENT}).json()
    assert r["race_actual"], "a raced event should report what the race measured"
    assert all("rate" in a and "compound" in a for a in r["race_actual"])


def test_practice_sessions_thin_cells_are_flagged_not_hidden(client):
    """Two runs of a soft carry a standard error wider than any rate on the
    calendar. Worth showing; not worth trusting. Only the flag says which."""
    r = client.get("/practice-sessions", params={"event": EVENT}).json()
    cells = [c for s in r["sessions"] for c in s["cells"]]
    assert cells, "the fixture event should have practice cells"
    assert all(c["thin"] == (c["n_runs"] < 3) for c in cells)


def test_practice_sessions_404s_for_an_event_with_no_practice(client):
    r = client.get("/practice-sessions", params={"event": "Nowhere Grand Prix"})
    assert r.status_code == 404


def test_forecast_answers_without_circuit_inputs(client):
    """A missing pit loss must not blank the tyre work.

    Madrid is a new circuit, so it has no pit loss and no race distance to
    carry forward and both have to be typed in. This used to 422 until they
    were, and the screen showed two empty boxes and NOTHING else -- no
    degradation rates, no session breakdown, no compound table -- on the one
    race the project exists to demo. None of that needs a pit lane.
    """
    r = client.post("/forecast", json={"event": "Spanish Grand Prix"})
    assert r.status_code == 200
    d = r.json()
    assert d["can_plan"] is False
    # Only the pit loss. The race DISTANCE is published -- the FIA fixes it
    # before anyone drives -- so asking for it was asking for a number that was
    # never in doubt. Having no history is not the same as not knowing.
    assert d["needs_inputs"] == ["pit_loss_s"]
    assert d["race_laps"] == 57
    assert d["pit_loss_s"] is None
    assert d["compounds"], "the compound table does not depend on the pit loss"
    # Best stint DOES need the pit loss, so it must stay blank rather than
    # report a confident zero.
    assert all(c["optimal_stint"] == 0 for c in d["compounds"])


def test_forecast_hints_a_quoted_pit_loss_and_names_its_provenance(client):
    """Offering a figure is fine. Offering it as if we measured it is not.

    Madrid's pit loss is quoted at 24s by Pirelli's own chief engineer, and at
    25s second-hand by a journalist -- a one-second disagreement between two
    simulations of the same pit lane. The hint carries who said it and what
    kind of number it is, and nothing prefills it.
    """
    d = client.post("/forecast", json={"event": "Spanish Grand Prix"}).json()
    hint = d["hints"]["pit_loss_s"]
    assert hint["seconds"] > 0
    assert hint["source"], "a quoted figure with no source is a rumour"
    assert "estimate" in hint["kind"] or "simulation" in hint["kind"]
    # It must NOT have been adopted.
    assert d["pit_loss_s"] is None
    assert d["can_plan"] is False


def test_forecast_plans_once_the_inputs_arrive(client):
    """And the same request with the two numbers produces a real plan."""
    d = client.post(
        "/forecast",
        json={"event": "Spanish Grand Prix", "pit_loss_s": 21.0, "race_laps": 56},
    ).json()
    assert d["can_plan"] is True
    assert not d.get("needs_inputs")
    assert d["recommended_stops"] >= 1
    assert any(c["optimal_stint"] > 0 for c in d["compounds"])


def test_forecast_marks_borrowed_compounds_as_stand_ins(client):
    """Madrid ran no hard on a race simulation in any of the three sessions.
    The rate is borrowed, and the response has to say so or the screen cannot."""
    d = client.post(
        "/forecast",
        json={"event": "Spanish Grand Prix", "pit_loss_s": 21.0, "race_laps": 56},
    ).json()
    by_c = {c["compound"]: c for c in d["compounds"]}
    assert by_c["C2"]["source"] == "stand-in"
    assert by_c["C2"]["n_runs"] == 0
    assert by_c["C3"]["source"] == "measured"
    assert by_c["C3"]["n_runs"] > 0
