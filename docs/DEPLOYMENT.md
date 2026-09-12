# Deployment

> **This is the last job, not the first.** Nothing here should be built until the model works and the artifact format is frozen. Deployment shapes itself around what the pipeline produces, so building it early means building it twice.
>
> Two paths are written up below. **Path A is now the recommendation.** It used to be Path B; see *What changed* immediately below.

---

## The API computes, it does not just serve rows

The front end is a **strategy console**: you move a pit-loss slider, toggle a safety car, drag a degradation rate, and the recommendation is recomputed. That means real compute behind an HTTP request, and it changes the hosting decision.

The rule below still holds, with a sharper line drawn through it.

### The scheduled worker now lives inside the API process

`cleanair/poller.py` runs as an asyncio task started by the API's lifespan, not
as a separate service. The recurring work is a network wait plus a tenth of a
second of arithmetic, so it does not need its own machine, and one process is
one deploy. Three rules make that safe: the pull runs in a SUBPROCESS so a
three-minute download cannot block the event loop, a file lock stops two
workers racing the same parquet, and a rate-cap failure backs off for 45
minutes rather than retrying into the 500-calls-an-hour limit.

`CLEANAIR_POLL=1` enables it. Off by default.

That removes the GitHub Actions worker and the database from the recommended
path: artifacts on disk are enough at this scale.

### The rule: FITTING never runs inside a web request. Optimising does.

Measured on this dataset:

| work | cost | where |
|---|---|---|
| fit the degradation model | 0.10s | at API startup, cached for the process |
| enumerate strategies, coarse (`step=3`) | 0.07–0.3s | **every request** |
| enumerate strategies, exact (`step=1`) | 0.35–6.6s | **every request** |
| hierarchical MCMC, one race | ~6 min | offline only, never behind a request |
| pull a session from the F1 API | up to a minute | scheduled worker only |

So the optimiser is a live endpoint and the sampler is not. `POST /fit` is still a bad idea; `POST /strategy` is the product.

**The consequence for hosting:** the exact enumeration at Barcelona is 1,060,416 plans and 6.6s on a developer laptop. On 0.1 CPU that is tens of seconds, which destroys the one interaction the demo is built around. Compute for *serving* now matters as much as compute for fitting.

The console mitigates this itself — it requests the coarse grid while a slider moves and the exact answer once it settles, and a test pins that both pick the same stop count — but a slow box still shows.

### Two things the deployed API needs from the environment

| variable | why |
|---|---|
| `CORS_ORIGINS` | comma-separated front-end origins. The React app is on a different host in every shape, so this is read from the environment rather than compiled in. |
| `VITE_API_BASE` | build-time, on the front end. Unset in dev, where Vite proxies `/api` to port 8000. |

### What updates itself

1. A practice session happens
2. The worker wakes, finds data it has not processed, pulls it
3. Fits the model, writes a row
4. The API serves the new numbers straight away
5. The site shows them

**No push, no rebuild, no human.** You only push when the *code* changes.

---

## Choosing between the paths

| | Path A — AWS EC2 | Path B — Render + Neon |
|---|---|---|
| Servers to manage | 1 (you patch it) | 0 |
| Certificates | Caddy, automatic | included |
| CPU for model fitting | 1–2 cores on the box | **4 cores, 16 GB** on a GitHub runner |
| **CPU for serving the optimiser** | **1–2 dedicated cores** | **0.1 CPU** |
| Persistent cache | yes, a disk | yes, GitHub Actions cache |
| Cost | free 12 months, then ~₹1,100/mo | **₹0, permanently** |
| Setup time | a few hours | under an hour |
| Cold starts | none | ~1 min on the API unless kept warm |

**Path A wins on serving CPU.** A slider drag is a request, so CPU is the binding constraint — and 0.1 CPU turns a 350ms answer into several seconds.

Cold starts matter for the same reason. A judge opening Next Race or Strategy on a Render free instance that has slept waits about a minute before anything appears.

Both paths still push the heavy fitting to GitHub Actions — a free 4-core, 16 GB runner beats anything either host gives you. That part of Path B was always right and is kept in Path A.

