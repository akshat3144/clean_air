"""The strategy console's backend.

WHY THIS EXISTS

The web app used to read static JSON, so every screen it could show was one of
seven precomputed pictures. That is a slideshow. A strategist changes the
inputs -- the safety car is out, the pit lane is slower than we measured, the
tyre is going off faster than the model says -- and needs the answer to change
with them.

So the optimiser runs here, per request. It stays in Python because it already
exists here and is already tested; reimplementing it in TypeScript would mean
two copies of the same arithmetic that can disagree, and disagreeing on stage
is the one failure mode with no recovery.

WHAT IS COMPUTED WHEN

    fitting the degradation model   once, at startup      0.10s
    enumerating strategies          every request         0.03s - 2.1s
    the hierarchical MCMC model     never here            ~6 min a race

The fit is fast enough to redo per request and is still cached, because it is
the same answer every time and the cache makes the slow path obvious. The MCMC
model is offline work and has no business behind an HTTP request.

    enumerate step=1   exact. 50,583 allocations at Barcelona, the worst
                       case of the seven, in 2.1s; 0.34s at Australia
    enumerate step=3   same recommended stop count at all seven events,
                       0.03s - 0.15s

Those counts are allocations, not sequences. The enumerator used to emit every
ordering of each one -- 1,470,486 rows at Barcelona for the same 69,145 answers
-- which inflated the figure roughly 21x and, because the orderings tie exactly,
left the recommendation to be picked by whichever came first out of a set.

``step`` is therefore a request parameter rather than a constant. A UI dragging
a slider asks for 3 and gets an instant answer; when the drag stops it asks for
1 and gets the exact stint lengths. We checked that the coarse grid picks the
same stop count everywhere before relying on it, because a call that changed
when you let go of the mouse would be a bug an audience would see.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import warnings
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import poller
from .config import ARTIFACTS, PROCESSED, SEASON
from .data import allocation as alloc
from .data import schedule as sched
from .models.design import prepare
from .models.mixed import fit_degradation
from .strategy.optimise import best_per_stop_count, crossover, enumerate_plans, optimal_stint

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

log = logging.getLogger(__name__)

#: Why FP2 outweighs FP1 and FP3. Each session's measured practice degradation
#: scored against the race degradation of the same (event, compound) cell, over
#: the races run so far this season. Regenerate with scripts/12_session_skill.py.
SESSION_SKILL = {
    "FP1": {"n_cells": 9, "correlation": 0.05, "factor": -0.015, "mae": 0.0428},
    "FP2": {"n_cells": 11, "correlation": 0.84, "factor": 0.438, "mae": 0.0393},
    "FP3": {"n_cells": 1, "correlation": None, "factor": None, "mae": None},
}

C_ORDER = ("C1", "C2", "C3", "C4", "C5")

#: Assumed fresh-tyre pace gap between adjacent compounds, seconds. Assumed
#: rather than fitted, and the weakest input in the layer, so it is a request
#: parameter too -- a caller who disagrees can say so.
PACE_STEP_S = 0.6

#: What a stop costs under a neutralisation, as a fraction of the green-flag
#: pit loss. MEASURED, on the same construction as the green number: observed
#: in-lap plus out-lap against the non-pitting field on those same two laps.
#: See strategy.pitloss.loss_by_status and scripts/10_pit_loss_by_status.py.
#:
#:     green        163 stops   22.15s   (the library's own estimate: 22.3s)
#:     VSC           48 stops   18.66s   ratio 0.84
#:     safety car    23 stops   30.71s   ratio 1.39  <- NOT USABLE
#:
#: The first version of this file asserted 0.45 on the universal intuition that
#: a neutralised field makes a stop cheap. The data does not support it. The
#: 1.39 is not usable either, and the reason is sample rather than mechanism:
#: those 23 stops come from just two events, and the two disagree by 15 seconds
#: -- Monaco 35.4s from 13 stops, Japan 20.10s from 10. One of those is above
#: green and one below. There is no safety-car number here, only two circuits.
#:
#: A pit-lane queue is the obvious candidate explanation and it is NOT
#: established: the loss does not rise monotonically with cars pitting on the
#: same lap (2 cars 20.7s, 3 cars 36.0s, 6 cars 18.0s, 10 cars 38.6s), whereas
#: green is flat across queue length at 21.8-23.0s. Something differs; which
#: thing is not shown by 23 stops.
#:
#: So the default is the VSC number, the only neutralised category with enough
#: stops and more than two events behind it. It is a request parameter because
#: a caller at Monaco should be able to say otherwise.
#:
#: THE LIMITATION WORTH STATING OUT LOUD: teams pit under a safety car to gain
#: TRACK POSITION, and this optimiser minimises total time. It has no concept of
#: position, so it cannot represent the actual reason the decision is made. A
#: correct pit-loss fraction would still not make it a safety-car strategist.
NEUTRALISED_PIT_LOSS_FRACTION = 0.84

#: Measured green-flag reference the fraction above is relative to, and the
#: stop counts behind each number. Returned with any neutralised answer so the
#: provenance travels with the number instead of living only in this comment.
PIT_LOSS_BY_STATUS = {
    "green": {"median_s": 22.15, "n_stops": 163, "ratio": 1.0},
    "vsc": {"median_s": 18.66, "n_stops": 48, "ratio": 0.84},
    "safety_car": {"median_s": 30.71, "n_stops": 23, "ratio": 1.39, "usable": False},
}


# ---------------------------------------------------------------------------
# state, loaded once
# ---------------------------------------------------------------------------


@dataclass
class State:
    race: pd.DataFrame
    fit: object
    #: Measured green-flag pit loss per event, from the worker's artifact.
    pit_loss: dict[str, float]
    n_green_stops: dict[str, int]
    race_laps: dict[str, int]
    #: Every event in the dataset, from ANY session. Distinct from race_laps,
    #: which only knows events that have actually raced -- an upcoming race with
    #: Friday practice is in the dataset and has no race laps, and checking the
    #: wrong one reports "not pulled yet" for data we are already holding.
    events_in_dataset: set[str] = field(default_factory=set)
    #: Practice long runs, for forecasting a race that has not happened.
    practice: pd.DataFrame | None = None


@lru_cache(maxsize=1)
def _state() -> State:
    """Load once per process, lazily, and keep it.

    Deliberately a cache rather than a module global assigned in lifespan. The
    global version set itself back to None on shutdown, so a second client in
    the same process -- which is exactly what a test suite does -- tore the
    state out from under the first one and every later request answered 503.
    A cache has no teardown to get wrong, and lifespan just warms it so the
    0.10s fit is paid at boot instead of on somebody's first request.
    """
    return _load()


def _load() -> State:
    """Read the dataset, fit the model, and pick up the worker's pit losses.

    Pit loss is NOT measured here. Measuring it opens race sessions through
    FastF1, which is slow and wants the network -- exactly the work that
    belongs on the scheduled worker per docs/DEPLOYMENT.md. The API reads what
    the worker left in playbook.json.
    """
    import json

    laps = pd.read_parquet(PROCESSED / "laps.parquet")
    all_events = set(laps["event"].unique())
    race = prepare(laps, "race")
    # circuit_effects=True is not optional here, whatever the default says.
    # Without it `circuit_slope` is empty, `rate_for` silently returns the
    # global rate, and every circuit is handed the season average -- which is
    # how the live app came to recommend one stop at all eleven events while
    # the offline playbook said two at four of them.
    fit = fit_degradation(race, quadratic=False, context="race", circuit_effects=True)

    try:
        practice = prepare(laps, "practice")
    except Exception:  # noqa: BLE001 -- a dataset with no practice is still usable
        practice = None

    pit_loss: dict[str, float] = {}
    n_stops: dict[str, int] = {}
    pb = ARTIFACTS / "playbook.json"
    if pb.exists():
        for e in json.loads(pb.read_text(encoding="utf-8"))["events"]:
            pit_loss[e["event"]] = float(e["pit_loss_s"])
            n_stops[e["event"]] = int(e["n_green_stops"])
    else:
        log.warning("playbook.json missing; pit loss must be supplied per request")

    race_laps = {
        str(ev): int(g["LapNumber"].max()) for ev, g in race.groupby("event", sort=True)
    }
    return State(
        race=race,
        fit=fit,
        pit_loss=pit_loss,
        n_green_stops=n_stops,
        race_laps=race_laps,
        events_in_dataset=all_events,
        practice=practice,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    st = _state()
    log.info("loaded %d events, %d laps", len(st.race_laps), len(st.race))

    # The poller lives in this process. See cleanair/poller.py for why that is
    # the right call here rather than a separate service: the recurring work is
    # a network wait plus a tenth of a second of arithmetic.
    #
    # Off by default so a developer running the API does not silently start
    # pulling sessions; the deployment turns it on.
    task = None
    if os.environ.get("CLEANAIR_POLL", "").lower() in ("1", "true", "yes"):
        poller.clear_stale_lock()
        task = asyncio.create_task(poller.run(SEASON))
    else:
        poller.STATE.enabled = False
        log.info("poller disabled (set CLEANAIR_POLL=1 to enable)")

    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Clean Air",
    summary="Deconfounded tyre degradation, and the pit-stop decision that follows from it.",
    lifespan=lifespan,
)

# The React app is served from a different origin in every deployment shape --
# Vite on 5173 locally, Vercel in production. Origins are read from the
# environment rather than hardcoded so the deployed app does not need a rebuild
# to move.
_origins = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def state() -> State:
    try:
        return _state()
    except FileNotFoundError as exc:  # no dataset on disk yet
        raise HTTPException(503, f"dataset not built: {exc}") from exc


# ---------------------------------------------------------------------------
# request and response shapes
# ---------------------------------------------------------------------------


class StrategyRequest(BaseModel):
    event: str
    #: Override the measured pit loss. This is the control that matters: it is
    #: measured from a handful of green stops, so it has real error, and a
    #: caller sweeping it is asking "how wrong can the measurement be before
    #: the call changes".
    pit_loss_s: float | None = Field(default=None, ge=5.0, le=60.0)
    race_laps: int | None = Field(default=None, ge=5, le=100)
    #: Degradation per compound, s/lap, overriding the fit. Lets a caller ask
    #: what happens at the edges of the model's own confidence interval.
    rates: dict[str, float] | None = None
    pace_step_s: float = Field(default=PACE_STEP_S, ge=0.0, le=3.0)
    #: 1 is exact and can take seconds; 3 is instant and agrees on the stop
    #: count at every event we checked. Use 3 while dragging, 1 on release.
    step: int = Field(default=1, ge=1, le=5)
    #: Treat the next stop as taken under a neutralisation.
    safety_car: bool = False
    #: What a neutralised stop costs, as a fraction of the green pit loss.
    #: Defaults to the MEASURED VSC ratio. A caller at Monaco, where the pit
    #: lane queues under a safety car, should be able to override it.
    neutralised_fraction: float = Field(
        default=NEUTRALISED_PIT_LOSS_FRACTION, ge=0.1, le=2.0
    )


class PlanOut(BaseModel):
    n_stops: int
    compounds: list[str]
    stint_lengths: list[int]
    total_time: float
    delta_s: float


class CompoundOut(BaseModel):
    compound: str
    label: str | None
    rate: float
    rate_lo: float
    rate_hi: float
    optimal_stint: int
    excluded: bool
    #: True when the caller supplied this rate instead of the fitted one, so the
    #: UI can mark that the answer is no longer the model's own view.
    overridden: bool = False


class StrategyResponse(BaseModel):
    event: str
    race_laps: int
    pit_loss_s: float
    pit_loss_measured_s: float | None
    n_green_stops: int | None
    safety_car: bool
    #: The fraction applied when safety_car is set. Measured, not assumed.
    safety_car_fraction: float | None
    #: Stop counts and medians behind that fraction, so the provenance travels
    #: with the answer rather than living in a source comment.
    pit_loss_by_status: dict | None = None
    compounds: list[CompoundOut]
    plans: list[PlanOut]
    recommended_stops: int
    margin_s: float
    crossover_pit_loss_s: float | None
    n_plans_enumerated: int
    step: int
    #: True when step > 1, so the UI can say the stint lengths are approximate.
    approximate: bool
    compute_ms: int


class WhatIfRequest(BaseModel):
    event: str
    #: The lap you are on now.
    current_lap: int = Field(ge=1, le=100)
    #: Laps on the current set.
    tyre_age: int = Field(ge=0, le=60)
    compound: str
    pit_loss_s: float | None = Field(default=None, ge=5.0, le=60.0)
    #: The same three overrides ``/strategy`` takes, and for the same reason:
    #: both panels are driven by one set of controls on one screen. Without
    #: them this endpoint silently answered a different race -- the console
    #: shortened Hungary to 50 laps, the plan above updated, and "pit now or
    #: later" went on optimising 70 laps behind it.
    race_laps: int | None = Field(default=None, ge=5, le=100)
    rates: dict[str, float] | None = None
    pace_step_s: float = Field(default=PACE_STEP_S, ge=0.0, le=3.0)
    #: A safety car is out NOW.
    safety_car: bool = False
    #: How many more laps the reduced pit loss is available for.
    #:
    #: This field is the whole safety-car decision. Applying the reduced pit
    #: loss to every candidate lap -- which is what this did first -- models a
    #: race run entirely under safety car, shifts every option by the same
    #: constant, and cancels out of the comparison completely. The cheap stop
    #: is a window that closes, so only laps inside it get the discount.
    safety_car_laps: int = Field(default=3, ge=1, le=10)
    neutralised_fraction: float = Field(
        default=NEUTRALISED_PIT_LOSS_FRACTION, ge=0.1, le=2.0
    )
    #: How many laps ahead to evaluate staying out.
    horizon: int = Field(default=8, ge=1, le=25)
    step: int = Field(default=3, ge=1, le=5)
    #: Laps costing less than this than the best are reported as an equally
    #: good window rather than as losses. Not derived from the model -- it is
    #: an operational threshold, and the screen states it. Half a second is
    #: below the execution spread of the stop itself, so a difference smaller
    #: than this is not a call anybody can make on purpose.
    window_tolerance_s: float = Field(default=0.5, ge=0.0, le=5.0)


class WhatIfOption(BaseModel):
    pit_on_lap: int
    laps_from_now: int
    total_time: float
    delta_s: float
    plan: PlanOut | None


class WhatIfResponse(BaseModel):
    event: str
    current_lap: int
    tyre_age: int
    compound: str
    pit_loss_s: float
    #: Echoed so the screen can prove it answered the race the controls asked
    #: for, rather than the calendar's default.
    race_laps: int
    safety_car: bool
    best_pit_lap: int
    #: The contiguous run of laps around ``best_pit_lap`` that cost less than
    #: ``window_tolerance_s``. Equal to ``best_pit_lap`` twice when the call is
    #: genuinely sharp.
    window_from: int
    window_to: int
    window_tolerance_s: float
    options: list[WhatIfOption]
    compute_ms: int


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rates_for(st: State, event: str, overrides: dict[str, float] | None):
    """Fitted degradation for this weekend's nominated tyres, with overrides."""
    allocation = alloc.compounds_for(event)
    if not allocation:
        raise HTTPException(404, f"no compound allocation known for {event!r}")
    label_of = {c: lab for lab, c in allocation.items()}
    nominated = set(allocation.values())

    usable: dict[str, float] = {}
    out: list[CompoundOut] = []
    for c in [x for x in C_ORDER if x in nominated]:
        if c not in st.fit.rates:
            continue
        # PER-CIRCUIT, not the season average. Fitted circuit slopes run from
        # -0.081 s/lap at Suzuka to +0.082 at Barcelona, a spread wider than
        # the one separating C1 from C5. Optimising on the global rate
        # understates wear everywhere it matters and recommends the same stop
        # count at every track, which is exactly what it did.
        iv = st.fit.interval_for(c, event)
        overridden = bool(overrides and c in overrides)
        rate = float(overrides[c]) if overridden else float(iv.mean)
        # A tyre that does not wear will be run to the flag by any optimiser,
        # so a non-positive rate is excluded rather than optimised on.
        excluded = rate <= 0
        if not excluded:
            usable[c] = rate
        out.append(
            CompoundOut(
                compound=c,
                label=label_of.get(c),
                rate=round(rate, 5),
                rate_lo=round(float(iv.lo), 5),
                rate_hi=round(float(iv.hi), 5),
                optimal_stint=0,
                excluded=excluded,
                overridden=overridden,
            )
        )
    return usable, out


