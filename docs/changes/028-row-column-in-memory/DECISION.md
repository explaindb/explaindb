# 028 — Row vs. column layout in main memory (animation)
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/195
---
## Context

The tutorial page "Row vs Column Layout" and the notebook `Data-Layout.ipynb` explain that a layout decides how much
data a query has to read. Students find the effect easier to grasp when they see it. The animation should show it in
main memory, where it applies just as on disk: memory is one linear address space, the CPU reads it in cache lines,
and a query that needs few attributes of many records wastes most of every cache line in a row layout. The look
follows the music video "LGTM" (Degenerative Pixels, made with Claude and three.js): kinetic word-by-word text,
objects from the topic's own world instead of diagrams, a header with counters that run through the whole piece,
labels like technical drawings, red hand-drawn notes, one green accent, continuous camera moves. The page must follow
the conventions for `visualizations/` (single offline HTML file, controls with test hooks, smoke tests unchanged).

## Decision

- One page `visualizations/row-or-column.html`, about 52 s with 7 stops, using the relation and query of the
  notebook: `books(title, author, price)`, `SELECT MAX(price) FROM books`. Eight books with fixed-width fields padded
  like SQL `CHAR(n)`: title 16 B, author 8 B, price 8 B, so 32 B per book; arrays aligned to 64 B; cache line 64 B
  (x86). The row layout reads 4 cache lines (256 B) and uses 64 B; the column layout reads the price array, 1 cache
  line, and uses all of it. The page says that this is simplified ("NOT TO SCALE").
- Beats: the query; memory as one long line; cache lines; scanning the row layout; the same table stored a second
  time, column by column (not re-sorted, so it does not look as if the database reorders data per query); the
  verdict, with a footnote that rows win when one whole book is fetched by position (1 cache line vs 3); back at the
  terminal with the result. Playback stops at the end.
- Memory is drawn as field blocks with byte ticks, folded at every 64 B like lines of text, so it stays readable on
  a phone. Green marks only useful data; the current word of the narration is set off in white, not green.
- three.js r160 draws the floor, the memory blocks, the scan head, the CPU cache and the camera moves, without
  post-processing. Header, narration, cards and notes are page text with the embedded fonts, so screen readers can
  read them; the narration is the `narration` element of the convention. Everything is a function of time, so the
  slider and Next show exact states.
- Vendoring: three.js r160 is bundled with esbuild 0.24.0 to the names the page uses, minified, and split into
  classic scripts of about 60 KB, so the Semgrep job does not time out; the page states its sha256. The fonts Archivo
  and JetBrains Mono are embedded as base64 woff2. `dependency_audit` does not see these copies; they are updated by
  hand by rebuilding the page with the build helpers.

## Consequences

**Positive:** the effect is shown where it matters for in-memory engines, with the numbers of the notebook's query;
the page works offline and is covered by the existing smoke tests without new tests.
**Negative:** the file is large (about 0.5 MB) and mostly vendored code; updating three.js is a manual rebuild with
helpers that are not in the repo; the model is simplified (fixed-width strings, aligned arrays, one cache line size).

## Out of scope & deferred

- A scene in which rows win (one whole book by position), beyond the footnote.
- A handwriting font for the red notes.
- The build helpers in the repo, for reproducible vendoring.
- Further topics in this style (B+-tree split, MVCC).

## Alternatives rejected

- Disk pages (the first draft): the effect is the same, but the course wanted main memory.
- Re-sorting the row strip into columns: suggests that the database reorders data at query time.
- One cell per byte: about 1.5 px per byte on a phone.
- Text as three.js geometry: bigger bundle and no text for screen readers.
- Bloom: the reference look uses little glow; leaving it out makes the bundle smaller and the code simpler.
- A video file: pages in `visualizations/` are interactive, can be scrubbed and are tested.
- Green for the current word, as in the reference video: green already means useful data.

<!-- notes below: skill never overwrites past this marker -->
