import { useMemo, useState } from "react";
import { scaleLinear } from "d3-scale";
import { COMPOUND_COLOR, type Bundle, type StrategyPlan } from "./types/artifacts";

/**
 * The decision the curves enable.
 *
 * The slider is the point. Pit loss is the input a team can least control and
 * most needs to plan around, so being able to drag it and watch the answer flip
 * is more useful than any single recommendation. It recomputes locally from the
 * tyre time, so it is instant -- no request, nothing to wait for.
 */

export function StrategyView({ bundle }: { bundle: Bundle }) {
  const { strategy } = bundle;
  const [pitLoss, setPitLoss] = useState(strategy.pit_loss_s);

  // total = tyre time + stops x pit loss. Recover tyre time from the stored
  // total at the measured pit loss, then re-score at whatever the slider says.
  const scored = useMemo(() => {
    return strategy.plans
      .map((p) => {
        const tyre = p.total_time.mean - p.n_stops * strategy.pit_loss_s;
        return { plan: p, tyre, total: tyre + p.n_stops * pitLoss };
      })
      .sort((a, b) => a.total - b.total);
  }, [strategy, pitLoss]);

  const bestNow = scored[0];
  const flipped = bestNow.plan.n_stops !== strategy.recommended_stops;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="panel p-4">
          <div className="label">recommended</div>
          <div className="readout mt-1">
            {bestNow.plan.n_stops}
            <span className="ml-1 text-xs text-fg-faint">
              {bestNow.plan.n_stops === 1 ? "stop" : "stops"}
            </span>
          </div>
          <div className="mt-1 text-micro text-fg-faint">
            {bestNow.plan.compounds.map((c, i) => `${c}×${bestNow.plan.stint_lengths[i]}`).join(" → ")}
          </div>
        </div>
        <div className="panel p-4">
          <div className="label">margin over next option</div>
          <div className="readout mt-1">
            {scored[1] ? (scored[1].total - bestNow.total).toFixed(1) : "—"}
            <span className="ml-1 text-xs text-fg-faint">s</span>
          </div>
          <div className="mt-1 text-micro text-fg-faint">over {strategy.race_laps} laps</div>
        </div>
        <div className="panel p-4">
          <div className="label">confidence</div>
          <div
            className={`readout mt-1 ${
              strategy.confidence < 0.4 ? "text-signal-warn" : "text-signal-good"
            }`}
          >
            {(strategy.confidence * 100).toFixed(0)}<span className="ml-1 text-xs text-fg-faint">%</span>
          </div>
          <div className="mt-1 text-micro text-fg-faint">from the margin, not asserted</div>
        </div>
      </div>

      <section className="panel p-4">
        <div className="mb-3 flex flex-wrap items-baseline gap-3">
          <h3 className="label">Pit loss</h3>
          <span className="num text-sm text-fg">{pitLoss.toFixed(1)}s</span>
          {Math.abs(pitLoss - strategy.pit_loss_s) < 0.05 ? (
            <span className="label text-signal-good">measured for this circuit</span>
          ) : (
            <button
              onClick={() => setPitLoss(strategy.pit_loss_s)}
              className="label text-brand underline decoration-dotted"
            >
              reset to measured {strategy.pit_loss_s.toFixed(1)}s
            </button>
          )}
          {flipped && (
            <span className="num text-micro uppercase tracking-wider text-signal-warn">
              the answer has flipped to {bestNow.plan.n_stops}{" "}
              {bestNow.plan.n_stops === 1 ? "stop" : "stops"}
            </span>
          )}
        </div>

        <input
          type="range"
          min={15}
          max={35}
          step={0.1}
          value={pitLoss}
          onChange={(e) => setPitLoss(Number(e.target.value))}
          className="w-full accent-[#e10600]"
          aria-label="pit loss in seconds"
        />

        <CrossoverChart plans={strategy.plans} measured={strategy.pit_loss_s} current={pitLoss} />

        <p className="mt-3 text-xs leading-relaxed text-fg-dim">{strategy.rationale}</p>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="panel p-4">
          <h3 className="label mb-3">Every stop count, at {pitLoss.toFixed(1)}s</h3>
          <table className="w-full text-xs">
            <tbody>
              {scored.map(({ plan, total }, i) => (
                <tr key={plan.n_stops} className="border-b border-ink-700/60">
                  <td className="py-2">
                    <span className={i === 0 ? "text-fg" : "text-fg-dim"}>
                      {plan.n_stops}-stop
                    </span>
                  </td>
                  <td className="py-2">
                    <div className="flex h-3 overflow-hidden rounded-sm">
                      {plan.compounds.map((c, j) => (
                        <div
                          key={j}
                          style={{
                            background: COMPOUND_COLOR[c],
                            width: `${(plan.stint_lengths[j] / plan.stint_lengths.reduce((a, b) => a + b, 0)) * 100}%`,
                          }}
                          title={`${c} × ${plan.stint_lengths[j]} laps`}
                        />
                      ))}
                    </div>
                  </td>
                  <td className="num py-2 pl-3 text-right">
                    {i === 0 ? "best" : `+${(total - scored[0].total).toFixed(1)}s`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel p-4">
          <h3 className="label mb-1">Optimal stint length</h3>
          <p className="mb-3 text-xs text-fg-dim">
            Where spreading the pit loss over more laps stops being worth the extra wear. A harder
            tyre earns a longer stint.
          </p>
          <dl className="space-y-2 text-xs">
            {Object.entries(strategy.optimal_stint).map(([c, iv]) => (
              <div key={c} className="flex items-center gap-3">
                <dt className="num w-8" style={{ color: COMPOUND_COLOR[c as never] }}>
                  {c}
                </dt>
                <dd className="flex-1">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 rounded-full bg-ink-600">
                      <div
                        className="h-1.5 rounded-full"
                        style={{
                          background: COMPOUND_COLOR[c as never],
                          width: `${(iv.mean / strategy.race_laps) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="num w-20 text-right text-fg">
                      {iv.mean.toFixed(0)} laps
                    </span>
                    <span className="num w-16 text-right text-micro text-fg-faint">
                      {iv.lo.toFixed(0)}–{iv.hi.toFixed(0)}
                    </span>
                  </div>
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-micro leading-relaxed text-fg-faint">
            The range shows what happens if pit loss is 15% cheaper or dearer than measured.
          </p>
        </section>
      </div>
    </div>
  );
}

function CrossoverChart({
  plans,
  measured,
  current,
}: {
  plans: StrategyPlan[];
  measured: number;
  current: number;
}) {
  const W = 700;
  const H = 190;
  const M = { top: 14, right: 60, bottom: 34, left: 52 };
  const LO = 15;
  const HI = 35;

  const tyre = plans.map((p) => ({
    n: p.n_stops,
    tyre: p.total_time.mean - p.n_stops * measured,
  }));

  const x = scaleLinear().domain([LO, HI]).range([M.left, W - M.right]);
  const totalsAt = (pl: number) => tyre.map((t) => t.tyre + t.n * pl);
  const all = [...totalsAt(LO), ...totalsAt(HI)];
  const y = scaleLinear()
    .domain([Math.min(...all) - 3, Math.max(...all) + 3])
    .nice()
    .range([H - M.bottom, M.top]);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full max-h-[200px]"
         preserveAspectRatio="xMidYMid meet" role="img"
         aria-label="Total race time by stop count against pit loss">
      {x.ticks(6).map((t) => (
        <text key={t} x={x(t)} y={H - M.bottom + 15} textAnchor="middle"
              className="fill-fg-faint num" fontSize={9}>
          {t}s
        </text>
      ))}
      <text x={(M.left + W - M.right) / 2} y={H - 3} textAnchor="middle" className="fill-fg-dim" fontSize={10}>
        pit loss
      </text>

      <line x1={x(measured)} x2={x(measured)} y1={M.top} y2={H - M.bottom}
            stroke="currentColor" className="text-signal-good" strokeWidth={1} strokeDasharray="3 3" />
      <text x={x(measured)} y={M.top - 3} textAnchor="middle" className="fill-signal-good num" fontSize={8}>
        measured
      </text>
      <line x1={x(current)} x2={x(current)} y1={M.top} y2={H - M.bottom}
            stroke="currentColor" className="text-brand" strokeWidth={1.5} />

      {tyre.map((t) => {
        const y1 = y(t.tyre + t.n * LO);
        const y2 = y(t.tyre + t.n * HI);
        return (
          <g key={t.n}>
            <line x1={x(LO)} y1={y1} x2={x(HI)} y2={y2}
                  stroke="currentColor" className="text-fg" strokeWidth={1.5}
                  opacity={0.35 + 0.2 * t.n} />
            <text x={x(HI) + 6} y={y2} dy="0.32em" className="fill-fg-dim num" fontSize={9}>
              {t.n}-stop
            </text>
          </g>
        );
      })}
    </svg>
  );
}
