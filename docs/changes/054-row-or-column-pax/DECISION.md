# 054 — PAX chapter in the row-or-column film
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/325
---
## Context

The row-or-column page (decisions 028, 035) shows in main memory why `SELECT MAX(price)` reads 4 cache lines of the
row layout but 1 of the column layout. The lecture (slides "10 Data Layouts": "PAX Layout", "Another PAX Layout",
"Mapping PAX to Blocks") presents PAX (Partition Attributes Across) as the compromise: it was invented for the pages of
a DBMS (e.g. 4 KB). Every tuple stays on its page, but inside the page the values are stored column by column. So PAX
reads and writes the same pages as the row layout, yet needs fewer cache lines when a query uses only some attributes.
Parquet, Arrow and others later took up the idea. The film should show this as a further step, still in main memory
and without a disk, and every statement it makes must hold at real page sizes, not only for its eight books.

## Decision

- **A new step "PAX layout"** (stop type `pax-layout`) between the column layout and the verdict, in the same world:
  the eight books of 32 B, cache lines of 64 B. The film has 8 steps.
- **Terms:** a page is the unit in which the DBMS stores, reads and writes a table; in the film a page has 128 B and
  holds 4 books (not to scale; really e.g. 4 KB). A cache line (64 B) is the unit in which the CPU loads memory.
- **PAX = the row layout's pages, sorted by column inside:** page 0 holds the titles of books 0–3 in one cache line,
  then their authors and prices in the next; page 1 the same for books 4–7. The PAX copy is laid down from the table
  card as a third strip, like the column layout (stored once more, not re-sorted). In the PAX step, the row strip and
  the PAX strip get page outlines (offset from the line outlines) that hold the same books.
- **Numbers:** `MAX(price)` reads 2 pages and 4 cache lines of the row layout, 2 pages and 2 cache lines of PAX. The
  header counters and the receipt name pages and cache lines; the order is that of the film: row, column, PAX. The
  footnote says what holds at any size: one whole book is on 1 page in the row layout and in PAX, on 3 in the column
  layout.
- **At real size:** after the scan, a schematic 4 KB page with 128 books shows that the prices of a page fill 16 cache
  lines completely, where the row layout reads all 64. So PAX needs as many pages as rows and as many cache lines as
  columns; the "half used" of the film comes from its small page only. The narration says so, so that it also
  reaches phones, where the declaration card is hidden. The spec card names "Partition Attributes Across" and that
  Parquet and Arrow use the idea.
- **Narration and voice:** two segments, the second one starting where the head reaches the first PAX cache line, as
  in the column step. The two new takes are made and measured first; the length L of the step follows from them.
  Everything up to 42 s stays; the verdict and the result move by exactly L, so the last clip keeps its rate. The
  nine existing takes are reused.
- **Process:** before the page code, 3–5 stills of the new shots (also phone portrait and landscape) on a local page;
  they settle the place of the third strip, the cache under the stamp, the receipt's height and the wording.
- **Tests:** the page tests' constants follow the longer film; new tests check the counters at stops of Next, the
  receipt's order and footnote, and that the header with its third counter covers neither the terminal (360 and
  390 px wide) nor the declaration card (768 and 800 px).

## Consequences

**Positive:** the page shows the three layouts of the lecture with the same books and the same query; the PAX
chapter's statements hold at real page sizes; the voice of the existing steps stays as it is.

**Negative:** the film gets longer (52 s + L) and the page larger; pages appear only in the PAX step, after two steps
that count cache lines only; the toy page makes PAX look like "half used", which the narration and the 4 KB page
have to correct.

## Out of scope & deferred

- PAX in the notebook `Data-Layout.ipynb` (own MR).
- A scene that fetches or inserts one whole book in all three layouts.
- The page size as a slider between row-like and column-like behaviour.
- PAX on the tutorial page "Row vs Column Layout" (own MR).
- A new README preview picture.
- A disk and disk blocks in the film.

