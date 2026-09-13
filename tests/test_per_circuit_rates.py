"""The strategy layer must use per-circuit rates, everywhere, consistently.

This is the bug that was live longest and showed the least. The API fitted
degradation without circuit effects and looked up the global rate, so every
one of the eleven events got the season average and the app recommended ONE
STOP AT ALL OF THEM. The offline playbook, fitted correctly, said two at four
of them. Same optimiser, same data, two different answers on the same screen.

The circuit slopes run from -0.081 s/lap at Suzuka to +0.082 at Barcelona --
a spread wider than the one separating C1 from C5. Dropping them is not a
rounding difference; it is the single largest term in the model.

Three places had a version of it:

    api.py            fitted without circuit_effects, read fit.rates (global)
    06_strategy.py    same, for the one event it is asked about
    09_playbook.py    optimised per-circuit but DISPLAYED global, so its own
                      compound table could not produce the plan beneath it
"""

from __future__ import annotations

import json

import pytest

from cleanair.artifacts.schema import Interval
from cleanair.config import ARTIFACTS, PROCESSED
from cleanair.models.mixed import Fit

PLAYBOOK = ARTIFACTS / "playbook.json"


def make_fit(**kw) -> Fit:
    """A Fit with two compounds and two circuits, one harsh and one kind."""
    base = dict(
        rates={"C3": Interval(0.05, 0.01, 0.09), "C4": Interval(0.03, -0.01, 0.07)},
        curvature={},
        offsets={},
        n_laps={"C3": 100, "C4": 100},
        n_runs={"C3": 10, "C4": 10},
        events={},
        context="race",
        quadratic=False,
        converged=True,
        n_obs=200,
        n_drivers=20,
        circuit_slope={"Harsh": 0.08, "Kind": -0.04},
    )
    base.update(kw)
    return Fit(**base)


# ---------------------------------------------------------------------------
# the Fit API itself
# ---------------------------------------------------------------------------


def test_rate_for_adds_the_circuit_slope():
    f = make_fit()
    assert f.rate_for("C3", "Harsh") == pytest.approx(0.13)
    assert f.rate_for("C3", "Kind") == pytest.approx(0.01)


def test_rate_for_falls_back_to_global_for_an_unknown_circuit():
    """A circuit we have never raced has no slope, and the global rate is the
    honest answer rather than an error."""
    assert make_fit().rate_for("C3", "Nowhere") == pytest.approx(0.05)


def test_interval_for_is_centred_on_rate_for():
    """The number a screen SHOWS has to be the number the optimiser USED.
    Displaying the global band beside a per-circuit rate is what made the
    playbook's compound table contradict its own plan."""
    f = make_fit()
    for ev in ("Harsh", "Kind", "Nowhere"):
        for c in ("C3", "C4"):
            assert f.interval_for(c, ev).mean == pytest.approx(f.rate_for(c, ev))


def test_interval_for_shifts_the_band_and_does_not_narrow_it():
    """The circuit term is a fitted mean shift. It moves the interval; it does
    not make the per-circuit slope better determined than the global one."""
    f = make_fit()
    g, h = f.rates["C3"], f.interval_for("C3", "Harsh")
    assert h.width == pytest.approx(g.width)
    assert h.lo == pytest.approx(g.lo + 0.08)
    assert h.hi == pytest.approx(g.hi + 0.08)


def test_interval_for_stays_ordered():
    """Interval.__post_init__ raises on an unordered band, so a sign error in
    the shift would surface here rather than as a 500 in the API."""
    f = make_fit()
    iv = f.interval_for("C4", "Kind")
    assert iv.lo <= iv.mean <= iv.hi


def test_a_fit_without_circuit_effects_is_identical_everywhere():
    """The failure mode, pinned. This is what the API was doing: a fit with no
    circuit slopes answers every track the same, and nothing in the response
    says so."""
    f = make_fit(circuit_slope={})
    assert f.rate_for("C3", "Harsh") == f.rate_for("C3", "Kind") == 0.05


def test_a_harsh_circuit_shortens_the_best_stint():
    """The consequence that reaches the pit wall. If this does not hold, the
    per-circuit term is not reaching the strategy layer."""
    from cleanair.strategy.optimise import optimal_stint

    f = make_fit()
    harsh = optimal_stint("C3", f.rate_for("C3", "Harsh"), 22.0)
    kind = optimal_stint("C3", f.rate_for("C3", "Kind"), 22.0)
    assert harsh < kind


# ---------------------------------------------------------------------------
# the API must agree with the published playbook
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not PLAYBOOK.exists() or not (PROCESSED / "laps.parquet").exists(),
    reason="needs the published playbook and the cached season",
)
def test_api_and_playbook_agree_on_every_event():
    """The end-to-end guard.

    Judges can open the live app and the offline fallback side by side. Two
    answers to the same question is the one failure with no recovery, and it
    is not enough for each to be internally consistent -- they have to match.
    """
    from fastapi.testclient import TestClient

    from cleanair.api import app

    book = json.loads(PLAYBOOK.read_text(encoding="utf-8"))
    client = TestClient(app)

    disagreements = []
    for event in book["events"]:
        r = client.post("/strategy", json={"event": event["event"]})
        if r.status_code != 200:
            disagreements.append(f"{event['event']}: API returned {r.status_code}")
            continue
        live = r.json()

        if live["recommended_stops"] != event["plans"][0]["n_stops"]:
            disagreements.append(
                f"{event['event']}: API says {live['recommended_stops']} stops, "
                f"playbook says {event['plans'][0]['n_stops']}"
            )

        offline = {c["compound"]: c for c in event["compounds"]}
        for c in live["compounds"]:
            if (o := offline.get(c["compound"])) is None:
                continue
            if abs(c["rate"] - o["rate"]["mean"]) > 1e-4:
                disagreements.append(
                    f"{event['event']} {c['compound']}: API rate {c['rate']}, "
                    f"playbook {o['rate']['mean']}"
                )
            if c["optimal_stint"] != o["optimal_stint"]:
                disagreements.append(
                    f"{event['event']} {c['compound']}: API stint {c['optimal_stint']}, "
                    f"playbook {o['optimal_stint']}"
                )

    assert not disagreements, "live app and offline playbook disagree:\n  " + "\n  ".join(
        disagreements
    )


@pytest.mark.skipif(not PLAYBOOK.exists(), reason="needs the published playbook")
def test_the_playbook_does_not_call_the_same_stop_count_everywhere():
    """A weak but load-bearing smoke test.

    Every circuit answering the same is exactly what the bug looked like from
    outside, and it looked plausible -- one stop IS the modal F1 strategy. The
    tell was that it never varied.
    """
    book = json.loads(PLAYBOOK.read_text(encoding="utf-8"))
    calls = {e["plans"][0]["n_stops"] for e in book["events"]}
    assert len(calls) > 1, (
        "every event has the same recommended stop count, which is what a "
        "dropped per-circuit term looks like"
    )


@pytest.mark.skipif(not PLAYBOOK.exists(), reason="needs the published playbook")
def test_playbook_compound_rates_vary_between_circuits():
    """The display half of the bug. Hungary and Australia both showed C3 at
    0.04403 s/lap while their fitted circuit slopes differ by 0.035."""
    book = json.loads(PLAYBOOK.read_text(encoding="utf-8"))
    seen: dict[str, set[float]] = {}
    for e in book["events"]:
        for c in e["compounds"]:
            seen.setdefault(c["compound"], set()).add(c["rate"]["mean"])
    varying = [c for c, vals in seen.items() if len(vals) > 1]
    assert varying, "no compound's displayed rate varies by circuit"
