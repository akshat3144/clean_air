import { AnimatePresence, motion } from "framer-motion";
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
import { DegradationHorizon } from "./DegradationHorizon";
import { PracticeSessionsPanel } from "./PracticeSessionsPanel";
import { RacePlanView } from "./RacePlanView";
import { COMPOUND_COLOR, type Compound, type PlaybookArtifact } from "./types/artifacts";
import { Animated, Dot, EASE, Panel, Pill, Row, Skeleton, StintAllocation } from "./ui";
import { useStrategy } from "./useStrategy";

/**
 * The strategy console.
 *
 * Every number here is computed by Python from the controls on the left, so the
 * screen can answer questions nobody precomputed. That is the difference
 * between a tool and a slideshow.
 *
 * ON THE LAYOUT
 *
 * The first version made all five panels identical -- `panel p-4`, a label,
 * some content -- which meant the recommendation had no more presence than the
 * footnote about the assumed pace gap. The call is now a hero panel with an
 * 88px readout and everything else is explicitly support. If a viewer takes one
 * thing off this screen it should be the number of stops.
 *
 * ON THE MOTION
 *
 * Only changes that already happened get animated, and only where the change
 * carries meaning: the stop count flipping, the crossover marker crossing the
 * measured pit loss, a value replacing another. Nothing spins to imply work.
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

  // Reset to the event's own measurements whenever it changes, so switching
  // races never silently carries Monaco's pit loss to Spa.
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

  const { result, error, pending, approximate, switching } = useStrategy(input);
  const dirty =
    !!event &&
    (pitLoss !== (event.pit_loss_s ?? 22) ||
      raceLaps !== event.race_laps ||
      safetyCar ||
      Object.keys(rates).length > 0);

  const reset = () => {
    if (!event) return;
    setPitLoss(event.pit_loss_s ?? 22);
    setRaceLaps(event.race_laps);
    setSafetyCar(false);
    setRates({});
  };

  if (apiDown) return <ApiDown message={apiDown} playbook={playbook} />;
  if (!events) return <Booting />;

  return (
    <div className="space-y-5">
      <EventBar events={events} active={eventName} onPick={setEventName} dirty={dirty} onReset={reset} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Controls
            event={event}
            pitLoss={pitLoss}
            setPitLoss={setPitLoss}
            raceLaps={raceLaps}
            setRaceLaps={setRaceLaps}
            safetyCar={safetyCar}
            setSafetyCar={setSafetyCar}
            result={result}
            pending={pending}
          />
          {result ? (
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
          ) : (
            <Panel title="degradation">
              <div className="space-y-3">
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
              </div>
            </Panel>
          )}
        </div>

        <div className="space-y-5">
          {error ? (
            <Panel className="border-signal-bad/40">
              <p className="text-base text-signal-bad">{error}</p>
            </Panel>
          ) : result ? (
            <>
              <TheCall r={result} pending={pending} approximate={approximate} dirty={dirty} />
              {/* What staying out costs, in seconds rather than as a slope.
                  This is the question the brief asks in these words -- how
                  does the tyre perform after 5, 10, 15 laps -- and the console
                  previously answered it only as a rate. */}
              <Panel title="what the tyre costs you" meta="seconds lost">
                <DegradationHorizon
                  rows={result.compounds}
                  note="Seconds slower than the same tyre fresh, at this circuit's fitted rate, with the 95% band beneath."
                />
              </Panel>
              <div className="grid gap-5 lg:grid-cols-2">
                <Alternatives r={result} />
                <Headroom r={result} />
              </div>
              <WhatIf
                event={result.event}
                raceLaps={result.race_laps}
                compounds={result.compounds}
                pitLoss={pitLoss}
                safetyCar={safetyCar}
                rates={rates}
              />
              {/* The same panel the Next Race tab carries, on the screen the
                  pit wall actually works from. Here the race HAS run, so it
                  also shows what Friday's sessions said against what Sunday
                  did -- which is the post-race validation the brief asks for,
                  and the evidence behind the practice-to-race factor the
                  forecast leans on. It is informational: this tab optimises on
                  the MEASURED race rate, not on practice. */}
              <PracticeSessionsPanel event={result.event} />
            </>
          ) : (
            // Named, not a grey rectangle. Switching circuit clears the plan
            // -- the previous one described a different race -- and a bare
            // skeleton then reads as "broken" rather than "working". Saying
            // which event is being computed also proves the click registered.
            <Computing event={eventName} switching={switching} />
          )}
        </div>
      </div>
    </div>
  );
}