## Alternatives rejected

- Arguing with disk blocks, as the slide "Mapping PAX to Blocks" does: the film stays in main memory (author).
- PAX as a dial between the row layout (pages of 1 book) and the column layout (one page of all books): true for the
  toy, but it hides why PAX was invented, to keep the row layout's pages.
- The slides' Employees example with k=6: the page's data are the eight books; switching would redo the film.
- A page of its own, or an epilogue after the result: the author asked to extend the film; it would end twice.
- Re-sorting the row strip into PAX: suggests that the database reorders data at query time (as in decision 028).
- Pages of 64 B or 256 B: one cache line per page reads as many lines as the row layout; one page of all books is
  the column layout.
- Padding each attribute's part of a page to 64 B: wastes space, and the scan still reads 2 cache lines.
- PAX numbers of the toy in the footnote (2 cache lines for a whole book): at real size it is one per attribute.

## Scope-shift 2026-11-26

The voice comes last (author). The PAX step gets a provisional length of 12 s; the stills and the page are built
without the two new takes. At the very end, the takes are made and measured; if they need a longer step, the step's
length L and with it the verdict, the result, the film's length and the tests' times are set once more from them.

## Scope-shift 2026-11-26 (after the stills)

The stills of the first version were approved with these changes to the decision above:

- **PAX is copied from the row layout's pages**, not from the table card: page by page, the books of a row page fly to
  the same page of PAX and are grouped there by attribute. This shows "the same pages, grouped by column inside";
  the row layout is not changed, so it does not look as if the database reordered data at query time.
- **The PAX step lasts 14 s for now and has three segments**; the third one goes with the schematic 4 KB page. The
  verdict and the result move by 14 s; the film lasts 66 s. The receipt's two extra lines move the stamp and the
  footnote 0.7 s later within the verdict.
- **"grouped by column", not "sorted by column"**: "sorted" reads as ordering by value. The first segment spells the
  abbreviation out: "PAX, Partition Attributes Across: …" (abbreviations are spelled out at their first use).
- **The CPU cache is empty during the verdict**: the PAX copies leave it, as the copies of each scan leave it before
  the next layout is read.
- **Footnote:** "Columns: a page per column" instead of "3 pages": in the toy, the column layout's arrays of authors
  and prices share a page of 128 B; a column store keeps each column on pages of its own.
- **Layout:** the cards (terminal, declaration card) start below the header, which grows with the third counter row
  and when the step's name wraps; on narrow phones the counters are set tighter; on low screens (a phone held
  sideways) the receipt is set smaller, so that it no longer runs far into the narration (on main it did by 78 px).
- The PAX step stays one step, although its subtitles fill four lines while the voice is silent.

## Scope-shift 2026-11-26 (pages from the start, real pages as a step)

The author found the PAX step confusing after watching it. Pages came in only with PAX ("introduced from behind").
The two red and green pages of 4 KB did not match the small example: other colors, "1 page" where the example has 2,
and no column layout. And the point was missing: in cache lines PAX is as good as the column layout, but PAX reads
every page like the row layout, while the column layout reads only the pages that hold the data the query needs. So:

- **Pages from step 03**, which is named "Cache lines, pages". A second segment says what a page costs: the
  database reads and writes the table in whole pages (128 B here, really 4 KB). Brackets mark each layout's pages
  from then on. The header counts pages from the row layout's scan on.
- **Page reads are marked in main memory**; no storage is drawn, as decided at first. When a scan loads the first
  line of a page, the page lights up as "read"; at the end of the scan, the pages it did not need are marked
  "not read". The second segments of the row and the column step name the pages (new takes).
- **One page per column in the small example:** titles on page 0, authors on page 1, prices on page 2. The second
  half of pages 1 and 2 stays free. The column scan reads 1 of 3 pages. This matches the real pages and the
  footnote "a page per column". The column layout moves right, clear of the CPU cache.
