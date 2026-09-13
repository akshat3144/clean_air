"""How much each practice session should count toward the race forecast.

A mentor put it plainly: you have FP1, FP2 and FP3, so summarise each and
weight the second most heavily. He was right, and the reason he is right is
not the reason usually given.

THE USUAL REASON, WHICH NO LONGER HOLDS
    Until 2021 a European weekend ran FP2 and the race both at 14:00 local.
    Same hour, same sun, same track temperature. "Use FP2" meant "use the
    session that looks like the race". The modern calendar broke that:
    Madrid 2026 runs FP1 at 13:30 local, FP2 at 17:00, and the race at 15:00,
    so by the clock FP1 is the closer match. Weighting on time of day alone
    would hand FP1 the top weight at most of the calendar.

THE REAL REASON, WHICH WE MEASURED
    Against the races that have actually run this season, we scored each
    session's measured degradation against the race's:

        FP2   11 cells   correlation 0.84   transfer factor 0.44
        FP1    9 cells   correlation 0.05   transfer factor -0.02
        FP3    1 cell    not enough to score

    FP1 carries almost no signal about race degradation. Part of that is
    thinness -- FP1 cells run 2 runs and 10-15 laps, against 4-7 runs and
    25-57 laps in FP2 -- and part of it is what the session is for. Teams
    change the car between FP1 runs, so a slope fitted across them is
    measuring setup work as much as tyre wear. Monaco's FP1 C3 cell reads
    -0.807 s/lap against a race value of 0.056.

    FP2 is where the setup is frozen and the heavy-fuel race simulations are
    run. That is why it transfers, and it is why its weight is highest here.

WHY FP1 AND FP3 ARE NOT ZERO
    The skill gap above would justify weights near zero, and we do not use
    them. Nine cells is not enough to retire a session on, and a weekend like
    Madrid -- a new circuit, one usable compound, 124 long-run laps in FP1 --
    cannot afford to discard evidence about the very track it is asked about.
    Halving is a deliberate shrink toward equal weighting: it respects the
    measured gap without betting the forecast on a small sample.

THE SPRINT
    A sprint weekend has no FP2. What it has instead is the Sprint: twenty
    cars running one set of tyres for eighteen laps at race pace, with
    nothing to hide and nowhere to stop. Scored the same way as the practice
    sessions, over the five sprint weekends that have raced this season:

        S     9 cells   correlation 0.65   median 58 laps per cell

    Level with FP2 on correlation, on thicker cells, and on a weekend where
    FP1 (0.29) is the only alternative it is not a close call. It carries
    FP2's weight. The sweep in ``scripts/12_session_skill.py`` also says
    FP1 should NOT be zeroed beside it: "sprint only" scores worse than the
    shipped blend, so the hour of practice still earns its half.

The weights are constants rather than a live fit, because fitting them from
nine cells would make the forecast lurch race to race. ``tests`` re-measures
the skill table and fails if FP2 ever stops being the best predictor, so the
choice stays checked rather than assumed.
"""

from __future__ import annotations

import logging

from . import schedule

log = logging.getLogger(__name__)

#: Weight per session, normalised so the best-transferring session is 1.0.
#: See the module docstring for the measurement behind these.
SESSION_WEIGHTS: dict[str, float] = {"FP1": 0.5, "FP2": 1.0, "FP3": 0.5, "S": 1.0}

#: Used for any session not named above, and for whole datasets that predate
#: the split. Equal weighting is what the model did before this module, so an
#: unrecognised session degrades to the old behaviour rather than to zero.
DEFAULT_WEIGHT = 1.0


def weight_for(session: str) -> float:
    """Weight for one session code."""
    return SESSION_WEIGHTS.get(str(session).upper(), DEFAULT_WEIGHT)


def weights() -> dict[str, float]:
    """The full weight table, copied so callers cannot edit the constant."""
    return dict(SESSION_WEIGHTS)


def hours_to_race(event: str, season: int | None = None) -> dict[str, float]:
    """Signed clock-hours from each practice session to the race start.

    Not used to weight anything. Reported on screen next to the weights
    because it is the first thing a strategist asks -- "was that session at
    race time?" -- and because at some circuits the answer is no, which is
    worth seeing rather than hiding. Negative is earlier in the day.
    """
    try:
        rnd = schedule.find(event, season) if season else schedule.find(event)
    except Exception as exc:  # noqa: BLE001 - a missing calendar is not fatal
        log.debug("no schedule for %s: %s", event, exc)
        return {}
    if rnd is None or (race := rnd.session("R")) is None:
        return {}

    out = {}
    for code in schedule.LONG_RUN_SESSIONS:
        if (s := rnd.session(code)) is None:
            continue
        ha = s.starts_utc.hour + s.starts_utc.minute / 60
        hb = race.starts_utc.hour + race.starts_utc.minute / 60
        d = (ha - hb) % 24
        out[code] = round(d - 24 if d > 12 else d, 2)
    return out
