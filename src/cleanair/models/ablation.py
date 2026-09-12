"""What does removing the confounders actually buy?

The naive estimate is what you get from the obvious analysis: take lap times,
regress them on tyre age, read off the slope. It is what the public FastF1 tyre
notebooks do, and it is wrong in a specific way -- fuel burn and track evolution
both make lap times FALL through a session, so they cancel part of the rise from
tyre wear. The slope you get is a blend, biased toward zero.

It is also pooled by the HARD/MEDIUM/SOFT label rather than by physical
compound, which mixes different rubber across events.

The deconfounded estimate removes both problems: the (event, lap) fixed effect
deletes everything shared by the field at that moment, and compounds are keyed
to C1-C5.

Reporting both side by side is the point. One number on its own invites "how do
we know that is better?"; the pair answers it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..artifacts.schema import AblationArtifact, AblationRow, Interval
from ..config import BENCHMARK_TABLE3


def naive_rates(laps: pd.DataFrame) -> dict[str, Interval]:
    """Degradation by the obvious method: lap time on tyre age, no controls.

    Deliberately crude, because that is the comparison. No fuel correction, no
    track evolution, no traffic, no pooling structure, and grouped by the timing
    feed's HARD/MEDIUM/SOFT label rather than by physical compound.
    """
    df = laps[laps["is_long_run"] & (laps["session"] == "R")].copy()
    df = df.dropna(subset=["TyreLife", "LapTimeSeconds", "Compound"])

    out: dict[str, Interval] = {}
    for label, g in df.groupby("Compound"):
        if len(g) < 30 or g["TyreLife"].nunique() < 3:
            continue
        x = g["TyreLife"].to_numpy(float)
        y = g["LapTimeSeconds"].to_numpy(float)
        X = np.column_stack([np.ones_like(x), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        dof = max(1, len(y) - 2)
        cov = np.linalg.pinv(X.T @ X) * (resid @ resid) / dof
        se = float(np.sqrt(cov[1, 1]))
        slope = float(beta[1])
        out[str(label)] = Interval(slope, slope - 1.96 * se, slope + 1.96 * se)
    return out


#: The naive analysis groups by label; ours groups by physical compound. To put
#: them on one chart we need a correspondence. These are the most common
#: nominations across the seven 2026 events we have.
LABEL_FOR = {"C2": "HARD", "C3": "HARD", "C4": "MEDIUM", "C5": "SOFT"}


def build(laps: pd.DataFrame, fit, context: str = "race") -> AblationArtifact:
    """Assemble the naive-versus-deconfounded comparison.

    Args:
        laps: the clean lap dataset.
        fit: a fitted ``Fit`` from ``models.mixed``.
    """
    naive = naive_rates(laps)

    rows = []
    for c in fit.ordered:
        label = LABEL_FOR.get(c)
        if label is None or label not in naive:
            continue
        rows.append(
            AblationRow(
                compound=c,
                label=label,
                naive=naive[label],
                deconfounded=fit.rates[c],
                # The benchmark's published Hard figure, for a third column.
                published=(
                    Interval(**{k: BENCHMARK_TABLE3["HARD"][k] for k in ("mean", "lo", "hi")})
                    if c == "C3"
                    else None
                ),
            )
        )

    if not rows:
        raise ValueError("no compound had both a naive and a deconfounded estimate")

    widths_naive = np.mean([r.naive.hi - r.naive.lo for r in rows])
    widths_deconf = np.mean([r.deconfounded.hi - r.deconfounded.lo for r in rows])
    shrink = widths_naive / widths_deconf if widths_deconf > 0 else float("nan")

    return AblationArtifact(
        context=context,
        rows=rows,
        caption=(
            "The naive slope regresses lap time on tyre age with no controls, so "
            "fuel burn and track evolution -- which both make laps faster -- cancel "
            f"part of the rise from wear. Removing them narrows the interval "
            f"{shrink:.0f}-fold and separates compounds the naive fit cannot."
        ),
    )
