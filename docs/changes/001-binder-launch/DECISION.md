# 001 — Launch the notebooks on mybinder.org
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/108
---
## Context

The project is now mirrored publicly on GitHub (`explaindb/explaindb`). Students should be
able to run the notebooks in the browser without installing uv, Python or Git. mybinder.org
does this for public GitHub repositories, but its image builder (repo2docker) has no uv
support: it installs packages only from a `requirements.txt`, and it ignores our
`pyproject.toml` because the project is deliberately not installable (`package = false`).
The notebooks additionally need Python 3.12, the `dot` binary for `graphviz`, and working
JupyterLab frontends for `ipywidgets` / `ipycanvas`. The GitHub mirror only carries `main`,
so a Binder launch can only be tested after a merge.

## Decision

Keep all Binder configuration in a `.binder/` directory (repo2docker then ignores the repo
root): a `requirements.txt` exported from `uv.lock`, a `runtime.txt` selecting Python 3.12,
and an `apt.txt` installing `graphviz`. The export uses exactly the locked versions, so
Binder runs the same environment as local development and CI. For Python ≥ 3.7 repo2docker
puts kernel and Jupyter server in one environment, so the widget frontends are available.

The export is written without header and annotations, so the file contains only the pins
and does not change with the uv version. A CI job regenerates it from `uv.lock` and fails if
the committed file differs, so a dependency change without a re-export is caught. The
canonical command is documented in `CONTRIBUTING.md`.

The development tools (black, pylint, sphinx, ...) stay in the image, because
`pyproject.toml` has no separate dev group; matching the tested environment is worth the
slower first build.

Delivery is split in two MRs: first the configuration and the CI job; after the merge and
mirror sync the launch on mybinder.org is checked by hand (JupyterLab starts, widgets
render, graphviz output appears); only then a second MR adds the Binder badge and a short
README section. If the launch fails, a fix MR comes before the badge MR, so `main` never
advertises a broken launch.

## Consequences
**Positive:** One click starts any notebook in the browser, with the same package versions
as CI. Forgotten re-exports are caught automatically.
**Negative:** Only the drift check is automated; the image build and the Binder launch are
one-off manual checks. A local repo2docker build on Apple Silicon only proves the
dependency set unless it is built for amd64. pip installs our pinned Jupyter packages over
repo2docker's own versions, which could in principle break the server start. The image is
larger than necessary because it includes the development tools.

## Out of scope & deferred
- Per-notebook launch links in a README table.
- A CI job that builds the Binder image (needs Docker on the GitLab runner).
- Pinning the uv version (`[tool.uv] required-version`) to rule out export differences
  between uv versions; only if the drift check fails spuriously.
- Colab support (would need `system/` to be importable without the repository clone).
- GitHub Actions on the mirror.
- Correcting the "19 notebooks" README badge to 16 (separate bugfix MR).

## Alternatives rejected
- Binder files in the repo root: clutters the root, and a root `requirements.txt` misleads
  uv users.
- `environment.yml` (conda): duplicates the pins and builds slower.
- Adding `[build-system]` to make `pyproject.toml` installable: contradicts the deliberate
  `package = false`.
- Exporting without the Jupyter server packages: diverges from the tested environment and
  needs a maintained exclusion list.
- `?labpath=notebooks` in the launch URL: opens single-document mode, not the folder view;
  `?urlpath=lab/tree/notebooks` is used instead.

<!-- notes below: skill never overwrites past this marker -->

Note 2026-10-02: the export uses `--no-hashes` on purpose. With hashes, pip switches to
hash-checking mode, which requires every package pip installs, including dependencies, to
be pinned and hashed; it is unverified whether that works on top of the Jupyter packages
repo2docker pre-installs via conda. The risk of skipping hashes is that a new or tampered
file is served for a version we pin; that risk is small for short-lived Binder sessions
that hold no secrets. Trying hashes is left to a possible later MR.