def _plan_out(p, top: float) -> PlanOut:
    return PlanOut(
        n_stops=p.n_stops,
        compounds=list(p.compounds),
        stint_lengths=[int(x) for x in p.stints],
        total_time=round(p.total_time, 2),
        delta_s=round(p.total_time - top, 2),
    )


@lru_cache(maxsize=512)
def _enumerate_cached(
    race_laps: int,
    rates_key: tuple[tuple[str, float], ...],
    offsets_key: tuple[tuple[str, float], ...],
    pit_loss: float,
    step: int,
):
    """Memoised enumeration.

    A slider sends the same value repeatedly as it settles, and the exact
    request on release is often one already computed during the drag. Keyed on
    everything that changes the answer, so a hit is genuinely the same problem.
    """
    return enumerate_plans(race_laps, dict(rates_key), dict(offsets_key), pit_loss, step=step)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    try:
        st = _state()
    except Exception as exc:  # report rather than 500 -- this is the probe
        return {"ok": False, "error": str(exc), "events": [], "n_laps": 0}
    return {
        "ok": True,
        "events": sorted(st.race_laps),
        "n_laps": int(len(st.race)),
        "pit_loss_known_for": sorted(st.pit_loss),
    }


@app.get("/events")
def events() -> list[dict]:
    """What the console can be pointed at, and what is known per event."""
    st = state()
    out = []
    for ev in sorted(st.race_laps):
        allocation = alloc.compounds_for(ev)
        out.append(
            {
                "event": ev,
                "race_laps": st.race_laps[ev],
                "pit_loss_s": st.pit_loss.get(ev),
                "n_green_stops": st.n_green_stops.get(ev),
                "allocation": allocation,
                "ready": bool(allocation) and ev in st.pit_loss,
            }
        )
    return out


