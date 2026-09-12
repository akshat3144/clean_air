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
- **Their fitted fuel coefficient is about half the physical value** — 0.016 s/kg against the 0.030–0.035 that mass sensitivity implies. Half the fuel effect is being absorbed into the latent tyre-pace state. That is the confounding, caught in the act, using their own model on their own data.

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
| Scored against the benchmark | ⚠️ CRPS 0.241 vs their best 0.202 — **we lose** |
| Strategy layer | ✅ pit loss measured per circuit, every legal plan enumerated |
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
| **Clean Air pooled** | **1.250** | **0.241** | **ours** |
| SSM compound-specific | 1.187 | 0.236 | published |
| SSM base | 1.169 | 0.230 | published |
| SSM skew-t | 1.082 | 0.202 | published, their best |

**We lose.** We beat ARIMA and nothing else. Across the 2025 season our median
race scores 0.315 against their 0.238 season mean, on 18 races to their 19.

Our per-stint CRPS at Austria is 0.178, 0.380, 0.157 -- competitive on the first
and third stints, and dragged by the second.

### An earlier version of this table said we won, and it was wrong

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

Neither number is one we would have found without scoring the whole season, and
both are recorded here because a reader who opens `CV_Functions.R` will check.

### So what is the claim?

Their model is a one-step lap-time forecaster for a single driver. It is better
at that than we are. What it cannot do is separate the compounds -- their own
compound-specific model scored *worse* than their base model, and their best
model has no compound structure at all. That is the question this project
answers, and the power analysis shows their three-stint design could not have.

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
  config.py           verified constants: 2026 regs, calendar, benchmark targets
  data/               FastF1 caching, clean-lap dataset, fuel model
  models/             MixedLM (fast, interpretable) + Stan (hierarchical Bayesian)
  validation/         cross-validation, CRPS scoring, calibration, power analysis
  strategy/           pit-stop and stint-length decisions
  artifacts/          the JSON contract the web app reads

benchmark/            R. Verification only, never part of the product.
  stan/               their models, migrated to Stan 2.32+ array syntax
  repro.R             reproduces their Table 3, and the corrected-fuel test
  upstream/           their repo — fetched locally, not committed (no license)

scripts/              numbered, run in order
app/                  Streamlit lab bench (internal — we look at fits here, never demoed)
web/                  the demo. Vite + React + TypeScript, reads static JSON
data/artifacts/       JSON the web app reads
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

**Web**

```bash
cd web && npm install && npm run dev
```

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

1. **Can it separate the compounds?** Non-overlapping credible intervals where the benchmark could not. Falsifiable, and the headline.
2. **Does it beat the benchmark?** Same metrics (RMSPE, CRPS), same cross-validation scheme, same CRPS estimator — we use `scoringrules`, the Python port of the R library they used, and cross-check the two agree. Reported whether or not we win.
3. **Is the uncertainty honest?** Empirical coverage of the stated intervals.
4. **How much data does this actually need?** A power analysis, which answers the open question the benchmark paper leaves.
5. **Practice → race.** Fit on Friday long runs, predict Sunday pace. The benchmark does not attempt this, and it is what the brief asks for.

---

## Beyond motorsport

The core method isolates a true wear signal from confounded operating conditions. Indian commercial fleets replace and retread tyres on odometer readings, which mix together load, road gradient, surface and driving style — the same way lap time mixes fuel, traffic and track evolution.

We are **not** claiming a validated fleet result. We have no fleet data. We are claiming a transferable estimator, shipped with a documented adapter interface so anyone with that data can test it.

---

## License

MIT.
