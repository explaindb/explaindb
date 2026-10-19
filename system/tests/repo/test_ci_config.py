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

# This module exceeds pylint's 1000 lines, as it holds one test class per security property of the audit jobs.
# pylint: disable=too-many-lines
"""Tests which jobs of ``.gitlab-ci.yml`` run in scheduled pipelines, and security properties of its audit jobs."""

import copy
import functools
import re
import shlex
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# pyyaml is not a declared dependency of the project: it comes with jupyter (via jupyter-events).
import yaml

# the repository root and its CI configuration, found relative to this file so that the test does not depend on the
# working directory:
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
CI_CONFIG: Path = REPO_ROOT / ".gitlab-ci.yml"

# top-level keys of a GitLab CI configuration that are not jobs:
RESERVED_KEYS: frozenset[str] = frozenset(
    {
        "workflow",
        "stages",
        "variables",
        "default",
        "include",
        "image",
        "services",
        "cache",
        "before_script",
        "after_script",
    }
)

# the jobs that run in scheduled pipelines (the nightly run on main):
SCHEDULED_JOBS: frozenset[str] = frozenset(
    {
        "serializability_nightly",
        "dependency_audit",
        "rust_dependency_audit",
        "generated_rust_check",
    }
)

# the rule that keeps a job out of scheduled pipelines; it must come first, as GitLab applies the first matching rule:
NOT_IN_SCHEDULE: dict[str, str] = {
    "if": "$CI_PIPELINE_SOURCE == 'schedule'",
    "when": "never",
}

# the jobs that fail the pipeline if a locked dependency has a known vulnerability:
PYTHON_AUDIT_JOB: str = "dependency_audit"
RUST_AUDIT_JOB: str = "rust_dependency_audit"
AUDIT_JOBS: tuple[str, ...] = (PYTHON_AUDIT_JOB, RUST_AUDIT_JOB)

# an image pinned by digest: its name (usually with a tag) ends in the SHA-256 checksum of the exact image:
PINNED_IMAGE: re.Pattern[str] = re.compile(r".+@sha256:[0-9a-f]{64}")

# a safe CARGO_HOME: a fixed path below /tmp, so no variable ($) can point it into the checkout:
SAFE_CARGO_HOME: re.Pattern[str] = re.compile(r"/tmp/[A-Za-z0-9._/-]+")

# a shell line verifies a checksum if it ends with this text (sha256sum -c - compares files with the checksums it
# reads from standard input) and contains no "||", as "|| true" would ignore a failed check:
VERIFIES_CHECKSUM: str = "sha256sum -c -"

# a shell line runs tar if tar stands as a word of its own (also /bin/tar, busybox tar, then tar, xargs tar):
RUNS_TAR: re.Pattern[str] = re.compile(r"\btar\b")

# the files, relative to the repository root, from which a local `cargo audit` would read ignored advisories; the
# Rust audit job fails if one of them exists, and the repository has none:
AUDIT_TOML_PATHS: frozenset[str] = frozenset(
    {".cargo/audit.toml", "generated/rust/.cargo/audit.toml"}
)

# the lockfile of the Rust code, relative to the repository root, and the path under which the Rust audit job
# passes it to cargo-audit (the job runs cargo-audit in /tmp, so the path must be absolute):
RUST_LOCKFILE: str = "generated/rust/Cargo.lock"
AUDITED_LOCKFILE: str = "$CI_PROJECT_DIR/" + RUST_LOCKFILE

# the start of a shell loop over a list of words, such as "for f in a b; do ...":
FOR_LOOP: re.Pattern[str] = re.compile(r"for \w+ in ([^;]*); do\b")

# a shell line changes the directory if cd stands as a word of its own (also "then cd", "&& cd"):
CHANGES_DIRECTORY: re.Pattern[str] = re.compile(r"\bcd\b")

# the options the Rust audit job may pass to cargo-audit audit; any other option could change what is checked,
# such as --target-os, --url, --db, -n/--no-fetch or --stale. Options without a value:
AUDIT_FLAGS: frozenset[str] = frozenset({"--no-yanked"})
# options with a value, each with the values it may take: the lockfile of the Rust code, the ID of an ignored
# RustSec advisory, and a kind of warning that fails the job as well:
AUDIT_OPTIONS_WITH_VALUE: dict[str, re.Pattern[str]] = {
    "--file": re.compile(re.escape(AUDITED_LOCKFILE)),
    "--ignore": re.compile(r"RUSTSEC-\d{4}-\d{4}"),
    "-D": re.compile(r"warnings|unmaintained|unsound|yanked"),
    "--deny": re.compile(r"warnings|unmaintained|unsound|yanked"),
}


class _CILoader(yaml.SafeLoader):  # pylint: disable=too-many-ancestors
    """A safe YAML loader that also reads GitLab's ``!reference`` tag (as the plain list it contains)."""


_CILoader.add_constructor(
    "!reference", lambda loader, node: loader.construct_sequence(node)
)


@functools.cache
def _read_ci_config() -> dict[str, Any]:
    """Returns the parsed ``.gitlab-ci.yml``, read only on the first call; see :func:`load_ci_config`."""
    with CI_CONFIG.open(encoding="utf-8") as file:
        # _CILoader is a SafeLoader:
        return yaml.load(file, Loader=_CILoader)  # nosec B506


def load_ci_config() -> dict[str, Any]:
    """Returns the parsed ``.gitlab-ci.yml``.

    The file is read once; every call returns a copy of its own, so a test that changes it does not affect others.
    """
    return copy.deepcopy(_read_ci_config())


def extended_templates(job: dict[str, Any]) -> list[str]:
    """Returns the templates a job extends directly (``extends`` names one template or a list of them)."""
    extends: str | list[str] = job.get("extends", [])
    return [extends] if isinstance(extends, str) else extends


def effective_rules(
    config: dict[str, Any], job: dict[str, Any], seen: frozenset[str] = frozenset()
) -> list[Any] | None:
    """Returns the rules of a job: its own, else the effective rules of the last template it extends that has any.

    A template's effective rules are found the same way, so templates count through every level of ``extends``
    (job -> ``.a`` -> ``.b``), as in GitLab. Returns None if neither the job nor any of its templates has rules.
    ``seen`` holds the templates already visited on the way to ``job``; a cycle of templates (which GitLab rejects)
    ends where it comes back to one of them.
    """
    if "rules" in job:
        return job["rules"]
    # the last template with rules wins, as in GitLab:
    for template in reversed(extended_templates(job)):
        if template in seen:
            continue
        rules: list[Any] | None = effective_rules(
            config, config[template], seen | {template}
        )
        if rules is not None:
            return rules
    return None