@app.post("/strategy", response_model=StrategyResponse)
def strategy(req: StrategyRequest) -> StrategyResponse:
    """Enumerate every legal strategy for the inputs given and pick the best.

    Every number in the response is computed from the request. Nothing here is
    read from a precomputed answer.
    """
    import time

    t0 = time.perf_counter()
    st = state()

    if req.event not in st.race_laps:
        raise HTTPException(404, f"unknown event {req.event!r}")

    measured = st.pit_loss.get(req.event)
    base_pit = req.pit_loss_s if req.pit_loss_s is not None else measured
    if base_pit is None:
        raise HTTPException(
            422,
            f"no measured pit loss for {req.event!r}; supply pit_loss_s explicitly",
        )
    pit = base_pit * req.neutralised_fraction if req.safety_car else base_pit

    race_laps = req.race_laps or st.race_laps[req.event]
    usable, compounds = _rates_for(st, req.event, req.rates)
    if len(usable) < 2:
        raise HTTPException(
            422,
            "fewer than two usable compounds: a dry race needs two, so there is "
            "no legal plan to enumerate",
        )

    order = [c for c in C_ORDER if c in usable]
    offsets = {c: -req.pace_step_s * i for i, c in enumerate(order)}

    for c in compounds:
        if not c.excluded:
            c.optimal_stint = int(optimal_stint(c.compound, usable[c.compound], pit))

    plans_all = _enumerate_cached(
        race_laps,
        tuple(sorted(usable.items())),
        tuple(sorted(offsets.items())),
        round(pit, 4),
        req.step,
    )
    if not plans_all:
        raise HTTPException(422, "no legal strategy exists for these inputs")

    best = best_per_stop_count(plans_all)
    top = plans_all[0].total_time
    rec = plans_all[0]
    runner_up = next((p for p in plans_all if p.n_stops != rec.n_stops), None)
    margin = (runner_up.total_time - rec.total_time) if runner_up else 0.0
    x = crossover(plans_all)

    return StrategyResponse(
        event=req.event,
        race_laps=race_laps,
        pit_loss_s=round(pit, 2),
        pit_loss_measured_s=round(measured, 2) if measured is not None else None,
        n_green_stops=st.n_green_stops.get(req.event),
        safety_car=req.safety_car,
        safety_car_fraction=req.neutralised_fraction if req.safety_car else None,
        pit_loss_by_status=PIT_LOSS_BY_STATUS if req.safety_car else None,
        compounds=compounds,
        plans=[
            _plan_out(p, top) for _, p in sorted(best.items(), key=lambda kv: kv[1].total_time)
        ],
        recommended_stops=rec.n_stops,
        margin_s=round(margin, 2),
        crossover_pit_loss_s=round(x, 2) if x else None,
        n_plans_enumerated=len(plans_all),
        step=req.step,
        approximate=req.step > 1,
        compute_ms=int((time.perf_counter() - t0) * 1000),
    )


