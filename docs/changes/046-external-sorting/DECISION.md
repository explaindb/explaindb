# 046 — External sorting, seen from above
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/251
---
## Context

Slide set 09b ("External Sorting") sorts a file that does not fit into main memory: pass 0 sorts memory-sized pieces
and writes them out as runs; merge passes merge several runs into one until one run is left. The code is
`system/query_processing/sorting.py` (`RunGenerator`, `SingleStreamMerge`, `ExternalMergeSort`: runs in a heap by
size, smallest first, fan-in at a time; merged runs are deleted). The B-tree page (040) already shows a warehouse of
rack sections lined up into one line. Plan, five rounds of looks and a storyboard of 18 stills were agreed in the
proposal merge request !251 (`PROPOSAL.md` there, with nine of the stills).

## Decision

A new page, `visualizations/external-sorting.html`: external merge sort, seen from above, in the B-tree film's world.

- **Opening as 040:** a small hall of 36 rack sections (table R, 576 keys, unsorted), lined up into one line; each
  section tips backwards onto casters and stays whole: **a page of 16 values, 4 rows of 4, read like a text**. All
  parcels are the same size; a blue bar shows each key (key/1000) from the first shot; green marks only the result.
- **Main memory is a steel workbench with room for exactly 4 pages** (ramps in and out, legs on casters, a sign). Three
  robots: the feeder hooks pages onto the cables, the merger moves values on the bench, the carrier takes empty racks
  to and from a depot beside the bench.
- **Input from above, output below; the bench moves down one level per pass**, driving round the end of the row
  between: R / bench / r1 … r9 / bench / r10 … r12 / bench / the query.
- **Cables in floor slots, as San Francisco's cable cars,** pull the racks: one from each input run's head to its place
  on the bench, one from the output place to the right end of the run being written (or on to the query). A run is a
  stream: its head leaves, the rest move up. Reading R copies (R stays complete); in merges the runs' pages leave for
  good (the runs are temporary).
- **Data: 36 pages = 9 runs = 3 × 3**, memory 4 pages (64 values), fan-in 3. Level 1: three merges on the same bench in
  the code's groups ({r1, r3, r7} → r10, {r4, r6, r8} → r11, {r2, r5, r9} → r12); the final merge (r10, r11, r12)
  writes nothing, its green pages are pushed to the query. Counter: read 108, written 72 = 180.
- **Page rules as every new page** (CONTRIBUTING.md, "What a new page has"); film of about 3:20, parts: the table,
  pass 0, merge level 1, final merge. Tests as for 040: a standard-library module reads the page's literal input and
  holds the expected runs, merge groups (as sets) and page counts; a unit test checks them against
  `ExternalMergeSort`; a browser test checks the page's data and its counter.

## Consequences

**Positive:** pages stay whole, as external sorting thinks in pages; every pass is one level, so one sees how many
passes the sort takes; runs as streams and the streamed final merge show the data flow; every merge has 3 inputs; the
film's data is tied to the real code by a test.
**Negative:** the hall is deep and wide (rows up to about 130 m), so overviews show bars, not numbers, and the camera
follows the bench; many motions (cables, pushing, moving up) cost film time, most of it in fast forward; the bench's
memory split differs from the code's in the final merge (the code has no output buffer there).

## Out of scope & deferred

- Second film: replacement selection on the same 36 pages (5 runs, 154 against 180 page reads and writes, no pass
  saved); after replacement selection is in `sorting.py`.
- The voice (own MR), links from the tutorial and slides 09b, early aggregation, sort-merge join, an interactive mode.

## Alternatives rejected

- The House DBMS's basement and pages of cache-line crates (first proposal); values rolled out of the pages into one
  long row.
- 20 pages (the code's last merge mixed two levels), 40 pages (a merge of only 2 inputs).
- Ways drawn on the floor (arrows, roads, rails, railway tracks, velvet cordons) before the cables; trucks for the
  result; a wooden bench; long ramps; a gap in the rows for the bench.

## Scope-shift 2026-11-21

- **Pass 0 reads R as a stream, not as copies** (user, on the first build): each page of R leaves its row for the
  bench, and the cable moves on to R's next page; after pass 0, R's row is empty. So pass 0 shows reading the same way
  as the merges (a page leaves its row). Replaces "reading R copies (R stays complete)" above.
- In pass 0, the four pages of a run leave the bench close behind each other, not one at a time.
- The input cables of a merge never cross: the input with the longest way sideways takes the lane nearest the bench.

## Scope-shift 2026-11-21, second round

- **Runs stay where they are; the cables move instead** (user, on the second build): in merges, a run's other pages
  no longer move up when its first page leaves; the cable's start moves on to the next page, as for R in pass 0.
  Replaces "when its head leaves, the rest move up" above.
- **Both ends of every cable move:** in pass 0, R's cable ends at the bench place the page goes to; the output cable
  starts at the place of the page leaving and ends at that page's place in the run (the page going furthest leaves
  first). In merges, the output cable ends at the next page's place in the run written.