def jobs_not_kept_out_of_schedules(config: dict[str, Any]) -> list[str]:
    """Returns the jobs outside SCHEDULED_JOBS whose rules do not start with NOT_IN_SCHEDULE.

    The rules are the effective ones, see :func:`effective_rules`.
    """
    # keys starting with a dot are templates, which GitLab never runs as jobs:
    jobs: list[str] = [
        name
        for name in config
        if not name.startswith(".") and name not in RESERVED_KEYS
    ]
    # a job without rules has no first rule, so it is reported:
    return [
        name
        for name in jobs
        if name not in SCHEDULED_JOBS
        and (effective_rules(config, config[name]) or [None])[0] != NOT_IN_SCHEDULE
    ]


def image_name(job: dict[str, Any]) -> str | None:
    """Returns the name of a job's own image, or None if the job sets no image.

    GitLab accepts ``image`` as a plain name or as a dict whose ``name`` is the name.
    """
    image: Any = job.get("image")
    if isinstance(image, dict):
        image = image.get("name")
    return image if isinstance(image, str) else None


def jobs_without_pinned_image(config: dict[str, Any], jobs: Iterable[str]) -> list[str]:
    """Returns those of the given jobs whose own image is missing or not pinned by digest, see PINNED_IMAGE."""
    return [
        name
        for name in jobs
        if not PINNED_IMAGE.fullmatch(image_name(config[name]) or "")
    ]


def all_extended_templates(config: dict[str, Any], name: str) -> list[str]:
    """Returns every template a job extends, directly or through other templates, each once.

    A cycle of templates (which GitLab rejects) ends where it comes back to a template already found or to the job.
    """
    found: list[str] = []
    pending: list[str] = list(extended_templates(config[name]))
    while pending:
        template: str = pending.pop(0)
        if template in found or template == name:
            continue
        found.append(template)
        pending.extend(extended_templates(config[template]))
    return found


def cache_places(config: dict[str, Any], jobs: Iterable[str]) -> list[str]:
    """Returns every place that gives or may give the given jobs a cache, such as ``"default.cache"``.

    The places are the top-level ``cache``, the ``cache`` in the top-level ``default``, a top-level ``include``
    (an included file can add a cache this function cannot see), and the ``cache`` of each job and of every
    template it extends, see :func:`all_extended_templates`.
    """
    places: list[str] = []
    if "cache" in config:
        places.append("cache")
    if "cache" in (config.get("default") or {}):
        places.append("default.cache")
    if "include" in config:
        places.append("include")
    for name in jobs:
        for key in [*all_extended_templates(config, name), name]:
            if "cache" in config[key]:
                places.append(f"{key}.cache")
    return places


def script_lines(script: str | list[Any]) -> list[str]:
    """Returns the shell lines of a job's script.

    A script given as one string (GitLab accepts that, too) counts as a list with that string. Multi-line
    entries are split into their lines; nested lists (from ``!reference``) are flattened.
    """
    if isinstance(script, str):
        script = [script]
    lines: list[str] = []
    for entry in script:
        if isinstance(entry, list):
            lines.extend(script_lines(entry))
        else:
            lines.extend(str(entry).splitlines())
    return lines


def cargo_home_problem(job: dict[str, Any]) -> str | None:
    """Returns why the ``CARGO_HOME`` of a job is unsafe, or None if it is safe.

    It is safe if the job's own ``variables`` set it to a path that fully matches SAFE_CARGO_HOME and has no
    ``..`` segment, and no line of the job's ``script`` contains ``CARGO_HOME=`` (an export there would override
    the variable).
    """
    cargo_home: Any = (job.get("variables") or {}).get("CARGO_HOME")
    if not isinstance(cargo_home, str):
        return "CARGO_HOME is not set"
    if not SAFE_CARGO_HOME.fullmatch(cargo_home):
        return f"CARGO_HOME {cargo_home} is not a fixed path below /tmp"
    if ".." in cargo_home.split("/"):
        return f"CARGO_HOME {cargo_home} leaves /tmp through .."
    for line in script_lines(job.get("script", [])):
        if "CARGO_HOME=" in line:
            return f"the script sets CARGO_HOME: {line}"
    return None


def checksum_order_problem(script: str | list[Any]) -> str | None:
    """Returns why a script may unpack an archive before checking it, or None if it checks it first.

    The check passes if a line verifies a checksum (see VERIFIES_CHECKSUM), a line matches RUNS_TAR, and the
    first checking line comes before the first tar line. A line that does both counts as unpacking too early.
    The match is textual: it does not check which file is verified or unpacked, and it also counts ``tar`` in a
    file name such as ``a.tar.gz`` as tar. It does not notice a check whose failure the shell ignores in other
    ways (a line starting with ``!``, an earlier ``set +e``), and it counts a comment or an ``echo`` whose
    unquoted argument ends with the check command as a check, although such a line checks nothing.
    """
    lines: list[str] = script_lines(script)
    check: int | None = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip().endswith(VERIFIES_CHECKSUM) and "||" not in line
        ),
        None,
    )
    unpack: int | None = next(
        (i for i, line in enumerate(lines) if RUNS_TAR.search(line)), None
    )
    if check is None:
        return f"no line without || ends with {VERIFIES_CHECKSUM}"
    if unpack is None:
        return "no line runs tar"
    if unpack <= check:
        return f"tar runs before {VERIFIES_CHECKSUM}: {lines[unpack]}"
    return None


def jobs_kept_out_of_schedules(
    config: dict[str, Any], jobs: Iterable[str]
) -> list[str]:
    """Returns those of the given jobs whose rules start with NOT_IN_SCHEDULE, so they never run in scheduled pipelines.

    The rules are the effective ones, see :func:`effective_rules`; a job without rules runs in every pipeline.
    """
    return [
        name
        for name in jobs
        if (effective_rules(config, config[name]) or [None])[0] == NOT_IN_SCHEDULE
    ]


def failure_keys(entry: dict[str, Any]) -> list[str]:
    """Returns the keys of a job, template or rule that let the job fail without failing the pipeline.

    These are an ``allow_failure`` other than ``false`` (also ``exit_codes``), and a ``when: manual`` without
    ``allow_failure: false`` next to it (GitLab lets such a job fail, or not run at all, without failing the
    pipeline).
    """
    keys: list[str] = []
    if entry.get("allow_failure", False) is not False:
        keys.append("allow_failure")
    if entry.get("when") == "manual" and entry.get("allow_failure") is not False:
        keys.append("when")
    return keys


def allow_failure_places(config: dict[str, Any], jobs: Iterable[str]) -> list[str]:
    """Returns every place that lets or may let one of the given jobs fail without failing the pipeline.

    The places are a top-level ``include`` (an included file can add such a key this function cannot see), and
    the keys of :func:`failure_keys` in each job, in every template it extends (see :func:`all_extended_templates`)
    and in each of its effective rules (see :func:`effective_rules`), e.g. ``"job.allow_failure"`` or
    ``"job.rules[1].when"``.
    """
    places: list[str] = ["include"] if "include" in config else []
    for name in jobs:
        for key in [*all_extended_templates(config, name), name]:
            places.extend(f"{key}.{field}" for field in failure_keys(config[key]))
        for i, rule in enumerate(effective_rules(config, config[name]) or []):
            if isinstance(rule, dict):
                places.extend(
                    f"{name}.rules[{i}].{field}" for field in failure_keys(rule)
                )
    return places


