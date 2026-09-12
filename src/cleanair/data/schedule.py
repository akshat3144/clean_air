"""The race calendar, discovered rather than hardcoded.

WHY THIS EXISTS

``config.CONVENTIONAL_2026`` was a hand-written list of seven event names, and
``COMPOUND_ALLOCATION_2026`` a hand-written table of nine. Every new race meant
editing Python and pushing. That is fine for an analysis and disqualifying for a
product: nobody ships a strategy tool that needs a deploy when the calendar
moves on.

The F1 API already publishes the whole calendar -- 23 rounds for 2026, with
per-session UTC timestamps, months ahead of time. So none of that needed to be
hardcoded. This module reads it.

WHAT STILL NEEDS A HUMAN

Exactly one thing: Pirelli's compound nomination. The timing feed carries only
HARD / MEDIUM / SOFT, which are relative to each weekend, and nothing in the
session or event metadata carries the C1-C5 mapping -- it is published in a
press release. So that lives in an editable store (see ``allocation.py``) and is
three dropdowns in the UI, not a constant in a source file.

OFFLINE

The schedule is cached to disk on every successful fetch. Challenge Day may have
no network, and a tool that cannot name the next race because the wifi is down
is not a tool. Reads fall back to the cached copy, then to the constants in
config, in that order, and say which one they used.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd

from ..config import CONVENTIONAL_2026, DATA, SEASON

log = logging.getLogger(__name__)

SCHEDULE_CACHE = DATA / "schedule"

#: Sessions we care about. Qualifying tells us nothing about degradation.
LONG_RUN_SESSIONS = ("FP1", "FP2", "FP3")
RACE_SESSION = "R"

#: FastF1 spells sessions out; we key on the short codes everywhere else.
_SHORT = {
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Qualifying": "Q",
    "Sprint": "S",
    "Sprint Qualifying": "SQ",
    "Sprint Shootout": "SS",
    "Race": "R",
}


@dataclass
class Session:
    """One session on the calendar."""

    code: str
    name: str
    #: UTC start. Naive datetimes from the API are treated as UTC, which is what
    #: the ``DateUtc`` columns are.
    starts_utc: datetime

    def has_run(self, now: datetime | None = None) -> bool:
        """Has this session finished?

        Judged from its START plus a pad, because the API publishes start times
        and not end times. Two hours covers a practice session and a race with a
        red flag; being late is harmless here since the poller simply tries
        again on its next tick.
        """
        now = now or datetime.now(timezone.utc)
        return (now - self.starts_utc).total_seconds() > 2 * 3600


@dataclass
class Round:
    """One event on the calendar."""

    round_number: int
    event: str
    country: str
    location: str
    date_utc: datetime
    #: "conventional" or "sprint_qualifying". Sprint weekends have no FP2 and
    #: therefore no race-simulation long runs, which is why they are excluded
    #: from the degradation dataset rather than merely absent from it.
    format: str
    sessions: list[Session] = field(default_factory=list)

    @property
    def is_conventional(self) -> bool:
        return self.format == "conventional"

    def session(self, code: str) -> Session | None:
        return next((s for s in self.sessions if s.code == code), None)

    def long_run_sessions_run(self, now: datetime | None = None) -> list[str]:
        """Which practice sessions have finished. The forecastable input."""
        return [
            s.code
            for s in self.sessions
            if s.code in LONG_RUN_SESSIONS and s.has_run(now)
        ]

    def race_has_run(self, now: datetime | None = None) -> bool:
        r = self.session(RACE_SESSION)
        return bool(r and r.has_run(now))

    @property
    def cacheable_sessions(self) -> tuple[str, ...]:
        """Sessions worth pulling for this weekend's format.

        A sprint weekend is FP1 + Sprint Qualifying on Friday, Sprint +
        Qualifying on Saturday, and a FULL GRAND PRIX on Sunday. It has no FP2
        or FP3, and its FP1 is sprint preparation rather than race simulation
        -- measured across the cached 2025 sprint weekends, FP1 yields 34 runs
        at a median of 6 laps, which the practice filters reject anyway.

        But its RACE is a race like any other: 198 long runs at a median of 20
        laps across those same four weekends, against 17 for conventional
        races. Excluding it was costing us five 2026 events.
        """
        return (*LONG_RUN_SESSIONS, RACE_SESSION) if self.is_conventional else (RACE_SESSION,)

    def sessions_to_pull(self, now: datetime | None = None) -> list[str]:
        """The subset of ``cacheable_sessions`` that has actually finished.

        Asking for a session that has not run makes the cache script record a
        failure, which writes ``complete: false``, which makes the completeness
        guard refuse the whole event -- including data that arrived perfectly
        well.
        """
        return [c for c in self.cacheable_sessions if (s := self.session(c)) and s.has_run(now)]


def _parse(sched: pd.DataFrame) -> list[Round]:
    rounds = []
    for _, r in sched.iterrows():
        sessions = []
        for i in range(1, 6):
            name = r.get(f"Session{i}")
            when = r.get(f"Session{i}DateUtc")
            if not isinstance(name, str) or pd.isna(when):
                continue
            ts = pd.Timestamp(when)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            sessions.append(
                Session(code=_SHORT.get(name, name), name=name, starts_utc=ts.to_pydatetime())
            )
        date = pd.Timestamp(r["EventDate"])
        date = date.tz_localize("UTC") if date.tzinfo is None else date.tz_convert("UTC")
        rounds.append(
            Round(
                round_number=int(r["RoundNumber"]),
                event=str(r["EventName"]),
                country=str(r.get("Country", "")),
                location=str(r.get("Location", "")),
                date_utc=date.to_pydatetime(),
                format=str(r.get("EventFormat", "conventional")),
                sessions=sessions,
            )
        )
    return rounds


def _to_disk(season: int, rounds: list[Round]) -> None:
    SCHEDULE_CACHE.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "round_number": r.round_number,
            "event": r.event,
            "country": r.country,
            "location": r.location,
            "date_utc": r.date_utc.isoformat(),
            "format": r.format,
            "sessions": [
                {"code": s.code, "name": s.name, "starts_utc": s.starts_utc.isoformat()}
                for s in r.sessions
            ],
        }
        for r in rounds
    ]
    (SCHEDULE_CACHE / f"{season}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _from_disk(season: int) -> list[Round] | None:
    path = SCHEDULE_CACHE / f"{season}.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Round(
            round_number=r["round_number"],
            event=r["event"],
            country=r["country"],
            location=r["location"],
            date_utc=datetime.fromisoformat(r["date_utc"]),
            format=r["format"],
            sessions=[
                Session(
                    code=s["code"],
                    name=s["name"],
                    starts_utc=datetime.fromisoformat(s["starts_utc"]),
                )
                for s in r["sessions"]
            ],
        )
        for r in raw
    ]


def _from_config(season: int) -> list[Round]:
    """Last resort: the hardcoded list this module exists to replace.

    Carries no dates, so nothing that depends on timing works -- but naming the
    events is better than an empty screen, and the caller is told the source.
    """
    return [
        Round(
            round_number=i + 1,
            event=name,
            country="",
            location="",
            date_utc=datetime(season, 1, 1, tzinfo=timezone.utc),
            format="conventional",
        )
        for i, name in enumerate(CONVENTIONAL_2026)
    ]


#: How long a cached calendar is trusted without asking the API again.
#: The calendar is stable for months, but session times do move -- and a cache
#: preferred unconditionally would be preferred FOREVER, which is what the
#: first version of this function did. Committed to the repo, that meant a
#: schedule frozen at whatever it looked like the day it was written.
CACHE_TTL_SECONDS = 12 * 3600


def _cache_age(season: int) -> float | None:
    path = SCHEDULE_CACHE / f"{season}.json"
    if not path.exists():
        return None
    return datetime.now(timezone.utc).timestamp() - path.stat().st_mtime


@lru_cache(maxsize=4)
def load(season: int = SEASON, refresh: bool = False) -> tuple[list[Round], str]:
    """The season's calendar, and where it came from.

    Returns (rounds, source) with source one of "api", "cache", "config".
    Never raises: a strategy tool that cannot name the next race because the
    network is down has failed at its first job.

    Order is fresh-cache, then API, then stale-cache, then constants. The stale
    fallback is deliberate -- an out-of-date calendar beats no calendar, and the
    caller is told which one it got.
    """
    age = _cache_age(season)
    if not refresh and age is not None and age < CACHE_TTL_SECONDS:
        cached = _from_disk(season)
        if cached:
            return cached, "cache"

    try:
        import fastf1

        from .cache import enable_cache

        enable_cache()
        sched = fastf1.get_event_schedule(season, include_testing=False)
        rounds = _parse(sched)
        if rounds:
            _to_disk(season, rounds)
            return rounds, "api"
    except Exception as exc:  # noqa: BLE001 -- offline is a normal state here
        log.warning("schedule fetch failed (%s); falling back", type(exc).__name__)

    cached = _from_disk(season)
    if cached:
        return cached, "cache"
    return _from_config(season), "config"


def rounds(season: int = SEASON) -> list[Round]:
    return load(season)[0]


def race_events(season: int = SEASON) -> list[str]:
    """Every event with a Grand Prix, whatever the weekend format.

    Use this for anything derived from RACE data -- degradation, pit loss,
    strategy. Use ``event_names`` only for practice-derived work, which
    genuinely needs an FP2.
    """
    return [r.event for r in rounds(season)]


def raced_events(season: int = SEASON, now: datetime | None = None) -> list[str]:
    """Events whose Grand Prix has actually finished.

    ``race_events`` lists every round on the calendar, most of which have not
    happened. Anything that loads a race session must use this instead, or it
    spends API calls failing on the future -- which is how a pull hit the
    500/h cap and wrote `complete: false` across a good season.
    """
    return [r.event for r in rounds(season) if r.race_has_run(now)]


def conventional(season: int = SEASON) -> list[Round]:
    """Rounds with an FP2, and therefore with race-simulation long runs."""
    return [r for r in rounds(season) if r.is_conventional]


def event_names(season: int = SEASON) -> list[str]:
    """Replaces ``config.CONVENTIONAL_2026`` as the source of truth."""
    return [r.event for r in conventional(season)]


def find(event: str, season: int = SEASON) -> Round | None:
    return next((r for r in rounds(season) if r.event == event), None)


def next_rounds(
    season: int = SEASON, now: datetime | None = None, limit: int = 3
) -> list[Round]:
    """Rounds whose race has not yet run, soonest first.

    This is what the console's front page is about: the race you are actually
    preparing for. Note a round counts as upcoming while its practice sessions
    have already happened -- which is the whole point, because that practice is
    the input to the forecast.
    """
    now = now or datetime.now(timezone.utc)
    future = [r for r in rounds(season) if r.is_conventional and not r.race_has_run(now)]
    return sorted(future, key=lambda r: r.date_utc)[:limit]


def completed(season: int = SEASON, now: datetime | None = None) -> list[Round]:
    now = now or datetime.now(timezone.utc)
    return [r for r in rounds(season) if r.is_conventional and r.race_has_run(now)]


def pending_sessions(
    season: int = SEASON, now: datetime | None = None
) -> list[tuple[Round, str]]:
    """Sessions that have finished, in calendar order.

    The poller diffs this against what is on disk. Deliberately returns
    everything rather than only recent items: the job is idempotent and decides
    what to do by comparing against the cache, so a missed tick self-heals on
    the next one instead of leaving a permanent hole.
    """
    now = now or datetime.now(timezone.utc)
    out: list[tuple[Round, str]] = []
    for r in sorted(rounds(season), key=lambda x: x.date_utc):
        # Every format, not just conventional: `cacheable_sessions` already
        # knows a sprint weekend offers only its race.
        for code in r.sessions_to_pull(now):
            out.append((r, code))
    return out
