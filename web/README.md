# Clean Air — front end

Vite + React + TypeScript. This is the demo; `app/lab.py` is the internal lab
bench and is never shown.

## Running it

The front end needs the Python service for Next Race and Strategy. Two processes:

```bash
python -m uvicorn cleanair.api:app --reload --port 8000
```

```bash
npm install && npm run dev
```

Vite proxies `/api` to port 8000, so the browser sees a single origin and CORS
does not arise in development. Point it somewhere else with `VITE_API_TARGET`.

**With the API stopped**, Tyre Curves, Track Record and Method still work — they
read published artifacts from `public/data`. Strategy falls back to the
precomputed playbook with a banner explaining why the controls are gone. Next
Race says plainly that it needs the service, because the calendar itself comes
from there.

## Two sources of data, and the line between them

| source | what | why |
|---|---|---|
| `public/data/*.json` | degradation curves, calibration, power, benchmark, management, playbook | the same numbers every time; there are no inputs to vary |
| `GET /api/upcoming` | the calendar, per-round readiness, circuit history | discovered from the F1 API, so a new race needs no code change |
| `GET`/`PUT`/`DELETE /api/allocation` | Pirelli's compound nomination | the one fact no feed carries; set and cleared from the app |
| `POST /api/forecast` | Sunday's plan from Friday practice | a race that has not happened has no measured inputs |
| `POST /api/strategy`, `/api/whatif` | the strategy console | recomputed from the controls, so it can answer what nobody precomputed |
| `GET /api/poller` | what the background watcher is doing | it runs unattended; its state should be visible |

The optimiser exists **only in Python**. There is deliberately no TypeScript
copy of it: two implementations of the same arithmetic can disagree, and
disagreeing during a demo is the one failure with no recovery.

## Files worth knowing

| file | |
|---|---|
| `App.tsx` | shell and the five tabs, named after moments not scripts |
| `NextRaceView.tsx` | the race that has not happened yet — the front door |
| `ConsoleView.tsx` | the strategy console |
| `CompoundLabels.tsx` | why nothing is grouped by hard/medium/soft — derived from the live nominations, never written down |
| `useStrategy.ts` | request policy: coarse while dragging, exact on settle |
| `api.ts` | typed client; surfaces the API's own error messages |
| `ui.tsx` | shared primitives and the type scale |
| `types/artifacts.ts` | mirrors `cleanair/artifacts/schema.py`, enforced by a parity test |
| `RacePlanView.tsx` | the offline fallback, rendered from the published playbook |

### The tabs

| tab | the question |
|---|---|
| Next Race | what are we walking into on Sunday? |
| Strategy | practice is in — what is the call, and how wrong can we be? |
| Track Record | were you right? |
| Tyre Curves | the measurement itself |
| Method | why should I believe any of it? |

### Assets

`public/logo.png` is the source artwork. Everything the app loads is derived
from it at a size that makes sense — `logo-mark.png` for the header,
`favicon-32.png`, `apple-touch-icon.png` and `logo-512.png` for icons. The
551px original is never sent to draw 24 CSS pixels. The square icons carry ~18%
padding so the circular mask iOS and Android apply does not clip the outer bars.

### Why two requests per change

The exact enumeration runs to 50,583 allocations at Barcelona, the worst of the
seven, and takes 2.1s cold. The coarse grid answers the same event in 152ms and
picks the same stop count everywhere, which is pinned by a test rather than
assumed.

Those are counts of allocations, not running orders. The optimiser deliberately
keeps one plan per allocation: every stint starts on a fresh tyre, so
resequencing cannot change a plan's total, and emitting all the orderings only
inflated the count 21x and let the hash seed choose between exact ties.

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
