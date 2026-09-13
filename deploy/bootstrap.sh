#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 (arm64) EC2 box. Run it AS ubuntu:
#
#   curl -fsSL https://raw.githubusercontent.com/... is not an option (private
#   repo), so copy this file over and run it:
#
#   scp -i key.pem deploy/bootstrap.sh ubuntu@<ip>:
#   ssh -i key.pem ubuntu@<ip> bash bootstrap.sh trackshift-api.duckdns.org https://clean-air-murex.vercel.app
#
# It stops half way, once, to have you add the box's deploy key to GitHub.
# Run it again and it continues. Every step is idempotent.
set -euo pipefail

API_HOST=${1:?usage: bootstrap.sh <api-hostname> <cors-origins>}
CORS_ORIGINS=${2:?usage: bootstrap.sh <api-hostname> <cors-origins>}
REPO=git@github.com:akshat3144/clean_air.git
APP=/opt/cleanair

echo "== packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3 python3-venv python3-dev build-essential git curl \
    debian-keyring debian-archive-keyring apt-transport-https

echo "== caddy"
if ! command -v caddy >/dev/null; then
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y -qq caddy
fi

echo "== swap"
# 2 GB of headroom on a 2 GB box. The refit runs as a subprocess next to the
# API, and the two together brush the limit; swap turns an OOM kill into a
# slow minute.
if ! swapon --show | grep -q /swapfile; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== deploy key"
KEY=$HOME/.ssh/id_ed25519
if [[ ! -f $KEY ]]; then
    ssh-keygen -q -t ed25519 -N "" -C "cleanair-ec2-deploy" -f "$KEY"
fi
ssh-keyscan -t ed25519 github.com 2>/dev/null >> "$HOME/.ssh/known_hosts"
sort -u -o "$HOME/.ssh/known_hosts" "$HOME/.ssh/known_hosts"
# ssh -T exits 1 even on success (GitHub gives no shell), so under pipefail
# the pipeline would too; read the message instead of the status.
if ! [[ $(ssh -T -o BatchMode=yes git@github.com 2>&1 || true) == *"successfully authenticated"* ]]; then
    cat <<MSG

------------------------------------------------------------------------
Add this as a DEPLOY KEY on the repo (read-only is enough):
  https://github.com/akshat3144/clean_air/settings/keys/new

$(cat "$KEY.pub")

Then run this script again with the same arguments.
------------------------------------------------------------------------
MSG
    exit 0
fi

echo "== checkout"
if [[ ! -d $APP/.git ]]; then
    sudo mkdir -p "$APP" && sudo chown "$USER:$USER" "$APP"
    git clone --quiet "$REPO" "$APP"
fi
cd "$APP"

echo "== python"
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .

echo "== config"
sudo tee /etc/cleanair.env >/dev/null <<ENV
CLEANAIR_POLL=1
CORS_ORIGINS=$CORS_ORIGINS
ENV
sudo cp deploy/cleanair.service /etc/systemd/system/cleanair.service
sed "s/API_HOST/$API_HOST/" deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --quiet cleanair caddy
sudo systemctl restart caddy

echo "== dataset"
# The API refuses to start without data/processed/laps.parquet, and that file
# is not in git. Pull the season from the F1 API once; the poller keeps it
# current from here. If you rsync'd data/ from a laptop first, this is a no-op.
if [[ ! -e data/processed/laps.parquet ]]; then
    .venv/bin/python scripts/01_cache_sessions.py --season 2026
fi
# Refit on the box so the artifacts match the data the box actually holds.
.venv/bin/python - <<'PY'
from cleanair.poller import _republish
ok, detail = _republish()
print(detail)
raise SystemExit(0 if ok else 1)
PY

echo "== start"
sudo systemctl restart cleanair
for _ in $(seq 1 30); do
    curl -sf http://127.0.0.1:8000/health | grep -q '"ok":true' && break
    sleep 2
done
curl -s http://127.0.0.1:8000/health; echo
echo
echo "done. From the outside: https://$API_HOST/health"
echo "GitHub secrets to set: EC2_HOST=$API_HOST  EC2_USER=$USER  EC2_SSH_KEY=<your .pem>"