@app.post("/whatif", response_model=WhatIfResponse)
def whatif(req: WhatIfRequest) -> WhatIfResponse:
    """Pit now, or in N laps?

    The question a pit wall actually asks. For each candidate lap we hold the
    laps already run fixed -- they happened -- and re-optimise everything after
    the stop, then report the cost of each choice relative to the best.
    """
    import time

    from .strategy.optimise import stint_time

    t0 = time.perf_counter()
    st = state()

    if req.event not in st.race_laps:
        raise HTTPException(404, f"unknown event {req.event!r}")
    measured = st.pit_loss.get(req.event)
    base_pit = req.pit_loss_s if req.pit_loss_s is not None else measured
    if base_pit is None:
        raise HTTPException(422, f"no measured pit loss for {req.event!r}")

    def pit_loss_on(lap: int) -> float:
        """What a stop costs on a given lap.

        Under a safety car the discount applies only while the field is still
        neutralised. Beyond that window the stop is a normal green-flag stop
        again, and that difference is the decision.
        """
        if req.safety_car and lap < req.current_lap + req.safety_car_laps:
            return base_pit * req.neutralised_fraction
        return base_pit

    race_laps = req.race_laps or st.race_laps[req.event]
    usable, _ = _rates_for(st, req.event, req.rates)
    if req.compound not in usable:
        raise HTTPException(
            422,
            f"{req.compound} has no usable fitted degradation at {req.event}, so the "
            "cost of staying out on it cannot be computed",
        )
    if req.current_lap >= race_laps:
        raise HTTPException(422, "the race is over")

    order = [c for c in C_ORDER if c in usable]
    offsets = {c: -req.pace_step_s * i for i, c in enumerate(order)}
    current_rate = usable[req.compound]

    options: list[WhatIfOption] = []
    raw: list[tuple[int, float, PlanOut | None]] = []
    for ahead in range(0, req.horizon + 1):
        pit_lap = req.current_lap + ahead
        if pit_lap >= race_laps:
            break
        # Cost of the laps we would run before stopping, on the tyre we are on,
        # continuing from its current age.
        extra = stint_time(req.tyre_age + ahead, current_rate, offsets[req.compound]) - stint_time(
            req.tyre_age, current_rate, offsets[req.compound]
        )
        remaining = race_laps - pit_lap
        if remaining < 5:
            break
        this_pit = pit_loss_on(pit_lap)
        # Laps after the stop are green-flag laps whatever happens now, so the
        # rest of the race is optimised at the full pit loss even when this
        # stop is discounted.
        rest = _enumerate_cached(
            remaining,
            tuple(sorted(usable.items())),
            tuple(sorted(offsets.items())),
            round(base_pit, 4),
            req.step,
        )
        if not rest:
            continue
        total = extra + this_pit + rest[0].total_time
        raw.append((pit_lap, total, _plan_out(rest[0], rest[0].total_time)))

    if not raw:
        raise HTTPException(422, "no stop lap leaves enough laps for a legal plan")

    top = min(t for _, t, _ in raw)
    for pit_lap, total, plan in raw:
        options.append(
            WhatIfOption(
                pit_on_lap=pit_lap,
                laps_from_now=pit_lap - req.current_lap,
                total_time=round(total, 2),
                delta_s=round(total - top, 2),
                plan=plan,
            )
        )
    best_lap = min(raw, key=lambda r: r[1])[0]

    # The window, not just the winner.
    #
    # "Best stop is lap 20" reads as a decision. It is often not one: at
    # Hungary on a mid-race medium the first four options come out 0.00, 0.03,
    # 0.03 and 0.16 seconds apart, which is far below the 2.2s median spread in
    # what a stop costs at the same circuit from one season to the next. A pit
    # wall told "lap 20" will burn a call defending it; told "anywhere in 20-23
    # is free, it starts costing at 25" it can wait for track position, or
    # traffic, or a safety car -- the things the optimiser does not model and
    # the strategist does.
    #
    # Contiguous from the best lap outward, deliberately. A cheap lap on the
    # far side of an expensive one is not somewhere you can drift to.
    by_lap = {lap: total - top for lap, total, _ in raw}
    lo = hi = best_lap
    while (lo - 1) in by_lap and by_lap[lo - 1] <= req.window_tolerance_s:
        lo -= 1
    while (hi + 1) in by_lap and by_lap[hi + 1] <= req.window_tolerance_s:
        hi += 1

    return WhatIfResponse(
        event=req.event,
        current_lap=req.current_lap,
        tyre_age=req.tyre_age,
        compound=req.compound,
        pit_loss_s=round(pit_loss_on(req.current_lap), 2),
        race_laps=race_laps,
        safety_car=req.safety_car,
        best_pit_lap=best_lap,
        window_from=lo,
        window_to=hi,
        window_tolerance_s=req.window_tolerance_s,
        options=options,
        compute_ms=int((time.perf_counter() - t0) * 1000),
    )


