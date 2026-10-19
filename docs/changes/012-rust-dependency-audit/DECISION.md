# 012 — Audit the Rust dependencies for known vulnerabilities in CI
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/145
---
## Context

Feature 011 adds a Rust port of the store core in `rust/`, with its dependencies pinned in `rust/Cargo.lock`.
The Python dependencies are audited by the CI job `dependency_audit` (see 002): a known vulnerability fails the
pipeline and, as "Pipelines must succeed" is enabled, blocks merging. In the design of 011 the user chose the same
for the Rust dependencies, in its own merge request. The runners (tag `test`) use the docker executor on amd64.
cargo-audit publishes prebuilt, statically linked Linux binaries on GitHub; the official slim Rust image has no
tool to download them.

## Decision

- A CI job `rust_dependency_audit` runs cargo-audit on `rust/Cargo.lock`, with the policy of `dependency_audit`:
  it runs in every pipeline except Markdown-only merge requests, also in the nightly scheduled pipeline, fails on
  a known vulnerability, and retries once on a script failure. The user chose that it also blocks merge requests
  that change only Python.
- It fails on vulnerabilities only; advisories that a crate is unmaintained or yanked are shown as warnings, as
  pip-audit reports vulnerabilities only. An advisory without a fix (or a false positive) is accepted with
  `--ignore RUSTSEC-…` in the job, with reason and date in a comment, and removed once a fix exists.
- The job uses the small image `curlimages/curl`, pinned by tag and digest, and needs no Rust toolchain:
  cargo-audit only reads the lockfile. It downloads the prebuilt cargo-audit for x86_64 Linux, pinned by version
  and SHA-256, over HTTPS only, and checks the checksum of the archive before unpacking it, on every run; nothing is
  cached. The checksum was computed from the download and equals the digest GitHub lists for the release asset.
- cargo-audit runs in `/tmp` with an empty `CARGO_HOME`, so no `audit.toml` from the checkout or the image can
  change what is checked (ignore advisories, use another advisory database); the job fails if the checkout contains
  `.cargo/audit.toml` or `rust/.cargo/audit.toml`. Every ignored advisory is thus visible in the job.
- The image, the cargo-audit version and its checksum are raised together at least once per semester; if the
  pinned cargo-audit cannot read the current advisory database, the job fails with a parse error, which also means
  raising them.
- The job proves on CI that it works: a temporary lockfile with smallvec 1.6.0 (RUSTSEC-2021-0003) fails it, and a
  wrong checksum stops it before unpacking; both temporary commits are dropped from the branch before merging.

## Consequences
**Positive:** Known vulnerabilities in the Rust dependencies are caught in every merge request and every night,
without a Rust toolchain and in seconds. A merge request cannot weaken the check unnoticed.
**Negative:** A new RustSec advisory for any crate in `rust/Cargo.lock` blocks every merge request, also those that
change only Python, until it is fixed or accepted; on `main` it also skips the `pages` deploy (stage deploy, runs
only after a green test stage), as 002 records for pip-audit. The job depends on github.com (release download,
advisory database) and index.crates.io (check for yanked crates). The checksum is trusted on first use: GitHub's
digest comes from the same source as the download.

## Out of scope & deferred
- cargo-deny (licenses, banned crates, duplicate versions in addition to advisories).
- One scanner for both languages (e.g. OSV-Scanner), which would also change the Python audit of 002.
- Moving `pages` to `needs`, so that a red audit does not skip the deploy (also deferred in 002).
- Builds of cargo-audit for other runner architectures.

## Alternatives rejected
- **`cargo install cargo-audit` in the Rust image:** compiles for several minutes on every run without a cache.
- **The full `rust` image, which has curl:** a pull of about 1.5 GB for a job that needs no toolchain.
- **Alpine with `apk add curl`:** installs an unpinned package from another source on every run.
- **Caching the binary:** caches are shared between merge request branches, so one branch could plant another
  binary for the others; with a checksum check on every run, the cache would save almost nothing.
- **`--deny warnings`:** would also fail on unmaintained or yanked crates, stricter than the Python audit.
- **Running only when `rust/` changes:** the user chose to block every merge request, as for the Python audit.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-15:** The job does not check for yanked crates (`--no-yanked`). That check reads the crates.io
index, which cargo-audit locates through cargo; the image has no cargo, so the check could not run and only printed
a warning. This removes the dependency on index.crates.io named under *Consequences*. Python's audit does not check
for yanked packages either.

**Note 2026-10-15 (first runs in MR !145):** The runners are x86_64, reach github.com (release download and advisory
database) and pull `curlimages/curl`; the job takes about half a minute.
- Green on the real `rust/Cargo.lock`: job 549718
  (https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/549718).
- Red with a temporary lockfile containing smallvec 1.6.0: jobs 549733 and its retry 549742 fail with
  `RUSTSEC-2021-0003` and `error: 1 vulnerability found!`
  (https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/549742). `rust_test` failed in that pipeline
  too (job 549735), only because the edited lockfile no longer matched `Cargo.toml` (`--locked`).
- Red with a wrong `CARGO_AUDIT_SHA256`: jobs 549749 and its retry 549758 stop at `sha256sum -c` (`FAILED`), before
  `tar` and cargo-audit run (https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/549758).

Both temporary commits were dropped from the branch.

**Note 2026-10-15 (final review):** *Decision* names unmaintained and yanked crates as warnings; cargo-audit's
warnings are unmaintained and unsound crates (yanked crates are not checked, see above).
`system/tests/test_ci_config.py` checks the image digest, the absence of a cache, the fixed `CARGO_HOME` below
`/tmp` and the checksum check before `tar`. Not tested: the `audit.toml` check and running in `/tmp`, which back
each other up against a repository `audit.toml`; the HTTPS-only curl options, which the checksum check covers; and
the x86_64 check, which only gives a clear error. cargo-audit 0.22.2 contains gix crates with known CVEs (used to
fetch the advisory database anonymously): a malicious server could make the job fail or, like any tampered
advisory database, hide advisories. At the next version bump, take the first cargo-audit release with fixed gix
crates.

**Note 2026-10-19 (rebase):** The Rust port moved from `rust/` to `generated/rust/` (see the heading
"Scope-shift 2026-10-19" in `docs/changes/011-rust-store-foundation/DECISION.md`); the job and the docs now name
`generated/rust/Cargo.lock` and `generated/rust/.cargo/audit.toml`. The tests moved from
`system/tests/test_ci_config.py` to `system/tests/repo/test_ci_config.py`. The paths `rust/...` and
`system/tests/test_ci_config.py` above are the old paths, as they were when the decision was made.

**Note 2026-10-19 (second review):** Tested now as well, in `system/tests/repo/test_ci_config.py`: the
`audit.toml` check, which must come before the `cd /tmp` (`AuditTomlGuardTest`); the lockfile path
(`AuditedLockfileTest`); the absence of `allow_failure` and of `when: manual` (`NoAllowFailureTest`); the options
allowed after `cargo-audit audit` (`AuditOptionsTest`); and that both audit jobs have no `rules`, `only`, `except`
or `when`, so they also run in scheduled pipelines (`ScheduledPipelineTest`).
