import { useEffect, useRef, useState } from "react";
import { ApiError, postStrategy, type StrategyInput, type StrategyResult } from "./api";

/**
 * Live strategy, recomputed whenever the inputs change.
 *
 * TWO REQUESTS PER SETTLE, ON PURPOSE
 *
 * The exact enumeration (step 1) runs to 337k plans at Hungary and over a
 * million at Barcelona -- seconds, not milliseconds. The coarse grid (step 3)
 * answers in about 70ms and picks the same stop count at every event, which is
 * pinned by a test rather than assumed.
 *
 * So a change fires the coarse request immediately, and the exact one once the
 * inputs have been still for a moment. The headline call is therefore correct
 * from the first frame and only the stint lengths sharpen afterwards, which is
 * why the number never changes under the user's hand.
 *
 * Requests are aborted when superseded. Dragging a slider produces dozens, and
 * without aborting an early slow reply can land after a later fast one and show
 * an answer for inputs nobody is looking at any more.
 */

const COARSE_STEP = 3;
const EXACT_STEP = 1;
const SETTLE_MS = 400;

export type StrategyState = {
  result: StrategyResult | null;
  error: string | null;
  /** A request is in flight. Kept separate from `result` so the last good
   *  answer stays on screen while the next one computes -- a console that
   *  blanks on every keystroke is unreadable. */
  pending: boolean;
  /** The showing result came from the coarse grid. */
  approximate: boolean;
};

export function useStrategy(input: StrategyInput | null): StrategyState {
  const [state, setState] = useState<StrategyState>({
    result: null,
    error: null,
    pending: false,
    approximate: false,
  });

  // Serialised so the effect compares by value, not identity. Without it every
  // parent render rebuilds the object and refires the request.
  const key = input ? JSON.stringify(input) : null;
  const settle = useRef<number | undefined>(undefined);
  // Monotonic request generation. Aborting covers most out-of-order replies,
  // but not all: a fetch already past the network can still resolve after its
  // controller aborts. Stamping every reply and dropping stale generations is
  // what actually guarantees the screen shows the current inputs.
  const gen = useRef(0);

  useEffect(() => {
    if (!key || !input) return;

    const mine = ++gen.current;
    const coarse = new AbortController();
    const exact = new AbortController();
    // Set once the exact answer for THIS generation has landed, so a coarse
    // reply that arrives late cannot overwrite a better one with itself.
    let exactArrived = false;

    const current = () => gen.current === mine;

    setState((s) => ({ ...s, pending: true, error: null }));

    postStrategy({ ...input, step: COARSE_STEP }, coarse.signal)
      .then((r) => {
        if (!current() || exactArrived) return;
        setState({ result: r, error: null, pending: true, approximate: true });
      })
      .catch((e) => {
        if (!current() || e?.name === "AbortError") return;
        setState({
          result: null,
          error: e instanceof ApiError ? e.message : "cannot reach the strategy service",
          pending: false,
          approximate: false,
        });
      });

    window.clearTimeout(settle.current);
    settle.current = window.setTimeout(() => {
      postStrategy({ ...input, step: EXACT_STEP }, exact.signal)
        .then((r) => {
          if (!current()) return;
          exactArrived = true;
          setState({ result: r, error: null, pending: false, approximate: false });
        })
        .catch((e) => {
          if (!current() || e?.name === "AbortError") return;
          // The coarse answer is already on screen and is the same call, so a
          // failed refinement is not worth throwing the view away for.
          setState((s) => ({ ...s, pending: false }));
        });
    }, SETTLE_MS);

    return () => {
      coarse.abort();
      exact.abort();
      window.clearTimeout(settle.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
