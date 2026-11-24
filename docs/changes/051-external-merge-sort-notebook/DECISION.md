# 051 — External merge sort notebook on the real sorter
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/288
---
## Context

`notebooks/External-Merge-Sort.ipynb` does no external sorting: it sorts with `sorted()`, pickles the data to a file,
loads it back whole and prints 10,000 lines; its last cell is a to-do list whose items now exist in
`system/query_processing/sorting.py` (external queues, the multi-way merge and, with 049, replacement selection).
The README row and the tutorial page on external sorting promise runs, merges and a memory budget to play with,
which the notebook does not have. Lecture 09b shows external merge sort on 16 values (slide 22) and replacement
selection on the same input (slide 23); slide 23 was wrong (replacement selection with M = 4 made three runs), so
the input row of slides 2–23 was changed to `3,4 6,2 9,4 8,7 5,6 3,1 1,4 6,7`, which keeps every run and merge of
slide 22 and makes slide 23 right. An earlier plan for 051, an ipywidgets panel comparing runs sorted in memory with
replacement selection by bars and tables, was not understood by the user and is folded into this notebook instead.

## Decision

- Rewrite the notebook as a guided tour that runs the repo's `ExternalMergeSort` and measures it: an introduction
  (lecture 09b, the tutorial page), the in-memory baseline, slides 22 and 23 in miniature (16 values, M = 4, F = 2)
  with the runs and merges printed and drawn, pass 0 at scale with the disk-backed queues, merging with counted
  elements written and read next to the textbook cost, a table over memory and fan-in for both run generations,
  replacement selection at scale on random, sorted and reversed input, tests and things to try.
- The drawn merge tree shows the two trees side by side as on slides 22/23: each run a column of page boxes of two
  values, the levels separated, arrows from each merge's inputs to its output, the final merge as an arrow to the
  result. It is drawn from what the real sorter did, as inline SVG that works in light and dark themes, for small
  inputs only.
- Counting and drawing live in two small tested modules under `system/playground/`, not in notebook cells; the
  counting comes from the earlier 051 model (a counting list queue and factory, a counted input), generalised to
  any comparable element and extended to record each merge's inputs and output without changing `sorting.py` (the
  queues first read since the previous output queue was made are the inputs of the next one; a test pins that
  order).
- The notebook states the code's cost exactly: with the real number of runs R, the textbook cost is
  2n · (1 + ⌈log_F R⌉); the final merge writes nothing, so sorted chunks with R = F^k (k ≥ 1) cost n less;
  replacement selection with R ≥ 2 costs at most that; when R is not a power of F, elements can skip a level and
  the cost can be lower; a single run costs 3n against the textbook's 2n. Every number the text quotes is asserted.
- The notebook uses its own orderable dataclass (`system.data_classes.Person` sorts by name in descending order).
  Records are checked as a multiset of full records, as their `==` compares the key only.
- Links to the replacement selection playground (050) and the external sorting film (046) are added by whichever
  merge request lands later; the one that lands second also re-measures the notebook weights and recomputes the
  expected packing of the notebook CI jobs.

## Consequences
**Positive:** The notebook finally shows external merge sort and replacement selection on the real code, with the
lecture's own example reproduced and drawn, and numbers students can change. The tutorial's promise holds.
**Negative:** The counting module relies on the order in which `SingleStreamMerge` reads its inputs and asks for
its output queue (pinned by a test). The counts are in elements, not pages. The drawing is for small inputs only.

## Out of scope & deferred
- A plot of elements written over memory for both run generations.
- Pages instead of elements (I/O counted in pages, as the slides do).
- A stable external sort (the merge heap compares values only).
- The ipywidgets comparison panel of the earlier 051 plan.

## Alternatives rejected
- Fixing the old notebook cell by cell: it has no external sorting to fix.
- Two merge requests (cleanup first, content second): the cleanup alone leaves a notebook that still shows no sort.
- The comparison as an ipywidgets panel with bars and tables: the user did not understand it; a narrated table and
  the slides' example drawn as a merge tree are easier to follow.
- Counting inside notebook cells: untested code.
- Recording merges by overriding a private method of `ExternalMergeSort`: ties the module to a private name.
- Pickle files as "disk": the repo's disk-backed queue does this and cleans up after itself.

## Scope-shift 2026-11-23

