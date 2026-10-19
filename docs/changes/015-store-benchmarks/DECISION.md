# 015 — Benchmarks of the MVCC store: Python and Rust
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/148
---
## Context

With 013 and 014, the MVCC store exists in Python (`system/stores/MVCC.py`) and in Rust (`rust/`), with the same
algorithm and both validation methods. The user wants to compare them: micro-benchmarks of single operations,
transactions per second, and how both scale with the size of the store, presented visually on a web page later.
The user chose to compare Python with Rust using struct values only, a static HTML page, measurements on a local
machine with the results checked in, and two merge requests: this one (workloads, runner, results) and one for the
HTML report. The series plan of 011 had placed the benchmarks after the indexed store and with more Rust variants.

## Decision

- **Workloads**, the same in both languages with the same deterministic data:
  - micro-benchmarks for stores of 100, 1 000 and 10 000 objects, with validation method 2: bulkload, point reads,
    `read_objects` (which scans all objects), and transactions of one update and a commit;
  - transactions per second on a store of 1 000 objects, for each validation method: read-only transactions,
    reading and writing transactions without conflicts, and pairs of transactions where the second fails
    validation.
  Each workload states exactly what is timed; building the data and filling the store are not.
- **Cross-check between the languages.** After each pass, both languages report a fingerprint of the work done
  (commits, aborts, objects read, final transaction counter, committed versions, sum of a field of the final
  objects); the runner rejects a run in which Python and Rust differ.
- **Harness without extra libraries.** One pass runs the workload on a fresh store; a repetition repeats passes until
  their timed parts add up to at least 50 ms; seven repetitions after a warm-up, reported as median, minimum and
  maximum. Every workload runs in its own process in both languages (Python as a module, Rust as a release build
  of an example program). Python's garbage collector is off while timing, as with `timeit`.
- **Results with provenance.** `benchmarks/results.json` holds all repetitions, fingerprints and the machine (CPU,
  cores, OS, Python and Rust versions, no host or user name), the git commit and whether the working tree had
  changes.
- **Location.** The Python code is a package in `system/benchmarks/`, so CI lints, tests and documents it; the Rust
  workloads are an example program whose tests run with `cargo test`. CI runs the tests only, it does not measure.
- **Report (next merge request).** A self-contained static page without JavaScript: charts as SVG with real text,
  one rendering for light and one for dark, text alternatives and a table; a text on what is measured and on the
  fairness of the comparison. It is meant for another web site than the project's GitLab Pages (user decision), so
  it uses relative links only.

## Consequences
**Positive:** Students see how much a compiled, statically typed implementation of the same algorithm gains, and
where both pay for the algorithm itself (scanning all objects, keeping all versions). The fingerprint check makes
sure both languages do the same work.
**Negative:** The numbers depend on the machine and are only as current as the last local run; the page names the
commit and machine. Python's numbers include costs of its implementation (pydantic objects, deep copies, generator
in `get`), Rust's include copies on reads; the comparison measures the two implementations, not the languages alone.

## Out of scope & deferred
- The HTML report with charts: the next merge request.
- Rust with a dynamic value enum and with closure predicates (planned in 011): deferred to a later benchmark merge
  request, as are benchmarks of the indexed store (step 2 of the series).
- Publishing the page; timing in CI; multithreading; calling Rust from Python.

## Alternatives rejected
- **criterion (Rust) and pyperf or pytest-benchmark (Python):** about 40 more crates or another dependency, and the
  two languages would be measured differently; one simple scheme for both is fairer and easier to read.
- **A workload file shared by both languages (JSON):** Rust would need serde; the runner passes the parameters on
  the command line instead.
- **Measuring in CI:** shared runners give noisy numbers.
- **Measuring Python in the runner's process:** the runner's own objects and imports would affect the garbage
  collector and the heap; each workload gets a fresh process, as in Rust.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-16 (Phase 3):**
- The fingerprint's last field weights the field of each object by its position in the store
  (Σ (position + 1) · b), so that it also shows which objects were updated.
- Python's garbage collector runs once before each repetition and is off for the whole repetition, untimed setup
  included.
- Reads or transactions per pass are a parameter of both programs, so both test suites pin the same small runs; a
  pass that times no operation is rejected.

**Note 2026-10-16 (review of the MR stack):**
- `results.json` holds every repetition; the median, minimum and maximum are computed from them by `Measurement`
  (for the report of 016 and the tests).
- After the stack was rebased onto 012 and its documentation was corrected, the results were measured again, so
  that their commit is in the branch's history.

**Note 2026-10-19 (rebase):** The Rust port moved from `rust/` to `generated/rust/`, whose folders mirror `system/`
(see "Scope-shift 2026-10-19" in [011's DECISION.md](../011-rust-store-foundation/DECISION.md)). The benchmark
program `rust/examples/store_benchmark.rs` is now `generated/rust/examples/benchmarks/workloads.rs`, generated from
`system/benchmarks/workloads.py` (and the fingerprints of `test_store_benchmark.py`); Cargo builds it as the example
`workloads` (user decision). The Python tests moved to `system/tests/benchmarks/`. The `rust/...` paths above are
the old paths, as they were when the decision was made.
