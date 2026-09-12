import { useState } from "react";
import { DegradationChart } from "./DegradationChart";
import { useBundle } from "./useBundle";
import { COMPOUND_COLOR, width } from "./types/artifacts";

/**
 * Shell. The four views are the four beats of the pitch, in the order the brief
 * asks for them: its own deliverables first, our evidence second.
 *
 * Only Degradation is built out. The rest land in Step 7, now that the data
 * contract is frozen and this can be built without waiting for the model.
 */

type ViewId = "curves" | "validation" | "evidence" | "strategy";

const VIEWS: { id: ViewId; label: string; hint: string }[] = [
  { id: "curves", label: "Degradation", hint: "Clean tyre curves by physical compound" },
  { id: "validation", label: "Validation", hint: "Predicted vs actual race pace" },
  { id: "evidence", label: "Evidence", hint: "Deconfounding, benchmark, calibration, power" },
  { id: "strategy", label: "Strategy", hint: "Stint length and stop count" },
];

export default function App() {
  const [view, setView] = useState<ViewId>("curves");
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

        {view === "curves" ? (
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
        ) : (
          <div className="panel flex min-h-64 items-center justify-center p-6">
            <p className="text-xs text-fg-faint">
              {active.label} — built in Step 7. The data contract is frozen, so this can be
              built without waiting for the model.
            </p>
          </div>
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