/** What the console shows while it has no plan to show. */
function Computing({ event, switching }: { event: string | null; switching: boolean }) {
  return (
    <>
      <Panel hero>
        <div className="flex items-center gap-3">
          <Dot tone="warn" />
          <span className="title">
            {switching && event ? `computing ${event}` : "computing"}
          </span>
        </div>
        <p className="mt-3 text-base leading-relaxed text-fg-dim">
          {switching
            ? "Enumerating every legal strategy for this circuit. The last plan has been cleared because it was for a different race."
            : "Enumerating every legal strategy for these inputs."}
        </p>
        <div className="mt-5 space-y-3">
          <Skeleton className="h-20 w-48" />
          <Skeleton className="h-8 w-64" />
        </div>
      </Panel>
      <Skeleton className="h-36 rounded-lg" />
    </>
  );
}

function Booting() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-9 w-full max-w-2xl rounded-md" />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <Skeleton className="h-64 rounded-lg" />
        <div className="space-y-5">
          <Skeleton className="h-48 rounded-xl" />
          <Skeleton className="h-36 rounded-lg" />
        </div>
      </div>
    </div>
  );
}

function EventBar({
  events,
  active,
  onPick,
  dirty,
  onReset,
}: {
  events: ApiEvent[];
  active: string | null;
  onPick: (e: string) => void;
  dirty: boolean;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {events.map((e) => (
        <button
          key={e.event}
          onClick={() => onPick(e.event)}
          disabled={!e.ready}
          className={`chip ${e.event === active ? "chip-active" : ""} ${!e.ready ? "chip-disabled" : ""}`}
          title={e.ready ? undefined : "no measured pit loss for this event"}
        >
          {e.event.replace(" Grand Prix", "")}
        </button>
      ))}
      <AnimatePresence>
        {dirty && (
          <motion.button
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.92 }}
            transition={{ duration: 0.18, ease: EASE }}
            onClick={onReset}
            className="ml-1 rounded-md border border-signal-warn/50 bg-signal-warn/5 px-3 py-1.5 text-tiny font-medium text-signal-warn transition-colors hover:bg-signal-warn/15"
          >
            reset to measured
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

/** THE CALL. One hero panel per screen, and this is it. */
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
    <motion.section
      className="panel-hero relative overflow-hidden p-6"
      // Ring pulse keyed on the stop count: the flip gets acknowledged.
      key={`ring-${r.recommended_stops}`}
      initial={false}
      animate={{ boxShadow: undefined }}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="title">the call</h3>
          <p className="mt-1 text-tiny text-fg-dim">
            {r.event.replace(" Grand Prix", "")} · {r.race_laps} laps ·{" "}
            {r.n_plans_enumerated.toLocaleString()} plans enumerated
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {dirty ? <Pill tone="warn">your inputs</Pill> : <Pill tone="neutral">as measured</Pill>}
          {pending && (
            <Pill tone="neutral">
              <Dot tone="warn" />
              refining
            </Pill>
          )}
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-end gap-x-8 gap-y-5">
        <div
          key={r.recommended_stops}
          className="flex items-baseline gap-3 animate-value-in"
        >
          <span className="num text-hero font-medium text-fg">{r.recommended_stops}</span>
          <span className="pb-2 text-xl text-fg-dim">
            {r.recommended_stops === 1 ? "stop" : "stops"}
          </span>
        </div>

        <div className="pb-2">
          <div className="label">margin over the next-best stop count</div>
          <div
            className={`num mt-1 text-2xl font-medium ${close ? "text-signal-warn" : "text-signal-good"}`}
          >
            <Animated value={`${r.margin_s.toFixed(1)}s`} direction="none" />
          </div>
        </div>
      </div>

      <div className="mt-5 divider" />

      <div className="mt-4">
        <StintAllocation
          compounds={rec.compounds}
          lengths={rec.stint_lengths}
          colors={COMPOUND_COLOR}
        />
        {approximate && (
          <span className="mt-1 block text-micro text-fg-faint">
            stint lengths settle in a moment
          </span>
        )}
      </div>

      {close && (
        <p className="mt-4 rounded-md border border-signal-warn/30 bg-signal-warn/5 px-3 py-2 text-tiny leading-relaxed text-signal-warn">
          Over {r.race_laps} laps, {r.margin_s.toFixed(1)}s is a coin flip leaning one way — not a
          decision.
        </p>
      )}
    </motion.section>
  );
}

