"""Tests for the background poller.

This is the only code in the project that runs unattended and WRITES to the
dataset, which makes it the code most worth pinning. Two of the tests below
exist because the behaviour they describe was wrong first:

  - it asked for sessions that had not happened, which made the cache script
    record a failure, which set `complete: false` in the manifest, which made
    the completeness guard reject an event whose practice data was perfectly
    good. An upcoming race having Friday practice and no race is the normal
    state, not a truncated pull.

  - the cache script it drives replaced the parquet rather than merging, so
    pulling one event would have destroyed the other seven. That is fixed in
    01_cache_sessions.py; the test here is that the poller asks for one event
    at a time, which is what made the bug reachable.

`tick` is exercised through asyncio.run rather than a plugin, so this needs no
extra dependency.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from cleanair import poller
from cleanair.data import schedule as sched

UTC = timezone.utc
BASE = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """The poller keeps module-level state; tests must not inherit each other's."""
    monkeypatch.setattr(poller, "STATE", poller.PollState())
    monkeypatch.setattr(poller, "LOCK", tmp_path / ".poller.lock")
    yield


def _session(code: str, hours: float) -> sched.Session:
    return sched.Session(code=code, name=code, starts_utc=BASE + timedelta(hours=hours))


def _round(event: str, fmt: str = "conventional", sessions=None) -> sched.Round:
    return sched.Round(
        round_number=1,
        event=event,
        country="",
        location="",
        date_utc=BASE,
        format=fmt,
        sessions=sessions
        if sessions is not None
        else [_session("FP1", 0), _session("FP2", 4), _session("FP3", 24), _session("R", 51)],
    )


def _patch_calendar(monkeypatch, rounds):
    monkeypatch.setattr(sched, "rounds", lambda season=2026: rounds)


# ---------------------------------------------------------------------------
# find_missing -- the reconcile decision
# ---------------------------------------------------------------------------


def test_an_event_already_in_the_dataset_is_not_pulled_again(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: {"Italian Grand Prix"})
    assert poller.find_missing(2026, now=BASE + timedelta(hours=100)) == []


def test_an_event_whose_practice_has_not_run_is_not_pulled(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())
    # One hour in: FP1 has started but cannot have finished.
    assert poller.find_missing(2026, now=BASE + timedelta(hours=1)) == []


def test_it_never_asks_for_a_session_that_has_not_happened(monkeypatch):
    """The bug this pins.

    Asking for FP3 before it runs makes the cache script log a failure, which
    writes `complete: false`, which makes the completeness guard refuse the
    whole event -- including the FP1 and FP2 data that arrived perfectly well.
    """
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())

    # After FP2, before FP3.
    missing = poller.find_missing(2026, now=BASE + timedelta(hours=10))
    assert missing == [("Italian Grand Prix", ["FP1", "FP2"])]

    ran = missing[0][1]
    assert "FP3" not in ran, "asked for a session that had not run"
    assert "R" not in ran, "asked for a race that had not happened"


def test_the_race_joins_the_pull_once_it_has_run(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())
    missing = poller.find_missing(2026, now=BASE + timedelta(hours=100))
    assert missing == [("Italian Grand Prix", ["FP1", "FP2", "FP3", "R"])]


def test_a_sprint_weekend_is_pulled_for_its_race_only(monkeypatch):
    """The bug this pins.

    A sprint weekend is FP1 + Sprint Qualifying, then Sprint + Qualifying, then
    a FULL GRAND PRIX on Sunday. We used to skip the whole weekend because it
    has no FP2, which silently cost us five 2026 races -- about 361 long runs,
    nearly as many as the seven conventional weekends put together.

    Its FP1 is sprint prep (median 6 laps) and the practice filters reject it
    anyway, so the race is the only thing worth taking -- but it IS worth
    taking.
    """
    _patch_calendar(monkeypatch, [_round("Sprinty Grand Prix", fmt="sprint_qualifying")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())

    missing = poller.find_missing(2026, now=BASE + timedelta(hours=100))
    assert missing == [("Sprinty Grand Prix", ["R"])], missing

    # ...and nothing at all before its race has run.
    assert poller.find_missing(2026, now=BASE + timedelta(hours=10)) == []


def test_one_event_at_a_time(monkeypatch):
    """The cache script is invoked per event, and used to REPLACE the parquet
    rather than merge into it. Pulling many at once would have hidden that;
    pulling one at a time is what made it visible."""
    _patch_calendar(
        monkeypatch, [_round("Italian Grand Prix"), _round("Spanish Grand Prix")]
    )
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())

    pulled = []
    monkeypatch.setattr(
        poller, "_pull", lambda ev, se, ses: (pulled.append((ev, ses)), (True, "ok"))[1]
    )
    monkeypatch.setattr(poller, "_republish", lambda: (True, "ok"))

    asyncio.run(poller.tick(2026))
    assert len(pulled) == 1, f"pulled {len(pulled)} events in one tick"


