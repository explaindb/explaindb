# 050 — Replacement selection playground
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/286
---
## Context

Feature 049 added replacement selection to `system/query_processing/sorting.py`: a lazy iterator `ReplacementSelection`
whose heap, list and run number can be read between steps, a public `start_next_run()` that bulk-loads the list into the
heap, and the textbook heap functions `sift_down` and `bulkload` (Floyd's linear method). The lecture (slides 09b,
24–43, and the pseudocode on slide 44) teaches replacement selection step by step with M = 4 elements and the input 30
20 10 40 25 73 16 26 33 50 31: the root of the heap goes to the output run, the next input element goes into the heap if
it is not smaller than the last output (green), else into a list for the next run (red); an empty heap is bulk-loaded
from the list and a new run starts. Students should be able to follow this on their own input, step by step and swap by
swap, on the code of 049 rather than on a second implementation. The RAID and MVCC playgrounds (048, 009/010) are the
pattern for such a sandbox: an ipywidgets view in a tested module and a thin notebook that runs on Binder.

## Decision

- A playground in the RAID/MVCC pattern: a model module and a widget module under `system/playground/`, tested
  without a kernel; the notebook only bootstraps the import path, shows the view and explains it.
- Input: integers from 0 to 999, at most 60 of them, typed into a text field and parsed with clear error messages (a
  token that is not a number, too many values, a value out of range); M from 3 to 12. Presets: the slides' example
  (M = 4), random (n and seed, drawn without repeats with `random.Random(seed).sample`), sorted, reversed and almost
  sorted. Own input may repeat values; equal values behave as on the slides (an element equal to the last output
  stays in the current run).
- The model drives `ReplacementSelection` on elements that carry their value and their position in the input; they
  compare by value only, so the code sees what it would see with plain numbers, while the playground tells equal
  values apart by their position. It records one frame per sub-step: what is left of the input, the heap as an
  array, the list, the output with its run numbers, the comparison of the current output step, the two elements a
  sift compares, a caption and the places to mark. Sub-steps:
  - the start (input full, memory empty); the first M elements loaded into the list in reading order, as the
    iterator's constructor does;
  - per output: the root goes to the output (its place stays empty); the next element is drawn and compared with the
    last output, and either takes the root's place (green) or goes to the list (red), after which the heap's last
    element takes the root's place; then the element at the root swaps down, one swap per sub-step. Once the input is
    exhausted, the last element takes the root's place without a comparison;
  - when the heap is empty and the list is not (run 0 included): "Bulkload a heap from the list", the list in its
    order as an array; the playground calls `start_next_run()`, which bulk-loads the list and starts the next run,
    and shows that bulk load node by node;
  - the end, when heap and list are empty.
