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
tests are skipped. The CI job ``visualization_test`` installs the group and Chromium and runs this module.
"""

from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

# the tests run only where Playwright is installed (see the module docstring):
PLAYWRIGHT_AVAILABLE: bool = importlib.util.find_spec("playwright") is not None

# without the dependency group browser-tests, pylint cannot find playwright:
# pylint: disable=import-error
if PLAYWRIGHT_AVAILABLE:
    from playwright.sync_api import expect, sync_playwright
else:
    # the tests are skipped, so these are never called:
    expect = sync_playwright = None  # pylint: disable=invalid-name
if TYPE_CHECKING:
    from playwright.sync_api import (
        Browser,
        ConsoleMessage,
        Error,
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

# Next is clicked at most this often on the way from the start of a page to its end:
MAX_NEXT_CLICKS: int = 300

# a wait for the film to reach a time (e.g. the first caption, after about 0.75 s) ends after this many milliseconds,
# not after the 5 s of a control: on a slow machine (software rendering) a frame may advance the film by only 0.1 s:
FILM_TIMEOUT: int = 15_000


@dataclass
class OpenedPage:
    """A page opened in a browser context of its own, with everything that went wrong in it so far."""

    page: Page
    # uncaught exceptions and messages the page logged as console errors:
    errors: list[str] = field(default_factory=list)
    # the URLs of requests and WebSockets to anything but a local file, which were blocked:
    outside_requests: list[str] = field(default_factory=list)


class _PageTestCase(unittest.TestCase):
    """Starts one headless Chromium per test class and opens pages in it; holds no tests of its own."""

    playwright: Playwright
    browser: Browser

    @classmethod
    def setUpClass(cls) -> None:
        """Starts Playwright and Chromium; both are stopped after the last test of the class, also if one fails."""
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def open_page(self, path: Path, reduced_motion: bool = True) -> OpenedPage:
        """Opens the page at path in a new browser context, which is closed after the test.

        Errors and outside requests are recorded from before the page loads.

        @param path: the HTML file of the page
        @param reduced_motion: whether the browser asks for reduced motion; the pages then do not start playing on
            their own, so that every test starts from a paused page at time 0
        @return: the opened page with the lists of errors and outside requests
        """
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

    def pages(self) -> list[Path]:
        """Returns the HTML files in visualizations/ and its subfolders, and asserts that the two known ones are there."""
        pages: list[Path] = sorted(PAGES_DIR.rglob("*.html"))
        self.assertLessEqual({ELASTICITY_PAGE, VALIDATION_PAGE}, set(pages))
        return pages


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
        """Runs a check on each page with a sound button, and asserts that the clock-scan page is one of them.

        The pages with a sound button are found in their HTML, so that the others are not opened in the browser. Each
        page is opened at its start, paused and with sound off; after the check, the page must have had no errors.

        @param check: the steps of a test on one page
        """
        # a page without a sound button has no voice; the button is written in the page's HTML, not made by its script:
        pages_with_sound: list[Path] = [
            path
            for path in self.pages()
            if 'data-testid="sound"' in path.read_text(encoding="utf-8")
        ]
        # the clock-scan page has a sound button, so that a test cannot pass without a page that speaks:
        self.assertIn(CLOCK_SCAN_PAGE, pages_with_sound)

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
    def let_film_play_on(page: Page, steps: int) -> None:
        """Waits until the playing film has moved the slider on by at least the given number of steps.

        The slider has 1000 steps from the start of the film to its end; on the clock-scan page, which lasts about
        100 s, ten steps are about 1 s.

        @param page: a playing page
        @param steps: how far the slider has to move on
        """
        scrub = page.get_by_test_id("scrub")
        page.wait_for_function(
            "([scrub, until]) => Number(scrub.value) >= until",
            arg=[scrub.element_handle(), int(scrub.input_value()) + steps],
            timeout=FILM_TIMEOUT,
        )

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

        Next drops the voice's clip; Play and the button of part 1 make the voice speak again; the sound button switches
        the voice off again.
        """

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            sound = page.get_by_test_id("sound")
            play = page.get_by_test_id("play")
            scrub = page.get_by_test_id("scrub")
            stage = page.get_by_test_id("stage")
            voice = page.get_by_test_id("voice")

            # sound is off at load, and the captions show as subtitles:
            self.expect_sound(page, on=False)

            # a click switches the sound on, and the voice speaks the captions instead:
            sound.click()
            self.expect_sound(page, on=True)

            # Play from the start: the voice speaks the clip of the first caption, which begins after about 0.75 s:
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

            # the button of part 1 jumps back to the start, before the first caption, and plays from there; the voice
            # speaks again once the first caption begins:
            page.get_by_test_id("chapter-1").click()
            self.assertEqual(
                "start",
                page.get_by_test_id("narration").get_attribute("data-stop-type"),
            )
            expect(play).to_have_attribute("data-state", "playing")
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )

            # the sound button switches the voice off, the film plays on, and the captions show as subtitles again:
            sound.click()
            self.expect_sound(page, on=False)
            expect(play).to_have_attribute("data-state", "playing")

            # the voice stays silent while the film plays on for about 1 s, and does not start even for a moment:
            self.record_voice_starts(page)
            self.let_film_play_on(page, 10)
            self.assertTrue(voice.evaluate("audio => audio.paused"))
            self.assertEqual([], page.evaluate("window.voiceStarts"))
            expect(stage).not_to_have_attribute("data-voice", "playing")

        self.check_each_page_with_sound(check)

    def test_voice_stays_silent_with_sound_off(self) -> None:
        """With sound off, the voice stays silent while the film plays on into the next caption; no clip is loaded."""

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            voice = page.get_by_test_id("voice")
            text = page.get_by_test_id("nar-text")

            # Next stops where the first caption is shown in full:
            page.get_by_test_id("next").click()
            first_caption: str = text.inner_text()
            self.assertNotEqual("", first_caption)

            # Play: the film plays on past the first caption into the second one, where the voice would speak with sound
            # on, and on for about half a second more:
            self.record_voice_starts(page)
            play.click()
            expect(text).not_to_have_text(first_caption, timeout=FILM_TIMEOUT)
            self.let_film_play_on(page, 5)

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

        Between the two captions, the voice is silent. After a jump back with the button of part 1, the first clip is
        said again.
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

            # the button of part 1 jumps back to the start and plays: the voice says the first clip again:
            page.get_by_test_id("chapter-1").click()
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

    def test_pause_holds_the_clip_and_play_goes_on_in_it(self) -> None:
        """With sound on, Pause holds the voice's clip where it is, and Play goes on in it, not from its start."""

        def check(page: Page) -> None:
            """Checks one page, opened at its start with sound off."""
            play = page.get_by_test_id("play")
            stage = page.get_by_test_id("stage")
            voice = page.get_by_test_id("voice")

            # sound on and Play: the voice speaks the first caption, until 2 s of its clip have been played (half of a
            # clip shorter than 4 s, so that the clip is still playing after Pause and Play):
            self.play_with_sound(page)
            page.wait_for_function(
                "audio => audio.currentTime >= Math.min(2, audio.duration / 2)",
                arg=voice.element_handle(),
                timeout=FILM_TIMEOUT,
            )

            # Pause silences the voice but holds its clip, well past the clip's start; where it holds it, and which
            # clip, is noted:
            play.click()
            expect(play).to_have_attribute("data-state", "paused")
            expect(stage).not_to_have_attribute("data-voice", "playing")
            self.assertTrue(voice.evaluate("audio => audio.paused"))
            expect(voice).to_have_attribute("src", re.compile(r"^data:audio/"))
            held: float = voice.evaluate(
                "audio => { window.heldClip = audio.currentSrc; return audio.currentTime; }"
            )
            self.assertGreater(held, 0.5)

            # Play goes on in the same clip where it was held, not from its start (which is 0.4 s of silence); the page
            # may move the voice a little, to the film's time:
            play.click()
            expect(stage).to_have_attribute(
                "data-voice", "playing", timeout=FILM_TIMEOUT
            )
            self.assertTrue(
                voice.evaluate("audio => audio.currentSrc === window.heldClip")
            )
            self.assertGreater(voice.evaluate("audio => audio.currentTime"), held - 0.3)

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
class ElasticityPageTest(_PageTestCase):
    """Checks the controls of the elasticity page: the stops, the models, the sizes and the results of the day."""

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
