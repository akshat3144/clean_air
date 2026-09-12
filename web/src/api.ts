/**
 * Client for the strategy API.
 *
 * Everything here is COMPUTED on request by Python. The static artifacts under
 * /data are still used for the evidence views, which are the same numbers every
 * time and have no inputs to vary; anything a user can change goes through this
 * file.
 *
 * The maths lives in Python once. There is deliberately no TypeScript
 * reimplementation of the optimiser: two copies of the same arithmetic can
 * disagree, and disagreeing in front of an audience is the one failure with no
 * recovery.
 */

/** Dev proxies /api to the local service; prod points at the deployed one. */
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export interface ApiEvent {
  event: string;
  race_laps: number;
  pit_loss_s: number | null;
  n_green_stops: number | null;
  allocation: Record<string, string>;
  ready: boolean;
}

export interface ApiCompound {
  compound: string;
  label: string | null;
  rate: number;
  rate_lo: number;
  rate_hi: number;
  optimal_stint: number;
  excluded: boolean;
  overridden: boolean;
}

export interface ApiPlan {
  n_stops: number;
  compounds: string[];
  stint_lengths: number[];
  total_time: number;
  delta_s: number;
}

export interface StrategyResult {
  event: string;
  race_laps: number;
  pit_loss_s: number;
  pit_loss_measured_s: number | null;
  n_green_stops: number | null;
  safety_car: boolean;
  safety_car_fraction: number | null;
  pit_loss_by_status: Record<string, { median_s: number; n_stops: number; ratio: number; usable?: boolean }> | null;
  compounds: ApiCompound[];
  plans: ApiPlan[];
  recommended_stops: number;
  margin_s: number;
  crossover_pit_loss_s: number | null;
  n_plans_enumerated: number;
  step: number;
  approximate: boolean;
  compute_ms: number;
}

export interface StrategyInput {
  event: string;
  pit_loss_s?: number;
  race_laps?: number;
  rates?: Record<string, number>;
  pace_step_s?: number;
  step?: number;
  safety_car?: boolean;
  neutralised_fraction?: number;
}

export interface WhatIfOption {
  pit_on_lap: number;
  laps_from_now: number;
  total_time: number;
  delta_s: number;
  plan: ApiPlan | null;
}

export interface WhatIfResult {
  event: string;
  current_lap: number;
  tyre_age: number;
  compound: string;
  pit_loss_s: number;
  race_laps: number;
  safety_car: boolean;
  best_pit_lap: number;
  /** The contiguous run of laps costing less than `window_tolerance_s` more
   *  than the best. Equal to best_pit_lap twice when the call is sharp. */
  window_from: number;
  window_to: number;
  window_tolerance_s: number;
  options: WhatIfOption[];
  compute_ms: number;
}

export interface WhatIfInput {
  event: string;
  current_lap: number;
  tyre_age: number;
  compound: string;
  pit_loss_s?: number;
  /** The same overrides /strategy takes. Both panels sit on one screen driven
   *  by one set of controls; sending fewer here makes them answer different
   *  races. */
  race_laps?: number;
  rates?: Record<string, number>;
  safety_car?: boolean;
  safety_car_laps?: number;
  neutralised_fraction?: number;
  horizon?: number;
  step?: number;
}

