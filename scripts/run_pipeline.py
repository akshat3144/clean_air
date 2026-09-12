"""Run everything, in order, with one command.

    python scripts/run_pipeline.py                 # refit and publish
    python scripts/run_pipeline.py --refresh        # pull new data first
    python scripts/run_pipeline.py --event "Spanish Grand Prix" --refresh

This exists for Challenge Day. Regenerating the whole site from a fresh practice
session must be one command, not six scripts run in the right order from memory
while people are watching. It is also what the deployment worker invokes.

Every stage is optional and every stage reports what it did, so a failure part
way through says which stage and leaves the artifacts from the stages that
succeeded.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(label: str, args: list[str], optional: bool = False) -> bool:
    """Run one stage. Returns True on success."""
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}", flush=True)
    t0 = time.time()
    proc = subprocess.run([PY, *args], cwd=ROOT)
    ok = proc.returncode == 0
    mark = "ok" if ok else ("skipped" if optional else "FAILED")
    print(f"-- {label}: {mark} ({time.time() - t0:.1f}s)", flush=True)
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="pull sessions from the F1 API first")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--event", default="Hungarian Grand Prix", help="event for the strategy layer")
    ap.add_argument("--publish", action="store_true", help="copy artifacts into web/public/data")
    ap.add_argument("--skip-validation", action="store_true", help="validation is the slow stage")
    args = ap.parse_args()

    stages: list[tuple[str, list[str], bool]] = []

    if args.refresh:
        stages.append(
            ("1. cache sessions (needs network)",
             ["scripts/01_cache_sessions.py", "--season", str(args.season)], False)
        )

    stages += [
        ("2. fit degradation", ["scripts/03_fit_model.py", "--context", "race"], False),
        ("3. practice to race transfer", ["scripts/05_transfer.py"], False),
        ("4. strategy", ["scripts/06_strategy.py", "--event", args.event], False),
    ]

    if not args.skip_validation:
        # Power analysis and leave-one-run-out calibration are the slow part.
        stages.insert(2, ("validation: power, calibration, scoring",
                          ["scripts/04_validate.py"], False))

    if args.publish:
        stages.append(("publish artifacts", ["scripts/02_publish_artifacts.py"], False))

    t0 = time.time()
    failed = [label for label, argv, opt in stages if not run(label, argv, opt)]

    print(f"\n{'=' * 72}")
    if failed:
        print(f"{len(failed)} stage(s) FAILED after {time.time() - t0:.1f}s:")
        for f in failed:
            print(f"   {f}")
        print("\nArtifacts from the stages that succeeded are still on disk.")
        raise SystemExit(1)

    print(f"all {len(stages)} stages ok in {time.time() - t0:.1f}s")
    if not args.publish:
        print("artifacts written to data/artifacts/ — add --publish to copy into the web app")


if __name__ == "__main__":
    main()
