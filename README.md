# ExplainDB - a Database System built for Understandability

[![License: AGPL v3](https://img.shields.io/github/license/explaindb/explaindb)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Jupyter notebooks](https://img.shields.io/github/directory-file-count/explaindb/explaindb/notebooks?type=file&extension=ipynb&label=Jupyter%20notebooks&logo=jupyter&logoColor=white&color=F37626)](notebooks/)
[![Last commit](https://img.shields.io/github/last-commit/explaindb/explaindb)](https://github.com/explaindb/explaindb/commits/main)
[![GitHub stars](https://img.shields.io/github/stars/explaindb/explaindb?style=social)](https://github.com/explaindb/explaindb)
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks)

Teaching materials for a database systems course: a collection of Jupyter notebooks and a didactic
DBMS implemented in Python (the `system/` package). The lecture that uses this code is available on
YouTube: [Database Systems 2024/25](https://www.youtube.com/playlist?list=PLC4UZxBVGKteZpmLGukzu2BpNDifaTe9G)
(Prof. Dr. Jens Dittrich, Big Data Analytics Group, Saarland University).

## Try It in the Browser

[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks)

Click the badge to open the notebooks in JupyterLab on [mybinder.org](https://mybinder.org), with no
installation needed. The start can take a few minutes the first time, after a change to the repository,
or after a longer pause, while Binder builds the environment. Sessions are temporary: they end after a
period of inactivity, or after a few hours at most, and all your changes are lost. Download any notebook
you want to keep (**File → Download**). mybinder.org is a free public service: do not upload private or
confidential data, and do not enter passwords in a Binder session.

## Setting Up the Environment with uv

This repository uses [uv](https://docs.astral.sh/uv/) to manage its Python version and dependencies.
uv installs the correct Python interpreter for you, so no separate Python installation is required.

### 1. Install uv

- **macOS/Linux**:
    ```sh
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
- **Windows** (PowerShell):
    ```sh
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) for
alternatives (Homebrew, pipx, etc.).

### 2. Clone the Repository

```sh
git clone https://github.com/explaindb/explaindb.git
cd explaindb
```

### 3. Install Dependencies

```sh
uv sync
```

This creates a virtual environment in `.venv/`, installs Python 3.12 if needed, and installs all
required packages from `uv.lock`.

### 4. Run Jupyter Notebook

```sh
uv run jupyter notebook
```

This opens a browser window listing the files in the current directory. The notebooks live in the
`notebooks/` directory; open them from there. Any command can be run inside the project environment by
prefixing it with `uv run` — no manual environment activation needed.

Alternatively, you may run the notebooks in an IDE like
[PyCharm](https://www.jetbrains.com/pycharm/); point its interpreter at the `.venv/` created by uv.

## Running the Tests

```sh
uv run python -m unittest discover system/tests/
```

## API Documentation

The API documentation is available online at
<https://bigdata.uni-saarland.de/software/explaindb/index.html>.

An HTML API reference is generated from the source docstrings with
[Sphinx](https://www.sphinx-doc.org). On every push to the default branch the CI
pipeline publishes it to GitLab Pages; the published site is reachable via the
project's **Deploy → Pages** page and is restricted to project members.

To build it locally:
```sh
uv run sphinx-apidoc --implicit-namespaces --no-toc --force --separate -o docs/api system system/tests
uv run sphinx-build -W -b html docs/api docs/api/_build
```
Then open `docs/api/_build/index.html`. The `sphinx-apidoc`-generated stubs and
the `_build/` output are git-ignored; the CI check (`docs_build`, run on every
merge request) builds with `-W` so any documentation warning fails the pipeline.

## Contributors

People, in order of number of commits:

- [Jens Dittrich](https://bigdata.uni-saarland.de/people/jensdittrich.html)
- [Marcel Maltry](https://bigdata.uni-saarland.de/people/marcelmaltry.html)
- [Simon Rink](https://bigdata.uni-saarland.de/people/simonrink.html)
- [Luca Gretscher](https://bigdata.uni-saarland.de/people/lucagretscher.html)
- [Joris Nix](https://bigdata.uni-saarland.de/people/jorisnix.html)

With help from [Claude](https://claude.com/claude-code), an AI coding assistant by Anthropic, credited as
co-author on commits.
