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

"""Tests that the jobs of ``.gitlab-ci.yml`` stay out of scheduled pipelines unless they are meant to run there."""

import unittest
from pathlib import Path
from typing import Any

# pyyaml is not a declared dependency of the project: it comes with jupyter (via jupyter-events).
import yaml

# the CI configuration, found relative to this file so that the test does not depend on the working directory:
CI_CONFIG: Path = Path(__file__).resolve().parents[3] / ".gitlab-ci.yml"

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
    {"serializability_nightly", "dependency_audit", "generated_rust_check"}
)

# the rule that keeps a job out of scheduled pipelines; it must come first, as GitLab applies the first matching rule:
NOT_IN_SCHEDULE: dict[str, str] = {
    "if": "$CI_PIPELINE_SOURCE == 'schedule'",
    "when": "never",
}


class _CILoader(yaml.SafeLoader):  # pylint: disable=too-many-ancestors
    """A safe YAML loader that also reads GitLab's ``!reference`` tag (as the plain list it contains)."""


_CILoader.add_constructor(
    "!reference", lambda loader, node: loader.construct_sequence(node)
)


def load_ci_config() -> dict[str, Any]:
    """Returns the parsed ``.gitlab-ci.yml``."""
    with CI_CONFIG.open(encoding="utf-8") as file:
        # _CILoader is a SafeLoader:
        return yaml.load(file, Loader=_CILoader)  # nosec B506


def effective_rules(config: dict[str, Any], job: dict[str, Any]) -> list[Any] | None:
    """Returns the rules of a job: its own, else those of the last template it extends that has rules, else None."""
    if "rules" in job:
        return job["rules"]
    # extends names one template or a list of them; the last one with rules wins, as in GitLab:
    extends: str | list[str] = job.get("extends", [])
    templates: list[str] = [extends] if isinstance(extends, str) else extends
    for template in reversed(templates):
        if "rules" in config[template]:
            return config[template]["rules"]
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


if __name__ == "__main__":
    unittest.main()
