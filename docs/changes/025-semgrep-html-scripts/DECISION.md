# 025 — Semgrep scans the JavaScript in HTML files
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/189
---
## Context

The CI job `semgrep_sast` (feature 008) scans Python files and the code cells of notebooks. The pages in
`visualizations/` are single HTML files whose logic is an inline `<script>`. Semgrep applies only its HTML rules to
`.html` files: on MR !186 the job ran 9 HTML rules on such a page and no JavaScript rule on its script. Measured with
the pinned Semgrep 1.173.0, the rulesets `p/security-audit` and `p/javascript` together apply 83 JavaScript rules to
the two pages' scripts (`p/xss` adds none) and find nothing. Semgrep's experimental extract mode (`mode: extract`,
HTML to JavaScript), meant for exactly this, does not work in 1.173.0: the rule is treated as a plain search rule.

## Decision

- The job gets a step like the one for notebooks: the HTML files a merge request changes (deleted ones left out) are
  given to a small standard-library script, `.ci/html_scripts.py`, which writes the text of their inline JavaScript
  `<script>` elements to `.js` files, each at its original line and column, so that a finding's position is the one in
  the page. These files are scanned in full with `p/security-audit` and `p/javascript`, with `--error` (a finding
  fails the job) and `--strict` (so does code Semgrep cannot parse, or any other Semgrep warning for these files).
- What counts as JavaScript follows the HTML specification (the JavaScript MIME types, compared without case and
  surrounding spaces, `module`, an empty `type`, or no `type` and a JavaScript `language`); every inline script the
  step skips is listed in the log. The script stops with an error where its result could differ from what a browser
  runs: two scripts whose text would share a line, a `<script>` that is never closed, a self-closing `<script/>`.
- A changed page without inline JavaScript produces no file; the step then says so and scans nothing.
- A suppression is a comment line of its own that names a rule, `// nosemgrep: <rule-id>`; as for Python, only this
  one form is accepted, and every suppression is listed in the log together with the findings it hides.

## Consequences
**Positive:** A merge request that adds an insecure pattern to the JavaScript of a page (e.g. `eval` of the URL,
an unsafe `innerHTML`) fails, with the line in the page. No inline script drops out of the scan unnoticed.
**Negative:** Changed pages are scanned in full, so a new rule in the unpinned rulesets can fail a merge request that
changes an unrelated line of a page (as for notebooks). `--strict` widens this: a rule that times out on a page, or
a registry rule that 1.173.0 cannot load, fails every merge request that changes a page until the job is adapted.
JavaScript that is valid but that Semgrep cannot parse must be rewritten, or the job changed. The Semgrep options
now live in two job variables that must change together.

## Out of scope & deferred
- `p/javascript` in the diff-aware scan, for `.js` files in the repository (there are none).
- Inline event handlers (`onclick="..."`) and `javascript:` URLs, which are not extracted.
- `<script>` inside inline SVG: the browser decodes its CDATA and entities, the extraction does not, so Semgrep fails
  to parse it and the job fails visibly.
- A nightly full scan of all pages (deferred for Python in 008 as well).

## Alternatives rejected
- Semgrep's extract mode: does not work in Semgrep 1.173.0 (measured: no JavaScript rule runs on the script).
- Scanning the `.html` files directly: Semgrep applies only its HTML rules to them.
- Moving each page's script into a `.js` file in the repository: the pages are single self-contained files by design.
- Joining the script blocks without keeping their positions: findings would point to the wrong lines.
- Adding `p/xss`: it adds no rule beyond `p/security-audit` and `p/javascript` (measured).
- Adding `p/javascript` to the diff-aware scan instead of a separate one: the extracted files are not in git, and the
  page itself gets only HTML rules.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-28 (after the reviews of the first version):**
- The scan catches honest mistakes; like Semgrep's rules, it is no defence against code hidden on purpose. So the
  script guards only against cases an honest page can run into, and lists the deliberate tricks it does not catch
  in its docstring (e.g. hiding an `<svg>` from Python's parser), instead of following every corner of the HTML
  parsing rules. The Positive consequence "No inline script drops out of the scan unnoticed" holds for honest
  mistakes only; the gaps are listed in the script's docstring and in the `--strict` bullet below.
- Each script is written to a file of its own (`<page>.<n>.js`), as browsers run each on its own: in one file, an
  unclosed string or comment in one script could hide the next. This also drops the error for two scripts on one
  line.
- One general check replaces the separate checks of comments, declarations and `<!--` in scripts: every `<script`
  in the page must be a start tag that Python's parser read, or text inside a script; otherwise (e.g. in a comment,
  or in a `<style>` inside `<svg>`, which Python reads as plain text) the script stops with an error.
- A `<script>` that is never closed: browsers do not run it (the HTML standard marks it "already started" at the
  end of the page). The script still stops, as the page is broken; the Decision above gives the wrong reason.
- A `<script>` inside `<svg>` or `<math>` stops the script, as browsers may read or run it differently there:
  directly inside `<svg>`, they decode character references in its text, and Semgrep repairs the resulting syntax
  errors silently, so the case does not fail visibly as the section "Out of scope & deferred" assumes.
- `--strict` fails on the syntax errors Semgrep reports; Semgrep repairs some others silently (e.g.
  `let a = (1;`). A script with a real syntax error is no gap, as browsers do not run it; valid JavaScript that
  Semgrep cannot parse fully and repairs silently would be partly missed, and is not detected.
- An empty `.semgrepignore` in the output directory switches off Semgrep's default exclusions there; without it,
  a page in a folder such as `tests/` was written but not scanned, and the job passed (measured). The notebook step
  has the same gap; it is not changed here.
- A self-check scans a page with `eval(location.hash)` in a `tests/` folder, the same way as the real pages, and
  requires exit status 1, so that a scan that finds nothing even there fails the job. The file patterns match
  `.html` and `.htm` in any case.
- The two scans share their options in one variable, so the "two job variables" of the Consequences no longer
  apply.

**Note 2026-10-28 (verified in CI):** the step behaves as designed on throwaway commits on top of the merge request
(each dropped again; the self-check found its 1 finding every time):
- `eval(location.hash)` added to `visualizations/validation-interval-to-point.html`: red, finding
  `detect-eval-with-expression` on line 178 of the page (https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/558017).
- A bare `// nosemgrep`: red, listed and rejected (https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/558034).
- `// nosemgrep: <rule>` above `eval(location.hash)`: green, with the suppression and the finding it hides listed
  (https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/558037).
- Only `benchmarks/index.html` changed, which has no inline JavaScript: green, "No inline JavaScript in the changed
  HTML pages." (https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/558053).