/** Thrown with the API's own message, so a 422 explains itself in the UI. */
export class ApiError extends Error {
  // Declared rather than a constructor parameter property: the build runs
  // tsc with erasableSyntaxOnly, which rejects the shorthand because it emits
  // runtime code instead of being purely erasable.
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    // FastAPI puts the reason in `detail`, and those reasons are written to be
    // read by a person -- "fewer than two usable compounds: a dry race needs
    // two". Surfacing it beats replacing it with "request failed".
    let detail = `${res.status}`;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep the status */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

/**
 * A reason a person can act on, rather than a status code.
 *
 * When the service is down the dev proxy answers 500 and a bare `${status}`
 * surfaced as "events 500" -- technically accurate and useless. A 502/503/500
 * from the proxy means nothing is listening; anything else is the service
 * itself answering unhappily, which is a different problem.
 */
function reason(res: Response, what: string): string {
  if (res.status >= 500) {
    return `nothing is listening on the strategy service (${what} returned ${res.status})`;
  }
  return `the strategy service refused the ${what} request (${res.status})`;
}

async function get<T>(path: string, what: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { signal });
  } catch (e) {
    // fetch rejects rather than resolving when the connection cannot be made
    // at all, which is the case with no proxy in front of it.
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError(`cannot reach the strategy service (${what})`, 0);
  }
  if (!res.ok) throw new ApiError(reason(res, what), res.status);
  return res.json() as Promise<T>;
}

export const health = (signal?: AbortSignal) =>
  get<{ ok: boolean; events: string[] }>("/health", "health", signal);

export const getEvents = (signal?: AbortSignal) =>
  get<ApiEvent[]>("/events", "events", signal);

export const postStrategy = (input: StrategyInput, signal?: AbortSignal) =>
  post<StrategyResult>("/strategy", input, signal);

export const postWhatIf = (input: WhatIfInput, signal?: AbortSignal) =>
  post<WhatIfResult>("/whatif", input, signal);

/* ---------------------------------------------------------------------------
 * The race that has not happened yet
 * ------------------------------------------------------------------------ */

export interface UpcomingSession {
  code: string;
  starts_utc: string;
  has_run: boolean;
}

export interface UpcomingRound {
  round_number: number;
  event: string;
  location: string;
  country: string;
  date_utc: string;
  sessions: UpcomingSession[];
  practice_sessions_run: string[];
  allocation: Record<string, string> | null;
  /** "pirelli" for a value we cited, "user" for one typed into the app. A typed
   *  number and a cited one are different kinds of claim. */
  allocation_source: string | null;
  history: {
    pit_loss_s: number | null;
    pit_loss_spread_s: number | null;
    race_laps: number | null;
    seasons: number[];
  } | null;
  ready_to_forecast: boolean;
  /** Plain sentences, not flags. This is what the screen shows when it has
   *  nothing else, and a boolean tells a user nothing they can act on. */
  blocked_by: string[];
}

export interface ForecastCompound {
  compound: string;
  label: string | null;
  rate: number;
  rate_lo: number;
  rate_hi: number;
  /** The uncorrected practice rate, before the practice-to-race factor. */
  practice_rate: number;
  optimal_stint: number;
  excluded: boolean;
  overridden: boolean;
  /** "measured" means this weekend put that tyre on a race simulation.
   *  "stand-in" means nobody did, and the rate was borrowed from other
   *  circuits and rescaled by this one's severity. The screen MUST NOT draw
   *  the two the same way. */
  source?: "measured" | "stand-in";
  /** Race-simulation runs and laps behind a measured rate. Zero on stand-ins. */
  n_runs?: number;
  n_laps?: number;
  /** How harsh this circuit is against the rest of the calendar, on the
   *  compounds it did run. Only set on stand-ins, which are scaled by it. */
  severity?: number | null;
}

/** One (session, compound) cell, before the sessions are blended. */
export interface SessionCell {
  session: string;
  compound: string;
  label: string | null;
  rate: number;
  se: number | null;
  n_runs: number;
  n_laps: number;
  weight: number;
  /** Under three runs. Shown, but never leaned on. */
  thin: boolean;
}

export interface SessionBreakdown {
  session: string;
  /** False when the weekend's FORMAT has no such session. A sprint weekend
   *  runs one practice session; its FP2 is not missing, it does not exist. */
  exists: boolean;
  has_run: boolean;
  weight: number;
  /** Signed clock-hours from this session's start to the race start. */
  hours_to_race: number | null;
  n_cells: number;
  n_race_sim_runs: number;
  n_race_sim_laps: number;
  cells: SessionCell[];
}

