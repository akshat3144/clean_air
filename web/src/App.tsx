import { useState } from "react";

/**
 * Shell only. The four views are the four beats of the pitch, in order:
 * the brief's deliverables first, our credibility apparatus second.
 *
 * Views get built in Step 7. Right now this proves the design system works.
 */

type ViewId = "curves" | "validation" | "evidence" | "strategy";

const VIEWS: { id: ViewId; label: string; hint: string }[] = [
  { id: "curves", label: "Degradation", hint: "Clean tyre curves from practice" },
  { id: "validation", label: "Validation", hint: "Predicted vs actual race pace" },
  { id: "evidence", label: "Evidence", hint: "Deconfounding, benchmark, calibration, power" },
  { id: "strategy", label: "Strategy", hint: "Stint length and stop count" },
];

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-signal-good" : "bg-signal-warn"}`}
    />
  );
}

export default function App() {
  const [view, setView] = useState<ViewId>("curves");
  const active = VIEWS.find((v) => v.id === view)!;

  return (
    <div className="flex h-full flex-col">
      {/* ---- header ---- */}
      <header className="flex items-baseline gap-4 border-b border-ink-600 px-5 py-3">
        <div className="flex items-baseline gap-2">
          <span className="h-3 w-1 rounded-sm bg-brand" />
          <h1 className="text-sm font-semibold tracking-tight">CLEAN AIR</h1>
        </div>
        <span className="label">Deconfounded Tyre Degradation</span>
        <div className="ml-auto flex items-center gap-2">
          <StatusDot ok={false} />
          <span className="label">fixtures — no model output yet</span>
        </div>
      </header>

      {/* ---- nav ---- */}
      <nav className="flex gap-1 border-b border-ink-600 px-4">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            onClick={() => setView(v.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-xs transition-colors ${
              v.id === view
                ? "border-brand text-fg"
                : "border-transparent text-fg-dim hover:text-fg"
            }`}
          >
            {v.label}
          </button>
        ))}
      </nav>

      {/* ---- body ---- */}
      <main className="flex-1 overflow-auto p-5">
        <div className="mb-4">
          <h2 className="text-base font-medium">{active.label}</h2>
          <p className="text-xs text-fg-dim">{active.hint}</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Hard", value: "—", unit: "s/lap", tint: "text-compound-hard" },
            { label: "Medium", value: "—", unit: "s/lap", tint: "text-compound-medium" },
            { label: "Soft", value: "—", unit: "s/lap", tint: "text-compound-soft" },
            { label: "Fuel effect", value: "—", unit: "s/kg", tint: "text-fg" },
          ].map((s) => (
            <div key={s.label} className="panel p-4">
              <div className="label">{s.label}</div>
              <div className={`readout mt-1 ${s.tint}`}>
                {s.value}
                <span className="ml-1 text-xs text-fg-faint">{s.unit}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="panel mt-4 flex min-h-64 items-center justify-center p-6">
          <p className="text-xs text-fg-faint">
            {active.label} view — built in Step 7, once the artifact schema is frozen.
          </p>
        </div>
      </main>

      {/* ---- footer ---- */}
      <footer className="flex items-center gap-4 border-t border-ink-600 px-5 py-2">
        <span className="label">Team Pit Wall</span>
        <span className="label">TrackShift 2026</span>
        <span className="num ml-auto text-micro text-fg-faint">v0.1.0</span>
      </footer>
    </div>
  );
}
