# Contributing to ExplainDB

## Code formatting

All Python code is formatted with [black](https://black.readthedocs.io) using its
default settings. The CI pipeline runs `black --check .` and rejects unformatted
code, so run `black .` before every push.

## Tests

The unit tests live in `system/tests/`, whose folders mirror the packages of `system/`: the tests of
`system/stores/` are in `system/tests/stores/`, and the tests of modules directly in `system/` (e.g.
`system/DBMS.py`) are directly in `system/tests/`. Tests that check the repository itself (CI configuration,
notebooks and the README, the Javadoc hook of the API documentation in `docs/api/javadoc.py`, the pages in
`visualizations/`) are in `system/tests/repo/`. Every test folder below `system/tests/` needs an `__init__.py`;
without it, `unittest discover` silently skips its tests. Run all tests with:

```sh
uv run python -m unittest discover system/tests/
```

## Dependencies

Dependencies are managed with [uv](https://docs.astral.sh/uv/) in `pyproject.toml`
and `uv.lock`. mybinder.org cannot read `uv.lock`, so `.binder/requirements.txt` is
an export of it. After every dependency change, regenerate it (the CI job
`binder_requirements` fails if you forget):

```sh
uv export --frozen --no-dev --no-hashes --no-header --no-annotate --format requirements.txt -o .binder/requirements.txt
```

The dependency group `browser-tests` in `pyproject.toml` holds what only the browser test of the
pages in `visualizations/` and the tool that turns them into videos need (see
[Visualizations](#visualizations)). `uv sync` does not install it, and the export above leaves it
out, so it does not reach Binder; the dependency audit below covers it.

### Security audit

The CI job `dependency_audit` runs [pip-audit](https://pypi.org/project/pip-audit/) on
the versions pinned in `uv.lock` and fails if any of them has a known vulnerability.
To fix a finding, move the affected package to a fixed version:

- If the package is an indirect dependency (not listed in `pyproject.toml`), run
  `uv lock --upgrade-package <package>`.
- If it is listed in `pyproject.toml` with an exact `==` pin, raise the pin there and
  run `uv lock`. Do the same if such a pin prevents an indirect dependency from moving
  to its fixed version.

Then regenerate `.binder/requirements.txt` with the command above. To reproduce the
check locally, run the `uv export` and `uv tool run` commands of the `dependency_audit`
job in `.gitlab-ci.yml`.

If no fixed version exists yet, or the finding is a false positive, append
`--ignore-vuln <ID>` to the pip-audit command in that job, where `<ID>` is the
vulnerability ID from the job log (for example `GHSA-…` or `PYSEC-…`). Put a comment
above the command giving the reason and the date, and remove the entry again as soon
as a fixed version is available. (A failing job blocks merging because the GitLab project
setting "Pipelines must succeed" is enabled.)

The CI job `rust_dependency_audit` does the same for the Rust code: it runs
[cargo-audit](https://crates.io/crates/cargo-audit) on the versions pinned in
`generated/rust/Cargo.lock` and fails if any of them has a known vulnerability in the
[RustSec advisory database](https://rustsec.org). Crates that are unmaintained (no longer
looked after) or unsound (can break Rust's memory safety when used in a certain way) are only
reported as warnings; yanked crates (withdrawn by their authors on crates.io) are not checked.
To fix a finding (the `cargo` commands run in `generated/rust/`): a dependency update is the one change
made directly in `generated/rust/`, in `Cargo.toml`, `Cargo.lock` and `rust-toolchain.toml`.

- For an indirect dependency, run `cargo update -p <crate>`; if `Cargo.lock` holds two
  versions of the crate, name the affected one: `cargo update -p <crate>@<version>`. If the
  fixed version is a new major version that the crate depending on it does not accept yet,
  update that crate instead.
- For a direct dependency, raise its version in `generated/rust/Cargo.toml`, then run
  `cargo update -p <crate>`.
- Finally, run `python3 .ci/check_generated.py --update-dependencies` from the repository root, so
  that the manifest `generated/rust/GENERATED_FROM.json` records the new hashes of these three files
  (and only of them). Otherwise `generated_rust_check` reports them as edited by hand and fails on
  main.

If no fixed version exists yet, or the finding is a false positive, append `--ignore <ID>`
(e.g. `--ignore RUSTSEC-2024-0001`) to the cargo-audit command in that job, with a comment
giving the reason and the date, and remove it again as soon as a fix is available. Besides
`--ignore <ID>`, the command may only take `--no-yanked`, `--file` with the lockfile and
`-D`/`--deny <kind>` (which makes it stricter); reviewers watch for any other option, as options
such as `--target-os`, `--url`, `--db` or `--no-fetch` can hide advisories, and
`system/tests/repo/test_ci_config.py` fails on them. Do not add a `.cargo/audit.toml` instead:
the job does not read it and fails if one exists, so that every ignored advisory is visible in
the job. If the job fails because cargo-audit cannot read the advisory database (a parse error,
not a finding), raise `CARGO_AUDIT_VERSION` and `CARGO_AUDIT_SHA256` in the job; the checksum is
listed on GitHub with the release asset `cargo-audit-x86_64-unknown-linux-musl-v<version>.tgz`.

To reproduce the check locally, install the version of `CARGO_AUDIT_VERSION` in the job and
run it from the repository root as below (add the job's `--ignore` options, if any):
cargo-audit then runs in an empty directory with an empty `CARGO_HOME`, so that, as in the
job, no `audit.toml` (of the repository, a shared `/tmp` or your own configuration) is read:

```sh
cargo install cargo-audit --version 0.22.2 --locked
( repo="$PWD"; cd "$(mktemp -d)" && CARGO_HOME="$(mktemp -d)" cargo-audit audit --no-yanked --file "$repo/generated/rust/Cargo.lock" )
```

## Security checks

Besides the dependency audit above, the CI scans every merge request for secrets and for
insecure code patterns.

### Secret detection

The CI job `gitleaks_secret_detection` runs [Gitleaks](https://github.com/gitleaks/gitleaks)
on the commits of a merge request (not on older commits) and fails if one of them adds a
secret, such as a password, an API token or a private key. The job log lists each finding
with its file, line, rule and fingerprint, with the secret itself replaced by `REDACTED`;
the job's artifact `gitleaks-report.json` holds the same.

If a real secret was committed:

1. Revoke or replace it right away and treat it as public: it may already have been copied,
   and older versions of the merge request still show it.
2. Remove it from the commit that added it, e.g. with `git rebase -i`, and force-push the
   branch; removing it in a later commit is not enough, as the job scans every commit.
3. Tell a project owner: until they redact the secret from the repository (Settings > Repository >
   Repository maintenance > Redact text) or delete the merge request, the old commit stays visible
   by its ID and in the merge request's older versions.

If a finding is a false positive, accept it in one of two ways:

- add the comment `gitleaks:allow` on the same line (e.g. `# gitleaks:allow` in Python), in the
  commit that adds the line (amend or rewrite that commit; a later commit does not change the
  earlier one), or
- add the finding's `Fingerprint` from `gitleaks-report.json` as a line to the file
  `.gitleaksignore` in the repository root. The fingerprint contains the commit ID, so after
  a rebase, amend or squash, take the new fingerprint from the new report. (For a file that had
  a merge conflict, the path in the fingerprint starts with `b/`; copy it as it is.) Reviewers
  accept only entries that start with a commit ID: Gitleaks also accepts the short form
  `path:rule:line`, but that would hide every later secret at that place, too.

Reviewers check every new `gitleaks:allow` comment and `.gitleaksignore` entry. The job fails
on a merge of three or more branches ("octopus" merge), which it cannot scan; use normal merges
instead.

To run the check locally with [Gitleaks installed](https://github.com/gitleaks/gitleaks#installing)
and git 2.42 or newer, update `origin/main` (or the merge request's target branch) and scan the
commits that are not yet on it. Like the CI job, the commands use only Gitleaks' default rules and
ignore a `.gitleaks.toml` and the `.gitattributes` in the repository (`GIT_ATTR_SOURCE` points
to git's empty tree, a fixed ID that git uses for an empty directory):

```sh
git fetch origin
printf '[extend]\nuseDefault = true\n' > /tmp/gitleaks.toml
GIT_ATTR_SOURCE=4b825dc642cb6eb9a060e54bf8d69288fbee4904 gitleaks git . --log-opts="--remerge-diff origin/main..HEAD" --config /tmp/gitleaks.toml --redact --verbose
```

### Static analysis

The CI job `semgrep_sast` runs [Semgrep](https://semgrep.dev) with the rulesets
`p/security-audit` and `p/python` (`p/javascript` for HTML pages, see below) and fails if the
merge request introduces a new finding, e.g. a call of `eval` or `pickle.load`, which can run
arbitrary code on untrusted input.
Findings in older code do not fail the job. The job log lists each finding with its file,
line and rule. Code in `tests/` folders is not scanned (except the inline JavaScript of HTML
pages, see below), and the job is skipped when a merge request only changes Markdown.

Semgrep cannot read notebooks, so the job writes the code cells of every notebook the merge
request changes to a Python file (`.ci/notebook_code.py`) and scans these in full: a finding
anywhere in a changed notebook fails the job, not only a new one. IPython syntax is turned into
Python first, keeping the Python code it runs (e.g. after `%time` or in a `%%time` cell). If
the result is still not valid Python, the job fails, as Semgrep would skip that code; the log
then names the notebook and shows the line that could not be read. For a finding, the log
names `/tmp/notebook_code/<path of the notebook>.py` and a line in that file; search the
notebook for the code shown in the log.

The code after `%timeit -s` and the bodies of cell magics such as `%%writefile` or
`%%script python3` are not scanned. A finding in `{...}` of a shell command or magic cannot be
suppressed, and a comment line above `%%timeit` makes the conversion fail; rewrite such code
as plain Python instead.

Semgrep applies only its HTML rules to HTML pages, so the job also writes each inline
JavaScript `<script>` of every HTML page the merge request changes to a file of its own
(`.ci/html_scripts.py`) and scans these in full with `p/security-audit` and `p/javascript`, also
in folders such as `tests/`. Each script keeps its line and column, so for a finding the log
names `/tmp/html_scripts/<path of the page>.<n>.js` (the n-th script) and a line that is the
same line in the page. Scripts with `src` or a type that is not JavaScript (e.g.
`application/json`) are not scanned; the log lists them. Where Python's parser could read a page
differently from a browser (e.g. `<script` in a comment, or a script inside `<svg>`), the job
fails and the log names the page, the line and what to change. The scan also fails on any
warning of Semgrep, e.g. on JavaScript it cannot parse; if that JavaScript is valid, rewrite it,
or change the job in a merge request of its own. The scan catches honest mistakes, not code
hidden on purpose. Inline event handlers (`onclick="..."`), `javascript:` URLs and
`<iframe srcdoc="...">` are not scanned.

If the code is wrong, fix it. If it is intentional (as `eval` and `pickle` in the teaching
code of `system/` and of some notebooks), add `# nosemgrep: <rule>` on the line before the
finding, in the same file or notebook cell, with the rule ID from the job log, and above it a
comment that says why the code is safe:

```python
# the file was written by this program itself, so unpickling it is safe here:
# nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
for tup in pickle.load(f):
```

In the JavaScript of an HTML page, the suppression has the same form with `//`:
`// nosemgrep: <rule>` on a line of its own.

The job lists every added suppression in its log (for a changed notebook or HTML page: all of
its suppressions), and reviewers check each one. A suppression is any line that contains `nosem`
in any case, as Semgrep reads it: also with a letter that Unicode case folding turns into one of
its letters, such as the long s `ſ`, and also after a NUL byte (`.ci/suppressions.py` finds them).
Below that list the job shows all findings, including those the suppressions hide. It fails if a
suppression is not a comment line of its own in exactly this form (e.g. a bare `nosemgrep`
without a rule, one at the end of a line of code, or one in capitals, with a `ſ` or with a NUL
byte). It also fails if the merge request adds or changes a `.semgrepignore`, or changes a file
that matches a `.gitignore`, as both would remove files from the scan. Suppressions are checked
in Python files, notebooks and the inline JavaScript of HTML pages only, not in other files
Semgrep scans (e.g. YAML, or a `<!-- nosemgrep -->` in HTML).

Semgrep has no rule set for Rust enabled, and its suppressions are not checked in `.rs` files:
the Rust code in [`generated/rust/`](generated/rust) is hardly scanned. This gap is accepted for now (see
[`docs/changes/011-rust-store-foundation`](docs/changes/011-rust-store-foundation/DECISION.md)).

To run the check locally, scan the changes that are not yet on `main`, then the notebooks and
HTML pages you changed:

```sh
git fetch origin
uv tool run --from semgrep==1.173.0 semgrep scan --metrics=off --config p/security-audit --config p/python --baseline-commit "$(git merge-base origin/main HEAD)"
rm -rf /tmp/notebook_code
uv run python .ci/notebook_code.py /tmp/notebook_code notebooks/<notebook>.ipynb
uv tool run --from semgrep==1.173.0 semgrep scan --metrics=off --config p/security-audit --config p/python /tmp/notebook_code
rm -rf /tmp/html_scripts
uv run python .ci/html_scripts.py /tmp/html_scripts visualizations/<page>.html
touch /tmp/html_scripts/.semgrepignore
uv tool run --from semgrep==1.173.0 semgrep scan --metrics=off --config p/security-audit --config p/javascript --error --strict /tmp/html_scripts
```

## Notebooks

The notebooks live in `notebooks/`. When you add, rename or remove one, also update:

- the notebook table in the README (section *Notebooks*): one row with the link, a
  one-line topic and the Binder badge. `system/tests/repo/test_readme_notebooks.py` fails if
  the table and `notebooks/` disagree.
- the line `Notebook: [<name>](notebooks/<name>.ipynb)` and its Binder badge in the README
  section *Visualizations*, if a page links the notebook.
  `system/tests/repo/test_readme_visualizations.py` fails if the linked notebook does not exist.
- `.ci/notebook_weights.tsv` (the notebook's run time, used to balance the parallel CI
  jobs) and the expected packing and notebook count in
  `system/tests/repo/test_assign_notebooks.py`, which fails otherwise.

## Visualizations

The pages in `visualizations/` are single HTML files with inline JavaScript; they load nothing
from the network, so they also work offline. Each page carries a Content-Security-Policy, a
`<meta http-equiv="Content-Security-Policy">` line right after `<meta charset="utf-8">`. With it the
reader's browser itself blocks every load from the network (the line and its rules are explained in
[`docs/changes/030-visualizations-csp`](docs/changes/030-visualizations-csp/DECISION.md)).
`system/tests/repo/test_visualizations.py` opens
each page in a headless Chromium, driven by [Playwright](https://playwright.dev/python/), and uses
its controls the way a reader does. The tests fail if a page's script throws an error or logs one
to the console, if a control does not work, or if the page requests anything but a local file.
The CI job `visualization_test` runs them in every merge request that changes a page, the test,
`.gitlab-ci.yml`, `pyproject.toml` or `uv.lock`.

The tests find elements only by their `data-testid` and read the state of a page mainly from `data-*`
attributes that its script sets. Some tests run on every page in the folder and its subfolders, so a
new page needs these elements as well:

| `data-testid` | Element | State the script sets |
| --- | --- | --- |
| `play` | the Play/Pause button | `data-state`: `paused`, `playing` or `ended` |
| `next` | the Next button, which jumps to the next stop | |
| `scrub` | the slider, from 0 to 1000 | its value |
| `narration` | the text that explains the current step | `data-stop-type`: `start` at the start, `end` at the end |

The README links to each page with an absolute link to htmlpreview.github.io, which shows the page
instead of its source code. GitLab opens such a link in a new tab, as it adds `target="_blank"` to
every link to another site (checked on 2026-11-01 with GitLab's Markdown API). GitHub's renderer
drops `target` attributes, so on the GitHub mirror the link opens in the same tab. The README
therefore needs no HTML links to force a new tab.

In the README's section *Visualizations*, each page has a subsection: a heading with its path in
`visualizations/` without `.html` (for a page directly in the folder, its file name), which links to
the page, a preview 480 pixels wide, which links to the page as well, the topic, and, if there is one,
the line `Notebook: [<name>](notebooks/<name>.ipynb)` with the notebook's Binder badge on the next
line, written as in the notebook tables. `system/tests/repo/test_readme_visualizations.py` fails if
the section, the pages, the previews and the notebooks disagree. The section has no table: GitLab
shows a Markdown table at most 70 % of the window high and lets a higher one scroll inside itself. The
preview is written as
`[<img src="docs/images/visualizations/<page>.jpg" width="480" alt="…">](<link>)`: an HTML image, as
Markdown's image syntax cannot set a width on GitHub, inside a Markdown link, and an alt text that
says what the picture shows. The preview is a screenshot of 960×540 pixels, twice its width on the
screen. It is taken in Chrome at a viewport of 1280×720 with device scale 2 and reduced motion, at a
moment that shows what the page is about, then shrunk to 960×540 and saved with JPEG quality 85 (about
45 to 110 KB). A new page needs a preview as well, and a page whose look changes needs a new one.

Playwright is in the dependency group `browser-tests`, which `uv sync` does not install; without
it, the tests are skipped. The tests of `tools/render_video.py` also need ffmpeg with ffprobe on the
PATH. To run them locally:

```sh
uv run --group browser-tests python -m playwright install --only-shell chromium
uv run --group browser-tests python -m unittest -v system.tests.repo.test_visualizations system.tests.repo.test_render_video
```

On Linux, add `--with-deps` to the install command: it installs the system libraries Chromium
needs (as root). A later `uv sync` without `--group browser-tests` removes the group again.

### What a new page has

A new page follows these rules, so that a reader who knows one page can use the next. The House DBMS
page (`call-through-dbms.html`) follows all of them. Older pages differ in some points, which a new
page should not copy; the main ones are listed under [Where older pages differ](#where-older-pages-differ).
The tests that run on every page (`EveryPageTest` in `system/tests/repo/test_visualizations.py`) use only
the elements in the table above: they check how Play, Next and the slider behave, autoplay, script errors
and network requests. On a page with a sound button, the tests in `EveryPageWithSoundTest` check how its
sound button and voice behave (not the line at the end that names the voice). A page that speaks is listed
in `PAGES_WITH_SOUND`, so that they fail if it loses its button, and, if its film has parts, in
`PAGES_WITH_PARTS` as well, as they expect the part buttons (`chapter-1`, …) exactly on the pages listed
there. At least one of its captions must begin with a clip of 4.5 s or more (`test_voice_follows_the_film`
needs it), no two captions may have the same text, and its clock reads exactly `m:ss / m:ss`. As the tests
wait at most 15 s for the film to reach a moment (`FILM_TIMEOUT`), its first caption begins a moment after
the start of the film but within a few seconds of it, the second within about ten seconds of the first,
and the clip of the first caption lasts more than 1.5 s (`test_a_jump_back_drops_the_clip`); the film
lasts at most about four minutes. The other rules are checked by the author and the reviewers.

The words used here: a page plays a *film* from its start to its end. A longer film is cut into
*parts*, e.g. the four orders (queries) of the House DBMS page; the test ids of the part buttons call
them chapters. A *step* is a scene of the film with its own name in the header. The narration says one
*caption*, a sentence or two, at a time. A *stop* is the moment when a caption has been said in full,
just before it fades out: Next jumps from stop to stop, so that each click shows the picture with a
whole caption under it. A page may also *speak* its narration: each caption then has a *clip*, a
recording of a synthetic voice. A caption may be said in *segments*, each from its own time and with a
clip of its own (on the row/column page); these are not the segments of the slider.

- **One file, offline:** as described at the start of *Visualizations*. Fonts are embedded in the page as
  `data:` URLs, with their license in a comment, or are the fonts of the reader's system; a page never
  loads a font from the network (e.g. from Google Fonts).
- **Links:** no link to a lecture video; a link to a notebook is fine.
- **No HTML from strings:** the script never turns text into markup, so no `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `document.write` or the like. It sets text with `textContent` and builds
  elements with `createElement`. That way no text, e.g. from a URL parameter, can put code into the
  page.
- **Playback time:** what the page shows depends only on the playback time. Each frame is drawn from
  that time alone, never from the frame before, so that the slider, Next and `t=` can jump to any
  moment. A paused page draws nothing until something changes (e.g. the size of the window), and the
  script writes into the page only values that have changed, so that it does not redraw everything
  60 times a second for nothing.
- **Layout:** the picture fills the window. The header names the page and the current step (e.g.
  `01/07 · The query` on the row/column page, `row-or-column.html`). Along the bottom edge run the
  narration and, below it, the controls.
- **The name ExplainDB:** the header begins with `ExplainDB ·`, in the header's own style (e.g.
  `ExplainDB · The House DBMS · lecture 03, slide 10 · 01/13 · Slide 10 becomes a house`), and the
  card at the end closes with the line `ExplainDB · github.com/explaindb/explaindb` (`credit`), whose
  address is a link that opens in a new tab (`credit-link`). A page may also show the name in its
  scene where it fits the picture, e.g. as the maker's name on a clock or as a stamp on a parcel;
  never in green, which marks results.
- **Controls:** from left to right, the part buttons (only if the film has parts), Play/Pause
  (`play`), Next (`next`), the slider (`scrub`), the clock (`clock`, e.g. `0:42 / 2:38`), the sound
  button (`sound`; only on a page that speaks), and full screen (`fullscreen`). They form one row, which
  may wrap onto a second one on a narrow window. Play, Next, sound and full screen are round buttons with
  an icon. For screen readers, each has an `aria-label` that names it; its `title`, shown when the
  pointer rests on it, names its key, e.g. "Next step (→)". All controls are disabled in the HTML until
  the script has set them up, so that no click is lost while the page loads. There is no Back and no
  Restart button; at the end, Play starts again from the beginning.
- **Next:** pauses and jumps to the next stop; after the last stop, to the end. While the voice of a
  page that speaks may speak (see *Voice*), Next and ← stop where a caption begins instead, and Play
  speaks it.
- **Slider:** it follows the playback, and moving it pauses the page. If the film has parts, the
  slider is cut into one segment per part (`segment-1`, …), each as long as its part, with gaps
  between them, like the chapters of a video; what has been played is green. When the pointer is over
  such a slider, a tip (`scrub-tip`) above it shows the name of the part and the time at that point. A
  button per part (`chapter-1`, …) jumps to the start of that part and plays from there. The button
  of the part on screen is outlined in green; for screen readers, it is marked with `aria-current`.
- **Keys:** Space plays and pauses wherever the focus is (the control last clicked or reached with
  Tab). When a button other than Play has the focus, Space does not click it, not even when held down;
  on Play itself, the browser's own click plays and pauses. The → key does the same as Next, and ←
  pauses and jumps back to the stop before, or to the start; on the slider, the arrow keys move the
  slider instead. F switches full screen on and off, also on the slider; on a page that speaks, M
  switches the sound on and off. Apart from that, keys held down or pressed with Alt, Ctrl or Cmd are
  left to the browser (e.g. Alt+← for the previous page, Ctrl+F to search).
- **Full screen:** the button switches the whole page to full screen and back. Browsers that cannot
  show a page in full screen (e.g. Safari on the iPhone) do not show the button.
- **Narration:** shown word by word, as if spoken: the words said are white, the current one is
  underlined, the words still to come are dim, and green marks a word that names a result. Each
  caption fades in and out. The narration has `aria-live="polite"`, so that a screen reader reads it
  out; its words are put in only when the caption changes, so that the screen reader reads each
  caption once. On a page that speaks, this holds while the sound is off or held back by the browser
  (see *Voice*).
- **Voice:** a page may speak its narration with a synthetic voice
  ([decision 034](docs/changes/034-narration-voice/DECISION.md); e.g. the clock-scan page,
  `clock-scan.html`). Each caption has a clip (a caption said in segments, as on the row/column page, has
  one per segment), embedded as an MP3 `data:` URL (mono, at a constant 48 or 64 kbit/s; at 48 kbit/s the
  voice adds about 0.5 MB to the page per minute of speech, 0.3 to 0.8 MB on the four pages that speak),
  which the page's Content-Security-Policy allows with `media-src data:` (see the note at the end of
  decision 030). Its words light up at the moments the voice says them, so that the subtitles keep the
  voice's pace also with sound off. Sound is off at load, as browsers allow sound only after a click or
  key press: the narration shows as subtitles, with the hint "Switch on audio (M)" (`sound-hint`). The
  sound button (a speaker, crossed out while the sound is off; title "Sound: synthetic voice (M)") and M
  switch the sound on and off. The voice *may speak* while the sound is on and the browser does not hold
  it back; then the narration and the hint are hidden, and the narration's `aria-live` is `off`, so that a
  screen reader does not speak at the same time. A browser that holds the sound back gets the hint
  "Click or press a key for sound", and the reader's next click or key press lets the voice speak; if the
  browser refuses it even after the sound button or M, the sound goes back off. The page's own clock
  drives the film, and the voice follows it. A clip begins with 0.4 s of silence, so that a browser that
  starts it late does not swallow the first syllable, and must end by its caption's stop (a segment's clip
  by the start of its caption's next segment, if there is one; no clip after the end of the film); a
  longer clip plays faster, at most 1.15 times (if a clip would need more, the page's script stops with an
  error at start-up, which the tests report). Pause holds the clip; Next, ←, the slider and the part
  buttons drop it. A pause from outside the page (e.g. media keys) pauses the film, and so does hiding the
  tab while sound is on; a play from outside is undone while the film is paused, and lets a held-back
  voice speak while the film plays. At the end, the page shows in writing that the voice is synthetic and
  names its model and voice (on the House DBMS page at the end of the `credit` line, on the clock-scan
  page in the card above it); a comment above the clips names the model, its license (MIT) and how the
  clips were made, and the README says that the page speaks, in its subsection of *Visualizations* and in
  the section *License*. The voice's code is the same on the four pages that speak; a new page takes it
  over. The clips are made outside the repository, as decision 034 describes: every new take is checked
  with a speech recogniser for misspoken or cut words and listened to before it goes into the page.
- **Fast passages:** while the film runs faster than normal, a badge `▶▶ ×4` (`fast-forward`) says
  so. On the House DBMS page, these are the ways through the house that the film has already shown
  once.
- **At the end:** a card sums up what the picture showed and stays until the end (the legend on the
  House DBMS page).
- **Nothing passes through anything:** a robot, a carried thing or anything else that moves never
  goes through a wall, a floor, a piece of furniture or another thing, not even through a thing that
  stands still at that moment (e.g. a parked cart). Touching is fine, overlapping is not: a box lies
  on a table, a robot holds a paper. Check this yourself before you open the merge request, with a
  small script. The page's code runs inside one function, so a script typed into the browser's console
  cannot reach it: pause at a breakpoint inside the page's script (e.g. in the function that draws a
  frame), so that the console runs there, or add a line that hands the scene and the film to
  `window` for the check and remove it again. Since each frame depends only on the playback time, the
  script can place everything for a time t without drawing it (on the House DBMS page:
  `film.motion.apply(t)`, then `scene.updateMatrixWorld()`) and go through the film at short
  intervals. At each time, test the box of each shown mesh that moves (not of the group it belongs to;
  skip meshes that are hidden, also through a hidden parent) against the boxes of the shown meshes that
  do not move and of the other shown meshes that move; count only an overlap deeper than a small
  tolerance, so that touching does not count. Make the interval so short that between two checks
  nothing moves further, relative to the thing it could pass through, than the two are thick
  together (each measured in the direction of the movement), less twice the tolerance; also in fast
  passages. Read every hit, list the contacts that are meant, run the check
  again whenever the motion changes, and say in the merge request how you checked and with which
  tolerance.
- **Start-up:** the controls answer clicks within a moment of loading, also on a GPU that the browser
  emulates in software, as in the tests, which give each action 5 s. Such a GPU finishes a shader
  program only when it first draws with it, so a 3D page with many materials prepares its programs and
  textures before the first picture, a few per frame, as the House DBMS page does, and marks the end of
  this with `data-ready` on the picture.
- **Autoplay:** unless the browser asks for reduced motion or a URL parameter (below) says otherwise,
  a page starts playing on its own shortly after it has loaded; any control except full screen and the
  sound button (and M) cancels that start. The tests ask for reduced motion (except the test of
  autoplay itself), so that they start from a paused page; reduced motion changes nothing else, so that
  the tests see the frames a reader sees (on a software GPU, after the start-up).
- **URL parameters:** `t=<seconds>` starts at that time, `paused` keeps the page from starting on its
  own, and, if the film has parts, `q=<n>` starts at part n; e.g. `?q=3&paused`. The page reads `t` as
  a number and keeps it within the length of the film, accepts `q` only if it names one of the parts
  (and then ignores `t`), and never writes a parameter into the page.
- **Test ids:** every control, and every element that shows a value (e.g. the clock or a counter),
  has a `data-testid`; those in the table above are needed on every page. The script also writes state
  for tests into `data-*` attributes, e.g. `data-scene` (the number of the step, `1` … `13` on the
  House DBMS page) and `data-ready` (see Start-up) on the picture (`stage`), and `data-active` (`true` or
  `false`) on the fast-forward badge. A page that speaks also has the audio element (`voice`), the two
  icons of the sound button (`sound-icon-on`, `sound-icon-off`) and the text of the narration
  (`nar-text`), with the state `data-voice="playing"` on the picture while the voice plays,
  `aria-pressed` (`true` or `false`) and `data-blocked` (empty, set only while the browser holds the
  sound back) on the sound button, and `data-voiced` (empty, set only while the voice may speak) and
  `data-words-said` (how many words of the caption have been said) on the narration.

#### Where older pages differ

These differences may be removed later.

- The two 2D pages, `validation-interval-to-point.html` and `elasticity-resources-follow-demand.html`,
  drawn in SVG:
  - They are laid out like a document, with text above and below the picture, and have no card at
    the end; their last caption sums up.
  - They have text buttons, among them Back (`prev`) and Restart (`restart`); Play, Back, Next and
    Restart have no `title` that names their key. They have no clock and no URL parameters, and the
    elasticity page puts full screen before the slider. Only the full-screen button starts disabled;
    Play, Back, Next, Restart and the slider can be clicked before the script has set them up.
  - Their narration shows the whole text of a step at once and is set with `innerHTML` (from text
    written in the page); the elasticity page also sets its model description with `innerHTML`.
  - Space does nothing on the slider and clicks a focused Play, Back, Next or Restart button. Space,
    → and ← also act when held down or pressed with Alt, Ctrl or Cmd (e.g. Alt+← steps back, and the
    browser goes back a page as well).
  - On the elasticity page, the chosen model and size decide the picture as well, not only the
    playback time; a click on a model or a size while the page waits to start playing on its own
    starts it at once.
- The row/column page: its card, the receipt, shows in the second-to-last step, and the film ends on
  the terminal's result; Space clicks a focused button such as Next; the narration also marks words in
  red (written `~word~` in its script); and with reduced motion it also leaves out a slight sway of
  the camera.
- The row/column page prepares all its programs and textures in one frame after the first picture.
- All three older pages set no `data-scene` (the elasticity page sets `data-minute` on the picture
  instead; the validation page has nothing in its place), and they write some values into the page on
  every frame, changed or not.
- None of the three older pages shows the name ExplainDB in its header or on a card at the end.

### Videos for YouTube

`tools/render_video.py` turns a three.js page with a voice into a video for YouTube: 3840×2160
pixels, 60 frames per second, with the voice and the subtitles, without the controls
([`docs/changes/037-render-videos`](docs/changes/037-render-videos/DECISION.md)). It needs Google
Chrome and ffmpeg (with ffprobe); Chrome must draw with the GPU. The videos are not committed.

```shell
uv run --group browser-tests python tools/render_video.py visualizations/clock-scan.html ~/Desktop/clock-scan.mp4
```

It takes about 0.16 s per frame, so about 17 minutes for a film of 1:43. Next to the video it
writes the picture alone (`clock-scan.video.mp4`) and the voice clips (`clock-scan.voice.json`);
`--mux-only` mixes the voice in again from these two files, in seconds. `--seconds` renders only the
start of the film, and `--hold` sets how long the last frame stays (3 s by default).

The CI job `render_video_test` runs the tool's tests (`system/tests/repo/test_render_video.py`) beside
`visualization_test`, in every merge request that changes the tool, its test, a page, the page
test, `.gitlab-ci.yml`, `pyproject.toml` or `uv.lock`; only this job installs ffmpeg.

## Serializability test of the MVCC store

`system/tests/stores/test_mvcc_serializability.py` runs every schedule of a *schedule space*: a set of
schedules given by the initial state, the data operations, how many of them each transaction runs,
and how the transactions end. The regular test job runs every schedule of two short transactions
(one or two data operations each).

The larger spaces (three transactions, voluntary aborts, longer transactions) take about half an
hour locally (about two hours on CI). They run in the job `serializability_nightly` of the nightly
scheduled pipeline on main; in a merge request the job can be started by hand. Only this job,
`dependency_audit`, `rust_dependency_audit` and `generated_rust_check` run in scheduled pipelines:
every new CI job must extend `.not_in_scheduled_pipelines` (or start its own rules with the same
`schedule`/`never` rule), which `system/tests/repo/test_ci_config.py` checks. A job meant for
scheduled pipelines is added to `SCHEDULED_JOBS` in that test instead. To run the larger spaces
locally:

```sh
EXPLAINDB_NIGHTLY=1 uv run python -m unittest -v system.tests.stores.test_mvcc_serializability.NightlySerializabilityTest
```

## API documentation

An HTML API reference is generated from the source docstrings with
[Sphinx](https://www.sphinx-doc.org). On every push to the default branch the CI
pipeline publishes it to GitLab Pages; the published site is reachable via the
project's **Deploy → Pages** page and is restricted to project members. The public
copy is at <https://bigdata.uni-saarland.de/software/explaindb/index.html>.

To build it locally:
```sh
uv run sphinx-apidoc --implicit-namespaces --no-toc --force --separate -o docs/api system system/tests
uv run sphinx-build -W -b html docs/api docs/api/_build
```
Then open `docs/api/_build/index.html`. The `sphinx-apidoc`-generated stubs and
the `_build/` output are git-ignored; the CI check (`docs_build`, run on every
merge request) builds with `-W` so any documentation warning fails the pipeline.

## Docstring conventions

We document code so that the *contract* lives in one place and implementations
only describe what they add. This keeps overrides free of redundant copies of
the interface documentation.

### Where the contract lives

- **Interfaces and abstract base classes** carry the full contract. Use Javadoc
  style with `@param` and `@return`, as in
  [`system/interfaces/indexing/Index.py`](system/interfaces/indexing/Index.py).
- The docstring on the abstract method is the single source of truth for what
  the method promises.

### Implementations document the delta

- An **override that follows the interface contract exactly** gets a short
  reference only — do *not* repeat the contract:

  ```python
  def put(self, key, value):
      """See :meth:`Index.put`."""
      ...
  ```

- An **override that specializes or changes behaviour** references the contract
  and then states what is special or different in this implementation:

  ```python
  def get_equal(self, key):
      """See :meth:`BitmapIndex.get_equal`.

      Equality-encoded variant: returns the stored bit sequence for the key
      directly instead of OR-ing a range.
      """
      ...
  ```

### Dunder methods

- Document only the **non-trivial** dunder methods — those with real logic or
  special rules:

  ```python
  def __eq__(self, other):
      """Equal iff same bits AND same represented length."""
      ...
  ```

- Skip trivial delegating dunders where Python's semantics are self-explanatory.

### Modules

- Every module gets a one-line module docstring describing its purpose.

### Summary

| Kind | Docstring |
| --- | --- |
| Interface / abstract method | Full contract (`@param` / `@return`) |
| Override, no behaviour change | `See :meth:`...`` reference only |
| Override with a delta | Reference + what is special / changed |
| Non-trivial dunder | Short description of the logic |
| Trivial dunder | None |
| Module | One-line purpose |

## Rust code

The Rust port of the store core in [`generated/rust/`](generated/rust) is **generated** from the
Python code in `system/` and never edited by hand: change the Python code, then generate the Rust
code again (see
[`generated/rust/README.md`](generated/rust/README.md#generated-code-change-the-python-not-this-folder)),
for example with the Claude Code skill [`/regenerate-rust`](.claude/commands/regenerate-rust.md).
Every generated file names its Python sources in its first line
(`// Code generated from ... DO NOT EDIT.`; only `Cargo.lock`, written by Cargo, and the manifest
have none), and its folders mirror `system/`. To see what changed in the Python sources of
out-of-date Rust files since they were generated, run
`python3 .ci/check_generated.py --diff [<file relative to generated/rust/> ...]`: it compares the
copies in [`generated/python_sources/`](generated/python_sources/README.md) with the current
sources. Regenerate every Rust file of a changed source, then record the new hashes with
`python3 .ci/check_generated.py --update`, which also stores a copy of each recorded source version
(copies are never deleted); commit the new copies with the Rust files. The CI job
`generated_rust_check` runs the check without `--update` and reports Rust files that are out of
date or were edited by hand, and missing or corrupt copies or other files in
`generated/python_sources/`; the job fails on main and in the nightly pipeline and
only warns in a merge request. A change of `Cargo.toml`, `Cargo.lock` and `rust-toolchain.toml` that
a person decided (e.g. a dependency or Rust version update) is the one change made directly; record
it with `python3 .ci/check_generated.py --update-dependencies`, which rewrites only the entries of
these three files (`--update` would also record out-of-date or hand-edited Rust files as current). A
regeneration keeps these files as they are: `--update` refuses while one of them differs from the
manifest. The check also reports dangerous constructs in the generated code, e.g. `std::process` or
a build script (see [`generated/rust/README.md`](generated/rust/README.md)).

The generated code follows the same rules as the Python code, written the Rust way. The CI job
`rust_test` fails if one of these checks fails (run them in `generated/rust/`):

```sh
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
RUSTDOCFLAGS="-D warnings" cargo doc --no-deps --locked
cargo test --locked
```

- **License header:** every `.rs` file starts, after its "Code generated" line, with the text of
  [`LICENSE header.txt`](LICENSE%20header.txt), with `//` instead of `#`.
- **Doc comments:** every item, private ones included, has a `///` doc comment, and every file a
  one-line `//!` module doc comment; the compiler rejects missing ones on public items, clippy
  (`missing_docs_in_private_items`) on private ones. Doc comments are Markdown,
  so instead of `@param` / `@return`, name the arguments in the text and use these sections:

  | Python docstring | Rust doc comment |
  | --- | --- |
  | `@param x: ...` | name `x` in the text |
  | `@return: ...` | say what the method returns in the text |
  | raises an exception | section `# Errors`, one line per error |
  | `assert` | section `# Panics` |
  | ``See :meth:`Index.put`.`` | ``See [`VersionedStore::put`].`` |

  clippy rejects a public function that returns a `Result`, or that calls e.g. `panic!`, `assert!`,
  `unwrap` or `expect` directly, without these sections; document other panics (e.g. of a
  called function) by hand. The contract lives on the trait; an implementation references it
  and states only its delta, as described in [Docstring conventions](#docstring-conventions).
- **Python names:** a Rust item whose name differs from the Python item it ports names it,
  e.g. "(Python: `WHERE_Clause`)", and every deviation from the Python behaviour is stated in its doc comment
  and listed in [`generated/rust/README.md`](generated/rust/README.md#deviations-from-python).
- **Tests:** one file per Python test file, at the mirrored place, e.g. `tests/stores/test_stores_basics.rs` for
  `system/tests/stores/test_stores_basics.py`, with the same test names in snake_case; each test folder in `tests/`
  has a `main.rs` that includes its test files (`tests/common/` only holds the shared `mod.rs`). The table in
  [`generated/rust/README.md`](generated/rust/README.md#which-python-test-became-which-rust-test) lists each Python
  test and its Rust counterpart.
- **Rust version:** the image tag of the job `rust_test`, the channel in
  [`generated/rust/rust-toolchain.toml`](generated/rust/rust-toolchain.toml) and `rust-version` in
  [`generated/rust/Cargo.toml`](generated/rust/Cargo.toml) name the same version; change all three together.
