import { AnimatePresence, motion } from "framer-motion";
import type { ReactNode } from "react";

/**
 * Shared display primitives.
 *
 * The console had 46 elements at 11px and 33 at 12px, then one at 48px. That
 * is not a hierarchy, and at 11px nothing is readable from across a room. These
 * components exist so hierarchy is chosen from a small set of named steps
 * rather than reinvented with a Tailwind size class at each call site.
 *
 * Motion follows one rule: it may only mark a change that already happened to
 * a value we computed. Nothing here animates to suggest work that is not real,
 * and `prefers-reduced-motion` removes all of it without changing a number.
 */

/** One easing for everything, so movement reads as a single system. */
export const EASE = [0.2, 0.8, 0.2, 1] as const;

/**
 * A number that acknowledges its own change.
 *
 * Keyed on the formatted value, so the old glyphs leave and the new ones
 * arrive. Dragging the pit-loss slider past the crossover flips the call from
 * 2 stops to 1 -- the best moment in the product -- and before this it happened
 * in complete silence.
 */
export function Animated({
  value,
  className = "",
  direction = "up",
}: {
  value: string | number;
  className?: string;
  /** Which way the new value enters. "up" for counts, "none" for tickers. */
  direction?: "up" | "none";
}) {
  const key = String(value);
  const dy = direction === "up" ? "0.35em" : 0;
  return (
    <span className={`relative inline-block ${className}`}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={key}
          initial={{ opacity: 0, y: dy }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: direction === "up" ? "-0.35em" : 0, position: "absolute", left: 0 }}
          transition={{ duration: 0.24, ease: EASE }}
          className="inline-block"
        >
          {key}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

/** A labelled value. The workhorse: label above, number below, optional note. */
export function Stat({
  label,
  value,
  unit,
  note,
  tone,
  size = "lg",
  animate = false,
}: {
  label: string;
  value: string | number;
  unit?: string;
  note?: ReactNode;
  tone?: "good" | "warn" | "bad";
  size?: "lg" | "xl";
  animate?: boolean;
}) {
  const colour =
    tone === "good"
      ? "text-signal-good"
      : tone === "warn"
        ? "text-signal-warn"
        : tone === "bad"
          ? "text-signal-bad"
          : "text-fg";
  return (
    <div>
      <div className="label">{label}</div>
      <div className={`num mt-1 font-medium ${size === "xl" ? "text-xl" : "text-lg"} ${colour}`}>
        {animate ? <Animated value={value} direction="none" /> : value}
        {unit && <span className="ml-1 text-tiny font-normal text-fg-faint">{unit}</span>}
      </div>
      {note && <div className="mt-0.5 text-micro leading-snug text-fg-faint">{note}</div>}
    </div>
  );
}

/** A row in a definition list: label left, value right. */
export function Row({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "good" | "warn" | "bad";
}) {
  const colour =
    tone === "good"
      ? "text-signal-good"
      : tone === "warn"
        ? "text-signal-warn"
        : tone === "bad"
          ? "text-signal-bad"
          : "text-fg";
  return (
    <div className="flex items-baseline justify-between gap-3 text-tiny">
      <dt className="text-fg-dim">{label}</dt>
      <dd className="text-right">
        <span className={`num ${colour}`}>{value}</span>
        {note && <span className="ml-2 text-micro text-fg-faint">{note}</span>}
      </dd>
    </div>
  );
}

/** Panel wrapper with a title and optional right-aligned meta. */
export function Panel({
  title,
  meta,
  children,
  className = "",
  hero = false,
}: {
  title?: string;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  hero?: boolean;
}) {
  return (
    <section className={`${hero ? "panel-hero p-6" : "panel p-4"} ${className}`}>
      {(title || meta) && (
        <header className="mb-3 flex items-baseline justify-between gap-3">
          {title && <h3 className="title">{title}</h3>}
          {meta && <div className="label">{meta}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/**
 * Skeleton placeholder.
 *
 * Replaces the bare "computing…" text. It holds the layout at the size the
 * real content will be, so the panel does not jump when the answer lands.
 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`sweep rounded bg-ink-700 ${className}`} />;
}

/** Status pill: a small piece of state, coloured by meaning. */
export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "brand";
}) {
  const styles = {
    neutral: "border-ink-500 text-fg-dim",
    good: "border-signal-good/40 bg-signal-good/10 text-signal-good",
    warn: "border-signal-warn/40 bg-signal-warn/10 text-signal-warn",
    bad: "border-signal-bad/40 bg-signal-bad/10 text-signal-bad",
    brand: "border-brand/50 bg-brand/10 text-fg",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-micro font-medium uppercase tracking-[0.1em] ${styles}`}
    >
      {children}
    </span>
  );
}

/** A live dot, for state that is genuinely live. */
export function Dot({ tone = "good" }: { tone?: "good" | "warn" | "bad" }) {
  const c =
    tone === "good" ? "bg-signal-good" : tone === "warn" ? "bg-signal-warn" : "bg-signal-bad";
  return (
    <span className="relative inline-flex h-1.5 w-1.5">
      <span className={`absolute inset-0 rounded-full ${c} opacity-70`} />
      <motion.span
        className={`absolute inset-0 rounded-full ${c}`}
        animate={{ scale: [1, 2.4, 1], opacity: [0.6, 0, 0.6] }}
        transition={{ duration: 2.2, repeat: Infinity, ease: "easeOut" }}
      />
    </span>
  );
}

/**
 * The stints a plan allocates -- deliberately not a running order.
 *
 * Every stint in the model starts on a fresh tyre, so a plan's total time is a
 * sum over unordered (compound, laps) pairs. Resequencing cannot change it, and
 * the optimiser has no term for the things that would actually decide the
 * order: track position, traffic, the undercut, warm-up, safety-car risk.
 *
 * This used to render with arrows between the pills. That asserted a call the
 * model never made, and because the tied orderings were enumerated through an
 * unordered set, which one appeared followed the hash seed -- the same data
 * could recommend starting on the hard tyre one day and the medium the next.
 * The separator is a plus, and the caption says what is and is not being
 * claimed.
 */
export function StintAllocation({
  compounds,
  lengths,
  colors,
  size = "base",
  note = true,
}: {
  compounds: string[];
  lengths: (number | undefined)[];
  colors: Record<string, string>;
  size?: "base" | "sm";
  note?: boolean;
}) {
  const pill =
    size === "sm"
      ? "num rounded px-2 py-1 text-xs font-medium text-ink-900"
      : "num rounded-md px-3 py-1.5 text-base font-semibold text-ink-950";
  return (
    <div>
      <div className={`flex flex-wrap items-center ${size === "sm" ? "gap-1.5" : "gap-2"}`}>
        {compounds.map((c, i) => (
          <span key={i} className={`flex items-center ${size === "sm" ? "gap-1.5" : "gap-2"}`}>
            {i > 0 && (
              <span className={`text-fg-faint ${size === "sm" ? "" : "text-lg"}`} aria-hidden>
                +
              </span>
            )}
            <motion.span
              layout
              transition={{ duration: 0.2, ease: EASE }}
              className={pill}
              style={{ backgroundColor: colors[c] }}
            >
              {c} <span className="opacity-60">×</span> {lengths[i]}
            </motion.span>
          </span>
        ))}
      </div>
      {note && (
        <p className="mt-2 text-micro leading-relaxed text-fg-faint">
          Stint lengths, not a running order — swapping stints cannot change the total, so the
          model ranks the allocation and leaves the sequence to you.
        </p>
      )}
    </div>
  );
}
