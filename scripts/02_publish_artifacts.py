"""Write artifacts and copy them where the web app can read them.

    python scripts/02_publish_artifacts.py --fixtures   # fake numbers, real shape
    python scripts/02_publish_artifacts.py              # real pipeline output

The web app reads /data/*.json at runtime. Those files are copied from
data/artifacts/ into web/public/data/ here, so the app never imports Python and
the two sides only ever meet through this contract.
"""

from __future__ import annotations

import argparse
import json
import shutil

from cleanair.artifacts import fixtures, schema
from cleanair.config import ARTIFACTS, WEB_DATA


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", action="store_true", help="write placeholder data")
    ap.add_argument("--no-copy", action="store_true", help="skip the copy into web/")
    args = ap.parse_args()

    if args.fixtures:
        paths = schema.write_all(fixtures.bundle())
        print(f"wrote {len(paths)} fixture artifacts to {ARTIFACTS}")
    else:
        missing = [n for n in schema.FILES if not (ARTIFACTS / f"{n}.json").exists()]
        if missing:
            raise SystemExit(
                f"missing artifacts: {missing}\n"
                "Run the pipeline first, or use --fixtures for placeholder data."
            )
        paths = [ARTIFACTS / f"{n}.json" for n in schema.FILES]
        print(f"found {len(paths)} artifacts in {ARTIFACTS}")

    meta = json.loads((ARTIFACTS / "meta.json").read_text(encoding="utf-8"))
    if not meta.get("is_real"):
        print("\n  !! these are FIXTURES, not model output.")
        print("     the app shows a warning banner while meta.is_real is false.\n")

    if not args.no_copy:
        WEB_DATA.mkdir(parents=True, exist_ok=True)
        for p in paths:
            shutil.copy2(p, WEB_DATA / p.name)
        print(f"copied into {WEB_DATA}")

    for p in paths:
        print(f"  {p.name:20s} {p.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
