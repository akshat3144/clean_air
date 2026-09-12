# Clean Air — front end

Vite + React + TypeScript. This is the demo; `app/lab.py` is the internal lab
bench and is never shown.

## Running it

The front end needs the Python service for the Race Plan view. Two processes:

```bash
python -m uvicorn cleanair.api:app --reload --port 8000
```

```bash
npm install && npm run dev
```

Vite proxies `/api` to port 8000, so the browser sees a single origin and CORS
does not arise in development. Point it somewhere else with `VITE_API_TARGET`.

**With the API stopped**, Tyre Curves, Friday → Sunday and Proof still work —
they read published artifacts from `public/data`. Race Plan falls back to the
precomputed playbook with a banner explaining why the controls are gone.

## Two sources of data, and the line between them

| source | what | why |
|---|---|---|
| `public/data/*.json` | degradation curves, calibration, power, benchmark, management, playbook | the same numbers every time; there are no inputs to vary |
| `POST /api/strategy`, `/api/whatif` | the strategy console | recomputed from the controls, so it can answer what nobody precomputed |

The optimiser exists **only in Python**. There is deliberately no TypeScript
copy of it: two implementations of the same arithmetic can disagree, and
disagreeing during a demo is the one failure with no recovery.

## Files worth knowing

| file | |
|---|---|
| `App.tsx` | shell and the five views, ordered answer-first |
| `ConsoleView.tsx` | the strategy console — the front door |
| `useStrategy.ts` | request policy: coarse while dragging, exact on settle |
| `api.ts` | typed client; surfaces the API's own error messages |
| `types/artifacts.ts` | mirrors `cleanair/artifacts/schema.py`, enforced by a parity test |
| `RacePlanView.tsx` | the offline fallback, rendered from the published playbook |

### Why two requests per change

The exact enumeration runs to 337k plans at Hungary and over a million at
Barcelona — seconds, not milliseconds. The coarse grid answers in about 70ms and
picks the same stop count at every event, which is pinned by a test rather than
assumed.

So a change fires the coarse request immediately and the exact one once the
inputs have been still for 400ms. The headline call is therefore right from the
first frame and only the stint lengths sharpen, which is why the number never
changes under your hand.

Replies carry a generation stamp and stale ones are dropped. Aborting covers
most out-of-order arrivals but not all — a fetch already past the network can
resolve after its controller aborts — and showing an answer for inputs nobody is
looking at is worse than showing none.

## Build

```bash
npm run build
```

Note `npm run build` runs `tsc -b`, which is stricter than `tsc --noEmit`:
`erasableSyntaxOnly` rejects constructor parameter properties and enums. The
build is the gate, not the editor.