# ---------------------------------------------------------------------------
# the race that has not happened yet
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _circuits() -> dict:
    """Per-circuit pit loss and distance from previous seasons.

    Written by scripts/11_circuits.py. Absent is a normal state -- it just means
    an upcoming race has to be told its pit loss rather than reminded of it.
    """
    import json

    path = ARTIFACTS / "circuits.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


@app.get("/poller")
def poller_status() -> dict:
    """What the background poller is doing. Read-only."""
    from dataclasses import asdict

    return asdict(poller.STATE)


@app.get("/allocation")
def get_allocation() -> list[dict]:
    """Pirelli's compound nomination per event -- the one fact no API carries."""
    from dataclasses import asdict

    return [asdict(a) for a in sorted(alloc.all_allocations().values(), key=lambda x: x.event)]


class AllocationIn(BaseModel):
    #: Label -> C number, e.g. {"HARD": "C3", "MEDIUM": "C4", "SOFT": "C5"}.
    compounds: dict[str, str]
    season: int = SEASON


@app.put("/allocation/{event}")
def put_allocation(event: str, body: AllocationIn) -> dict:
    """Record a nomination for an event.

    This is what makes adding a race three dropdowns rather than a code change.
    Validation rejects duplicates and an inverted hard-to-soft ordering, because
    a typo here surfaces three screens later as a backwards degradation curve.
    """
    from dataclasses import asdict

    try:
        a = alloc.set_allocation(event, body.compounds, season=body.season, source="user")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _state.cache_clear()  # the fit keys on nominated compounds
    return asdict(a)


