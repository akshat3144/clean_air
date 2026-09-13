import { useEffect, useState } from "react";
import {
  ApiError,
  getPracticeSessions,
  type PracticeSessions,
  type RaceActual,
  type SessionBreakdown,
  type SessionCell,
  type WeightScheme,
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
 * The sessions are NOT equal, and the panel shows why rather than asserting it:
 * the response carries the error of every weighting scheme, scored over the
 * same cells. Per-session correlations are deliberately NOT the argument --
 * each session answers a different number of cells, so ranking them rewards
 * whichever skipped the hard ones.
 *
 * Thin cells are shown, not hidden. One run of a soft at Madrid is worth
 * seeing AND worth distrusting, and only the counts say which.
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
  const tone = heaviest && s.exists ? "brand" : "neutral";
  return (
    <div
      className={`rounded border p-3 ${
        !s.exists
          ? "border-ink-600/40 bg-ink-950/40"
          : heaviest
            ? "border-brand/50 bg-brand/5"
            : "border-ink-500/60"
      }`}
    >
      <header className="mb-2 flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className={`title ${s.exists ? "" : "text-fg-faint"}`}>{s.session}</span>
          {s.exists && <Pill tone={tone}>×{s.weight.toFixed(2)}</Pill>}
        </div>
        {s.exists && (
          <span className="text-micro text-fg-dim">{clockGap(s.hours_to_race)}</span>
        )}
      </header>

      {!s.exists ? (
        // A sprint weekend runs one practice session. Its FP2 is not missing
        // and it is not late -- it does not exist, and saying "not run yet"
        // sends a reader looking for something that is never coming.
        <p className="text-micro text-fg-faint">Not part of a sprint weekend.</p>
      ) : !s.has_run ? (
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

  // Heaviest among the sessions this weekend actually has. FP2 and the
  // Sprint carry the same weight and never share a weekend.
  const heaviest = Object.entries(data.weights)
    .filter(([code]) => data.sessions.some((s) => s.session === code && s.exists))
    .sort((a, b) => b[1] - a[1])[0]?.[0];
  const ev = data.weight_evidence;
  // The shipped scheme and the nearest alternative. Showing the gap between
  // them is the honest version of "FP2 matters": it says how much the choice
  // is worth, rather than asserting that it is right.
  const schemes: WeightScheme[] = ev?.schemes ?? [];
  const shipped = schemes.find((x) => x.scheme.includes("shipped"));
  const equal = schemes.find((x) => x.scheme === "equal");

  // "2 of 3 run" is wrong on a sprint weekend, which only HAS one practice
  // session. Count against what the format offers, not against three.
  const offered = data.sessions.filter((x) => x.exists);
  const run = offered.filter((x) => x.has_run);

  return (
    <Panel
      title="Session by session"
      meta={
        <span className="flex items-center gap-2">
          {data.sprint_weekend && <Pill tone="warn">sprint</Pill>}
          <span>
            {run.length} of {offered.length} run
          </span>
        </span>
      }
    >
      <div
        className={`grid gap-3 ${
          data.sessions.length > 3 ? "sm:grid-cols-2 xl:grid-cols-4" : "sm:grid-cols-3"
        }`}
      >
        {data.sessions.map((s) => (
          <SessionCard key={s.session} s={s} heaviest={s.session === heaviest} />
        ))}
      </div>

      {data.sprint_weekend && (
        <p className="mt-3 border-t border-ink-600/40 pt-3 text-micro text-fg-dim">
          <span className="text-fg">Sprint weekend.</span> One hour of practice and no FP2 —
          but the Sprint itself is twenty cars running one set for eighteen laps at race
          pace, and once it has run it carries the forecast. Until then, FP1 is what there
          is.
        </p>
      )}

      {/* Friday against Sunday, on one screen.
          The brief asks for a post-race tool comparing predicted wear to
          actual race pace, and this is the smallest honest version of it: what
          practice measured, what the race measured, and the gap. A race
          degrades at roughly 38% of its practice rate because drivers nurse a
          tyre and practice pushes it, so the two columns are NOT expected to
          match -- the ratio is the thing to read. */}
      {data.race_actual.length > 0 && <RaceComparison data={data} />}

      {/* Why the weights are what they are. An unexplained weight is a number
          a strategist will not use, and "because FP2 is the race-sim session"
          is a claim we can put a figure against rather than assert. */}
      {/* Only where the weekend actually has the session being explained.
          A sprint weekend runs FP1 and nothing else, and a footnote reasoning
          about FP2's weight underneath three cards that say "not part of a
          sprint weekend" reads as a screen that has not noticed where it is. */}
      {heaviest && shipped && data.sessions.some((s) => s.session === heaviest && s.exists) && (
        <p
          className="mt-3 border-t border-ink-600/40 pt-3 text-micro text-fg-dim"
          title={
            "Every scheme is scored over the same cells, through the pipeline that " +
            "ships. Per-session correlations are not comparable -- each session " +
            "answers a different number of cells."
          }
        >
          <span className="text-fg">{heaviest}</span> is weighted heaviest because it
          predicts best: <span className="tabular-nums text-fg">{shipped.mae.toFixed(4)}</span>{" "}
          s/lap of practice-to-race error
          {equal && (
            <>
              , against <span className="tabular-nums">{equal.mae.toFixed(4)}</span> if every
              session counted equally
            </>
          )}
          . Nothing is weighted to zero.
        </p>
      )}

    </Panel>
  );
}


/** Practice against the race that followed, per compound. */
function RaceComparison({ data }: { data: PracticeSessions }) {
  // Practice side is the heaviest session that actually measured the compound,
  // not a re-blend: this panel exists to show working, and inventing a fourth
  // number here would be one more thing a reader has to take on trust.
  const order = [...data.sessions].sort((a, b) => b.weight - a.weight);
  const practiceOf = (c: string): SessionCell | null => {
    for (const s of order) {
      const hit = s.cells.find((x) => x.compound === c && !x.thin);
      if (hit) return hit;
    }
    return null;
  };

  const rows = data.race_actual
    .map((a: RaceActual) => ({ actual: a, practice: practiceOf(a.compound) }))
    .filter((r) => r.practice);

  if (!rows.length) return null;

  return (
    <div className="mt-4 border-t border-ink-600/40 pt-3">
      <p className="mb-2 text-micro uppercase tracking-[0.1em] text-fg-dim">
        practice against the race
      </p>
      <div className="divide-y divide-ink-600/40">
        {rows.map(({ actual, practice }) => {
          const ratio = practice!.rate !== 0 ? actual.rate / practice!.rate : null;
          return (
            <div key={actual.compound} className="flex items-baseline gap-2 py-1.5">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: COMPOUND_COLOR[actual.compound as Compound] ?? "#8b8b8b" }}
                aria-hidden
              />
              <span className="w-16 shrink-0 text-micro uppercase tracking-wide text-fg-dim">
                {actual.label ?? actual.compound}
              </span>
              <span className="tabular-nums text-fg-dim">{rate(practice!.rate)}</span>
              <span className="text-micro text-fg-dim">{practice!.session}</span>
              <span className="text-fg-faint">→</span>
              <span className="tabular-nums text-fg">{rate(actual.rate)}</span>
              <span className="text-micro text-fg-dim">race</span>
              {ratio !== null && ratio > 0 && (
                <span className="ml-auto shrink-0 text-micro tabular-nums text-fg-dim">
                  ×{ratio.toFixed(2)}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-micro text-fg-faint">
        Not meant to match — a race runs at roughly a third of its practice rate, because
        a driver nurses a tyre on Sunday and pushes it on Friday.
      </p>
    </div>
  );
}