Every merge in the drawn merge trees reads at least three runs, so the miniature deviates from slides 22 and 23 (it
replaces their reproduction with F = 2 in *Decision*): the user's standing rule (as in the external sorting film,
046) is that merges of only two runs look like pairs and confuse students, as they hide that a merge reads many runs
at once. The miniature sorts 36 one-digit values on 18 pages of two with M = 4 and F = 3: sorted chunks make 9 runs,
three merges of three runs and a final merge of three (9 = 3 × 3); the values are chosen so that replacement
selection makes 3 runs, which the final merge reads at once, one level of merges less. With F = 3 the code takes
only two runs in its last merge before the final one when pass 0 makes 4, 6 or 8 runs, so the miniature needs an odd
number of runs; the notebook's tests and a unit test check that every drawn merge reads three runs. The slides' own
example (16 values, F = 2) stays in the notebook as a thing to try and as a row of the cost table. The section
comparing the counted cost with the textbook's is shortened to one table and a few sentences.

## Scope-shift 2026-11-23: example data, not layout

The code merges the smallest runs first, so on some inputs a merge reads runs that lie far apart in the drawing
(e.g. 39 ascending values with M = 4 and F = 3: the short last run with the first two runs), and their arrows cross
or lie on top of each other. The user decided to choose the example data so that this does not happen, not to
change the drawing's layout: the trees shown (the notebook's miniature and its preview) merge only neighbouring
runs (runs of equal size, whose smallest are neighbours, or no merge before the final one), and a test checks that
no two of their arrows lie on top of each other. The notebook says near "Things to try" that other inputs can give
crossing arrows, as the drawing shows what the code does.

## Scope-shift 2026-11-24

The notebook sorts integers throughout (the user's decision). One seeded list of 10,000 random integers is the input
of the in-memory baseline, of pass 0 on disk, of the counted cost with M = 1,000 and F = 4, of the table over memory
and fan-in, and of replacement selection at scale. This replaces the customer records made up by Faker and the
notebook's own orderable dataclass in *Decision*. Why: every sort at scale now works on the same data, so its numbers
can be compared across sections, and the table no longer needs a sentence on why it uses other data than the rest;
the records' names and cities played no part in the sort, and a record whose `==` compares its key only needed a
check of its own. One sentence in the introduction says that a DBMS sorts whole tuples by a key and that the
integers stand for those keys. The tests compare the output with `sorted()` of the input, and now check the run sizes
on disk and on counting queues for replacement selection too. Without Faker, the notebook runs in about 0.6 s instead
of 1.6 s; its weight and the expected packing of the notebook CI jobs are updated.

The same round applies a review of the notebook's text (17 findings): the introduction speaks of two steps, a merge
pass is tied to the drawing's level, the miniature's dense paragraph is split, the counted cost at scale is explained
(46,000 and 38,214 against 60,000 for both, as ⌈log_4 10⌉ = ⌈log_4 6⌉ = 2), the four cases of the cost table form a
list, the 16-value counterexample has a heading of its own, "ways of making runs" replaces "run generations", the
text names the buffer of `ExternalQueueFactory` (100 values), and a thing to try asks for which M and F both ways of
making runs need the same number of merges.

## Scope-shift 2026-11-24 (2)

The user's second round on the notebook's text:

- **Fan-in in words:** the prose says "fan-in 3" instead of "F = 3"; formulas keep F, introduced once as "the fan-in F".
- **N and M as in the external-memory literature:** N elements (no longer n), M elements of memory, R runs; one
  sentence in the introduction says that upper case counts elements, as in Vitter, *Algorithms and Data Structures
  for External Memory* (2008). The docstrings of `sort_counting.py` that quote the formula follow; identifiers stay.
- **Names instead of jargon:** no "counted" or "textbook" as labels; the columns are "written", "read",
  "written + read", "formula − N" and "formula 2N(1 + ⌈log_F R⌉)", "fan-in" and "N"; the variable `counted` is now
  `at_scale`, and the tests are renamed to match.
- **A clearer cost section:** why the elements written and read differ from the formula is a numbered list of the
  three ways the code differs, each with its rows of the table; a new test checks the run that skips a level.
- **Labels:** where `compare` is introduced and at the cost table, the text says that it runs the real
  `ExternalMergeSort` on counting queues and only the formula is computed; at the first drawing, that the merge
  trees are drawn from what the sort recorded, with only `MINIATURE` fixed.

## Scope-shift 2026-11-24 (3)

The user found the notebook unclear as a notebook: terms such as "miniature" were not defined, variables were used
before they were introduced, and there was too much running prose. The notebook is reworked completely; what it
shows and the numbers it quotes stay.

- **Definitions as tables, first:** *Terms and symbols* (element, N, M, run, pass 0 with its two ways, R, merge,
  fan-in, level, final merge, written + read as measured, the formula as computed), *Data* (every input with its
  variable, size, how it is made and why), *The sorts of this notebook* (data, M, fan-in and result variable per
  section) and *How the notebook measures* (`sort_counted`, `compare`, the fields of `SortCounts` used, the drawing).
- **Much less prose:** each numbered section has a one-line goal, the code, its result and at most a few lines of
  interpretation, as a table where several cases are compared (the three reasons why written + read differs from
  the formula, the sweep, the input orders, the things to try). Each claim is made once.
- **Every input in one cell, under a name that says what it is:** `MINIATURE` is now `SMALL_EXAMPLE` (the word
  "miniature" is gone), `SLIDE_ROW` `SLIDE_VALUES`, `SWAPPED_ROW` `SLIDE_VALUES_SWAPPED`, `numbers`
  `random_values`; the ascending inputs of the cost table are `ASCENDING_16`, `ASCENDING_20` and `ASCENDING_104`,
  and `input_orders` holds the three orders. The results are `small_sorts`, `large_sorts` (was `at_scale`),
  `sorts_by_order` and `swapped_sorts`; `M` and `F` as Python variables are `MEMORY` and `FAN_IN`, so that M and F
  stay symbols. The copy of the small example in `test_merge_tree.py` and its check are renamed to match.
- **Tables made by the code:** the helpers `both_ways` and `summary` give every table the same columns ("pass 0",
  "R", "merges before final", "written", "read", "written + read", the formula); the cost table has a "data" and
  a "pass 0" column instead of a free-text case name.
- **Tests:** as strict as before, on the new names; new checks for the data sets (sizes, value ranges, the three
  orders, the swapped values), the settings the tables quote (M, fan-in, the queue buffer of 100, at most 40
  values drawn, fan-in from 2 to M − 1) and that every counted sort returns its input in order.

## Scope-shift 2026-11-24 (4)

Review of MR !288 by Gunce Su Yilmaz: the notebook used R for the number of runs although R is the input on the
slides, did not use the slides' terms for pass 0, showed the effect of the fan-in only in a crowded table, and was
long and textual. The four decisions:

- **W for the runs, R for the input:** the number of runs of pass 0 is W, as in Graefe, *Query Evaluation
  Techniques for Large Databases* (1993); R only names the input table, as on the slides and in the film's legend.
  The formula reads 2N(1 + ⌈log_F W⌉), in the notebook (terms, column headers, tests), in the docstrings and error
  messages of `sort_counting.py` and in its tests. Identifiers in the code are unchanged.
- **Quicksort instead of "sorted chunks":** the first way of making runs is called quicksort, as on the slides
  (labels, columns, prose, README, tutorial page). The terms table notes once that the code sorts each chunk with
  Python's `list.sort()` (`RunGenerator.create_runs`). Replacement selection is defined as a term (a way of making
  runs that can be longer than main memory), with a link to the Replacement Selection Playground notebook, not
  described as an algorithm.
