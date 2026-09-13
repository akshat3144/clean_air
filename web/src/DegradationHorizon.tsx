import { COMPOUND_COLOR, type Compound } from "./types/artifacts";

/**
 * What staying out actually costs, in seconds.
 *
 * A degradation rate of 0.087 s/lap is the right number and the wrong unit for
 * a pit wall. Nobody makes a call on a slope. They make it on "another ten laps
 * on this set costs you nine tenths", which is the same number multiplied by
 * the only thing anyone is deciding.
 *
 * Nothing new is computed. The model fits a straight line in tyre age, so the
 * loss after N laps IS rate x N -- this is the fitted answer stated in the
 * units the question was asked in, interval included.
 */

const HORIZONS = [5, 10, 15] as const;

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
            <th className="py-1.5 pr-3 font-normal text-fg-dim">per lap</th>
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
                const lo = r.rate_lo !== undefined ? r.rate_lo * h : null;
                const hi = r.rate_hi !== undefined ? r.rate_hi * h : null;
                return (
                  <td key={h} className="py-2 pl-3 text-right">
                    <span className="num block text-sm text-fg">{secs(r.rate * h)}</span>
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
