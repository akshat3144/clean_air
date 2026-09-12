/**
 * The contract between the Python pipeline and this app.
 *
 * Mirrors `src/cleanair/artifacts/schema.py`. Python is the source of truth;
 * if you change one, change both. A test on the Python side checks that the
 * generated JSON carries exactly the keys declared here.
 *
 * FROZEN as of v1. Additive changes only — adding an optional field is fine,
 * renaming or retyping one is not.
 *
 * Two things here come out of the Step 1 gate and are worth knowing before you
 * build against them:
 *
 * 1. Degradation is keyed on the PHYSICAL compound (C1–C5), not on the
 *    HARD/MEDIUM/SOFT label. Pirelli nominates three of C1–C5 per weekend, so
 *    the labels are relative — a "HARD" at Monaco is softer rubber than a
 *    "SOFT" at Suzuka. `label` is carried alongside because that is what people
 *    say out loud, but never group by it.
 *
 * 2. Every result carries `context`: practice or race. They genuinely differ.
 *    In races drivers manage soft tyres hard enough to flatten measured
 *    degradation; in practice the physical ordering shows up. That is a
 *    finding, not noise, so the UI should always say which one it is showing.
 */

export type Compound = "C1" | "C2" | "C3" | "C4" | "C5";
export type Label = "HARD" | "MEDIUM" | "SOFT";
export type Context = "practice" | "race";

/** Files fetched from /data/. Same list as schema.FILES on the Python side. */
export const ARTIFACT_FILES = [
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
] as const;

/** A value with an uncertainty band. Seconds unless the field says otherwise. */
export interface Interval {
  mean: number;
  lo: number;
  hi: number;
}

export const width = (i: Interval) => i.hi - i.lo;
export const overlaps = (a: Interval, b: Interval) => !(a.hi < b.lo || b.hi < a.lo);

// ---------------------------------------------------------------------------

export interface Meta {
  generated_at: string;
  schema_version: string;
  model_version: string;
  season: number;
  events: string[];
  n_laps_clean: number;
  n_long_run_laps: number;
  n_runs: number;
  n_drivers: number;
  fastf1_version: string;
  /** False for fixtures. Show a warning banner when false. */
  is_real: boolean;
}

// --- degradation.json : the brief's primary deliverable ---------------------

export interface CurvePoint {
  tyre_life: number;
  /** Lap time lost relative to a fresh tyre, seconds. */
  delta: Interval;
}

export interface CompoundCurve {
  compound: Compound;
  label: Label | null;
  context: Context;
  /** Degradation rate, seconds lost per lap. The headline number. */
  rate: Interval;
  curve: CurvePoint[];
  n_laps: number;
  n_runs: number;
  /** Events contributing. Length > 1 means pooled. */
  events: string[];
}

export interface DegradationArtifact {
  /** null when pooled across the season. */
  event: string | null;
  curves: CompoundCurve[];
  /** Fitted fuel effect, s/kg. Physics implies 0.030–0.035; the benchmark's
   *  model recovers only ~0.016 because its latent state absorbs the rest. */
  fuel_coefficient: Interval | null;
  track_evolution: Interval | null;
  /** P(softer of the pair degrades faster). Keys like "C3>C4". */
  separation: Record<string, number>;
  /** Pairs whose 95% intervals do not overlap. Keys like "C3|C4". */
  separated_pairs: string[];
}

// --- ablation.json : drives the Deconfound button ---------------------------

export interface AblationRow {
  compound: Compound;
  label: Label | null;
  /** Lap time regressed on stint lap alone. The naive approach. */
  naive: Interval;
  /** Fuel, traffic and track evolution removed, field pooled. */
  deconfounded: Interval;
  /** The benchmark's published figure, where one exists. */
  published: Interval | null;
}

export interface AblationArtifact {
  context: Context;
  rows: AblationRow[];
  /** Written by the pipeline so the caption cannot drift from the numbers. */
  caption: string;
}

// --- benchmark.json ---------------------------------------------------------

export interface BenchmarkScore {
  model: string;
  rmspe: number | null;
  crps: number | null;
  source: "published" | "reproduced" | "ours";
}

export interface RaceScore {
  race: string;
  ours_crps: number;
  theirs_crps: number;
  ours_wins: boolean;
}

export interface BenchmarkArtifact {
  austria_2025: BenchmarkScore[];
  season_2025: RaceScore[];
  n_wins: number;
  n_races: number;
  /** Season-wide mean CRPS. Their repo publishes only a season mean, not
   *  per-race numbers, so `season_2025` stays empty rather than being filled
   *  with a guess at their side of each race. These two means are the
   *  like-for-like comparison that can actually be made. */
  ours_season_crps: number | null;
  theirs_season_crps: number | null;
  /** Median race. One race dominates the mean: at Singapore 2025 Hamilton lost
   *  32s on a single green-flag lap while the field's median was unchanged. The
   *  lap stays in the test set; the median is shown so both readings are
   *  visible. */
  ours_season_crps_median: number | null;
  /** Race counts behind each mean. They differ, which is why both are here. */
  ours_season_races: number | null;
  theirs_season_races: number | null;
  /** Worst absolute gap between our CRPS and R's scoringRules on identical
   *  input. Backs the "same estimator" claim with a number. */
  r_crosscheck_max_diff: number | null;
}

// --- calibration.json / power.json ------------------------------------------

export interface CalibrationPoint {
  nominal: number;
  empirical: number;
  n: number;
}

export interface CalibrationArtifact {
  points: CalibrationPoint[];
  coverage_80: number;
  context: Context;
}

export interface PowerPoint {
  n_driver_stints: number;
  power: number;
}

