"""Watches the calendar and pulls sessions as they happen.

WHY IN-PROCESS AND NOT A SEPARATE SERVICE

The usual reason to give a worker its own machine is that heavy compute would
starve the request handlers. Measured on this dataset, the recurring work is:

    read the schedule        ~0s      cached
    pull one new session     1-3 min  NETWORK-bound, almost no CPU
    refit the degradation    0.10s    trivial
    republish artifacts      ~0s      file writes

That is a network wait plus a tenth of a second of arithmetic. It does not need
its own box, and putting it in-process means one deploy and one thing to
explain. The genuinely expensive thing in this project -- the hierarchical MCMC
at roughly six minutes a race -- is offline work and is deliberately NOT here.

POLL AND RECONCILE, NOT CRON

Every tick asks a stateless question: which sessions have finished per the
schedule, and which of those are missing from disk? Then it pulls the oldest
missing one.

That is idempotent and self-healing. A missed tick, a reboot, a session delayed
two hours -- all fix themselves on the next pass, with no persisted job state
and no missed-window bugs.

THE RULE THAT MATTERS

The pull runs in a SUBPROCESS. ``fastf1`` is synchronous and a three-minute
download on the event loop would freeze every strategy request for three
minutes. The subprocess also means a segfault in a data library cannot take the
API down with it.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import PROCESSED, ROOT, SEASON
from .data import schedule as sched

log = logging.getLogger(__name__)

#: How often to reconcile. Practice sessions are an hour long and the race is
#: on Sunday; a quarter hour is far more often than the world changes, and it
#: costs one cached schedule read when there is nothing to do.
POLL_SECONDS = 15 * 60

#: The F1 API allows 500 calls an hour. We have been truncated by it three
#: times already -- it silently cut 2022, 2024 and 2025 mid-pull -- so a failed
#: pull backs off hard rather than retrying into the cap.
BACKOFF_SECONDS = 45 * 60

#: One pull at a time, and only from one process. A second uvicorn worker
#: scheduling the same job would race the first one writing the same parquet.
LOCK = PROCESSED / ".poller.lock"


@dataclass
class PollState:
    """What the poller has been doing. Surfaced at /poller."""

    enabled: bool = True
    running: bool = False
    last_tick: str | None = None
    last_pull: str | None = None
    last_error: str | None = None
    pulls: int = 0
    failures: int = 0
    #: Sessions known to have run but not yet on disk, newest question first.
    missing: list[str] = field(default_factory=list)
    schedule_source: str = "unknown"
    next_tick_seconds: int = POLL_SECONDS


STATE = PollState()


def _cached_sessions(season: int) -> set[tuple[str, str]]:
    """(event, session) pairs already represented in the season's parquet.

    SESSION-LEVEL, and that is the whole point.

    This used to return event names, and ``find_missing`` skipped any event it
    found there. That is correct exactly once -- the first time an event is
    seen. After FP1 lands, the event is "cached", so FP2, FP3 and the RACE are
    never pulled, and the weekend the product is actually for is the weekend it
    silently stops updating. Reconciling per session is what makes the loop
    idempotent in the way the docstring at the top of this file claims.
    """
    import pandas as pd

    name = "laps.parquet" if season == SEASON else f"laps_{season}.parquet"
    path = PROCESSED / name
    if not path.exists():
        return set()
    try:
        df = pd.read_parquet(path, columns=["event", "session"])
    except Exception:  # noqa: BLE001 -- a half-written parquet is a normal race
        return set()
    return {(str(e), str(c)) for e, c in df.drop_duplicates().itertuples(index=False)}


def find_missing(
    season: int = SEASON, now: datetime | None = None
) -> list[tuple[str, list[str]]]:
    """Events with finished sessions that are not in the dataset.

    Returns (event, sessions_missing). Event-level because the cache script
    pulls an event in one invocation, but the session list is what is actually
    missing, so a weekend already holding FP1 asks only for FP2 -- one network
    call, not four.
    """
    have = _cached_sessions(season)
    out: list[tuple[str, list[str]]] = []
    # Every round, not just conventional ones. A sprint weekend has no FP2 but
    # it still races on Sunday, and that race is as good as any other. The
    # format-aware `sessions_to_pull` returns practice + race for a
    # conventional weekend and the race alone for a sprint one.
    for rnd in sched.rounds(season):
        ran = rnd.sessions_to_pull(now)
        gap = [c for c in ran if (rnd.event, c) not in have]
        if not gap:
            continue
        out.append((rnd.event, gap))
    return out


def _pull(event: str, season: int, sessions: list[str]) -> tuple[bool, str]:
    """Cache one event, in a subprocess.

    ``sessions`` must list only sessions that have ALREADY RUN. Asking for a
    session that has not happened makes the cache script record a failure, which
    writes ``complete: false`` into the manifest, which makes the completeness
    guard refuse the whole event downstream. For an upcoming race that is
    exactly wrong: having Friday practice and no race is the normal, useful
    state, not a truncated pull.

    Returns (ok, detail). Never raises: the poller must survive a bad session.
    """
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "01_cache_sessions.py"),
        "--season",
        str(season),
        "--events",
        event,
        "--sessions",
        *sessions,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20 * 60,
        )
    except subprocess.TimeoutExpired:
        return False, "timed out after 20 minutes"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

    tail = (proc.stdout or "")[-400:]
    if proc.returncode != 0:
        return False, f"exit {proc.returncode}: {(proc.stderr or tail)[-300:]}"
    if "500 calls/h" in (proc.stdout or ""):
        return False, "hit the F1 API rate cap; backing off"
    return True, tail


#: Every stage whose output changes when a new 2026 session lands, in
#: dependency order. Measured end to end at about 90 seconds, comfortably
#: inside the fifteen-minute tick.
#:
#: Four were missing before, so a new race refreshed the strategy call while
#: calibration, power and the five-season management result silently stayed on
#: the previous race's numbers.
#:
#: Deliberately NOT here:
#:   11_circuits   reads only the 2022-2025 parquets, so a 2026 race cannot
#:                 change it -- and it costs 4.4 minutes. Run it from
#:                 run_pipeline.py when a new SEASON is added.
#:   10_pit_loss   writes no artifact; it is a console diagnostic.
#:   08_benchmark  scores against 2025 and does not move.
#:   06_strategy   superseded by 09_playbook, which covers every event.
REPUBLISH_STAGES = (
    "03_fit_model.py",       # degradation + ablation + meta
    "04_validate.py",        # calibration + power
    "05_transfer.py",        # practice -> race
    "07_management.py",      # the five-season result
    "09_playbook.py",        # the strategy call per event
    "02_publish_artifacts.py",
)


def _republish() -> tuple[bool, str]:
    """Refit and rewrite every artifact the app reads.

    The benchmark and the hierarchical model are not in this path: one needs a
    different season's data and the other is six minutes of MCMC, and neither
    belongs behind a fifteen-minute timer.
    """
    for script in REPUBLISH_STAGES:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15 * 60,
        )
        if proc.returncode != 0:
            return False, f"{script}: {(proc.stderr or '')[-300:]}"
    return True, f"refit and republished ({len(REPUBLISH_STAGES)} stages)"


async def tick(season: int = SEASON) -> None:
    """One reconcile pass."""
    STATE.last_tick = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _, STATE.schedule_source = sched.load(season)

    missing = await asyncio.to_thread(find_missing, season)
    STATE.missing = [f"{ev} ({'+'.join(ses)})" for ev, ses in missing]
    if not missing:
        STATE.next_tick_seconds = POLL_SECONDS
        return

    if LOCK.exists():
        log.info("poller: another pull holds the lock")
        return

    event, sessions = missing[0]
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(f"{event} {STATE.last_tick}", encoding="utf-8")
    STATE.running = True
    try:
        log.info("poller: pulling %s", event)
        ok, detail = await asyncio.to_thread(_pull, event, season, sessions)
        if not ok:
            STATE.failures += 1
            STATE.last_error = f"{event}: {detail}"
            # A rate-cap hit is the one failure worth waiting out rather than
            # retrying, because retrying is what causes it.
            STATE.next_tick_seconds = BACKOFF_SECONDS if "rate cap" in detail else POLL_SECONDS
            log.warning("poller: %s", STATE.last_error)
            return

        ok, detail = await asyncio.to_thread(_republish)
        if not ok:
            STATE.failures += 1
            STATE.last_error = f"republish after {event}: {detail}"
            log.warning("poller: %s", STATE.last_error)
            return

        STATE.pulls += 1
        STATE.last_pull = f"{event} at {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
        STATE.last_error = None
        STATE.next_tick_seconds = POLL_SECONDS
        log.info("poller: %s cached and republished", event)
    finally:
        STATE.running = False
        LOCK.unlink(missing_ok=True)


async def run(season: int = SEASON) -> None:
    """The loop. Started from the API's lifespan, cancelled on shutdown."""
    log.info("poller: started, every %ds", POLL_SECONDS)
    # A short first delay so startup is not competing with the initial fit.
    await asyncio.sleep(20)
    while True:
        if STATE.enabled:
            try:
                await tick(season)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- the loop must never die
                STATE.failures += 1
                STATE.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("poller: tick failed")
        await asyncio.sleep(STATE.next_tick_seconds)


def clear_stale_lock(max_age_seconds: int = 30 * 60) -> bool:
    """Drop a lock left behind by a process that died mid-pull."""
    if not LOCK.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - Path(LOCK).stat().st_mtime
    if age > max_age_seconds:
        LOCK.unlink(missing_ok=True)
        return True
    return False
