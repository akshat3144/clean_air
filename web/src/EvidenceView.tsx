import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { AblationChart } from "./AblationChart";
import type { Bundle, CalibrationPoint, ManagementArtifact, PowerPoint } from "./types/artifacts";

/**
 * How do you know it is right?
 *
 * Four answers, in the order they carry weight: the deconfounding itself, the
 * power analysis that explains why the published model could not do this, the
 * calibration that shows the uncertainty is honest, and the benchmark scores.
 */

export function EvidenceView({ bundle }: { bundle: Bundle }) {
  const { ablation, power, calibration, benchmark, management } = bundle;

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

      <Management m={management} />

      <section className="panel p-4">
        <h3 className="label mb-1">Scored against the published benchmark</h3>
        <p className="mb-3 text-xs text-fg-dim">
          Their race, their cross-validation scheme (last quarter of each stint, one lap ahead),
          their CRPS estimator
          {benchmark.r_crosscheck_max_diff != null && (
            <>
              {" "}
              &mdash; which agrees with R&apos;s <span className="num">scoringRules</span> to{" "}
              <span className="num">
                {benchmark.r_crosscheck_max_diff.toExponential(0)}
              </span>
            </>
          )}
          . Lower is better.
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
        <p className="mt-3 rounded border border-signal-warn/30 bg-signal-warn/5 px-3 py-2 text-xs leading-relaxed text-signal-warn">
          <strong>We do not beat them at this.</strong> Their model forecasts one driver&apos;s
          next lap and does it better than ours does.
          {benchmark.ours_season_crps_median != null && benchmark.theirs_season_crps != null && (
            <>
              {" "}
              Across the season our median race scores{" "}
              <span className="num">{benchmark.ours_season_crps_median.toFixed(3)}</span> against
              their <span className="num">{benchmark.theirs_season_crps.toFixed(3)}</span> mean
              &mdash; on {benchmark.ours_season_races} races to their{" "}
              {benchmark.theirs_season_races}, so it is indicative rather than head-to-head.
            </>
          )}{" "}
          What their model cannot do is separate the compounds: their own compound-specific
          version scored <em>worse</em> than their base model, and their best model has no
          compound structure at all. That is the question this project answers, and the power
          analysis above shows their three-stint design could not have.
        </p>
        <p className="mt-3 text-xs leading-relaxed text-fg-dim">
          Their &quot;RMSPE&quot; is a plain RMSE in seconds despite the name, and their total is a
          sum across stints while the CRPS total is a mean. Both traps are pinned by tests that
          reproduce their published 1.082 and 0.202.
        </p>
      </section>
    </div>
  );
}

function Management({ m }: { m: ManagementArtifact }) {
  const max = Math.max(...m.rows.map((r) => Math.abs(r.ratio)), 1);
  return (
    <section className="panel p-4">
      <h3 className="label mb-1">Why softer compounds do not look faster-wearing</h3>
      <p className="mb-4 text-xs leading-relaxed text-fg-dim">
        Softer tyres <em>do</em> degrade faster &mdash; in practice. In a race a driver nurses a
        fragile tyre to hit a target lap time, so the measured degradation is suppressed, and the
        softer the tyre the harder it is nursed. Across {m.n_cells} event-compound cells over{" "}
        {m.n_seasons} seasons:
      </p>

      <div className="space-y-2">
        {m.rows.map((r) => (
          <div key={r.label} className="flex items-center gap-3 text-xs">
            <span className="num w-16 text-fg-dim">{r.label.toLowerCase()}</span>
            <div className="relative h-5 flex-1 overflow-hidden rounded-sm bg-ink-700">
              <div
                className="h-5 rounded-sm bg-brand/40"
                style={{ width: `${(Math.max(0, r.ratio) / max) * 100}%` }}
              />
              <span className="num absolute left-2 top-0 leading-5 text-fg">
                {(r.ratio * 100).toFixed(0)}%
              </span>
            </div>
            <span className="num w-14 text-right text-fg-faint">n={r.n_cells}</span>
          </div>
        ))}
      </div>
      <p className="mt-1 text-micro text-fg-faint">
        share of a tyre&apos;s practice degradation that still shows up in the race
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <dl className="space-y-1 text-xs">
          <Row label="ordering holds" value={m.ordered ? "yes" : "no"} tone={m.ordered ? "good" : "bad"} />
          <Row label="Spearman rho" value={m.rho.toFixed(3)} />
          <Row label="p, direction predicted" value={m.p_one_sided.toFixed(3)}
               tone={m.p_one_sided < 0.05 ? "good" : "warn"} />
          <Row label="p, two-sided" value={m.p_two_sided.toFixed(3)}
               tone={m.p_two_sided < 0.05 ? "good" : "warn"} />
          <Row label="p, ignoring the ordering" value={m.p_kruskal.toFixed(3)} />
        </dl>

        {/* This table is the audit trail, not decoration. At three seasons the
            two-sided p was 0.062 and this claim did NOT hold; it cleared only
            after 2023 and 2022 were added. Both failing rows stay visible, in
            warn colour, because the alternative -- dropping the season that
            disagreed -- would have reached significance by choosing the data
            for its answer. rho is not monotone either, and that shows here. */}
        <div>
          <div className="label mb-1">as seasons were added</div>
          <table className="w-full text-micro">
            <thead>
              <tr className="text-left text-fg-faint">
                <th className="font-normal">seasons</th>
                <th className="text-right font-normal">cells</th>
                <th className="text-right font-normal">rho</th>
                <th className="text-right font-normal">p 2-sided</th>
              </tr>
            </thead>
            <tbody className="num">
              {m.stability.map((s, i) => (
                <tr key={i} className="border-t border-ink-700/60">
                  {/* Five seasons joined by "+" is 24 characters and wrapped
                      the column. The sets are always contiguous, so a range
                      says the same thing. */}
                  <td className="py-0.5 whitespace-nowrap">
                    {s.seasons.length > 2
                      ? `${s.seasons[0]}–${s.seasons[s.seasons.length - 1]}`
                      : s.seasons.join("+")}
                  </td>
                  <td className="py-0.5 text-right">{s.n_cells}</td>
                  <td className="py-0.5 text-right">{s.rho.toFixed(3)}</td>
                  <td className={`py-0.5 text-right ${s.p_two_sided < 0.05 ? "text-signal-good" : "text-signal-warn"}`}>
                    {s.p_two_sided.toFixed(3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className={`mt-3 rounded border px-3 py-2 text-xs leading-relaxed ${
        m.significant
          ? "border-signal-good/30 bg-signal-good/5 text-signal-good"
          : "border-signal-warn/30 bg-signal-warn/5 text-signal-warn"
      }`}>
        {m.verdict}
      </p>
    </section>
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
