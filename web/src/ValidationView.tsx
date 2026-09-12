import { scaleLinear } from "d3-scale";
import { COMPOUND_COLOR, type Bundle } from "./types/artifacts";

/**
 * Practice to race: the deliverable the brief actually names.
 *
 * Predicted against actual, one point per (event, compound). Points on the
 * diagonal are right. Everything about how far off we are is visible at once,
 * which is the honest way to show a prediction.
 */

export function ValidationView({ bundle }: { bundle: Bundle }) {
  const { transfer } = bundle;
  const scored = transfer.rows.filter((r) => r.actual !== null);

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          label="mean absolute error"
          value={transfer.mae !== null ? `${transfer.mae.toFixed(4)}` : "—"}
          unit="s/lap"
          note="fit on Friday, predict Sunday"
        />
        <Stat
          label="comparisons"
          value={`${scored.length}`}
          unit={`over ${new Set(scored.map((r) => r.event)).size} events`}
          note="leave-one-event-out"
        />
        <Stat
          label="mode"
          value={transfer.is_forecast ? "forecast" : "validated"}
          unit=""
          note={
            transfer.is_forecast
              ? "the race has not run yet"
              : "compared against actual race pace"
          }
          tone={transfer.is_forecast ? "warn" : "good"}
        />
      </div>

      <section className="panel p-4">
        <h3 className="label mb-1">Predicted vs actual</h3>
        <p className="mb-3 text-xs text-fg-dim">
          On the diagonal is a perfect prediction. Practice degradation runs about twice race
          degradation, so the naive prediction is corrected by a factor learned from the other
          events &mdash; never from the event being predicted.
        </p>
        <Scatter rows={scored} />
      </section>

      <section className="panel p-4">
        <h3 className="label mb-3">Every comparison</h3>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-ink-600 text-left">
              <th className="py-1.5 font-normal text-fg-dim">event</th>
              <th className="py-1.5 font-normal text-fg-dim">compound</th>
              <th className="py-1.5 text-right font-normal text-fg-dim">predicted</th>
              <th className="py-1.5 text-right font-normal text-fg-dim">actual</th>
              <th className="py-1.5 text-right font-normal text-fg-dim">error</th>
            </tr>
          </thead>
          <tbody>
            {transfer.rows.map((r, i) => (
              <tr key={i} className="border-b border-ink-700/60">
                <td className="py-1.5">{r.event.replace(" Grand Prix", "")}</td>
                <td className="py-1.5">
                  <span className="num" style={{ color: COMPOUND_COLOR[r.compound] }}>
                    {r.compound}
                  </span>
                </td>
                <td className="num py-1.5 text-right">{r.predicted.mean.toFixed(4)}</td>
                <td className={`num py-1.5 text-right ${(r.actual ?? 0) < 0 ? "text-signal-bad" : ""}`}>
                  {r.actual !== null ? r.actual.toFixed(4) : "—"}
                </td>
                <td className="num py-1.5 text-right text-fg-dim">
                  {r.abs_error !== null ? r.abs_error.toFixed(4) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {scored.some((r) => (r.actual ?? 0) < 0) && (
          <p className="mt-3 text-xs leading-relaxed text-signal-warn">
            Rows with a negative actual rate are flagged. A tyre cannot get faster as it wears, so
            those measurements are wrong and we say so rather than averaging them away. Two survive
            our identifiability filter and we have not established why &mdash; tyre-age windows,
            post-pit traffic and traffic generally were all tested and ruled out.
          </p>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  unit,
  note,
  tone,
}: {
  label: string;
  value: string;
  unit: string;
  note: string;
  tone?: "good" | "warn";
}) {
  const colour = tone === "good" ? "text-signal-good" : tone === "warn" ? "text-signal-warn" : "text-fg";
  return (
    <div className="panel p-4">
      <div className="label">{label}</div>
      <div className={`readout mt-1 ${colour}`}>
        {value}
        {unit && <span className="ml-1 text-xs text-fg-faint">{unit}</span>}
      </div>
      <div className="mt-1 text-micro text-fg-faint">{note}</div>
    </div>
  );
}

function Scatter({ rows }: { rows: Bundle["transfer"]["rows"] }) {
  const W = 560;
  const H = 300;
  const M = { top: 16, right: 20, bottom: 40, left: 52 };
  if (!rows.length) return null;

  const vals = rows.flatMap((r) => [r.predicted.mean, r.actual ?? 0]);
  const lo = Math.min(...vals) - 0.02;
  const hi = Math.max(...vals) + 0.02;
  const x = scaleLinear().domain([lo, hi]).nice().range([M.left, W - M.right]);
  const y = scaleLinear().domain([lo, hi]).nice().range([H - M.bottom, M.top]);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-h-[320px]"
         preserveAspectRatio="xMidYMid meet" role="img"
         aria-label="Predicted versus actual degradation">
      <line x1={x(lo)} y1={y(lo)} x2={x(hi)} y2={y(hi)}
            stroke="currentColor" className="text-fg-faint" strokeWidth={1} strokeDasharray="4 3" />
      {/* zero lines: anything below the horizontal is a negative actual rate */}
      <line x1={M.left} x2={W - M.right} y1={y(0)} y2={y(0)}
            stroke="currentColor" className="text-signal-bad" strokeWidth={1} opacity={0.35} />

      {x.ticks(5).map((t) => (
        <text key={`x${t}`} x={x(t)} y={H - M.bottom + 15} textAnchor="middle"
              className="fill-fg-faint num" fontSize={9}>
          {t.toFixed(2)}
        </text>
      ))}
      {y.ticks(5).map((t) => (
        <text key={`y${t}`} x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end"
              className="fill-fg-faint num" fontSize={9}>
          {t.toFixed(2)}
        </text>
      ))}
      <text x={(M.left + W - M.right) / 2} y={H - 6} textAnchor="middle" className="fill-fg-dim" fontSize={10}>
        predicted from practice (s/lap)
      </text>
      <text transform={`rotate(-90) translate(${-(H / 2)} 13)`} textAnchor="middle"
            className="fill-fg-dim" fontSize={10}>
        actual race (s/lap)
      </text>

      {rows.map((r, i) => {
        const colour = COMPOUND_COLOR[r.compound];
        const bad = (r.actual ?? 0) < 0;
        return (
          <g key={i}>
            <line x1={x(r.predicted.lo)} x2={x(r.predicted.hi)} y1={y(r.actual ?? 0)} y2={y(r.actual ?? 0)}
                  stroke={colour} strokeWidth={1} opacity={0.4} />
            <circle cx={x(r.predicted.mean)} cy={y(r.actual ?? 0)} r={bad ? 5 : 4}
                    fill={bad ? "none" : colour} stroke={colour} strokeWidth={bad ? 1.5 : 0} />
            <title>
              {r.event} {r.compound}: predicted {r.predicted.mean.toFixed(4)}, actual{" "}
              {r.actual?.toFixed(4)}
            </title>
          </g>
        );
      })}
    </svg>
  );
}
