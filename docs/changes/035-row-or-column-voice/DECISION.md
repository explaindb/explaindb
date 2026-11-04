# 035 — A synthetic voice speaks the row-or-column narration
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/206
---
## Context

Decision 034 gave the clock-scan page a synthetic voice and deferred the voice on the other three.js pages. The
row-or-column page (028) has seven captions, one per step; a caption is said in segments, each from its own time,
nine segments in all. Two steps have two segments, the second one several seconds after the first, while the picture
moves on.

## Decision

- **Decision 034 applies** in its final state: the same model, voice, aligner, bit rate and generator; sound off at
  load; the sound button, key M and the hint; subtitles only while the voice is silent; the voice's code as on the
  clock-scan page.
- **One clip per segment.** A clip starts at its segment's time. It has to end before the next segment of its caption
  begins, and the last clip of a caption at that caption's stop (where Next stops with sound off, or the film's end);
  a longer clip plays faster, at most 1.15 times. One clip per caption would have to bridge the seconds between two
  segments with silence.
- **Next and ← with sound on** stop where each step's first segment begins, once per step, as with sound off.
- **Highlight:** a word stays underlined until the next word of its segment begins, the last word of a segment until
  the voice has said it.
- **Spoken texts** that differ from the shown ones: `sixty-four` for `64`; `Four lines red` for `Four lines read`, so
  that the voice says the past tense; and the two words marked `~title~` and `~author~` without their marks.
- **Timing:** unchanged. All nine first takes fit; the last one ("Same answer. A quarter of the traffic.", 2.7 s until
  the end of the film) plays 1.12 times as fast.
- **Hint** above the narration on the right, over the sound button: the top of the picture holds the terminal and the
  declaration card, its middle the CPU cache.
- **Credit:** the page has no card at the end; at the end, the terminal shows below "-- try it" the two lines
  `-- synthetic voice: Ming-3.0 TTS,` and `--   voice UK_George` (one line would be cut off on a narrow phone).
- **Space** plays and pauses also while the sound or full-screen button has the focus; a held Space does not click
  that button when it comes up (as on the clock-scan page).
- **Tests:** the page joins the tests for every page with a sound button and the list of pages that must keep their
  voice; where those tests use the button of part 1, a page without parts jumps back with the slider and Play. Its own
  tests check a clip per segment, Next and ← once per step, the words said per segment, the faster last clip and the
  credit.

## Consequences

**Positive:** the second three.js page speaks; the same code drives the voice on both pages.

**Negative:** the page grows from 0.71 MB to 1.01 MB. The voice says the last word 0.13 s before the film ends; in a
browser that starts the last clip later than that, the film's end cuts off the end of "traffic".

## Out of scope & deferred

- The voice on the House DBMS page (decision 036, its own merge request) and on query-city.
- A longer end of the film, so that the last clip plays at its own speed (open question for the author).

## Alternatives rejected

- One clip per caption: silence of several seconds inside a clip between two segments.
- Next stopping at every segment with sound on: the button is "Next step", and with sound off it stops once per step.
- The hint at the top center, as on the clock-scan page: there it covers the table at the start, and the terminal on a
  phone. Centered above the narration, it covers the CPU cache while the row layout is read.

<!-- notes below: skill never overwrites past this marker -->

Built with the same tools and model revisions as decision 034 (see there). The spoken texts lie in
`row-or-column.voice.json` next to the page build, outside the repository.
