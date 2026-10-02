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

## Notebooks

The notebooks are grouped by the chapters of the [tutorial](docs/tutorial/README.md), which explains each
topic and points to the code that implements it. The launch badge opens a notebook directly on Binder.

### Storage & Data Layout

| Notebook | Topic | Launch |
|---|---|---|
| [Data-Layout](notebooks/Data-Layout.ipynb) | Row vs. column layout: how much each layout has to read for different queries | [![Open Data-Layout on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Data-Layout.ipynb) |
| [RAID-Nesting-Trade-offs](notebooks/RAID-Nesting-Trade-offs.ipynb) | Nesting RAID 0 arrays and its effect on sequential read performance | [![Open RAID-Nesting-Trade-offs on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/RAID-Nesting-Trade-offs.ipynb) |

### Indexing

| Notebook | Topic | Launch |
|---|---|---|
| [B-tree](notebooks/B-tree.ipynb) | Building a B⁺-tree step by step, with visualized splits and leaf chain | [![Open B-tree on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/B-tree.ipynb) |
| [Bitmaps-and-Bloom-Filters](notebooks/Bitmaps-and-Bloom-Filters.ipynb) | Bitmap indexes, their compression (WAH), and Bloom filters for fast "is this value present?" checks | [![Open Bitmaps-and-Bloom-Filters on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Bitmaps-and-Bloom-Filters.ipynb) |
| [Bit-Sequences-in-Pandas](notebooks/Bit-Sequences-in-Pandas.ipynb) | Boolean masks in pandas as bit sequences: filtering rows and combining masks with AND | [![Open Bit-Sequences-in-Pandas on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Bit-Sequences-in-Pandas.ipynb) |
| [Christmas-Tree](notebooks/Christmas-Tree.ipynb) | Radix and descriptor tries, with buffered and "crystal ball" variants | [![Open Christmas-Tree on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Christmas-Tree.ipynb) |
| [Recursive-Model-Index](notebooks/Recursive-Model-Index.ipynb) | A learned index (RMI) for searching sorted data | [![Open Recursive-Model-Index on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Recursive-Model-Index.ipynb) |

### Query Processing

| Notebook | Topic | Launch |
|---|---|---|
| [Result-DB](notebooks/Result-DB.ipynb) | Running a query with two joins as a pipeline of operators (push model) | [![Open Result-DB on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Result-DB.ipynb) |
| [CodeGen](notebooks/CodeGen.ipynb) | Generating Python code for the Result-DB query and running it | [![Open CodeGen on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/CodeGen.ipynb) |
| [Shared-Scan](notebooks/Shared-Scan.ipynb) | Several concurrent queries sharing one pass over the data | [![Open Shared-Scan on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Shared-Scan.ipynb) |
| [External-Merge-Sort](notebooks/External-Merge-Sort.ipynb) | Sorting data larger than main memory: sort chunks, then merge them | [![Open External-Merge-Sort on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/External-Merge-Sort.ipynb) |
| [Top-k](notebooks/Top-k.ipynb) | `ORDER BY title LIMIT 10` without sorting all rows | [![Open Top-k on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Top-k.ipynb) |
| [Online-Aggregation](notebooks/Online-Aggregation.ipynb) | A running estimate of an aggregate before the scan completes | [![Open Online-Aggregation on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Online-Aggregation.ipynb) |

### Query Optimization

| Notebook | Topic | Launch |
|---|---|---|
| [PlanEnumeration](notebooks/PlanEnumeration.ipynb) | Join-order enumeration algorithms (DPsize, DPsub, DPccp) | [![Open PlanEnumeration on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/PlanEnumeration.ipynb) |
| [Distributed-Joins](notebooks/Distributed-Joins.ipynb) | Executing a join across several nodes | [![Open Distributed-Joins on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Distributed-Joins.ipynb) |

### Multidimensional

| Notebook | Topic | Launch |
|---|---|---|
| [Z-Order-Curve](notebooks/Z-Order-Curve.ipynb) | Z-codes (Morton codes): mapping 2-D data to 1-D while preserving locality | [![Open Z-Order-Curve on Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/Z-Order-Curve.ipynb) |

## What's Inside the `system/` Package

A small DBMS written for reading, not for speed. Interfaces in
[`system/interfaces/`](system/interfaces) carry the contracts; the other folders implement them:

- **Storage** ([`storage/`](system/storage)): the storage hierarchy (DRAM, caches, SSD, disk) and RAID
  block assignment (RAID 0/1/4/5) with a reliability and performance cost model.
- **Indexes** ([`indexes/`](system/indexes)): B⁺-tree, bitmap indexes (equality- and range-encoded),
  Bloom filters, radix tries and the "Christmas tree" (a radix trie with node buffers).
- **Bit sequences** ([`bit_sequences.py`](system/bit_sequences.py)): plain and WAH-compressed bit
  sequences used by the bitmap indexes.
- **Transactional stores** ([`stores/`](system/stores)): a versioned key-value store and MVCC
  (multi-version concurrency control) with journaling, also with an index.
- **Query processing** ([`query_processing/`](system/query_processing)): operators such as scan,
  filter, hash join, semi-join and count, plus WHERE-clause predicates.
- **Sorting and queues** ([`sorting.py`](system/sorting.py), [`queues/`](system/queues)): external
  merge sort with in-memory and disk-backed queues.
- **Query optimization** ([`query_optimization/`](system/query_optimization)): join graphs (chain,
  star, cycle, clique), cardinality estimation, the C_out cost function and plan tables for
  dynamic-programming join ordering.

[`DBMS.py`](system/DBMS.py) ties these parts together: it manages stores, prepared queries and query
optimization. Unit tests for all of this live in [`system/tests/`](system/tests).

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

The API documentation, generated from the source docstrings, is available online at
<https://bigdata.uni-saarland.de/software/explaindb/index.html>. How to build it locally is described in
[CONTRIBUTING.md](CONTRIBUTING.md#api-documentation).

## Contributors

People, in order of number of commits:

- [Jens Dittrich](https://bigdata.uni-saarland.de/people/jensdittrich.html)
- [Marcel Maltry](https://bigdata.uni-saarland.de/people/marcelmaltry.html)
- [Simon Rink](https://bigdata.uni-saarland.de/people/simonrink.html)
- [Luca Gretscher](https://bigdata.uni-saarland.de/people/lucagretscher.html)
- [Joris Nix](https://bigdata.uni-saarland.de/people/jorisnix.html)

With help from [Claude](https://claude.com/claude-code), an AI coding assistant by Anthropic, credited as
co-author on commits.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the code formatting, the docstring conventions, and how
dependencies, notebooks and the API documentation are maintained.

## License

ExplainDB is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).
Copyright (C) 2026 Prof. Dr. Jens Dittrich, Saarland University.
