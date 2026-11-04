# 034 — A synthetic voice speaks the clock-scan narration
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/205
---
## Context

The three.js pages show their narration word by word, at a fixed 2.6 words per second, and have no sound. The
user wants the narration spoken as well, by a synthetic voice, inside the page itself (one file that works
offline), not only in a video. The first page is the clock scan (031). All pages share one Content Security
Policy (decision 030) and the rules of "What a new page has" (merge request !200); the build tooling stays
outside the repository.

Tried on 2026-11-03: Kokoro-82M (Apache-2.0) works and gives word times, but its voices sound mechanical to the
user. Ming-3.0-tts-0.5B (MIT, inclusionAI) with its built-in voice UK_George sounded best among Ming, Qwen3-TTS
and Kokoro; Ming gives a different take on every run, also with temperature 0. Qwen3-ForcedAligner-0.6B
(Apache-2.0) aligned a known text to Ming's audio word by word. A one-file demo with embedded MP3 `data:` URLs and
the pages' CSP plus `media-src data:` played in Chromium without errors or network requests.

## Decision

- **Voice:** Ming-3.0-tts-0.5B with its built-in voice UK_George, in English, run locally with mlx-audio. The
  start and end of each word come from Qwen3-ForcedAligner-0.6B, which is given the known text.
- **Generator, outside the repository** next to the page build. Each caption has a spoken text with pronunciation
  fixes, e.g. `ay equals forty-two` for `a = 42`; brackets group several spoken words for one shown word, e.g.
  `[Q one]` for `Q1`. The shown caption is split at spaces, as the page does; the spoken text must give exactly as
  many groups, and the aligner's words must equal the spoken words once both are normalised (lowercase, letters
  and digits only). Otherwise the build fails.
- **Takes:** each caption is synthesised once, the author listens to it, and it is kept. The page in the
  repository is the record: it stores for each clip its key (spoken text, take number, model, voice), and the
  generator reuses every clip whose key is unchanged; a new take number redoes a rejected take. A changed caption
  needs a new take and a listen. The clips are MP3, mono, at a constant bit rate (48 or 64 kbit/s, chosen by ear),
  encoded so that the same take gives the same bytes. The model revisions and tool versions used are noted below
  the marker when the voice is first built.
- **The page:** a sound button (a speaker icon, key M, title "Sound: synthetic voice (M)") between the clock and
  full screen. Sound is off at load: browsers allow sound only after a click, and WCAG 1.4.2 asks for it. The
  playback time still comes from the page's own clock; the voice follows it and is moved only when it is more than
  0.25 s off, so that the film never waits for the sound. A clip longer than its caption's window plays faster, at
  most 1.15 times. Pause holds the clip and Play goes on in it; Next, ←, the slider and the part buttons drop it.
  Next and ← stay silent, as they show a whole caption on every page; the voice speaks while the film plays. A
  pause from outside the page (media keys, a call) pauses the film, and so does hiding the tab while sound is on.
- **Highlight:** the words light up at the voice's word times instead of 2.6 words per second, also with sound
  off.
- **Screen readers:** with sound on, the narration's `aria-live` is off, so that a screen reader does not speak at
  the same time as the voice.
- **Credits:** the card at the end names the synthetic voice; a comment in the page gives the model's license
  (MIT) and how the voice was made; the README says that the page speaks.
- **CSP:** `media-src data:` goes onto all pages in a merge request of its own, before this one and after a check
  that embedded audio plays on an iPhone (else `blob:`), with a note in decision 030, as `font-src data:` went onto
  all pages.
- **Tests:** a test for every page with a sound button joins the tests that run on every page, and the clock-scan
  page must have one. Safari (macOS and iPhone) and Firefox are checked by hand.

## Consequences

**Positive:** the narration can be heard, in one offline file, with the same voice on every device; the highlight
follows real speech.

**Negative:** the page grows by about 0.5–0.65 MB. Takes cannot be reproduced, so a changed caption means a new
take and a listen. The source of UK_George's reference audio is not documented; the model card allows built-in
voices for "legitimate creative use" and asks to label synthetic speech, which the page does. Until the rule of
!200 is updated, the page has one more control than that rule lists.

## Out of scope & deferred

- The voice on the other three.js pages.
- The sound button in CONTRIBUTING's rules for every page (after !200).
- A video export with the voice, e.g. for YouTube.
- Narration in German.
- Remembering the sound choice across pages.
- Other models, e.g. Phonon 31M (not available for speech output in mlx-audio).

## Alternatives rejected

- Kokoro-82M: its voices sound mechanical to the user.
- Qwen3-TTS: the user preferred Ming's UK_George.
- The browser's speech synthesis: the voice differs per device, online voices break "works offline", word events
  are unreliable, and on Android a pause cancels the speech.