@app.delete("/allocation/{event}")
def delete_allocation(event: str) -> dict:
    """Clear a nomination entered here, reverting to the cited value if any.

    The set path existed without this one, which meant a value typed into the
    app could not be taken back out of it -- and a typed value that cannot be
    removed is worse than one that was never allowed, because it looks like a
    fact from then on. Testing this app wrote a nomination for a race Pirelli
    has not announced, and only the `source` marker made that visible.
    """
    removed = alloc.unset(event)
    if not removed:
        raise HTTPException(404, f"no nomination recorded for {event!r}")
    _state.cache_clear()  # the fit keys on nominated compounds
    a = alloc.get(event)
    return {
        "event": event,
        "cleared": True,
        "reverted_to": a.compounds if a else None,
        "source": a.source if a else None,
    }


@app.get("/upcoming")
def upcoming(limit: int = 3) -> list[dict]:
    """Races that have not run yet, and how much we can already say.

    The point of the product. A race becomes answerable in stages:

        on the calendar        we know the date and the circuit
        + nominated            Pirelli announced the compounds
        + practice run         we have long runs, so we can forecast
        + raced                we can score ourselves

    Each field says which stage it came from, so a forecast built on Friday
    practice is never displayed as if it were a measured race.
    """
    st = state()
    circuits = _circuits()
    out = []

    for rnd in sched.next_rounds(SEASON, limit=limit):
        compounds = alloc.compounds_for(rnd.event)
        practice_run = rnd.long_run_sessions_run()
        have_practice = rnd.event in st.events_in_dataset

        hist = circuits.get(rnd.event, {})
        row = {
            "round_number": rnd.round_number,
            "event": rnd.event,
            "location": rnd.location,
            "country": rnd.country,
            "date_utc": rnd.date_utc.isoformat(),
            "sessions": [
                {"code": s.code, "starts_utc": s.starts_utc.isoformat(), "has_run": s.has_run()}
                for s in rnd.sessions
            ],
            "practice_sessions_run": practice_run,
            "allocation": compounds or None,
            "allocation_source": (a.source if (a := alloc.get(rnd.event)) else None),
            # From previous seasons at this circuit. Explicitly labelled, since
            # last year's pit lane is evidence and not a measurement of this
            # weekend.
            "history": {
                "pit_loss_s": hist.get("pit_loss_s"),
                "pit_loss_spread_s": hist.get("pit_loss_spread_s"),
                "race_laps": hist.get("race_laps"),
                "seasons": hist.get("seasons", []),
            }
            if hist
            else None,
            "ready_to_forecast": bool(compounds) and bool(practice_run) and have_practice,
            "blocked_by": _blocked_by(compounds, practice_run, have_practice, hist),
        }
        out.append(row)
    return out


def _blocked_by(compounds, practice_run, have_practice, hist) -> list[str]:
    """Plain reasons a race cannot be answered yet.

    Written as sentences rather than flags because this is what the screen shows
    when it has nothing else, and "ready_to_forecast: false" tells a user
    nothing they can act on.
    """
    reasons = []
    if not compounds:
        reasons.append("Pirelli's compound nomination has not been entered for this weekend")
    if not practice_run:
        reasons.append("no practice session has finished yet")
    elif not have_practice:
        reasons.append("practice has run but has not been pulled into the dataset yet")
    if not hist or hist.get("pit_loss_s") is None:
        reasons.append("no pit-loss history for this circuit, so it must be supplied")
    return reasons


class ForecastRequest(BaseModel):
    """A race that has not happened yet."""

    event: str
    #: Override the circuit's historical pit loss. Editable because last year's
    #: pit lane is evidence about this weekend, not a measurement of it.
    pit_loss_s: float | None = Field(default=None, ge=5.0, le=60.0)
    race_laps: int | None = Field(default=None, ge=5, le=100)
    pace_step_s: float = Field(default=PACE_STEP_S, ge=0.0, le=3.0)
    step: int = Field(default=1, ge=1, le=5)
    #: Fill nominated compounds that never ran a race simulation this weekend
    #: with a rate borrowed from other circuits and rescaled by this circuit's
    #: severity. Default on: a labelled stand-in is more use to a pit wall than
    #: a refusal, and every such row is marked ``source="stand-in"``.
    allow_stand_ins: bool = True