def run_condition_places(config: dict[str, Any], jobs: Iterable[str]) -> list[str]:
    """Returns every place that decides or may decide when one of the given jobs runs, such as ``"job.rules"``.

    The places are a top-level ``include`` (an included file can add such a key this function cannot see), and
    the keys ``rules``, ``only``, ``except`` and ``when`` of each job and of every template it extends, see
    :func:`all_extended_templates`.
    """
    places: list[str] = ["include"] if "include" in config else []
    for name in jobs:
        for key in [*all_extended_templates(config, name), name]:
            places.extend(
                f"{key}.{field}"
                for field in ("rules", "only", "except", "when")
                if field in config[key]
            )
    return places


def is_cargo_audit(word: str) -> bool:
    """Returns whether a word of a shell line names the cargo-audit program: ``cargo-audit`` or a path ending in it."""
    return word == "cargo-audit" or word.endswith("/cargo-audit")


def cargo_audit_command(lines: list[str]) -> tuple[int, list[str]] | None:
    """Returns the position and the words of the first line that runs ``cargo-audit audit``, or None if none does.

    The words are those of :func:`shlex.split`, so quotes are removed. A line runs the audit if one word names
    cargo-audit (see :func:`is_cargo_audit`) and the next word is ``audit``. A line that shlex cannot split (such
    as one with an unclosed quote) is skipped.
    """
    for i, line in enumerate(lines):
        try:
            words: list[str] = shlex.split(line)
        except ValueError:
            continue
        for word, next_word in zip(words, words[1:]):
            if is_cargo_audit(word) and next_word == "audit":
                return i, words
    return None


def audit_toml_guard_problem(  # pylint: disable=too-many-return-statements
    script: str | list[Any],
) -> str | None:
    """Returns why a script may run cargo-audit without first failing on an ``audit.toml``, or None if it may not.

    The guard is the first line that contains ``audit.toml`` and starts with a loop such as ``for f in a b; do``
    (see FOR_LOOP). The check passes if the words the loop goes through are exactly AUDIT_TOML_PATHS, the line
    contains ``exit 1``, it comes before the first line that runs cargo-audit (see :func:`cargo_audit_command`),
    and it comes before the first line that changes the directory (see CHANGES_DIRECTORY), as the paths are
    relative to the repository root. Like :func:`checksum_order_problem`, the match is textual: it does not check
    what the loop body tests, and it also counts ``cd`` in a path such as ``/tmp/cd`` as a change of directory.
    """
    lines: list[str] = script_lines(script)
    guard: tuple[int, re.Match[str]] | None = next(
        (
            (i, match)
            for i, line in enumerate(lines)
            if "audit.toml" in line and (match := FOR_LOOP.match(line.strip()))
        ),
        None,
    )
    audit: tuple[int, list[str]] | None = cargo_audit_command(lines)
    if guard is None:
        return "no line loops over the audit.toml paths"
    if audit is None:
        return "no line runs cargo-audit audit"
    paths: set[str] = set(shlex.split(guard[1].group(1)))
    if paths != AUDIT_TOML_PATHS:
        return f"the guard checks {sorted(paths)} instead of {sorted(AUDIT_TOML_PATHS)}"
    if "exit 1" not in lines[guard[0]]:
        return "the guard does not exit 1"
    if audit[0] <= guard[0]:
        return f"cargo-audit runs before the guard: {lines[audit[0]]}"
    cd: int | None = next(
        (i for i, line in enumerate(lines) if CHANGES_DIRECTORY.search(line)), None
    )
    if cd is not None and cd <= guard[0]:
        return f"the directory changes before the guard: {lines[cd]}"
    return None


def audited_lockfile(script: str | list[Any]) -> str | None:
    """Returns the lockfile the first ``cargo-audit audit`` of a script checks, or None if it names none.

    The lockfile is the word after ``--file`` or ``-f``, or the rest of a word ``--file=...``, in the words of
    :func:`cargo_audit_command`. None also stands for a script without ``cargo-audit audit``.
    """
    command: tuple[int, list[str]] | None = cargo_audit_command(script_lines(script))
    if command is None:
        return None
    words: list[str] = command[1]
    for i, word in enumerate(words):
        if word in ("--file", "-f") and i + 1 < len(words):
            return words[i + 1]
        if word.startswith("--file="):
            return word.removeprefix("--file=")
    return None


def audit_option_problems(script: str | list[Any]) -> list[str]:
    """Returns the options of the first ``cargo-audit audit`` of a script that are not allowed, or an empty list.

    Allowed are the words after ``audit`` that are in AUDIT_FLAGS, and pairs of an option of
    AUDIT_OPTIONS_WITH_VALUE and a value that fully matches its pattern. Any other word is reported, and an
    option of AUDIT_OPTIONS_WITH_VALUE together with its wrong value (or alone, if it ends the line). Shell
    operators after the command, such as ``|| true``, are words like any other and are reported too. A script
    without ``cargo-audit audit`` gives a list with that problem.
    """
    command: tuple[int, list[str]] | None = cargo_audit_command(script_lines(script))
    if command is None:
        return ["no line runs cargo-audit audit"]
    words: list[str] = command[1]
    # the words after the first "cargo-audit audit" of the line:
    i: int = next(
        i + 2
        for i, (word, next_word) in enumerate(zip(words, words[1:]))
        if is_cargo_audit(word) and next_word == "audit"
    )
    problems: list[str] = []
    while i < len(words):
        word: str = words[i]
        if word in AUDIT_FLAGS:
            i += 1
        elif word in AUDIT_OPTIONS_WITH_VALUE:
            value: str | None = words[i + 1] if i + 1 < len(words) else None
            if value is None or not AUDIT_OPTIONS_WITH_VALUE[word].fullmatch(value):
                problems.append(word if value is None else f"{word} {value}")
            i += 2
        else:
            problems.append(word)
            i += 1
    return problems


def audit_file_problems(root: Path) -> list[str]:
    """Returns what is wrong with the files of a repository that the Rust audit depends on, or an empty list.

    Wrong are a missing RUST_LOCKFILE (the job would fail without auditing anything) and each existing file of
    AUDIT_TOML_PATHS, also a symbolic link whose target does not exist (the job would fail on it).
    """
    problems: list[str] = []
    if not (root / RUST_LOCKFILE).is_file():
        problems.append(f"{RUST_LOCKFILE} is missing")
    for path in sorted(AUDIT_TOML_PATHS):
        if (root / path).exists() or (root / path).is_symlink():
            problems.append(f"{path} exists")
    return problems


