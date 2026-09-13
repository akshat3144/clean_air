"""The race-shape chart must be in finishing order.

It was not. The chart sorted on whoever reached the highest lap number, which
ties every car that goes the full distance, so the ALPHABETICAL tie-break
decided the order of everyone who finished. The Austrian Grand Prix drew its
eight finishers as ANT HAD HAM LEC NOR PIA RUS VER -- the alphabet -- with the
race winner seventh and four of twenty-one rows in the right place.

The fix is a `position` on every stint, read from the session classification.
These tests guard the data the chart sorts on; the sort itself lives in
web/src/RaceShapeView.tsx and is one comparator over this field.
"""

from __future__ import annotations

import json

import pytest

from cleanair.config import ARTIFACTS

PLAYBOOK = ARTIFACTS / "playbook.json"

pytestmark = pytest.mark.skipif(
    not PLAYBOOK.exists(), reason="needs the published playbook"
)


def events() -> list[dict]:
    pb = json.loads(PLAYBOOK.read_text(encoding="utf-8"))
    return pb["events"] + pb.get("unavailable", []) if isinstance(pb, dict) else pb


def test_every_car_carries_a_finishing_position():
    """No row may fall back to the old ordering.

    A missing position is not a crash -- the chart sorts it last -- but it is a
    silent return to alphabetical for that car, so it is worth failing on.
    """
    for ev in events():
        if not ev.get("stints"):
            continue
        missing = sorted({s["driver"] for s in ev["stints"] if s.get("position") is None})
        assert not missing, f"{ev['event']}: no classification for {missing}"


def test_positions_are_a_ranking_not_a_label():
    """One car per position, and somebody won.

    Catches the shape of failure where a join misses and every driver inherits
    the same row: a chart ordered on that looks sorted and is not.
    """
    for ev in events():
        if not ev.get("stints"):
            continue
        per_driver = {s["driver"]: s["position"] for s in ev["stints"]}
        positions = sorted(per_driver.values())
        assert len(set(positions)) == len(positions), f"{ev['event']}: duplicate positions"
        assert min(positions) == 1, f"{ev['event']}: nobody classified first"


def test_a_stints_position_does_not_change_mid_race():
    """Every stint of one car carries that car's single classification.

    The chart reads the position off the first stint it happens to hold. That
    is only sound while they all agree.
    """
    for ev in events():
        for driver in {s["driver"] for s in ev.get("stints", [])}:
            seen = {s["position"] for s in ev["stints"] if s["driver"] == driver}
            assert len(seen) == 1, f"{ev['event']} {driver}: positions {seen}"


def test_retirements_are_distinguishable_from_short_stints():
    """A bar ending on lap 12 needs to say which kind of lap 12 it was.

    Status is what separates "retired" from "pitted"; without it the two draw
    identically.
    """
    statuses = {
        s.get("status") for ev in events() for s in ev.get("stints", []) if s.get("status")
    }
    assert statuses, "no status reached the artifact at all"
    assert "Finished" in statuses
