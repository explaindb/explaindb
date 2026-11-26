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

"""Tests of the type check of ``system/`` with pyright: its settings and pin in ``pyproject.toml``, and its command."""

import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import Any

# the module, not its test classes, is imported, so that unittest does not run those tests here again:
from system.tests.repo import test_ci_config

# the repository root and the files read here, found relative to this file so that the test does not depend on the
# working directory:
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
PYPROJECT: Path = REPO_ROOT / "pyproject.toml"
CONTRIBUTING: Path = REPO_ROOT / "CONTRIBUTING.md"

# the CI job of the type check, the folder that it must check, and the dependency group that holds pyright:
TYPE_CHECK_JOB: str = "type_check"
CHECKED_FOLDER: str = "system"
TYPE_CHECK_GROUP: str = "type-check"

# the only settings that [tool.pyright] may hold; any other one could take files out of the check (exclude), hide
# their errors (ignore, a rule set to "none" or "warning") or bring in settings that this test does not read
# (extends):
ALLOWED_SETTINGS: frozenset[str] = frozenset(
    {"include", "typeCheckingMode", "pythonPlatform"}
)

# the modes that may be set: standard, in which system/ was brought to 0 errors, and strict, which checks more:
ALLOWED_MODES: frozenset[str] = frozenset({"standard", "strict"})

# pyright with the extra nodejs, which brings Node.js as a package locked in uv.lock (without it, pyright downloads
# an unpinned Node.js from nodejs.org on every CI run), pinned to one version:
PINNED_PYRIGHT: re.Pattern[str] = re.compile(r"pyright\[nodejs\]==[0-9][0-9.]*")

# a shell command runs pyright if it names pyright with no letter, digit or underscore right before or after it:
RUNS_PYRIGHT: re.Pattern[str] = re.compile(r"\bpyright\b")

# the characters that separate the words of a shell command (not, e.g., a non-breaking space):
WORD_GAP: re.Pattern[str] = re.compile(r"[ \t]+")

# the section "Type check" of CONTRIBUTING.md: the lines below its heading up to the next level-2 heading:
TYPE_CHECK_SECTION: re.Pattern[str] = re.compile(
    r"^## Type check[ \t]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL
)


def pyright_settings_problems(pyproject: dict[str, Any], root: Path) -> list[str]:
    """Returns why the pyright settings of a repository could let pyright pass without checking CHECKED_FOLDER.

    pyright passes, as if there were no errors, when a path in ``include`` does not exist or is a hidden folder
    (which pyright always skips), when other settings take files out of the check or hide their errors, or in the
    mode ``off``; the mode must be set, so that a new pyright version cannot change it. A pyrightconfig.json next to
    pyproject.toml would replace the section ``[tool.pyright]`` in editors and in runs without ``--project``.

    @param pyproject: pyproject.toml as parsed by ``tomllib``
    @param root: the folder of pyproject.toml, against which the paths in ``include`` are resolved
    @return: one message per problem; empty if there is none
    """
    problems: list[str] = []
    if (root / "pyrightconfig.json").exists():
        problems.append("pyrightconfig.json replaces [tool.pyright]; remove it")
    settings: Any = pyproject.get("tool", {}).get("pyright")
    if not isinstance(settings, dict):
        return problems + ["pyproject.toml has no section [tool.pyright]"]

    # no other settings, so that nothing takes files out of the check or hides their errors:
    for key in sorted(set(settings) - ALLOWED_SETTINGS):
        problems.append(
            f"the setting {key} could take files out of the type check or hide errors; remove it"
        )

    # include names CHECKED_FOLDER, and each of its paths is a folder with Python files that pyright does not skip:
    include: Any = settings.get("include")
    paths: list[Any] = include if isinstance(include, list) else []
    if CHECKED_FOLDER not in paths:
        problems.append(f'include must name "{CHECKED_FOLDER}"')
    for path in paths:
        folder: Path = root / str(path)
        if any(part.startswith(".") for part in Path(str(path)).parts):
            problems.append(
                f'include names "{path}", which pyright skips as a hidden folder'
            )
        elif not folder.is_dir() or not any(folder.rglob("*.py")):
            problems.append(
                f'include names "{path}", which is no folder with Python files'
            )

    # the mode is one of ALLOWED_MODES (a value that is no string, e.g. a list, cannot be looked up there):
    mode: Any = settings.get("typeCheckingMode")
    if mode is None:
        problems.append("typeCheckingMode is not set; set it to standard or strict")
    elif not isinstance(mode, str) or mode not in ALLOWED_MODES:
        problems.append(f"typeCheckingMode is {mode!r}; set it to standard or strict")
    return problems