/** How each practice session scored against the races that have run. */
export interface SessionSkill {
  n_cells: number;
  correlation: number | null;
  factor: number | null;
  mae: number | null;
}

/** What the race actually did, where it has been run. */
export interface RaceActual {
  compound: string;
  label: string | null;
  rate: number;
  n_runs: number;
  n_laps: number;
}

export interface PracticeSessions {
  event: string;
  sessions: SessionBreakdown[];
  race_actual: RaceActual[];
  sprint_weekend: boolean;
  weights: Record<string, number>;
  weight_evidence: Record<string, SessionSkill>;
  allocation: Record<string, string> | null;
}

export interface ForecastResult {
  event: string;
  is_forecast: true;
  /** False when fewer than two compounds have a usable rate. The compound
   *  table and `reason` are still returned -- that is the useful part. */
  can_plan: boolean;
  reason?: string;
  /** Circuit inputs the PLAN is still waiting on. Everything else in this
   *  response is measured from practice and does not depend on them. */
  needs_inputs?: string[];
  race_laps: number | null;
  race_laps_source?: string;
  pit_loss_s: number | null;
  pit_loss_source?: string;
  pit_loss_spread_s?: number | null;
  history_seasons?: number[];
  practice_sessions: string[];
  /** A race degrades at roughly this fraction of its practice rate. Learned
   *  from other events, never from the one being predicted. */
  practice_to_race_factor: number;
  compounds: ForecastCompound[];
  plans?: ApiPlan[];
  recommended_stops?: number;
  margin_s?: number;
  crossover_pit_loss_s?: number | null;
  n_plans_enumerated?: number;
  approximate?: boolean;
  compute_ms: number;
}

export interface PollerState {
  enabled: boolean;
  running: boolean;
  last_tick: string | null;
  last_pull: string | null;
  last_error: string | null;
  pulls: number;
  failures: number;
  missing: string[];
  schedule_source: string;
  next_tick_seconds: number;
}

export const getUpcoming = (limit = 3, signal?: AbortSignal) =>
  get<UpcomingRound[]>(`/upcoming?limit=${limit}`, "upcoming", signal);

export const getPracticeSessions = (event: string, signal?: AbortSignal) =>
  get<PracticeSessions>(
    `/practice-sessions?event=${encodeURIComponent(event)}`,
    "practice sessions",
    signal,
  );

export const getPoller = (signal?: AbortSignal) =>
  get<PollerState>("/poller", "poller", signal);

export const postForecast = (
  input: { event: string; pit_loss_s?: number; race_laps?: number; step?: number },
  signal?: AbortSignal,
) => post<ForecastResult>("/forecast", input, signal);

export async function putAllocation(
  event: string,
  compounds: Record<string, string>,
  signal?: AbortSignal,
): Promise<unknown> {
  const res = await fetch(`${BASE}/allocation/${encodeURIComponent(event)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ compounds }),
    signal,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep the status */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

export interface AllocationRow {
  event: string;
  season: number;
  /** Label -> C number, e.g. {"HARD": "C3", "MEDIUM": "C4", "SOFT": "C5"}. */
  compounds: Record<string, string>;
  /** "pirelli" for a cited value, "user" for one entered in the app. */
  source: string;
  updated_at: string | null;
}

export const getAllocations = (signal?: AbortSignal) =>
  get<AllocationRow[]>("/allocation", "allocation", signal);

/** Clear a nomination entered in the app, reverting to the cited value if any. */
export async function clearAllocation(event: string, signal?: AbortSignal): Promise<unknown> {
  const res = await fetch(`${BASE}/allocation/${encodeURIComponent(event)}`, {
    method: "DELETE",
    signal,
  });
  if (!res.ok) throw new ApiError(reason(res, "clear allocation"), res.status);
  return res.json();
}
