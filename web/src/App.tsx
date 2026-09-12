import { useState } from "react";
import { DegradationChart } from "./DegradationChart";
import { EvidenceView } from "./EvidenceView";
import { RacePlanView } from "./RacePlanView";
import { StrategyView } from "./StrategyView";
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

type ViewId = "plan" | "friday" | "curves" | "evidence" | "strategy";

const VIEWS: { id: ViewId; label: string; hint: string }[] = [
  { id: "plan", label: "Race Plan", hint: "The call, and how wrong we can be before it changes" },
  { id: "friday", label: "Friday → Sunday", hint: "Predicted from practice, checked against the race" },
  { id: "curves", label: "Tyre Curves", hint: "Clean degradation by physical compound" },
  { id: "evidence", label: "Proof", hint: "Deconfounding, benchmark, calibration, power" },
  { id: "strategy", label: "Optimiser", hint: "One event in full detail" },
];

export default function App() {
  const [view, setView] = useState<ViewId>("plan");
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
      <header className="flex items-baseline gap-4 border-b border-ink-600 px-5 py-3">
        <div className="flex items-baseline gap-2">
          <span className="h-3 w-1 rounded-sm bg-brand" />
          <h1 className="text-sm font-semibold tracking-tight">CLEAN AIR</h1>
        </div>
        <span className="label">Deconfounded Tyre Degradation</span>
        <span className="ml-auto label">
          {meta.season} · {meta.events.length} events · {meta.n_drivers} drivers
        </span>
      </header>

      {!meta.is_real && (
        <div className="border-b border-signal-warn/30 bg-signal-warn/10 px-5 py-1.5">
          <span className="text-micro uppercase tracking-widest text-signal-warn">
            placeholder data — model output not published yet
          </span>
        </div>
      )}

      <nav className="flex gap-1 border-b border-ink-600 px-4">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            onClick={() => setView(v.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-xs transition-colors ${
              v.id === view ? "border-brand text-fg" : "border-transparent text-fg-dim hover:text-fg"
            }`}
          >
            {v.label}
          </button>
        ))}
      </nav>

      <main className="flex-1 overflow-auto p-5">
        <div className="mb-4 flex items-baseline gap-3">
          <h2 className="text-base font-medium">{active.label}</h2>
          <p className="text-xs text-fg-dim">{active.hint}</p>
          {view === "curves" && (
            <span className="ml-auto label">
              context: {degradation.curves[0]?.context ?? "—"}
            </span>
          )}
        </div>

        {view === "plan" ? (
          <RacePlanView playbook={state.bundle.playbook} />
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
        ) : view === "friday" ? (
          <ValidationView bundle={state.bundle} />
        ) : view === "evidence" ? (
          <EvidenceView bundle={state.bundle} />
        ) : (
          <StrategyView bundle={state.bundle} />
        )}
      </main>

      <footer className="flex items-center gap-4 border-t border-ink-600 px-5 py-2">
        <span className="label">Team Pit Wall</span>
        <span className="label">TrackShift 2026</span>
        <span className="num ml-auto text-micro text-fg-faint">
          schema {meta.schema_version} · model {meta.model_version} ·{" "}
          {meta.n_long_run_laps.toLocaleString()} long-run laps
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
