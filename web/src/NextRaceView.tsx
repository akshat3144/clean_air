import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  getUpcoming,
  postForecast,
  clearAllocation,
  putAllocation,
  type ForecastResult,
  type PitLossHint,
  type UpcomingRound,
} from "./api";
import { DegradationHorizon } from "./DegradationHorizon";
import { PracticeSessionsPanel } from "./PracticeSessionsPanel";
import { COMPOUND_COLOR, type Compound } from "./types/artifacts";
import { Animated, Panel, Pill, Row, Skeleton, StintAllocation } from "./ui";

/**
 * The race that has not happened yet.
 *
 * This is what the product is actually for. Everything else in the app looks
 * backwards at races we can already score; this one looks forward, from the
 * practice that has already run to the Sunday that has not.
 *
 * A race becomes answerable in stages, and the screen shows which stage it is
 * at rather than pretending to a number it does not have:
 *
 *   on the calendar   we know the date and the circuit
 *   + nominated       Pirelli announced the compounds (the one human input)
 *   + practice run    long runs exist, so a forecast is possible
 *   + enough of it    at least two compounds have a usable rate
 *
 * Every input says where it came from. A rate forecast from Friday long runs
 * and a rate measured from a finished race are not the same claim.
 */
export function NextRaceView() {
  const [rounds, setRounds] = useState<UpcomingRound[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [idx, setIdx] = useState(0);

  const reload = () => {
    const ac = new AbortController();
    getUpcoming(3, ac.signal)
      .then(setRounds)
      .catch((e) => {
        if (e?.name === "AbortError") return;
        setError(e instanceof ApiError ? e.message : "cannot reach the strategy service");
      });
    return () => ac.abort();
  };

  useEffect(reload, []);

  if (error) {
    return (
      <Panel className="border-signal-warn/40">
        <p className="text-base text-signal-warn">{error}</p>
        <p className="mt-2 text-tiny text-fg-dim">
          The calendar comes from the service. Start it with{" "}
          <code className="text-fg">uvicorn cleanair.api:app --port 8000</code>.
        </p>
      </Panel>
    );
  }
  if (!rounds) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-9 w-96 rounded-md" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }
  if (!rounds.length) {
    return (
      <Panel>
        <p className="text-base text-fg-dim">
          No races left on the {new Date().getFullYear()} calendar.
        </p>
      </Panel>
    );
  }

  const rnd = rounds[Math.min(idx, rounds.length - 1)];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {rounds.map((r, i) => (
          <button
            key={r.event}
            onClick={() => setIdx(i)}
            className={`chip ${i === idx ? "chip-active" : ""}`}
          >
            R{r.round_number} {r.event.replace(" Grand Prix", "")}
          </button>
        ))}
      </div>

      <RoundHeader rnd={rnd} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Nomination rnd={rnd} onSaved={reload} />
          <CircuitHistory rnd={rnd} />
        </div>
        <Forecast rnd={rnd} />
      </div>
    </div>
  );
}