**Take Path B instead if** the console is dropped in favour of the precomputed playbook, which the app already falls back to when the API is unreachable. That is a genuine fallback and not a broken state, so Path B remains a defensible cheaper answer — it just gives up the interaction.

---

# Path A — AWS EC2 (one box)  ← recommended

```
┌─ EC2, docker compose ───────────────────────────┐
│  caddy      HTTPS, certs auto-renew              │
│  fastapi    playbook reads + live optimiser      │
│  postgres   results as JSONB                     │
│  worker     timer: pull, fit, write              │
└──────────────────────────────────────────────────┘
                       ▲ https
              React app on Vercel
```

### Instance

| Setting | Value |
|---|---|
| Region | `ap-south-1` (Mumbai) |
| AMI | Ubuntu 24.04 LTS, **ARM64** |
| Type | `t4g.small` (2 GB) — free tier only covers `t3.micro` (1 GB) |
| Storage | 20 GB gp3 |

Security group inbound: 22 from your IP, 80 and 443 from anywhere. **Never open 5432** — Postgres stays inside the Docker network.

Attach an **Elastic IP**, or the address changes on restart and the certificate breaks.

### Hostname without buying a domain

Judges only ever see the Vercel URL, so the API hostname can be anything. Create a free subdomain at [duckdns.org], point it at the Elastic IP, and Caddy gets a real Let's Encrypt certificate automatically.

### Compose

`deploy/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: cleanair
      POSTGRES_USER: cleanair
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cleanair"]
      interval: 10s
      retries: 5
    # No ports section on purpose: only other containers can reach it.

  api:
    image: ghcr.io/${GH_OWNER}/cleanair-api:latest
    restart: unless-stopped
    depends_on: { postgres: { condition: service_healthy } }
    environment:
      DATABASE_URL: postgresql://cleanair:${POSTGRES_PASSWORD}@postgres:5432/cleanair
      CORS_ORIGINS: https://cleanair.vercel.app

  worker:
    image: ghcr.io/${GH_OWNER}/cleanair-worker:latest
    restart: unless-stopped
    depends_on: { postgres: { condition: service_healthy } }
    environment:
      DATABASE_URL: postgresql://cleanair:${POSTGRES_PASSWORD}@postgres:5432/cleanair
    volumes: [fastf1cache:/cache]

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddydata:/data
    depends_on: [api]

volumes: { pgdata: , caddydata: , fastf1cache: }
```

`deploy/Caddyfile`:

```
cleanair-api.duckdns.org {
    reverse_proxy api:8000
}
```

That is the entire HTTPS setup. No certbot, no renewal cron to forget.

### Auto-deploy

GitHub Actions: run tests → build ARM images → push to `ghcr.io` → SSH to the box → `docker compose pull && up -d`.

**Build with `platforms: linux/arm64`.** Runners are x86, the box is ARM. Miss this and the container fails to start with a confusing `exec format error`.

---

# Path B — Render + Neon + GitHub Actions  ← cheaper, gives up the live console

```
GitHub Actions (cron)          Render                 Vercel
  pull data                     FastAPI                React app
  fit models          ───▶      0.1 CPU        ◀───    fetch
  write rows                       │
        │                          │
        └──────────▶  Neon Postgres  ◀───────────────┘
```

Nothing to patch, nothing to SSH into, everything deploys from git.

### B1. Database — Neon

1. Create a project at [neon.com]
2. Copy the pooled connection string
3. Run the schema below

Free plan: 0.5 GB storage and **100 compute-hours per month**, autosuspending after 5 minutes idle. Our data is a few megabytes of JSON, so storage is a non-issue.

### B2. API — Render

New Web Service from the repo:

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Build | `pip install -e .` |
| Start | `uvicorn cleanair.api:app --host 0.0.0.0 --port $PORT` |
| Plan | Free |

Environment: `DATABASE_URL` (from Neon), `CORS_ORIGINS=https://cleanair.vercel.app`.

Free tier is 512 MB and 0.1 CPU. **This is the constraint that moved the recommendation to Path A.** No fitting happens in this process — that is still true and still the rule — but the optimiser does, and 0.1 CPU turns a 350ms answer into several seconds.

