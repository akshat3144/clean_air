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
  safety_car: boolean;
  best_pit_lap: number;
  options: WhatIfOption[];
  compute_ms: number;
}

export interface WhatIfInput {
  event: string;
  current_lap: number;
  tyre_age: number;
  compound: string;
  pit_loss_s?: number;
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