class ScheduledPipelineTest(unittest.TestCase):
    """Checks which jobs run in scheduled pipelines."""

    def test_only_scheduled_jobs_run_in_scheduled_pipelines(self) -> None:
        """Every job of .gitlab-ci.yml except those in SCHEDULED_JOBS starts its rules with NOT_IN_SCHEDULE."""
        config: dict[str, Any] = load_ci_config()
        # the scheduled jobs exist, so a renamed job is noticed:
        self.assertLessEqual(SCHEDULED_JOBS, set(config))
        self.assertEqual(
            [],
            jobs_not_kept_out_of_schedules(config),
            "extend .not_in_scheduled_pipelines or start the job's rules with the schedule/never rule",
        )

    def test_job_without_the_rule_is_found(self) -> None:
        """Jobs whose effective rules do not start with NOT_IN_SCHEDULE are found.

        Scheduled jobs, templates, reserved keys and jobs that start their rules (own or extended) with
        NOT_IN_SCHEDULE are not reported.
        """
        config: dict[str, Any] = {
            "stages": ["test"],
            ".not_in_scheduled_pipelines": {
                "rules": [NOT_IN_SCHEDULE, {"when": "on_success"}]
            },
            "serializability_nightly": {"script": ["true"]},
            "extended": {"extends": ".not_in_scheduled_pipelines"},
            "own_rules": {"rules": [NOT_IN_SCHEDULE, {"if": "$CI_COMMIT_BRANCH"}]},
            "without_rules": {"script": ["true"]},
            "rule_not_first": {"rules": [{"if": "$CI_COMMIT_BRANCH"}, NOT_IN_SCHEDULE]},
            ".no_rules": {"script": ["true"]},
            ".other_rules": {"rules": [{"when": "on_success"}]},
            "extends_template_without_rules": {"extends": ".no_rules"},
            # the last template with rules counts, as in GitLab:
            "extends_list_good_last": {
                "extends": [".other_rules", ".not_in_scheduled_pipelines", ".no_rules"]
            },
            "extends_list_bad_last": {
                "extends": [".not_in_scheduled_pipelines", ".other_rules"]
            },
        }
        self.assertEqual(
            [
                "without_rules",
                "rule_not_first",
                "extends_template_without_rules",
                "extends_list_bad_last",
            ],
            jobs_not_kept_out_of_schedules(config),
        )

    def test_rules_are_found_through_every_level_of_templates(self) -> None:
        """A job without rules has those of its templates, followed through every level of ``extends``.

        Of several templates, the last one with (own or inherited) rules counts, and a template's own rules count
        before those it inherits, as in GitLab. Would fail if only the templates a job extends directly were
        looked at, or would not end if a cycle of templates were followed again.
        """
        other: list[Any] = [{"when": "on_success"}]
        config: dict[str, Any] = {
            ".base": {"rules": [NOT_IN_SCHEDULE]},
            ".middle": {"extends": ".base"},
            ".middle_with_rules": {"extends": ".base", "rules": other},
            ".other": {"rules": other},
            ".plain": {"script": ["true"]},
            ".loop_a": {"extends": ".loop_b"},
            ".loop_b": {"extends": ".loop_a"},
            "two_levels": {"extends": ".middle"},
            "own_rules_of_middle_first": {"extends": ".middle_with_rules"},
            "inherited_rules_of_last_template": {"extends": [".other", ".middle"]},
            "last_template_without_rules": {"extends": [".middle", ".plain"]},
            "cycle": {"extends": ".loop_a"},
        }
        self.assertEqual(
            {
                "two_levels": [NOT_IN_SCHEDULE],
                "own_rules_of_middle_first": other,
                "inherited_rules_of_last_template": [NOT_IN_SCHEDULE],
                "last_template_without_rules": [NOT_IN_SCHEDULE],
                "cycle": None,
            },
            {
                name: effective_rules(config, job)
                for name, job in config.items()
                if not name.startswith(".")
            },
        )
        self.assertEqual(
            ["inherited_rules_of_last_template"],
            jobs_kept_out_of_schedules(
                config, ["inherited_rules_of_last_template", "cycle"]
            ),
        )

    def test_scheduled_jobs_run_in_scheduled_pipelines(self) -> None:
        """No SCHEDULED_JOBS in .gitlab-ci.yml start their rules with NOT_IN_SCHEDULE; AUDIT_JOBS have no conditions.

        The AUDIT_JOBS have no effective rules and no place that decides when they run (see
        :func:`run_condition_places`), so they run in every pipeline, scheduled or not. Would fail if a scheduled
        job, such as ``generated_rust_check``, extended ``.not_in_scheduled_pipelines`` and so silently stopped
        running in the nightly pipeline, or if an audit job got rules, ``only``, ``except`` or ``when``, which could
        keep it out of the nightly pipeline or out of merge requests.
        """
        config: dict[str, Any] = load_ci_config()
        self.assertLessEqual(SCHEDULED_JOBS, set(config))
        self.assertEqual([], jobs_kept_out_of_schedules(config, sorted(SCHEDULED_JOBS)))
        self.assertEqual(
            {name: None for name in AUDIT_JOBS},
            {name: effective_rules(config, config[name]) for name in AUDIT_JOBS},
        )
        self.assertEqual([], run_condition_places(config, AUDIT_JOBS))

    def test_run_conditions_are_found(self) -> None:
        """``rules``, ``only``, ``except`` and ``when`` in a job or any template it extends, and an include are found.

        Templates are followed through every level of ``extends``. Other keys and jobs not asked about are not
        reported.
        """
        config: dict[str, Any] = {
            "include": [{"local": "ci/more.yml"}],
            ".deep": {"only": ["main"]},
            ".middle": {"extends": ".deep", "except": ["tags"]},
            "two_levels": {"extends": ".middle", "script": ["true"]},
            "own": {"rules": [{"when": "always"}], "when": "on_success"},
            "without_conditions": {"script": ["true"], "retry": {"when": ["x"]}},
            "not_asked_about": {"when": "manual"},
        }
        self.assertEqual(
            ["include", ".middle.except", ".deep.only", "own.rules", "own.when"],
            run_condition_places(config, ["two_levels", "own", "without_conditions"]),
        )

    def test_scheduled_job_kept_out_is_found(self) -> None:
        """Jobs whose effective rules start with NOT_IN_SCHEDULE are found; jobs without rules run and are not.

        Would fail if a rule from an extended template were ignored, or if a job without rules were reported.
        """
        config: dict[str, Any] = {
            ".not_in_scheduled_pipelines": {
                "rules": [NOT_IN_SCHEDULE, {"when": "on_success"}]
            },
            "without_rules": {"script": ["true"]},
            "own_schedule_rule": {
                "rules": [{"if": "$CI_PIPELINE_SOURCE == 'schedule'"}]
            },
            "extended": {"extends": ".not_in_scheduled_pipelines"},
            "own_rules": {"rules": [NOT_IN_SCHEDULE, {"when": "on_success"}]},
        }
        self.assertEqual(
            ["extended", "own_rules"],
            jobs_kept_out_of_schedules(config, list(config)[1:]),
        )