- A cloud service: an account, costs and terms of use.
- Models under non-commercial licenses (Fish Audio, Voxtral, F5-TTS, XTTS-v2).
- One long audio track: silence between captions, and drift.
- Web Audio: its playback rate shifts the pitch.
- Whisper or whisperX for the word times: the forced aligner is given the known text and is more precise.
- Longer caption windows: they would change the film's timing.
- Next speaking the caption: Next would behave unlike on every other page.
- `media-src data:` on this page only: decision 030 keeps one line for all pages.

## Scope-shift 2026-11-03

After listening to the first version in Firefox (the user):

- **Sound is on at load.** Browsers allow a page sound only after the reader's first click or key press; until then
  the film plays silently, and the voice joins where the film is with the first click or key press anywhere on the
  page. The sound button and M switch it off and on. Its icon is a speaker with waves while sound is on and a
  crossed-out speaker while it is off.
- **Clips are not cut.** Each clip plays from its start when its caption begins and may finish its last words after
  its caption has faded, until the next caption begins; the next clip is loaded ahead. The voice is moved only when
  it runs more than 0.25 s ahead of the film or more than 1 s behind it: Firefox reports a clip's position only
  coarsely, and moving the voice on each small difference cut the first syllables, while stopping it with its
  caption cut the last ones. While the voice speaks, the film advances up to 0.5 s a frame, so that it keeps up on a
  slow machine.

## Scope-shift 2026-11-03 (the film grows by a second)

- The caption "At 7, a = 42: …" needed 1.16 times its speed once its last word was kept in full (the aligner had
  ended "26" half a second early). The user chose a longer film over a faster voice: the slow stretch around 7
  o'clock runs on to 7.8 instead of 7.6, the caption with it, and the film lasts 1:43 instead of 1:42. The motion,
  a function of the car's hour, stays as it was.
- Each clip ends where its sound ends (measured in the take, not taken from the aligner) and begins with 0.4 s of
  silence, so that a browser that starts its sound late does not swallow the first syllable.
- Where the voice should pause, the spoken text may differ in punctuation from the shown text, e.g. "at 6. Two" for
  "at 6: two".

## Scope-shift 2026-11-03 (a hint for the first click)

- While the browser holds the voice back, a hint "Click or press a key for sound" shows above the picture and the
  sound button pulses (not with reduced motion); both go with the first click or key press. Firefox tells at load
  that sound is held back, other browsers when they refuse the first clip.

## Scope-shift 2026-11-03 (the voice instead of the text)

The user found the text at the bottom left distracting once the voice speaks it:

- While the voice may speak, the narration is not shown (and not read out by a screen reader). While it is silent
  (sound switched off, or held back by the browser), the narration shows as subtitles, as before, with the hint
  "Switch on audio (M)" or "Click or press a key for sound". So no one loses the narration: readers without sound
  and deaf readers still read it.
- While the voice may speak, Next and ← stop where a caption begins, paused, and Play speaks it; with sound off they
  stop where a caption is shown in full, as on every other page. This differs from the rule of !200 (a stop is the
  moment a caption has been said in full) and goes into it with the sound button.

## Scope-shift 2026-11-03 (sound off at load again)

- On second thought (the user), sound is off at load, as first decided: the page starts with subtitles and the hint
  "Switch on audio (M)", and the click on the sound button is the reader's action that browsers ask for, so the voice
  speaks at once. The hint "Click or press a key for sound" stays for a browser that still holds the voice back.
- The page learns that the browser holds the voice back only from a refused clip; it does not ask the browser at load.
  A browser that refuses the voice even after the sound button or M (sound blocked for the page) gets sound off again.

<!-- notes below: skill never overwrites past this marker -->

Built with (2026-11-03): mlx-audio 0.6.4 (Python 3.12, Apple M3 Max); `mlx-community/Ming-3.0-tts-0.5B-bf16` at
revision `283b3c342c6fb69a7a87832c97f9799567efe05d`, voice `UK_George`; `mlx-community/Qwen3-ForcedAligner-0.6B-8bit` at
revision `0e1a68e91d815300c7c9754b2a7639378b23db15`; ffmpeg 7.1.1 with LAME 3.100, MP3 mono at 48 kbit/s. The generator
(`voice.py`) and the spoken texts (`clock-scan.voice.json`) lie next to the page build outside the repository; it takes
the approved takes from the page in the repository when its cache is missing.

Checked with (2026-11-03): `check_voice.py`, next to `voice.py`, transcribes each clip of the built page with
`mlx-community/whisper-large-v3-turbo-asr-fp16` (Whisper, MIT) at revision `624c19c9af5603fa73b83bce14d4aeea96156d18`,
without the text, and flags a clip whose words differ from its caption. It found that the voice said "ay" (the letter
a) as "I"; the spoken texts now write it "A". A flag still needs an ear: the recogniser can mishear as well.
