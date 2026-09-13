import { COMPOUND_COLOR, type CompoundCurve, type Compound } from "./types/artifacts";

/**
 * "How will the tyre perform after 5 laps, 10 laps, 15 laps?"
 *
 * That question was asked in those words, so it is answered in those words
 * rather than left for a reader to measure off the chart beside it. The chart
 * shows the shape; this shows the three numbers a strategist says out loud on
 * the pit wall.
 *
 * Nothing new is computed here. Every value is read straight out of the fitted
 * curve in degradation.json, interval included -- the point being that the
 * model already answers this and only the presentation was missing.
 */

const HORIZONS = [5, 10, 15] as const;

function at(c: CompoundCurve, lap: number) {
  return c.curve.find((p) => p.tyre_life === lap) ?? null;
}

export function HorizonTable({ curves }: { curves: CompoundCurve[] }) {
  if (!curves.length) return null;

  return (
    <div className="panel p-4">
      <h3 className="label mb-1">Lap time lost, by the time the tyre is this old</h3>
      <p className="mb-3 text-xs text-fg-dim">
        Seconds slower than the same tyre when fresh, with the 95% interval beneath. This
        is the pace deficit at that age, not the cost of the stint — every lap on the way
        there was slower too, and the Strategy tab adds them up.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-ink-600 text-left">
              <th className="py-1.5 font-normal text-fg-dim">compound</th>
              <th className="py-1.5 font-normal text-fg-dim">rate</th>
              {HORIZONS.map((h) => (
                <th key={h} className="py-1.5 text-right font-normal text-fg-dim">
                  after {h} laps
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {curves.map((c) => (
              <tr key={c.compound} className="border-b border-ink-700/60 last:border-0">
                <td className="py-2">
                  <span className="flex items-center gap-1.5">
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ background: COMPOUND_COLOR[c.compound as Compound] }}
                    />
                    <span className="num font-medium">{c.compound}</span>
                    {c.label && (
                      <span className="text-fg-faint">· {c.label.toLowerCase()}</span>
                    )}
                  </span>
                </td>
                <td className="num py-2 text-fg-dim">{c.rate.mean.toFixed(3)} s/lap</td>
                {HORIZONS.map((h) => {
                  const p = at(c, h);
                  return (
                    <td key={h} className="py-2 text-right">
                      {p ? (
                        <>
                          <div className="num text-sm text-fg">
                            +{p.delta.mean.toFixed(2)}s
                          </div>
                          <div className="num text-micro text-fg-faint">
                            {p.delta.lo.toFixed(2)} to {p.delta.hi.toFixed(2)}
                          </div>
                        </>
                      ) : (
                        <span className="text-fg-faint">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-tiny leading-relaxed text-fg-faint">
        Pooled across the season, so the interval carries the spread between circuits as well
        as the noise in the fit &mdash; which is why some of them cross zero. Fitted one race
        at a time they are several times tighter; the Method tab has the comparison.
      </p>
    </div>
  );
}
