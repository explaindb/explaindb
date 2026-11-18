# 045 — The storage hierarchy: a mine shaft under the House DBMS
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/249
---
## Context

Slide set 08 ("Storage") explains how far away data is: registers, caches, main memory, an NVMe SSD and a hard disk,
each slower and bigger than the one before. The slides count CPU cycles of an Intel Core Ultra 9 285K (5.7 GHz, one
cycle 0.175 ns) and stretch time so that one cycle takes half a second ("human time", after Gustavo Duarte): L1 4
cycles (2 s), L2 17 (8.5 s), L3 84 (42 s), DRAM 570 (285 s), SSD 285,000 (39.6 h), hard disk 57,000,000 (330 days);
sizes 640 B of registers, 48 KB, 3 MB, 36 MB, 32 GB, 2 TB. Numbers this far apart are hard to feel. The House DBMS
page (029) already shows the DBMS as an old brick works with a basement; this page goes down from that basement.
It follows the rules of !200 ("What a new page has") and the Content Security Policy of 030. Plan, looks and a
fifteen-still storyboard were agreed in the proposal merge request !248 (`PROPOSAL.md` there, with its previews).

## Decision

A new speaking page, `visualizations/storage-hierarchy.html`: the House DBMS of 029 in cross-section, standing in
Saarland, with a mine shaft under its basement down to the Earth's centre.

- **Depth is time, strictly to scale.** The basement floor (5 m below ground) stands for the CPU core. A cage runs
  at one constant speed (1.6 km/h in human time, shown on a digital display), so every round trip takes exactly the
  access time of its level: one cycle is (6,371 km − 5 m) ÷ 57,000,000 = 11.2 cm of depth, and the hard disk is
  reached at the Earth's centre.
- **Values and crates.** A value is a parcel of the House page; a crate is one cache line (64 bytes) holding eight
  of them, explained in its own shot. Each level is a block of crates round the shaft, as many as it holds bytes
  ÷ 64, in whole crate places; the top levels are flat and wide (L1 one crate high, 34 m wide). The registers are a
  tray of 80 parcels under a hatch in the basement floor.
- **The House, reused.** Its scene is read from 029's template when the page is built, with a few patches that are
  checked to apply exactly once (openings in the foundation, things moved off the shaft and the hatch).
- **The ground** is a geological section for Saarland as checked against published sources (coal measures to about
  3 km, granite from about 5 km, the end of the crust at about 30 km), with three holes for comparison (the deepest
  Saar coal shaft, the borehole Saar 1, Kola). The NVMe SSD lies just below the crust, at 31.86 km.
- **Every depth is given below the Earth's surface:** depth signs at the shaft, the header, and a depth ruler on the
  right edge whose ticks follow the picture's scale and whose marker follows the cage.
- **Pickups.** At each level a crate rides out of the top layer into the shaft under the cage and a winch lifts it
  through a hatch in the cage floor; from the SSD the robot brings a whole page of 4 KB, a pallet of 64 crates.