class PinnedImageTest(unittest.TestCase):
    """Checks that the Rust audit job runs in an image pinned by digest.

    Whoever controls an image repository can move a tag such as ``curl:8.22.0`` to a different image at any
    time. A digest names one exact image, so the programs that run the audit can only change through a change of
    ``.gitlab-ci.yml``, which reviewers see.
    """

    def test_rust_audit_image_is_pinned_by_digest(self) -> None:
        """The image of RUST_AUDIT_JOB in .gitlab-ci.yml ends in ``@sha256:`` and 64 lowercase hex digits."""
        config: dict[str, Any] = load_ci_config()
        self.assertIn(RUST_AUDIT_JOB, config)
        self.assertEqual(
            [],
            jobs_without_pinned_image(config, [RUST_AUDIT_JOB]),
            "pin the image by tag and digest: name:tag@sha256:<64 hex digits>",
        )

    def test_job_without_pinned_image_is_found(self) -> None:
        """Jobs without an image, or whose image (a plain name or a dict's ``name``) has no valid digest, are found.

        A digest must consist of exactly 64 lowercase hex digits; jobs not asked about are not reported.
        """
        digest: str = "@sha256:" + "0123456789abcdef" * 4
        config: dict[str, Any] = {
            "plain_pinned": {"image": "alpine:3.22" + digest},
            "dict_pinned": {
                "image": {"name": "curl:8.22.0" + digest, "entrypoint": [""]}
            },
            "plain_tag_only": {"image": "alpine:3.22"},
            "dict_tag_only": {"image": {"name": "alpine:3.22", "entrypoint": [""]}},
            "dict_without_name": {"image": {"entrypoint": [""]}},
            "without_image": {"script": ["true"]},
            "uppercase_digest": {"image": "alpine@sha256:" + "A" * 64},
            "short_digest": {"image": "alpine@sha256:" + "a" * 63},
            "long_digest": {"image": "alpine@sha256:" + "a" * 65},
            "not_asked_about": {"image": "alpine:3.22"},
        }
        jobs: list[str] = [name for name in config if name != "not_asked_about"]
        self.assertEqual(
            [
                "plain_tag_only",
                "dict_tag_only",
                "dict_without_name",
                "without_image",
                "uppercase_digest",
                "short_digest",
                "long_digest",
            ],
            jobs_without_pinned_image(config, jobs),
        )


class NoCacheTest(unittest.TestCase):
    """Checks that nothing can give the audit jobs a cache.

    Checked are the top-level ``cache``, the ``cache`` in ``default``, a top-level ``include`` (which may add a
    cache), and the ``cache`` of the audit jobs and of every template they extend, directly or through other
    templates. GitLab shares a cache between the pipelines of different branches, including merge request
    branches. With a cache, one merge request could plant a changed program in it, and the audit job of another
    branch would run it. Without a cache, every run starts from the pinned image and downloads that are checked.
    """

    def test_audit_jobs_have_no_cache(self) -> None:
        """.gitlab-ci.yml has no place that gives or may give the AUDIT_JOBS a cache, see :func:`cache_places`."""
        config: dict[str, Any] = load_ci_config()
        # the audit jobs exist, so a renamed job is noticed (a missing job would have no cache either):
        self.assertLessEqual(set(AUDIT_JOBS), set(config))
        self.assertEqual([], cache_places(config, AUDIT_JOBS))

    def test_cache_is_found(self) -> None:
        """A cache at the top level, in ``default``, in a job or in any template it extends, and an include are found.

        Templates are followed through every level of ``extends``. Templates without a cache and jobs not asked
        about are not reported.
        """
        cache: dict[str, Any] = {"paths": ["target"]}
        config: dict[str, Any] = {
            "cache": cache,
            "default": {"cache": cache},
            "include": [{"local": "ci/more.yml"}],
            ".cached": {"cache": cache},
            ".plain": {"script": ["true"]},
            ".deep_cached": {"cache": cache},
            ".middle": {"extends": ".deep_cached"},
            "extends_cached": {"extends": [".plain", ".cached"], "script": ["true"]},
            "own_cache": {"cache": cache, "script": ["true"]},
            "two_levels": {"extends": ".middle", "script": ["true"]},
            "without_cache": {"script": ["true"]},
            "not_asked_about": {"cache": cache},
        }
        self.assertEqual(
            [
                "cache",
                "default.cache",
                "include",
                ".cached.cache",
                "own_cache.cache",
                ".deep_cached.cache",
            ],
            cache_places(
                config, ["extends_cached", "own_cache", "two_levels", "without_cache"]
            ),
        )

    def test_config_without_cache_has_none(self) -> None:
        """A configuration whose ``default`` and extended templates set no cache gives no places.

        Would fail if any ``default`` or any ``extends`` (here a single name) were taken for a cache, or would not
        end if a cycle of templates (here back to a template found before and back to the job) were followed again.
        """
        config: dict[str, Any] = {
            "default": {"image": "alpine:3.22"},
            ".plain": {"extends": ".loop"},
            ".loop": {"extends": [".plain", "audit"]},
            "audit": {"extends": ".plain"},
        }
        self.assertEqual([], cache_places(config, ["audit"]))