def type_check_group_problems(pyproject: dict[str, Any]) -> list[str]:
    """Returns why the dependency group TYPE_CHECK_GROUP does not pin pyright with Node.js, see PINNED_PYRIGHT.

    @param pyproject: pyproject.toml as parsed by ``tomllib``
    @return: one message per problem; empty if there is none
    """
    group: Any = pyproject.get("dependency-groups", {}).get(TYPE_CHECK_GROUP)
    # one entry, as a whole, pins pyright; entries that are no string, such as {include-group = ...}, are skipped:
    if isinstance(group, list) and any(
        isinstance(entry, str) and PINNED_PYRIGHT.fullmatch(entry) for entry in group
    ):
        return []
    return [
        f"the group {TYPE_CHECK_GROUP} must pin pyright with the extra nodejs: pyright[nodejs]==<version>"
    ]


def shell_commands(text: str) -> list[str]:
    """Returns the commands of a shell text, one per line, with one space between their words.

    As in the shell, a backslash at the end of a line continues the command on the next line: the backslash and the
    line break are removed. The indentation and the number of spaces and tabs between words do not count.

    @param text: the text, e.g. a job's script or the section TYPE_CHECK_SECTION of CONTRIBUTING.md
    @return: the commands, one per line that does not continue another
    """
    return [
        " ".join(WORD_GAP.split(line.strip(" \t")))
        for line in text.replace("\\\n", "").splitlines()
    ]


def pyright_command_problems(
    job: dict[str, Any] | None, contributing: str
) -> list[str]:
    """Returns why the job TYPE_CHECK_JOB does not run exactly the command of the type check in CONTRIBUTING.md.

    The job must run pyright in exactly one command of its script, and the section TYPE_CHECK_SECTION of
    CONTRIBUTING.md must show that command as one of its own. Commands are compared whole, as
    :func:`shell_commands` gives them, so that developers run the very command of the job.

    @param job: the job as parsed from .gitlab-ci.yml, or None if the configuration has no such job
    @param contributing: the text of CONTRIBUTING.md
    @return: one message per problem; empty if there is none
    """
    if job is None:
        return [f"the job {TYPE_CHECK_JOB} is missing"]
    # the job runs pyright in exactly one command of its script:
    script: str = "\n".join(test_ci_config.script_lines(job.get("script", [])))
    commands: list[str] = [
        command for command in shell_commands(script) if RUNS_PYRIGHT.search(command)
    ]
    if len(commands) != 1:
        return [f"the job runs pyright in {len(commands)} commands instead of one"]

    # the section shows that command as one of its own, e.g. in a code block:
    section: re.Match[str] | None = TYPE_CHECK_SECTION.search(contributing)
    if section is None:
        return ['CONTRIBUTING.md has no section "## Type check"']
    if commands[0] not in shell_commands(section.group(1)):
        return [
            'the section "## Type check" of CONTRIBUTING.md does not show the job\'s command as a command of its own: '
            + commands[0]
        ]
    return []


def read_pyproject() -> dict[str, Any]:
    """Returns pyproject.toml of the repository, parsed by ``tomllib``."""
    with PYPROJECT.open("rb") as file:
        return tomllib.load(file)


