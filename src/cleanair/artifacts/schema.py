"""The contract between the pipeline and the web app.

The pipeline writes JSON here; the web app reads it and never calls Python.
`web/src/types/artifacts.ts` mirrors these shapes and must be kept in sync.

FROZEN as of v1. Additive changes only:
  - adding an optional field is fine
  - renaming, removing or retyping a field is not
Anything else means rebuilding the front end, which is the thing this contract
exists to prevent.

Two decisions here come straight out of the Step 1 gate.

1. Degradation is keyed on the PHYSICAL compound (C1-C5), not on the HARD /
   MEDIUM / SOFT label. Pirelli nominates three of C1-C5 per weekend and the
   labels are relative to that nomination, so a "HARD" at Monaco is softer
   rubber than a "SOFT" at Suzuka. Keying on the label pools different tyres.
   The label is carried alongside, because that is what people say out loud.

2. Every degradation result carries `context`: practice or race. They are not
   the same number. In races drivers manage soft tyres hard enough to flatten
   measured degradation; in practice, where they are measuring the tyre, the
   physical ordering appears. That difference is a finding, not noise, so the
   format has to be able to express both.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ..config import ARTIFACTS

SCHEMA_VERSION = "1.0.0"

Compound = Literal["C1", "C2", "C3", "C4", "C5"]
Label = Literal["HARD", "MEDIUM", "SOFT"]
Context = Literal["practice", "race"]

#: Filenames the web app fetches from /data/. Kept here so the publish script
#: and the tests agree on one list.
FILES = (
    "meta",
    "degradation",
    "ablation",
    "benchmark",
    "calibration",
    "power",
    "transfer",
    "strategy",
    "management",
    "playbook",
)


@dataclass
class Interval:
    """A value with an uncertainty band. Seconds unless the field says otherwise."""

    mean: float
    lo: float  # 2.5th percentile by default
    hi: float  # 97.5th percentile by default

    def __post_init__(self) -> None:
        if not (self.lo <= self.mean <= self.hi):
            raise ValueError(f"interval not ordered: lo={self.lo} mean={self.mean} hi={self.hi}")

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def overlaps(self, other: Interval) -> bool:
        return not (self.hi < other.lo or other.hi < self.lo)


# ---------------------------------------------------------------------------
# meta.json
# ---------------------------------------------------------------------------


@dataclass
class Meta:
    """Provenance. Rendered in the footer so the demo describes itself."""

    generated_at: str
    schema_version: str
    model_version: str
    season: int
    events: list[str]
    n_laps_clean: int
    n_long_run_laps: int
    n_runs: int
    n_drivers: int
    fastf1_version: str
    #: False for fixtures. The app shows a warning banner when this is False,
    #: so we can never demo fake numbers by accident.
    is_real: bool = False

    @staticmethod
    def now(**kw) -> Meta:
        return Meta(
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            schema_version=SCHEMA_VERSION,
            **kw,
        )


# ---------------------------------------------------------------------------
# degradation.json  -- the brief's primary deliverable
# ---------------------------------------------------------------------------


@dataclass
class CurvePoint:
    tyre_life: int
    #: Lap time lost relative to a fresh tyre, seconds.
    delta: Interval


@dataclass
class CompoundCurve:
    compound: Compound
    #: What this compound was called at this event. None when pooled.
    label: Label | None
    context: Context
    #: Degradation rate, seconds lost per lap. The headline number.
    rate: Interval
    curve: list[CurvePoint]
    n_laps: int
    n_runs: int
    #: Events contributing to this estimate. Length > 1 means pooled.
    events: list[str]


@dataclass
class DegradationArtifact:
    #: None when pooled across the season.
    event: str | None
    curves: list[CompoundCurve]
    #: Fitted fuel effect, s/kg. Checked against the 0.030-0.035 physical prior;
    #: the benchmark's model recovers only ~0.016 because its latent state
    #: absorbs the rest. None where the design absorbs fuel non-parametrically.
    fuel_coefficient: Interval | None
    #: Fitted track evolution, s per lap of session elapsed.
    track_evolution: Interval | None
    #: P(softer of the pair degrades faster). Keys like "C3>C4".
    #:
    #: NOT a posterior probability. The model is mixed-effects, so what we have
    #: are confidence intervals; this is a normal approximation to the
    #: difference between two fitted rates. It reads like a Bayesian quantity and
    #: is not one, which is worth saying rather than letting a reader assume.
    separation: dict[str, float] = field(default_factory=dict)
    #: Pairs whose 95% intervals do not overlap. Keys "C3|C4".
    separated_pairs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ablation.json  -- drives the Deconfound button
# ---------------------------------------------------------------------------


@dataclass
class AblationRow:
    compound: Compound
    label: Label | None
    #: Lap time regressed on stint lap alone. What the naive approach gives.
    naive: Interval
    #: Fuel, traffic and track evolution removed, field pooled.
    deconfounded: Interval
    #: The benchmark's published figure, where one exists for comparison.
    published: Interval | None = None


@dataclass
class AblationArtifact:
    context: Context
    rows: list[AblationRow]
    #: One sentence the UI shows under the chart, written by the pipeline so the
    #: caption can never drift from the numbers it describes.
    caption: str = ""


# ---------------------------------------------------------------------------
# benchmark.json
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkScore:
    model: str
    rmspe: float | None
    crps: float | None
    #: published = from their paper; reproduced = we ran their code; ours = us.
    source: Literal["published", "reproduced", "ours"]


@dataclass
class RaceScore:
    race: str
    ours_crps: float
    theirs_crps: float
    ours_wins: bool


@dataclass
class BenchmarkArtifact:
    #: Austria 2025 under their exact CV scheme -- direct comparison to Table 1/2.
    austria_2025: list[BenchmarkScore]
    #: Their 19-race season set, which never appeared in the paper. Lets us
    #: report a win rate rather than a single number.
    season_2025: list[RaceScore] = field(default_factory=list)
    n_wins: int = 0
    n_races: int = 0
    #: Season-wide mean CRPS, ours and theirs. Their repo reports only a season
    #: mean, not per-race numbers, so a per-race win table cannot be built
    #: honestly -- these two means are the like-for-like comparison we can make.
    ours_season_crps: float | None = None
    theirs_season_crps: float | None = None
    #: Median race, carried next to the mean because one race dominates the
    #: mean: at Singapore 2025 Hamilton lost 32 seconds on a single green-flag
    #: lap while the field's median was unchanged, so it was his car, not the
    #: track. The lap is kept in the test set -- dropping the laps we predict
    #: worst would flatter the score -- and the median is shown so the reader
    #: can see both the typical race and the damage one bad one does.
    ours_season_crps_median: float | None = None
    #: Race counts behind each mean. They differ (they had 19, we scored 18),
    #: which is exactly why both are carried rather than just the difference.
    ours_season_races: int | None = None
    theirs_season_races: int | None = None
    #: Largest absolute gap between our CRPS and R's scoringRules on identical
    #: input. Backs the "same estimator" claim with a number instead of a word.
    r_crosscheck_max_diff: float | None = None


# ---------------------------------------------------------------------------
# calibration.json / power.json
# ---------------------------------------------------------------------------


@dataclass
class CalibrationPoint:
    nominal: float
    empirical: float
    n: int


@dataclass
class CalibrationArtifact:
    points: list[CalibrationPoint]
    coverage_80: float
    context: Context = "race"


@dataclass
class PowerPoint:
    n_driver_stints: int
    power: float


@dataclass
class PowerArtifact:
    """How much data separating two compounds actually needs.

    Answers the open question the benchmark leaves, and tells us whether our own
    result is real or lucky.
    """

    effect_size: float
    points: list[PowerPoint]
    n_for_80pct: int
    #: What the benchmark had, for contrast. They had 3 stints.
    benchmark_n: int
    ours_n: int


# ---------------------------------------------------------------------------
# transfer.json  -- practice to race, what the brief asks for
# ---------------------------------------------------------------------------


@dataclass
class TransferRow:
    event: str
    compound: Compound
    label: Label | None
    predicted: Interval
    #: None when the race has not happened yet (the live forecast).
    actual: float | None
    abs_error: float | None


@dataclass
class TransferArtifact:
    rows: list[TransferRow]
    #: Mean absolute error, s/lap. None when every row is a forecast.
    mae: float | None
    #: True when this is a prediction for a race that has not run.
    is_forecast: bool = False


# ---------------------------------------------------------------------------
# strategy.json
# ---------------------------------------------------------------------------


@dataclass
class StrategyPlan:
    n_stops: int
    compounds: list[Compound]
    stint_lengths: list[int]
    total_time: Interval


@dataclass
class StrategyArtifact:
    event: str
    pit_loss_s: float
    race_laps: int
    plans: list[StrategyPlan]
    recommended_stops: int
    rationale: str
    confidence: float
    #: Optimal stint length per compound given the pit loss. Keyed by C-number.
    optimal_stint: dict[str, Interval] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# playbook.json -- the per-event decision surface
# ---------------------------------------------------------------------------
#
# strategy.json holds one event, because it was built to demonstrate that the
# optimiser works. That is a proof, not a product: nobody can use a tool that
# answers for Hungary when they are at Monza. This artifact is the same layer
# computed for every event we have, plus the two things that make a
# recommendation usable rather than merely correct -- what it costs to be wrong,
# and what the teams actually did.


@dataclass
class PlaybookCompound:
    """One nominated tyre at one event."""

    compound: Compound
    #: The weekend's relative nomination. Included because a strategist thinks
    #: in HARD/MEDIUM/SOFT while the model works in C1-C5, and conflating the
    #: two across events is the error this whole project exists to avoid.
    label: Label
    rate: Interval
    #: Best stint length in laps at this circuit's measured pit loss.
    optimal_stint: int
    #: True when the fitted degradation was not positive, so the optimiser was
    #: not allowed to use it. An optimiser handed a tyre that never wears will
    #: run it to the flag.
    excluded: bool = False


@dataclass
class PlaybookPlan:
    n_stops: int
    compounds: list[Compound]
    stint_lengths: list[int]
    total_time: float
    #: Seconds behind the best plan overall. Zero for the recommendation.
    delta_s: float


@dataclass
class PlaybookEvent:
    event: str
    race_laps: int
    pit_loss_s: float
    #: Green-flag stops the pit loss was measured from. A pit loss from two
    #: stops is a guess wearing a decimal point.
    n_green_stops: int
    compounds: list[PlaybookCompound]
    #: Best plan at each stop count, cheapest first.
    plans: list[PlaybookPlan]
    n_plans_enumerated: int
    recommended_stops: int
    #: Seconds between the recommendation and the best plan at a different stop
    #: count. This is the number that says whether the call is close.
    margin_s: float
    confidence: float
    #: Pit loss at which the recommendation would flip, in seconds. None when
    #: no flip occurs between 15s and 35s, meaning the answer is not close.
    #: This is the sensitivity a strategist actually needs: our pit loss is
    #: measured with error, and this says how much error the call survives.
    crossover_pit_loss_s: float | None = None
    #: How many cars ran each stop count, keyed by stop count as a string.
    #: The recommendation is checkable against it.
    actual_stop_counts: dict[str, int] = field(default_factory=dict)
    actual_median_stops: int | None = None
    #: Cars that never pitted. A dry race requires two compounds, so these
    #: retired before their first stop -- they did not run a strategy, and
    #: counting them among the strategies would drag the median. Reported
    #: separately rather than dropped silently.
    n_retired_before_stop: int = 0


@dataclass
class PlaybookArtifact:
    events: list[PlaybookEvent]
    #: Pace gap assumed between adjacent compounds on fresh tyres, seconds.
    #: Surfaced because it is assumed rather than fitted, and it is the weakest
    #: input in the layer -- a reader should be able to see it without reading
    #: the source.
    pace_step_s: float


# ---------------------------------------------------------------------------
# management.json -- why softer compounds do not appear to degrade faster
# ---------------------------------------------------------------------------


@dataclass
class ManagementRow:
    label: Label
    n_cells: int
    #: Race degradation divided by practice degradation, median across cells.
    #: Below 1 means the race number is suppressed relative to practice.
    ratio: float
    median_race: float
    median_practice: float


@dataclass
class ManagementArtifact:
    """Evidence that drivers nurse softer tyres in races.

    Keyed on the HARD/MEDIUM/SOFT label rather than the physical compound, and
    that is correct here even though it is wrong everywhere else: within one
    event the label is the same tyre in practice and in the race, which is all a
    ratio needs.
    """

    rows: list[ManagementRow]
    n_cells: int
    n_events: int
    n_seasons: int
    seasons: list[int]
    #: Spearman correlation between compound softness and the ratio.
    rho: float
    #: One-sided, because the direction was predicted before the data was pulled.
    p_one_sided: float
    #: Two-sided as well, so the reader need not accept the one-sided choice.
    p_two_sided: float
    #: The omnibus alternative, which ignores the ordering we predicted.
    p_kruskal: float
    ordered: bool
    #: True only when BOTH sidedness conventions clear 0.05.
    significant: bool
    verdict: str
    #: How the effect moved as seasons were added. Shrinking with more data is
    #: worth showing rather than hiding.
    stability: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def write(name: str, artifact, out_dir: Path | None = None) -> Path:
    """Write one artifact to ``<out_dir>/<name>.json``.

    Rejects unknown names so a typo cannot silently produce a file the web app
    will never fetch.
    """
    if name not in FILES:
        raise ValueError(f"unknown artifact {name!r}; expected one of {FILES}")

    out_dir = out_dir or ARTIFACTS
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(asdict(artifact), indent=2), encoding="utf-8")
    return path


def write_all(bundle: dict, out_dir: Path | None = None) -> list[Path]:
    """Write a full set. Every file in FILES must be present."""
    missing = set(FILES) - set(bundle)
    if missing:
        raise ValueError(f"bundle is missing {sorted(missing)}")
    return [write(name, bundle[name], out_dir) for name in FILES]
