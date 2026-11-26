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
from typing import TYPE_CHECKING, NamedTuple, TypedDict
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

# the page counts and runs of the external sorting page, from a module that uses only the standard library as well:
from system.tests.repo.external_sorting_page_data import (
    EXPECTED_GROUPS,
    EXPECTED_PASS_COUNTS,
    EXPECTED_READS,
    EXPECTED_WRITES,
    EXTERNAL_SORTING_PAGE,
    MEMORY_PAGES,
    PageCounts,
    merge_heaps,
    merged_runs,
    pass_0_runs,
    read_input,
)

# the tests that open a browser run only where Playwright is installed (see the module docstring):
PLAYWRIGHT_AVAILABLE: bool = importlib.util.find_spec("playwright") is not None

# without the dependency group browser-tests, pylint cannot find playwright:
# pylint: disable=import-error
# the type checker always takes the import, so that it knows these names as Playwright's and never as None:
if TYPE_CHECKING or PLAYWRIGHT_AVAILABLE:
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
# the storage hierarchy as a mine shaft under the House DBMS, its depth strictly to scale with the access times
# (decision 045):
STORAGE_HIERARCHY_PAGE: Path = PAGES_DIR / "storage-hierarchy.html"
# the pages that speak their narration (the B-tree page, B_TREE_PAGE, the storage hierarchy page,
# STORAGE_HIERARCHY_PAGE, and the external sorting page, EXTERNAL_SORTING_PAGE, with the same voice, decisions 040, 045
# and 046); each must keep its sound button:
PAGES_WITH_SOUND: frozenset[Path] = frozenset(
    {
        CLOCK_SCAN_PAGE,
        ROW_OR_COLUMN_PAGE,
        HOUSE_DBMS_PAGE,
        YANNAKAKIS_PAGE,
        B_TREE_PAGE,
        STORAGE_HIERARCHY_PAGE,
        EXTERNAL_SORTING_PAGE,
    }
)
# the pages with sound whose film has parts, with a button (chapter-1, ...) that jumps to the start of each:
PAGES_WITH_PARTS: frozenset[Path] = frozenset(
    {
        CLOCK_SCAN_PAGE,
        HOUSE_DBMS_PAGE,
        YANNAKAKIS_PAGE,
        B_TREE_PAGE,
        STORAGE_HIERARCHY_PAGE,
        EXTERNAL_SORTING_PAGE,
    }
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


def file_size(path: Path) -> int:
    """Returns the size of the file at path in bytes."""
    return path.stat().st_size


def pages_of_job(
    pages: list[Path],
    index: int,
    total: int,
    sound: Callable[[Path], bool] = has_sound,
    size: Callable[[Path], int] = file_size,
) -> list[Path]:
    """Returns the pages that job index of total tests; each page is tested in exactly one job.

    The pages with a sound button, whose tests take longest, come first, then the others; each group is sorted by size,
    largest first (a page's size, its voice, 3D code and fonts, goes with how long its tests take), then by path; page
    number k of this order (from 0) goes to job k mod total + 1. So the pages with sound, and among them the largest,
    are spread over the jobs before the others.

    @param pages: all pages
    @param index: the job, from 1 to total
    @param total: the number of jobs
    @param sound: whether a page has a sound button
    @param size: a page's size
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
    order: list[Path] = sorted(
        pages, key=lambda path: (not sound(path), -size(path), path)
    )
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


class MadeBySortingPage(TypedDict):
    """What the external sorting page's own quicksort and heap make, as its script writes it into ``data-made``."""

    # the runs r1 … r9 of pass 0, each sorted:
    runs: list[list[int]]
    # the runs r10 … r12 of merge level 1:
    merged: list[list[int]]
    # the final merge's output:
    output: list[int]


class PageMarks(NamedTuple):
    """The pages of the row-or-column page's three layouts as it marks them in memory at one moment, as noted in
    ``data-pages-shown``, ``data-pages-row``, ``-column`` and ``-pax`` of its stage."""

    # the layouts whose pages are marked, in the film's order, comma-separated (e.g. ``row,column``; empty before any):
    shown: str
    # the state of each page of a layout, in page order, comma-separated: ``none`` before its scan has passed it,
    # ``read`` once the read head has reached the first line the scan loads of it, ``not-read`` at the end of a scan
    # that loads none of its lines (e.g. ``not-read,not-read,read``):
    row: str
    column: str
    pax: str


@dataclass(frozen=True)
class RealReads:
    """What SELECT MAX(price) reads of one layout of the row-or-column page's table at real size (512 books on pages
    of 4 KB)."""

    # the pages that hold a cache line it reads, and the pages that hold none:
    pages: int
    not_read: int
    # the cache lines it reads:
    lines: int
    # the share of prices among the bytes of those lines (%, rounded):
    share: int


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

    def open_page(
        self, path: Path, reduced_motion: bool = True, query: str = ""
    ) -> OpenedPage:
        """Opens the page at path in a new browser context, which is closed after the test.

        Errors and outside requests are recorded from before the page loads. A class with a PAGE opens only that page,
        as it runs only in that page's job.

        @param path: the HTML file of the page
        @param reduced_motion: whether the browser asks for reduced motion; the pages then do not start playing on
            their own, so that every test starts from a paused page at time 0
        @param query: added to the page's URL, e.g. ``?t=12.5&paused`` for a page that opens at the time given there
        @return: the opened page with the lists of errors and outside requests
        @raise AssertionError: if the class has a PAGE and path is another page; raised before the browser is used
        """
        return self.open_page_in(
            self.browser, self.addCleanup, path, reduced_motion, query
        )

    @classmethod
    def open_page_in(
        cls,
        browser: Browser,
        add_cleanup: Callable[[Callable[[], None]], None],
        path: Path,
        reduced_motion: bool = True,
        query: str = "",
    ) -> OpenedPage:
        """Opens the page at path as open_page does, in a new context of the given browser, and hands the closing of
        that context to add_cleanup: open_page closes it after the test, while setUpClass, with ``cls.addClassCleanup``,
        keeps one page open for all tests of the class.

        @param browser: the browser to open the page in
        @param add_cleanup: registers a function to call once the page is no longer needed
        @param path: the HTML file of the page
        @param reduced_motion: whether the browser asks for reduced motion; the pages then do not start playing on
            their own, so that every test starts from a paused page at time 0
        @param query: added to the page's URL, e.g. ``?t=12.5&paused`` for a page that opens at the time given there
        @return: the opened page with the lists of errors and outside requests
        @raise AssertionError: if the class has a PAGE and path is another page; raised before the browser is used
        """
        if cls.PAGE is not None and path != cls.PAGE:
            raise AssertionError(
                f"{cls.__name__} opens {path}, but its PAGE is {cls.PAGE}"
            )
        context = browser.new_context(
            reduced_motion="reduce" if reduced_motion else "no-preference"
        )
        add_cleanup(context.close)
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
        opened.page.goto(path.as_uri() + query)
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
        100 s, ten steps are about 1 s, on the row-or-column page, which lasts 83.2 s, about 0.83 s.

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
    """Checks what is particular to the row-or-column page: its voice, which says some captions in two segments; the
    counters and the pages marked in memory of its three layouts (row, column and PAX); its real pages and the receipt
    that counts them; the slider with a segment per step; the step's name top left as a step begins; and its header,
    which leaves the terminal and the step's name below it free.

    Each segment has a clip of its own, which starts at the segment's time (decision 035). The times below are those
    of the page's CAPTIONS, SCANS and CUES; the PAX step, the pages from step 03 on, the real pages step, the receipt,
    the slider's segments and the step's name top left are those of decision 054.
    """

    PAGE: Path | None = ROW_OR_COLUMN_PAGE

    # the film's length (s); the slider has 1000 steps over it:
    LENGTH: float = 83.2
    # the steps of the film in their order: their stop type, their name in the header, where each begins and where
    # its first segment begins (s):
    STEP_TYPES: list[str] = [
        "query",
        "memory",
        "cache-lines",
        "row-layout",
        "column-layout",
        "pax-layout",
        "real-pages",
        "verdict",
        "result",
    ]
    STEP_NAMES: list[str] = [
        "01/09 · The query",
        "02/09 · Memory",
        "03/09 · Cache lines, pages",
        "04/09 · Row layout",
        "05/09 · Column layout",
        "06/09 · PAX layout",
        "07/09 · Real pages",
        "08/09 · Verdict",
        "09/09 · Result",
    ]
    STEPS_FROM: list[float] = [0, 6.0, 13.0, 26.2, 37.2, 49.2, 61.2, 73.2, 80.2]
    FIRST_SEGMENTS: list[float] = [0.5, 6.4, 13.4, 26.6, 37.8, 49.4, 61.7, 73.7, 80.5]
    # the steps whose caption the voice says in two segments, with the two segments as the subtitle shows them:
    TWO_SEGMENTS: dict[str, list[str]] = {
        "cache-lines": [
            "The CPU loads it in cache lines: 64 bytes at a time.",
            "The database reads and writes whole pages: 128 bytes here, really 4 kilobytes.",
        ],
        "row-layout": [
            "Row layout: each cache line drags title and author along.",
            "Two pages, four cache lines: a quarter used.",
        ],
        "column-layout": [
            "Same data, stored by column: all prices side by side.",
            "One page, one cache line, every byte used.",
        ],
        "pax-layout": [
            "PAX, Partition Attributes Across: the same pages, grouped by column inside.",
            "Same two pages, half the cache lines.",
        ],
        "real-pages": [
            "Real pages of 4 kilobytes: PAX reads as few cache lines as columns.",
            "But every page. Columns read only the page of prices.",
        ],
    }
    # where the second segment of each of them begins (s): in the cache-lines step where it brings in pages, in the
    # column-layout and the PAX step where the scan loads its first line (the tests of tools/render_video.py check the
    # start of each clip):
    SECOND_SEGMENTS: dict[str, float] = {
        "cache-lines": 18.6,
        "row-layout": 33.0,
        "column-layout": 44.2,
        "pax-layout": 55.6,
        "real-pages": 68.8,
    }
    # the row-layout step is the fourth:
    ROW_LAYOUT_STEP: int = 4
    # a clip longer than its time plays at most this many times as fast (decision 034):
    MAX_RATE: float = 1.15

    # the layouts in the order of the film and of the header's counters:
    LAYOUTS: list[str] = ["row", "column", "pax"]
    # when the pages of each layout are marked in memory (s): the row layout's with the second segment of the
    # cache-lines step, which says what a page is, and the header's counters show their pages from then on; the column
    # layout's and PAX's once the layout is complete:
    PAGES_FROM: dict[str, float] = {"row": 18.6, "column": 42.8, "pax": 54.8}
    # the scans of SELECT MAX(price): when the read head reaches each cache line that a scan loads (s), and when the
    # scan ends (s), where the pages it did not need are marked "not read". First the page, then its lines: as the head
    # reaches the first line it loads of a page, the page is read (marked "read" and counted among the pages read);
    # each line arrives in the cache, and is counted with its bytes, LOAD_DURATION later. The row layout loads its lines
    # 0 to 3 (pages 0 and 1), the column layout its line 4 (page 2, that of the prices), PAX its lines 1 (page 0) and 3
    # (page 1):
    LOADS: dict[str, list[float]] = {
        "row": [27.2, 28.7, 30.2, 31.7],
        "column": [44.2],
        "pax": [55.6, 57.6],
    }
    SCAN_DONE: dict[str, float] = {"row": 34.1, "column": 46.1, "pax": 59.1}
    LOAD_DURATION: float = 0.8
    # what the counters of each layout show once its scan of SELECT MAX(price) is done: the pages and the cache lines
    # read, and the bytes loaded and used (the 64 B of the eight prices):
    COUNTED: dict[str, tuple[int, int, int, int]] = {
        "row": (2, 4, 256, 64),
        "column": (1, 1, 64, 64),
        "pax": (2, 2, 128, 64),
    }
    # what they show before it:
    NOT_COUNTED: tuple[int, int, int, int] = (0, 0, 0, 0)
    # what the row layout's counter shows while its third line is on its way to the cache: its pages 0 and 1 read,
    # and the first two lines arrived, each with the prices of two books (16 B):
    ROW_THIRD_LINE_ON_ITS_WAY: tuple[int, int, int, int] = (2, 2, 128, 32)
    # what PAX's counter shows while its first line is on its way: its page 0 read, no line arrived yet:
    PAX_FIRST_LINE_ON_ITS_WAY: tuple[int, int, int, int] = (1, 0, 0, 0)
    # once that line has arrived: the line, on page 0, with its 32 B of prices:
    PAX_FIRST_LINE_ARRIVED: tuple[int, int, int, int] = (1, 1, 64, 32)
    # while its second line is on its way: its pages 0 and 1 read, the first line arrived:
    PAX_SECOND_LINE_ON_ITS_WAY: tuple[int, int, int, int] = (2, 1, 64, 32)
    # the real pages come in at 61.8 s; the header's counters, which count the eight books of the small example, are
    # dimmed from then on, fully 0.6 s later:
    REAL_PAGES_FROM: float = 61.8
    COUNTERS_DIMMED: float = 62.4
    # PAX's row of the counters shows from when PAX's title appears, as PAX is laid down (s):
    PAX_COUNTER_FROM: float = 50.2
    # the real pages are shown until 73.6 s; they fade in and out over REAL_PAGES_FADE (s). Each layout's real pages are
    # read from its REAL_READ time on (s): first the pages read get their green frames (REAL_FRAME_LEAD, s), then their
    # lines read light up (REAL_READ_DURATION, s):
    REAL_PAGES_UNTIL: float = 73.6
    REAL_PAGES_FADE: float = 0.4
    REAL_READ: dict[str, float] = {"row": 63.2, "column": 65.2, "pax": 67.2}
    REAL_FRAME_LEAD: float = 0.5
    REAL_READ_DURATION: float = 1.2

    # the table at real size, which the real pages step shows and the receipt counts: 512 books, each with a title of
    # 16 B, an author of 8 B and a price of 8 B (32 B in all), on pages of 4 KB, read in cache lines of 64 B:
    REAL_BOOKS: int = 512
    FIELD_BYTES: dict[str, int] = {"title": 16, "author": 8, "price": 8}
    BOOK_BYTES: int = 32
    REAL_PAGE_BYTES: int = 4096
    LINE_BYTES: int = 64
    # what SELECT MAX(price) reads of each layout at real size, as decision 054 states it (DECISION.md, section
    # "Scope-shift 2026-11-26 (pages from the start, real pages as a step)"): the pages read and not read, the cache
    # lines read and the share of prices among their bytes (%):
    REAL_READS_OF_DECISION: dict[str, RealReads] = {
        "row": RealReads(pages=4, not_read=0, lines=256, share=25),
        "column": RealReads(pages=1, not_read=3, lines=64, share=100),
        "pax": RealReads(pages=4, not_read=0, lines=64, share=100),
    }
    # how the receipt names the layouts:
    RECEIPT_NAMES: dict[str, str] = {
        "row": "row layout",
        "column": "column layout",
        "pax": "PAX",
    }
    # the receipt's items from top to bottom: the heads of its two columns, input/output and memory; the line of each
    # layout, in the film's order; and the totals, what the column layout and what PAX save against the row layout:
    RECEIPT_ITEMS: list[str] = [
        "receipt-heads",
        "receipt-row",
        "receipt-column",
        "receipt-pax",
        "receipt-total",
        "receipt-total-pax",
    ]
    # the receipt's footnote on one whole book, which holds also for pages of real size:
    FOOTNOTE: str = (
        "One whole book? Row layout: 1 page, 1 cache line. PAX: 1 page. Column layout: a page per column."
    )

    # the slider's thumb is this wide (px); its middle runs from half of it after the slider's left edge to half of it
    # before its right edge:
    THUMB_WIDTH: float = 14
    # phones held upright, on which the header stands above the terminal and the slider gets a line of its own:
    PHONES: list[tuple[int, int]] = [(360, 780), (390, 844)]
    # the least width of the slider on such a phone (px):
    PHONE_SLIDER_WIDTH: float = 250
    # as a step begins, its name shows top left from STEP_TITLE_DELAY after the step's beginning for STEP_TITLE_FOR,
    # fading in and out over STEP_TITLE_FADE (s); not in the first and the last step, where the terminal stands there:
    STEP_TITLE_DELAY: float = 0.3
    STEP_TITLE_FOR: float = 3.0
    STEP_TITLE_FADE: float = 0.4

    class ScansShown(TypedDict):
        """What the header's counters and the pages marked in memory show at one moment (see scans_shown)."""

        # the data attributes of ``counters``, by their name in the dataset (e.g. ``paxLines``):
        noted: dict[str, str]
        # the visibility of the pages of each layout's counter, ``visible`` or ``hidden``:
        pages: dict[str, str]
        # the pages marked in memory:
        marks: PageMarks

    @dataclass
    class Stretch:
        """A stretch of the film between two of its events, and what the counters and the pages in memory show in it
        (see test_scrubbing_back_shows_what_a_page_opened_there_shows)."""

        # the two events (s):
        after: float
        before: float
        # what the counters count of each layout (see counters), and the visibility of their pages (for PAX's counter
        # only from when its row shows, PAX_COUNTER_FROM; before, its pages are hidden with the row):
        counted: dict[str, tuple[int, int, int, int]]
        pages: str
        # the pages marked in memory:
        marks: PageMarks

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

    def thumb_at(self, seconds: float) -> float:
        """Returns where the middle of the slider's thumb stands at a time of the film, from the slider's left edge.

        @param seconds: a time of the film
        @return: the distance (px) from the slider's left edge
        """
        width: float = self.box_of("scrub")["width"]
        return self.THUMB_WIDTH / 2 + seconds / self.LENGTH * (width - self.THUMB_WIDTH)

    def step_title_middle(self, step: int) -> float:
        """Returns the middle of the time in which a step's name shows top left, where it shows in full.

        @param step: the step, from 1 to 9
        @return: the time (s)
        """
        return (
            self.STEPS_FROM[step - 1] + self.STEP_TITLE_DELAY + self.STEP_TITLE_FOR / 2
        )

    def press_next(self, times: int) -> None:
        """Clicks Next the given number of times.

        @param times: how often Next is clicked
        """
        for _ in range(times):
            self.page.get_by_test_id("next").click()

    def next_to(self, stop_type: str) -> None:
        """Clicks Next until the narration shows the given step. With sound off, Next stops at the end of each step
        (CAPTION_FADE, 0.35 s, before the next one begins), where the step is shown in full.

        @param stop_type: the step's stop type, one of STEP_TYPES at or after the current stop, but not the last (the
            last stop is the end, ``end``)
        """
        narration = self.page.get_by_test_id("narration")
        for _ in range(len(self.STEP_TYPES)):
            if narration.get_attribute("data-stop-type") == stop_type:
                return
            self.page.get_by_test_id("next").click()
        expect(narration).to_have_attribute("data-stop-type", stop_type)

    def counters(self) -> dict[str, tuple[int, int, int, int]]:
        """Returns what the header's counters note for each layout, and asserts that they show the same numbers.

        @return: for each layout of LAYOUTS, the pages, the cache lines, the bytes loaded and the bytes used, as noted
            in ``data-{layout}-pages``, ``-lines``, ``-loaded`` and ``-used`` of ``counters``
        """
        box = self.page.get_by_test_id("counters")

        def number(layout: str, quantity: str, unit: str) -> int:
            """Returns the number that the counters note for a layout and a quantity (e.g. ``pages``), and asserts that
            the counter shows it, followed by the unit (" B" for bytes, "" else).
            """
            noted: str = box.get_attribute(f"data-{layout}-{quantity}") or ""
            shown: str | None = self.page.get_by_test_id(
                f"{layout}-{quantity}"
            ).text_content()
            self.assertEqual(f"{noted}{unit}", shown, f"{layout}-{quantity}")
            return int(noted)

        return {
            layout: (
                number(layout, "pages", ""),
                number(layout, "lines", ""),
                number(layout, "loaded", " B"),
                number(layout, "used", " B"),
            )
            for layout in self.LAYOUTS
        }

    def counters_opacity(self) -> float:
        """Returns the opacity of the header's counters, as the browser has computed it."""
        return float(
            self.page.get_by_test_id("counters").evaluate(
                "box => getComputedStyle(box).opacity"
            )
        )

    def page_marks(self, page: Page) -> PageMarks:
        """Returns the pages of the three layouts as a page marks them in memory.

        @param page: the row-or-column page, also one opened in another browser context than ``self.page``
        @return: ``data-pages-shown``, ``data-pages-row``, ``-column`` and ``-pax`` of ``stage``
        """
        data: dict[str, str] = page.get_by_test_id("stage").evaluate(
            "stage => ({ ...stage.dataset })"
        )
        return PageMarks(
            data["pagesShown"], data["pagesRow"], data["pagesColumn"], data["pagesPax"]
        )

    def scans_shown(self, page: Page) -> ScansShown:
        """Returns what the header's counters of a page show, whether their pages are visible, and the pages marked in
        memory.

        @param page: the row-or-column page, also one opened in another browser context than ``self.page``
        @return: the data attributes of ``counters``, the visibility of ``{layout}-pages`` for each layout of LAYOUTS,
            and the pages marked in memory (see page_marks)
        """
        noted: dict[str, str] = page.get_by_test_id("counters").evaluate(
            "box => ({ ...box.dataset })"
        )
        pages: dict[str, str] = {
            layout: page.get_by_test_id(f"{layout}-pages").evaluate(
                "pages => getComputedStyle(pages).visibility"
            )
            for layout in self.LAYOUTS
        }
        return {"noted": noted, "pages": pages, "marks": self.page_marks(page)}

    def real_reads_shown(self) -> dict[str, RealReads]:
        """Returns what the page counts of the real pages of each layout, once it has built its scene (in which it
        counts them) and set up its controls.

        @return: for each layout of LAYOUTS, ``data-real-{layout}-pages``, ``-not-read``, ``-lines`` and ``-share`` of
            ``stage``
        """
        expect(self.page.get_by_test_id("play")).to_be_enabled()
        data: dict[str, str] = self.page.get_by_test_id("stage").evaluate(
            "stage => ({ ...stage.dataset })"
        )
        shown: dict[str, RealReads] = {}
        for layout in self.LAYOUTS:
            # in the dataset, e.g. realPaxNotRead for data-real-pax-not-read:
            name: str = f"real{layout.capitalize()}"
            shown[layout] = RealReads(
                pages=int(data[f"{name}Pages"]),
                not_read=int(data[f"{name}NotRead"]),
                lines=int(data[f"{name}Lines"]),
                share=int(data[f"{name}Share"]),
            )
        return shown

    @staticmethod
    def part_at(offset: int, parts: list[tuple[str | None, int]]) -> str | None:
        """Returns the part that holds a byte, of parts that lie one after the other.

        @param offset: the byte's distance from the start of the first part
        @param parts: the parts in their order, each with its name (None for free bytes) and its size in bytes
        @return: the name of the part that holds the byte; None if it is free or lies after the last part
        """
        for name, size in parts:
            if offset < size:
                return name
            offset -= size
        return None

    def field_at(self, layout: str, address: int) -> str | None:
        """Returns the attribute that holds a byte of a layout of the table at real size.

        The row layout stores book after book, each with its title, author and price. The column layout stores an
        array per attribute, each on pages of its own, after the pages of the attributes before it; the rest of its last
        page stays free. PAX stores the books of the row layout's pages, but inside each page first the titles of its
        books, then their authors, then their prices.

        @param layout: ``row``, ``column`` or ``pax``
        @param address: the byte's address, from 0 at the start of the layout's first page
        @return: ``title``, ``author`` or ``price``; None for a free byte
        """
        if layout == "row":
            return self.part_at(
                address % self.BOOK_BYTES, list(self.FIELD_BYTES.items())
            )
        if layout == "pax":
            books_per_page: int = self.REAL_PAGE_BYTES // self.BOOK_BYTES
            return self.part_at(
                address % self.REAL_PAGE_BYTES,
                [
                    (attribute, books_per_page * size)
                    for attribute, size in self.FIELD_BYTES.items()
                ],
            )
        parts: list[tuple[str | None, int]] = []
        for attribute, size in self.FIELD_BYTES.items():
            array: int = self.REAL_BOOKS * size
            parts += [(attribute, array), (None, -array % self.REAL_PAGE_BYTES)]
        return self.part_at(address, parts)

    def real_page_count(self, layout: str) -> int:
        """Returns how many pages a layout needs for the table at real size: the row layout and PAX fill page after
        page with whole books, the column layout fills pages of its own for each attribute.

        @param layout: ``row``, ``column`` or ``pax``
        @return: the number of pages
        """
        if layout == "column":
            return sum(
                math.ceil(self.REAL_BOOKS * size / self.REAL_PAGE_BYTES)
                for size in self.FIELD_BYTES.values()
            )
        books_per_page: int = self.REAL_PAGE_BYTES // self.BOOK_BYTES
        return math.ceil(self.REAL_BOOKS / books_per_page)

    def expected_real_reads(self, layout: str) -> RealReads:
        """Returns what SELECT MAX(price) reads of a layout of the table at real size, counted byte by byte (see
        field_at): every cache line that holds a price, and every page that holds such a line.

        @param layout: ``row``, ``column`` or ``pax``
        @return: the pages read and not read, the lines read and the share of prices among their bytes, rounded as
            Math.round does (half up)
        """
        lines_per_page: int = self.REAL_PAGE_BYTES // self.LINE_BYTES
        pages: int = self.real_page_count(layout)
        pages_read: int = 0
        lines_read: int = 0
        prices: int = 0
        for page in range(pages):
            lines_of_page: int = 0
            for line in range(lines_per_page):
                start: int = page * self.REAL_PAGE_BYTES + line * self.LINE_BYTES
                fields: list[str | None] = [
                    self.field_at(layout, start + byte)
                    for byte in range(self.LINE_BYTES)
                ]
                if "price" in fields:
                    lines_of_page += 1
                    prices += fields.count("price")
            lines_read += lines_of_page
            if lines_of_page:
                pages_read += 1
        return RealReads(
            pages=pages_read,
            not_read=pages - pages_read,
            lines=lines_read,
            share=math.floor(100 * prices / (lines_read * self.LINE_BYTES) + 0.5),
        )

    @staticmethod
    def as_bytes(count: int) -> str:
        """Returns a number of bytes as the receipt writes it: in KB from 1 KB on (e.g. ``16 KB``), else in B
        (e.g. ``64 B``)."""
        return f"{count / 1024:g} KB" if count >= 1024 else f"{count} B"

    @staticmethod
    def times(factor: float) -> str:
        """Returns a factor as the receipt prints it: rounded to two decimals, without trailing zeros (e.g. ``4×`` or
        ``1.33×``)."""
        return f"{round(factor, 2):g}×"

    def savings(self, layout: str) -> tuple[str, str]:
        """Returns how many times fewer pages (input/output) and cache lines (memory) a layout reads than the row
        layout, at real size, as the receipt's totals write them under the two column heads: e.g. ``4× fewer``, or
        ``same`` where the layout reads as many as the row layout.

        @param layout: ``column`` or ``pax``
        @return: the savings in pages and in cache lines, computed from the sizes (see expected_real_reads)
        """
        row: RealReads = self.expected_real_reads("row")
        other: RealReads = self.expected_real_reads(layout)

        def fewer(mine: int, theirs: int) -> str:
            """Returns ``<factor>× fewer`` if the row layout reads more than the other layout, else ``same``."""
            return f"{self.times(mine / theirs)} fewer" if mine > theirs else "same"

        return fewer(row.pages, other.pages), fewer(row.lines, other.lines)

    def real_states(self, page: Page) -> tuple[str, str, str]:
        """Returns how far a page shows the real pages of the row layout, the column layout and PAX read.

        @param page: the row-or-column page, also one opened in another browser context than ``self.page``
        @return: ``data-real-state-row``, ``-column`` and ``-pax`` of ``stage``, each ``hidden``, ``waiting``,
            ``reading`` or ``read``
        """
        data: dict[str, str] = page.get_by_test_id("stage").evaluate(
            "stage => ({ ...stage.dataset })"
        )
        return data["realStateRow"], data["realStateColumn"], data["realStatePax"]

    def box_of(self, test_id: str) -> FloatRect:
        """Returns the box of the element with the given test id, and fails if it has none (e.g. is hidden)."""
        box: FloatRect | None = self.page.get_by_test_id(test_id).bounding_box()
        if box is None:
            self.fail(f"{test_id} has no box")
        return box

    def assert_below_the_header(self, test_id: str) -> None:
        """Asserts that the element with the given test id begins below the header: below the hairline that closes it,
        under the step's name and the counters, which stand beside or below it.

        The page moves its terminal and the step's name top left below the header in a ResizeObserver's callback,
        which runs in the frame after the header has changed its size (with the window, or with a step's name that
        wraps); so the check waits for two frames first.

        @param test_id: ``terminal`` or ``step-title``
        """
        self.page.evaluate(
            "() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"
        )
        header: FloatRect = self.box_of("header")
        header_bottom: float = header["y"] + header["height"]
        card: FloatRect = self.box_of(test_id)
        self.assertGreaterEqual(
            card["y"],
            header_bottom,
            f"the header, down to {header_bottom} px, covers {test_id} {card}",
        )

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
            math.floor(self.slider_at(self.SECOND_SEGMENTS["row-layout"])),
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

    def test_next_stops_in_each_step_which_the_header_names(self) -> None:
        """With sound off, Next stops once in each of the nine steps, in their order, the last time at the end of the
        film, in the result step; the header names each step by its number of nine and its name, from "01/09 · The
        query" over "03/09 · Cache lines, pages" and "07/09 · Real pages" to "09/09 · Result".

        Fails if a step's name is numbered wrongly or out of another count (e.g. "06/08 · PAX layout"), if the header
        names another step than the one the narration tells, or if a step is skipped or comes out of order.
        """
        narration = self.page.get_by_test_id("narration")
        step = self.page.get_by_test_id("step")
        # the stop in each step: at its end, and in the last step at the end of the film (``end``):
        stop_types: list[str] = [*self.STEP_TYPES[:-1], "end"]
        for stop_type, name in zip(stop_types, self.STEP_NAMES):
            with self.subTest(step=name):
                # Next stops in the next step, which the header names:
                self.press_next(1)
                expect(narration).to_have_attribute("data-stop-type", stop_type)
                expect(step).to_contain_text(name)
        self.assert_no_errors(self.opened)

    def test_each_step_of_two_segments_shows_both_with_sound_off(self) -> None:
        """With sound off, at the end of each step whose caption the voice says in two segments, the subtitle shows the
        two segments one after the other: the cache-lines step says what a page is, the row-layout and the
        column-layout step how many pages and lines their scans read, the PAX step spells its name out, and the real
        pages step says that PAX reads as few lines as the column layout, but every page.

        Fails if a segment is missing, out of order or says something else.
        """
        text = self.page.get_by_test_id("nar-text")
        for stop_type, segments in self.TWO_SEGMENTS.items():
            with self.subTest(step=stop_type):
                # Next stops at the end of the step; the subtitle shows its two segments:
                self.next_to(stop_type)
                expect(text).to_be_visible()
                expect(text).to_have_text(" ".join(segments))
        self.assert_no_errors(self.opened)

    def test_words_said_count_segment_by_segment(self) -> None:
        """With sound off, the words of a caption in two segments count as said segment by segment.

        Just before the second segment begins, all words of the first are said; on the first step of the slider after
        it begins, before the voice has said the second segment's first word, still only those; where the caption is
        shown in full, all words of both.
        """
        page: Page = self.page
        scrub = page.get_by_test_id("scrub")
        narration = page.get_by_test_id("narration")
        segments: list[str] = self.TWO_SEGMENTS["row-layout"]
        first_words: int = len(segments[0].split())
        all_words: int = len(" ".join(segments).split())
        second_segment: float = self.slider_at(self.SECOND_SEGMENTS["row-layout"])

        # with sound off, Next stops where the row-layout step is shown in full: both segments, all words said:
        self.press_next(self.ROW_LAYOUT_STEP)
        expect(narration).to_have_attribute("data-stop-type", "row-layout")
        expect(page.get_by_test_id("nar-text")).to_have_text(" ".join(segments))
        expect(narration).to_have_attribute("data-words-said", str(all_words))

        # on the last step of the slider before the second segment begins, all words of the first one are said:
        scrub.fill(str(math.ceil(second_segment) - 1))
        expect(narration).to_have_attribute("data-words-said", str(first_words))

        # on the first step after it begins, before the voice has said the first word of its clip, still only those:
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

    def test_next_shows_the_counters_of_each_scan_once_it_is_done(self) -> None:
        """With sound off, Next stops at the end of each layout's step with its scan counted and the scans still to
        come at 0: at the end of the row-layout step the row layout's 2 pages, 4 cache lines, 256 B loaded and 64 B
        used; at the end of the column-layout step also the column layout's 1 page, 1 line, 64 B loaded and 64 B used;
        at the end of the PAX step also PAX's 2 pages, 2 lines, 128 B loaded and 64 B used.

        Fails if a line is counted before its layout's step or only after it, if one is counted on the wrong page, or
        if a scan changes the counters of another layout. When within a step each line is counted is checked by
        test_scrubbing_back_shows_what_a_page_opened_there_shows.
        """
        # Next stops at the end of the row-layout step: only the row layout is counted:
        self.next_to("row-layout")
        self.assertEqual(
            {
                "row": self.COUNTED["row"],
                "column": self.NOT_COUNTED,
                "pax": self.NOT_COUNTED,
            },
            self.counters(),
        )

        # Next stops at the end of the column-layout step: the column layout is counted as well, PAX is not:
        self.next_to("column-layout")
        self.assertEqual({**self.COUNTED, "pax": self.NOT_COUNTED}, self.counters())

        # Next stops at the end of the PAX step: its two lines, on two pages, are counted as well:
        self.next_to("pax-layout")
        self.assertEqual(self.COUNTED, self.counters())
        self.assert_no_errors(self.opened)

    def test_the_counters_show_the_pages_from_the_second_segment_of_step_03_on(
        self,
    ) -> None:
        """The pages in the counters of the row and the column layout are hidden until the second segment of the
        cache-lines step (03), which says what a page is, begins at 18.6 s; from then on they show, at the same moment
        as the row layout's pages are marked in memory, and until the end of the film. Back at the start, they are
        hidden again. (PAX's counter shows only from when PAX's title appears, see
        test_the_pax_counter_shows_from_when_pax_is_laid_down.)

        Fails if the pages show before the film brings them in, or only later (e.g. from the PAX step on), if the
        header and the memory bring in pages at different moments, or if the pages hide again later in the film.
        """
        scrub = self.page.get_by_test_id("scrub")
        stage = self.page.get_by_test_id("stage")
        pages_from: float = self.slider_at(self.SECOND_SEGMENTS["cache-lines"])

        def expect_pages(visibility: str) -> None:
            """Expects the pages of the row and the column layout's counters to have the given visibility,
            ``hidden`` or ``visible``."""
            for layout in ["row", "column"]:
                expect(self.page.get_by_test_id(f"{layout}-pages")).to_have_css(
                    "visibility", visibility
                )

        # at the start, the pages are hidden:
        expect_pages("hidden")

        # on the last step of the slider before the second segment of step 03 begins, they are still hidden, and no
        # page is marked in memory:
        scrub.fill(str(math.ceil(pages_from) - 1))
        expect_pages("hidden")
        expect(stage).to_have_attribute("data-pages-shown", "")

        # on the first step after it begins, they show, and the row layout's pages are marked:
        scrub.fill(str(math.ceil(pages_from)))
        expect_pages("visible")
        expect(stage).to_have_attribute("data-pages-shown", "row")

        # at the end of the film, they still show:
        scrub.fill("1000")
        expect(self.page.get_by_test_id("play")).to_have_attribute(
            "data-state", "ended"
        )
        expect_pages("visible")

        # back at the start, they are hidden again:
        scrub.fill("0")
        expect_pages("hidden")
        self.assert_no_errors(self.opened)

    def test_the_pax_counter_shows_from_when_pax_is_laid_down(self) -> None:
        """PAX's counter in the header, its row with all its numbers, is hidden until PAX's title appears as PAX is
        laid down (50.2 s), also after the other counters have shown their pages (from 18.6 s); from then on it shows,
        to the end of the film. Back at the start, it is hidden again.

        Fails if PAX's counter, or a part of it such as its pages, shows before the film has brought in PAX, or if it
        does not show from then on.
        """
        scrub = self.page.get_by_test_id("scrub")
        parts: list[str] = [
            "counter-pax",
            "pax-pages",
            "pax-lines",
            "pax-loaded",
            "pax-used",
        ]

        def expect_shown(shown: bool) -> None:
            """Expects PAX's counter and each of its numbers to be visible, or each of them to be hidden."""
            for test_id in parts:
                counter = self.page.get_by_test_id(test_id)
                if shown:
                    expect(counter).to_be_visible()
                else:
                    expect(counter).to_be_hidden()

        # at the start, it is hidden:
        expect_shown(False)

        # on the last step of the slider before PAX's title appears, it is still hidden, while the other counters show
        # their pages:
        scrub.fill(str(math.ceil(self.slider_at(self.PAX_COUNTER_FROM)) - 1))
        expect(self.page.get_by_test_id("row-pages")).to_be_visible()
        expect_shown(False)

        # on the first step at or after it, it shows:
        scrub.fill(str(math.ceil(self.slider_at(self.PAX_COUNTER_FROM))))
        expect_shown(True)

        # at the end of the film, it still shows:
        scrub.fill("1000")
        expect(self.page.get_by_test_id("play")).to_have_attribute(
            "data-state", "ended"
        )
        expect_shown(True)

        # back at the start, it is hidden again:
        scrub.fill("0")
        expect_shown(False)
        self.assert_no_errors(self.opened)

    def test_the_counters_are_dimmed_from_the_real_pages_on(self) -> None:
        """The header's counters, which count the eight books of the small example, show in full until the real pages
        of 4 KB come in at 61.8 s; then they fade, and from 62.4 s on they are dimmed, to at most half their opacity,
        and marked ``data-dimmed="true"``, through the real pages, the verdict and the result, still with the counts of
        the three scans. Back at the start, they show in full again.

        Fails if the counters stay in full beside the real pages, whose numbers they do not count, if they are dimmed
        already in the PAX step, if they are marked dimmed while they still fade, or if they show in full again in the
        verdict or the result.
        """
        scrub = self.page.get_by_test_id("scrub")
        box = self.page.get_by_test_id("counters")

        # on the last step of the slider before the real pages come in, the counters show in full, with the three
        # scans counted:
        scrub.fill(str(math.ceil(self.slider_at(self.REAL_PAGES_FROM)) - 1))
        self.assertEqual(1, self.counters_opacity())
        expect(box).to_have_attribute("data-dimmed", "false")
        self.assertEqual(self.COUNTED, self.counters())

        # halfway through the fade, they are no longer in full, but not yet marked dimmed:
        scrub.fill(
            str(
                round(self.slider_at((self.REAL_PAGES_FROM + self.COUNTERS_DIMMED) / 2))
            )
        )
        self.assertLess(self.counters_opacity(), 1)
        expect(box).to_have_attribute("data-dimmed", "false")

        # from 62.4 s on, they are dimmed:
        scrub.fill(str(math.ceil(self.slider_at(self.COUNTERS_DIMMED))))
        self.assertLessEqual(self.counters_opacity(), 0.5)
        expect(box).to_have_attribute("data-dimmed", "true")

        # still at the end of the verdict step, where Next stops:
        self.next_to("verdict")
        self.assertLessEqual(self.counters_opacity(), 0.5)
        expect(box).to_have_attribute("data-dimmed", "true")

        # and at the end of the film, in the result step, still with the three scans counted:
        scrub.fill("1000")
        expect(self.page.get_by_test_id("play")).to_have_attribute(
            "data-state", "ended"
        )
        self.assertLessEqual(self.counters_opacity(), 0.5)
        expect(box).to_have_attribute("data-dimmed", "true")
        self.assertEqual(self.COUNTED, self.counters())

        # back at the start, they show in full:
        scrub.fill("0")
        self.assertEqual(1, self.counters_opacity())
        expect(box).to_have_attribute("data-dimmed", "false")
        self.assert_no_errors(self.opened)

    def test_next_marks_the_pages_each_scan_reads_and_those_it_leaves_out(
        self,
    ) -> None:
        """With sound off, Next stops at the end of each step with the pages in memory marked as far as the film has
        come: no pages before step 03 brings them in; then the row layout's two pages, not yet read; both read once the
        row layout's scan is done; then the column layout's three pages, one per column, with page 2, that of the
        prices, read and pages 0 and 1, those of the titles and the authors, "not read"; then PAX's two pages, both
        read. The marks stay so to the end of the film.

        Fails if a layout's pages are marked before the film brings them in, if the column layout has another number
        of pages than one per column, if a scan marks a page read of which it loads no line, if it does not mark the
        pages it leaves out as "not read", or if the marks change after the scans.
        """
        # at the end of each step, which layouts' pages are marked, and the state of each page of the row layout, the
        # column layout and PAX:
        stops: list[tuple[str, PageMarks]] = [
            (
                "memory",
                PageMarks("", "none,none", "none,none,none", "none,none"),
            ),
            (
                "cache-lines",
                PageMarks("row", "none,none", "none,none,none", "none,none"),
            ),
            (
                "row-layout",
                PageMarks("row", "read,read", "none,none,none", "none,none"),
            ),
            (
                "column-layout",
                PageMarks(
                    "row,column", "read,read", "not-read,not-read,read", "none,none"
                ),
            ),
            (
                "pax-layout",
                PageMarks(
                    "row,column,pax",
                    "read,read",
                    "not-read,not-read,read",
                    "read,read",
                ),
            ),
        ]
        for stop_type, marks in stops:
            with self.subTest(step=stop_type):
                # Next stops at the end of the step:
                self.next_to(stop_type)
                self.assertEqual(marks, self.page_marks(self.page))

        # at the end of the film, the pages are marked as after the PAX step:
        self.page.get_by_test_id("scrub").fill("1000")
        expect(self.page.get_by_test_id("play")).to_have_attribute(
            "data-state", "ended"
        )
        self.assertEqual(stops[-1][1], self.page_marks(self.page))
        self.assert_no_errors(self.opened)

    def test_the_real_pages_count_what_select_max_price_reads_of_512_books(
        self,
    ) -> None:
        """The real pages step shows the same 512 books in each layout, on pages of 4 KB. For each layout, the page
        counts the pages that SELECT MAX(price) reads and does not read, the cache lines it reads and the share of
        prices among their bytes, and notes them in ``data-real-{layout}-pages``, ``-not-read``, ``-lines`` and
        ``-share`` of ``stage``. They are the numbers computed here byte by byte from the sizes of a book, its
        attributes, a page and a cache line (see expected_real_reads), and those that decision 054 states
        (REAL_READS_OF_DECISION). So the step makes its point: PAX reads as few lines as the column layout, but as
        many pages as the row layout, and only the column layout leaves pages unread.

        Fails if a layout of the real pages puts an attribute elsewhere (e.g. PAX's prices spread over more lines, or
        the column layout's authors and prices on one page), or if the page counts the pages, the lines or the share
        wrongly.
        """
        shown: dict[str, RealReads] = self.real_reads_shown()
        computed: dict[str, RealReads] = {
            layout: self.expected_real_reads(layout) for layout in self.LAYOUTS
        }

        # the numbers computed from the sizes are those that decision 054 states:
        self.assertEqual(self.REAL_READS_OF_DECISION, computed)

        # each layout's numbers on the page are those computed from the sizes:
        self.assertEqual(computed, shown)

        # PAX reads as few lines as the column layout, fewer than the row layout:
        self.assertEqual(shown["column"].lines, shown["pax"].lines)
        self.assertLess(shown["pax"].lines, shown["row"].lines)

        # but as many pages as the row layout, every page; only the column layout leaves pages unread:
        self.assertEqual(shown["row"].pages, shown["pax"].pages)
        self.assertEqual(
            {"row": 0, "pax": 0},
            {layout: shown[layout].not_read for layout in ["row", "pax"]},
        )
        self.assertGreater(shown["column"].not_read, 0)
        self.assert_no_errors(self.opened)

    def test_the_real_pages_are_read_layout_after_layout(self) -> None:
        """In the real pages step, the real pages of the three layouts come in from 61.8 s, all waiting to be read.
        Then the row layout's are read from 63.2 s (first the pages read get their green frames, then their lines read
        light up, 1.7 s in all), the column layout's from 65.2 s and PAX's from 67.2 s, each once the one before is
        done; by 68.9 s all are read, and from 73.6 s the real pages are gone. ``data-real-state-{layout}`` of
        ``stage`` notes it: ``hidden``, ``waiting``, ``reading`` or ``read``. Scrubbed back through the step, each
        moment shows the same again, and so does a page opened at one of them (``?t=…&paused``).

        Each time lies halfway between two events, at least 0.1 s from both, which the test asserts. Fails if the
        layouts are read in another order or at the same time, if one is read before the real pages show or shown
        after they are gone, if a layout falls back from read while the next one is read, or if a scrub back keeps a
        later state.
        """
        scrub = self.page.get_by_test_id("scrub")
        step_from: dict[str, float] = dict(zip(self.STEP_TYPES, self.STEPS_FROM))
        read: dict[str, float] = self.REAL_READ
        done: dict[str, float] = {
            layout: at + self.REAL_FRAME_LEAD + self.REAL_READ_DURATION
            for layout, at in read.items()
        }
        hidden: tuple[str, str, str] = ("hidden", "hidden", "hidden")

        # the stretches between two events, and the states of the row layout, the column layout and PAX in each:
        stretches: list[tuple[float, float, tuple[str, str, str]]] = [
            (step_from["real-pages"], self.REAL_PAGES_FROM, hidden),
            (
                self.REAL_PAGES_FROM + self.REAL_PAGES_FADE,
                read["row"],
                ("waiting", "waiting", "waiting"),
            ),
            (read["row"], done["row"], ("reading", "waiting", "waiting")),
            (done["row"], read["column"], ("read", "waiting", "waiting")),
            (read["column"], done["column"], ("read", "reading", "waiting")),
            (done["column"], read["pax"], ("read", "read", "waiting")),
            (read["pax"], done["pax"], ("read", "read", "reading")),
            (
                done["pax"],
                self.REAL_PAGES_UNTIL - self.REAL_PAGES_FADE,
                ("read", "read", "read"),
            ),
            (self.REAL_PAGES_UNTIL, step_from["result"], hidden),
        ]

        # the slider's position halfway through each stretch, and its time, at least 0.1 s from both events:
        positions: list[int] = []
        for after, before, _ in stretches:
            position: int = round(self.slider_at((after + before) / 2))
            seconds: float = position * self.LENGTH / 1000
            self.assertGreaterEqual(seconds, after + 0.1, (after, before))
            self.assertLessEqual(seconds, before - 0.1, (after, before))
            positions.append(position)

        # scrubbed forward through the step, and then back, each moment shows its states:
        moments: list[tuple[int, tuple[str, str, str]]] = [
            (position, states) for position, (_, _, states) in zip(positions, stretches)
        ]
        for position, states in [*moments, *reversed(moments)]:
            with self.subTest(position=position):
                scrub.fill(str(position))
                self.assertEqual(states, self.real_states(self.page))

        # a page opened while the column layout's real pages are read shows the same:
        position, states = moments[4]
        fresh: OpenedPage = self.open_page(
            ROW_OR_COLUMN_PAGE, query=f"?t={position * self.LENGTH / 1000:.3f}&paused"
        )
        expect(fresh.page.get_by_test_id("scrub")).to_have_value(str(position))
        self.assertEqual(states, self.real_states(fresh.page))
        self.assert_no_errors(fresh)
        self.assert_no_errors(self.opened)

    def test_scrubbing_back_shows_what_a_page_opened_there_shows(self) -> None:
        """Scrubbed to the end of the PAX scan, where all three scans are done, and back, the counters and the pages in
        memory show what belongs to that earlier time, and the same as a page freshly opened there
        (``?t=…&paused``). A page is read as the read head reaches the first line the scan loads of it, before that
        line arrives in the cache (first the page, then its lines):

        - while PAX's second line is on its way to the cache, both its pages are read and counted, but only its first
          line (2 pages, 1 line, 64 B loaded, 32 B used);
        - between the arrival of its first line and the load of its second, its page 0 is read, page 1 not yet (1 page,
          1 line, 64 B loaded, 32 B used);
        - while its first line is on its way, its page 0 is read and counted, but no line (1 page, 0 lines);
        - once PAX is complete, before the head reaches its first line, PAX counts nothing and none of its pages is
          read;
        - in the PAX step before PAX is complete, its pages are not marked;
        - between the arrival of the column layout's line of prices and the end of its scan, the column layout is
          counted and its page 2 read, but its pages 0 and 1 are not yet marked "not read";
        - while the row layout's third line is on its way, both its pages are read, but only its first two lines are
          counted (2 pages, 2 lines, 128 B loaded, 32 B used);
        - before step 03 brings in pages, nothing is counted, and no page shows, neither in the counters nor in memory.

        So the counters and the pages are a pure function of the film's time. Each time lies halfway between two
        events (e.g. a line loaded and its arrival in the cache), at least 0.1 s from both, which the test asserts, so
        that a shifted timeline fails the test instead of moving a time past an event. Fails if a page is read before
        the head reaches its first line or only once that line has arrived, if a line is counted before its copy has
        arrived in the cache, if a page is marked "not read" before its scan has ended, if the counters or the pages
        keep a later state after a scrub back, or if a page opened at that time shows something else.
        """
        scrub = self.page.get_by_test_id("scrub")
        step_from: dict[str, float] = dict(zip(self.STEP_TYPES, self.STEPS_FROM))
        pax_first, pax_second = self.LOADS["pax"]
        column_line: float = self.LOADS["column"][0]
        row_third: float = self.LOADS["row"][2]
        # the pages at the end of the PAX scan:
        done: PageMarks = PageMarks(
            "row,column,pax", "read,read", "not-read,not-read,read", "read,read"
        )

        stretches: list[RowOrColumnPageTest.Stretch] = [
            self.Stretch(
                after=pax_second,
                before=pax_second + self.LOAD_DURATION,
                counted={**self.COUNTED, "pax": self.PAX_SECOND_LINE_ON_ITS_WAY},
                pages="visible",
                marks=done,
            ),
            self.Stretch(
                after=pax_first + self.LOAD_DURATION,
                before=pax_second,
                counted={**self.COUNTED, "pax": self.PAX_FIRST_LINE_ARRIVED},
                pages="visible",
                marks=done._replace(pax="read,none"),
            ),
            self.Stretch(
                after=pax_first,
                before=pax_first + self.LOAD_DURATION,
                counted={**self.COUNTED, "pax": self.PAX_FIRST_LINE_ON_ITS_WAY},
                pages="visible",
                marks=done._replace(pax="read,none"),
            ),
            self.Stretch(
                after=self.PAGES_FROM["pax"],
                before=pax_first,
                counted={**self.COUNTED, "pax": self.NOT_COUNTED},
                pages="visible",
                marks=done._replace(pax="none,none"),
            ),
            self.Stretch(
                after=step_from["pax-layout"],
                before=self.PAGES_FROM["pax"],
                counted={**self.COUNTED, "pax": self.NOT_COUNTED},
                pages="visible",
                marks=done._replace(shown="row,column", pax="none,none"),
            ),
            self.Stretch(
                after=column_line + self.LOAD_DURATION,
                before=self.SCAN_DONE["column"],
                counted={**self.COUNTED, "pax": self.NOT_COUNTED},
                pages="visible",
                marks=done._replace(
                    shown="row,column", column="none,none,read", pax="none,none"
                ),
            ),
            self.Stretch(
                after=row_third,
                before=row_third + self.LOAD_DURATION,
                counted={
                    "row": self.ROW_THIRD_LINE_ON_ITS_WAY,
                    "column": self.NOT_COUNTED,
                    "pax": self.NOT_COUNTED,
                },
                pages="visible",
                marks=PageMarks("row", "read,read", "none,none,none", "none,none"),
            ),
            self.Stretch(
                after=step_from["cache-lines"],
                before=self.PAGES_FROM["row"],
                counted={layout: self.NOT_COUNTED for layout in self.LAYOUTS},
                pages="hidden",
                marks=PageMarks("", "none,none", "none,none,none", "none,none"),
            ),
        ]
        # the first step of the slider at or after the end of the PAX scan:
        scan_done: int = math.ceil(self.slider_at(self.SCAN_DONE["pax"]))
        for stretch in stretches:
            with self.subTest(after=stretch.after, before=stretch.before):
                # the slider's position halfway between the two events, and its time, at least 0.1 s from each:
                position: int = round(
                    self.slider_at((stretch.after + stretch.before) / 2)
                )
                seconds: float = position * self.LENGTH / 1000
                self.assertGreaterEqual(seconds, stretch.after + 0.1)
                self.assertLessEqual(seconds, stretch.before - 0.1)

                # scrubbed to the end of the PAX scan, the counters show all three scans counted, with their pages,
                # and every page in memory is marked read or not read:
                scrub.fill(str(scan_done))
                self.assertEqual(self.COUNTED, self.counters())
                shown: RowOrColumnPageTest.ScansShown = self.scans_shown(self.page)
                self.assertEqual(
                    {layout: "visible" for layout in self.LAYOUTS}, shown["pages"]
                )
                self.assertEqual(done, shown["marks"])

                # scrubbed back, they show what belongs to that time; the pages of PAX's counter follow its row, which
                # shows only from when PAX's title appears:
                scrub.fill(str(position))
                self.assertEqual(stretch.counted, self.counters())
                shown = self.scans_shown(self.page)
                self.assertEqual(
                    {
                        layout: (
                            "hidden"
                            if layout == "pax" and seconds < self.PAX_COUNTER_FROM
                            else stretch.pages
                        )
                        for layout in self.LAYOUTS
                    },
                    shown["pages"],
                )
                self.assertEqual(stretch.marks, shown["marks"])

                # a page opened at that time shows the same, once it has drawn it:
                fresh: OpenedPage = self.open_page(
                    ROW_OR_COLUMN_PAGE, query=f"?t={seconds:.3f}&paused"
                )
                expect(fresh.page.get_by_test_id("scrub")).to_have_value(str(position))
                self.assertEqual(
                    self.scans_shown(fresh.page), self.scans_shown(self.page)
                )
                self.assert_no_errors(fresh)
                # close the fresh page before the next one opens, not only at the end of the test:
                fresh.page.context.close()
        self.assert_no_errors(self.opened)

    def test_a_time_outside_the_film_opens_it_at_its_start_or_its_end(self) -> None:
        """Opened at a time before the film's start or after its end (``?t=-5&paused``, ``?t=999&paused``), the page
        opens at its start (0 s) or at its end (83.2 s): the slider at 0 or 1000, the narration at the start or the end.

        Fails if the page does not clamp the time to the film: no caption covers a time outside it, so the page would
        throw an error while it draws the narration.
        """
        for query, slider, stop_type in [
            ("?t=-5&paused", "0", "start"),
            ("?t=999&paused", "1000", "end"),
        ]:
            with self.subTest(query=query):
                opened: OpenedPage = self.open_page(ROW_OR_COLUMN_PAGE, query=query)
                narration = opened.page.get_by_test_id("narration")

                # the page has drawn the start or the end of the film:
                expect(narration).to_have_attribute("data-stop-type", stop_type)
                expect(opened.page.get_by_test_id("scrub")).to_have_value(slider)
                self.assert_no_errors(opened)
                # close the page before the next one opens, not only at the end of the test:
                opened.page.context.close()

    def test_the_receipt_lists_row_column_and_pax_and_ends_with_the_footnote(
        self,
    ) -> None:
        """At the end of the verdict step, the receipt shows all its items, from top to bottom: the heads of its
        input/output and its memory column; the row layout, the column layout and PAX, in the film's order; and the
        totals of the column layout and of PAX. The footnote says on how many pages one whole book lies in each layout.

        Fails if the items are out of order, if one is not yet printed when the verdict step ends (each comes 0.35 s
        after the one above it), or if the footnote says something else. The numbers of the items are checked by
        test_the_receipt_counts_the_real_pages_in_io_and_memory.
        """
        receipt = self.page.get_by_test_id("receipt")
        footnote = self.page.get_by_test_id("footnote")

        # Next stops at the end of the verdict step, where the receipt shows:
        self.next_to("verdict")
        expect(receipt).to_have_css("opacity", "1")

        # its items, from top to bottom, are the heads, the three layouts in the film's order and the two totals, and
        # each is printed:
        items: list[str] = self.page.get_by_test_id("receipt-lines").evaluate(
            "list => [...list.children].map((item) => item.dataset.testid)"
        )
        self.assertEqual(self.RECEIPT_ITEMS, items)
        for test_id in self.RECEIPT_ITEMS:
            expect(self.page.get_by_test_id(test_id)).to_have_css("opacity", "1")

        # the footnote shows below:
        expect(footnote).to_have_css("opacity", "1")
        expect(footnote).to_have_text(self.FOOTNOTE)
        self.assert_no_errors(self.opened)

    def test_the_receipt_counts_the_real_pages_in_io_and_memory(self) -> None:
        """At the end of the verdict step, the receipt names the table at real size, "512 books · pages of 4 KB", and
        heads two columns: input/output, the pages the database reads, and memory, the cache lines the processor
        loads. For each layout it gives both, each with its bytes, e.g. "4 · 16 KB" and "256 · 16 KB" for the row
        layout. The totals say under the same heads how many times fewer pages and cache lines the column layout and
        PAX read than the row layout: "4× fewer" and "4× fewer", and for PAX "same" (its pages) and "4× fewer". All
        numbers are computed here from the sizes of a book, its attributes, a page and a cache line (see
        expected_real_reads); the real pages step shows the same (see
        test_the_real_pages_count_what_select_max_price_reads_of_512_books).

        Fails if the receipt counts the eight books of the small example (e.g. PAX with 2 pages and 2 lines), puts
        input/output and memory in each other's column, counts the bytes of pages or lines wrongly, or if a total
        compares other layouts or writes a saving of 1× instead of "same".
        """
        expected: dict[str, RealReads] = {
            layout: self.expected_real_reads(layout) for layout in self.LAYOUTS
        }

        # Next stops at the end of the verdict step, where the receipt shows:
        self.next_to("verdict")
        expect(self.page.get_by_test_id("receipt")).to_have_css("opacity", "1")

        # below its head, the size of the table; then the heads of its two columns:
        expect(self.page.get_by_test_id("receipt-scale")).to_have_text(
            f"{self.REAL_BOOKS} books · pages of {self.as_bytes(self.REAL_PAGE_BYTES)}"
        )
        expect(self.page.get_by_test_id("receipt-heads")).to_have_text(
            "input/output pages memory cache lines", use_inner_text=True
        )

        # each layout's line, read as shown: its name, its input/output (the pages read and their bytes) and its memory
        # traffic (the cache lines read and their bytes):
        for layout in self.LAYOUTS:
            with self.subTest(layout=layout):
                read: RealReads = expected[layout]
                io: str = (
                    f"{read.pages} · {self.as_bytes(read.pages * self.REAL_PAGE_BYTES)}"
                )
                memory: str = (
                    f"{read.lines} · {self.as_bytes(read.lines * self.LINE_BYTES)}"
                )
                expect(self.page.get_by_test_id(f"receipt-{layout}-io")).to_have_text(
                    io
                )
                expect(
                    self.page.get_by_test_id(f"receipt-{layout}-memory")
                ).to_have_text(memory)
                expect(self.page.get_by_test_id(f"receipt-{layout}")).to_have_text(
                    f"{self.RECEIPT_NAMES[layout]} {io} {memory}", use_inner_text=True
                )

        # the totals: how much less the column layout and PAX read than the row layout, under the same two heads:
        for test_id, layout in [
            ("receipt-total", "column"),
            ("receipt-total-pax", "pax"),
        ]:
            with self.subTest(total=test_id):
                pages, lines = self.savings(layout)
                expect(
                    self.page.get_by_test_id(f"receipt-{layout}-io-saved")
                ).to_have_text(pages)
                expect(
                    self.page.get_by_test_id(f"receipt-{layout}-memory-saved")
                ).to_have_text(lines)
                expect(self.page.get_by_test_id(test_id)).to_have_text(
                    f"{self.RECEIPT_NAMES[layout]} {pages} {lines}",
                    use_inner_text=True,
                )
        self.assert_no_errors(self.opened)

    def test_on_a_phone_held_sideways_the_receipt_leaves_the_narration_free(
        self,
    ) -> None:
        """On phones held sideways (844 × 390 px and the lower 800 × 360 px), at the end of the verdict step, where the
        receipt shows in full with the subtitles below it, the receipt's lower edge is at or above the narration's
        upper edge, and the hint for the sound (shown while the sound is off) gives way to the receipt, which it would
        cover; on a large screen (1280 × 720 px) the hint stays.

        Fails if the receipt runs into the narration on a low screen, e.g. after a line was added to it or its text
        was set larger, or if the hint covers the receipt's numbers there, or if it is hidden on a large screen too.
        """
        # Next stops at the end of the verdict step, where the receipt and the narration show:
        self.next_to("verdict")
        expect(self.page.get_by_test_id("receipt")).to_have_css("opacity", "1")
        expect(self.page.get_by_test_id("nar-text")).to_be_visible()

        for width, height in [(844, 390), (800, 360)]:
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})
                # once the page has laid them out for the window, the receipt ends above the narration:
                self.page.evaluate(
                    "() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"
                )
                receipt: FloatRect = self.box_of("receipt")
                narration: FloatRect = self.box_of("narration")
                self.assertLessEqual(
                    receipt["y"] + receipt["height"],
                    narration["y"],
                    f"the receipt {receipt} runs into the narration {narration}",
                )
                expect(self.page.get_by_test_id("sound-hint")).to_be_hidden()

        # on a large screen, the hint for the sound stays beside the receipt:
        self.page.set_viewport_size({"width": 1280, "height": 720})
        expect(self.page.get_by_test_id("sound-hint")).to_be_visible()
        self.assert_no_errors(self.opened)

    def test_the_slider_has_a_segment_per_step_as_long_as_the_step(self) -> None:
        """The slider is cut into nine segments, ``segment-1`` to ``segment-9``, one per step in the film's order, each
        as long as its step: its flex-grow is the step's length in seconds, from the step's beginning to the next one's
        (the last one to the film's end). So each segment begins and ends where the slider's thumb stands at the
        beginning and the end of its step, give or take the gap between two segments.

        Fails if a step has no segment or one too many, if a segment is as long as another step (e.g. after a step was
        added to the film but not to the slider), or if the segments do not line up with the thumb (e.g. if they are
        not set in by half the thumb's width).
        """
        segments = self.page.get_by_test_id("segments")
        ends: list[float] = [*self.STEPS_FROM[1:], self.LENGTH]

        # the page has made the segments when it has set up its controls; one per step, in order:
        expect(self.page.get_by_test_id("scrub")).to_be_enabled()
        test_ids: list[str] = segments.evaluate(
            "box => [...box.children].map((segment) => segment.dataset.testid)"
        )
        self.assertEqual(
            [f"segment-{k}" for k in range(1, len(self.STEP_TYPES) + 1)], test_ids
        )

        # a segment's edges may lie up to the gap between two segments (and a pixel for rounding) from the thumb:
        gap: float = segments.evaluate(
            "box => parseFloat(getComputedStyle(box).columnGap)"
        )
        scrub_x: float = self.box_of("scrub")["x"]
        for k, (start, end) in enumerate(zip(self.STEPS_FROM, ends), 1):
            with self.subTest(segment=k):
                # the segment is as long as its step:
                grow: float = float(
                    self.page.get_by_test_id(f"segment-{k}").evaluate(
                        "segment => getComputedStyle(segment).flexGrow"
                    )
                )
                self.assertAlmostEqual(end - start, grow)

                # it begins and ends where the thumb stands at the beginning and the end of its step:
                box: FloatRect = self.box_of(f"segment-{k}")
                self.assertAlmostEqual(
                    scrub_x + self.thumb_at(start), box["x"], delta=gap + 1
                )
                self.assertAlmostEqual(
                    scrub_x + self.thumb_at(end), box["x"] + box["width"], delta=gap + 1
                )
        self.assert_no_errors(self.opened)

    def test_hovering_the_slider_names_the_step_under_the_pointer(self) -> None:
        """Hovering the slider shows a tip above it that names the step under the pointer and the time there in
        minutes and whole seconds (e.g. "06/09 · PAX layout · 0:55" at 55.5 s), in each of the nine steps; the tip
        hides when the pointer leaves the slider.

        Each time lies half a second after a whole second, about halfway through its step, so that the pointer's
        rounding to a pixel cannot change the second shown. Fails if the tip names a neighbouring step or another time
        (e.g. if it maps the pointer to another time than the slider does), or if it stays after the pointer has left.
        """
        scrub = self.page.get_by_test_id("scrub")
        tip = self.page.get_by_test_id("scrub-tip")
        ends: list[float] = [*self.STEPS_FROM[1:], self.LENGTH]

        # before the pointer comes, there is no tip; the page reacts to the pointer once it has set up its controls:
        expect(tip).to_be_hidden()
        expect(scrub).to_be_enabled()
        height: float = self.box_of("scrub")["height"]

        # the pointer about the middle of each step: the tip names the step, and the time in minutes and seconds:
        for name, start, end in zip(self.STEP_NAMES, self.STEPS_FROM, ends):
            with self.subTest(step=name):
                seconds: float = math.floor((start + end) / 2) + 0.5
                minutes, whole = divmod(math.floor(seconds), 60)
                scrub.hover(position={"x": self.thumb_at(seconds), "y": height / 2})
                expect(tip).to_be_visible()
                expect(tip).to_have_text(f"{name} · {minutes}:{whole:02d}")

        # the pointer leaves the slider, and the tip hides:
        self.page.mouse.move(0, 0)
        expect(tip).to_be_hidden()
        self.assert_no_errors(self.opened)

    def test_on_a_phone_the_slider_has_a_line_of_its_own(self) -> None:
        """On a phone held upright (360 × 780 and 390 × 844 px), the slider stands on a line of its own above the
        buttons and is at least 250 px wide, so that its nine segments, the shortest of them 3 s of the film's 83.2 s,
        can still be seen and hit.

        Fails if the slider shares its line with the buttons and the clock, which leave it too little room.
        """
        for width, height in self.PHONES:
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})

                # the slider is wide enough, and the buttons stand below it:
                scrub: FloatRect = self.box_of("scrub")
                self.assertGreaterEqual(scrub["width"], self.PHONE_SLIDER_WIDTH)
                self.assertGreaterEqual(
                    self.box_of("play")["y"], scrub["y"] + scrub["height"]
                )
        self.assert_no_errors(self.opened)

    def test_review_clips_play_one_after_the_other_and_then_pause(self) -> None:
        """Opened with ``?clips=10-11,20-21``, the page stands at 10 s with the hint "review clip 1/2". Play plays from
        10 s to 11 s, jumps to 20 s ("review clip 2/2") and plays to 21 s, where the film pauses with the hint "end of
        review clips · press space to play on"; meanwhile the slider shows no time outside the two clips. Space then
        plays on past 21 s, and the hint hides.

        Fails if a clip is skipped or played past its end, if the clips play in another order, if the film does not
        pause after the last clip or pauses without the hint, or if it does not play on after it.
        """
        opened: OpenedPage = self.open_page(
            ROW_OR_COLUMN_PAGE, query="?clips=10-11,20-21"
        )
        page: Page = opened.page
        scrub = page.get_by_test_id("scrub")
        hint = page.get_by_test_id("clips-hint")
        play = page.get_by_test_id("play")
        clips: list[tuple[float, float]] = [(10, 11), (20, 21)]

        # opened, the film stands at the first clip's start, and the hint names the clip:
        expect(scrub).to_have_value(str(round(self.slider_at(clips[0][0]))))
        expect(hint).to_have_text("review clip 1/2")

        # every frame from now on notes the slider's position; Play: the second clip follows the first:
        scrub.evaluate("""(scrub) => {
                window.positions = [];
                const note = () => { window.positions.push(Number(scrub.value)); requestAnimationFrame(note); };
                requestAnimationFrame(note);
            }""")
        play.click()
        expect(hint).to_have_text("review clip 2/2", timeout=FILM_TIMEOUT)

        # after the second clip, the film pauses at its end, with the hint that the clips are over:
        expect(hint).to_have_text(
            "end of review clips · press space to play on", timeout=FILM_TIMEOUT
        )
        expect(play).to_have_attribute("data-state", "paused")
        expect(scrub).to_have_value(str(math.floor(self.slider_at(clips[1][1]) + 0.5)))

        # the slider showed no time outside the clips, and the first clip, then the second:
        positions: list[int] = page.evaluate("window.positions")
        windows: list[tuple[int, int]] = [
            (math.floor(self.slider_at(start)), math.ceil(self.slider_at(end)))
            for start, end in clips
        ]
        self.assertEqual(
            [],
            [
                at
                for at in positions
                if not any(low <= at <= high for low, high in windows)
            ],
            "times outside the clips",
        )
        in_first: list[bool] = [at <= windows[0][1] for at in positions]
        self.assertEqual(sorted(in_first, reverse=True), in_first, positions)
        self.assertEqual({True, False}, set(in_first), positions)

        # Space plays on past the clips' end, without the hint:
        page.keyboard.press("Space")
        expect(play).to_have_attribute("data-state", "playing")
        expect(hint).to_be_hidden()
        self.let_film_play_until(page, math.ceil(self.slider_at(clips[1][1])) + 1)
        self.assert_no_errors(opened)

    def test_a_step_range_plays_from_its_first_step_to_the_end_of_its_last(
        self,
    ) -> None:
        """Opened with ``?step=a-b``, the page stands at the start of step a with the hint "review clip 1/1", and Play
        plays to the end of step b, where the film pauses with the hint that the review clips are over: ``?step=7-8``
        opens at the start of step 07 (61.2 s), and ``?step=1-2`` plays to the end of step 02 (13 s).

        The start is checked on a range in the middle of the film, the end on the shortest range that ends neither
        with its first step nor with the film, so that the test plays only 13 s. Fails if a range starts elsewhere
        (e.g. at the film's start), ends at the end of its first step or at the film's end, or is not played as a
        review clip.
        """
        # opened with ?step=7-8, the film stands at the start of step 07, in a review clip:
        opened: OpenedPage = self.open_page(ROW_OR_COLUMN_PAGE, query="?step=7-8")
        expect(opened.page.get_by_test_id("scrub")).to_have_value(
            str(round(self.slider_at(self.STEPS_FROM[6])))
        )
        expect(opened.page.get_by_test_id("clips-hint")).to_have_text("review clip 1/1")
        self.assert_no_errors(opened)
        # close the page before the next one opens, not only at the end of the test:
        opened.page.context.close()

        # opened with ?step=1-2, it stands at the start of step 01, in a review clip:
        opened = self.open_page(ROW_OR_COLUMN_PAGE, query="?step=1-2")
        page: Page = opened.page
        scrub = page.get_by_test_id("scrub")
        hint = page.get_by_test_id("clips-hint")
        expect(scrub).to_have_value("0")
        expect(hint).to_have_text("review clip 1/1")

        # Space plays it (in a small window, where each drawing is a little cheaper and the Play button may lie
        # outside the window); the film plays in real time, and a frame advances it by at most 0.1 s (see
        # FILM_TIMEOUT), so on a slow machine, where a frame may take up to a second, it plays up to ten times slower:
        ends: float = self.STEPS_FROM[2]
        timeout: float = FILM_TIMEOUT + 10 * ends * 1000
        page.set_viewport_size({"width": 320, "height": 180})
        page.keyboard.press("Space")

        # the film plays to the end of step 02 and pauses there, with the hint that the clips are over:
        expect(hint).to_have_text(
            "end of review clips · press space to play on", timeout=timeout
        )
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "paused")
        expect(scrub).to_have_value(str(math.floor(self.slider_at(ends) + 0.5)))
        self.assert_no_errors(opened)

    def test_the_name_of_a_step_shows_top_left_as_the_step_begins(self) -> None:
        """As each of the steps 02 to 08 begins, its number and name show top left (e.g. "Step 05/09" and "Column
        layout"), from 0.3 s after the step's beginning for 3 s; before and after that, the step title is hidden. In
        step 01 and step 09, where the terminal stands top left, it never shows. ``data-step`` of ``step-title`` names
        the step (1 to 9), ``data-shown`` whether the title shows (opacity above 0.5).

        Fails if the title shows over the terminal in the first or the last step, names another step than the one
        that begins (e.g. the one before it), shows right as the step begins instead of 0.3 s later, or stays on
        through the step.
        """
        scrub = self.page.get_by_test_id("scrub")
        title = self.page.get_by_test_id("step-title")
        steps: int = len(self.STEP_TYPES)
        for step, (begins, name) in enumerate(zip(self.STEPS_FROM, self.STEP_NAMES), 1):
            with self.subTest(step=name):
                # before the title fades in, while it shows in full, and after it has faded out (at most at the end of
                # the film), whether it shows: in the middle only, and only in the steps 02 to 08:
                middle: float = self.step_title_middle(step)
                after: float = middle + self.STEP_TITLE_FOR / 2 + self.STEP_TITLE_FADE
                moments: list[tuple[float, bool]] = [
                    (begins + self.STEP_TITLE_DELAY / 3, False),
                    (middle, 1 < step < steps),
                    (min(after, self.LENGTH), False),
                ]
                for seconds, shown in moments:
                    scrub.fill(str(round(self.slider_at(seconds))))
                    expect(title).to_have_attribute("data-step", str(step))
                    expect(title).to_have_attribute("data-shown", str(shown).lower())
                    expect(title).to_have_css("opacity", "1" if shown else "0")

                # in the steps 02 to 08, it names the step: its number above, its name below:
                if 1 < step < steps:
                    number, step_name = name.split(" · ", 1)
                    expect(self.page.get_by_test_id("step-title-number")).to_have_text(
                        f"Step {number}"
                    )
                    expect(self.page.get_by_test_id("step-title-name")).to_have_text(
                        step_name
                    )
        self.assert_no_errors(self.opened)

    def test_the_header_leaves_the_terminal_free_on_a_phone(self) -> None:
        """On a phone held upright (360 × 780 and 390 × 844 px), where the three counters stand below the step's name,
        the terminal begins below them: at the start, where it types the query, and in the result step at the end,
        where it prints the result.

        Fails if the terminal stays at its least distance from the top (96 px on a phone) while the header reaches
        further down, i.e. if the page no longer moves its cards below the header.
        """
        scrub = self.page.get_by_test_id("scrub")
        terminal = self.page.get_by_test_id("terminal")
        for width, height in self.PHONES:
            with self.subTest(width=width, height=height):
                self.page.set_viewport_size({"width": width, "height": height})

                # at the start, the terminal shows below the header:
                scrub.fill("0")
                expect(terminal).to_have_css("opacity", "1")
                self.assert_below_the_header("terminal")

                # at the end, in the result step, as well:
                scrub.fill("1000")
                expect(self.page.get_by_test_id("play")).to_have_attribute(
                    "data-state", "ended"
                )
                expect(terminal).to_have_css("opacity", "1")
                self.assert_below_the_header("terminal")
        self.assert_no_errors(self.opened)

    def test_the_header_leaves_the_step_title_free_on_a_phone(self) -> None:
        """On a phone held upright (360 × 780 and 390 × 844 px), where the three counters stand below the step's name,
        the step's name top left begins below them, in each of the steps 02 to 08 where it shows (the header is
        taller where the step's name in it wraps).

        Fails if the step title stays at its least distance from the top (76 px) while the header reaches further
        down, i.e. if the page does not move it below the header.
        """
        scrub = self.page.get_by_test_id("scrub")
        title = self.page.get_by_test_id("step-title")
        for width, height in self.PHONES:
            self.page.set_viewport_size({"width": width, "height": height})
            for step in range(2, len(self.STEP_TYPES)):
                with self.subTest(width=width, height=height, step=step):
                    # while the step's name shows in full, it stands below the header:
                    scrub.fill(str(round(self.slider_at(self.step_title_middle(step)))))
                    expect(title).to_have_css("opacity", "1")
                    self.assert_below_the_header("step-title")
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
        # a tree of height 5 has an inner node as its root, a dict:
        root: Tree = self.trees[-1]
        assert isinstance(root, dict)
        self.assertEqual(1, len(root["keys"]))

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
class StorageHierarchyPageTest(_PageTestCase):
    """Checks the numbers of the storage hierarchy page against the slides (slide set 08, decision 045): where each
    level lies and how many crates it holds, and what the stopwatch, the depth and the fast-forward badge show during
    the cage's rides.

    The page writes each level into a child of the hidden element ``levels``, as data-* attributes; their depths are
    metres below the basement floor, which lies 5 m below the Earth's surface. It writes the state of the cage into
    data-* of ``stage``; there, depths are metres below the surface. A URL with ``?t=<seconds>&paused`` opens the page
    paused at that time of the film.

    Opening the page takes seconds on a GPU emulated in software (as in CI), so the tests share one page, opened in
    setUpClass, and move it to each time they check with the slider (see stage_at). That shows the same as opening the
    page at the time: all the page shows is a function of the film's time. The slider keeps the step ``any`` that
    stage_at gives it for the rest of the tests, so that it can stand at any time of the film, not only at its 1000
    steps. Each test checks only the errors that the shared page has had during the test (see setUp).
    """

    PAGE: Path | None = STORAGE_HIERARCHY_PAGE
    # the page that the tests share, paused, and its levels as read_levels returns them; both set in setUpClass:
    opened: OpenedPage
    shared_levels: tuple[float, dict[str, dict[str, str]]]
    # how many errors and outside requests the shared page had had when the test began; set in setUp:
    errors_before: int
    requests_before: int
    # the page is ready once it has prepared its GPU programs, a few per frame: on a GPU emulated in software, some 6 s
    # on a fast machine and several times that on a slow CI runner, so a wait for it ends after this many milliseconds:
    READY_TIMEOUT: int = 8 * FILM_TIMEOUT

    # the levels below the registers, from the slides: access time in CPU cycles and size in bytes:
    SLIDES: dict[str, tuple[int, int]] = {
        "L1": (4, 48 * 1024),
        "L2": (17, 3 * 1024**2),
        "L3": (84, 36 * 1024**2),
        "DRAM": (570, 32 * 1024**3),
        "NVMe SSD": (285_000, 2 * 1024**4),
        "HARD DISK": (57_000_000, 2 * 1024**4),
    }
    # each level's access time in human time, as the stopwatch writes it once the cage is back:
    HUMAN_TEXTS: dict[str, str] = {
        "L1": "2 s",
        "L2": "8.5 s",
        "L3": "42 s",
        "DRAM": "4 min 45 s",
        "NVMe SSD": "39.6 h",
        "HARD DISK": "330 days",
    }
    # the levels that are a block of crates round the shaft; the hard disk is a platter:
    BLOCKS: list[str] = ["L1", "L2", "L3", "DRAM", "NVMe SSD"]
    # the Earth's radius, and the depth of the basement floor (the CPU core) below the surface (m):
    EARTH_RADIUS: float = 6_371_000
    FLOOR_DEPTH: float = 5
    # the depth of one CPU cycle (m), so that the hard disk's 57,000,000 cycles end at the Earth's centre:
    SCALE: float = (EARTH_RADIUS - FLOOR_DEPTH) / 57_000_000
    # one cycle takes half a second of human time:
    HUMAN_S_PER_CYCLE: float = 0.5
    # a cycle of the CPU (5.7 GHz) in real time, in ns:
    REAL_NS_PER_CYCLE: float = 0.175
    # a crate is one cache line, flat and open at the top: 8 parcels side by side (4 along x, 2 deep), 2.36 m wide (x),
    # as high as a parcel (0.44 m) and 1.08 m deep (z):
    CRATE_BYTES: int = 64
    CRATE_WIDTH: float = 2.36
    CRATE_HEIGHT: float = 0.44
    CRATE_DEPTH: float = 1.08
    # the fast-forward factor while the cage picks up a crate: the level's cycles over L1's 4:
    PICKUP_FACTORS: dict[str, float] = {"L2": 4.25, "HARD DISK": 14_250_000}
    # the levels that send one crate up, pulled from their rack; the NVMe SSD and the hard disk deliver a pallet:
    CRATE_LEVELS: list[str] = ["L1", "L2", "L3", "DRAM"]
    # the platter turns once in this many seconds of film (not to scale: slow enough to watch, plain to see):
    PLATTER_TURN: float = 5
    # the steps of loading a crate at a level of crates, in their order: the robot walks to the cage's open side,
    # reaches into the rack and pulls a crate straight across into the cage:
    LOAD_STEPS: list[str] = ["walk", "reach", "pull", "loaded"]
    # where the crate is, in the order of the loading: none shown, still in the rack, on its way across, in the cage:
    CRATE_PLACES: list[str] = ["", "rack", "gap", "cage"]
    # the steps of the detailed unloading back at the floor after L1, in their order: the robot takes the value out of
    # the crate, turns, walks to the register tray, puts the value in, it is stored, and the robot walks back:
    UNLOAD_STEPS: list[str] = ["take", "turn", "walk", "put", "stored", "back"]
    # the steps of the short unloading back at the floor after L2, L3 and DRAM, in their order: the robot takes the
    # value out of the crate, puts it in (the value flies across into the register), and it is stored:
    SHORT_UNLOAD_STEPS: list[str] = ["take", "put", "stored"]
    # L1's pickup: the robot loads its crate slowly, once, while the voice tells it (s of film):
    LOAD_L1: float = 14.3
    # after L1, the unloading takes this many seconds of film, then the robot stands still this many more, while the
    # text says that only the value goes into a register and the crate stays in L1:
    UNLOAD_L1: float = 6.5
    STILL_AFTER_L1: float = 5.3

    class StopwatchBoxes(TypedDict):
        """Where the stopwatch's fields and labels are at one moment, and what the fields show (see
        test_the_stopwatch_fields_keep_their_places_whatever_the_numbers)."""

        # the left and right edge of each field, then the left edge of each label (px):
        edges: list[float]
        # for each field, the width of its text and of its box (px):
        widths: list[list[int]]
        # the text of each field:
        texts: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        """Opens the page once for all tests of the class, paused at its start, waits until it has drawn its warm-up
        frames, reads its levels (see read_levels) and asserts that it loaded without errors and requested only local
        files; the page's browser context is closed after the last test.
        """
        super().setUpClass()
        cls.opened = cls.open_page_in(
            cls.browser, cls.addClassCleanup, STORAGE_HIERARCHY_PAGE, query="?paused"
        )
        page: Page = cls.opened.page

        # the page has prepared the GPU's programs and textures and drawn a frame:
        expect(page.get_by_test_id("stage")).to_have_attribute(
            "data-ready", "true", timeout=cls.READY_TIMEOUT
        )

        # the script lays out the levels after the fonts have loaded (at most 2.5 s), all in one go:
        levels = page.get_by_test_id("levels")
        expect(levels).to_have_attribute(
            "data-scale", re.compile(r"^\d"), timeout=FILM_TIMEOUT
        )
        scale: float = float(levels.get_attribute("data-scale") or "")
        attributes: dict[str, dict[str, str]] = levels.evaluate(
            """(box) => Object.fromEntries([...box.children].map((level) => [
                level.dataset.key,
                Object.fromEntries([...level.attributes].filter((a) => a.name.startsWith('data-'))
                    .map((a) => [a.name.slice('data-'.length), a.value])),
            ]))"""
        )
        cls.shared_levels = scale, attributes

        # the page loaded without errors and requested only local files (from here on, each test checks its own):
        if cls.opened.errors or cls.opened.outside_requests:
            raise AssertionError(
                f"the page had errors {cls.opened.errors} or requested more than local files "
                f"{cls.opened.outside_requests}"
            )

    def setUp(self) -> None:
        """Notes how many errors and outside requests the shared page has had before the test, so that the test checks
        only those of its own time (see assert_no_new_errors), and checks them once more after the test, for an error
        that comes after the test's last check (e.g. in a frame the page draws later).
        """
        super().setUp()
        self.errors_before = len(self.opened.errors)
        self.requests_before = len(self.opened.outside_requests)
        self.addCleanup(self.assert_no_new_errors)

    def assert_no_new_errors(self) -> None:
        """Asserts that the shared page has neither had an error nor requested anything but a local file since the test
        began."""
        self.assertEqual(
            [], self.opened.errors[self.errors_before :], "the page had errors"
        )
        self.assertEqual(
            [],
            self.opened.outside_requests[self.requests_before :],
            "the page requested more than local files",
        )

    def read_levels(self) -> tuple[float, dict[str, dict[str, str]]]:
        """Returns the levels that setUpClass read from the shared page, and asserts that the page has had no errors
        since the test began.

        @return: the depth of one cycle (``data-scale`` of ``levels``), and for each level, by its ``data-key``, its
            data-* attributes without ``data-``, e.g. for L1 ``{"key": "L1", "crates": "768", "down-from": "...", ...}``
        """
        self.assert_no_new_errors()
        return self.shared_levels

    def stage_at(
        self, seconds: float, phase: str | None
    ) -> tuple[OpenedPage, dict[str, str]]:
        """Moves the shared page to the given time with the slider, waits until it shows that time with the cage in
        the given phase, and reads the stage's data-* attributes without ``data-`` (e.g. ``human-s``).

        The slider pauses the film; the page then shows what it shows when opened at ``?t=<seconds>&paused``.

        @param seconds: the time of the film
        @param phase: the phase of the cage's ride at that time, e.g. ``down``; None: any phase (not waited for)
        @return: the shared page, and the stage's attributes
        """
        page: Page = self.opened.page
        stage = page.get_by_test_id("stage")

        # the slider goes to the time's share of the film's length; with step "any", the slider does not round it to
        # its 1000 steps:
        duration: float = float(stage.get_attribute("data-duration") or "")
        page.get_by_test_id("scrub").evaluate(
            """(s, [seconds, duration]) => {
                s.step = 'any';
                s.value = String(seconds / duration * Number(s.max));
                s.dispatchEvent(new Event('input'));
            }""",
            [seconds, duration],
        )

        # the stage shows that time (its data-t has three decimals):
        page.wait_for_function(
            "([stage, seconds]) => Math.abs(Number(stage.dataset.t) - seconds) <= 1e-3",
            arg=[stage.element_handle(), seconds],
            timeout=FILM_TIMEOUT,
        )
        return self.opened, self.read_stage(self.opened, phase)

    @staticmethod
    def read_stage(
        opened: OpenedPage, phase: str | None, timeout: int = FILM_TIMEOUT
    ) -> dict[str, str]:
        """Waits until the page shows the cage in the given phase, and reads the stage's data-* attributes without
        ``data-`` (e.g. ``human-s``).

        @param opened: a paused page
        @param phase: the phase of the cage's ride at the page's time, e.g. ``down``; None: any phase, once the stage
            shows one (the caller has waited for the page's time)
        @param timeout: how long to wait for the phase (ms); READY_TIMEOUT for a page just opened, which first prepares
            its GPU programs
        @return: the stage's attributes
        """
        stage = opened.page.get_by_test_id("stage")

        # the stage has all its attributes once the script shows a time (opened at the time of a URL, only after the
        # fonts have loaded):
        if phase is None:
            expect(stage).to_have_attribute(
                "data-phase", re.compile(".+"), timeout=timeout
            )
        else:
            expect(stage).to_have_attribute("data-phase", phase, timeout=timeout)
        return stage.evaluate(
            """(stage) => Object.fromEntries([...stage.attributes].filter((a) => a.name.startsWith('data-'))
                .map((a) => [a.name.slice('data-'.length), a.value]))"""
        )

    def stages_between(
        self, start: float, end: float, step: float
    ) -> list[dict[str, str]]:
        """Moves the shared page from start to end in steps with the slider, as stage_at does (any phase), and reads
        the stage each time; all in one call into the page, which shows a time at once when the slider moves, and
        with ``data-sampling`` on the stage, which tells the page not to draw the picture meanwhile (one call per
        step, each drawn, took several minutes of a CI job for the class's sweeps). Asserts that the stage shows each
        time (its data-t, with three decimals).

        @param start: the first time of the film
        @param end: the last time (included when a step lands on it)
        @param step: the time between two readings
        @return: the stage's attributes at each time (without ``data-``, e.g. ``human-s``), in order
        """
        count: int = int((end - start) / step + 1e-9) + 1
        times: list[float] = [start + k * step for k in range(count)]
        page: Page = self.opened.page
        stage = page.get_by_test_id("stage")

        # the stage has its attributes (as read_stage waits for), then each time in turn, read at once:
        expect(stage).to_have_attribute(
            "data-phase", re.compile(".+"), timeout=FILM_TIMEOUT
        )
        stages: list[dict[str, str]] = page.get_by_test_id("scrub").evaluate(
            """(scrub, [times, stage]) => {
                const duration = Number(stage.dataset.duration);
                scrub.step = 'any';
                stage.dataset.sampling = ''; // (the page then computes each time without drawing it)
                try {
                    return times.map((seconds) => {
                        scrub.value = String(seconds / duration * Number(scrub.max));
                        scrub.dispatchEvent(new Event('input'));
                        return Object.fromEntries([...stage.attributes]
                            .filter((a) => a.name.startsWith('data-') && a.name !== 'data-sampling')
                            .map((a) => [a.name.slice('data-'.length), a.value]));
                    });
                } finally {
                    delete stage.dataset.sampling;
                }
            }""",
            [times, stage.element_handle()],
        )
        for seconds, shown in zip(times, stages):
            self.assertAlmostEqual(seconds, float(shown["t"]), delta=1e-3)
        return stages

    def assert_close(self, expected: float, actual: float, what: str) -> None:
        """Asserts that actual equals expected up to rounding: a relative difference of at most 1e-12."""
        self.assertAlmostEqual(expected, actual, delta=1e-12 * abs(expected), msg=what)

    def test_the_levels_lie_at_their_cycles_and_hold_their_crates(self) -> None:
        """Each level's stop, where the cage's floor stops, lies its cycles of the slides below the basement floor, one
        cycle (6,371 km − 5 m) / 57,000,000 deep, so that the hard disk's stop lies at the Earth's centre; each level
        holds one crate per 64 bytes. A block's top layer of crates stands on its stop, so the block's top lies one
        crate's height (0.44 m) above it; the platter's top (its read head) is its stop. The blocks of L1 to the SSD
        have just enough layers of crate places round the shaft, reach down one crate's height per layer, and end above
        the next level's top.

        Fails if the scale, a level's stop or its number of crates drifts from the slides, if a block's top layer does
        not stand on its stop, if a block has a layer too many or too few for its crates, if its bottom does not follow
        its layers, or if a block reaches into the next level.
        """
        scale, levels = self.read_levels()

        # one cycle's depth:
        self.assert_close(self.SCALE, scale, "data-scale")

        # the registers: 80 values (640 bytes) in a tray one cycle below the floor:
        self.assertEqual("80", levels["REGISTERS"]["values"])
        self.assert_close(self.SCALE, float(levels["REGISTERS"]["top"]), "registers")

        # each level's stop lies its cycles deep, and each level holds one crate per 64 bytes:
        for key, (cycles, size) in self.SLIDES.items():
            with self.subTest(level=key):
                self.assertEqual(size // self.CRATE_BYTES, int(levels[key]["crates"]))
                stop: float = cycles * self.SCALE
                self.assert_close(stop, float(levels[key]["stop"]), "stop")

                # the top layer of crates stands on the stop; the platter's top is the stop itself:
                top: float = stop if key == "HARD DISK" else stop - self.CRATE_HEIGHT
                self.assert_close(top, float(levels[key]["top"]), "top")

        # the hard disk's stop lies at the Earth's centre:
        self.assert_close(
            self.EARTH_RADIUS - self.FLOOR_DEPTH,
            float(levels["HARD DISK"]["stop"]),
            "the hard disk's stop",
        )

        # each block: layers of crate places, cols × rows less the holes (the shaft, 3 × 5, and in L1 also the room
        # under the register tray, 3 × 6), with the last layer partly filled:
        next_keys: list[str] = list(self.SLIDES)[1:]
        for key, next_key in zip(self.BLOCKS, next_keys):
            with self.subTest(block=key):
                level: dict[str, str] = levels[key]
                cols, rows, holes = (
                    int(level[name]) for name in ("cols", "rows", "holes")
                )
                crates, layers = int(level["crates"]), int(level["layers"])
                self.assertEqual(33 if key == "L1" else 15, holes)
                places: int = cols * rows - holes
                self.assertLess((layers - 1) * places, crates)
                self.assertLessEqual(crates, layers * places)
                self.assert_close(
                    cols * self.CRATE_WIDTH, float(level["width"]), "width"
                )

                # the block reaches down one crate's height per layer, and ends above the next level's top:
                self.assert_close(
                    float(level["top"]) + layers * self.CRATE_HEIGHT,
                    float(level["bottom"]),
                    "bottom",
                )
                self.assertLessEqual(
                    float(level["bottom"]), float(levels[next_key]["top"])
                )

    def test_the_platter_has_just_enough_rings_for_the_hard_disks_crates(self) -> None:
        """The hard disk's platter holds its crates in one layer on each of its two faces, in rings a crate's depth
        (1.08 m) apart from r0 outwards, each with as many crates as fit along its inner edge: it has just enough rings,
        the last one partly filled, and is as thick as a real platter for its width (1.27 mm for 95 mm).

        Fails if the platter has a ring too many or too few for its crates (e.g. when the crates per ring are counted
        along the outer edge), or if its thickness does not follow its width.
        """
        _, levels = self.read_levels()

        # the rings of both faces hold the crates; one ring fewer would not:
        disk: dict[str, str] = levels["HARD DISK"]
        r0, rings, crates = float(disk["r0"]), int(disk["rings"]), int(disk["crates"])

        def on_both_faces(n: int) -> int:
            """Returns how many crates the n innermost rings of both faces hold."""
            return 2 * sum(
                math.floor(2 * math.pi * (r0 + self.CRATE_DEPTH * i) / self.CRATE_WIDTH)
                for i in range(n)
            )

        self.assertGreaterEqual(on_both_faces(rings), crates)
        self.assertLess(on_both_faces(rings - 1), crates)

        # as thick as a real platter for its width: 1.27 mm for 95 mm:
        radius: float = r0 + rings * self.CRATE_DEPTH
        self.assert_close(2 * radius * 1.27 / 95, float(disk["thickness"]), "thickness")

    def test_after_each_ride_the_stopwatch_shows_the_access_time(self) -> None:
        """Half a second after the cage is back from a level, the stopwatch shows the level's access time from the
        slides: half a second of human time per cycle, the cycles in the header with thousands separators, and the
        human time in the unit of the captions (``HUMAN_TEXTS``); the cage is back at the floor.

        Fails if a round trip takes more or less human time than the slides' cycles (e.g. when the cage's speed or a
        level's depth changes), if the cage does not come back up, or if the header rounds or writes the cycles or the
        human time otherwise.
        """
        _, levels = self.read_levels()
        for key, (cycles, _) in self.SLIDES.items():
            with self.subTest(level=key):
                opened, stage = self.stage_at(
                    float(levels[key]["back-from"]) + 0.5, "back"
                )

                # back at the floor from this level:
                self.assertEqual(key, stage["level"])
                self.assert_close(self.FLOOR_DEPTH, float(stage["depth"]), "depth")

                # the stopwatch shows the access time, in human time and in cycles:
                self.assert_close(
                    cycles * self.HUMAN_S_PER_CYCLE, float(stage["human-s"]), "human-s"
                )
                expect(opened.page.get_by_test_id("sw-cycles")).to_have_text(
                    f"{cycles:,}"
                )
                expect(opened.page.get_by_test_id("sw-human")).to_have_text(
                    self.HUMAN_TEXTS[key]
                )

    def test_the_cage_rides_down_at_one_constant_speed(self) -> None:
        """At the film's time halfway between ``down-from`` and ``pickup-from`` of L2 and of the SSD (still on the ride
        down: the film runs faster the deeper the cage is, so the cage is then far less than halfway down; for the SSD,
        whose pickup begins with a view from afar, some 2 s past the ride's own middle), the cage has gone 4 cycles'
        depth per second of human time (the speed shown, 1.6 km/h), the fast-forward factor is its depth below the
        floor over L1's stop (at least 1), and the depth ruler's marker stands at the cage's depth.

        Fails if the cage's speed changes with the depth (e.g. the film's fast-forward leaks into the stopwatch), if
        the badge's factor is not proportional to the depth, or if the ruler's marker is missing or stands at another
        depth than the cage.
        """
        _, levels = self.read_levels()
        l1_stop: float = float(levels["L1"]["stop"])
        for key in ("L2", "NVMe SSD"):
            with self.subTest(level=key):
                middle: float = (
                    float(levels[key]["down-from"]) + float(levels[key]["pickup-from"])
                ) / 2
                opened, stage = self.stage_at(middle, "down")
                below_floor: float = float(stage["depth"]) - self.FLOOR_DEPTH

                # on the way to this level, between the floor and the level's stop:
                self.assertEqual(key, stage["level"])
                self.assertGreater(below_floor, 0)
                self.assertLess(below_floor, float(levels[key]["stop"]))

                # the speed: 4 cycles' depth per second of human time, about 1.6 km/h:
                self.assert_close(
                    4 * self.SCALE, below_floor / float(stage["human-s"]), "speed"
                )
                self.assertEqual(round(4 * self.SCALE * 3.6, 1), float(stage["speed"]))

                # the fast-forward factor grows with the depth:
                self.assert_close(
                    max(1, below_floor / l1_stop), float(stage["factor"]), "factor"
                )

                # the ruler draws its marker at the cage's depth (read back from where it drew it, so up to rounding):
                self.assertNotEqual("", stage["marker-depth"], "no marker on the ruler")
                self.assert_close(
                    float(stage["depth"]), float(stage["marker-depth"]), "marker-depth"
                )
                self.assert_no_new_errors()

    def test_during_a_pickup_the_badge_shows_the_slides_factor(self) -> None:
        """While the cage waits at L2 and at the hard disk for its crate or its page, the fast-forward factor is the
        slides' factor, the level's cycles over L1's 4 (4.25 and 14,250,000), and the stopwatch shows half the access
        time, the way down.

        Fails if the badge shows another factor on arrival than the slides, or if the stopwatch runs on during the
        pickup.
        """
        _, levels = self.read_levels()
        for key, factor in self.PICKUP_FACTORS.items():
            with self.subTest(level=key):
                cycles: int = self.SLIDES[key][0]
                opened, stage = self.stage_at(
                    float(levels[key]["pickup-from"]) + 1, "pickup"
                )

                # at this level, with the slides' factor:
                self.assertEqual(key, stage["level"])
                self.assert_close(factor, float(stage["factor"]), "factor")

                # the stopwatch stands at the way down, half the access time:
                self.assert_close(
                    cycles * self.HUMAN_S_PER_CYCLE / 2,
                    float(stage["human-s"]),
                    "human-s",
                )
                self.assert_no_new_errors()

    def test_leaving_the_hard_disk_the_badge_says_only_the_film_runs_fast(
        self,
    ) -> None:
        """Just after the cage leaves the hard disk, where the fast-forward factor has its most digits, the badge says
        that the film runs as a time lapse while the cage keeps its speed, and its whole text fits into the badge; so
        does the longer text while the cage stands at the hard disk ("arrived · the stopwatch stands still").

        Fails if the badge leaves out that the film is a time lapse or that the cage keeps 1.6 km/h, or if it is too
        narrow for its longest text and cuts the end off (e.g. "1.6 km" without "/h", or "still" as "stil").
        """
        _, levels = self.read_levels()
        opened, stage = self.stage_at(
            float(levels["HARD DISK"]["up-from"]) + 0.01, "up"
        )
        badge = opened.page.get_by_test_id("fast-forward")

        # at the Earth's centre, the factor has eight digits (up to 14,250,000):
        self.assertGreater(float(stage["factor"]), 10_000_000)
        expect(badge).to_contain_text("time lapse ×")
        expect(opened.page.get_by_test_id("ff-label")).to_have_text(
            "the cage keeps 1.6 km/h"
        )

        # nothing is cut off: the text is no wider than the badge:
        widths: list[int] = badge.evaluate(
            "(badge) => [badge.scrollWidth, badge.clientWidth]"
        )
        self.assertLessEqual(widths[0], widths[1], "the badge cuts its text off")

        # nor at the hard disk itself, with the longer label of an arrival and the same factor:
        self.stage_at(float(levels["HARD DISK"]["pickup-from"]) + 1, "pickup")
        expect(opened.page.get_by_test_id("ff-label")).to_have_text(
            "arrived · the stopwatch stands still"
        )
        widths = badge.evaluate("(badge) => [badge.scrollWidth, badge.clientWidth]")
        self.assertLessEqual(widths[0], widths[1], "the badge cuts its text off")

    def test_at_l1_the_robot_pulls_a_crate_into_the_cage_while_the_stopwatch_stands_still(
        self,
    ) -> None:
        """While the cage stands at L1 (``LOAD_L1`` s of film: the loading is shown slowly once), the robot loads a crate
        step by step in the order of ``LOAD_STEPS``: it walks to the cage's open side, reaches into the rack and pulls
        a crate straight across into the cage, the crate passing the places of ``CRATE_PLACES`` in order: out of the
        rack, across the gap, into the cage. While it pulls and holds the crate, its hands, as its arms point, are on
        the crate's grip (at most 2 cm away along the pull). On the way down the cage has no crate yet; it rides up
        loaded, the crate in the cage. All the while, the robot stands on the cage's floor, and the stopwatch stands at
        half L1's access time (4 cycles × 0.5 s / 2 = 1.0 s). The pickup is read every 0.1 s, so that each step is
        seen.

        Fails if the cage carries a crate on the way down, if L1's pickup is not ``LOAD_L1`` s long, if a step or a
        place of the crate is unknown, missing, comes twice or out of order, if the crate is not in the cage by the end
        of the pickup or when the cage rides up, if the crate moves away from the robot's hands while it pulls or holds it, if the
        robot floats above or sinks into the cage's floor, or if the stopwatch runs on during the loading.
        """
        _, levels = self.read_levels()
        l1: dict[str, str] = levels["L1"]
        pickup_from, up_from = float(l1["pickup-from"]), float(l1["up-from"])
        cycles: int = self.SLIDES["L1"][0]

        # on the way down, the cage has no crate yet; the robot stands on its floor:
        opened, stage = self.stage_at(float(l1["down-from"]) + 0.5, "down")
        self.assertEqual("", stage["load"])
        self.assertEqual("", stage["crate"])
        self.assertAlmostEqual(0.0, float(stage["robot-floor"]), delta=1e-9)

        # L1's pickup lasts LOAD_L1 s of film:
        self.assert_close(self.LOAD_L1, up_from - pickup_from, "L1's pickup")

        # every 0.1 s of the pickup: a known step, a known place of the crate, the robot's hands on the grip while it
        # pulls and holds the crate, the robot on the cage's floor, and the stopwatch standing at the way down:
        steps: list[str] = []
        places: list[str] = []
        for stage in self.stages_between(pickup_from + 0.05, up_from - 0.05, 0.1):
            with self.subTest(t=stage["t"]):
                self.assertEqual("pickup", stage["phase"])
                self.assertIn(stage["load"], self.LOAD_STEPS)
                self.assertIn(stage["crate"], self.CRATE_PLACES)
                if stage["load"] in ("pull", "loaded"):
                    self.assertLessEqual(float(stage["grip"]), 0.02, "grip")
                self.assertAlmostEqual(0.0, float(stage["robot-floor"]), delta=1e-9)
                self.assert_close(
                    cycles * self.HUMAN_S_PER_CYCLE / 2,
                    float(stage["human-s"]),
                    "human-s",
                )
            steps.append(stage["load"])
            places.append(stage["crate"])

        # the steps come in their order, each once, the last one loaded; the crate goes from nowhere (hidden in the
        # rack) out of the rack, across the gap, into the cage, never back:
        self.assertEqual(self.LOAD_STEPS, [step for step, _ in groupby(steps)])
        self.assertEqual(self.CRATE_PLACES, [place for place, _ in groupby(places)])

        # just after the cage leaves, it rides up with the crate in the cage, the robot still on its floor:
        opened, stage = self.stage_at(up_from + 0.3, "up")
        self.assertEqual("loaded", stage["load"])
        self.assertEqual("cage", stage["crate"])
        self.assertAlmostEqual(0.0, float(stage["robot-floor"]), delta=1e-9)

    def test_every_level_of_crates_sends_one_crate_up_and_the_ssd_and_disk_a_pallet(
        self,
    ) -> None:
        """At the end of the pickup at L1, L2, L3 and DRAM (0.05 s before the cage leaves), the robot has pulled the
        crate into the cage and holds it by its grip (load ``loaded``, crate ``cage``, hands at most 2 cm away), on the
        cage's floor and without a pallet. Just after the cage leaves a level, it rides up with what the level gives:
        from L1, L2, L3 and DRAM that one crate, and no pallet; from the NVMe SSD and the hard disk a pallet of 64
        crates (a 4 KB page), and no single crate (load and crate empty).

        Fails if a pull has not finished by the end of the pickup (the crate still in the rack or on its way across, or
        the robot's hands off its grip), if the robot is not on the cage's floor there, if a level of crates sends the
        cage up without its crate or with a pallet, or if the SSD or the hard disk sends the cage up without its pallet
        or shows a single crate beside it.
        """
        _, levels = self.read_levels()
        for key in self.SLIDES:
            with self.subTest(level=key):
                up_from: float = float(levels[key]["up-from"])
                crate_level: bool = key in self.CRATE_LEVELS

                # at the end of the loading at a level of crates, the crate is in the cage and the robot holds it:
                if crate_level:
                    opened, stage = self.stage_at(up_from - 0.05, "pickup")
                    self.assertEqual(key, stage["level"])
                    self.assertEqual(
                        ("loaded", "cage", "false"),
                        (stage["load"], stage["crate"], stage["pallet"]),
                    )
                    self.assertLessEqual(float(stage["grip"]), 0.02, "grip")
                    self.assertAlmostEqual(0.0, float(stage["robot-floor"]), delta=1e-9)
                    self.assert_no_new_errors()

                opened, stage = self.stage_at(up_from + 0.3, "up")

                # riding up from this level, with one crate in the cage or a pallet:
                self.assertEqual(key, stage["level"])
                expected: tuple[str, str, str] = (
                    ("loaded", "cage", "false") if crate_level else ("", "", "true")
                )
                self.assertEqual(
                    expected, (stage["load"], stage["crate"], stage["pallet"])
                )
                if crate_level:
                    self.assertAlmostEqual(0.0, float(stage["robot-floor"]), delta=1e-9)
                self.assert_no_new_errors()

    def test_an_arrow_marks_the_cage_whenever_it_is_too_small_to_see(self) -> None:
        """A green arrow labelled "THE CAGE" appears exactly when the cage would be too small to find: while it rides
        down or up or picks up a crate and the picture's half height (``data-view-h``) is more than 50 m. In the
        close-ups, at L1's pickup and on the ride down to L2 (the camera follows the cage closely), there is no arrow;
        in the views from far away, DRAM's pickup (the whole block of main memory, hundreds of metres), the ride down
        to the SSD (an overview of 20 km) and the ride up from the hard disk (the whole Earth), there is one.

        Fails if the arrow is missing far away, where the cage is far smaller than a pixel, or if it clutters the
        close-ups, where the cage is plain to see.
        """
        _, levels = self.read_levels()

        def middle(key: str, start: str, end: str) -> float:
            """Returns the time halfway between two times of a level, e.g. its ``down-from`` and ``pickup-from``."""
            return (float(levels[key][start]) + float(levels[key][end])) / 2

        # (level, time of the film, phase of the cage, whether the arrow shows):
        cases: list[tuple[str, float, str, str]] = [
            ("L1", float(levels["L1"]["pickup-from"]) + 2, "pickup", "false"),
            ("L2", middle("L2", "down-from", "pickup-from"), "down", "false"),
            # (once the camera has zoomed out to the whole block: the zoom takes 2.4 s)
            ("DRAM", float(levels["DRAM"]["pickup-from"]) + 2.5, "pickup", "true"),
            (
                "NVMe SSD",
                middle("NVMe SSD", "down-from", "pickup-from"),
                "down",
                "true",
            ),
            ("HARD DISK", middle("HARD DISK", "up-from", "back-from"), "up", "true"),
        ]
        for key, seconds, phase, arrow in cases:
            with self.subTest(level=key, phase=phase):
                opened, stage = self.stage_at(seconds, phase)

                # at this level, with the arrow shown only from far away:
                self.assertEqual(key, stage["level"])
                self.assertEqual(arrow, stage["arrow"])
                self.assert_no_new_errors()

    def test_the_cage_stays_in_the_picture_during_rides_and_zooms(self) -> None:
        """While the cage rides down or up or picks up its crate, also while the camera zooms in or out, the cage's
        middle stays in the picture (``data-cage-screen``, "x,y" in normalized device coordinates, -1 … 1, left to
        right and bottom to top): at most half the picture's height above its middle (0.5, plus 0.1 for the
        perspective), at most 0.45 below it (plus 0.1), and inside it from left to right. The moments: leaving DRAM's
        block view, zooming out on the way down to the SSD and the hard disk, zooming into the platter, and climbing
        fast from the hard disk while the camera zooms out to the whole Earth.

        Fails if the camera lags behind the cage during a zoom, so that the cage (and its arrow) leaves the picture,
        or if the stage stops reporting where the cage is.
        """
        _, levels = self.read_levels()

        def at(key: str, start: str, offset: float) -> float:
            """Returns a time of the film: a level's time (e.g. its ``down-from``) plus an offset (s)."""
            return float(levels[key][start]) + offset

        # (level, time of the film, phase of the cage):
        cases: list[tuple[str, float, str]] = [
            # leaving the whole block's view of main memory:
            ("DRAM", at("DRAM", "up-from", 0.5), "up"),
            # zooming out on the way down, then riding down, then up again:
            ("NVMe SSD", at("NVMe SSD", "down-from", 1.0), "down"),
            ("NVMe SSD", at("NVMe SSD", "down-from", 4.0), "down"),
            ("NVMe SSD", at("NVMe SSD", "up-from", 1.0), "up"),
            # zooming out on the way down, then riding down:
            ("HARD DISK", at("HARD DISK", "down-from", 1.5), "down"),
            ("HARD DISK", at("HARD DISK", "down-from", 8), "down"),
            # the zoom into the platter's view, before the pickup's last segment starts at pickup-from:
            ("HARD DISK", at("HARD DISK", "pickup-from", -1.5), "pickup"),
            # climbing fast while the camera zooms out to the whole Earth:
            ("HARD DISK", at("HARD DISK", "up-from", 1.0), "up"),
            ("HARD DISK", at("HARD DISK", "up-from", 2.0), "up"),
            ("HARD DISK", at("HARD DISK", "up-from", 4.0), "up"),
        ]
        for key, seconds, phase in cases:
            with self.subTest(level=key, phase=phase, t=seconds):
                opened, stage = self.stage_at(seconds, phase)
                self.assertEqual(key, stage["level"])

                # where the cage's middle is in the picture, with three decimals:
                self.assertRegex(stage["cage-screen"], r"^-?\d+\.\d{3},-?\d+\.\d{3}$")
                x, y = (float(part) for part in stage["cage-screen"].split(","))
                where: str = f"cage at x {x}, y {y}"
                self.assertLessEqual(abs(x), 0.95, where)
                self.assertLessEqual(y, 0.6, where)
                self.assertGreaterEqual(y, -0.55, where)
                self.assert_no_new_errors()

    def test_the_stage_reports_the_films_time_and_length(self) -> None:
        """At three times of the film (picking up at L1, riding down to L2, riding up from the hard disk), the stage's
        ``data-t`` is the time the page was opened at (``?t=<seconds>&paused``), in seconds with exactly three
        decimals, and its ``data-duration`` is the film's length: the same at all three, after the cage is back from the
        hard disk, and the total the clock shows ("m:ss / m:ss", whole seconds cut off as the page writes them). Each
        time opens a page of its own, as this checks the time of the URL, not the slider's (see stage_at).

        Fails if the stage reports another time than the one shown (e.g. the time before the jump of the URL), writes
        it with more or fewer decimals, or if its length differs from the clock's total or ends before the film does.
        """
        _, levels = self.read_levels()

        def clock_text(seconds: float) -> str:
            """Returns a time (s) as the clock writes it: whole minutes, then whole seconds with two digits."""
            return f"{math.floor(seconds / 60)}:{math.floor(seconds % 60):02d}"

        # (level, time of the film, phase of the cage):
        cases: list[tuple[str, float, str]] = [
            ("L1", float(levels["L1"]["pickup-from"]) + 1, "pickup"),
            ("L2", float(levels["L2"]["down-from"]) + 0.5, "down"),
            ("HARD DISK", float(levels["HARD DISK"]["up-from"]) + 1, "up"),
        ]
        durations: list[float] = []
        for key, seconds, phase in cases:
            with self.subTest(level=key, phase=phase):
                # a page of its own, opened paused at the time:
                opened: OpenedPage = self.open_page(
                    STORAGE_HIERARCHY_PAGE, query=f"?t={seconds}&paused"
                )
                stage: dict[str, str] = self.read_stage(
                    opened, phase, self.READY_TIMEOUT
                )

                # the time shown, with exactly three decimals:
                self.assertRegex(stage["t"], r"^\d+\.\d{3}$")
                self.assertAlmostEqual(seconds, float(stage["t"]), delta=1e-3)

                # the film's length, after the cage is back from the hard disk, and the clock's total:
                duration: float = float(stage["duration"])
                durations.append(duration)
                self.assertGreater(duration, float(levels["HARD DISK"]["back-from"]))
                expect(opened.page.get_by_test_id("clock")).to_have_text(
                    f"{clock_text(seconds)} / {clock_text(duration)}"
                )
                self.assert_no_errors(opened)
                # close the page before the next one opens, not only at the end of the test:
                opened.page.context.close()

        # the same length at every time of the film:
        self.assertEqual(len(cases), len(durations))
        self.assertEqual(1, len(set(durations)), f"lengths {durations}")

    def test_the_platter_turns_one_turn_in_five_seconds(self) -> None:
        """At two moments of the hard disk's first pickup, 3.5 s and 2.5 s before ``pickup-from`` (the platter's own
        view), the stage's ``data-platter-turn`` is the platter's angle in radians, in [0, 2π), equal to
        ((t mod 5) / 5) · 2π for the film's time t: one turn in 5 s of film (not to scale, but plain to see), the angle
        growing with the time (which way that turns on the screen is not checked). Between the two moments it has
        turned forward by (Δt / 5) · 2π (mod 2π).

        Fails if the platter stands still, turns backwards or at another speed, if its angle depends on anything but
        the film's time (e.g. on the time since the page was opened), or if the stage stops reporting it.
        """
        _, levels = self.read_levels()
        pickup_from: float = float(levels["HARD DISK"]["pickup-from"])
        full_turn: float = 2 * math.pi

        def turn_apart(expected: float, actual: float) -> float:
            """Returns how far two angles (radians) lie apart round the circle, so 0 and just below 2π are close."""
            difference: float = (actual - expected) % full_turn
            return min(difference, full_turn - difference)

        # (time of the film, angle of the platter) at both moments:
        seen: list[tuple[float, float]] = []
        for offset in (-3.5, -2.5):
            with self.subTest(offset=offset):
                opened, stage = self.stage_at(pickup_from + offset, "pickup")
                self.assertEqual("HARD DISK", stage["level"])

                # the angle, with four decimals, in [0, 2π), as a function of the film's time only:
                self.assertRegex(stage["platter-turn"], r"^\d+\.\d{4}$")
                t, turn = float(stage["t"]), float(stage["platter-turn"])
                self.assertGreaterEqual(turn, 0)
                self.assertLess(turn, full_turn)
                self.assertLessEqual(
                    turn_apart(
                        (t % self.PLATTER_TURN) / self.PLATTER_TURN * full_turn, turn
                    ),
                    1e-3,
                    f"platter at {turn} rad at t {t}",
                )
                seen.append((t, turn))
                self.assert_no_new_errors()

        # between the two moments, the platter turned forward by Δt / 5 of a turn:
        self.assertEqual(2, len(seen))
        (t0, turn0), (t1, turn1) = seen
        self.assertAlmostEqual(1, t1 - t0, delta=1e-3)
        self.assertAlmostEqual(
            (t1 - t0) / self.PLATTER_TURN * full_turn,
            (turn1 - turn0) % full_turn,
            delta=1e-3,
            msg=f"turned from {turn0} to {turn1} rad in {t1 - t0} s",
        )

    def test_the_stopwatch_fields_keep_their_places_whatever_the_numbers(self) -> None:
        """At five moments with numbers of very different lengths (on the way down to L1, up from DRAM, the SSD and
        the hard disk, and back from the hard disk, e.g. "9" against "57,000,000" cycles, "4.48 s" against
        "18 min 17 s"), every field of the stopwatch in the header (level, cycles, real, human time, depth) has the same
        left and right edge, and every label ("cycles", "real", ...) the same left edge, to 0.5 px; each field's text
        fits into its box.

        Fails if a field's width follows its text, so that the header jumps while the numbers count (the labels after
        it move), or if a field is too narrow for its longest value and cuts it off or spills over.
        """
        _, levels = self.read_levels()
        fields: list[str] = ["sw-level", "sw-cycles", "sw-real", "sw-human", "sw-depth"]
        labels: list[str] = [
            "sw-cycles-label",
            "sw-real-label",
            "sw-human-label",
            "sw-depth-label",
        ]

        # (level, time of the film, phase of the cage):
        cases: list[tuple[str, float, str]] = [
            ("L1", float(levels["L1"]["down-from"]) + 0.5, "down"),
            ("DRAM", float(levels["DRAM"]["up-from"]) + 2, "up"),
            ("NVMe SSD", float(levels["NVMe SSD"]["up-from"]) + 6, "up"),
            ("HARD DISK", float(levels["HARD DISK"]["up-from"]) + 3, "up"),
            ("HARD DISK", float(levels["HARD DISK"]["back-from"]) + 0.5, "back"),
        ]
        # at each moment: the left and right edge of each field, then the left edge of each label (px):
        edges_seen: list[list[float]] = []
        # at each moment: the text of each field:
        texts_seen: list[list[str]] = []
        for key, seconds, phase in cases:
            with self.subTest(level=key, phase=phase):
                opened, stage = self.stage_at(seconds, phase)
                self.assertEqual(key, stage["level"])
                header: (
                    StorageHierarchyPageTest.StopwatchBoxes
                ) = opened.page.get_by_test_id("stopwatch").evaluate(
                    """(stopwatch, [fieldIds, labelIds]) => {
                            const byId = (id) => stopwatch.querySelector(`[data-testid="${id}"]`);
                            const fields = fieldIds.map(byId);
                            return {
                                edges: [
                                    ...fields.flatMap((field) => {
                                        const box = field.getBoundingClientRect();
                                        return [box.left, box.right];
                                    }),
                                    ...labelIds.map((id) => byId(id).getBoundingClientRect().left),
                                ],
                                widths: fields.map((field) => [field.scrollWidth, field.clientWidth]),
                                texts: fields.map((field) => field.textContent),
                            };
                        }""",
                    [fields, labels],
                )

                # each field's text fits into its box:
                for field, (scroll_width, client_width), text in zip(
                    fields, header["widths"], header["texts"]
                ):
                    self.assertLessEqual(
                        scroll_width,
                        client_width + 1,
                        f"{field} cuts off {text!r}: {scroll_width} px in {client_width} px",
                    )
                edges_seen.append(header["edges"])
                texts_seen.append(header["texts"])

        # the moments show numbers of different lengths, else the test proves nothing:
        self.assertEqual(len(cases), len(edges_seen))
        for index in (fields.index("sw-cycles"), fields.index("sw-human")):
            self.assertGreater(
                len({len(texts[index]) for texts in texts_seen}),
                1,
                f"{fields[index]} has one length only: {texts_seen}",
            )

        # every edge stands where it stood at the first moment:
        first: list[float] = edges_seen[0]
        for (key, _, phase), edges, texts in zip(cases, edges_seen, texts_seen):
            for index, (expected, actual) in enumerate(zip(first, edges)):
                self.assertAlmostEqual(
                    expected,
                    actual,
                    delta=0.5,
                    msg=f"edge {index} at {key} ({phase}), texts {texts}: {edges} vs. {first}",
                )

    def test_the_stopwatch_keeps_its_place_whatever_the_steps_name(self) -> None:
        """With a short step name in the header ("04/15 · L1"), the page's longest ("02/15 · The core and its
        registers") and one twice as long, the stopwatch has the same left and top edge, to 0.5 px, on a wide screen
        (1280 px, top right, beside the name) and on a narrow one (900 px, on the first line, above the name); it stays
        inside the screen and clear of the step's text.

        Fails if a long step name pushes the stopwatch onto a line of its own (on a wide screen) or one line further
        down (on a narrow one): then it jumps whenever the step changes.
        """
        self.read_levels()
        page: Page = self.opened.page
        long_name: str = "02/15 · The core and its registers"
        names: list[str] = ["04/15 · L1", long_name, f"{long_name} · {long_name}"]
        try:
            for width in (1280, 900):
                with self.subTest(width=width):
                    page.set_viewport_size({"width": width, "height": 720})
                    # for each name: the stopwatch's box and the step's box (px); the name is put back at once, in the
                    # same task, so that no frame of the film shows it:
                    boxes: list[dict[str, dict[str, float]]] = page.get_by_test_id(
                        "step-name"
                    ).evaluate(
                        """(stepName, names) => {
                            const shown = stepName.textContent;
                            const box = (testId) => {
                                const r = document.querySelector(`[data-testid="${testId}"]`).getBoundingClientRect();
                                return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
                            };
                            const seen = names.map((name) => {
                                stepName.textContent = name;
                                return { stopwatch: box('stopwatch'), step: box('step') };
                            });
                            stepName.textContent = shown;
                            return seen;
                        }""",
                        names,
                    )
                    first: dict[str, float] = boxes[0]["stopwatch"]
                    for name, seen in zip(names, boxes):
                        stopwatch, step = seen["stopwatch"], seen["step"]
                        for edge in ("left", "top"):
                            self.assertAlmostEqual(
                                first[edge],
                                stopwatch[edge],
                                delta=0.5,
                                msg=f"{edge} edge with {name!r}: {stopwatch} vs. {first}",
                            )
                        self.assertLessEqual(
                            stopwatch["right"],
                            width,
                            f"stopwatch leaves the screen: {stopwatch}",
                        )
                        # beside the step's text, or above it:
                        self.assertTrue(
                            step["right"] <= stopwatch["left"] + 0.5
                            or stopwatch["bottom"] <= step["top"] + 0.5,
                            f"stopwatch {stopwatch} overlaps step {step} with {name!r}",
                        )
        finally:
            # back to the size of the other tests' pages (Playwright's default), and one frame, in which the page
            # follows the new size, before the next test:
            page.set_viewport_size({"width": 1280, "height": 720})
            page.evaluate(
                "() => new Promise((done) => requestAnimationFrame(() => done()))"
            )

    def test_back_at_the_floor_the_robot_puts_the_value_into_a_register(
        self,
    ) -> None:
        """Back at the floor from a level of crates, the robot puts the value it fetched into a register, step by step
        (``data-unload``): after L1, in detail, in the order of ``UNLOAD_STEPS``: it takes the value out of the crate,
        turns, walks to the register tray, puts the value in, the value is stored, and the robot walks back; after L2
        (and L3 and DRAM), short, in the order of ``SHORT_UNLOAD_STEPS``: it takes the value, which flies across into
        the register, and it is stored. Back from the NVMe SSD there is no unloading (``""``). Each stay is read every
        0.1 s, so that each step is seen. After L1 the robot (``data-robot-at``) puts and stores the value at least 3 m
        left of where it took it, by the register tray, and ends where it began; it never jumps (at most 0.7 m in
        0.1 s), its hands are on the crate's grip while it takes the value, and its legs (``data-legs``) swing while it
        walks to the tray and stand together whenever it stands.

        Fails if a step is unknown, missing, comes twice or out of order, if the robot does not really walk to the tray
        (only the step's name changes), jumps, or does not come back, if its arms drop while it takes the value, if its
        legs never swing or stand apart while it stands, if the short unloading after L2 is missing or out of order, or
        if the SSD's pallet is unloaded like a crate.
        """
        _, levels = self.read_levels()

        # after L1, every 0.1 s of the stay at the floor: the steps, and where the robot stands (x, z):
        back_from: float = float(levels["L1"]["back-from"])
        stay: list[dict[str, str]] = self.stages_between(
            back_from + 0.05,
            back_from + self.UNLOAD_L1 + self.STILL_AFTER_L1 - 0.05,
            0.1,
        )
        for stage in stay:
            self.assertEqual(
                ("L1", "back"), (stage["level"], stage["phase"]), stage["t"]
            )
        steps: list[str] = [stage["unload"] for stage in stay]
        self.assertEqual(self.UNLOAD_STEPS, [step for step, _ in groupby(steps)])

        # while it takes the value out, its arms are forward, as on the ride up: its hands on the crate's grip:
        for stage in stay:
            if stage["unload"] == "take":
                self.assertLessEqual(
                    float(stage["grip"]), 0.02, f"grip at {stage['t']}"
                )

        # the robot puts and stores the value by the tray, at least 3 m left of where it took it, and comes back:
        places: list[tuple[float, ...]] = [
            tuple(float(v) for v in stage["robot-at"].split(",")) for stage in stay
        ]
        start_x, start_z = places[0]
        for (x, _), step in zip(places, steps):
            if step in ("put", "stored"):
                self.assertLessEqual(x, start_x - 3, f"{step} at x {x}, from {start_x}")
        self.assertAlmostEqual(start_x, places[-1][0], delta=0.01)
        self.assertAlmostEqual(start_z, places[-1][1], delta=0.01)

        # it walks, never jumps (at most 0.7 m in 0.1 s: its fastest step, on the way back, is about 0.6 m); wherever it
        # stands, its legs stand together, and while it walks to the tray they swing:
        standing: int = 0
        for before, after, (x0, z0), (x1, z1) in zip(
            stay, stay[1:], places, places[1:]
        ):
            where: str = f"{before['t']} s to {after['t']} s"
            self.assertLessEqual(
                math.hypot(x1 - x0, z1 - z0), 0.7, f"the robot jumps, {where}"
            )
            if (x0, z0) == (x1, z1):
                standing += 1
                self.assertEqual(
                    "0.000", after["legs"], f"legs apart while it stands, {where}"
                )
        self.assertGreater(standing, 0, "the robot never stands")
        self.assertTrue(
            any(
                float(stage["legs"]) > 0.05
                for stage in stay
                if stage["unload"] == "walk"
            ),
            "the legs do not swing while the robot walks",
        )

        # after L2, every 0.1 s of its stay: the short unloading's steps, in order:
        l2_back: float = float(levels["L2"]["back-from"])
        short_stay: list[dict[str, str]] = self.stages_between(
            l2_back + 0.05, float(levels["L3"]["down-from"]) - 0.05, 0.1
        )
        short_steps: list[str] = [
            stage["unload"] for stage in short_stay if stage["level"] == "L2"
        ]
        self.assertEqual(
            self.SHORT_UNLOAD_STEPS, [step for step, _ in groupby(short_steps)]
        )

        # back from the NVMe SSD, nothing is unloaded:
        opened, stage = self.stage_at(
            float(levels["NVMe SSD"]["back-from"]) + 0.5, "back"
        )
        self.assertEqual("NVMe SSD", stage["level"])
        self.assertEqual("", stage["unload"])

    def test_in_the_basement_the_robot_walks_to_the_registers_and_back(self) -> None:
        """From the film's start to the ride down to L1 (through the House's view and the basement's), every quarter
        of a second, the robot moves at most 0.75 m (it walks, at most 3 m/s); while it reaches into the registers
        (phase ``reach``) it stands at least 3 m left of where it started, by the cage's open side next to the register
        tray; at the end it stands where it started, where it waits for the crate at L1.

        Fails if the robot jumps out of the cage to the registers (or back), if it does not go to the registers for
        the reach, or if it starts the ride from another place than it waits at (a jump at the ride's start).
        """
        _, levels = self.read_levels()

        # every quarter of a second up to the ride down to L1: the time, the cage's phase and the robot's place:
        seen: list[tuple[float, str, float, float]] = []  # (time, phase, x, z)
        for stage in self.stages_between(0, float(levels["L1"]["down-from"]), 0.25):
            x, z = (float(v) for v in stage["robot-at"].split(","))
            seen.append((float(stage["t"]), stage["phase"], x, z))

        # it walks, never jumps:
        for (t0, _, x0, z0), (t1, _, x1, z1) in zip(seen, seen[1:]):
            self.assertLessEqual(
                math.hypot(x1 - x0, z1 - z0),
                0.75,
                f"the robot jumps between {t0} s ({x0}, {z0}) and {t1} s ({x1}, {z1})",
            )

        # it reaches by the registers, and ends where it started:
        start_x: float = seen[0][2]
        at_reach: list[float] = [x for _, phase, x, _ in seen if phase == "reach"]
        self.assertTrue(at_reach, "no reach sampled")
        self.assertTrue(
            all(x <= start_x - 3 for x in at_reach),
            f"not by the registers: {at_reach} from {start_x}",
        )
        self.assertAlmostEqual(seen[0][2], seen[-1][2], delta=0.01)
        self.assertAlmostEqual(seen[0][3], seen[-1][3], delta=0.01)

    def test_coming_home_from_the_hard_disk_the_camera_zooms_in_early_and_slowly(
        self,
    ) -> None:
        """On the ride up from the hard disk, every quarter of a second, the picture (``data-view-h``, its half height
        in metres) grows to one highest point and from there only gets smaller or stays: the camera zooms out once as
        the cage leaves, then only in. Once it has zoomed out (3 s after leaving) until the cage is home, every second
        the picture gets smaller by at most eight times; halfway home it is already at most a hundredth of the overview
        of the whole Earth (7,400 km).

        Fails if the camera stays on the overview and zooms in only at the end (some million times in a few seconds),
        if it zooms in and out on the way out (in, out, in while the cage leaves), or if it zooms out on the way home.
        """
        _, levels = self.read_levels()
        up_from: float = float(levels["HARD DISK"]["up-from"])
        back_from: float = float(levels["HARD DISK"]["back-from"])

        # out once, then only in (1 % slack for rounding):
        ride: list[tuple[float, float]] = []  # (time, picture's half height)
        for stage in self.stages_between(
            up_from + 0.25, up_from + (int((back_from - up_from) * 4) - 1) / 4, 0.25
        ):
            self.assertEqual("up", stage["phase"], stage["t"])
            ride.append((float(stage["t"]), float(stage["view-h"])))
        top: int = max(range(len(ride)), key=lambda i: ride[i][1])
        for (t0, h0), (t1, h1) in zip(ride[:top], ride[1 : top + 1]):
            self.assertGreaterEqual(
                h1,
                h0 / 1.01,
                f"zooms in while leaving, {t0} s to {t1} s: {h0} m to {h1} m",
            )
        for (t0, h0), (t1, h1) in zip(ride[top:], ride[top + 1 :]):
            self.assertLessEqual(
                h1,
                h0 * 1.01,
                f"zooms out on the way home, {t0} s to {t1} s: {h0} m to {h1} m",
            )

        # every second from 3 s after leaving until home: never out, and in by at most eight times a second:
        heights: list[tuple[float, float]] = []  # (time, picture's half height)
        seconds: float = up_from + 3
        for stage in self.stages_between(seconds, back_from - 1e-6, 1):
            self.assertEqual("up", stage["phase"], stage["t"])
            heights.append((float(stage["t"]), float(stage["view-h"])))
        for (t0, h0), (t1, h1) in zip(heights, heights[1:]):
            self.assertLessEqual(
                h1,
                h0 * 1.01,
                f"the camera zooms out between {t0} s and {t1} s: {h0} m to {h1} m",
            )
            self.assertLessEqual(
                h0 / h1,
                8,
                f"the camera zooms in fast between {t0} s and {t1} s: {h0} m to {h1} m",
            )

        # halfway home, at most a hundredth of the Earth's overview:
        halfway: float = (up_from + back_from) / 2
        self.assertLessEqual(
            min(h for t, h in heights if t <= halfway),
            7.4e6 / 100,
            f"not zoomed in halfway home: {heights}",
        )

    def test_coming_closer_the_strata_and_their_signs_fade_in(self) -> None:
        """On the ride up from the hard disk, every 0.2 s from 2.5 s before to 2.5 s after the moment the picture's
        half height (``data-view-h``) gets lower than 100 km (where the Earth cut open gives way to the strata of the
        section): the strata's grain and colours, the section's signs and holes and the sky (``data-near-detail``, 0
        none ... 1 all) are 0 while the half height is 100 km or more and 1 from 30 km down (the SSD's overview, 29 km,
        in full); in between they grow, by at most 0.5 from one sample to the next, and at least one sample shows them
        half-way (0.2 to 0.8). Samples are seen on both sides: at 100 km or more, and at 30 km or less.

        Fails if the strata's textures and the signs appear all at once ("out of nowhere"), or if they come in at
        another scale (e.g. later, from 30 km only).
        """
        _, levels = self.read_levels()
        up_from: float = float(levels["HARD DISK"]["up-from"])
        back_from: float = float(levels["HARD DISK"]["back-from"])

        # the moment the half height gets lower than 100 km, to a tenth of a second, before the cage is home:
        seconds: float = up_from + 3
        for stage in self.stages_between(seconds, back_from - 1e-6, 0.1):
            self.assertEqual("up", stage["phase"], stage["t"])
            seconds = float(stage["t"])
            if float(stage["view-h"]) < 1e5:
                break
        else:
            seconds = back_from
        self.assertLess(seconds, back_from, "the picture never gets lower than 100 km")

        # every 0.2 s around that moment: the time, the half height, the detail:
        seen: list[tuple[float, float, float]] = []  # (time, half height, detail)
        for stage in self.stages_between(seconds - 2.4, seconds + 2.4 + 1e-6, 0.2):
            self.assertEqual("up", stage["phase"], stage["t"])
            seen.append(
                (float(stage["t"]), float(stage["view-h"]), float(stage["near-detail"]))
            )

        # none at 100 km and more, all at 30 km and less, and both sides are sampled:
        self.assertTrue(any(height >= 1e5 for _, height, _ in seen), f"{seen}")
        self.assertTrue(any(height <= 3e4 for _, height, _ in seen), f"{seen}")
        for t, height, detail in seen:
            if height >= 1e5:
                self.assertEqual(
                    0, detail, f"detail {detail} at {t} s, the picture {height} m high"
                )
            if height <= 3e4:
                self.assertEqual(
                    1, detail, f"detail {detail} at {t} s, the picture {height} m high"
                )

        # in between, it grows step by step, and is seen half-way:
        for (t0, _, d0), (t1, _, d1) in zip(seen, seen[1:]):
            self.assertLessEqual(
                d0, d1, f"the detail fades out between {t0} s and {t1} s"
            )
            self.assertLessEqual(
                d1 - d0,
                0.5,
                f"the detail jumps between {t0} s and {t1} s: {d0} to {d1}",
            )
        self.assertTrue(
            any(0.2 <= d <= 0.8 for _, _, d in seen), f"never half-way: {seen}"
        )

    def test_after_l1_the_robot_stands_still_with_the_value_stored(self) -> None:
        """After L1's unloading (``UNLOAD_L1`` seconds after the cage is back at the floor) the robot stands still for
        ``STILL_AFTER_L1`` seconds: at the start, the middle and the end of that time, the film is still back from L1,
        the unloading is over (``data-unload`` is ``back``, the last step), the used crate is gone (``data-crate`` is
        ``""``), and the robot (``data-robot-at``) stands at the same place each time, within 1 cm of where it stood on
        the ride down to L1, its legs together (``data-legs`` 0); just after it, the film shows the start of the ride
        to L2.

        Fails if the still time is missing (the film moves on to L2 at once), if it is made by drawing the unloading
        out (the robot still carries the value, still walks, or the crate is still there), or if it lasts longer than
        planned.
        """
        _, levels = self.read_levels()

        # where the robot stands on the ride down to L1:
        _, stage = self.stage_at(float(levels["L1"]["down-from"]) + 0.5, "down")
        home: tuple[float, ...] = tuple(float(v) for v in stage["robot-at"].split(","))

        # at the start, the middle and the end of the still time: back from L1, unloaded, no crate, the robot still:
        still_from: float = float(levels["L1"]["back-from"]) + self.UNLOAD_L1
        places: list[str] = []
        for offset in (0.2, self.STILL_AFTER_L1 / 2, self.STILL_AFTER_L1 - 0.2):
            with self.subTest(offset=offset):
                opened, stage = self.stage_at(still_from + offset, "back")
                self.assertEqual("L1", stage["level"])
                self.assertEqual("back", stage["unload"])
                self.assertEqual("", stage["crate"])
                self.assertEqual("0.000", stage["legs"])
                places.append(stage["robot-at"])
                x, z = (float(v) for v in stage["robot-at"].split(","))
                self.assertLessEqual(
                    math.hypot(x - home[0], z - home[1]), 0.01, stage["robot-at"]
                )
        self.assertEqual(1, len(set(places)), f"the robot moves: {places}")

        # just after the still time, the film shows the start of the ride to L2 (the cage idle, no level yet):
        opened, stage = self.stage_at(still_from + self.STILL_AFTER_L1 + 0.2, "idle")
        self.assertEqual("", stage["level"])
        step_name: str = opened.page.get_by_test_id("step-name").text_content() or ""
        self.assertTrue(step_name.endswith("· L2"), step_name)

    def test_on_its_way_up_the_cage_leaves_a_copy_in_every_faster_level(
        self,
    ) -> None:
        """Inclusion, as in the textbook: on its way up, the cage leaves a copy in every faster level it passes (among
        L1, L2, L3 and DRAM), and a page from the NVMe SSD or the hard disk also leaves one in DRAM. The copies stay, so
        that back at the floor from each level, the copies counted so far (``data-copies``) grow by one in every level
        faster than it: none after L1, then L1:1, then L1:2 and L2:1, and so on up to L1:5, L2:4, L3:3, DRAM:2 after the
        hard disk. Just after the cage leaves L2, before it passes L1, L1 has no copy yet. The copies of single crates
        lie in their level's top layer (``data-copy-layers``, 0 from the top), clear of the depth sign one layer down;
        main memory's two pages lie under each other (layers 0 and 2, two layers high each).

        Fails if the cage leaves a copy in the level it comes from or in a slower one, misses a level it passes, if the
        SSD's or the hard disk's page leaves no copy in DRAM, if copies vanish, if a copy appears before the cage
        passes its level, or if a copy lies below the top layer (behind the depth sign).
        """
        _, levels = self.read_levels()

        # where the copies lie, from the top layer down:
        layers: dict[str, str] = {
            key: levels[key]["copy-layers"] for key in ("L1", "L2", "L3", "DRAM")
        }
        self.assertEqual(
            {"L1": "0,0,0,0,0", "L2": "0,0,0,0", "L3": "0,0,0", "DRAM": "0,2"}, layers
        )

        # (level, offset after its back-from (s), the copies counted at the floor):
        cases: list[tuple[str, float, str]] = [
            ("L1", 1, "L1:0,L2:0,L3:0,DRAM:0"),
            ("L2", 0.5, "L1:1,L2:0,L3:0,DRAM:0"),
            ("L3", 0.5, "L1:2,L2:1,L3:0,DRAM:0"),
            ("DRAM", 0.5, "L1:3,L2:2,L3:1,DRAM:0"),
            ("NVMe SSD", 0.5, "L1:4,L2:3,L3:2,DRAM:1"),
            ("HARD DISK", 0.5, "L1:5,L2:4,L3:3,DRAM:2"),
        ]
        for key, offset, copies in cases:
            with self.subTest(level=key):
                opened, stage = self.stage_at(
                    float(levels[key]["back-from"]) + offset, "back"
                )
                self.assertEqual(key, stage["level"])
                self.assertEqual(copies, stage["copies"])
                self.assert_no_new_errors()

        # just after the cage leaves L2, it has not passed L1 yet: no copy so far:
        opened, stage = self.stage_at(float(levels["L2"]["up-from"]) + 0.05, "up")
        self.assertEqual("L2", stage["level"])
        self.assertEqual("L1:0,L2:0,L3:0,DRAM:0", stage["copies"])
        self.assert_no_new_errors()

    def test_after_the_intro_the_narration_gives_access_times_in_cycles_and_made_up_time(
        self,
    ) -> None:
        """The narration names a real time only in its intro, where one cycle (0.175 ns) becomes half a second; from
        then on, its captions give access times in cycles and in that made-up time only, never in nano-, micro- or
        milliseconds. Next shows the captions one after the other; the second one is the intro.

        Fails if a level's caption names its real access time (e.g. "Main memory: 100 nanoseconds, ...").
        """
        # from the start, Next to the end, each caption once:
        opened, _ = self.stage_at(0, None)
        page: Page = opened.page
        text = page.get_by_test_id("nar-text")
        captions: list[str] = []
        clicks: int = 0
        while page.get_by_test_id("play").get_attribute("data-state") != "ended":
            self.assertLess(clicks, MAX_NEXT_CLICKS, "Next did not reach the end")
            page.get_by_test_id("next").click()
            clicks += 1
            caption: str = " ".join((text.text_content() or "").split())
            if not captions or captions[-1] != caption:
                captions.append(caption)

        # a real time only in the intro:
        real_time: re.Pattern[str] = re.compile(
            r"\b(nano|micro|milli)seconds?\b|\b(ns|µs|ms)\b"
        )
        self.assertRegex(captions[1], real_time, "the intro names one cycle's time")
        for caption in captions[2:]:
            with self.subTest(caption=caption):
                self.assertNotRegex(caption, real_time)

    def test_over_l3s_whole_trip_the_stopwatch_never_runs_back_and_the_depth_never_jumps(
        self,
    ) -> None:
        """Every quarter of a second from the start of the ride down to L3 until the ride to main memory begins, the
        trip's parts come in order (down, pickup, up, back at the floor), and at every sample the cage's depth below
        the floor and the stopwatch's human time agree with one constant speed v (4 cycles' depth per second of human
        time): on the way down depth = v · human; during the pickup depth = L3's stop, the stopwatch standing still; on
        the way up depth = 2 · stop − v · human; back at the floor depth = 0 (to a nanometre per metre of the stop).
        The human time never goes back, and from one sample to the next the depth changes by no more than the ride
        allows: the film shows a ride down to depth D in 1 + ln(D ÷ L1's depth) seconds, in the first second at L1's
        pace (45 cm a second), then faster in proportion to the depth, so in a quarter of a second the depth grows by
        at most e^0.25 times, by at most 22 % of the deeper of two samples (the way up mirrors it); allowed: 23 % of
        the deeper plus 15 cm.

        Fails if the cage's speed changes anywhere on the trip, if the depth jumps where one part of the trip hands over
        to the next (e.g. the pickup at another depth than the ride's end), if the stopwatch runs back or on during the
        pickup, or if the parts come out of order.
        """
        _, levels = self.read_levels()

        # every quarter of a second of L3's trip, until the ride to main memory; the trip ends where the cage waits
        # for that ride (no level, idle):
        # (from just after the ride starts: through the slider, the time can come out a hair before it)
        sampled: list[dict[str, str]] = self.stages_between(
            float(levels["L3"]["down-from"]) + 0.01,
            float(levels["DRAM"]["down-from"]) - 0.05,
            0.25,
        )
        stages: list[dict[str, str]] = [
            stage for stage in sampled if stage["level"] == "L3"
        ]
        self.assertEqual(stages, sampled[: len(stages)], "L3's trip is interrupted")
        for stage in sampled[len(stages) :]:
            self.assertEqual(("", "idle"), (stage["level"], stage["phase"]), stage["t"])

        # the parts in order:
        phases: list[str] = [stage["phase"] for stage in stages]
        self.assertEqual(
            ["down", "pickup", "up", "back"], [phase for phase, _ in groupby(phases)]
        )

        # the stopwatch never goes back, the depth never jumps:
        for before, after in zip(stages, stages[1:]):
            where: str = f"{before['t']} s to {after['t']} s"
            self.assertGreaterEqual(
                float(after["human-s"]), float(before["human-s"]), where
            )
            d0: float = float(before["depth"]) - self.FLOOR_DEPTH
            d1: float = float(after["depth"]) - self.FLOOR_DEPTH
            self.assertLessEqual(
                abs(d1 - d0), 0.23 * max(d0, d1) + 0.15, f"{where}: {d0} m to {d1} m"
            )

        # depth and human time agree with one constant speed in every part of the trip:
        speed: float = 4 * self.SCALE
        stop: float = float(levels["L3"]["stop"])
        for stage in stages:
            below: float = float(stage["depth"]) - self.FLOOR_DEPTH
            human: float = float(stage["human-s"])
            expected: float = {
                "down": speed * human,
                "pickup": stop,
                "up": 2 * stop - speed * human,
                "back": 0.0,
            }[stage["phase"]]
            self.assertAlmostEqual(
                expected,
                below,
                delta=1e-9 * stop,
                msg=f"{stage['phase']} at {stage['t']}",
            )

        # during the pickup the stopwatch stands still:
        at_pickup: set[str] = {
            stage["human-s"] for stage in stages if stage["phase"] == "pickup"
        }
        self.assertEqual(
            1, len(at_pickup), f"the stopwatch runs during the pickup: {at_pickup}"
        )

    def test_the_part_buttons_jump_to_their_parts_and_play(self) -> None:
        """Each of the five part buttons (caches, memory, SSD, hard disk, Earth), pressed from part 5 down to part 1,
        starting near the film's end (so that each jumps back from a later time), jumps to the start of its part and
        plays from there, and marks itself as the current part while the four others are not marked. The film's time
        is read in the same step as the click, before the film has run on. Part 1 starts the film (at 0); parts 2 to 5
        start where the step named after them begins (main memory, the SSD, the hard disk, "To the centre of the
        Earth"), the cage waiting at the floor, after the level before and, for parts 2 to 4, before the part's ride
        down (``down-from``); 0.01 s earlier another step shows.

        Fails if a button jumps to another part or into the middle of one (e.g. past the start of its step), does not
        jump at all, does not play, leaves another part marked, or cannot be clicked (hidden or covered).
        """
        _, levels = self.read_levels()
        page: Page = self.opened.page
        stage = page.get_by_test_id("stage")
        play = page.get_by_test_id("play")
        step_name = page.get_by_test_id("step-name")
        # parts 2 to 5: (the level the cage is back from before the part, the part's level or None, its step's name):
        later_parts: dict[int, tuple[str, str | None, str]] = {
            2: ("L3", "DRAM", "Main memory"),
            3: ("DRAM", "NVMe SSD", "An NVMe SSD"),
            4: ("NVMe SSD", "HARD DISK", "A hard disk"),
            5: ("HARD DISK", None, "To the centre of the Earth"),
        }
        # near the film's end, after part 5 has begun:
        self.stage_at(float(levels["HARD DISK"]["back-from"]) + 5, None)
        for part in range(5, 0, -1):
            with self.subTest(part=part):
                # the button can be clicked; it jumps (its time read at once), plays, and is the one part marked:
                button = page.get_by_test_id(f"chapter-{part}")
                button.click(trial=True)
                seconds: float = float(
                    button.evaluate(
                        "(b, stage) => { b.click(); return stage.dataset.t; }",
                        stage.element_handle(),
                    )
                )
                expect(play).to_have_attribute("data-state", "playing")
                play.click()
                expect(play).to_have_attribute("data-state", "paused")
                expect(button).to_have_attribute("aria-current", "true")
                for other in range(1, 6):
                    if other != part:
                        expect(
                            page.get_by_test_id(f"chapter-{other}")
                        ).not_to_have_attribute("aria-current", "true")
                if part == 1:
                    self.assertEqual(0, seconds)
                    continue

                # after the level before, and before the part's ride:
                before, key, title = later_parts[part]
                self.assertGreater(seconds, float(levels[before]["back-from"]))
                if key is not None:
                    self.assertLess(seconds, float(levels[key]["down-from"]))

                # 1 ms after the time read (data-t has three decimals: the part begins at most half a millisecond
                # from it), the part's step shows, the cage waiting at the floor:
                _, shown = self.stage_at(seconds + 0.001, None)
                expect(step_name).to_have_text(re.compile(f"· {re.escape(title)}$"))
                self.assertEqual("idle", shown["phase"], shown["t"])

                # 0.01 s before, another step:
                self.stage_at(seconds - 0.01, None)
                expect(step_name).not_to_have_text(re.compile(f"· {re.escape(title)}$"))

    def test_back_goes_to_the_stop_before_or_to_the_start(self) -> None:
        """From the film's start, Next goes on to the first and then to the second stop; Back (the left arrow key)
        goes from the second stop to the first, and from the first to the film's start; the film stays paused.

        Fails if Back skips a stop, stays where it is, or does not go back to the start from the first stop.
        """
        opened, _ = self.stage_at(0, None)
        page: Page = opened.page
        stage = page.get_by_test_id("stage")

        # Next to the first and to the second stop:
        page.get_by_test_id("next").click()
        first: str = stage.get_attribute("data-t") or ""
        page.get_by_test_id("next").click()
        second: str = stage.get_attribute("data-t") or ""
        self.assertGreater(float(first), 0)
        self.assertGreater(float(second), float(first))

        # Back to the first stop, then to the start (with the focus on the page, not on a control):
        page.evaluate("() => document.activeElement?.blur()")
        page.keyboard.press("ArrowLeft")
        expect(stage).to_have_attribute("data-t", first)
        page.keyboard.press("ArrowLeft")
        expect(stage).to_have_attribute("data-t", "0.000")
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "paused")

    def test_the_full_screen_button_and_the_key_f_switch_full_screen(self) -> None:
        """The full-screen button puts the page into full screen and says so (``aria-pressed`` true); the key F
        leaves it again (``aria-pressed`` false), and F once more enters it.

        Fails if the button or the key does nothing, or if the button does not show whether the page is in full screen.
        """
        self.read_levels()
        page: Page = self.opened.page
        button = page.get_by_test_id("fullscreen")
        in_full_screen: str = "() => document.fullscreenElement !== null"
        try:
            # the button enters full screen:
            button.click()
            expect(button).to_have_attribute("aria-pressed", "true")
            self.assertTrue(page.evaluate(in_full_screen))

            # F leaves it, and enters it again:
            page.keyboard.press("f")
            expect(button).to_have_attribute("aria-pressed", "false")
            self.assertFalse(page.evaluate(in_full_screen))
            page.keyboard.press("f")
            expect(button).to_have_attribute("aria-pressed", "true")
        finally:
            # out of full screen for the next test:
            page.evaluate(
                "() => document.fullscreenElement && document.exitFullscreen()"
            )
            expect(button).to_have_attribute("aria-pressed", "false")

    def test_the_register_tray_lies_in_the_room_l1_leaves_for_it(self) -> None:
        """The register tray with its bottom, back wall and sides (``data-box`` of the registers, x0,x1,y0,y1,z0,z1 in
        metres) lies inside the room that L1 leaves for it under the basement floor (``data-room`` of L1; its z1 is
        infinite: the room is open at the front, at the cut), with a gap of at least 5 mm on every side: the two drawn
        objects do not meet. The room comes from L1's layout (its crate places), the tray's walls from its box.

        Fails if the tray reaches into L1's crates or its body behind it (faces inside one another, or in one plane).
        """
        _, levels = self.read_levels()
        tray: list[float] = [float(v) for v in levels["REGISTERS"]["box"].split(",")]
        room: list[float] = [float(v) for v in levels["L1"]["room"].split(",")]
        self.assertEqual((6, 6), (len(tray), len(room)))
        for index, axis in enumerate("xyz"):
            with self.subTest(axis=axis):
                self.assertGreaterEqual(
                    tray[2 * index] - room[2 * index],
                    0.005,
                    f"tray {tray}, room {room}",
                )
                self.assertGreaterEqual(
                    room[2 * index + 1] - tray[2 * index + 1],
                    0.005,
                    f"tray {tray}, room {room}",
                )

    def test_after_the_ssd_the_pallet_fades_and_the_robot_walks_back_to_its_place(
        self,
    ) -> None:
        """Back at the floor from the NVMe SSD, every 0.1 s from 0.05 s to 2.55 s after ``back-from``, then 3.25 s after
        it (in the view where the hard disk's part begins) and 0.5 s after the ride down to the hard disk begins: the
        pallet (``data-pallet``) shows at first, fades (``data-pallet-opacity`` between 0 and 1 at some reading) and is
        gone from 0.8 s after ``back-from`` on; the robot (``data-robot-at``) starts by the pallet, more than 2 m from
        its place, never moves more than 0.35 m between two readings 0.1 s apart (its fastest step on this walk is
        about 0.25 m), and stands within 1 cm of where it stood on the ride down to the SSD at the walk's last reading
        and the two after it, ready for the next ride.

        Fails if the pallet vanishes at once or stays, if the robot jumps from the pallet to its place (2.3 m in one
        frame), or if it starts the next ride from another place.
        """
        _, levels = self.read_levels()

        # where the robot stands on the ride down to the SSD:
        _, stage = self.stage_at(float(levels["NVMe SSD"]["down-from"]) + 0.5, "down")
        home: tuple[float, ...] = tuple(float(v) for v in stage["robot-at"].split(","))

        # every 0.1 s of the walk back, then where the hard disk's part and its ride begin:
        back_from: float = float(levels["NVMe SSD"]["back-from"])
        walk: list[dict[str, str]] = self.stages_between(
            back_from + 0.05, back_from + 2.6, 0.1
        )
        later: list[dict[str, str]] = [
            self.stage_at(back_from + 3.25, None)[1],
            self.stage_at(float(levels["HARD DISK"]["down-from"]) + 0.5, "down")[1],
        ]

        # the pallet shows at first, fades, and is gone from 0.8 s on (data-t has three decimals, hence 1 ms more):
        self.assertEqual("true", walk[0]["pallet"])
        self.assertTrue(
            any(0 < float(stage["pallet-opacity"]) < 1 for stage in walk),
            "the pallet does not fade",
        )
        for stage in walk + later:
            if float(stage["t"]) >= back_from + 0.8 + 1e-3:
                self.assertEqual("false", stage["pallet"], stage["t"])

        # the robot walks from the pallet to its place, never jumping:
        places: list[tuple[float, ...]] = [
            tuple(float(v) for v in stage["robot-at"].split(",")) for stage in walk
        ]
        self.assertGreater(math.dist(places[0], home), 2, "not by the pallet at first")
        for before, after, here, there in zip(walk, walk[1:], places, places[1:]):
            self.assertLessEqual(
                math.dist(here, there),
                0.35,
                f"the robot jumps, {before['t']} s to {after['t']} s: {here} to {there}",
            )

        # it stays at its place, also when the hard disk's part and its ride begin:
        for stage in [walk[-1]] + later:
            there: tuple[float, ...] = tuple(
                float(v) for v in stage["robot-at"].split(",")
            )
            self.assertLessEqual(
                math.dist(there, home), 0.01, f"{there} vs. {home} at {stage['t']}"
            )

    def test_the_stopwatch_rounds_before_it_picks_a_unit(self) -> None:
        """On rides down, at moments where a value rounds up to the next unit or to fewer decimals, the stopwatch shows
        it so: the human time from 59.95 s to just under 60 s reads "1 min 0 s", the depth below the surface from
        999.995 m to just under 1,000 m reads "1.00 km", the real time (``REAL_NS_PER_CYCLE`` per ``HUMAN_S_PER_CYCLE``
        of human time) from 999.95 ns to just under 1,000 ns reads "1.0 µs" and from 9.995 ns to just under 10 ns
        "10.0 ns". Each moment is found by halving a span of the film's time around it.

        Fails if a field picks its unit or its decimals before it rounds, and shows "60 s", "1000.00 m", "1000.0 ns" or
        "10.00 ns".
        """
        _, levels = self.read_levels()
        ns_per_human_s: float = self.REAL_NS_PER_CYCLE / self.HUMAN_S_PER_CYCLE

        def moment(
            start: float,
            end: float,
            read: Callable[[dict[str, str]], float],
            low: float,
            high: float,
        ) -> dict[str, str]:
            """Leaves the page at a time of the ride down between start and end at which read(stage), growing with
            the time there, lies in [low, high), found by halving the span, and returns the stage there; fails if
            there is none.
            """
            for _ in range(60):
                middle: float = (start + end) / 2
                _, stage = self.stage_at(middle, None)
                value: float = read(stage)
                if low <= value < high and stage["phase"] == "down":
                    return stage
                start, end = (middle, end) if value < low else (start, middle)
            self.fail(f"no time on the ride down with a value in [{low}, {high})")

        # (field, the level on whose ride down it is checked, what grows there, its window, the text expected):
        cases: list[
            tuple[str, str, Callable[[dict[str, str]], float], float, float, str]
        ] = [
            (
                "sw-human",
                "DRAM",
                lambda stage: float(stage["human-s"]),
                59.95,
                60,
                "1 min 0 s",
            ),
            (
                "sw-depth",
                "NVMe SSD",
                lambda stage: float(stage["depth"]),
                999.995,
                1000,
                "1.00 km",
            ),
            (
                "sw-real",
                "NVMe SSD",
                lambda stage: ns_per_human_s * float(stage["human-s"]),
                999.95,
                1000,
                "1.0 µs",
            ),
            (
                "sw-real",
                "DRAM",
                lambda stage: ns_per_human_s * float(stage["human-s"]),
                9.995,
                10,
                "10.0 ns",
            ),
        ]
        for field, key, read, low, high, text in cases:
            with self.subTest(field=field, text=text):
                # the page left at such a moment of the ride down to the level (its pickup, where the value stands at
                # its highest, ends the span), the field shows the text:
                moment(
                    float(levels[key]["down-from"]) + 0.01,
                    float(levels[key]["pickup-from"]),
                    read,
                    low,
                    high,
                )
                expect(self.opened.page.get_by_test_id(field)).to_have_text(text)

    def test_after_a_pause_the_header_shows_the_numbers_of_that_moment(self) -> None:
        """While the film plays a long ride fast, the header's numbers change five times a second only (else they
        would flicker); paused, the page draws once more, so that the stopwatch's cycles match the time it stopped at:
        ``sw-cycles`` is ``data-human-s`` ÷ 0.5 s, rounded, with thousands separated. To make the 200 ms of the
        header's pace certain, the page's clock (``performance.now``) stands still while the film plays and pauses, so
        its numbers are at most as new as the first frame (checked: just before the pause they lag behind the film);
        it runs again afterwards. The ride: 6 s into the one down to the SSD, where the film runs about 150 times
        faster than real time (the header slows down from 50 times on).

        Fails if pausing leaves the header with the numbers of a moment before the pause.
        """
        _, levels = self.read_levels()
        page: Page = self.opened.page
        play = page.get_by_test_id("play")

        # 6 s into the ride down to the SSD, playing, with the page's clock standing still:
        start: float = float(levels["NVMe SSD"]["down-from"]) + 6
        stage = page.get_by_test_id("stage")
        self.stage_at(start, "down")
        page.evaluate(
            """() => { window.__now = performance.now; const t0 = performance.now();
                performance.now = () => t0; }"""
        )
        try:
            play.click()
            expect(play).to_have_attribute("data-state", "playing")
            page.wait_for_function(
                "([stage, seconds]) => Number(stage.dataset.t) > seconds + 0.3",
                arg=[stage.element_handle(), start],
                timeout=FILM_TIMEOUT,
            )

            # while it plays, the header lags behind the film (read in one step: the cycles shown and the time):
            shown, human_now = stage.evaluate(
                """(stage) => [document.querySelector('[data-testid="sw-cycles"]').textContent,
                    Number(stage.dataset.humanS)]"""
            )
            self.assertNotEqual(f"{round(human_now / self.HUMAN_S_PER_CYCLE):,}", shown)

            # paused: after the page's next frame, the cycles shown match the time it stopped at:
            play.click()
            expect(play).to_have_attribute("data-state", "paused")
            page.evaluate(
                "() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"
            )
            human: float = float(stage.get_attribute("data-human-s") or "")
            expect(page.get_by_test_id("sw-cycles")).to_have_text(
                f"{round(human / self.HUMAN_S_PER_CYCLE):,}"
            )
        finally:
            # the page's clock runs again:
            page.evaluate("() => { performance.now = window.__now; }")

    def test_what_the_voice_names_lights_up_while_it_says_it(self) -> None:
        """Every half second from the film's start to the ride down to L1, and through the sizes view after main memory,
        the stage names what is lit because the voice names it (``data-highlight``, separated by ``|``): the register tray only in step 2
        (the core and its registers), the crate of the cache line only in step 3 (a crate is a cache line); in step 8
        (the faster, the smaller), the factors appear one after the other, as the voice says them (L2 ×64, then L3
        ×768, then DRAM ×699,051), each staying once it is there, and only in that step (``data-scene``).

        Fails if something lights up in another step than the one whose words name it, never lights up, or if a factor
        comes out of order or goes again.
        """
        _, levels = self.read_levels()

        def lit_by_step(start: float, end: float) -> list[tuple[str, set[str]]]:
            """Returns, every half second from start to end, the step's number and what is lit then."""
            return [
                (stage["scene"], set(filter(None, stage["highlight"].split("|"))))
                for stage in self.stages_between(start, end, 0.5)
            ]

        # from the start to the ride down to L1: the registers and the cache line, each in its own step:
        early = lit_by_step(0, float(levels["L1"]["down-from"]))
        for name, step in (("registers", "2"), ("cache line", "3")):
            steps: set[str] = {scene for scene, lit in early if name in lit}
            self.assertEqual({step}, steps, f"{name} lit in steps {steps}")

        # through the sizes view: the factors one after the other, each staying, only in step 8:
        sizes = lit_by_step(
            float(levels["DRAM"]["back-from"]), float(levels["NVMe SSD"]["down-from"])
        )
        factors: list[str] = ["L2 ×64", "L3 ×768", "DRAM ×699,051"]
        shown_so_far: list[list[str]] = [
            [name for name in factors if name in lit] for _, lit in sizes
        ]
        for (scene, _), names in zip(sizes, shown_so_far):
            if names:
                self.assertEqual("8", scene, f"factors {names} in step {scene}")
        counts: list[int] = [len(names) for names in shown_so_far if names]
        self.assertEqual([1, 2, 3], sorted(set(counts)), f"{shown_so_far}")
        for names in shown_so_far:
            self.assertEqual(factors[: len(names)], names, "a factor out of order")
        self.assertEqual(sorted(counts), counts, "a factor goes again")

    def test_the_card_at_the_end_lists_every_round_trip(self) -> None:
        """At the end, the card lists the round trip of the registers and of every level (``round-trips``, a row
        ``trip-<level>`` each, in order from the registers to the hard disk): its cycles with thousands separators,
        the real time as the stopwatch writes it, and the human time of the slides (``HUMAN_TEXTS``, the registers half
        a second).

        Fails if a level is missing or out of order, or if a row gives other cycles or another human time than the
        slides.
        """
        # half a second before the film's end, with the card shown:
        self.read_levels()
        duration: float = float(
            self.opened.page.get_by_test_id("stage").get_attribute("data-duration")
            or ""
        )
        opened, _ = self.stage_at(duration - 0.5, None)
        rows = opened.page.get_by_test_id("round-trips").locator("tbody tr")

        # one row per level, in order, with its cycles and its human time:
        expected: list[tuple[str, int, str]] = [("registers", 1, "0.5 s")] + [
            (key, cycles, self.HUMAN_TEXTS[key])
            for key, (cycles, _) in self.SLIDES.items()
        ]
        expect(rows).to_have_count(len(expected))
        test_ids: list[str] = rows.evaluate_all(
            "(rows) => rows.map((r) => r.dataset.testid)"
        )
        self.assertEqual(
            [
                "trip-registers",
                "trip-l1",
                "trip-l2",
                "trip-l3",
                "trip-main-memory",
                "trip-nvme-ssd",
                "trip-hard-disk",
            ],
            test_ids,
        )
        cells: list[list[str]] = rows.evaluate_all(
            "(rows) => rows.map((r) => [...r.cells].map((c) => c.textContent))"
        )
        for (key, cycles, human), (_, shown_cycles, real, shown_human) in zip(
            expected, cells
        ):
            with self.subTest(level=key):
                self.assertEqual(f"{cycles:,}", shown_cycles)
                self.assertEqual(human, shown_human)
                self.assertRegex(real, r"^\d+(\.\d+)? (ns|µs|ms)$")


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class ExternalSortingPageTest(_PageTestCase):
    """Checks the external sorting page (decision 046): its counter counts the pages that the repository's external
    merge sort reads and writes, its film makes the runs of the code, and its narration, which a synthetic voice says,
    fits the film.

    The page sorts table R, 36 pages of 16 keys, with a main memory of 4 pages and fan-in 3, in three passes: pass 0,
    merge level 1 and the final merge. Its header counts the pages read (``reads``) and written (``writes``); its
    script writes the same numbers into data-* of ``stage``, with the step of the film under way (``data-phase``, e.g.
    ``read``), the level the bench works on (``data-level``, 0 in pass 0), the values on the merges' heap stand
    (``data-heap``) and what is lit because the voice names it (``data-highlight``). test_external_sorting_page_data.py
    checks the page counts and runs of external_sorting_page_data.py, which these tests expect, against the real
    ExternalMergeSort. The tests of the film open the page paused at a moment given in its URL and wait until it has
    prepared its GPU programs (open_at); some move it on from there with the slider (see stages_from), and the tests
    of the merges share one such sweep (see merge_stages).

    The narration is the 25 captions of CAPTIONS: each begins in the step it tells of (CAPTION_STEPS), the voice has
    said a caption before the next part begins, what the voice names lights up while it says it, and the page stops
    if a clip of its voice does not belong to its caption; EveryPageWithSoundTest checks the voice itself. The page's
    own controls, which EveryPageTest does not check, are checked as on the storage hierarchy page: the part buttons,
    full screen and the review clips; so are the part's name top left as a part begins, the hint how to switch on the
    sound, which gives way to the end card, and the end card's credit to the voice. Some of the tests that look only at
    the header, the narration, the controls or the end card do not wait for the GPU (open_controls).
    """

    PAGE: Path | None = EXTERNAL_SORTING_PAGE
    # the page is ready once it has prepared its GPU programs, a few per frame: about 1.5 s on a fast machine with a
    # GPU emulated in software, several times that on a slow CI runner, so a wait for it ends after this many
    # milliseconds (as for the storage hierarchy page):
    READY_TIMEOUT: int = 8 * FILM_TIMEOUT
    # the readings of the merges that the tests share, once merge_stages has made them; None until then:
    shared_merge_stages: list[dict[str, str]] | None = None
    # what the voice names stays lit from just before its phrase's first word (0.15 s) until a moment (1.8 s at most)
    # after its last; the longest phrase that lights something up takes about 3 s, so a highlight lasts at most this
    # many seconds:
    LIT_AT_MOST: float = 6.0
    # the narration, caption by caption, as the page shows it (without the marks of the words that name a result, which
    # show green); the voice says each caption, its numbers written out (e.g. "one hundred and eight" for 108):
    CAPTIONS: list[str] = [
        (
            "Table R: 36 pages of 16 keys, unsorted. The query wants them sorted, but"
            " main memory holds only 4 pages."
        ),
        (
            "As in the B-tree film, we linearize the rack sections: page after page, "
            "as the file lies on disk."
        ),
        (
            "For the purpose of the visualization, each section tips onto its back "
            "and stays whole: one page."
        ),
        (
            "From above: 16 values, four rows of four, ordered left to right and top "
            "to bottom. The blue bar shows the key."
        ),
        (
            "Pass 0. Main memory is a workbench with room for 4 pages. A cable pulls "
            "R's first 4 pages onto it, one after the other."
        ),
        (
            "In memory, quicksort sorts the 64 values: the red one is the pivot. "
            "Values smaller than it swap into the left part, larger ones into the "
            "right part; then the same for each part, recursively."
        ),
        (
            "The sorted pages leave by the second cable, close behind each other, "
            "into a temporary file: Run 1."
        ),
        (
            "The same for the rest of R: nine runs of 4 pages, each one sorted. Every"
            " page was read once and written once."
        ),
        (
            "For the next pass, for the purpose of the visualization, the bench "
            "drives round the runs, one level down; in reality we use the same main "
            "memory as before. Input comes from above, output goes below."
        ),
        (
            "Merge level 1 merges three runs at a time. Each sends its first page "
            "onto the bench; the fourth place takes the output."
        ),
        (
            "The first value of each input page goes into a heap of three. Its root, "
            "at the top, holds the smallest."
        ),
        (
            "The value at the root of the heap goes to the output page. The next "
            "value of its run takes the root's place and swaps with a smaller child."
        ),
        (
            "The size of the heap is so small that its memory requirements can be "
            "neglected for small inputs like this one."
        ),
        (
            "The output page is full: it goes to Run 10, and an empty page takes its "
            "place."
        ),
        (
            "An input page is used up: it goes to the depot, and its cable brings the"
            " next page of its run."
        ),
        (
            "From here the film runs faster. Memory never holds more than four pages:"
            " one page of each input run, and the output page. That is why it merges "
            "three runs at a time. All input runs are merged the same way into larger"
            " output runs."
        ),
        (
            "Two more merges: Runs 4, 5 and 6 into Run 11, Runs 7, 8 and 9 into Run "
            "12. The merged input runs can be deleted."
        ),
        (
            "Like pass 0, merge level 1 reads every page once and writes it once: "
            "when it ends, the counter shows 72 reads and 72 writes: so far, each "
            "page was read twice and written twice."
        ),
        "Three runs of 12 pages are left: one more level down.",
        (
            "The final merge takes Runs 10, 11 and 12. Its output is not written to "
            "disk, but streamed to the consumer."
        ),
        (
            "Each full page goes straight on to the query: the first 16 values of the"
            " result."
        ),
        (
            "The query gets the result page by page, in sorted order, while the merge"
            " is still running: it can start working before the sort is done."
        ),
        (
            "Nine runs with fan-in 3 need two merge levels: nine runs become three, "
            "three become one. More memory means a larger fan-in and fewer passes."
        ),
        (
            "Note, though: because of the random access times of disks and SSDs, "
            "setting the fan-in to the largest possible value does not necessarily "
            "give the shortest end-to-end sort time."
        ),
        (
            "Each of the three passes read all 36 pages, and the first two also wrote"
            " all 36: 108 reads and 72 writes."
        ),
    ]
    # the step of the header (01 … 13) in which each caption of CAPTIONS begins: one in each of the steps 1 to 8 but
    # two in step 3, seven in step 9 (the first merge of level 1), two in step 10, one in step 11, five in step 12
    # (the final merge) and one in step 13:
    CAPTION_STEPS: list[int] = (
        [1, 2, 3, 3, 4, 5, 6, 7, 8] + [9] * 7 + [10, 10, 11] + [12] * 5 + [13]
    )

    def open_at(self, query: str) -> tuple[OpenedPage, dict[str, str]]:
        """Opens the page with the given URL parameters, waits until it is ready and reads the stage's data-*
        attributes.

        @param query: e.g. ``?t=40&paused`` for the moment 40 s into the film, or ``?q=3&paused`` for the start of
            part 3
        @return: the opened page, and the stage's attributes without ``data-`` (e.g. ``reads``)
        """
        opened: OpenedPage = self.open_page(EXTERNAL_SORTING_PAGE, query=query)
        stage = opened.page.get_by_test_id("stage")

        # the browser can draw the scene (WebGL 2), as the script says at once, so that a browser without it fails
        # here and not after the long wait below:
        expect(stage).to_have_attribute("data-renderer", "webgl2")

        # the page has made its film, after checking that its own quicksort and heap give the code's runs; if that
        # check throws, the page's own error is reported now, not as a timeout after the long wait below:
        try:
            expect(stage).to_have_attribute(
                "data-made", re.compile("."), timeout=FILM_TIMEOUT
            )
        except AssertionError:
            self.assert_no_errors(opened)
            raise

        # the page has prepared its GPU programs and textures and drawn a whole frame, with the text of its textures in
        # the embedded fonts, not in fallbacks:
        expect(stage).to_have_attribute(
            "data-ready", "true", timeout=self.READY_TIMEOUT
        )
        expect(stage).to_have_attribute("data-fonts", "embedded")
        self.assert_no_errors(opened)
        attributes: dict[str, str] = stage.evaluate(
            """(stage) => Object.fromEntries([...stage.attributes].filter((a) => a.name.startsWith('data-'))
                .map((a) => [a.name.slice('data-'.length), a.value]))"""
        )
        return opened, attributes

    def open_controls(self, query: str = "?paused") -> OpenedPage:
        """Opens the page with the given URL parameters and waits only until it has set up its controls, not until it
        has prepared its GPU programs (see open_at): for tests of the header, the narration, the controls and the end
        card, which the page shows without drawing the scene. The page sets up its controls at the end of its
        start-up, after its own checks and after writing ``data-made``.

        @param query: e.g. ``?paused`` for the start of the film
        @return: the opened page, which has had no errors so far
        """
        opened: OpenedPage = self.open_page(EXTERNAL_SORTING_PAGE, query=query)

        # the page has made its film and set up its controls; if a check of its start-up throws, the page's own error
        # is reported, not a timeout:
        try:
            expect(opened.page.get_by_test_id("stage")).to_have_attribute(
                "data-made", re.compile("."), timeout=FILM_TIMEOUT
            )
            expect(opened.page.get_by_test_id("play")).to_be_enabled()
        except AssertionError:
            self.assert_no_errors(opened)
            raise
        self.assert_no_errors(opened)
        return opened

    def stages_from(
        self, opened: OpenedPage, step: float, until: str
    ) -> list[dict[str, str]]:
        """Moves the slider of an opened page on from the time it shows, step seconds at a time, until the stage shows
        the phase until or the film ends, and reads the stage's data-* attributes after each move.

        All in one call into the page, which shows a time at once when the slider moves; the slider takes the step
        ``any`` for it, so that it can stand at any time of the film, not only at its 1000 steps. The page draws each
        of these times, so the sweep waits for an animation frame after every 25 of them (as the Yannakakis page's test
        does): else, on a GPU emulated in software, their drawings pile up in the browser. The window is made small
        first, which makes each drawing a little cheaper; the stage's data-* do not depend on its size. Asserts that
        the stage shows each time (its data-t, with three decimals) and that the sweep has reached the phase until.

        @param opened: the page, opened paused with open_at
        @param step: the time between two readings (s)
        @param until: the phase to stop at, e.g. ``benchMove``: the sweep ends with the first reading that shows it
        @return: the stage's attributes after each move (without ``data-``, e.g. ``heap``; all but ``made``, which the
            page writes once at start-up and which is long), with the words of the caption shown (``words``) and how
            many of them the voice has said (``said``), in order; the first one step after the time the page showed
        """
        stage = opened.page.get_by_test_id("stage")
        start: float = float(stage.get_attribute("data-t") or "")
        opened.page.set_viewport_size({"width": 320, "height": 180})

        # from the page's time on, step by step, until the phase until (in the browser, without a round trip per step):
        stages: list[dict[str, str]] = opened.page.get_by_test_id("scrub").evaluate(
            """async (scrub, [stage, narration, start, step, until]) => {
                const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()));
                const duration = Number(stage.dataset.duration), stages = [];
                scrub.step = 'any';
                for (let k = 1; start + k * step <= duration; k += 1) {
                    scrub.value = String(((start + k * step) / duration) * Number(scrub.max));
                    scrub.dispatchEvent(new Event('input', { bubbles: true }));
                    stages.push({
                        ...Object.fromEntries([...stage.attributes]
                            .filter((a) => a.name.startsWith('data-') && a.name !== 'data-made')
                            .map((a) => [a.name.slice('data-'.length), a.value])),
                        words: narration.textContent.trim(), said: narration.dataset.wordsSaid,
                    });
                    if (stage.dataset.phase === until) break;
                    if (k % 25 === 0) await frame();
                }
                await frame();
                await frame();
                return stages;
            }""",
            [
                stage.element_handle(),
                opened.page.get_by_test_id("narration").element_handle(),
                start,
                step,
                until,
            ],
        )

        # the stage showed each time, and the sweep ended in the phase until:
        for k, shown in enumerate(stages, 1):
            self.assertAlmostEqual(start + k * step, float(shown["t"]), delta=1e-3)
        self.assertEqual(until, stages[-1]["phase"], "the sweep did not reach it")
        return stages

    def merge_stages(self) -> list[dict[str, str]]:
        """Returns the stage's attributes from the start of part 3 (merge level 1) to the last step (``end``), read
        every 0.8 s by stages_from on a page opened at ``?q=3&paused``, for the tests of the merges.

        The sweep takes seconds on a GPU emulated in software, so the class sweeps once, for the first test that asks,
        which also checks the page's errors meanwhile, and keeps the readings for the others (as
        StorageHierarchyPageTest keeps its levels); each test gets copies of its own.

        @return: the readings, in order (see stages_from)
        """
        cls: type[ExternalSortingPageTest] = type(self)
        if cls.shared_merge_stages is None:
            opened, _ = self.open_at("?q=3&paused")
            stages: list[dict[str, str]] = self.stages_from(opened, 0.8, "end")
            self.assert_no_errors(opened)
            # close the page, which the other tests do not need:
            opened.page.context.close()
            cls.shared_merge_stages = stages
        return [dict(shown) for shown in cls.shared_merge_stages]

    def stage_at(self, opened: OpenedPage, seconds: float) -> dict[str, str]:
        """Moves the slider of an opened page to a time of the film, with the step ``any`` as in stages_from, and reads
        the stage's data-* attributes, which the page sets at once when the slider moves. Asserts that the stage shows
        the time (its data-t, with three decimals).

        @param opened: the page, opened with open_at
        @param seconds: the time
        @return: the stage's attributes without ``data-``
        """
        shown: dict[str, str] = opened.page.get_by_test_id("scrub").evaluate(
            """(scrub, [stage, seconds]) => {
                scrub.step = 'any';
                scrub.value = String((seconds / Number(stage.dataset.duration)) * Number(scrub.max));
                scrub.dispatchEvent(new Event('input', { bubbles: true }));
                return Object.fromEntries([...stage.attributes].filter((a) => a.name.startsWith('data-'))
                    .map((a) => [a.name.slice('data-'.length), a.value]));
            }""",
            [opened.page.get_by_test_id("stage").element_handle(), seconds],
        )
        self.assertAlmostEqual(seconds, float(shown["t"]), delta=1e-3)
        return shown

    @staticmethod
    def next_values(runs: list[list[int]], least: int) -> set[int]:
        """Returns the next value of each run that a merge has not used up, once it has given out all values below
        least: each run's smallest value that is least or larger.

        @param runs: the runs that a merge reads, each in ascending order
        @param least: the smallest value not yet given out
        @return: one value per run with a value of least or more
        """
        return {min(v for v in run if v >= least) for run in runs if run[-1] >= least}

    def test_at_the_end_the_counter_shows_108_reads_and_72_writes(self) -> None:
        """The counter starts at 0 pages read and 0 written; at the end of the film, it shows 108 read and 72 written,
        the pages the code's sort reads and writes (EXPECTED_READS, EXPECTED_WRITES), in the header and on the stage,
        and the last step's title and caption name the same two numbers.

        Fails if the page counts a page that the code does not read or write (e.g. the final merge's output pages as
        writes) or misses one, or if the title or the caption, typed by hand, names other numbers than the counter.
        """
        opened, stage = self.open_at("?paused")
        page: Page = opened.page

        # at the start, nothing is read or written yet:
        self.assertEqual(("0", "0"), (stage["reads"], stage["writes"]))

        # the slider to its end:
        page.get_by_test_id("scrub").fill("1000")
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "ended")
        expect(page.get_by_test_id("stage")).to_have_attribute("data-phase", "end")

        # the counter in the header and on the stage:
        expect(page.get_by_test_id("reads")).to_have_text(str(EXPECTED_READS))
        expect(page.get_by_test_id("writes")).to_have_text(str(EXPECTED_WRITES))
        expect(page.get_by_test_id("stage")).to_have_attribute(
            "data-reads", str(EXPECTED_READS)
        )
        expect(page.get_by_test_id("stage")).to_have_attribute(
            "data-writes", str(EXPECTED_WRITES)
        )

        # the last step's title and caption sum up with the same numbers:
        expect(page.get_by_test_id("step-name")).to_contain_text(
            f"{EXPECTED_READS} reads, {EXPECTED_WRITES} writes"
        )
        expect(page.get_by_test_id("nar-text")).to_contain_text(
            f"{EXPECTED_READS} reads and {EXPECTED_WRITES} writes"
        )
        self.assert_no_errors(opened)

    def test_in_pass_0_pages_are_read_before_any_is_written(self) -> None:
        """47.5 s into the film, while pass 0 loads its first 4 pages onto the bench, the counter shows 3 pages read
        and none written, in the header and on the stage: pass 0 begins 38.5 s into the film (after the opening, whose
        scenes last as long as the voice speaks) and sends a page of R every 4 s, and a page counts as read once it
        sets out, so the third, which set out at 46.5 s, is counted while it rides.

        Fails if the page counts a page as written before pass 0 has sorted its first load, or as read only once it
        has arrived on the bench (the counter would show 2), or counts a page twice.
        """
        opened, stage = self.open_at("?t=47.5&paused")
        page: Page = opened.page

        # the moment lies in pass 0, while pages of R ride onto the bench:
        self.assertEqual(
            ("read", "0"),
            (stage["phase"], stage["level"]),
            "47.5 s into the film, pass 0 no longer loads its first pages",
        )

        # 3 pages read, none written:
        self.assertEqual("3", stage["reads"], "pages read 47.5 s into the film")
        self.assertEqual("0", stage["writes"], "pages written 47.5 s into the film")

        # the header shows the same:
        expect(page.get_by_test_id("reads")).to_have_text("3")
        expect(page.get_by_test_id("writes")).to_have_text("0")
        self.assert_no_errors(opened)

    def test_each_pass_reads_all_36_pages_and_all_but_the_last_write_them(
        self,
    ) -> None:
        """At the start of part 3, when the bench drives down after pass 0, the counter shows 36 pages read and 36
        written; at the start of part 4, after merge level 1, 72 and 72: each of the two passes reads all 36 pages of
        the data and writes them again (EXPECTED_PASS_COUNTS), which leaves the final merge's 36 reads for the end.

        Fails if a pass counts a page twice or not at all (e.g. a merge's input page counted once as it sets out and
        again as it arrives on the bench), or if a pass's last write is counted only in the next pass.
        """
        # (URL, the level of the pass that has just ended, the number of passes done):
        cases: list[tuple[str, str, int]] = [
            ("?q=3&paused", "0", 1),
            ("?q=4&paused", "1", 2),
        ]
        for query, level, passes in cases:
            with self.subTest(query=query):
                opened, stage = self.open_at(query)
                page: Page = opened.page

                # the bench is about to drive down from the level of the pass that has just ended:
                self.assertEqual(("benchMove", level), (stage["phase"], stage["level"]))

                # the pages read and written by the passes done, on the stage and in the header:
                done: list[PageCounts] = EXPECTED_PASS_COUNTS[:passes]
                reads: str = str(sum(counts.reads for counts in done))
                writes: str = str(sum(counts.writes for counts in done))
                self.assertEqual((reads, writes), (stage["reads"], stage["writes"]))
                expect(page.get_by_test_id("reads")).to_have_text(reads)
                expect(page.get_by_test_id("writes")).to_have_text(writes)
                self.assert_no_errors(opened)
                # close the page before the next one opens, not only at the end of the test:
                opened.page.context.close()

    def test_pass_0_reads_sorts_and_writes_each_load_in_turn(self) -> None:
        """Pass 0 takes R in 9 loads of 4 pages, one after the other: it reads a load's pages onto the bench, sorts
        them, writes them as a run, and only then reads the next load; after the last run, the bench drives down a
        level. Read every 0.3 s from the start of part 2 to the bench's drive, the step under way (data-phase) and the
        counter agree: while a load is read, the runs of all loads before it are written; while it is sorted, all its
        4 pages are read and none of its run is written; while it is written, between none and all 4 of its pages are.

        Fails if the bench sorts a load before all its pages have arrived, writes it before it is sorted or reads the
        next load before the run is written, if a step of pass 0 shows another level than 0, or if a load is missing.
        """
        opened, _ = self.open_at("?q=2&paused")
        stages: list[dict[str, str]] = self.stages_from(opened, 0.3, "benchMove")
        loads: int = EXPECTED_PASS_COUNTS[0].reads // MEMORY_PAGES

        # the bench drives down from the level of pass 0 once the last run is written:
        self.assertEqual("0", stages[-1]["level"])

        # before, each reading lies in pass 0, in the load of the page read last (page i of R, from 1, is in load
        # (i - 1) // 4, from 0), at a step of that load:
        steps: list[str] = ["read", "sort", "out"]
        order: list[tuple[int, int]] = []
        for shown in stages[:-1]:
            at: str = f"at {shown['t']} s ({shown['phase']})"
            self.assertEqual("0", shown["level"], at)
            self.assertIn(shown["phase"], steps, at)
            reads, writes = int(shown["reads"]), int(shown["writes"])
            load: int = (reads - 1) // MEMORY_PAGES
            order.append((load, steps.index(shown["phase"])))

            # the runs of the loads before are written; once the load is sorted, all its pages are read:
            done: int = MEMORY_PAGES * load
            if shown["phase"] == "read":
                self.assertEqual(done, writes, at)
            elif shown["phase"] == "sort":
                self.assertEqual((done + MEMORY_PAGES, done), (reads, writes), at)
            else:
                self.assertEqual(done + MEMORY_PAGES, reads, at)
                self.assertGreaterEqual(writes, done, at)
                self.assertLessEqual(writes, done + MEMORY_PAGES, at)

        # load after load, each read, then sorted, then written; each load seen at each of its steps (the shortest, the
        # writing of a load at fast forward, takes about 0.7 s):
        self.assertEqual(sorted(order), order)
        self.assertEqual(
            {(load, step) for load in range(loads) for step in range(len(steps))},
            set(order),
        )
        self.assert_no_errors(opened)

    def test_the_final_merge_reads_the_36_pages_of_its_runs_and_writes_none(
        self,
    ) -> None:
        """Read every 0.8 s from the start of part 3 to the last step (merge_stages): at level 2, the counter's writes
        stay at 72 throughout the final merge, also while its full output pages leave the bench for the query, and its
        reads climb, never back, from the 72 of the passes before to 108: the final merge reads the 36 pages of Runs
        10, 11 and 12 and writes none (EXPECTED_PASS_COUNTS).

        Fails if the page counts an output page of the final merge as written, even only while the page moves (an
        output page of merge level 1 counts once it has arrived in its run), or if a read is counted and taken back.
        """
        final: list[dict[str, str]] = [
            shown for shown in self.merge_stages() if shown["level"] == "2"
        ]
        reads_before: int = sum(counts.reads for counts in EXPECTED_PASS_COUNTS[:2])

        # no page written, also while an output page leaves for the query (the first one at real speed, for 10 s):
        self.assertEqual({str(EXPECTED_WRITES)}, {shown["writes"] for shown in final})
        outputs: list[dict[str, str]] = [
            shown for shown in final if shown["phase"] == "swapOut"
        ]
        self.assertGreaterEqual(
            len(outputs), 5, "readings while an output page leaves for the query"
        )

        # the reads climb from those of the passes before to all 108, never back:
        reads: list[int] = [int(shown["reads"]) for shown in final]
        self.assertEqual(sorted(reads), reads)
        self.assertGreater(
            reads[0], reads_before, f"reads at level 2's first reading, {final[0]}"
        )
        self.assertEqual(EXPECTED_READS, reads[-1], "reads at the last step")

    def test_the_heap_holds_the_next_value_of_each_run_with_the_smallest_at_its_root(
        self,
    ) -> None:
        """Read every 0.8 s from the start of part 3 (merge level 1) to the last step (merge_stages), the merges' heap
        stand (data-heap: its root and two children at the start of the step under way) is the heap of a merge: at
        each level, a merge fills it (hInit) after its pages have come and before the first value goes out (mv); its
        root is smaller than the children present, and a second child is there only with the first; while a value
        goes out, it holds exactly the next value of each run of the merge not yet used up, the smallest on the root,
        each on the place where the code's heap holds it then (merge_heaps, which test_external_sorting_page_data.py
        checks against the code's SingleStreamMerge); while a new input page refills it (hFill), the root's place is
        empty; its values come from different runs of one merge, at level 1 of the groups EXPECTED_GROUPS in their
        order; and while the bench drives, the pages of a merge come and hInit begins, it is empty.

        Fails if the heap gives out a value that is not the smallest left (e.g. a missed swap of the root with a
        smaller child), puts a value on another place than the code's heap (e.g. swaps the root with the first smaller
        child, not the smallest, or fills the heap from the runs in another order), keeps a value of a used-up run or
        of the merge before, holds two values of one run, gives out a value before it is filled, or if the stage shows
        the heap of another moment than the step's start (e.g. the filled heap as hInit begins).
        """
        stages: list[dict[str, str]] = self.merge_stages()

        # the runs as the page draws them, r1 … r9 of pass 0 and r10 … r12, the runs that merge level 1 writes into
        # level 2's row (level_2_runs), and each value's run:
        runs: list[list[int]] = pass_0_runs(read_input())
        level_2_runs: list[list[int]] = merged_runs(runs, EXPECTED_GROUPS)
        run_of: dict[int, int] = {v: r for r, run in enumerate(runs) for v in run}
        level_2_run_of: dict[int, int] = {
            v: r for r, run in enumerate(level_2_runs) for v in run
        }
        group_of: dict[int, int] = {
            r: g for g, group in enumerate(EXPECTED_GROUPS) for r in group
        }

        # the code's heap by place before each value it gives out, at each level by that value, with None for an
        # empty place; a merge reads its runs in the order of its group, the final merge r10, r11, r12:
        heaps: dict[str, dict[int, list[int | None]]] = {"1": {}, "2": {}}
        merges: list[tuple[str, list[list[int]]]] = [
            ("1", [runs[r] for r in group]) for group in EXPECTED_GROUPS
        ] + [("2", level_2_runs)]
        for level, inputs in merges:
            for heap in merge_heaps(inputs):
                heaps[level][heap[0]] = [*heap, *[None] * (3 - len(heap))]

        # at each level, the inputs' first pages come, then the output's empty page, then the heap is filled, and
        # only then does the first value go out:
        for level in ("1", "2"):
            phases: list[str] = [
                phase
                for phase, _ in groupby(
                    shown["phase"]
                    for shown in stages
                    if shown["level"] == level and shown["phase"] != "benchMove"
                )
            ]
            self.assertEqual(
                ["mIn", "mEmpty", "hInit", "mv"], phases[:4], f"level {level}"
            )

        groups: list[int] = []
        going_out: dict[str, int] = {"1": 0, "2": 0}
        refills: int = 0
        for shown in stages:
            at: str = f"at {shown['t']} s ({shown['phase']}, heap {shown['heap']})"
            places: list[int | None] = [
                int(v) if v else None for v in shown["heap"].split(",")
            ]
            self.assertEqual(3, len(places), at)
            values: list[int] = [v for v in places if v is not None]

            # while the bench drives, a merge's pages come and its heap is about to be filled, the stand is empty:
            if shown["phase"] in ("benchMove", "mIn", "mEmpty", "hInit", "end"):
                self.assertEqual([None, None, None], places, at)
                continue

            # a heap: the second child only with the first, the root smaller than the children:
            if places[2] is not None:
                self.assertIsNotNone(places[1], at)
            if places[0] is not None:
                for child in values[1:]:
                    self.assertLess(places[0], child, at)
            if not values:
                continue

            # its values come from different runs of one merge, at level 1 of one group:
            inputs: list[list[int]] = level_2_runs
            if shown["level"] == "1":
                merged: list[int] = [run_of[v] for v in values]
                self.assertEqual(1, len({group_of[r] for r in merged}), at)
                groups.append(group_of[merged[0]])
                inputs = [runs[r] for r in EXPECTED_GROUPS[groups[-1]]]
            else:
                merged = [level_2_run_of[v] for v in values]
            self.assertEqual(len(values), len(set(merged)), at)

            # a value goes out: the heap holds the next value of each run not used up, the smallest on the root, each
            # on the place of the code's heap; a new page refills the root's place:
            if shown["phase"] == "mv":
                self.assertEqual(min(values), places[0], at)
                self.assertEqual(self.next_values(inputs, min(values)), set(values), at)
                self.assertEqual(heaps[shown["level"]].get(min(values)), places, at)
                going_out[shown["level"]] += 1
            elif shown["phase"] == "hFill":
                self.assertIsNone(places[0], at)
            if places[0] is None:
                refills += 1

        # merge level 1 takes the groups in their order:
        self.assertEqual(
            list(range(len(EXPECTED_GROUPS))), [group for group, _ in groupby(groups)]
        )

        # the readings caught many values going out at each level, and the root's place empty during a refill:
        self.assertGreaterEqual(
            min(going_out.values()), 20, f"values going out by level: {going_out}"
        )
        self.assertGreater(refills, 0, "readings during a refill")

    def test_the_page_makes_the_runs_and_the_output_of_the_code(self) -> None:
        """What the page's own quicksort and heap make, as its script writes it at start-up (``data-made``), is what
        the code makes: pass 0's runs are the 9 pieces of R, each sorted (pass_0_runs); merge level 1 writes the groups
        EXPECTED_GROUPS merged, in their order (merged_runs); the final merge gives out R sorted.
        test_external_sorting_page_data.py checks these against the real ExternalMergeSort.

        Fails if the page's quicksort or merge sorts wrongly, or if it makes other runs or merges other groups or in
        another order than the code, even where its start-up check, which compares them with its own RUNS and LEVEL2
        only, passes.
        """
        _, stage = self.open_at("?paused")
        made: MadeBySortingPage = json.loads(stage["made"])
        values: list[int] = read_input()
        runs: list[list[int]] = pass_0_runs(values)

        # the runs of pass 0, the runs of merge level 1 and the output, each in its order:
        self.assertEqual(runs, made["runs"])
        self.assertEqual(merged_runs(runs, EXPECTED_GROUPS), made["merged"])
        self.assertEqual(sorted(values), made["output"])

    def test_the_part_buttons_jump_to_their_parts_and_play(self) -> None:
        """Each of the four part buttons (the table, pass 0, merge level 1, the final merge), pressed from part 4 down
        to part 1, starting near the film's end (so that each jumps back from a later time), jumps to the start of its
        part and plays from there, and marks itself as the current part while the three others are not marked. The
        film's time is read in the same step as the click. Part 1 starts the film (at 0); parts 2 to 4 start where the
        step named after them begins: pass 0's first load, with its first page of R on its way (read), and the bench's
        drive down after pass 0 and after merge level 1 (benchMove, from level 0 and 1); 0.01 s earlier another step
        shows.

        Fails if a button jumps to another part or into the middle of one (e.g. past the start of its step), does not
        jump at all, does not play, leaves another part marked, or cannot be clicked (hidden or covered).
        """
        opened, _ = self.open_at("?t=340&paused")
        page: Page = opened.page
        stage = page.get_by_test_id("stage")
        play = page.get_by_test_id("play")
        step_name = page.get_by_test_id("step-name")
        # parts 2 to 4: (the name of the step they start with, the step's phase and level):
        later_parts: dict[int, tuple[str, str, str]] = {
            2: ("Pass 0: four pages into memory", "read", "0"),
            3: ("Down a level, round the runs", "benchMove", "0"),
            4: ("Down a level again", "benchMove", "1"),
        }
        for part in range(4, 0, -1):
            with self.subTest(part=part):
                # the button can be clicked; it jumps (its time read at once), plays, and is the one part marked:
                button = page.get_by_test_id(f"chapter-{part}")
                button.click(trial=True)
                seconds: float = float(
                    button.evaluate(
                        "(b, stage) => { b.click(); return stage.dataset.t; }",
                        stage.element_handle(),
                    )
                )
                expect(play).to_have_attribute("data-state", "playing")
                play.click()
                expect(play).to_have_attribute("data-state", "paused")
                expect(button).to_have_attribute("aria-current", "true")
                for other in range(1, 5):
                    if other != part:
                        expect(
                            page.get_by_test_id(f"chapter-{other}")
                        ).not_to_have_attribute("aria-current", "true")
                if part == 1:
                    self.assertEqual(0, seconds)
                    continue

                # 1 ms after the time read (data-t has three decimals: the part begins at most half a millisecond
                # from it), the part's step shows:
                title, phase, level = later_parts[part]
                shown: dict[str, str] = self.stage_at(opened, seconds + 0.001)
                expect(step_name).to_have_text(re.compile(f"· {re.escape(title)}$"))
                self.assertEqual((phase, level), (shown["phase"], shown["level"]))

                # 0.01 s before, another step:
                self.stage_at(opened, seconds - 0.01)
                expect(step_name).not_to_have_text(re.compile(f"· {re.escape(title)}$"))
        self.assert_no_errors(opened)

    def test_the_full_screen_button_and_the_key_f_switch_full_screen(self) -> None:
        """The full-screen button puts the page into full screen and says so (``aria-pressed`` true); the key F
        leaves it again (``aria-pressed`` false), and F once more enters it.

        Fails if the button or the key does nothing, or if the button does not show whether the page is in full screen.
        """
        opened, _ = self.open_at("?paused")
        page: Page = opened.page
        button = page.get_by_test_id("fullscreen")
        in_full_screen: str = "() => document.fullscreenElement !== null"

        # the button enters full screen:
        button.click()
        expect(button).to_have_attribute("aria-pressed", "true")
        self.assertTrue(page.evaluate(in_full_screen))

        # F leaves it, and enters it again:
        page.keyboard.press("f")
        expect(button).to_have_attribute("aria-pressed", "false")
        self.assertFalse(page.evaluate(in_full_screen))
        page.keyboard.press("f")
        expect(button).to_have_attribute("aria-pressed", "true")
        self.assertTrue(page.evaluate(in_full_screen))
        self.assert_no_errors(opened)

    def test_review_clips_play_one_after_the_other_and_then_pause(self) -> None:
        """Opened with the review clips 40-41 and 100-101 (``?clips=40-41,100-101``), the page stands paused at 40 s,
        its hint saying "review clip 1/2"; Play plays the first clip, goes on with the second from 100 s and pauses at
        its end, 101 s, the hint saying "end of review clips · press space to play on"; Play then plays on from there,
        and the hint goes.

        Fails if the page ignores the clips (starts elsewhere, or plays on past a clip's end: from 41 s to 100 s at
        real speed would outlast the wait), does not stop at the last clip's end, or shows the hint at the wrong time.
        """
        opened, shown = self.open_at("?clips=40-41,100-101&paused")
        page: Page = opened.page
        stage = page.get_by_test_id("stage")
        play = page.get_by_test_id("play")
        hint = page.get_by_test_id("clips-hint")

        # paused at the first clip's start:
        self.assertEqual("40.000", shown["t"])
        expect(hint).to_have_text("review clip 1/2")
        expect(play).to_have_attribute("data-state", "paused")

        # Play plays both clips and pauses at the second one's end:
        play.click()
        expect(hint).to_have_text(
            "end of review clips · press space to play on", timeout=FILM_TIMEOUT
        )
        expect(play).to_have_attribute("data-state", "paused")
        expect(stage).to_have_attribute("data-t", "101.000")

        # Play again plays on from there, without the hint:
        play.click()
        expect(play).to_have_attribute("data-state", "playing")
        expect(hint).to_be_hidden()
        expect(stage).not_to_have_attribute("data-t", "101.000")
        play.click()
        self.assertGreater(float(stage.get_attribute("data-t") or ""), 101)
        self.assert_no_errors(opened)

    def read_stops(self, opened: OpenedPage) -> list[dict[str, str]]:
        """Clicks Next on an opened page until its film has ended, and reads after each click where Next stopped: the
        stage's data-* attributes (without ``data-``; all but ``made``), the words of the caption shown (``words``) and
        how many of them the voice has said (``said``). All in one call into the page, which shows a stop at once.

        With sound off, Next stops where a caption is shown in full; while the voice may speak, where a caption begins.

        @param opened: the page, opened paused
        @return: the readings, one per click, the last one at the end of the film
        """
        page: Page = opened.page
        stops: list[dict[str, str]] = page.get_by_test_id("next").evaluate(
            """(next, [stage, narration, play, limit]) => {
                const stops = [];
                while (play.dataset.state !== 'ended' && stops.length < limit) {
                    next.click();
                    const { made, ...shown } = stage.dataset;
                    stops.push({ ...shown, words: narration.textContent.trim(), said: narration.dataset.wordsSaid });
                }
                return stops;
            }""",
            [
                page.get_by_test_id("stage").element_handle(),
                page.get_by_test_id("narration").element_handle(),
                page.get_by_test_id("play").element_handle(),
                MAX_NEXT_CLICKS,
            ],
        )

        # Next has led to the end of the film:
        expect(page.get_by_test_id("play")).to_have_attribute("data-state", "ended")
        return stops

    def test_the_narration_is_its_25_captions_in_order(self) -> None:
        """With sound off, Next stops once per caption, where the caption is shown in full, and then at the end of the
        film: the narration is the 25 captions of CAPTIONS, in their order, and at each stop the voice has said every
        word of its caption (the words light up as the voice says them, also with sound off).

        Fails if a caption is missing or added, says other words than CAPTIONS (the voice's clips are made for these
        texts, and the page checks that each clip belongs to its caption), if two captions change places, or if Next
        stops before the voice has said a caption in full.
        """
        opened: OpenedPage = self.open_controls()
        stops: list[dict[str, str]] = self.read_stops(opened)
        captions: list[dict[str, str]] = stops[:-1]

        # 25 captions, in their order:
        self.assertEqual(25, len(captions), "captions")
        self.assertEqual(self.CAPTIONS, [stop["words"] for stop in captions])

        # each said in full where Next stops:
        for n, stop in enumerate(captions, 1):
            self.assertEqual(
                str(len(stop["words"].split(" "))), stop["said"], f"caption {n}"
            )
        self.assert_no_errors(opened)

    def test_each_caption_begins_in_the_step_it_tells_of(self) -> None:
        """With sound on, Next stops where each caption begins, before the voice has said a word of it: each caption
        begins in its step of the header (CAPTION_STEPS), and those that tell of a moment begin as it comes, each in
        the one step that goes at real speed for it: "The output page is full" (caption 14) as merge level 1's first
        output page leaves for Run 10 (``swapOut``), "An input page is used up" (15) as its first input page used up
        goes to the depot (``swapIn``), and "Each full page goes straight on to the query" (21) as the final merge's
        first output page leaves for the query (``swapOut`` at level 2). The three captions after it begin in the final
        merge's fast forward, and the last one in the last step (``end``).

        Fails if a caption begins in another step, e.g. tells of a page leaving before the page is full (in the steps
        that fill it), or of a step that is over.
        """
        opened: OpenedPage = self.open_controls()
        page: Page = opened.page

        # the sound on, so that Next stops where a caption begins (the voice may speak, the narration is not shown):
        page.get_by_test_id("sound").click()
        expect(page.get_by_test_id("narration")).to_have_attribute("data-voiced", "")
        stops: list[dict[str, str]] = self.read_stops(opened)
        expect(page.get_by_test_id("narration")).to_have_attribute("data-voiced", "")
        starts: list[dict[str, str]] = stops[:-1]

        # one stop where each caption begins, none of its words said yet, then the end:
        self.assertEqual(self.CAPTIONS, [stop["words"] for stop in starts])
        self.assertEqual(["0"] * len(starts), [stop["said"] for stop in starts])

        # each caption begins in its step of the header:
        self.assertEqual(self.CAPTION_STEPS, [int(stop["scene"]) for stop in starts])

        # captions 14, 15 and 21 begin in the steps they tell of (phase, level, speed: real speed only there):
        moments: dict[int, tuple[str, str, str]] = {
            14: ("swapOut", "1", "1"),
            15: ("swapIn", "1", "1"),
            21: ("swapOut", "2", "1"),
        }
        for caption, moment in moments.items():
            stop: dict[str, str] = starts[caption - 1]
            self.assertEqual(
                moment,
                (stop["phase"], stop["level"], stop["speed"]),
                f"caption {caption}, at {stop['t']} s",
            )

        # captions 22 to 24 in the final merge's fast forward, the last one in the last step:
        for caption in (22, 23, 24):
            stop = starts[caption - 1]
            at: str = f"caption {caption}, at {stop['t']} s"
            self.assertEqual("2", stop["level"], at)
            self.assertGreater(float(stop["speed"]), 1, at)
        self.assertEqual("end", starts[24]["phase"])
        self.assert_no_errors(opened)

    def test_the_voice_has_said_the_caption_before_a_part_begins(self) -> None:
        """Where parts 2, 3 and 4 begin, as their buttons jump there, the voice has said every word of the caption
        before: a jump to a part with sound on does not begin in the middle of a sentence. The narration is read in the
        same step as the click on the part's button.

        Fails if a caption is still being said as a part begins, e.g. one that begins too late in the part before for
        its words to fit.
        """
        opened: OpenedPage = self.open_controls()
        page: Page = opened.page

        # each part button jumps to its part's start and plays from there; the narration is read at once, then the
        # film is paused again:
        readings: list[dict[str, str]] = page.get_by_test_id("play").evaluate(
            """(play, [stage, narration, buttons]) => buttons.map((button) => {
                button.click();
                const reading = { t: stage.dataset.t, words: narration.textContent.trim(),
                    said: narration.dataset.wordsSaid };
                play.click();
                return reading;
            })""",
            [
                page.get_by_test_id("stage").element_handle(),
                page.get_by_test_id("narration").element_handle(),
                [
                    page.get_by_test_id(f"chapter-{part}").element_handle()
                    for part in (2, 3, 4)
                ],
            ],
        )

        # as each part begins, the caption before it has been said in full:
        for part, reading in zip((2, 3, 4), readings, strict=True):
            at: str = f"part {part}, at {reading['t']} s"
            words: list[str] = reading["words"].split(" ")
            self.assertGreater(len(words), 1, f"{at}: no caption before it")
            self.assertEqual(str(len(words)), reading["said"], at)
        self.assert_no_errors(opened)

    def test_what_the_voice_names_lights_up_while_it_says_it(self) -> None:
        """While the voice names a thing in the picture, the stage names it as lit (``data-highlight``, separated by
        ``|``; the times are the clips' word times, so the same with sound off), each for one short stretch (at most
        ``LIT_AT_MOST`` s) per phrase that names it, in the step of that phrase:

        - the workbench in step 4 (pass 0's first load: "Main memory is a workbench …");
        - the counter of pages read and written in step 7 (pass 0's eight more loads: "Every page was read once and
          written once"), in step 10 (merge level 1's two more merges: "the counter shows 72 reads and 72 writes")
          and in step 13, the last ("The bill"), from the word "108" on ("108 reads and 72 writes"), outlined in green
          exactly while it is lit;
        - the heap stand, its root and the depot one after the other in step 9 (the first merge of level 1), the heap
          and its root while the heap is filled (``hInit``).

        Each stretch is tied to the words of its phrase, as the narration counts them (``data-words-said``): it begins
        in the caption that says the phrase, as the voice reaches it (read again 0.2 s after its first reading, the
        voice has said every word before the phrase: a frame fades in from 0.15 s before the phrase's first word), the
        counter's outline only once the voice has begun the phrase; and it lasts until the voice has said the phrase in
        full.

        The film is read every 0.5 s from its start to the bench's first drive and through the last step, and every
        0.8 s from part 3 on (merge_stages). The frames in the scene are checked by their names only, not by whether or
        where they are drawn (as on the storage hierarchy page).

        Fails if something lights up in another step than the phrase that names it, for longer or more often, never,
        or out of order; if anything else lights up; if something lights up before the voice reaches its phrase or
        goes dark before the voice has said it, e.g. a frame whose times come from another caption or word; if the
        counter is lit at the end before the voice says "108"; or if its outline shows while it is not lit, or not
        while it is.
        """
        # from the start to the bench's first drive:
        opened, _ = self.open_at("?paused")
        early: list[dict[str, str]] = self.stages_from(opened, 0.5, "benchMove")
        merges: list[dict[str, str]] = self.merge_stages()

        # the last step, every 0.5 s from where the merges' readings end to the end of the film (in one call into the
        # page, on the page opened above), with the counter's outline as drawn and the words of the caption said:
        last_step: list[dict[str, str]] = opened.page.get_by_test_id("scrub").evaluate(
            """(scrub, [stage, counter, narration, start]) => {
                const duration = Number(stage.dataset.duration), readings = [];
                scrub.step = 'any';
                for (let t = start + 0.5; t <= duration; t += 0.5) {
                    scrub.value = String((t / duration) * Number(scrub.max));
                    scrub.dispatchEvent(new Event('input', { bubbles: true }));
                    // (without data-made, which the page writes once at start-up and which is long)
                    const { made, ...shown } = stage.dataset;
                    readings.push({ ...shown, outline: getComputedStyle(counter).outlineStyle,
                        said: narration.dataset.wordsSaid, words: narration.textContent.trim() });
                }
                return readings;
            }""",
            [
                opened.page.get_by_test_id("stage").element_handle(),
                opened.page.get_by_test_id("counter").element_handle(),
                opened.page.get_by_test_id("narration").element_handle(),
                float(merges[-1]["t"]),
            ],
        )
        self.assert_no_errors(opened)

        def lit(reading: dict[str, str]) -> set[str]:
            """Returns what is lit at a reading."""
            return set(filter(None, reading["highlight"].split("|")))

        def lit_stretches(name: str) -> list[list[dict[str, str]]]:
            """Returns each stretch of readings in a row (within one sweep) at which name is lit."""
            stretches: list[list[dict[str, str]]] = []
            for sweep in (early, merges, last_step):
                for is_lit, stretch in groupby(sweep, key=lambda r: name in lit(r)):
                    if is_lit:
                        stretches.append(list(stretch))
            return stretches

        readings: list[dict[str, str]] = early + merges + last_step

        # each thing lights up only in the steps whose words name it, and nothing else lights up:
        expected: dict[str, set[str]] = {
            "workbench": {"4"},
            "counter": {"7", "10", "13"},
            "heap": {"9"},
            "root": {"9"},
            "depot": {"9"},
        }
        for name, steps in expected.items():
            self.assertEqual(
                steps,
                {reading["scene"] for reading in readings if name in lit(reading)},
                f"the steps in which the {name} is lit",
            )
        self.assertEqual(
            set(expected),
            set().union(*(lit(reading) for reading in readings)),
            "what lights up",
        )

        # once per phrase that names it (the counter three times), each time for one short stretch of readings in a row:
        for name, steps in expected.items():
            stretches: list[list[dict[str, str]]] = lit_stretches(name)
            self.assertEqual(
                len(steps), len(stretches), f"how often the {name} lights up"
            )
            for stretch in stretches:
                self.assertLessEqual(
                    float(stretch[-1]["t"]) - float(stretch[0]["t"]),
                    self.LIT_AT_MOST,
                    f"the {name} lit from {stretch[0]['t']} s",
                )

        # in step 9 one after the other: the heap, its root, the depot; the heap and its root while it is filled:
        firsts: list[int] = [
            next(i for i, reading in enumerate(readings) if name in lit(reading))
            for name in ("heap", "root", "depot")
        ]
        self.assertLess(firsts[0], firsts[1], "the root lights up before the heap")
        self.assertLess(firsts[1], firsts[2], "the depot lights up before the root")
        for reading in readings:
            if lit(reading) & {"heap", "root"}:
                self.assertEqual("hInit", reading["phase"], f"at {reading['t']} s")

        # in the last step, the counter is lit from the word "108" on, and outlined exactly while it is lit:
        self.assertTrue(any("counter" in lit(reading) for reading in last_step))
        for reading in last_step:
            at: str = f"at {reading['t']} s"
            counter_lit: bool = "counter" in lit(reading)
            self.assertEqual(counter_lit, reading["outline"] == "solid", at)
            if counter_lit:
                words_before: int = reading["words"].split(" ").index("108")
                self.assertGreaterEqual(int(reading["said"]), words_before, at)

        # the phrases that name each thing (their first and last word, as shown), in the order the voice says them:
        phrases: dict[str, list[tuple[str, str]]] = {
            "workbench": [("workbench", "pages.")],
            "counter": [("Every", "once."), ("counter", "writes:"), ("108", "writes.")],
            "heap": [("heap", "three.")],
            "root": [("root,", "top,")],
            "depot": [("depot,", "depot,")],
        }
        stretches_of: dict[str, list[list[dict[str, str]]]] = {
            name: lit_stretches(name) for name in phrases
        }

        # the narration 0.2 s after the first reading of each stretch, read again on the page opened above:
        soon: float = 0.2
        soon_after: list[dict[str, str]] = opened.page.get_by_test_id("scrub").evaluate(
            """(scrub, [stage, narration, times]) => {
                scrub.step = 'any';
                return times.map((t) => {
                    scrub.value = String((t / Number(stage.dataset.duration)) * Number(scrub.max));
                    scrub.dispatchEvent(new Event('input', { bubbles: true }));
                    return { t: stage.dataset.t, words: narration.textContent.trim(), said: narration.dataset.wordsSaid };
                });
            }""",
            [
                opened.page.get_by_test_id("stage").element_handle(),
                opened.page.get_by_test_id("narration").element_handle(),
                [
                    float(stretch[0]["t"]) + soon
                    for name in phrases
                    for stretch in stretches_of[name]
                ],
            ],
        )
        self.assert_no_errors(opened)

        # each stretch is tied to the words of its phrase:
        later: Iterator[dict[str, str]] = iter(soon_after)
        for name, named_by in phrases.items():
            for (first, last), stretch in zip(
                named_by, stretches_of[name], strict=True
            ):
                start: dict[str, str] = stretch[0]
                at = f"the {name} lit from {start['t']} s"

                # it lights up in the caption that says its phrase:
                words: list[str] = start["words"].split(" ")
                self.assertIn(first, words, at)
                i: int = words.index(first)
                self.assertIn(last, words[i:], at)
                j: int = words.index(last, i)

                # as the voice reaches the phrase: 0.2 s later, it has said every word before it:
                reading_soon: dict[str, str] = next(later)
                self.assertEqual(start["words"], reading_soon["words"], at)
                self.assertGreaterEqual(int(reading_soon["said"]), i, at)

                # the counter's outline shows only once the voice has begun the phrase:
                in_caption: list[dict[str, str]] = [
                    reading for reading in stretch if reading["words"] == start["words"]
                ]
                if name == "counter":
                    for reading in in_caption:
                        self.assertGreaterEqual(int(reading["said"]), i, at)

                # it stays lit until the voice has said the phrase in full:
                self.assertGreater(
                    max(int(reading["said"]) for reading in in_caption), j, at
                )

    def test_a_part_shows_its_name_top_left_as_it_begins(self) -> None:
        """As each part begins, its number and name show top left (``part-title``) for about 9 s, fading in and out:
        "Part 1 · The table" at the start of the film, then "Part 2 · Pass 0", "Part 3 · Merge level 1" and "Part 4 ·
        Final merge", each the name on its part button; before a part begins and from 9 s after, the title is hidden.

        Each part's start comes from the slider, whose segments are as long as the parts (``flex-grow``). The film is
        read 0.3 s before each start, at 0.3, 2, 5, 8 and 8.6 s after it, where the title shows the part (it fades in
        and out in 0.4 s), and at 9.3 and 11 s after it, where it is hidden. A few readings only: each reading draws a
        frame, and a long sweep would keep the browser busy into the next test.

        Fails if a part shows another part's name or a name other than its button's, if the title does not show as a
        part begins or still shows 9.3 s after, or if ``data-shown`` and its opacity disagree.
        """
        names: dict[int, str] = {
            1: "The table",
            2: "Pass 0",
            3: "Merge level 1",
            4: "Final merge",
        }
        opened = self.open_controls()
        page: Page = opened.page
        for part, name in names.items():
            expect(page.get_by_test_id(f"chapter-{part}")).to_have_text(
                f"{part} · {name}"
            )
        readings: list[dict[str, str | float | int]] = page.get_by_test_id(
            "scrub"
        ).evaluate(
            """(scrub, [stage, title, number, name, segments]) => {
                const duration = Number(stage.dataset.duration);
                const lengths = [...segments.children].map((segment) => parseFloat(segment.style.flexGrow));
                const readings = [];
                scrub.step = 'any';
                lengths.forEach((_, i) => {
                    const start = lengths.slice(0, i).reduce((sum, length) => sum + length, 0);
                    for (const after of [-0.3, 0.3, 2, 5, 8, 8.6, 9.3, 11]) {
                        if (start + after < 0) continue;
                        scrub.value = String(((start + after) / duration) * Number(scrub.max));
                        scrub.dispatchEvent(new Event('input', { bubbles: true }));
                        readings.push({ part: i + 1, after, t: Number(stage.dataset.t), shownPart: title.dataset.part,
                            shown: title.dataset.shown, opacity: Number(getComputedStyle(title).opacity),
                            text: `${number.textContent} · ${name.textContent}` });
                    }
                });
                return readings;
            }""",
            [
                page.get_by_test_id("stage").element_handle(),
                page.get_by_test_id("part-title").element_handle(),
                page.get_by_test_id("part-number").element_handle(),
                page.get_by_test_id("part-name").element_handle(),
                page.get_by_test_id("segments").element_handle(),
            ],
        )
        self.assert_no_errors(opened)

        # four parts, each read 8 times (the first one not before its start):
        self.assertEqual(
            [1] * 7 + [2] * 8 + [3] * 8 + [4] * 8, [r["part"] for r in readings]
        )
        for reading in readings:
            part, after = int(reading["part"]), float(reading["after"])
            at: str = f"part {part}, {after} s after its start, at {reading['t']} s"
            # before the start, the title names the part before, and is hidden:
            shown_part: int = part - 1 if after < 0 else part
            self.assertEqual(str(shown_part), reading["shownPart"], at)
            self.assertEqual(
                f"Part {shown_part} · {names[shown_part]}", reading["text"], at
            )
            self.assertEqual(0 < after < 9, reading["shown"] == "true", at)
            self.assertEqual(
                reading["shown"] == "true", float(reading["opacity"]) > 0.5, at
            )

    def test_the_end_card_names_the_voice(self) -> None:
        """The last line of the end card, the credit, ends by saying that the voice is synthetic and naming its model
        and voice."""
        voice_named: str = "The voice is synthetic: Ming-3.0 TTS, voice UK_George."
        opened: OpenedPage = self.open_controls()
        page: Page = opened.page

        # at the end, the end card shows, and its credit ends with the voice's (read as shown, so that the line breaks
        # of the HTML count as spaces):
        page.get_by_test_id("scrub").fill("1000")
        expect(page.get_by_test_id("legend")).to_have_css("opacity", "1")
        expect(page.get_by_test_id("credit")).to_have_text(
            re.compile(re.escape(voice_named) + "$"), use_inner_text=True
        )
        self.assert_no_errors(opened)

    def test_the_sound_hint_gives_way_to_the_end_card(self) -> None:
        """With sound off, the hint "Switch on audio (M)" fades out while the end card fades in, which it would cover on
        a narrow window, and shows again before it."""
        opened: OpenedPage = self.open_controls()
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

    def test_the_page_stops_if_a_clip_of_its_voice_does_not_belong_to_its_caption(
        self,
    ) -> None:
        """At start-up, the page checks that each clip of its voice belongs to its caption: a copy whose first clip was
        made for another text stops with an error that says so, whereas the page itself passes the check.

        The clips are matched to the captions by their order, as on the Yannakakis page, so a voice built for other
        captions would otherwise speak the wrong words; with the error, the page fails its tests instead.
        """
        # the page itself passes the check: it sets up its controls, which comes after the check, without an error
        # (open_controls waits for them):
        opened: OpenedPage = self.open_controls()
        page: Page = opened.page

        # a copy whose voice notes another text for its first clip than the first caption's, loaded into the same tab
        # (the class opens only its own page) after an empty page, so that it starts with globals of its own (the
        # page's clips are a global constant), with the errors recorded so far cleared:
        html: str = EXTERNAL_SORTING_PAGE.read_text(encoding="utf-8")
        first_clip: str = 'const VOICE = [{"text": "'
        self.assertEqual(1, html.count(first_clip), "the page's voice was not found")
        page.goto("about:blank")
        opened.errors.clear()
        page.set_content(html.replace(first_clip, first_clip + "Once more: "))

        # the copy throws the error once it has loaded its fonts and built its scene; the error is recorded as soon as
        # Playwright has handled it. The copy requests nothing but local files:
        error: str = (
            "uncaught: the voice does not match caption 1: rebuild it with voice.py"
        )
        for _ in range(FILM_TIMEOUT // 100):
            if error in opened.errors:
                break
            page.wait_for_timeout(100)
        self.assertEqual([error], opened.errors)
        self.assertEqual([], opened.outside_requests)

        # the copy stops there: it never sets up its controls, so Play stays disabled, as the HTML writes it:
        expect(page.get_by_test_id("play")).to_be_disabled()


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

    # made-up pages, which need not exist, in no particular order; three of the five have a sound button; their sizes
    # in bytes, made up as well, so that neither group's order by size is that by path:
    PAGES: list[Path] = [Path(f"v/{name}.html") for name in "eabdc"]
    WITH_SOUND: frozenset[Path] = frozenset(Path(f"v/{name}.html") for name in "bde")
    SIZES: dict[Path, int] = {
        Path(f"v/{name}.html"): size
        for name, size in {"b": 200, "d": 300, "e": 100, "a": 10, "c": 20}.items()
    }

    def shares(self, total: int) -> list[list[Path]]:
        """Returns the made-up pages of each of total jobs, from job 1 on."""
        return [
            pages_of_job(
                self.PAGES,
                index,
                total,
                sound=lambda path: path in self.WITH_SOUND,
                size=self.SIZES.__getitem__,
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
        """A single job tests all pages: those with sound first, then the others, each sorted by size, largest first
        (d 300, b 200, e 100 with sound; c 20, a 10).

        Would fail if a group were sorted by path (b, d, e and a, c) or by size the other way round.
        """
        b, d, e, a, c = (Path(f"v/{name}.html") for name in "bdeac")
        self.assertEqual([[d, b, e, c, a]], self.shares(1))

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

        In the order d, b, e (with sound, largest first), c, a, page k goes to job k mod 3 + 1; sorted by path alone,
        job 2 would get b and e, and job 3 no page with sound.
        """
        b, d, e, a, c = (Path(f"v/{name}.html") for name in "bdeac")
        shares: list[list[Path]] = self.shares(3)
        self.assertEqual([[d, c], [b, a], [e]], shares)
        self.assertEqual(
            [1, 1, 1], [len(self.WITH_SOUND.intersection(share)) for share in shares]
        )

    def test_the_largest_pages_with_sound_go_to_different_jobs(self) -> None:
        """Among the pages of visualizations/, the CI_JOBS largest pages with sound, whose tests take longest, are
        tested in CI_JOBS different jobs.

        Would fail if the pages with sound were spread by path again: then b-tree, external-sorting and yannakakis
        went to the same job of three, which ran over the CI job's time limit of 10 minutes (merge request !289).
        """
        with_sound: list[Path] = [page for page in find_pages() if has_sound(page)]
        largest: list[Path] = sorted(with_sound, key=file_size, reverse=True)[:CI_JOBS]
        self.assertEqual(CI_JOBS, len({self.job_of(page, CI_JOBS) for page in largest}))

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
