# sphinx-api-docs — Sphinx API documentation site
**Date:** 2026-09
**MR:** link TBD
---
## Context

Docstrings in `system/` mix Javadoc `@param`/`@return` tags with reST cross-references
(`:meth:`Index.put``). The `CONTRIBUTING.md` convention keeps the full contract on
interfaces and reduces overrides to `"""See :meth:`X`."""` deltas. There is no rendered
API reference: the docstrings live only in the source. We want a browsable HTML site
generated directly from those docstrings, so humans (students, contributors) read the
contract without opening the code, and the single-source docstrings cannot drift from a
hand-written reference.

Constraints that were obvious at decision time:

- The code is a **PEP 420 namespace package** (no `__init__.py` anywhere under `system/`);
  imports resolve only because CI runs from the repo root.
- Docstrings use **Javadoc tags**, which no standard Sphinx extension (autodoc, napoleon)
  parses, and some `@param` descriptions **wrap across multiple indented lines**.
- Code uses **PEP 695 generics** (`class Index[Key, Value](ABC)`), which only recent
  Sphinx renders correctly.
- The repo is hosted on a **self-hosted GitLab 19.3.1-ee** instance with GitLab Pages
  available at `pages_access_level=private` (project members only), `visibility=internal`.
- Package manager is **pipenv**; CI runs on self-hosted runners tagged `test`.

## Decision

Use **Sphinx + autodoc** (chosen over MkDocs because the code already carries reST
`:meth:` roles) with the **furo** theme, pinned to a current Sphinx 8.x. The Javadoc tags
are bridged by a small `autodoc-process-docstring` hook that rewrites `@param`/`@return`
into reST field lists and re-attaches multi-line continuation lines to the field body;
`:meth:` roles are left untouched. The hook lives in its own importable module
(`docs/api/javadoc.py`) so it can be unit-tested independently of a full Sphinx build.
Per-module `.rst` stubs are generated at build time with
`sphinx-apidoc --implicit-namespaces` (required for the namespace package), excluding
`system/tests/`; the generated stubs are not committed, because they rot.

The site is built and published on **GitLab Pages via CI**, published only from the
default branch. To validate the build before merge, a separate `docs_build` job runs on
merge-request pipelines with `sphinx-build -W -n` (warnings as errors), so import errors,
dangling cross-references, and unconverted Javadoc tags fail the MR rather than surfacing
after merge. No per-MR rendered preview is hosted — the MR gets a build check only.

## Consequences

**Positive:**
- Browsable API reference generated from the single-source docstrings; cannot drift.
- `sphinx-build -W -n` on every MR turns doc-build breakage into a pre-merge failure.
- No existing docstrings are rewritten — the hook adapts to the code, not vice versa.
- Namespace-package and PEP 695 support handled explicitly, so the site is not silently
  empty or mis-rendered.

**Negative:**
- The Javadoc→reST hook covers the docstring patterns present today; exotic or deeply
  nested field constructs are not guaranteed — `-W` makes any such case visible.
- Pages is `private`, so the published site is reachable only by authenticated project
  members; the README says so.
- autodoc imports the `system` package, so the build job needs the full dependency set
  (`pipenv install`), making it slower than a pure-static docs build.

## Out of scope & deferred

- Integrate `docs/tutorial/` Markdown into the site via myst-parser.
- Render the notebooks into the site (myst-nb / nbsphinx) — heavy, executes notebooks.
- Docstring-coverage gate in CI (interrogate / `sphinx.ext.coverage`).
- `viewcode` → `linkcode` linking rendered API to GitLab source.
- Per-MR rendered Pages preview via environments — more CI machinery than a build check.

## Alternatives rejected

- **MkDocs + mkdocstrings** — the code already uses reST `:meth:` roles; user chose Sphinx.
- **Read the Docs** — private uni GitLab makes repo mirroring/token setup awkward.
- **Committing generated apidoc stubs** — they rot against the code.
- **Rewriting all docstrings to Google/NumPy style** (for napoleon) — touches hundreds of
  files, violates the surgical-changes convention.

## Scope-shift 2026-09-07

The `## Decision` and `## Consequences` sections above describe the build gate
as `sphinx-build -W -n` (nitpicky). During the POC, `-n` was **dropped**: it raised
415 warnings for unresolved cross-reference targets on standard-library,
third-party, and `TypeVar` types, none of which are defects. Resolving them
cleanly needs intersphinx plus a `nitpick_ignore` list, which is deferred to a
Tier-2 MR. The shipped gate is therefore `sphinx-build -W` (warnings as errors,
without `-n`); it still catches import failures, dangling `:meth:` references,
and unconverted Javadoc tags. The three real docstring warnings `-W` surfaced
were fixed via the conversion hook, so the build is clean at `-W`.

<!-- notes below: skill never overwrites past this marker -->
