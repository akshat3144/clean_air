import { line, area } from "d3-shape";
import { scaleLinear } from "d3-scale";
import { COMPOUND_COLOR, type CompoundCurve, type CurvePoint } from "./types/artifacts";

/**
 * Degradation curves with uncertainty bands.
 *
 * Raw SVG on d3 scales rather than a charting library, because these charts are
 * the deliverable and we want exact control over them. d3-shape and d3-scale are
 * pure maths helpers; React owns the DOM.
 */

const W = 720;
const H = 340;
const M = { top: 16, right: 92, bottom: 40, left: 52 };

export function DegradationChart({ curves }: { curves: CompoundCurve[] }) {
  const pts = curves.flatMap((c) => c.curve);
  if (!pts.length) return null;

  const x = scaleLinear()
    .domain([1, Math.max(...pts.map((p) => p.tyre_life))])
    .range([M.left, W - M.right]);
  const y = scaleLinear()
    .domain([0, Math.max(...pts.map((p) => p.delta.hi)) * 1.05])
    .nice()
    .range([H - M.bottom, M.top]);

  const mkLine = line<CurvePoint>()
    .x((p) => x(p.tyre_life))
    .y((p) => y(p.delta.mean));
  const mkBand = area<CurvePoint>()
    .x((p) => x(p.tyre_life))
    .y0((p) => y(p.delta.lo))
    .y1((p) => y(p.delta.hi));

  return (
    // max-h caps the height: the viewBox scales with width, so on a wide screen
    // an uncapped SVG grows taller than the panel and clips its own x-axis.
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-h-[380px]"
         preserveAspectRatio="xMidYMid meet" role="img"
         aria-label="Tyre degradation by compound, with uncertainty bands">
      {y.ticks(5).map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)}
                stroke="currentColor" className="text-ink-600" strokeWidth={1} />
          <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end"
                className="fill-fg-faint font-mono" fontSize={10}>
            {t.toFixed(1)}
          </text>
        </g>
      ))}

      {x.ticks(6).map((t) => (
        <text key={t} x={x(t)} y={H - M.bottom + 16} textAnchor="middle"
              className="fill-fg-faint font-mono" fontSize={10}>
          {t}
        </text>
      ))}

      <text x={(M.left + W - M.right) / 2} y={H - 6} textAnchor="middle"
            className="fill-fg-dim" fontSize={11}>
        tyre age (laps)
      </text>
      <text transform={`rotate(-90) translate(${-(H / 2)} 14)`} textAnchor="middle"
            className="fill-fg-dim" fontSize={11}>
        lap time lost (s)
      </text>

      {curves.map((c) => {
        const col = COMPOUND_COLOR[c.compound];
        const last = c.curve[c.curve.length - 1];
        return (
          <g key={c.compound}>
            <path d={mkBand(c.curve) ?? ""} fill={col} opacity={0.13} />
            <path d={mkLine(c.curve) ?? ""} fill="none" stroke={col} strokeWidth={2} />
            <text x={x(last.tyre_life) + 8} y={y(last.delta.mean)} dy="0.32em"
                  fill={col} className="font-mono" fontSize={11}>
              {c.compound}
            </text>
            <text x={x(last.tyre_life) + 8} y={y(last.delta.mean) + 13} dy="0.32em"
                  className="fill-fg-faint font-mono" fontSize={9}>
              {c.rate.mean.toFixed(3)} s/lap
            </text>
          </g>
        );
      })}
    </svg>
  );
}
