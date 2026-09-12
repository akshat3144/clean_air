import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { AblationChart } from "./AblationChart";
import type { Bundle, CalibrationPoint, PowerPoint } from "./types/artifacts";

/**
 * How do you know it is right?
 *
 * Four answers, in the order they carry weight: the deconfounding itself, the
 * power analysis that explains why the published model could not do this, the
 * calibration that shows the uncertainty is honest, and the benchmark scores.
 */

export function EvidenceView({ bundle }: { bundle: Bundle }) {
  const { ablation, power, calibration, benchmark } = bundle;

  return (
    <div className="space-y-5">
      <section className="panel p-4">
        <h3 className="label mb-3">Deconfounding</h3>
        <AblationChart ablation={ablation} />
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="panel p-4">
          <h3 className="label mb-1">How much data does this need?</h3>
          <p className="mb-3 text-xs text-fg-dim">
            Probability of detecting a {power.effect_size.toFixed(3)} s/lap difference between
            two compounds.
          </p>
          <PowerChart points={power.points} benchmarkN={power.benchmark_n} oursN={power.ours_n} />
          <dl className="mt-3 space-y-1 text-xs">
            <Row label="80% power needs" value={`${power.n_for_80pct} driver-stints`} />
            <Row
              label="the published model had"
              value={`${power.benchmark_n} stints`}
              tone="bad"
            />
            <Row label="we have" value={`${power.ours_n} stints`} tone="good" />
          </dl>
          <p className="mt-3 text-xs leading-relaxed text-fg-dim">
            With three stints the published model could not have detected a difference sixteen
            times larger than the one it was looking for. Its null result was a property of the
            design, not a finding about tyres.
          </p>
        </section>

        <section className="panel p-4">
          <h3 className="label mb-1">Is the uncertainty honest?</h3>
          <p className="mb-3 text-xs text-fg-dim">
            When it says 80%, is it right 80% of the time? Perfect calibration is the diagonal.
          </p>
          <CalibrationChart points={calibration.points} />
          <dl className="mt-3 space-y-1 text-xs">
            <Row
              label="coverage of the 80% interval"
              value={`${(calibration.coverage_80 * 100).toFixed(1)}%`}
              tone={Math.abs(calibration.coverage_80 - 0.8) < 0.05 ? "good" : "warn"}
            />
            <Row label="validated on" value={`${calibration.points[0]?.n.toLocaleString()} held-out laps`} />
          </dl>
          <p className="mt-3 text-xs leading-relaxed text-fg-dim">
            Leave-one-run-out, not leave-one-lap-out: laps inside a run are correlated, so holding
            out single laps would let the model see almost the same information and flatter itself.
          </p>
        </section>
      </div>

      <section className="panel p-4">
        <h3 className="label mb-1">Scored against the published benchmark</h3>
        <p className="mb-3 text-xs text-fg-dim">
          Same metrics, same cross-validation scheme, same CRPS estimator &mdash; verified to agree
          with the R reference implementation to 1e-11. Lower is better.
        </p>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-ink-600 text-left">
              <th className="py-1.5 font-normal text-fg-dim">model</th>
              <th className="py-1.5 text-right font-normal text-fg-dim">RMSE (s)</th>
              <th className="py-1.5 text-right font-normal text-fg-dim">CRPS</th>
              <th className="py-1.5 pl-4 font-normal text-fg-dim">source</th>
            </tr>
          </thead>
          <tbody>
            {benchmark.austria_2025.map((s, i) => (
              <tr key={i} className="border-b border-ink-700/60">
                <td className="py-1.5">{s.model}</td>
                <td className="num py-1.5 text-right">{s.rmspe?.toFixed(3) ?? "—"}</td>
                <td className="num py-1.5 text-right">{s.crps?.toFixed(3) ?? "—"}</td>
                <td className="py-1.5 pl-4">
                  <span
                    className={`num text-micro uppercase tracking-wider ${
                      s.source === "ours"
                        ? "text-signal-good"
                        : s.source === "reproduced"
                          ? "text-signal-warn"
                          : "text-fg-faint"
                    }`}
                  >
                    {s.source}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {benchmark.austria_2025.some((s) => s.source === "ours" && s.crps === null) && (
          <p className="mt-3 rounded border border-signal-warn/30 bg-signal-warn/5 px-3 py-2 text-xs leading-relaxed text-signal-warn">
            Our own score is <strong>not yet computed</strong>. Their cross-validation is a
            single driver&apos;s stints, and our design needs the whole field at the same lap, so
            scoring like-for-like means fitting the 2025 field and evaluating on their exact test
            laps. Until that runs, the row stays empty &mdash; we have verified their parameter
            estimates reproduce, not that we beat their scores.
          </p>
        )}
        <p className="mt-3 text-xs leading-relaxed text-fg-dim">
          Their &quot;RMSPE&quot; is a plain RMSE in seconds despite the name, and their total is a
          sum across stints while the CRPS total is a mean. Both traps are pinned by tests that
          reproduce their published 1.082 and 0.202.
        </p>
      </section>
    </div>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" | "warn" }) {
  const colour =
    tone === "good" ? "text-signal-good" : tone === "bad" ? "text-signal-bad" : tone === "warn" ? "text-signal-warn" : "text-fg";
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-fg-dim">{label}</dt>
      <dd className={`num ${colour}`}>{value}</dd>
    </div>
  );
}

function PowerChart({
  points,
  benchmarkN,
  oursN,
}: {
  points: PowerPoint[];
  benchmarkN: number;
  oursN: number;
}) {
  const W = 340;
  const H = 170;
  const M = { top: 10, right: 12, bottom: 28, left: 34 };

  // Log scale: the interesting range spans three orders of magnitude, from the
  // benchmark's three stints to our four hundred.
  const x = scaleLinear()
    .domain([Math.log10(2), Math.log10(Math.max(...points.map((p) => p.n_driver_stints)))])
    .range([M.left, W - M.right]);
  const y = scaleLinear().domain([0, 1]).range([H - M.bottom, M.top]);
  const mk = line<PowerPoint>()
    .x((p) => x(Math.log10(p.n_driver_stints)))
    .y((p) => y(p.power));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Statistical power curve">
      {[0.8].map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)}
                stroke="currentColor" className="text-signal-good" strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
          <text x={W - M.right} y={y(t) - 4} textAnchor="end" className="fill-signal-good num" fontSize={8}>
            80%
          </text>
        </g>
      ))}
      {[0, 0.5, 1].map((t) => (
        <text key={t} x={M.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-fg-faint num" fontSize={8}>
          {(t * 100).toFixed(0)}
        </text>
      ))}

      <line x1={x(Math.log10(benchmarkN))} x2={x(Math.log10(benchmarkN))} y1={M.top} y2={H - M.bottom}
            stroke="currentColor" className="text-signal-bad" strokeWidth={1} />
      <text x={x(Math.log10(benchmarkN)) + 4} y={M.top + 8} className="fill-signal-bad num" fontSize={8}>
        published
      </text>
      <line x1={x(Math.log10(oursN))} x2={x(Math.log10(oursN))} y1={M.top} y2={H - M.bottom}
            stroke="currentColor" className="text-signal-good" strokeWidth={1} />
      <text x={x(Math.log10(oursN)) - 4} y={M.top + 8} textAnchor="end" className="fill-signal-good num" fontSize={8}>
        ours
      </text>

      <path d={mk(points) ?? ""} fill="none" stroke="currentColor" className="text-fg" strokeWidth={2} />
      <text x={(M.left + W - M.right) / 2} y={H - 6} textAnchor="middle" className="fill-fg-dim" fontSize={9}>
        driver-stints (log scale)
      </text>
    </svg>
  );
}

