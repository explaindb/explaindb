# 031 — Clock scan: queries ride one scan
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/201
---
## Context

Lecture 04a has one slide, "Clock Scan", after QPipe: scan the table continuously; serve several queries at the same
time; attach and detach queries at any point in time; "if a query attaches at 3pm it has to detach at 3pm". The
course gets three.js animations in the look of the "LGTM" music video for its topics (decisions 028 and 029). A new
page follows the rules for every page in merge request !200 ("What a new page has", not merged yet) and the Content
Security Policy of decision 030.

## Decision

- A new page `visualizations/clock-scan.html`: one file that works offline, with three.js and the fonts inside,
  built like the House DBMS page (029) from a readable template outside the repository.
- The picture is a clock dial. The table's 12 rows sit at the 12 hours (row k at k o'clock, with values such as
  a = 42); 12 o'clock is the end of the table, where the scan goes on with row 1. There is one hand: the scan. It
  turns all the time, as on the slide, and is grey while no query is attached.
- Queries (e.g. Q1: a = 42, Q2: a < 10, Q3: all rows) arrive at different times and clip onto the hand where it
  is. The hand at hour k means that row k has just been read, so a query that attaches at 3 reads rows 4 … 12 and
  1 … 3 and unclips after row 3, one full turn later ("attaches at 3 o'clock, detaches at 3 o'clock"; no am/pm).
  Several queries ride at once; every row the hand passes is checked against each attached query, and a matching
  row sends a green-tagged copy into that query's bag, which stands beside the dial. Row 2 holds a = 42, so Q1
  (attached at 3) finds it only after the hand has passed 12: why a query has to go round once. If 12 tags in the
  bag of Q3 clutter the picture, it shows a count instead.
- The comparison without the clock scan is told by numbers, not by more hands (the user: only one hand, the queries
  hang on it): "rows read" counts the rows the hand reads while queries are attached; a second counter counts the
  rows the same queries would read with a scan each, 12 per query (e.g. 19 against 36).
- The queries are told apart by label and shape; green marks only matching rows (one accent, as in the LGTM look).
  The page names its sources: the circular scan of QPipe (Harizopoulos, Shkapenyuk, Ailamaki, SIGMOD 2005), as on
  the slide, and the name ClockScan from Crescando (Unterbrunner et al., VLDB 2009).
- The page follows every rule of "What a new page has" in !200: header with the name of the step, the controls in
  their order, Next from stop to stop, the keys, the narration word by word, a card at the end, nothing passing
  through anything (checked with a script; the merge request states how and with which tolerance), start-up on a
  GPU emulated in software (`data-ready`), autoplay, the URL parameters `t` and `paused`, test ids and
  `data-scene`. The counters are also written to `data-*` attributes (e.g. `data-rows-read`).
- The way there, as the user wants it for animations: the look of the dial on a small preview page, then a
  storyboard of real 3D stills with the narration of each shot, then the motion; the user approves each stage. No
  new tests besides the tests that run on every page (as for 029). The README gets a row for the page and names it
  among the pages that embed three.js and the fonts.

## Consequences

**Positive:** the slide's three points become one picture: one scan that never stops, queries that join it at any
hour and leave one turn later, several answered at once; the reason for the full turn (a match before the hour of
attaching) and the saving (19 against 36 rows read) are on screen.

**Negative:** with one hand, the cost of a scan per query (more reads, competing for the disk, later answers) shows
only as a number. Twelve rows are few. The build tooling stays outside the repository, as for 028 and 029.

## Out of scope & deferred

- Crescando's updates and its index of the queries; queries with more than one condition.
- A short video for LinkedIn; a link from the HTML slides of lecture 04a.
- Scans without the clock scan as hands of their own (see below).

## Alternatives rejected

