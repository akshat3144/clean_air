# Reference material

Run `bash scripts/fetch_reference.sh` to get everything that is not committed.

## Committed here

**Cappello, C. & Hoegh, A. (2025). *A State-Space Approach to Modeling Tire Degradation in Formula 1 Racing.*** arXiv:2512.00640 [stat.AP].
`cappello_hoegh_2025_arXiv-2512.00640.pdf`

Licensed **CC BY 4.0**, so it is redistributed here with attribution. This is the benchmark Clean Air is measured against, and the repo carries it so it stays self-contained.

## Not committed — fetch locally

**Todd, J. et al. (2025). *Explainable Time Series Prediction of Tyre Energy in Formula One Race Strategy.*** arXiv:2501.04067.
<https://arxiv.org/abs/2501.04067>

Cited by the benchmark paper as the deep-learning approach that lacks interpretability and explicit uncertainty. Useful context, tangential to us, and 4.4 MB — so it is linked rather than carried.

**The benchmark authors' code.** <https://github.com/colecappello12/F1_SSM_Paper>

Fetched to `benchmark/upstream/`. **Not committed: the repo has no license file, so all rights are reserved and we have no right to redistribute it.** We read it and run it locally, and `benchmark/README.md` records what we found.

Their four Stan models *are* committed, in `benchmark/stan/`, with pre-2.32 array declarations migrated so they compile on current Stan. That is a mechanical syntax change; the model, priors and data blocks are untouched, and `upstream/` is left pristine so the diff stays auditable. If they add a restrictive license we remove those too.

## Other sources, no local copy needed

- FastF1 docs — <https://docs.fastf1.dev/>. The 4–5 Hz positional sample rate that ruled out the Track Limits problem statement is in the accurate-calculations guide.
- FastF1 discussion #861 — <https://github.com/theOehrly/Fast-F1/discussions/861>. Confirms ERS and active-aero data are not published, and the 2026 DRS column is all zeros. This ruled out the Energy & Overtake problem statement.
- 2026 calendar and session formats — read directly from `fastf1.get_event_schedule(2026)`, not from news sites. See `src/cleanair/config.py`.
