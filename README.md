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
| Toolchain | ✅ Python + R + CmdStan verified working |
| Benchmark reproduced | ✅ |
| 2026 data verified | ✅ ~2,000 usable long-run laps across 7 weekends |
| Pooled model separates compounds | ⏳ **unproven — this is the next thing to answer** |

The last row is the whole project. Everything else is contingent on it.

---

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
