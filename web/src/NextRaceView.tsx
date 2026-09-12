import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import {
  ApiError,
  getUpcoming,
  postForecast,
  putAllocation,
  type ForecastResult,
  type UpcomingRound,
} from "./api";
import { COMPOUND_COLOR, type Compound } from "./types/artifacts";
import { Animated, EASE, Panel, Pill, Row, Skeleton } from "./ui";

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
          <AllocationEditor rnd={rnd} onSaved={reload} />
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
          const isLongRun = ["FP1", "FP2", "FP3"].includes(s.code);
          return (
            <div
              key={s.code}
              className={`flex-1 rounded-md border px-3 py-2 ${
                s.has_run
                  ? isLongRun
                    ? "border-signal-good/40 bg-signal-good/5"
                    : "border-ink-500 bg-ink-700/50"
                  : "border-ink-600"
              }`}
              title={when.toUTCString()}
            >
              <div
                className={`num text-tiny font-semibold ${
                  s.has_run && isLongRun ? "text-signal-good" : "text-fg"
                }`}
              >
                {s.code}
              </div>
              <div className="mt-0.5 text-micro text-fg-faint">
                {s.has_run
                  ? isLongRun
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
 * The one fact no feed carries.
 *
 * The timing data reports HARD / MEDIUM / SOFT, which are relative to whatever
 * three of C1-C5 Pirelli brought. Nothing in the session or event metadata
 * carries the mapping -- it is a press release. So it is three dropdowns here,
 * which is what makes adding a race a UI action rather than a code change.
 */
function AllocationEditor({ rnd, onSaved }: { rnd: UpcomingRound; onSaved: () => void }) {
  const LABELS = ["HARD", "MEDIUM", "SOFT"] as const;
  const CS = ["C1", "C2", "C3", "C4", "C5"];
  const [draft, setDraft] = useState<Record<string, string>>(
    rnd.allocation ?? { HARD: "C2", MEDIUM: "C3", SOFT: "C4" },
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraft(rnd.allocation ?? { HARD: "C2", MEDIUM: "C3", SOFT: "C4" });
    setErr(null);
    setSaved(false);
  }, [rnd.event, rnd.allocation]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(rnd.allocation ?? {});

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      await putAllocation(rnd.event, draft);
      setSaved(true);
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel
      title="this weekend's tyres"
      meta={
        rnd.allocation_source === "user" ? (
          <Pill tone="warn">entered here</Pill>
        ) : rnd.allocation ? (
          <Pill tone="neutral">from pirelli</Pill>
        ) : (
          <Pill tone="warn">not set</Pill>
        )
      }
    >
      <p className="mb-3 text-tiny leading-relaxed text-fg-faint">
        The timing feed only says HARD, MEDIUM and SOFT — and those are relative to
        whichever three compounds were brought. Pirelli publishes the mapping and no feed
        carries it, so it is set here.
      </p>

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
            <span
              className="h-5 w-5 shrink-0 rounded"
              style={{ backgroundColor: COMPOUND_COLOR[(draft[lab] ?? "C3") as Compound] }}
            />
          </div>
        ))}
      </div>

      <AnimatePresence>
        {(dirty || err) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18, ease: EASE }}
            className="overflow-hidden"
          >
            <button
              onClick={save}
              disabled={saving}
              className="mt-3 w-full rounded-md border border-brand bg-brand/15 px-3 py-2 text-tiny font-medium text-fg transition-colors hover:bg-brand/25 disabled:opacity-50"
            >
              {saving ? "saving…" : "save nomination"}
            </button>
            {err && <p className="mt-2 text-tiny text-signal-bad">{err}</p>}
          </motion.div>
        )}
      </AnimatePresence>
      {saved && !dirty && (
        <p className="mt-2 text-tiny text-signal-good">saved — the forecast will use it</p>
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
    <Panel title="circuit history" meta={h.seasons.length ? `${h.seasons.length} seasons` : undefined}>
      <dl className="space-y-2">
        {h.pit_loss_s !== null && (
          <Row
            label="pit loss"
            value={`${h.pit_loss_s.toFixed(1)}s`}
            note={h.pit_loss_spread_s !== null ? `spread ${h.pit_loss_spread_s.toFixed(1)}s` : undefined}
            tone={wide ? "warn" : undefined}
          />
        )}
        {h.race_laps !== null && <Row label="race distance" value={`${h.race_laps} laps`} />}
        {h.seasons.length > 0 && (
          <Row label="measured in" value={h.seasons.join(", ")} />
        )}
      </dl>
      {wide && (
        <p className="mt-3 text-tiny leading-relaxed text-signal-warn">
          The pit loss moved by {h.pit_loss_spread_s?.toFixed(1)}s across those seasons, so
          treat it as a starting point rather than a measurement.
        </p>
      )}
      <p className="mt-3 text-micro leading-relaxed text-fg-faint">
        Distance is the longest completed race, not the average — a race shortened by a red
        flag is not the circuit's distance.
      </p>
    </Panel>
  );
}

