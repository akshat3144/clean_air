"""Fuel mass estimation.

Fuel is not published in the timing feed, so it has to be derived. The benchmark
paper assumes a linear ramp and we do the same in shape, but not in indexing.

Their code does this:

    fuel.kg <- seq(110, 1, length.out = length(retained_laps))

The ramp is spread across the *retained* laps, after pit and safety-car laps have
been dropped. So the fuel value attached to a lap stops tracking how much fuel is
actually in the car. On Hamilton's 2025 Austrian GP that misplaces up to 4.7 kg,
about 0.16 s of lap time at typical mass sensitivity.

We index to real ``LapNumber`` instead. Note that when we tested this against
their model it changed the result by ~0.002 s/lap -- their latent state absorbs
the error. So this is correctness for its own sake, not a fix for their null
result. Do not claim otherwise. See benchmark/README.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import FUEL_RACE_KG_2026, MASS_SENSITIVITY_S_PER_KG

#: Fuel remaining at the chequered flag. Teams optimise this close to zero, but
#: not to zero -- a car must return to the pits and give a fuel sample.
RESERVE_KG = 1.0


def race_fuel_kg(
    lap_number: pd.Series | np.ndarray,
    race_laps: int,
    start_kg: float = FUEL_RACE_KG_2026,
    reserve_kg: float = RESERVE_KG,
) -> np.ndarray:
    """Estimated fuel on board at the start of each lap, in kg.

    Linear burn from ``start_kg`` on lap 1 down to ``reserve_kg`` on the final
    lap, indexed to the true lap number so gaps in the lap series do not
    distort it.

    Args:
        lap_number: 1-based lap numbers. May have gaps.
        race_laps: Total scheduled laps for the race, not the number of rows.
        start_kg: Fuel at the start. Defaults to the 2026 load.
        reserve_kg: Fuel at the finish.

    Returns:
        Fuel mass per lap, same length as ``lap_number``.
    """
    if race_laps < 2:
        raise ValueError(f"race_laps must be at least 2, got {race_laps}")

    lap = np.asarray(lap_number, dtype=float)
    progress = (lap - 1.0) / (race_laps - 1.0)
    return start_kg - (start_kg - reserve_kg) * progress


def benchmark_fuel_kg(n_laps: int, start_kg: float = 110.0, end_kg: float = 1.0) -> np.ndarray:
    """The benchmark paper's fuel vector, reproduced exactly.

    Spread across ``n_laps`` retained rows rather than real race distance. Kept
    so we can reproduce their numbers and quantify the difference. Do not use
    this for our own model.
    """
    return np.linspace(start_kg, end_kg, n_laps)


def practice_fuel_kg(
    tyre_life: pd.Series | np.ndarray,
    start_kg: float,
    burn_per_lap: float = 1.6,
) -> np.ndarray:
    """Estimated fuel during a practice long run, in kg.

    Practice is harder than a race: we do not know the starting load. Teams run
    race-simulation stints at representative fuel, but the exact figure is
    private. So this returns fuel *relative* to the start of the run, and the
    absolute level gets absorbed by the driver/stint intercept in the model.

    That is the honest treatment. The model identifies the fuel *coefficient*
    from variation across drivers and runs, not from a known absolute mass.

    Args:
        tyre_life: Laps completed on this set, at the start of each lap.
        start_kg: Assumed load at the start of the run.
        burn_per_lap: kg consumed per lap. Around 1.6 is typical for 2026 given
            a 70 kg race load over a ~57 lap distance, but it varies by circuit.
    """
    life = np.asarray(tyre_life, dtype=float)
    return start_kg - burn_per_lap * (life - life.min())


def fuel_effect_seconds(
    fuel_kg: np.ndarray, s_per_kg: float = MASS_SENSITIVITY_S_PER_KG
) -> np.ndarray:
    """Lap time added by carrying ``fuel_kg``, in seconds.

    Only for sanity checks and plots. The model fits its own coefficient, and we
    compare the fitted value against ``MASS_SENSITIVITY_S_PER_KG`` as evidence
    that it learned real physics rather than noise.
    """
    return fuel_kg * s_per_kg
