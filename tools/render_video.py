#!/usr/bin/env python3
#
#    This is ExplainDB, educational database systems materials.
#
#    Copyright (C) 2026 Prof. Dr. Jens Dittrich, Saarland University
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#

"""Turns a three.js page of ``visualizations/`` into a video for YouTube: 3840×2160, 60 fps, with its voice.

Usage (needs the dependency group ``browser-tests`` for Playwright, Google Chrome, and ffmpeg with ffprobe on the
PATH)::

    uv run --group browser-tests python tools/render_video.py visualizations/clock-scan.html clock-scan.mp4
    uv run --group browser-tests python tools/render_video.py --mux-only visualizations/clock-scan.html clock-scan.mp4

A virtual clock drives the page (decision 037): an init script replaces ``performance.now`` and
``requestAnimationFrame``, and each step advances the clock by 1/60 s and runs the page's own frame code. Frame 0 shows
film time 0, frame k film time k/60 s. The page plays its voice into a stand-in for ``HTMLMediaElement``, which records
each start and stop of a clip; the recorded clips are mixed into the video afterwards. The picture is the page with
sound on, its subtitles shown again, the transport bar and the sound hint hidden. Chrome draws with the GPU; the tool
stops if WebGL has none.

Two files are written next to the video: ``<name>.video.mp4`` (the picture alone) and ``<name>.voice.json`` (the
clips). ``--mux-only`` mixes the voice into the picture again from these two files, in seconds, without rendering. A
render that fails while it records leaves the three files of an earlier render as they were; if only the voice mix
fails, the two new side files are kept, and ``--mux-only`` can mix them again.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import math
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

if TYPE_CHECKING:
    # pylint: disable=import-error
    from playwright.sync_api import Browser, BrowserContext, Page, Route, WebSocketRoute

FPS: int = 60
# the CSS viewport and the device scale: the page's canvas is then 3840×2160
VIEWPORT: tuple[int, int] = (1920, 1080)
SCALE: float = 2
HOLD: float = 3.0  # seconds the last frame (legend, credit) is held
AUDIO_RATE: int = 48_000
# a WebGL renderer with one of these names draws without a GPU (as the pages themselves tell it)
SOFTWARE_RENDERERS: tuple[str, ...] = (
    "swiftshader",
    "llvmpipe",
    "software",
    "basic render",
)
# a page's voice clips are MP3 files in data URIs
CLIP_PREFIX: str = "data:audio/mpeg;base64,"
# the slowest and the fastest speed of a clip that ffmpeg's atempo can play
RATES: tuple[float, float] = (0.5, 100.0)
# a film may run this many seconds longer than the length its clock shows (in whole seconds) before the tool stops
FILM_MARGIN: float = 2.0

# The virtual clock, the stand-in for audio elements and a watch for a lost WebGL context, installed before the page's
# own script runs.
INIT_SCRIPT: str = r"""
(() => {
  const FPS = %(fps)d;
  const CLIP_PREFIX = %(prefix)s;
  const RATES = [%(slowest)r, %(fastest)r];
  let frame = 0; // the number of steps so far: the virtual time is frame / FPS seconds
  let callbacks = new Map(); // the callbacks asked for with requestAnimationFrame, by their id
  let running = new Map(); // the callbacks of the frame being run that have not run yet
  let nextId = 1;
  performance.now = () => (frame * 1000) / FPS;
  window.requestAnimationFrame = (callback) => { callbacks.set(nextId, callback); return nextId++; };
  // as in a browser, a callback cancelled while its frame is run does not run
  window.cancelAnimationFrame = (id) => { callbacks.delete(id); running.delete(id); };
  // without its WebGL context a page draws no 3D scene until it gets a new one (perhaps without the GPU); the error
  // stops the render. The event does not bubble, so the listener on window catches it on its way down to the canvas
  // (capture, the last argument):
  window.addEventListener('webglcontextlost', () => console.error('render_video: the WebGL context was lost'), true);
  /**
   * Runs the callbacks asked for so far at the current time, one after the other; promises they start settle only
   * after the last one (the pages ask for one callback per frame). A callback that throws is reported as an uncaught
   * error of the page, as a browser does, and the others still run. @returns {number} how many ran
   */
  const flush = () => {
    running = callbacks;
    callbacks = new Map();
    let ran = 0;
    for (const [id, callback] of running) {
      running.delete(id);
      ran += 1;
      try {
        callback(performance.now());
      } catch (error) {
        reportError(error);
      }
    }
    return ran;
  };
  /** @returns {string|null} Play's data-state: playing, paused or ended */
  const playState = () => document.querySelector('[data-testid=play]')?.dataset.state ?? null;

  // each start and stop of a voice clip, with the step it happened at; a jump inside a clip is a stop and a start
  const log = [];
  const unmodelled = new Set(); // what the page did with an audio element that the stand-in does not model
  /**
   * Notes a use of audio that the stand-in does not model, and logs it as an error, which stops the render at once.
   * @param {string} what
   */
  const report = (what) => {
    if (unmodelled.has(what)) return;
    unmodelled.add(what);
    console.error(`render_video: the stand-in does not model this use of audio: ${what}`);
  };
  // the state of each audio element: whether it is paused, and its position in the clip (s, clip time) at step since;
  // while it plays, the position moves on with the virtual clock at the element's playbackRate
  const states = new WeakMap();
  /** @param {HTMLMediaElement} el @returns {{paused: boolean, position: number, since: number}} its state */
  const stateOf = (el) => {
    if (!states.has(el)) states.set(el, { paused: true, position: 0, since: 0 });
    return states.get(el);
  };
  /** @param {HTMLMediaElement} el @returns {number} its position in the clip now (s, clip time) */
  const position = (el) => {
    const s = stateOf(el);
    return s.paused ? s.position : s.position + ((frame - s.since) / FPS) * el.playbackRate;
  };
  /**
   * Logs that el starts to play its clip now, from the position in its state s; reports a start the mix cannot play.
   */
  const start = (el, s) => {
    const clip = el.getAttribute('src') ?? '';
    if (!clip.startsWith(CLIP_PREFIX)) report('play a clip that is no MP3 data URI');
    if (!(el.playbackRate >= RATES[0] && el.playbackRate <= RATES[1])) report(`play at rate ${el.playbackRate}`);
    if (!(Number.isFinite(s.position) && s.position >= 0)) report(`play from position ${s.position}`);
    log.push({ kind: 'play', frame, clip, rate: el.playbackRate, position: s.position });
  };
  // as a browser sends them: after the call that caused them
  const fire = (el, type) => Promise.resolve().then(() => el.dispatchEvent(new Event(type)));
  const media = HTMLMediaElement.prototype;
  let voice = null; // the audio element that plays the voice; the log holds the clips of one element only
  /** Starts the clip where it stands, unless it plays already. @returns {Promise<void>} resolved at once */
  media.play = function () {
    if (voice !== null && voice !== this) report('play a second audio element');
    voice = this;
    const s = stateOf(this);
    if (s.paused) {
      s.paused = false;
      s.since = frame;
      start(this, s);
      fire(this, 'play');
      fire(this, 'playing');
    }
    return Promise.resolve();
  };
  /** Stops the clip where it stands, if it plays. */
  media.pause = function () {
    const s = stateOf(this);
    if (s.paused) return;
    s.position = position(this);
    s.paused = true;
    log.push({ kind: 'pause', frame });
    fire(this, 'pause');
  };
  /** Loads the clip anew: stops it, if it plays, and puts it back to its start. */
  media.load = function () {
    const s = stateOf(this);
    if (!s.paused) log.push({ kind: 'pause', frame });
    Object.assign(s, { paused: true, position: 0, since: frame });
  };
  /** Replaces the member name of all audio elements by the getter get and the setter set. */
  const define = (name, get, set) => Object.defineProperty(media, name, { configurable: true, get, set });
  define('paused', function () { return stateOf(this).paused; });
  // a clip is always loaded and never ends: the page then plays it at once, and holds a clip that has said its last
  // word until it loads the next one, which changes nothing that is heard
  define('ended', () => false);
  define('readyState', () => HTMLMediaElement.HAVE_ENOUGH_DATA);
  define('currentSrc', function () { return this.getAttribute('src') ?? ''; });
  define('currentTime', function () { return position(this); }, function (value) {
    const s = stateOf(this);
    if (!s.paused) log.push({ kind: 'pause', frame });
    Object.assign(s, { position: Number(value), since: frame });
    if (!s.paused) start(this, s);
  });
  // the members the stand-in does not model: a page that reads or sets one is reported
  for (const name of ['duration', 'seeking', 'buffered', 'seekable', 'played', 'networkState', 'error', 'volume',
                      'muted', 'loop', 'autoplay', 'preservesPitch']) {
    const original = Object.getOwnPropertyDescriptor(media, name);
    if (!original) continue; // not in this browser
    define(name, function () { report(`read ${name}`); return original.get.call(this); },
           original.set && function (value) { report(`set ${name}`); original.set.call(this, value); });
  }
  // the clip and its speed may change only while it is paused (the log keeps them from the start of the clip)
  for (const name of ['src', 'playbackRate', 'defaultPlaybackRate']) {
    const original = Object.getOwnPropertyDescriptor(media, name);
    define(name, original.get, function (value) {
      if (!stateOf(this).paused) report(`set ${name} while playing`);
      original.set.call(this, value);
    });
  }
  // the events the stand-in sends, and waiting, which never comes, as a clip is always loaded; a page that waits for
  // any other event, with addEventListener or one of the on-properties below, is reported
  const SENT = new Set(['play', 'playing', 'pause', 'waiting']);
  media.addEventListener = function (type, ...rest) {
    if (!SENT.has(type)) report(`listen ${type}`);
    return EventTarget.prototype.addEventListener.call(this, type, ...rest);
  };
  for (const type of ['ended', 'timeupdate', 'seeked', 'seeking', 'loadedmetadata', 'loadeddata', 'canplay',
                      'canplaythrough', 'durationchange', 'ratechange', 'error', 'stalled', 'loadstart', 'progress',
                      'suspend', 'emptied', 'abort', 'volumechange']) {
    define(`on${type}`, () => null, () => { report(`listen ${type}`); });
  }

  window.__video = {
    /** Runs the callbacks asked for so far, without advancing the time. @returns {number} how many ran */
    flush,
    /** Advances the time by one frame and runs the page's callbacks. @returns {string|null} Play's data-state */
    step() { frame += 1; flush(); return playState(); },
    log,
    unmodelled: () => [...unmodelled],
  };
})();
""" % {
    "fps": FPS,
    "prefix": json.dumps(CLIP_PREFIX),
    "slowest": RATES[0],
    "fastest": RATES[1],
}

# shows the subtitles, which the page hides while its voice speaks, and hides the controls
VIDEO_CSS: str = """
[data-testid=nar-text] { visibility: visible !important; }
[data-testid=transport], [data-testid=sound-hint] { visibility: hidden !important; }
"""


class LogEntry(TypedDict):
    """A start (``play``) or stop (``pause``) of a voice clip, as the stand-in logs it."""

    kind: Literal["play", "pause"]
    frame: int  # the step it happened at
    clip: NotRequired[str]  # play only: the clip, as the page's data URI
    rate: NotRequired[float]  # play only: the speed it plays at
    # play only: where in the clip it starts (s, clip time)
    position: NotRequired[float]


@dataclass(frozen=True)
class Segment:
    """A stretch of the film in which one voice clip sounds."""

    clip: str  # the clip, as the page's data URI of an MP3 file
    rate: float  # the speed it plays at (1 = as recorded), within RATES
    start: float  # where it starts in the film (s)
    offset: float  # where in the clip it starts (s, clip time)
    # where the page stops it in the film (s); the clip itself may have said its last word before
    end: float

    def __post_init__(self) -> None:
        """Checks the values, which go into an ffmpeg command line. @raise ValueError: if one is not as described"""
        if not isinstance(self.clip, str) or not self.clip.startswith(CLIP_PREFIX):
            raise ValueError(f"a clip must be a data URI starting with {CLIP_PREFIX}")
        for name in ("rate", "start", "offset", "end"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be a finite number, not {value!r}")
        if not (
            RATES[0] <= self.rate <= RATES[1]
            and self.start >= 0
            and self.offset >= 0
            and self.end > self.start
        ):
            raise ValueError(f"not a segment of the film: {self}")


def segments_from_log(log: list[LogEntry], last_frame: int) -> list[Segment]:
    """Turns the stand-in's log into the stretches in which a clip sounds.

    @param log: the starts and stops in the order they happened
    @param last_frame: the step the recording ends at (one after its last frame); a clip still sounding stops there
    @return: the segments that last longer than zero, in the order they start
    """
    segments: list[Segment] = []
    playing: LogEntry | None = None
    closing: LogEntry = {"kind": "pause", "frame": last_frame}
    for entry in [*log, closing]:
        if playing is not None:
            segments += _segment(playing, entry["frame"])
        playing = entry if entry["kind"] == "play" else None
    return segments


def _segment(started: LogEntry, stop: int) -> list[Segment]:
    """@return: the segment of a clip started as logged and stopped at step stop, or none if it lasts zero steps"""
    if stop == started["frame"]:
        return []
    return [
        Segment(
            started["clip"],
            started["rate"],
            started["frame"] / FPS,
            started["position"],
            stop / FPS,
        )
    ]


def open_page(
    page: Page, path: Path, errors: list[str], allow_software_gpu: bool = False
) -> int:
    """Opens the page paused at its start, waits until it is ready, starts it with sound on and shows frame 0.

    @param page: a page of a context with ``INIT_SCRIPT`` installed
    @param path: the HTML file
    @param errors: the errors the page has logged so far, filled while it runs
    @param allow_software_gpu: whether a WebGL renderer without GPU is accepted
    @return: the most steps the film may take: the length its clock shows, plus ``FILM_MARGIN``
    @raise RuntimeError: if WebGL is missing or draws without a GPU (and that is not allowed), if the page logs an
        error, if it does not get ready or does not start, or if its clock shows no length
    """
    page.goto(path.resolve().as_uri() + "?paused")
    renderer: str | None = page.evaluate("""() => {
            const gl = document.createElement('canvas').getContext('webgl2');
            const info = gl?.getExtension('WEBGL_debug_renderer_info');
            return gl ? String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER)) : null;
        }""")  # fmt: skip
    if renderer is None:
        raise RuntimeError("the browser has no WebGL 2")
    if not allow_software_gpu and any(
        name in renderer.lower() for name in SOFTWARE_RENDERERS
    ):
        raise RuntimeError(f"WebGL draws without a GPU: {renderer}")
    page.evaluate("document.fonts.ready.then(() => true)")
    # pylint: disable-next=import-error,import-outside-toplevel
    from playwright.sync_api import expect

    # the page enables its controls once it is set up (after its fonts have loaded or a timeout), and in the same step
    # asks for the first frame of its warm-up
    try:
        expect(page.get_by_test_id("play")).to_be_enabled(timeout=30_000)
    except AssertionError as error:
        raise RuntimeError("the page did not enable Play") from error
    # the page's warm-up runs one step per animation frame; the time stands still meanwhile
    for _ in range(10_000):
        if page.evaluate("window.__video.flush()") == 0:
            break
    else:
        raise RuntimeError("the page did not get ready")
    # the click event is sent straight to each button: a mouse click at the button's place could hit whatever covers
    # it in a small window
    page.get_by_test_id("sound").dispatch_event("click")
    page.get_by_test_id("play").dispatch_event("click")
    page.add_style_tag(content=VIDEO_CSS)
    # draws frame 0 with sound on and the CSS above; the time is still 0
    page.evaluate("window.__video.flush()")
    play = page.get_by_test_id("play")
    if (
        play.get_attribute("data-state") != "playing"
        or page.get_by_test_id("sound").get_attribute("aria-pressed") != "true"
    ):
        raise RuntimeError("the page did not start playing with sound on")
    if errors:
        raise RuntimeError(f"the page logged errors: {errors}")
    clock: str = page.get_by_test_id("clock").text_content() or ""
    length = re.fullmatch(r".*/ (\d+):(\d\d)", clock)
    if length is None:
        raise RuntimeError(f"the page's clock shows no length: {clock!r}")
    return round((int(length[1]) * 60 + int(length[2]) + FILM_MARGIN) * FPS)


@dataclass(frozen=True)
class BrowserOptions:
    """How the page is shown: in which browser, how large, whether WebGL may draw without a GPU, and whether Chrome
    runs in its sandbox."""

    viewport: tuple[int, int] = VIEWPORT  # the CSS viewport
    scale: float = SCALE  # the device scale; the picture is viewport × scale pixels
    channel: str | None = (
        "chrome"  # "chrome": Google Chrome; None: Playwright's Chromium
    )
    allow_software_gpu: bool = False
    # the page runs in Chrome's sandbox, as in a reader's browser; it does not start for root (e.g. in CI)
    sandbox: bool = True


def record(
    path: Path,
    frames_to: subprocess.Popen[bytes] | None,
    seconds: float | None = None,
    browser: BrowserOptions = BrowserOptions(),
) -> list[Segment]:
    """Plays the page from its start to its end (or for the given seconds) and records its voice.

    @param path: the HTML file
    @param frames_to: ffmpeg reading PNG frames on its stdin, or None to record only the voice (much faster)
    @param seconds: how much of the film to record, or None for all of it
    @param browser: how the page is shown
    @return: the voice segments
    @raise RuntimeError: see ``check_recording``, ``_play`` and ``open_page``
    @raise ValueError: if a clip the page played cannot be mixed (see ``Segment``); the stand-in reports such a clip
        when it starts, so this is a last check
    """
    # pylint: disable-next=import-error,import-outside-toplevel
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(
            channel=browser.channel, chromium_sandbox=browser.sandbox
        )
        try:
            page = prepare_page(chromium, path, browser, errors)
            # limit counts frames, frame 0 included; each step after frame 0 adds one
            limit: int = open_page(page, path, errors, browser.allow_software_gpu) + 1
            if seconds is not None:
                limit = round(seconds * FPS)
            frame, reached = _play(page, frames_to, limit, errors)
            log: list[LogEntry] = page.evaluate("window.__video.log")
            unmodelled: list[str] = page.evaluate("window.__video.unmodelled()")
        finally:
            chromium.close()
    check_recording(errors, unmodelled, reached, limit if seconds is None else None)
    # the last frame shows until one frame later
    return segments_from_log(log, frame + 1)


def prepare_page(
    chromium: Browser, path: Path, browser: BrowserOptions, errors: list[str]
) -> Page:
    """Opens a blank page in a new context, as the tool records with: at the size the options give, with the virtual
    clock and the stand-in, allowed to load only the files in the folder of path, and logging its errors.

    @param chromium: the browser
    @param path: the HTML file that will be shown (see ``open_page``)
    @param browser: how the page is shown
    @param errors: filled with the errors the page logs and each request it is refused
    @return: the blank page
    """
    context = chromium.new_context(
        viewport={"width": browser.viewport[0], "height": browser.viewport[1]},
        device_scale_factor=browser.scale,
    )
    allow_only(context, path.resolve().parent.as_uri() + "/", errors)
    context.add_init_script(INIT_SCRIPT)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: message.type == "error" and errors.append(message.text),
    )
    return page


def allow_only(context: BrowserContext, folder: str, errors: list[str]) -> None:
    """Lets the pages of the context load only files in a folder (CONTRIBUTING.md: a page works offline); any other
    request and any WebSocket that a frame of the page opens is refused and logged as an error. WebSockets of workers,
    WebRTC and connection hints are outside its reach.

    @param context: the browser context, before its page is opened
    @param folder: the folder's file URI, ending with a slash
    @param errors: the errors the page logs, to which each refusal is added
    """

    def refuse(route: Route) -> None:
        """Refuses a request and logs it."""
        errors.append(f"refused a request: {route.request.url}")
        route.abort()

    def refuse_socket(socket: WebSocketRoute) -> None:
        """Logs a WebSocket, which never reaches its server, as the handler does not connect it (closing it here
        would make Playwright wait for ever: the page's socket opens only after the handler has returned).
        """
        errors.append(f"refused a WebSocket: {socket.url}")

    context.route(lambda url: not url.startswith(folder), refuse)
    context.route_web_socket(lambda url: True, refuse_socket)


def check_recording(
    errors: list[str], unmodelled: list[str], reached: str | None, limit: int | None
) -> None:
    """Checks that a recording of the page's film is complete and its voice can be trusted.

    @param errors: the errors the page logged
    @param unmodelled: what the page did with its audio that the stand-in does not model
    @param reached: Play's data-state after the last frame
    @param limit: the frames the whole film may take, frame 0 included (so the last is frame limit - 1), or None if
        only a part of it was recorded
    @raise RuntimeError: if the page used its audio in a way the stand-in does not model, if it logged an error, if the
        film stopped playing before its end, or if it had not ended by frame limit - 1
    """
    if unmodelled:
        raise RuntimeError(
            f"the page uses its audio in ways the stand-in does not model: {unmodelled}"
        )
    if errors:
        raise RuntimeError(f"the page logged errors: {errors}")
    if reached not in ("playing", "ended"):
        raise RuntimeError(f"the film stopped before its end: Play is {reached!r}")
    if limit is not None and reached != "ended":
        raise RuntimeError(f"the film had not ended by frame {limit - 1}")


def _play(
    page: Page, frames_to: subprocess.Popen[bytes] | None, limit: int, errors: list[str]
) -> tuple[int, str | None]:
    """Plays the started page frame by frame until the film stops playing (at its end, or paused before it) or
    limit frames are taken.

    @param page: the page, started and showing frame 0 (see ``open_page``)
    @param frames_to: ffmpeg reading PNG frames on its stdin, or None to take no pictures
    @param limit: the most frames, frame 0 included
    @param errors: the errors the page has logged so far, filled while it runs
    @return: the last frame's number and Play's data-state after it
    @raise RuntimeError: if the page logs an error (also one that ``INIT_SCRIPT`` logs)
    """
    frame: int = 0
    reached: str | None = "playing"
    while True:
        if frames_to is not None:
            assert frames_to.stdin is not None
            frames_to.stdin.write(page.screenshot(type="png", caret="initial"))
        if errors:
            raise RuntimeError(f"the page logged errors: {errors}")
        if reached != "playing" or frame + 1 >= limit:
            return frame, reached
        reached = page.evaluate("window.__video.step()")
        frame += 1


def video_command(out: Path, hold: float) -> list[str]:
    """@return: the ffmpeg command that encodes PNG frames from its stdin to H.264 for YouTube (BT.709) into out,
    holding the last frame for hold seconds (written with fixed decimals: ffmpeg rejects Python's exponent notation,
    e.g. 1e-05)"""
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
        "-vf", f"tpad=stop_mode=clone:stop_duration={hold:.6f},"
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high", "-r", str(FPS),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-an", str(out),
    ]  # fmt: skip


def mux_command(
    video: Path,
    duration: float,
    clip_files: dict[str, Path],
    segments: list[Segment],
    out: Path,
) -> list[str]:
    """Builds the ffmpeg command that adds the voice to the picture, as AAC for YouTube.

    @param video: the picture alone
    @param duration: its length (s); the voice is padded with silence or cut to it
    @param clip_files: each clip of the segments (its data URI) and the MP3 file that holds it, in the order they are
        given to ffmpeg
    @param segments: the stretches in which a clip sounds
    @param out: the video to write
    @return: the command
    """
    inputs: list[str] = ["-i", str(video)]
    for clip_file in clip_files.values():
        inputs += ["-f", "mp3", "-i", str(clip_file)]
    input_of: dict[str, int] = {clip: i + 1 for i, clip in enumerate(clip_files)}
    parts: list[str] = []
    for i, segment in enumerate(segments):
        delay: int = round(segment.start * AUDIO_RATE)
        # from the clip's offset, at its rate, until the page stops it, at its place in the film (times with fixed
        # decimals: ffmpeg rejects Python's exponent notation, e.g. 5e-05):
        parts.append(
            f"[{input_of[segment.clip]}:a]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,"
            f"atrim=start={segment.offset:.6f},asetpts=PTS-STARTPTS,atempo={segment.rate},"
            f"atrim=end={segment.end - segment.start:.6f},asetpts=PTS-STARTPTS,"
            f"adelay=delays={delay}S:all=1[a{i}]"
        )
    labels: str = "".join(f"[a{i}]" for i in range(len(segments)))
    if segments:
        voice = f"{labels}amix=inputs={len(segments)}:normalize=0"
    else:
        voice = f"anullsrc=r={AUDIO_RATE}:cl=stereo"
    # as long as the video, counted in samples; the mixed samples reach the encoder without valid time stamps (the AAC
    # stream would start at a nonsense time), so they are counted anew
    parts.append(
        f"{voice},apad=whole_dur={duration},atrim=end_sample={round(duration * AUDIO_RATE)},"
        "asetpts=N/SR/TB[voice]"
    )
    return [
        "ffmpeg", "-y", "-nostdin", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[voice]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "384k", "-ar", str(AUDIO_RATE), "-ac", "2",
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def mux(video: Path, segments: list[Segment], out: Path) -> None:
    """Writes out: the picture with the voice segments mixed in.

    @param video: the picture alone
    @param segments: the stretches in which a clip sounds
    @param out: the video to write
    @raise subprocess.CalledProcessError: if ffprobe or ffmpeg fails
    """
    with tempfile.TemporaryDirectory() as tmp:
        clip_files: dict[str, Path] = {}
        for segment in segments:
            if segment.clip not in clip_files:
                clip_file = Path(tmp) / (
                    hashlib.sha256(segment.clip.encode()).hexdigest()[:16] + ".mp3"
                )
                clip_file.write_bytes(
                    base64.b64decode(segment.clip.removeprefix(CLIP_PREFIX))
                )
                clip_files[segment.clip] = clip_file
        # the video is written under a name of its own and replaces an earlier one only once it is complete
        partial = out.with_name(out.stem + ".partial" + out.suffix)
        try:
            subprocess.run(
                mux_command(
                    video, video_duration(video), clip_files, segments, partial
                ),
                check=True,
            )
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        partial.replace(out)


def video_duration(video: Path) -> float:
    """@return: the length of the video (s), as ffprobe reads it"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return float(result.stdout)


def side_files(out: Path) -> tuple[Path, Path]:
    """@return: the picture alone and the voice segments, next to the video out"""
    return out.with_name(out.stem + ".video.mp4"), out.with_name(
        out.stem + ".voice.json"
    )


def render(
    page: Path,
    out: Path,
    seconds: float | None = None,
    hold: float = HOLD,
    browser: BrowserOptions = BrowserOptions(),
) -> None:
    """Renders the page into the video out and writes its two side files (see the module docstring).

    @param page: the HTML file
    @param out: the video to write
    @param seconds: how much of the film to render, or None for all of it
    @param hold: how long the last frame is held (s)
    @param browser: how the page is shown
    @raise RuntimeError: if the ffmpeg run that encodes the picture fails, or see ``record``; the side files and the
        video of an earlier render then stay as they were
    @raise ValueError: see ``record``; the files of an earlier render stay as they were
    @raise OSError: if the voice file cannot be written; the files of an earlier render stay as they were
    @raise subprocess.CalledProcessError: see ``mux``
    """
    video, voice = side_files(out)
    # the picture is encoded under a name of its own and replaces an earlier one only once it is complete
    partial = video.with_name(video.stem + ".partial.mp4")
    ffmpeg = subprocess.Popen(  # pylint: disable=consider-using-with
        video_command(partial, hold), stdin=subprocess.PIPE
    )
    assert ffmpeg.stdin is not None
    try:
        segments = record(page, ffmpeg, seconds, browser)
        ffmpeg.stdin.close()
        code: int = ffmpeg.wait()
    except BrokenPipeError as error:
        code = _stop(ffmpeg, partial, kill=False)
        raise RuntimeError(
            f"ffmpeg stopped reading the frames, exit code {code}"
        ) from error
    except BaseException:
        _stop(ffmpeg, partial, kill=True)
        raise
    if code != 0:
        _stop(ffmpeg, partial, kill=False)
        raise RuntimeError(f"ffmpeg failed with exit code {code}")
    # the voice, too, takes the place of an earlier one only once it is written, right after the picture's
    voice_partial = voice.with_name(voice.stem + ".partial.json")
    try:
        voice_partial.write_text(
            json.dumps([asdict(s) for s in segments]), encoding="utf-8"
        )
    except BaseException:
        partial.unlink(missing_ok=True)
        voice_partial.unlink(missing_ok=True)
        raise
    partial.replace(video)
    voice_partial.replace(voice)
    mux(video, segments, out)


def _stop(ffmpeg: subprocess.Popen[bytes], partial: Path, kill: bool) -> int:
    """Ends a failed encode: stops ffmpeg (at once if kill), waits for it and deletes the partial picture.

    @param ffmpeg: the ffmpeg run that encodes the picture
    @param partial: the file it writes
    @param kill: whether ffmpeg is stopped at once, instead of finishing the frames it has read
    @return: ffmpeg's exit code
    """
    if kill:
        ffmpeg.kill()
    assert ffmpeg.stdin is not None
    with contextlib.suppress(BrokenPipeError):
        ffmpeg.stdin.close()
    code: int = ffmpeg.wait()
    partial.unlink(missing_ok=True)
    return code


def main(argv: list[str] | None = None) -> None:
    """Reads the command line (see the module docstring) and renders, or only mixes the voice in again.

    @param argv: the arguments, or None for those of the process
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "page", type=Path, help="the HTML file (not read with --mux-only)"
    )
    parser.add_argument("out", type=Path, help="the video to write (.mp4)")
    parser.add_argument(
        "--seconds",
        type=lambda text: _seconds(text, above_zero=True),
        help="render only the first seconds of the film",
    )
    parser.add_argument(
        "--hold",
        type=lambda text: _seconds(text, above_zero=False),
        default=HOLD,
        help="seconds the last frame is held",
    )
    parser.add_argument(
        "--mux-only",
        action="store_true",
        help="only mix the voice into the picture again, from the side files of an earlier render",
    )
    args = parser.parse_args(argv)
    if args.mux_only:
        video, voice = side_files(args.out)
        segments = [Segment(**s) for s in json.loads(voice.read_text(encoding="utf-8"))]
        mux(video, segments, args.out)
    else:
        render(args.page, args.out, args.seconds, args.hold)


def _seconds(text: str, above_zero: bool) -> float:
    """Reads a number of seconds from the command line.

    @param text: the argument
    @param above_zero: whether 0 is too few
    @return: the seconds
    @raise argparse.ArgumentTypeError: if text is not a finite number of seconds, at least 0 (above 0 if above_zero)
    """
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0 or (above_zero and value == 0):
        raise argparse.ArgumentTypeError(
            f"not a number of seconds {'above' if above_zero else 'of at least'} 0: {text!r}"
        )
    return value


if __name__ == "__main__":
    main()