- Merge cables: the two outer inputs take the lane nearest the bench, the middle input the lane above (replaces the
  rule by the longest way sideways, which could cross once the cables' starts move).
- The first page written in a merge shown in detail leaves at real speed and slowly. The final merge's pages go down
  a short cable and sink through a hatch in the floor, "to the query"; its overview shows the input runs as well.
- Key plates: one atlas of all keys at a higher resolution, drawn on every parcel (no longer a pool of 28 racks).
- The film's time is shown large in the top right corner, so that a place in the film is easy to name.

## Scope-shift 2026-11-21, third round

- Names: "Run 1" … "Run 12" (not "r1"); the rows' titles only "DISK", the names beside the rows' first pages.
- Pass 0 writes a run's pages left to right, the smallest values first.
- The sort in memory: all 64 values rise above the bench, then come down one by one, the smallest first, into the
  pages in reading order (before, all flew at once).
- The final merge's pages go into an old factory building, the DBMS, through its gate (replaces the hatch); its
  narration: not written to disk, but streamed to the consumer.

## Scope-shift 2026-11-21, fourth round

- **Merge level 1 takes the runs in their order: Runs 1-3, 4-6, 7-9** (user: the code's groups 1, 3, 7 … were
  "total verwirrend"). The code now merges runs of the same size oldest first (own merge request !284, on which this
  branch builds); the page and its data test follow the code. Replaces the groups in "Data" above.
- The merge cables' lanes: per direction (runs left of their bench place, runs right of it), the input whose start is
  furthest out takes the lane nearest the bench; the cables never cross.
- **The sort in memory is quicksort** (user: "mach einfach quicksort"; replaces the cloud of the third round): Hoare's
  partition with the middle value as the pivot (88 swaps for Run 1's values); the pivot framed in amber, values outside
  the part being partitioned dimmed, each swap two values changing places; the first partition at real speed.
- **The query's building is the works of the House DBMS page** (user: brick, as in that film): its seeded old-brick
  texture, a parapet with a cornice, a chimney, a water tower, "DBMS WORKS" painted on its roof.

## Scope-shift 2026-11-21, fifth round

- **The merge shows its heap** (user: "heap ist gut, damit weiter"): a narrow stand on the bench between the inputs and
  the output holds SingleStreamMerge's heap, one entry per input: the root (the smallest, framed in amber) above, its
  two children below. The first value of each input page goes into it; the root goes to the output page; the next
  value of its run takes the root's place and swaps with a smaller child. An input page is replaced only when its run's
  next value is needed; once a run is used up, the heap's last entry moves to the root.
- **Colours say where a value comes from:** each input's place on the bench is filled in its colour (pink, cyan,
  violet; the yellow frames only round the output); a value in the heap stands on a plate in its input's colour, which
  goes with it (swaps, to the output page); on the output page, a rim of that colour round the value.
- Merge level 1: one view per merge; the swing down to the DBMS works once, while the first green page goes in; no
  film time in the picture.

## Scope-shift 2026-11-21, sixth round

- **The root's plate stays in the heap** (user): when the root goes to the output page, its plate stays on the root's
  place, in the colour of the input read next, until that input's next value lands on it; the output page shows no
  colours. Replaces "which goes with it (… to the output page); on the output page, a rim" above.
- Empty racks for the output come round behind the bench and up its rear ramp, never along the output's cable. The
  robots walk. The heap's first filling shows each place's plate before its value lands.
- The film lasts 5:45 (the heap's three moves per value), not about 3:20 as planned above.
- The page checks at start-up that its own quicksort and heap give the code's runs (RUNS, LEVEL2) and writes what it
  made into `stage[data-made]` for the tests; the merge groups are compared in their order, not as sets (replaces
  "merge groups (as sets)" above).

<!-- notes below: skill never overwrites past this marker -->
