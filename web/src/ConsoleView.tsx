import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  getEvents,
  postWhatIf,
  type ApiCompound,
  type ApiEvent,
  type StrategyResult,
  type WhatIfResult,
} from "./api";
import { RacePlanView } from "./RacePlanView";
import { COMPOUND_COLOR, type Compound, type PlaybookArtifact } from "./types/artifacts";
import { useStrategy } from "./useStrategy";

/**
 * The strategy console.
 *
 * This replaced a read-only version of the same panels. The difference is that
 * every number here is computed by Python from the controls on the left, so the
 * screen can answer questions nobody precomputed -- which is the whole gap
 * between a tool and a slideshow.
 *
 * The controls are the ones a strategist would actually reach for, and each is
 * here because a measurement has error worth exploring rather than because a
 * slider looks impressive:
 *
 *   pit loss     measured from a handful of green stops, so it has real error
 *   safety car   changes what a stop costs, using a MEASURED fraction
 *   degradation  draggable across the model's own confidence interval
 *   race laps    a shortened race is a different problem
 *
 * If the API is unreachable the view says so plainly and points at the command
 * to start it, rather than showing an empty frame.
 */
export function ConsoleView({ playbook }: { playbook: PlaybookArtifact }) {
  const [events, setEvents] = useState<ApiEvent[] | null>(null);
  const [apiDown, setApiDown] = useState<string | null>(null);
  const [eventName, setEventName] = useState<string | null>(null);

  // controls
  const [pitLoss, setPitLoss] = useState<number | null>(null);
  const [raceLaps, setRaceLaps] = useState<number | null>(null);
  const [safetyCar, setSafetyCar] = useState(false);
  const [rates, setRates] = useState<Record<string, number>>({});

  useEffect(() => {
    const ac = new AbortController();
    getEvents(ac.signal)
      .then((rows) => {
        setEvents(rows);
        const first = rows.find((r) => r.ready) ?? rows[0];
        if (first) setEventName(first.event);
      })
      .catch((e) => {
        if (e?.name === "AbortError") return;
        setApiDown(e instanceof ApiError ? e.message : "cannot reach the strategy service");
      });
    return () => ac.abort();
  }, []);

  const event = events?.find((e) => e.event === eventName) ?? null;

  // Reset the controls to the event's own measurements whenever it changes, so
  // switching races never silently carries Monaco's pit loss to Spa.
  useEffect(() => {
    if (!event) return;
    setPitLoss(event.pit_loss_s ?? 22);
    setRaceLaps(event.race_laps);
    setSafetyCar(false);
    setRates({});
  }, [event?.event]);

  const input = useMemo(
    () =>
      event && pitLoss !== null && raceLaps !== null
        ? {
            event: event.event,
            pit_loss_s: pitLoss,
            race_laps: raceLaps,
            safety_car: safetyCar,
            ...(Object.keys(rates).length ? { rates } : {}),
          }
        : null,
    [event?.event, pitLoss, raceLaps, safetyCar, rates],
  );

  const { result, error, pending, approximate } = useStrategy(input);
  const dirty =
    !!event &&
    (pitLoss !== (event.pit_loss_s ?? 22) ||
      raceLaps !== event.race_laps ||
      safetyCar ||
      Object.keys(rates).length > 0);

  if (apiDown) {
    return <ApiDown message={apiDown} playbook={playbook} />;
  }
  if (!events) {
    return <p className="panel p-4 text-xs text-fg-dim">connecting to the strategy service…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {events.map((e) => (
          <button
            key={e.event}
            onClick={() => setEventName(e.event)}
            disabled={!e.ready}
            className={`rounded border px-2.5 py-1 text-xs transition-colors ${
              e.event === eventName
                ? "border-brand bg-brand/15 text-fg"
                : e.ready
                  ? "border-ink-600 text-fg-dim hover:border-ink-500 hover:text-fg"
                  : "border-ink-700 text-fg-faint"
            }`}
            title={e.ready ? undefined : "no measured pit loss for this event"}
          >
            {e.event.replace(" Grand Prix", "")}
          </button>
        ))}
        {dirty && (
          <button
            onClick={() => {
              if (!event) return;
              setPitLoss(event.pit_loss_s ?? 22);
              setRaceLaps(event.race_laps);
              setSafetyCar(false);
              setRates({});
            }}
            className="ml-2 rounded border border-signal-warn/40 px-2.5 py-1 text-xs text-signal-warn hover:bg-signal-warn/10"
          >
            reset to measured
          </button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Controls
            event={event}
            pitLoss={pitLoss}
            setPitLoss={setPitLoss}
            raceLaps={raceLaps}
            setRaceLaps={setRaceLaps}
            safetyCar={safetyCar}
            setSafetyCar={setSafetyCar}
            result={result}
          />
          {result && (
            <Tyres
              compounds={result.compounds}
              rates={rates}
              onChange={(c, v) => setRates((r) => ({ ...r, [c]: v }))}
              onClear={(c) =>
                setRates((r) => {
                  const { [c]: _drop, ...rest } = r;
                  return rest;
                })
              }
            />
          )}
        </div>

        <div className="space-y-4">
          {error ? (
            <p className="panel border-signal-bad/40 p-4 text-xs text-signal-bad">{error}</p>
          ) : result ? (
            <>
              <TheCall r={result} pending={pending} approximate={approximate} dirty={dirty} />
              <Alternatives r={result} />
              <WhatIf event={result.event} raceLaps={result.race_laps} compounds={result.compounds}
                      pitLoss={pitLoss} safetyCar={safetyCar} />
            </>
          ) : (
            <p className="panel p-4 text-xs text-fg-dim">computing…</p>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Fallback when the service is unreachable.
 *
 * It falls back to the PUBLISHED playbook rather than to an error screen. The
 * live console can answer questions nobody precomputed, and that is the point
 * of it -- but if the backend dies thirty seconds before a demo, showing the
 * seven precomputed races is enormously better than showing a stack trace. The
 * banner says which one you are looking at, so the fallback can never be
 * mistaken for the live thing.
 */
function ApiDown({ message, playbook }: { message: string; playbook: PlaybookArtifact }) {
  return (
    <div className="space-y-4">
      <section className="panel border-signal-warn/40 p-4">
        <h3 className="label text-signal-warn">
          strategy service unreachable — showing published results
        </h3>
        <p className="mt-2 text-xs leading-relaxed text-fg-dim">
          These are the precomputed calls for the events we have. The controls are gone because
          there is nothing to recompute with. Start the service to get them back:
        </p>
        <pre className="mt-2 overflow-x-auto rounded bg-ink-900 p-2 text-micro text-fg">
          uvicorn cleanair.api:app --reload --port 8000
        </pre>
        <p className="mt-2 text-micro text-fg-faint">{message}</p>
      </section>
      {playbook.events.length > 0 && <RacePlanView playbook={playbook} />}
    </div>
  );
}

function Controls({
  event,
  pitLoss,
  setPitLoss,
  raceLaps,
  setRaceLaps,
  safetyCar,
  setSafetyCar,
  result,
}: {
  event: ApiEvent | null;
  pitLoss: number | null;
  setPitLoss: (v: number) => void;
  raceLaps: number | null;
  setRaceLaps: (v: number) => void;
  safetyCar: boolean;
  setSafetyCar: (v: boolean) => void;
  result: StrategyResult | null;
}) {
  if (!event || pitLoss === null || raceLaps === null) return null;
  const measured = event.pit_loss_s;
  const x = result?.crossover_pit_loss_s ?? null;

  return (
    <section className="panel p-4">
      <span className="label">race state</span>

      <div className="mt-3">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-fg-dim">pit loss</span>
          <span className="num text-fg">{pitLoss.toFixed(1)}s</span>
        </div>
        <input
          type="range"
          min={15}
          max={35}
          step={0.5}
          value={pitLoss}
          onChange={(e) => setPitLoss(Number(e.target.value))}
          className="mt-1 w-full accent-brand"
        />
        <div className="flex justify-between text-micro text-fg-faint">
          <span className="num">15s</span>
          {measured !== null && (
            <button
              onClick={() => setPitLoss(measured)}
              className="num hover:text-fg"
              title="back to the measured value"
            >
              measured {measured.toFixed(1)}s
              {event.n_green_stops !== null && ` (${event.n_green_stops} stops)`}
            </button>
          )}
          <span className="num">35s</span>
        </div>
        {/* The crossover is the whole reason this slider exists: it says how
            much measurement error the call survives. */}
        {x !== null && (
          <p className="mt-1.5 text-micro leading-snug text-fg-faint">
            the call flips at <span className="num text-signal-warn">{x.toFixed(1)}s</span>
            {measured !== null && (
              <>
                {" "}
                — <span className="num">{Math.abs(x - measured).toFixed(1)}s</span> from the
                measurement
              </>
            )}
          </p>
        )}
      </div>

      <label className="mt-4 flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={safetyCar}
          onChange={(e) => setSafetyCar(e.target.checked)}
          className="accent-brand"
        />
        <span className={safetyCar ? "text-signal-warn" : "text-fg-dim"}>safety car is out</span>
      </label>
      {safetyCar && result?.safety_car_fraction && (
        <p className="mt-1 text-micro leading-snug text-fg-faint">
          a stop now costs{" "}
          <span className="num text-fg">{result.pit_loss_s.toFixed(1)}s</span> — the{" "}
          <span className="num">{result.safety_car_fraction}</span> fraction is measured from{" "}
          {result.pit_loss_by_status?.vsc?.n_stops ?? "?"} VSC stops. It is NOT measurable for a
          full safety car: 23 stops across two events, 15s apart.
        </p>
      )}

      <div className="mt-4">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-fg-dim">race laps</span>
          <span className="num text-fg">{raceLaps}</span>
        </div>
        <input
          type="range"
          min={Math.max(10, Math.round(event.race_laps * 0.4))}
          max={event.race_laps}
          step={1}
          value={raceLaps}
          onChange={(e) => setRaceLaps(Number(e.target.value))}
          className="mt-1 w-full accent-brand"
        />
        <div className="flex justify-between text-micro text-fg-faint">
          <span>shortened</span>
          <span className="num">full {event.race_laps}</span>
        </div>
      </div>

      {result && (
        <p className="mt-4 border-t border-ink-600 pt-2 text-micro text-fg-faint">
          <span className="num">{result.n_plans_enumerated.toLocaleString()}</span> plans enumerated
          in <span className="num">{result.compute_ms}ms</span>
        </p>
      )}
    </section>
  );
}

function Tyres({
  compounds,
  rates,
  onChange,
  onClear,
}: {
  compounds: ApiCompound[];
  rates: Record<string, number>;
  onChange: (c: string, v: number) => void;
  onClear: (c: string) => void;
}) {
  return (
    <section className="panel p-4">
      <div className="flex items-baseline justify-between">
        <span className="label">degradation</span>
        <span className="label">s/lap</span>
      </div>
      <p className="mt-1 text-micro leading-snug text-fg-faint">
        Drag to ask what happens if the tyre goes off faster than the model thinks. The bar is the
        fitted 95% interval; outside it you are overruling the model, and it says so.
      </p>

      <div className="mt-3 space-y-3">
        {compounds.map((c) => {
          const overridden = c.compound in rates;
          const value = overridden ? rates[c.compound] : c.rate;
          const outside = value < c.rate_lo || value > c.rate_hi;
          const max = Math.max(0.12, c.rate_hi * 1.6);
          return (
            <div key={c.compound}>
              <div className="flex items-baseline gap-2 text-xs">
                <span
                  className="num w-7 rounded px-1 text-center text-micro font-medium text-ink-900"
                  style={{ backgroundColor: COMPOUND_COLOR[c.compound as Compound] }}
                >
                  {c.compound}
                </span>
                <span className="label w-12">{c.label}</span>
                <span className={`num ${outside ? "text-signal-warn" : "text-fg"}`}>
                  {value.toFixed(4)}
                </span>
                {overridden && (
                  <button
                    onClick={() => onClear(c.compound)}
                    className="text-micro text-fg-faint hover:text-fg"
                  >
                    reset
                  </button>
                )}
                <span className="num ml-auto text-micro text-fg-faint">
                  {c.excluded ? "unusable" : `${c.optimal_stint} laps`}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={max}
                step={0.001}
                value={Math.min(value, max)}
                onChange={(e) => onChange(c.compound, Number(e.target.value))}
                className={`mt-1 w-full ${outside ? "accent-signal-warn" : "accent-brand"}`}
              />
              {/* The fitted interval, drawn under the slider on the same scale,
                  so "inside the model" is visible rather than a number to
                  remember. */}
              <div className="relative h-1">
                <div
                  className="absolute h-1 rounded-sm bg-fg-faint/40"
                  style={{
                    left: `${(Math.max(0, c.rate_lo) / max) * 100}%`,
                    width: `${((c.rate_hi - Math.max(0, c.rate_lo)) / max) * 100}%`,
                  }}
                />
              </div>
              {outside && (
                <p className="mt-0.5 text-micro text-signal-warn">
                  outside the fitted interval — this is your number, not the model&apos;s
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function TheCall({
  r,
  pending,
  approximate,
  dirty,
}: {
  r: StrategyResult;
  pending: boolean;
  approximate: boolean;
  dirty: boolean;
}) {
  const rec = r.plans.find((p) => p.n_stops === r.recommended_stops) ?? r.plans[0];
  const close = r.margin_s < 3;
  return (
    <section className="panel p-5">
      <div className="flex items-baseline justify-between">
        <span className="label">the call</span>
        <span className="label">
          {dirty ? (
            <span className="text-signal-warn">your inputs</span>
          ) : (
            "as measured"
          )}{" "}
          · {r.event.replace(" Grand Prix", "")} · {r.race_laps} laps
        </span>
      </div>

      <div className="mt-2 flex items-baseline gap-3">
        <span className="num text-5xl font-medium leading-none text-fg">
          {r.recommended_stops}
        </span>
        <span className="text-lg text-fg-dim">
          {r.recommended_stops === 1 ? "stop" : "stops"}
        </span>
        {pending && <span className="label ml-2 text-fg-faint">refining…</span>}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {rec.compounds.map((c, i) => (
          <span key={i} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-fg-faint">→</span>}
            <span
              className="num rounded px-2 py-1 text-xs font-medium text-ink-900"
              style={{ backgroundColor: COMPOUND_COLOR[c as Compound] }}
            >
              {c} × {rec.stint_lengths[i]}
            </span>
          </span>
        ))}
        {approximate && (
          <span className="label ml-2 text-fg-faint">
            stint lengths approximate until it settles
          </span>
        )}
      </div>

      <p className="mt-3 text-xs leading-relaxed text-fg-dim">
        <span className="num text-fg">{r.margin_s.toFixed(1)}s</span> clear of the best plan at any
        other stop count.
      </p>
      {close && (
        <p className="mt-2 rounded border border-signal-warn/30 bg-signal-warn/5 px-2.5 py-1.5 text-xs text-signal-warn">
          Under {r.race_laps} laps that margin is a coin flip leaning one way, not a decision.
        </p>
      )}
    </section>
  );
}

function Alternatives({ r }: { r: StrategyResult }) {
  const worst = Math.max(...r.plans.map((p) => p.delta_s), 1);
  return (
    <section className="panel p-4">
      <span className="label">what the alternatives cost</span>
      <div className="mt-3 space-y-2">
        {r.plans.map((p) => {
          const best = p.n_stops === r.recommended_stops;
          return (
            <div key={p.n_stops} className="flex items-center gap-2 text-xs">
              <span className={`num w-14 ${best ? "text-fg" : "text-fg-dim"}`}>
                {p.n_stops} stop{p.n_stops === 1 ? "" : "s"}
              </span>
              <div className="relative h-4 flex-1 overflow-hidden rounded-sm bg-ink-700">
                <div
                  className={`h-4 rounded-sm ${best ? "bg-brand/60" : "bg-ink-600"}`}
                  style={{ width: `${best ? 4 : Math.max(4, (p.delta_s / worst) * 100)}%` }}
                />
              </div>
              <span className={`num w-16 text-right ${best ? "text-signal-good" : "text-fg-dim"}`}>
                {best ? "best" : `+${p.delta_s.toFixed(1)}s`}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Pit now or in N laps -- the question a pit wall actually asks. */
function WhatIf({
  event,
  raceLaps,
  compounds,
  pitLoss,
  safetyCar,
}: {
  event: string;
  raceLaps: number;
  compounds: ApiCompound[];
  pitLoss: number | null;
  safetyCar: boolean;
}) {
  const usable = compounds.filter((c) => !c.excluded);
  const [lap, setLap] = useState(Math.round(raceLaps * 0.5));
  const [age, setAge] = useState(15);
  const [compound, setCompound] = useState(usable[0]?.compound ?? "");
  const [res, setRes] = useState<WhatIfResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!usable.some((c) => c.compound === compound)) {
      setCompound(usable[0]?.compound ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compounds]);

  useEffect(() => {
    setLap((l) => Math.min(l, raceLaps - 6));
  }, [raceLaps]);

  useEffect(() => {
    if (!compound || pitLoss === null) return;
    const ac = new AbortController();
    const t = window.setTimeout(() => {
      postWhatIf(
        {
          event,
          current_lap: lap,
          tyre_age: age,
          compound,
          pit_loss_s: pitLoss,
          safety_car: safetyCar,
          step: 3,
        },
        ac.signal,
      )
        .then((r) => {
          setRes(r);
          setErr(null);
        })
        .catch((e) => {
          if (e?.name === "AbortError") return;
          setRes(null);
          setErr(e instanceof ApiError ? e.message : "what-if failed");
        });
    }, 250);
    return () => {
      ac.abort();
      window.clearTimeout(t);
    };
  }, [event, lap, age, compound, pitLoss, safetyCar]);

  const worst = res ? Math.max(...res.options.map((o) => o.delta_s), 1) : 1;

  return (
    <section className="panel p-4">
      <div className="flex items-baseline justify-between">
        <span className="label">pit now, or later?</span>
        {res && <span className="label">{res.compute_ms}ms</span>}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
        <label>
          <span className="text-fg-dim">on lap</span>
          <input
            type="number"
            min={1}
            max={raceLaps - 6}
            value={lap}
            onChange={(e) => setLap(Number(e.target.value))}
            className="num mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1 text-fg"
          />
        </label>
        <label>
          <span className="text-fg-dim">tyre age</span>
          <input
            type="number"
            min={0}
            max={50}
            value={age}
            onChange={(e) => setAge(Number(e.target.value))}
            className="num mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1 text-fg"
          />
        </label>
        <label>
          <span className="text-fg-dim">on</span>
          <select
            value={compound}
            onChange={(e) => setCompound(e.target.value)}
            className="num mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1 text-fg"
          >
            {usable.map((c) => (
              <option key={c.compound} value={c.compound}>
                {c.compound} {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {err ? (
        <p className="mt-3 text-xs text-signal-warn">{err}</p>
      ) : res ? (
        <>
          <p className="mt-3 text-xs text-fg-dim">
            Best stop is lap <span className="num text-fg">{res.best_pit_lap}</span>
            {res.best_pit_lap === lap ? (
              <span className="text-signal-good"> — now</span>
            ) : (
              <>
                {" "}
                — <span className="num text-fg">{res.best_pit_lap - lap}</span> lap
                {res.best_pit_lap - lap === 1 ? "" : "s"} from now
              </>
            )}
            . A stop costs <span className="num text-fg">{res.pit_loss_s.toFixed(1)}s</span>.
          </p>
          <div className="mt-2 flex items-end gap-1">
            {res.options.map((o) => {
              const best = o.delta_s === 0;
              return (
                <div key={o.pit_on_lap} className="flex flex-1 flex-col items-center gap-1">
                  <span
                    className={`num text-micro ${best ? "text-signal-good" : "text-fg-faint"}`}
                  >
                    {best ? "best" : `+${o.delta_s.toFixed(1)}`}
                  </span>
                  <div
                    className={`w-full rounded-sm ${best ? "bg-signal-good/60" : "bg-ink-600"}`}
                    style={{ height: `${6 + (1 - o.delta_s / worst) * 34}px` }}
                    title={`pit on lap ${o.pit_on_lap}: +${o.delta_s.toFixed(2)}s`}
                  />
                  <span className="num text-micro text-fg-dim">{o.pit_on_lap}</span>
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-micro leading-snug text-fg-faint">
            Laps already run are held fixed; everything after the stop is re-optimised. Under a
            safety car only laps inside the window get the cheaper stop, which is what makes
            missing it cost anything.
          </p>
        </>
      ) : (
        <p className="mt-3 text-xs text-fg-dim">computing…</p>
      )}
    </section>
  );
}
