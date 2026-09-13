import { useState } from "react";

import type { DriverStint, PlaybookArtifact } from "./types/artifacts";
import { Panel } from "./ui";

/**
 * Did this car stop racing before the end?
 *
 * "Retired" is what the timing feed calls it; anything else -- Finished,
 * Lapped, +1 Lap -- saw the flag. A bar that ends on lap 12 looks identical
 * either way, and "retired" and "ran a very short last stint" are not the
 * same race.
 */
function retired(status: string | null): boolean {
  return status === "Retired";
}

/**
 * What every car actually did, against what we said.
 *
 * This is the only claim in the project a viewer can check against a race they
 * watched, so it is worth drawing rather than tabulating. Each row is one car's
 * race; each block is a stint, coloured by the compound the timing feed
 * reported and sized by the laps it actually ran.
 *
 * The stint data comes from RAW race laps while the stop counts printed beside
 * it come from the design frame. Those two agree at every event -- checked --
 * so the picture cannot contradict the number.
 *
 * Colours are Pirelli's own, by LABEL, because that is what a viewer saw on
 * television. Everywhere the model is involved we key on the physical compound
 * instead; this is the one screen showing the race rather than the measurement.
 */
const LABEL_COLOR: Record<string, string> = {
  HARD: "#EDEDED",
  MEDIUM: "#FFD500",
  SOFT: "#FF3B3B",
  INTERMEDIATE: "#43B02A",
  WET: "#0067AD",
};

function color(c: string): string {
  return LABEL_COLOR[c?.toUpperCase?.() ?? ""] ?? "#7A7A7A";
}

type Row = {
  event: string;
  race_laps: number | null;
  stints: DriverStint[];
  actual_median_stops: number | null;
  n_retired_before_stop: number;
  /** null when we declined to call this race. */
  recommended_stops: number | null;
  plan: string | null;
  reason: string | null;
};

