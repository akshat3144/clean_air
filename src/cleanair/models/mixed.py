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

import logging
import math
from dataclasses import dataclass, field

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
    #: Fresh-tyre pace of each compound relative to the field average at that
    #: moment, seconds. Softer compounds should be NEGATIVE (faster). Strategy
    #: needs these: without them an optimiser always picks the hardest tyre,
    #: because it only sees that hard tyres degrade more slowly.
    offsets: dict[str, Interval]
    n_laps: dict[str, int]
    n_runs: dict[str, int]
    events: dict[str, list[str]]
    context: str
    quadratic: bool
    converged: bool
    n_obs: int
    n_drivers: int
    #: How much each circuit's tyre-age slope differs from the global one,
    #: s/lap. Empty when circuit effects are off.
    #:
    #: One rate per compound for every track is false. Across the 13 circuits
    #: of 2026 the fitted slopes span 0.146 s/lap, from Barcelona at +0.076 to
    #: Suzuka at -0.070 -- WIDER than the 0.112 s/lap that separates C1 from C5.
    #: A model without this blames the rubber for what is really the track, and
    #: a pit call built on the global average is wrong everywhere. A
    #: likelihood-ratio test against the same model with no circuit slope gives
    #: LR = 385 on 1 df, p = 4e-86.
    circuit_slope: dict[str, float] = field(default_factory=dict)

    def rate_for(self, compound: str, event: str | None = None) -> float:
        """Degradation rate for a compound, at a circuit if we know one.

        The global rate answers "how does this compound behave in general".
        It is the wrong answer to "what do we do on Sunday at Monaco", which is
        what the strategy layer asks.
        """
        return self.rates[compound].mean + self.circuit_slope.get(event or "", 0.0)

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


log = logging.getLogger(__name__)


def fit_degradation(
    df: pd.DataFrame,
    *,
    quadratic: bool = True,
    context: str = "race",
    with_offsets: bool = True,
    circuit_effects: bool = False,
) -> Fit:
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

    # Compound main effects give the pace difference between compounds at equal
    # tyre age -- the "soft is faster when fresh" term. In the demeaned design
    # these are identified from cars on different compounds at the same lap.
    formula = "y ~ 0 + " + ("C + " if with_offsets else "") + "C:tl"
    formula += " + C:tl2" if quadratic else ""
    # Traffic gets a single shared coefficient, not one per compound: dirty air
    # costs the same lap time whatever tyre you are on, and a per-compound
    # traffic term would compete with the degradation slope for the same signal.
    #
    # Only include it if it actually varies. In a race where nobody ran in dirty
    # air the column is identically zero, and a constant regressor makes the
    # design matrix singular.
    if "tr" in df.columns and float(df["tr"].std() or 0.0) > 1e-9:
        formula += " + tr"
    if circuit_effects and df["event"].nunique() >= 4:
        # Let the tyre-age slope vary by circuit, with partial pooling: a track
        # with plenty of clean running gets its own estimate, a thin or
        # safety-car-shredded one is pulled toward the global mean instead of
        # shouting over it. That second property is the point -- Canada 2026
        # produced 65 C4 "runs" only because neutralisations chopped its stints
        # into 6-lap pieces, and under the old model that noise outvoted every
        # other circuit and dragged C4 from 0.09 to 0.02.
        #
        # Driver becomes a variance component inside the event group, named
        # "drv" rather than reusing "Driver": patsy reads a bare C(...) as its
        # categorical helper and our compound column is called C, so the
        # collision raises "Series object is not callable".
        df = df.assign(drv=df["Driver"].astype(str))
        model = smf.mixedlm(
            formula, df, groups=df["event"], re_formula="~0 + tl",
            vc_formula={"driver": "0 + drv"},
        )
    else:
        model = smf.mixedlm(formula, df, groups=df["Driver"])
    res = model.fit(method="lbfgs")

    params, ci = res.params, res.conf_int()

    def pull(prefix: str | None) -> dict[str, Interval]:
        """Collect per-compound coefficients. ``None`` pulls the main effects."""
        out = {}
        for name in params.index:
            if prefix is None:
                # A main effect looks like "C[C3]" with no interaction suffix.
                if ":" in name or not name.startswith("C["):
                    continue
            elif not name.endswith(f":{prefix}"):
                continue
            compound = name.split("[")[1].split("]")[0].replace("T.", "")
            lo, hi = float(ci.loc[name, 0]), float(ci.loc[name, 1])
            if not (math.isfinite(lo) and math.isfinite(hi)):
                # statsmodels returns a coefficient with a NaN standard error
                # when a parameter is not identified by the design. Dropping it
                # reports "we could not estimate this" instead of raising, which
                # used to take the whole pipeline down from one degenerate cell.
                log.warning(
                    "%s has no finite interval in the %s fit; not reporting it",
                    name, context,
                )
                continue
            out[compound] = Interval(mean=float(params[name]), lo=lo, hi=hi)
        return out

    circuit_slope: dict[str, float] = {}
    if circuit_effects:
        for ev, vals in (res.random_effects or {}).items():
            try:
                circuit_slope[str(ev)] = float(np.asarray(vals)[0])
            except (IndexError, TypeError, ValueError):
                continue

    counts = df.groupby("C", observed=True)
    return Fit(
        rates=pull("tl"),
        curvature=pull("tl2") if quadratic else {},
        offsets=pull(None) if with_offsets else {},
        n_laps={str(k): int(v) for k, v in counts.size().items()},
        n_runs={str(k): int(v) for k, v in counts["run_id"].nunique().items()},
        events={str(k): sorted(v) for k, v in counts["event"].unique().items()},
        context=context,
        quadratic=quadratic,
        converged=bool(res.converged),
        n_obs=len(df),
        n_drivers=df["Driver"].nunique(),
        circuit_slope=circuit_slope,
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
            # Practice centres within run, so a compound's level is differenced
            # away before the model sees it. Asking for offsets here yields
            # coefficients of exactly zero with NaN standard errors.
            with_offsets=False,
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

    # Normal approximation to the difference between two fitted rates. This is
    # frequentist -- the model is mixed-effects, not Bayesian -- so it is not a
    # posterior probability even though it is on a 0-1 scale.
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
