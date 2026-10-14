# ADR 0001 — falcon-stats goes public with rewritten history, under GPL-3.0

**Status:** accepted · **Date:** 2026-10-14

## Context

falcon-stats was private, though a 2026-04-27 blog post announced it as open source and linked to it. A
pre-publication audit of all 46 commits found real broker account identifiers in 7 commits (58
occurrences, 2026-04-27 → 05-09). They had been scrubbed from the code on 2026-05-09, but they remained
in history on every branch. No secrets, cloud account IDs, or trade data were found. The author email in
commit metadata was a personal address.

Three options were weighed:
- **A1:** rewrite history, force-push, and ask GitHub Support to purge cached views and pull-request refs.
  This keeps issues and PRs, but the identifiers stay reachable through old PR pages until Support acts.
- **A2:** rewrite history, then delete and recreate the repository under the same name. The identifiers
  are gone the same day, and the URL is kept, but issues and PRs are lost.
- **B:** start a fresh public repo from the current tree and keep the private one for history. That means
  two repositories to keep in sync.

## Decision

**A2.** History was rewritten with `git filter-repo`:
- account identifiers became `<LIVE_ACCOUNT>` / `<SIM_ACCOUNT>` in files and commit messages;
- the author email became the GitHub noreply address.

The repository was deleted and recreated as `davdunc/falcon-stats`, and the 5 branches were pushed. A scan
of every object in the rewritten repository for the deny-listed identifiers found zero hits before the
push. Issues and open PRs were exported first and re-opened with identifiers redacted.

The project is licensed **GPL-3.0-or-later**: derivatives that are distributed must stay open source.
Machine-restore tooling (`Restore-PAI.ps1`) was removed from this repo, since it is personal
infrastructure and unrelated to the tool.

## Consequences

- Every pre-rewrite clone must be discarded and re-cloned. Old SHAs no longer exist upstream.
- Issue and PR numbers changed. Old PR discussion survives only in the export, not on GitHub.
- On `feature/sqlite-canonical`, `broker_parser.py` sets the account as a literal, which is now the
  placeholder string. That branch must be rebased onto `main`, which reads the account from config,
  before merging.
- Before anything is published, scan for identifiers (the LifeOS containment deny list), including in
  issue and PR text, not just code.
