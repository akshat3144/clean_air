import { useEffect, useState } from "react";
import { loadBundle, type Bundle } from "./types/artifacts";

type State =
  | { status: "loading" }
  | { status: "ready"; bundle: Bundle }
  | { status: "error"; message: string };

/**
 * Loads every artifact once, at mount.
 *
 * There is no API. The JSON ships with the site, so this is a static fetch and
 * cannot time out mid-demo. If it fails, the files were not published — run
 * `python scripts/02_publish_artifacts.py`.
 */
export function useBundle(): State {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadBundle()
      .then((bundle) => !cancelled && setState({ status: "ready", bundle }))
      .catch((e) => !cancelled && setState({ status: "error", message: String(e.message ?? e) }));
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
