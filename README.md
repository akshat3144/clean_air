# Clean Air

**Deconfounded tyre degradation intelligence — and the strategy console built on top of it.**

Built for the [TrackShift Innovation Challenge 2026](https://www.trackshift.in/) — Plaksha University, with TGR Haas F1 Team and the Mphasis Foundation.
Problem statement: *Tyre Degradation Intelligence*.

> A Formula 1 lap time is three effects fighting each other. Clean Air pulls them
> apart using the whole field at once, then turns the answer into a pit call you
> can argue with — live, for a race that has not happened yet.

---

## The problem

A team needs one number: **how much slower does this tyre get, per lap, as it wears?**

That number is buried, because lap times move for three reasons simultaneously:

| Effect                                 | Direction                |
| -------------------------------------- | ------------------------ |
| Fuel burns off, the car gets lighter   | laps get **faster** |
| The track rubbers in through a session | laps get **faster** |
| The tyre wears out                     | laps get **slower** |

For a **single car in a single session** these three move along the same axis —
lap number. They are mathematically inseparable. No amount of modelling fixes
that, because it is a data problem, not a model problem.

This is not a hypothetical limitation. It is exactly why the only published
model of this problem **cannot tell a Hard tyre from a Medium one.**

---

## The core idea

**Stop modelling the confounders. Subtract them.**

Clean Air pools every car in the field and applies a **within-transformation** —
subtracting the mean lap time of every car on that lap, at that event:

```
adjusted_lap = lap_time − mean(lap_time | event, lap)
```

Every car on lap 30 at Monza burned the same fuel, drove the same rubbered-in
track, ran under the same safety car, in the same weather. Subtracting the
(event, lap) mean removes **all of it at once** — fuel, track evolution,
weather, neutralisations — without estimating a single one of them.

What survives the subtraction is what differs *between cars on the same lap*:
**how old their tyres are, and which compound they are on.** That is the signal.

The identification comes from the fact that drivers start long runs at different
fuel loads, at different points in a session, on different compounds. That
spread is what makes the effects separable — and 2026 helps, with Audi and
Cadillac taking the grid to 11 teams and 22 cars.

*The name is the idea.* In F1 you only see a car's true pace in **clean air**,
with nothing ahead disturbing it. This puts every lap into clean air
mathematically.

---

## What is genuinely new here

**1. Field-level identification instead of per-car modelling.**
The published approach models one driver's lap times as a latent state and tries
to estimate the fuel effect. Ours never estimates fuel at all — it differences it
away. That is why our intervals are tight enough to separate compounds where
theirs are not.

**2. We ran the published model. We did not just cite it.**
Cappello & Hoegh (2025), [arXiv:2512.00640](https://arxiv.org/abs/2512.00640).
We rebuilt their Stan models, reproduced their Table 3, **found a defect in their
fuel calculation, fixed it, and re-ran.** Their null result survived the fix
(separation probability 0.522 → 0.515) — so the tyres really are indistinguishable
from one car's data, and we have the control to prove it rather than assert it.

**3. A power analysis that says their design could never have worked.**
Separating two compounds 0.006 s/lap apart needs **512 driver-stints** for 80%
power. Their study had **3**. We have **417**. This answers an open question
their own paper leaves standing.

**4. We tested a mechanism their paper proposed and left untested.**
Their section 4.3 suggests drivers *manage* softer tyres harder. We tested it
across **five seasons, 20 events, 97 event-compound cells** — and it holds
(below). The direction was fixed by their text before we touched the data.

**5. Physical compounds, not relative labels.**
Everyone else groups by HARD / MEDIUM / SOFT. Those labels are **relative to
whatever three of C1–C5 Pirelli brought that weekend** — C3 is HARD at five races,
MEDIUM at three, and SOFT at Suzuka. Grouping by label averages different rubber
together. Clean Air works in C-numbers throughout, which is why its curves mean
anything at all.

**6. It is a live product, not a results viewer.**
Adding a race to the system requires **no code push**. The calendar is discovered
from the F1 API, session data arrives via an in-process poller, and circuit
history supplies pit loss and race distance. The single human input — Pirelli's
compound nomination — is one click in the UI.

---

## Results

|                                     |                                                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------ |
| **Compound separation**       | ✅ **2 of 4 adjacent pairs cleanly separated** — where the benchmark separates none  |
| **Interval precision**        | ✅ **up to 5.3× tighter** than the published model                                   |
| **Statistical power**         | ✅ **417 driver-stints** vs the 512 needed and the 3 they had                         |
| **Uncertainty is honest**     | ✅ 80% intervals cover **80.5%** empirically                                          |
| **Practice → race**          | ✅ MAE **0.048 s/lap**, a **52% error reduction** over assuming Sunday = Friday |
| **Benchmark reproduced**      | ✅ their Table 3 recovered by running their own code                                       |
| **Driver management effect**  | ✅ **p = 0.0034** across 5 seasons, 97 cells                                          |
| **Strategy call vs reality**  | ✅ **6 of 7 races** match the stop count teams actually ran                           |
| **Forecasts an unraced race** | ✅ Monza predicted from FP1 + FP2, two days out                                            |
| **Test suite**                | ✅ **228 tests**                                                                      |

### Compound separation — the headline

Fitted degradation, 2026 race data, 95% intervals:

| Compound     | Rate (s/lap)      | 95% interval                | Long runs |
| ------------ | ----------------- | --------------------------- | --------- |
| C1 | +0.0420 | [−0.0597, +0.1436] | 19 |
| **C2** | **+0.1675** | **[+0.1305, +0.2044]** | 86 |
| **C3** | **+0.0914** | **[+0.0792, +0.1036]** | 152 |
| C4 | +0.0910 | [+0.0705, +0.1114] | 100 |
| **C5** | **−0.0063** | **[−0.0290, +0.0165]** | 60 |

**C2 vs C3 and C4 vs C5 do not overlap.** The published model's two compounds
overlap almost completely — Hard 0.054 [0.004, 0.133] against Medium 0.060
[0.009, 0.120].

Our tightest interval is **0.0244 wide against their 0.1290** — a 5.3× reduction,
from pooling 417 long runs instead of 3.

### Why softer compounds do not degrade faster in races

In race data the expected ordering is absent — C5 comes out slightly negative.
That is a real result, and it has a tested explanation. In **practice** sessions
softer tyres do degrade faster. The fraction of that practice degradation which
survives into the race **falls monotonically as the tyre softens**:

| Label  | Race ÷ practice rate | Cells |
| ------ | --------------------- | ----- |
| HARD   | **0.506**       | 16    |
| MEDIUM | **0.394**       | 50    |
| SOFT   | **0.173**       | 31    |

Spearman **ρ = −0.295**, one-sided **p = 0.0017**, two-sided **p = 0.0034**,
Kruskal–Wallis **p = 0.0155**. Across **97 cells, 20 events, 5 seasons (2022–2026)**.
Significant on every convention, ordering intact.

**Drivers nurse the fragile tyre, and they nurse it hardest when it is softest.**
The mechanism was predicted in the benchmark paper and never tested. We tested it.

Robustness across seasons, cumulative. The full trail ships in the `stability`
block of `management.json` and is rendered in the app, so the claim is checkable
rather than asserted:

| Seasons              | Cells        | ρ                | p (2-sided)      |
| -------------------- | ------------ | ----------------- | ---------------- |
| 2026                 | 13           | −0.375           | 0.207            |
| 2025–2026           | 29           | −0.416           | 0.025            |
| 2024–2026           | 54           | −0.295           | 0.031            |
| 2023–2026           | 72           | −0.329           | 0.0047           |
| **2022–2026** | **97** | **−0.295** | **0.0034** |

### Against the published benchmark

We score on **their metric, their cross-validation scheme, their CRPS estimator**
— `scoringrules`, cross-checked against the R library they used to **2.5 × 10⁻¹¹**.

Austria 2025, the race they publish:

| Model                             | RMSPE           | CRPS            |
| --------------------------------- | --------------- | --------------- |
| ARIMA(2,1,2)                      | 1.520           | 0.324           |
| SSM base                          | 1.169           | 0.230           |
| SSM compound-specific             | 1.187           | 0.236           |
| **SSM skew-t (their best)** | **1.082** | **0.202** |
| Clean Air pooled                  | 1.250           | 0.241           |

**On their task, their model wins — and we publish that.** Across the 15 races of
2025 they scored, we win 2. Their model is a one-step lap-time forecaster for a
single driver, and it is very good at being one.

That is a different question from the one the brief asks. Their *own*
compound-specific model scored **worse** than their base model, and their best
model **has no compound structure at all** — because, as their power curve shows,
three stints cannot support one. Clean Air is built for the question their
architecture cannot reach: **which tyre, how long, and what does that make the
pit call.**

---

## The product

A **strategy console**. Set the state of the race; it tells you the call, and how
wrong your inputs can be before that call changes.

### Five tabs, named after moments rather than scripts

| Tab                    | The question it answers                                      |
| ---------------------- | ------------------------------------------------------------ |
| **Next Race**    | What are we walking into on Sunday?                          |
| **Strategy**     | Practice is in — what is the call, and how wrong can we be? |
| **Track Record** | Were you right?                                              |
| **Tyre Curves**  | The measurement itself                                       |
| **Method**       | Why should I believe any of it?                              |

### Next Race — the race that has not happened yet

A race becomes answerable in stages, and the screen shows the stage honestly:

```
on the calendar    date and circuit, from the F1 API
+ nominated        Pirelli announced the compounds (the one human input)
+ practice run     long runs exist, so a forecast is possible
+ enough of it     at least two compounds have a usable rate
```

Circuit history supplies what an unraced race cannot: Monza's pit loss is
**25.45 s with a 2.02 s spread across four seasons**, its distance 53 laps — both
labelled as history, because last year's pit lane is evidence about Sunday, not a
reading from it.

### Nothing needs a code push to add a race

| What                          | Where it comes from                               |
| ----------------------------- | ------------------------------------------------- |
| Which races exist             | the F1 calendar — all 23 rounds, future included |
| Session times                 | same, per session, in UTC                         |
| Race distance                 | previous seasons at that circuit                  |
| Pit loss                      | previous seasons at that circuit                  |
| New session data              | the in-process poller, every 15 minutes           |
| **Compound nomination** | **the one thing a human sets — one click** |

Pirelli slides a window of three **adjacent** compounds by circuit severity, so
only three windows exist (C1–C3, C2–C4, C3–C5). The UI offers those three, not
125 dropdown combinations. Values we cited are marked `pirelli`; anything typed
in the app is marked `user`, because those are different kinds of claim.

### The optimiser

Every legal strategy is **enumerated, not searched** — so the answer is the
optimum, not wherever a search stopped. At Barcelona that is **50,583 distinct
allocations in 2.1 s**; a coarse grid answers the same question in 150 ms while
you drag a slider, and a test pins that both pick the same stop count.

It ranks **which compound runs which stint length, and how many stops.** It
deliberately does *not* claim a running order: every stint starts on a fresh
tyre, so resequencing cannot change a plan's total, and the model has no term for
what would actually decide it — track position, traffic, the undercut, warm-up,
safety-car risk. The UI says so on the screen.

Four controls, each because a **measured** quantity carries real error: pit loss,
safety car, degradation (draggable across the model's own 95% interval), and race
laps. Plus **pit now or later**, which prices every stop lap in the next few.

Everything is computed per request in Python. There is deliberately **no
TypeScript reimplementation** — two copies of the same arithmetic can disagree,
and disagreeing in front of an audience is the one failure with no recovery.

If the API is unreachable the console **falls back to the published playbook**
with a banner, rather than an error screen.

---

## Repository

```
src/cleanair/                    the package
  config.py                      verified constants: 2026 regs, benchmark targets, seeds
  api.py                         FastAPI strategy console — everything computed live
  poller.py                      in-process watcher; pulls sessions as they finish, in a subprocess
  fleet.py                       the same estimator pointed at non-F1 sensors
  data/
    schedule.py                  the race calendar, discovered from the API rather than hardcoded
    allocation.py                Pirelli's compound nomination — the one fact no feed carries
    cache.py                     FastF1 session loading and caching
    laps.py                      building the clean-lap dataset and detecting long runs
    fuel.py                      fuel mass estimation, for the ablation only
    traffic.py                   the traffic covariate: how close was the car ahead?
  models/
    design.py                    turns clean laps into a matrix degradation is identifiable from
    mixed.py                     the pooled mixed-effects model — fast, interpretable, the workhorse
    hierarchical.py              hierarchical Bayesian race model, one lap ahead
    ablation.py                  what removing each confounder actually buys
    stan/hier_race.stan          their state-space model with our field-wide pooling
  validation/
    benchmark.py                 scoring against the published model, like for like
    hier_benchmark.py            scores the hierarchical model on their exact predictions
    calibration.py               is the stated uncertainty honest?
    power.py                     how much data separating two compounds actually needs
    scoring.py                   CRPS and RMSPE, defined to match the benchmark exactly
    transfer.py                  practice → race: the deliverable the brief names
    management.py                do drivers manage softer tyres harder in races?
  strategy/
    optimise.py                  enumerate every legal plan, score it, rank allocations
    pitloss.py                   what a pit stop costs, measured, split by track status
  artifacts/
    schema.py                    the contract between the pipeline and the web app
    fixtures.py                  fake artifacts in the real shape, so the app can be built early

scripts/                         numbered, run in order
  01_cache_sessions.py           download and cache every session; Challenge Day needs no network
  02_publish_artifacts.py        write artifacts and copy them where the web app reads them
  03_fit_model.py                fit the degradation model, write the real artifacts
  04_validate.py                 run every validation check
  05_transfer.py                 practice → race
  06_strategy.py                 turn degradation curves into a pit-stop decision
  07_management.py               why softer compounds do not appear to degrade faster
  08_benchmark.py                score us against the published benchmark
  09_playbook.py                 the strategy call for every event, not just one
  10_pit_loss_by_status.py       what a stop costs under a safety car
  11_circuits.py                 per-circuit pit loss and distance, for races not yet run
  run_pipeline.py                run everything, in order, with one command
  fetch_reference.sh             pull reference material we cannot redistribute

benchmark/                       R. Verification only — never part of the product.
  repro.R                        reproduces their Table 3, plus the corrected-fuel test
  stan/                          their four models, migrated to Stan 2.32+ array syntax
  upstream/                      their repo — fetched locally, never committed (no license)

web/                             the demo. Vite + React + TypeScript
  src/App.tsx                    shell and the five tabs
  src/NextRaceView.tsx           the race that has not happened yet — the front door
  src/ConsoleView.tsx            the live strategy console
  src/RacePlanView.tsx           offline fallback, rendered from the published playbook
  src/ValidationView.tsx         practice → race, the deliverable the brief names
  src/EvidenceView.tsx           how do you know it is right?
  src/CompoundLabels.tsx         why nothing is grouped by HARD/MEDIUM/SOFT — derived live
  src/DegradationChart.tsx       degradation curves with uncertainty bands
  src/AblationChart.tsx          the Deconfound button
  src/ui.tsx                     shared display primitives and the type scale
  src/api.ts                     typed client for the live optimiser
  src/useStrategy.ts             coarse while dragging, exact on settle, generation-guarded
  src/useBundle.ts               loads every artifact once, at mount
  src/types/artifacts.ts         mirrors schema.py, enforced by a parity test

data/
  artifacts/*.json               the JSON contract the web app reads — committed on purpose
  schedule/2026.json             cached calendar, so a demo survives having no network
  allocation.json                compound nominations, editable from the app

app/lab.py                       Streamlit lab bench — internal, never demoed
docs/DEPLOYMENT.md               how this ships
docs/reference/                  the benchmark paper, plus licensing notes on every source
tests/                           228 tests
```

---

## Run it

**Python**

```bash
python -m venv .venv && .venv/Scripts/activate && pip install -e ".[lab,dev]"
```

`pandas` is pinned below 3.0 because `fastf1` 3.8.3 requires it, so the venv is
not optional.

**The console** — two processes:

```bash
python -m uvicorn cleanair.api:app --reload --port 8000
```

```bash
cd web && npm install && npm run dev
```

Vite proxies `/api` to port 8000, so the browser sees one origin and CORS never
arises in development. Set `CLEANAIR_POLL=1` to start the background poller
alongside the API — off by default, so running locally does not silently begin
pulling sessions.

Tyre Curves, Track Record and Method read published artifacts and work with the
API stopped. Next Race and Strategy need it, and say so plainly.

**Stan** (hierarchical model and benchmark only) — CmdStan 2.39.0 in `~/.cmdstan/`,
shared by `cmdstanpy` and `cmdstanr`. On this machine, put Rtools ahead of the
2016-era MinGW on PATH first:

```bash
export PATH="/c/rtools45/x86_64-w64-mingw32.static.posix/bin:/c/rtools45/usr/bin:$PATH"
```

---

## Known limits

- **Softer compounds do not show faster race degradation.** Tyre-age windowing,
  unidentifiable cells, post-pit traffic and traffic as a covariate are all ruled
  out — traffic moves rates by less than 0.015 s/lap. The management effect
  explains *why* the ordering is absent; it does not recover it.
- **The compound pace offset is assumed, not fitted** — 0.6 s per step, surfaced
  in the UI as the weakest input on the screen. Race data confounds compound
  choice with car pace; practice data confounds it with fuel load.
- **A full safety car is not measurable from this data.** 23 stops across two
  events disagree by 15 s. The VSC figure **is** measured: **0.84× a green
  stop**, from 48 VSC stops against 163 green ones.
- **The optimiser minimises total time and has no concept of track position**,
  which is the real reason teams pit under a safety car.
- **Two of nine practice→race cells have negative actual rates**, cause not
  established.

---

## Beyond motorsport

The estimator isolates a true wear signal from confounded operating conditions.
Indian commercial fleets replace and retread tyres on odometer readings — which
mix load, gradient, surface and driving style exactly the way lap time mixes
fuel, traffic and track evolution.

We are **not** claiming a validated fleet result; we have no fleet data. We are
claiming a transferable estimator, shipped with a documented adapter interface
(`src/cleanair/fleet.py`) so anyone with that data can test it.

---

## License

MIT. The benchmark paper is redistributed under CC BY 4.0; the authors' code
carries no license and is fetched locally, never committed.
