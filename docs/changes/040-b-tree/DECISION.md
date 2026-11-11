# 040 — B-trees: an index above a warehouse
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/224
---
## Context

Slide set 06a ("B-Trees") defines the B+-tree with the bounds k and 2k, shows point and range queries, "B-tree
inception" (every subtree is again a root with subtrees), the invariants (slide "B-Tree Invariants and Rules") and the
splits of a leaf, of an inner node and of the root. The code is `system/indexes/btree.py`. The page
`visualizations/b-tree.html` shows this as a warehouse: the store is a rack on rails, a section per leaf, a parcel per
key; above it hangs the index, every inner node a room with holes in its floor and a chute from every hole down to the
next room or onto a section. The proposal with its two drafts is in merge request !224 (branch
`docs/040-b-tree-proposal`).

The first version of the page showed the chain of leaves as neighbourhood on the rails: the sections stood in key
order, so a new section from a leaf split had to stand right next to the one it split from, and robots pushed the
racks aside when there was no free place next to it. Feedback from a colleague showed that this misleads: whether the
rails next to a full section were free looked like a property of the tree; free places between sections made a room
seem to point to sections of two racks. In the code and on the slide the chain is pointers: each leaf points to its
left and right neighbour (Inv5), wherever they are stored.

## Decision

- **The chain of leaves is shown as pointers.** Every section keeps its place on the rails. A bright line on the floor
  in front of the racks links neighbouring sections in key order; where the next section stands elsewhere, the line
  rises over the sections in between as an arc in the air, above the robots' heads. Nothing is pushed aside.
- **A new section from a leaf split stands two places to the right of the section it split from**, in a free place at
  the border between two rooms of the lowest level. All free places lie at such borders, so at the start no room stands
  over a free place. The chute to the new section passes behind the chute it crosses.
- **Three inserts:** one that fits (6284), a leaf split (6434) and a split up to the root (7047). The start tree is
  built so that the last one splits a leaf, the room above it (R, explained step by step), the room above that and the
  root.
- **A second, short range query after the leaf split** follows the line from the split section to the new one and back
  to the old neighbour, so that the jump of a pointer is seen, not only stated.
- The page writes the place of every section and the links of the line for each state into data attributes, so that
  tests can check that the line follows key order and that no section moves.

## Consequences

**Positive:** the page shows what the code does: a leaf split allocates a new leaf somewhere and links it; the order
of the leaves on the rails and their order in the chain differ after a split. The confusing pushing is gone, and the
film is shorter.
**Negative:** the start tree and the inserted keys differ from the first version (6434 and 7047 instead of 6353, 6434
and 7023), and one of its leaves holds keys made up for the film. The chute to the new section is hidden for a moment
behind the chute it crosses. The arcs and the longer ways of the helpers add moving parts that must not pass through
anything.

## Out of scope & deferred

- Arrows on the racks instead of the line on the floor.
- A voice for the page (sound button and narration spoken).
- Per-page weights for the CI job that tests the pages.
- Delete and merge of nodes, as in the code.

## Alternatives rejected

- The new section at the end of the rails: the user preferred a free place nearby.
- Empty rack frames in the free places: the free places stay bare rails.
- Keeping four inserts: the split of an inner node is shown in the split up to the root instead.
- A new subtree for the room Q instead of moving one from its neighbour: more keys for the same effect.
- The only range query after the inserts: the slides show queries before inserts.
- The new section four to five places away: long ways for the helpers, more crossed chutes, a wide camera.
- A bulge of the line on the floor for a jump: lines over the same stretch overlap, and a flat strip flickers.
- A cart for the parcels: a new object and motion for little gain.
- The chute to the new section in front of the one it crosses: it would meet the arcs of the line.

## Scope-shift 2026-11-10

The first draft placed the new section of a leaf split two places away and showed the jump of the chain with a line
and arcs. Looking at it, the user decided that this mixes the linearization of the tree into the page, which belongs
in another animation and lecture. Revised decision:

- **A leaf splits only where a free place is right next to it.** The data is chosen so that this is the case for both
  leaf splits: the split leaf is the last one of its room, and the free place is the border to the next room. Nothing
  is pushed aside and nothing is carried past another section.
- **The leaves are linked by short chains with arrows in both directions** (next and previous), from each section to
  its neighbour in key order, also across a free place. At a leaf split the chain across the free place is replaced by
  the two chains to and from the new section. The line on the floor and its arcs are dropped.
- **No second range query**; the film has one range query, before the inserts, as on the slides.
- **Inserts:** 6284 (fits), 6045 (leaf split; 6042 is copied up) and 7060 (split up to the root; 7057 is copied up
  into R; R, Q and the root send up 6961, 6631 and 5797). Two leaves of the start tree get keys made up for the film
  (one key in the leaf from 6025, six in the leaf from 7048), so that both are full.
- When a room splits, its two halves stand side by side and never overlap.

## Scope-shift 2026-11-11

- **The page speaks in this merge request.** The voice, listed above under "Out of scope & deferred", comes now, made
  as decision 034 describes: Ming-3.0-tts-0.5B with its voice UK_George, word times from Qwen3-ForcedAligner-0.6B,
  one MP3 clip per caption (mono, 48 kbit/s), every take checked with a speech recogniser; the voice's code is that of
  the other pages that speak.
- **The film grows instead of the voice speeding up.** Where a clip was longer than its caption, the caption's time
  grows and the times after it move on, so that every clip plays at its own pace; no caption is shortened to fit its
  clip. After listening, caption 7 gained ", which in this case is an inner node". The film lasts 6:23 instead of
  5:08, and the page grows by about 2.6 MB.
- **An exception to two timing rules for pages that speak** (CONTRIBUTING.md, *What a new page has*): the film lasts
  6:23, not at most about four minutes, and its second caption begins 13.4 s after the first, not within about ten
  seconds. The rules keep the shared sound tests within their waits: at most 15 s (`FILM_TIMEOUT`), some of them
  counted in steps of the slider, a thousandth of the film. The page passes them today: in the merge request's
  pipeline 158259, all three `visualization_test` jobs passed, the shared sound tests included (the jobs took 437,
  282 and 206 s). A follow-up merge request will make these tests wait for seconds of film instead of steps of the
  slider.

<!-- notes below: skill never overwrites past this marker -->