function CalibrationChart({ points }: { points: CalibrationPoint[] }) {
  const W = 340;
  const H = 170;
  const M = { top: 10, right: 12, bottom: 28, left: 34 };
  const s = scaleLinear().domain([0.4, 1]).range([M.left, W - M.right]);
  const y = scaleLinear().domain([0.4, 1]).range([H - M.bottom, M.top]);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Calibration: nominal versus empirical coverage">
      <line x1={s(0.4)} y1={y(0.4)} x2={s(1)} y2={y(1)}
            stroke="currentColor" className="text-fg-faint" strokeWidth={1} strokeDasharray="4 3" />
      {[0.5, 0.8, 1].map((t) => (
        <g key={t}>
          <text x={s(t)} y={H - M.bottom + 12} textAnchor="middle" className="fill-fg-faint num" fontSize={8}>
            {(t * 100).toFixed(0)}
          </text>
          <text x={M.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-fg-faint num" fontSize={8}>
            {(t * 100).toFixed(0)}
          </text>
        </g>
      ))}
      {points.map((p) => (
        <circle key={p.nominal} cx={s(p.nominal)} cy={y(p.empirical)} r={3.5}
                fill="currentColor" className="text-signal-good" />
      ))}
      <text x={(M.left + W - M.right) / 2} y={H - 4} textAnchor="middle" className="fill-fg-dim" fontSize={9}>
        nominal % (empirical on the vertical)
      </text>
    </svg>
  );
}
