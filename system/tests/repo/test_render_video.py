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

# Test modules use self-documenting method/class names and module-level
# fixtures, so pylint's naming and docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring,too-many-lines
"""Tests for ``tools/render_video.py``, which turns a three.js page of ``visualizations/`` into a video.

The tool is a script in ``tools/``, not part of a package, so it is loaded from its file path; it imports Playwright
only when it opens a browser, so it loads without it. The tests that open a browser are skipped without Playwright (its
Chromium must be installed with it), the tests of a video also without ffmpeg. The CI job ``render_video_test``
installs all of them, so nothing is skipped there. As in that job, the browser is Playwright's headless Chromium, which
draws WebGL in software. That job installs no numpy either, so the frames of a video are compared in plain Python.
"""

from __future__ import annotations

import base64
import contextlib
import errno
import importlib.util
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from time import monotonic, sleep
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

# the page tests fix the times of the row-or-column page's captions; the module, not its test classes, is imported,
# so that unittest does not run those tests here again:
from system.tests.repo import test_visualizations as page_tests

if TYPE_CHECKING:
    # pylint: disable-next=import-error
    from playwright.sync_api import Browser, Page, Playwright

    from tools.render_video import Segment

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
TOOL_PATH: Path = REPO_ROOT / "tools" / "render_video.py"


def load_tool() -> ModuleType:
    """Loads ``tools/render_video.py`` as a module."""
    spec = importlib.util.spec_from_file_location("render_video", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    # its dataclass looks the module up by its name while the module loads:
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool: ModuleType = load_tool()

# the tests of a video need ffmpeg and ffprobe:
FFMPEG_AVAILABLE: bool = (
    shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
)
FFMPEG_SKIP_REASON: str = "needs ffmpeg and ffprobe on the PATH"

# a CSS viewport as on a laptop (a much smaller one breaks the page's layout), at a quarter of its size in pixels
# (320×180), so that a frame is quick to take:
VIEWPORT: tuple[int, int] = (1280, 720)
SCALE: float = 0.25
PICTURE: tuple[int, int] = (round(VIEWPORT[0] * SCALE), round(VIEWPORT[1] * SCALE))
# how the tests open a page: in Playwright's Chromium (as in CI), which draws WebGL in software, without Chrome's
# sandbox, which does not start for root (CI runs the tests as root):
BROWSER_OPTIONS = tool.BrowserOptions(
    viewport=VIEWPORT,
    scale=SCALE,
    channel=None,
    allow_software_gpu=True,
    sandbox=False,
)

# the times (s) at which the segments of the row-or-column page's captions begin: the first segment of each step, and
# the second one of the row-layout and of the column-layout step:
SEGMENT_TIMES: list[float] = sorted(
    page_tests.RowOrColumnPageTest.FIRST_SEGMENTS
    + [
        page_tests.RowOrColumnPageTest.ROW_LAYOUT_SECOND_SEGMENT,
        page_tests.RowOrColumnPageTest.COLUMN_LAYOUT_SECOND_SEGMENT,
    ]
)
# the page starts the clip of a segment on a frame shortly after the segment's time, e.g. at 31/60 = 0.517 s for
# 0.5 s, and stops the last one on a frame shortly after the film's end:
TWO_FRAMES: float = 2 / tool.FPS
# a length of the video is exact to one frame:
ONE_FRAME: float = 1 / tool.FPS
# H.264 changes a pixel that stays the same from frame to frame by at most about 10 of 255 in a colour channel; a
# pixel that differs by more than NOISE, a margin above that, has changed in the picture:
NOISE: int = 16
# the stand-in logs each use of audio that it does not model as a console error that starts with this text:
STAND_IN_ERROR: str = "render_video: the stand-in does not model this use of audio: "
# an init script that makes WebGL 2 name its renderer RENDERER_NAME (put in as a JSON string), as the driver of a GPU
# would: as UNMASKED_RENDERER_WEBGL (0x9246) of the extension WEBGL_debug_renderer_info, and as RENDERER, which a
# browser without that extension names:
RENAMED_RENDERER: str = """(() => {
  const getParameter = WebGL2RenderingContext.prototype.getParameter;
  WebGL2RenderingContext.prototype.getParameter = function (name) {
    return name === 0x9246 || name === this.RENDERER ? RENDERER_NAME : getParameter.call(this, name);
  };
})();"""


def probe(video: Path) -> dict[str, Any]:
    """Reads the streams and the length of a video with ffprobe, which decodes it to count its frames.

    @param video: the video file
    @return: ffprobe's JSON output, with the list ``streams`` and the dict ``format``
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(video)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return json.loads(result.stdout)


def mean_volume(video: Path, start: float, end: float) -> float:
    """Measures the mean volume of a video's sound between two times, with ffmpeg's filter volumedetect.

    @param video: the video file
    @param start: where the measured stretch begins (s)
    @param end: where it ends (s)
    @return: the mean volume (dB); digital silence gives about -91 dB, speech about -30 dB
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a",
         "-af", f"atrim=start={start}:end={end},volumedetect", "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    # volumedetect writes its result to the error output:
    return float(re.findall(r"mean_volume: (\S+) dB", result.stderr)[-1])


def decode_frames(video: Path) -> list[bytes]:
    """Decodes every frame of a video to RGB: three bytes per pixel, row by row from the top left.

    @param video: the video file, with frames of ``PICTURE`` pixels
    @return: the frames in their order
    """
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    )  # fmt: skip
    size: int = PICTURE[0] * PICTURE[1] * 3
    return [result.stdout[i : i + size] for i in range(0, len(result.stdout), size)]


def pixels_apart(first: bytes, second: bytes) -> int:
    """Counts the pixels at which two frames differ by more than ``NOISE`` in a colour channel.

    @param first: a frame as ``decode_frames`` returns it
    @param second: another one
    @return: the number of pixels
    """
    apart: list[bool] = [abs(a - b) > NOISE for a, b in zip(first, second)]
    return sum(any(apart[i : i + 3]) for i in range(0, len(apart), 3))


