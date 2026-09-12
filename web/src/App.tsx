import { useState } from "react";
import { DegradationChart } from "./DegradationChart";
import { ConsoleView } from "./ConsoleView";
import { NextRaceView } from "./NextRaceView";
import { EvidenceView } from "./EvidenceView";
import { RaceShapeView } from "./RaceShapeView";
import { ValidationView } from "./ValidationView";
import { useBundle } from "./useBundle";
import { COMPOUND_COLOR, width } from "./types/artifacts";

/**
 * Shell.
 *
 * ORDER MATTERS HERE, so it is worth saying why it changed.
 *
 * This used to open on the degradation curves, with three tabs of statistics
 * behind them. That ordering answers "is this method sound?" first, which is a
 * reviewer's question, and it left the reader to assemble the story from four
 * screens of evidence.
 *
 * A strategist has one question: what do we do on Sunday. So the answer comes
 * first, the Friday-to-Sunday prediction that produces it comes second, the
 * measurement underneath comes third, and the proof that the measurement is
 * sound comes last -- one click away rather than the front door.
 *
 * Nothing was deleted. Every panel that existed still exists.
 */

type ViewId = "next" | "plan" | "record" | "curves" | "evidence";

/**
 * Tabs are the moments a strategist actually has, not the scripts that produce
 * the data.
 *
 * The previous set was named after the pipeline -- Race Plan, Friday to Sunday,
 * Tyre Curves, Proof, Optimiser -- which meant two product tabs, two evidence
 * tabs, one redundant one, and a single tab that jammed together planning a
 * race and reacting mid-race. Those are different jobs done in different
 * states of mind.
 */
const VIEWS: { id: ViewId; label: string; hint: string }[] = [
  { id: "next", label: "Next Race", hint: "The race that has not happened yet" },
  { id: "plan", label: "Strategy", hint: "Set the race state; the call is recomputed live" },
  { id: "record", label: "Track Record", hint: "Predicted against what actually happened" },
  { id: "curves", label: "Tyre Curves", hint: "Clean degradation by physical compound" },
  { id: "evidence", label: "Method", hint: "Deconfounding, benchmark, calibration, power" },
];