- **The hard disk is a platter,** like a real one keeping its data on its two faces, one layer of crates on each:
  57,148 tracks per face, 180 km across, 2.4 km thick (a real platter's proportions). It stands upright right behind
  the shaft so that the cross-section shows it whole; it turns (7,200 rpm: once every 276 days in human time). Its
  read head, built like a real one, is where the shaft ends, at the Earth's centre; the robot arrives there, and the
  head lifts the page's crates onto a chute into the cage.
- **The film** is a pure function of the playback time; one function drives the cage, the camera, the stopwatch,
  the fast-forward badge (which shows the slides' factors on arrival) and the ruler. At the end the camera rises to
  Saarland from above and to the Earth with a quarter cut away. Narration in English with the page's voice.
- **Tests** read the page's numbers from `data-*` attributes: the slide table and the exact scale; every block and
  the platter recomputed to hold exactly their crates; boxes of the drawn objects that must not meet (the House
  against the shaft, the tray against L1, the pickups); the stopwatch, depth and speed after every ride; the cage's
  constant speed over a sweep of the slider; the badge and the frozen stopwatch during pickups.

## Consequences

**Positive:** the hierarchy's distances and sizes are shown to scale in one continuous picture, from 11 cm to the
Earth's centre, in the House DBMS's own world; the depth ruler and the stopwatch keep the viewer oriented across seven
orders of magnitude; the numbers are checked by tests against the slides.
**Negative:** a long film (about 3:30 to 4:30) whose long rides must be carried by the stopwatch, ruler, strata,
signs and voice; the top levels are flat and wide; the cage is big (6.6 m) to take a pallet; reusing the House's scene
ties the page to 029's template (caught by the checked patches and the tests at each build) and brings its lights and
textures to slow machines; depth precision at kilometre scales needs care (local groups, polygon offsets); geology
and the platter are simplified.

## Out of scope & deferred

- The step from the SSD to the platter: open, to be judged in the moving film.
- Filling the caches on the way up (copies of the crate in DRAM, L3, L2, L1).
- The DBMS's buffer in the same basement; several cores; network storage as further levels.
- A photo texture for the globe; a short video; a still image for slides 08; "big drives stack about ten platters".

## Alternatives rejected

- Planets in space (distance as time, volume as size): the hierarchy belongs under the House DBMS.
- A lift at walking speed: the hard disk would lie 23,750 km deep, through the Earth.
- Depth not to scale, or on a log scale: loses the point of the film.
- Crates of 0.3 m with values an eighth of them: values must look as on the House page.
- Crates of 4 KB: L1 would hold just 12.
- Random against sequential access on the hard disk: dropped.
- Naming a town or district for the house; a simplified house.
- The hard disk as a block of crates, as a platter lying flat (cut in half), with crates through its whole volume, or
  with its spindle at the Earth's centre (the robot should arrive at the read head).

## Scope-shift 2026-11-16

At L1 the cage rides 0.45 m (4 cycles), but a crate of 2 × 2 × 2 parcels was 0.92 m high: the cage stopped on top of
the crates and needed a hatch and a winch, which read as a second mechanism with a meaning of its own. Decided with
the user (sketch of three variants):

- **A crate is flat:** the eight parcels stand side by side, 4 along the cut and 2 deep, in a tray open at the top,
  as high as a parcel: 2.36 × 0.44 × 1.08 m. Its long side, four values, faces the camera.
- **A level is where its crates stand:** the cage stops at the level's cycles (depth = time, unchanged) with its floor
  level with the floor of the level's top layer; the robot reaches into the rack and pulls a crate straight across
  into the cage. No hatch, no winch.
- **L1 lies right under the basement floor:** its top layer ends 7 mm under it; the floor is a thin plate over it.
- The other levels move 0.44 m up; the blocks get more, flatter layers (L1 3, L2 15, L3 84); the shaft is three crate
  places wide (7.08 m); a page of the SSD or the disk is a pallet of 2 × 4 × 8 crates.

## Scope-shift 2026-11-17

What the page does now differs from the decision above in these points:

- **Copies on the way up are in scope:** as in the textbook (inclusion), the cage leaves a copy of its crate in every
  faster level it passes, and a page from the SSD or the hard disk leaves one in main memory; the copies stay as green
  marks. The film also unloads at the floor: the robot puts the fetched value into a register (in detail after L1).
- **No voice yet:** the page has captions only; the voice is deferred to a later merge request.
- **The end:** the film zooms out to the Earth with a quarter cut away; the view from above onto Saarland was dropped.
- **The platter:** about 80,200 tracks per face, about 248 km across and about 3.3 km thick (one layer of crates on
  each face, as decided, with the flat crates of 2026-11-16).
- **Tests:** the "boxes that must not meet" are checked for the register tray against L1 (the tray lies inside the
  room L1 leaves for it); the House's patches are checked when the page is built. The cage's constant speed is checked
  over a sweep of L3's whole trip (the stopwatch never runs back and stands still during the pickup, the depth never
  jumps).

<!-- notes below: skill never overwrites past this marker -->

Not covered by a test, on purpose (2026-11-17): the cage's cable in two pieces. Its end jittered on the cage roof
because the graphics card places a mesh thousands of kilometres long only to about half a metre; the tests' software
renderer does not show this, so the split follows the page's rule for giant geometry near the camera instead: a short
piece near the camera (`CABLE_NEAR`), as the shaft's walls and guides are split into pieces growing tenfold from both
ends (`tenfoldPieces`).