def colours_in_the_middle(frame: bytes) -> int:
    """Counts the distinct colours in the middle of a frame: in half its width and half its height, around its centre.

    @param frame: a frame as ``decode_frames`` returns it
    @return: the number of colours
    """
    width, height = PICTURE
    colours: set[bytes] = set()
    for y in range(height // 4, 3 * height // 4):
        row: bytes = frame[
            (y * width + width // 4) * 3 : (y * width + 3 * width // 4) * 3
        ]
        colours.update(row[i : i + 3] for i in range(0, len(row), 3))
    return len(colours)


def black_frame() -> bytes:
    """Makes a frame as ffmpeg reads it from ``record``: a black PNG of 64×36 pixels.

    @return: the PNG file's bytes
    """
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=s=64x36", "-frames:v", "1",
         "-c:v", "png", "-f", "image2pipe", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip


class FrameSink:
    """Stands in for the ffmpeg run that ``_play`` writes the frames to: its stdin keeps each frame written to it."""

    def __init__(self) -> None:
        """Starts with no frames."""
        self.frames: list[bytes] = []
        self.stdin: SimpleNamespace = SimpleNamespace(write=self.frames.append)


class SegmentTest(unittest.TestCase):
    """Checks that a segment of the voice takes only values that describe a stretch of the film."""

    def test_a_segment_rejects_what_is_no_stretch_of_the_film(self) -> None:
        """A segment raises a ValueError for each value that describes no stretch of the film.

        These are a clip that is no MP3 data URI, an offset that is a string, not finite or negative, a rate that is a
        boolean, below 0.5 or above 100 (beyond what ffmpeg's atempo plays), a negative start, and an end at the start.
        The rates 0.5 and 100 themselves make a segment.
        """
        # these values make a segment, also with the lowest and the highest rate:
        valid: dict[str, Any] = {
            "clip": tool.CLIP_PREFIX + "Zmlyc3Q=",
            "rate": 1.1,
            "start": 0.5,
            "offset": 0.25,
            "end": 2.0,
        }
        tool.Segment(**valid)
        for rate in (0.5, 100):
            with self.subTest(rate=rate):
                self.assertEqual(rate, tool.Segment(**{**valid, "rate": rate}).rate)

        # each of these values, put in place of the valid one, makes none:
        invalid: list[tuple[str, Any]] = [
            ("clip", "data:audio/wav;base64,Zmlyc3Q="),
            ("offset", "0.25"),
            ("offset", math.inf),
            ("offset", -0.25),
            ("rate", True),
            ("rate", 0.4),
            ("rate", 100.5),
            ("start", -0.5),
            ("end", 0.5),
        ]
        for name, value in invalid:
            with self.subTest(name=name, value=value):
                with self.assertRaises(ValueError):
                    tool.Segment(**{**valid, name: value})


class SegmentsFromLogTest(unittest.TestCase):
    """Checks how the stand-in's log of starts and stops becomes the segments of the voice."""

    FIRST: str = "data:audio/mpeg;base64,Zmlyc3Q="
    SECOND: str = "data:audio/mpeg;base64,c2Vjb25k"

    def test_each_clip_sounds_from_its_start_to_its_stop(self) -> None:
        """Each clip becomes a segment from its start to its stop, with the rate and the position it started at.

        The start and stop at frame 0, with which the sound button lets the voice speak, last no time and give no
        segment; a clip still playing when the recording ends stops at last_frame. A time in the film is its frame / 60.
        """
        log: list[dict[str, Any]] = [
            # the sound button starts and stops the first clip at once:
            {"kind": "play", "frame": 0, "clip": self.FIRST, "rate": 1, "position": 0},
            {"kind": "pause", "frame": 0},
            # the first clip plays from 0.5 s to 2 s; then the page switches to the second clip, which starts 0.25 s
            # into it at 1.1 times its speed and still plays when the recording ends at 3 s:
            {"kind": "play", "frame": 30, "clip": self.FIRST, "rate": 1, "position": 0},
            {"kind": "pause", "frame": 120},
            {"kind": "play", "frame": 120, "clip": self.SECOND, "rate": 1.1, "position": 0.25},
        ]  # fmt: skip
        self.assertEqual(
            [
                tool.Segment(clip=self.FIRST, rate=1, start=0.5, offset=0, end=2.0),
                tool.Segment(
                    clip=self.SECOND, rate=1.1, start=2.0, offset=0.25, end=3.0
                ),
            ],
            tool.segments_from_log(log, 180),
        )

    def test_a_jump_inside_a_clip_splits_it_into_two_segments(self) -> None:
        """A jump to another position of the playing clip, a stop and a start in the same frame, gives two segments.

        The second one starts in the film where the first one stops, and in the clip at the position jumped to.
        """
        log: list[dict[str, Any]] = [
            # the clip plays from 0.5 s; at 1.5 s the page jumps to 2.5 s into it, and it plays on to the end at 2.5 s:
            {"kind": "play", "frame": 30, "clip": self.FIRST, "rate": 1, "position": 0},
            {"kind": "pause", "frame": 90},
            {"kind": "play", "frame": 90, "clip": self.FIRST, "rate": 1, "position": 2.5},
        ]  # fmt: skip
        self.assertEqual(
            [
                tool.Segment(clip=self.FIRST, rate=1, start=0.5, offset=0, end=1.5),
                tool.Segment(clip=self.FIRST, rate=1, start=1.5, offset=2.5, end=2.5),
            ],
            tool.segments_from_log(log, 150),
        )


class CheckRecordingTest(unittest.TestCase):
    """Checks when ``check_recording`` accepts a recording, and the reason it gives when it does not."""

    # the most frames the 52 s film of the row-or-column page may take, with the margin and frame 0, as ``record``
    # counts them:
    LIMIT: int = (
        round((page_tests.RowOrColumnPageTest.LENGTH + tool.FILM_MARGIN) * tool.FPS) + 1
    )

    def test_a_complete_recording_passes(self) -> None:
        """A film that has ended passes; so does a part of a film that still plays when only that part was recorded."""
        self.assertIsNone(tool.check_recording([], [], "ended", self.LIMIT))
        self.assertIsNone(tool.check_recording([], [], "playing", None))

    def test_each_flaw_of_a_recording_stops_it_with_its_reason(self) -> None:
        """An unmodelled use of audio, an error of the page, a film that stopped before its end and a film that had not
        ended by its last frame each raise a RuntimeError.

        An unmodelled use comes with the console error the stand-in logs for it; the use is named, not the error. A
        film that stopped, here paused, is rejected also when only a part of it was recorded (limit None).
        """
        flaws: list[tuple[str, list[str], list[str], str | None, int | None, str]] = [
            (
                "unmodelled",
                [STAND_IN_ERROR + "set volume"],
                ["set volume"],
                "ended",
                self.LIMIT,
                r"^the page uses its audio in ways the stand-in does not model: \['set volume'\]$",
            ),
            (
                "error",
                ["boom"],
                [],
                "ended",
                self.LIMIT,
                r"^the page logged errors: \['boom'\]$",
            ),
            (
                "paused",
                [],
                [],
                "paused",
                None,
                r"^the film stopped before its end: Play is 'paused'$",
            ),
            (
                "not ended",
                [],
                [],
                "playing",
                self.LIMIT,
                rf"^the film had not ended by frame {self.LIMIT - 1}$",
            ),
        ]
        for flaw, errors, unmodelled, reached, limit, reason in flaws:
            with self.subTest(flaw=flaw):
                with self.assertRaisesRegex(RuntimeError, reason):
                    tool.check_recording(errors, unmodelled, reached, limit)


class VideoCommandTest(unittest.TestCase):
    """Checks the ffmpeg command that encodes the picture and holds its last frame."""

    def test_the_hold_is_written_with_six_fixed_decimals(self) -> None:
        """The hold goes into the command in seconds with six fixed decimals, also a tiny one such as 1e-05 s.

        Python writes 1e-05 in exponent notation, which ffmpeg rejects.
        """
        for hold, written in ((1e-05, "0.000010"), (tool.HOLD, "3.000000")):
            with self.subTest(hold=hold):
                command: list[str] = tool.video_command(Path("picture.mp4"), hold)
                self.assertEqual(
                    f"tpad=stop_mode=clone:stop_duration={written}",
                    command[command.index("-vf") + 1].split(",")[0],
                )

    @unittest.skipUnless(FFMPEG_AVAILABLE, FFMPEG_SKIP_REASON)
    def test_ffmpeg_encodes_a_frame_with_a_tiny_hold(self) -> None:
        """ffmpeg accepts the command with a hold of 1e-05 s and encodes a frame into an H.264 picture."""
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        picture: Path = Path(folder.name) / "picture.mp4"

        # one frame, held for 1e-05 s, which adds no frame:
        subprocess.run(
            tool.video_command(picture, 1e-05), input=black_frame(), check=True
        )
        self.assertEqual(
            [("video", "h264", "1")],
            [
                (
                    stream["codec_type"],
                    stream["codec_name"],
                    stream.get("nb_read_frames"),
                )
                for stream in probe(picture)["streams"]
            ],
        )


class MuxCommandTest(unittest.TestCase):
    """Checks the ffmpeg command that mixes the voice into the picture."""

    def test_two_segments_of_one_clip_read_the_same_input(self) -> None:
        """A clip that sounds in two segments is given to ffmpeg once, as MP3, and both segments read it."""
        # one clip that sounds from 0.5 s to 1.5 s, and again from 1.5 s on, 2.5 s into it, in a picture of 3 s:
        clip: str = tool.CLIP_PREFIX + "Zmlyc3Q="
        segments: list[Segment] = [
            tool.Segment(clip=clip, rate=1, start=0.5, offset=0, end=1.5),
            tool.Segment(clip=clip, rate=1, start=1.5, offset=2.5, end=2.5),
        ]
        command: list[str] = tool.mux_command(
            Path("picture.mp4"),
            3.0,
            {clip: Path("clip.mp3")},
            segments,
            Path("out.mp4"),
        )

        # the inputs are the picture and the clip's file, which is read as MP3:
        self.assertEqual(
            ["picture.mp4", "clip.mp3"],
            [command[i + 1] for i, argument in enumerate(command) if argument == "-i"],
        )
        clip_input: int = command.index("clip.mp3")
        self.assertEqual(["-f", "mp3", "-i"], command[clip_input - 3 : clip_input])

        # both segments read input 1, the clip, each placed at its own start in samples, and both are mixed:
        parts: list[str] = command[command.index("-filter_complex") + 1].split(";")
        self.assertEqual(["[1:a]", "[1:a]"], [part[:5] for part in parts[:2]])
        self.assertIn("adelay=delays=24000S", parts[0])
        self.assertIn("adelay=delays=72000S", parts[1])
        self.assertEqual(
            "[a0][a1]amix=inputs=2:normalize=0,"
            "apad=whole_dur=3.0,atrim=end_sample=144000,asetpts=N/SR/TB[voice]",
            parts[2],
        )

    def test_a_segment_is_cut_from_its_clip_sped_up_stopped_and_placed_in_this_order(
        self,
    ) -> None:
        """A segment's filter cuts the clip at the offset, plays it at its rate, stops it, then delays it to its start.

        Only in this order is the offset counted in the clip's time and the stop in the film's time. The voice is then
        padded and cut to the picture's length, counted in samples. ffmpeg reads no keys from the terminal.
        """
        # one clip, played from 0.25 s into it at 1.1 times its speed, from 0.5 s to 2 s of a picture of 3 s:
        clip: str = tool.CLIP_PREFIX + "Zmlyc3Q="
        command: list[str] = tool.mux_command(
            Path("picture.mp4"),
            3.0,
            {clip: Path("clip.mp3")},
            [tool.Segment(clip=clip, rate=1.1, start=0.5, offset=0.25, end=2.0)],
            Path("out.mp4"),
        )

        # the clip at 48 kHz in stereo, from its offset, sped up, stopped after the 1.5 s the segment lasts in the film,
        # and delayed by 0.5 s (24000 samples); the voice lasts the 3 s of the picture, 144000 samples:
        self.assertEqual(
            [
                "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                "atrim=start=0.250000,asetpts=PTS-STARTPTS,atempo=1.1,"
                "atrim=end=1.500000,asetpts=PTS-STARTPTS,adelay=delays=24000S:all=1[a0]",
                "[a0]amix=inputs=1:normalize=0,"
                "apad=whole_dur=3.0,atrim=end_sample=144000,asetpts=N/SR/TB[voice]",
            ],
            command[command.index("-filter_complex") + 1].split(";"),
        )
        self.assertIn("-nostdin", command)


class MainTest(unittest.TestCase):
    """Checks how ``main`` reads the seconds of ``--seconds`` and ``--hold``; ``render`` is replaced by a mock."""

    def test_seconds_that_are_no_length_stop_the_tool_before_it_renders(self) -> None:
        """``--seconds`` that are not a finite number above 0, and a ``--hold`` that is not a finite number of at least
        0, stop the tool with exit code 2 and say why, before it renders (and opens a browser).
        """
        # each option with a value that it does not take, and the reason the tool gives:
        cases: list[tuple[str, str, str]] = [
            ("--seconds", "0", "above"),
            ("--seconds", "-1", "above"),
            ("--seconds", "nan", "above"),
            ("--seconds", "inf", "above"),
            ("--seconds", "abc", "above"),
            ("--hold", "-1", "of at least"),
            ("--hold", "nan", "of at least"),
        ]
        for option, value, bound in cases:
            with self.subTest(option=option, value=value):
                usage = io.StringIO()
                with (
                    mock.patch.object(tool, "render") as render,
                    contextlib.redirect_stderr(usage),
                ):
                    with self.assertRaises(SystemExit) as exited:
                        tool.main(["page.html", "out.mp4", option, value])

                # the tool stopped as for any wrong argument, and did not render:
                self.assertEqual(2, exited.exception.code)
                self.assertIn(
                    f"argument {option}: not a number of seconds {bound} 0: {value!r}",
                    usage.getvalue(),
                )
                render.assert_not_called()

    def test_seconds_above_0_and_a_hold_of_0_reach_the_render(self) -> None:
        """``--seconds`` above 0 and a ``--hold`` of 0 are passed on to ``render`` as numbers."""
        with mock.patch.object(tool, "render") as render:
            tool.main(["page.html", "out.mp4", "--seconds", "0.5", "--hold", "0"])
        render.assert_called_once_with(Path("page.html"), Path("out.mp4"), 0.5, 0.0)


@unittest.skipUnless(FFMPEG_AVAILABLE, FFMPEG_SKIP_REASON)
class MuxTest(unittest.TestCase):
    """Checks the sound that ``mux`` mixes into a silent picture of 3 s from two segments of a tone of 2 s (440 Hz).

    Both play the tone at twice its speed. The first one plays it from its start, from 0.5 s on, and the page stops it
    at 1.3 s, before the tone has ended (at 1.5 s). The second one plays it from 1 s into it, from 2 s on, so the tone
    ends at 2.5 s, before the page stops it at 3 s.
    """

    LENGTH: float = 3.0
    out: Path

    @classmethod
    def setUpClass(cls) -> None:
        """Makes the tone and the picture with ffmpeg and mixes them once for all tests of the class."""
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        cls.addClassCleanup(folder.cleanup)
        tone: Path = Path(folder.name) / "tone.mp3"
        picture: Path = Path(folder.name) / "picture.mp4"
        cls.out = Path(folder.name) / "out.mp4"

        # the tone as MP3, and a black picture of 64×36 pixels at 60 fps:
        for command in (
            ["-f", "lavfi", "-i", "sine=f=440:d=2", str(tone)],
            ["-f", "lavfi", "-i", f"color=s=64x36:r=60:d={cls.LENGTH}", "-c:v", "libx264", str(picture)],
        ):  # fmt: skip
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", *command], check=True)

        # the tone as the page holds a clip, in a data URI:
        clip: str = tool.CLIP_PREFIX + base64.b64encode(tone.read_bytes()).decode()
        tool.mux(
            picture,
            [
                tool.Segment(clip=clip, rate=2, start=0.5, offset=0, end=1.3),
                tool.Segment(clip=clip, rate=2, start=2.0, offset=1.0, end=3.0),
            ],
            cls.out,
        )

    def test_each_segment_sounds_from_its_offset_at_its_rate_until_its_clip_or_the_page_stops_it(
        self,
    ) -> None:
        """The tone sounds from 0.5 s to 1.3 s and from 2 s to 2.5 s; before, between and after, the sound is silent.

        The first segment's stop is counted in the film's time: counted in the tone's time, its 0.8 s would end at
        0.9 s. The second segment starts 1 s into the tone and plays it at twice its speed: from the tone's start, or
        at its own speed, it would sound until the page stops it at 3 s; with its offset of 1 s cut after the
        speed-up, it would skip 2 s of the tone, all of it.
        """
        # a tone is loud (about -25 dB); digital silence gives about -91 dB:
        loud: list[tuple[float, float]] = [(0.55, 0.85), (1.0, 1.25), (2.05, 2.45)]
        silent: list[tuple[float, float]] = [(0, 0.45), (1.35, 1.95), (2.6, 3.0)]
        for start, end in loud:
            with self.subTest(loud=(start, end)):
                self.assertGreater(mean_volume(self.out, start, end), -50)
        for start, end in silent:
            with self.subTest(silent=(start, end)):
                self.assertLess(mean_volume(self.out, start, end), -80)

    def test_the_voice_lasts_exactly_as_long_as_the_picture(self) -> None:
        """The sound starts at 0 and lasts the 3 s of the picture, 144000 samples at 48 kHz, after the last segment."""
        streams: dict[str, dict[str, Any]] = {
            stream["codec_type"]: stream for stream in probe(self.out)["streams"]
        }
        self.assertEqual("3.000000", streams["video"]["duration"])
        self.assertEqual(
            {"start_time": "0.000000", "duration_ts": 144000, "time_base": "1/48000"},
            {
                key: streams["audio"].get(key)
                for key in ("start_time", "duration_ts", "time_base")
            },
        )


@unittest.skipUnless(FFMPEG_AVAILABLE, FFMPEG_SKIP_REASON)
class RenderFailureTest(unittest.TestCase):
    """Checks that a render that fails stops with an error and keeps the files that ``--mux-only`` or a later render
    needs.

    A render that fails while it records or writes its side files leaves the three files of an earlier render as they
    were; a render whose voice mix fails leaves the earlier video and keeps its own two new side files. No browser is
    opened: ``record`` is replaced by a function that writes frames to ffmpeg and then fails or returns, and in some
    tests an ffmpeg run by a Python process that fails.
    """

    # the files an earlier render left in the folder, with the bytes they hold, which no render writes:
    EARLIER: dict[str, bytes] = {
        "film.mp4": b"the earlier video",
        "film.video.mp4": b"the earlier picture",
        "film.voice.json": b"the earlier voice",
    }
    # in place of the ffmpeg run that mixes the voice in: a process that writes a part of the video into the file it is
    # given and exits with exit code 5:
    FAILING_MIX: str = "import sys; open(sys.argv[1], 'wb').write(b'part'); sys.exit(5)"
    frame: bytes
    segment: Segment

    @classmethod
    def setUpClass(cls) -> None:
        """Makes one frame and one voice segment for all tests of the class: a black PNG of 64×36 pixels, and a tone
        of 0.1 s as an MP3 data URI, which sounds through the first three frames."""
        cls.frame = black_frame()
        tone: bytes = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=0.1", "-f", "mp3", "-"],
            check=True, capture_output=True,
        ).stdout  # fmt: skip
        cls.segment = tool.Segment(
            clip=tool.CLIP_PREFIX + base64.b64encode(tone).decode(),
            rate=1,
            start=0,
            offset=0,
            end=3 / tool.FPS,
        )

    def record_three_frames(
        self, _page: Path, frames_to: subprocess.Popen[bytes] | None, *_: object
    ) -> list[Segment]:
        """Stands in for ``record``: writes three frames to ffmpeg and returns a voice of the one segment.

        @param frames_to: ffmpeg, which reads the frames on its stdin
        @return: the voice segments
        """
        assert frames_to is not None and frames_to.stdin is not None
        for _ in range(3):
            frames_to.stdin.write(self.frame)
        return [self.segment]

    def failing_mux_command(self, *arguments: Any) -> list[str]:
        """Stands in for ``mux_command``: the command of ``FAILING_MIX``, given the video to write, the last argument.

        @param arguments: those of ``mux_command``
        @return: the command
        """
        return [sys.executable, "-c", self.FAILING_MIX, str(arguments[-1])]

    def earlier_render(self) -> Path:
        """Writes the files of an earlier render into a folder that is removed after the test.

        @return: the earlier render's video, which the test renders again
        """
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        for name, content in self.EARLIER.items():
            (Path(folder.name) / name).write_bytes(content)
        return Path(folder.name) / "film.mp4"

    def assert_earlier_render_kept(self, out: Path) -> None:
        """Asserts that the folder of out holds the files of the earlier render, unchanged, and no other file."""
        self.assertEqual(
            self.EARLIER,
            {path.name: path.read_bytes() for path in out.parent.iterdir()},
        )

    def test_a_failed_recording_leaves_an_earlier_render_as_it_was(self) -> None:
        """A recording that fails after ffmpeg has begun the picture stops the render with the recording's error.

        ffmpeg is stopped and its partial picture deleted; the earlier video and its side files are unchanged.
        """
        out: Path = self.earlier_render()
        partial: Path = out.with_name("film.video.partial.mp4")
        began: list[bool] = []

        def record(
            _page: Path, frames_to: subprocess.Popen[bytes] | None, *_: object
        ) -> list[Segment]:
            """Writes 6 s of frames, waits until ffmpeg has begun its picture, and fails as a page with an error
            does."""
            assert frames_to is not None and frames_to.stdin is not None
            # ffmpeg begins its picture once it has looked at 5 s of frames:
            for _ in range(6 * tool.FPS):
                frames_to.stdin.write(self.frame)
            frames_to.stdin.flush()

            # wait until it has (at most 30 s), then fail:
            deadline: float = monotonic() + 30
            while not partial.exists() and monotonic() < deadline:
                sleep(0.05)
            began.append(partial.exists())
            raise RuntimeError("the page logged errors: ['boom']")

        # the error of the recording stops the render:
        with mock.patch.object(tool, "record", record):
            with self.assertRaisesRegex(
                RuntimeError, r"^the page logged errors: \['boom'\]$"
            ):
                tool.render(page_tests.ROW_OR_COLUMN_PAGE, out)

        # ffmpeg had begun the partial picture, which is gone now, as are all traces of the failed render:
        self.assertEqual([True], began)
        self.assert_earlier_render_kept(out)

    def test_ffmpeg_that_stops_reading_the_frames_stops_the_render(self) -> None:
        """If ffmpeg exits while frames are still written to it, the render stops with its exit code.

        The earlier video and its side files are unchanged.
        """
        out: Path = self.earlier_render()

        def record(
            _page: Path, frames_to: subprocess.Popen[bytes] | None, *_: object
        ) -> list[Segment]:
            """Writes frames of 1 MiB until ffmpeg reads no more."""
            assert frames_to is not None and frames_to.stdin is not None
            for _ in range(1000):
                frames_to.stdin.write(bytes(1 << 20))
            raise AssertionError("ffmpeg read 1000 MiB of frames")

        # in place of ffmpeg, a process that exits at once with exit code 3:
        exits_at_once: list[str] = [sys.executable, "-c", "raise SystemExit(3)"]
        with (
            mock.patch.object(tool, "video_command", lambda _out, _hold: exits_at_once),
            mock.patch.object(tool, "record", record),
        ):
            with self.assertRaisesRegex(
                RuntimeError, r"^ffmpeg stopped reading the frames, exit code 3$"
            ):
                tool.render(page_tests.ROW_OR_COLUMN_PAGE, out)
        self.assert_earlier_render_kept(out)

    def test_ffmpeg_that_fails_after_the_last_frame_stops_the_render(self) -> None:
        """If ffmpeg reads all frames but exits with an error, the render stops with its exit code.

        The partial picture it wrote is deleted; the earlier video and its side files are unchanged.
        """
        out: Path = self.earlier_render()

        def record(
            _page: Path, frames_to: subprocess.Popen[bytes] | None, *_: object
        ) -> list[Segment]:
            """Writes one frame and records no voice."""
            assert frames_to is not None and frames_to.stdin is not None
            frames_to.stdin.write(self.frame)
            return []

        # in place of ffmpeg, a process that reads all frames, writes a partial picture and exits with exit code 4:
        encoder: str = (
            "import sys; sys.stdin.buffer.read(); open(sys.argv[1], 'wb').write(b'part'); sys.exit(4)"
        )
        with (
            mock.patch.object(
                tool,
                "video_command",
                lambda partial, _hold: [sys.executable, "-c", encoder, str(partial)],
            ),
            mock.patch.object(tool, "record", record),
        ):
            with self.assertRaisesRegex(
                RuntimeError, r"^ffmpeg failed with exit code 4$"
            ):
                tool.render(page_tests.ROW_OR_COLUMN_PAGE, out)
        self.assert_earlier_render_kept(out)

    def test_a_failed_write_of_the_voice_leaves_an_earlier_render_as_it_was(
        self,
    ) -> None:
        """If the voice cannot be written once ffmpeg has encoded the picture, the render stops with the error.

        The new picture and the part of the voice written so far are deleted; the earlier video and its side files are
        unchanged.
        """
        out: Path = self.earlier_render()
        written: list[Path] = []

        def full_disk(path: Path, text: str, *_: object, **_options: object) -> int:
            """Stands in for ``Path.write_text``: writes the first half of the text, then fails as on a full disk."""
            written.append(path)
            with open(path, "w", encoding="utf-8") as file:
                file.write(text[: len(text) // 2])
            raise OSError(errno.ENOSPC, "No space left on device")

        # ffmpeg encodes the picture, and the disk is full while the voice is written:
        with (
            mock.patch.object(tool, "record", self.record_three_frames),
            mock.patch.object(Path, "write_text", full_disk),
        ):
            with self.assertRaises(OSError) as raised:
                tool.render(page_tests.ROW_OR_COLUMN_PAGE, out, hold=0)
        self.assertEqual(errno.ENOSPC, raised.exception.errno)

        # the voice was being written under a name of its own; that part and the new picture are gone:
        self.assertEqual([out.with_name("film.voice.partial.json")], written)
        self.assert_earlier_render_kept(out)

    def test_a_failed_voice_mix_leaves_an_earlier_video_as_it_was(self) -> None:
        """If the ffmpeg run that mixes the voice in fails, ``mux`` raises its error and deletes the partial video.

        The earlier video and its side files are unchanged.
        """
        out: Path = self.earlier_render()

        # the mix of a picture of 1 s without voice, by a process that writes a partial video and fails:
        with (
            mock.patch.object(tool, "video_duration", lambda _video: 1.0),
            mock.patch.object(
                tool, "mux_command", side_effect=self.failing_mux_command
            ) as mux_command,
        ):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                tool.mux(out.with_name("film.video.mp4"), [], out)
        self.assertEqual(5, raised.exception.returncode)

        # the process wrote its part of the video under a name of its own next to the video; that file is gone:
        self.assertEqual(
            out.with_name("film.partial.mp4"), mux_command.call_args.args[-1]
        )
        self.assert_earlier_render_kept(out)

    def test_a_failed_voice_mix_keeps_the_new_side_files_for_mux_only(self) -> None:
        """If only the voice mix of a render fails, the render raises its error and keeps its new side files.

        The earlier video stays as it was, next to the new picture and voice, from which ``--mux-only`` then makes the
        video.
        """
        out: Path = self.earlier_render()

        # ffmpeg encodes the picture, and the mix fails:
        with (
            mock.patch.object(tool, "record", self.record_three_frames),
            mock.patch.object(
                tool, "mux_command", side_effect=self.failing_mux_command
            ),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                tool.render(page_tests.ROW_OR_COLUMN_PAGE, out, hold=0)

        # the earlier video is unchanged, no partial file is left, and the side files are those of the new render: the
        # picture of three frames and the voice of one segment:
        self.assertEqual(self.EARLIER["film.mp4"], out.read_bytes())
        self.assertEqual(
            sorted(self.EARLIER), sorted(path.name for path in out.parent.iterdir())
        )
        picture, voice = tool.side_files(out)
        self.assertEqual(
            [("video", "3")],
            [
                (stream["codec_type"], stream.get("nb_read_frames"))
                for stream in probe(picture)["streams"]
            ],
        )
        self.assertEqual(
            [self.segment],
            [
                tool.Segment(**entry)
                for entry in json.loads(voice.read_text(encoding="utf-8"))
            ],
        )

        # from them, --mux-only makes the video, with picture and voice:
        tool.main(["--mux-only", str(page_tests.ROW_OR_COLUMN_PAGE), str(out)])
        self.assertEqual(
            [("video", "h264"), ("audio", "aac")],
            [
                (stream["codec_type"], stream["codec_name"])
                for stream in probe(out)["streams"]
            ],
        )


@unittest.skipUnless(page_tests.PLAYWRIGHT_AVAILABLE, page_tests.SKIP_REASON)
class RecordLaunchTest(unittest.TestCase):
    """Checks how ``record`` launches the browser, without launching one: Playwright is replaced by a stand-in."""

    def test_chrome_runs_in_its_sandbox_unless_the_options_switch_it_off(
        self,
    ) -> None:
        """By default, ``record`` launches Google Chrome in its sandbox; the tests' options launch Playwright's
        Chromium without it.

        CI runs as root, for which the sandbox does not start, so only the arguments of the launch are checked.
        """

        class Launched(Exception):
            """Stops ``record`` right after the launch."""

        launches: list[dict[str, Any]] = []

        def launch(**arguments: Any) -> None:
            """Stands in for Playwright's ``chromium.launch``: notes its arguments and stops ``record``."""
            launches.append(arguments)
            raise Launched

        playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
        # the options record is given (none: its default), and the arguments it launches the browser with:
        cases: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
            ("default", {}, {"channel": "chrome", "chromium_sandbox": True}),
            (
                "tests",
                {"browser": BROWSER_OPTIONS},
                {"channel": None, "chromium_sandbox": False},
            ),
        ]
        for options, given, launched in cases:
            with self.subTest(options=options):
                launches.clear()
                with mock.patch(
                    "playwright.sync_api.sync_playwright",
                    lambda: contextlib.nullcontext(playwright),
                ):
                    with self.assertRaises(Launched):
                        tool.record(page_tests.ROW_OR_COLUMN_PAGE, None, **given)
                self.assertEqual([launched], launches)


@unittest.skipUnless(page_tests.PLAYWRIGHT_AVAILABLE, page_tests.SKIP_REASON)
class RecordTest(unittest.TestCase):
    """Checks the voice that ``record`` takes from the whole row-or-column page, without taking its picture."""

    segments: list[Segment]

    @classmethod
    def setUpClass(cls) -> None:
        """Records the voice of the whole film once for all tests of the class."""
        cls.segments = tool.record(
            page_tests.ROW_OR_COLUMN_PAGE, None, browser=BROWSER_OPTIONS
        )

    def test_a_clip_starts_where_each_segment_of_a_caption_begins(self) -> None:
        """Exactly one clip starts at each of the 9 segments' times, or up to two frames later, from its beginning."""
        starts: list[float] = sorted(segment.start for segment in self.segments)
        self.assertEqual(len(SEGMENT_TIMES), len(starts), starts)

        # the n-th start belongs to the n-th segment's time:
        for time, start in zip(SEGMENT_TIMES, starts):
            with self.subTest(time=time):
                self.assertGreaterEqual(start - time, 0, starts)
                self.assertLessEqual(start - time, TWO_FRAMES, starts)

        # each clip plays from its beginning:
        self.assertEqual(
            [0] * len(self.segments), [segment.offset for segment in self.segments]
        )

    def test_the_last_clip_plays_faster_until_the_page_stops_it(self) -> None:
        """The last clip plays faster, at most 1.15 times as fast, and the page stops it where the film ends.

        At its own speed, the clip is longer than the time left in the film; its segment ends where the page stops it,
        which may be after the clip has said its last word.
        """
        last: Segment = self.segments[-1]
        self.assertGreater(last.rate, 1)
        self.assertLessEqual(last.rate, page_tests.RowOrColumnPageTest.MAX_RATE)

        # the film is 52 s long; the recording ends on the frame after it has ended:
        self.assertAlmostEqual(
            page_tests.RowOrColumnPageTest.LENGTH, last.end, delta=TWO_FRAMES
        )


@unittest.skipUnless(page_tests.PLAYWRIGHT_AVAILABLE, page_tests.SKIP_REASON)
class OpenedPageTest(unittest.TestCase):  # pylint: disable=too-many-public-methods
    """Checks the virtual clock and the stand-in of ``INIT_SCRIPT``, the start that ``open_page`` gives a page, the
    stops of ``_play``, the requests that ``allow_only`` lets a page make and the errors that ``prepare_page`` logs.

    Each test opens its pages with ``prepare_page``, as ``record`` does, each in a browser context of its own; the
    browser is started once for the class.
    """

    playwright: Playwright
    browser: Browser

    @classmethod
    def setUpClass(cls) -> None:
        """Starts Playwright and Chromium; both are stopped after the last test of the class, also if one fails."""
        # pylint: disable-next=import-error,import-outside-toplevel
        from playwright.sync_api import sync_playwright

        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def new_page(
        self, errors: list[str], path: Path = page_tests.ROW_OR_COLUMN_PAGE
    ) -> Page:
        """Opens a blank page with ``prepare_page``, as ``record`` does, in a context that is closed after the test.

        @param errors: filled with the page's uncaught exceptions and console errors, and each request it is refused
        @param path: the HTML file the page will show; the page may load only the files in its folder
        @return: the page, with the virtual clock and the stand-in installed
        """
        page: Page = tool.prepare_page(self.browser, path, BROWSER_OPTIONS, errors)
        self.addCleanup(page.context.close)
        return page

    def stub_page(self, script: str) -> Path:
        """Writes a page with only the controls that ``open_page`` uses into a folder that is removed after the test.

        Play is disabled until the page's script enables it; a click on Play starts the film, a click on the sound
        button switches the sound on, and the clock shows a film of 1 s.

        @param script: the page's own script, which runs once the controls are there (the constants play and sound
            hold Play and the sound button)
        @return: the page's HTML file
        """
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        path: Path = Path(folder.name) / "stub.html"
        path.write_text(
            """<!doctype html>
            <button data-testid="play" data-state="paused" disabled>Play</button>
            <button data-testid="sound" aria-pressed="false">Sound</button>
            <span data-testid="clock">0:00 / 0:01</span>
            <script>
              const play = document.querySelector('[data-testid=play]');
              const sound = document.querySelector('[data-testid=sound]');
              play.addEventListener('click', () => { play.dataset.state = 'playing'; });
              sound.addEventListener('click', () => { sound.setAttribute('aria-pressed', 'true'); });
            </script>
            <script>""" + script + "</script>",
            encoding="utf-8",
        )
        return path

    def open_row_or_column_page(self, errors: list[str]) -> tuple[Page, int]:
        """Opens the row-or-column page with ``open_page``, which starts it with sound on and shows frame 0.

        @param errors: filled with the page's uncaught exceptions and console errors
        @return: the page and the most steps its film may take
        """
        page: Page = self.new_page(errors)
        most: int = tool.open_page(
            page, page_tests.ROW_OR_COLUMN_PAGE, errors, allow_software_gpu=True
        )
        return page, most

    def test_the_stand_in_reports_what_it_does_not_model(self) -> None:
        """Reading the duration, setting the volume and listening for the end of a clip or for time updates are
        reported.

        Each such use is listed as unmodelled and logged once as a console error, which stops a render. A listener is
        reported both when it is added and when it is set as an on-property (``ontimeupdate``).
        """
        errors: list[str] = []
        page: Page = self.new_page(errors)
        page.goto(page_tests.ROW_OR_COLUMN_PAGE.as_uri())
        voice = page.get_by_test_id("voice")

        # loading, the page itself does nothing that the stand-in does not model:
        self.assertEqual([], page.evaluate("window.__video.unmodelled()"))
        self.assertEqual([], errors)

        # one read (twice), one setting and two listeners the stand-in does not model:
        voice.evaluate("audio => audio.duration")
        voice.evaluate("audio => audio.duration")
        voice.evaluate("audio => { audio.volume = 0.5; }")
        voice.evaluate("audio => audio.addEventListener('ended', () => {})")
        voice.evaluate("audio => { audio.ontimeupdate = () => {}; }")
        self.assertEqual(
            ["listen ended", "listen timeupdate", "read duration", "set volume"],
            sorted(page.evaluate("window.__video.unmodelled()")),
        )

        # each use is logged once, in the order the page made them:
        self.assertEqual(
            [
                STAND_IN_ERROR + use
                for use in (
                    "read duration",
                    "set volume",
                    "listen ended",
                    "listen timeupdate",
                )
            ],
            errors,
        )

    def test_the_stand_in_moves_the_position_at_the_speed_and_logs_a_jump(
        self,
    ) -> None:
        """While a clip plays, its position moves on with the virtual clock at its speed; a jump while it plays is
        logged as a stop and a start in the same frame.

        The clip plays at 1.5 times its speed from frame 0, so at frame 30 (0.5 s) it is 0.75 s into it. There the page
        jumps to 2.5 s, and at frame 60 it pauses the clip at 3.25 s. The log gives two segments of 0.5 s in the film:
        one from the clip's start, one from 2.5 s into it.
        """
        mp3: str = tool.CLIP_PREFIX + "Zmlyc3Q="
        errors: list[str] = []
        page: Page = self.new_page(errors)
        steps: str = "(n) => { for (let i = 0; i < n; i += 1) window.__video.step(); }"

        # an audio element plays its clip at 1.5 times its speed from frame 0; 30 frames on, it is 0.75 s into it:
        page.evaluate(
            f"() => {{ window.audio = new Audio('{mp3}'); audio.playbackRate = 1.5; audio.play(); }}"
        )
        page.evaluate(steps, 30)
        self.assertEqual(0.75, page.evaluate("audio.currentTime"))

        # the page jumps to 2.5 s into the clip while it plays, and pauses it 30 frames later, at 3.25 s:
        page.evaluate("() => { audio.currentTime = 2.5; }")
        page.evaluate(steps, 30)
        page.evaluate("() => { audio.pause(); }")
        self.assertEqual(3.25, page.evaluate("audio.currentTime"))

        # the log holds the start, the stop and start of the jump, and the pause:
        log: list[dict[str, Any]] = page.evaluate("window.__video.log")
        self.assertEqual(
            [
                {"kind": "play", "frame": 0, "clip": mp3, "rate": 1.5, "position": 0},
                {"kind": "pause", "frame": 30},
                {
                    "kind": "play",
                    "frame": 30,
                    "clip": mp3,
                    "rate": 1.5,
                    "position": 2.5,
                },
                {"kind": "pause", "frame": 60},
            ],
            log,
        )

        # it gives the two segments, the second one from 2.5 s into the clip:
        self.assertEqual(
            [
                tool.Segment(clip=mp3, rate=1.5, start=0, offset=0, end=0.5),
                tool.Segment(clip=mp3, rate=1.5, start=0.5, offset=2.5, end=1.0),
            ],
            tool.segments_from_log(log, 61),
        )
        self.assertEqual([], errors)

    def test_a_frame_callback_cancelled_by_an_earlier_one_of_its_frame_does_not_run(
        self,
    ) -> None:
        """A frame callback that an earlier callback of the same frame cancels does not run, as in a browser.

        ``flush`` counts only the callbacks that ran, and the cancelled one does not come back in the next frame. A
        callback cancelled before its frame does not run either.
        """
        errors: list[str] = []
        page: Page = self.new_page(errors)

        # three callbacks of one frame: the first cancels the second, and the third is cancelled before the frame; then
        # the frame and the next one are run:
        flushed: list[Any] = page.evaluate("""() => {
            const ran = [];
            let second = null;
            requestAnimationFrame(() => { ran.push('first'); cancelAnimationFrame(second); });
            second = requestAnimationFrame(() => { ran.push('second'); });
            cancelAnimationFrame(requestAnimationFrame(() => { ran.push('third'); }));
            return [window.__video.flush(), window.__video.flush(), ran];
        }""")  # fmt: skip

        # only the first callback ran, in the first frame; the next frame ran none:
        self.assertEqual([1, 0, ["first"]], flushed)
        self.assertEqual([], errors)

    def test_the_stand_in_reports_a_start_that_the_mix_cannot_play(self) -> None:
        """A clip that starts and is no MP3 data URI, plays slower than ``RATES`` allows, or starts from a position that
        is not a finite number >= 0 is reported at its start.

        Each report is listed as unmodelled and logged as a console error, which stops a render at once. An MP3 data
        URI at the slowest speed of ``RATES`` from position 0 is not reported. (Chrome refuses speeds above 16, so a
        page cannot set one above the fastest speed of ``RATES``.)
        """
        mp3: str = tool.CLIP_PREFIX + "Zmlyc3Q="
        # what is set on a new audio element (speed 1, position 0) before it plays, and what its start reports:
        cases: list[tuple[str, list[str]]] = [
            (
                "audio.src = 'data:audio/ogg;base64,T2dnUw==';",
                ["play a clip that is no MP3 data URI"],
            ),
            (f"audio.src = '{mp3}'; audio.playbackRate = 0.25;", ["play at rate 0.25"]),
            (
                f"audio.src = '{mp3}'; audio.currentTime = NaN;",
                ["play from position NaN"],
            ),
            (
                f"audio.src = '{mp3}'; audio.currentTime = -1;",
                ["play from position -1"],
            ),
            (f"audio.src = '{mp3}'; audio.playbackRate = {tool.RATES[0]};", []),
        ]
        for change, reports in cases:
            with self.subTest(change=change):
                # an audio element of a page of its own, changed while it is paused, then played:
                errors: list[str] = []
                page: Page = self.new_page(errors)
                page.evaluate(
                    f"() => {{ const audio = new Audio(); {change} audio.play(); }}"
                )

                # the start is reported, and logged once:
                self.assertEqual(reports, page.evaluate("window.__video.unmodelled()"))
                self.assertEqual(
                    [STAND_IN_ERROR + report for report in reports], errors
                )

    def test_the_stand_in_reports_each_on_property_of_an_event_it_does_not_send(
        self,
    ) -> None:
        """Setting the on-property of an event that the stand-in does not send, e.g. ``onprogress``, is reported as
        listening for that event.

        The stand-in sends only the events play, playing and pause; a page may also listen for waiting, which never
        comes, as a clip is always loaded. A page that listens for any other event of its voice would get it never, or
        from the real element, which still loads the clip, at a time that does not follow the virtual clock.
        """
        errors: list[str] = []
        page: Page = self.new_page(errors)
        types: list[str] = [
            "ended", "timeupdate", "seeked", "seeking", "loadedmetadata", "loadeddata", "canplay", "canplaythrough",
            "durationchange", "ratechange", "error", "stalled", "loadstart", "progress", "suspend", "emptied", "abort",
            "volumechange",
        ]  # fmt: skip

        # an audio element on which each on-property is set, in this order; each is reported and logged:
        page.evaluate(
            "(types) => { const audio = new Audio(); for (const type of types) audio['on' + type] = () => {}; }",
            types,
        )
        reports: list[str] = [f"listen {type_}" for type_ in types]
        self.assertEqual(reports, page.evaluate("window.__video.unmodelled()"))
        self.assertEqual([STAND_IN_ERROR + report for report in reports], errors)

    def test_a_change_of_the_playing_clip_or_a_second_audio_element_stops_the_film(
        self,
    ) -> None:
        """Setting the voice's speed, clip or default speed while it plays, and playing a second audio element, are
        reported and stop ``_play``.

        All are listed as unmodelled and logged as console errors, so ``_play`` stops before its next step; if it takes
        frames, it has taken only the first one. The page itself, which sets the speed and the clip of its voice before
        it plays a clip, makes no such change.
        """
        changes: list[str] = [
            "set playbackRate while playing",
            "set src while playing",
            "set defaultPlaybackRate while playing",
            "play a second audio element",
        ]
        for frames_to in (None, FrameSink()):
            with self.subTest(taking_frames=frames_to is not None):
                errors: list[str] = []
                page, most = self.open_row_or_column_page(errors)
                voice = page.get_by_test_id("voice")

                # 40 frames on, at 0.67 s, the voice plays the first caption's clip; so far the page has changed
                # nothing that the stand-in does not model:
                for _ in range(40):
                    page.evaluate("window.__video.step()")
                self.assertFalse(voice.evaluate("audio => audio.paused"))
                self.assertEqual([], page.evaluate("window.__video.unmodelled()"))
                self.assertEqual([], errors)

                # its speed, clip and default speed set while it plays, and a second audio element that plays the
                # same clip:
                voice.evaluate("""audio => {
                    audio.playbackRate = 1.2;
                    audio.src = audio.src;
                    audio.defaultPlaybackRate = 1.2;
                    new Audio(audio.getAttribute('src')).play();
                }""")  # fmt: skip
                self.assertEqual(
                    sorted(changes),
                    sorted(page.evaluate("window.__video.unmodelled()")),
                )
                self.assertEqual(
                    [STAND_IN_ERROR + change for change in changes], errors
                )

                # the errors stop the film before its next step, with the time still at 40/60 s; with frames to take,
                # only the first one is taken:
                with self.assertRaisesRegex(
                    RuntimeError, "set playbackRate while playing"
                ):
                    # pylint: disable-next=protected-access
                    tool._play(page, frames_to, most + 1, errors)
                self.assertEqual(
                    40, round(page.evaluate("performance.now()") * tool.FPS / 1000)
                )
                if frames_to is not None:
                    self.assertEqual(1, len(frames_to.frames))

    def test_play_stops_right_after_the_step_in_which_the_page_logs_an_error(
        self,
    ) -> None:
        """``_play`` stops with a RuntimeError that names the page's error right after the step that logged it.

        The page logs the error at 3/60 s of a film that may take more than 3000 frames. If ``_play`` takes frames, it
        has taken frames 0 to 3, the frame of that step included.
        """
        for frames_to in (None, FrameSink()):
            with self.subTest(taking_frames=frames_to is not None):
                errors: list[str] = []
                page, most = self.open_row_or_column_page(errors)

                # a frame callback of the page that logs an error once the film's time has reached 3/60 s:
                page.evaluate("""() => {
                    const tick = (now) => (now >= 3000 / 60 ? console.error('boom') : requestAnimationFrame(tick));
                    requestAnimationFrame(tick);
                }""")  # fmt: skip

                # the film stops with the error after step 3:
                with self.assertRaisesRegex(
                    RuntimeError, r"^the page logged errors: \['boom'\]$"
                ):
                    # pylint: disable-next=protected-access
                    tool._play(page, frames_to, most + 1, errors)
                self.assertEqual(
                    3, round(page.evaluate("performance.now()") * tool.FPS / 1000)
                )
                if frames_to is not None:
                    self.assertEqual(4, len(frames_to.frames))

    def test_play_stops_right_after_the_step_in_which_a_frame_callback_throws(
        self,
    ) -> None:
        """An exception that a frame callback of the page throws stops ``_play`` with a RuntimeError that names it,
        right after the step in which it was thrown; the other callbacks of that frame still run.

        The callback throws at 3/60 s of a film that may take more than 3000 frames. If ``_play`` takes frames, it has
        taken frames 0 to 3, the frame of that step included.
        """
        for frames_to in (None, FrameSink()):
            with self.subTest(taking_frames=frames_to is not None):
                errors: list[str] = []
                page, most = self.open_row_or_column_page(errors)

                # two frame callbacks of the page, asked for in this order in each frame: the first throws once the
                # film's time has reached 3/60 s, the second counts the frames it has run in:
                page.evaluate("""() => {
                    window.counted = 0;
                    const throwing = (now) => {
                        if (now >= 3000 / 60) throw new Error('boom');
                        requestAnimationFrame(throwing);
                    };
                    const counting = () => { window.counted += 1; requestAnimationFrame(counting); };
                    requestAnimationFrame(throwing);
                    requestAnimationFrame(counting);
                }""")  # fmt: skip

                # the film stops with the exception after step 3:
                with self.assertRaisesRegex(
                    RuntimeError, r"^the page logged errors: \['boom'\]$"
                ):
                    # pylint: disable-next=protected-access
                    tool._play(page, frames_to, most + 1, errors)
                self.assertEqual(
                    3, round(page.evaluate("performance.now()") * tool.FPS / 1000)
                )
                if frames_to is not None:
                    self.assertEqual(4, len(frames_to.frames))

                # the second callback has run in each of the 3 steps, also in the one in which the first one threw:
                self.assertEqual(3, page.evaluate("window.counted"))

    def test_play_stops_when_the_page_loses_its_webgl_context(self) -> None:
        """A page whose WebGL context is lost logs the error of ``INIT_SCRIPT``, which stops ``_play`` within a step.

        The page's stage loses its context at 3/60 s, in a film that may take more than 3000 frames. The browser sends
        the event of the loss in a task of its own after that step, so ``_play`` stops after step 3 or step 4.
        """
        errors: list[str] = []
        page, most = self.open_row_or_column_page(errors)

        # a frame callback of the page that loses the context of its stage's canvas once the film's time has reached
        # 3/60 s:
        page.evaluate("""() => {
            const lose = () => document.querySelector('[data-testid=stage] canvas')
                .getContext('webgl2').getExtension('WEBGL_lose_context').loseContext();
            const tick = (now) => (now >= 3000 / 60 ? lose() : requestAnimationFrame(tick));
            requestAnimationFrame(tick);
        }""")  # fmt: skip

        # the film stops with that error, right after the step it came in:
        with self.assertRaisesRegex(
            RuntimeError,
            r"^the page logged errors: \['render_video: the WebGL context was lost'\]$",
        ):
            tool._play(page, None, most + 1, errors)  # pylint: disable=protected-access
        self.assertIn(
            round(page.evaluate("performance.now()") * tool.FPS / 1000), (3, 4)
        )

    def test_play_stops_right_after_the_step_in_which_the_film_pauses(self) -> None:
        """``_play`` returns right after the step in which the film stops playing, and ``check_recording`` rejects it.

        The page pauses at 3/60 s, as if its Play button were clicked, so ``_play`` returns frame 3 and Play's state
        'paused', long before the end of the film. ``check_recording`` rejects that also for a recording of only a part
        of the film. If ``_play`` takes frames, it has taken frames 0 to 3.
        """
        for frames_to in (None, FrameSink()):
            with self.subTest(taking_frames=frames_to is not None):
                errors: list[str] = []
                page, most = self.open_row_or_column_page(errors)

                # a frame callback of the page that clicks Play, which pauses the film, once its time has reached
                # 3/60 s:
                page.evaluate("""() => {
                    const tick = (now) => (now >= 3000 / 60
                        ? document.querySelector('[data-testid=play]').click()
                        : requestAnimationFrame(tick));
                    requestAnimationFrame(tick);
                }""")  # fmt: skip

                # the film stops after step 3, paused:
                # pylint: disable-next=protected-access
                frame, reached = tool._play(page, frames_to, most + 1, errors)
                self.assertEqual((3, "paused"), (frame, reached))
                if frames_to is not None:
                    self.assertEqual(4, len(frames_to.frames))

                # the recording is rejected, also as a part of the film:
                unmodelled: list[str] = page.evaluate("window.__video.unmodelled()")
                with self.assertRaisesRegex(
                    RuntimeError, r"^the film stopped before its end: Play is 'paused'$"
                ):
                    tool.check_recording(errors, unmodelled, reached, None)

    def test_open_page_accepts_webgl_only_with_a_gpu(self) -> None:
        """Unless it is allowed, ``open_page`` stops when WebGL draws without a GPU, and opens the page when it draws
        with one.

        It tells them apart by the name of WebGL's renderer. This headless Chromium's own renderer, SwiftShader under
        ANGLE, llvmpipe, Microsoft's Basic Render Driver and Apple's Software Renderer emulate a GPU in software; ANGLE
        on Apple's Metal draws with a GPU. The test makes WebGL give each of these names but the browser's own.
        """
        path: Path = self.stub_page("play.disabled = false;")

        def page_naming(renderer: str | None, errors: list[str]) -> Page:
            """@return: a new page whose WebGL names the renderer, or its own one if it is None"""
            page: Page = self.new_page(errors, path)
            if renderer is not None:
                page.context.add_init_script(
                    RENAMED_RENDERER.replace("RENDERER_NAME", json.dumps(renderer))
                )
            return page

        # this browser's own renderer and the four in software are refused; the reason names the renderer:
        software: list[str] = [
            "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)",
            "llvmpipe (LLVM 15.0.7, 256 bits)",
            "Microsoft Basic Render Driver",
            "ANGLE (Apple, Apple Software Renderer, OpenGL 4.1)",
        ]
        refused: list[tuple[str | None, str]] = [
            (None, r"^WebGL draws without a GPU: ")
        ] + [
            (name, rf"^WebGL draws without a GPU: {re.escape(name)}$")
            for name in software
        ]
        for renderer, reason in refused:
            with self.subTest(renderer=renderer):
                errors: list[str] = []
                with self.assertRaisesRegex(RuntimeError, reason):
                    tool.open_page(page_naming(renderer, errors), path, errors)

        # with ANGLE on Apple's Metal, the page is opened and started; its film of 1 s may take 3 s with the margin:
        errors = []
        gpu: str = (
            "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Max, Unspecified Version)"
        )
        self.assertEqual(
            round((1 + tool.FILM_MARGIN) * tool.FPS),
            tool.open_page(page_naming(gpu, errors), path, errors),
        )
        self.assertEqual([], errors)

    def test_open_page_stops_with_the_reason_why_a_page_cannot_be_filmed(
        self,
    ) -> None:
        """``open_page`` stops with a RuntimeError that names why a page cannot be filmed.

        These are a browser without WebGL 2, a page that does not start playing or does not switch its sound on (its
        video would have no voice), a page that logs an error while it opens, and a clock that shows no length. The
        same page without these flaws opens (see ``test_open_page_accepts_webgl_only_with_a_gpu``).
        """
        # an init script that takes WebGL 2 from the browser:
        no_webgl2: str = """(() => {
            const getContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
                return type === 'webgl2' ? null : getContext.call(this, type, ...rest);
            };
        })();"""
        # each flaw: the page's script (which enables Play), an init script, and the reason open_page gives:
        flaws: list[tuple[str, str, str | None, str]] = [
            (
                "no WebGL 2",
                "play.disabled = false;",
                no_webgl2,
                r"^the browser has no WebGL 2$",
            ),
            (
                "not started",
                "play.disabled = false;"
                " play.addEventListener('click', () => { play.dataset.state = 'paused'; });",
                None,
                r"^the page did not start playing with sound on$",
            ),
            (
                "sound off",
                "play.disabled = false;"
                " sound.addEventListener('click', () => { sound.setAttribute('aria-pressed', 'false'); });",
                None,
                r"^the page did not start playing with sound on$",
            ),
            (
                "error",
                "play.disabled = false; console.error('boom');",
                None,
                r"^the page logged errors: \['boom'\]$",
            ),
            (
                "no length",
                "play.disabled = false;"
                " document.querySelector('[data-testid=clock]').textContent = '0:00';",
                None,
                r"^the page's clock shows no length: '0:00'$",
            ),
        ]
        for flaw, script, init_script, reason in flaws:
            with self.subTest(flaw=flaw):
                # the stub page with the flaw, in a browser that WebGL may draw in without a GPU:
                path: Path = self.stub_page(script)
                errors: list[str] = []
                page: Page = self.new_page(errors, path)
                if init_script is not None:
                    page.context.add_init_script(init_script)
                with self.assertRaisesRegex(RuntimeError, reason):
                    tool.open_page(page, path, errors, allow_software_gpu=True)

    def test_allow_only_refuses_requests_outside_the_page_folder(self) -> None:
        """A page loads a script from its own folder; a script in the folder above, one in a folder beside it whose name
        begins with the page folder's name, and a picture on the web are refused.

        Each refused request is added to the page's errors, which stops a render.
        """
        # a page in the folder page, with a script next to it, one in the folder above and one in the folder
        # page-other beside it:
        root = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(root.cleanup)
        outside: Path = Path(root.name).resolve() / "outside.js"
        folder: Path = outside.with_name("page")
        beside: Path = outside.with_name("page-other") / "beside.js"
        folder.mkdir()
        beside.parent.mkdir()
        outside.write_text("window.outside = true;", encoding="utf-8")
        beside.write_text("window.beside = true;", encoding="utf-8")
        (folder / "inside.js").write_text("window.inside = true;", encoding="utf-8")
        (folder / "page.html").write_text(
            '<!doctype html><script src="inside.js"></script><script src="../outside.js"></script>'
            '<script src="../page-other/beside.js"></script><img src="https://example.com/picture.png">',
            encoding="utf-8",
        )

        # the page loads, and only the script in its own folder has run:
        errors: list[str] = []
        page: Page = self.new_page(errors, folder / "page.html")
        page.goto((folder / "page.html").as_uri())
        self.assertEqual(
            [True, False, False],
            page.evaluate(
                "[window.inside === true, window.outside === true, window.beside === true]"
            ),
        )

        # the three other requests were refused and logged:
        self.assertEqual(
            sorted(
                [
                    f"refused a request: {outside.as_uri()}",
                    f"refused a request: {beside.as_uri()}",
                    "refused a request: https://example.com/picture.png",
                ]
            ),
            sorted(error for error in errors if error.startswith("refused")),
        )

    def test_allow_only_refuses_a_websocket(self) -> None:
        """A WebSocket that the page opens is refused and logged as an error, and the page goes on."""
        errors: list[str] = []
        page: Page = self.new_page(errors)

        # the page opens a WebSocket and waits until it is open or closed:
        page.evaluate("""() => new Promise((resolve) => {
            const socket = new WebSocket('ws://127.0.0.1:9/');
            socket.onopen = socket.onclose = () => resolve();
        })""")  # fmt: skip
        self.assertEqual(
            ["refused a WebSocket: ws://127.0.0.1:9/"],
            [error for error in errors if error.startswith("refused")],
        )

    def test_prepare_page_logs_an_uncaught_exception_of_the_page(self) -> None:
        """An exception that the page does not catch is added to its errors, as a console error is, which stops a
        render."""
        errors: list[str] = []
        page: Page = self.new_page(errors)

        # a timer of the page throws; the test waits until the exception has reached Playwright:
        with page.expect_event("pageerror"):
            page.evaluate("setTimeout(() => { throw new Error('boom'); })")
        self.assertEqual(["boom"], errors)

    def test_open_page_runs_the_warm_up_that_begins_once_play_is_enabled(
        self,
    ) -> None:
        """``open_page`` waits until Play is enabled, and then runs all of the page's warm-up while the time stands
        still.

        The page here enables Play 200 ms after it has loaded and in the same step asks for the first of 30 warm-up
        steps, each in an animation frame of its own; all 30 have run when ``open_page`` returns, at time 0.
        """
        # a page with only the controls that open_page uses, and the warm-up:
        path: Path = self.stub_page("""
            window.warmUps = 0;
            const warmUp = () => { window.warmUps += 1; if (window.warmUps < 30) requestAnimationFrame(warmUp); };
            setTimeout(() => { play.disabled = false; requestAnimationFrame(warmUp); }, 200);
        """)  # fmt: skip

        # once the page is open, it has run its whole warm-up, and the time is still 0:
        errors: list[str] = []
        page: Page = self.new_page(errors, path)
        tool.open_page(page, path, errors, allow_software_gpu=True)
        self.assertEqual([30, 0], page.evaluate("[window.warmUps, performance.now()]"))
        self.assertEqual([], errors)

    def test_open_page_allows_the_film_its_length_and_a_margin(self) -> None:
        """``open_page`` returns the most steps the film may take: the 52 s its clock shows plus ``FILM_MARGIN``."""
        errors: list[str] = []
        _, most = self.open_row_or_column_page(errors)
        self.assertEqual(
            round(
                (page_tests.RowOrColumnPageTest.LENGTH + tool.FILM_MARGIN) * tool.FPS
            ),
            most,
        )
        self.assertEqual([], errors)

    def test_the_video_shows_the_subtitles_but_not_the_controls(self) -> None:
        """At 1 s, while the voice speaks, the subtitles show, and the transport bar and the sound hint do not.

        The stage draws with WebGL 2. The subtitles hold text; its wording is the page's, which the page tests check.
        """
        errors: list[str] = []
        page, _ = self.open_row_or_column_page(errors)

        # one second on, the voice says the first caption, so the page itself would hide its text (data-voiced):
        for _ in range(tool.FPS):
            page.evaluate("window.__video.step()")
        stage = page.get_by_test_id("stage")
        self.assertEqual("webgl2", stage.get_attribute("data-renderer"))
        self.assertEqual("playing", stage.get_attribute("data-voice"))
        self.assertIsNotNone(
            page.get_by_test_id("narration").get_attribute("data-voiced")
        )

        # the video's CSS shows the subtitles, which hold text, and hides the controls:
        visibility: str = "element => getComputedStyle(element).visibility"
        self.assertEqual(
            {"nar-text": "visible", "transport": "hidden", "sound-hint": "hidden"},
            {
                test_id: page.get_by_test_id(test_id).evaluate(visibility)
                for test_id in ("nar-text", "transport", "sound-hint")
            },
        )
        self.assertNotEqual(
            "", (page.get_by_test_id("nar-text").text_content() or "").strip()
        )
        self.assertEqual([], errors)


class _RenderedTestCase(unittest.TestCase):
    """Renders a page into a video once for all tests of a class; holds no tests of its own.

    The video and its side files lie in a folder that is removed after the last test of the class.
    """

    PAGE: Path
    SECONDS: float
    HOLD: float = 0
    out: Path

    @classmethod
    def setUpClass(cls) -> None:
        """Renders the first SECONDS of PAGE, holding the last frame for HOLD seconds."""
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        cls.addClassCleanup(folder.cleanup)
        cls.out = Path(folder.name) / (cls.PAGE.stem + ".mp4")
        tool.render(
            cls.PAGE,
            cls.out,
            seconds=cls.SECONDS,
            hold=cls.HOLD,
            browser=BROWSER_OPTIONS,
        )


@unittest.skipUnless(page_tests.PLAYWRIGHT_AVAILABLE, page_tests.SKIP_REASON)
@unittest.skipUnless(FFMPEG_AVAILABLE, FFMPEG_SKIP_REASON)
class RenderTest(_RenderedTestCase):
    """Checks a video that ``render`` makes of the first 2 s of the row-or-column page; its voice starts at 0.5 s."""

    PAGE: Path = page_tests.ROW_OR_COLUMN_PAGE
    SECONDS: float = 2.0
    # the number of frames of the video:
    FRAMES: int = 120
    # each clip begins with 0.4 s of silence (decision 034), so that a browser that starts its sound late does not
    # swallow the first syllable; the voice's first sound rises in its last tenth. So the video is silent until 0.3 s
    # after the clip starts and loud from 0.5 s after it on:
    SILENT_UNTIL: float = 0.3
    LOUD_FROM: float = 0.5

    def voice(self) -> list[Segment]:
        """@return: the voice segments of the side file ``row-or-column.voice.json``"""
        voice: Path = self.out.with_name("row-or-column.voice.json")
        return [
            tool.Segment(**segment)
            for segment in json.loads(voice.read_text(encoding="utf-8"))
        ]

    def test_picture_and_sound_have_the_format_for_youtube(self) -> None:
        """The picture is H.264 in yuv420p with BT.709 tags at 60 fps, the sound AAC 48 kHz stereo; both last 2 s."""
        info: dict[str, Any] = probe(self.out)
        streams: dict[str, dict[str, Any]] = {
            stream["codec_type"]: stream for stream in info["streams"]
        }
        self.assertEqual({"video", "audio"}, set(streams))

        # the picture: H.264 with the colours YouTube expects, viewport × scale pixels, one frame per 1/60 s:
        expected_video: dict[str, Any] = {
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "color_space": "bt709",
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "color_range": "tv",
            "width": 320,
            "height": 180,
            "r_frame_rate": "60/1",
            "avg_frame_rate": "60/1",
            "nb_read_frames": str(self.FRAMES),
        }
        self.assertEqual(
            expected_video,
            {key: streams["video"].get(key) for key in expected_video},
        )

        # the sound: AAC at 48 kHz in stereo:
        expected_audio: dict[str, Any] = {
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
        }
        self.assertEqual(
            expected_audio,
            {key: streams["audio"].get(key) for key in expected_audio},
        )

        # the video lasts 2 s, to within a frame:
        self.assertAlmostEqual(
            self.SECONDS, float(info["format"]["duration"]), delta=ONE_FRAME
        )

    def test_the_picture_changes_as_the_film_runs(self) -> None:
        """The last frame differs clearly from frame 0: by then the query is typed and the first subtitle shows."""
        frames: list[bytes] = decode_frames(self.out)
        self.assertEqual(self.FRAMES, len(frames))

        # at least 1 % of the pixels have changed (about 6 % do):
        self.assertGreater(
            pixels_apart(frames[0], frames[-1]), PICTURE[0] * PICTURE[1] // 100
        )

    def test_the_voice_sounds_after_the_silence_of_its_clip(self) -> None:
        """The sound is silent until the first clip has started and its silence has passed, and loud from then on."""
        start: float = self.voice()[0].start
        self.assertLess(mean_volume(self.out, 0, start + self.SILENT_UNTIL), -80)
        self.assertGreater(
            mean_volume(self.out, start + self.LOUD_FROM, self.SECONDS), -50
        )

    def test_the_side_files_hold_the_picture_alone_and_the_voice(self) -> None:
        """Next to the video lie its picture alone and its voice, from which ``--mux-only`` mixes the video again.

        No other file is left, in particular none of the partial files that the render writes first.
        """
        # the folder holds the video and its two side files only:
        self.assertEqual(
            [
                "row-or-column.mp4",
                "row-or-column.video.mp4",
                "row-or-column.voice.json",
            ],
            sorted(path.name for path in self.out.parent.iterdir()),
        )

        # the picture alone has all frames and no sound:
        picture: Path = self.out.with_name("row-or-column.video.mp4")
        self.assertEqual(
            [("video", str(self.FRAMES))],
            [
                (stream["codec_type"], stream.get("nb_read_frames"))
                for stream in probe(picture)["streams"]
            ],
        )

        # the voice is the clip of the first caption, at its speed from its beginning, from the caption's time (or up
        # to two frames later) to the end of the video:
        segments: list[Segment] = self.voice()
        self.assertEqual(1, len(segments))
        self.assertGreaterEqual(segments[0].start - SEGMENT_TIMES[0], 0)
        self.assertLessEqual(segments[0].start - SEGMENT_TIMES[0], TWO_FRAMES)
        self.assertEqual(
            (1, 0, self.SECONDS),
            (segments[0].rate, segments[0].offset, segments[0].end),
        )

    def test_mux_only_makes_the_video_again_from_its_side_files(self) -> None:
        """With ``--mux-only``, ``main`` makes the video again from its two side files alone, with picture and voice."""
        # a folder with only the side files, under the video's name:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        out: Path = Path(folder.name) / self.out.name
        for side_file in tool.side_files(self.out):
            shutil.copy(side_file, out.with_name(side_file.name))

        tool.main(["--mux-only", str(self.PAGE), str(out)])

        # the video is back: the picture with all its frames, and the voice, which speaks where it did before:
        streams: list[dict[str, Any]] = probe(out)["streams"]
        self.assertEqual(
            [("video", "h264"), ("audio", "aac")],
            [(stream["codec_type"], stream["codec_name"]) for stream in streams],
        )
        self.assertEqual(str(self.FRAMES), streams[0]["nb_read_frames"])
        start: float = self.voice()[0].start
        self.assertGreater(mean_volume(out, start + self.LOUD_FROM, self.SECONDS), -50)


@unittest.skipUnless(page_tests.PLAYWRIGHT_AVAILABLE, page_tests.SKIP_REASON)
@unittest.skipUnless(FFMPEG_AVAILABLE, FFMPEG_SKIP_REASON)
class HoldTest(_RenderedTestCase):
    """Checks a video of the first 0.25 s of the row-or-column page, with its last frame held for 0.5 s.

    The page's voice starts only at 0.5 s, so no clip sounds in the video.
    """

    PAGE: Path = page_tests.ROW_OR_COLUMN_PAGE
    SECONDS: float = 0.25
    HOLD: float = 0.5

    def test_the_last_frame_is_held(self) -> None:
        """The video lasts 0.75 s, and its last 30 frames, those of the hold, show its last recorded frame.

        That frame differs from frame 0, as the film has moved on, so a hold of an earlier frame would show.
        """
        self.assertAlmostEqual(
            self.SECONDS + self.HOLD,
            float(probe(self.out)["format"]["duration"]),
            delta=ONE_FRAME,
        )

        # 15 recorded frames, then 30 held ones, each equal to the last recorded one but for H.264's noise:
        frames: list[bytes] = decode_frames(self.out)
        self.assertEqual(45, len(frames))
        last_recorded: bytes = frames[-31]
        self.assertEqual(
            [0] * 30, [pixels_apart(last_recorded, frame) for frame in frames[-30:]]
        )

        # the last recorded frame differs from frame 0 in at least 0.1 % of the pixels (about 1100 of 57600 do):
        self.assertGreater(
            pixels_apart(frames[0], last_recorded), PICTURE[0] * PICTURE[1] // 1000
        )

    def test_a_film_without_voice_gets_a_silent_sound_track(self) -> None:
        """A video in which no clip sounds still has a sound track: silent, and as long as the picture."""
        # before the first caption, no clip sounds: the voice side file has no segment:
        voice: Path = self.out.with_name("row-or-column.voice.json")
        self.assertEqual([], json.loads(voice.read_text(encoding="utf-8")))

        # the sound track is AAC as for a film with voice, lasts as long as the picture, and is silent:
        audio: list[dict[str, Any]] = [
            stream
            for stream in probe(self.out)["streams"]
            if stream["codec_type"] == "audio"
        ]
        self.assertEqual(["aac"], [stream["codec_name"] for stream in audio])
        self.assertAlmostEqual(
            self.SECONDS + self.HOLD, float(audio[0]["duration"]), delta=ONE_FRAME
        )
        self.assertLess(mean_volume(self.out, 0, self.SECONDS + self.HOLD), -80)


@unittest.skipUnless(page_tests.PLAYWRIGHT_AVAILABLE, page_tests.SKIP_REASON)
@unittest.skipUnless(FFMPEG_AVAILABLE, FFMPEG_SKIP_REASON)
class ClockScanPictureTest(_RenderedTestCase):
    """Checks the picture of a video of the first second of the clock-scan page.

    On a software GPU, as here, the page draws its 3D scene (a clock on wooden boards) only after a warm-up of many
    animation frames; ``open_page`` lets it run before frame 0, while the film's time stands still.
    """

    PAGE: Path = page_tests.CLOCK_SCAN_PAGE
    SECONDS: float = 1.0

    def test_the_3d_scene_shows_from_the_first_frame_on(self) -> None:
        """Frame 0 and the last frame show the 3D scene: their middle has many colours, not the page's plain one."""
        frames: list[bytes] = decode_frames(self.out)

        # the scene has thousands of colours in the middle of the picture (about 3800); the page's background, which
        # shows there without it, has one:
        for index in (0, len(frames) - 1):
            with self.subTest(frame=index):
                self.assertGreater(colours_in_the_middle(frames[index]), 1000)


if __name__ == "__main__":
    unittest.main()
