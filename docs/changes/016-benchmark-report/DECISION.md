# 016 — HTML report of the store benchmarks
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/149
---
## Context

015 measures the MVCC store in Python and in Rust and writes `benchmarks/results.json`. Its decision record left
the presentation to this merge request: a self-contained static page without JavaScript, charts as SVG with real
text, light and dark, text alternatives and a table, a text on what is measured and on the fairness of the
comparison, meant for another web site than the project's GitLab Pages. The user chose an English, standalone page.
The GitLab project needs a login, so readers of the other site cannot follow links into it.

## Decision

- **Generator** in two modules under `system/benchmarks/`: one draws the charts as SVG, the other reads
  `results.json`, checks it and writes `benchmarks/index.html` (generated and checked in), run as
  `python -m system.benchmarks.report`. It is separate from the runner, so the page can be re-rendered without
  measuring again; the runner names the command after a full run.
- **Only full runs.** The report accepts exactly the 18 configs of a full run, each measured in both languages with
  the same fingerprint, the expected number of repetitions and finite, positive times; anything else (e.g. a quick
  run) is rejected with a message.
- **Hand-written SVG** instead of matplotlib: the charts are simple, and matplotlib's SVG would need cleaning before
  it can be inlined several times (repeated ids, XML declaration, metadata with external links), writes log-axis
  labels as positioned glyphs instead of text, and its output may differ between macOS and the Linux CI image. The
  module formats every number itself, so the page is identical on every machine.
- **One SVG per chart, light and dark via CSS** (user decision, instead of one rendering per theme): the elements
  carry classes whose colours the page sets for light and dark mode, and printing is always light. Python and Rust
  differ by colour and by shape or label. Every SVG has a title and a short description; the table holds all
  numbers.
- **Charts:** four small charts of the micro-benchmarks (time per operation over the store size, log-log, one shared
  time axis); transactions per second on 1 000 objects for both validation methods as horizontal bars on a linear
  axis with the value written at every bar (user decision); the speed-up of Rust over Python for all 18 configs.
  Times in ns, µs or ms with three significant digits.
- **Page:** summary, what is measured, the charts, the full table, fairness, machine and git commit, how to
  reproduce; readable on a 360 px phone; no external resources and no links outside the page.
- **Up to date:** a test regenerates the page from the committed results and compares it byte for byte with the
  committed page.

## Consequences
**Positive:** The results can be put on another web site as one file that works offline, in light and dark mode,
for screen readers and on phones. CI notices when the results and the page do not match.
**Negative:** A small SVG writer is project code to maintain; overlapping labels or wrong colours are not caught by
tests and need a look in the browsers. On the linear axis the Python bars are short (1–8 % of the Rust bars) and
are read from their numbers. Each new measurement changes the checked-in page.

## Out of scope & deferred
- Publishing the page on the other web site (manual upload).
- Interactive charts (would need JavaScript).
- Results of several machines on one page, or a history over commits.
- Rust variants (value enum, closure predicates) and the indexed store (step 2) in the report.

## Alternatives rejected
- **matplotlib SVG:** see Decision; more cleaning than drawing the simple charts directly.
- **Two SVGs per chart, one per theme** (015's wording): duplicate content and a hidden copy; CSS gives the same
  result with one SVG.
- **JavaScript chart libraries (Chart.js, Vega):** need JavaScript and usually a CDN.
- **A template engine (Jinja2):** a new dependency for one page; the standard library's `string.Template` suffices.
- **Rendering inside the runner:** re-rendering would require re-measuring.
- **PNG images:** blurry when zoomed; text neither selectable nor readable by screen readers.
- **A logarithmic axis for transactions per second:** bar lengths would not be proportional to the values (user
  decision for linear).

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-16 (review of the MR stack):**
- Two further user decisions: the page declares a Content Security Policy (no scripts, no other files), and the
  provenance of a run is a typed `Provenance`, shared by the runner and the report; the JSON format is unchanged.
- With the committed results, the Python bars of the transactions chart are about 2–4 % of the Rust bars.
- The page's text takes the numbers of reads, transactions, pairs, store sizes and repetitions from the results.

**Note 2026-10-19 (rebase):** The Rust port moved from `rust/` to `generated/rust/` (see "Scope-shift 2026-10-19"
in [011's DECISION.md](../011-rust-store-foundation/DECISION.md)), and the tests of the benchmarks, together with
the HTML parser of the report tests (`page_parser.py`), moved from `system/tests/` to `system/tests/benchmarks/`.

**Note 2026-10-19 (review of the rebase):** Every drawn element of the charts (texts, lines, bars, markers, the
lines through the medians) carries a `data-testid` that names its kind, e.g. `marker-python`, `bar-rust`, `grid`,
`y-tick` or `bar-label`, and the tests select chart elements by it only, not by CSS class or text (user decision);
a test checks that no drawn element lacks one. The page grows from about 39 KB to 46 KB.