- The linear bulk load is replayed, not reimplemented: the playground calls `sorting.sift_down` on a copy for every
  inner node, from the last to the root, as `bulkload` does, and checks that the result is the heap the iterator built,
  element by element (by position in the input, not by value); otherwise it raises an error. Inner nodes are dashed.
  Every comparison of a sift in the bulk load has a frame of its own: the sinking element and its smaller child are
  framed blue and the edge between them is drawn four times as wide ("Sift down 30 from place 0: its smaller child is
  10; 10 < 30, so they swap"), and the sift ends with a frame that says why ("Sift down 20 from place 1: its smaller
  child 40 is not smaller, so 20 stays", or "30 at place 2 has reached a leaf"). The smaller child at the sift's end is
  read off the array after it. The sifts after an output show only their swaps; one argument switches the comparisons on
  there too. There is no comparison counter: with M ≤ 12, 2n and n log n hardly differ; the notebook explains why the
  method is linear.
- The swaps of one sift are derived from the heap array before and after it, without a second heap: in the bulk
  load, and inside `__next__`, whose array before the sift is the heap with the drawn element, or the last element,
  at the root. The elements that changed place lie on one path down from the sifted place: the sifted element ends
  at the path's end, and every element above it on the path moves up one level. Each edge of that path is one swap,
  shown top down and captioned "swaps with its smaller child".
- The view shows the rows of the slides: input R (taken elements empty), the heap as a tree (root on top, framed
  amber, children below, the array index at every place), the list and the output runs. Captions use the slides'
  wording ("Remove top element 10 from heap and write it to output run", "Draw next element 25 from input sequence",
  "Bulkload a heap from the list").
- A comparison box at the top right of the view, with the same place and size in every frame, shows as on the slides the
  last element on output, the next element of the input and the decision: "25 >= 10 → heap (this run)" on green or
  "16 >= 25 → list (next run)" on red (written as on the slides also on red, while the caption says "16 < 25"). It
  belongs to an output step: from the frame that writes the root to the output, where the slides show the decision
  already, through the draw and the swaps that follow; during the swaps it still compares with the last output, not with
  the root. Before the first output and during the bulk load of a new run it shows dashes and a note (that nothing is
  left to compare if the input is empty already, or that nothing is to compare if the whole input fits into memory);
  once the input is empty, "— (R is empty)" and no decision.
- Marks follow the slides' timing: at the start the M elements the next step loads; when the root is written, that
  element in the output, the empty root, the next element of the input and, in the box, the last output; when an
  element is drawn, its new place in the heap or the list.
- The output is a conveyor that flows away from the heap: every new element enters on the left end of the output row
  and pushes the elements already written one place to the right, and a new run's box stands left of the older runs'
  (run 0 reads 73 40 30 25 20 10 once complete).
- The root's amber is that of the external sorting film on dark pages and a darker amber on light pages, where the
  film's amber stands out too little. The view takes the theme from the page where JupyterLab, Jupyter Notebook or VS
  Code mark it, else from the system's colour scheme; without either, the darker amber is the default, as it stands
  out from dark pages too.
- Run colours cycle through three tints (pink, cyan and violet, the run colours of the external sorting film), so
  that neighbouring runs always differ: heap elements have the colour of the current run, list elements that of the
  next run, output elements that of their run. The colours are translucent tints and no text colour is set, so that
  the theme's text stays readable in light and dark themes (tested, as in the RAID playground).
- Controls: ⏮ start, ◀ back, forward ▶, next output ⏩ (to the next "Remove top element …", past draws, swaps and
  bulk loads), end ⏭; a preset dropdown, the input text, an M slider, and n and seed for the generated presets. A
  change of the preset, the text or M traces anew and goes back to the start. All HTML is built with `html.escape`
  on every value; no `interact()`.
- The README lists the notebook in its notebook table (section "Query Processing"); the tutorial page on external
  sorting points to it.

## Consequences
**Positive:** Students follow replacement selection on their own input, swap by swap, with the code of 049; nothing
is implemented twice, and the replay check ties every shown heap to the iterator's. The view is tested by driving
its widgets.
**Negative:** The playground relies on the order of `bulkload`'s loop (last inner node to the root), which it repeats,
and on the branches of `__next__`, from which it rebuilds the heap array before each sift; the checks fail loudly if
either changes. Memory is counted in elements of heap and list only, as on the slides. Where the page marks no theme the
style reads (e.g. PyCharm, classic Notebook, Colab, VS Code's high-contrast themes) and the system's colour scheme is
dark while the notebook is light, the root gets the film's amber, which stands out little on a light page. The layout in
a browser (CSS, dark theme) is checked by hand, apart from the colour contrast tests.

## Out of scope & deferred
- The comparison with runs sorted in memory (quicksort): runs, merges, elements written and read (feature 051).
- A film on replacement selection.
- Pages and page I/Os; variable record sizes.
- A snowplow picture (why runs are about 2M long on random input).

## Alternatives rejected
- Replacement selection written inside the playground: implemented twice, and the tests could not tie it to the code.
- A page in `visualizations/`: those pages are films, checked as such; free input does not fit.
- The heap as a sorted sequence, as on the slides: a real heap, drawn as a tree, shows what the code does.
- Events or callbacks in `sorting.py` for the view, also a per-node callback in `bulkload`: visualisation concerns in
  production code; readable iterator state, `start_next_run()` and a replayed node loop are enough.
- A sift written in the playground: a second heap; the playground calls `sorting.sift_down` and derives the swaps
  from the arrays before and after.
- `interact()`: cannot keep state across clicks.

## Scope-shift 2026-11-23

After the user tried the notebook:
- The steps inside a bulk load are optional and off by default: a checkbox "Bulkload step by step". Off, every bulk load
  (run 0's and every later run's) shows two frames: "Bulkload a heap from the list", the list as an array that is no
  heap yet, and the finished heap ("Heap maintains half order"), on which the places that hold another element than
  before the bulk load are marked grey. On, it shows the comparisons (the blue pair and its wide edge), the swaps and
  the ends of the sifts, as before. The slides' example has 38 frames off and 44 on.
- The trace always holds every frame, so the bulk load is replayed and checked against the iterator's heap in both
  modes; the view leaves out the steps inside the bulk loads when the checkbox is off. Toggling does not trace anew and
  keeps the place: the same frame, or, if it was a step inside a bulk load, the start of that bulk load.

## Scope-shift 2026-11-23 (2)

- The frame "Bulkload a heap from the list" is animated, without JavaScript, by CSS keyframes in the widget's style:
  the full list slides left as a row into the heap (0.6 s), then every element moves from its position i in the row to
  its node, place i of a complete binary tree in array order (0.9 s); the animation ends exactly in the frame's static
  tree, which is no heap yet. The edges and the place numbers fade in meanwhile; the list beside the heap is empty at
  the end. It plays whenever that frame is shown, for the first M elements and for every new run, with the bulk load
  step by step or not. A reader whose system asks for reduced motion sees the tree at once. The elements start over
  the list's cells by the layout's own sizes (the gap between heap and list, the cells' width), so the movement starts
  where the list is as long as both columns stand side by side. Checked in headless Chromium and in JupyterLab 4.
- ⏮ and ⏭ are drawn as text, as ⏩ already was, not as coloured emoji.

## Scope-shift 2026-11-23 (3)

After the user tried the notebook again ("du musst alle Vergleiche zeigen": you must show all comparisons): a sift
that shows only the swaps hides the algorithm, as it does not show which comparisons lead to a swap and which end the
sift.
- Every sift shows every comparison `sift_down` makes, each a frame of its own with the blue pair: where the sinking
  element has two children, first the two children compared with each other, which picks the smaller one (the left
  one if they are equal), then the sinking element with the smaller child, which leads to a swap or ends the sift;
  where it has one child, only that comparison. This holds for the bulk load and for the sift after every output;
  there, a heap of one element compares nothing and shows no sift. A bulk load of n elements thus shows at most 2n
  comparisons, as the notebook says.
- A bulk load first shows its order: which places are leaves, with nothing to sift, and that the inner nodes are
  sifted down from the last one back to the root.
- The checkbox "Bulkload step by step" becomes "Heap maintenance step by step" (user: "heap maintenance step by step
  … und dann die heap maintenance zwischendurch entsprechend abschalten": and then switch off the heap maintenance in
  between accordingly) and is on by default. It covers every heap maintenance: a bulk load and the sift after every
  output. Every heap maintenance ends with the frame "Heap maintains half order", now also after an output; off, the
  view leaves out the steps in between and marks on that frame the places whose element changed, for a bulk load as
  before.
- The playground's model reconstructs each comparison from the heap it shows and checks it against the swaps
  `sift_down` made.
- The captions quoted in *Decision* change: "Sift down 30 from place 0: its children are 20 and 10; 10 is smaller",
  then "30 and its smaller child 10: 10 < 30, so they swap"; "Sift down 20 from place 1: its only child is 40;
  40 ≥ 20, so 20 stays". The wide blue edge joins only an element and its child, not two children compared.
- The slides' example has 74 frames with the checkbox on and 38 with it off.

## Scope-shift 2026-11-24

The user: "Heap maintenance step by step" is off by default. Without it, a bulk load shows only the heap before it
and the heap in half order after it, the places that changed marked; after an output, the half order is no frame of
its own: the frame in which an element takes the root's place shows the heap after the sift, the places that changed
marked, and its caption adds ", then sinks until no child is smaller". Switching it on shows every comparison and
swap, as in Scope-shift (3). The slides' example has 31 frames with the checkbox off. The comparison box stands
between the input and the heap, no longer beside the input.

## Scope-shift 2026-11-24 (2)

The user, on heap and list drawn as two areas: "eigentlich ist es ja nur eine Liste oder ein Array" (it is really just
one list or array). The playground shows main memory as one array, as the code keeps it since 052 (replacement
selection in one memory array), on which this feature now builds.
- Frames carry `memory` (M places; those an input shorter than M never fills stay empty) and `heap_size` instead of a
  heap and a list; marks name places of memory, place i of the heap being place i of memory. After every step the
  playground checks its memory against the iterator's (without the places the iterator does not have for a short
  input): every place, the empty ones included, and the heap size. For a bulk load it moves the list to the front
  itself (empty places dropped, memory order kept) and replays the loop of `bulkload` with `sift_down` on the heap at
  the front.
- The view: input R; the comparison box; the heap drawn as a tree, the view of the first `heap_size` places of memory;
  below it main memory as one row of M numbered cells with a bar between heap and list, heap cells in the current run's
  colour, list cells in the next run's, empty places dashed; the output runs.
- An element x smaller than the last output: the draw shows x in the comparison box only; then "The heap gives up its
  last place, and its last element 73 takes the root's place", the bar moving in this frame; then the sift; then "16
  goes into the freed place: the list's newest element, next to the heap". If the root was the heap's only element, a
  single frame: x takes its place as the list's newest element. Without the steps of heap maintenance, the sift's result
  shows in the frame in which the last element took the root's place.
- Where the input ended while the heap still held elements, the outputs after that leave empty places in front of the
  list. Before the next bulk load, and only then, a frame of its own moves the list to the front of memory, in its order
  ("Heap is empty: the list moves to the front of memory, in its order, closing the empty places"). A "Things to try"
  input shows it: the slides' input without its last three values.
- The animation of the list sliding into the heap (Scope-shift 2026-11-23 (2)) is removed with its tests, as the list
  no longer moves into a separate heap. Animations of the array (the row of memory becoming the tree in a bulk load, the
  list moving to the front) are left to a second round, once the static view is approved.
- The playground relies on the order in which `start_next_run` moves the list to the front (memory order, empty places
  dropped), which it repeats. The replay check after the bulk load alone would not notice every change of that order,
  as two orders of the list can bulk-load into the same heap; a test pins the order against the iterator's. The code
  puts x into the freed place before the sift, the playground shows the sift first and x placed after it; as the sift
  works within the heap only, both orders lead to the same memory.
- As the in-place list is newest first, run 1's heap in the slides' example is 16 33 26 50, not the slides'
  16 26 33 50; "What the model assumes" in the notebook says so. The slides' example has 85 frames with the checkbox on
  and 34 with it off.

## Scope-shift 2026-11-24 (3)

The user: a caption that goes onto a second line moves the view below it; each caption is to stay on one line.
- Every caption has at most 110 characters (about 700 pixels of the widgets' bold 13 px text), with values of three
  digits and every M; a test traces the presets, the inputs of "Things to try" and inputs of repeating three-digit
  values with M from 3 to 12. Shortened: the draw into the list where the root was the heap's only element ("…, so it
  goes to the list, into the place the heap gives up"); the heap giving up its last place once the input is empty
  ("R is empty: the heap gives up its last place, and its last element 50 takes the root's place"); what the frame of
  a sift without its steps adds (" and sifts down" instead of ", then sinks until no child is smaller"); the order of
  a bulk load ("… Sift down the inner nodes from place 1 back to the root, place 0"); the end, whose run lengths are
  separated by spaces, as in the input ("Continue… and end: 11 elements in 2 runs (6 5), on average 5.5 = 1.4 × M").
- The caption has a fixed height of two lines (`calc(2 * var(--jp-widgets-inline-height))`, the line height ipywidgets
  gives an HTML widget), so that a caption that wraps in a narrow window does not move the view either; a caption that
  needs more lines scrolls within it. Checked in headless Chromium with the ipywidgets rules for an HTML widget.

<!-- notes below: skill never overwrites past this marker -->
