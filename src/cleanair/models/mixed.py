"""The pooled mixed-effects degradation model.

Fast, interpretable, and it emits exactly the deliverable the brief asks for:
a per-compound degradation rate in seconds per lap, with an interval.

Fitted on the design matrices from ``design.py``, where the confounders have
already been removed by construction rather than by modelling them. That is
deliberate -- a fixed effect you subtract cannot be misspecified, and a fuel
coefficient you never estimate cannot be estimated wrongly.

A quadratic tyre-age term is included because the shape is an open question.
Step 1 found slopes steepen when restricted to young tyres, which suggests the
curve is concave, while the benchmark's time-varying model found the opposite.
Rather than assume either, we fit the curvature and report it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from ..artifacts.schema import CompoundCurve, CurvePoint, DegradationArtifact, Interval

#: Order matters: hardest to softest. Used for ordering output and for checking
#: whether the fitted rates are monotone in compound hardness.
C_ORDER = ("C1", "C2", "C3", "C4", "C5")


@dataclass
class Fit:
    """A fitted model plus everything needed to report it honestly."""

    rates: dict[str, Interval]
    curvature: dict[str, Interval]
    n_laps: dict[str, int]
    n_runs: dict[str, int]
    events: dict[str, list[str]]
    context: str
    quadratic: bool
    converged: bool
    n_obs: int
    n_drivers: int

    @property
    def ordered(self) -> list[str]:
        return [c for c in C_ORDER if c in self.rates]

    def is_monotone(self) -> bool:
        """Do softer compounds degrade faster, as physics expects?"""
        ks = self.ordered
        return all(self.rates[ks[i]].mean <= self.rates[ks[i + 1]].mean for i in range(len(ks) - 1))

    def separated_pairs(self) -> list[str]:
        """Adjacent compound pairs whose 95% intervals do not overlap."""
        ks = self.ordered
        return [
            f"{ks[i]}|{ks[i + 1]}"
            for i in range(len(ks) - 1)
            if not self.rates[ks[i]].overlaps(self.rates[ks[i + 1]])
        ]

    def rate_at(self, compound: str, tyre_age: float) -> float:
        """Instantaneous degradation rate at a given tyre age, s/lap.

        With a quadratic term the raw ``rates`` coefficient is the rate at age
        zero, which is not a number anyone wants -- a tyre at zero laps is not
        degrading yet. This is the useful one.
        """
        rate = self.rates[compound].mean
        quad = self.curvature.get(compound)
        return rate + 2 * quad.mean * tyre_age if quad else rate

    def total_loss(self, compound: str, n_laps: int) -> float:
        """Seconds lost across a whole stint of ``n_laps``.

        The most interpretable summary, and the one a race engineer would ask
        for: not a gradient, but how much time this tyre costs you by the end.
        """
        rate = self.rates[compound].mean
        quad = self.curvature.get(compound)
        return rate * n_laps + (quad.mean * n_laps**2 if quad else 0.0)


def fit_degradation(df: pd.DataFrame, *, quadratic: bool = True, context: str = "race") -> Fit:
    """Fit per-compound degradation on a prepared design frame.

    The design is already demeaned, so there is no intercept: ``0 +`` in the
    formula. Driver random effects soak up the fact that some drivers are
    simply quicker, which would otherwise leak into the tyre-age slope whenever
    quick drivers happen to run older tyres.

    Returns:
        A ``Fit``. ``rates`` are seconds lost per lap at the start of a stint;
        with the quadratic term, the instantaneous rate at tyre age *a* is
        ``rate + 2 * curvature * a``.
    """
    df = df.copy()
    df["C"] = pd.Categorical(df["C"], [c for c in C_ORDER if c in set(df["C"])])

    formula = "y ~ 0 + C:tl" + (" + C:tl2" if quadratic else "")
    model = smf.mixedlm(formula, df, groups=df["Driver"])
    res = model.fit(method="lbfgs")

    params, ci = res.params, res.conf_int()

    def pull(prefix: str) -> dict[str, Interval]:
        out = {}
        for name in params.index:
            if not name.endswith(f":{prefix}"):
                continue
            compound = name.split("[")[1].split("]")[0].replace("T.", "")
            out[compound] = Interval(
                mean=float(params[name]),
                lo=float(ci.loc[name, 0]),
                hi=float(ci.loc[name, 1]),
            )
        return out

    counts = df.groupby("C", observed=True)
    return Fit(
        rates=pull("tl"),
        curvature=pull("tl2") if quadratic else {},
        n_laps={str(k): int(v) for k, v in counts.size().items()},
        n_runs={str(k): int(v) for k, v in counts["run_id"].nunique().items()},
        events={str(k): sorted(v) for k, v in counts["event"].unique().items()},
        context=context,
        quadratic=quadratic,
        converged=bool(res.converged),
        n_obs=len(df),
        n_drivers=df["Driver"].nunique(),
    )


def fuel_sensitivity(
    laps: pd.DataFrame,
    s_per_kg_values=(0.030, 0.033, 0.035),
    **prepare_kw,
) -> pd.DataFrame:
    """Refit practice across the plausible range of the fuel coefficient.

    The practice model assumes a value for seconds-per-kg rather than fitting
    it, because it is not identifiable from lap times. This is how we show
    whether that assumption is doing any work. If the compound ordering holds
    across the range, the conclusion is safe. If it flips, we say so.
    """
    from .design import prepare

    rows = []
    for s in s_per_kg_values:
        # No quadratic: practice runs average seven laps, over which tyre age
        # and its square correlate at 0.99. The curvature is not identifiable
        # there and including it destabilises the linear term.
        fit = fit_degradation(
            prepare(laps, "practice", s_per_kg=s, **prepare_kw),
            context="practice",
            quadratic=False,
        )
        for c, iv in fit.rates.items():
            rows.append(
                {
                    "s_per_kg": s,
                    "compound": c,
                    "rate": iv.mean,
                    "lo": iv.lo,
                    "hi": iv.hi,
                    "monotone": fit.is_monotone(),
                }
            )
    return pd.DataFrame(rows)


def to_artifact(fit: Fit, max_life: int = 26, event: str | None = None) -> DegradationArtifact:
    """Package a fit into the frozen artifact format for the web app."""
    curves = []
    for c in fit.ordered:
        rate = fit.rates[c]
        quad = fit.curvature.get(c)

        points = []
        for life in range(1, max_life + 1):
            mean = rate.mean * life + (quad.mean * life**2 if quad else 0.0)
            # Widen with tyre age: extrapolating a slope compounds its error.
            half = (rate.hi - rate.lo) / 2 * life
            points.append(
                CurvePoint(
                    tyre_life=life,
                    delta=Interval(
                        mean=round(mean, 5),
                        lo=round(mean - half, 5),
                        hi=round(mean + half, 5),
                    ),
                )
            )

        curves.append(
            CompoundCurve(
                compound=c,
                label=None,  # pooled across events, where labels differ
                context=fit.context,
                rate=Interval(round(rate.mean, 5), round(rate.lo, 5), round(rate.hi, 5)),
                curve=points,
                n_laps=fit.n_laps.get(c, 0),
                n_runs=fit.n_runs.get(c, 0),
                events=fit.events.get(c, []),
            )
        )

    separation = {}
    ks = fit.ordered
    for i in range(len(ks) - 1):
        a, b = ks[i], ks[i + 1]
        ia, ib = fit.rates[a], fit.rates[b]
        # Normal approximation from the interval half-width.
        sa, sb = (ia.hi - ia.lo) / 3.92, (ib.hi - ib.lo) / 3.92
        se = float(np.hypot(sa, sb))
        z = (ib.mean - ia.mean) / se if se > 0 else 0.0
        separation[f"{a}>{b}"] = round(float(0.5 * (1 + math.erf(z / math.sqrt(2)))), 3)

    return DegradationArtifact(
        event=event,
        curves=curves,
        # Absorbed by construction in races; assumed, not fitted, in practice.
        fuel_coefficient=None,
        track_evolution=None,
        separation=separation,
        separated_pairs=fit.separated_pairs(),
    )