class CargoHomeTest(unittest.TestCase):
    """Checks that the Rust audit job sets CARGO_HOME to a fixed path below /tmp, outside the checkout.

    cargo-audit reads an ``audit.toml`` from CARGO_HOME, which can switch off advisories, and keeps its copy of
    the advisory database there. In the checkout, a merge request could supply both itself and so hide a known
    vulnerability. Ignored advisories belong in the job's command line instead, where reviewers see them. Only
    a fixed path below /tmp is accepted: a variable or a ``..`` could lead back into the checkout.
    """

    def test_rust_audit_cargo_home_is_outside_the_checkout(self) -> None:
        """RUST_AUDIT_JOB in .gitlab-ci.yml sets CARGO_HOME to a fixed path below /tmp; its script does not set it."""
        config: dict[str, Any] = load_ci_config()
        self.assertIn(RUST_AUDIT_JOB, config)
        self.assertIsNone(cargo_home_problem(config[RUST_AUDIT_JOB]))

    def test_unsafe_cargo_home_is_found(self) -> None:
        """An unsafe CARGO_HOME is reported with its reason.

        Unsafe is a CARGO_HOME that is missing, not a fixed path below /tmp, leaves /tmp through ``..``, or is set
        in the script.
        """
        safe: dict[str, str] = {"CARGO_HOME": "/tmp/cargo-home"}
        jobs: dict[str, dict[str, Any]] = {
            "safe": {"variables": safe, "script": ["cd /tmp"]},
            "without_variables": {"script": ["true"]},
            "without_cargo_home": {"variables": {"GIT_DEPTH": 0}},
            "project_dir": {"variables": {"CARGO_HOME": "$CI_PROJECT_DIR/.cargo"}},
            "checkout_path": {
                "variables": {"CARGO_HOME": "/builds/group/project/.cargo"}
            },
            "variable_after_slash": {
                "variables": {"CARGO_HOME": "/${CI_PROJECT_DIR}/x"}
            },
            "variable_below_tmp": {"variables": {"CARGO_HOME": "/tmp/$X"}},
            "relative": {"variables": {"CARGO_HOME": "cargo-home"}},
            "dot_dot": {"variables": {"CARGO_HOME": "/tmp/../builds/x"}},
            "exported_in_script": {
                "variables": safe,
                "script": ["true", "export CARGO_HOME=/builds/x"],
            },
            "exported_in_string_script": {
                "variables": safe,
                "script": "export CARGO_HOME=/builds/x",
            },
        }
        self.assertEqual(
            {
                "safe": None,
                "without_variables": "CARGO_HOME is not set",
                "without_cargo_home": "CARGO_HOME is not set",
                "project_dir": "CARGO_HOME $CI_PROJECT_DIR/.cargo is not a fixed path below /tmp",
                "checkout_path": "CARGO_HOME /builds/group/project/.cargo is not a fixed path below /tmp",
                "variable_after_slash": "CARGO_HOME /${CI_PROJECT_DIR}/x is not a fixed path below /tmp",
                "variable_below_tmp": "CARGO_HOME /tmp/$X is not a fixed path below /tmp",
                "relative": "CARGO_HOME cargo-home is not a fixed path below /tmp",
                "dot_dot": "CARGO_HOME /tmp/../builds/x leaves /tmp through ..",
                "exported_in_script": "the script sets CARGO_HOME: export CARGO_HOME=/builds/x",
                "exported_in_string_script": "the script sets CARGO_HOME: export CARGO_HOME=/builds/x",
            },
            {name: cargo_home_problem(job) for name, job in jobs.items()},
        )


class ChecksumBeforeUnpackTest(unittest.TestCase):
    """Checks that the Rust audit job verifies the downloaded archive before it unpacks it.

    The archive with cargo-audit comes from the internet. tar writes whatever files the archive contains, so an
    archive that was swapped on the way could already change files before anything in it runs. Checking the
    SHA-256 first makes sure that tar only ever sees the exact archive whose checksum is in ``.gitlab-ci.yml``.
    """

    def test_rust_audit_checks_the_archive_before_unpacking(self) -> None:
        """The script of RUST_AUDIT_JOB in .gitlab-ci.yml checks the archive's SHA-256 on a line before the first tar.

        See :func:`checksum_order_problem` for what counts as a check and as tar.
        """
        config: dict[str, Any] = load_ci_config()
        self.assertIn(RUST_AUDIT_JOB, config)
        self.assertIsNone(checksum_order_problem(config[RUST_AUDIT_JOB]["script"]))

    def test_unpacking_before_the_check_is_found(self) -> None:
        """Scripts without a check, without tar, or with tar on or before the first check line are reported.

        Lines of multi-line entries and of nested lists count on their own. Not counted as a check: ``sha256sum``
        without ``-c``, a line with ``||`` (``|| true`` ignores a mismatch, ``a || check`` may skip the check), and
        an ``echo`` of the check command in quotes. tar counts wherever it stands as a word (``/bin/tar``,
        ``busybox tar``, ``then tar``, ``| tar``), but not inside a word (``start``).
        """
        check: str = 'echo "$SHA  /tmp/a.tgz" | sha256sum -c -'
        unpack: str = "tar -xzf /tmp/a.tgz -C /tmp"
        no_check: str = "no line without || ends with sha256sum -c -"
        scripts: dict[str, list[Any]] = {
            "check_first": ["curl -o /tmp/a.tgz $URL", check, unpack],
            "check_first_in_block": [f"{check}\n{unpack}"],
            "check_first_in_nested_list": [[check], unpack],
            "tar_first": [unpack, check],
            "piped_tar_first": ["curl $URL | tar -xz", check],
            "bin_tar_first": ["/bin/tar -xzf /tmp/a.tgz", check, unpack],
            "busybox_tar_first": ["busybox tar -xzf /tmp/a.tgz", check, unpack],
            "then_tar_first": ["if true; then tar -xzf /tmp/a.tgz; fi", check, unpack],
            "check_then_tar_on_one_line": [f"{check} && {unpack}"],
            "tar_then_check_on_one_line": [f"{unpack} && {check}"],
            "check_switched_off": [f"{check} || true", unpack],
            # the check runs only if test -f fails:
            "check_skipped_by_or": [f"test -f /tmp/ok || {check}", unpack],
            "check_only_echoed": ['echo "run sha256sum -c -"', unpack],
            "sha256sum_without_check": ["sha256sum /tmp/a.tgz", unpack],
            "without_tar": [check, "echo start"],
        }
        self.assertEqual(
            {
                "check_first": None,
                "check_first_in_block": None,
                "check_first_in_nested_list": None,
                "tar_first": f"tar runs before sha256sum -c -: {unpack}",
                "piped_tar_first": "tar runs before sha256sum -c -: curl $URL | tar -xz",
                "bin_tar_first": "tar runs before sha256sum -c -: /bin/tar -xzf /tmp/a.tgz",
                "busybox_tar_first": "tar runs before sha256sum -c -: busybox tar -xzf /tmp/a.tgz",
                "then_tar_first": "tar runs before sha256sum -c -: if true; then tar -xzf /tmp/a.tgz; fi",
                "check_then_tar_on_one_line": no_check,
                "tar_then_check_on_one_line": f"tar runs before sha256sum -c -: {unpack} && {check}",
                "check_switched_off": no_check,
                "check_skipped_by_or": no_check,
                "check_only_echoed": no_check,
                "sha256sum_without_check": no_check,
                "without_tar": "no line runs tar",
            },
            {name: checksum_order_problem(script) for name, script in scripts.items()},
        )


