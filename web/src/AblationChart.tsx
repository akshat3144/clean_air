import { useState } from "react";
import { motion } from "framer-motion";
import { scaleLinear } from "d3-scale";
import { COMPOUND_COLOR, type AblationArtifact } from "./types/artifacts";

/**
 * The Deconfound button.
 *
 * One control. Press it and the naive estimates slide to the deconfounded ones,
 * intervals collapsing as they go. The whole thesis in about a second, and the
 * reason this app is custom rather than Streamlit -- you cannot animate a state
 * change like this out of a plotting library.
 *
 * The zero line matters: the naive fit puts MEDIUM at -0.145 s/lap, which claims
 * a worn tyre is three seconds FASTER over a stint. Anything left of zero is
 * physically impossible, so crossing it is the visual argument.
 */

const W = 720;
const H = 300;
const M = { top: 24, right: 24, bottom: 44, left: 96 };

export function AblationChart({ ablation }: { ablation: AblationArtifact }) {
  const [deconfounded, setDeconfounded] = useState(false);
  const rows = ablation.rows;

  const all = rows.flatMap((r) => [r.naive.lo, r.naive.hi, r.deconfounded.lo, r.deconfounded.hi]);
  const x = scaleLinear()
    .domain([Math.min(...all, 0) - 0.01, Math.max(...all, 0) + 0.01])
    .nice()
    .range([M.left, W - M.right]);

  const band = (H - M.top - M.bottom) / rows.length;

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <button
          onClick={() => setDeconfounded((d) => !d)}
          className={`num rounded border px-3 py-1.5 text-xs transition-colors ${
            deconfounded
              ? "border-signal-good/50 bg-signal-good/10 text-signal-good"
              : "border-brand/50 bg-brand/10 text-brand"
          }`}
        >
          {deconfounded ? "✓ deconfounded" : "deconfound →"}
        </button>
        <span className="label">
          {deconfounded
            ? "fuel, track evolution and traffic removed; keyed to physical compound"
            : "lap time regressed on tyre age, no controls — the usual approach"}
        </span>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-h-[320px]"
           preserveAspectRatio="xMidYMid meet" role="img"
           aria-label="Naive versus deconfounded degradation estimates">
        {/* zero line: anything left of it says a worn tyre is faster */}
        <line x1={x(0)} x2={x(0)} y1={M.top - 6} y2={H - M.bottom}
              stroke="currentColor" className="text-fg-faint" strokeWidth={1} strokeDasharray="3 3" />
        <text x={x(0)} y={M.top - 10} textAnchor="middle" className="fill-fg-faint num" fontSize={9}>
          0
        </text>

        {x.ticks(6).map((t) => (
          <text key={t} x={x(t)} y={H - M.bottom + 16} textAnchor="middle"
                className="fill-fg-faint num" fontSize={9}>
            {t.toFixed(2)}
          </text>
        ))}
        <text x={(M.left + W - M.right) / 2} y={H - 8} textAnchor="middle"
              className="fill-fg-dim" fontSize={11}>
          degradation (s/lap) &mdash; negative means a worn tyre is faster, which cannot happen
        </text>

        {rows.map((r, i) => {
          const iv = deconfounded ? r.deconfounded : r.naive;
          const y = M.top + band * i + band / 2;
          const colour = COMPOUND_COLOR[r.compound];
          const impossible = iv.mean < 0;

          return (
            <g key={r.compound}>
              <text x={M.left - 12} y={y} dy="0.32em" textAnchor="end"
                    className="fill-fg num" fontSize={11}>
                {r.compound}
                <tspan className="fill-fg-faint" fontSize={9}>
                  {" "}
                  {r.label?.toLowerCase()}
                </tspan>
              </text>

              {/* A plain rect with plain attributes, and no transition.
                  Two things went wrong before this. framer-motion animates
                  `width` on an SVG rect through CSS rather than the attribute,
                  leaving width="undefined" in the DOM. Replacing that with a
                  CSS transition on x/width was worse: SVG2 exposes those as CSS
                  properties, so the browser held the OLD computed value and the
                  band stopped tracking the interval entirely while the dot moved.
                  The dot and whiskers carry the motion; the band snaps. */}
              <rect
                x={x(iv.lo)}
                width={Math.max(1, x(iv.hi) - x(iv.lo))}
                y={y - 8}
                height={16}
                rx={2}
                fill={colour}
                opacity={0.18}
              />
              <motion.line
                initial={false}
                x1={x(iv.lo)} x2={x(iv.lo)}
                animate={{ x1: x(iv.lo), x2: x(iv.lo) }}
                transition={{ type: "spring", stiffness: 90, damping: 18 }}
                y1={y - 7} y2={y + 7} stroke={colour} strokeWidth={1.5}
              />
              <motion.line
                initial={false}
                x1={x(iv.hi)} x2={x(iv.hi)}
                animate={{ x1: x(iv.hi), x2: x(iv.hi) }}
                transition={{ type: "spring", stiffness: 90, damping: 18 }}
                y1={y - 7} y2={y + 7} stroke={colour} strokeWidth={1.5}
              />
              <motion.circle
                initial={false}
                cx={x(iv.mean)}
                animate={{ cx: x(iv.mean) }}
                transition={{ type: "spring", stiffness: 90, damping: 18 }}
                cy={y} r={4} fill={colour}
              />
              <motion.text
                initial={false}
                x={x(iv.hi) + 10}
                animate={{ x: x(iv.hi) + 10 }}
                transition={{ type: "spring", stiffness: 90, damping: 18 }}
                y={y} dy="0.32em" fontSize={10}
                className={impossible ? "fill-signal-bad num" : "fill-fg-dim num"}
              >
                {iv.mean >= 0 ? "+" : ""}
                {iv.mean.toFixed(3)}
                {impossible ? "  impossible" : ""}
              </motion.text>
            </g>
          );
        })}
      </svg>

      <p className="mt-2 text-xs leading-relaxed text-fg-dim">{ablation.caption}</p>
    </div>
  );
}
