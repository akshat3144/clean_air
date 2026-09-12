import { useEffect, useState } from "react";
import {
  ApiError,
  getPracticeSessions,
  type PracticeSessions,
  type SessionBreakdown,
  type SessionCell,
} from "./api";
import { COMPOUND_COLOR, type Compound } from "./types/artifacts";
import { Panel, Pill, Skeleton } from "./ui";

/**
 * What each practice session says, before they are blended.
 *
 * A mentor asked the question this panel answers: you have FP1, FP2 and FP3,
 * so summarise each one, then tell me how you combined them. The forecast
 * above answers only the last part -- one number, with the disagreement
 * already averaged away. That is the number a pit wall is least likely to
 * trust, because nothing on screen says where it came from.
 *
 * The sessions are NOT equal, and this panel shows why rather than asserting
 * it. Scored against the races that have already run, FP2's measured
 * degradation correlates 0.84 with the race and FP1's correlates 0.05, so FP2
 * carries twice the weight. Both figures are in the response.
 *
 * Thin cells are shown, not hidden. Two runs of a soft at Madrid carry a
 * standard error of 0.39 s/lap -- wider than any rate on the calendar -- and
 * a strategist needs to see that the number exists AND that it is unusable.
 */

/** Hours as the strategist reads them: "1.5h before", "2h after". */
function clockGap(h: number | null): string {
  if (h === null || h === undefined) return "—";
  if (Math.abs(h) < 0.05) return "at race time";
  const mag = Math.abs(h) % 1 === 0 ? Math.abs(h).toFixed(0) : Math.abs(h).toFixed(1);
  return `${mag}h ${h < 0 ? "before" : "after"}`;
}

function rate(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(3)}`;
}

function CellRow({ cell }: { cell: SessionCell }) {
  const colour = COMPOUND_COLOR[cell.compound as Compound] ?? "#8b8b8b";
  return (
    <div className="flex items-baseline gap-2 py-1">
      <span
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: colour }}
        aria-hidden
      />
      <span className="w-16 shrink-0 text-micro uppercase tracking-wide text-fg-dim">
        {cell.label ?? cell.compound}
      </span>
      <span
        className={`tabular-nums ${cell.thin ? "text-fg-dim line-through decoration-signal-warn/60" : "text-fg"}`}
        title={
          cell.thin
            ? "Fewer than three runs. Shown for completeness; too thin to fit a rate on."
            : undefined
        }
      >
        {rate(cell.rate)}
      </span>
      <span className="text-micro text-fg-dim">s/lap</span>
      <span className="ml-auto shrink-0 text-micro tabular-nums text-fg-dim">
        {cell.n_runs} {cell.n_runs === 1 ? "run" : "runs"} · {cell.n_laps} laps
        {cell.se !== null && ` · ±${(1.96 * cell.se).toFixed(3)}`}
      </span>
    </div>
  );
}

function SessionCard({
  s,
  heaviest,
}: {
  s: SessionBreakdown;
  heaviest: boolean;
}) {
  const tone = heaviest ? "brand" : "neutral";
  return (
    <div
      className={`rounded border p-3 ${
        heaviest ? "border-brand/50 bg-brand/5" : "border-ink-500/60"
      }`}
    >
      <header className="mb-2 flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="title">{s.session}</span>
          <Pill tone={tone}>×{s.weight.toFixed(2)}</Pill>
        </div>
        <span className="text-micro text-fg-dim">{clockGap(s.hours_to_race)}</span>
      </header>

      {!s.has_run ? (
        <p className="text-micro text-fg-dim">Not run yet.</p>
      ) : s.cells.length === 0 ? (
        // A session can run in full and still say nothing about degradation.
        // FP3 is qualifying prep: short, low-fuel, and at Madrid it produced a
        // single long run of five laps. "No race-simulation running" is the
        // honest caption, and it is not the same as "no data".
        <p className="text-micro text-fg-dim">
          Ran, but no race-simulation long runs. Nothing to fit.
        </p>
      ) : (
        <>
          <div className="divide-y divide-ink-600/40">
            {s.cells.map((c) => (
              <CellRow key={`${c.session}-${c.compound}`} cell={c} />
            ))}
          </div>
          <p className="mt-2 text-micro text-fg-dim">
            {s.n_race_sim_runs} race-sim runs · {s.n_race_sim_laps} laps
          </p>
        </>
      )}
    </div>
  );
}

export function PracticeSessionsPanel({ event }: { event: string }) {
  const [data, setData] = useState<PracticeSessions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setData(null);
    setError(null);
    getPracticeSessions(event, ac.signal)
      .then(setData)
      .catch((e) => {
        if (e?.name === "AbortError") return;
        setError(e instanceof ApiError ? e.message : "cannot reach the strategy service");
      });
    return () => ac.abort();
  }, [event]);

  if (error) {
    return (
      <Panel title="Session by session">
        <p className="text-micro text-signal-warn">{error}</p>
      </Panel>
    );
  }

  if (!data) {
    return (
      <Panel title="Session by session">
        <div className="grid gap-3 sm:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      </Panel>
    );
  }

  const heaviest = Object.entries(data.weights).sort((a, b) => b[1] - a[1])[0]?.[0];
  const ev = data.weight_evidence;
  const best = ev[heaviest ?? ""];
  const worst = Object.entries(ev)
    .filter(([, v]) => v.correlation !== null)
    .sort((a, b) => (a[1].correlation ?? 0) - (b[1].correlation ?? 0))[0];

  return (
    <Panel
      title="Session by session"
      meta={`${data.sessions.filter((s) => s.has_run).length} of 3 run`}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {data.sessions.map((s) => (
          <SessionCard key={s.session} s={s} heaviest={s.session === heaviest} />
        ))}
      </div>

      {/* Why the weights are what they are. An unexplained weight is a number
          a strategist will not use, and "because FP2 is the race-sim session"
          is a claim we can put a figure against rather than assert. */}
      {heaviest && best?.correlation !== null && best?.correlation !== undefined && (
        <p className="mt-3 border-t border-ink-600/40 pt-3 text-micro leading-relaxed text-fg-dim">
          <span className="text-fg">{heaviest} carries the most weight.</span> Against the races
          already run this season, its measured degradation tracks the race at a correlation of{" "}
          <span className="tabular-nums text-fg">{best.correlation.toFixed(2)}</span> over{" "}
          {best.n_cells} cells
          {worst && worst[0] !== heaviest && (
            <>
              , where {worst[0]} manages{" "}
              <span className="tabular-nums text-fg">{worst[1].correlation?.toFixed(2)}</span>
            </>
          )}
          . {heaviest} is where the setup is frozen and the heavy-fuel race simulations run; the
          others are setup and qualifying work. No session is weighted to zero — this weekend's
          worst session still beats another circuit's best.
        </p>
      )}
    </Panel>
  );
}
