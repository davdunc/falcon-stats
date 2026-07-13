# Spec 003 — Wire the Ralph loop to run inside the microVM sandbox

## Status Checklist

- [x] Spec drafted
- [ ] Spec reviewed
- [ ] Implementation complete
- [ ] Tests passing on `pytest tests/ -q`
- [ ] Merged to `main`

## Problem

The `sandbox/` directory (PR #18) provides a krun microVM image + `compose.yaml` +
`entrypoint.sh` + `run-ralph-sandboxed.sh` that runs **one** Ralph iteration inside a
microVM. What is still missing is the **loop driver** that runs iterations repeatedly, and
the documentation/tests that make "run the Ralph loop *through the sandbox*" the sanctioned
path instead of running Claude Code directly on the host.

## Goal

Provide a small, well-tested loop driver and the docs/tests to wire the existing
single-iteration sandbox into a repeatable Ralph loop, so the agent's arbitrary commands
always execute inside the microVM, never on the host.

## Non-goals

- Changing `RALPH_PROMPT.md` (human-curated; must not be modified).
- Installing `crun-krun`/`podman-compose` or booting a microVM in CI (author-only; the
  operator runs the loop on a KVM-capable Fedora host).
- Adding any new Python runtime dependency.
- Changing the microVM image, compose annotations, or the security model from PR #18.

## Design

A thin POSIX/bash driver `sandbox/ralph-loop.sh` that repeatedly invokes
`run-ralph-sandboxed.sh ralph-once`, sleeping between iterations, and stops when a single
iteration reports no work (`no ralph-ready work; exiting`) or a max-iteration bound is hit.
The driver adds only host-side loop control — all agent work stays inside the microVM that
`run-ralph-sandboxed.sh` already boots.

## Acceptance Criteria

- [ ] `sandbox/ralph-loop.sh` exists, is executable, and passes `bash -n`
- [ ] `ralph-loop.sh` invokes `run-ralph-sandboxed.sh ralph-once` once per iteration
- [ ] `ralph-loop.sh` accepts a max-iterations argument (default sensible, documented)
- [ ] `ralph-loop.sh` sleeps a configurable interval between iterations
- [ ] `ralph-loop.sh` exits cleanly when an iteration outputs `no ralph-ready work; exiting`
- [ ] `ralph-loop.sh` refuses to run if `run-ralph-sandboxed.sh` is missing or non-executable
- [ ] `sandbox/README.md` gains a "Running the full loop" section documenting `ralph-loop.sh`
- [ ] `tests/test_sandbox_wiring.py` asserts `ralph-loop.sh`, `run-ralph-sandboxed.sh`, and `entrypoint.sh` exist and are executable
- [ ] `tests/test_sandbox_wiring.py` asserts `ralph-loop.sh` references `run-ralph-sandboxed.sh` and `ralph-once`
- [ ] Pytest gate green locally: `pytest tests/ -q` exits 0
- [ ] No regressions in existing tests

## References

- PR #18 — `sandbox/` microVM artifacts (Containerfile.agent, compose.yaml, entrypoint.sh, run-ralph-sandboxed.sh, README.md)
- Fedora Magazine — *Sandbox AI coding agents with microVMs on Fedora Linux*
- `RALPH_PROMPT.md` — the human-curated loop contract this driver executes (read-only)
