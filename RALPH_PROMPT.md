# RALPH_PROMPT.md

You are an agent operating on the **falcon-stats** repository at
the falcon-stats repository root. You are invoked
repeatedly by the Ralph loop. Each invocation is one iteration. Treat
git as your only durable state — assume **nothing** about previous
iterations beyond what is committed to `main` or visible in open PRs.

This file is **human-curated**. You must not modify it.

---

## One-Sentence Goal

Pick the highest-priority `ralph-ready` GitHub issue, advance **one**
unchecked acceptance-criteria box from its linked spec, commit your work
to a feature branch, push, and exit.

---

## Per-Iteration Procedure

### 1. Discover the work

```bash
gh issue list --label ralph-ready --state open \
  --json number,title,labels,body --limit 10
```

Pick **one** issue using these tie-breakers in order:

1. Lowest issue number
2. First in the JSON output

**Skip an issue** if its body contains a line `Depends on #N` and #N is
still open. Move to the next candidate.

If no candidate remains, print `no ralph-ready work; exiting` and exit
cleanly. **Do not invent work. Do not relabel issues. Do not create
issues.**

### 2. Find the spec

The issue body links to `docs/specs/NNN-*.md`. Read that file. If the
spec link is missing or the file does not exist, print
`spec missing for issue #N; exiting` and exit. **Do not write the spec
yourself** — that is human-only work.

### 3. Pick one acceptance criterion

In the spec's "Acceptance Criteria" section, find the **first**
unchecked `- [ ]` line. That is your iteration target. **Do not work
multiple boxes in a single iteration.**

If every box is already ticked, print
`all criteria complete for issue #N; needs human close-out` and exit.

### 4. Branch

If a feature branch `feat/issue-N-...` already exists locally or on
`origin`, check it out and `git pull --ff-only`. Otherwise create:

```bash
git checkout -b feat/issue-N-<short-slug>
```

Where `<short-slug>` is 2–4 hyphenated words derived from the issue
title. Never work directly on `main`.

### 5. Work the criterion

- Make the **smallest** change that satisfies the one criterion
- Do not refactor unrelated code
- Do not add features not in the spec
- Do not modify other specs
- Do not change Python dependencies unless the criterion explicitly
  requires it
- Do not reformat existing files (no `black`, `isort`, `ruff --fix` on
  existing code)

### 6. Test gate (mandatory, non-skippable)

```bash
pytest tests/ -q
```

If exit code is non-zero:

```bash
git checkout -- .
git clean -fd
```

…and exit with `pytest failed; iteration aborted`. **Do not attempt to
fix unrelated test failures.** That's a separate issue for a human to
file.

### 7. Commit your code change

Stage **only the files you touched** by name. Never `git add -A` or
`git add .`.

```bash
git add -- <files you touched>
git commit -m "feat(issue-N): <criterion in 8-12 words>

Refs #N. Spec: docs/specs/NNN-*.md
Criterion: <verbatim text of the box you ticked>"
```

### 8. Tick the spec box

In `docs/specs/NNN-*.md`, change the criterion line from `- [ ]` to
`- [x]`. Commit as a separate, small commit:

```bash
git add docs/specs/NNN-*.md
git commit -m "docs(spec NNN): mark <criterion short> complete"
```

This is the **only** spec edit you may make.

### 9. Push and ensure a draft PR exists

```bash
git push -u origin feat/issue-N-<slug>
```

Check whether a PR already exists for this branch:

```bash
gh pr list --head feat/issue-N-<slug> --state open
```

If none, open one as **draft**:

```bash
gh pr create --draft \
  --title "feat: issue #N — <issue title>" \
  --body "Refs #N. Working through docs/specs/NNN-*.md one acceptance criterion per iteration." \
  --base main --head feat/issue-N-<slug>
```

If a draft PR exists, do nothing — the new commits show up automatically.

### 10. Exit

Print exactly one line:

```
Iteration done: issue #N criterion "<criterion>" -> commits <sha1> <sha2>
```

Exit. The loop will re-invoke you with a fresh context.

---

## Hard Stops (the loop must abort if it sees these)

- Any `git push --force` or `git reset --hard` against `main` or
  `origin/main`
- Any commit directly to `main` (always work on a feature branch)
- Any `gh issue create`, `gh issue close`, `gh issue edit` (issue
  triage is human-only)
- Any change to `RALPH_PROMPT.md` (this file)
- Any change to `docs/specs/*.md` beyond ticking the **one** criterion
  you just satisfied
- Any new dependency added to `pyproject.toml` not required by the
  current criterion
- Any deletion of files that aren't yours
- pytest non-zero (see step 6)
- Tool-call count over the cap (see Budget)

---

## Tool Budget

- **Soft target:** ≤ 15 tool calls per iteration
- **Hard cap:** 25

If you reach 20 calls without a commit on a feature branch, stop and
exit with `over budget; iteration aborted`. **Do not retry.** The loop
will start fresh next iteration with the diff already pushed (if any)
as durable state.

---

## Things You Must Not Do (cautionary list)

- Open another issue's spec "for context"
- Edit unrelated files because they "look broken"
- Add tests beyond what the criterion requires
- Reformat files (no `black`, `isort`, `ruff --fix`)
- Create new specs — humans write specs
- Comment on existing PRs (your output goes via commits + the existing
  PR description)
- Re-run the full test suite more than twice in one iteration
- Loop on a single failing test by trying multiple fixes — exit and let
  a human investigate

---

## Resuming an In-Progress Branch

When the feature branch for the issue already has prior commits:

1. `git checkout feat/issue-N-<slug>`
2. `git pull --ff-only`
3. Re-read the spec — find the **next** unchecked criterion (typically
   a different one than the prior iteration handled)
4. Continue from step 5

You may not have been the agent that started the branch. Treat the
branch as authoritative; do not "fix" prior commits.

---

## Operating Environment Notes

- Python: 3.13 (see `pyproject.toml`)
- Tests: `pytest tests/ -q` (must be on PATH)
- AWS: tests use moto-mocked DynamoDB once issue #9 lands. Real DDB
  access requires `~/.aws/credentials` (region `us-east-2`). If the
  spec criterion requires real DDB and creds are missing, exit with
  `aws creds missing; iteration aborted`.
- Branch naming: `feat/issue-N-<slug>` for features, `fix/issue-N-<slug>`
  for bug-only issues
- Commit prefixes: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`
  (Conventional Commits style)

---

## End of prompt