function Forecast({ rnd }: { rnd: UpcomingRound }) {
  const [res, setRes] = useState<ForecastResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setRes(null);
    setErr(null);
    if (!rnd.ready_to_forecast) return;
    const ac = new AbortController();
    setLoading(true);
    postForecast({ event: rnd.event }, ac.signal)
      .then(setRes)
      .catch((e) => {
        if (e?.name === "AbortError") return;
        setErr(e instanceof ApiError ? e.message : "forecast failed");
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
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
            <Pill tone="warn">forecast</Pill>
            <span className="num">{res.compute_ms}ms</span>
          </span>
        }
      >
        {res.can_plan ? (
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
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {res.plans
                ?.find((p) => p.n_stops === res.recommended_stops)
                ?.compounds.map((c, i, arr) => (
                  <span key={i} className="flex items-center gap-2">
                    {i > 0 && <span className="text-lg text-fg-faint">→</span>}
                    <span
                      className="num rounded-md px-3 py-1.5 text-base font-semibold text-ink-950"
                      style={{ backgroundColor: COMPOUND_COLOR[c as Compound] }}
                    >
                      {c} <span className="opacity-60">×</span>{" "}
                      {
                        res.plans?.find((p) => p.n_stops === res.recommended_stops)
                          ?.stint_lengths[i]
                      }
                    </span>
                    {i === arr.length - 1 && null}
                  </span>
                ))}
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
          <Row
            label="pit loss"
            value={`${res.pit_loss_s.toFixed(1)}s`}
            note={res.pit_loss_source}
          />
          <Row
            label="distance"
            value={`${res.race_laps} laps`}
            note={res.race_laps_source}
          />
          <Row
            label="practice → race"
            value={`×${res.practice_to_race_factor.toFixed(2)}`}
            note="learned from other events"
          />
        </dl>

        <p className="mt-4 text-tiny leading-relaxed text-fg-faint">
          A race degrades at about{" "}
          <span className="num text-fg-dim">
            {(res.practice_to_race_factor * 100).toFixed(0)}%
          </span>{" "}
          of its practice rate — drivers nurse a tyre in a race and push it in practice. That
          correction is learned from events that have already raced, never from this one.
        </p>
      </Panel>

      <Panel title="what practice says" meta="s/lap">
        <div className="space-y-3">
          {res.compounds.map((c) => (
            <div key={c.compound} className="flex items-baseline gap-3">
              <span
                className="num w-9 rounded px-1.5 py-0.5 text-center text-micro font-bold text-ink-950"
                style={{ backgroundColor: COMPOUND_COLOR[c.compound as Compound] }}
              >
                {c.compound}
              </span>
              <span className="label w-14">{c.label}</span>
              <span className="num text-tiny text-fg-dim">
                {c.practice_rate.toFixed(4)}
              </span>
              <span className="text-fg-faint">→</span>
              <span
                className={`num text-lg font-medium ${
                  c.excluded ? "text-fg-faint line-through" : "text-fg"
                }`}
              >
                {c.rate.toFixed(4)}
              </span>
              <span className="num ml-auto text-tiny text-fg-dim">
                {c.excluded ? "unusable" : `${c.optimal_stint} laps`}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-4 text-tiny leading-relaxed text-fg-faint">
          Left is what the tyre did in practice; right is what it should do in the race. A
          compound with a non-positive forecast rate is excluded — an optimiser handed a tyre
          that never wears will run it to the flag.
        </p>
      </Panel>
    </div>
  );
}
