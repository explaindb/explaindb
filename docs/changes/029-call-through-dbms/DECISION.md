# 029 — Animation: a call travels through the DBMS
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/197
---
## Context

Lecture 03, "The Architecture of a DBMS", draws the course's DBMS as boxes (slide 10): an application on top, the
DBMS with its query optimizer, an MVCC store on a key-value store, and two persistence layers, (1a.) "data store" and
(1b.) "temp data". Slides 11 to 13 add the roles of the stores, the UML and the design principles: the DBMS is a
decorator (it is an ACID store and has one), the MVCC store inherits from a key-value store, and that key-value store is
not a layer. In the recorded lecture this point needed four explanations; the slide itself needs a footnote to say
that its arrows mean "calls go down, results come back up". Students confuse a layer, a base class and a decorator
because slide 10 draws all three as stacked boxes.

ExplainDB's code has the classes and interfaces of these slides (`PyDBMS`, `DBMS`, `ACIDStore`,
`TransactionalKeyValueStore`, `VersionedKeyValueStore`, `QueryableComponent`, `QEPQueryable`), but not all of the
design yet: the query optimizer and QEP execution exist only as interfaces in `system/` (parts are in the notebooks),
the DBMS does not forward transaction calls to the store it wraps, and the indexed MVCC store gets no persistence layer.

## Decision

- A new page `visualizations/call-through-dbms.html` in the style and with the build of the row/column page (decision
  028): three.js r160 and the fonts embedded, the controls of CONTRIBUTING.md, a pure function of time, about 66 s
  with 8 stops.
