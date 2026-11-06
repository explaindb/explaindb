# 032 — Yannakakis: semi-join reduction as an animation
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/202
---
## Context

Lecture 04b ("What if an SQL Statement Returned a Subdatabase?", ResultDB) shows on slides 34–44 how a query with
an acyclic query graph computes its result subdatabase without the full join: the graph R–T, T–U, T–S becomes a
tree with root R; a semi-join reduction runs bottom-up (1. T′ = T ⋉ U, 2. T″ = T′ ⋉ S, 3. R′ = R ⋉ T″), then
top-down (4. T‴ = T″ ⋉ R′, 5. U′ = U ⋉ T‴, 6. S′ = S ⋉ T‴); afterwards every relation holds only the tuples that
take part in the join. The slides show this with blue fill levels. The course gets three.js animations in the look
of the House DBMS (decision 029) and the clock scan (031); a new page follows the rules for every page in
CONTRIBUTING (merge request !200, not merged yet) and the Content Security Policy of decision 030. The notebook
Result-DB computes the same reduction (Yannakakis' algorithm) on an example of its own.

## Decision

- A new page `visualizations/yannakakis.html` ("Yannakakis: semi-join reduction"): one file that works offline,
  with three.js (only the names it uses) and the fonts inside, built from a readable template outside the
  repository, as for 029 and 031. It covers slides 34–44; choosing the root and cyclic graphs come only as an
  outlook (the user).
- The picture (the user's choice: racks and robots): the tree is a building in cross-section, in the factory look
  of 029. R is on the top floor, T on the floor below, U and S on the bottom floor, left and right; the floor
  plates name the levels of the tree (root, inner node, leaves), as a floor here is not a layer of the DBMS. Each
  relation is a rack of parcels, the stored table, which stays as it is; in front of it a cart holds copies of all
  its parcels, and the reduction works on these copies (as reads send copies in 029). A parcel's tag shows its
  tuple.
- A semi-join X ⋉ Y: Y's robot writes the join values of Y's copies on paper (e.g. "b: 10, 11, 12, 14"); a runner
  carries the paper along the edge of the tree, by the stairs, to X's floor; X's robot checks each copy on X's cart
  against the list, the compared field lit on the tag and on the paper. A copy with a partner gets a small amber
  tick (cleared after the step); one without gets a red mark and drops into a bin "not in the result". How full a
  cart is, is the slides' fill level. Green marks only the copies left after step 6: the result subdatabase.
- The opening: the query graph of slide 34 as a chalk drawing on a board in the hall; R is picked as root (slide 37,
  "assume we picked this tree"), and the graph hangs down into the tree that becomes the building.
- The data is invented (the slides give only the names and fill levels), with the user's names R, S, T and U and
  4–6 tuples each: R(a) = 1, 2, 3, 4; T(a, b, c) = (1, 10, 20), (2, 11, 21), (3, 12, 22), (5, 14, 24),
  (2, 13, 20), (4, 11, 23); U(b) = 10, 11, 12, 14; S(c) = 20, 21, 24, 25. Every step removes something (6 → 5,
  5 → 3, 4 → 2, 3 → 2, 4 → 2, 4 → 2); 18 tuples become 8, which is the full join (2 rows) cut down to each
  relation's columns. It shows three reasons a tuple goes: it never had a partner (S 25); a neighbour across T
  removed its partner (U 12, through S); the root removed it (U 14 and S 24, only because R has no 5: why the way
  down is needed). The page works out which copy drops in which step by running the six semi-joins on its data.
- The SQL card shows `SELECT RESULTDB * FROM R JOIN T ON R.a = T.a JOIN U ON T.b = U.b JOIN S ON T.c = S.c`; a
  board lists the six steps as on the slides, the current one marked; the header names the step in words. The
  embedded fonts lack ⋉ and ‴: ⋉ is drawn as a shape and T‴ written T′′′; the narration says the steps in words,
  so that a screen reader reads them. The counter "tuples left" (also in `data-tuples-left`) goes from 18 to 8.
- Parts: 1 · The tree, 2 · Bottom-up, 3 · Top-down, 4 · The result; about 2:30 and 14 stops. Fast (×4): the walks
  on the stairs after the first one, and checks that find a partner after the first two of the film; every red
  mark and drop plays at normal speed.
- The card at the end: what the picture means; that every root and every order of the children gives the same
  subdatabase, only the work differs (the root node enumeration problem, 12 trees); that a cyclic graph is first
  folded into a tree by joins (slides 45–49); the sources (Yannakakis, VLDB 1981; the ResultDB paper,
  arXiv 2312.00638) and a link to the notebook Result-DB. Where the code differs is checked against the code before
  the merge request (today: system/ has the semi-join operator only; the reduction is in the notebook).
- The way there, as the user wants it for animations: the look on a small preview page, then a storyboard of real
  3D stills with the narration, then the motion; the user approves each stage. No new tests besides those that run
  on every page; nothing passes through anything, checked with a script with a stated tolerance, as for 031. The
  README gets a row for the page and names it among the pages that embed three.js and the fonts.

## Consequences

**Positive:** the slides' fill levels become single tuples that one can follow; the page shows what a semi-join
sends (only the join values) and why both passes are needed; it ends on the result subdatabase that ResultDB returns.

**Negative:** invented data with few tuples, so the fill levels are only roughly those of the slides; a building
for a tree whose root is chosen freely; another page to keep in line with the rules of !200; the build tooling stays
outside the repository.

## Out of scope & deferred

- Choosing the root as a part of its own (12 trees; the root and the order of the children change the work, not the
  result).
- Cyclic query graphs: folding them into a tree (slides 45–49), as a second page or part.
- A short video for LinkedIn; a link from the HTML slides of 04b; the same data in the notebook Result-DB (its order
  of the children would have to match the slides).

## Alternatives rejected

- Silos with fill levels, as the slides' bars: no single tuples, and it does not show what a semi-join sends (user).
- A post office with letters and sender lists: no tie to the other pages (user).
- The notebook's chain persons–orders–books: not the slides' tree (user).
- The query graph in the look of the join enumeration page (!194, a draft): the user wants the look of this page.
- 8–10 tuples per relation, closer to the slides' fill levels: smaller tags and a longer film (user).
- Computing the full join on screen: the point of ResultDB is that the reduction alone gives the subdatabase.

## Scope-shift 2026-11-03 (the look: bitmaps; work paused)

The look preview of racks and robots (the tree as a stepped building, a cart of copies per relation, the join values
on paper, a bin for the copies without a partner) did not convince the user: "we need a better idea". The user's
new idea, now being worked out: the relations as bitmaps, the keys only colours.

- Each relation is a small picture of pixels next to its node of the tree: a row per tuple, a column per attribute,
  the colour of a pixel its value (equal values, equal colours), each colour with a sign of its own (circle, square,
  triangle, …) so that colours need not be told apart alone. A column of lamps beside it shows which rows are still
  there: the slides' fill levels.
- A semi-join X ⋉ Y sends along the edge only a bitmap of Y's keys: a strip with a slot for every value the
  attribute can take, lit where Y has it. At X the compared column is outlined; a row whose colour is dark in the
  strip is marked red and goes dark, its lamp goes out.
- After step 6 the rows left are outlined green: the result subdatabase.

Open, to be settled with the user before the storyboard:
- a, b and c share one set of colours, so a red a looks like a red b: a family of colours for each attribute?
- flat like a diagram (the LGTM look) or more three-dimensional (pixels as cubes that fall out)?
- the parts of the first decision that still hold for the new look (data, steps, parts, length, the end card).

The work is paused here (the user); this merge request holds the plan so far, no page yet.

## Scope-shift 2026-11-05 (the look settled: keys as boxes; the page)

The open questions of 2026-11-03 were settled with the user, first on look previews, then on a storyboard of 15
stills, then on the page itself. What holds now, where it differs from the decision above:

- The look: flat like a diagram, not three-dimensional; no racks, robots, carts, paper or bins, and no crates (also
  tried). A relation shows its keys as boxes beside its node in the query tree: a row per tuple (its pixels joined by a
  rail), a column per attribute; only keys and join attributes, each value a colour, without signs and without numbers.
  Each attribute has a family of colours of its own (a blue, b orange, c violet), so no colour stands for two
  attributes. No column of lamps: the dark rows and the counter of tuples left show what is left.
- The tree: bigger nodes with the relations' names, primes as on the slides (T′, T″, R′, T′′′, U′, S′); thick edges; the
  join attribute in the middle of each edge. The six semi-joins are listed at the top right as on the slides.
- A semi-join X ⋉ Y: the compared columns keep their colours, the others turn pale (not grey, which would read as gone).
  Y's keys show as a key column: a slot per key Y has, without gaps; only the keys travel, no empty slots (the user). It
  travels along the edge, with the formula beside it (on a slanted edge read from the left relation to the right one, on
  the upright R–T edge from top to bottom; the bar of the sign towards X), then, with the camera still on the whole
  tree, on to its place beside X's boxes. Only once it has landed does the camera close in, so that the column does not
  grow on its way, and only then is it drawn out to the length of X's compared column, beside X's rows: beside each row
  a slot in the colour of its key if Y has the key, else an empty frame. Without the drawing-out, a key column beside a
  column of another length would not show which rows stay (the user). The semi-join is written over it (T ⋉ U = T′;
  U′ = T′′′ ⋊ U where the column stands left of the boxes). Rows beside an empty frame are marked red, a copy of the new
  name moves onto X's node, and the rows go dark grey (no red crosses).
- The data: as above. Only T repeats a key; R, U and S hold each key once, as the dimensions of a star schema around T
  (the user). T also holds values that R, U or S lack (as if these had been filtered before), so a, b and c are called
  join attributes, not foreign keys: otherwise no semi-join that cuts T down would remove a row (the review; the user
  chose the term). Holding keys twice in U and S, so that the full join, computed without the reduction, grows before
  rows drop out, was tried and dropped, and with it the scenes of that join and of the join on the reduced relations
  (the user). The six semi-joins each remove something: 18 rows become 8.
- The film (four parts: The tree, Bottom-up, Top-down, The result; 2:09, 19 steps, 21 stops; no fast passages, no voice
  yet): the query in SQL (without RESULTDB; Yannakakis' reduction does not depend on ResultDB), each relation's node lit
  for a moment as the caption names it (the user), and the tree it makes, each join lit in the query, on its edge and at
  its letter; what a relation shows, in two captions (in one, it would reach the leaves at the bottom of the tree);
  equal colours mean equal keys. Then the six semi-joins (bottom-up, a pause, top-down), the eight rows left outlined
  green, and the query on the original relations = the same query on the reduced ones.
- The narration's letters are as high as the smaller of 3.5 % of the window's width and 4.4 % of its height, between 23
  and 48 pixels (on the other pages 3.5 % of its width, between the same limits), so that on a laptop's window the
  narration covers no more of the picture than on a 1920 × 1080 screen. Each view is framed so that the narration covers
  no node, box, key column or letter, only edges, except for a moment while the camera moves (checked with a script at
  1920 × 1080, 1680 × 1050, 1512 × 982, 1440 × 900, 1440 × 790, 1280 × 800 and 1280 × 720); the tree stands a little
  right of the middle; while the camera is close to a node, the letters on the edges below it fade out. On a 4:3 window
  the top of T's boxes shows under the narration while the camera is close to R. At the end the tree stands far enough
  left that the card on the right covers none of it, on windows down to about 700 pixels wide and up to about 1.75 times
  as tall as wide (a test checks it); on narrower ones the tree goes as far left as it can, and on a phone, where the
  card is nearly as wide as the window, it stays where it stands on a wide window.
- The fonts: the embedded subsets have ′ and ″ but no ‴, ⋉ or ⋊ (checked in their character tables). ‴ is written as
  three primes (T′′′), as the decision above said; ⋉ and ⋊ are drawn, also on the card at the end.
- The card at the end cites Yannakakis (VLDB 1981), lecture 04b and the ResultDB paper in its SIGMOD version (Nix and
  Dittrich, Extending SQL to Return a Subdatabase, SIGMOD 2025) instead of arXiv 2312.00638, and links the notebook
  Result-DB. Left out for now: the root node enumeration and cyclic graphs.
- After the review by Simon Rink: the captions of the six semi-joins follow one pattern ("X sends its keys of A up to
  Y.", then "X keeps the rows whose A is in Y: n rows go, X′ is left."); "The way back down fixes the rest." is gone;
  the legend says node, not circle, and boxes, not bitmap (a bitmap holds one bit per key), and explains the primes
  instead of R′ alone; the colours of a family lie further apart (at least 21 in CIELAB ΔE between neighbours) instead
  of numbers on the keys (the user).
- A test of its own, unlike the decision above (the user, after the review): `YannakakisPageTest` clicks Next to the end
  and checks that the tuples left go 18, 17, 15, 13, 12, 10, 8 as the six semi-joins are done one by one; the button of
  part 3 (Top-down) starts at semi-join 4, with semi-joins 1 to 3 done and 13 tuples left. Next stops in each of the 19
  steps, in their order; and at the end the card leaves the whole tree free on windows from 1920 down to 700 pixels
  wide.
- Kept from the decision above: the six semi-joins (the page works out the drops from the data), the counter of tuples
  left, the README subsection and the mention of the page among those that embed three.js and the fonts.

<!-- notes below: skill never overwrites past this marker -->

The two look previews (the rejected racks and robots, and the first draft of the bitmaps) were removed once the page
existed; they are in the history of this branch (commit "docs(032): add the two look previews").
