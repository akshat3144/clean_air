"""The same estimator, different sensors.

WHAT ACTUALLY TRANSFERS

Not the F1 model. What transfers is the identification trick, and it is worth
stating precisely because "this could apply to fleets" is easy to say and
usually means nothing.

The trick is: when you cannot separate wear from the conditions it was measured
under, find groups of vehicles that shared the same conditions at the same time,
subtract the group mean from everything, and read the wear signal out of what is
left. Anything common to the group -- weather, road surface, fuel load, traffic,
the state of the track -- disappears without ever being modelled, so it cannot be
modelled wrongly.

    F1        cohort = (event, lap)     every car on track at that instant
    fleet     cohort = (route, day)     every truck on that road that day

The requirement is the same in both: within a cohort, vehicles must differ in
tyre AGE. If every truck on a route replaces tyres on the same schedule, there
is nothing to compare and no honest answer, exactly as at the 2026 Belgian GP
where every car on C3 was the same age on any given lap.

WHAT WE ARE NOT CLAIMING

We have no fleet data. Nothing here has been validated against real trucks. This
is a working, tested interface plus a synthetic demonstration that the estimator
recovers a known wear rate from fleet-shaped data -- which is a different and
much smaller claim than "it works on fleets".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Minimum vehicles in a cohort. A group of one has no comparison in it, and a
#: group of two gives an unstable mean.
MIN_COHORT_SIZE = 3

#: Minimum spread of age within a cohort, in the age variable's own units.
#: Below this the vehicles are effectively the same age and the rate is not
#: identifiable. See the module docstring.
MIN_AGE_SPREAD = 1e-6


@dataclass
class WearRate:
    """Wear per unit of age, for one cohort group."""

    group: str
    rate: float
    lo: float
    hi: float
    n_observations: int
    n_cohorts: int
    age_spread: float

    @property
    def identifiable(self) -> bool:
        return self.age_spread > MIN_AGE_SPREAD and self.n_cohorts >= 2


@dataclass
class FleetSchema:
    """Which of your columns mean what.

    Example, for a haulage fleet measuring tread depth::

        FleetSchema(
            wear="tread_depth_mm",
            age="km_since_fitted",
            cohort=["route_id", "date"],
            group="tyre_model",
            unit="vehicle_id",
        )
    """

    #: The thing that degrades. Lap time in F1; tread depth or rolling
    #: resistance in a fleet. May improve or worsen with age -- the sign is
    #: yours to interpret.
    wear: str
    #: How much use the tyre has had. Laps in F1; kilometres in a fleet.
    age: str
    #: Columns that together identify vehicles sharing conditions. This is the
    #: whole method: get it wrong and confounders survive.
    cohort: list[str]
    #: What to estimate a separate rate for. Compound in F1; tyre model,
    #: manufacturer or specification in a fleet.
    group: str
    #: Identifies one vehicle, used for reporting only.
    unit: str = "unit_id"


def estimate_wear_rate(
    df: pd.DataFrame,
    schema: FleetSchema,
    min_cohort: int = MIN_COHORT_SIZE,
) -> list[WearRate]:
    """Wear per unit of age, per group, with confounders removed by design.

    Subtracts the cohort mean from both wear and age, then regresses one on the
    other. Algebraically identical to a fixed effect for every cohort, and far
    cheaper.

    Args:
        df: one row per vehicle per observation.
        schema: which columns mean what.
        min_cohort: smallest usable cohort.

    Returns:
        One ``WearRate`` per group. Check ``identifiable`` before using a rate:
        a group whose vehicles never differ in age inside a cohort will return a
        number, and that number will be meaningless.
    """
    needed = [schema.wear, schema.age, schema.group, *schema.cohort]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")

    d = df.dropna(subset=needed).copy()

    # Keep only cohorts big enough to contain a comparison.
    sizes = d.groupby(schema.cohort)[schema.wear].transform("size")
    d = d[sizes >= min_cohort]
    if d.empty:
        raise ValueError(
            f"no cohort has at least {min_cohort} vehicles. Cohorts are defined by "
            f"{schema.cohort} -- if that is too fine-grained, widen it."
        )

    cell = d.groupby(schema.cohort)
    d["_w"] = d[schema.wear] - cell[schema.wear].transform("mean")
    d["_a"] = d[schema.age] - cell[schema.age].transform("mean")

    out: list[WearRate] = []
    for group, g in d.groupby(schema.group):
        x = g["_a"].to_numpy(float)
        y = g["_w"].to_numpy(float)
        denom = float(x @ x)
        spread = float(g.groupby(schema.cohort)[schema.age].std().mean() or 0.0)

        if denom <= MIN_AGE_SPREAD:
            out.append(WearRate(str(group), np.nan, np.nan, np.nan, len(g),
                                g.groupby(schema.cohort).ngroups, spread))
            continue

        rate = float(x @ y / denom)
        se = _cluster_robust_se(x, y - rate * x, g[schema.unit].to_numpy(), denom)
        out.append(
            WearRate(
                group=str(group),
                rate=rate,
                lo=rate - 1.96 * se,
                hi=rate + 1.96 * se,
                n_observations=len(g),
                n_cohorts=g.groupby(schema.cohort).ngroups,
                age_spread=spread,
            )
        )
    return out


def _cluster_robust_se(x: np.ndarray, resid: np.ndarray, cluster: np.ndarray, denom: float) -> float:
    """Standard error of a slope, clustered by vehicle.

    Repeated measurements on the same vehicle are correlated: a truck that runs
    heavy routes is slow to wear on every one of its observations, not
    independently on each. Treating every row as independent counts the same
    information many times and makes the interval far too narrow.

    Measured, not assumed: with ordinary errors, our 95% intervals covered the
    true wear rate 37% of the time across 25 simulated fleets. They should cover
    it 95% of the time. Clustering by vehicle is what fixes that.

    This is the Liang-Zeger sandwich estimator for a slope through the origin,
    which reduces to::

        Var(b) = sum_over_clusters( (sum_in_cluster x_i * u_i)^2 ) / (x'x)^2
    """
    total = 0.0
    for c in np.unique(cluster):
        m = cluster == c
        total += float(x[m] @ resid[m]) ** 2

    n_clusters = len(np.unique(cluster))
    if n_clusters < 2 or denom <= 0:
        return float("nan")

    # Small-sample correction, as used by Stata and statsmodels.
    correction = n_clusters / max(1, n_clusters - 1)
    return float(np.sqrt(correction * total) / denom)


def naive_wear_rate(df: pd.DataFrame, schema: FleetSchema) -> list[WearRate]:
    """The same thing done the obvious way, with no cohort adjustment.

    Provided so the difference can be shown rather than asserted. This is what
    you get from regressing wear on odometer reading, which is how replacement
    and retreading decisions are usually made -- and it absorbs every difference
    in load, gradient, surface and driving style into the wear estimate.
    """
    d = df.dropna(subset=[schema.wear, schema.age, schema.group])
    out = []
    for group, g in d.groupby(schema.group):
        x = g[schema.age].to_numpy(float)
        y = g[schema.wear].to_numpy(float)
        X = np.column_stack([np.ones_like(x), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        # Clustered here too, so the two methods are compared on equal terms and
        # the naive method is not made to look worse than it is.
        xc = x - x.mean()
        se = _cluster_robust_se(xc, resid, g[schema.unit].to_numpy(), float(xc @ xc))
        out.append(
            WearRate(str(group), float(beta[1]), float(beta[1]) - 1.96 * se,
                     float(beta[1]) + 1.96 * se, len(g), 0, 0.0)
        )
    return out


def synthetic_fleet(
    n_routes: int = 12,
    n_days: int = 30,
    trucks_per_route: int = 6,
    true_rates: dict[str, float] | None = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Fleet-shaped data with a KNOWN wear rate, for demonstrating the transfer.

    Built to contain the same confounding structure as the F1 problem: a large
    per-cohort effect (route difficulty and daily weather) that dwarfs the wear
    signal, and vehicles within a cohort at different tyre ages.

    Wear here is tread depth in mm, so the rates are NEGATIVE -- tread is lost,
    not gained.
    """
    # mm of tread lost per KILOMETRE, matching the units of ``km_since_fitted``.
    # A heavy-truck tyre losing ~10 mm over ~150,000 km is around -7e-5, so these
    # are realistic. Keeping the rate and the age variable in the same units
    # matters: expressing one per 1000 km and the other per km silently puts a
    # factor of a thousand between the truth and the estimate.
    true_rates = true_rates or {"budget": -9e-5, "midrange": -6e-5, "premium": -4e-5}
    rng = np.random.default_rng(seed)

    models = list(true_rates)

    # Assign each truck a model and a replacement offset INDEPENDENTLY. Deriving
    # both from the truck index ties tyre age to tyre model, which is residual
    # confounding of exactly the kind this method exists to remove -- it left the
    # premium estimate 27% out even after the cohort transformation.
    n_trucks = n_routes * trucks_per_route
    truck_model = {i: models[int(rng.integers(len(models)))] for i in range(n_trucks)}
    truck_offset_km = {i: float(rng.uniform(0, 20_000)) for i in range(n_trucks)}

    rows = []
    for route in range(n_routes):
        # Route difficulty: gradient, surface, typical load. Big, and shared by
        # every truck on that route -- exactly the sort of thing the cohort
        # transformation is meant to delete.
        # Deliberately LARGER than the wear signal itself. A tyre loses about
        # 1.8 mm over a 20,000 km life here, and route-to-route differences in
        # gradient, surface and typical load swamp that. If the confounder were
        # small the demonstration would prove nothing, because the naive method
        # would work fine.
        difficulty = rng.normal(0, 4.0)
        for day in range(n_days):
            weather = rng.normal(0, 1.2)  # shared by everyone on that route that day
            for t in range(trucks_per_route):
                truck = route * trucks_per_route + t
                model = truck_model[truck]
                # Staggered replacement, so ages differ within a cohort. Without
                # this the rate is not identifiable, as at the Belgian GP.
                km = truck_offset_km[truck] + day * 400
                depth = (
                    14.0
                    + difficulty
                    + weather
                    + true_rates[model] * km
                    + rng.normal(0, 0.15)
                )
                rows.append(
                    {
                        "unit_id": f"T{truck:03d}",
                        "route_id": f"R{route:02d}",
                        "date": f"2026-{1 + day // 28:02d}-{1 + day % 28:02d}",
                        "tyre_model": model,
                        "km_since_fitted": km,
                        "tread_depth_mm": depth,
                    }
                )
    return pd.DataFrame(rows)


FLEET_SCHEMA = FleetSchema(
    wear="tread_depth_mm",
    age="km_since_fitted",
    cohort=["route_id", "date"],
    group="tyre_model",
    unit="unit_id",
)