- **A new step "Real pages"** after PAX replaces the two schematic pages, so the film has 9 steps.
  - The same 512 books are shown in each layout: 4 pages of 4 KB each, all drawn the same size, 64 cache lines per
    page, in the colors of the small example.
  - The layouts are read one after the other. Lines read light up, and pages not read stay dark and are marked
    "not read". The row layout reads 4 pages and 256 lines (a quarter of them prices); the column layout 1 page and
    64 lines; PAX 4 pages and 64 lines.
  - The header counters, which count the small example, are dimmed from this step to the end.
- **The receipt shows the real size**: pages, cache lines and bytes of the 512 books, computed like the step
  before it, and ends with "column layout · 4× fewer pages". Only the pages single out the column layout.
- **Chapter markers:** the time slider is split into one segment per step, named on hover. On phones it gets a line
  of its own. It is part of this MR, by the author's choice.
- The film becomes about 80 s long. The voice still comes last, with 7 new takes; the other takes are kept and only
  moved in time.

Alternatives rejected in addition: the real pages as a third segment of the PAX step (24 s, and it would mix PAX
with the comparison of all three); a storage layer under main memory (the author chose marks in memory); keeping
the shared page of authors and prices in the small example (it contradicts the real pages); 256 books, 2 pages per
layout (the column layout's authors and prices would share a page again); the receipt with the small example's
numbers (it brings back PAX "half used"); buttons per chapter (9 do not fit on phones).

## Scope-shift 2026-11-26 (review rounds of the reworked film)

The author reviewed the reworked film passage by passage, writing notes on the page. The changes to the decisions
above:

- **The scene:** the row layout stands on the left, the column layout on the right, and PAX, the compromise between
  the two, in the middle; it is laid down last, copied from the row layout's pages. The CPU cache lies below the
  middle. It has a lighter plate and frame, so that it does not look like memory.
- **Pages read:** a page a scan reads gets a green frame when the read head reaches the first of its lines it loads,
  before that line is loaded. The page counter counts it from then on. First the page (input/output, I/O), then its
  cache lines (memory): the same two stages as on the real pages, where a frame comes first and then the lines read fill
  with green.
- **The real pages** are seen from straight above. On a wide screen each layout's 4 pages form a square of 2 × 2,
  side by side in the scene's order; on a tall screen each layout's pages form a row. They are titled with the
  layout's name only; their size (512 books, 4 pages of 4 KB per layout) is given once, in the figure's line.
- **The receipt** shows I/O (pages) and memory traffic (cache lines) in two columns. It ends with how much less of
  each the column layout and PAX need than the row layout. It has no stamp.
- **Cache lines are named in full** wherever they are meant: in the narration, the labels, the counters (now a table
  with a head row) and the footnote. "Line" alone could be taken for a row of the table.
- **Without:** the declaration card with the C structs, and the labels that mapped the memory onto them (books[n],
  title[0..3], …). The name of PAX and where it is used today (Parquet, Arrow) stand beside its title.
- **Also:** a step's name shows top left for a few seconds as the step begins (as in the external sorting film); a
  dark band lies behind the header; the table card is larger at the start, with lines between its columns and lighter
  heads; numbers are right-aligned (card, counters). The film has review clips (`clips=A-B,C-D`, `step=a-b`), as the
  B-tree, storage hierarchy and external sorting films have.
- **Abbreviations on screen:** the counters' row of PAX shows from when PAX's title appears (50.2 s), as the
  narration spells the name out. The receipt's column heads read "input/output" (pages) and "memory" (cache lines);
  under them its totals say how many times fewer the column layout and PAX read than the row layout, or "same".
- **The tutorial page** links the film's steps 06 and 07; changes to its PAX section beyond that link stay out of
  scope, as above.
- **Voice:** 8 new takes (6 of the 14 segments keep theirs), one of them redone. Step 03 and the PAX step grew by
  2.2 s and 1.0 s for the longer takes; the film lasts 83 s.

<!-- notes below: skill never overwrites past this marker -->