class NoAllowFailureTest(unittest.TestCase):
    """Checks that a finding of an audit job fails the pipeline.

    With ``allow_failure`` the pipeline would pass despite a known vulnerability, and the merge request could be
    merged; only a warning would remain in the pipeline view.
    """

    def test_audit_jobs_do_not_allow_failure(self) -> None:
        """.gitlab-ci.yml has no place that lets the AUDIT_JOBS fail, see :func:`allow_failure_places`.

        Would fail if, for example, ``rust_dependency_audit`` got a rule
        ``if: $CI_PIPELINE_SOURCE == 'merge_request_event'`` with ``allow_failure: true`` or ``when: manual``.
        """
        config: dict[str, Any] = load_ci_config()
        self.assertLessEqual(set(AUDIT_JOBS), set(config))
        self.assertEqual([], allow_failure_places(config, AUDIT_JOBS))

    def test_allow_failure_is_found(self) -> None:
        """An ``allow_failure`` or ``when: manual`` in a job, a template it extends or an effective rule is found.

        So is a top-level include. ``allow_failure: false``, ``when: manual`` next to ``allow_failure: false``, and
        jobs not asked about are not reported. Would fail if ``exit_codes`` (which lets some failures pass) were
        not counted, if a rule taken from a template were ignored, or if a ``when: manual`` without
        ``allow_failure: false`` were not counted.
        """
        config: dict[str, Any] = {
            "include": [{"local": "ci/more.yml"}],
            ".allowed": {"allow_failure": True},
            ".manual": {"when": "manual"},
            ".rules_allowed": {
                "rules": [{"when": "on_success", "allow_failure": True}]
            },
            "own": {"allow_failure": True},
            "exit_codes": {"allow_failure": {"exit_codes": [1]}},
            "explicitly_false": {
                "allow_failure": False,
                "rules": [{"allow_failure": False}],
            },
            "extends_allowed": {"extends": ".allowed"},
            "own_rule": {
                "rules": [{"if": "$CI_MERGE_REQUEST_IID"}, {"allow_failure": True}]
            },
            "extends_rule": {"extends": ".rules_allowed"},
            "manual": {"when": "manual"},
            "manual_and_allowed": {"when": "manual", "allow_failure": True},
            "manual_explicitly_false": {
                "when": "manual",
                "allow_failure": False,
                "rules": [{"when": "manual", "allow_failure": False}],
            },
            "extends_manual": {"extends": ".manual"},
            "manual_rule": {
                "rules": [{"if": "$CI_MERGE_REQUEST_IID", "when": "manual"}]
            },
            "not_asked_about": {"allow_failure": True},
        }
        self.assertEqual(
            [
                "include",
                "own.allow_failure",
                "exit_codes.allow_failure",
                ".allowed.allow_failure",
                "own_rule.rules[1].allow_failure",
                "extends_rule.rules[0].allow_failure",
                "manual.when",
                "manual_and_allowed.allow_failure",
                "manual_and_allowed.when",
                ".manual.when",
                "manual_rule.rules[0].when",
            ],
            allow_failure_places(
                config,
                [
                    "own",
                    "exit_codes",
                    "explicitly_false",
                    "extends_allowed",
                    "own_rule",
                    "extends_rule",
                    "manual",
                    "manual_and_allowed",
                    "manual_explicitly_false",
                    "extends_manual",
                    "manual_rule",
                ],
            ),
        )


class AuditTomlGuardTest(unittest.TestCase):
    """Checks that the Rust audit job fails on an ``audit.toml`` before it runs cargo-audit.

    A local ``cargo audit`` reads ignored advisories from an ``audit.toml``. The job does not (see CargoHomeTest),
    but a file in the repository would make local runs differ from the job and hide advisories from reviewers.
    """

    def test_rust_audit_fails_on_audit_toml_first(self) -> None:
        """The script of RUST_AUDIT_JOB in .gitlab-ci.yml loops over exactly AUDIT_TOML_PATHS before cargo-audit and cd.

        Would fail if the guard lost one of the paths or checked another path, such as ``rust/.cargo/audit.toml``,
        no longer exited with 1, or came after the cargo-audit line or after the ``cd /tmp`` (its paths are relative
        to the repository root).
        """
        config: dict[str, Any] = load_ci_config()
        self.assertIn(RUST_AUDIT_JOB, config)
        self.assertIsNone(audit_toml_guard_problem(config[RUST_AUDIT_JOB]["script"]))

    def test_missing_or_late_guard_is_found(self) -> None:
        """Scripts without a guard or cargo-audit, with other paths, without ``exit 1`` or a late guard are reported.

        A guard is late if it comes after cargo-audit or after a ``cd``. Would fail if the paths were compared as a
        subset or superset instead of exactly, or if the order were not checked.
        """
        guard: str = (
            'for f in .cargo/audit.toml generated/rust/.cargo/audit.toml; do if [ -e "$f" ]; then exit 1; fi; done'
        )
        audit: str = (
            './cargo-audit/cargo-audit audit --file "$CI_PROJECT_DIR/generated/rust/Cargo.lock"'
        )
        scripts: dict[str, list[Any]] = {
            "guard_first": [guard, "cd /tmp", "cargo-audit --version", audit],
            "guard_first_in_block": [f"{guard}\n{audit}"],
            "without_guard": [audit],
            "without_audit": [guard, "cargo-audit --version"],
            "wrong_path": [guard.replace("generated/rust/", "rust/"), audit],
            "dropped_path": [
                guard.replace(" generated/rust/.cargo/audit.toml", ""),
                audit,
            ],
            "extra_path": [guard.replace("; do", " x/audit.toml; do", 1), audit],
            "without_exit": [guard.replace("exit 1", "echo found"), audit],
            "guard_late": [audit, guard],
            "guard_after_cd": ["cd /tmp", guard, audit],
            "guard_after_cd_in_if": ["if true; then cd /tmp; fi", guard, audit],
        }
        expected_paths: list[str] = sorted(AUDIT_TOML_PATHS)
        self.assertEqual(
            {
                "guard_first": None,
                "guard_first_in_block": None,
                "without_guard": "no line loops over the audit.toml paths",
                "without_audit": "no line runs cargo-audit audit",
                "wrong_path": f"the guard checks {['.cargo/audit.toml', 'rust/.cargo/audit.toml']} instead of "
                f"{expected_paths}",
                "dropped_path": f"the guard checks {['.cargo/audit.toml']} instead of {expected_paths}",
                "extra_path": f"the guard checks {[*expected_paths, 'x/audit.toml']} instead of {expected_paths}",
                "without_exit": "the guard does not exit 1",
                "guard_late": f"cargo-audit runs before the guard: {audit}",
                "guard_after_cd": "the directory changes before the guard: cd /tmp",
                "guard_after_cd_in_if": "the directory changes before the guard: if true; then cd /tmp; fi",
            },
            {
                name: audit_toml_guard_problem(script)
                for name, script in scripts.items()
            },
        )