/**
 * How much measurement error the call survives.
 *
 * Pit loss comes from a handful of green-flag stops, so it carries real error.
 * The crossover is where the recommendation flips. The gap between the two is
 * the answer to "how wrong can we be", which is what a strategist needs and
 * what a single point estimate never says.
 */
function Headroom({ r }: { r: StrategyResult }) {
  const x = r.crossover_pit_loss_s;
  const lo = 15;
  const hi = 35;
  const pos = (v: number) => ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * 100;
  const headroom = x === null ? null : Math.abs(x - r.pit_loss_s);
  const tight = headroom !== null && headroom < 1.5;

  return (
    <Panel title="how wrong can we be" meta={x === null ? "not close" : `${headroom!.toFixed(1)}s`}>
      <div className="relative mt-1 h-12">
        <div className="absolute inset-x-0 top-6 h-1.5 rounded-full bg-ink-700" />
        {x !== null && (
          <>
            <motion.div
              className={`absolute top-6 h-1.5 rounded-full ${tight ? "bg-signal-warn" : "bg-signal-good"}`}
              initial={false}
              animate={{
                left: `${Math.min(pos(r.pit_loss_s), pos(x))}%`,
                width: `${Math.abs(pos(x) - pos(r.pit_loss_s))}%`,
              }}
              transition={{ duration: 0.3, ease: EASE }}
            />
            <motion.div
              className="absolute top-3 flex flex-col items-center"
              initial={false}
              animate={{ left: `${pos(x)}%` }}
              transition={{ duration: 0.3, ease: EASE }}
              style={{ translateX: "-50%" }}
            >
              <div className="h-7 w-0.5 bg-signal-warn" />
              <span className="num mt-0.5 text-micro text-signal-warn">{x.toFixed(1)}</span>
            </motion.div>
          </>
        )}
        <motion.div
          className="absolute top-2 flex flex-col items-center"
          initial={false}
          animate={{ left: `${pos(r.pit_loss_s)}%` }}
          transition={{ duration: 0.2, ease: EASE }}
          style={{ translateX: "-50%" }}
        >
          <div className="h-9 w-1 rounded-sm bg-fg shadow-glow" />
        </motion.div>
      </div>

      <dl className="mt-2 space-y-1.5">
        <Row
          label="pit loss now"
          value={`${r.pit_loss_s.toFixed(1)}s`}
          note={
            r.pit_loss_measured_s !== null && r.n_green_stops !== null
              ? `measured ${r.pit_loss_measured_s.toFixed(1)}s · ${r.n_green_stops} stops`
              : undefined
          }
          tone={r.n_green_stops !== null && r.n_green_stops < 4 ? "warn" : undefined}
        />
        {x === null ? (
          <Row label="flips at" value="never in 15–35s" tone="good" />
        ) : (
          <Row
            label="flips at"
            value={`${x.toFixed(1)}s`}
            note={`${headroom!.toFixed(1)}s of rope`}
            tone={tight ? "warn" : "good"}
          />
        )}
      </dl>
    </Panel>
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
    <Panel title="degradation" meta="s/lap">
      <p className="mb-4 text-tiny leading-relaxed text-fg-faint">
        Drag to ask what happens if a tyre goes off faster than the model thinks. The pale bar is
        the fitted 95% interval.
      </p>

      <div className="space-y-4">
        {compounds.map((c) => {
          const overridden = c.compound in rates;
          const value = overridden ? rates[c.compound] : c.rate;
          const outside = value < c.rate_lo || value > c.rate_hi;
          const max = Math.max(0.12, c.rate_hi * 1.6);
          return (
            <div key={c.compound}>
              <div className="flex items-baseline gap-2">
                <span
                  className="num w-9 rounded px-1.5 py-0.5 text-center text-micro font-bold text-ink-950"
                  style={{ backgroundColor: COMPOUND_COLOR[c.compound as Compound] }}
                >
                  {c.compound}
                </span>
                <span className="label w-14">{c.label}</span>
                <span className={`num text-lg font-medium ${outside ? "text-signal-warn" : "text-fg"}`}>
                  <Animated value={value.toFixed(4)} direction="none" />
                </span>
                {overridden && (
                  <button
                    onClick={() => onClear(c.compound)}
                    className="text-micro text-fg-faint underline decoration-dotted hover:text-fg"
                  >
                    reset
                  </button>
                )}
                <span className="num ml-auto text-tiny text-fg-dim">
                  {c.excluded ? "unusable" : `${c.optimal_stint} laps`}
                </span>
              </div>
              <div className="relative mt-2">
                <input
                  type="range"
                  min={0}
                  max={max}
                  step={0.001}
                  value={Math.min(value, max)}
                  onChange={(e) => onChange(c.compound, Number(e.target.value))}
                />
                {/* The fitted interval on the same scale as the slider, so
                    "inside the model" is visible rather than a number to hold
                    in your head. */}
                <div
                  className="pointer-events-none absolute -bottom-1.5 h-1 rounded-full bg-fg-faint/30"
                  style={{
                    left: `${(Math.max(0, c.rate_lo) / max) * 100}%`,
                    width: `${((c.rate_hi - Math.max(0, c.rate_lo)) / max) * 100}%`,
                  }}
                />
              </div>
              {outside && (
                <p className="mt-2 text-micro text-signal-warn">
                  outside the fitted interval — your number, not the model&apos;s
                </p>
              )}
            </div>
          );
        })}
      </div>

      {compounds.some((c) => c.excluded) && (
        <p className="mt-3 text-tiny text-fg-faint">
          Unusable means a non-positive fitted rate — a tyre that never wears would be run
          to the flag.
        </p>
      )}
    </Panel>
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
  pending,
}: {
  event: ApiEvent | null;
  pitLoss: number | null;
  setPitLoss: (v: number) => void;
  raceLaps: number | null;
  setRaceLaps: (v: number) => void;
  safetyCar: boolean;
  setSafetyCar: (v: boolean) => void;
  result: StrategyResult | null;
  pending: boolean;
}) {
  if (!event || pitLoss === null || raceLaps === null) {
    return (
      <Panel title="race state">
        <Skeleton className="h-40" />
      </Panel>
    );
  }
  const measured = event.pit_loss_s;

  return (
    <Panel
      title="race state"
      meta={
        result ? (
          <span className="num">
            {pending ? "computing" : `${result.compute_ms}ms`}
          </span>
        ) : undefined
      }
    >
      <div className="space-y-6">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="label">pit loss</span>
            <span className="num text-xl font-medium text-fg">
              <Animated value={pitLoss.toFixed(1)} direction="none" />
              <span className="ml-0.5 text-tiny text-fg-faint">s</span>
            </span>
          </div>
          <input
            type="range"
            min={15}
            max={35}
            step={0.5}
            value={pitLoss}
            onChange={(e) => setPitLoss(Number(e.target.value))}
            className="mt-2"
          />
          <div className="mt-1.5 flex items-center justify-between text-micro text-fg-faint">
            <span className="num">15</span>
            {measured !== null && (
              <button
                onClick={() => setPitLoss(measured)}
                className="text-micro underline decoration-dotted hover:text-fg"
              >
                measured {measured.toFixed(1)}s
              </button>
            )}
            <span className="num">35</span>
          </div>
        </div>

        <div className="divider" />

        <div>
          <label className="flex cursor-pointer items-center justify-between">
            <span className={`text-base ${safetyCar ? "text-signal-warn" : "text-fg-dim"}`}>
              safety car is out
            </span>
            <input
              type="checkbox"
              checked={safetyCar}
              onChange={(e) => setSafetyCar(e.target.checked)}
            />
          </label>
          <AnimatePresence>
            {safetyCar && result?.safety_car_fraction && (
              <motion.p
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2, ease: EASE }}
                className="overflow-hidden text-tiny leading-relaxed text-fg-faint"
              >
                <span className="mt-2 block">
                  A stop now costs{" "}
                  <span className="num text-signal-warn">{result.pit_loss_s.toFixed(1)}s</span>. The{" "}
                  <span className="num">{result.safety_car_fraction}</span>× fraction is measured
                  from {result.pit_loss_by_status?.vsc?.n_stops ?? "?"} VSC stops. A full safety car
                  is <strong>not</strong> measurable here — 23 stops across two events, 15s apart.
                </span>
              </motion.p>
            )}
          </AnimatePresence>
        </div>

        <div className="divider" />

        <div>
          <div className="flex items-baseline justify-between">
            <span className="label">race laps</span>
            <span className="num text-xl font-medium text-fg">
              <Animated value={raceLaps} direction="none" />
            </span>
          </div>
          <input
            type="range"
            min={Math.max(10, Math.round(event.race_laps * 0.4))}
            max={event.race_laps}
            step={1}
            value={raceLaps}
            onChange={(e) => setRaceLaps(Number(e.target.value))}
            className="mt-2"
          />
          {/* Both ends name their lap count, like the pit-loss slider above.
              "shortened" alone made a reader work out what the left end meant
              and read as a status on the current value rather than as an axis
              label. */}
          <div className="mt-1.5 flex justify-between text-micro text-fg-faint">
            <span className="num">{Math.max(10, Math.round(event.race_laps * 0.4))} shortened</span>
            <span className="num">full {event.race_laps}</span>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Alternatives({ r }: { r: StrategyResult }) {
  const worst = Math.max(...r.plans.map((p) => p.delta_s), 1);
  return (
    <Panel title="what the alternatives cost" meta="total race time">
      <div className="space-y-3">
        {r.plans.map((p) => {
          const best = p.n_stops === r.recommended_stops;
          return (
            <div key={p.n_stops} className="flex items-center gap-3">
              <span className={`num w-16 text-tiny ${best ? "text-fg" : "text-fg-dim"}`}>
                {p.n_stops} stop{p.n_stops === 1 ? "" : "s"}
              </span>
              <div className="relative h-6 flex-1 overflow-hidden rounded bg-ink-700">
                <motion.div
                  className={`h-6 rounded ${best ? "bg-brand/70" : "bg-ink-500"}`}
                  initial={false}
                  animate={{ width: `${best ? 5 : Math.max(5, (p.delta_s / worst) * 100)}%` }}
                  transition={{ duration: 0.3, ease: EASE }}
                />
              </div>
              <span
                className={`num w-20 text-right text-base font-medium ${best ? "text-signal-good" : "text-fg-dim"}`}
              >
                {best ? "best" : `+${p.delta_s.toFixed(1)}s`}
              </span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

/** Pit now or later -- the question a pit wall actually asks. */
function WhatIf({
  event,
  raceLaps,
  compounds,
  pitLoss,
  safetyCar,
  rates,
}: {
  event: string;
  raceLaps: number;
  compounds: ApiCompound[];
  pitLoss: number | null;
  safetyCar: boolean;
  /** Degradation overrides from the same controls that drive the plan above.
   *  This panel used to receive raceLaps only to bound its slider and never
   *  sent it, so shortening the race moved the plan and left this answering
   *  the old distance. */
  rates: Record<string, number>;
}) {
  const usable = compounds.filter((c) => !c.excluded);
  const [lap, setLap] = useState(Math.round(raceLaps * 0.5));
  const [age, setAge] = useState(15);
  const [compound, setCompound] = useState(usable[0]?.compound ?? "");
  const [res, setRes] = useState<WhatIfResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!usable.some((c) => c.compound === compound)) setCompound(usable[0]?.compound ?? "");
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
          race_laps: raceLaps,
          safety_car: safetyCar,
          ...(Object.keys(rates).length ? { rates } : {}),
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
    // raceLaps and rates belong here. Sending them without depending on them
    // is the same bug in a quieter form: the request carries the new value,
    // but nothing re-issues the request when the control moves.
  }, [event, lap, age, compound, pitLoss, safetyCar, raceLaps, rates]);

  const worst = res ? Math.max(...res.options.map((o) => o.delta_s), 1) : 1;

  return (
    <Panel
      title="pit now, or later?"
      meta={res ? <span className="num">{res.compute_ms}ms</span> : undefined}
    >
      <div className="grid grid-cols-3 gap-4">
        <Field label="on lap">
          <input
            type="number"
            min={1}
            max={raceLaps - 6}
            value={lap}
            onChange={(e) => setLap(Number(e.target.value))}
            className="num w-full rounded-md border border-ink-600 bg-ink-950 px-2.5 py-1.5 text-base text-fg focus:border-brand focus:outline-none"
          />
        </Field>
        <Field label="tyre age">
          <input
            type="number"
            min={0}
            max={50}
            value={age}
            onChange={(e) => setAge(Number(e.target.value))}
            className="num w-full rounded-md border border-ink-600 bg-ink-950 px-2.5 py-1.5 text-base text-fg focus:border-brand focus:outline-none"
          />
        </Field>
        <Field label="on">
          <select
            value={compound}
            onChange={(e) => setCompound(e.target.value)}
            className="num w-full rounded-md border border-ink-600 bg-ink-950 px-2.5 py-1.5 text-base text-fg focus:border-brand focus:outline-none"
          >
            {usable.map((c) => (
              <option key={c.compound} value={c.compound}>
                {c.compound} {c.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {err ? (
        <p className="mt-4 text-tiny text-signal-warn">{err}</p>
      ) : res ? (
        <>
          {/* The window, not the winner.
              "Best stop is lap 20" reads as a decision, and usually is not
              one -- the first four options at Hungary sit 0.03s apart, far
              below the 2.2s the same pit lane varies by between seasons. A
              strategist given a window can spend it on the things we do not
              model: track position, traffic, a safety car. Given a single lap
              they will defend it. */}
          {(() => {
            const wide = res.window_to > res.window_from;
            const callNow = res.window_from <= lap;
            return (
              <p className="mt-4 text-base leading-relaxed text-fg-dim">
                {wide ? (
                  <>
                    <span className="text-lg font-medium text-signal-good">
                      {callNow ? "Box any lap now through " : "Box between laps "}
                      <span className="num">{callNow ? res.window_to : `${res.window_from}–${res.window_to}`}</span>
                    </span>{" "}
                    — all within{" "}
                    <span className="num text-fg">{res.window_tolerance_s.toFixed(1)}s</span> of
                    each other, so the lap is yours to pick.
                  </>
                ) : (
                  <>
                    <span className="text-lg font-medium text-signal-warn">
                      Box on lap <span className="num">{res.best_pit_lap}</span>
                      {res.best_pit_lap === lap && " — now"}
                    </span>{" "}
                    — waiting a lap already costs more than{" "}
                    <span className="num text-fg">{res.window_tolerance_s.toFixed(1)}s</span>.
                  </>
                )}{" "}
                A stop costs <span className="num text-fg">{res.pit_loss_s.toFixed(1)}s</span>.
              </p>
            );
          })()}
          {/* Bar height is COST, so taller is worse and the shortest bar is the
              answer. The first version inverted this -- tallest meant best --
              which put a tall bar directly under a label reading "+8.7s". The
              chart and the number it sat beside disagreed. */}
          <div className="mt-3 flex h-24 items-end gap-1.5">
            {res.options.map((o) => {
              // Green means "you can take this lap", which is the window --
              // colouring only the single minimum told a strategist four
              // equally good laps were three mistakes and one right answer.
              const best = o.pit_on_lap >= res.window_from && o.pit_on_lap <= res.window_to;
              return (
                <div key={o.pit_on_lap} className="flex h-full flex-1 flex-col items-center justify-end gap-1.5">
                  <span
                    className={`num text-micro ${best ? "font-bold text-signal-good" : "text-fg-faint"}`}
                  >
                    {o.delta_s === 0 ? "best" : best ? "free" : `+${o.delta_s.toFixed(1)}`}
                  </span>
                  <motion.div
                    className={`w-full rounded-t ${best ? "bg-signal-good" : "bg-ink-500"}`}
                    initial={false}
                    animate={{ height: `${Math.max(3, (o.delta_s / worst) * 56)}px` }}
                    transition={{ duration: 0.25, ease: EASE }}
                    title={`pit on lap ${o.pit_on_lap}: +${o.delta_s.toFixed(2)}s slower than the best`}
                  />
                  <span
                    className={`num text-micro ${best ? "text-signal-good" : "text-fg-dim"}`}
                  >
                    {o.pit_on_lap}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="mt-1 text-tiny text-fg-faint">
            seconds lost versus stopping on the best lap — shorter is better
          </p>
          <p className="mt-3 text-tiny leading-relaxed text-fg-faint">
            Laps already run are held fixed; everything after the stop is re-optimised. Under a
        safety car only laps inside the window get the cheaper stop.
          </p>
        </>
      ) : (
        <Skeleton className="mt-4 h-24" />
      )}
    </Panel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

/**
 * Fallback when the service is unreachable.
 *
 * Falls back to the PUBLISHED playbook rather than to an error screen. The live
 * console answers questions nobody precomputed and that is the point of it --
 * but if the backend dies thirty seconds before a demo, seven precomputed races
 * beat a stack trace. The banner says which one you are looking at.
 */
function ApiDown({ message, playbook }: { message: string; playbook: PlaybookArtifact }) {
  return (
    <div className="space-y-5">
      <Panel className="border-signal-warn/40 bg-signal-warn/[0.03]">
        <div className="flex items-start gap-3">
          <Pill tone="warn">offline</Pill>
          <div className="min-w-0">
            <h3 className="title text-signal-warn">
              strategy service unreachable — showing published results
            </h3>
            <p className="mt-2 text-tiny leading-relaxed text-fg-dim">
              These are the precomputed calls for the events we have. The controls are gone because
              there is nothing to recompute with. Start the service to get them back:
            </p>
            <pre className="mt-2 overflow-x-auto rounded-md border border-ink-600 bg-ink-950 p-2.5 text-micro text-fg">
              uvicorn cleanair.api:app --reload --port 8000
            </pre>
            <p className="mt-2 text-micro text-fg-faint">{message}</p>
          </div>
        </div>
      </Panel>
      {playbook.events.length > 0 && <RacePlanView playbook={playbook} />}
    </div>
  );
}