@app.get("/practice-sessions")
def practice_sessions(event: str) -> dict:
    """What each practice session says on its own, and how they are combined.

    Built for the question a strategist actually asks on a Friday night: what
    did FP1 tell us, what did FP2 tell us, do they agree, and which one am I
    trusting? The pooled forecast answers none of that -- it hands over one
    number with the disagreement already averaged away.

    Sessions are NOT weighted equally. Scored against the races that have run,
    FP2's measured degradation correlates 0.84 with the race and FP1's
    correlates 0.05, so FP2 carries twice the weight of the other two. The
    weights and the evidence behind them ship in the response rather than
    living in a docstring, because a number a pit wall cannot interrogate is a
    number it will not use.
    """
    from .data import session_weight
    from .validation.transfer import per_session_rates

    st = state()
    if st.practice is None or st.practice.empty:
        raise HTTPException(422, "no practice data in the dataset")
    if event not in st.events_in_dataset:
        raise HTTPException(404, f"{event!r} has no practice in the dataset yet")

    compounds = alloc.compounds_for(event)
    label_of = {c: lab for lab, c in (compounds or {}).items()}

    tbl = per_session_rates(st.practice, event)
    rnd = sched.find(event, SEASON)
    gaps = session_weight.hours_to_race(event, SEASON)

    rows = []
    for _, r in tbl.iterrows():
        se = float(r["se"])
        rows.append(
            {
                "session": str(r["session"]),
                "compound": str(r["C"]),
                "label": label_of.get(str(r["C"])),
                "rate": round(float(r["rate"]), 5),
                "se": None if pd.isna(se) else round(se, 5),
                "n_runs": int(r["n_runs"]),
                "n_laps": int(r["n_laps"]),
                "weight": round(float(r["weight"]), 3),
                # A cell this thin is shown but must not be leaned on. Two runs
                # of a soft at Madrid carry a standard error of 0.39 s/lap,
                # which is wider than any rate on the calendar.
                "thin": int(r["n_runs"]) < 3,
            }
        )

    ran = rnd.long_run_sessions_run() if rnd else []
    sessions = []
    for code in ("FP1", "FP2", "FP3"):
        cells = [r for r in rows if r["session"] == code]
        sessions.append(
            {
                "session": code,
                "has_run": code in ran,
                "weight": session_weight.weight_for(code),
                "hours_to_race": gaps.get(code),
                "n_cells": len(cells),
                "n_race_sim_runs": sum(c["n_runs"] for c in cells),
                "n_race_sim_laps": sum(c["n_laps"] for c in cells),
                "cells": cells,
            }
        )

    return {
        "event": event,
        "sessions": sessions,
        "weights": session_weight.weights(),
        # The measurement that sets the weights, so the screen can show why
        # rather than asserting it. Correlation of each session's measured
        # degradation against the same cell's race degradation.
        "weight_evidence": SESSION_SKILL,
        "allocation": compounds or None,
    }


