import { COMPOUND_COLOR, type Compound } from "./types/artifacts";

/**
 * What staying out actually costs, in seconds.
 *
 * A degradation rate of 0.087 s/lap is the right number and the wrong unit for
 * a pit wall. Nobody makes a call on a slope. They make it by weighing what the
 * next stretch of laps gives away against the ~22s a stop costs.
 *
 * THE NUMBER THIS USED TO SHOW WAS THE WRONG ONE.
 *
 * It displayed rate x N and called it "seconds lost". That is the PACE DEFICIT
 * -- how much slower one lap is by the time the tyre is N laps old -- not what
 * staying out costs. The cost is the whole triangle underneath: every lap of
 * the stint is slower than the last, and you pay all of them.
 *
 *     rate x N            0.087 x 10  =  0.87s     what it showed
 *     rate x N(N+1)/2     0.087 x 55  =  4.79s     what it costs
 *
 * Understated 3x at five laps, 5.5x at ten, 8x at fifteen -- and it sat next to
 * a 24s pit loss, which is exactly the comparison it invites. At fifteen laps
 * the real figure is 10.4s against a 24s stop, a live decision; the old one
 * read 1.3s, which says never pit.
 *
 * The formula here is `stint_time` from strategy/optimise.py with no pace
 * offset, so this panel and the plan beneath it now price a stint the same way.
 * The pace-deficit reading still has a home: the Tyre Curves tab answers "how
 * will the tyre perform after N laps" in exactly those terms, and labels it as
 * such.
 */

const HORIZONS = [5, 10, 15] as const;

/**
 * Seconds given away over the first N laps of a stint, against a tyre that
 * never wore. Matches `stint_time(n, rate)` in the optimiser.
 */
function cost(rate: number, n: number): number {
  return (rate * n * (n + 1)) / 2;
}

export interface HorizonRow {
  compound: string;
  label: string | null;
  /** Seconds per lap. */
  rate: number;
  rate_lo?: number;
  rate_hi?: number;
  excluded?: boolean;
  /** "thin" under three runs here; "stand-in" where the rate was borrowed. */
  source?: string;
  /** Null on a stand-in that nothing here could scale. */
  severity?: number | null;
}

function secs(v: number): string {
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}s`;
}

export function DegradationHorizon({
  rows,
  note,
}: {
  rows: HorizonRow[];
  note?: string;
}) {
  const usable = rows.filter((r) => !r.excluded);
  if (!usable.length) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-tiny">
        <thead>
          <tr className="border-b border-ink-600/60 text-left">
            <th className="py-1.5 pr-2 font-normal text-fg-dim">tyre</th>
            <th className="py-1.5 pr-3 font-normal text-fg-dim">s/lap</th>
            {HORIZONS.map((h) => (
              <th key={h} className="py-1.5 pl-3 text-right font-normal text-fg-dim">
                +{h} laps
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {usable.map((r) => (
            <tr key={r.compound} className="border-b border-ink-700/40 last:border-0">
              <td className="py-2 pr-2">
                <span className="flex items-center gap-2">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: COMPOUND_COLOR[r.compound as Compound] }}
                    aria-hidden
                  />
                  <span className="text-fg">{r.label ?? r.compound}</span>
                  {r.source === "stand-in" && (
                    <span
                      className="text-micro uppercase tracking-wide text-signal-warn"
                      title={
                        r.severity == null
                          ? "Nobody ran this compound on a race simulation here, and nothing else ran to scale it by. The calendar average, unscaled."
                          : "Nobody ran this compound on a race simulation here. Borrowed from other circuits and rescaled."
                      }
                    >
                      est
                    </span>
                  )}
                  {r.source === "thin" && (
                    <span
                      className="text-micro uppercase tracking-wide text-fg-dim"
                      title="Fewer than three race-simulation runs on this compound here. Measured, but from very little; the band is widened to match."
                    >
                      thin
                    </span>
                  )}
                </span>
              </td>
              <td className="num py-2 pr-3 text-fg-dim">{r.rate.toFixed(3)}</td>
              {HORIZONS.map((h) => {
                const lo = r.rate_lo !== undefined ? cost(r.rate_lo, h) : null;
                const hi = r.rate_hi !== undefined ? cost(r.rate_hi, h) : null;
                return (
                  <td key={h} className="py-2 pl-3 text-right">
                    <span className="num block text-sm text-fg">{secs(cost(r.rate, h))}</span>
                    {lo !== null && hi !== null && (
                      <span className="num block text-micro text-fg-faint">
                        {lo.toFixed(1)} to {hi.toFixed(1)}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {note && <p className="mt-3 text-tiny leading-relaxed text-fg-faint">{note}</p>}
    </div>
  );
}