function RoundHeader({ rnd }: { rnd: UpcomingRound }) {
  const race = rnd.sessions.find((s) => s.code === "R");
  const days = race
    ? Math.round((new Date(race.starts_utc).getTime() - Date.now()) / 86_400_000)
    : null;

  return (
    <section className="panel-hero p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="label">round {rnd.round_number} · next up</div>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">{rnd.event}</h2>
          <p className="mt-1 text-base text-fg-dim">
            {rnd.location}
            {rnd.country ? `, ${rnd.country}` : ""}
          </p>
        </div>
        {days !== null && (
          <div className="text-right">
            <div className="label">race in</div>
            <div className="num text-4xl font-medium leading-none text-fg">
              <Animated value={days <= 0 ? "today" : `${days}d`} direction="none" />
            </div>
          </div>
        )}
      </div>

      {/* The session timeline. Which of the inputs we need already exist is the
          single most useful thing on this screen, and it is a timeline rather
          than a list because "FP2 done, FP3 tomorrow" is a fact about time. */}
      <div className="mt-5 flex flex-wrap gap-2">
        {rnd.sessions.map((s) => {
          const when = new Date(s.starts_utc);
          const isLongRun = ["FP1", "FP2", "FP3", "S"].includes(s.code);
          return (
            <div
              key={s.code}
              className={`flex-1 rounded-md border px-3 py-2 ${
                s.has_run
                  ? "border-signal-good/40 bg-signal-good/5"
                  : "border-ink-600"
              }`}
              title={when.toUTCString()}
            >
              <div
                className={`num text-tiny font-semibold ${
                  s.has_run ? "text-signal-good" : "text-fg"
                }`}
              >
                {s.code}
              </div>
              <div className="mt-0.5 text-micro text-fg-faint">
                {s.has_run
                  ? s.code === "S"
                    ? "race pace in"
                    : isLongRun
                      ? "long runs in"
                      : "done"
                  : when.toLocaleDateString(undefined, { weekday: "short", hour: "2-digit" })}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/**
 * Pirelli brings three ADJACENT compounds and slides the window by circuit
 * severity. Every 2026 nomination we have verified is one of exactly three
 * windows, and their own language is "the middle trio" and "the softest trio".
 *
 * So this is three buttons, not three dropdowns. The dropdown version offered
 * 125 combinations of which 122 are impossible, which is a worse control and a
 * worse description of how the sport works.
 *
 * `custom` stays, because adjacency is a strong pattern rather than a rule and
 * asserting it as a law would be overreach.
 */
const WINDOWS = [
  {
    key: "hardest",
    compounds: ["C1", "C2", "C3"],
    name: "hardest trio",
    when: "punishing surface — Suzuka",
  },
  {
    key: "middle",
    compounds: ["C2", "C3", "C4"],
    name: "middle trio",
    when: "high-energy corners — Spa, Barcelona",
  },
  {
    key: "softest",
    compounds: ["C3", "C4", "C5"],
    name: "softest trio",
    when: "slow or smooth — Monaco, Monza",
  },
] as const;

const LABELS = ["HARD", "MEDIUM", "SOFT"] as const;
const CS = ["C1", "C2", "C3", "C4", "C5"];

function windowOf(a: Record<string, string> | null): string | null {
  if (!a) return null;
  const trio = LABELS.map((l) => a[l]).join("");
  return WINDOWS.find((w) => w.compounds.join("") === trio)?.key ?? null;
}

function Nomination({ rnd, onSaved }: { rnd: UpcomingRound; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [custom, setCustom] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>(
    rnd.allocation ?? { HARD: "C3", MEDIUM: "C4", SOFT: "C5" },
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setDraft(rnd.allocation ?? { HARD: "C3", MEDIUM: "C4", SOFT: "C5" });
    setEditing(false);
    setCustom(false);
    setErr(null);
  }, [rnd.event, rnd.allocation]);

  const save = async (compounds: Record<string, string>) => {
    setSaving(true);
    setErr(null);
    try {
      await putAllocation(rnd.event, compounds);
      setEditing(false);
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "could not save");
    } finally {
      setSaving(false);
    }
  };

  const current = windowOf(rnd.allocation);
  const showPicker = editing || !rnd.allocation;

  return (
    <Panel
      title="this weekend's tyres"
      meta={
        rnd.allocation_source === "user" ? (
          <Pill tone="warn">entered here</Pill>
        ) : rnd.allocation ? (
          <Pill tone="neutral">from pirelli</Pill>
        ) : (
          <Pill tone="warn">not announced</Pill>
        )
      }
    >
      {/* SET: read it, do not edit it. A strategist reads this; the form is
          admin and only appears when there is nothing to read. */}
      {rnd.allocation && !showPicker && (
        <>
          <div className="flex items-center gap-2">
            {LABELS.map((lab) => (
              <div key={lab} className="flex-1 text-center">
                <div
                  className="num rounded-md py-2 text-base font-bold text-ink-950"
                  style={{
                    backgroundColor: COMPOUND_COLOR[rnd.allocation![lab] as Compound],
                  }}
                >
                  {rnd.allocation![lab]}
                </div>
                <div className="label mt-1">{lab}</div>
              </div>
            ))}
          </div>
          {/* One line, about THIS race, not a lecture. The full derivation lives
              in Method; here it only has to explain why the numbers below are
              keyed on a C number instead of the word on the sidewall. */}
          <p className="mt-3 text-tiny leading-relaxed text-fg-faint">
            <span className="num text-fg-dim">{rnd.allocation!.HARD}</span> is this
            weekend&apos;s <span className="text-fg-dim">hard</span> — the label is relative to
            what was brought, so the same rubber is called something else elsewhere.
          </p>

          <div className="mt-3 flex items-center justify-between">
            <span className="text-tiny text-fg-dim">
              {WINDOWS.find((w) => w.key === current)?.name ?? "custom nomination"}
            </span>
            <span className="flex items-center gap-3">
              {/* Only for values typed here. A cited nomination has nothing to
                  take back, and offering to "clear" it would imply otherwise. */}
              {rnd.allocation_source === "user" && (
                <button
                  onClick={async () => {
                    setSaving(true);
                    try {
                      await clearAllocation(rnd.event);
                      onSaved();
                    } catch (e) {
                      setErr(e instanceof ApiError ? e.message : "could not clear");
                    } finally {
                      setSaving(false);
                    }
                  }}
                  disabled={saving}
                  className="text-tiny text-signal-warn underline decoration-dotted hover:text-fg disabled:opacity-50"
                >
                  clear
                </button>
              )}
              <button
                onClick={() => setEditing(true)}
                className="text-tiny text-fg-faint underline decoration-dotted hover:text-fg"
              >
                change
              </button>
            </span>
          </div>
        </>
      )}

      {showPicker && (
        <>
          <p className="mb-3 text-tiny leading-relaxed text-fg-faint">
            Pirelli brings three adjacent compounds, sliding the window by how hard the
            circuit is on tyres. No feed carries the mapping — it is a press release — so it
            is set here.
          </p>

          {!custom ? (
            <div className="space-y-2">
              {WINDOWS.map((w) => {
                const active = w.key === current;
                return (
                  <button
                    key={w.key}
                    disabled={saving}
                    onClick={() =>
                      save({
                        HARD: w.compounds[0],
                        MEDIUM: w.compounds[1],
                        SOFT: w.compounds[2],
                      })
                    }
                    className={`w-full rounded-md border px-3 py-2.5 text-left transition-colors disabled:opacity-50 ${
                      active
                        ? "border-brand bg-brand/10"
                        : "border-ink-600 hover:border-ink-500 hover:bg-ink-700/40"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      {w.compounds.map((c) => (
                        <span
                          key={c}
                          className="num rounded px-2 py-0.5 text-micro font-bold text-ink-950"
                          style={{ backgroundColor: COMPOUND_COLOR[c as Compound] }}
                        >
                          {c}
                        </span>
                      ))}
                      <span className="ml-auto text-tiny font-medium text-fg">{w.name}</span>
                    </div>
                    <div className="mt-1 text-micro text-fg-faint">{w.when}</div>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="space-y-2">
              {LABELS.map((lab) => (
                <div key={lab} className="flex items-center gap-3">
                  <span className="label w-16">{lab}</span>
                  <select
                    value={draft[lab] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [lab]: e.target.value }))}
                    className="num flex-1 rounded-md border border-ink-600 bg-ink-950 px-2.5 py-1.5 text-base text-fg focus:border-brand focus:outline-none"
                  >
                    {CS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
              <button
                onClick={() => save(draft)}
                disabled={saving}
                className="w-full rounded-md border border-brand bg-brand/15 px-3 py-2 text-tiny font-medium text-fg hover:bg-brand/25 disabled:opacity-50"
              >
                {saving ? "saving…" : "save nomination"}
              </button>
            </div>
          )}

          <div className="mt-3 flex items-center justify-between text-micro">
            <button
              onClick={() => setCustom((v) => !v)}
              className="text-fg-faint underline decoration-dotted hover:text-fg"
            >
              {custom ? "back to the three windows" : "custom nomination"}
            </button>
            {rnd.allocation && (
              <button
                onClick={() => setEditing(false)}
                className="text-fg-faint underline decoration-dotted hover:text-fg"
              >
                cancel
              </button>
            )}
          </div>
          {err && <p className="mt-2 text-tiny text-signal-bad">{err}</p>}
        </>
      )}
    </Panel>
  );
}

/**
 * What previous seasons say about this circuit.
 *
 * An upcoming race supplies neither its pit loss nor its distance, and both are
 * properties of the circuit rather than the weekend. Labelled as history rather
 * than measurement: last year's pit lane is evidence about Sunday, not a
 * reading from it.
 */
function CircuitHistory({ rnd }: { rnd: UpcomingRound }) {
  const h = rnd.history;
  if (!h || (h.pit_loss_s === null && h.race_laps === null)) {
    return (
      <Panel title="circuit history">
        <p className="text-tiny leading-relaxed text-fg-dim">
          We have never raced here in the seasons we hold, so there is no pit loss or
          distance to carry forward. Both would have to be supplied.
        </p>
      </Panel>
    );
  }
  const wide = (h.pit_loss_spread_s ?? 0) > 3;
  return (
    <Panel
      title="circuit history"
      meta={h.seasons.length ? `${h.seasons.length} seasons` : undefined}
    >
      <dl className="space-y-2">
        {h.pit_loss_s !== null && (
          <Row
            label="pit loss"
            value={`${h.pit_loss_s.toFixed(1)}s`}
            note={
              h.pit_loss_spread_s !== null
                ? `spread ${h.pit_loss_spread_s.toFixed(1)}s`
                : undefined
            }
            tone={wide ? "warn" : undefined}
          />
        )}
        {h.race_laps !== null && <Row label="race distance" value={`${h.race_laps} laps`} />}
        {h.seasons.length > 0 && <Row label="measured in" value={h.seasons.join(", ")} />}
      </dl>
      {wide && (
        <p className="mt-3 text-tiny leading-relaxed text-signal-warn">
          The pit loss moved by {h.pit_loss_spread_s?.toFixed(1)}s across those seasons, so
          treat it as a starting point rather than a measurement.
        </p>
      )}
      <p className="mt-3 text-micro leading-relaxed text-fg-faint">
        Distance is the longest completed race, not the average — a race shortened by a red
        flag is not the circuit&apos;s distance.
      </p>
    </Panel>
  );
}

/**
 * The two inputs a circuit with no past cannot supply for itself.
 *
 * Madrid has never held a race, so there is no pit loss and no distance to
 * carry forward, and the forecast endpoint refuses without them. That refusal
 * is right -- inventing a pit lane time for a track nobody has driven is
 * exactly the kind of confident wrong number this project exists to avoid.
 *
 * But refusing and then offering no way forward is a dead end, and the demo
 * race is the one race guaranteed to hit it. So the screen ASKS. The fields
 * start empty on purpose: a prefilled default would be a fabricated
 * measurement wearing the clothes of a real one. The range hint is from the 22
 * circuits we do have history for, which is evidence about what is plausible
 * and is labelled as nothing more than that.
 */
function SupplyInputs({
  pit,
  laps,
  setPit,
  setLaps,
  onSubmit,
  busy,
  needs,
  hints,
}: {
  pit: string;
  laps: string;
  setPit: (v: string) => void;
  setLaps: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  /** Which inputs are actually outstanding. A new circuit still has a
   *  PUBLISHED race distance -- the FIA fixes it before anyone drives -- so
   *  asking for both was asking for one number that was never in doubt. */
  needs: string[];
  hints?: Record<string, PitLossHint>;
}) {
  const wantPit = needs.includes("pit_loss_s");
  const wantLaps = needs.includes("race_laps");
  const pitN = Number(pit);
  const lapsN = Number(laps);
  const ok =
    (!wantPit || (pit !== "" && pitN >= 5 && pitN <= 60)) &&
    (!wantLaps || (laps !== "" && lapsN >= 5 && lapsN <= 100));
  const hint = hints?.pit_loss_s;

  // No Panel of its own: this renders INSIDE the plan panel, beneath the
  // compound table, rather than in place of the entire screen.
  return (
    <>
      <p className="text-base text-fg-dim">
        Never raced here, so there is no{" "}
        {wantPit && wantLaps ? "pit loss or race distance" : wantPit ? "pit loss" : "race distance"}{" "}
        to carry forward. The tyre numbers below do not depend on{" "}
        {wantPit && wantLaps ? "either" : "it"}.
      </p>

      {/* A quoted figure, with who produced it and what kind of number it is.
          Not a default and not prefilled: it is somebody's simulation, two
          sources disagree by a second, and the operator should adopt it
          knowingly or not at all. */}
      {hint && (
        <div className="mt-3 rounded border border-signal-warn/30 bg-signal-warn/5 p-3">
          <p className="text-tiny leading-relaxed text-fg-dim" title={hint.note}>
            <span className="num text-fg">{hint.seconds.toFixed(1)}s</span> is quoted by{" "}
            <span className="text-fg">{hint.source}</span> — a{" "}
            <span className="text-signal-warn">{hint.kind}</span>, not a measurement.
          </p>
          <button
            type="button"
            onClick={() => setPit(String(hint.seconds))}
            className="mt-2 rounded border border-ink-600 px-2 py-1 text-micro uppercase tracking-widest text-fg-dim transition-colors hover:border-fg-dim hover:text-fg"
          >
            use {hint.seconds.toFixed(1)}s
          </button>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-4">
        {wantPit && (
        <label className="flex flex-col gap-1">
          <span className="label">pit loss</span>
          <span className="flex items-baseline gap-1.5">
            <input
              type="number"
              value={pit}
              onChange={(e) => setPit(e.target.value)}
              placeholder="—"
              step="0.1"
              min={5}
              max={60}
              className="num w-24 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fg outline-none focus:border-fg-dim"
            />
            <span className="text-tiny text-fg-faint">s</span>
          </span>
        </label>
        )}

        {wantLaps && (
        <label className="flex flex-col gap-1">
          <span className="label">race distance</span>
          <span className="flex items-baseline gap-1.5">
            <input
              type="number"
              value={laps}
              onChange={(e) => setLaps(e.target.value)}
              placeholder="—"
              min={5}
              max={100}
              className="num w-24 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fg outline-none focus:border-fg-dim"
            />
            <span className="text-tiny text-fg-faint">laps</span>
          </span>
        </label>
        )}

        <button
          type="button"
          onClick={onSubmit}
          disabled={!ok || busy}
          className="rounded border border-ink-600 px-3 py-1.5 text-tiny uppercase tracking-widest text-fg-dim transition-colors hover:border-fg-dim hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "computing…" : "compute the plan"}
        </button>
      </div>

      <p className="mt-3 text-tiny text-fg-faint">
        Blank on purpose — a default would be a made-up measurement. Elsewhere we measure{" "}
        <span className="num text-fg-dim">19.0&ndash;29.2s</span>, median{" "}
        <span className="num text-fg-dim">23.0</span>.
      </p>
    </>
  );
}

function Forecast({ rnd }: { rnd: UpcomingRound }) {
  const [res, setRes] = useState<ForecastResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Only ever set for a circuit with no history. Everywhere else these stay
  // empty and the endpoint uses the measured values, as before.
  const [pit, setPit] = useState("");
  const [laps, setLaps] = useState("");
  // No `supplied` flag any more. Whether the plan is still waiting is the
  // SERVER's answer (`needs_inputs`), not a local guess -- one source of truth,
  // and it cannot drift out of step with what the response actually contains.
  // No local guess about what is missing. `rnd.history === null` was that
  // guess, and it went stale the moment Madrid gained a published race
  // distance: history stopped being null, so the typed pit loss silently
  // stopped being sent and "compute the plan" did nothing at all. The server
  // says what it still needs, in `res.needs_inputs`, and the boxes only render
  // for what it asks for -- so an empty box is simply a field we omit.

  const run = useCallback(
    (signal?: AbortSignal) => {
      setLoading(true);
      setErr(null);
      const body: { event: string; pit_loss_s?: number; race_laps?: number } = {
        event: rnd.event,
      };
      // Only send what the user has actually typed. `Number("")` is 0, and
      // sending 0 fails the endpoint's own `ge=5` validation -- so the first
      // automatic call for a new circuit came back 422 and the screen printed
      // the raw pydantic error where the plan goes. An untouched box is an
      // absent field, not a zero.
      if (pit !== "") body.pit_loss_s = Number(pit);
      if (laps !== "") body.race_laps = Number(laps);
      postForecast(body, signal)
        .then(setRes)
        .catch((e) => {
          if (e?.name === "AbortError") return;
          setErr(e instanceof ApiError ? e.message : "forecast failed");
        })
        .finally(() => setLoading(false));
    },
    [rnd.event, pit, laps],
  );

  useEffect(() => {
    setRes(null);
    setErr(null);
    if (!rnd.ready_to_forecast) return;
    // Fire even for a circuit with no history. It used to be skipped because
    // the request was guaranteed to 422; the endpoint now answers with
    // everything that does not need a pit lane -- the compound rates and the
    // session breakdown -- and says which inputs the PLAN is still waiting on.
    const ac = new AbortController();
    run(ac.signal);
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rnd.event, rnd.ready_to_forecast]);

  if (!rnd.ready_to_forecast) {
    return (
      <Panel title="sunday's plan" meta={<Pill tone="warn">not yet</Pill>}>
        <p className="text-base leading-relaxed text-fg-dim">
          This race cannot be forecast yet. What is missing:
        </p>
        <ul className="mt-3 space-y-2">
          {rnd.blocked_by.map((b, i) => (
            <li key={i} className="flex gap-2.5 text-tiny leading-relaxed text-fg-dim">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-signal-warn" />
              {b}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-tiny leading-relaxed text-fg-faint">
          Practice sessions are pulled automatically as they finish, so this fills itself in.
        </p>
      </Panel>
    );
  }

  // NOTE: there is deliberately no early return for a circuit awaiting its two
  // inputs. That is what blanked Madrid -- the one race this is built to demo
  // -- down to two empty boxes, hiding degradation rates and a full
  // session-by-session breakdown that are computed from practice alone and
  // need neither number. The form now renders as the PLAN panel, with the
  // tyre work above it.

  if (loading || (!res && !err)) {
    return (
      <Panel title="sunday's plan">
        <Skeleton className="h-20 w-64" />
        <Skeleton className="mt-4 h-24" />
      </Panel>
    );
  }
  if (err) {
    return (
      <Panel title="sunday's plan" className="border-signal-bad/40">
        <p className="text-base text-signal-bad">{err}</p>
      </Panel>
    );
  }
  if (!res) return null;

  return (
    <div className="space-y-5">
      <Panel
        title="sunday's plan"
        meta={
          <span className="flex items-center gap-2">
            <Pill tone="warn">
              {res.needs_inputs?.length
                ? `needs ${res.needs_inputs.length === 1 ? "an input" : `${res.needs_inputs.length} inputs`}`
                : "forecast"}
            </Pill>
            <span className="num">{res.compute_ms}ms</span>
          </span>
        }
      >
        {res.needs_inputs?.length ? (
          <SupplyInputs
            pit={pit}
            laps={laps}
            setPit={setPit}
            setLaps={setLaps}
            busy={loading}
            onSubmit={() => run()}
            needs={res.needs_inputs ?? []}
            hints={res.hints}
          />
        ) : res.can_plan ? (
          <>
            <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
              <div className="flex items-baseline gap-3">
                <span className="num text-hero font-medium leading-none text-fg">
                  {res.recommended_stops}
                </span>
                <span className="pb-2 text-xl text-fg-dim">
                  {res.recommended_stops === 1 ? "stop" : "stops"}
                </span>
              </div>
              <div className="pb-2">
                <div className="label">margin</div>
                <div className="num mt-1 text-2xl font-medium text-signal-good">
                  {res.margin_s?.toFixed(1)}s
                </div>
              </div>
            </div>
            <div className="mt-4">
              <StintAllocation
                compounds={
                  res.plans?.find((p) => p.n_stops === res.recommended_stops)?.compounds ?? []
                }
                lengths={
                  res.plans?.find((p) => p.n_stops === res.recommended_stops)?.stint_lengths ?? []
                }
                colors={COMPOUND_COLOR}
              />
            </div>
          </>
        ) : (
          <div className="rounded-md border border-signal-warn/30 bg-signal-warn/5 px-3 py-2.5">
            <p className="text-base leading-relaxed text-signal-warn">{res.reason}</p>
          </div>
        )}

        <div className="mt-5 divider" />

        <dl className="mt-4 grid gap-x-8 gap-y-2 sm:grid-cols-2">
          <Row
            label="built from"
            value={res.practice_sessions.join(" + ") || "—"}
            note="long runs"
          />
          {/* Both are null on a circuit still awaiting its inputs. tsconfig
              has strictNullChecks off, so a bare .toFixed() here type-checks
              clean and throws at runtime on exactly the race we demo. */}
          <Row
            label="pit loss"
            value={res.pit_loss_s === null ? "—" : `${res.pit_loss_s.toFixed(1)}s`}
            note={res.pit_loss_source ?? (res.pit_loss_s === null ? "not supplied" : undefined)}
          />
          <Row
            label="distance"
            value={res.race_laps === null ? "—" : `${res.race_laps} laps`}
            note={res.race_laps_source ?? (res.race_laps === null ? "not supplied" : undefined)}
          />
          <Row
            label="practice → race"
            value={`×${res.practice_to_race_factor.toFixed(2)}`}
            note="learned from other events"
          />
        </dl>

        <p className="mt-3 text-tiny text-fg-faint">
          A race runs at about{" "}
          <span className="num text-fg-dim">
            {(res.practice_to_race_factor * 100).toFixed(0)}%
          </span>{" "}
          of its practice rate — drivers nurse a tyre on Sunday. Learned from other events,
          never this one.
        </p>
      </Panel>

      <Panel title="what the tyre costs you" meta="seconds lost">
        {/* A rate of 0.087 s/lap is the right number in the wrong unit. Nobody
            calls a stop off a slope; they call it off "ten more laps on this
            set costs you nine tenths". Same fitted number, stated in what is
            actually being decided. */}
        <DegradationHorizon
          rows={res.compounds}
          note="Seconds slower than the same tyre fresh, 95% band beneath. A compound that never wears is left out — an optimiser would run it to the flag."
        />

        <dl className="mt-4 grid gap-x-6 gap-y-1.5 border-t border-ink-600/40 pt-3 sm:grid-cols-2">
          {res.compounds
            .filter((c) => !c.excluded)
            .map((c) => (
              <Row
                key={c.compound}
                label={c.label ?? c.compound}
                value={
                  res.pit_loss_s === null ? "needs pit loss" : `${c.optimal_stint} laps`
                }
                note={
                  c.source === "stand-in"
                    ? `estimated · ${c.practice_rate.toFixed(3)} in practice`
                    : `${c.n_runs} ${c.n_runs === 1 ? "run" : "runs"} · ${c.practice_rate.toFixed(3)} in practice`
                }
              />
            ))}
        </dl>

        {res.compounds.some((c) => c.source === "thin" && !c.excluded) && (
          // One or two runs is an observation of this tyre at this circuit,
          // and the plan uses it. Say how little it rests on rather than
          // either hiding it or throwing it away.
          <p className="mt-3 text-tiny text-fg-dim">
            {res.compounds
              .filter((c) => c.source === "thin" && !c.excluded)
              .map((c) => c.label ?? c.compound)
              .join(" and ")}{" "}
            rest on fewer than three race-simulation runs here — measured, thinly, with the
            band widened to match.
          </p>
        )}

        {res.compounds.some((c) => c.source === "stand-in") && (
          // Never let a borrowed number sit in the same column as a measured
          // one without saying so. Madrid nominated a HARD that nobody put on
          // a long run in any of the three sessions; the choice is between a
          // labelled stand-in and refusing to answer at all.
          <p className="mt-3 text-tiny text-signal-warn">
            {res.compounds
              .filter((c) => c.source === "stand-in")
              .map((c) => c.label ?? c.compound)
              .join(" and ")}{" "}
            never ran a race simulation here —{" "}
            {res.compounds.some((c) => c.source === "stand-in" && c.severity != null)
              ? "borrowed from other circuits and rescaled, with a wider band to match."
              : "borrowed from other circuits, unscaled, because nothing ran here to scale it by. The band is as wide as that deserves."}
          </p>
        )}
      </Panel>

      <PracticeSessionsPanel event={res.event} />
    </div>
  );
}