class PyrightSettingsTest(unittest.TestCase):
    """Checks that [tool.pyright] makes pyright check every Python file in CHECKED_FOLDER and report its errors.

    pyright passes, as if there were no errors, if its settings leave nothing to check or hide the errors; the job
    type_check would then pass without checking system/ (see :func:`pyright_settings_problems`).
    """

    # good settings, which the cases below change:
    GOOD: dict[str, Any] = {"include": ["system"], "typeCheckingMode": "standard"}

    @staticmethod
    def problems(settings: dict[str, Any] | None, *files: str) -> list[str]:
        """Returns the problems of the settings (None: no section) in a temporary repository with these files."""
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            for name in ("system/module.py", *files):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).touch()
            tool: dict[str, Any] = {} if settings is None else {"pyright": settings}
            return pyright_settings_problems({"tool": tool}, root)

    def test_repository_settings_have_no_problem(self) -> None:
        """The section [tool.pyright] of the repository's pyproject.toml makes pyright check CHECKED_FOLDER."""
        self.assertEqual([], pyright_settings_problems(read_pyproject(), REPO_ROOT))

    def test_section_is_the_only_configuration(self) -> None:
        """A missing section [tool.pyright] is reported, and so is a pyrightconfig.json, which would replace it."""
        no_section: list[str] = ["pyproject.toml has no section [tool.pyright]"]
        self.assertEqual(no_section, self.problems(None))
        self.assertEqual(
            ["pyrightconfig.json replaces [tool.pyright]; remove it"],
            self.problems(self.GOOD, "pyrightconfig.json"),
        )

    def test_include_names_system_and_only_folders_with_python_files(self) -> None:
        """include names system, and each of its paths is a folder with Python files that pyright does not skip."""
        no_system: list[str] = ['include must name "system"']
        no_py: str = 'include names "{}", which is no folder with Python files'
        hidden: str = 'include names "{}", which pyright skips as a hidden folder'
        # name: (include, further files besides system/module.py, the expected messages):
        cases: dict[str, tuple[Any, tuple[str, ...], list[str]]] = {
            "system": (["system"], (), []),
            "no system": (["tools"], ("tools/a.py",), no_system),
            "a string": ("system", (), no_system),
            "missing folder": (["system", "src"], (), [no_py.format("src")]),
            "only .txt": (["system", "docs"], ("docs/a.txt",), [no_py.format("docs")]),
            "hidden folder": (["system", ".ci"], (".ci/a.py",), [hidden.format(".ci")]),
        }
        for name, (include, files, expected) in cases.items():
            with self.subTest(name):
                settings: dict[str, Any] = self.GOOD | {"include": include}
                self.assertEqual(expected, self.problems(settings, *files))

    def test_only_allowed_settings_are_accepted(self) -> None:
        """Every setting outside ALLOWED_SETTINGS, e.g. exclude or a rule turned into a warning, is reported."""
        bad: dict[str, Any] = {"exclude": ["system"], "reportArgumentType": "warning"}
        for key, value in bad.items():
            with self.subTest(key):
                message: str = (
                    f"the setting {key} could take files out of the type check or hide errors; remove it"
                )
                self.assertEqual([message], self.problems(self.GOOD | {key: value}))

    def test_mode_is_standard_or_strict(self) -> None:
        """typeCheckingMode is standard or strict; a missing, weak or unknown mode, even a list, is reported."""
        message: str = "typeCheckingMode is {}; set it to standard or strict"
        # the mode, None for none, and the expected messages:
        cases: list[tuple[Any, list[str]]] = [
            ("strict", []),
            (None, ["typeCheckingMode is not set; set it to standard or strict"]),
            ("off", [message.format("'off'")]),
            ("basic", [message.format("'basic'")]),
            ("Standard", [message.format("'Standard'")]),
            (["off"], [message.format("['off']")]),
        ]
        for mode, expected in cases:
            with self.subTest(mode=mode):
                settings: dict[str, Any] = {"include": ["system"]}
                if mode is not None:
                    settings["typeCheckingMode"] = mode
                self.assertEqual(expected, self.problems(settings))


class TypeCheckGroupTest(unittest.TestCase):
    """Checks that the dependency group type-check pins pyright, with the extra nodejs, to one exact version.

    With the extra, Node.js comes as a package locked in uv.lock; without it, pyright downloads an unpinned Node.js
    from nodejs.org on every CI run, outside uv.lock and the dependency audit. The exact pin keeps the errors that
    pyright reports the same until someone raises it on purpose.
    """

    def test_repository_pins_pyright(self) -> None:
        """The group type-check of the repository's pyproject.toml pins pyright with the extra nodejs."""
        self.assertEqual([], type_check_group_problems(read_pyproject()))

    def test_group_pins_pyright_with_nodejs(self) -> None:
        """Only an entry pyright[nodejs]==<version>, as a whole and also among other entries, pins pyright."""
        message: list[str] = [
            "the group type-check must pin pyright with the extra nodejs: pyright[nodejs]==<version>"
        ]
        # name: (the group type-check, None for none, the expected messages):
        cases: dict[str, tuple[Any, list[str]]] = {
            "pinned": ([{"include-group": "x"}, "pyright[nodejs]==1.1.414"], []),
            "no group": (None, message),
            "a string": ("pyright[nodejs]==1.1.414", message),
            "no extra": (["pyright==1.1.414"], message),
            "lower bound": (["pyright[nodejs]>=1.1.414"], message),
            "wildcard": (["pyright[nodejs]==1.1.*"], message),
            "other package": (["basedpyright[nodejs]==1.1.414"], message),
        }
        for name, (group, expected) in cases.items():
            with self.subTest(name):
                groups: dict[str, Any] = {} if group is None else {"type-check": group}
                pyproject: dict[str, Any] = {"dependency-groups": groups}
                self.assertEqual(expected, type_check_group_problems(pyproject))


