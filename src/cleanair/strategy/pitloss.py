"""How much time does a pit stop cost?

Everything in strategy turns on this number. Degradation tells you when a tyre
is slow; pit loss tells you whether it is slow enough to be worth changing. Get
it wrong by two seconds and the one-stop versus two-stop answer flips.

It is not published, so we measure it. A pit stop costs the extra time on the
lap you enter the pits and the lap you leave, relative to a normal lap:

    pit_loss = (in-lap + out-lap) - 2 x (that driver's normal lap time)

Circuit-specific, because it depends on pit lane length, the speed limit, and
where the entry and exit sit relative to the timing line. Monaco and Monza are
nothing alike.

Measured rather than assumed also means it comes with an uncertainty, which
propagates into the strategy recommendation instead of being hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Reject a stop whose implied loss falls outside this range, in seconds.
#: Real pit loss runs roughly 16-30s. Values outside that come from a safety
#: car (everyone pits cheaply), a red flag, a drive-through penalty, or a stop
#: that also involved damage repair -- none of which is a normal pit stop.
PLAUSIBLE_RANGE_S = (12.0, 40.0)


@dataclass
class PitLoss:
    event: str
    seconds: float
    lo: float
    hi: float
    n_stops: int

    @property
    def se(self) -> float:
        return (self.hi - self.lo) / 3.92


def estimate(laps: pd.DataFrame, event: str) -> PitLoss | None:
    """Pit loss for one event, from its in-laps and out-laps.

    Needs the RAW laps, not the cleaned set -- cleaning drops pit laps, which
    are the entire signal here.

    Args:
        laps: raw ``session.laps`` for a race, with PitInTime and PitOutTime.
        event: event name, for labelling.

    Returns:
        A ``PitLoss``, or None if no plausible stops could be measured.
    """
    df = laps.copy()
    if "LapTimeSeconds" not in df.columns:
        df["LapTimeSeconds"] = pd.to_timedelta(df["LapTime"]).dt.total_seconds()
    df = df[df["LapTimeSeconds"].notna()]

    # Reference pace: the driver's own median green lap, so a slow car is not
    # credited with a cheap pit stop.
    green = df[
        df["PitInTime"].isna()
        & df["PitOutTime"].isna()
        & df["TrackStatus"].astype(str).eq("1")
    ]
    if green.empty:
        return None
    reference = green.groupby("Driver")["LapTimeSeconds"].median()

    losses = []
    for driver, g in df.groupby("Driver"):
        if driver not in reference:
            continue
        base = reference[driver]
        g = g.sort_values("LapNumber")

        for _, in_lap in g[g["PitInTime"].notna()].iterrows():
            out_lap = g[g["LapNumber"] == in_lap["LapNumber"] + 1]
            if out_lap.empty or out_lap["PitOutTime"].isna().all():
                continue
            # Only count stops made under green: under a safety car the whole
            # field pits at a discount and the number means nothing.
            if str(in_lap.get("TrackStatus", "1")) != "1":
                continue
            total = in_lap["LapTimeSeconds"] + out_lap["LapTimeSeconds"].iloc[0]
            loss = total - 2 * base
            if PLAUSIBLE_RANGE_S[0] <= loss <= PLAUSIBLE_RANGE_S[1]:
                losses.append(loss)

    if len(losses) < 3:
        return None

    arr = np.array(losses)
    # Median, not mean: a single botched stop should not move the estimate.
    centre = float(np.median(arr))
    se = float(arr.std(ddof=1) / np.sqrt(len(arr)))
    return PitLoss(
        event=event,
        seconds=centre,
        lo=centre - 1.96 * se,
        hi=centre + 1.96 * se,
        n_stops=len(arr),
    )


def estimate_all(events: list[str], season: int = 2026) -> pd.DataFrame:
    """Pit loss for every event, read from the local FastF1 cache."""
    from ..data.cache import load_session

    rows = []
    for event in events:
        try:
            s = load_session(event, "R", season, telemetry=False, weather=False)
            pl = estimate(s.laps, event)
        except Exception:  # noqa: BLE001 -- one bad session must not stop the batch
            pl = None
        if pl:
            rows.append(
                {
                    "event": pl.event,
                    "pit_loss_s": round(pl.seconds, 2),
                    "lo": round(pl.lo, 2),
                    "hi": round(pl.hi, 2),
                    "n_stops": pl.n_stops,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Pit loss by track status
# ---------------------------------------------------------------------------
#
# The strategy console has a "safety car is out" toggle, and the obvious way to
# implement it is to discount the pit loss: the field is neutralised, so a stop
# should be cheap. That is the universal intuition in F1 and it is why the first
# version of the API simply asserted a 0.45 multiplier.
#
# It does not survive measurement, and the reason matters.

#: Track-status categories, from FastF1's codes. A lap's status is a
#: concatenation of every code that applied during it, so these are substring
#: tests rather than equality: "41" is a safety car followed by all-clear.
_STATUS_CODES = (
    ("safety_car", ("4",)),
    ("vsc", ("6", "7")),
    ("yellow", ("2",)),
)


def status_category(status: object) -> str:
    """Which neutralisation applied during a lap, if any."""
    s = str(status)
    for name, codes in _STATUS_CODES:
        if any(c in s for c in codes):
            return name
    return "green"


def loss_by_status(laps: pd.DataFrame, event: str) -> pd.DataFrame:
    """Pit loss split by track status, each measured the same way.

    The reference is the NON-PITTING field on the same two laps, not the
    driver's own green-flag median. Under a neutralisation every car is slow, so
    a green reference charges the stop for the safety car as well as for the
    stop, and the resulting number means nothing.

    Returns one row per stop: event, driver, lap, category, loss in seconds.
    """
    df = laps.copy()
    if "LapTimeSeconds" not in df.columns:
        df["LapTimeSeconds"] = pd.to_timedelta(df["LapTime"]).dt.total_seconds()
    df = df[df["LapTimeSeconds"].notna()].sort_values(["Driver", "LapNumber"])
    if df.empty:
        return pd.DataFrame(columns=["event", "driver", "lap", "category", "loss", "n_pitting"])

    df["category"] = df["TrackStatus"].map(status_category)
    pitting = df["PitInTime"].notna() | df["PitOutTime"].notna()

    # What a car that stayed out did on each lap.
    reference = df[~pitting].groupby("LapNumber")["LapTimeSeconds"].median()

    rows = []
    for driver, g in df.groupby("Driver"):
        for _, in_lap in g[g["PitInTime"].notna()].iterrows():
            lap = in_lap["LapNumber"]
            out_lap = g[g["LapNumber"] == lap + 1]
            if out_lap.empty or out_lap["PitOutTime"].isna().all():
                continue
            if lap not in reference.index or (lap + 1) not in reference.index:
                continue
            observed = in_lap["LapTimeSeconds"] + float(out_lap["LapTimeSeconds"].iloc[0])
            expected = float(reference.loc[lap]) + float(reference.loc[lap + 1])
            rows.append(
                {
                    "event": event,
                    "driver": driver,
                    "lap": int(lap),
                    "category": in_lap["category"],
                    "loss": observed - expected,
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # Cars pitting on the same lap in the same state: a pit-lane queue, which
    # costs real time and is not a property of the neutralisation.
    counts = out.groupby(["lap", "category"]).size().rename("n_pitting")
    out = out.merge(counts, on=["lap", "category"])
    # A negative loss is not a stop, and 45s is a stop that also involved
    # damage. The green floor of PLAUSIBLE_RANGE_S is deliberately NOT applied:
    # it would discard cheap stops, which are the ones under question here.
    return out[(out["loss"] > 0) & (out["loss"] < 45.0)]