- A sushi conveyor, a circle line, or the racks of the House DBMS as the picture: the user chose the dial.
- Pages on the dial (as the slide's P0 … Pn): what matters is the hour at which a query attaches, not pages (user).
- A hand for each query's own scan, for the comparison: the user wants only one hand, with the queries on it.
- A hand that stops while no query is attached (as in QPipe): the slide says the table is scanned continuously.

## Scope-shift 2026-11-02

The queries filter on different attributes (the user: otherwise one could use an index). Each row carries three
attributes, a, b and c, and each query asks about another one, e.g. Q1: a = 42, Q2: b < 10, Q3: c = 'red'; no single
index answers them all, so one shared scan is the way to serve them. Q3 no longer asks for all rows. The narration
says once why the queries do not use an index.

## Scope-shift 2026-11-02 (the rotunda)

The dial did not carry the idea (the user, after several look previews); the picture is now the user's own, closer to
the House DBMS (029):

- A rotunda: a rack bent into a circle, with 12 bays and one value per bay, a parcel with a tag (a, b, c; colours in
  quotes, e.g. c 'red'). There are no rows: the clock scan works on a key-value store as well, so the bays hold
  values only (the user). The hall has the factory look of 029.
- Around the rotunda runs a conveyor, and on it one scan car with a reading lamp: the scan, which never stops. A
  robot holding its query on a card waits at the rail and jumps onto the car wherever it is when the robot comes.
  All riders see the same parcel at the same moment; a rider whose query matches takes a copy of the parcel, as in
  the key-value store of 029, and its card lights up. After 360° the robot jumps off where it got on.
- One car, not robots that jump onto the belt where they stand: those would ride at different places and each read
  every value itself, which is a scan per query again, not the clock scan (the user chose the car).
- Two kinds of shot: from the side, at eye level (the rack, the belt, the robots), and from above, where the 12
  bays read like the hours of a clock and the 360° shows.
- The comparison stays a pair of counters (values read by the car against a scan per query).

Rejected in this round: the clock dial with parcels around it (looks A, B and C, and B with cards on the hand,
robots on scissor lifts and carts under the clock).

## Scope-shift 2026-11-02 (the car as the hand)

After the first stills of the rotunda (the user):

- The scan car stands across the belt, like the hand of a clock; the robots on it stand side by side and face the way it
  goes, each with its crate behind it. The belt is wide enough for three of them. A robot keeps its place across the
  car (its lane) all the way round.
- The floor of the rotunda is the dial of a station clock: white in a dark rim, bars for the minutes and the hours, and
  the hours as numbers. Its hand turns on the pillar in the middle and runs over the car, where it is the car's roof,
  of tinted glass so the riders show from above. The red disc on the hand of one railway's clock is left out: that
  design is protected.
- The car never stops: robots jump on and off while it moves, and they get on at different times (Q1 at 3, Q2 at 7,
  Q3 at 10).
- Getting on and off is shown once from the side and once from above. From above, each rider's way so far is a strip in
  its lane, from the hour it got on to the car, so the 360° of every robot shows.

## Scope-shift 2026-11-02 (storyboard and motion)

After the storyboard of ten stills (the user approved it and the points below):

- Q2 gets on at 6, not at 7: otherwise its getting on would fall on Q1's match at 7. The counters stay at 19 values
  read against 36.
- The film runs on the hour of the car: slowly where something happens, four times as fast in between (with the badge
  `▶▶ ×4`). The camera moves between three views instead of cutting: from the side ahead of the car (the riders face
  it), from further out where robots get on and off, and straight down onto the clock. The numbers of the hours lie
  outside the dial's rim, large, so that the dial itself stays as on a station clock.
- On the car, a walkway runs in front of the riders, open at the outer end: a robot jumps on there while the car
  moves, walks to its lane and keeps it all round. The empty crates ride the car from the start. To get off, a robot
  takes its crate on its back, walks out along the walkway, reads its last value at its hour (a match still flies into
  its crate) and jumps straight out from the car a moment later.
- The robots walk in from the hall, and out of it with their crates: there is no place where the results are collected
  (the user's choice).
- The reading lamp hangs from the roof, over the bay just read. The four parts of the film: Q1 gets on, two more,
  once round, 19 against 36.

## Scope-shift 2026-11-02 (after the code review)

- The robots come into the hall by a door and leave by it, through a short dark corridor behind it, so that they
  never appear or vanish in sight, on any shape of window. Q1's door is on the right, Q2's at the front, Q3's on the
  left.
- A robot reads its last value at its hour and jumps off just after (if that value matched, once the copy is in its
  crate), straight out from the car; so it lands a little past its hour. Its ring seen from above closes at its hour.
- The page has its own three.js bundle with only the names it uses (26), built as for 029.
- The counters are written to `data-values-read` and `data-scan-each` (not `data-rows-read`); the URL parameters are
  `t`, `paused` and `q` (a part, 1 … 4). `data-fonts` tells whether the textures' text uses the embedded fonts.
- Nothing passes through anything. A script outside the repository (as for 029) goes through the film every 0.01 s
  and counts an overlap only if it is deeper than 0.02 units (a robot is about 1.5 units tall). It tests every moving
  thing as a box that turns with it; the dial, its rim, the conveyor, the pillar and the hub as solid rings; the
  corridors' walls; the floor; and, between two samples, the paths of all corners, so that a thin card slipping
  through a thin door frame between two samples is seen too (unless the two cross only edge through edge). It finds
  no overlap. A self-test plants one fault of each kind, and the script finds each.

## Scope-shift 2026-11-03 (the name ExplainDB)

The user wants the project's name in every animation. Here: the header begins with "ExplainDB ·" (small, in the
header's own style); the card at the end closes with "ExplainDB · github.com/explaindb/explaindb", a link; and the
dial carries "ExplainDB" over "SAARBRÜCKEN" as a station clock carries its maker's name, between its middle and
12; the parcels carry a faded shipping stamp, "ExplainDB" over "THIS SIDE UP ↑", on both ends. The rule for
every page (header and card) goes into CONTRIBUTING (!200).

<!-- notes below: skill never overwrites past this marker -->