- **A fan-in table instead of a third tree:** section 2 has a table of two rows, the 9 quicksort runs of the small
  example merged with fan-in 2 and with fan-in 3 (W, level of the final merge, merges before the final one,
  written + read, formula), measured on the real sort and asserted in the tests. No third drawing, because drawn
  merges read at least three runs, and a fan-in-2 tree of the 36 values also has crossing arrows. The sweep of
  section 5 is two small tables that change one thing each (M at fan-in 10; the fan-in at M = 100, now also
  fan-in 2) and show quicksort only; the numbers of replacement selection are one sentence.
- **Shorter, and fewer tables up front:** the Markdown is cut from about 12,800 to about 8,900 characters.
  *The sorts of this notebook* is a column "used in" of the data table, *How the notebook measures* one sentence
  under the terms table; interpretations are one or two sentences; *Things to try* has three rows.

<!-- notes below: skill never overwrites past this marker -->

**2026-11-23, POC:** the rule in *Decision* that replacement selection with R ≥ 2 costs at most textbook − n is
false in general. The code merges the smallest runs first, F at a time, and takes fewer than F runs only in its last
merge before the final one, so some elements can go through one merge more than ⌈log_F R⌉: 104 values, M = 4, F = 3
give 26 runs of 4 (sorted chunks, or replacement selection on descending input) and cost 752 against
textbook − n = 728 (textbook 832). The notebook shows this case as a counterexample instead of stating the rule; in
all its other examples with R ≥ 2, the counted cost stays at or below textbook − n.
