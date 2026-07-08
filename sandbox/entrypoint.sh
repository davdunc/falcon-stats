#!/usr/bin/env bash
# entrypoint.sh — baked into the sandbox image at /usr/local/bin/entrypoint.sh.
#
# The krun microVM ALWAYS boots as root and ignores the Containerfile USER directive.
# This script is the trusted, image-resident hand-off that drops root -> appuser before
# any agent code runs. It is intentionally NOT read from the /app mount (which the agent
# can write to) — a mutable entrypoint would let a compromised iteration retain root.
set -euo pipefail

APP_USER="appuser"

# gh reads GH_TOKEN from the environment (injected via the runtime env-file). Fail loud
# if it is missing so Ralph doesn't silently run without push/issue access.
if [[ -z "${GH_TOKEN:-}" ]]; then
    echo "entrypoint: WARNING — GH_TOKEN not set; gh operations (issues/PR/push) will fail." >&2
fi

# Guard: this VM must never carry AWS creds. Refuse to start if they leak in via ANY standard
# environment spelling or a mounted credentials file — the coding agent has no business
# holding production trading credentials.
if [[ -n "${AWS_ACCESS_KEY_ID:-}${AWS_SECRET_ACCESS_KEY:-}${AWS_SESSION_TOKEN:-}${AWS_PROFILE:-}${AWS_SHARED_CREDENTIALS_FILE:-}${AWS_WEB_IDENTITY_TOKEN_FILE:-}${AWS_ROLE_ARN:-}${AWS_CONTAINER_CREDENTIALS_RELATIVE_URI:-}${AWS_CONTAINER_CREDENTIALS_FULL_URI:-}" \
   || -f "${HOME:-/home/appuser}/.aws/credentials" ]]; then
    echo "entrypoint: FATAL — AWS credentials detected in the coding-agent VM. Refusing to start." >&2
    exit 1
fi

run_ralph_once() {
    # One Ralph iteration: hand the human-curated RALPH_PROMPT.md to Claude Code
    # non-interactively. RALPH_PROMPT.md is read-only input and is never modified.
    cd /app
    if [[ ! -f RALPH_PROMPT.md ]]; then
        echo "entrypoint: FATAL — /app/RALPH_PROMPT.md not found (is the repo mounted?)." >&2
        exit 1
    fi
    exec claude -p "$(<RALPH_PROMPT.md)" --dangerously-skip-permissions
}

# If we booted as root (the microVM default), re-exec this same script as appuser via
# runuser so the agent never runs privileged. Forward args unchanged; the dispatch below
# owns the default, so the ralph-once default lives in exactly one place.
if [[ "$(id -u)" -eq 0 ]]; then
    exec runuser -u "${APP_USER}" -- /usr/local/bin/entrypoint.sh "$@"
fi

# Dispatch (unprivileged). Default to one Ralph iteration when no command is given.
case "${1:-ralph-once}" in
    ralph-once) run_ralph_once ;;
    shell)      exec /bin/bash ;;
    *)          exec "$@" ;;
esac
