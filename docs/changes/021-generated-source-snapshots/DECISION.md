# 021 — Keep the Python sources of the generated Rust
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/164
---
## Context

The Rust code in `generated/rust/` is generated from the Python code in `system/` (see "Scope-shift 2026-10-19" in
[011's DECISION.md](../011-rust-store-foundation/DECISION.md)). The manifest records, for every Rust file, a hash of
each Python source at the time of generation, so the check knows when a Rust file is out of date. To regenerate it, one
also needs the old text of the source, to see what changed. That text was nowhere: the first regeneration (019)
searched the git history by content hash, as `generated_at_commit` names a branch commit that is gone after a squash
merge, and a skill that described this search in prose (closed MR !163) kept breaking. Like a build system, the tools
should do the mechanical steps; the skill only the translation.

## Decision

- Dependencies stay per file, as today. A model of dependencies per function or class was considered and dropped
  (user decision): it needs much more tooling, and the AI can read in a diff which parts changed. Whether a change
  touches the ported parts of a file is judged from the diff and the README of `generated/rust/`.
- `--update` stores every Python source in the version it records as `generated/python_sources/<hash>.txt`, once per
  version, named by the manifest's hash. The copies are never deleted (user decision): two merge requests merged at
  the same time cannot leave an entry without its copy, and the folder grows only by the changed versions.
- `--diff [<rust file> ...]` shows, for each old version of a source, its diff against the current file, with the Rust
  files that were generated from it; without arguments, for all out-of-date files.
- The check also reports missing or corrupt copies and other files in the folder; `--update` stops on corrupt copies
  and other files, and writes missing copies anew.
- Copies, not git blob ids: a source version generated inside a merge request and changed again before the squash
  never reaches `main` as a blob, but its committed copy does.

## Consequences

**Positive:** The old text of every source is in the repository, also after squash merges; `--diff` gives the AI
exactly the change to port.

**Negative:** The repository holds a copy of each recorded version of the ported Python sources (280 KB for the 14
sources today, growing with every regeneration). A change of a part of a source that is not ported still makes its Rust
files out of date; the AI then sees in the diff that there is nothing to port.

## Out of scope & deferred

- Dropping `generated_at_commit` from the manifest (its own merge request, user decision): it conflicts on every rebase
  and is redundant with the copies.
- `--update <rust file>`, recording a single regenerated file.
- `--prune`, removing copies that no entry names, if the folder ever grows too large.
- Verification tools (test names, unchanged Cargo files, dangerous calls) and the short skill `/regenerate-rust`
  (the next merge requests).

## Alternatives rejected

- Dependencies per function or class: much more tooling for the early cutoff it buys (user decision).
- Bazel: its actions must be deterministic and its outputs are build artefacts; our generator is an AI and its output
  is checked-in source code; it knows dependencies per file only.
- The old text from the git history (by commit or blob id): a commit is gone after a squash merge, and a blob of a
  version changed again before the squash never reaches `main`.
- Mirrored `.py` copies: black, pylint and semgrep would treat them as code, and one copy per Python file breaks when
  only some of the Rust files of a shared source are regenerated.
- Deleting copies that no entry names: a race between merge requests could remove a copy that is still needed.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-20 (final review):** "writes missing copies anew" above means the copies of the current source versions;
a missing copy of an older version cannot be written by the update and is restored from git (the check's message says
how), as running the update instead would record out-of-date Rust files as current; if git has no intact copy, the old
text is lost, and the Rust files of the source are regenerated from the current one before the update. Copies are
written to a hidden file first and then renamed, so an interrupted update leaves no cut-off copy.
