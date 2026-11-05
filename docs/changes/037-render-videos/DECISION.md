# 037 — YouTube videos of the three.js pages
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/211
---
## Context

The three three.js pages in `visualizations/` (clock scan, row or column, House DBMS) should also go to YouTube, as
videos of 3840×2160 pixels at 60 frames per second, with their synthetic voice. YouTube takes no HTML, so each page
has to be turned into a video file. A recording in real time drops frames and does not reach 4K at 60 fps exactly. The
pages compute every picture from the film's time alone, so a picture can be taken for each 1/60 s on its own. The
three pages are built differently inside (e.g. `buildFilm()` exists in only one of them), but they share how they
advance their film (`requestAnimationFrame` and `performance.now()`) and their voice code (one `<audio>` element).

## Decision

- **A Python tool in the repo**, `tools/render_video.py <page.html> <out.mp4>`, turns a built page into a video. The
  pages and their templates stay as they are; the videos are not committed.
- **A virtual clock drives the page.** An init script replaces `performance.now` and `requestAnimationFrame`; the tool
  advances the clock by 1/60 s per frame and runs the page's own frame code. Frame 0 shows film time 0, frame k film
  time k/60 s. Before the start the tool waits for the fonts and runs the page's warm-up frames until none is left.
- **The page plays its own voice into a stand-in.** An init script replaces the members of `HTMLMediaElement` that
  the pages use; the stand-in's position follows the virtual clock, and it records each start, pause and jump with
  the clip, its rate and the film time. So the start times and rates come from the page itself, not from a copy of
  its logic.
- **One pass, sound on.** The page hides its subtitles while the voice speaks; the tool shows them again with one CSS
  rule. The transport bar and the sound hint are hidden with `visibility: hidden`, so the layout stays as on the page
  (an empty band under the subtitles, where YouTube draws its own progress bar). The header, the counters, the figure
  boxes and the subtitles with their word-by-word highlighting stay in the picture.
- **The picture** is the page at a 1920×1080 viewport with device scale 2: the WebGL canvas is then 3840×2160, native
  4K. Each frame is a PNG screenshot piped into ffmpeg. The tool runs Chrome and stops if WebGL has no GPU (a
  software renderer), so that a render of more than an hour never runs without one by accident.
- **Two ffmpeg runs.** The first encodes the picture: H.264, 60 fps constant, `yuv420p`, BT.709 matrix, range and
  tags; the last frame (legend and credit) is held for 3 s. The second adds the voice to the copied video stream: AAC
  48 kHz stereo at 384 kbit/s, as YouTube recommends, each clip placed at its film time and played at its rate
  (`atempo`; the browser keeps the pitch too). The recorded clips are saved, so the voice can be mixed again in
  seconds, without rendering the picture again.
- **Tests run in CI and are never skipped there.** The CI job `visualization_test` installs ffmpeg and checks: the
  clips start at the times the page tests already fix, and the page reads no media member the stand-in does not model;
  the 3D scene is drawn, the transport hidden and the subtitles shown; a short video has the expected format, frame
  rate, colour tags, sound and timing.

## Consequences

**Positive:** every frame is exact and sharp at 4K; picture and voice come from the same run of the unchanged page;
a new page with the same frame and voice code needs no change in the tool; a wrong voice mix costs seconds, not a
render.

**Negative:** about 0.3 s per frame, so the three videos take about 100 minutes; the tool depends on two things inside
the pages (the CSS rule that hides the subtitles while the voice speaks, and the media members the voice uses), which
the tests guard; the CI job `visualization_test` takes 30 to 60 s longer for ffmpeg.

## Out of scope & deferred

- Uploading to YouTube, titles, descriptions.
- Parallel rendering (several browsers, each a part of the film): about 25 instead of 100 minutes.
- Chapter lines for the YouTube description from the page's part buttons.
- An SRT subtitle file (for YouTube's translations), in addition to the burned-in subtitles.
- A thumbnail picture.
- Other formats, e.g. 1080×1080 for LinkedIn.

## Alternatives rejected

- A recording in real time (Playwright's video, MediaRecorder, a screen recorder): drops frames; Playwright's video is
  low-quality VP8.
- A line injected into the page that hands its film to the tool: the three pages have no common place for it.
- One reload per frame with `?t=`, or the slider: far too slow, and the slider has only 1000 steps (0.16 s on House
  DBMS).
- Playwright's own clock (`page.clock`): its animation frames fall on a 16 ms grid, so the film would run about 4 %
  slow against 60 fps and drift from the voice.
- The voice taken from the voice files outside the repo: start times and rates are computed in the page.
- Two passes (voice with sound on, picture with sound off): a second page load for what one CSS rule gives.
- The fast CDP screenshot: it returns 1920×1080 and only upscales it.
- One ffmpeg run for picture and voice: a mistake in the voice would cost a full render.

## Scope-shift 2026-11-05

The tests of the tool run in a CI job of their own, `render_video_test`, beside `visualization_test`, and only that
job installs ffmpeg. In one job they made `visualization_test`, which already takes about 7 minutes for the page tests,
about a minute longer (half a minute of tests, half a minute for ffmpeg); side by side, the pipeline takes no longer
than without the tool. The cost: Playwright and Chromium are installed twice per pipeline.

<!-- notes below: skill never overwrites past this marker -->

Measured on a MacBook Pro with an M3 Max: about 0.16 s per frame, not 0.3 s; the full render of row-or-column (55 s
with the hold) took 9 minutes, so the three videos take about 55 minutes.
