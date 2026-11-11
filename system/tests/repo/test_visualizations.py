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

"""Smoke tests of the pages in ``visualizations/`` in a headless browser (Chromium, driven by Playwright).

The tests open each page from its file, with no web server, and use its controls the way a reader does. They fail if
the page's script throws an error or logs one to the console, if a control stops working, or if the page requests
anything but local files, also through a WebSocket (a page must work offline). They find elements only by their
``data-testid`` and read the state of a page mainly from ``data-*`` attributes that its script sets (see
CONTRIBUTING.md, section Visualizations).

Playwright is only in the dependency group ``browser-tests``, which ``uv sync`` does not install; without it, the
tests that open a browser are skipped. The CI job ``visualization_test`` installs the group and Chromium and runs
this module in CI_JOBS jobs, each on its share of the pages (see pages_of_job); a run without the variable
VISUALIZATION_JOB tests every page.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import tempfile
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict
from unittest import mock

# the trees and queries of the B-tree page, from a module that uses only the standard library (the CI job installs
# only Playwright):
from system.tests.repo.b_tree_page_trees import (
    B_TREE_PAGE,
    BETWEEN_LEAVES_RANGE,
    EXPECTED_BETWEEN_LEAVES,
    EXPECTED_DIGESTS,
    EXPECTED_POINT_PATH,
    EXPECTED_RANGE_HITS,
    EXPECTED_RANGE_LEAVES,
    Tree,
    digest_mismatches,
    digests,
    height,
    keys_of,
    read_queries,
    read_start_and_puts,
)

# the tests that open a browser run only where Playwright is installed (see the module docstring):
PLAYWRIGHT_AVAILABLE: bool = importlib.util.find_spec("playwright") is not None

# without the dependency group browser-tests, pylint cannot find playwright:
# pylint: disable=import-error
if PLAYWRIGHT_AVAILABLE:
    from playwright.sync_api import Error, expect, sync_playwright
else:
    # the tests that open a browser are skipped, so these are never used:
    Error = expect = sync_playwright = None  # pylint: disable=invalid-name
if TYPE_CHECKING:
    from playwright.sync_api import (
        Browser,
        ConsoleMessage,
        FloatRect,
        Page,
        Playwright,
        Route,
    )
# pylint: enable=import-error

SKIP_REASON: str = (
    "needs Playwright and Chromium: uv run --group browser-tests python -m playwright install --only-shell chromium"
)

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
PAGES_DIR: Path = REPO_ROOT / "visualizations"
ELASTICITY_PAGE: Path = PAGES_DIR / "elasticity-resources-follow-demand.html"
VALIDATION_PAGE: Path = PAGES_DIR / "validation-interval-to-point.html"
# a page with a synthetic voice, which the sound button switches on (decision 034):
CLOCK_SCAN_PAGE: Path = PAGES_DIR / "clock-scan.html"
# a page whose voice says some captions in two segments, each with a clip of its own (decision 035):
ROW_OR_COLUMN_PAGE: Path = PAGES_DIR / "row-or-column.html"
# the House DBMS page, which speaks its narration with the same voice (decision 036):
HOUSE_DBMS_PAGE: Path = PAGES_DIR / "call-through-dbms.html"
# the page on Yannakakis' semi-join reduction, which counts the semi-joins done and the tuples left (decision 032) and
# speaks its narration with the same voice (decision 038):
YANNAKAKIS_PAGE: Path = PAGES_DIR / "yannakakis.html"
# the pages that speak their narration (the B-tree page, B_TREE_PAGE, with the same voice, decision 040); each must
# keep its sound button:
PAGES_WITH_SOUND: frozenset[Path] = frozenset(
    {CLOCK_SCAN_PAGE, ROW_OR_COLUMN_PAGE, HOUSE_DBMS_PAGE, YANNAKAKIS_PAGE, B_TREE_PAGE}
)
# the pages with sound whose film has parts, with a button (chapter-1, ...) that jumps to the start of each:
PAGES_WITH_PARTS: frozenset[Path] = frozenset(
    {CLOCK_SCAN_PAGE, HOUSE_DBMS_PAGE, YANNAKAKIS_PAGE, B_TREE_PAGE}
)

# Next is clicked at most this often on the way from the start of a page to its end:
MAX_NEXT_CLICKS: int = 300

# a capital letter on its own, as a room named by a letter ("room R", "Q's right half"); not "A", the article, nor a
# letter in a compound such as "B-tree":
LETTER_NAME: re.Pattern[str] = re.compile(r"(?<![\w-])(?!A\b)[A-Z](?![\w-])")

# a wait for the film to reach a time (e.g. the first caption, after about 0.75 s on the clock-scan page) ends after
# this many milliseconds, not after the 5 s of a control: on a slow machine (software rendering) a frame may advance
# the film by only 0.1 s:
FILM_TIMEOUT: int = 15_000

# the variable in which a CI job names its share of the pages, as "i/n": job i of n (see pages_of_job):
JOB_VARIABLE: str = "VISUALIZATION_JOB"
# the `parallel` of the CI job visualization_test in .gitlab-ci.yml, which system/tests/repo/test_ci_config.py checks
# against it:
CI_JOBS: int = 3


def job_of_this_run() -> tuple[int, int]:
    """Returns which of how many jobs this run is, from the variable VISUALIZATION_JOB; without it, the only one.

    @return: (i, n) for job i of n, with 1 <= i <= n; (1, 1) if the variable is not set
    @raise ValueError: if the variable is set, but not to "i/n" with 1 <= i <= n
    """
    value: str | None = os.environ.get(JOB_VARIABLE)
    if value is None:
        return 1, 1
    match: re.Match[str] | None = re.fullmatch(r"([1-9][0-9]*)/([1-9][0-9]*)", value)
    if match is None or int(match[1]) > int(match[2]):
        raise ValueError(f"{JOB_VARIABLE} must be i/n with 1 <= i <= n, not {value!r}")
    return int(match[1]), int(match[2])


def find_pages() -> list[Path]:
    """Returns the HTML files in visualizations/ and its subfolders, sorted."""
    return sorted(PAGES_DIR.rglob("*.html"))


def has_sound(path: Path) -> bool:
    """Returns whether the page at path has a sound button, which is written in its HTML, not made by its script."""
    return 'data-testid="sound"' in path.read_text(encoding="utf-8")


def pages_of_job(
    pages: list[Path],
    index: int,
    total: int,
    sound: Callable[[Path], bool] = has_sound,
) -> list[Path]:
    """Returns the pages that job index of total tests; each page is tested in exactly one job.

    The pages with a sound button, whose tests take longest, come first, then the others, each group sorted by path;
    page number k of this order (from 0) goes to job k mod total + 1. So the pages with sound are spread over the jobs
    before the others.

    @param pages: all pages
    @param index: the job, from 1 to total
    @param total: the number of jobs
    @param sound: whether a page has a sound button
    @return: the pages of the job, in the order above
    @raise ValueError: if the job is not one of 1 to total, or if there are more jobs than pages, so that a job would
        test no page
    """
    if not 1 <= index <= total:
        raise ValueError(f"job {index} of {total}: a job is one of 1 to {total}")
    if total > len(pages):
        raise ValueError(
            f"{total} jobs for {len(pages)} pages: a job would test no page"
        )
    order: list[Path] = sorted(pages, key=lambda path: (not sound(path), path))
    return order[index - 1 :: total]


def sections_that_were_there(before: list[int], after: list[int]) -> list[int]:
    """Returns the places of a tree's sections (in key order) without those of new sections, i.e. without the places
    that no section held in the tree before.

    @param before: the places of the sections of the tree before an insert, in key order
    @param after: the places of the sections of the tree after it, in key order
    @return: after without the places that are not in before; equal to before if no section moved
    """
    return [place for place in after if place in before]


@dataclass
class OpenedPage:
    """A page opened in a browser context of its own, with everything that went wrong in it so far."""

    page: Page
    # uncaught exceptions and messages the page logged as console errors:
    errors: list[str] = field(default_factory=list)
    # the URLs of requests and WebSockets to anything but a local file, which were blocked:
    outside_requests: list[str] = field(default_factory=list)


class VoiceEntry(TypedDict):
    """What the voice did at one moment, and its state then, as recorded by ``record_voice_events`` (see there)."""

    at: float
    event: str
    voice: float
    src: bool
    clip: int | None
    length: float
    paused: bool
    seeking: bool
    ended: bool
    ready: int
    slider: int
    stage: str | None
    warmed: str | None
    play: str | None
    blocked: bool


class _PageTestCase(unittest.TestCase):
    """Starts one headless Chromium per test class and opens pages in it; holds no tests of its own."""

    playwright: Playwright
    browser: Browser
    # the page that all tests of the class open, if they open only one; the class runs only in that page's job:
    PAGE: Path | None = None

    @classmethod
    def setUpClass(cls) -> None:
        """Starts Playwright and Chromium; both are stopped after the last test of the class, also if one fails.

        A class with a PAGE that another job tests is skipped, before Chromium starts. A PAGE that is not among the
        pages (renamed, misspelled) is an error, not a skip, so that no page drops out of the tests unnoticed.
        """
        if cls.PAGE is not None:
            pages: list[Path] = find_pages()
            if cls.PAGE not in pages:
                raise AssertionError(f"{cls.PAGE} is not among the pages")
            index, total = job_of_this_run()
            if cls.PAGE not in pages_of_job(pages, index, total):
                job: int = next(
                    other
                    for other in range(1, total + 1)
                    if cls.PAGE in pages_of_job(pages, other, total)
                )
                raise unittest.SkipTest(
                    f"{cls.PAGE.name} is tested in job {job} of {total}"
                )
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def open_page(self, path: Path, reduced_motion: bool = True) -> OpenedPage:
        """Opens the page at path in a new browser context, which is closed after the test.

        Errors and outside requests are recorded from before the page loads. A class with a PAGE opens only that page,
        as it runs only in that page's job.

        @param path: the HTML file of the page
        @param reduced_motion: whether the browser asks for reduced motion; the pages then do not start playing on
            their own, so that every test starts from a paused page at time 0
        @return: the opened page with the lists of errors and outside requests
        @raise AssertionError: if the class has a PAGE and path is another page; raised before the browser is used
        """
        if self.PAGE is not None and path != self.PAGE:
            raise AssertionError(
                f"{type(self).__name__} opens {path}, but its PAGE is {self.PAGE}"
            )
        context = self.browser.new_context(
            reduced_motion="reduce" if reduced_motion else "no-preference"
        )
        self.addCleanup(context.close)
        # every control reacts at once, so a control that is missing fails after 5 s, not after Playwright's 30 s:
        context.set_default_timeout(5_000)
        opened: OpenedPage = OpenedPage(context.new_page())

        def block(route: Route) -> None:
            """Records and blocks a request to anything but a local file."""
            opened.outside_requests.append(route.request.url)
            route.abort()

        def record_error(error: Error) -> None:
            """Records an uncaught exception of the page."""
            opened.errors.append(f"uncaught: {error}")

        def record_console(message: ConsoleMessage) -> None:
            """Records a message the page logged as a console error."""
            if message.type == "error":
                opened.errors.append(f"console: {message.text}")

        context.route(lambda url: not url.startswith("file:"), block)
        # a WebSocket is not a request that route sees; without a call to connect it to its server, Playwright
        # answers it inside the browser, so the server is never reached (closing it here would make Playwright hang).
        # This covers the WebSockets of the page and its frames, not those of a Web Worker (no page uses one):
        context.route_web_socket(
            lambda url: True, lambda ws: opened.outside_requests.append(ws.url)
        )
        opened.page.on("pageerror", record_error)
        opened.page.on("console", record_console)
        opened.page.goto(path.as_uri())
        return opened

    def assert_no_errors(self, opened: OpenedPage) -> None:
        """Asserts that the page neither had an error nor requested anything but a local file."""
        self.assertEqual([], opened.errors, "the page had errors")
        self.assertEqual(
            [], opened.outside_requests, "the page requested more than local files"
        )

    def step_to_end(self, page: Page) -> list[str]:
        """Clicks Next until the page has ended, and asserts that every click moves the slider on, up to its end.

        @param page: a paused page
        @return: the type of the narrated stop after each click (``data-stop-type`` of the narration)
        """
        play = page.get_by_test_id("play")
        scrub = page.get_by_test_id("scrub")
        narration = page.get_by_test_id("narration")
        position: int = int(scrub.input_value())
        stop_types: list[str] = []
        clicks: int = 0
        while play.get_attribute("data-state") != "ended":
            self.assertLess(clicks, MAX_NEXT_CLICKS, "Next did not reach the end")
            page.get_by_test_id("next").click()
            clicks += 1
            # Next moves the slider on:
            new_position: int = int(scrub.input_value())
            self.assertGreater(
                new_position, position, f"Next did not move on from {position}"
            )
            position = new_position
            stop_types.append(narration.get_attribute("data-stop-type") or "")
        self.assertEqual(1000, position)
        return stop_types

    def all_pages(self) -> list[Path]:
        """Returns the HTML files in visualizations/ and its subfolders, and asserts that the two known ones are there."""
        pages: list[Path] = find_pages()
        self.assertLessEqual({ELASTICITY_PAGE, VALIDATION_PAGE}, set(pages))
        return pages

    def pages(self) -> list[Path]:
        """Returns the pages that this run tests: all of them, or in a CI job its share (see pages_of_job)."""
        return pages_of_job(self.all_pages(), *job_of_this_run())


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class EveryPageTest(_PageTestCase):
    """Checks what every page in visualizations/ has, so that a new page is covered without tests of its own."""

    def test_steps_from_start_to_end_without_errors(self) -> None:
        """Each page loads at its start and leads with Next, step by step, to its end without errors."""
        for path in self.pages():
            with self.subTest(page=path.name):
                opened: OpenedPage = self.open_page(path)
                page: Page = opened.page
                narration = page.get_by_test_id("narration")

                # the page loaded without errors (e.g. a syntax error in its script):
                self.assert_no_errors(opened)

                # the script has run: the narration shows the start; Play has not been pressed:
                expect(narration).to_have_attribute("data-stop-type", "start")
                expect(page.get_by_test_id("play")).to_have_attribute(
                    "data-state", "paused"
                )

                # Next leads to the end, with at least one stop on the way:
                stop_types: list[str] = self.step_to_end(page)
                self.assertGreater(len(stop_types), 1, "Next jumped to the end")
                expect(narration).to_have_attribute("data-stop-type", "end")
                self.assert_no_errors(opened)
                # close the page before the next one opens, not only at the end of the test:
                opened.page.context.close()

    def test_play_and_pause(self) -> None:
        """On each page, Play starts the animation, which then moves on, and a second click pauses it."""
        for path in self.pages():
            with self.subTest(page=path.name):
                opened: OpenedPage = self.open_page(path)
                play = opened.page.get_by_test_id("play")

                # Play starts the animation, and the slider follows it:
                play.click()
                expect(play).to_have_attribute("data-state", "playing")
                expect(opened.page.get_by_test_id("scrub")).not_to_have_value("0")

                # a second click pauses it:
                play.click()
                expect(play).to_have_attribute("data-state", "paused")
                self.assert_no_errors(opened)
                # close the page before the next one opens, not only at the end of the test:
                opened.page.context.close()

    def test_starts_playing_on_its_own(self) -> None:
        """Without reduced motion, each page starts playing on its own and draws its frames without errors."""
        for path in self.pages():
            with self.subTest(page=path.name):
                opened: OpenedPage = self.open_page(path, reduced_motion=False)

                # the page starts playing after a short delay, and the slider follows the animation:
                expect(opened.page.get_by_test_id("play")).to_have_attribute(
                    "data-state", "playing"
                )
                expect(opened.page.get_by_test_id("scrub")).not_to_have_value("0")
                self.assert_no_errors(opened)
                # close the page, which would go on playing, before the next one opens:
                opened.page.context.close()


class _SoundPageTestCase(_PageTestCase):
    """Opens the pages with a sound button and reads the state of their voice; holds no tests of its own."""

    def check_each_page_with_sound(self, check: Callable[[Page], None]) -> None:
        """Runs a check on each page with a sound button that this run tests (see pages).

        First it asserts that the pages of PAGES_WITH_SOUND are among all pages with a sound button. The pages with a
        sound button are found in their HTML, so that the others are not opened in the browser. Each page is opened at
        its start, paused and with sound off; after the check, the page must have had no errors. A job without a page
        with sound skips the test.

        @param check: the steps of a test on one page
        """
        # the pages that speak have a sound button, so that a test cannot pass without them:
        self.assertLessEqual(
            PAGES_WITH_SOUND, {path for path in self.all_pages() if has_sound(path)}
        )
        # a page without a sound button has no voice:
        pages_with_sound: list[Path] = [
            path for path in self.pages() if has_sound(path)
        ]
        if not pages_with_sound:
            index, total = job_of_this_run()
            self.skipTest(f"job {index} of {total} tests no page with sound")

        for path in pages_with_sound:
            with self.subTest(page=path.name):
                opened: OpenedPage = self.open_page(path)
                check(opened.page)
                self.assert_no_errors(opened)
                # close the page, which would go on playing, before the next one opens:
                opened.page.context.close()

    @staticmethod
    def expect_sound(page: Page, on: bool, held_back: bool = False) -> None:
        """Expects the sound to be on or off, as the sound button, its icon, the narration and the hint show it.

        The button shows a speaker with waves while the sound is on, and a crossed-out one while it is off. While the
        voice may speak (sound on, and not held back by the browser), it speaks the captions, so they are neither shown
        nor read out by a screen reader, and there is no hint. While it is silent, the captions show as subtitles,
        which a screen reader reads out, and a hint tells how to get the sound: with sound off, how to switch it on;
        while the browser holds the voice back, that a click or key press brings it, and the sound button pulses for
        that click.

        @param page: a page with a sound button
        @param on: whether the sound is expected to be on
        @param held_back: whether the browser is expected to hold the voice back (only with sound on)
        """
        sound = page.get_by_test_id("sound")
        narration = page.get_by_test_id("narration")
        hint = page.get_by_test_id("sound-hint")
        expect(sound).to_have_attribute("aria-pressed", "true" if on else "false")
        shown_icon, hidden_icon = (
            ("sound-icon-on", "sound-icon-off")
            if on
            else ("sound-icon-off", "sound-icon-on")
        )
        expect(page.get_by_test_id(shown_icon)).to_be_visible()
        expect(page.get_by_test_id(hidden_icon)).to_be_hidden()
        if held_back:
            expect(sound).to_have_attribute("data-blocked", "")
        else:
            expect(sound).not_to_have_attribute("data-blocked", "")
        if on and not held_back:
            expect(narration).to_have_attribute("aria-live", "off")
            expect(narration).to_have_attribute("data-voiced", "")
            expect(hint).to_be_hidden()
        else:
            expect(narration).to_have_attribute("aria-live", "polite")
            expect(narration).not_to_have_attribute("data-voiced", "")
            expect(hint).to_be_visible()
            expect(hint).to_have_text(
                "Click or press a key for sound" if on else "Switch on audio (M)"
            )

    def play_with_sound(self, page: Page) -> None:
        """Switches the sound on and plays the page from its start until the voice speaks the first caption.

        @param page: a page with a sound button, paused at its start with sound off
        """
        page.get_by_test_id("sound").click()
        self.expect_sound(page, on=True)
        page.get_by_test_id("play").click()
        expect(page.get_by_test_id("stage")).to_have_attribute(
            "data-voice", "playing", timeout=FILM_TIMEOUT
        )

    @staticmethod
    def set_tab_hidden(page: Page, hidden: bool) -> None:
        """Makes the page believe that its tab was hidden (e.g. another tab chosen) or shown again.

        A headless browser shows all its pages, so the page's ``document.hidden`` is replaced, and the event
        ``visibilitychange`` is sent here, as the browser would send it.

        @param page: an open page
        @param hidden: whether the tab is hidden from now on
        """
        page.evaluate(
            """hidden => {
                Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
                Object.defineProperty(document, "visibilityState", {
                    configurable: true,
                    get: () => (hidden ? "hidden" : "visible"),
                });
                document.dispatchEvent(new Event("visibilitychange"));
            }""",
            hidden,
        )

    @staticmethod
    def hold_back_sound(page: Page, held_back: bool) -> None:
        """Makes the browser refuse the page's sound from now on, or allow it again.

        A browser allows a page sound only after the reader's click or key press, and a click or key press of a test
        counts as one; so the refusal is played here: while ``window.blockSound`` is true, ``play()`` of an audio or
        video element returns a promise rejected with a ``NotAllowedError``, as a browser's does.

        @param page: an open page
        @param held_back: whether the browser refuses the sound from now on
        """
        page.evaluate(
            """heldBack => {
                if (!("blockSound" in window)) {
                    const play = HTMLMediaElement.prototype.play;
                    HTMLMediaElement.prototype.play = function () {
                        if (window.blockSound) {
                            return Promise.reject(new DOMException("no sound before a click", "NotAllowedError"));
                        }
                        return play.call(this);
                    };
                }
                window.blockSound = heldBack;
            }""",
            held_back,
        )

    @staticmethod
    def record_voice_starts(page: Page) -> None:
        """Records every start of the voice from now on in ``window.voiceStarts``, also one the page undoes at once.

        Each start is recorded as the text of the caption shown at that moment.

        @param page: a page with a voice
        """
        page.evaluate(
            """([audio, text]) => {
                window.voiceStarts = [];
                audio.addEventListener("play", () => window.voiceStarts.push(text.textContent));
            }""",
            [
                page.get_by_test_id("voice").element_handle(),
                page.get_by_test_id("nar-text").element_handle(),
            ],
        )

    @staticmethod
    def record_voice_events(page: Page) -> None:
        """Records from now on in ``window.voiceEvents`` what the voice does, for checks to read and to show on failure.

        An entry is recorded for each event of the audio element that loads, starts, moves, pauses or ends a clip, and
        for each click on Play, each before the page handles it (except a click while the browser holds the voice back:
        the page lets the voice speak on the click's way down to the button, so its entry already shows the voice
        started). An entry (see VoiceEntry) holds the state at that moment: the seconds since the recording began, the
        event, where the voice is in its clip, whether it holds a clip (its ``src`` attribute, which the page removes to
        drop a clip), which clip it has loaded (``currentSrc``, numbered in the order the clips first appear, as their
        sources are long ``data:`` URLs; none before the first), the clip's length, whether the voice is paused, moving
        to another position or at its end, how much of the clip is loaded (``readyState``), where the slider is, whether
        the stage marks the voice as playing, whether the page has drawn its warm-up frames (``warmed``: the stage's
        ``data-ready``; none on a page without a warm-up), the state of Play, and whether the browser holds the voice
        back. The slider moves in 1000 steps over the film, so a step is a thousandth of the film's length (0.1 s on a
        film of 100 s). ``window.voiceState(name)`` returns such an entry for the moment it is called.

        @param page: a page with a voice
        """
        page.evaluate(
            """([audio, play, scrub, stage, sound]) => {
                const begin = performance.now();
                const rounded = (seconds) => Math.round(seconds * 1000) / 1000;
                window.voiceSrcs = [];
                window.voiceEvents = [];
                const clip = () => {
                    if (!audio.currentSrc) return null;
                    if (!window.voiceSrcs.includes(audio.currentSrc)) window.voiceSrcs.push(audio.currentSrc);
                    return window.voiceSrcs.indexOf(audio.currentSrc);
                };
                window.voiceState = (name) => ({
                    at: rounded((performance.now() - begin) / 1000),
                    event: name,
                    voice: rounded(audio.currentTime),
                    src: audio.hasAttribute("src"),
                    clip: clip(),
                    length: rounded(audio.duration),
                    paused: audio.paused,
                    seeking: audio.seeking,
                    ended: audio.ended,
                    ready: audio.readyState,
                    slider: Number(scrub.value),
                    stage: stage.dataset.voice ?? null,
                    warmed: stage.dataset.ready ?? null,
                    play: play.dataset.state,
                    blocked: sound.hasAttribute("data-blocked"),
                });
                const record = (event) => window.voiceEvents.push(window.voiceState(event.type));
                const events = [
                    "loadstart", "emptied", "abort", "error", "loadedmetadata", "seeking", "seeked",
                    "play", "playing", "waiting", "pause", "ended",
                ];
                // listeners of the capture phase run before the page's own listeners on the same element:
                for (const type of events) audio.addEventListener(type, record, true);
                play.addEventListener("click", record, true);
            }""",
            [
                page.get_by_test_id(test_id).element_handle()
                for test_id in ("voice", "play", "scrub", "stage", "sound")
            ],
        )

    @staticmethod
    def voice_report(page: Page) -> str:
        """Returns what the voice did since record_voice_events, and its state now, as text for a failed check.

        @param page: a page whose voice is recorded (see record_voice_events)
        @return: one line for each recorded entry, and a last one for the state now, as ``name=value`` pairs
        """
        entries: list[VoiceEntry] = page.evaluate(
            '[...window.voiceEvents, window.voiceState("now")]'
        )
        return "\n".join(
            " ".join(f"{name}={value}" for name, value in entry.items())
            for entry in entries
        )

    @classmethod
    @contextmanager
    def voice_reported(cls, page: Page) -> Iterator[None]:
        """Appends what the voice did (see voice_report) to the message of a check that fails in the with block.

        A failed check is an AssertionError (also one of ``expect``) or an error of Playwright, e.g. the timeout of a
        wait; either is raised again as an AssertionError whose message ends with the report. If the report cannot be
        made (the page is closed or has crashed), the error is raised again as it is.

        @param page: a page whose voice is recorded (see record_voice_events)
        @return: a context manager for the checks
        """
        try:
            yield
        except (AssertionError, Error) as error:
            report: str | None
            try:
                report = cls.voice_report(page)
            except Error:
                report = None
            if report is None:
                raise
            raise AssertionError(
                f"{error}\n\nwhat the voice did, and its state now:\n{report}"
            ) from error

    @staticmethod
    def voice_event_indexes(
        events: list[VoiceEntry], name: str, start: int = 0
    ) -> list[int]:
        """Returns where the recorded entries of an event are, from a given index on.

        @param events: the entries recorded in ``window.voiceEvents`` (see record_voice_events)
        @param name: the event, e.g. ``"pause"`` of the audio element, or ``"click"`` for a click on Play
        @param start: the index of the first entry to look at
        @return: the indexes of the entries of the event, in the order they were recorded
        """
        return [i for i in range(start, len(events)) if events[i]["event"] == name]

    @staticmethod
    def wait_for_voice_event_after_last_click(page: Page, name: str) -> None:
        """Waits until an entry of an event is recorded after the last recorded click on Play.

        @param page: a page whose voice is recorded (see record_voice_events)
        @param name: the event, e.g. ``"pause"`` or ``"playing"`` of the audio element
        """
        page.wait_for_function(
            """name => {
                const click = window.voiceEvents.findLastIndex((entry) => entry.event === "click");
                return window.voiceEvents.slice(click + 1).some((entry) => entry.event === name);
            }""",
            arg=name,
            timeout=FILM_TIMEOUT,
        )

    @staticmethod
    def let_film_play_until(page: Page, position: int) -> None:
        """Waits until the playing film has moved the slider to at least the given position.

        @param page: a playing page
        @param position: the slider's value to reach, from 0 at the start of the film to 1000 at its end
        """
        scrub = page.get_by_test_id("scrub")
        page.wait_for_function(
            "([scrub, until]) => Number(scrub.value) >= until",
            arg=[scrub.element_handle(), position],
            timeout=FILM_TIMEOUT,
        )

    @classmethod
    def let_film_play_on(cls, page: Page, steps: int) -> None:
        """Waits until the playing film has moved the slider on by at least the given number of steps.

        The slider has 1000 steps from the start of the film to its end; on the clock-scan page, which lasts about
        100 s, ten steps are about 1 s, on the row-or-column page, which lasts 52 s, about 0.5 s.

        @param page: a playing page
        @param steps: how far the slider has to move on
        """
        position: int = int(page.get_by_test_id("scrub").input_value())
        cls.let_film_play_until(page, position + steps)

    @staticmethod
    def has_parts(page: Page) -> bool:
        """Returns whether the page is one of PAGES_WITH_PARTS, and expects the button of part 1 on exactly those.

        @param page: a page with a sound button
        @return: whether the film of the page has parts, with a button that jumps to the start of each
        """
        parts: bool = page.url in {path.as_uri() for path in PAGES_WITH_PARTS}
        expect(page.get_by_test_id("chapter-1")).to_have_count(1 if parts else 0)
        return parts

    def play_until_held_back(self, page: Page) -> None:
        """Makes the browser refuse the sound from now on and plays until it refuses the voice: the voice is held back.

        The browser refuses the voice when a caption begins, as browsers do that hold back a page's first clip; the
        film plays on.

        @param page: a page with sound on and the voice allowed to speak, paused at a caption's start or before it
        """
        self.hold_back_sound(page, True)
        page.get_by_test_id("play").click()
        expect(page.get_by_test_id("sound")).to_have_attribute(
            "data-blocked", "", timeout=FILM_TIMEOUT
        )
        self.expect_sound(page, on=True, held_back=True)
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "playing")


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class EveryPageWithSoundTest(_SoundPageTestCase):
    """Checks the sound button and the voice of every page that has one (decision 034)."""

    def test_voice_speaks_while_playing_with_sound_on(self) -> None:
        """On each page with a sound button, the voice speaks while the page plays with sound on; sound is off at load.

        Next drops the voice's clip, and Play makes the voice speak again; so does a jump back to the start with the
        button of part 1 (on a page without parts: the slider back to the start, and Play). The sound button switches
        the voice off again.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")
            play = page.get_by_test_id("play")
            scrub = page.get_by_test_id("scrub")
            stage = page.get_by_test_id("stage")
            voice = page.get_by_test_id("voice")
            narration = page.get_by_test_id("narration")

            # sound is off at load, and the captions show as subtitles:
            self.expect_sound(page, on=False)

            # a click switches the sound on, and the voice speaks the captions instead:
            sound.click()
            self.expect_sound(page, on=True)

            # Play from the start: the voice speaks the clip of the first caption, which begins shortly after the start
            # (after about 0.75 s on the clock-scan page):
            expect(scrub).to_have_value("0")
            play.click()
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )
            self.assertFalse(voice.evaluate("audio => audio.paused"))
            expect(voice).to_have_attribute("src", re.compile(r"^data:audio/"))

            # Next pauses at the start of the next caption and drops the clip:
            page.get_by_test_id("next").click()
            expect(play).to_have_attribute("data-state", "paused")
            self.assertTrue(voice.evaluate("audio => audio.paused"))
            # the browser tells whether the clip is gone, so that a failure does not print the whole clip:
            self.assertFalse(voice.evaluate("audio => audio.hasAttribute('src')"))
            expect(stage).not_to_have_attribute("data-voice", "playing")

            # Play speaks the next caption:
            play.click()
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

            # the button of part 1 jumps back to the start, before the first caption, and plays from there (on a page
            # without parts: the slider back to the start, which pauses, and Play); the voice speaks again once the
            # first caption begins:
            if self.has_parts(page):
                page.get_by_test_id("chapter-1").click()
                self.assertEqual("start", narration.get_attribute("data-stop-type"))
            else:
                scrub.fill("0")
                self.assertEqual("start", narration.get_attribute("data-stop-type"))
                play.click()
            expect(play).to_have_attribute("data-state", "playing")
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

            # the sound button switches the voice off, the film plays on, and the captions show as subtitles again:
            sound.click()
            self.expect_sound(page, on=False)
            expect(play).to_have_attribute("data-state", "playing")

            # the voice stays silent while the film plays on by 10 steps of the slider, and does not start even for a
            # moment:
            self.record_voice_starts(page)
            self.let_film_play_on(page, 10)
            self.assertTrue(voice.evaluate("audio => audio.paused"))
            self.assertEqual([], page.evaluate("window.voiceStarts"))
            expect(stage).not_to_have_attribute("data-voice", "playing")

        self.check_each_page_with_sound(check)

    def test_voice_stays_silent_with_sound_off(self) -> None:
        """With sound off, the voice stays silent while the film plays on past where it would say the second caption.

        No clip is loaded.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")
            play = page.get_by_test_id("play")
            scrub = page.get_by_test_id("scrub")
            voice = page.get_by_test_id("voice")

            # with sound on, two Next stop where the voice would begin to say the second caption; there the sound is
            # switched off:
            sound.click()
            self.expect_sound(page, on=True)
            page.get_by_test_id("next").click()
            page.get_by_test_id("next").click()
            second_caption: int = int(scrub.input_value())
            sound.click()
            self.expect_sound(page, on=False)

            # ← stops before, where the first caption is shown in full; Play: the film plays on past where the voice
            # would begin the second caption, by 10 steps of the slider:
            page.keyboard.press("ArrowLeft")
            self.assertLess(int(scrub.input_value()), second_caption)
            self.record_voice_starts(page)
            play.click()
            self.let_film_play_until(page, second_caption + 10)

            # the film plays, but the voice is silent, has not started even for a moment, and holds no clip:
            expect(play).to_have_attribute("data-state", "playing")
            self.assertTrue(voice.evaluate("audio => audio.paused"))
            self.assertEqual([], page.evaluate("window.voiceStarts"))
            self.assertFalse(voice.evaluate("audio => audio.hasAttribute('src')"))
            expect(page.get_by_test_id("stage")).not_to_have_attribute(
                "data-voice", "playing"
            )

        self.check_each_page_with_sound(check)

    def test_voice_follows_the_film(self) -> None:
        """With sound on, a voice that runs ahead of the film, or lags more than 1 s behind it, is moved to the film."""

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            voice = page.get_by_test_id("voice")
            # the film's length (s), as the clock shows it, e.g. "0:00 / 1:43":
            minutes, seconds = (
                page.get_by_test_id("clock").inner_text().split(" / ")[1].split(":")
            )
            # the voice, and the slider, which shows the film's time to 1/1000 of its length (on the clock-scan page
            # about 0.1 s):
            film: dict[str, object] = {
                "audio": voice.element_handle(),
                "scrub": page.get_by_test_id("scrub").element_handle(),
                "length": 60 * int(minutes) + int(seconds),
            }

            # how far the voice runs ahead of the film (s), negative while it lags behind:
            ahead: str = "audio.currentTime - (scrub.value / 1000) * length"

            # sound on; Next stops where a caption begins, and Play lets the voice speak it, until it speaks a clip of
            # at least 4.5 s, long enough for the moves below; where it is in that clip:
            page.get_by_test_id("sound").click()
            self.expect_sound(page, on=True)
            duration: float = 0
            while duration < 4.5:
                page.get_by_test_id("next").click()
                self.assertNotEqual(
                    "ended",
                    play.get_attribute("data-state"),
                    "no clip of 4.5 s or more",
                )
                play.click()
                expect(page.get_by_test_id("stage")).to_have_attribute(
                    "data-voice", "playing", timeout=FILM_TIMEOUT
                )
                duration = voice.evaluate("audio => audio.duration")
            start: float = voice.evaluate("audio => audio.currentTime")

            # once the voice is 1 s further in its clip, how far it runs ahead of the film:
            page.wait_for_function(
                "({audio, start}) => audio.currentTime >= start + 1",
                arg={**film, "start": start},
                timeout=FILM_TIMEOUT,
            )
            before: float = page.evaluate(
                f"({{audio, scrub, length}}) => {ahead}", film
            )

            # the voice is moved 2 s ahead in its clip, which is noted:
            voice.evaluate(
                "audio => { window.movedClip = audio.currentSrc; audio.currentTime += 2; }"
            )

            # the page moves it back while it still speaks that clip, to less than 1 s further ahead of the film than
            # before; else the wait would end with a timeout, as the clip would play on about 2 s ahead to its end
            # (after which the film would catch up with it), and then another clip would follow:
            page.wait_for_function(
                f"""({{audio, scrub, length, before}}) =>
                    audio.currentSrc === window.movedClip && !audio.paused && {ahead} < before + 1""",
                arg={**film, "before": before},
                timeout=FILM_TIMEOUT,
            )

            # once the voice is 3 s further in its clip than where it was found, how far it runs ahead of the film:
            page.wait_for_function(
                "({audio, start}) => audio.currentTime >= start + 3",
                arg={**film, "start": start},
                timeout=FILM_TIMEOUT,
            )
            before = page.evaluate(f"({{audio, scrub, length}}) => {ahead}", film)

            # the voice is moved 2.5 s back in its clip: more than 1 s behind the film:
            voice.evaluate("audio => { audio.currentTime -= 2.5; }")

            # the page moves it forward while it still speaks that clip, to less than 1 s further behind the film than
            # before; else the wait would end with a timeout, as the clip would play on about 2.5 s behind, until
            # another clip follows:
            page.wait_for_function(
                f"""({{audio, scrub, length, before}}) =>
                    audio.currentSrc === window.movedClip && !audio.paused && {ahead} > before - 1""",
                arg={**film, "before": before},
                timeout=FILM_TIMEOUT,
            )

        self.check_each_page_with_sound(check)

    def test_voice_speaks_each_caption_once_and_again_after_a_jump_back(self) -> None:
        """With sound on, a clip said in full is not said again, and the next one starts when its caption begins.

        Between the two captions, the voice is silent. After a jump back with the button of part 1 (with the slider on
        a page without parts), the first clip is said again.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            scrub = page.get_by_test_id("scrub")
            stage = page.get_by_test_id("stage")
            voice = page.get_by_test_id("voice")
            # the voice speaks a clip: the first one, or another one:
            speaks_clip: str = """([audio, stage, first]) =>
                stage.dataset.voice === "playing" && (audio.currentSrc === window.firstClip) === first"""

            # with sound off, Next stops where the first caption is shown in full; the slider goes halfway back to the
            # start, into the first caption:
            page.get_by_test_id("next").click()
            scrub.fill(str(int(scrub.input_value()) // 2))

            # sound on and Play: the voice joins the first caption where the film is; its clip is noted, and every
            # start of the voice from now on is recorded:
            page.get_by_test_id("sound").click()
            self.expect_sound(page, on=True)
            page.get_by_test_id("play").click()
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )
            voice.evaluate("audio => { window.firstClip = audio.currentSrc; }")
            self.record_voice_starts(page)

            # the first clip plays to its end, and then the voice speaks another one:
            page.wait_for_function(
                speaks_clip,
                arg=[voice.element_handle(), stage.element_handle(), False],
                timeout=FILM_TIMEOUT,
            )

            # it started once since the first clip, when the second caption was shown, so not during the silence
            # between the captions, and the first clip did not start again:
            self.assertEqual(
                [page.get_by_test_id("nar-text").evaluate("text => text.textContent")],
                page.evaluate("window.voiceStarts"),
            )

            # the button of part 1 jumps back to the start and plays (on a page without parts: the slider back to the
            # start, which pauses, and Play): the voice says the first clip again:
            if self.has_parts(page):
                page.get_by_test_id("chapter-1").click()
            else:
                scrub.fill("0")
                page.get_by_test_id("play").click()
            page.wait_for_function(
                speaks_clip,
                arg=[voice.element_handle(), stage.element_handle(), True],
                timeout=FILM_TIMEOUT,
            )

        self.check_each_page_with_sound(check)

    def test_a_jump_back_drops_the_clip(self) -> None:
        """With sound on, ← and the slider drop the clip the voice speaks, and Play lets the voice speak again.

        The part buttons do so as well (see test_voice_speaks_each_caption_once_and_again_after_a_jump_back); Pause only
        holds the clip (see test_pause_holds_the_clip_and_play_goes_on_in_it).
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            stage = page.get_by_test_id("stage")
            voice = page.get_by_test_id("voice")

            # sound on and Play: the voice speaks the first caption, until 1.5 s of its clip have been played:
            self.play_with_sound(page)
            page.wait_for_function(
                "audio => audio.currentTime >= 1.5",
                arg=voice.element_handle(),
                timeout=FILM_TIMEOUT,
            )

            # ← stops where the first caption begins and drops the clip; Play: the voice speaks again:
            page.keyboard.press("ArrowLeft")
            self.assertFalse(voice.evaluate("audio => audio.hasAttribute('src')"))
            play.click()
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

            # once 1.5 s of the clip have been played again, the slider moves to the start of the film and drops the
            # clip; Play: the voice speaks again when the first caption begins:
            page.wait_for_function(
                "audio => audio.currentTime >= 1.5",
                arg=voice.element_handle(),
                timeout=FILM_TIMEOUT,
            )
            page.get_by_test_id("scrub").fill("0")
            self.assertFalse(voice.evaluate("audio => audio.hasAttribute('src')"))
            play.click()
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

        self.check_each_page_with_sound(check)

    def test_words_light_up_as_the_voice_says_them(self) -> None:
        """The words of a caption light up at the times the voice says them, also with sound off.

        Just after the caption begins, no word is said yet, as each clip begins with 0.4 s of silence; where the caption
        is shown in full, all its words are said.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")
            next_button = page.get_by_test_id("next")
            scrub = page.get_by_test_id("scrub")
            narration = page.get_by_test_id("narration")
            text = page.get_by_test_id("nar-text")

            # with sound on, Next stops where the first caption begins; then the sound is switched off:
            sound.click()
            self.expect_sound(page, on=True)
            next_button.click()
            caption_start: int = int(scrub.input_value())
            sound.click()
            self.expect_sound(page, on=False)

            # one step of the slider into the first caption (a thousandth of the film, e.g. 0.1 s of 1:43; less than
            # the 0.4 s of silence at a clip's start), the caption shows, and no word is said:
            scrub.fill(str(caption_start + 1))
            expect(text).to_have_text(re.compile(r"\w"))
            expect(narration).to_have_attribute("data-words-said", "0")

            # where the first caption is shown in full, all its words are said:
            next_button.click()
            words: int = len(text.inner_text().split())
            self.assertGreater(words, 1)
            expect(narration).to_have_attribute("data-words-said", str(words))

        self.check_each_page_with_sound(check)

    def test_every_stop_shows_a_caption_in_full_with_sound_off(self) -> None:
        """With sound off, every stop of Next before the end shows another caption, with all its words said."""

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            narration = page.get_by_test_id("narration")
            text = page.get_by_test_id("nar-text")
            captions: list[str] = []

            # Next leads to the end; at every stop on the way, the caption shown has all its words said (not none, as
            # just after the next caption has begun):
            for _ in range(MAX_NEXT_CLICKS):
                page.get_by_test_id("next").click()
                if play.get_attribute("data-state") == "ended":
                    break
                caption: str = text.evaluate("text => text.textContent")
                expect(narration).to_have_attribute(
                    "data-words-said", str(len(caption.split()))
                )
                captions.append(caption)
            else:
                self.fail("Next did not reach the end")

            # each stop showed another caption:
            self.assertGreater(len(captions), 1)
            self.assertEqual(len(captions), len(set(captions)))

        self.check_each_page_with_sound(check)

    def test_every_caption_has_a_clip_of_its_own(self) -> None:
        """With sound on, the voice speaks a clip of its own at every caption, from the first one to the last."""

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            stage = page.get_by_test_id("stage")
            voice = page.get_by_test_id("voice")
            text = page.get_by_test_id("nar-text")
            captions: list[str] = []

            # sound on; every clip the voice speaks from now on is noted:
            page.get_by_test_id("sound").click()
            self.expect_sound(page, on=True)
            voice.evaluate("audio => { window.spokenClips = []; }")

            # Next stops where each caption begins, and Play lets the voice speak it, until the film has ended; the
            # clip is noted once the voice speaks it, without waiting for its end:
            for _ in range(MAX_NEXT_CLICKS):
                page.get_by_test_id("next").click()
                if play.get_attribute("data-state") == "ended":
                    break
                captions.append(text.evaluate("text => text.textContent"))
                play.click()
                expect(stage).to_have_attribute(
                    "data-voice", "playing", timeout=FILM_TIMEOUT
                )
                voice.evaluate(
                    "audio => { window.spokenClips.push(audio.currentSrc); }"
                )
            else:
                self.fail("Next did not reach the end")

            # each stop showed another caption, and at each the voice spoke another clip:
            self.assertGreater(len(captions), 1)
            self.assertEqual(len(captions), len(set(captions)))
            self.assertEqual(
                [len(captions), len(captions)],
                page.evaluate(
                    "[window.spokenClips.length, new Set(window.spokenClips).size]"
                ),
            )

        self.check_each_page_with_sound(check)

    def test_narration_text_shows_only_while_the_voice_is_silent(self) -> None:
        """The narration's text is hidden while the voice may speak, and shows as subtitles with sound off.

        Checked where the first caption is shown in full, as at the start the narration has no text yet.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")
            text = page.get_by_test_id("nar-text")

            # with sound off, Next stops where the first caption is shown in full, as a subtitle:
            page.get_by_test_id("next").click()
            expect(text).to_have_text(re.compile(r"\w"))
            expect(text).to_be_visible()

            # sound on: the voice may speak, and the text is hidden:
            sound.click()
            self.expect_sound(page, on=True)
            expect(text).to_be_hidden()

            # sound off: the text shows again:
            sound.click()
            self.expect_sound(page, on=False)
            expect(text).to_be_visible()

        self.check_each_page_with_sound(check)

    def test_voice_held_back_by_the_browser_speaks_after_a_click_on_the_sound_button(
        self,
    ) -> None:
        """While the browser holds the voice back, the captions show as with sound off, and Next and ← stop as then.

        A click or key press the browser refuses as well leaves the voice held back. Once the browser allows sound, a
        click on the pulsing sound button lets the voice speak and leaves the sound on.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")
            play = page.get_by_test_id("play")
            scrub = page.get_by_test_id("scrub")

            # with sound off, Next stops where the first caption is shown in full, and ← returns to the start:
            page.get_by_test_id("next").click()
            shown_in_full: str = scrub.input_value()
            page.keyboard.press("ArrowLeft")
            expect(scrub).to_have_value("0")

            # sound on and Play, and the browser refuses the voice when the first caption begins: the voice is held
            # back, the captions show, and a hint asks for a click or key press:
            sound.click()
            self.expect_sound(page, on=True)
            self.play_until_held_back(page)

            # Next, whose click the browser refuses as well, stops where the first caption is shown in full, not where
            # the second one begins, and the caption shows:
            page.get_by_test_id("next").click()
            expect(scrub).to_have_value(shown_in_full)
            self.expect_sound(page, on=True, held_back=True)
            expect(page.get_by_test_id("nar-text")).to_be_visible()

            # ←, a key press the browser refuses as well, returns to the start, not to where the first caption begins:
            page.keyboard.press("ArrowLeft")
            expect(scrub).to_have_value("0")
            self.expect_sound(page, on=True, held_back=True)

            # Play: the film plays, and the voice stays held back:
            play.click()
            expect(play).to_have_attribute("data-state", "playing")
            self.expect_sound(page, on=True, held_back=True)

            # the browser allows sound again: a click on the pulsing sound button lets the voice speak, the sound
            # stays on:
            self.hold_back_sound(page, False)
            sound.click()
            self.expect_sound(page, on=True)
            expect(page.get_by_test_id("stage")).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

        self.check_each_page_with_sound(check)

    def test_voice_held_back_by_the_browser_speaks_after_any_click_or_key_press(
        self,
    ) -> None:
        """Once the browser allows sound, a click or key press that does nothing else lets a held-back voice speak."""

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            stage = page.get_by_test_id("stage")

            # sound on and Play, and the browser refuses the voice when the first caption begins; the film plays on:
            page.get_by_test_id("sound").click()
            self.expect_sound(page, on=True)
            self.play_until_held_back(page)

            # the browser allows sound again, and a press of X lets the voice speak:
            self.hold_back_sound(page, False)
            page.keyboard.press("x")
            self.expect_sound(page, on=True)
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

            # ← stops where the caption on screen begins, and the browser refuses the voice when it plays again:
            page.keyboard.press("ArrowLeft")
            self.play_until_held_back(page)

            # the browser allows sound again, and a click on the clock lets the voice speak:
            self.hold_back_sound(page, False)
            page.get_by_test_id("clock").click()
            self.expect_sound(page, on=True)
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

        self.check_each_page_with_sound(check)

    def test_sound_goes_off_if_the_browser_refuses_it_after_the_sound_button_or_m(
        self,
    ) -> None:
        """If the browser refuses the voice even after a click on the sound button or M, the sound goes back off.

        This holds for switching the sound on, and for the click or M that would let a held-back voice speak.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")

            # the browser refuses sound: switched on, the sound goes back off at once:
            self.hold_back_sound(page, True)
            sound.click()
            self.expect_sound(page, on=False)

            # the browser allows sound: switched on, and then it refuses the voice when the first caption begins:
            self.hold_back_sound(page, False)
            sound.click()
            self.expect_sound(page, on=True)
            self.play_until_held_back(page)

            # a click on the pulsing sound button, which the browser refuses as well, switches the sound off, and the
            # film plays on:
            sound.click()
            self.expect_sound(page, on=False)
            expect(page.get_by_test_id("play")).to_have_attribute(
                "data-state", "playing"
            )

            # the browser allows sound: M switches it on, and ← stops where the caption on screen begins; then the
            # browser refuses the voice when that caption plays again:
            self.hold_back_sound(page, False)
            page.keyboard.press("m")
            self.expect_sound(page, on=True)
            page.keyboard.press("ArrowLeft")
            self.play_until_held_back(page)

            # M, which the browser refuses as well, switches the sound off:
            page.keyboard.press("m")
            self.expect_sound(page, on=False)

        self.check_each_page_with_sound(check)

    def test_a_play_from_outside_lets_a_held_back_voice_speak(self) -> None:
        """While the voice is held back and the film plays, a play of the voice from outside lets the voice speak.

        Such a play, e.g. by the media keys, shows that the browser allows sound now; the voice follows the film from
        there on.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            # sound on and Play, and the browser refuses the voice when the first caption begins; the film plays on:
            page.get_by_test_id("sound").click()
            self.expect_sound(page, on=True)
            self.play_until_held_back(page)

            # the browser allows sound, and the voice is played from outside the page, as the media keys do:
            self.hold_back_sound(page, False)
            page.get_by_test_id("voice").evaluate(
                "audio => { audio.play().catch(() => {}); }"
            )

            # the voice speaks, and the captions are no longer shown:
            self.expect_sound(page, on=True)
            expect(page.get_by_test_id("stage")).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )
            expect(page.get_by_test_id("play")).to_have_attribute(
                "data-state", "playing"
            )

        self.check_each_page_with_sound(check)

    def test_m_switches_the_sound_on_and_off(self) -> None:
        """On each page with a sound button, the key M switches the sound on and off again; sound is off at load.

        A held M switches only once, and M with Ctrl is left to the browser.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            # sound is off at load, with the hint how to switch it on:
            self.expect_sound(page, on=False)

            # M switches the sound on, and M again off:
            page.keyboard.press("m")
            self.expect_sound(page, on=True)
            page.keyboard.press("m")
            self.expect_sound(page, on=False)

            # a held M, which the keyboard repeats, switches the sound only once:
            page.keyboard.down("m")
            page.keyboard.down("m")
            page.keyboard.up("m")
            self.expect_sound(page, on=True)

            # with Ctrl, M is left to the browser, and the sound stays on:
            page.keyboard.press("Control+m")
            self.expect_sound(page, on=True)

        self.check_each_page_with_sound(check)

    def test_space_on_the_sound_button_plays_and_pauses_and_leaves_the_sound_on(
        self,
    ) -> None:
        """On the sound button, which keeps the focus after a click, Space plays and pauses, and the sound stays on.

        A held Space, which the keyboard repeats, pauses once and does not click the sound button when it comes up.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")
            play = page.get_by_test_id("play")

            # a click switches the sound on, and the sound button keeps the focus:
            sound.click()
            self.expect_sound(page, on=True)
            expect(sound).to_be_focused()

            # Space plays the film, and the sound stays on:
            page.keyboard.press("Space")
            expect(play).to_have_attribute("data-state", "playing")
            self.expect_sound(page, on=True)

            # a held Space, which the keyboard repeats before it comes up, pauses the film, and the sound stays on:
            page.keyboard.down("Space")
            page.keyboard.down("Space")
            page.keyboard.up("Space")
            expect(play).to_have_attribute("data-state", "paused")
            self.expect_sound(page, on=True)

        self.check_each_page_with_sound(check)

    def test_pause_holds_the_clip_and_play_goes_on_in_it(self) -> None:
        """With sound on, Pause holds the voice's clip where it is, and Play goes on in it, not from its start.

        A listener that the test adds to the page clicks Pause, and the checks read the voice's state at Pause and at
        Play from the recorded events, as a click or a read of the test may come seconds late on a slow machine.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            stage = page.get_by_test_id("stage")
            voice = page.get_by_test_id("voice")

            # record what the voice does: the checks below read it, and a failed check shows it:
            self.record_voice_events(page)
            with self.voice_reported(page):
                # sound on:
                page.get_by_test_id("sound").click()
                self.expect_sound(page, on=True)

                # a listener that the test adds to the page clicks Pause once the voice plays past 2 s of its clip (half
                # of a clip shorter than 4 s, so that the clip still plays after Pause and Play). It clicks in a frame,
                # after the page's own frame callback, and only if stage[data-voice] is "playing" (else it tries again
                # in the next frame): only then has the page kept the voice at most VOICE_AHEAD (0.25 s) ahead of the
                # film and VOICE_BEHIND (1.0 s) behind it, which bounds where Play lets the voice go on:
                voice.evaluate(
                    """(audio, [play, stage]) => {
                        const due = () =>
                            !audio.paused && !audio.ended && audio.currentTime >= Math.min(2, audio.duration / 2);
                        const pauseInFrame = () => {
                            if (play.dataset.state !== "playing") return;
                            if (due() && stage.dataset.voice === "playing") play.click();
                            else requestAnimationFrame(pauseInFrame);
                        };
                        const arm = () => {
                            if (!due()) return;
                            audio.removeEventListener("timeupdate", arm);
                            requestAnimationFrame(pauseInFrame);
                        };
                        audio.addEventListener("timeupdate", arm);
                    }""",
                    [play.element_handle(), stage.element_handle()],
                )

                # Play: the voice speaks the first caption until the listener clicks Pause, and the voice's pause is
                # recorded (the browser sends its event a moment after the click):
                play.click()
                expect(play).to_have_attribute(
                    "data-state", "paused", timeout=FILM_TIMEOUT
                )
                self.wait_for_voice_event_after_last_click(page, "pause")

                # Pause silences the voice but holds its clip:
                expect(stage).not_to_have_attribute("data-voice", "playing")
                self.assertTrue(voice.evaluate("audio => audio.paused"))
                expect(voice).to_have_attribute("src", re.compile(r"^data:audio/"))

                # the last click on Play was made while the film played, so it is the listener's click on Pause:
                events: list[VoiceEntry] = page.evaluate("window.voiceEvents")
                clicks: list[int] = self.voice_event_indexes(events, "click")
                self.assertTrue(clicks, "no click on Play recorded")
                pause_click: int = clicks[-1]
                self.assertEqual(
                    "playing", events[pause_click]["play"], "no in-page click on Pause"
                )

                # after that click, the voice was paused before its clip ended, and well past the clip's start:
                pauses: list[int] = self.voice_event_indexes(
                    events, "pause", pause_click
                )
                self.assertTrue(pauses, "no pause of the voice after the in-page click")
                paused: VoiceEntry = events[pauses[0]]
                self.assertFalse(
                    paused["ended"], "the voice was not paused before its clip ended"
                )
                held: float = paused["voice"]
                self.assertGreater(held, 0.5, "Pause held the clip at its start")

                # Play, and wait until the voice plays again after this click:
                play.click()
                self.wait_for_voice_event_after_last_click(page, "playing")

                # where the voice started after Play, as recorded then (a late read of the test does not change it):
                events = page.evaluate("window.voiceEvents")
                play_click: int = self.voice_event_indexes(events, "click")[-1]
                self.assertGreater(
                    play_click, pause_click, "no click on Play after Pause"
                )
                start: int = self.voice_event_indexes(events, "playing", play_click)[0]
                resumed: VoiceEntry = events[start]

                # Play goes on in the held clip, without loading it again:
                reloads: list[str] = [
                    entry["event"]
                    for entry in events[pause_click:start]
                    if entry["event"] in ("emptied", "loadstart")
                ]
                self.assertEqual([], reloads, "Play loaded a clip again")
                self.assertEqual(
                    paused["clip"], resumed["clip"], "Play started another clip"
                )

                # and near where Pause held it, not from its start (which is 0.4 s of silence): the page may move the
                # voice to the film's time, back by up to VOICE_AHEAD (0.25 s, plus a margin: 0.3 s), or forward by up
                # to VOICE_BEHIND (1.0 s) and one frame of the film (plus a margin: 1.5 s):
                self.assertGreaterEqual(
                    resumed["voice"],
                    held - 0.3,
                    "Play did not go on where Pause held the clip",
                )
                self.assertLessEqual(
                    resumed["voice"], held + 1.5, "Play jumped ahead in the held clip"
                )

        self.check_each_page_with_sound(check)

    def test_a_pause_from_outside_pauses_the_film_and_a_play_is_undone(self) -> None:
        """A pause of the voice that the page did not cause, e.g. by the media keys, pauses the film as well.

        A play of the voice that the page did not cause, over the paused film, is undone.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            voice = page.get_by_test_id("voice")

            # sound on and Play: the voice speaks the first caption:
            self.play_with_sound(page)
            expect(play).to_have_attribute("data-state", "playing")

            # the voice is paused from outside the page, as the media keys do, and the film pauses with it:
            voice.evaluate("audio => audio.pause()")
            expect(play).to_have_attribute("data-state", "paused")

            # the voice is played from outside the page, and it starts (the browser allows it after the clicks above);
            # where it was in its clip:
            started, position = voice.evaluate(
                "audio => { audio.play().catch(() => {}); return [!audio.paused, audio.currentTime]; }"
            )
            self.assertTrue(started)

            # the page pauses it again at once, not at the end of its clip, and the film stays paused:
            page.wait_for_function(
                "audio => audio.paused && !audio.ended",
                arg=voice.element_handle(),
                timeout=2_000,
            )
            self.assertLess(
                voice.evaluate("audio => audio.currentTime") - position, 0.5
            )
            expect(page.get_by_test_id("stage")).not_to_have_attribute(
                "data-voice", "playing"
            )
            expect(play).to_have_attribute("data-state", "paused")

        self.check_each_page_with_sound(check)

    def test_a_hidden_tab_pauses_the_film_only_with_sound_on(self) -> None:
        """Hiding the tab pauses the film while sound is on, as the voice would speak on; with sound off it plays on."""

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")

            # with sound off, the film plays on in a hidden tab:
            play.click()
            expect(play).to_have_attribute("data-state", "playing")
            self.set_tab_hidden(page, True)
            expect(play).to_have_attribute("data-state", "playing")

            # the tab is shown again, and the sound is switched on while the film plays:
            self.set_tab_hidden(page, False)
            page.get_by_test_id("sound").click()
            self.expect_sound(page, on=True)
            expect(play).to_have_attribute("data-state", "playing")

            # now hiding the tab pauses the film:
            self.set_tab_hidden(page, True)
            expect(play).to_have_attribute("data-state", "paused")

        self.check_each_page_with_sound(check)

    def test_next_and_back_stop_where_a_caption_begins_with_sound_on(self) -> None:
        """With sound on, Next and ← stop where a caption begins, earlier than with sound off.

        With sound off, they stop where a caption is shown in full.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            scrub = page.get_by_test_id("scrub")
            next_button = page.get_by_test_id("next")

            # with sound off, Next stops where the first caption is shown in full:
            next_button.click()
            without_sound: int = int(scrub.input_value())

            # ← returns to the start, and the sound is switched on:
            page.keyboard.press("ArrowLeft")
            expect(scrub).to_have_value("0")
            page.get_by_test_id("sound").click()
            self.expect_sound(page, on=True)

            # with sound on, Next stops earlier, where the first caption begins, paused, so that Play speaks it:
            next_button.click()
            expect(page.get_by_test_id("play")).to_have_attribute(
                "data-state", "paused"
            )
            with_sound: int = int(scrub.input_value())
            self.assertGreater(with_sound, 0)
            self.assertLess(with_sound, without_sound)

            # a second Next stops where the second caption begins, after the first one was shown in full:
            next_button.click()
            self.assertGreater(int(scrub.input_value()), without_sound)

            # ← returns to where the first caption begins, not to where it is shown in full:
            page.keyboard.press("ArrowLeft")
            expect(scrub).to_have_value(str(with_sound))

        self.check_each_page_with_sound(check)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class ClockScanPageTest(_SoundPageTestCase):
    """Checks what is particular to the voice of the clock-scan page."""

    PAGE: Path | None = CLOCK_SCAN_PAGE

    def test_a_clip_longer_than_its_caption_plays_faster(self) -> None:
        """The clip of the first caption plays at its normal speed, and that of the fifth, which is longer, faster.

        A clip longer than its caption plays at most 1.15 times as fast (decision 034).
        """
        opened: OpenedPage = self.open_page(CLOCK_SCAN_PAGE)
        page: Page = opened.page
        next_button = page.get_by_test_id("next")
        play = page.get_by_test_id("play")
        stage = page.get_by_test_id("stage")
        voice = page.get_by_test_id("voice")

        # sound on, and Next stops where the first caption begins; Play: its clip plays at its normal speed:
        page.get_by_test_id("sound").click()
        self.expect_sound(page, on=True)
        next_button.click()
        play.click()
        expect(stage).to_have_attribute("data-voice", "playing", timeout=FILM_TIMEOUT)
        self.assertEqual(1, voice.evaluate("audio => audio.playbackRate"))

        # four more Next stop where the fifth caption begins; Play: its clip plays faster:
        for _ in range(4):
            next_button.click()
        expect(page.get_by_test_id("nar-text")).to_contain_text("At 7, a = 42")
        play.click()
        expect(stage).to_have_attribute("data-voice", "playing", timeout=FILM_TIMEOUT)
        rate: float = voice.evaluate("audio => audio.playbackRate")
        self.assertGreater(rate, 1)
        self.assertLessEqual(rate, 1.15)
        self.assert_no_errors(opened)

    def test_the_sound_hint_gives_way_to_the_end_card(self) -> None:
        """With sound off, the hint "Switch on audio (M)" fades out while the end card fades in, which it would cover on
        a narrow window, and shows again before it."""
        opened: OpenedPage = self.open_page(CLOCK_SCAN_PAGE)
        page: Page = opened.page
        hint = page.get_by_test_id("sound-hint")
        scrub = page.get_by_test_id("scrub")

        # at the start, the hint shows in full:
        expect(hint).to_have_text("Switch on audio (M)")
        expect(hint).to_have_css("opacity", "1")

        # at the end, where the end card shows, the hint has faded out:
        scrub.fill("1000")
        expect(page.get_by_test_id("legend")).to_have_css("opacity", "1")
        expect(hint).to_have_css("opacity", "0")

        # back at the start, it shows again:
        scrub.fill("0")
        expect(hint).to_have_css("opacity", "1")
        self.assert_no_errors(opened)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class RowOrColumnPageTest(_SoundPageTestCase):
    """Checks what is particular to the voice of the row-or-column page, which says some captions in two segments.

    Each segment has a clip of its own, which starts at the segment's time (decision 035). The times below are those
    of the page's CAPTIONS.
    """

    PAGE: Path | None = ROW_OR_COLUMN_PAGE

    # the film's length (s); the slider has 1000 steps over it:
    LENGTH: float = 52
    # the steps of the film in their order, by their stop type, and where the first segment of each begins (s):
    STEP_TYPES: list[str] = [
        "query",
        "memory",
        "cache-lines",
        "row-layout",
        "column-layout",
        "verdict",
        "result",
    ]
    FIRST_SEGMENTS: list[float] = [0.5, 6.4, 13.4, 19.4, 30.6, 42.5, 49.3]
    # the row-layout step, the fourth, says its caption in two segments; the second one begins at 25.8 s:
    ROW_LAYOUT_STEP: int = 4
    ROW_LAYOUT_SEGMENTS: list[str] = [
        "Row layout: each line drags title and author along.",
        "Four lines read, a quarter used.",
    ]
    ROW_LAYOUT_SECOND_SEGMENT: float = 25.8
    # the column-layout step, the fifth, says its caption in two segments as well; the second one begins at 37.0 s (the
    # tests of tools/render_video.py check the start of its clip):
    COLUMN_LAYOUT_SECOND_SEGMENT: float = 37.0
    # a clip longer than its time plays at most this many times as fast (decision 034):
    MAX_RATE: float = 1.15

    def setUp(self) -> None:
        """Opens the page, paused at its start with sound off."""
        self.opened: OpenedPage = self.open_page(ROW_OR_COLUMN_PAGE)
        self.page: Page = self.opened.page

    def slider_at(self, seconds: float) -> float:
        """Returns where the slider stands at a time of the film, before the page rounds it to a whole step.

        @param seconds: a time of the film
        @return: the slider's position, from 0 at the start of the film to 1000 at its end
        """
        return seconds / self.LENGTH * 1000

    def press_next(self, times: int) -> None:
        """Clicks Next the given number of times.

        @param times: how often Next is clicked
        """
        for _ in range(times):
            self.page.get_by_test_id("next").click()

    def test_a_second_segment_gets_a_clip_of_its_own(self) -> None:
        """With sound on, the second segment of a caption is said by a clip of its own, which starts at its time.

        The first clip does not start again; the second one starts once, not before its segment begins, while the step
        is still shown.
        """
        page: Page = self.page
        scrub = page.get_by_test_id("scrub")
        narration = page.get_by_test_id("narration")
        stage = page.get_by_test_id("stage")
        voice = page.get_by_test_id("voice")

        # with sound on, Next stops where the row-layout step begins, whose caption is said in two segments:
        page.get_by_test_id("sound").click()
        self.expect_sound(page, on=True)
        self.press_next(self.ROW_LAYOUT_STEP)
        expect(narration).to_have_attribute("data-stop-type", "row-layout")

        # Play: the voice says the first segment; its clip is noted, and every start of the voice from now on is
        # recorded:
        page.get_by_test_id("play").click()
        expect(stage).to_have_attribute("data-voice", "playing", timeout=FILM_TIMEOUT)
        voice.evaluate("audio => { window.firstClip = audio.currentSrc; }")
        self.record_voice_starts(page)

        # the first clip plays to its end, and then the voice speaks another one:
        page.wait_for_function(
            """([audio, stage]) =>
                stage.dataset.voice === "playing" && audio.currentSrc !== window.firstClip""",
            arg=[voice.element_handle(), stage.element_handle()],
            timeout=FILM_TIMEOUT,
        )

        # it began at or after the time of the second segment, still in the row-layout step, and the voice started
        # only once, for it:
        self.assertGreaterEqual(
            int(scrub.input_value()),
            math.floor(self.slider_at(self.ROW_LAYOUT_SECOND_SEGMENT)),
        )
        self.assertEqual("row-layout", narration.get_attribute("data-stop-type"))
        self.assertEqual(1, len(page.evaluate("window.voiceStarts")))
        self.assert_no_errors(self.opened)

    def test_next_and_back_stop_once_per_step_with_sound_on(self) -> None:
        """With sound on, Next and ← stop once per step, where its first segment begins, also in a step of two segments.

        So a step's second segment is no stop.
        """
        page: Page = self.page
        scrub = page.get_by_test_id("scrub")
        narration = page.get_by_test_id("narration")

        # with sound on, Next leads to the end through each step once, in their order:
        page.get_by_test_id("sound").click()
        self.expect_sound(page, on=True)
        self.assertEqual([*self.STEP_TYPES, "end"], self.step_to_end(page))

        # ← leads back to the start through each step once, in reverse order, each time where its first segment
        # begins:
        stops: list[tuple[str, int]] = []
        for _ in range(len(self.STEP_TYPES) + 1):
            page.keyboard.press("ArrowLeft")
            stops.append(
                (
                    narration.get_attribute("data-stop-type") or "",
                    int(scrub.input_value()),
                )
            )
        # the page rounds the slider to a whole step, half steps up, as Math.round does:
        expected: list[tuple[str, int]] = [
            (step_type, math.floor(self.slider_at(at) + 0.5))
            for step_type, at in zip(self.STEP_TYPES, self.FIRST_SEGMENTS)
        ]
        self.assertEqual([*reversed(expected), ("start", 0)], stops)
        self.assert_no_errors(self.opened)

    def test_words_said_count_segment_by_segment(self) -> None:
        """With sound off, the words of a caption in two segments count as said segment by segment.

        Just before the second segment begins, all words of the first are said; in the silence at the start of the
        second segment's clip, still only those; where the caption is shown in full, all words of both.
        """
        page: Page = self.page
        scrub = page.get_by_test_id("scrub")
        narration = page.get_by_test_id("narration")
        first_words: int = len(self.ROW_LAYOUT_SEGMENTS[0].split())
        all_words: int = len(" ".join(self.ROW_LAYOUT_SEGMENTS).split())
        second_segment: float = self.slider_at(self.ROW_LAYOUT_SECOND_SEGMENT)

        # with sound off, Next stops where the row-layout step is shown in full: both segments, all words said:
        self.press_next(self.ROW_LAYOUT_STEP)
        expect(narration).to_have_attribute("data-stop-type", "row-layout")
        expect(page.get_by_test_id("nar-text")).to_have_text(
            " ".join(self.ROW_LAYOUT_SEGMENTS)
        )
        expect(narration).to_have_attribute("data-words-said", str(all_words))

        # on the last step of the slider before the second segment begins, all words of the first one are said:
        scrub.fill(str(math.ceil(second_segment) - 1))
        expect(narration).to_have_attribute("data-words-said", str(first_words))

        # on the first step after it begins, in the silence of 0.4 s at the start of its clip, still only those:
        scrub.fill(str(math.ceil(second_segment)))
        expect(narration).to_have_attribute("data-words-said", str(first_words))
        self.assert_no_errors(self.opened)

    def test_the_last_clip_plays_faster(self) -> None:
        """The first clip plays at its normal speed, and the last one, longer than the time left in the film, faster.

        It plays at most 1.15 times as fast.
        """
        page: Page = self.page
        play = page.get_by_test_id("play")
        stage = page.get_by_test_id("stage")
        voice = page.get_by_test_id("voice")

        # sound on, and Next stops where the first step begins; Play: its clip plays at its normal speed:
        page.get_by_test_id("sound").click()
        self.expect_sound(page, on=True)
        self.press_next(1)
        play.click()
        expect(stage).to_have_attribute("data-voice", "playing", timeout=FILM_TIMEOUT)
        self.assertEqual(1, voice.evaluate("audio => audio.playbackRate"))

        # Next leads on to where the last step begins; Play: its clip plays faster:
        self.press_next(len(self.STEP_TYPES) - 1)
        expect(page.get_by_test_id("narration")).to_have_attribute(
            "data-stop-type", "result"
        )
        play.click()
        expect(stage).to_have_attribute("data-voice", "playing", timeout=FILM_TIMEOUT)
        rate: float = voice.evaluate("audio => audio.playbackRate")
        self.assertGreater(rate, 1)
        self.assertLessEqual(rate, self.MAX_RATE)
        self.assert_no_errors(self.opened)

    def test_the_terminal_credits_the_synthetic_voice_at_the_end(self) -> None:
        """The terminal shows the line that credits the synthetic voice only at the end of the film."""
        page: Page = self.page
        scrub = page.get_by_test_id("scrub")
        credit = page.get_by_test_id("voice-credit")

        # at the start, the line is left out:
        expect(credit).to_be_hidden()

        # at the end, the terminal shows it:
        scrub.fill("1000")
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "ended")
        expect(credit).to_be_visible()
        expect(credit).to_contain_text("synthetic voice")

        # back at the start, it is left out again:
        scrub.fill("0")
        expect(credit).to_be_hidden()
        self.assert_no_errors(self.opened)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class HouseDbmsPageTest(_SoundPageTestCase):
    """Checks what is particular to the voice of the House DBMS page (decision 036)."""

    PAGE: Path | None = HOUSE_DBMS_PAGE

    # the caption that stays on until 0.3 s after the optimizer has handed over the plan, so that the voice has the
    # time to say it:
    PLANNED_ONCE: str = "The optimizer plans it once: id = ?"

    def test_the_stop_of_the_optimizers_caption_stays_in_its_scene(self) -> None:
        """With sound off, Next stops on "The optimizer plans it once: id = ?" in scene 9, with all its 8 words said.

        The caption ends 0.3 s after scene 10 begins (at the hand-over of the plan); its stop lies CAPTION_FADE
        (0.35 s) before its end, so still in scene 9.
        """
        opened: OpenedPage = self.open_page(HOUSE_DBMS_PAGE)
        page: Page = opened.page
        text = page.get_by_test_id("nar-text")

        # with sound off, Next stops where each caption is shown in full, until the optimizer's caption shows:
        clicks: int = 0
        while text.text_content() != self.PLANNED_ONCE:
            self.assertLess(clicks, MAX_NEXT_CLICKS, "Next did not reach the caption")
            page.get_by_test_id("next").click()
            clicks += 1

        # the stop shows scene 9 (PREPARE), and all 8 words of the caption are said by then:
        expect(page.get_by_test_id("stage")).to_have_attribute("data-scene", "9")
        expect(page.get_by_test_id("narration")).to_have_attribute(
            "data-words-said", "8"
        )
        self.assert_no_errors(opened)

    def test_the_sound_hint_gives_way_to_the_end_card(self) -> None:
        """With sound off, the hint "Switch on audio (M)" fades out while the end card fades in, which it would cover on
        a narrow window, and shows again before it."""
        opened: OpenedPage = self.open_page(HOUSE_DBMS_PAGE)
        page: Page = opened.page
        hint = page.get_by_test_id("sound-hint")
        scrub = page.get_by_test_id("scrub")

        # at the start, the hint shows in full:
        expect(hint).to_have_text("Switch on audio (M)")
        expect(hint).to_have_css("opacity", "1")

        # at the end, where the end card shows, the hint has faded out:
        scrub.fill("1000")
        expect(page.get_by_test_id("legend")).to_have_css("opacity", "1")
        expect(hint).to_have_css("opacity", "0")

        # back at the start, it shows again:
        scrub.fill("0")
        expect(hint).to_have_css("opacity", "1")
        self.assert_no_errors(opened)

    def test_the_end_card_names_the_voice(self) -> None:
        """The end card says that the voice is synthetic and names its model and voice."""
        opened: OpenedPage = self.open_page(HOUSE_DBMS_PAGE)
        page: Page = opened.page

        # at the end, the end card shows, with the credit of the voice:
        page.get_by_test_id("scrub").fill("1000")
        expect(page.get_by_test_id("legend")).to_contain_text(
            "The voice is synthetic: Ming-3.0 TTS, voice UK_George."
        )
        self.assert_no_errors(opened)

    def test_the_sound_hint_leaves_the_sql_card_free_on_a_phone(self) -> None:
        """On a phone's narrow screen (360 × 800 px), the hint does not cover the SQL card, not even the widest one
        (order 3's): neither "Switch on audio (M)" with sound off nor the longer "Click or press a key for sound" while
        the browser holds the voice back.

        On a screen up to 720 px wide, the card moves below the place of the ×4 badge, and the hint to its right,
        where a hint too long for one line wraps.
        """
        opened: OpenedPage = self.open_page(HOUSE_DBMS_PAGE)
        page: Page = opened.page
        play = page.get_by_test_id("play")
        query = page.get_by_test_id("query")
        hint = page.get_by_test_id("sound-hint")

        def expect_hint_beside_order_3s_card() -> None:
            """Expects order 3's SQL card to show, and the hint's box not to overlap the card's box."""
            expect(query).to_have_attribute("data-order", "3")
            expect(query).to_have_css("opacity", "1")
            hint_box: FloatRect | None = hint.bounding_box()
            query_box: FloatRect | None = query.bounding_box()
            if hint_box is None or query_box is None:
                self.fail("the hint or the SQL card has no box")
            apart: bool = (
                hint_box["x"] >= query_box["x"] + query_box["width"]
                or query_box["x"] >= hint_box["x"] + hint_box["width"]
                or hint_box["y"] >= query_box["y"] + query_box["height"]
                or query_box["y"] >= hint_box["y"] + hint_box["height"]
            )
            self.assertTrue(
                apart, f"the hint {hint_box} covers the SQL card {query_box}"
            )

        # a small phone held upright:
        page.set_viewport_size({"width": 360, "height": 800})

        # the button of order 3 jumps to its start and plays; Play pauses there, with order 3's SQL shown and, with
        # sound off, the hint "Switch on audio (M)" beside it:
        page.get_by_test_id("chapter-3").click()
        play.click()
        expect(play).to_have_attribute("data-state", "paused")
        self.expect_sound(page, on=False)
        expect_hint_beside_order_3s_card()

        # sound on, and Play while the browser refuses sound: the voice is held back, and the hint "Click or press a
        # key for sound" shows, also beside the card (the film plays on in order 3, which lasts about 28 s):
        page.get_by_test_id("sound").click()
        self.expect_sound(page, on=True)
        self.play_until_held_back(page)
        expect_hint_beside_order_3s_card()
        self.assert_no_errors(opened)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class YannakakisPageTest(_SoundPageTestCase):
    """Checks the counts, the steps and the robot of the Yannakakis page, and what is particular to its voice
    (decision 038).

    The counts are how many of the six semi-joins are done and how many tuples are left: the four relations of the film
    have 18 tuples together; each semi-join removes some of them, and 8 are left at the end. The steps are the 19 steps
    of the film, of which Next shows each at some stop. The robot carries each semi-join's key column to its place.
    """

    # the pairs (semi-joins done, tuples left) that Next shows on the way from the start to the end, in this order:
    COUNTS: list[tuple[int, int]] = [
        (0, 18),
        (1, 17),
        (2, 15),
        (3, 13),
        (4, 12),
        (5, 10),
        (6, 8),
    ]
    # the second caption, one of the longest, which wraps to several lines on a phone:
    SECOND_CAPTION: str = (
        "Its joins form a tree with root R: T joins R on a, U on b, S on c."
    )
    # the buttons of the controls at the bottom:
    TRANSPORT_BUTTONS: list[str] = [
        "chapter-1",
        "chapter-2",
        "chapter-3",
        "chapter-4",
        "play",
        "next",
        "sound",
        "fullscreen",
    ]
    # how long the robot leaves (s): from when the camera starts to close in, it walks off and fades:
    ROBOT_LEAVES: float = 1.7
    # which way the robot of each semi-join is turned as it starts to carry the key column and when it has left: 1 for a
    # positive turn, its front towards the right of the picture, -1 for a negative one, towards the left:
    ROBOT_SIDES: dict[int, tuple[int, int]] = {
        1: (1, 1),
        2: (-1, 1),
        3: (1, 1),
        4: (1, 1),
        5: (-1, -1),
        6: (1, 1),
    }

    def setUp(self) -> None:
        """Opens the page, paused at its start."""
        self.opened: OpenedPage = self.open_page(YANNAKAKIS_PAGE)
        self.page: Page = self.opened.page

    def counts(self) -> tuple[int, int]:
        """Returns the semi-joins done and the tuples left, as the page shows them.

        Also asserts that the semi-joins done are the first ones and that the counter shows the tuples left.

        @return: how many of the six semi-joins are done (``data-state`` of ``semi-join-1`` … ``semi-join-6``), and
            how many tuples are left (``data-tuples-left`` of the stage)
        """
        states: list[str] = [
            self.page.get_by_test_id(f"semi-join-{k}").get_attribute("data-state") or ""
            for k in range(1, 7)
        ]
        done: int = states.count("done")
        # the semi-joins are done in their order: those done are semi-joins 1 to done:
        self.assertEqual(["done"] * done, states[:done], f"out of order: {states}")

        # the counter shows the tuples left that the stage holds:
        left: str = (
            self.page.get_by_test_id("stage").get_attribute("data-tuples-left") or ""
        )
        self.assertEqual(left, self.page.get_by_test_id("tuples-left").text_content())
        return done, int(left)

    def seen_at_each_stop[T](self, read: Callable[[], T]) -> list[T]:
        """Clicks Next from the start to the end and returns what read returns at the start and after each click.

        A value is noted only when it differs from the one noted before, so stops in a row that show the same value
        give it once.

        @param read: reads what the paused page shows, e.g. its counts
        @return: the values in the order in which Next showed them
        """
        play = self.page.get_by_test_id("play")
        seen: list[T] = [read()]
        clicks: int = 0
        while play.get_attribute("data-state") != "ended":
            self.assertLess(clicks, MAX_NEXT_CLICKS, "Next did not reach the end")
            self.page.get_by_test_id("next").click()
            clicks += 1
            # read right after the click, as Next draws its stop at once (the page's show() renders before returning):
            value: T = read()
            if value != seen[-1]:
                seen.append(value)
        return seen

    def test_next_shows_each_semi_join_done_and_the_tuples_left_after_it(self) -> None:
        """Next leads from the start to the end through the six semi-joins, done one after the other in their order,
        and shows the tuples left at the start and after each: 18, 17, 15, 13, 12, 10 and 8.
        """
        # at the start, no semi-join is done and all 18 tuples are left:
        expect(self.page.get_by_test_id("stage")).to_have_attribute(
            "data-tuples-left", "18"
        )

        # Next leads to the end; the counts after each click are noted when they differ from those before:
        self.assertEqual(self.COUNTS, self.seen_at_each_stop(self.counts))
        self.assert_no_errors(self.opened)

    def test_next_stops_in_every_step(self) -> None:
        """Next leads from the start to the end through the 19 steps of the film in their order and stops in each.

        A step that began and ended between two stops would never be shown to a reader who clicks Next.
        """
        stage = self.page.get_by_test_id("stage")

        # at the start, the page shows step 1:
        expect(stage).to_have_attribute("data-scene", "1")

        # Next leads to the end; the step after each click is noted when it differs from the one before:
        steps: list[str] = self.seen_at_each_stop(
            lambda: stage.get_attribute("data-scene") or ""
        )
        self.assertEqual([str(n) for n in range(1, 20)], steps)
        self.assert_no_errors(self.opened)

    def test_top_down_starts_with_three_semi_joins_done(self) -> None:
        """The button of part 3, "Top-down", jumps to the start of semi-join 4 (its first step, the 12th of the film),
        with semi-joins 1 to 3 done and 13 tuples left.
        """
        play = self.page.get_by_test_id("play")

        # the button jumps to the start of part 3 and plays; Play pauses at once, long before step 13 begins (about
        # 6.7 s later, just after the camera starts to close in) and long before semi-join 4 is done (about 12 s later):
        self.page.get_by_test_id("chapter-3").click()
        play.click()
        expect(play).to_have_attribute("data-state", "paused")
        expect(self.page.get_by_test_id("stage")).to_have_attribute("data-scene", "12")

        # semi-joins 1 to 3 are done, semi-join 4 is under way, and 13 tuples are left:
        self.assertEqual((3, 13), self.counts())
        expect(self.page.get_by_test_id("semi-join-4")).to_have_attribute(
            "data-state", "now"
        )
        self.assert_no_errors(self.opened)

    def test_the_robot_carries_the_key_column_of_each_semi_join_and_leaves(
        self,
    ) -> None:
        """From the start of the film to its end, the robot carries a key column, leaves and is gone again six times,
        the k-th time while semi-join k is under way; it is gone at the start, between two semi-joins and at the end.
        Carrying, it looks half towards where it walks and turns softly where it changes sides; leaving, it turns its
        back to us the short way round.

        A semi-join begins (its compared columns light up) shortly before the robot comes with its key column, and is
        done (its rows go dark) after the robot has gone. The robot leaves for 1.7 s: once the camera starts to close
        in, it walks off and fades. The stage shows what it does in ``data-robot`` and how far it is turned about its
        upright axis in ``data-robot-turn`` (rad, 0: facing the camera, also while it is gone).
        """
        page: Page = self.page
        scrub = page.get_by_test_id("scrub")

        # the slider's step (s): the film's length, as the clock shows it (e.g. "0:00 / 2:14"), over its 1000 steps:
        minutes, seconds = (
            page.get_by_test_id("clock").inner_text().split(" / ")[1].split(":")
        )
        step: float = (60 * int(minutes) + int(seconds)) / 1000

        # once the page has set up its controls, the slider takes each of its values, which the page draws at once on
        # the input event, as when a reader drags it; in one call into the browser, so the 1001 values take seconds.
        # At each value, what the robot does, the semi-join under way (0 for none) and the robot's turn are noted.
        # Every 25 values and twice at the end, the sweep waits for an animation frame, as a reader's drag lets the
        # page draw while it moves: else the drawings of all 1001 values pile up in the browser and, on a slow machine
        # with WebGL in software, keep the next test's page from loading in time:
        expect(scrub).to_be_enabled()
        samples: list[tuple[str, int, float]] = [
            (robot, now, float(turn))
            for robot, now, turn in page.evaluate(
                """async ([scrub, stage, semiJoins]) => {
                    const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()));
                    const samples = [];
                    for (let value = 0; value <= 1000; value += 1) {
                        scrub.value = String(value);
                        scrub.dispatchEvent(new Event("input", { bubbles: true }));
                        const now = semiJoins.findIndex((item) => item.dataset.state === "now") + 1;
                        samples.push([stage.dataset.robot, now, stage.dataset.robotTurn]);
                        if ((value + 1) % 25 === 0) await frame();
                    }
                    await frame();
                    await frame();
                    return samples;
                }""",
                [
                    scrub.element_handle(),
                    page.get_by_test_id("stage").element_handle(),
                    [
                        page.get_by_test_id(f"semi-join-{k}").element_handle()
                        for k in range(1, 7)
                    ],
                ],
            )
        ]
        # the values in a row with the same robot state and semi-join form a run, with the robot's turn at each value:
        runs: list[tuple[str, int, list[float]]] = [
            (robot, now, [turn for _, _, turn in run])
            for (robot, now), run in groupby(samples, key=lambda sample: sample[:2])
        ]

        # gone at the start; for each semi-join k: it begins, the robot carries its key column, leaves and is gone,
        # and the semi-join is done; gone at the end. Each state is seen at one value at least, so it lasts a step or
        # more, and a reader who drags the slider sees it:
        expected: list[tuple[str, int]] = [("gone", 0)]
        for k in range(1, 7):
            expected += [
                ("gone", k),
                ("carrying", k),
                ("leaving", k),
                ("gone", k),
                ("gone", 0),
            ]
        self.assertEqual(expected, [(robot, now) for robot, now, _ in runs])

        # at least once (in semi-join 2), the robot changes sides while it carries, from a negative turn to a positive
        # one, so that the check of a soft turn below has a turn to check:
        self.assertTrue(
            any(
                min(turns) < 0 < max(turns)
                for robot, _, turns in runs
                if robot == "carrying"
            ),
            "the robot never changes sides while it carries",
        )

        def side(turn: float) -> int:
            """Returns 1 for a positive turn (the robot's front towards the right of the picture), -1 for a negative one
            (towards the left) and 0 for none."""
            return (turn > 0) - (turn < 0)

        # the robot's turn where it stops carrying, for each semi-join (noted below, before it leaves):
        carried_until: dict[int, float] = {}
        for robot, now, turns in runs:
            # carrying, it is turned by 0.6 towards where it walks, starting to the side the table gives; where it
            # changes sides at the end of an edge, it turns softly, by at most 0.8 rad from one step to the next (about
            # 0.5 at the most; a snap would be 1.2). On the upright R–T edge (semi-joins 3 and 4), it stays half
            # turned, not facing the camera:
            if robot == "carrying":
                self.assertEqual(
                    self.ROBOT_SIDES[now][0],
                    side(turns[0]),
                    f"the robot of semi-join {now} starts to carry turned the wrong way: {turns}",
                )
                self.assertLessEqual(
                    max((abs(b - a) for a, b in zip(turns, turns[1:])), default=0.0),
                    0.8,
                    f"the robot of semi-join {now} snaps round: {turns}",
                )
                if now in (3, 4):
                    self.assertGreaterEqual(
                        min(abs(turn) for turn in turns),
                        0.5,
                        f"the robot of semi-join {now} faces the camera: {turns}",
                    )
                carried_until[now] = turns[-1]

            # leaving, it takes 1.7 s, to within a step, and turns its back to us the short way round: by less than
            # half a turn from where it stopped carrying, to π − 0.7 to the side the table gives (its front away and
            # outwards), so that "ExplainDB" on its back shows:
            if robot == "leaving":
                self.assertAlmostEqual(
                    self.ROBOT_LEAVES,
                    len(turns) * step,
                    delta=step,
                    msg=f"the robot of semi-join {now} leaves for {len(turns)} steps",
                )
                self.assertLess(
                    abs(turns[-1] - carried_until[now]),
                    math.pi,
                    f"the robot of semi-join {now} spins from {carried_until[now]}: {turns}",
                )
                self.assertAlmostEqual(
                    self.ROBOT_SIDES[now][1] * (math.pi - 0.7),
                    turns[-1],
                    delta=0.01,
                    msg=f"the robot of semi-join {now} does not turn its back: {turns}",
                )
        self.assert_no_errors(self.opened)

    def test_the_end_card_leaves_the_tree_free(self) -> None:
        """The card at the end leaves the whole tree free, from U′'s bitmap on the left to S′'s on the right, on
        windows from 1920 × 1080 down to 700 px wide (and up to about 1.75 times as tall as wide).

        The camera's position at the end follows the card's width: at a fixed x, the card would cover S′ on windows
        narrower than about 1165 px. On a phone the card cannot be cleared, so phones are not checked.
        """
        stage = self.page.get_by_test_id("stage")
        scrub = self.page.get_by_test_id("scrub")
        legend = self.page.get_by_test_id("legend")

        # from a big screen down to a tablet held upright, a narrow window and a tall one (about 1.75 times as tall as
        # wide); each size differs from the one before
        # (the first from the browser's 1280 × 720), so that the window fires a resize event for each:
        for width, height in [
            (1920, 1080),
            (1280, 720),
            (1024, 768),
            (820, 1180),
            (700, 900),
            (700, 1220),
        ]:
            with self.subTest(width=width, height=height):
                # the window takes the size; the wait lasts until it has fired its resize event, on which the page
                # fits the camera to the window and notes where the card begins (a jump to the end before that would
                # be drawn for the size before):
                self.page.evaluate("""() => {
                        window.resized = false;
                        addEventListener("resize", () => { window.resized = true; }, { once: true });
                    }""")
                self.page.set_viewport_size({"width": width, "height": height})
                self.page.wait_for_function("() => window.resized")

                # the slider jumps to the end, which the page draws at once, and the card shows:
                scrub.fill("1000")
                expect(legend).to_have_css("opacity", "1")

                # U′'s bitmap begins in the window, and S′'s ends left of the card:
                box: FloatRect | None = legend.bounding_box()
                if box is None:
                    self.fail("the card has no box")
                left: int = int(stage.get_attribute("data-tree-left") or "")
                right: int = int(stage.get_attribute("data-tree-right") or "")
                self.assertLessEqual(
                    0, left, f"U′'s bitmap begins at {left} px, left of the window"
                )
                self.assertLess(
                    right,
                    box["x"],
                    f"S′'s bitmap ends at {right} px, under the card, which begins at {box['x']} px",
                )
        self.assert_no_errors(self.opened)

    def test_the_end_card_names_the_voice(self) -> None:
        """The last line of the end card, the credit, ends by saying that the voice is synthetic and naming its model
        and voice."""
        voice_named: str = "The voice is synthetic: Ming-3.0 TTS, voice UK_George."

        # at the end, the end card shows, and its credit ends with the voice's (read as shown, so that the line breaks
        # of the HTML count as spaces):
        self.page.get_by_test_id("scrub").fill("1000")
        expect(self.page.get_by_test_id("legend")).to_have_css("opacity", "1")
        expect(self.page.get_by_test_id("credit")).to_have_text(
            re.compile(re.escape(voice_named) + "$"), use_inner_text=True
        )
        self.assert_no_errors(self.opened)

    def test_the_sound_hint_gives_way_to_the_end_card(self) -> None:
        """With sound off, the hint "Switch on audio (M)" fades out while the end card fades in, which it would cover on
        a narrow window, and shows again before it."""
        hint = self.page.get_by_test_id("sound-hint")
        scrub = self.page.get_by_test_id("scrub")

        # at the start, the hint shows in full:
        expect(hint).to_have_text("Switch on audio (M)")
        expect(hint).to_have_css("opacity", "1")

        # at the end, where the end card shows, the hint has faded out:
        scrub.fill("1000")
        expect(self.page.get_by_test_id("legend")).to_have_css("opacity", "1")
        expect(hint).to_have_css("opacity", "0")

        # back at the start, it shows again:
        scrub.fill("0")
        expect(hint).to_have_css("opacity", "1")
        self.assert_no_errors(self.opened)

    def test_the_sound_hint_sits_above_the_narration_and_leaves_it_the_list_and_the_controls_free(
        self,
    ) -> None:
        """The hint sits at the bottom right, just above the narration, its right edge where the controls end, and
        covers neither the narration's text, nor the list of the semi-joins, nor a button of the controls: on a phone
        held upright (360 × 800 px) and sideways (800 × 360 and 844 × 390 px), on a window 500 px tall (900 × 500 px),
        on a tablet held upright (820 × 1180 px) and on a laptop (1280 × 720 px); neither "Switch on audio (M)" with
        sound off nor the longer "Click or press a key for sound" while the browser holds the voice back.

        The place is the decision's (038): at the bottom, above the controls on the right, as on the row/column page;
        at the top, it would cover the root R of the tree. On a window up to 500 px tall, the list shows its two
        passes side by side, so that it ends above the hint. Checked while the second caption shows, which wraps to
        several lines on a phone, so that the narration reaches up towards the hint.
        """
        page: Page = self.page
        text = page.get_by_test_id("nar-text")
        hint = page.get_by_test_id("sound-hint")
        play = page.get_by_test_id("play")
        scrub = page.get_by_test_id("scrub")

        def box_of(test_id: str) -> FloatRect:
            """Returns the box of the element with the given test id, and fails if it has none (e.g. is hidden)."""
            box: FloatRect | None = page.get_by_test_id(test_id).bounding_box()
            if box is None:
                self.fail(f"{test_id} has no box")
            return box

        def apart(one: FloatRect, other: FloatRect) -> bool:
            """Returns whether two boxes do not overlap (they may touch)."""
            return (
                one["x"] >= other["x"] + other["width"]
                or other["x"] >= one["x"] + one["width"]
                or one["y"] >= other["y"] + other["height"]
                or other["y"] >= one["y"] + one["height"]
            )

        def expect_hint_in_place_and_apart(hint_text: str) -> None:
            """On each of the six screens, expects the second caption and the hint to show, the hint in its place,
            and the hint's box to overlap neither the caption's, nor the list's, nor a button's.
            """
            for width, height in [
                (360, 800),
                (800, 360),
                (844, 390),
                (900, 500),
                (820, 1180),
                (1280, 720),
            ]:
                with self.subTest(width=width, height=height, hint=hint_text):
                    # the window takes the size, which the page lays out at once:
                    page.set_viewport_size({"width": width, "height": height})
                    expect(text).to_have_text(self.SECOND_CAPTION)
                    expect(hint).to_have_text(hint_text)
                    hint_box: FloatRect = box_of("sound-hint")

                    # the hint sits 8 px above the narration, which begins at the top of the bottom bar (the CSS puts
                    # the hint's bottom edge 8 px above the bar's top), and its right edge is the bar's, where the
                    # controls end:
                    narration_box: FloatRect = box_of("narration")
                    transport_box: FloatRect = box_of("transport")
                    self.assertAlmostEqual(
                        8,
                        narration_box["y"] - (hint_box["y"] + hint_box["height"]),
                        delta=1,
                        msg=f"the hint {hint_box} is not just above the narration {narration_box}",
                    )
                    self.assertAlmostEqual(
                        transport_box["x"] + transport_box["width"],
                        hint_box["x"] + hint_box["width"],
                        delta=1,
                        msg=f"the hint {hint_box} does not end where the controls {transport_box} end",
                    )

                    # the hint's box lies apart from the caption's, the list's and each button's:
                    for test_id in ["nar-text", "semi-joins", *self.TRANSPORT_BUTTONS]:
                        box: FloatRect = box_of(test_id)
                        self.assertTrue(
                            apart(hint_box, box),
                            f"the hint {hint_box} covers {test_id} {box}",
                        )

        # with sound off, Next stops where the first caption and then the second one are shown in full (the slider's
        # value there is noted); the hint "Switch on audio (M)" shows:
        page.get_by_test_id("next").click()
        page.get_by_test_id("next").click()
        shown_in_full: str = scrub.input_value()
        self.expect_sound(page, on=False)
        expect_hint_in_place_and_apart("Switch on audio (M)")

        # sound on, and ← stops where the second caption begins; Play while the browser refuses sound: the voice is
        # held back, and the hint "Click or press a key for sound" shows while the film plays on in the second caption
        # (which lasts about 7.6 s):
        page.get_by_test_id("sound").click()
        self.expect_sound(page, on=True)
        page.keyboard.press("ArrowLeft")
        expect(text).to_have_text(self.SECOND_CAPTION)
        self.play_until_held_back(page)

        # the slider moves back to where the second caption was shown in full, which pauses the film, so that it does
        # not play past the caption while the window changes size six times (on a slow machine, that takes a while).
        # Moving the slider is no click or key press on the page, so the voice stays held back:
        scrub.fill(shown_in_full)
        expect(play).to_have_attribute("data-state", "paused")
        self.expect_sound(page, on=True, held_back=True)
        expect_hint_in_place_and_apart("Click or press a key for sound")
        self.assert_no_errors(self.opened)

    def test_the_page_stops_if_a_clip_of_its_voice_does_not_belong_to_its_caption(
        self,
    ) -> None:
        """At start-up, the page checks that each clip of its voice belongs to its caption: a copy whose first clip was
        made for another text stops with an error that says so, whereas the page itself passes the check.

        The clips are matched to the captions by their order (decision 038), so a voice built for other captions would
        otherwise speak the wrong words; with the error, the page fails its tests instead.
        """
        # a copy of the page, in a folder of its own that is removed after the test, whose voice notes another text
        # for its first clip than the first caption's:
        html: str = YANNAKAKIS_PAGE.read_text(encoding="utf-8")
        first_clip: str = 'const VOICE = [{"text": "'
        self.assertEqual(1, html.count(first_clip), "the page's voice was not found")
        # enterContext removes the folder with addCleanup, which runs after the copy's browser context is closed (the
        # cleanups run in reverse order); pylint does not know that, so it asks for a with block:
        # pylint: disable-next=consider-using-with
        folder: str = self.enterContext(tempfile.TemporaryDirectory())
        changed_page: Path = Path(folder) / YANNAKAKIS_PAGE.name
        changed_page.write_text(
            html.replace(first_clip, first_clip + "Once more: "), encoding="utf-8"
        )

        # the copy throws the error once it has loaded its fonts, which may be after open_page has returned; the error
        # is recorded as soon as Playwright has handled it (at most 5 s). The copy requests nothing but local files:
        opened: OpenedPage = self.open_page(changed_page)
        error: str = (
            "uncaught: the voice does not match caption 1: rebuild it with voice.py"
        )
        for _ in range(50):
            if error in opened.errors:
                break
            opened.page.wait_for_timeout(100)
        self.assertIn(error, opened.errors)
        self.assertEqual([], opened.outside_requests)

        # the copy stops there: it never sets up its controls, so Play stays disabled, as the HTML writes it:
        expect(opened.page.get_by_test_id("play")).to_be_disabled()

        # the page itself passes the check: it sets up its controls, which comes after the check, without an error:
        expect(self.page.get_by_test_id("play")).to_be_enabled()
        self.assert_no_errors(self.opened)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class BTreePageTest(_PageTestCase):
    """Checks that the B-tree page shows the trees of the repository's B+-tree code, BPlusTree(8, 16).

    The page builds its start tree from START, inserts the three keys of PUTS with insertTree, its JavaScript copy of
    BPlusTree.put, and writes the start tree and the tree after each put into data-trees of its stage.
    test_b_tree_page_data.py checks the same EXPECTED_DIGESTS (b_tree_page_trees.py) against the real BPlusTree.
    It also writes, for the same four trees, the place on the rails of each section (leaf), in key order, into
    data-slots; the places are numbered from the left, one section wide. For the point query and the range query of the
    film it writes the nodes on the way and the keys found into data-point-path and data-range-hits, which
    test_b_tree_page_data.py checks against the real BPlusTree as well.
    """

    PAGE: Path | None = B_TREE_PAGE

    def setUp(self) -> None:
        """Opens the page, paused at its start, and reads the trees it made and the places of their sections.

        Fails at once, naming the page's errors, if the page stops at start-up (e.g. a check of its numbers fails),
        instead of letting every test wait in vain for what the page never sets up.
        """
        self.opened: OpenedPage = self.open_page(B_TREE_PAGE)
        self.page: Page = self.opened.page
        stage = self.page.get_by_test_id("stage")

        # the script sets up the controls at the end of its start-up, after its checks (it waits up to 2.5 s for its
        # fonts first); a check that fails throws an error instead, which is recorded as soon as Playwright has
        # handled it:
        play = self.page.get_by_test_id("play")
        for _ in range(FILM_TIMEOUT // 100):
            if self.opened.errors or play.is_enabled():
                break
            self.page.wait_for_timeout(100)
        self.assert_no_errors(self.opened)
        expect(play).to_be_enabled()

        # the script writes the trees and the places at start-up, before it sets up the controls:
        expect(stage).to_have_attribute("data-trees", re.compile(r"^\["))
        # the start tree and the trees after the three puts, as plain data (see Tree):
        self.trees: list[Tree] = json.loads(stage.get_attribute("data-trees") or "")
        expect(stage).to_have_attribute("data-slots", re.compile(r"^\["))
        # per tree, the places of its sections (leaves) in key order, 0 the leftmost:
        self.slots: list[list[int]] = json.loads(
            stage.get_attribute("data-slots") or ""
        )

    def test_at_the_start_the_places_rise_with_the_keys(self) -> None:
        """At the start, the sections stand on the rails in key order: each one further right than the one before.

        Fails if the start layout puts a section left of a section with smaller keys, or two on one place.
        """
        start: list[int] = self.slots[0]
        self.assertGreater(len(start), 1)
        self.assertEqual([], [(a, b) for a, b in zip(start, start[1:]) if not a < b])

    def test_no_section_ever_changes_its_place(self) -> None:
        """From one tree to the next, every section that was there stays at its place, and the sections keep their
        order; the only change is the new section of a leaf split.

        Fails if a section moves along the rails during an insert (e.g. pushed aside to make room for a new one).
        """
        # the four trees: the start tree and the tree after each put:
        self.assertEqual(len(self.trees), len(self.slots))
        for before, after in zip(self.slots, self.slots[1:]):
            self.assertEqual(before, sections_that_were_there(before, after))

    def test_a_new_section_stands_right_next_to_the_section_it_split_from(
        self,
    ) -> None:
        """The first put fits into its leaf; each of the two others splits a leaf, and the new section (the right
        half, next in key order) stands on the place right after the section it split from.

        Fails if a leaf split puts its new section somewhere else, e.g. into a free place further away.
        """
        new_sections: list[list[int]] = []
        for put, (before, after) in enumerate(zip(self.slots, self.slots[1:]), 1):
            new: list[int] = [i for i, place in enumerate(after) if place not in before]
            new_sections.append(new)

            # the section it split from is the one before it in key order:
            for i in new:
                self.assertEqual(
                    after[i - 1] + 1,
                    after[i],
                    f"put {put}: its new section is not right after the one it split from",
                )

        # one new section in each of the last two puts:
        self.assertEqual([0, 1, 1], [len(new) for new in new_sections])

    def test_no_place_is_ever_held_by_two_sections(self) -> None:
        """In each of the four trees, no two sections stand on the same place.

        Fails if a leaf split puts its new section onto a place that a section already holds.
        """
        for places in self.slots:
            self.assertEqual(len(places), len(set(places)))

    def test_the_page_makes_the_trees_of_the_code(self) -> None:
        """The page's start tree and its tree after each of the three puts are those that the code makes.

        Fails if insertTree splits a node otherwise than BPlusTree.put (e.g. another key moves up), or if the page
        builds other keys of the inner nodes from START than the least key of each subtree to their right.
        """
        self.assertEqual(
            EXPECTED_DIGESTS, digests(self.trees), digest_mismatches(self.trees)
        )
        self.assert_no_errors(self.opened)

    def test_the_queries_take_the_way_and_find_the_keys_of_the_code(self) -> None:
        """The point query passes through the nodes that the code's get visits on its way to 7013, from the root
        down to the section, and the range query finds the keys that the code's get_all_in_range finds, in the
        sections that it scans (test_b_tree_page_data.py checks these against BPlusTree).

        Fails if the page's point query takes another hole in some room than the code (e.g. when the descent or
        POINT_KEY changes), or if its range query starts or stops a section too early or too late, or with another
        range.
        """
        stage = self.page.get_by_test_id("stage")
        point_path: list[list[int]] = json.loads(
            stage.get_attribute("data-point-path") or ""
        )
        range_hits: list[int] = json.loads(stage.get_attribute("data-range-hits") or "")
        range_leaves: list[int] = json.loads(
            stage.get_attribute("data-range-leaves") or ""
        )

        # the keys of each node on the way, from the root down, the keys found, and the sections read for them, by
        # their least keys:
        self.assertEqual(EXPECTED_POINT_PATH, point_path)
        self.assertEqual(EXPECTED_RANGE_HITS, range_hits)
        self.assertEqual(EXPECTED_RANGE_LEAVES, range_leaves)

    def test_each_put_adds_its_key_and_the_last_one_splits_the_root(self) -> None:
        """Each of the three puts adds its key to the tree; the last one splits the root, so the tree grows from 4
        levels to 5 under a new root with one key, and the stage shows height 4 at the start, still 4 when the last
        put begins, and 5 at the end.

        Spells out what the digests check; also fails if the height on the stage does not follow the tree on screen
        (e.g. stays 4 after the root split, or shows 5 as soon as the last put begins, long before the new root
        appears).
        """
        _, puts = read_start_and_puts()

        # the start tree and the tree after each put:
        self.assertEqual(4, len(self.trees))

        # each put adds its key and no other, and the leaves keep their keys in ascending order:
        for before, key, after in zip(self.trees, puts, self.trees[1:]):
            self.assertEqual(sorted([*keys_of(before), key]), keys_of(after))

        # only the last put adds a level; the new root holds the one key that moved up from the old root:
        self.assertEqual([4, 4, 4, 5], [height(tree) for tree in self.trees])
        self.assertEqual(1, len(self.trees[-1]["keys"]))

        # the stage shows the height of the tree on screen, at the start and at the end of the film:
        stage = self.page.get_by_test_id("stage")
        expect(stage).to_have_attribute("data-height", "4")

        # part 7 begins with the last put, the one that splits the root; the new root appears only about a minute
        # later, so the tree on screen still has height 4:
        self.page.get_by_test_id("chapter-7").click()
        expect(self.page.get_by_test_id("operation")).to_have_text("insert(7060)")
        expect(stage).to_have_attribute("data-height", "4")

        self.page.get_by_test_id("scrub").fill("1000")
        expect(self.page.get_by_test_id("play")).to_have_attribute(
            "data-state", "ended"
        )
        expect(stage).to_have_attribute("data-height", "5")
        self.assert_no_errors(self.opened)

    def test_each_part_begins_by_naming_itself_and_no_room_has_a_letter_name(
        self,
    ) -> None:
        """The first caption of each part names the part as its button does (e.g. "Let's run a point query on key
        7013." for "3 · Point query"), and no caption or step in the header calls a room by a letter (e.g. "room R",
        "Q's right half"), which the picture does not show.

        Fails if a part begins with a caption that does not say what the part shows (e.g. "We are looking for key
        7013."), or if a caption or a step's title names a room or node by a single capital letter.
        """
        play = self.page.get_by_test_id("play")
        first_captions: dict[str, str] = {}
        lettered: list[str] = []

        # Next from stop to stop up to the end; at each stop, the part on screen, the step and the caption:
        clicks: int = 0
        while play.get_attribute("data-state") != "ended":
            self.assertLess(clicks, MAX_NEXT_CLICKS, "Next did not reach the end")
            self.page.get_by_test_id("next").click()
            clicks += 1
            part: str = (
                self.page.locator(
                    '[data-testid^="chapter-"][aria-current="true"]'
                ).text_content()
                or ""
            )
            step: str = self.page.get_by_test_id("step-name").text_content() or ""
            caption: str = self.page.get_by_test_id("nar-text").text_content() or ""
            first_captions.setdefault(part, caption)
            lettered.extend(
                text for text in (step, caption) if LETTER_NAME.search(text)
            )

        # no step or caption names a room by a letter:
        self.assertEqual([], lettered)

        # each of the seven parts begins with a caption that has every word of the part's name, e.g. "point" and
        # "query" for "3 · Point query" ("split" also in "splits"):
        self.assertEqual(7, len(first_captions))
        for button, caption in first_captions.items():
            name: str = button.split("·")[-1].strip().lower()
            for word in name.split():
                self.assertIn(word, caption.lower(), f"part {button!r}")
        self.assert_no_errors(self.opened)

    def load_copy(self, changes: dict[str, str]) -> None:
        """Loads a changed copy of the page into the page opened in setUp, with the errors recorded so far cleared.

        open_page opens only the page itself, as the class has a PAGE; set_content puts the copy into the same tab, so
        that its errors and outside requests are recorded as for the page. The first page's script (and that of an
        earlier copy) keeps running in the same window: its closures still hold its own elements and its own film,
        which are no longer shown and which it draws only on request (it is paused, and nothing asks it), so it can
        neither change the copy nor record an error for it.

        @param changes: each text to change (found in the page, else the test fails) and what it becomes; every place
            of the text is changed, e.g. a caption and the text noted with its clip alike (plain text with spaces,
            never inside the clips' base64 data, which has none)
        """
        html: str = B_TREE_PAGE.read_text(encoding="utf-8")
        for old, new in changes.items():
            self.assertIn(old, html, "the text to change was not found")
            html = html.replace(old, new)
        self.opened.errors.clear()
        self.page.set_content(html)

    def test_the_page_stops_if_a_caption_no_longer_says_what_the_page_gives(
        self,
    ) -> None:
        """At start-up, the page checks that its captions name the numbers that its constants and its tree give: a copy
        with one changed number in a caption stops with an error that names the words it misses and never sets up its
        controls; one copy for each kind of number: a key moved up by a split, the point query's key (POINT_KEY), the
        range query's range (RANGE), a key the film inserts (PUTS) and the number of nodes the point query passes
        through. The page itself passes the check (setUp).

        The captions are spoken by recorded clips, so their numbers are typed by hand; with the check, the page fails
        its tests once its constants or its tree no longer give them, instead of saying something else than it shows.
        """
        # (kind, the caption's words, the same with another number, the words the check misses):
        cases: list[tuple[str, str, str, str]] = [
            ("a split", "6961 goes into", "6962 goes into", "6961 goes into"),
            (
                "POINT_KEY",
                "point query on key 7013.",
                "point query on key 7014.",
                "point query on key 7013.",
            ),
            (
                "RANGE",
                "range query from 6267 to 6306:",
                "range query from 6268 to 6306:",
                "range query from 6267 to 6306:",
            ),
            (
                "PUTS",
                "Let's insert key 6284.",
                "Let's insert key 6285.",
                "Let's insert key 6284.",
            ),
            (
                "the height",
                "looking into four nodes.",
                "looking into five nodes.",
                "7013, found by looking into four nodes.",
            ),
        ]
        for kind, words, changed, missed in cases:
            with self.subTest(kind=kind):
                self.load_copy({words: changed})

                # the copy throws the error once it has loaded its fonts; the error is recorded as soon as Playwright
                # has handled it:
                error: str = f'uncaught: no caption says "{missed}"'
                for _ in range(FILM_TIMEOUT // 100):
                    if error in self.opened.errors:
                        break
                    self.page.wait_for_timeout(100)
                self.assertEqual([error], self.opened.errors)
                self.assertEqual([], self.opened.outside_requests)

                # the copy stops there: it never sets up its controls, so Play stays disabled, as the HTML writes it:
                expect(self.page.get_by_test_id("play")).to_be_disabled()

    def test_a_range_from_between_two_sections_starts_where_the_robot_lands(
        self,
    ) -> None:
        """On a copy whose range query begins at 6270, which falls between two sections (6269 ends one, 6271 begins
        the next), the range query reads the sections that the code's get_all_in_range scans for that range
        (EXPECTED_BETWEEN_LEAVES, which test_b_tree_page_data.py checks against BPlusTree): from the one the robot's way
        down lands in, before the gap, along the chains to the one with the first key after the range.

        Fails if the page starts at the first section whose last key is in the range or after it, which skips the
        section the robot lands in.
        """
        point_key, (least, greatest) = read_queries()
        new_least, new_greatest = BETWEEN_LEAVES_RANGE

        # a copy with the range from 6270, its caption changed alike, so that the page's check of the captions passes:
        self.load_copy(
            {
                f"const POINT_KEY = {point_key}, RANGE = [{least}, {greatest}];": (
                    f"const POINT_KEY = {point_key}, RANGE = [{new_least}, {new_greatest}];"
                ),
                f"range query from {least} to {greatest}": (
                    f"range query from {new_least} to {new_greatest}"
                ),
            }
        )
        expect(self.page.get_by_test_id("play")).to_be_enabled(timeout=FILM_TIMEOUT)
        self.assert_no_errors(self.opened)

        # the sections it reads, by their least keys:
        leaves: list[int] = json.loads(
            self.page.get_by_test_id("stage").get_attribute("data-range-leaves") or ""
        )
        self.assertEqual(EXPECTED_BETWEEN_LEAVES, leaves)

    def test_the_end_card_names_the_voice(self) -> None:
        """The last line of the end card, the credit, ends by saying that the voice is synthetic and naming its model
        and voice."""
        voice_named: str = "The voice is synthetic: Ming-3.0 TTS, voice UK_George."

        # at the end, the end card shows, and its credit ends with the voice's (read as shown, so that the line breaks
        # of the HTML count as spaces):
        self.page.get_by_test_id("scrub").fill("1000")
        expect(self.page.get_by_test_id("legend")).to_have_css("opacity", "1")
        expect(self.page.get_by_test_id("credit")).to_have_text(
            re.compile(re.escape(voice_named) + "$"), use_inner_text=True
        )
        self.assert_no_errors(self.opened)

    def test_the_sound_hint_gives_way_to_the_end_card(self) -> None:
        """With sound off, the hint "Switch on audio (M)" fades out while the end card fades in, which it would cover on
        a narrow window, and shows again before it."""
        hint = self.page.get_by_test_id("sound-hint")
        scrub = self.page.get_by_test_id("scrub")

        # at the start, the hint shows in full:
        expect(hint).to_have_text("Switch on audio (M)")
        expect(hint).to_have_css("opacity", "1")

        # at the end, where the end card shows, the hint has faded out:
        scrub.fill("1000")
        expect(self.page.get_by_test_id("legend")).to_have_css("opacity", "1")
        expect(hint).to_have_css("opacity", "0")

        # back at the start, it shows again:
        scrub.fill("0")
        expect(hint).to_have_css("opacity", "1")
        self.assert_no_errors(self.opened)

    def test_the_texture_caches_stay_within_their_limits(self) -> None:
        """Jumping with the slider to 200 moments all through the film, back and forth, the page draws more pictures
        of the sections' fronts and of the rooms' key rows than its caches may keep, yet neither cache ever holds more
        than its limit (the pictures in use included), and the fronts' cache reaches its limit: the caches free old
        pictures.

        Fails if a cache stops freeing pictures (e.g. it gives up at the oldest one when that one is still in use), if
        its limit grows (a front takes about 0.8 MB on the GPU, a key row about 0.6 MB), or if the page stops writing
        the sizes.
        """
        stage = self.page.get_by_test_id("stage")
        limits: dict[str, int] = json.loads(
            stage.get_attribute("data-cache-limits") or ""
        )

        # the limits are small: 60 fronts, and a key row per room (68 in the film) and a few more:
        self.assertEqual(60, limits["fronts"])
        self.assertLessEqual(limits["rows"], 80)

        # the slider jumps forwards to every tenth step, then back to the steps between; after each jump, the page's
        # notes are read: how many fronts and key rows each cache holds and how many it has drawn so far (null where
        # the page has written nothing yet; at the start, it has drawn no front, only each room's key row):
        notes: list[list[str | None]] = self.page.get_by_test_id("scrub").evaluate(
            """scrub => {
                const stage = document.querySelector('[data-testid="stage"]'), notes = [];
                const steps = [...Array(100).keys()];
                for (const value of [...steps.map((i) => i * 10), ...steps.map((i) => 995 - i * 10)]) {
                    scrub.value = String(value);
                    scrub.dispatchEvent(new Event('input', { bubbles: true }));
                    const { cacheFronts, cacheRows, cacheMadeFronts, cacheMadeRows } = stage.dataset;
                    notes.push([cacheFronts, cacheRows, cacheMadeFronts, cacheMadeRows].map((value) => value ?? null));
                }
                return notes;
            }"""
        )
        self.assertEqual(200, len(notes))

        # the key rows' cache holds rows from the start on, at least one per room, never more than its limit:
        self.assertNotIn(None, [note[1] for note in notes])
        rows: list[int] = [int(note[1] or "") for note in notes]
        self.assertGreaterEqual(min(rows), 1)
        self.assertLessEqual(max(rows), limits["rows"])

        # the fronts' cache, once the film shows fronts, never holds more than its limit, and is full at some moment:
        fronts: list[int] = [int(note[0]) for note in notes if note[0] is not None]
        self.assertGreater(len(fronts), 0)
        self.assertLessEqual(max(fronts), limits["fronts"])
        self.assertEqual(limits["fronts"], max(fronts))

        # more pictures were drawn than each cache may keep, so the caches have freed some:
        self.assertNotIn(None, notes[-1])
        made_fronts, made_rows = int(notes[-1][2] or ""), int(notes[-1][3] or "")
        self.assertGreater(made_fronts, limits["fronts"])
        self.assertGreater(made_rows, limits["rows"])
        self.assert_no_errors(self.opened)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class ElasticityPageTest(_PageTestCase):
    """Checks the controls of the elasticity page: the stops, the models, the sizes and the results of the day."""

    PAGE: Path | None = ELASTICITY_PAGE

    MODELS: list[str] = ["onprem", "hosting", "iaas", "paas", "planned", "saas"]
    # the models whose servers have a fixed size, chosen with the size buttons:
    MODELS_WITH_SIZE: set[str] = {"onprem", "hosting"}
    SIZES: list[str] = ["normal", "peak"]
    # a minute of the day after midnight, as the stage shows it in data-minute:
    LATER_MINUTE: re.Pattern[str] = re.compile(r"^[1-9]\d*$")

    def test_next_shows_the_minute_of_the_next_stop(self) -> None:
        """Next jumps from minute 0 to the minute of the next stop, which the narration names."""
        opened: OpenedPage = self.open_page(ELASTICITY_PAGE)
        page: Page = opened.page
        stage = page.get_by_test_id("stage")
        expect(stage).to_have_attribute("data-minute", "0")

        # Next moves on to the minute of the stop it narrates:
        page.get_by_test_id("next").click()
        expect(stage).to_have_attribute("data-minute", self.LATER_MINUTE)
        expect(page.get_by_test_id("narration")).to_have_attribute(
            "data-stop-minute", stage.get_attribute("data-minute") or ""
        )
        self.assert_no_errors(opened)

    def test_switching_the_model_keeps_the_minute(self) -> None:
        """Choosing another model while paused shows the new model at the same minute, still paused."""
        opened: OpenedPage = self.open_page(ELASTICITY_PAGE)
        page: Page = opened.page

        # Next moves on to a later minute of the day:
        stage = page.get_by_test_id("stage")
        page.get_by_test_id("next").click()
        expect(stage).to_have_attribute("data-minute", self.LATER_MINUTE)
        minute: str = stage.get_attribute("data-minute") or ""

        # PaaS is chosen, at the same minute:
        paas = page.get_by_test_id("model-option-paas")
        paas.click()
        expect(paas).to_have_attribute("aria-pressed", "true")
        expect(stage).to_have_attribute("data-minute", minute)
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "paused")
        self.assert_no_errors(opened)

    def test_end_stop_has_the_results_of_the_day(self) -> None:
        """At the end of the day, the narration carries the results of the day as whole numbers."""
        opened: OpenedPage = self.open_page(ELASTICITY_PAGE)
        page: Page = opened.page

        # the slider is moved to the end:
        page.get_by_test_id("scrub").fill("1000")
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "ended")
        narration = page.get_by_test_id("narration")
        expect(narration).to_have_attribute("data-stop-type", "end")

        # the results of the day: slow minutes, money paid and idle capacity:
        for key in ("slow", "paid", "idle"):
            self.assertRegex(
                narration.get_attribute(f"data-result-{key}") or "", r"^\d+$", key
            )
        self.assert_no_errors(opened)

    def test_model_picker_offers_every_model(self) -> None:
        """The model picker offers the six models, and the size buttons are enabled only for models with a size."""
        opened: OpenedPage = self.open_page(ELASTICITY_PAGE)
        page: Page = opened.page

        # the six models, in this order:
        options = page.get_by_test_id(re.compile(r"^model-option-"))
        self.assertEqual(
            [f"model-option-{model}" for model in self.MODELS],
            [option.get_attribute("data-testid") for option in options.all()],
        )

        # the size buttons are enabled for on premise and hosting only; on premise comes again at the end, so that
        # the buttons are also seen to be enabled again after a model without a size:
        for step, model in enumerate(self.MODELS + self.MODELS[:1]):
            with self.subTest(step=step, model=model):
                page.get_by_test_id(f"model-option-{model}").click()
                for size in self.SIZES:
                    button = page.get_by_test_id(f"size-option-{size}")
                    if model in self.MODELS_WITH_SIZE:
                        expect(button).to_be_enabled()
                    else:
                        expect(button).to_be_disabled()
        self.assert_no_errors(opened)

    def test_every_model_and_size_steps_to_the_end_without_errors(self) -> None:
        """For every model, and for both sizes where the model has a size, Next leads to the end without errors."""
        for model in self.MODELS:
            sizes: list[str | None] = (
                list(self.SIZES) if model in self.MODELS_WITH_SIZE else [None]
            )
            for size in sizes:
                with self.subTest(model=model, size=size):
                    # a fresh page, so that an error is reported only for the model and size that caused it:
                    opened: OpenedPage = self.open_page(ELASTICITY_PAGE)
                    page: Page = opened.page

                    # the model and the size are chosen, and the day still shows its start:
                    choices: list[str] = [f"model-option-{model}"]
                    if size is not None:
                        choices.append(f"size-option-{size}")
                    for choice in choices:
                        page.get_by_test_id(choice).click()
                        expect(page.get_by_test_id(choice)).to_have_attribute(
                            "aria-pressed", "true"
                        )
                    expect(page.get_by_test_id("narration")).to_have_attribute(
                        "data-stop-type", "start"
                    )

                    # Next leads to the end, with at least one stop on the way:
                    stop_types: list[str] = self.step_to_end(page)
                    self.assertGreater(len(stop_types), 1, "Next jumped to the end")
                    self.assert_no_errors(opened)
                    # close the page before the next one opens, not only at the end of the test:
                    page.context.close()


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class ValidationPageTest(_PageTestCase):
    """Checks the controls of the page on MVCC validation: Next and Back, and the kinds of steps it narrates."""

    PAGE: Path | None = VALIDATION_PAGE

    def setUp(self) -> None:
        """Opens the page, paused at its start."""
        self.opened: OpenedPage = self.open_page(VALIDATION_PAGE)
        self.page: Page = self.opened.page

    def test_next_and_back(self) -> None:
        """Next moves on to the begin of T1, and Back returns to the start."""
        narration = self.page.get_by_test_id("narration")
        scrub = self.page.get_by_test_id("scrub")

        # Next shows the begin of the first transaction:
        self.page.get_by_test_id("next").click()
        expect(narration).to_have_attribute("data-stop-type", "begin")
        expect(self.page.get_by_test_id("nar-text")).to_contain_text("T1")
        self.assertGreater(int(scrub.input_value()), 0)

        # Back returns to the start:
        self.page.get_by_test_id("prev").click()
        expect(narration).to_have_attribute("data-stop-type", "start")
        expect(scrub).to_have_value("0")
        self.assert_no_errors(self.opened)

    def test_narrates_every_kind_of_step(self) -> None:
        """On the way to the end, the page narrates begins, validations, commits, an abort and the end."""
        stop_types: list[str] = self.step_to_end(self.page)
        # a commit is narrated as "morph": the interval of the transaction shrinks to its point in time:
        self.assertEqual(
            {"begin", "validate", "morph", "abort", "end"}, set(stop_types)
        )
        self.assert_no_errors(self.opened)


class JobShareTest(unittest.TestCase):
    """Checks without a browser how a run reads its job from VISUALIZATION_JOB and which pages each job tests.

    The tests that read the variable set it themselves, as they also run inside a CI job, where it is set.
    """

    # made-up pages, which need not exist, in no particular order; three of the five have a sound button:
    PAGES: list[Path] = [Path(f"v/{name}.html") for name in "eabdc"]
    WITH_SOUND: frozenset[Path] = frozenset(Path(f"v/{name}.html") for name in "bde")

    def shares(self, total: int) -> list[list[Path]]:
        """Returns the made-up pages of each of total jobs, from job 1 on."""
        return [
            pages_of_job(
                self.PAGES, index, total, sound=lambda path: path in self.WITH_SOUND
            )
            for index in range(1, total + 1)
        ]

    @staticmethod
    def job_of(page: Path, total: int) -> int:
        """Returns which of total jobs tests the page, among the pages of visualizations/."""
        pages: list[Path] = find_pages()
        return next(
            index
            for index in range(1, total + 1)
            if page in pages_of_job(pages, index, total)
        )

    @staticmethod
    def page_class(page: Path | None) -> type[_PageTestCase]:
        """Returns a subclass of _PageTestCase, without tests of its own, whose PAGE is page."""
        return type("OnePageTestCase", (_PageTestCase,), {"PAGE": page})

    def test_the_job_is_read_from_the_variable(self) -> None:
        """Without the variable, the run is the only job, also where GitLab sets its own CI_NODE_INDEX and
        CI_NODE_TOTAL; with "i/n", it is job i of n.
        """
        # each environment and the job it names:
        cases: list[tuple[dict[str, str], tuple[int, int]]] = [
            ({}, (1, 1)),
            ({"CI_NODE_INDEX": "2", "CI_NODE_TOTAL": "3"}, (1, 1)),
            ({JOB_VARIABLE: "1/1"}, (1, 1)),
            ({JOB_VARIABLE: "2/3"}, (2, 3)),
            ({JOB_VARIABLE: "10/12"}, (10, 12)),
        ]
        for environment, job in cases:
            with self.subTest(environment=environment):
                with mock.patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(job, job_of_this_run())

    def test_a_value_that_is_no_job_is_an_error(self) -> None:
        """A value that is not "i/n" with 1 <= i <= n is an error that names the value, so that no page drops out.

        "/1" is what the CI job sets if ``parallel`` is removed but its script kept, as GitLab then sets no
        CI_NODE_INDEX.
        """
        for value in ["", "/1", "0/3", "4/3", "x", "2/3/4", " 2/3"]:
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, {JOB_VARIABLE: value}, clear=True):
                    with self.assertRaises(ValueError) as raised:
                        job_of_this_run()
                self.assertIn(repr(value), str(raised.exception))

    def test_one_job_tests_the_pages_with_sound_first(self) -> None:
        """A single job tests all pages: those with sound first, then the others, each sorted by path."""
        b, d, e, a, c = (Path(f"v/{name}.html") for name in "bdeac")
        self.assertEqual([[b, d, e, a, c]], self.shares(1))

    def test_each_page_is_tested_in_exactly_one_job(self) -> None:
        """For any number of jobs up to the number of pages, each page is in exactly one job, and no job is empty."""
        for total in range(1, len(self.PAGES) + 1):
            with self.subTest(total=total):
                shares: list[list[Path]] = self.shares(total)
                self.assertEqual(
                    sorted(self.PAGES),
                    sorted(page for share in shares for page in share),
                )
                self.assertNotIn([], shares)

    def test_three_jobs_get_one_page_with_sound_each(self) -> None:
        """With three jobs and three pages with sound among five, each job gets one page with sound.

        In the order b, d, e (with sound), a, c, page k goes to job k mod 3 + 1; sorted by path alone, job 2 would get
        b and e, and job 3 no page with sound.
        """
        b, d, e, a, c = (Path(f"v/{name}.html") for name in "bdeac")
        shares: list[list[Path]] = self.shares(3)
        self.assertEqual([[b, a], [d, c], [e]], shares)
        self.assertEqual(
            [1, 1, 1], [len(self.WITH_SOUND.intersection(share)) for share in shares]
        )

    def test_more_jobs_than_pages_is_an_error(self) -> None:
        """More jobs than pages, also one job for no page, is an error that names both, as a job would test no page."""
        cases: list[tuple[list[Path], int]] = [(self.PAGES, 6), ([], 1)]
        for pages, total in cases:
            with self.subTest(pages=len(pages), total=total):
                with self.assertRaises(ValueError) as raised:
                    pages_of_job(pages, 1, total, sound=lambda _path: False)
                self.assertIn(
                    f"{total} jobs for {len(pages)} pages", str(raised.exception)
                )

    def test_a_job_outside_1_to_total_is_an_error(self) -> None:
        """A job below 1 or above total, and any job of 0 jobs, is an error that names the job.

        The error is checked by its message, as a slice with a step of 0 would raise a ValueError, too.
        """
        for index, total in [(0, 3), (4, 3), (-1, 3), (1, 0)]:
            with self.subTest(index=index, total=total):
                with self.assertRaises(ValueError) as raised:
                    pages_of_job(self.PAGES, index, total, sound=lambda _path: False)
                self.assertIn(f"job {index} of {total}", str(raised.exception))

    def test_each_page_of_visualizations_is_in_exactly_one_ci_job(self) -> None:
        """In the CI jobs, each page of visualizations/ is tested exactly once."""
        pages: list[Path] = find_pages()
        shares: list[list[Path]] = [
            pages_of_job(pages, index, CI_JOBS) for index in range(1, CI_JOBS + 1)
        ]
        self.assertEqual(pages, sorted(page for share in shares for page in share))

    def test_the_pages_with_sound_are_spread_evenly_over_the_ci_jobs(self) -> None:
        """Each CI job tests at least one page of visualizations/ with sound, and no job two more than another.

        At least one, so that no job skips the sound tests; spread evenly, so that no job takes much longer than the
        others, as the tests of a page with sound take longest. A new page with sound needs no change to the CI
        configuration: it goes to the job whose turn it is.
        """
        pages: list[Path] = find_pages()
        # the number of pages with sound of each job:
        with_sound: list[int] = [
            sum(has_sound(path) for path in pages_of_job(pages, index, CI_JOBS))
            for index in range(1, CI_JOBS + 1)
        ]
        # evenly spread first: only then does a job without a page with sound mean that there are too many jobs
        self.assertLessEqual(
            max(with_sound) - min(with_sound),
            1,
            f"a job takes much longer than another (pages with sound per job: {with_sound}): pages_of_job must "
            "spread the pages with sound over the jobs before the other pages",
        )
        self.assertGreaterEqual(
            min(with_sound),
            1,
            f"a job skips the sound tests (pages with sound per job: {with_sound}): there are fewer pages with sound "
            "than jobs, so lower `parallel` of visualization_test in .gitlab-ci.yml and CI_JOBS",
        )

    def test_a_page_class_of_another_job_is_skipped_before_playwright_starts(
        self,
    ) -> None:
        """A class whose PAGE another job tests is skipped in setUpClass, names the page and its job, and starts no
        browser.
        """
        # one job per page (at least the two known ones, so there is another job): the job that tests the clock-scan
        # page, and the next one:
        total: int = len(find_pages())
        own_job: int = self.job_of(CLOCK_SCAN_PAGE, total)
        environment: dict[str, str] = {JOB_VARIABLE: f"{own_job % total + 1}/{total}"}

        # setUpClass skips the class and does not start Playwright:
        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch(f"{__name__}.sync_playwright") as start,
        ):
            with self.assertRaises(unittest.SkipTest) as skipped:
                self.page_class(CLOCK_SCAN_PAGE).setUpClass()
        self.assertEqual(
            f"{CLOCK_SCAN_PAGE.name} is tested in job {own_job} of {total}",
            str(skipped.exception),
        )
        start.assert_not_called()

    def test_a_page_class_of_this_job_and_one_without_page_start_playwright(
        self,
    ) -> None:
        """A class whose PAGE this job tests, and a class without PAGE, start Playwright in setUpClass."""
        # the job that tests the clock-scan page, and any job for a class without PAGE:
        own_job: int = self.job_of(CLOCK_SCAN_PAGE, CI_JOBS)
        cases: list[tuple[Path | None, str]] = [
            (CLOCK_SCAN_PAGE, f"{own_job}/{CI_JOBS}"),
            (None, f"{CI_JOBS}/{CI_JOBS}"),
        ]
        for page, job in cases:
            with self.subTest(page=page, job=job):
                page_class: type[_PageTestCase] = self.page_class(page)

                # setUpClass starts Playwright (here a mock); a SkipTest would only mark this test as skipped, so the
                # except turns it into a failure; the cleanups stop Playwright again:
                with (
                    mock.patch.dict(os.environ, {JOB_VARIABLE: job}, clear=True),
                    mock.patch(f"{__name__}.sync_playwright") as start,
                ):
                    try:
                        page_class.setUpClass()
                    except unittest.SkipTest as skipped:
                        self.fail(f"the class was skipped: {skipped}")
                    page_class.doClassCleanups()
                start.assert_called_once_with()

    def test_a_page_class_whose_page_is_missing_is_an_error(self) -> None:
        """A class whose PAGE is not among the pages of visualizations/ fails in setUpClass instead of being skipped,
        before Playwright starts.
        """
        page_class: type[_PageTestCase] = self.page_class(
            PAGES_DIR / "no-such-page.html"
        )

        # setUpClass raises an AssertionError that names the page; a SkipTest is caught as well, as it would only mark
        # this test as skipped:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch(f"{__name__}.sync_playwright") as start,
        ):
            with self.assertRaises(Exception) as raised:
                page_class.setUpClass()
        self.assertIs(AssertionError, type(raised.exception))
        self.assertIn("no-such-page.html", str(raised.exception))
        start.assert_not_called()

    def test_a_page_class_opens_only_its_page(self) -> None:
        """A class with a PAGE fails on another page before it uses the browser, as it runs only in its page's job;
        it opens its own page, and a class without PAGE opens any page.
        """
        # a class of the clock-scan page, in a mock browser, fails on the elasticity page:
        page_test: _PageTestCase = self.page_class(CLOCK_SCAN_PAGE)()
        page_test.browser = mock.Mock()
        with self.assertRaises(AssertionError) as raised:
            page_test.open_page(ELASTICITY_PAGE)
        self.assertEqual(
            f"OnePageTestCase opens {ELASTICITY_PAGE}, but its PAGE is {CLOCK_SCAN_PAGE}",
            str(raised.exception),
        )
        page_test.browser.new_context.assert_not_called()

        # the clock-scan page itself, and the elasticity page in a class without PAGE, are opened:
        for page, path in [(CLOCK_SCAN_PAGE, CLOCK_SCAN_PAGE), (None, ELASTICITY_PAGE)]:
            with self.subTest(page=page):
                page_test = self.page_class(page)()
                page_test.browser = mock.Mock()
                page_test.open_page(path)
                page_test.browser.new_context.assert_called_once()
                page_test.doCleanups()

    def test_a_job_without_a_page_with_sound_skips_the_sound_checks(self) -> None:
        """In a job whose pages have no sound button, a check on each page with sound is skipped with a message that
        names the job, and runs on no page.
        """
        # one job per page, and this run is the job of the elasticity page, which has no sound button:
        self.assertFalse(has_sound(ELASTICITY_PAGE))
        total: int = len(find_pages())
        job: int = self.job_of(ELASTICITY_PAGE, total)
        environment: dict[str, str] = {JOB_VARIABLE: f"{job}/{total}"}

        # the check is skipped before a page is opened:
        check: mock.Mock = mock.Mock()
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(unittest.SkipTest) as skipped:
                _SoundPageTestCase().check_each_page_with_sound(check)
        self.assertEqual(
            f"job {job} of {total} tests no page with sound", str(skipped.exception)
        )
        check.assert_not_called()


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class RecordingTest(_PageTestCase):
    """Checks that open_page records what the tests above rely on, also after an update of Playwright."""

    # a page that logs a console error, throws an error and reaches for the network twice, with a request and with
    # a WebSocket:
    BAD_PAGE: str = """<!doctype html>
<script>
  fetch("https://example.invalid/data.json").catch(() => {});
  new WebSocket("wss://example.invalid/socket");
  console.error("planted console error");
  throw new Error("planted error");
</script>
"""

    def test_errors_requests_and_websockets_are_recorded(self) -> None:
        """A console error, an uncaught error, a request and a WebSocket to the network are each recorded."""
        with tempfile.TemporaryDirectory() as folder:
            path: Path = Path(folder) / "bad.html"
            path.write_text(self.BAD_PAGE, encoding="utf-8")
            opened: OpenedPage = self.open_page(path)

            # the request and the WebSocket are recorded as soon as Playwright has handled them (at most 5 s):
            expected: set[str] = {
                "https://example.invalid/data.json",
                "wss://example.invalid/socket",
            }
            for _ in range(50):
                if expected <= set(opened.outside_requests):
                    break
                opened.page.wait_for_timeout(100)
            self.assertEqual(expected, set(opened.outside_requests))

            # the console error and the uncaught error are recorded:
            self.assertIn("console: planted console error", opened.errors)
            self.assertIn("uncaught: planted error", opened.errors)


if __name__ == "__main__":
    unittest.main()
