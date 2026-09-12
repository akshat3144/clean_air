# Clean Air

**Separating true tyre wear from fuel load, traffic and track evolution.**

Built for the [TrackShift Innovation Challenge 2026](https://www.trackshift.in/) — Plaksha University, with TGR Haas F1 Team and the Mphasis Foundation. Problem statement: *Tyre Degradation Intelligence*.

---

## The problem

A Formula 1 team needs to know how much slower a tyre gets as it wears. That is **tyre degradation**, measured in seconds lost per lap.

The trouble is that lap times move for three reasons at the same time:

| Effect | Direction |
|---|---|
| Fuel burns off, car gets lighter | laps get **faster** |
| Track rubbers in during a session | laps get **faster** |
| Tyre wears out | laps get **slower** |

A raw lap time mixes all three together. The first two are **confounders** — things that contaminate the measurement you actually want.

Worse, for a single car in a single session, the three effects move along the same time axis. They are mathematically inseparable. No amount of clever statistics fixes that, because it is a data problem, not a modelling problem.

**Clean Air separates them by pooling the whole field.** Different drivers start long runs at different fuel loads and at different points in a session, and compounds are spread unevenly across the grid. That variation is what makes the three effects tell apart. 2026 helps: Audi and Cadillac bring the grid to 11 teams and 22 cars.

The name is the idea. In F1 you only see a car's real pace in *clean air*, with nothing ahead disturbing it. This puts every lap into clean air mathematically.

---

## Where this stands against published work

There is one published model of this problem: **Cappello & Hoegh (2025)**, [arXiv:2512.00640](https://arxiv.org/abs/2512.00640), with [code on GitHub](https://github.com/colecappello12/F1_SSM_Paper). It is careful work. It also **cannot tell a Hard tyre apart from a Medium one** — its uncertainty ranges overlap almost completely (Hard 0.054 s/lap [0.004, 0.133], Medium 0.060 [0.009, 0.120]).

Their own conclusion names the fix: extend across multiple races and drivers, and explore hierarchical structures. We are building that, and measuring what it buys.

We did not take their paper's word for any of it. We ran their code.

**What we found by running it:**

- **Their result reproduces.** Our run: Hard 0.0550 [0.0032, 0.1339], Medium 0.0555 [0.0068, 0.1165].
- **Their null result is genuine, not a bug.** We found a defect in their fuel calculation, fixed it, and re-ran. It changed nothing (separation probability 0.522 → 0.515). So the tyres really are indistinguishable from one car's data, and we have the control to prove it.
- **Their fitted fuel coefficient is about half the physical value** — 0.016 s/kg against the 0.030–0.035 that mass sensitivity implies. Half the fuel effect is being absorbed into the latent tyre-pace state.

We used to call that last point "the confounding, caught in the act." It is a real observation about their fit and we no longer present it as a scoreboard, because **we built a state-space model of our own and it has the same problem in the other direction** — it reads 0.043 s/kg, about 30% high. Fuel burn and track evolution are both functions of lap number, so at field level they are collinear; any model that estimates a *level* has to split two effects that move together, and it will get the split wrong. Theirs did, ours did.

What survives is the reason it does not affect our degradation result: the **within-transformation subtracts the (event, lap) mean**, which removes fuel and track evolution *together*, so it never has to separate them at all. That is the argument for the design — not that we estimate fuel better than they do.

---

## Status

| | |
|---|---|
| Idea round | ✅ shortlisted |
| Toolchain | ✅ Python + R + CmdStan verified |
| Benchmark reproduced | ✅ their Table 3 estimates recovered by running their code |
| 2026 data | ✅ 13,128 clean laps, 7 conventional weekends, 22 drivers |
| Identification | ✅ recovers a known rate from synthetic data with a 10x larger confounder |
| Power analysis | ✅ 512 driver-stints needed; they had 3, we have 417 |
| Calibration | ✅ 80% intervals cover 80.5% |
| Practice → race | ✅ MAE 0.048 s/lap, +52% over the naive prediction |
| Scored against the benchmark | ❌ **we win 2 of 15 races** they also scored |
| Strategy layer | ✅ pit loss measured per circuit, every legal plan enumerated |
| Matches the field's actual call | ✅ **6 of 7 races**, against what the teams really ran |
| Strategy console | ✅ live FastAPI optimiser, answers recomputed per request |
| Adding a race | ✅ **no code push** — calendar discovered, nomination is one click |
| New session data | ✅ in-process poller, every 15 min, pull in a subprocess |
| Forecasting a race not yet run | ✅ Monza from FP1+FP2, two days before it happens |
| Softer compounds degrade faster | ❌ **not in races — and we found why** |

**The last row is the honest headline.** Pooling the field buys precision the
published model could not get -- intervals 15x tighter, and enough power to
resolve a 0.006 s/lap difference. What it does *not* do is reproduce the
expected compound ordering in race data.

The explanation is behavioural, and it is now tested rather than asserted. In
practice sessions softer tyres *do* degrade faster. The share of that practice
degradation which survives into the race falls as the tyre softens -- hard
0.506, medium 0.394, soft 0.173 -- across 97 event-compound cells over five
seasons. Spearman rho -0.295, one-sided p 0.0017, two-sided p 0.0034,
Kruskal-Wallis 0.016. Significant on every convention, ordering intact. Drivers
nurse the fragile tyre, and they nurse it hardest when it is softest.

The mechanism was proposed in the benchmark paper's own section 4.3 and left
untested there, so the prediction is theirs and the direction was fixed before
we touched the data.

**The seasons disagree, and we show that rather than average over it.** 2024 is
the largest single contributor at 25 cells and shows no effect at all (rho
-0.066). Dropping it lifts rho and shaves the p-value, so it stays in. The whole
cumulative trail lives in the `stability` block of `management.json` and is
rendered in the app, both to make the claim checkable and because the row where
it does not hold is part of the result:

| seasons | cells | rho | p 2-sided |
|---|---|---|---|
| 2026 | 13 | −0.375 | 0.207 ❌ |
| 2025–2026 | 29 | −0.416 | 0.025 |
| 2024–2026 | 54 | −0.295 | 0.031 |
| 2023–2026 | 72 | −0.329 | 0.0047 |
| 2022–2026 | 97 | −0.295 | **0.0034** ✅ |

Per season alone: 2023 −0.472, 2025 −0.479, 2026 −0.375, 2022 −0.257, 2024
−0.066. Only 2023 clears on its own, which is what an effect of this size looks
like at 13–25 cells a season and is the reason the pooled test exists.

Two caveats we do not paper over. The pooled Spearman treats a 2022 cell and a
2026 cell as exchangeable, and the seasons plainly disagree; a season-blocked
test is the obvious refinement and is deliberately not swapped in after the
fact, because picking the test that likes your data is the same error as picking
the seasons. And this explains why the race ordering is absent -- it does not
recover the ordering itself. See [the open questions](#open-questions).

### We tried to beat their best and did not

Three attempts, all developed on **2024** so the decisions never touched Austria,
which is the benchmark race. Austria was scored once, at the end.

1. **Predictive spread — kept.** The old estimator was wrong twice over: it built
   residuals from the `field` construction while the scored forecast used
   `hybrid`, so the spread described a different prediction than the one being
   made; and it read the field's *actual* mean pace at each lap, while a real
   forecast has to extrapolate it. Excluding that extrapolation error made us
   badly overconfident. Replaced with a nested rolling origin: re-run the
   identical forecaster on earlier laps and take the spread of its own
   one-step-ahead errors.

   | interval | before | after | target |
   |---|---|---|---|
   | 50% | 33.8% | 49.3% | 50% |
   | 80% | 59.1% | 80.4% | 80% |
   | 90% | 67.6% | 90.2% | 90% |

   **It made Austria very slightly worse — 0.2384 to 0.2409 — and it stays.**
   The old number came from an uncertainty that described a forecast we were not
   making. Keeping it for 0.0025 of CRPS would be the same trade as dropping an
   inconvenient season.

2. **Bias correction — rejected.** The same backtest shows the forecaster runs
   0.274 s slow on average. Correcting a forecast by its own measured past error
   is standard and helps `field` a lot (0.730 → 0.606), but it *hurts* the
   default `hybrid` (0.516 → 0.531), because hybrid already re-reads the
   driver's pace level over the last eight laps and a race-long offset fights
   it. Measured, reported, not applied.

3. **Student-t errors — rejected.** Coverage is right in the body but mean
   z² = 2.31, which says fat tails, and their best model used skewed-t. On the
   dev set it wins 10 of 18 and moves the mean the wrong way. A wash.

**The honest conclusion:** their model is a purpose-built state-space forecaster
for one driver's next lap, with a latent pace state and MCMC. Ours is a pooled
design built to separate compounds, and we are scoring it on a job it was not
designed for. Closing the gap properly means their structure *plus* our pooling
— the hierarchical Stan model in [open questions](#open-questions) — not more
tinkering with this predictor.

### These numbers were wrong once, because three seasons had silently truncated

The F1 API caps at 500 calls an hour. When the cap is hit mid-pull the script
logged the failures to the console and wrote a parquet holding whatever had
arrived, which on disk is indistinguishable from a complete season. 2022 landed
9 of 19 events, then 17, then 19. 2024 was missing Abu Dhabi and Las Vegas.
2025 was missing Abu Dhabi. Abu Dhabi is the final round, so it is last in fetch
order and first to be lost -- a systematic bias toward dropping late-season
races, not random loss.

`scripts/01_cache_sessions.py` now writes a `laps_YYYY.manifest.json` beside
each parquet recording sessions requested, loaded and failed, and
`season_completeness` in `cleanair/data/cache.py` makes both `07` and `08`
refuse an incomplete season instead of pooling or scoring it. 2026 and 2023 were
verified complete and unchanged.

## Where we stand against the benchmark

Scored on their race, their cross-validation scheme, and their metric. Their
scheme is transcribed from their own `CV_Functions.R`: test the last quarter of
each stint, one lap ahead, expanding the training window a lap at a time. Our
CRPS agrees with R's `scoringRules` to 2.5e-11, which is checked by a test
rather than asserted here.

| model | RMSE (s) | CRPS | |
|---|---|---|---|
| ARIMA(2,1,2) | 1.520 | 0.324 | published |
| Clean Air hierarchical SSM | 1.274 | 0.242 | ours |
| **Clean Air pooled** | **1.250** | **0.241** | **ours, best** |
| SSM compound-specific | 1.187 | 0.236 | published |
| SSM base | 1.169 | 0.230 | published |
| SSM skew-t | 1.082 | 0.202 | published, their best |

**We do not beat their best.** On the point estimate we beat ARIMA and nothing
else.

### Race by race across 2025: we win 2 of 15

Their repo publishes per-race CRPS in
`Cross_Validation_Results/All_CV_results1.csv`, so this is a head-to-head rather
than two season averages over different race sets.

| | ours | theirs |
|---|---|---|
| races won | **2** | 13 |
| mean CRPS | 0.5471 | 0.2203 |
| median CRPS | 0.3116 | 0.2022 |

We win at Italy (0.111 vs 0.128) and Spain (0.257 vs 0.265). We lose the other
thirteen, badly at Bahrain (0.382 vs 0.145) and catastrophically at Singapore
(3.83 vs 0.240, one 32-second lap).

**This corrects a claim we made for a while.** `08_benchmark.py` used to state
that their per-race numbers were not published and that a win/loss table
therefore could not be built without inventing their side of it. The file was in
their repo the whole time; we wrote the claim down instead of opening it. The
comparison it was standing in for — our *median* against their *mean* — flattered
us, and the real table is much worse for us.

Two things make it genuinely like-for-like: their Austria figure here is 0.2022
against the paper's published 0.202, and **our reconstructed stint counts match
theirs at 14 of 15 races**. That is the strongest evidence we have that the fold
scheme we transcribed from `CV_Functions.R` is the one they ran.

### Their single-race evaluation cannot tell these models apart

Their scheme scores **16 predictions** from one driver in one race. Bootstrapping
our per-lap CRPS over those 16 laps:

| | |
|---|---|
| our score | 0.237 (per-lap mean) |
| 95% CI | **[0.151, 0.365]** |
| their best | 0.202 — **inside our interval** |
| P(we beat 0.202 on a resample) | 0.30 |
| share of our score from one lap | **28%** |

One lap carries 28% of the total: Hamilton lost 1.31s to the field median on lap
48, a +2.8σ event on his car alone while the field was unaffected. No model
forecasts that lap.

So on **Austria alone** we are statistically indistinguishable from the published
best, and so is every other model in that table. This is the same criticism as
the power analysis in a second place: their three-stint design was underpowered
to separate compounds, and a 16-lap evaluation is underpowered to rank
forecasters.

But that argument only covers the single race. **Across fifteen races we lose
thirteen**, and no sample-size objection rescues that. The bootstrap is the right
caveat on the headline 0.241-versus-0.202 figure; it is not a defence of the
model.

Our per-stint CRPS at Austria is 0.178, 0.380, 0.157 -- competitive on the first
and third stints, and dragged by the second, which is the stint containing lap 48.

### We built their model with our pooling, and it did not win either

`models/stan/hier_race.stan` is their state-space structure -- a latent pace
state per car that resets at a pit stop -- with the one change our data allows:
their single scalar slope `v` becomes `v[compound]`, **shared across all twenty
cars**. Twenty cars on different compounds at different tyre ages identify what
one car cannot.

It is genuinely the better forecaster *across* races: on a 2024 development set
it beat our simpler model at 14 of 18 events, mean CRPS 0.4615 against 0.5169
(sign test p = 0.015). Adding Student-t observation errors -- their own ablation
attributes a 12% gain to robustness, not tyre physics -- took Austria from 0.268
to 0.242.

On Austria itself it ties with the simpler model and loses to 0.202. We report
both rather than picking whichever looked better on the test race.

One defect in their code worth noting: `full_race_1driver_and_fuel_base_t.stan`
fits with `skew_t` and then forecasts with `normal_rng`, so its predictive
intervals are thinner-tailed than the model it fitted. Ours uses the same
Student-t in both places.

### An earlier version of this table said we won, and it was wrong

The number in this table has moved three times, all downward, and every move was
a bug we found ourselves: **0.210 → 0.238 → 0.241**. The history is here because
a reader who opens `CV_Functions.R` will check the first one.

It reported CRPS 0.210 on 35 predictions. Their scheme gives 16. The fold
builder was passing each stint's last *global lap number* where a stint *length*
belongs, which made the training fraction relative to the race instead of the
stint: the third stint was tested on 17 of its 19 laps instead of 5, and the
extra mid-stint laps are the easy ones. Fixing it moved us from 0.210 to 0.238.

Scoring the full season then exposed a second bug. In-race degradation rates
were being fitted with no identifiability guard, and early in a race every car
is on a similar tyre age, so the slope was read off numerical noise -- at Saudi
Arabia it returned 1.0 s/lap, twenty times any real tyre, and the predictor ran
a whole stint 4.7 seconds slow. Requiring a real tyre-age spread first, the same
rule already used in `transfer.py`, cut that race from 2.10 to 0.188 and the
season mean from 0.816 to 0.606. Both failures are pinned by tests.

Neither number is one we would have found without scoring the whole season.

The third move, 0.238 to 0.241, is the only one that made the score **worse on
purpose**. The predictive spread was estimated from a different construction
than the forecast being scored, and from the field's *actual* pace where the
forecast has to extrapolate — so it excluded the extrapolation error and left us
badly overconfident: the nominal 90% interval covered 67.6%. Fixing it put
coverage at 90.2% and cost 0.0025 of CRPS. That trade is not close, and the
0.0025 is 1% of the interval width anyway.

All three failures are pinned by tests.

### So what is the claim?

Their model is a one-step lap-time forecaster for a single driver. It is better
at that than we are. What it cannot do is separate the compounds -- their own
compound-specific model scored *worse* than their base model, and their best
model has no compound structure at all. That is the question this project
answers, and the power analysis shows their three-stint design could not have.

## The product

A **strategy console**. You set the state of the race and it tells you what to
do, and how wrong the inputs can be before the answer changes.

This is a deliberate change of shape. The app used to open on degradation curves
with three tabs of statistics behind them, which answers *"is this method
sound?"* — a reviewer's question. Every screen it could show was one of seven
precomputed pictures. A strategist has one question: what do we do on Sunday.

### Five tabs, named after moments rather than scripts

| tab | the question it answers |
|---|---|
| **Next Race** | what are we walking into on Sunday? |
| **Strategy** | practice is in — what is the call, and how wrong can we be? |
| **Track Record** | were you right? |
| **Tyre Curves** | the measurement itself |
| **Method** | why should I believe any of it? |

The previous set was named after the pipeline, which meant two product tabs, two
evidence tabs, one redundant one, and a single tab that jammed together planning
a race and reacting mid-race — different jobs done in different states of mind.

### Next Race: the one that has not happened yet

Everything else looks backwards at races we can already score. This looks
forward, and a race becomes answerable in stages that the screen shows honestly
rather than papering over:

    on the calendar    the date and the circuit, from the F1 API
    + nominated        Pirelli announced the compounds (the one human input)
    + practice run     long runs exist, so a forecast is possible
    + enough of it     at least two compounds have a usable rate

As this is written, **Monza is two days away and its FP1 and FP2 are already
in** — so the app is forecasting a race that has not happened. It also says, in
as many words, that it cannot plan it yet: on practice alone two of the three
nominated compounds forecast a non-positive degradation rate, and a dry race
needs two usable tyres. That is the truthful state, and FP3 resolves it without
anyone touching a keyboard.

Circuit history fills the two inputs an upcoming race cannot supply itself:
Monza's pit loss is **25.4s with a 2.0s spread across four seasons**, its
distance 53 laps. Both are labelled as history, because last year's pit lane is
evidence about Sunday rather than a reading from it.

### Nothing needs a code push to add a race

| what | where it comes from |
|---|---|
| which races exist | the F1 calendar — all 23 rounds, future included |
| session times | same, per session, in UTC |
| race distance | previous seasons at that circuit |
| pit loss | previous seasons at that circuit |
| new session data | the in-process poller, every 15 minutes |
| **compound nomination** | **the one thing a human sets** |

That last row is not laziness. The timing feed reports HARD / MEDIUM / SOFT and
those are relative to whatever three of C1–C5 were brought; nothing in the
session or event metadata carries the mapping, and it is checked — it is a
Pirelli press release. So it is a control in the app, not a constant in a source
file, and it is one click: Pirelli slides a window of three ADJACENT compounds
by circuit severity, and every 2026 nomination we verified is one of exactly
three windows. Their own language is *"the middle trio"* and *"the softest
trio"*.

Values we cited are marked `pirelli` and anything typed in the app is marked
`user`, because those are different kinds of claim. That distinction earned its
place immediately: testing this app wrote a nomination for a race Pirelli had
not announced, and the marker is what made it visible.

### Four controls on the Strategy tab

Each is there because a measured quantity has error worth exploring rather than
because a slider looks good:

| control | why it exists |
|---|---|
| **pit loss** | measured from a handful of green-flag stops, so it carries real error |
| **safety car** | changes what a stop costs, using a *measured* fraction (see below) |
| **degradation** | draggable across the model's own 95% interval; outside it, the UI says the number is yours and not the model's |
| **race laps** | a shortened race is a different problem |

Plus **pit now or later**: give it a lap, a tyre age and a compound, and it
prices every stop lap in the next few.

Everything is computed per request by Python. There is deliberately **no
TypeScript reimplementation of the optimiser** — two copies of the same
arithmetic can disagree, and disagreeing in front of an audience is the one
failure with no recovery.

**What the controls actually do**, at Hungary:

| pit loss | call | margin |
|---|---|---|
| 22.5s | 2 stops | 1.6s |
| 24.0s | 2 stops | **0.1s** |
| 25.0s | **1 stop** | 0.9s |
| 30.0s | 1 stop | 5.9s |

The call flips between 24 and 25s — exactly the 24.5s crossover the optimiser
reports independently. Two calculations that have to agree, and a test pins that
they do.

If the API is unreachable the console **falls back to the published playbook**
with a banner saying so, rather than an error screen. The live version answers
questions nobody precomputed; the fallback still shows seven real races.

### Two numbers in here are assumptions, and they are labelled

- **The compound pace offset is 0.6s per step, assumed not fitted.** Surfaced in
  the UI as the weakest input on the screen. Two attempts to measure it failed
  (see open questions).
- **A neutralised stop costs 0.84× a green one.** That *is* measured — 48 VSC
  stops against 163 green ones, both against the non-pitting field on the same
  laps. The first version asserted 0.45 from folk intuition and was wrong.

A full safety car is **not measurable** from our data: 23 stops across two
events, and they disagree by 15 seconds (Monaco 35.4s, Japan 20.1s — one above
the green number, one below). `scripts/10_pit_loss_by_status.py` prints that
rather than hiding it.

And the limitation no number fixes: teams pit under a safety car for **track
position**, and this optimiser minimises total time. It has no concept of
position, so a perfect pit-loss ratio would still not make it a safety-car
strategist.

## Open questions

Things we tested and could not resolve. Listed because a reader will find them
anyway, and because the tests that ruled things out are worth more than a
confident story.

1. **Softer compounds do not show faster degradation in races.** C5 comes out at
   -0.004 s/lap. Ruled out: tyre-age windowing (ranges overlap), unidentifiable
   cells (filtered), post-pit traffic (dropping opening laps changes nothing),
   and traffic generally (added as a covariate; moves rates by <0.015 s/lap).
2. **Two of nine transfer cells have negative actual rates.** Same list of
   ruled-out causes. Belgian C4 has only 40 laps; Japanese C1 may suffer
   compound-age confounding within a lap, since Japan ran only two compounds.
3. **Practice is underpowered.** 97 runs gives 35% power, so the practice-versus-
   race gap -- our most interesting lead -- is a lead, not a result.
4. **The compound pace offset is assumed, not measured** (0.6 s per step). Two
   attempts to fit it failed: in races compound choice correlates with car pace;
   in practice a driver's best lap per compound comes from different fuel loads.
   The strategy margin is smaller than the uncertainty in this number, so the
   crossover is defensible and the specific stint plan is illustrative.

## Layout

```
src/cleanair/         the package
  config.py           verified constants: 2026 regs, benchmark targets, seeds
  api.py              FastAPI strategy console -- everything computed live
  poller.py           in-process watcher: pulls sessions as they finish
  data/
    schedule.py       the calendar, discovered from the API not hardcoded
    allocation.py     Pirelli's nomination -- the one fact no feed carries
    cache/laps/fuel   FastF1 caching, clean-lap dataset, fuel model
  models/             MixedLM (fast, interpretable) + Stan (hierarchical Bayesian)
    stan/hier_race    their state-space model with our field-wide pooling
  validation/         cross-validation, CRPS scoring, calibration, power analysis
  strategy/           pit-stop and stint-length decisions, pit loss by track status
  artifacts/          the JSON contract the web app reads

benchmark/            R. Verification only, never part of the product.
  stan/               their models, migrated to Stan 2.32+ array syntax
  repro.R             reproduces their Table 3, and the corrected-fuel test
  upstream/           their repo — fetched locally, not committed (no license)

scripts/              numbered, run in order
  01 cache  02 publish  03 fit  04 validate  05 transfer  06 strategy
  07 management  08 benchmark  09 playbook  10 pit loss by status
  11 circuits         per-circuit pit loss and distance, for races not yet run
app/                  Streamlit lab bench (internal — we look at fits here, never demoed)
web/                  the demo. Vite + React + TypeScript
  api.ts              client for the live optimiser
  NextRaceView.tsx    the race that has not happened yet -- the front door
  ConsoleView.tsx     the strategy console
  CompoundLabels.tsx  why nothing is grouped by hard/medium/soft, derived live
  useStrategy.ts      coarse-while-dragging, exact-on-settle, generation-guarded
  ui.tsx              shared display primitives and the type scale
data/
  artifacts/          JSON the web app reads for everything NOT computed live
  schedule/           cached calendar, so a demo works with no network
  allocation.json     compound nominations, editable from the app
docs/reference/       the benchmark paper, plus licensing notes on every source
tests/
```

---

## Setup

**Python**

```bash
python -m venv .venv && .venv/Scripts/activate && pip install -e ".[lab,dev]"
```

`pandas` is pinned below 3.0 because `fastf1` 3.8.3 requires it. This machine has pandas 3.0 globally, so the venv is not optional.

**Stan** (needed for the hierarchical model and the benchmark)

CmdStan 2.39.0 lives in `~/.cmdstan/` and is shared by Python's `cmdstanpy` and R's `cmdstanr`. One install, both languages.

⚠️ **Before compiling anything with Stan**, put Rtools ahead of the old MinGW on PATH:

```bash
export PATH="/c/rtools45/x86_64-w64-mingw32.static.posix/bin:/c/rtools45/usr/bin:$PATH"
```

`C:/MinGW/bin` is on this machine's system PATH carrying GCC 6.3.0 from 2016. It shadows modern compilers and breaks every Stan build. Do not delete it — other tooling may need it. Override per-process instead.

**R** (verification only — the package works without it)

R 4.6.1 + Rtools45. Packages in `%LOCALAPPDATA%/R/win-library/4.6`: `cmdstanr`, `scoringRules`, `scoringutils`, `sgt`, `posterior`, `tidyverse`. Note `cmdstanr` is not on CRAN; install from `https://stan-dev.r-universe.dev`.

**The strategy console** (two processes)

```bash
python -m uvicorn cleanair.api:app --reload --port 8000
```

Set `CLEANAIR_POLL=1` to start the background poller with it. It is off by
default so running the API locally does not silently begin pulling sessions.


```bash
cd web && npm install && npm run dev
```

Vite proxies `/api` to port 8000, so the browser sees one origin and CORS never
comes up in development. In production `VITE_API_BASE` points at the deployed
service and `CORS_ORIGINS` lists the front end — no hostname is compiled in.

Tyre Curves, Track Record and Method read published artifacts and work with the
API stopped. Next Race and Strategy need it: Next Race says so plainly, and
Strategy falls back to the published playbook with a banner.

---

## Reference material

The benchmark paper is committed at `docs/reference/` — it is CC BY 4.0, so redistributing it with attribution is fine.

Everything else is fetched locally rather than committed:

```bash
bash scripts/fetch_reference.sh
```

That pulls the authors' code repo (which carries **no license**, so we have no right to redistribute it) and one large secondary paper. `docs/reference/README.md` records the licence position on each source.

---

## How we validate

1. **Can it separate the compounds?** Non-overlapping intervals where the benchmark could not. Falsifiable, and the headline.
2. **Does it beat the benchmark?** Same metrics, same cross-validation scheme, same CRPS estimator — `scoringrules`, the Python port of the R library they used, cross-checked against R itself to 2.5e-11. **We report the race-by-race table, and it says we lose 13 of 15.**
3. **Is the uncertainty honest?** Empirical coverage of the stated intervals — 80% intervals cover 80.5%, and the one-step forecaster's coverage was 67.6% until we fixed it.
4. **How much data does this actually need?** A power analysis, which answers the open question the benchmark paper leaves.
5. **Practice → race.** Fit on Friday long runs, predict Sunday pace. The benchmark does not attempt this, and it is what the brief asks for.
6. **Does the strategy call match reality?** Our recommendation against the stop count the teams actually ran, at every event. **6 of 7.** The only claim here a viewer can check against a race they watched.

### Things we deliberately did not do

Recorded because the discipline is the point, and because each was tempting.

- **Did not drop 2024** from the management test, though it is the season that disagrees and dropping it turns p = 0.062 into significance. We added seasons instead: 97 cells, p = 0.0034, with 2024 still in.
- **Did not keep a better-scoring predictive spread** that described a different forecast than the one being scored. Fixing it cost 0.0025 CRPS and moved coverage from 67.6% to 90.2%.
- **Did not pick between our two models on the test race.** The hierarchical model wins the 2024 development set and ties on Austria; both are reported.
- **Did not develop against Austria.** Every choice — fold minimum, fuel load, parameterisation, error distribution — was made on 2024 and Austria was scored once.
- **Did not keep an invented safety-car constant.** 0.45 came from folk intuition; measurement said 0.84 for VSC and that a full safety car is not measurable from 23 stops.

---

## Beyond motorsport

The core method isolates a true wear signal from confounded operating conditions. Indian commercial fleets replace and retread tyres on odometer readings, which mix together load, road gradient, surface and driving style — the same way lap time mixes fuel, traffic and track evolution.

We are **not** claiming a validated fleet result. We have no fleet data. We are claiming a transferable estimator, shipped with a documented adapter interface so anyone with that data can test it.

---

## License

MIT.
