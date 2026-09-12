import { useState } from "react";
import { COMPOUND_COLOR, type PlaybookArtifact, type PlaybookEvent } from "./types/artifacts";
import { StintAllocation } from "./ui";

/**
 * The front door.
 *
 * This used to open on a chart of degradation curves, which answers "is your
 * method sound?" -- a reviewer's question. A strategist has one question on a
 * Friday evening: what do we do on Sunday. So this opens on the answer, and
 * everything else is support for it.
 *
 * Three things are on screen because a recommendation without them is not
 * usable:
 *   1. THE CALL, stated once, in plain words.
 *   2. HEADROOM -- our pit loss is measured with error, so how much error does
 *      the call survive before it flips? That is the crossover.
 *   3. WHAT ACTUALLY HAPPENED -- the stop counts the field really ran. It is
 *      the only part of this a viewer can check against a race they watched,
 *      which makes it the part that earns trust or loses it.
 */
export function RacePlanView({ playbook }: { playbook: PlaybookArtifact }) {
  const [idx, setIdx] = useState(0);
  const e = playbook.events[idx];

  if (!e) {
    return (
      <p className="panel p-4 text-xs text-fg-dim">
        No event has a computable plan. Run{" "}
        <code className="text-fg">python scripts/09_playbook.py</code>.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <EventPicker events={playbook.events} idx={idx} onPick={setIdx} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <TheCall e={e} />
          <Headroom e={e} />
        </div>
        <div className="space-y-4">
          <Tyres e={e} paceStep={playbook.pace_step_s} />
          <Alternatives e={e} />
        </div>
      </div>
      <RealityCheck e={e} />
    </div>
  );
}

function EventPicker({
  events,
  idx,
  onPick,
}: {
  events: PlaybookEvent[];
  idx: number;
  onPick: (i: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {events.map((e, i) => {
        const agrees = e.actual_median_stops === e.recommended_stops;
        return (
          <button
            key={e.event}
            onClick={() => onPick(i)}
            className={`rounded border px-2.5 py-1 text-xs transition-colors ${
              i === idx
                ? "border-brand bg-brand/15 text-fg"
                : "border-ink-600 text-fg-dim hover:border-ink-500 hover:text-fg"
            }`}
          >
            {e.event.replace(" Grand Prix", "")}
            {/* A dot per event, so the hit rate is visible before you click
                through all seven rather than only after. */}
            <span
              className={`ml-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${
                agrees ? "bg-signal-good" : "bg-signal-warn"
              }`}
            />
          </button>
        );
      })}
    </div>
  );
}

function TheCall({ e }: { e: PlaybookEvent }) {
  const rec = e.plans.find((p) => p.n_stops === e.recommended_stops) ?? e.plans[0];
  const close = e.margin_s < 3;

  return (
    <section className="panel p-5">
      <div className="flex items-baseline justify-between">
        <span className="label">the call</span>
        <span className="label">
          {e.event} · {e.race_laps} laps
        </span>
      </div>

      <div className="mt-2 flex items-baseline gap-3">
        <span className="num text-5xl font-medium leading-none text-fg">{e.recommended_stops}</span>
        <span className="text-lg text-fg-dim">
          {e.recommended_stops === 1 ? "stop" : "stops"}
        </span>
      </div>

      <div className="mt-4">
        <StintAllocation
          compounds={rec.compounds}
          lengths={rec.stint_lengths}
          colors={COMPOUND_COLOR}
          size="sm"
        />
      </div>

      <p className="mt-4 text-xs leading-relaxed text-fg-dim">
        Best of{" "}
        <span className="num text-fg">{e.n_plans_enumerated.toLocaleString()}</span> legal
        strategies, every one enumerated rather than searched, so this is the optimum and not
        wherever a search stopped. It is{" "}
        <span className="num text-fg">{e.margin_s.toFixed(1)}s</span> clear of the best plan at any
        other stop count.
      </p>

      {close && (
        <p className="mt-2 rounded border border-signal-warn/30 bg-signal-warn/5 px-2.5 py-1.5 text-xs text-signal-warn">
          {e.margin_s.toFixed(1)}s over {e.race_laps} laps is close. Treat this as a coin flip
          leaning one way, not a decision.
        </p>
      )}
    </section>
  );
}

/**
 * The sensitivity panel, and the reason this is a tool rather than a readout.
 *
 * Pit loss is measured from a handful of green-flag stops, so it carries real
 * error. The crossover is the pit loss at which the recommendation flips. The
 * distance between the two is how wrong the measurement can be before the
 * answer changes -- which is what a strategist actually needs to know.
 */
function Headroom({ e }: { e: PlaybookEvent }) {
  const x = e.crossover_pit_loss_s;
  const lo = 15;
  const hi = 35;
  const pos = (v: number) => ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * 100;
  const headroom = x === null ? null : Math.abs(x - e.pit_loss_s);

  return (
    <section className="panel p-4">
      <span className="label">how wrong can we be</span>

      <div className="mt-3 relative h-9">
        <div className="absolute inset-x-0 top-4 h-1 rounded-full bg-ink-700" />
        {x !== null && (
          <>
            {/* The band between measured and crossover: the margin of error the
                call tolerates. Coloured by how much rope there is, because a
                wide band is good news and the brand red read as an alarm. */}
            <div
              className={`absolute top-4 h-1 rounded-full ${
                headroom! < 1.5 ? "bg-signal-warn/60" : "bg-signal-good/50"
              }`}
              style={{
                left: `${Math.min(pos(e.pit_loss_s), pos(x))}%`,
                width: `${Math.abs(pos(x) - pos(e.pit_loss_s))}%`,
              }}
            />
            <div
              className="absolute top-1.5 h-6 w-0.5 bg-signal-warn"
              style={{ left: `${pos(x)}%` }}
              title={`flips at ${x.toFixed(1)}s`}
            />
          </>
        )}
        <div
          className="absolute top-0.5 h-8 w-1 rounded-sm bg-fg"
          style={{ left: `${pos(e.pit_loss_s)}%` }}
          title={`measured ${e.pit_loss_s.toFixed(1)}s`}
        />
      </div>
      <div className="flex justify-between text-micro text-fg-faint">
        <span className="num">{lo}s</span>
        <span className="label">pit loss</span>
        <span className="num">{hi}s</span>
      </div>

      <dl className="mt-3 space-y-1 text-xs">
        <Row
          label="measured at this circuit"
          value={`${e.pit_loss_s.toFixed(1)}s`}
          note={`from ${e.n_green_stops} green-flag stops`}
          tone={e.n_green_stops < 4 ? "warn" : undefined}
        />
        {x === null ? (
          <Row
            label="flips to another call at"
            value="never"
            note="no flip between 15s and 35s — not close"
            tone="good"
          />
        ) : (
          <Row
            label="flips to another call at"
            value={`${x.toFixed(1)}s`}
            note={`${headroom!.toFixed(1)}s of headroom`}
            tone={headroom! < 1.5 ? "warn" : "good"}
          />
        )}
      </dl>
    </section>
  );
}

function Tyres({ e, paceStep }: { e: PlaybookEvent; paceStep: number }) {
  const max = Math.max(...e.compounds.map((c) => Math.abs(c.rate.hi)), 0.01);
  return (
    <section className="panel p-4">
      <div className="flex items-baseline justify-between">
        <span className="label">this weekend&apos;s tyres</span>
        <span className="label">seconds lost per lap</span>
      </div>

      <div className="mt-3 space-y-2.5">
        {e.compounds.map((c) => (
          <div key={c.compound} className="text-xs">
            <div className="flex items-baseline gap-2">
              <span
                className="num w-7 rounded px-1 text-center text-micro font-medium text-ink-900"
                style={{ backgroundColor: COMPOUND_COLOR[c.compound] }}
              >
                {c.compound}
              </span>
              <span className="label w-14">{c.label}</span>
              <span className="num text-fg">
                {c.excluded ? "—" : c.rate.mean.toFixed(3)}
              </span>
              <span className="num ml-auto text-fg-faint">
                {c.excluded ? "unusable" : `best ${c.optimal_stint} laps`}
              </span>
            </div>
            {/* The interval, drawn to scale. A wide bar is the honest signal
                that this tyre's rate is barely pinned down. */}
            {!c.excluded && (
              <div className="relative mt-1 ml-9 h-1.5">
                <div className="absolute inset-x-0 top-0.5 h-0.5 bg-ink-700" />
                <div
                  className="absolute top-0 h-1.5 rounded-sm opacity-70"
                  style={{
                    backgroundColor: COMPOUND_COLOR[c.compound],
                    left: `${(Math.max(0, c.rate.lo) / max) * 100}%`,
                    width: `${((c.rate.hi - Math.max(0, c.rate.lo)) / max) * 100}%`,
                  }}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* A shared axis. Without it the interval bars are three unrelated
          smudges; with it they are comparable, which is the only reason to
          draw them to scale in the first place. */}
      <div className="mt-2 ml-9 flex justify-between border-t border-ink-600 pt-1 text-micro text-fg-faint">
        <span className="num">0</span>
        <span>95% interval on the fitted rate</span>
        <span className="num">{max.toFixed(3)}</span>
      </div>

      {e.compounds.some((c) => c.excluded) && (
        <p className="mt-3 text-micro leading-relaxed text-fg-faint">
          A tyre marked unusable had a fitted degradation that was not positive, so the optimiser
          was not allowed to pick it. Hand an optimiser a tyre that never wears and it will run it
          to the flag.
        </p>
      )}
      <p className="mt-2 text-micro leading-relaxed text-fg-faint">
        Fresh-tyre pace gap between adjacent compounds is{" "}
        <span className="num">{paceStep.toFixed(1)}s</span>, assumed rather than measured. It is the
        weakest input on this screen.
      </p>
    </section>
  );
}

function Alternatives({ e }: { e: PlaybookEvent }) {
  const worst = Math.max(...e.plans.map((p) => p.delta_s), 1);
  return (
    <section className="panel p-4">
      <span className="label">what the alternatives cost</span>
      <div className="mt-3 space-y-2">
        {e.plans.map((p) => {
          const best = p.n_stops === e.recommended_stops;
          return (
            <div key={p.n_stops} className="flex items-center gap-2 text-xs">
              <span className={`num w-12 ${best ? "text-fg" : "text-fg-dim"}`}>
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
      <p className="mt-3 text-micro leading-relaxed text-fg-faint">
        Total race time, tyres and pit loss together. The bar is how much slower each stop count is
        than the call.
      </p>
    </section>
  );
}

/**
 * The credibility panel. Everything else on this screen is our own model
 * talking about itself; this is the one number a viewer can check against a
 * race they watched.
 */
function RealityCheck({ e }: { e: PlaybookEvent }) {
  const entries = Object.entries(e.actual_stop_counts).sort(
    (a, b) => Number(a[0]) - Number(b[0]),
  );
  const total = entries.reduce((s, [, n]) => s + n, 0);
  const agrees = e.actual_median_stops === e.recommended_stops;

  if (!entries.length) {
    return null;
  }

  return (
    <section className="panel p-4">
      <div className="flex items-baseline justify-between">
        <span className="label">what the field actually ran</span>
        <span
          className={`label ${agrees ? "text-signal-good" : "text-signal-warn"}`}
        >
          {agrees ? "we agree" : "we disagree"}
        </span>
      </div>

      <div className="mt-3 flex items-end gap-4">
        {entries.map(([stops, n]) => {
          const mine = Number(stops) === e.recommended_stops;
          return (
            <div key={stops} className="flex flex-col items-center gap-1">
              <span className="num text-xs text-fg">{n}</span>
              <div
                className={`w-10 rounded-sm ${mine ? "bg-brand/60" : "bg-ink-600"}`}
                style={{ height: `${Math.max(6, (n / total) * 90)}px` }}
              />
              <span className="num text-micro text-fg-dim">{stops}</span>
            </div>
          );
        })}
        <p className="ml-2 flex-1 text-xs leading-relaxed text-fg-dim">
          {total} cars ran a strategy
          {e.n_retired_before_stop > 0 && (
            <>
              ; <span className="num text-fg">{e.n_retired_before_stop}</span> more never pitted
              and {e.n_retired_before_stop === 1 ? "is" : "are"} held out, since a dry race
              requires two compounds and a car that never stopped retired rather than chose
            </>
          )}
          . The median car made{" "}
          <span className="num text-fg">{e.actual_median_stops}</span> stop
          {e.actual_median_stops === 1 ? "" : "s"}; we called{" "}
          <span className="num text-fg">{e.recommended_stops}</span>.
          {agrees ? (
            " Matching the field is not proof we are right, but disagreeing with every car would be a reason to doubt us."
          ) : (
            " Teams optimise for track position and traffic, we optimise for total time, so a disagreement is not automatically our error — but it is not something to hide either."
          )}
        </p>
      </div>
    </section>
  );
}

function Row({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "good" | "warn";
}) {
  const colour =
    tone === "good" ? "text-signal-good" : tone === "warn" ? "text-signal-warn" : "text-fg";
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-fg-dim">{label}</dt>
      <dd className="text-right">
        <span className={`num ${colour}`}>{value}</span>
        {note && <span className="ml-2 text-micro text-fg-faint">{note}</span>}
      </dd>
    </div>
  );
}