- It shows the design of slides 10 to 13, also where the code does not have it yet (the user's choice). A note on
  the page names the gaps of today's code: query optimizer and QEP execution only partly, in the notebooks; no
  forwarding of transaction calls by the DBMS yet; no persistence layer in the MVCC store yet.
- Picture rules: an object is a glass box with an instance badge; the classes it is made of are slabs stacked inside
  that one box; a reference (has-a) is a cable to another box, labelled with the field's name; the same interface
  has the same color everywhere. A call is a card that travels down a cable, a return value a card that travels up.
- Story: `prepare_query("SELECT * FROM R WHERE a = :C", ["C"])` and `execute_prepared_query(q, {"C": 42})` (named
  placeholder, as the API binds parameters by name; no transaction id, so the query runs in its own transaction);
  slide 10 turns into objects ("seven boxes, but (2.) and (3.) are one object"); prepare and execute each travel down
  and back up; inside the store box, (2.) is the base class `VersionedKeyValueStore` and `super()` stays in the same
  object, while (1a.) is another object; the DBMS and the store share the `ACIDStore` slab, and a call to the DBMS
  travels on to the store it wraps; an end card with layer = has-a, inheritance = is-a, decorator = is-a and has-a of
  the same interface, and slide 13's note "inheritance is basically the static variant of a decorator".
- The header counts calls between objects, down and up; "calls upward between objects" stays 0. Inside one object,
  a base class may call an override through `self` (e.g. `TransactionalKeyValueStore.update_object` calls
  `self.abort_transaction`, which runs the indexed subclass's version); a note says so, as one more sign that
  inheritance is not a layer.
- Two departures from slide 10, shown on the page: nesting on the slide means "part of the DBMS", in the animation it
  means "the same object" (slide 10's layout turns into objects in step 2); slide 10's arrow from the optimizer to the
  MVCC store is left out, as the optimizer has no reference to the store (the DBMS calls both).
- The page links to no lecture video. Every claim about the code (classes, base classes, fields, the gaps) is checked
  against `system/` with a scratch script before the merge request.

## Consequences

**Positive:** the difference between layer, base class and decorator becomes visible as "another box" versus "the
same box"; the page uses the names students find in `system/`.
**Negative:** the page shows calls the code cannot run yet; the note must stay true as the code grows (a later change
that completes the decorator or adds QEP execution should update or remove it). The page is large (about 0.7 MB,
mostly the vendored three.js) and duplicates the HUD and playback code of the row/column page.

## Out of scope & deferred

- Completing the decorator in the code (forwarding the transaction calls) and a persistence layer for the indexed
  MVCC store: code changes with tests, separate merge requests.
- A page on prepared queries versus string queries (SQL injection).
- A page on durability for the later lectures (journal flush, buffered writes, a crash at any moment).
- Shared code for the 3D pages, if a third one comes.

## Alternatives rejected

- Showing only today's code: exact, but many notes and lecture-05 material (`create_index` is the only forwarded call).
- Following `update_object` or `commit_transaction` through the DBMS as working calls: the DBMS does not forward them.
- `execute_unprepared_query`: deprecated in the code and in the lecture.
- Animating the UML of slide 12: static relations and no call.
- Slide 10 in 2D: "the same object" versus "another object" needs depth.
- Drawing (2.) as a box of its own with a cable: the misreading the lecture argues against.
- `WHERE a = ?`: a positional placeholder does not match an API that binds by name.

## Scope-shift 2026-10-30

The first version (glass boxes with class slabs, cables, a code card; prepare, execute, base class and decorator in
66 s) was too confusing, and the user asked for something bolder: a 3D ride through the DBMS as a landscape. The page
is rebuilt as "Query City", a ride of about 74 s with 8 stops and one event per stop:

- The query rides through a city at night: buildings are the DBMS's objects, roads are references, the store's
  floors are its classes. The application's terminal sends `prepare_query("SELECT * FROM R WHERE a = :C", ["C"])`;
  the DBMS headquarters (`PyDBMS`) sends it over a bridge to the optimizer, where a blueprint draws the plan tree
  (σ a = :C over a scan of R) with a hole at `:C` (a preview of later lectures); the plan is filed in
  `prepared_queries[0]`, and a ticket 0 goes back.
- `execute_prepared_query(q, {"C": 42})`: a copy of the plan gets the value (`bind_parameters` returns a new QEP;
  the original keeps its hole); the copy rides to the store building, a QEP-queryable MVCC store (design). Upstairs
  (3.), the reading rule: the query's own transaction TA 7 sees the versions committed before it began; downstairs,
  in the same building, (2.) holds the rows (`self.key_value_store`): r2 and r4 match, r5's newest version is TA 9's
  uncommitted work and stays invisible (invented example data).
- The DBMS hands back an iterator once; each `next()` fetches a row straight from the store. A map of the city ends
  the ride, with (1a.) as another building across the street whose road is closed (durability comes later).
- The decorator is not part of this ride; it is deferred to a later page. Tokens, a river and a monorail
  through the DBMS were cut to keep one event per stop. The note on the gaps of system/ stays, now also naming the
  lazy iterator (today's store reads a list).

## Scope-shift 2026-10-31

Query City was rejected as well ("nicht gut"); the user asked to plan more before building. The new page, "The House
DBMS", was agreed step by step: concept, figure proposals, a storyboard of 3D stills (look "evening shift"), then a
motion plan with a timeline and 35 frames. Both are scratch pages outside the repository.

- The DBMS is an old brick factory in cross-section. Its floors are the layers of slide 10: the application on the
  roof; the DBMS with its reception (the API) and the optimizer's mezzanine; the store, with (3.) on a gallery above
  the racks of (2.), one floor, as (2.) is a base class and not a layer; the basement with (1a.) and (1b.). A work
  level in a floor is a component; box robots do the work.
- Calls go down on paper, by hand, by the stairs; results ride the lift up. Every key-value store is the same rack:
  the plate of a slot is the key, its parcel the value; a read sends up a copy with a green tag.
- Two orders on invented rows (36 keys, six values of a): `SELECT * FROM R WHERE id = 2` brings up one copy;
  `SELECT a, COUNT(*) FROM R GROUP BY a` scans: copies of all 36 parcels ride up on a cart, the DBMS folds them into
  a cardboard bar chart, and only this aggregate rides to the roof.
- Two chapters: the film (about 97 s; order 1 runs straight on into order 2, whose known way down runs at four
  times the speed), and order 2 on its own (about 61 s; its way at normal speed; nothing of order 1 in the house),
  chosen with two buttons or `?q=2`.
- (1b.) stays empty: these orders need no intermediate results. (1a.) waits behind a cage: the store does not
  persist yet. The legend at the end says both and names the gaps (optimizer and plan execution only partly, in
  the notebooks).
- Prepared queries, transactions and the decorator are left out of this version (the user's choice) and deferred,
  together with the end card on layer, base class and decorator.
- Controls beyond CONTRIBUTING.md: the two chapter buttons, a full-screen button (key F). Next stops where a
  caption is fully shown, as on the row/column page.
- Deferred: fewer draw calls and lights for phones (instancing; the user's choice). The page carries the
  Content-Security-Policy that decision 030 gives every page (merge request !198).

## Scope-shift 2026-11-01

The user asked for a prepared query, whose EXECUTE skips the optimizer, shown in two orders: PREPARE, then EXECUTE.
Both were agreed through storyboards of 3D stills (scratch pages outside the repository).

- Order 3 is `PREPARE q1 AS SELECT * FROM R WHERE id = ?`. It goes the known way to the optimizer, which draws the
  plan once, with a hole (lookup → id = ?). The plan does not go to the store: it goes back to the reception, which
  files it in a key rack, like a hotel reception's: a small key-value store, the plan under its name
  (`PyDBMS.prepared_queries`). The reception hands back the name on a green card, q1, a result that rides the lift
  up; the application keeps the card. In `system/` the name is a number (the first is 0).
- Order 4 is `EXECUTE q1 (id = 7)`: only the name and the key go down, no query text. The reception reads q1,
  copies the plan in q1's cubby (its compartment) onto a gold VIP ticket and writes the key into the hole by hand
  (? = 7). This departs from `system/`, where the DBMS lets the optimizer fill the parameter in
  (`query_optimizer.bind_parameters`), though without planning anew; the legend says so. The runner does not go to
  the optimizer: a red carpet between gold stanchions and red ropes leads to a small VIP lift behind the reception,
  straight down to the gallery of (3.). From there order 4 runs as order 1 (get(7), one copy, up by the big lift).
- For the carpet, the reception moves two units to the left; the DBMS floor's window, the safety board and the
  crates move as well, and the floor gets an opening for the VIP lift. Orders 1 and 2 pass the reception in front
  of it, and their runners wait at the gallery's left end once they have handed over their plans.
- One film of about 2:38 with four orders; the known ways of orders 2 to 4 run at four times the speed. The versions
  of an order on its own, at normal speed, are dropped: the user found their separate timelines confusing. Four
  buttons jump to an order's start (also `?q=1` … `?q=4`), and the slider is cut into one segment per order, like the
  chapters of a video, with the order's name above the pointer.
- A check (a scratch script outside the repository; a person reads its list) plays the film in steps of 0.1 s and
  reports where a robot, the cart, the chart or a prop overlaps a fixed object, the cart or a robot. It found the
  cart going through the inner stairs and a hand truck, the chart through the press, a bench and a drum, the
  optimizer in its drafting board and runners in railings and a desk; routes and places were changed. It missed a
  robot walking through the waiting cart (the user saw it) and, until it also tested props against robots and thin
  boards, copies flying through the keeper, plans passing through the key rack's shelves and the chart standing in
  the press's flat cardboard (a review found them). All of these were fixed (the cart, for one, now waits further
  along the aisle, clear of parcel 2). What the list still shows, read and accepted: the robot pushing the cart at
  its handle, props lying on furniture or held close to a robot, and runners or props grazing a stair tread for a
  single step.
- Start-up: in a browser without a usable GPU, as in the page tests, the GPU is emulated in software, which prepares
  a shader program only when it first draws with it. The first picture then kept the page from answering clicks for
  over a second, and under load for over the tests' 5 s. On such a GPU the page now prepares its programs, then
  uploads its textures and draws once with the materials of the first shot, a few per frame, into a single pixel; it
  answers clicks at once and shows the picture after about 4 s, and `data-ready` on the stage marks the end of this
  warm-up. Meanwhile autoplay already runs over the empty stage, and the page tests for Play and autoplay end before
  the first picture; holding autoplay back would bring back the tests' time-outs. With a real GPU nothing changes.
- (3.) no longer drops a slip for (2.): it folds the plan it got into a paper plane at the gallery's rail and throws
  it; the blue plane, the plan's drawing on its wings, glides down in a curve into (2.)'s hands, which unfold it and
  read the plan (the user's idea). In order 4, (3.) puts the VIP ticket on its desk and folds the plan it wrote down
  from it (id = 7).
- More posters, the user's ideas and choices, all drawn on canvases (no picture is loaded): "IN CODD WE TRUST" by
  the DBMS's workbench; "PERFORMANCE FOR NOTHING AND THE CONSISTENCY FOR FREE" with a guitar after an 80s music
  video, in the stairwell at the counter's height, where a new shot looks down the stairwell as order 1's runner
  comes down; "MAY THE INDEX BE WITH YOU" (a B+-tree as a constellation) on the roof; "VACUUM" (an arcade game in
  which the dead versions of a tuple are eaten) by the MVCC store's gallery; "I'LL BE BACK(UP)" by the persistent
  stores, beside "KEEP CALM", which moved out from behind a rack. "NO NULLS" got a WARNING! band and moved above the
  inner stairs, which hid it. Rejected poster drafts: a hand on the guitar, a hotel, a deadlock patch, O(1).

## Scope-shift 2026-11-02

A review of the merge request found the house's labels at odds with slide 10 and one step unexplained; the user
decided:

- The whole house is the DBMS, as on slide 10, whose DBMS box holds the optimizer, (3.) and (2.); the application
  stays on the roof. The slide drawn at the start now nests them in the DBMS box, and the top floor's sign says
  QUERIES (API · QueryableComponent · QueryOptimizer) instead of DBMS; the sign on the roof names the house (DBMS
  WORKS). This replaces the first departure above: nesting means "part of the DBMS" in the house too, and only "one
  floor, one object" is the animation's own. One departure is new: the persistent stores (1a.) and (1b.) are in the
  house's basement, while slide 10 draws them outside the DBMS box. The basement stays, though no order uses it: the
  house may become a thread through the course, with more animations (durability).
- The reception's stamp says which call of the API an order is, and so where it goes next: UNPREPARED
  (`execute_unprepared_query`) for orders 1 and 2, PREPARE (`prepare_query`) for order 3; both go on to the
  optimizer. Before, it said "API ✓", which left open what was checked. The caption at the first stamp: "The API
  sees an unprepared query: up to the optimizer for a plan." The stamp does not claim that the SQL is checked:
  `PyDBMS` passes the text on, and the optimizer reads it.
- Every plan is titled QUERY PLAN: on the optimizer's drafting board, in the key rack, on the VIP ticket and on the
  paper planes.
- The store floor's signs are written as on the slide: (3.) MVCC Store, (2.) Key-value Store.

## Scope-shift 2026-11-03 (the name ExplainDB)

Every animation shows the project's name (the user; the rule is in CONTRIBUTING, !200): the header begins with
"ExplainDB ·", and the legend card closes with "ExplainDB · github.com/explaindb/explaindb", a link. The eight
wooden crates in the floors carry a shipping stamp, "ExplainDB" over "THIS SIDE UP ↑", on their fronts, and every
third parcel in the racks a fainter one on its lid.

<!-- notes below: skill never overwrites past this marker -->
