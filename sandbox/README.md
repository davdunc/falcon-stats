# Falcon Ralph Sandbox — microVM isolation for the AI coding agent

This directory sandboxes the **Ralph loop** — the AI coding agent (Claude Code) that
runs repeatedly against `falcon-stats`, executing arbitrary `git`/`gh`/build/test
commands each iteration — inside a **krun microVM**. Instead of sharing the host kernel
like a normal container, the agent gets its **own kernel behind a hypervisor**, so a
prompt-injection or a malicious dependency that makes the agent run arbitrary commands
cannot escalate into the host kernel.

Adapted from the Fedora Magazine article
[*Sandbox AI coding agents with microVMs on Fedora Linux*](https://fedoramagazine.org/sandbox-ai-coding-agents-with-microvms-on-fedora-linux/).

---

## Why the coding agent, and not falcon-stats itself?

The article's threat model is **an AI coding agent that runs arbitrary commands**. In
Falcon that is the Ralph loop, not the `falcon-stats` runtime container (which runs
trusted Python and only needs read access to DAS exports + DynamoDB). So this sandbox
wraps the *agent*; the existing `../Containerfile` / `../falcon-stats.container` runtime
is unchanged.

---

## What a microVM does — and does NOT — protect

| Threat | Contained by the microVM? |
|---|---|
| Agent escalates to the **host kernel** | ✅ Yes — separate kernel behind a hypervisor |
| Agent fork-bombs / mines within its caps | ✅ Blast radius capped to 4 CPU / 4 GiB / 512 pids |
| Agent **exfiltrates secrets over the network** | ❌ **No** — kernel isolation ≠ network isolation |
| Agent **pushes malicious code to `main`** via `gh` | ❌ No — the token works from inside the VM |
| Agent poisons the **mounted repo** (git hooks, build hooks) | ❌ No — the mount is a write channel back to the host |

The microVM is one layer. The mitigations below close the gaps it doesn't.

---

## Files

| File | Purpose |
|---|---|
| `Containerfile.agent` | Fedora 44 image: unprivileged `appuser`, `uv`, Claude Code, `gh`, `git`. No secrets baked in. |
| `compose.yaml` | podman-compose spec with `run.oci.handler: krun` + RAM/CPU/pids caps + hardened mounts. |
| `entrypoint.sh` | Baked into the image; drops root→`appuser` at boot and runs one Ralph iteration. |
| `run-ralph-sandboxed.sh` | Host wrapper: build + one iteration with `--rm` and a wall-clock `timeout`. |
| `.env.example` | Runtime secret template (repo-scoped `GH_TOKEN`, optional `ANTHROPIC_API_KEY`). No AWS. |

---

## Prerequisites

A microVM needs **KVM** and the krun runtime. None of this is installed by default.

```bash
# Runtime + orchestration (Fedora ships these natively — no third-party repos)
sudo dnf install -y crun-krun podman podman-compose

# Verify KVM is present (microVMs require it)
ls -l /dev/kvm            # must exist
podman info --format '{{.Host.OCIRuntime.Name}}'   # crun; krun is selected per-run
```

- **`crun-krun`** provides the krun handler (needs **libkrun ≥ 1.8**).
- **`/dev/kvm`** must exist and be accessible to your user.

### WSL2 caveat (important)

On **Fedora-on-WSL2** the microVM runs *nested* under Hyper-V. `/dev/kvm` is present on
recent WSL2 kernels (verified on this host: kernel `6.6.87.2-microsoft-standard-WSL2`),
and nested virtualization is exposed — so this **works** — but understand the tradeoff:

> On WSL2 you are trusting two hypervisor layers, and WSL kernel updates can drop
> `/dev/kvm`. Treat WSL2 microVM isolation as **"meaningfully better than a bare
> container, not a security guarantee."** For genuinely untrusted code, run this on a
> **bare-metal Fedora** host (true KVM) or a disposable cloud VM.

### Isolation is not perfect anywhere

microVMs are not a hard security boundary. libkrun has had escape vulnerabilities (e.g.
**CVE-2026-39861**). For high-risk / fully-untrusted workloads, prefer a full VM or an
ephemeral cloud instance you can destroy.

---

## Usage

```bash
# 1. Provide a repo-scoped GitHub token (NOT a classic/admin token)
cp sandbox/.env.example sandbox/.env
$EDITOR sandbox/.env          # set GH_TOKEN

# 2. Build + run one Ralph iteration inside the microVM
./sandbox/run-ralph-sandboxed.sh

# Debugging: open a shell inside the sandbox
./sandbox/run-ralph-sandboxed.sh shell

# Override the 30-minute wall-clock cap
RALPH_TIMEOUT=3600 ./sandbox/run-ralph-sandboxed.sh
```

The wrapper preflights `podman`, `podman-compose`, `/dev/kvm`, and `sandbox/.env`, then
exports `HOST_UID`/`HOST_GID`, builds the image, ensures the `claude-config` volume
exists, and runs one iteration with `--rm` and `timeout`.

---

## Security model — the controls that close the microVM's gaps

These are baked into the artifacts, derived from an adversarial review of the design:

1. **No AWS credentials in the agent VM.** The image has no `aws` CLI, `.env.example`
   carries no AWS keys, and `entrypoint.sh` **refuses to start** if AWS creds appear in
   the environment. The coding agent develops code; it never touches production trading
   credentials.
2. **Secrets injected at runtime only.** `GH_TOKEN` / `ANTHROPIC_API_KEY` come from the
   gitignored `.env` at run time — never as a build `ARG`/`ENV` (those persist in image
   layers). `.gitignore` blocks `.env` and common key material.
3. **The repo mount is the falcon-stats root only** (`../` resolves to the repo because
   this dir is nested one level in) — never the wider Falcon parent tree — mounted `:z`.
   We **do not** use `:U` (recursive chown), which would rewrite host file ownership;
   `userns_mode: keep-id` already reconciles UIDs.
4. **Agent runs unprivileged.** The microVM boots as root; the image-resident
   `entrypoint.sh` drops to `appuser` via `runuser` before any agent code runs. The
   entrypoint is baked into the image (root-owned `0755`), **not** sourced from the
   writable `/app` mount, so a compromised iteration cannot rewrite it to keep root.
5. **The gh token is the real supply-chain risk — scope it and protect `main`.** Use a
   **fine-grained PAT limited to `falcon-stats`** (Contents/Issues/PRs read-write, no
   admin). Ralph pushes to a **feature branch**, never `main`. Enforce **branch
   protection on `main`** (require PR review) on GitHub — that human gate, not the
   sandbox, is what stops the agent shipping malicious code.
6. **Network egress is not restricted by the microVM.** Anything the agent can read it
   can send over HTTPS. Keeping the VM creds-minimal (rule 1) is the primary defense.
   For stronger control, add an egress allowlist (GitHub + Anthropic + PyPI) at the host
   firewall.
7. **Bounded blast radius.** `--rm` (no lingering container), a wall-clock `timeout`,
   `pids_limit: 512`, and 4 CPU / 4 GiB caps bound a looping or compromised agent.
8. **`claude-config` volume holds credentials only.** Agent settings/hooks are baked
   read-only into the image, so a poisoned config can't persist into the next iteration.

`RALPH_PROMPT.md` is human-curated and is treated as read-only input — the sandbox never
modifies it.

---

## Notes & known limitations

- **`RALPH_PROMPT.md` references a host path (`/mnt/c/.../falcon-stats`).** Inside the
  microVM the repo is mounted at `/app`, and `entrypoint.sh` `cd`s there before invoking
  the agent, so Claude Code's working directory is correct. The literal path string in the
  prompt is informational only — but since the prompt is human-curated and must not be
  edited by the sandbox, keep it in mind if you later add path-sensitive automation.
- **Why compose and not a Quadlet `.container`?** The `falcon-stats` *runtime* ships as a
  Podman Quadlet (`../falcon-stats.container`) because it's a managed one-shot service. The
  *agent* needs krun annotations plus ephemeral `run --rm` semantics and a build step, which
  map more cleanly onto `podman-compose`. The two mechanisms are intentionally separate:
  Quadlet for the trusted runtime, compose for the sandboxed agent.
