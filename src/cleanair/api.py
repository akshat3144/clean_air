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
    enumerating strategies          every request         0.07s - 6.6s
    the hierarchical MCMC model     never here            ~6 min a race

The fit is fast enough to redo per request and is still cached, because it is
the same answer every time and the cache makes the slow path obvious. The MCMC
model is offline work and has no business behind an HTTP request.

    enumerate step=1   exact, 337k plans at Hungary, 2.1s
    enumerate step=3   same recommended stop count at all seven events, 0.07s

``step`` is therefore a request parameter rather than a constant. A UI dragging
a slider asks for 3 and gets an instant answer; when the drag stops it asks for
1 and gets the exact stint lengths. We checked that the coarse grid picks the
same stop count everywhere before relying on it, because a call that changed
when you let go of the mouse would be a bug an audience would see.
"""

from __future__ import annotations

import logging
import warnings
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import ARTIFACTS, COMPOUND_ALLOCATION_2026, PROCESSED
from .models.design import prepare
from .models.mixed import fit_degradation
from .strategy.optimise import best_per_stop_count, crossover, enumerate_plans, optimal_stint

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

log = logging.getLogger(__name__)

C_ORDER = ("C1", "C2", "C3", "C4", "C5")

#: Assumed fresh-tyre pace gap between adjacent compounds, seconds. Assumed
#: rather than fitted, and the weakest input in the layer, so it is a request
#: parameter too -- a caller who disagrees can say so.
PACE_STEP_S = 0.6

#: A safety car neutralises the field, so the time lost pitting collapses to
#: roughly the pit-lane transit rather than a full green-flag stop. Treated as a
#: fraction of the measured green-flag pit loss rather than a fixed number,
#: because it scales with the circuit's pit lane.
#:
#: This is a MODELLING ASSUMPTION and not measured from our data. It is exposed
#: in the response so a caller can see the answer rests on it.
SAFETY_CAR_PIT_LOSS_FRACTION = 0.45


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
    race = prepare(laps, "race")
    fit = fit_degradation(race, quadratic=False, context="race")

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
    return State(race=race, fit=fit, pit_loss=pit_loss, n_green_stops=n_stops, race_laps=race_laps)


@asynccontextmanager
async def lifespan(app: FastAPI):
    st = _state()
    log.info("loaded %d events, %d laps", len(st.race_laps), len(st.race))
    yield


app = FastAPI(
    title="Clean Air",
    summary="Deconfounded tyre degradation, and the pit-stop decision that follows from it.",
    lifespan=lifespan,
)

# The React app is served from a different origin in every deployment shape --
# Vite on 5173 locally, Vercel in production. Origins are read from the
# environment rather than hardcoded so the deployed app does not need a rebuild
# to move.
import os  # noqa: E402  (kept next to the thing that needs it)

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
    #: Treat the next stop as taken under a safety car.
    safety_car: bool = False


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
    #: The pit loss actually used when safety_car is set, and the fraction it
    #: came from. Surfaced because it is assumed, not measured.
    safety_car_fraction: float | None
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
    #: How many laps ahead to evaluate staying out.
    horizon: int = Field(default=8, ge=1, le=25)
    step: int = Field(default=3, ge=1, le=5)


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
    safety_car: bool
    best_pit_lap: int
    options: list[WhatIfOption]
    compute_ms: int


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rates_for(st: State, event: str, overrides: dict[str, float] | None):
    """Fitted degradation for this weekend's nominated tyres, with overrides."""
    allocation = COMPOUND_ALLOCATION_2026.get(event, {})
    if not allocation:
        raise HTTPException(404, f"no compound allocation known for {event!r}")
    label_of = {c: lab for lab, c in allocation.items()}
    nominated = set(allocation.values())

    usable: dict[str, float] = {}
    out: list[CompoundOut] = []
    for c in [x for x in C_ORDER if x in nominated]:
        if c not in st.fit.rates:
            continue
        iv = st.fit.rates[c]
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
        allocation = COMPOUND_ALLOCATION_2026.get(ev, {})
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
    pit = base_pit * SAFETY_CAR_PIT_LOSS_FRACTION if req.safety_car else base_pit

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
        safety_car_fraction=SAFETY_CAR_PIT_LOSS_FRACTION if req.safety_car else None,
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
            return base_pit * SAFETY_CAR_PIT_LOSS_FRACTION
        return base_pit

    race_laps = st.race_laps[req.event]
    usable, _ = _rates_for(st, req.event, None)
    if req.compound not in usable:
        raise HTTPException(
            422,
            f"{req.compound} has no usable fitted degradation at {req.event}, so the "
            "cost of staying out on it cannot be computed",
        )
    if req.current_lap >= race_laps:
        raise HTTPException(422, "the race is over")

    order = [c for c in C_ORDER if c in usable]
    offsets = {c: -PACE_STEP_S * i for i, c in enumerate(order)}
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

    return WhatIfResponse(
        event=req.event,
        current_lap=req.current_lap,
        tyre_age=req.tyre_age,
        compound=req.compound,
        pit_loss_s=round(pit_loss_on(req.current_lap), 2),
        safety_car=req.safety_car,
        best_pit_lap=best_lap,
        options=options,
        compute_ms=int((time.perf_counter() - t0) * 1000),
    )
