#!/usr/bin/env bash
# Runs ON THE BOX, over SSH from GitHub Actions. Usage: deploy.sh <git-sha>
#
# Two stages, because this file is itself part of what gets deployed:
#   stage 1  take the poller lock, fetch and check out the requested commit,
#            then re-exec the NEW copy of this script
#   stage 2  install, refit if anything the artifacts depend on changed,
#            restart, and refuse to report success until /health says ok
#
# The lock matters. The poller in the running API pulls a session and rewrites
# every artifact in one go; resetting the tree or restarting the service in the
# middle of that leaves half-written JSON on disk. The poller checks the same
# lock file before it starts a pull, so holding it here is enough.
set -euo pipefail

APP=/opt/cleanair
LOCK=$APP/data/processed/.poller.lock
PY=$APP/.venv/bin/python
SHA=${1:?git sha}

cd "$APP"

if [[ "${2:-}" != "--stage2" ]]; then
    # ---- stage 1 --------------------------------------------------------
    # Wait for an in-flight pull rather than racing it. A pull is bounded at
    # twenty minutes by the poller itself, so this cannot spin forever.
    for _ in $(seq 1 60); do
        [[ -e $LOCK ]] || break
        echo "deploy: poller holds the lock, waiting"; sleep 20
    done
    mkdir -p "$(dirname "$LOCK")"
    echo "deploy $SHA $(date -u +%FT%TZ)" > "$LOCK"

    OLD=$(git rev-parse HEAD)
    # Artifacts the poller rewrote since the last deploy. They are about to be
    # clobbered by the committed copies, so remember that a refit is owed.
    DIRTY=$(git status --porcelain -- data/artifacts | wc -l)

    git fetch --quiet origin
    git reset --hard --quiet "$SHA"
    echo "deploy: $OLD -> $(git rev-parse --short HEAD)"

    exec bash "$APP/deploy/deploy.sh" "$SHA" --stage2 "$OLD" "$DIRTY"
fi

# ---- stage 2 ------------------------------------------------------------
OLD=$3
DIRTY=$4
trap 'rm -f "$LOCK"' EXIT

"$PY" -m pip install --quiet -e .

# Refit when the model code, the pipeline, or the committed artifacts moved,
# or when the box had fresher artifacts than the commit. Skipped when there is
# no dataset yet: that is the first deploy, before bootstrap.sh has seeded it.
if [[ -e data/processed/laps.parquet ]]; then
    changed=0
    git diff --quiet "$OLD" HEAD -- src scripts pyproject.toml data/artifacts || changed=1
    if (( changed || DIRTY )); then
        echo "deploy: refitting artifacts (code changed: $changed, box was ahead: $DIRTY)"
        "$PY" - <<'PYEOF'
from cleanair.poller import _republish
ok, detail = _republish()
print("deploy:", detail)
raise SystemExit(0 if ok else 1)
PYEOF
    else
        echo "deploy: nothing the artifacts depend on changed, skipping refit"
    fi
else
    echo "deploy: no dataset on disk yet, skipping refit (run deploy/bootstrap.sh)"
fi

sudo systemctl restart cleanair

# Startup loads the dataset and fits the degradation model, which is a few
# seconds. Give it a minute, then fail loudly with the log rather than let a
# green tick sit on top of a 503.
for _ in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/health | grep -q '"ok":true'; then
        echo "deploy: healthy"
        exit 0
    fi
    sleep 2
done
echo "deploy: /health never came up" >&2
sudo journalctl -u cleanair -n 60 --no-pager >&2
exit 1
