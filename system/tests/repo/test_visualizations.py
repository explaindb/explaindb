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

# Next is clicked at most this often on the way from the start of a page to its end:
MAX_NEXT_CLICKS: int = 300


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


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, SKIP_REASON)
class EveryPageTest(_PageTestCase):
    """Checks what every page in visualizations/ has, so that a new page is covered without tests of its own."""

    def pages(self) -> list[Path]:
        """Returns the HTML files in visualizations/ and its subfolders, and asserts that the two known ones are there."""
        pages: list[Path] = sorted(PAGES_DIR.rglob("*.html"))
        self.assertLessEqual({ELASTICITY_PAGE, VALIDATION_PAGE}, set(pages))
        return pages

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