class PyrightCommandTest(unittest.TestCase):
    """Checks that the job type_check runs exactly the command shown in the section Type check of CONTRIBUTING.md.

    Developers run that command before they push; if it differed from the job's, a check could pass on their machine
    and fail in CI. Commands are compared as the shell runs them (see :func:`shell_commands`).
    """

    # a command of the type check, on one line and split with a backslash before an indented second line:
    COMMAND: str = (
        "uv run --locked --isolated --all-groups pyright --project pyproject.toml --stats"
    )
    SPLIT: str = COMMAND.replace(" pyright", " \\\n    pyright")

    @staticmethod
    def contributing(section: str, before: str = "", after: str = "") -> str:
        """Returns a CONTRIBUTING.md with the given texts in its sections Formatting, Type check and Tests."""
        return f"## Formatting\n\n{before}\n\n## Type check\n\n{section}\n\n## Tests\n\n{after}\n"

    def test_repository_job_runs_the_documented_command(self) -> None:
        """The job type_check runs pyright in one command, which CONTRIBUTING.md shows in its section Type check."""
        job: dict[str, Any] | None = test_ci_config.load_ci_config().get(TYPE_CHECK_JOB)
        contributing: str = CONTRIBUTING.read_text(encoding="utf-8")
        self.assertEqual([], pyright_command_problems(job, contributing))

    def test_job_runs_pyright_in_one_command(self) -> None:
        """The job runs pyright in exactly one command, which may be split with a backslash and indented."""
        contributing: str = self.contributing(self.COMMAND)
        count: str = "the job runs pyright in {} commands instead of one"
        # name: (the job's script, None for no job, the expected messages):
        cases: dict[str, tuple[str | None, list[str]]] = {
            "one command": (self.COMMAND, []),
            "split": (self.SPLIT, []),
            "no job": (None, ["the job type_check is missing"]),
            "no pyright": ("rm -f pyrightconfig.json", [count.format(0)]),
            "two": (f"pyright --version\n{self.COMMAND}", [count.format(2)]),
        }
        for name, (script, expected) in cases.items():
            with self.subTest(name):
                job: dict[str, Any] | None = {"script": [script]} if script else None
                self.assertEqual(expected, pyright_command_problems(job, contributing))

    def test_section_shows_the_whole_command(self) -> None:
        """The section Type check shows the job's whole command; layout that the shell ignores does not count."""
        command: str = self.COMMAND
        job: dict[str, Any] = {"script": [command]}
        doc = self.contributing
        # no section Type check, though a similar heading shows the command:
        self.assertEqual(
            ['CONTRIBUTING.md has no section "## Type check"'],
            pyright_command_problems(job, f"## Type checking\n\n{command}\n"),
        )

        # sections that show the command: split, indented with spaces and tabs between words, below a subheading:
        shown: dict[str, str] = {
            "one line": doc(command),
            "split": doc(self.SPLIT),
            "spaces and tabs": doc("   " + command.replace(" ", " \t ")),
            "subheading": doc(f"### Locally\n\n{command}"),
        }
        for name, contributing in shown.items():
            with self.subTest(name):
                self.assertEqual([], pyright_command_problems(job, contributing))

        # the command only in another section, or another command in the section Type check:
        not_shown: dict[str, str] = {
            "only before": doc("See below.", before=command),
            "only after": doc("See above.", after=command),
            "in a sentence": doc(f"Run `{command}` first."),
            "other options": doc(command.replace(" --isolated", "")),
            "line above": doc(f"PYRIGHT_PYTHON_FORCE_VERSION=1.1.999 \\\n{command}"),
            "line below": doc(f"{command} \\\n    --verbose"),
            "split in a word": doc(command.replace(" --project", "\\\n--project")),
            "no-break space": doc(command.replace("run ", "run\u00a0")),
        }
        expected: list[str] = [
            'the section "## Type check" of CONTRIBUTING.md does not show the job\'s command as a command of its own: '
            + command
        ]
        for name, contributing in not_shown.items():
            with self.subTest(name):
                self.assertEqual(expected, pyright_command_problems(job, contributing))
