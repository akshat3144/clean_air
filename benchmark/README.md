# Benchmark — verification only

**This directory is not part of the product.** It exists so we can say "we ran
their model", not "we read their paper". Nothing in `src/cleanair/` imports from
here, and the package installs and tests clean with no R present.

## What is here

```
upstream/   The authors' repo, unmodified. Reference only, never redistributed.
stan/       Their four .stan models, migrated to Stan 2.32+ array syntax.
results/    Our reproduction output.
repro.R     Reproduces their Table 3.
```

## The paper

Cappello & Hoegh (2025), [arXiv:2512.00640](https://arxiv.org/abs/2512.00640) —
a Bayesian state-space model of tyre degradation, fitted to one driver across
three stints. Code: <https://github.com/colecappello12/F1_SSM_Paper>.

The paper is CC BY 4.0 and ships in `docs/reference/`. **Their code carries no
license**, so it is fetched locally by `scripts/fetch_reference.sh` and never
committed.

## Setup

R 4.6.1 with Rtools45, and `cmdstanr` 0.9.0 against CmdStan 2.39.0 — the same
CmdStan install Python's `cmdstanpy` uses. One toolchain, both languages.

`cmdstanr` is **not on CRAN** — install from <https://stan-dev.r-universe.dev>.

Before compiling, put Rtools ahead of the system MinGW on PATH:

```bash
export PATH="/c/rtools45/x86_64-w64-mingw32.static.posix/bin:/c/rtools45/usr/bin:$PATH"
```

Their `.stan` files use pre-2.32 array syntax (`int Compound[TT];`), removed in
Stan 2.32. The migration is mechanical and does not touch the model:
`array[TT] int Compound;`. `upstream/` is left pristine so the diff stays
auditable.

## Reproduction result

Their Table 3 estimates, recovered by running their code:

| Compound | Published | Our run |
|---|---|---|
| Hard | 0.054 [0.004, 0.133] | 0.0550 [0.0032, 0.1339] |
| Medium | 0.060 [0.009, 0.120] | 0.0555 [0.0068, 0.1165] |

The two intervals overlap almost entirely — which is the finding Clean Air is
built to move past, and the reason we reproduced it before building anything of
our own.

## Scoring

We adopt their metrics so the comparison is like for like: RMSPE and CRPS under
rolling-origin cross-validation, replicating `CV_Functions.R`. CRPS via Python's
`scoringrules`, cross-checked against the R `scoringRules` package they used to
**2.5 × 10⁻¹¹**.

One note on their metrics: **"RMSPE" is not a percentage error** — the formula
is a plain RMSE in seconds. And Table 1's "Total" is a *sum* over three stints
while the CRPS total is a *mean*, so RMSPE totals are not comparable across
races with different stint counts.

Per-race figures for both models are in `data/artifacts/benchmark.json`.
