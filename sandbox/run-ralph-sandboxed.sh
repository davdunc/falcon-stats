#!/usr/bin/env bash
# run-ralph-sandboxed.sh — build the sandbox image and run ONE Ralph iteration inside a
# krun microVM. This is the host-side wrapper the operator invokes.
#
#   ./sandbox/run-ralph-sandboxed.sh          # build (cached, near no-op if unchanged) + one iteration
#   ./sandbox/run-ralph-sandboxed.sh shell    # drop into the sandbox for debugging
#   RALPH_TIMEOUT=1800 ./sandbox/run-ralph-sandboxed.sh   # override wall-clock cap
#
# Isolation model: the microVM gives the agent its own kernel. This wrapper adds the
# host-side controls the VM can't provide: a wall-clock timeout, one-shot --rm cleanup,
# and host UID/GID reconciliation. See sandbox/README.md for the full threat model.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Boundary assert: compose mounts `../` as /app, which MUST be the falcon-stats repo root.
# If this dir is ever relocated deeper, refuse rather than silently mounting the wider
# Falcon parent tree (exactly the exposure the sandbox exists to prevent).
if [[ ! -f ../RALPH_PROMPT.md || ! -d ../.git ]]; then
    echo "run: FATAL — sandbox/ must sit in the falcon-stats repo root (../RALPH_PROMPT.md + ../.git not found)." >&2
    exit 1
fi

# Host identity so files written to the mounted repo are owned by you, not root.
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

# Wall-clock cap on a single iteration — bounds a compromised/looping agent (default 30m).
RALPH_TIMEOUT="${RALPH_TIMEOUT:-1800}"

# Preflight: the tooling from the article must be present. Author-only setups will trip
# these until `dnf install crun-krun podman-compose` has been run — that's expected.
missing=0
for bin in podman podman-compose; do
    command -v "$bin" >/dev/null 2>&1 || { echo "run: MISSING '$bin' (see sandbox/README.md install steps)" >&2; missing=1; }
done
[[ -e /dev/kvm ]] || { echo "run: MISSING /dev/kvm — microVMs need KVM (see README WSL2/bare-metal notes)" >&2; missing=1; }
[[ -f .env ]] || { echo "run: MISSING sandbox/.env — copy .env.example and fill in a repo-scoped GH_TOKEN" >&2; missing=1; }
[[ "$missing" -eq 0 ]] || exit 1

echo "run: building sandbox image (HOST_UID=$HOST_UID HOST_GID=$HOST_GID)..."
podman-compose build

# One-time persistent volume for Claude Code OAuth/session state.
podman volume inspect claude-config >/dev/null 2>&1 || podman volume create claude-config

CMD="${1:-ralph-once}"
echo "run: launching microVM (runtime=krun, timeout=${RALPH_TIMEOUT}s, cmd=${CMD})..."

# --rm: no lingering container. timeout: hard wall-clock bound. The krun runtime and RAM/
# CPU/pids caps come from compose.yaml annotations.
timeout --signal=TERM --kill-after=30 "${RALPH_TIMEOUT}" \
    podman-compose run --rm ralph "$CMD"

echo "run: iteration complete."
