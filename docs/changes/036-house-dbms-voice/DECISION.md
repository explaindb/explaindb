# 036 — A synthetic voice speaks the House DBMS narration
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/207
---
## Context

Decision 034 gave the clock-scan page a synthetic voice and left the other three.js pages for later. The House DBMS
page (decision 029, merge request !197, not merged yet) has 17 captions. Their times are computed from the moments of
the animation, and some captions are long. They name abbreviations, SQL keywords and code: DBMS, API, VIP, q1,
PREPARE, EXECUTE, `id = ?` and `id = 7`.

## Decision

- **Decision 034 applies** in its final state (its last scope-shift): the same voice, models and generator; sound off
  at load; subtitles and a hint while the voice is silent; Next and ← stop where a caption begins while the voice may
  speak; key M; the voice named on the end card; the same tests, which run on every page with a sound button.
- **Spoken texts** (`house-dbms.voice.json`, next to the page build): letters for the abbreviations (`D B M S`,
  `A P I`, `V I P`, `I D`), `queue one` for q1, `prepare` and `execute` in lower case, so that the voice says them as
  words, `equals` for `=`, `question mark` for `?` and `seven` for `7`. Each take was transcribed with Whisper to find
  words said wrong.
- **Takes:** take 1 for every caption, except captions 13 and 14 (take 2 and take 4). These are shorter, so they play
  at 1.0 and 1.09 times their speed instead of 1.02 and 1.14 times.
- **One timing change:** the caption "The optimizer plans it once: id = ?" ends 0.3 s later, 0.3 s after the
  optimizer has handed over the plan (`marks.handed3 + 0.3` instead of `marks.handed3`). None of 13 takes (4.2 to
  4.5 s long, with three ways of writing the spoken text) fit into the 3.4 s it had at 1.15 times the speed; now it
  plays at 1.14 times. The motion and the length of the film stay as they were. With sound off, Next stops 0.3 s
  later on this caption, still in scene 9.
- **The closing caption** stays on past the end of the film, but the film stops at its end; so its clip's speed is
  computed up to the end of the film.
- **The hint** "Switch on audio (M)" sits below the ×4 badge, as on the clock-scan page. On a narrow screen (up to
  720 px) the SQL card is there, so the hint moves to its right, and a longer hint ("Click or press a key for sound")
  wraps there instead of covering the card. The hint fades out while the end card fades in, which it would cover on a
  narrow window.
- **The end card** names the voice in its last line, after the link to the repository: "The voice is synthetic:
  Ming-3.0 TTS, voice UK_George."

## Consequences

**Positive:** the second three.js page can be heard; the highlighted words follow the voice.

**Negative:** the page grows by about 0.58 MB (from 0.87 to 1.46 MB). Two captions play faster than spoken: "The
optimizer plans it once: id = ?" at 1.14 times, the caption about the key rack at 1.09 times. The voice's name makes
the end card's last line longer. This merge request depends on !197 and can only be merged after it.

## Out of scope & deferred

- The voice on the row-or-column page (decision 035, its own merge request).
- A longer window for caption 10, so that it plays at its own speed.

## Alternatives rejected

- Spelling the letters as words (`ay pee eye`): Whisper heard "IPI".
- A longer pause in the animation for caption 10: it would make the film longer and move every later moment.
- Playing caption 10 at more than 1.15 times its speed: above the limit of decision 034.

<!-- notes below: skill never overwrites past this marker -->

Built with (2026-11-03) the same tools and model revisions as decision 034: mlx-audio 0.6.4,
`mlx-community/Ming-3.0-tts-0.5B-bf16` at revision `283b3c342c6fb69a7a87832c97f9799567efe05d` with voice `UK_George`,
`mlx-community/Qwen3-ForcedAligner-0.6B-8bit` at revision `0e1a68e91d815300c7c9754b2a7639378b23db15`, ffmpeg 7.1.1,
MP3 mono at 48 kbit/s. Checked with `mlx-community/whisper-large-v3-turbo-asr-fp16` at revision
`624c19c9af5603fa73b83bce14d4aeea96156d18`.