Take this path only if you accept the console degrading to the precomputed playbook, which the app already falls back to cleanly.

### B3. ⚠ Keeping it warm without burning Neon

Render free services sleep after 15 minutes and take about a minute to wake. A cron pinger fixes that — but there is a trap:

**The ping must hit an endpoint that does not touch the database.**

Neon only suspends when nothing queries it. If the ping reads Postgres every 10 minutes, Neon never sleeps, and you need ~730 compute-hours a month against an allowance of 100. The free tier is gone in under a week.

So:

```python
@app.get("/health")
def health():
    return {"ok": True}      # no database call, deliberately
```

Point the pinger at `/health` only. Render stays awake, Neon stays asleep, both stay free.

### B4. Model fitting — GitHub Actions

This is what makes Path B work. Runners give **4 CPUs and 16 GB**, free, on a schedule.

`.github/workflows/fit.yml`:

```yaml
name: fit
on:
  schedule:
    - cron: "0 */6 * * *"     # every 6 hours; tighten during a race weekend
  workflow_dispatch:           # and a manual button

jobs:
  fit:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }

      # Without this every run re-downloads every session.
      - uses: actions/cache@v4
        with:
          path: data/fastf1_cache
          key: fastf1-${{ github.run_id }}
          restore-keys: fastf1-

      - run: pip install -e .
      - run: python scripts/run_pipeline.py --publish
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

`workflow_dispatch` matters on Challenge Day: after Madrid practice you press one button and the site updates. No laptop, no push.

### B5. Frontend — Vercel

Import the repo, Root Directory `web`, framework Vite.

| Env var | Value |
|---|---|
| `VITE_API_URL` | your Render URL |

Never hardcode the API address. Local development uses `web/.env.local` with `http://localhost:8000`; localhost is exempt from mixed-content blocking, so plain HTTP is fine there.

---

## Database schema (both paths)

One table does most of the work. `JSONB` suits us because artifacts are nested and their shape will evolve.

```sql
create table artifacts (
    id            bigserial primary key,
    kind          text        not null,   -- 'degradation' | 'ablation' | 'benchmark' | ...
    event         text,                   -- null when pooled across events
    season        int         not null,
    payload       jsonb       not null,
    model_version text        not null,
    created_at    timestamptz not null default now()
);

create index on artifacts (kind, season, event, created_at desc);
```

**Rows are only ever inserted, never updated.** Every fit is a new row.

That gives history for free — you can show how an estimate changed as more of a session came in, which the static-file version could not do. The API returns the newest row unless asked for a specific time.

---

## Local development

```bash
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=dev postgres:17-alpine
uvicorn cleanair.api:app --reload      # :8000
cd web && npm run dev                  # :5173
```

Set `VITE_API_URL=http://localhost:8000` in `web/.env.local`.

---

## Troubleshooting

**Browser blocked the request.** Mixed content — an HTTPS page cannot call an HTTP API. Check `VITE_API_URL` starts with `https://`.

**CORS error.** `CORS_ORIGINS` must match the frontend origin exactly, scheme included. Vercel preview deployments get different URLs, so allow a pattern if you want previews working.

**Neon free tier exhausted.** Something is querying the database continuously. Almost always the keep-alive ping hitting a DB-backed endpoint — see B3.

**First request takes a minute.** Render cold start. The pinger is not running, or it is pointed at the wrong path.

**`exec format error` (Path A).** An x86 image on an ARM box. Rebuild with `platforms: linux/arm64`.

**Out of memory during a fit.** Reduce chains, or move the fit to GitHub Actions where there is 16 GB.

---

## On the day

The site is live, so present from the Vercel URL.

Two pieces of insurance that cost nothing:

```bash
cd web && npm run build     # dist/ runs from a plain folder
```

Not because the internet will fail, but because deploys, DNS and captive portals do things you cannot control. A built copy on the laptop means a network problem can never stop the pitch.

And run the full pipeline once **before travelling**, so the database already holds fresh results. A live update on the day should be a bonus, never a dependency.