export function RaceShapeView({ playbook }: { playbook: PlaybookArtifact }) {
  // Planned races and refused ones in one list. A race we decline to call used
  // to disappear from this tab entirely, so somebody who watched the Japanese
  // Grand Prix just saw it missing. Showing it with the reason is the honest
  // version, and we still have its stints, so the race itself still draws.
  const planned: Row[] = playbook.events
    .filter((e) => (e.stints?.length ?? 0) > 0)
    .map((e) => {
      const rec = e.plans.find((p) => p.n_stops === e.recommended_stops);
      return {
        event: e.event,
        race_laps: e.race_laps,
        stints: e.stints,
        actual_median_stops: e.actual_median_stops,
        n_retired_before_stop: e.n_retired_before_stop,
        recommended_stops: e.recommended_stops,
        plan: rec
          ? rec.compounds.map((c, i) => `${c} ×${rec.stint_lengths[i]}`).join("  +  ")
          : null,
        reason: null,
      };
    });
  const refused: Row[] = (playbook.unavailable ?? [])
    .filter((u) => (u.stints?.length ?? 0) > 0)
    .map((u) => ({
      event: u.event,
      race_laps: u.race_laps,
      stints: u.stints,
      actual_median_stops: u.actual_median_stops,
      n_retired_before_stop: u.n_retired_before_stop,
      recommended_stops: null,
      plan: null,
      reason: u.reason,
    }));
  const withStints = [...planned, ...refused].sort((a, b) =>
    a.event.localeCompare(b.event)
  );

  const [eventName, setEventName] = useState(withStints[0]?.event ?? "");
  const ev: Row | undefined =
    withStints.find((e) => e.event === eventName) ?? withStints[0];

  if (!ev) {
    return (
      <Panel title="Race shape">
        <p className="text-base leading-relaxed text-fg-dim">
          No stint data published yet. Run <span className="num">scripts/09_playbook.py</span>.
        </p>
      </Panel>
    );
  }

  // Group stints by driver, in CLASSIFIED FINISHING ORDER.
  //
  // This used to sort on whoever reached the highest lap number. Every car
  // that goes the full distance ties on that, so the alphabetical tie-break
  // decided the order of everyone who finished: the Austrian Grand Prix listed
  // its eight finishers as ANT HAD HAM LEC NOR PIA RUS VER, with the winner
  // seventh. Four of twenty-one rows were in the right place.
  //
  // Cars with no classification sort last rather than first, so a missing
  // result degrades to the bottom of the chart instead of the top of it.
  const byDriver = new Map<string, typeof ev.stints>();
  for (const s of ev.stints) {
    if (!byDriver.has(s.driver)) byDriver.set(s.driver, []);
    byDriver.get(s.driver)!.push(s);
  }
  const drivers = [...byDriver.entries()]
    .map(([driver, stints]) => ({
      driver,
      stints: [...stints].sort((a, b) => a.start_lap - b.start_lap),
      last: Math.max(...stints.map((s) => s.end_lap)),
      stops: stints.length - 1,
      position: stints[0].position ?? null,
      status: stints[0].status ?? null,
    }))
    .sort(
      (a, b) =>
        (a.position ?? Infinity) - (b.position ?? Infinity) ||
        b.last - a.last ||
        a.driver.localeCompare(b.driver),
    );

  const laps = ev.race_laps ?? Math.max(...ev.stints.map((s) => s.end_lap), 1);
  const agrees =
    ev.recommended_stops !== null && ev.actual_median_stops === ev.recommended_stops;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-1.5">
        {withStints.map((e) => (
          <button
            key={e.event}
            onClick={() => setEventName(e.event)}
            className={`chip ${e.event === ev.event ? "chip-active" : ""}`}
            title={e.reason ?? undefined}
          >
            {e.event.replace(" Grand Prix", "")}
            {e.reason && <span className="ml-1 text-fg-faint">·</span>}
          </button>
        ))}
      </div>

      <Panel
        title="race shape"
        meta={`${drivers.length} cars · ${laps} laps · finishing order`}
      >
        {/* our call, as a reference row */}
        {ev.recommended_stops !== null ? (
          <div className="mb-4 rounded-md border border-signal-good/25 bg-signal-good/5 px-3 py-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="label text-signal-good">Clean Air said</span>
              <span className="num text-lg font-medium text-fg">
                {ev.recommended_stops} stop{ev.recommended_stops === 1 ? "" : "s"}
              </span>
              {ev.plan && <span className="num text-tiny text-fg-dim">{ev.plan}</span>}
              <span className="ml-auto text-tiny text-fg-dim">
                the field ran{" "}
                <span
                  className={`num font-medium ${agrees ? "text-signal-good" : "text-signal-warn"}`}
                >
                  {ev.actual_median_stops ?? "—"}
                </span>{" "}
                (median)
              </span>
            </div>
          </div>
        ) : (
          <div className="mb-4 rounded-md border border-signal-warn/30 bg-signal-warn/5 px-3 py-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="label text-signal-warn">no call on this race</span>
              <span className="ml-auto text-tiny text-fg-dim">
                the field ran{" "}
                <span className="num font-medium text-fg">
                  {ev.actual_median_stops ?? "—"}
                </span>{" "}
                (median)
              </span>
            </div>
            <p className="mt-2 text-tiny leading-relaxed text-fg-dim">{ev.reason}</p>
          </div>
        )}

        <div className="space-y-1">
          {drivers.map((d) => (
            // No entrance animation. Motion here would gate the content on an
            // animation completing, and a staggered fade left 18 of 22 rows at
            // opacity 0 when the event was switched. Every row is data; data is
            // visible or it is a bug.
            <div key={d.driver} className="flex items-center gap-2">
              <span className="num w-6 shrink-0 text-right text-tiny text-fg-faint">
                {d.position ?? "—"}
              </span>
              <span
                className={`num w-10 shrink-0 text-tiny ${
                  retired(d.status) ? "text-fg-faint line-through" : "text-fg-dim"
                }`}
                title={d.status ?? undefined}
              >
                {d.driver}
              </span>
              <div className="relative h-4 flex-1 overflow-hidden rounded-sm bg-ink-800">
                {d.stints.map((s, i) => {
                  const left = ((s.start_lap - 1) / laps) * 100;
                  const width = ((s.end_lap - s.start_lap + 1) / laps) * 100;
                  const n = s.end_lap - s.start_lap + 1;
                  return (
                    <div
                      key={i}
                      title={`${d.driver} · ${s.compound} · laps ${s.start_lap}–${s.end_lap} (${n})`}
                      className="absolute inset-y-0 flex items-center justify-center"
                      style={{
                        left: `${left}%`,
                        width: `${Math.max(width, 0.6)}%`,
                        backgroundColor: color(s.compound),
                      }}
                    >
                      {width > 7 && (
                        <span className="num text-[9px] font-semibold text-ink-950">{n}</span>
                      )}
                    </div>
                  );
                })}
              </div>
              <span
                className={`num w-4 shrink-0 text-right text-tiny ${
                  ev.recommended_stops !== null && d.stops === ev.recommended_stops
                    ? "text-signal-good"
                    : "text-fg-faint"
                }`}
              >
                {d.stops}
              </span>
            </div>
          ))}
        </div>

        <div className="mt-3 flex items-center gap-4 border-t border-ink-600 pt-3">
          {["HARD", "MEDIUM", "SOFT"].map((l) => (
            <span key={l} className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-sm"
                style={{ backgroundColor: color(l) }}
              />
              <span className="text-micro text-fg-dim">{l}</span>
            </span>
          ))}
          <span className="ml-auto text-micro text-fg-faint">
            right-hand number is that car's stop count
          </span>
        </div>
      </Panel>

      <p className="text-tiny leading-relaxed text-fg-dim">
        Bars are the laps each car actually ran on each set, from the timing feed.
        {ev.n_retired_before_stop > 0 && (
          <>
            {" "}
            <span className="num">{ev.n_retired_before_stop}</span> car
            {ev.n_retired_before_stop === 1 ? "" : "s"} never pitted — a dry race needs two
            compounds, so {ev.n_retired_before_stop === 1 ? "it" : "they"} retired before
            stopping and {ev.n_retired_before_stop === 1 ? "is" : "are"} held out of the median
            rather than counted as a one-stop.
          </>
        )}{" "}
        We optimise total time and have no concept of track position, which is the honest
        reason a disagreement is not automatically our error.
      </p>
    </div>
  );
}