export default function App() {
  const [view, setView] = useState<ViewId>("next");
  const state = useBundle();
  const active = VIEWS.find((v) => v.id === view)!;

  if (state.status === "loading") {
    return <Centered>loading…</Centered>;
  }
  if (state.status === "error") {
    return (
      <Centered>
        <p className="text-signal-bad">{state.message}</p>
        <p className="mt-2 text-fg-faint">
          run <code className="text-fg">python scripts/02_publish_artifacts.py --fixtures</code>
        </p>
      </Centered>
    );
  }

  const { meta, degradation } = state.bundle;

  return (
    <div className="flex h-full flex-col">
      {/* The header used to be three spans of 11px text. It is the first thing
          anyone sees, so it now carries an actual mark and the dataset the whole
          app is speaking about. */}
      <header className="flex items-center gap-5 border-b border-ink-600 bg-ink-900/60 px-6 py-3.5 backdrop-blur">
        <div className="flex items-center gap-2.5">
          {/* The mark: three ascending bars, a tyre losing pace. This was three
              CSS spans until the real artwork arrived -- the drawn version has
              the rounded caps and the three-tone red the spans only approximated.
              Trimmed and pre-scaled at build time rather than shipping the
              551px original to draw 24 CSS pixels. */}
          <img
            src="/logo-mark.png"
            alt=""
            aria-hidden
            width={23}
            height={24}
            className="h-6 w-auto select-none"
            draggable={false}
          />
          <h1 className="text-lg font-bold leading-none tracking-tight">CLEAN AIR</h1>
        </div>
        <span className="hidden text-tiny text-fg-dim sm:inline">
          Deconfounded tyre degradation
        </span>
        <div className="ml-auto flex items-center gap-4 text-tiny">
          <span className="num text-fg-dim">
            <span className="text-fg">{meta.season}</span> season
          </span>
          <span className="num text-fg-dim">
            <span className="text-fg">{meta.events.length}</span> events
          </span>
          <span className="num text-fg-dim">
            <span className="text-fg">{meta.n_long_run_laps.toLocaleString()}</span> long-run laps
          </span>
        </div>
      </header>

      {!meta.is_real && (
        <div className="border-b border-signal-warn/30 bg-signal-warn/10 px-5 py-1.5">
          <span className="text-micro uppercase tracking-widest text-signal-warn">
            placeholder data — model output not published yet
          </span>
        </div>
      )}

      <nav className="flex gap-1 border-b border-ink-600 px-5">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            onClick={() => setView(v.id)}
            className={`tab ${v.id === view ? "tab-active" : ""}`}
          >
            {v.label}
          </button>
        ))}
      </nav>

      <main className="flex-1 overflow-auto p-6">
        <div className="mb-5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="text-2xl font-semibold leading-none tracking-tight">{active.label}</h2>
          <p className="text-base text-fg-dim">{active.hint}</p>
          {view === "curves" && (
            <span className="ml-auto label">
              context: {degradation.curves[0]?.context ?? "—"}
            </span>
          )}
        </div>

        {view === "next" ? (
          <NextRaceView />
        ) : view === "plan" ? (
          <ConsoleView playbook={state.bundle.playbook} />
        ) : view === "curves" ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {degradation.curves.map((c) => (
                <div key={c.compound} className="panel p-4">
                  <div className="label flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-full"
                          style={{ background: COMPOUND_COLOR[c.compound] }} />
                    {c.compound}
                    {c.label && <span className="text-fg-faint">· {c.label.toLowerCase()}</span>}
                  </div>
                  <div className="readout mt-1">
                    {c.rate.mean.toFixed(3)}
                    <span className="ml-1 text-xs text-fg-faint">s/lap</span>
                  </div>
                  <div className="num mt-1 text-micro text-fg-faint">
                    ±{(width(c.rate) / 2).toFixed(4)} · {c.n_runs} runs
                  </div>
                </div>
              ))}
              <div className="panel p-4">
                <div className="label">Fuel effect</div>
                {degradation.fuel_coefficient ? (
                  <>
                    <div className="readout mt-1">
                      {degradation.fuel_coefficient.mean.toFixed(4)}
                      <span className="ml-1 text-xs text-fg-faint">s/kg</span>
                    </div>
                    <div className="num mt-1 text-micro text-fg-faint">physics 0.030–0.035</div>
                  </>
                ) : (
                  <>
                    {/* Not a missing value. In races fuel is identical across
                        cars on a given lap, so the design removes it whether or
                        not we know it — we cannot get it wrong. */}
                    <div className="mt-1 text-sm text-signal-good">absorbed by design</div>
                    <div className="mt-1 text-micro leading-snug text-fg-faint">
                      fuel is the same for every car on a lap, so it cancels — no estimate needed
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="panel mt-4 p-4">
              <DegradationChart curves={degradation.curves} />
            </div>

            <p className="mt-3 text-xs text-fg-dim">
              {degradation.separated_pairs.length > 0 ? (
                <>
                  Separated at 95%:{" "}
                  <span className="num text-fg">
                    {degradation.separated_pairs.join(", ").replace(/\|/g, " vs ")}
                  </span>
                </>
              ) : (
                "No compound pair separates at 95% on this fit."
              )}
            </p>
          </>
        ) : view === "record" ? (
          <div className="space-y-6">
            <RaceShapeView playbook={state.bundle.playbook} />
            <ValidationView bundle={state.bundle} />
          </div>
        ) : (
          <EvidenceView bundle={state.bundle} />
        )}
      </main>

      <footer className="flex items-center gap-4 border-t border-ink-600 bg-ink-900/60 px-6 py-2.5">
        <span className="label">Team Pit Wall</span>
        <span className="label text-fg-faint">TrackShift 2026</span>
        <span className="num ml-auto text-micro text-fg-faint">
          schema {meta.schema_version} · model {meta.model_version} · fastf1{" "}
          {meta.fastf1_version}
        </span>
      </footer>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center text-xs text-fg-dim">{children}</div>
    </div>
  );
}
