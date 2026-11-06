# 038 — The Yannakakis page speaks its narration
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/216
---
## Context

The Yannakakis page (decision 032, merge request !202, not merged yet) shows its narration as subtitles only. Three
pages already speak theirs with a synthetic voice (decisions 034–036), and CONTRIBUTING (*Voice*) states the rules for
a page that speaks. The voice tools lie outside the repository, next to the page build (`voice.py`, `check_voice.py`);
`voice.py` reads a template's captions from its `NARRATION` block, but only entries whose times are numbers, and the
Yannakakis page computes its caption times from the film's timing. Its captions were timed for subtitles, so some are
too short for the voice: a clip may play at most 1.15 times as fast.

## Decision

- The page speaks its narration as the other three do: the same model, voice (Ming-3.0 TTS, UK_George), aligner and
  48 kbit/s MP3; the voice code is taken over from the House DBMS page, with sound off at load, the sound button, key
  M, the hints, the words lit as the voice says them, and the voice named on the card at the end. The hint sits at the
  bottom, above the controls on the right, as on the row/column page (the user).
- `voice.py` takes a template's captions in the order of the page's `voice.json` when its `NARRATION` block holds no
  caption with times written as numbers, and stops with an error if neither gives captions or if only some are found;
  the page checks at start-up that each clip belongs to its caption. The other three pages are not affected.
- Spoken texts where the shown text would be read wrongly: primes as words ("T double prime"), the attributes as
  capitals (A, B, C). Every take is transcribed with Whisper (`check_voice.py`) and listened to by the user, as in 034.
- Where a clip is too long for its caption, first another take; then only that caption's time is lengthened (an intro
  passage, the pause after the way up, or one semi-join: a hold after its key column has landed or before the camera
  goes back), so the other semi-joins keep their pace (the user).
- The page is listed with the pages that speak and with those that have parts, so that the shared voice tests run on
  it; new tests check that the card at the end names the voice and where the hint sits.
- This merge request is stacked on !202: a change to the captions or the timing in !202's review means new takes or a
  new fit here; a conflict in the built page is resolved by rebuilding it.

## Consequences

**Positive:** all four three.js pages speak; the voice gives the semi-joins a pace one can follow without reading.

**Negative:** the page grows by about 0.6 MB; the film grows where a caption has to be lengthened; another copy of the
voice code to keep in line with the other three pages; it depends on !202.

## Out of scope & deferred

- A voice for the robot variant of the page (a preview outside the repository).
- A voice in another language.
- One shared script for the voice code of all pages (each page keeps its own copy, as decided in 034).

## Alternatives rejected

- The page computing its timing from the clips' lengths when it loads: unlike the other pages, more code, and the
  timing would no longer be visible in the template.
- Shortening captions to fit the voice: the user chose to lengthen the film.
- Parsing computed caption times in `voice.py`: riskier for a tool the other pages share; the order from `voice.json`
  with the page's start-up check is enough.
- Renaming the page's `NARRATION` so that `voice.py` does not find it: hides the captions from the tool by accident.
- The hint at the top centre (clock-scan, House DBMS): it would cover the root R of the tree.

## Scope-shift 2026-11-05 (a robot carries the key columns)

The user, after a preview: the key columns no longer float through the air; the box robot of the House DBMS page
carries them, and this merge request brings the robot together with the voice.

- The robot walks on the edge with the key column under its arm, beside it; it looks half towards the camera, so its
  visor and eyes show; it walks on to the column's place beside X's boxes, lets go, turns its back, so that
  "ExplainDB" on a light plate on its back shows, walks off outwards and fades while the camera closes in on X.
- Its paths (the stretch of each edge, the bend of the walk to the column's place, the side it carries the column on)
  were searched by a script so that the robot and its column pass clear of the nodes, boxes and texts; the formula
  beside the upright R–T edge stands further from it, and an edge's formula goes once the robot leaves the edge.
- The robot is lit (the rest of the picture stays flat); the page's three.js bundle holds the lights and the shapes it
  needs. Its timing follows the voice's: the intro passages are long enough for their clips, and semi-join 4 holds a
  moment after its key column has landed; the film lasts 2:14.
- The page that speaks is this one with the robot; the page in !202 stays without robot and voice until this merge
  request follows it.
- This replaces the first item of *Out of scope & deferred*: the voice for the robot variant is part of this merge
  request; and the size under *Consequences*: the page grows by about 0.8 MB (mostly the voice; the robot's shapes
  and lights take some 16 kB), not 0.6 MB.
- `voice.py` also stops if the fallback (`voice.json`) gives no captions, or if `NARRATION` computes its caption times
  and `voice.json` has another number of captions than it: the page would never play the extra clips.
- On a window up to 500 px tall (a phone held sideways), the list of the six semi-joins shows the two passes side by
  side, so that the sound hint does not cover it.
- !202 was merged on 2026-11-06; this merge request is now based on main and no longer stacked.
- After the review: nothing of the robot passes through the column it carries. It walks a little further in front of
  the column, and steps forward while the column passes behind it to its other side (in semi-join 2); a check outside
  the repository (`yannakakis-robot-exact.py`, next to `voice.py`) cuts each part of the robot by the column's plane.
  Its legs are light grey, so that they stand out from the dark background (the user).

<!-- notes below: skill never overwrites past this marker -->