@app.post("/forecast")
def forecast(req: ForecastRequest) -> dict:
    """Predict a race from the practice that has already run.

    THE ACTUAL PRODUCT. Friday practice is in, Sunday has not happened, and a
    strategist wants the plan. Distinct from /strategy in what it is allowed to
    use: /strategy fits on races that finished, this fits on practice and
    applies a correction learned from OTHER events.

    Every input reports its source. A rate forecast from Friday long runs and a
    rate measured from a finished race are not the same claim, and the screen
    has to be able to tell a viewer which one it is looking at.
    """
    import time

    from .validation.transfer import forecast as forecast_rates
    from .validation.transfer import leave_one_event_out, stand_in_rates

    t0 = time.perf_counter()
    st = state()

    if st.practice is None or st.practice.empty:
        raise HTTPException(422, "no practice data in the dataset")
    if req.event not in st.events_in_dataset:
        raise HTTPException(
            404,
            f"{req.event!r} is not in the dataset; its practice has not been pulled yet",
        )

    compounds = alloc.compounds_for(req.event)
    if not compounds:
        raise HTTPException(
            422,
            f"no compound nomination recorded for {req.event!r}. Pirelli publishes "
            "this and no feed carries it, so it has to be entered.",
        )

    hist = _circuits().get(req.event, {})
    pit = req.pit_loss_s if req.pit_loss_s is not None else hist.get("pit_loss_s")
    laps = req.race_laps if req.race_laps is not None else hist.get("race_laps")
    if pit is None or laps is None:
        raise HTTPException(
            422,
            f"no pit-loss or distance history for {req.event!r}; supply pit_loss_s "
            "and race_laps explicitly",
        )

    # The practice-to-race factor, learned from events that HAVE raced. The
    # event being forecast contributes nothing to its own correction.
    try:
        loo = leave_one_event_out(st.practice, st.race)
        factor = float(loo.factor)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"could not learn the practice-to-race factor: {exc}") from exc

    try:
        rows = forecast_rates(st.practice, factor, req.event)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    label_of = {c: lab for lab, c in compounds.items()}
    nominated = set(compounds.values())

    # Stand in for nominated compounds this weekend never ran on a race
    # simulation. Madrid nominated a HARD that nobody put on a long run in any
    # of the three sessions, which left one usable compound, which is not a
    # legal plan -- so the screen refused to answer on the very race we demo.
    # A borrowed rate, scaled by how harsh this circuit is and labelled as
    # borrowed, beats silence. Off by default so /forecast keeps its old
    # meaning for callers that want measured-only.
    standins = pd.DataFrame()
    if req.allow_stand_ins:
        try:
            standins = stand_in_rates(st.practice, factor, req.event, sorted(nominated))
        except Exception as exc:  # noqa: BLE001 - a stand-in is a bonus, never a blocker
            log.warning("stand-in rates failed for %s: %s", req.event, exc)
    if not standins.empty:
        rows = pd.concat([rows, standins], ignore_index=True)

    usable: dict[str, float] = {}
    out_compounds = []
    for _, r in rows.iterrows():
        c = str(r["C"])
        if c not in nominated:
            continue  # ran in practice but is not nominated for the race
        rate = float(r["predicted_race_rate"])
        excluded = rate <= 0
        if not excluded:
            usable[c] = rate
        src = str(r.get("source", "measured"))
        out_compounds.append(
            {
                "compound": c,
                "label": label_of.get(c),
                "rate": round(rate, 5),
                "rate_lo": round(float(r["lo"]), 5),
                "rate_hi": round(float(r["hi"]), 5),
                "practice_rate": round(float(r["rate"]), 5),
                "optimal_stint": 0,
                "excluded": excluded,
                "overridden": False,
                # "measured" means this weekend put that tyre on a race
                # simulation. "stand-in" means nobody did and the number came
                # from other circuits, rescaled. The screen must not draw the
                # two the same way.
                "source": src,
                "n_runs": int(r.get("n_runs") or 0),
                "n_laps": int(r.get("n_laps") or 0),
                "severity": (
                    None if pd.isna(r.get("severity")) else round(float(r["severity"]), 3)
                ),
            }
        )
    out_compounds.sort(key=lambda c: C_ORDER.index(c["compound"]) if c["compound"] in C_ORDER else 99)

    # Best stint length per usable tyre, computed BEFORE the can-plan check.
    # It used to sit after the early return, so a compound that was perfectly
    # usable displayed "0 laps" whenever the race as a whole could not be
    # planned -- which is exactly the state this screen spends most of a weekend
    # in, and "C5 is good for 29 laps" is useful even when the plan is not.
    for c in out_compounds:
        if not c["excluded"]:
            c["optimal_stint"] = int(optimal_stint(c["compound"], usable[c["compound"]], pit))

    if len(usable) < 2:
        # NOT a 422. The compound table and the reason are the useful part of
        # this answer -- "we cannot plan Monza yet, and here is exactly which
        # tyre is missing and why" beats a bare error, and it is the state the
        # screen will legitimately be in for most of a race weekend.
        return {
            "event": req.event,
            "is_forecast": True,
            "can_plan": False,
            "reason": (
                "Fewer than two nominated compounds have a usable degradation rate. "
                "A dry race needs two, so no legal plan exists yet."
            ),
            "compounds": out_compounds,
            "practice_sessions": (
                r.long_run_sessions_run() if (r := sched.find(req.event, SEASON)) else []
            ),
            "practice_to_race_factor": round(factor, 4),
            "race_laps": int(laps),
            "pit_loss_s": round(float(pit), 2),
            "compute_ms": int((time.perf_counter() - t0) * 1000),
        }

    order = [c for c in C_ORDER if c in usable]
    offsets = {c: -req.pace_step_s * i for i, c in enumerate(order)}

    plans_all = _enumerate_cached(
        int(laps),
        tuple(sorted(usable.items())),
        tuple(sorted(offsets.items())),
        round(float(pit), 4),
        req.step,
    )
    if not plans_all:
        raise HTTPException(422, "no legal strategy exists for these inputs")

    best = best_per_stop_count(plans_all)
    top = plans_all[0].total_time
    rec = plans_all[0]
    runner_up = next((p for p in plans_all if p.n_stops != rec.n_stops), None)
    margin = (runner_up.total_time - rec.total_time) if runner_up else 0.0
    x = crossover(plans_all)

    rnd = sched.find(req.event, SEASON)
    return {
        "event": req.event,
        "is_forecast": True,
        "can_plan": True,
        "race_laps": int(laps),
        "race_laps_source": "supplied" if req.race_laps is not None else "circuit history",
        "pit_loss_s": round(float(pit), 2),
        "pit_loss_source": "supplied" if req.pit_loss_s is not None else "circuit history",
        "pit_loss_spread_s": hist.get("pit_loss_spread_s"),
        "history_seasons": hist.get("seasons", []),
        "practice_sessions": rnd.long_run_sessions_run() if rnd else [],
        # The correction, surfaced. A race degrades at roughly this fraction of
        # its practice rate, learned from other events and never from the one
        # being predicted.
        "practice_to_race_factor": round(factor, 4),
        "compounds": out_compounds,
        "plans": [
            {
                "n_stops": p.n_stops,
                "compounds": list(p.compounds),
                "stint_lengths": [int(v) for v in p.stints],
                "total_time": round(p.total_time, 2),
                "delta_s": round(p.total_time - top, 2),
            }
            for _, p in sorted(best.items(), key=lambda kv: kv[1].total_time)
        ],
        "recommended_stops": rec.n_stops,
        "margin_s": round(margin, 2),
        "crossover_pit_loss_s": round(x, 2) if x else None,
        "n_plans_enumerated": len(plans_all),
        "step": req.step,
        "approximate": req.step > 1,
        "compute_ms": int((time.perf_counter() - t0) * 1000),
    }
