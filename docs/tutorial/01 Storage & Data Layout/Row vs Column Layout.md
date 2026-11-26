# Row vs. Column Layout

The same table can be stored two ways:

- **Row layout (row-major):** all fields of one record sit together, records one after another. Great
  when you touch whole records — point reads and inserts as in OLTP (online transaction processing: many
  short transactions, each on a few records).
- **Column layout (column-major):** all values of one column sit together. Great when a query reads a
  few columns of many rows — scans and aggregations as in OLAP (online analytical processing: few long
  queries over many records) — because you read only the columns you need and skip the rest, and each
  column compresses well (homogeneous values).

The layout decides how much data you must actually read for a given query, so it is one of the biggest
levers on analytical performance.

## In this repo

- **Notebook:** [`Data-Layout.ipynb`](../../../notebooks/Data-Layout.ipynb) — writes the same data in row and
  column layout (as plain text files with one value per line, for readability) and shows how much each layout has
  to read for different queries. The concepts apply equally to binary on-disk formats and to in-memory
  representations.
- **Visualization:** [`row-or-column.html`](../../../visualizations/row-or-column.html) — an animation
  (open it in a browser): memory is read one 64-byte cache line at a time, so `SELECT MAX(price)` loads
  4 cache lines of a row layout but only 1 of a column layout.

## The idea in one picture

```
rows:      (1,Alice,30) (2,Bob,25) (3,Carol,41)      read a whole record cheaply
columns:   [1,2,3] [Alice,Bob,Carol] [30,25,41]      read one column cheaply
```

`SELECT avg(age)` touches only the `age` column under a column layout; under a row layout it must read
every field of every record.

## A hybrid: PAX

A database stores a table in **pages**, blocks of a fixed size (often a few kilobytes) that it reads from disk as a
whole. **PAX (Partition Attributes Across)** puts the same records on each page as the row layout, but groups their
values column by column *inside* the page: one **minipage** per column. Ailamaki, DeWitt, Hill and Skounakis
proposed it in *Weaving Relations for Cache Performance* (VLDB 2001, the conference on Very Large Data Bases).
Research papers call the row layout the **N-ary storage model (NSM)** and the column layout the **decomposition
storage model (DSM)**, a name from Copeland and Khoshafian (SIGMOD 1985, the conference of the Special Interest
Group on Management of Data of the ACM, the Association for Computing Machinery).

```
{ } = one page, with room for six values

row layout:      { (1,Alice,30) (2,Bob,25) }    { (3,Carol,41) }
PAX:             { [1,2] [Alice,Bob] [30,25] }  { [3] [Carol] [41] }    the same records per page
column layout:   { [1,2,3] }  { [Alice,Bob,Carol] }  { [30,25,41] }     each column on pages of its own
```

As PAX only rearranges the values inside a page, a query reads and writes the same pages as with the row layout:
`SELECT avg(age)` still reads every page from disk, and a whole record still comes from a single page, whereas the
column layout reads a page of every column. What changes is the step from memory into the cache of the CPU (central
processing unit, the processor).

- **Like a column layout, inside a page:** `SELECT avg(age)` brings only the age minipage of each page into the
  cache, so the cache lines it loads hold only ages, apart from a few bytes at the two ends of the minipage. With
  the animation's 32-byte books and 8-byte prices, a 4 KB (4,096 bytes) page holds 128 books (ignoring the page
  header); `SELECT MAX(price)` loads all 64 cache lines of such a page in the row layout, but only the 16 of its
  price minipage in PAX, the same 16 as a column layout.
- **Costs:** rebuilding a whole record takes one value from every minipage, so it touches one cache line per
  column, whereas a short record in the row layout sits in one or two. And with values of varying length, such as
  names, the database must estimate in advance how much room each minipage gets: a new record may not fit although
  the page still has free space, because that space lies in another minipage; then the borders between the
  minipages have to move.

This repo does not implement PAX; the notebook compares only the row and the column layout.

## Where you meet these layouts

- **Row layout:** in files, CSV (comma-separated values) and JSON Lines (one JSON object, JavaScript Object
  Notation, per line) store one record per line. On disk, row stores such as PostgreSQL keep a table in pages that
  hold whole rows, and read these pages into their buffer pool in memory (in PostgreSQL called *shared buffers*).
- **Column layout:** in memory, Apache Arrow keeps the values of each column one after the other, and pandas can
  keep the columns of a DataFrame as Arrow arrays. On disk, column stores such as ClickHouse store the values of
  each column one after the other.
- **Hybrid, like PAX:** in files, the open file format Apache Parquet splits a table into **row groups** of many rows
  and stores each column of a row group contiguously (a **column chunk**); Apache ORC (Optimized Row Columnar), a
  similar file format, does the same with **stripes**. On disk, the database DuckDB stores its tables in row groups,
  too. In memory, Arrow can split a table into **record batches**, each holding all columns for one slice of the
  rows.

Parquet, ORC and DuckDB are usually called columnar, but their layout is PAX at a much larger scale. As a row group
is far larger than a page (ORC's default stripe is about 64 MB, megabytes), a query that needs only some columns
skips the bytes of the others on disk, which is not possible inside a PAX page, as the page is read as a whole.

## Try it

In `Data-Layout.ipynb`, run a whole-record query and a single-column aggregation against both layouts and
compare how many blocks and bytes each has to read.
