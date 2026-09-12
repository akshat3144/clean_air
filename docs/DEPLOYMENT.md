# Deployment

How Clean Air runs in production, and how to set it up from nothing.

---

## The shape of it

```
┌─ EC2, one box, docker compose ──────────────────┐
│                                                  │
│  caddy      HTTPS in front, certs auto-renew     │
│     │                                            │
│  fastapi    read-only API over the database      │
│     │                                            │
│  postgres   results stored as JSONB              │
│     ▲                                            │
│  worker     on a timer: checks for new sessions, │
│             pulls data, fits models, writes rows │
└──────────────────────────────────────────────────┘
                       ▲ https
                       │
              React app on Vercel
```

Frontend and backend are deployed separately and neither blocks the other.

## The one rule

**The model never runs inside a web request.**

The worker fits models on a schedule and writes results to Postgres. The API only reads.

This matters because a model fit takes seconds to minutes, and F1 data pulls take up to a minute. If that happened during a request, the demo would show a spinner or a timeout while judges watched. Reading a finished row from Postgres takes milliseconds and cannot fail in an interesting way.

If you ever feel tempted to add `POST /fit`, don't. Add a job the worker picks up instead.

## What updates itself

1. A practice session happens
2. The worker wakes up, finds data it has not processed, pulls it
3. Fits the model, writes a row
4. The API serves the new numbers straight away
5. The site shows them

**No push, no rebuild, no human.** You only push when the *code* changes.

---

## Before you start

- [ ] AWS account (free tier covers the box for 12 months on a new account)
- [ ] GitHub repo pushed
- [ ] Vercel account, connected to GitHub
- [ ] DuckDNS account (free, sign in with GitHub)
- [ ] An SSH key pair for the EC2 box

No paid domain is needed. Judges only ever see the Vercel URL; the API hostname is invisible inside the JavaScript.

---

# Part 1 — Frontend on Vercel

1. Import the repo at <https://vercel.com/new>
2. Set **Root Directory** to `web`
3. Framework preset: Vite. Build `npm run build`, output `dist`
4. Add an environment variable:

   | Name | Value |
   |---|---|
   | `VITE_API_URL` | `https://cleanair-api.duckdns.org` |

5. Deploy

You get `cleanair.vercel.app`. Every push to `main` redeploys automatically. Pull requests get their own preview URL.

**Why the API URL is an environment variable:** so local development points at `localhost:8000` and production points at EC2, with no code change. Never hardcode it.

Local override goes in `web/.env.local` (gitignored):

```
VITE_API_URL=http://localhost:8000
```

---

# Part 2 — Backend on EC2

## 2.1 Launch the instance

| Setting | Value |
|---|---|
| Region | `ap-south-1` (Mumbai) |
| AMI | Ubuntu Server 24.04 LTS, **ARM64** |
| Type | `t4g.small` (2 vCPU, 2 GB) |
| Storage | 20 GB gp3 |
| Key pair | create one, keep the `.pem` safe |

Security group inbound rules:

| Port | Source | Why |
|---|---|---|
| 22 | your IP only | SSH |
| 80 | anywhere | Let's Encrypt certificate challenge |
| 443 | anywhere | the API |

Do **not** open 5432. Postgres stays inside the Docker network and is never reachable from the internet.

ARM (`t4g`) is chosen because it is cheaper than x86 for the same performance, and every image we use has ARM builds.

## 2.2 Point a hostname at it

Allocate an **Elastic IP** and attach it to the instance. Without this the IP changes every time the box restarts, and the certificate breaks.

Then at <https://duckdns.org>:

1. Create a subdomain, e.g. `cleanair-api`
2. Set its IP to your Elastic IP
3. Copy your DuckDNS token — the worker uses it to keep the record fresh

You now have `cleanair-api.duckdns.org`. Caddy gets a real Let's Encrypt certificate for it automatically.

## 2.3 Install Docker

```bash
ssh -i key.pem ubuntu@<elastic-ip>

sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker
docker compose version
```

## 2.4 Compose file

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
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cleanair"]
      interval: 10s
      retries: 5
    # No ports section on purpose. Only other containers can reach it.

  api:
    image: ghcr.io/${GH_OWNER}/cleanair-api:latest
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql://cleanair:${POSTGRES_PASSWORD}@postgres:5432/cleanair
      CORS_ORIGINS: https://cleanair.vercel.app

  worker:
    image: ghcr.io/${GH_OWNER}/cleanair-worker:latest
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql://cleanair:${POSTGRES_PASSWORD}@postgres:5432/cleanair
      DUCKDNS_TOKEN: ${DUCKDNS_TOKEN}
      DUCKDNS_DOMAIN: cleanair-api
    volumes:
      - fastf1cache:/cache

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddydata:/data
    depends_on: [api]

volumes:
  pgdata:
  caddydata:
  fastf1cache:
```

`deploy/Caddyfile`:

```
cleanair-api.duckdns.org {
    reverse_proxy api:8000
}
```

That is the whole HTTPS setup. Caddy requests the certificate on first start and renews it forever. There is no certbot and no cron job to forget about.

## 2.5 Secrets

On the box, `deploy/.env` (never committed):

```
POSTGRES_PASSWORD=<long random string>
DUCKDNS_TOKEN=<from duckdns.org>
GH_OWNER=<your github username>
```

Generate the password with `openssl rand -base64 32`.

## 2.6 Start it

```bash
cd deploy
docker compose up -d
docker compose logs -f caddy   # watch the certificate get issued
curl https://cleanair-api.duckdns.org/health
```

---

# Part 3 — Database

One table does most of the work. Postgres `JSONB` suits us because artifacts are nested and their shape evolves.

```sql
create table artifacts (
    id          bigserial primary key,
    kind        text        not null,   -- 'degradation' | 'ablation' | 'benchmark' | ...
    event       text,                   -- null when pooled across events
    season      int         not null,
    payload     jsonb       not null,
    model_version text      not null,
    created_at  timestamptz not null default now()
);

create index on artifacts (kind, season, event, created_at desc);
```

**Rows are never updated, only inserted.** Every fit is a new row.

That gives history for free. You can show how the estimate for a session changed as more laps came in — a demo feature the static-file version could not do. The API returns the newest row unless asked for a specific `created_at`.

---

# Part 4 — Auto-deploy on push

`.github/workflows/deploy.yml`:

```yaml
name: deploy
on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest
      - run: ruff check .

  build:
    needs: test
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    strategy:
      matrix: { target: [api, worker] }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3        # needed to build ARM on x86 runners
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: .
          file: deploy/Dockerfile.${{ matrix.target }}
          platforms: linux/arm64
          push: true
          tags: ghcr.io/${{ github.repository_owner }}/cleanair-${{ matrix.target }}:latest

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.EC2_HOST }}
          username: ubuntu
          key: ${{ secrets.EC2_SSH_KEY }}
          script: |
            cd ~/clean_air/deploy
            docker compose pull
            docker compose up -d
            docker image prune -f
```

GitHub secrets to add: `EC2_HOST` (the Elastic IP) and `EC2_SSH_KEY` (contents of the `.pem`).

**Tests gate the deploy.** If `pytest` fails, nothing ships.

Note the `platforms: linux/arm64` line. GitHub runners are x86, the box is ARM, so images are cross-built with QEMU. Forgetting this produces an image that will not start, with a confusing `exec format error`.

---

# Part 5 — The worker

A loop, not a web service. Roughly:

```python
while True:
    for event, session in sessions_worth_checking():
        if already_processed(event, session):
            continue
        laps = pull(event, session)          # FastF1, cached to /cache
        result = fit(laps)
        insert_artifact(kind="degradation", event=event, payload=result)
    refresh_duckdns()
    sleep(30 * 60)
```

Points that matter:

- **The FastF1 cache is a Docker volume.** Without it every restart re-downloads everything.
- **Check before fitting.** Sessions do not change once complete, so process each one once.
- **A failed session must not kill the loop.** Catch per session, log, carry on.
- **Race weekends are the only time anything changes.** Half-hourly is plenty; during a live session drop it to five minutes with an env var.

---

## Local development

Run the same stack locally, minus Caddy:

```bash
docker compose -f deploy/docker-compose.local.yml up -d   # postgres only
uvicorn cleanair.api:app --reload                          # api on :8000
cd web && npm run dev                                      # site on :5173
```

Set `VITE_API_URL=http://localhost:8000` in `web/.env.local`. Localhost is exempt from mixed-content blocking, so plain HTTP is fine here.

---

## Costs

| | |
|---|---|
| EC2 `t4g.small` | ~₹1,100/month, free for 12 months on a new account |
| Postgres (in Docker, same box) | ₹0 |
| DuckDNS hostname | ₹0 |
| Let's Encrypt certificates | ₹0 |
| Vercel | ₹0 on the hobby plan |
| Domain | ₹0 — not needed |

RDS is deliberately not used. It is roughly ₹1,200/month more and buys managed backups we do not need here. If this ever became a real product, that is the first thing to change.

A paid domain is cosmetic only. Buy one if you want `cleanair.dev` on the final slide.

---

## Troubleshooting

**Certificate will not issue.** Port 80 must be open to the world, not just your IP — Let's Encrypt validates over HTTP. Check the DuckDNS record actually resolves to the Elastic IP: `dig +short cleanair-api.duckdns.org`.

**Browser console says the request was blocked.** Mixed content: an HTTPS page cannot call an HTTP API. Confirm `VITE_API_URL` starts with `https://`.

**CORS error.** `CORS_ORIGINS` on the API must exactly match the frontend origin, scheme included. Vercel preview deployments get different URLs, so allow a pattern if you want previews to work.

**Container will not start, `exec format error`.** An x86 image on an ARM box. Rebuild with `platforms: linux/arm64`.

**Box runs out of memory during a fit.** 2 GB is tight for MCMC. Either reduce chains, add a swap file, or move up to `t4g.medium`.

**Data has stopped updating.** Check the worker: `docker compose logs worker --tail 100`. It is designed to keep running through failures, so an error there is silent by design.

---

## On the day

The site is live, so present from the Vercel URL. But keep insurance that costs nothing:

```bash
cd web && npm run build     # dist/ runs from a folder, no network
```

Not because the internet will fail — because deploys, DNS and captive portals do things you cannot control, and a built copy on the laptop means a network problem can never stop the pitch.

Also worth doing before you travel: run the whole pipeline once against the most recent weekend so the database already holds fresh results. Then a live update on the day is a bonus, not a dependency.
