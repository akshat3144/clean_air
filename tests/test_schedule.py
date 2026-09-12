"""Tests for calendar discovery and the allocation store.

These two exist to remove a code push from the act of adding a race. The tests
therefore care about the FALLBACK behaviour as much as the happy path: a
strategy tool that cannot name the next race because the network is down has
failed at its first job, and a demo laptop with no wifi is a normal Saturday.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cleanair.data import allocation as alloc
from cleanair.data import schedule as sched

UTC = timezone.utc


def _round(event="Test Grand Prix", when=None, fmt="conventional", sessions=None):
    when = when or datetime(2026, 6, 1, tzinfo=UTC)
    return sched.Round(
        round_number=1,
        event=event,
        country="Testland",
        location="Testville",
        date_utc=when,
        format=fmt,
        sessions=sessions or [],
    )


def _session(code, offset_hours, base=None):
    base = base or datetime(2026, 6, 1, tzinfo=UTC)
    return sched.Session(code=code, name=code, starts_utc=base + timedelta(hours=offset_hours))


# ---------------------------------------------------------------------------
# session timing
# ---------------------------------------------------------------------------


def test_a_session_counts_as_run_only_after_it_could_have_finished():
    """The API publishes start times, not end times.

    Judging "has run" from the start alone would try to pull a race while it is
    on lap 3. The pad is deliberately generous: being late costs one poll
    interval, being early costs a wasted API call against a 500/hour cap.
    """
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    just_started = sched.Session("R", "Race", now - timedelta(minutes=30))
    long_over = sched.Session("R", "Race", now - timedelta(hours=5))

    assert not just_started.has_run(now)
    assert long_over.has_run(now)


def test_practice_that_has_run_is_reported_before_the_race():
    """The state that makes an upcoming race forecastable.

    Friday practice is finished and Sunday has not happened. That is not a
    half-broken record, it is the exact moment the product is for.
    """
    base = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    rnd = _round(
        when=datetime(2026, 9, 6, tzinfo=UTC),
        sessions=[
            _session("FP1", 0, base),
            _session("FP2", 4, base),
            _session("FP3", 24, base),
            _session("R", 51, base),
        ],
    )
    now = base + timedelta(hours=10)  # after FP2, before FP3

    assert rnd.long_run_sessions_run(now) == ["FP1", "FP2"]
    assert not rnd.race_has_run(now)


def test_sprint_weekends_are_excluded_from_the_conventional_list():
    """Sprint weekends have no FP2 and therefore no race-simulation long runs,
    which is why they are absent from the degradation dataset."""
    rounds = [_round("A"), _round("B", fmt="sprint_qualifying")]
    assert [r.event for r in rounds if r.is_conventional] == ["A"]


# ---------------------------------------------------------------------------
# offline behaviour
# ---------------------------------------------------------------------------


def test_the_schedule_falls_back_rather_than_raising(monkeypatch, tmp_path):
    """Offline must degrade, not fail.

    With the network gone and no cache, the hardcoded constants are still
    better than an empty screen -- and the caller is told which source it got,
    so a date-less fallback is never mistaken for the real calendar.
    """
    monkeypatch.setattr(sched, "SCHEDULE_CACHE", tmp_path / "nothing")

    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr("fastf1.get_event_schedule", boom, raising=False)
    sched.load.cache_clear()

    rounds, source = sched.load(2026, refresh=True)
    assert source == "config"
    assert rounds, "fallback produced no events at all"
    sched.load.cache_clear()


def test_a_cached_schedule_is_reused_without_the_network(monkeypatch, tmp_path):
    monkeypatch.setattr(sched, "SCHEDULE_CACHE", tmp_path)
    payload = [
        {
            "round_number": 1,
            "event": "Cached Grand Prix",
            "country": "C",
            "location": "L",
            "date_utc": datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
            "format": "conventional",
            "sessions": [],
        }
    ]
    (tmp_path / "2026.json").write_text(json.dumps(payload), encoding="utf-8")
    sched.load.cache_clear()

    rounds, source = sched.load(2026)
    assert source == "cache"
    assert rounds[0].event == "Cached Grand Prix"
    sched.load.cache_clear()


# ---------------------------------------------------------------------------
# allocation -- the one fact no API carries
# ---------------------------------------------------------------------------


def test_an_inverted_allocation_is_rejected():
    """HARD must be harder rubber than SOFT.

    A typo here does not fail loudly -- it surfaces three screens later as a
    backwards degradation ordering, which is the exact bug this project exists
    to avoid making.
    """
    a = alloc.Allocation("X", 2026, {"HARD": "C5", "MEDIUM": "C4", "SOFT": "C3"})
    with pytest.raises(ValueError, match="hardest to softest"):
        a.validate()


def test_duplicate_compounds_are_rejected():
    a = alloc.Allocation("X", 2026, {"HARD": "C3", "MEDIUM": "C3", "SOFT": "C5"})
    with pytest.raises(ValueError, match="distinct"):
        a.validate()


def test_a_missing_label_is_rejected():
    a = alloc.Allocation("X", 2026, {"HARD": "C3", "MEDIUM": "C4"})
    with pytest.raises(ValueError, match="missing"):
        a.validate()


def test_a_non_compound_is_rejected():
    a = alloc.Allocation("X", 2026, {"HARD": "C3", "MEDIUM": "C4", "SOFT": "C9"})
    with pytest.raises(ValueError, match="not compounds"):
        a.validate()


def test_a_valid_allocation_passes():
    alloc.Allocation("X", 2026, {"HARD": "C1", "MEDIUM": "C3", "SOFT": "C5"}).validate()


def test_an_unnominated_event_returns_empty_not_an_error():
    """A race on the calendar that Pirelli has not announced tyres for is a
    normal state. Callers branch on it; they should not have to catch it."""
    assert alloc.compounds_for("No Such Grand Prix") == {}


def test_the_store_round_trips_and_marks_user_edits(monkeypatch, tmp_path):
    """A typed number and a cited one are different kinds of claim, so the
    source is recorded rather than lost."""
    monkeypatch.setattr(alloc, "STORE", tmp_path / "allocation.json")

    seeded = alloc.get("Italian Grand Prix")
    assert seeded is not None
    assert seeded.source == "pirelli"

    alloc.set_allocation("Brand New Grand Prix", {"HARD": "C2", "MEDIUM": "C3", "SOFT": "C4"})
    back = alloc.get("Brand New Grand Prix")
    assert back is not None
    assert back.source == "user"
    assert back.compounds["MEDIUM"] == "C3"
    assert back.updated_at

    # Seeded events survive a write of an unrelated one.
    assert alloc.get("Italian Grand Prix") is not None


def test_unsetting_a_user_edit_restores_the_cited_value(monkeypatch, tmp_path):
    monkeypatch.setattr(alloc, "STORE", tmp_path / "allocation.json")
    original = alloc.compounds_for("Italian Grand Prix")

    alloc.set_allocation("Italian Grand Prix", {"HARD": "C1", "MEDIUM": "C2", "SOFT": "C3"})
    assert alloc.compounds_for("Italian Grand Prix")["HARD"] == "C1"

    alloc.unset("Italian Grand Prix")
    assert alloc.compounds_for("Italian Grand Prix") == original
    assert alloc.get("Italian Grand Prix").source == "pirelli"


def test_a_stale_cache_is_refreshed_rather_than_trusted_forever(monkeypatch, tmp_path):
    """The first version of load() preferred disk unconditionally.

    Committed to the repo, that froze the calendar at whatever it looked like
    the day the file was written -- a moved session time would never be seen
    again. Fresh cache wins, then the API, then a stale cache, then constants.
    """
    monkeypatch.setattr(sched, "SCHEDULE_CACHE", tmp_path)
    payload = [
        {
            "round_number": 1,
            "event": "Stale Grand Prix",
            "country": "",
            "location": "",
            "date_utc": datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
            "format": "conventional",
            "sessions": [],
        }
    ]
    path = tmp_path / "2026.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    # Age it well past the TTL.
    import os

    old = datetime.now(UTC).timestamp() - (sched.CACHE_TTL_SECONDS + 3600)
    os.utime(path, (old, old))

    called = {"n": 0}

    def fake_schedule(*a, **k):
        called["n"] += 1
        raise OSError("offline")

    monkeypatch.setattr("fastf1.get_event_schedule", fake_schedule, raising=False)
    sched.load.cache_clear()

    rounds, source = sched.load(2026)
    # It tried the API rather than silently serving the stale copy...
    assert called["n"] == 1
    # ...and still fell back to the stale copy rather than failing.
    assert source == "cache"
    assert rounds[0].event == "Stale Grand Prix"
    sched.load.cache_clear()


def test_a_typed_nomination_can_be_taken_back_out(monkeypatch, tmp_path):
    """Set existed without clear, which is the wrong asymmetry.

    A value typed into the app that cannot be removed reads as a fact from then
    on. Testing this project wrote a nomination for a race Pirelli had not
    announced, and only the `source` marker made it visible -- there was no way
    to undo it from the interface that created it.
    """
    monkeypatch.setattr(alloc, "STORE", tmp_path / "allocation.json")

    # A race with no cited value disappears entirely when cleared.
    alloc.set_allocation("Invented Grand Prix", {"HARD": "C1", "MEDIUM": "C2", "SOFT": "C3"})
    assert alloc.compounds_for("Invented Grand Prix")
    assert alloc.unset("Invented Grand Prix") is True
    assert alloc.compounds_for("Invented Grand Prix") == {}

    # A race that HAS a cited value reverts to it rather than vanishing.
    cited = alloc.compounds_for("Monaco Grand Prix")
    alloc.set_allocation("Monaco Grand Prix", {"HARD": "C1", "MEDIUM": "C2", "SOFT": "C3"})
    assert alloc.get("Monaco Grand Prix").source == "user"
    alloc.unset("Monaco Grand Prix")
    assert alloc.compounds_for("Monaco Grand Prix") == cited
    assert alloc.get("Monaco Grand Prix").source == "pirelli"

    # Clearing something that was never set is not an error to swallow.
    assert alloc.unset("Never Existed Grand Prix") is False
