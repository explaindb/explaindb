# 048 — RAID playground: build RAID arrays, compare and fail disks
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/280
---
## Context

The RAID cost model (`system/storage/RAID/cost_model.py`) computes the storage blow-up, the sequential throughput, the
random I/O and, per array, which failures it survives; `block_assignment.py` places logical blocks and parity on the
disks. Students can use both only by writing code. The user asked for a "RAID simulator": put a configuration together
and see what it costs and what it survives. The pages in `visualizations/` are films (play, next, slider, narration,
all driven by the playback time and checked for every page by `EveryPageTest`), so a free sandbox does not fit there.
The MVCC playground (009, 010) is the pattern for such a sandbox: an ipywidgets view in a tested module and a thin
notebook that runs on Binder. The playground depends on model changes made right before it: RAID 5 random I/O with
the read-modify-write penalty, random I/O limited by the slowest member under round-robin striping, and counting the
device failures an array survives.

## Decision

- A playground in the MVCC pattern: a model module and a widget module under `system/playground/`, tested without a
  kernel; the notebook only bootstraps the import path, shows the view and explains it.
- Configurations have one or two levels of RAID 0, 1 or 5 (e.g. 5, 0+1, 1+0, 5+0, 5+1): RAID 0 and 1 have at least
  two members, RAID 5 at least three, every level at most six. The outer level stripes or mirrors over the inner
  arrays; disk slots are numbered inner array by inner array. Every disk is slow or fast; both device types are
  shared by the configurations and their four values can be edited.
- Two configurations, A and B, stand side by side, with presets, and a table compares them: storage blow-up and
  usable share of the raw capacity, sequential read and write, random read and write I/O, whether all data can still
  be read with the disks marked as failed, and how many of all combinations of one, two and three failed disks the
  array survives ("—" when it has fewer disks).
- A click on a disk marks it failed, slow or fast, as a labelled switch selects. A change of a member count clears
  the failed and slow/fast marks; a change of only the levels keeps them, so the same disks can be compared under
  0+1 and 1+0. Failure counts are cached per structure, as they do not depend on the device types.
- For single-level arrays a block view shows which logical block and which parity lies on which disk. A block on a
  failed disk is orange if it can be rebuilt and red if it is lost. Whether data is lost is taken from the cost
  model's `survives()`, not decided a second time; the grid of positions comes from `block_assignment.py`, whose loop
  is moved into a helper that returns the cells as data and that `compute_assignment` formats.
- The notebook states the model's two assumptions: an array member that loses any data counts as failed as a whole
  (in 0+1, failing one disk in each stripe loses data, although every block still exists once), and all performance
  numbers assume that every disk works.
- The README lists the notebook in its notebook table; the tutorial page on RAID points to it.

## Consequences
**Positive:** Students compare RAID configurations, mixed devices and failures by clicking, with the numbers of the
tested cost model; nothing is implemented twice. The view is tested by driving its widgets.
**Negative:** Capacity is shown only relative to the raw capacity, as devices have no size. The block view covers
single-level arrays only. Two levels at most, six members per level. Degraded performance after a failure is not
modelled. The layout in a browser (CSS, dark theme) is checked by hand, apart from the colour contrast tests.

## Out of scope & deferred
- Arrays nested deeper than two levels.
- A block view for nested arrays.
- Performance while a disk has failed (degraded mode) and during a rebuild.
- Reliability over time (MTTDL) and disk sizes in GB.
- Exporting a configuration as Python code.

## Alternatives rejected
- A page in `visualizations/`: those pages are films checked as such by `EveryPageTest`, and the cost model would
  have to be written a second time in JavaScript.
- `interact()`: cannot keep state across clicks.
- Arbitrary nesting depth: a much larger interface for little gain.
- Separate features for the model and the view (as 009/010): the user preferred one feature and one MR.

## Scope-shift 2026-11-19

After the user tried the POC:
- The block view moves into the disk columns: below each disk button, inside the dashed box of its inner array,
  stand the blocks of that disk row by row (data block number or parity `P[…]`). It covers nested arrays too: the
  placement is composed from both levels (the outer level places a block or its parity on an inner array, which
  places it on its disks, adding its own parity). The separate block view and its single-level restriction go.
- Each block on a failed disk is checked on its own, level by level: RAID 0 needs its one position, RAID 1 any
  copy, RAID 5 its own position or every other block of its row including the parity. Orange marks a block that is
  still readable or can be rebuilt, red a block that is lost. Where this per-block answer says all blocks are
  readable but `survives()` says data is lost (e.g. 0+1 with one failed disk in each stripe), the view says so: the
  model, like a typical RAID 0+1 controller, counts an array member that lost data as failed as a whole. The
  verdict and the failure counts per array stay those of `survives()`.
- Configuration B can be switched off; A then uses the full width.
- The numbers stand directly below each configuration, in rows at the same height for A and B, with the better
  value in bold, instead of a separate table.
- Defaults: the device types of the RAID tests (slow 100/50 MB/s and 1000/400 IOPS, fast twice that); unmarked
  disks are fast; at least four block rows, and as many as the array has disks; the introduction comes before the
  setup cell, as in the MVCC playground.

## Scope-shift 2026-11-19 (2)

After the review of phase 3:
- A block on a failed disk counts as readable if a copy of it is on a working disk, or if it is the only missing
  block of a RAID 5 row at either level; rebuilt blocks count in turn, and this repeats until nothing changes. So
  red really means lost, also where only the other level can rebuild a block. Blocks are rebuilt row by row, as RAID
  controllers do; in rare cases of RAID 5 over RAID 5 with many failed disks, a block that several rows together
  could still determine is shown red. The code and the notebook state this limit.
- Disks are named a, b, c, …, so that they are not confused with the block numbers; the parity of an inner RAID 5
  array is written `p[…]`, that of the outer level `P[…]`.
- The disk columns show at most twelve rows of blocks.
- The failure counts of A and B are compared by the share of the survived combinations, not by their number, so that
  a larger array does not win only by having more combinations.

<!-- notes below: skill never overwrites past this marker -->
