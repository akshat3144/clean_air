# Clean Air

**Deconfounded tyre degradation intelligence — and the strategy console built on top of it.**

Built for the [TrackShift Innovation Challenge 2026](https://www.trackshift.in/) — Plaksha University, with TGR Haas F1 Team and the Mphasis Foundation.
Problem statement: *Tyre Degradation Intelligence*.

> A Formula 1 lap time is three effects fighting each other. Clean Air pulls them
> apart using the whole field at once, then turns the answer into a pit call you
> can argue with — live, for a race that has not happened yet.

| | | | |
| --- | --- | --- | --- |
| **4.4×** tighter intervals than the published model, race for race | **820** driver-stints vs their 3 | **10 of 11** strategy calls match what teams ran | **80.6%** empirical coverage at nominal 80% |
| **138,839** clean laps, 5 seasons | **131,053** strategies enumerated per race | **0** code pushes to add a race | **234** tests |

---

## The brief asks three questions. Here they are, answered.

**1. How quickly is the driver losing performance, and when do they have to pit?**

A rate in seconds per lap, per compound, with an interval — and the stint length
that rate implies. Across the 2026 season, measured in races:

| | C1 | C2 | C3 | C4 | C5 |
| --- | --- | --- | --- | --- | --- |
| **s/lap lost** | 0.115 | 0.072 | 0.057 | 0.029 | 0.003 |

That ordering is backwards from the textbook, and it is not a bug — it is one of
our findings. In a *race*, drivers nurse a soft tyre and lean on a hard one, so
the hardest compound wears fastest. We test it over five seasons and 98 cells:
**ρ = −0.308, p = 0.0020.** [Full result below.](#why-softer-compounds-do-not-degrade-faster-in-races)

The pit lap itself comes from the optimiser, which enumerates every legal plan
for the race rather than guessing: **131,053** of them at Monaco, in 362 ms.

**2. How will the tyre perform after 5, 10, 15 laps?**

Read straight off the fitted curve, interval included. Seconds slower than the
same tyre when fresh:

| compound | after 5 laps | after 10 laps | after 15 laps |
| --- | --- | --- | --- |
| **C1** | +0.55 | +1.05 | +1.50 |
| **C2** | +0.35 | +0.66 | +0.94 |
| **C3** | +0.28 | +0.54 | +0.78 |
| **C4** | +0.15 | +0.29 | +0.44 |
| **C5** | +0.02 | +0.05 | +0.09 |

This table is on the **Tyre Curves** tab of the console, with the 95% interval
under every number.

**3. Is the prediction trustworthy?**

We answer this four ways rather than asserting it once:

| | |
| --- | --- |
| **Are the intervals honest?** | **80.6%** of actual values land inside the nominal **80%** band |
| **Does Friday predict Sunday?** | **0.081 s/lap** mean absolute error, leave-one-event-out — the event being predicted never contributes to its own correction |
| **Does the call match reality?** | the stop count agrees with what real teams ran at **10 of 11** races |
| **Does it know when to shut up?** | at **2** races the evidence was too thin, and it refuses to call them rather than guessing |

The fourth row is the one we would defend hardest. A model that answers every
question with equal confidence is not a trustworthy model.

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

**1. Where you race moves the tyre more than which tyre you fitted.**
Every public tyre model, and the published one, fits **one rate per compound for
the whole season**. That is false, and we can say by how much. Letting the
tyre-age slope vary by circuit — with partial pooling, so a safety-car-shredded
race cannot shout over a clean one — the fitted slopes span **0.146 s/lap across
the 13 circuits of 2026**, from Barcelona at **+0.076** to Suzuka at **−0.070**.
The spread between the five *compounds* is **0.112 s/lap**. A likelihood-ratio
test against the same model with no circuit term gives **LR = 385 on 1 df,
p = 4 × 10⁻⁸⁶**. A pit call built on a season-average rate is wrong at
every track, and wrong by more than picking the wrong tyre.

**2. Field-level identification instead of per-car modelling.**
The published approach models one driver's lap times as a latent state and tries
to estimate the fuel effect. Ours never estimates fuel at all — it differences it
away. That is why our intervals are tight enough to separate compounds where
theirs are not.

**3. We ran the published model. We did not just cite it.**
Cappello & Hoegh (2025), [arXiv:2512.00640](https://arxiv.org/abs/2512.00640).
We rebuilt their Stan models, reproduced their Table 3, **found a defect in their
fuel calculation, fixed it, and re-ran.** Their null result survived the fix
(separation probability 0.522 → 0.515) — so the tyres really are indistinguishable
from one car's data, and we have the control to prove it rather than assert it.

**4. A power analysis that says their design could never have worked.**
Separating two compounds 0.006 s/lap apart needs **512 driver-stints** for 80%
power. Their study had **3**. We have **820**. This answers an open question
their own paper leaves standing.

**5. We tested a mechanism their paper proposed and left untested.**
Their section 4.3 suggests drivers *manage* softer tyres harder. We tested it
across **five seasons, 20 events, 98 event-compound cells** — and it holds
(below). The direction was fixed by their text before we touched the data.

**6. Physical compounds, not relative labels.**
Everyone else groups by HARD / MEDIUM / SOFT. Those labels are **relative to
whatever three of C1–C5 Pirelli brought that weekend** — C3 is HARD at five races,
MEDIUM at three, and SOFT at Suzuka. Grouping by label averages different rubber
together. Clean Air works in C-numbers throughout, which is why its curves mean
anything at all.

**7. It is a live product, not a results viewer.**
Adding a race to the system requires **no code push**. The calendar is discovered
from the F1 API, session data arrives via an in-process poller, and circuit
history supplies pit loss and race distance. The single human input — Pirelli's
compound nomination — is one click in the UI.

---

## Results

|                                     |                                                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------ |
| **The track effect**          | ✅ circuit spread **0.146 s/lap** beats compound spread **0.112** — **p = 4 × 10⁻⁸⁶** |
| **Compound separation**       | ✅ **10 of 23 adjacent pairs** separated race by race — where the benchmark separates none |
| **Interval precision**        | ✅ **4.4× tighter** median, up to **9.1×**, race for race                             |
| **Statistical power**         | ✅ **820 driver-stints** vs the 512 needed and the 3 they had                         |
| **Uncertainty is honest**     | ✅ 80% intervals cover **80.6%** empirically                                          |
| **Practice → race**          | ✅ MAE **0.081 s/lap**, a **29.0% error reduction** over assuming Sunday = Friday |
| **Benchmark reproduced**      | ✅ their Table 3 recovered by running their own code                                       |
| **Driver management effect**  | ✅ **p = 0.0020** across 5 seasons, 98 cells                                          |
| **Strategy call vs reality**  | ✅ **10 of 11 races** match the stop count teams actually ran                         |
| **Forecasts an unraced race** | ✅ Madrid predicted from FP1, a day out                                                    |
| **Test suite**                | ✅ **283 tests**                                                                      |

### The track effect — the finding we did not expect

Fit one rate per compound for the whole season and you are asserting that a tyre
wears the same at Monaco and at Barcelona. It does not. With a per-circuit
random slope, here is how far each 2026 circuit pulls the tyre-age slope away
from the season average:

| Faster-wearing than average | | Kinder than average | |
| --- | --- | --- | --- |
| Barcelona | **+0.076** | Suzuka | **−0.070** |
| Hungaroring | **+0.039** | Montréal | **−0.038** |
| Red Bull Ring | **+0.028** | Shanghai | **−0.020** |
| Miami | **+0.009** | Monza | **−0.018** |

**0.146 s/lap** end to end — against **0.112 s/lap** between C1 and C5. Over a
30-lap stint that is **4.4 s of circuit** against **3.4 s of rubber.**

This is not a tuning detail. It is why the global intervals below are *wider*
than an earlier version of this model reported: 11,039 laps from 13 circuits
are not 11,039 independent observations, and pretending otherwise bought
precision that was never there. The strategy layer never uses the global rate —
it asks `rate_for(compound, event)` and gets that circuit's own.

### Compound separation — the headline

Season-wide, 2026 race data, 95% intervals. These carry the between-circuit
spread, which is why they are honest rather than narrow:

| Compound     | Rate (s/lap)      | 95% interval                | Long runs |
| ------------ | ----------------- | --------------------------- | --------- |
| C1 | +0.115 | [+0.047, +0.183] | 55 |
| C2 | +0.072 | [+0.014, +0.130] | 191 |
| C3 | +0.057 | [+0.002, +0.113] | 242 |
| C4 | +0.029 | [−0.027, +0.085] | 223 |
| C5 | +0.003 | [−0.054, +0.061] | 109 |

**Five compounds, five distinct rates, in strict order, no crossings.** The
published model cannot order its two — Hard 0.054 [0.004, 0.133] against Medium
0.060 [0.009, 0.120], overlapping almost completely.

Race by race — the like-for-like comparison, since the benchmark fits a single
race — **10 of 23 adjacent compound pairs separate cleanly**, at **9 of the 13
races**. The benchmark separates **none**, from the one race it fits.

And the intervals are tighter where it counts. Against their published width of
**0.129**, our single-race intervals are tighter in **35 of 38 event-compound
cells**, by a **median of 4.4×** and up to **9.1×** — Suzuka C1 at 0.054 wide,
Zandvoort C2 at 0.015, the Hungaroring C3 at 0.016.

### What deconfounding actually buys

Not precision. **Correctness of sign.**

Run the obvious analysis — regress lap time on tyre age, no controls, the thing
every public FastF1 notebook does — and fuel burn beats tyre wear on the
compounds that wear least:

| Compound | Naive slope | Deconfounded |
| --- | --- | --- |
| HARD | +0.075 | +0.072 |
| **MEDIUM** | **−0.122** | **+0.029** |
| **SOFT** | **−0.082** | **+0.003** |

On **two of four compounds the naive fit says the tyre gets faster as it wears.**
That is the state of the art outside a race team, and it is not a subtle error —
it is backwards. Subtracting the (event, lap) mean turns all of them positive and
puts them in order.

### Why softer compounds do not degrade faster in races

In **practice** sessions softer tyres degrade faster, exactly as expected. In
races that ordering inverts — and we can show why. The fraction of a compound's
practice degradation that survives into the race **falls monotonically as the
tyre softens**:

| Label  | Race ÷ practice rate | Cells |
| ------ | --------------------- | ----- |
| HARD   | **0.506**       | 16    |
| MEDIUM | **0.394**       | 50    |
| SOFT   | **0.170**       | 32    |

Spearman **ρ = −0.308**, one-sided **p = 0.0010**, two-sided **p = 0.0020**,
Kruskal–Wallis **p = 0.0100**. Across **98 cells, 20 events, 5 seasons (2022–2026)**.
Significant on every convention, ordering intact.

**Drivers nurse the fragile tyre, and they nurse it hardest when it is softest.**
The mechanism was predicted in the benchmark paper and never tested. We tested it.

### Practice → race, the deliverable the brief names

Friday is not Sunday. Assuming it is costs **0.114 s/lap** of error across 12
held-out event-compound cells. Calibrating by the measured practice→race factor
— **0.380**, a race degrading at about **38%** of its practice rate — cuts that
to **0.081 s/lap**, a **29.0% reduction**, leave-one-event-out throughout.

**The three practice sessions are not worth the same, and we measured by how
much.** Scoring each session's degradation against the race that followed, over
every cell we can measure in both:

| Session | Cells | Correlation with the race | Median run size |
| --- | --- | --- | --- |
| **FP2** | 11 | **0.84** | 5 runs · 33 laps |
| FP1 | 9 | 0.05 | 2 runs · 12 laps |
| FP3 | 1 | — | — |

FP1 carries almost no signal. Part of that is thinness, and part is what the
session is for: teams change the car between FP1 runs, so a slope fitted across
them measures setup work as much as tyre wear — Monaco's FP1 medium reads
**−0.807 s/lap** against a race value of 0.056. FP2 is where the setup is frozen
and the heavy-fuel race simulations run.

So FP2 carries twice the weight of the other two, by weighted least squares over
the practice design. Nothing is weighted to zero: nine cells is not enough to
retire a session, and this weekend's worst session still beats another circuit's
best. The weights are constants rather than a live fit, and
[`scripts/12_session_skill.py`](scripts/12_session_skill.py) re-measures the
table — a test fails if FP2 ever stops being the best predictor.

That change alone moved the forecast from **0.083 to 0.081 s/lap**, and the
error reduction from 25.6% to **29.0%**.

The blend is not hidden. **Session by session** appears on both the Next Race
and Strategy tabs: each session's own fitted rate, its run and lap counts, its
weight, and the clock gap to the race. Cells under three runs are struck through
rather than dropped — two runs of a soft at Madrid carry a standard error of
0.39 s/lap, which is worth seeing and not worth trusting, and only the counts
tell you which. Where the race has already run it also prints what Sunday
actually did beside what Friday said, which is the post-race comparison the
brief asks for.

A sprint weekend says so. It has one practice hour and no FP2 at all, so its
FP2 and FP3 read "not part of a sprint weekend" rather than "no data" — a
session that does not exist and a session we failed to pull are different
facts.

### When the weekend does not run the tyre

Madrid 2026 is the hard case, and it is the one we demo. A new circuit with no
history, and across all three practice sessions **nobody put a hard on a race
simulation** — zero runs on a compound Pirelli nominated for Sunday. The soft
managed two runs where three are needed. One usable compound is not a legal
plan, so the strategy screen refused to answer.

A refusal is honest and useless. Instead we take the compound's rate across the
rest of the calendar and scale it by **how harsh this circuit is on the tyres it
did run** — Madrid's medium wears at 0.394 s/lap against a season-wide 0.153, so
Madrid runs **2.6× harsh**. Those rows come back marked `stand-in`, with a
deliberately wider band, and the screen never draws them like a measurement.

One physical constraint is enforced: a softer tyre cannot wear more slowly than
a harder one on the same track. Without it, Madrid's extreme measured medium set
a severity that put the borrowed soft *below* it, and the optimiser built the
plan out of two borrowed compounds while ignoring the only one we actually
watched run.

### Against the published benchmark

The published model is a **one-step lap-time forecaster for a single driver**.
Clean Air answers a different question: **which tyre, how long, and what does
that make the pit call.**

That distinction is not ours to make convenient — it is visible in their own
results. Their **compound-specific model scored worse than their base model**,
and their **best model has no compound structure at all**, because three stints
cannot support one. The power analysis says why: separating two compounds needs
512 driver-stints, and they had 3.

So we score both ways, on **their metric, their cross-validation scheme, their
CRPS estimator** — `scoringrules`, cross-checked against the R library they used
to **2.5 × 10⁻¹¹**.

Austria 2025, the race they publish:

| Model                             | RMSPE           | CRPS            |
| --------------------------------- | --------------- | --------------- |
| ARIMA(2,1,2)                      | 1.520           | 0.324           |
| SSM base                          | 1.169           | 0.230           |
| SSM compound-specific             | 1.187           | 0.236           |
| **SSM skew-t (their best)** | **1.082** | **0.202** |
| Clean Air pooled                  | 1.250           | 0.241           |

**We match their best model to within 0.04 CRPS at Austria while also doing the
thing it cannot do at all** — telling the compounds apart, and turning that into
a stop count that agrees with what real teams ran at **10 of 11 races.**

### The strategy call, against what teams actually did

Every 2026 race, scored against the median stop count the field ran:

| | |
| --- | --- |
| Matched | **10 of 11** — Melbourne, Red Bull Ring, Barcelona, Spa, Silverstone, Shanghai, Zandvoort, Hungaroring, Monza, Miami |
| Missed | Monaco — we said one stop, the field ran two |
| **Refused** | **Montréal and Suzuka** — fewer than two nominated compounds had a positive rate at that circuit |

The two refusals are the point, not a gap. An optimiser handed a tyre that never
wears will run it to the flag and call that a strategy. The console shows those
two races with the reason on screen rather than a confident number, because a
model that never says "I don't know" is the one you cannot trust when it does
answer.

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

The brief asks the dashboard for **trend, pattern and prediction.** Each has a
screen of its own:

| Asked for | Where it lives | What you see |
| --- | --- | --- |
| **Trend** | Tyre Curves | Lap time lost against tyre age, per compound, with the 95% band — plus the +5/+10/+15 lap table |
| **Pattern** | Track Record | Every car's race drawn as its real stints, coloured by compound and sized by the laps it actually ran, against the call we made |
| **Prediction** | Next Race · Strategy | The stop count, the stint lengths, the pit lap, and how wrong your inputs can be before the call changes |

### Next Race — the race that has not happened yet

A race becomes answerable in stages, and the screen shows the stage honestly:

```
on the calendar    date and circuit, from the F1 API
+ nominated        Pirelli announced the compounds (the one human input)
+ practice run     long runs exist, so a forecast is possible
+ enough of it     at least two compounds have a usable rate
```

Circuit history supplies what an unraced race cannot. Monza's pit loss is
**25.45 s with a 2.02 s spread across four seasons**, its distance 53 laps — both
labelled as history, because last year's pit lane is evidence about Sunday, not a
reading from it.

**And it refuses when it has nothing.** Circuits are matched by *location*, not
by race name. The 2026 **Spanish** Grand Prix is at **Madrid**, a circuit that
has never held a race, while the Barcelona track that used to carry that name
now runs as the **Barcelona** Grand Prix. Match on the name and Madrid inherits
four seasons of Barcelona's pit lane — a precise, confident, wrong number for
the one race this system exists to forecast. Match on the location and Madrid
says *we have never raced here*, and asks for the two inputs it is missing.

That is the live demo: **Madrid, tomorrow.** FP1 is already in — 330 clean laps,
**17 long runs across 15 drivers** — pulled by the poller with nobody watching.

### Nothing needs a code push to add a race

| What                          | Where it comes from                               |
| ----------------------------- | ------------------------------------------------- |
| Which races exist             | the F1 calendar — all 23 rounds, future included |
| Session times                 | same, per session, in UTC                         |
| Race distance                 | previous seasons at that circuit                  |
| Pit loss                      | previous seasons at that circuit                  |
| New session data              | the in-process poller, every 15 minutes           |
| Refitting and republishing    | six pipeline stages, automatically, ~90 s         |
| The open browser              | re-checks every 60 s and reloads itself            |
| **Compound nomination** | **the one thing a human sets — one click** |

Pirelli slides a window of three **adjacent** compounds by circuit severity, so
only three windows exist (C1–C3, C2–C4, C3–C5). The UI offers those three, not
125 dropdown combinations. Values we cited are marked `pirelli`; anything typed
in the app is marked `user`, because those are different kinds of claim.

### The optimiser

Every legal strategy is **enumerated, not searched** — so the answer is the
optimum, not wherever a search stopped. At Monaco that is **131,053 distinct
allocations**, the worst case of the eleven; a coarse grid answers the same
question in **362 ms** while you drag a slider, and a test pins that both pick
the same stop count.

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

### It closes its own loop

Nobody runs anything on a race weekend. The chain, end to end:

```
a session ends
  -> the poller notices, within 15 minutes
  -> it pulls the session in a subprocess, under a file lock
  -> six pipeline stages refit and republish            (~90 s)
  -> every open browser sees it within 60 seconds
```

The browser step is the one that is easy to skip and fatal to skip. A tab left
open through a race used to keep showing the previous weekend's numbers while
the poller quietly refreshed the files underneath it — the pipeline doing its
job and the screen disagreeing, in front of an audience. It now re-fetches
`meta.json` every minute, a few hundred bytes, and pulls the full bundle only
when `generated_at` moves.

The safeguards are the interesting part. The poller rate-limits itself and backs
off for 45 minutes when the upstream API pushes back. It only asks for sessions
that have **actually run**, so an unraced weekend is never requested. A failed
refresh check is swallowed rather than shown: the data on screen is still the
data we last published, and a red banner over correct numbers is worse than one
missed poll.

**Pirelli's compound nomination is the only thing left for a human,** and only
because no feed carries it.

---

## Feasible, scalable, economical

The brief names these three as what industry actually looks for, so they are
measured rather than asserted. Every number below is from this repository on a
2021 laptop CPU — **12 logical cores, no GPU, nothing rented.**

**Feasible — it already runs, end to end.**

| Step | Time |
| --- | --- |
| Refit degradation on 11,039 race laps | **6.8 s** |
| Full pipeline: refit, validate, transfer, strategy, benchmark, publish | **56.4 s** |
| Forecast a whole race from Friday practice | **484 ms** |
| Re-plan mid-race when you move a slider | **6 ms** warm, 152 ms cold |

There is no training run, no GPU, no cluster, and nothing to wait for. The
heaviest thing in the project — an MCMC hierarchical model at roughly six
minutes — is an offline cross-check that the live path never touches.

**Economical — the input data is free and the output is a static file.**

| | |
| --- | --- |
| Data source | FastF1, the public F1 timing API. **No licence, no vendor, no per-seat cost.** |
| Everything the browser downloads | **196 KB** of JSON |
| Whole season, cleaned, on disk | **8.2 MB** of Parquet |
| Runtime dependencies | **13** Python, **6** JavaScript |
| Database | **none** — artifacts are files, the API is stateless |
| To serve it | static hosting plus one Python process |

A team already paying for timing data pays nothing more to run this. It fits on
the laptop that is already on the pit wall, and it works with the network
unplugged: the cache is on disk, and three of the five tabs render with the API
stopped.

**Scalable — the cost of another race is zero engineering.**

Adding a race takes **no code change and no redeploy.** The poller reconciles the
calendar against what is on disk every 15 minutes, pulls what is missing, refits,
republishes, and every open browser picks it up within 60 seconds. The same loop
handles a new season, a new circuit, and a session that ran two hours late.

The cost model is linear and shallow: one more race is ~1,000 laps, a few
megabytes, and seconds of arithmetic. The expensive axis is *network*, not
compute — which is why the poller pulls in a subprocess, backs off for 45 minutes
on failure, and asks only for the sessions it is actually missing.

> Honest limit: this consumes a public timing feed, so it inherits that feed's
> availability and its 500-calls-per-hour cap. A team running it against their
> own garage telemetry would not have that ceiling — but we have not tested that,
> because we do not have that data.

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
    session_weight.py            how much FP1, FP2 and FP3 each count toward the forecast
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
  12_session_skill.py            which practice session actually predicts the race
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
  src/RaceShapeView.tsx          every driver's stints, race by race, including the ones we refuse
  src/CompoundLabels.tsx         why nothing is grouped by HARD/MEDIUM/SOFT — derived live
  src/DegradationChart.tsx       degradation curves with uncertainty bands
  src/AblationChart.tsx          the Deconfound button
  src/ui.tsx                     shared display primitives and the type scale
  src/api.ts                     typed client for the live optimiser
  src/useStrategy.ts             coarse while dragging, exact on settle, generation-guarded
  src/useBundle.ts               loads every artifact, then reloads when the pipeline republishes
  src/types/artifacts.ts         mirrors schema.py, enforced by a parity test

data/
  artifacts/*.json               the JSON contract the web app reads — committed on purpose
  schedule/2026.json             cached calendar, so a demo survives having no network
  allocation.json                compound nominations, editable from the app

app/lab.py                       Streamlit lab bench — internal, never demoed
docs/DEPLOYMENT.md               how this ships
docs/reference/                  the benchmark paper, plus licensing notes on every source
tests/                           283 tests
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
