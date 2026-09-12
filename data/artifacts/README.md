# Clean Air artifacts

JSON written by the pipeline and read by the web app. Committed on purpose, so a
fresh clone renders without running anything.

Contract: `src/cleanair/artifacts/schema.py` (Python) and
`web/src/types/artifacts.ts` (TypeScript). Additive changes only once frozen —
adding an optional field is fine, renaming or retyping one is not. A parity test
fails if the two sides drift.

## What is here

| file | written by | |
|---|---|---|
| `meta.json` | 02 | provenance; `is_real: false` makes the app show a warning banner |
| `degradation.json` | 03 | the brief's primary deliverable: rate per physical compound |
| `ablation.json` | 03 | naive vs deconfounded, for the Deconfound comparison |
| `calibration.json` | 04 | empirical coverage against nominal |
| `power.json` | 04 | how many driver-stints separation actually needs |
| `transfer.json` | 05 | practice → race, predicted vs actual |
| `strategy.json` | 06 | one event in full detail |
| `management.json` | 07 | why softer compounds do not look faster-wearing |
| `benchmark.json` | 08 | scored against the published model |
| `playbook.json` | 09 | every event's call, and what the teams actually ran |

## These are not the live console

The Race Plan view computes its answers from `POST /strategy`, because a pit-loss
slider has no precomputed answer. Everything in this directory is the opposite
case: the same numbers every time, with no inputs to vary.

`playbook.json` sits on the line. It is the precomputed call for all seven
events, and it is what the console **falls back to** when the API is unreachable
— which is a real state worth having, not a broken one. If the service dies
before a demo, seven real races still render.

## Regenerating

```bash
python scripts/run_pipeline.py --publish
```

Individual stages are numbered and safe to run alone. `02_publish_artifacts.py`
copies this directory into `web/public/data`, which is gitignored — the app
reads the copy, not this original.

`--fixtures` writes invented numbers in the real shape instead. Those set
`is_real: false`, so the app can never show fabricated figures without saying so.
