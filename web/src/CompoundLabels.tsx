import { useEffect, useState } from "react";
import { ApiError, getAllocations, type AllocationRow } from "./api";
import { COMPOUND_COLOR, type Compound } from "./types/artifacts";
import { Panel } from "./ui";

/**
 * Why nothing here is grouped by HARD / MEDIUM / SOFT.
 *
 * DERIVED, not written down. The first version of this panel was a hardcoded
 * list -- "HARD at Melbourne, Austria, Hungary, Monza, Monaco" -- which is the
 * exact failure the rest of this work removed: the moment somebody nominates a
 * new race in the app, a prose list is silently wrong and nothing says so.
 *
 * It reads the allocation store instead, so the table is a consequence of the
 * data rather than a claim about it. That also makes it stronger evidence: a
 * reader can see it covers every race we hold rather than a chosen few.
 */

const LABELS = ["HARD", "MEDIUM", "SOFT"] as const;
const CS = ["C1", "C2", "C3", "C4", "C5"] as const;

type Row = {
  compound: string;
  /** label -> events called that at this compound */
  byLabel: Record<string, string[]>;
  total: number;
};

function build(rows: AllocationRow[]): Row[] {
  const table = new Map<string, Record<string, string[]>>();
  for (const r of rows) {
    for (const lab of LABELS) {
      const c = r.compounds[lab];
      if (!c) continue;
      if (!table.has(c)) table.set(c, { HARD: [], MEDIUM: [], SOFT: [] });
      table.get(c)![lab].push(r.event.replace(" Grand Prix", ""));
    }
  }
  return CS.filter((c) => table.has(c)).map((c) => {
    const byLabel = table.get(c)!;
    return {
      compound: c,
      byLabel,
      total: LABELS.reduce((n, l) => n + byLabel[l].length, 0),
    };
  });
}

export function CompoundLabels() {
  const [rows, setRows] = useState<AllocationRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getAllocations(ac.signal)
      .then(setRows)
      .catch((e) => {
        if (e?.name === "AbortError") return;
        setErr(e instanceof ApiError ? e.message : "could not read the nominations");
      });
    return () => ac.abort();
  }, []);

  if (err) {
    return (
      <Panel title="why we never group by hard / medium / soft">
        <p className="text-tiny text-fg-dim">
          {err} — this table is built from the live nominations, so it needs the service.
        </p>
      </Panel>
    );
  }
  if (!rows) return null;

  const table = build(rows);
  // The compound that appears under the most different labels makes the point
  // most sharply, so lead with it rather than with a fixed choice.
  const sharpest = [...table].sort(
    (a, b) =>
      LABELS.filter((l) => b.byLabel[l].length).length -
      LABELS.filter((l) => a.byLabel[l].length).length,
  )[0];

  return (
    <Panel
      title="why we never group by hard / medium / soft"
      meta={`${rows.length} nominations`}
    >
      <p className="text-tiny leading-relaxed text-fg-dim">
        Pirelli nominates three of C1–C5 per weekend, and the timing feed names them HARD,
        MEDIUM and SOFT <em>relative to that nomination</em>. So the label does not identify
        the rubber. Below is every compound we hold, and what it gets called:
      </p>

      <div className="mt-4 space-y-2.5">
        {table.map((r) => (
          <div key={r.compound} className="flex items-start gap-3">
            <span
              className="num mt-0.5 w-9 shrink-0 rounded px-1.5 py-0.5 text-center text-micro font-bold text-ink-950"
              style={{ backgroundColor: COMPOUND_COLOR[r.compound as Compound] }}
            >
              {r.compound}
            </span>
            <div className="flex min-w-0 flex-wrap gap-x-4 gap-y-1">
              {LABELS.map((lab) =>
                r.byLabel[lab].length ? (
                  <span key={lab} className="text-tiny">
                    <span className="label">{lab}</span>{" "}
                    <span className="num text-fg">×{r.byLabel[lab].length}</span>{" "}
                    <span className="text-fg-faint">{r.byLabel[lab].join(", ")}</span>
                  </span>
                ) : null,
              )}
            </div>
          </div>
        ))}
      </div>

      {sharpest && LABELS.filter((l) => sharpest.byLabel[l].length).length > 1 && (
        <p className="mt-4 rounded-md border border-ink-600 bg-ink-900/60 px-3 py-2.5 text-tiny leading-relaxed text-fg-dim">
          <span className="num font-bold text-fg">{sharpest.compound}</span> is one physical
          tyre and is called{" "}
          {LABELS.filter((l) => sharpest.byLabel[l].length).map((l, i, arr) => (
            <span key={l}>
              <span className="text-fg">{l.toLowerCase()}</span> at{" "}
              <span className="num text-fg">{sharpest.byLabel[l].length}</span>
              {i < arr.length - 2 ? ", " : i === arr.length - 2 ? " and " : ""}
            </span>
          ))}{" "}
          of the {sharpest.total} weekends it appears at. Group by the label and you pool
          different rubber while splitting identical rubber apart — which is how a tyre
          analysis ends up reporting that hards wear faster than softs.
        </p>
      )}

      <p className="mt-3 text-micro leading-relaxed text-fg-faint">
        Built from the live nominations rather than written down, so it stays true as races
        are added. The label is still carried alongside, because it is what people say out
        loud.
      </p>
    </Panel>
  );
}
