import { useEffect, useRef, useState } from "react";
import { loadBundle, type Bundle } from "./types/artifacts";

type State =
  | { status: "loading" }
  | { status: "ready"; bundle: Bundle; refreshedAt: string | null }
  | { status: "error"; message: string };

/** How often to ask whether the published artifacts have changed. */
const CHECK_MS = 60_000;

/**
 * Loads every artifact, then keeps them current.
 *
 * The JSON ships with the site, so the first load is a static fetch that cannot
 * time out mid-demo. But it used to load ONCE, at mount — which meant a tab
 * left open through a race session kept showing the previous numbers while the
 * poller quietly refreshed the files underneath it. During a live demo that is
 * the failure mode: the pipeline does its job and the screen disagrees.
 *
 * So every minute we re-fetch only `meta.json` — a few hundred bytes — and
 * compare `generated_at`. If it moved, the pipeline republished and we pull the
 * whole bundle again. If it did not, we have spent one tiny request.
 *
 * `cache: "no-store"` on the probe matters: the whole point is to see a file
 * that changed, and a cached 200 would hide exactly that.
 */
export function useBundle(): State {
  const [state, setState] = useState<State>({ status: "loading" });
  // Held in a ref, not state: changing it must not itself trigger a re-render.
  const generatedAt = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const bundle = await loadBundle();
      if (cancelled) return;
      generatedAt.current = bundle.meta?.generated_at ?? null;
      setState({ status: "ready", bundle, refreshedAt: generatedAt.current });
    };

    load().catch(
      (e) => !cancelled && setState({ status: "error", message: String(e.message ?? e) })
    );

    const timer = window.setInterval(async () => {
      if (cancelled) return;
      try {
        const res = await fetch(`/data/meta.json?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) return;
        const meta = (await res.json()) as { generated_at?: string };
        if (meta.generated_at && meta.generated_at !== generatedAt.current) {
          await load();
        }
      } catch {
        // A failed probe is not an error state. The data on screen is still the
        // data we last published; showing a red banner because one poll missed
        // would be worse than quietly trying again in a minute.
      }
    }, CHECK_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return state;
}
