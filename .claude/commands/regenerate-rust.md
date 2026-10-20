Keep the generated Rust port in generated/rust/ up to date with the Python code in system/, or port a new part of it.

Rules for the Rust code: the tables in `generated/rust/README.md` and the section "Rust code" of `CONTRIBUTING.md`.
Run `.ci/check_generated.py` with `python3` from the repository root.

## Stop rules (at every step)

- **A design decision the design does not name** (a new type, enum, error variant, deviation or crate, a Cargo
  change, a deleted Python source): no `.ci/check_generated.py --update`. On `chore/`: discard that branch and its
  changes, switch to `main` and go on with step 3. On a `feat/` branch: run `/design` there again.
- **A Cargo change or a new line in `ALLOWED_LINES`** of `.ci/check_generated.py`: only if the design names it. Show
  it to the user; on their yes, record a Cargo change with `.ci/check_generated.py --update-dependencies`, or add the
  line as the check shows it (change nothing else in that file).
- **Anything else unexpected** (a dangerous construct not covered above, a report about the copies, a refusal of the
  update, a check report other than those step 5 names): stop and ask the user.

## Step 1: Start

If the working tree is not clean, stop and ask. Otherwise switch to `main`, pull, and run the check.

- Only "out of date" reports: step 2 (a new part only in a later run, from a clean check).
- A clean check: ask which part of the Python code to port, unless the user said so; then step 3, or stop.
- Any other report: stop and ask the user.

## Step 2: Keep up to date

Create `chore/regenerate-rust-<topic>`. Run `.ci/check_generated.py --diff` and keep its output in a file outside the
repository. Classify each change for each Rust file its heading names: **port** (ported code, its comments and
docstrings included), **nothing to port** (only parts not ported: leave that Rust file unchanged, the update records
it) or a design decision. A test name only in `+` lines gets a Rust test and a README row; one only in `-` lines
loses both; where a README row already covers the test's file ("all tests not listed below", "not ported"), follow
it. Then step 4.

## Step 3: Port a new part

Run `/design` from `main`; the design names the Rust types, the Python tests to translate, the README rows, and any
Cargo change or allowed line, and takes in a kept `--diff` output and classification. `/develop` implements it on its
branch: tests are translated from the named Python tests, `test-writer` adds only Rust-only tests. Each of its phases
ends with steps 4–5; its `/finish-feature` is step 6.

## Step 4: Translate

Change the Rust files with a change to port, or create the new ones at the mirrored place, and where needed the
files without a Python source (README, `src/lib.rs`, mod files, `tests/*/main.rs`).

## Step 5: Check, build, record

1. Run the check. During a run, "out of date", "not in the manifest" and "edited by hand" are expected; fix your own
   slips (e.g. a missing first line or `mod` line).
2. In `generated/rust/`: `cargo fmt`, then the four checks of `CONTRIBUTING.md` "Rust code". Fix the Rust code; no
   `#[allow]`, no weaker flags.
3. Run `.ci/check_generated.py --update`, commit and push.

## Step 6: Finish

Run `/finish-feature`. Give the code reviewer the kept `--diff` output with your classification (step 2) and the
design (step 3), where they exist, to check every change, the Rust files left unchanged included. Open the MR with
`glab mr create --assignee @me` (instead of the link `/finish-feature` names); put its link into the design's
`DECISION.md`, if there is one, then commit and push. After any fix, repeat step 5.
