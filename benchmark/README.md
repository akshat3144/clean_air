# Benchmark — verification only

**This directory is not part of the product.** It exists so we can say "we ran their model", not "we read their paper". Nothing in `src/cleanair/` imports from here, and the package installs and tests clean with no R present.

## What is here

```
upstream/   The authors' repo, unmodified. Reference only.
stan/       Their four .stan models, migrated to Stan 2.32+ array syntax.
results/    Our reproduction output.
repro.R     Reproduce Table 3, and the corrected-fuel experiment.
```

## The paper

Cappello, C. & Hoegh, A. (2025), *A State-Space Approach to Modeling Tire Degradation in Formula 1 Racing*. [arXiv:2512.00640](https://arxiv.org/abs/2512.00640). PDF saved at `../docs/reference/`.

Code: <https://github.com/colecappello12/F1_SSM_Paper>

## Setup

R 4.6.1 with Rtools45. Packages live in `%LOCALAPPDATA%/R/win-library/4.6`.

**Every R script here must prepend Rtools to PATH before touching Stan:**

```r
Sys.setenv(RTOOLS45_HOME = "C:/rtools45")
Sys.setenv(PATH = paste("C:/rtools45/x86_64-w64-mingw32.static.posix/bin",
                        "C:/rtools45/usr/bin",
                        Sys.getenv("PATH"), sep = ";"))
```

Without this, `C:/MinGW/bin` (GCC 6.3.0, from 2016) shadows the real compiler and every Stan build fails.

## Three things we learned by running it

**1. `rstan` does not work here. Use `cmdstanr`.**

`rstan` 2.32.7 fails to compile models on this machine, and masks the real error behind `Error in sink(type = "output") : invalid connection`. Not worth chasing. `cmdstanr` 0.9.0 with CmdStan 2.39.0 works, is the reference implementation, and shares its CmdStan install with Python's `cmdstanpy`. One toolchain, both languages.

`cmdstanr` is **not on CRAN** — install from `https://stan-dev.r-universe.dev`.

**2. Their `.stan` files do not compile on current Stan.**

They use pre-2.32 array syntax (`int Compound[TT];`), removed in Stan 2.32. The fix is mechanical and does not touch the model: `array[TT] int Compound;`. Migrated declarations are `Pit`, `Compound` and `compound_map`. `upstream/` is left pristine so the diff stays auditable.

**3. Their code filters `TrackStatus`, though the paper says it does not.**

`upstream/Cross_Validation_Scripts_and_Stan_Code/Full_Race_CV.qmd` line 25:

```r
filter(!str_detect(TrackStatus, "4|5|6|7"))
```

The paper's section 2 says cleaning was "minimal, consisting only of the removal of laps in which the driver entered or exited the pit lane", and section 4.5 offers safety-car handling as *future work*. The code is ahead of the paper. We had this wrong in the idea-round deck and it is corrected.

## Reproduction result (2026-09-03)

Extension 1 (compound-specific degradation), Hamilton, 2025 Austrian GP:

| | ours | paper Table 3 |
|---|---|---|
| v Hard | 0.0550 [0.0032, 0.1339] | 0.054 [0.004, 0.133] |
| v Medium | 0.0555 [0.0068, 0.1165] | 0.060 [0.009, 0.120] |

Hard is near-exact. Medium sits 0.0045 low, well inside MCMC noise for a parameter with a 0.11-wide interval — we used 2000+2000 iterations against their 15000+15000, a different seed, and CmdStan rather than rstan's vendored Stan. **Their result reproduces.**

## The corrected-fuel experiment — negative result

Their fuel covariate is `seq(110, 1, length.out = length(retained_laps))`, spread across retained rows rather than real race distance. On Austria that misplaces up to 4.7 kg, about 0.16 s of lap time — larger than the 0.054–0.060 s/lap effect they are measuring.

So we refit with fuel indexed to real `LapNumber`, changing nothing else:

| | their ramp | corrected |
|---|---|---|
| v Hard | 0.0550 | 0.0538 |
| v Medium | 0.0555 | 0.0539 |
| P(v_Med > v_Hard) | 0.522 | 0.515 |
| 95% CrIs overlap | YES | YES |

**No effect.** The latent random walk absorbs the misspecification.

Two consequences, both important:

- **Do not claim the fuel bug explains their null result.** It does not. Keep it as a code-quality note only.
- **Their null result is genuine.** The compounds really are indistinguishable from one car's data, and we now have the control to prove it. That strengthens the pooling argument — it eliminates a competing explanation instead of assuming it away.

## The finding worth keeping

Their fitted fuel coefficient is **`gamma` ≈ 0.016 s/kg** (0.0156 their ramp, 0.0164 corrected — tight intervals, converged). Mass sensitivity implies **0.030–0.035 s/kg**.

Their model recovers roughly *half* the fuel effect. The rest is absorbed by the latent state, which is where degradation lives. That is a direct measurement of the confounding, produced by their own model on their own data.

Caveat to state honestly: 0.3–0.35 s/lap per 10 kg is a circuit-agnostic rule of thumb and Austria is a short lap, so say "roughly half", not a precise ratio. Our own model fitting `gamma` and landing near the physical prior is the proper confirmation.

## Also in `upstream/`, and not in the paper

`Cross_Validation_Results/All_CV_results1.csv` — a **19-race 2025 cross-validation** (Hamilton, skew-t vs ARIMA), 51 stints. Season means: skew-t CRPS 0.238 vs ARIMA 0.2997; skew-t RMSPE 0.4088 vs 0.4786. Skew-t wins CRPS in 16 of 19 races, losing at China, Singapore and the USA.

This is a far richer target than the single 0.202 figure. We can report a win rate across 19 races instead of one number.

⚠️ Their repo's ARIMA figures differ slightly from the paper's Table 1 (repo Austria: 0.457/0.773/0.249; paper: 0.613/0.727/0.180) — a different run. Cite the paper's numbers; mention the repo only if asked.

## Two traps in their metrics

1. **"RMSPE" is not a percentage error.** Their formula is a plain RMSE in seconds. And Table 1's "Total" is a **sum** over three stints while the CRPS total is a **mean** — so RMSPE totals are not comparable across races with different stint counts.
2. **Separating the compounds and beating CRPS 0.202 are different jobs.** Their compound-specific model (Ext 1) scored *worse* than their base model on both metrics, and their best model (skew-t, 0.202) has no compound structure at all. Their skew-t gain came from outlier robustness, not tyre physics. We need pooling **and** a heavy-tailed observation model to do both.