export interface PowerArtifact {
  effect_size: number;
  points: PowerPoint[];
  n_for_80pct: number;
  /** What the benchmark had, for contrast. */
  benchmark_n: number;
  ours_n: number;
}

// --- transfer.json : practice to race ---------------------------------------

export interface TransferRow {
  event: string;
  compound: Compound;
  label: Label | null;
  predicted: Interval;
  /** null when the race has not happened yet. */
  actual: number | null;
  abs_error: number | null;
}

export interface TransferArtifact {
  rows: TransferRow[];
  /** Mean absolute error, s/lap. null when every row is a forecast. */
  mae: number | null;
  is_forecast: boolean;
}

// --- strategy.json ----------------------------------------------------------

export interface StrategyPlan {
  n_stops: number;
  compounds: Compound[];
  stint_lengths: number[];
  total_time: Interval;
}

export interface StrategyArtifact {
  event: string;
  pit_loss_s: number;
  race_laps: number;
  plans: StrategyPlan[];
  recommended_stops: number;
  rationale: string;
  confidence: number;
  optimal_stint: Record<string, Interval>;
}

// ---------------------------------------------------------------------------

// --- management.json : why softer compounds do not appear to degrade faster --

export interface ManagementRow {
  label: Label;
  n_cells: number;
  /** Race degradation over practice degradation. Below 1 = suppressed in races. */
  ratio: number;
  median_race: number;
  median_practice: number;
}

export interface ManagementStability {
  seasons: number[];
  n_cells: number;
  rho: number;
  p_one_sided: number;
  p_two_sided: number;
  ordered: boolean;
}

export interface ManagementArtifact {
  rows: ManagementRow[];
  n_cells: number;
  n_events: number;
  n_seasons: number;
  seasons: number[];
  rho: number;
  /** One-sided; the direction was predicted before the data was pulled. */
  p_one_sided: number;
  /** Two-sided, so the reader need not accept the one-sided choice. */
  p_two_sided: number;
  /** Omnibus alternative, which ignores the ordering we predicted. */
  p_kruskal: number;
  ordered: boolean;
  /** True only when BOTH sidedness conventions clear 0.05. */
  significant: boolean;
  verdict: string;
  /** How the effect moved as seasons were added. Ours shrank. */
  stability: ManagementStability[];
}

/* ---------------------------------------------------------------------------
 * playbook.json -- the per-event decision surface
 *
 * strategy.json answers one event, which is enough to prove the optimiser works
 * and not enough to be useful. This is the same layer for every event, plus the
 * two fields that make a call actionable: what it costs to be wrong
 * (crossover_pit_loss_s) and what the teams actually did (actual_stop_counts).
 * ------------------------------------------------------------------------- */

export interface PlaybookCompound {
  compound: Compound;
  /** This weekend's relative nomination. A strategist thinks in HARD/MEDIUM/
   *  SOFT; the model works in C1-C5. Both are carried so neither is guessed. */
  label: Label;
  rate: Interval;
  /** Best stint length in laps at this circuit's measured pit loss. */
  optimal_stint: number;
  /** Fitted degradation was not positive, so the optimiser could not use it. */
  excluded: boolean;
}

export interface PlaybookPlan {
  n_stops: number;
  compounds: Compound[];
  stint_lengths: number[];
  total_time: number;
  /** Seconds behind the best plan overall. Zero for the recommendation. */
  delta_s: number;
}

export interface PlaybookEvent {
  event: string;
  race_laps: number;
  pit_loss_s: number;
  /** Green-flag stops the pit loss was measured from. Two is a guess. */
  n_green_stops: number;
  compounds: PlaybookCompound[];
  plans: PlaybookPlan[];
  n_plans_enumerated: number;
  recommended_stops: number;
  /** Seconds to the best plan at a different stop count. Says if it is close. */
  margin_s: number;
  confidence: number;
  /** Pit loss at which the call flips. null means no flip between 15s and 35s,
   *  i.e. the answer is not close. Our pit loss is measured with error, so this
   *  is how much error the recommendation survives. */
  crossover_pit_loss_s: number | null;
  /** Cars per stop count, keyed by stop count as a string. */
  actual_stop_counts: Record<string, number>;
  actual_median_stops: number | null;
  /** Cars that never pitted, so retired before their first stop. Held out of
   *  the distribution above -- a DNF did not run a strategy -- but reported,
   *  because "five cars never pitted" says something about the race. */
  n_retired_before_stop: number;
}

export interface PlaybookArtifact {
  events: PlaybookEvent[];
  /** Assumed fresh-tyre pace gap between adjacent compounds, seconds. Surfaced
   *  because it is assumed rather than fitted -- the weakest input here. */
  pace_step_s: number;
}

export interface Bundle {
  meta: Meta;
  degradation: DegradationArtifact;
  ablation: AblationArtifact;
  benchmark: BenchmarkArtifact;
  calibration: CalibrationArtifact;
  power: PowerArtifact;
  transfer: TransferArtifact;
  strategy: StrategyArtifact;
  management: ManagementArtifact;
  playbook: PlaybookArtifact;
}

/** Official Pirelli colours, keyed by physical compound rather than by label. */
export const COMPOUND_COLOR: Record<Compound, string> = {
  C1: "#f2f2f2",
  C2: "#e8e0c8",
  C3: "#ffd500",
  C4: "#ff8c3b",
  C5: "#ff3b3b",
};

export async function loadBundle(base = "/data"): Promise<Bundle> {
  const entries = await Promise.all(
    ARTIFACT_FILES.map(async (name) => {
      const res = await fetch(`${base}/${name}.json`);
      if (!res.ok) throw new Error(`could not load ${name}.json (${res.status})`);
      return [name, await res.json()] as const;
    }),
  );
  return Object.fromEntries(entries) as unknown as Bundle;
}