class AuditedLockfileTest(unittest.TestCase):
    """Checks that the Rust audit job audits the lockfile of the Rust code.

    cargo-audit checks only the lockfile it is given. With a wrong path it would fail, or, worse, check another
    lockfile and pass although the Rust code depends on a vulnerable crate.
    """

    def test_rust_audit_checks_the_rust_lockfile(self) -> None:
        """The cargo-audit command of RUST_AUDIT_JOB in .gitlab-ci.yml passes exactly AUDITED_LOCKFILE to ``--file``.

        Would fail if the path named another lockfile, such as ``rust/Cargo.lock``, or were relative (the job runs
        cargo-audit in /tmp).
        """
        config: dict[str, Any] = load_ci_config()
        self.assertIn(RUST_AUDIT_JOB, config)
        self.assertEqual(
            AUDITED_LOCKFILE, audited_lockfile(config[RUST_AUDIT_JOB]["script"])
        )

    def test_lockfile_is_read_from_the_audit_command(self) -> None:
        """The lockfile is taken from ``--file``, ``-f`` or ``--file=`` of the first ``cargo-audit audit`` line.

        Quotes are removed. Would fail if another line naming cargo-audit (such as ``cargo-audit --version``) were
        taken for the audit, or if a missing ``--file`` gave anything but None.
        """
        scripts: dict[str, list[Any]] = {
            "long_option": [
                "cd /tmp",
                './bin/cargo-audit audit --no-yanked --file "/a/Cargo.lock"',
            ],
            "short_option": ["cargo-audit audit -f /b/Cargo.lock"],
            "equals": ["cargo-audit audit --file=/c/Cargo.lock"],
            "version_first": [
                "cargo-audit --version --file /x",
                "cargo-audit audit --file /d/Cargo.lock",
            ],
            "without_file": ["cargo-audit audit --no-yanked"],
            "without_audit": ["cargo-audit --version"],
        }
        self.assertEqual(
            {
                "long_option": "/a/Cargo.lock",
                "short_option": "/b/Cargo.lock",
                "equals": "/c/Cargo.lock",
                "version_first": "/d/Cargo.lock",
                "without_file": None,
                "without_audit": None,
            },
            {name: audited_lockfile(script) for name, script in scripts.items()},
        )


class AuditOptionsTest(unittest.TestCase):
    """Checks that the Rust audit job passes cargo-audit only options that cannot hide a vulnerability.

    Some options of cargo-audit narrow what it checks or which advisories it knows, such as ``--target-os`` (only
    crates used on one system), ``--url`` or ``--db`` (another advisory database), ``-n``/``--no-fetch`` or
    ``--stale`` (an old copy of it). Ignored advisories (``--ignore``) are allowed, as reviewers see each of them.
    """

    def test_rust_audit_passes_only_allowed_options(self) -> None:
        """The cargo-audit command of RUST_AUDIT_JOB in .gitlab-ci.yml has no option outside the allowed ones.

        See AUDIT_FLAGS and AUDIT_OPTIONS_WITH_VALUE for the allowed options.
        """
        config: dict[str, Any] = load_ci_config()
        self.assertIn(RUST_AUDIT_JOB, config)
        self.assertEqual([], audit_option_problems(config[RUST_AUDIT_JOB]["script"]))

    def test_options_not_allowed_are_found(self) -> None:
        """Options that are not allowed, and allowed options with a wrong or missing value, are reported.

        Would fail if a word after ``audit`` were skipped (also a shell operator such as ``||``), or if a value
        were accepted that only starts like an allowed one.
        """
        lockfile: str = '--file "$CI_PROJECT_DIR/generated/rust/Cargo.lock"'
        audit: str = "./bin/cargo-audit audit --no-yanked"
        scripts: dict[str, list[Any]] = {
            "allowed": [
                "cd /tmp",
                f"{audit} {lockfile} --ignore RUSTSEC-2024-0001 -D warnings --deny unsound",
            ],
            "without_audit": ["cargo-audit --version"],
            "target_os": [f"{audit} {lockfile} --target-os linux"],
            "other_database": [
                f"{audit} --url https://x.example --db /tmp/db {lockfile}"
            ],
            "no_fetch_and_stale": [f"{audit} -n --no-fetch --stale {lockfile}"],
            "wrong_lockfile": [f"{audit} --file rust/Cargo.lock"],
            "short_file_option": [
                f"{audit} -f $CI_PROJECT_DIR/generated/rust/Cargo.lock"
            ],
            "longer_lockfile": [f"{audit} {lockfile}.bak"],
            "wrong_advisory_id": [
                f"{audit} {lockfile} --ignore RUSTSEC-2024-1 --ignore all"
            ],
            "wrong_deny_kind": [f"{audit} {lockfile} -D nothing"],
            "value_missing": [f"{audit} {lockfile} --ignore"],
            "result_ignored": [f"{audit} {lockfile} || true"],
        }
        self.assertEqual(
            {
                "allowed": [],
                "without_audit": ["no line runs cargo-audit audit"],
                "target_os": ["--target-os", "linux"],
                "other_database": ["--url", "https://x.example", "--db", "/tmp/db"],
                "no_fetch_and_stale": ["-n", "--no-fetch", "--stale"],
                "wrong_lockfile": ["--file rust/Cargo.lock"],
                "short_file_option": [
                    "-f",
                    "$CI_PROJECT_DIR/generated/rust/Cargo.lock",
                ],
                "longer_lockfile": [
                    "--file $CI_PROJECT_DIR/generated/rust/Cargo.lock.bak"
                ],
                "wrong_advisory_id": ["--ignore RUSTSEC-2024-1", "--ignore all"],
                "wrong_deny_kind": ["-D nothing"],
                "value_missing": ["--ignore"],
                "result_ignored": ["||", "true"],
            },
            {name: audit_option_problems(script) for name, script in scripts.items()},
        )


class AuditFilesTest(unittest.TestCase):
    """Checks the files of the repository that the Rust audit job depends on."""

    def test_repository_has_the_lockfile_and_no_audit_toml(self) -> None:
        """The repository has RUST_LOCKFILE and none of AUDIT_TOML_PATHS.

        Would fail if the lockfile were moved or deleted (the job would then fail on every run) or if someone added
        an ``audit.toml`` (the job would fail on it).
        """
        self.assertEqual([], audit_file_problems(REPO_ROOT))

    def test_missing_lockfile_and_audit_toml_are_found(self) -> None:
        """A missing lockfile, an ``audit.toml`` and a dangling symbolic link named ``audit.toml`` are found.

        Would fail if a symbolic link whose target does not exist were not counted (``Path.exists`` is false for it).
        """
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            self.assertEqual([f"{RUST_LOCKFILE} is missing"], audit_file_problems(root))
            (root / RUST_LOCKFILE).parent.mkdir(parents=True)
            (root / RUST_LOCKFILE).write_text("", encoding="utf-8")
            self.assertEqual([], audit_file_problems(root))
            (root / ".cargo").mkdir()
            (root / ".cargo/audit.toml").write_text("", encoding="utf-8")
            (root / "generated/rust/.cargo").mkdir()
            (root / "generated/rust/.cargo/audit.toml").symlink_to(root / "missing")
            self.assertEqual(
                [".cargo/audit.toml exists", "generated/rust/.cargo/audit.toml exists"],
                audit_file_problems(root),
            )


if __name__ == "__main__":
    unittest.main()