# ---------------------------------------------------------------------------
# reading the dataset must never throw
# ---------------------------------------------------------------------------


def test_a_missing_dataset_reads_as_empty_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(poller, "PROCESSED", tmp_path)
    assert poller._cached_events(2026) == set()


def test_a_corrupt_parquet_reads_as_empty_not_an_error(monkeypatch, tmp_path):
    """A half-written parquet is a normal race with the writer, not a crash.

    The poller loop must survive it: returning an empty set means "we hold
    nothing", which at worst causes a redundant pull. Raising would kill the
    tick.
    """
    monkeypatch.setattr(poller, "PROCESSED", tmp_path)
    (tmp_path / "laps.parquet").write_bytes(b"this is not a parquet file")
    assert poller._cached_events(2026) == set()


# ---------------------------------------------------------------------------
# the lock -- one pull at a time
# ---------------------------------------------------------------------------


def test_a_held_lock_stops_a_second_pull(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())
    poller.LOCK.parent.mkdir(parents=True, exist_ok=True)
    poller.LOCK.write_text("someone else is pulling", encoding="utf-8")

    called = []
    monkeypatch.setattr(poller, "_pull", lambda *a: (called.append(1), (True, "ok"))[1])

    asyncio.run(poller.tick(2026))
    assert not called, "pulled while another pull held the lock"


def test_the_lock_is_released_even_when_the_pull_fails(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())
    monkeypatch.setattr(poller, "_pull", lambda *a: (False, "boom"))

    asyncio.run(poller.tick(2026))
    assert not poller.LOCK.exists(), "a failed pull left the lock behind forever"


def test_a_stale_lock_is_cleared_but_a_fresh_one_is_kept():
    poller.LOCK.parent.mkdir(parents=True, exist_ok=True)
    poller.LOCK.write_text("mid-pull", encoding="utf-8")

    assert poller.clear_stale_lock(max_age_seconds=3600) is False
    assert poller.LOCK.exists(), "cleared a lock that was still fresh"

    # A process that died mid-pull leaves this behind; nothing else frees it.
    assert poller.clear_stale_lock(max_age_seconds=-1) is True
    assert not poller.LOCK.exists()


def test_clearing_a_lock_that_does_not_exist_is_not_an_error():
    assert poller.clear_stale_lock() is False


# ---------------------------------------------------------------------------
# failure handling
# ---------------------------------------------------------------------------


def test_hitting_the_rate_cap_backs_off_far_longer_than_a_normal_failure(monkeypatch):
    """Retrying into the cap is what causes the cap.

    The F1 API allows 500 calls an hour and has already silently truncated
    three seasons of this project's data. A poller that retried on the normal
    interval would keep it truncated.
    """
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())

    monkeypatch.setattr(poller, "_pull", lambda *a: (False, "hit the F1 API rate cap; backing off"))
    asyncio.run(poller.tick(2026))
    assert poller.STATE.next_tick_seconds == poller.BACKOFF_SECONDS

    poller.STATE.next_tick_seconds = poller.POLL_SECONDS
    monkeypatch.setattr(poller, "_pull", lambda *a: (False, "some other problem"))
    asyncio.run(poller.tick(2026))
    assert poller.STATE.next_tick_seconds == poller.POLL_SECONDS

    assert poller.STATE.failures == 2
    assert poller.STATE.last_error


def test_a_failed_republish_is_recorded_rather_than_swallowed(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())
    monkeypatch.setattr(poller, "_pull", lambda *a: (True, "cached"))
    monkeypatch.setattr(poller, "_republish", lambda: (False, "03_fit_model.py exploded"))

    asyncio.run(poller.tick(2026))
    assert poller.STATE.failures == 1
    assert "exploded" in (poller.STATE.last_error or "")
    # The pull DID succeed, so it must not be counted as one.
    assert poller.STATE.pulls == 0


def test_a_clean_pass_records_the_pull_and_clears_the_error(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: set())
    monkeypatch.setattr(poller, "_pull", lambda *a: (True, "cached"))
    monkeypatch.setattr(poller, "_republish", lambda: (True, "republished"))
    poller.STATE.last_error = "something from before"

    asyncio.run(poller.tick(2026))
    assert poller.STATE.pulls == 1
    assert poller.STATE.last_error is None
    assert poller.STATE.running is False
    assert "Italian" in (poller.STATE.last_pull or "")


def test_nothing_missing_is_a_quiet_no_op(monkeypatch):
    _patch_calendar(monkeypatch, [_round("Italian Grand Prix")])
    monkeypatch.setattr(poller, "_cached_events", lambda s: {"Italian Grand Prix"})
    called = []
    monkeypatch.setattr(poller, "_pull", lambda *a: (called.append(1), (True, "x"))[1])

    asyncio.run(poller.tick(2026))
    assert not called
    assert poller.STATE.missing == []
    assert poller.STATE.failures == 0
    assert poller.STATE.last_tick, "a no-op tick should still record that it ran"
