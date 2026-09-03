# Row vs. Column Layout

The same table can be stored two ways:

- **Row layout (row-major):** all fields of one record sit together, records one after another. Great
  when you touch whole records — OLTP-style point reads and inserts.
- **Column layout (column-major):** all values of one column sit together. Great when a query reads a
  few columns of many rows — OLAP-style scans and aggregations — because you read only the columns you
  need and skip the rest, and each column compresses well (homogeneous values).

The layout decides how much data you must actually read for a given query, so it is one of the biggest
levers on analytical performance.

## In this repo

- **Notebook:** [`Data-Layout.ipynb`](../../../notebooks/Data-Layout.ipynb) — writes the same data in row and
  column layout (as CSV, for readability) and shows how much each layout has to read for different
  queries. The concepts apply equally to binary on-disk formats and to in-memory representations.

## The idea in one picture

```
rows:      (1,Alice,30) (2,Bob,25) (3,Carol,41)      read a whole record cheaply
columns:   [1,2,3] [Alice,Bob,Carol] [30,25,41]      read one column cheaply
```

`SELECT avg(age)` touches only the `age` column under a column layout; under a row layout it must read
every field of every record.

## Try it

In `Data-Layout.ipynb`, run a whole-record query and a single-column aggregation against both layouts and
compare how many bytes each has to read.
