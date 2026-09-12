/**
 * The contract between the Python pipeline and this app.
 *
 * DRAFT v1. Finalised in Step 2 of the plan, after the Step 1 gate tells us
 * whether the compounds separate. Until then the app runs on fixtures.
 *
 * Rules once frozen:
 *  - additive changes only (new optional fields are fine)
 *  - never rename or retype an existing field
 *  - the Python side owns generation, in src/cleanair/artifacts/schema.py
 *
 * Every file lives at /data/<name>.json, copied from data/artifacts/ at build.
 */

export type Compound = "HARD" | "MEDIUM" | "SOFT";

/** A value with a credible (or confidence) interval. Always seconds unless noted. */
export interface Interval {
  mean: number;
  lo: number; // 2.5th percentile by default
  hi: number; // 97.5th percentile by default
}

// ---------------------------------------------------------------------------
// meta.json — provenance. Shown in the footer so the demo is self-describing.
// ---------------------------------------------------------------------------

export interface Meta {
  generated_at: string; // ISO 8601
  season: number;
  model_version: string;
  events: string[]; // events the fit used
  n_laps_total: number;
  n_laps_clean: number;
  n_long_runs: number;
  n_drivers: number;
  fastf1_version: string;
  /** True when values came from the real pipeline, false for fixtures. */
  is_real: boolean;
}

// ---------------------------------------------------------------------------
// degradation.json — the brief's primary deliverable: clean tyre curves.
// ---------------------------------------------------------------------------

export interface DegradationPoint {
  tyre_life: number; // laps on this set
  pace: Interval; // predicted lap time delta vs fresh, seconds
}

export interface CompoundCurve {
  compound: Compound;
  /** Degradation rate, seconds lost per lap. The headline number. */
  rate: Interval;
  /** The curve itself, for plotting. */
  curve: DegradationPoint[];
  n_laps: number;
  n_stints: number;
}

export interface DegradationArtifact {
  event?: string; // omitted when pooled across events
  compounds: CompoundCurve[];
  /** Fitted fuel effect, s/kg. Checked against the 0.030-0.035 physical prior. */
  fuel_coefficient: Interval;
  /** Fitted track evolution, s/lap of session elapsed. */
  track_evolution: Interval;
  /** P(a softer compound degrades faster than a harder one), from the posterior. */
  separation_probability: Record<string, number>;
  /** Do the 95% intervals overlap? The falsifiable claim. */
  intervals_overlap: boolean;
}

// ---------------------------------------------------------------------------
// ablation.json — drives the "Deconfound" button. The money moment.
// ---------------------------------------------------------------------------

export interface AblationRow {
  compound: Compound;
  naive: Interval; // lap time regressed on stint lap only
  deconfounded: Interval; // fuel + track evolution removed, field pooled
}

export interface AblationArtifact {
  rows: AblationRow[];
  /** Benchmark's published values, for the third comparison column. */
  published?: AblationRow[];
}

// ---------------------------------------------------------------------------
// benchmark.json — like-for-like scoring against the published paper.
// ---------------------------------------------------------------------------

export interface BenchmarkScore {
  model: string;
  rmspe: number | null;
  crps: number | null;
  source: "published" | "reproduced" | "ours";
}

export interface BenchmarkArtifact {
  /** Austria 2025, their exact CV scheme. Direct comparison to their tables. */
  austria_2025: BenchmarkScore[];
  /** Their 19-race season set, from their repo. Gives a win rate. */
  season_2025?: {
    race: string;
    ours_crps: number;
    theirs_crps: number;
    ours_wins: boolean;
  }[];
}

// ---------------------------------------------------------------------------
// calibration.json — is the uncertainty honest?
// ---------------------------------------------------------------------------

export interface CalibrationArtifact {
  /** Nominal vs empirical coverage. Perfect calibration is the diagonal. */
  points: { nominal: number; empirical: number; n: number }[];
  /** Headline: coverage of the 80% interval. */
  coverage_80: number;
}

// ---------------------------------------------------------------------------
// power.json — how much data does separating the compounds actually need?
// ---------------------------------------------------------------------------

export interface PowerArtifact {
  /** True effect size being tested, s/lap. */
  effect_size: number;
  /** Probability of detecting it, by number of driver-stints. */
  points: { n_driver_stints: number; power: number }[];
  /** Stints needed for 80% power. */
  n_for_80pct: number;
  /** What the benchmark paper had, for contrast. */
  benchmark_n: number;
}

// ---------------------------------------------------------------------------
// transfer.json — practice to race. What the brief actually asks for.
// ---------------------------------------------------------------------------

export interface TransferArtifact {
  /** One row per event: fit on FP2, predict the race. */
  events: {
    event: string;
    compound: Compound;
    predicted: Interval;
    actual: number;
    abs_error: number;
  }[];
  /** Headline: mean absolute error, s/lap. */
  mae: number;
  /** Set when predicting a race that has not happened yet (the live demo). */
  is_forecast?: boolean;
}

// ---------------------------------------------------------------------------
// strategy.json — the decision the curves enable.
// ---------------------------------------------------------------------------

export interface StrategyArtifact {
  event: string;
  pit_loss_s: number;
  race_laps: number;
  /** Total race time by stop count, for the crossover chart. */
  plans: {
    n_stops: number;
    compounds: Compound[];
    stint_lengths: number[];
    total_time: Interval;
  }[];
  recommended: { n_stops: number; rationale: string; confidence: number };
  /** Optimal stint length per compound, given pit loss. */
  optimal_stint: Record<string, Interval>;
}

// ---------------------------------------------------------------------------
// replay/<event>.json — lap-by-lap, for the scrubber.
// ---------------------------------------------------------------------------

export interface ReplayLap {
  lap: number;
  driver: string;
  compound: Compound;
  tyre_life: number;
  lap_time: number | null;
  /** Model's degradation estimate using only laps up to here. */
  estimate: Interval;
  /** Recommendation as of this lap. */
  recommendation: "stay_out" | "box_now" | "box_window";
  track_status: string;
}

export interface ReplayArtifact {
  event: string;
  race_laps: number;
  laps: ReplayLap[];
  /** What the team actually did, for the counterfactual comparison. */
  actual_pit_laps: number[];
}

// ---------------------------------------------------------------------------
// Everything, as loaded by the app.
// ---------------------------------------------------------------------------

export interface Bundle {
  meta: Meta;
  degradation: DegradationArtifact;
  ablation: AblationArtifact;
  benchmark: BenchmarkArtifact;
  calibration: CalibrationArtifact;
  power: PowerArtifact;
  transfer: TransferArtifact;
  strategy: StrategyArtifact;
}
