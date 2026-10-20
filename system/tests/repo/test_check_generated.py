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
# fixtures, so pylint's naming and docstring checks are relaxed here; this module also exceeds pylint's 1000 lines.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring,too-many-lines
"""Tests for the CI helper ``.ci/check_generated.py`` that checks the Rust code in ``generated/rust/``.

Every test builds a small repository in a temporary directory: a ``system/`` folder with Python
sources and a ``generated/rust/`` folder with generated files. It then calls ``update`` (as a
developer does right after regenerating), changes something, and calls ``check`` (or ``diff``). The real
``generated/rust/`` folder is checked by a separate CI job, not here.

``.ci`` is not an importable package, so the module is loaded from its file path.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from types import ModuleType
from unittest import mock

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
SCRIPT_PATH: Path = REPO_ROOT / ".ci" / "check_generated.py"


def load_script(path: Path = SCRIPT_PATH, name: str = "check_generated") -> ModuleType:
    """Loads ``check_generated.py`` from the given path as a module of the given name.

    The module is registered in ``sys.modules`` before it runs, as its dataclass looks itself up there.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def symlinks_work() -> bool:
    """Returns whether this system can create symbolic links (Windows may refuse without privileges)."""
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.symlink(Path(directory) / "target", Path(directory) / "link")
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


def colon_and_backslash_names_work() -> bool:
    """Returns whether this system can create files named with ':' and '\\' (Windows cannot, or means other files)."""
    names: list[str] = ["a:b.rs", "a\\b.rs"]
    with tempfile.TemporaryDirectory() as directory:
        try:
            for name in names:
                (Path(directory) / name).write_bytes(b"")
        except OSError:
            return False
        # on Windows, "a:b.rs" would write into a file "a" instead:
        return sorted(os.listdir(directory)) == sorted(names)


script: ModuleType = load_script()
SYMLINKS: bool = symlinks_work()
COLON_AND_BACKSLASH_NAMES: bool = colon_and_backslash_names_work()

# the first line of a generated file without a Python source, in Rust:
NO_SOURCE_HEADER: str = (
    "// Code generated for the Rust port (no Python source). DO NOT EDIT."
)
# what the script reports for a file without a valid first line:
NO_HEADER: str = 'the first line is not a "Code generated ... DO NOT EDIT." comment'
# the folder of the copies of the Python sources, relative to the repository root:
COPIES: str = "generated/python_sources"
# what the diff prints if no Python source changed:
NOTHING_CHANGED: str = (
    "No Python source changed since its generated files were generated."
)
# what the diff reports for a path that is not in the manifest:
UNKNOWN_PATH: str = (
    "src/nope.rs: not in the manifest (paths are relative to generated/rust/)"
)


def header(*sources: str) -> str:
    """Returns the first line of a generated Rust file that names the given Python sources."""
    return f"// Code generated from {', '.join(sources)}. DO NOT EDIT."


def digest(path: Path) -> str:
    """Returns the hash the manifest is expected to record for a file, computed independently of the script.

    The manifest records the first 16 hex digits of the SHA-256, after the prefix ``sha256:``.
    """
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def copy_name_of_file(path: Path) -> str:
    """Returns the name of the copy of a file as it is now: its hash without the prefix, plus ``.txt``."""
    return digest(path).removeprefix("sha256:") + ".txt"


def copy_name_of_text(text: str) -> str:
    """Returns the name of the copy of a source with the given text (UTF-8, LF line endings)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] + ".txt"


def old_label(source: str, text: str) -> str:
    """Returns the diff's header line of the old version of a source: its path and the name of its copy."""
    return f"--- {source} (as generated, {copy_name_of_text(text)})"


def mvcc_diff_head(old: str) -> list[str]:
    """Returns the first four lines the diff prints for ``system/stores/mvcc.py`` changed from the given old text.

    These are the heading, the header lines of the old and the new version, and the range line of a
    change within the first two lines.
    """
    return [
        "system/stores/mvcc.py: changed; generated from it: src/mvcc.rs",
        old_label("system/stores/mvcc.py", old),
        "+++ system/stores/mvcc.py (now)",
        "@@ -1,2 +1,2 @@",
    ]


# what the diff prints after system/stores/mvcc.py changed from "pass" to "x = 1":
MVCC_DIFF: list[str] = mvcc_diff_head("class MVCC:\n    pass\n") + [
    " class MVCC:",
    "-    pass",
    "+    x = 1",
]


# what the check says to do before the update records every Rust file as generated from the current sources:
REGENERATE_FIRST: str = (
    "regenerate every Rust file the check reports as out of date or edited by hand first"
)


def recovery(copy: str, source: str) -> str:
    """Returns the hint how to get a missing copy of an older version back, for the copy's path and its source."""
    return (
        f"find the commit that added it with `git log --all --diff-filter=A --format=%H -n 1 -- {copy}` and restore "
        f"it with `git checkout <commit> -- {copy}`; if git finds no commit, or the check reports the restored copy "
        f"as corrupt, delete the copy, regenerate every Rust file generated from {source} and every Rust file the "
        "check reports as out of date or edited by hand, then run the update"
    )


def missing_copy(name: str, source: str) -> str:
    """Returns the problem reported for a missing copy of an older version, with the hint how to restore it."""
    copy: str = f"{COPIES}/{name}"
    return f"{copy}: missing, the copy of {source} as recorded in the manifest; {recovery(copy, source)}"


def missing_current_copy(name: str, source: str) -> str:
    """Returns the problem reported for a missing copy of the current version of a source, which the update writes."""
    return (
        f"{COPIES}/{name}: missing, the copy of the current version of {source}; {REGENERATE_FIRST}, then run the "
        "update to write it, and commit it"
    )


def cargo_changed(path: str) -> str:
    """Returns the problem ``update`` reports for a Cargo file that differs from its entry in the manifest."""
    return (
        f"{path}: differs from the manifest (changed, added or deleted); a regeneration keeps the Cargo files, "
        "and a change of them is decided by a person and recorded with --update-dependencies before the update"
    )


def corrupt_copy(name: str) -> str:
    """Returns the problem reported for a copy whose content does not match its name: delete it, then see the check."""
    return (
        f"{COPIES}/{name}: corrupt, its content does not match its name; delete it, and if the manifest still records "
        "its version, the check says how to get it back"
    )


class GeneratedRepositoryTest(unittest.TestCase):
    """Base class: a temporary repository root with one Python source and one Rust file generated from it."""

    def setUp(self) -> None:
        """Creates ``system/stores/mvcc.py`` and ``generated/rust/src/mvcc.rs`` generated from it.

        The repository root is a folder inside the temporary directory, so a test can place a file
        outside the repository without leaving the temporary directory.
        """
        directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(directory.cleanup)
        self.root: Path = Path(directory.name) / "repo"
        self.generated: Path = self.root / "generated" / "rust"
        self.manifest_path: Path = self.generated / "GENERATED_FROM.json"
        self.write("system/stores/mvcc.py", "class MVCC:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs", header("system/stores/mvcc.py") + "\npub struct Mvcc;\n"
        )

    def write(self, path: str, text: str) -> None:
        """Writes a file relative to the repository root, creating its folders.

        The text is written as UTF-8 bytes, so its line endings stay LF also on Windows.
        """
        target: Path = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def write_generated(self, path: str, text: str) -> None:
        """Writes a file relative to the generated folder, creating its folders."""
        self.write(f"generated/rust/{path}", text)

    def append_generated(self, path: str, text: str) -> None:
        """Appends text to a generated file, as a hand edit would."""
        target: Path = self.generated / path
        target.write_bytes(target.read_bytes() + text.encode("utf-8"))

    def manifest(self) -> dict:
        """Returns the manifest as it is on disk."""
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def recorded_paths(self) -> list[str]:
        """Returns the paths of the files recorded in the manifest, in their order."""
        return [entry["path"] for entry in self.manifest()["files"]]

    def recorded(self, path: str) -> dict:
        """Returns the manifest entry of a generated file."""
        entries: list[dict] = [
            entry for entry in self.manifest()["files"] if entry["path"] == path
        ]
        self.assertEqual(1, len(entries), f"{path} is not recorded exactly once")
        return entries[0]

    def update_cleanly(self) -> None:
        """Runs ``update`` and asserts it wrote the manifest without problems."""
        self.assertEqual([], script.update(self.root))

    def mark_manifest(self) -> bytes:
        """Adds a top-level key the script never writes to the manifest and returns the manifest's bytes.

        A refused update must leave these bytes as they are; a rewrite writes only ``files``, so the
        key would be gone even if the files recorded are the same (the reader ignores unknown keys).
        """
        manifest: dict = self.manifest()
        manifest["marker"] = "marker of the manifest before"
        self.write_generated("GENERATED_FROM.json", json.dumps(manifest, indent=2))
        return self.manifest_path.read_bytes()

    def copies(self) -> dict[str, bytes]:
        """Returns the entries of the folder of the copies, by name, with the bytes of each file."""
        return {
            entry.name: entry.read_bytes() if entry.is_file() else b""
            for entry in (self.root / COPIES).iterdir()
        }


class UpToDateTest(GeneratedRepositoryTest):
    """Checks that a freshly updated manifest makes the check pass, and the format of the manifest."""

    def test_check_passes_right_after_update(self) -> None:
        """After ``update``, ``check`` reports nothing.

        Would fail if ``update`` recorded different hashes than ``check`` computes, so the CI job
        would report every file right after regenerating.
        """
        self.update_cleanly()
        self.assertEqual([], script.check(self.root))

    def test_windows_line_endings_do_not_count_as_a_change(self) -> None:
        """A source and a generated file whose LF line endings became CR LF still pass the check.

        Would fail if the raw bytes were hashed, so a Windows checkout that converts line endings
        reported every file as out of date or edited by hand.
        """
        self.update_cleanly()
        # turn the LF line endings of the source and of the generated file into CR LF, as a Windows checkout may do:
        for path in [
            self.root / "system/stores/mvcc.py",
            self.generated / "src/mvcc.rs",
        ]:
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        # line endings are made LF before hashing, so the check still finds nothing:
        self.assertEqual([], script.check(self.root))

    def test_update_records_prefixed_hashes_with_the_path_last(self) -> None:
        """Each entry records ``sha256:``-prefixed hashes of the file and its sources, with the path last.

        Would fail if a hash were not the start of the SHA-256 of the bytes, lost its prefix, or came
        after a path, where the secret scanner gitleaks takes it for an API key.
        """
        self.update_cleanly()
        entry: dict = self.recorded("src/mvcc.rs")
        # the entry holds the prefixed hashes of the generated file and of its source, as digest() computes them:
        self.assertEqual(
            {
                "sha256": digest(self.generated / "src/mvcc.rs"),
                "sources": [
                    {
                        "sha256": digest(self.root / "system/stores/mvcc.py"),
                        "path": "system/stores/mvcc.py",
                    }
                ],
                "path": "src/mvcc.rs",
            },
            entry,
        )
        # the keys come in this order, with the path last, both in the entry and in its source:
        self.assertEqual(["sha256", "sources", "path"], list(entry))
        self.assertEqual(["sha256", "path"], list(entry["sources"][0]))

    def test_commit_field_is_accepted_and_dropped_by_a_rewrite(self) -> None:
        """A manifest with a ``generated_at_commit`` field, which the script does not write, passes the check.

        Both updates then write only ``files``.

        Would fail if the reader refused such a manifest, or if ``update`` or ``update_dependencies``
        wrote the field or kept it from the manifest before.
        """
        self.update_cleanly()
        for name, rewrite in [
            ("update", script.update),
            ("update_dependencies", script.update_dependencies),
        ]:
            with self.subTest(name):
                # add the field to the manifest; check accepts the manifest as it is:
                manifest: dict = self.manifest()
                manifest["generated_at_commit"] = "abc1234"
                self.write_generated(
                    "GENERATED_FROM.json", json.dumps(manifest, indent=2)
                )
                self.assertEqual([], script.check(self.root))
                # the rewrite succeeds and leaves only "files" in the manifest:
                self.assertEqual([], rewrite(self.root))
                self.assertEqual(["files"], list(self.manifest()))


class ManifestReadTest(GeneratedRepositoryTest):
    """Checks that a missing or unreadable manifest is reported instead of making the check crash."""

    def test_missing_manifest_is_reported(self) -> None:
        """Without a manifest, ``check`` reports it missing.

        Would fail if ``check`` crashed on the missing file or silently passed.
        """
        self.assertEqual(
            ["generated/rust/GENERATED_FROM.json is missing"], script.check(self.root)
        )

    def test_corrupt_manifest_is_reported(self) -> None:
        """A manifest that is not JSON is reported as unreadable.

        Would fail if the ``json`` error escaped from ``check``, so the CI job showed a traceback.
        """
        # write a manifest that breaks off in the middle, so it is not valid JSON:
        self.write_generated("GENERATED_FROM.json", '{"files": [')
        # check reports one problem: the manifest cannot be read, with the error and the hint to run the update:
        problems: list[str] = script.check(self.root)
        self.assertEqual(1, len(problems))
        self.assertTrue(
            problems[0].startswith(
                "generated/rust/GENERATED_FROM.json cannot be read ("
            ),
            problems[0],
        )
        self.assertTrue(
            problems[0].endswith("); run the update after regenerating"), problems[0]
        )

    def test_manifest_of_another_shape_is_reported(self) -> None:
        """A manifest without ``files``, in the older format, or with an incomplete or wrongly typed entry is reported
        as unreadable.

        Would fail if a ``KeyError`` or ``TypeError`` escaped from ``check`` for a manifest written
        by an older version of the script or edited by hand. The entries that lack a field otherwise
        match the files on disk, so the missing field is the only thing wrong with them.
        """
        # a source and the hash of the generated file as the update records them, to fill the entries below:
        source: dict[str, str] = {
            "sha256": digest(self.root / "system/stores/mvcc.py"),
            "path": "system/stores/mvcc.py",
        }
        file_digest: str = digest(self.generated / "src/mvcc.rs")

        def manifest_with(entry: dict) -> str:
            """Returns a manifest whose only entry is the given one."""
            return json.dumps({"files": [entry]})

        # each manifest with the start of the error it is reported with: no "files"; the older format, where "files" is
        # a dictionary by path; an entry without "sources"; one without its own hash; one whose source has no hash; one
        # whose own hash is no string:
        expected: dict[str, str] = {
            "{}": "KeyError('files')",
            json.dumps(
                {"files": {"src/mvcc.rs": {"sources": {}, "sha256": "abc"}}}
            ): "TypeError(",
            manifest_with({"sha256": file_digest, "path": "src/mvcc.rs"}): (
                "KeyError('sources')"
            ),
            manifest_with({"sources": [source], "path": "src/mvcc.rs"}): (
                "KeyError('sha256')"
            ),
            manifest_with(
                {
                    "sha256": file_digest,
                    "sources": [{"path": "system/stores/mvcc.py"}],
                    "path": "src/mvcc.rs",
                }
            ): "KeyError('sha256')",
            manifest_with({"sha256": 123, "sources": [], "path": "src/mvcc.rs"}): (
                "TypeError("
            ),
        }
        # write each manifest in turn; check reports only that the manifest cannot be read, with the expected error:
        for text, error in expected.items():
            with self.subTest(manifest=text):
                self.write_generated("GENERATED_FROM.json", text)
                problems: list[str] = script.check(self.root)
                self.assertEqual(1, len(problems))
                self.assertTrue(
                    problems[0].startswith(
                        f"generated/rust/GENERATED_FROM.json cannot be read ({error}"
                    ),
                    problems[0],
                )

    def test_source_hash_that_is_no_hash_is_reported(self) -> None:
        """A source hash that is not ``sha256:`` and 16 hex digits makes the manifest unreadable, for check and diff.

        The hash of a source is also the name of its copy. Would fail if any string were accepted,
        which would let ``sha256:../../x`` make ``--diff`` read a file outside the folder of the copies.
        """
        self.update_cleanly()
        # hashes that are not valid: one that leads out of the folder of the copies, one without the prefix, one with
        # upper case digits, one with 17 digits:
        for invalid in [
            "sha256:../../x",
            "0123456789abcdef",
            "sha256:0123456789ABCDEF",
            "sha256:0123456789abcdef0",
        ]:
            with self.subTest(sha256=invalid):
                # put the invalid hash into the only source of the only entry:
                manifest: dict = self.manifest()
                manifest["files"][0]["sources"][0]["sha256"] = invalid
                self.write_generated("GENERATED_FROM.json", json.dumps(manifest))
                # check reports the manifest as unreadable, as the hash is not valid:
                problems: list[str] = script.check(self.root)
                self.assertEqual(1, len(problems))
                self.assertTrue(
                    problems[0].startswith(
                        "generated/rust/GENERATED_FROM.json cannot be read (ValueError("
                    ),
                    problems[0],
                )
                self.assertIn("has no valid hash", problems[0])
                # diff shows nothing and gives the same problem as its only error:
                self.assertEqual(([], problems), script.diff(self.root, []))

    def test_entry_path_outside_the_generated_folder_is_reported(self) -> None:
        """An entry path that is empty, absolute or has a backslash, colon or ``..`` part makes the manifest unreadable.

        The paths of the manifest lead into the generated folder. Would fail if any string were
        accepted as a path, so an edited manifest could name a file outside the generated folder
        (or, with a backslash or a drive such as ``C:``, one that means another folder on Windows;
        ``C:x.rs`` is no absolute path on Linux or macOS, so only the colon gives it away there).
        """
        self.update_cleanly()
        # paths that are not valid: empty, absolute, leading out with "..", with a backslash, with a drive and a colon:
        for invalid in ["", "/abs/x.rs", "../x.rs", "src\\x.rs", "C:x.rs"]:
            with self.subTest(path=invalid):
                # put the invalid path into the only entry:
                manifest: dict = self.manifest()
                manifest["files"][0]["path"] = invalid
                self.write_generated("GENERATED_FROM.json", json.dumps(manifest))
                # check reports the manifest as unreadable, as the path is not valid, and diff gives the same error:
                problems: list[str] = script.check(self.root)
                self.assertEqual(1, len(problems))
                self.assertTrue(
                    problems[0].startswith(
                        "generated/rust/GENERATED_FROM.json cannot be read (ValueError("
                    ),
                    problems[0],
                )
                self.assertIn("has no valid path", problems[0])
                self.assertEqual(([], problems), script.diff(self.root, []))

    def test_entry_path_starting_with_a_slash_is_reported_also_under_windows_rules(
        self,
    ) -> None:
        """An entry path ``/abs/x.rs`` makes the manifest unreadable also where paths follow Windows rules.

        Windows takes ``/abs/x.rs`` for a path relative to the current drive, not for an absolute
        one, yet joined to the repository root it leads out of it. Windows rules are simulated by
        reading the manifest with ``Path`` replaced by ``PureWindowsPath``. Would fail if only the
        system's own rules were asked whether the path is absolute, so the manifest were accepted
        on Windows.
        """
        self.update_cleanly()
        # record the path /abs/x.rs for the only entry:
        manifest: dict = self.manifest()
        manifest["files"][0]["path"] = "/abs/x.rs"
        self.write_generated("GENERATED_FROM.json", json.dumps(manifest))
        # read the manifest with Windows path rules: it is refused, as the path is not valid:
        with mock.patch.object(script, "Path", PureWindowsPath):
            recorded, problem = script.read_manifest(self.root)
        self.assertIsNone(recorded)
        self.assertIn("has no valid path", str(problem))

    def test_entry_path_that_appears_twice_is_reported(self) -> None:
        """Two entries with the same path make the manifest unreadable, for check and diff.

        The second entry records another source hash, so it is not a harmless repetition. Would
        fail if the entries were read into a dictionary by path without a check, so the last one
        silently replaced the first and the check compared the file with only one of them.
        """
        self.update_cleanly()
        # add a twin of the only entry with another source hash, so its path appears twice:
        manifest: dict = self.manifest()
        twin: dict = json.loads(json.dumps(manifest["files"][0]))
        twin["sources"][0]["sha256"] = "sha256:0123456789abcdef"
        manifest["files"].append(twin)
        self.write_generated("GENERATED_FROM.json", json.dumps(manifest))
        # check and diff both report that the manifest cannot be read:
        problem: str = (
            "generated/rust/GENERATED_FROM.json cannot be read "
            '(ValueError("an entry\'s path appears twice")); run the update after regenerating'
        )
        self.assertEqual([problem], script.check(self.root))
        self.assertEqual(([], [problem]), script.diff(self.root, []))


class OutOfDateTest(GeneratedRepositoryTest):
    """Checks that a changed Python source makes its generated files out of date."""

    def test_changed_source_is_reported_by_name(self) -> None:
        """A Python source changed after generating makes the file out of date, naming the source.

        Would fail if the source hashes were not compared, so stale Rust code would pass the check.
        """
        self.update_cleanly()
        # change the source after the update; check reports the generated file as out of date, naming the source:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            [
                "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
                "regenerate it and run the update"
            ],
            script.check(self.root),
        )

    def test_only_the_changed_one_of_two_sources_is_named(self) -> None:
        """For a file generated from two sources of which only the second changed, only that one is named.

        Would fail if the header's source list were split wrongly (e.g. without stripping the space
        after the comma), or if all sources were named instead of the changed one.
        """
        # generate src/mvcc.rs from two sources, mvcc.py and versioned.py:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Mvcc;\n",
        )
        self.update_cleanly()
        # change only the second source after the update; check names only that one:
        self.write("system/stores/versioned.py", "class Versioned:\n    x = 1\n")
        self.assertEqual(
            [
                "src/mvcc.rs: out of date, system/stores/versioned.py changed since it was generated; "
                "regenerate it and run the update"
            ],
            script.check(self.root),
        )

    def test_dropped_source_is_reported_by_name(self) -> None:
        """A file whose header no longer names one of its unchanged sources is out of date, naming it.

        Would fail if only the sources still listed were compared, so dropping a source from the
        header would go unnoticed.
        """
        # generate src/mvcc.rs from two sources, mvcc.py and versioned.py:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Mvcc;\n",
        )
        self.update_cleanly()
        # after the update, drop versioned.py from the first line, while both sources stay unchanged:
        self.write_generated(
            "src/mvcc.rs", header("system/stores/mvcc.py") + "\npub struct Mvcc;\n"
        )
        # check reports the file as out of date, naming the dropped source:
        self.assertEqual(
            [
                "src/mvcc.rs: out of date, its list of sources (system/stores/versioned.py dropped) "
                "changed since it was generated; regenerate it and run the update"
            ],
            script.check(self.root),
        )


class HandEditTest(GeneratedRepositoryTest):
    """Checks that a generated file changed without a change of its sources counts as edited by hand."""

    def test_hand_edit_is_reported(self) -> None:
        """A generated file that changed while its source did not is reported as edited by hand.

        Would fail if the file's own hash were not compared with the manifest.
        """
        self.update_cleanly()
        # append a line to the generated file after the update, while its source stays unchanged:
        self.append_generated("src/mvcc.rs", "pub fn patched() {}\n")
        self.assertEqual(
            [
                "src/mvcc.rs: edited by hand; change the Python source and regenerate instead"
            ],
            script.check(self.root),
        )

    def test_hand_edit_of_a_file_without_python_source_is_reported(self) -> None:
        """A file with the "no Python source" header is still tracked, so its hand edit is reported.

        Would fail if files without sources were left out of the manifest or the comparison.
        """
        # add a generated file without a Python source; the update records it with an empty list of sources:
        self.write_generated("src/lib.rs", NO_SOURCE_HEADER + "\npub mod mvcc;\n")
        self.update_cleanly()
        self.assertEqual([], self.recorded("src/lib.rs")["sources"])
        # edit it by hand; check reports it:
        self.append_generated("src/lib.rs", "pub mod extra;\n")
        self.assertEqual(
            [
                "src/lib.rs: edited by hand; change the Python source and regenerate instead"
            ],
            script.check(self.root),
        )


class HeaderTest(GeneratedRepositoryTest):
    """Checks the first line every generated file must carry."""

    def assert_rejected(self, cases: dict[str, str]) -> None:
        """Asserts that ``update`` rejects each file (by path) with the given first line, one at a time."""
        for path, first_line in cases.items():
            with self.subTest(path=path, first_line=first_line):
                self.write_generated(path, first_line + "\ncontent\n")
                try:
                    self.assertEqual([f"{path}: {NO_HEADER}"], script.update(self.root))
                finally:
                    # the next case starts from the valid files only:
                    (self.generated / path).unlink()

    def test_missing_first_line_is_reported(self) -> None:
        """A generated file whose first line is ordinary code is reported.

        Would fail if the header pattern matched any first line, or files without it were skipped.
        """
        self.update_cleanly()
        self.write_generated("src/mvcc.rs", "pub struct Mvcc;\n")
        self.assertEqual([f"src/mvcc.rs: {NO_HEADER}"], script.check(self.root))

    def test_wrong_first_line_is_reported(self) -> None:
        """A first line that is a comment but lacks "DO NOT EDIT." is reported.

        Would fail if "DO NOT EDIT." became optional in the pattern.
        """
        self.update_cleanly()
        self.write_generated(
            "src/mvcc.rs",
            "// Code generated from system/stores/mvcc.py.\npub struct Mvcc;\n",
        )
        self.assertEqual([f"src/mvcc.rs: {NO_HEADER}"], script.check(self.root))

    def test_text_after_the_header_is_reported(self) -> None:
        """A first line with more text after "DO NOT EDIT." is reported.

        Would fail if the pattern were not anchored at the end of the line, accepting e.g. a remark
        that invites editing the file after all.
        """
        self.assert_rejected(
            {"src/lib.rs": NO_SOURCE_HEADER + " Except for this line."}
        )

    def test_empty_file_is_reported(self) -> None:
        """An empty generated file is reported as lacking the first line.

        Would fail if the empty file made the script crash on reading its first line.
        """
        self.update_cleanly()
        self.write_generated("src/mvcc.rs", "")
        self.assertEqual([f"src/mvcc.rs: {NO_HEADER}"], script.check(self.root))

    def test_missing_source_is_reported(self) -> None:
        """A source named in the first line that does not exist is reported.

        Would fail if the script hashed only existing sources, so a renamed Python module would
        silently drop out of the check.
        """
        self.update_cleanly()
        self.write_generated(
            "src/mvcc.rs", header("system/stores/renamed.py") + "\npub struct Mvcc;\n"
        )
        self.assertEqual(
            ["src/mvcc.rs: its source system/stores/renamed.py does not exist"],
            script.check(self.root),
        )

    def test_toml_and_markdown_headers_are_accepted(self) -> None:
        """A ``#`` header in TOML and a ``<!-- ... -->`` header in Markdown are accepted.

        Would fail if the pattern only knew the ``//`` comment of Rust.
        """
        # add a TOML file without a Python source and a Markdown
        # file generated from mvcc.py, each with its kind of comment:
        self.write_generated(
            "Cargo.toml",
            "# Code generated for the Rust port (no Python source). DO NOT EDIT.\n"
            '[package]\nname = "explaindb"\n',
        )
        self.write_generated(
            "README.md",
            "<!-- Code generated from system/stores/mvcc.py. DO NOT EDIT. -->\n# Title\n",
        )
        self.update_cleanly()
        # the update records the sources each first line names, and check passes:
        self.assertEqual([], self.recorded("Cargo.toml")["sources"])
        self.assertEqual(
            ["system/stores/mvcc.py"],
            [source["path"] for source in self.recorded("README.md")["sources"]],
        )
        self.assertEqual([], script.check(self.root))

    def test_comment_must_be_closed_exactly_in_markdown(self) -> None:
        """``<!--`` needs the closing ``-->``, while ``//`` and ``#`` must not end with it.

        Would fail if the closing ``-->`` stayed optional for every kind of comment, accepting an
        unclosed Markdown comment or a Rust or TOML line with a stray ``-->``.
        """
        self.assert_rejected(
            {
                "README.md": "<!-- Code generated from system/stores/mvcc.py. DO NOT EDIT.",
                "src/lib.rs": NO_SOURCE_HEADER + " -->",
                "Cargo.toml": "# Code generated for the Rust port (no Python source). DO NOT EDIT. -->",
            }
        )

    def test_comment_must_fit_the_file_extension(self) -> None:
        """A ``.rs`` file needs ``//``, a ``.toml`` file ``#`` and a ``.md`` file ``<!-- ... -->``.

        Would fail if any of the three comments were accepted in any file, e.g. a ``#`` line in Rust,
        which does not even compile.
        """
        self.assert_rejected(
            {
                "src/lib.rs": "# Code generated for the Rust port (no Python source). DO NOT EDIT.",
                "Cargo.toml": "// Code generated for the Rust port (no Python source). DO NOT EDIT.",
                "README.md": NO_SOURCE_HEADER,
            }
        )

    def test_source_with_other_case_does_not_exist(self) -> None:
        """A source named ``MVCC.py`` in the header does not exist if the file is ``mvcc.py``, on every OS.

        Would fail if the existence check followed the file system, which ignores case on macOS, so
        the check passed locally but failed in the Linux CI.
        """
        self.update_cleanly()
        # after the update, name the source with upper case letters, while the file on disk is mvcc.py:
        self.write_generated(
            "src/mvcc.rs", header("system/stores/MVCC.py") + "\npub struct Mvcc;\n"
        )
        self.assertEqual(
            ["src/mvcc.rs: its source system/stores/MVCC.py does not exist"],
            script.check(self.root),
        )

    def test_source_outside_system_is_reported(self) -> None:
        """A source that is not in ``system/`` or whose path contains ``..`` is reported, even if the file exists.

        ``..`` is refused even where it stays inside ``system/``, as in ``system/../system/...``.
        Would fail if any existing file could serve as a source, e.g. one outside the repository
        reached through ``system/../../``.
        """
        # a Python file that exists, but in docs/ instead of system/:
        self.write("docs/notes.py", "x = 1\n")
        # outside the repository root, but still inside the temporary directory:
        (self.root.parent / "outside.py").write_bytes(b"x = 1\n")
        # name each source in turn: one outside system/, one that leaves system/ through ".." and comes back, and one
        # outside the repository; the update refuses each as not in system/:
        for source in [
            "docs/notes.py",
            "system/../system/stores/mvcc.py",
            "system/../../outside.py",
        ]:
            with self.subTest(source=source):
                self.write_generated(
                    "src/mvcc.rs", header(source) + "\npub struct Mvcc;\n"
                )
                self.assertEqual(
                    [f"src/mvcc.rs: its source {source} is not in system/"],
                    script.update(self.root),
                )

    def test_source_with_a_nul_character_is_reported_as_outside_system(self) -> None:
        """A source with a NUL character in the first line is reported as not in ``system/``, by check and diff.

        No file in ``system/`` has a NUL character in its name. Would fail if the path were resolved
        on disk, which raises ``ValueError`` for a NUL character, so check and ``--diff`` would crash
        with a traceback instead of naming the file to fix.
        """
        self.update_cleanly()
        # add a second source with a NUL character in its name to the first line:
        source: str = "system/stores/mvcc\0.py"
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", source) + "\npub struct Mvcc;\n",
        )
        # check and diff both report it as not in system/:
        problem: str = f"src/mvcc.rs: its source {source} is not in system/"
        self.assertEqual([problem], script.check(self.root))
        self.assertEqual(([], [problem]), script.diff(self.root, []))

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_source_linked_to_outside_system_is_reported(self) -> None:
        """A source in ``system/`` that is a symbolic link to a file outside ``system/`` is reported.

        Would fail if only the spelling of the path were checked, so a link could make any file of
        the machine a source.
        """
        # a file outside system/ and a link in system/stores/ that points to it:
        self.write("outside.py", "x = 1\n")
        os.symlink(self.root / "outside.py", self.root / "system/stores/link.py")
        # name the link as the source; the update refuses it as not in system/:
        self.write_generated(
            "src/mvcc.rs", header("system/stores/link.py") + "\npub struct Mvcc;\n"
        )
        self.assertEqual(
            ["src/mvcc.rs: its source system/stores/link.py is not in system/"],
            script.update(self.root),
        )

    def test_file_that_is_not_utf8_is_reported(self) -> None:
        """A generated file that is not UTF-8 text is reported instead of making the script crash.

        Would fail if reading the first line raised ``UnicodeDecodeError`` out of ``check``, so the
        CI job showed a traceback instead of the file to fix.
        """
        self.update_cleanly()
        (self.generated / "src/data.bin").write_bytes(b"\xff\xfe\x00binary")
        self.assertEqual(
            [
                "src/data.bin: not a UTF-8 text file, so it cannot carry the first line",
            ],
            script.check(self.root),
        )


class CargoLockTest(GeneratedRepositoryTest):
    """Checks ``Cargo.lock``, which Cargo writes without a first line."""

    def test_cargo_lock_needs_no_first_line(self) -> None:
        """``Cargo.lock`` without a "Code generated" line is accepted and recorded without sources.

        Would fail if ``Cargo.lock`` were no longer exempt from the header, so every update would be refused.
        """
        self.write_generated("Cargo.lock", "version = 4\n")
        self.update_cleanly()
        self.assertEqual([], self.recorded("Cargo.lock")["sources"])
        self.assertEqual([], script.check(self.root))

    def test_hand_edit_of_cargo_lock_is_reported(self) -> None:
        """A change of ``Cargo.lock`` after the update is reported as edited by hand.

        Would fail if the exemption from the header also left ``Cargo.lock`` out of the manifest.
        """
        self.write_generated("Cargo.lock", "version = 4\n")
        self.update_cleanly()
        self.append_generated("Cargo.lock", '[[package]]\nname = "rand"\n')
        self.assertEqual(
            [
                "Cargo.lock: edited by hand; change the Python source and regenerate instead"
            ],
            script.check(self.root),
        )


class ManifestCoverageTest(GeneratedRepositoryTest):
    """Checks which files are recorded, and that the files on disk and in the manifest are the same."""

    def test_file_not_in_manifest_is_reported(self) -> None:
        """A generated file added after the update is reported as not in the manifest.

        Would fail if new files were only checked for their header and never matched against the manifest.
        """
        self.update_cleanly()
        self.write_generated("src/lib.rs", NO_SOURCE_HEADER + "\npub mod mvcc;\n")
        self.assertEqual(["src/lib.rs: not in the manifest"], script.check(self.root))

    def test_deleted_file_is_reported(self) -> None:
        """A file in the manifest that was deleted is reported as not on disk.

        Would fail if only the files on disk were compared with the manifest, never the other way round.
        """
        self.update_cleanly()
        (self.generated / "src/mvcc.rs").unlink()
        self.assertEqual(
            ["src/mvcc.rs: in the manifest, but not on disk"], script.check(self.root)
        )

    def test_build_folder_and_manifest_are_ignored(self) -> None:
        """Files under the top-level ``target/`` and the manifest itself are neither recorded nor checked.

        Would fail if Cargo's build output (which has no header) were treated as generated code, or
        the manifest tried to record its own hash.
        """
        # a build log in Cargo's build folder target/; the update does not record it:
        self.write_generated("target/debug/build.log", "compiled\n")
        self.update_cleanly()
        self.assertEqual(["src/mvcc.rs"], self.recorded_paths())
        # change and add files in target/; check still passes:
        self.write_generated("target/debug/build.log", "compiled again\n")
        self.write_generated("target/release/libexplaindb.rlib", "binary\n")
        self.assertEqual([], script.check(self.root))

    def test_nested_target_folder_is_generated_code(self) -> None:
        """A folder named ``target`` below ``src/`` is generated code like any other, so it is recorded.

        Would fail if every folder named ``target`` were left out, not only Cargo's build folder at the
        top, so generated code in such a folder escaped the check.
        """
        self.write_generated("src/target/plan.rs", NO_SOURCE_HEADER + "\n")
        self.update_cleanly()
        self.assertEqual(["src/mvcc.rs", "src/target/plan.rs"], self.recorded_paths())

    def test_hidden_files_and_folders_are_ignored(self) -> None:
        """Hidden files and folders such as ``.DS_Store`` or ``.idea/`` are neither recorded nor checked.

        Would fail if the files that macOS or an IDE put next to the code made ``update`` refuse for a
        missing first line.
        """
        # hidden files at the top, in src/ and in a hidden folder:
        self.write_generated(".DS_Store", "finder\n")
        self.write_generated("src/.DS_Store", "finder\n")
        self.write_generated(".idea/workspace.xml", "<project/>\n")
        # the update records only the generated Rust file, and check passes:
        self.update_cleanly()
        self.assertEqual(["src/mvcc.rs"], self.recorded_paths())
        self.assertEqual([], script.check(self.root))


class ModuleTest(GeneratedRepositoryTest):
    """Checks that each test folder's ``main.rs`` includes all test files of its folder."""

    def setUp(self) -> None:
        """Adds the test folder ``tests/stores/`` whose ``main.rs`` includes ``test_basics.rs``."""
        super().setUp()
        self.write_generated(
            "tests/stores/main.rs", NO_SOURCE_HEADER + "\nmod test_basics;\n"
        )
        self.write_generated(
            "tests/stores/test_basics.rs", header("system/stores/mvcc.py") + "\n"
        )

    def test_included_test_file_is_accepted(self) -> None:
        """A test file that ``main.rs`` includes as a module is accepted.

        Would fail if the ``mod`` lines of ``main.rs`` were not read, so every test file were reported.
        """
        self.update_cleanly()
        self.assertEqual([], script.check(self.root))

    def test_test_file_not_included_is_reported(self) -> None:
        """A test file that ``main.rs`` does not include is reported, and ``update`` refuses.

        Would fail if the check did not look at ``main.rs``, so Cargo silently left the file's tests out.
        """
        self.write_generated(
            "tests/stores/test_extra.rs", header("system/stores/mvcc.py") + "\n"
        )
        self.assertEqual(
            [
                "tests/stores/test_extra.rs: not included as a module by tests/stores/main.rs"
            ],
            script.update(self.root),
        )

    def test_block_comment_start_in_a_line_comment_is_ignored(self) -> None:
        """A ``/*`` inside a ``//`` comment opens no block comment, so the module on the next line counts.

        Would fail if a ``//`` comment were not skipped to its end, so its ``/*`` swallowed the rest
        of ``main.rs`` and every module after it were reported as not included.
        """
        self.write_generated(
            "tests/stores/main.rs",
            NO_SOURCE_HEADER + "\n// see /* here\nmod test_basics;\n",
        )
        self.update_cleanly()

    def test_public_modules_count_as_included(self) -> None:
        """``pub mod x;`` and ``pub(crate) mod x;`` include a test file just like ``mod x;``.

        Would fail if only a bare ``mod`` were recognised, reporting test files that Cargo does compile.
        """
        # main.rs includes one test file with "pub mod" and another with "pub(crate) mod":
        self.write_generated(
            "tests/stores/main.rs",
            NO_SOURCE_HEADER + "\npub mod test_basics;\npub(crate) mod test_extra;\n",
        )
        # add the second test file; the update accepts both:
        self.write_generated(
            "tests/stores/test_extra.rs", header("system/stores/mvcc.py") + "\n"
        )
        self.update_cleanly()

    def test_modules_in_comments_do_not_count(self) -> None:
        """A ``mod x;`` inside a ``//`` or ``/* ... */`` comment, also a nested one, does not include the test file.

        Would fail if comments were not removed before looking for modules, or if a nested block
        comment ended at its first ``*/``, so a commented-out test file, which Cargo does not compile,
        would count as included.
        """
        # main.rs includes test_basics, and names four more modules only in comments: in a line comment, in a block
        # comment on one line, in one over several lines, and in a nested one:
        self.write_generated(
            "tests/stores/main.rs",
            NO_SOURCE_HEADER
            + "\nmod test_basics;\n// mod test_line;\n/* mod test_block; */\n"
            "/*\nmod test_lines;\n*/\n"
            "/* outer /* inner */ mod test_nested; */\n",
        )
        # add the four test files:
        for name in ["test_line", "test_block", "test_lines", "test_nested"]:
            self.write_generated(
                f"tests/stores/{name}.rs", header("system/stores/mvcc.py") + "\n"
            )
        # the update refuses each of them as not included, in the order of their paths:
        self.assertEqual(
            [
                f"tests/stores/{name}.rs: not included as a module by tests/stores/main.rs"
                for name in ["test_block", "test_line", "test_lines", "test_nested"]
            ],
            script.update(self.root),
        )

    def test_test_folder_without_main_is_reported(self) -> None:
        """A folder in ``tests/`` with test files but no ``main.rs`` is reported.

        Would fail if only folders with a ``main.rs`` were looked at, so Cargo silently built none of
        the folder's tests.
        """
        self.write_generated(
            "tests/queries/test_select.rs", header("system/stores/mvcc.py") + "\n"
        )
        self.assertEqual(
            [
                "tests/queries/: a test folder without main.rs; Cargo would not build its tests"
            ],
            script.update(self.root),
        )

    def test_folder_with_only_mod_rs_needs_no_main(self) -> None:
        """A folder in ``tests/`` holding only a shared ``mod.rs`` (like ``tests/common/``) is accepted.

        Would fail if every folder in ``tests/`` needed a ``main.rs``, including the shared helpers
        that the test programs include with ``mod common;``.
        """
        self.write_generated("tests/common/mod.rs", NO_SOURCE_HEADER + "\n")
        self.update_cleanly()

    def test_folder_with_mod_rs_and_a_file_that_is_not_rust_needs_no_main(
        self,
    ) -> None:
        """A folder in ``tests/`` with a ``mod.rs`` and a file that is not Rust (a README) is accepted.

        Would fail if every file counted as a test file, although Cargo only compiles ``.rs`` files.
        """
        self.write_generated("tests/common/mod.rs", NO_SOURCE_HEADER + "\n")
        self.write_generated(
            "tests/common/README.md",
            "<!-- Code generated for the Rust port (no Python source). DO NOT EDIT. -->\n",
        )
        self.update_cleanly()

    def test_folder_with_mod_rs_and_a_test_file_needs_main(self) -> None:
        """A folder in ``tests/`` with a ``mod.rs`` and a test file but no ``main.rs`` is reported.

        Would fail if any folder with a ``mod.rs`` were exempt, so the test file next to it was never built.
        """
        # a shared mod.rs and a test file next to it, without main.rs:
        self.write_generated("tests/common/mod.rs", NO_SOURCE_HEADER + "\n")
        self.write_generated(
            "tests/common/test_helpers.rs", header("system/stores/mvcc.py") + "\n"
        )
        self.assertEqual(
            [
                "tests/common/: a test folder without main.rs; Cargo would not build its tests"
            ],
            script.update(self.root),
        )

    def test_main_outside_a_test_folder_is_not_module_checked(self) -> None:
        """A ``main.rs`` that is not in a folder ``tests/<folder>/`` does not have to include its neighbours.

        Would fail if every ``main.rs`` were treated as a test program, e.g. ``src/main.rs``, whose
        neighbours are included by the crate root instead.
        """
        self.write_generated("src/main.rs", NO_SOURCE_HEADER + "\nfn main() {}\n")
        self.write_generated("src/other.rs", NO_SOURCE_HEADER + "\n")
        self.update_cleanly()

    def test_main_that_is_not_utf8_is_reported_once(self) -> None:
        """A ``main.rs`` that is not UTF-8 text is reported only as such, without a crash.

        Would fail if the module check read ``main.rs`` again and raised ``UnicodeDecodeError``.
        """
        (self.generated / "tests/stores/main.rs").write_bytes(
            b"\xff\xfe mod test_basics;\n"
        )
        self.assertEqual(
            [
                "tests/stores/main.rs: not a UTF-8 text file, so it cannot carry the first line"
            ],
            script.update(self.root),
        )


class ToolSettingsTest(GeneratedRepositoryTest):
    """Checks that the generated folder has no hidden tool settings: ``.cargo``, ``.rustfmt.toml``, ``.clippy.toml``."""

    def problem(self, name: str) -> str:
        """Returns what the script reports for hidden tool settings, by their path in the generated folder."""
        return f"{name}: hidden tool settings are not allowed in the generated code"

    def test_tool_settings_are_reported(self) -> None:
        """A ``.cargo/`` folder, ``.rustfmt.toml`` and ``.clippy.toml`` are each reported; ``update`` writes nothing.

        Would fail if one of them were ignored like any other hidden file, although Cargo, rustfmt
        or clippy read it and so could build or check the code differently from what the check has seen.
        """
        # write the manifest and mark it, to see later whether the refused update rewrote it:
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        # add a .cargo/ folder, a .rustfmt.toml and a .clippy.toml:
        self.write_generated(
            ".cargo/config.toml", '[build]\nrustflags = ["-Awarnings"]\n'
        )
        self.write_generated(".rustfmt.toml", "max_width = 200\n")
        self.write_generated(".clippy.toml", "too-many-arguments-threshold = 99\n")
        # check and update report each of them, sorted by name; the refused update leaves the manifest as it was:
        expected: list[str] = [
            self.problem(name) for name in [".cargo", ".clippy.toml", ".rustfmt.toml"]
        ]
        self.assertEqual(expected, script.check(self.root))
        self.assertEqual(expected, script.update(self.root))
        self.assertEqual(before, self.manifest_path.read_bytes())

    def test_tool_settings_in_a_subfolder_are_reported(self) -> None:
        """A ``.rustfmt.toml`` in ``src/`` is reported; one in Cargo's build folder ``target/`` is not.

        Would fail if only the top of the generated folder were searched, although rustfmt also reads
        the settings next to the files it formats.
        """
        self.update_cleanly()
        self.write_generated("src/.rustfmt.toml", "max_width = 200\n")
        self.write_generated("target/.rustfmt.toml", "max_width = 200\n")
        self.assertEqual([self.problem("src/.rustfmt.toml")], script.check(self.root))

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_tool_settings_links_are_reported(self) -> None:
        """A symbolic link to tool settings elsewhere, or to nothing, is reported as both; ``update`` writes nothing.

        Would fail if only real files and folders counted as tool settings, so a link to settings
        elsewhere slipped through, or if a link whose target does not exist (yet) were not seen.
        """
        # a folder with tool settings outside the repository:
        configuration: Path = self.root.parent / "configuration"
        configuration.mkdir()
        (configuration / "config.toml").write_bytes(b"[build]\n")
        # write the manifest and mark it, to see later whether the refused update rewrote it:
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        # link each tool setting in turn to that folder or to nothing:
        missing: Path = self.root.parent / "missing"
        cases: list[tuple[str, Path]] = [
            (".cargo", configuration),
            (".cargo", missing),
            (".rustfmt.toml", missing),
            (".clippy.toml", missing),
        ]
        for name, target in cases:
            with self.subTest(name=name, target=target.name):
                link: Path = self.generated / name
                os.symlink(target, link)
                # check and update report the link both as tool settings and as a link; the update refuses, and the
                # manifest stays as it was:
                expected: list[str] = [
                    self.problem(name),
                    f"{name}: a symbolic link, not allowed in the generated code",
                ]
                try:
                    self.assertEqual(expected, script.check(self.root))
                    self.assertEqual(expected, script.update(self.root))
                    self.assertEqual(before, self.manifest_path.read_bytes())
                finally:
                    link.unlink()


class DangerousConstructTest(GeneratedRepositoryTest):
    """Checks that constructs reaching the system or the build are reported, unless their line is allowed."""

    def problem(self, path: str, number: int, line: str) -> str:
        """Returns what the script reports for a dangerous construct, by file, line number and line."""
        return (
            f"{path}:{number}: dangerous construct `{line.strip()}`; a person decides on it (allowed lines are "
            "listed in .ci/check_generated.py)"
        )

    def test_dangerous_constructs_are_reported(self) -> None:
        """Each dangerous construct is reported with its file and line number, also in the README; so is ``build.rs``.

        Would fail if one of the std modules, macros or keywords listed below were no longer matched, if
        ``std::{`` or ``# [ path =``, ``env !`` or ``::std :: fs`` with spaces were missed, if a doc comment
        were skipped although it runs as a doctest, if the code in ``README.md`` were not searched, if
        ``build.rs`` at the top were not reported, or if the line number were counted from 0.
        """
        rust_lines: list[str] = [
            '/// std::process::Command::new("sh");',
            'let _ = std::net::TcpStream::connect("x");',
            'let _ = ::std :: fs::read("x");',
            'std::os::unix::fs::symlink("a", "b");',
            'let _ = std::env::var("HOME");',
            "use std::{collections::HashMap, net::TcpStream};",
            "extern crate alloc;",
            "unsafe { }",
            'include!("x.rs");',
            'include_bytes!("x");',
            'include_str!("x");',
            'let _ = env !("HOME");',
            'option_env!("X");',
            '# [ path = "x.rs" ] mod x;',
            '#![path = "x"]',
            '#[cfg_attr(test, path = "x.rs")] mod y;',
        ]
        readme_line: str = 'let _ = std::fs::read("x");'
        # the file to write, its text, and the problems it is expected to give:
        cases: list[tuple[str, str, list[str]]] = [
            (
                "src/case.rs",
                f"pub struct Mvcc;\n{line}\n",
                [self.problem("src/case.rs", 2, line)],
            )
            for line in rust_lines
        ] + [
            (
                "README.md",
                f"```rust\n{readme_line}\n```\n",
                [self.problem("README.md", 2, readme_line)],
            ),
            (
                "build.rs",
                "fn main() {}\n",
                [
                    "build.rs: dangerous construct, a build script Cargo runs; a person decides on it"
                ],
            ),
        ]
        for path, text, expected in cases:
            with self.subTest(path=path, text=text):
                self.write_generated(path, text)
                self.assertEqual(
                    expected, script.dangerous_construct_problems(self.root, [path])
                )

    def test_harmless_and_allowed_lines_are_not_reported(self) -> None:
        """Harmless lines, allowed lines and a nested ``build.rs`` are not reported; an allowed line elsewhere is.

        The line ``std::process::exit(2);`` is allowed in ``examples/benchmarks/workloads.rs`` only, also
        with other spacing, and only as the whole line. A form feed does not start a new line, as in an
        editor. Would fail if ``std::collections``, a variable named ``path``, ``external`` or
        ``unsafe_count``, or the comparison ``env != 0`` counted as dangerous, if ``src/build.rs`` were taken
        for the build script, if the allowed lines were ignored, allowed in every file or matched as part of a
        line, or if lines were split at a form feed.
        """
        workloads: str = "examples/benchmarks/workloads.rs"
        two_calls: str = 'std::process::exit(2); std::fs::remove_file("x");'
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py")
            + '\nuse std::collections::HashMap;\f\nlet path = "x";\nstd::process::exit(2);\n'
            + "let external = 1;\nlet unsafe_count = 0;\nif env != 0 {}\n",
        )
        self.write_generated("src/build.rs", NO_SOURCE_HEADER + "\nfn main() {}\n")
        self.write_generated(
            workloads,
            NO_SOURCE_HEADER
            + f'\n    std::process::exit( 2 );\nstd::process::Command::new("sh");\n{two_calls}\n',
        )
        self.assertEqual(
            [
                self.problem(workloads, 3, 'std::process::Command::new("sh");'),
                self.problem(workloads, 4, two_calls),
                self.problem("src/mvcc.rs", 4, "std::process::exit(2);"),
            ],
            script.dangerous_construct_problems(
                self.root, [workloads, "src/build.rs", "src/mvcc.rs"]
            ),
        )

    def test_allowed_line_written_with_spaces_allows_the_line_with_other_spacing(
        self,
    ) -> None:
        """An allowed line written with spaces, as the check shows it, allows the line also without these spaces.

        Would fail if the whitespace were removed only from the line in the file and not from the allowed
        entry, so that an entry copied from the check's report would never match.
        """
        # an entry with spaces, and the same line without them and with other spaces in the file:
        allowed: dict[str, frozenset[str]] = {
            "src/case.rs": frozenset({'#[path = "x.rs"]'})
        }
        self.write_generated(
            "src/case.rs", 'pub struct Mvcc;\n#[path="x.rs"]\n  #[ path =  "x.rs" ]\n'
        )
        # neither line is reported:
        with mock.patch.dict(script.ALLOWED_LINES, allowed):
            self.assertEqual(
                [], script.dangerous_construct_problems(self.root, ["src/case.rs"])
            )

    def test_update_refuses_on_a_dangerous_construct(self) -> None:
        """A dangerous construct added after an update is reported by the check, and ``update`` refuses to record it.

        Would fail if the check that CI runs missed the construct, or if ``update`` recorded it and so
        changed the manifest.
        """
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        self.append_generated("src/mvcc.rs", "unsafe { }\n")
        problem: str = self.problem("src/mvcc.rs", 3, "unsafe { }")
        self.assertEqual(
            [
                problem,
                "src/mvcc.rs: edited by hand; change the Python source and regenerate instead",
            ],
            script.check(self.root),
        )
        self.assertEqual([problem], script.update(self.root))
        self.assertEqual(before, self.manifest_path.read_bytes())


@unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
class SymbolicLinkTest(GeneratedRepositoryTest):
    """Checks that the generated folder holds no symbolic links."""

    def test_symbolic_links_are_reported(self) -> None:
        """A link to a file, a link to a folder and a link to nothing are each reported; ``update`` writes nothing.

        Would fail if links were listed like files: the files in a linked folder would be neither
        recorded nor checked although Cargo compiles them, and a link to nothing cannot be read.
        """
        # a folder outside the repository with a Rust file:
        outside: Path = self.root.parent / "outside"
        outside.mkdir()
        (outside / "extra.rs").write_bytes((NO_SOURCE_HEADER + "\n").encode("utf-8"))
        # write the manifest and mark it, to see later whether the refused update rewrote it:
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        # add a link to a generated file, a link to nothing and a link to the folder outside:
        os.symlink(self.generated / "src/mvcc.rs", self.generated / "src/alias.rs")
        os.symlink(self.root.parent / "missing.rs", self.generated / "src/dangling.rs")
        os.symlink(outside, self.generated / "src/linked")
        # check and update report each link, and the refused update leaves the manifest as it was:
        expected: list[str] = [
            f"src/{name}: a symbolic link, not allowed in the generated code"
            for name in ["alias.rs", "dangling.rs", "linked"]
        ]
        self.assertEqual(expected, script.check(self.root))
        self.assertEqual(expected, script.update(self.root))
        self.assertEqual(before, self.manifest_path.read_bytes())

    def test_dangling_main_link_is_reported_without_a_crash(self) -> None:
        """A ``main.rs`` that links to nothing is reported as a link, and its folder as one without ``main.rs``.

        Would fail if the module check tried to read the linked ``main.rs`` and crashed with
        ``FileNotFoundError`` instead of reporting the problems.
        """
        # a test file in a folder whose main.rs is a link to nothing:
        self.write_generated(
            "tests/stores/test_basics.rs", header("system/stores/mvcc.py") + "\n"
        )
        os.symlink(
            self.root.parent / "missing.rs", self.generated / "tests/stores/main.rs"
        )
        # the update reports the folder as one without main.rs and
        # main.rs as a link; check also reports the missing manifest:
        expected: list[str] = [
            "tests/stores/: a test folder without main.rs; Cargo would not build its tests",
            "tests/stores/main.rs: a symbolic link, not allowed in the generated code",
        ]
        self.assertEqual(expected, script.update(self.root))
        self.assertEqual(
            expected + ["generated/rust/GENERATED_FROM.json is missing"],
            script.check(self.root),
        )

    def test_linked_test_file_is_reported_only_as_a_link(self) -> None:
        """A test file that links to a real ``.rs`` file is reported as a link, not also as not included.

        Would fail if the module check still saw the linked file and added a "not included" line
        for a file that is rejected anyway.
        """
        # a test folder whose main.rs includes test_basics:
        self.write_generated(
            "tests/stores/main.rs", NO_SOURCE_HEADER + "\nmod test_basics;\n"
        )
        self.write_generated(
            "tests/stores/test_basics.rs", header("system/stores/mvcc.py") + "\n"
        )
        # add test_alias.rs as a link to test_basics.rs; it is reported only as a link:
        os.symlink(
            self.generated / "tests/stores/test_basics.rs",
            self.generated / "tests/stores/test_alias.rs",
        )
        self.assertEqual(
            [
                "tests/stores/test_alias.rs: a symbolic link, not allowed in the generated code"
            ],
            script.update(self.root),
        )

    def test_links_in_the_build_folder_are_ignored(self) -> None:
        """A symbolic link in Cargo's build folder ``target/`` is not reported.

        Would fail if ``target/`` were searched for links, although Cargo writes its build output there.
        """
        (self.generated / "target").mkdir()
        os.symlink(self.root.parent / "missing", self.generated / "target/latest")
        self.update_cleanly()
        self.assertEqual([], script.check(self.root))

    def test_linked_generated_folder_is_reported_and_update_refuses(self) -> None:
        """``generated/rust`` itself as a symbolic link is reported; ``update`` writes nothing through it.

        Would fail if only the links inside the generated folder were looked for: the listing follows
        the link at its start, so ``update`` wrote the manifest into a folder anywhere on the machine,
        stored a copy of the changed source, and the check took the code there for the generated code.
        """
        # write the manifest and mark it, and keep the copies of the sources:
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        copies: dict[str, bytes] = self.copies()
        # change the source, then move generated/rust elsewhere and put a link to it in its place:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        elsewhere: Path = self.root.parent / "elsewhere"
        self.generated.rename(elsewhere)
        os.symlink(elsewhere, self.generated)
        # note the files behind the link:
        content: list[Path] = sorted(elsewhere.rglob("*"))
        # the update refuses; the manifest and the copies stay as they were, and no file behind the link is added or
        # removed:
        problem: str = "generated/rust: a symbolic link; it must be a real folder"
        self.assertEqual([problem], script.update(self.root))
        self.assertEqual(before, (elsewhere / "GENERATED_FROM.json").read_bytes())
        self.assertEqual(content, sorted(elsewhere.rglob("*")))
        self.assertEqual(copies, self.copies())
        # check reports the link, and also the out-of-date Rust file behind it:
        self.assertEqual(
            [
                problem,
                "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
                "regenerate it and run the update",
            ],
            script.check(self.root),
        )

    def test_linked_folder_with_a_dangling_link_inside_is_reported_without_a_crash(
        self,
    ) -> None:
        """A linked ``generated/rust`` or ``generated/`` whose files include a link to nothing gives both reports.

        The files behind the folder link are still listed, so the link to nothing among them is
        reported and not read. Would fail if the check stopped at the folder link and then read
        ``src/dangling.rs`` as a generated file, so it crashed with ``FileNotFoundError``, or if
        the link inside were not reported.
        """
        self.update_cleanly()
        # after the update, add a link to nothing among the generated files:
        os.symlink(self.root.parent / "missing.rs", self.generated / "src/dangling.rs")
        for folder in ["generated/rust", "generated"]:
            with self.subTest(folder=folder):
                # move the folder elsewhere and put a link to it in its place:
                linked: Path = self.root / folder
                elsewhere: Path = self.root.parent / "elsewhere"
                linked.rename(elsewhere)
                os.symlink(elsewhere, linked)
                try:
                    # check and update report both the folder link and the link to nothing inside:
                    expected: list[str] = [
                        f"{folder}: a symbolic link; it must be a real folder",
                        "src/dangling.rs: a symbolic link, not allowed in the generated code",
                    ]
                    self.assertEqual(expected, script.check(self.root))
                    self.assertEqual(expected, script.update(self.root))
                finally:
                    # put the folder back for the next case:
                    linked.unlink()
                    elsewhere.rename(linked)


class UpdateDependenciesTest(GeneratedRepositoryTest):
    """Checks ``update_dependencies``, which records only Cargo.toml, Cargo.lock and rust-toolchain.toml anew."""

    def setUp(self) -> None:
        """Adds the three dependency files and writes the manifest.

        Without a manifest, the update records the Cargo files as they are.
        """
        super().setUp()
        self.write_generated(
            "Cargo.toml",
            "# Code generated for the Rust port (no Python source). DO NOT EDIT.\n"
            '[dependencies]\nrand = "0.8"\n',
        )
        self.write_generated("Cargo.lock", 'version = 4\n[[package]]\nname = "rand"\n')
        self.write_generated(
            "rust-toolchain.toml",
            "# Code generated for the Rust port (no Python source). DO NOT EDIT.\n"
            '[toolchain]\nchannel = "1.80"\n',
        )
        self.update_cleanly()

    def test_only_the_dependency_files_are_recorded_anew(self) -> None:
        """After a changed Cargo.lock and a changed Python source, only the stale Rust file is still reported.

        Would fail if ``update_dependencies`` recorded every file anew, hiding the out-of-date Rust
        code, or did not record the new Cargo.lock, which would then count as edited by hand.
        """
        # change Cargo.lock as a dependency update would, and also the Python source:
        self.append_generated("Cargo.lock", 'version = "0.9.0"\n')
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # the dependency update records the new Cargo.lock, but not the changed source, so check still reports the
        # out-of-date Rust file:
        self.assertEqual([], script.update_dependencies(self.root))
        self.assertEqual(
            [
                "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
                "regenerate it and run the update"
            ],
            script.check(self.root),
        )

    def test_hand_edit_stays_reported(self) -> None:
        """A hand edit of a generated Rust file is still reported after ``update_dependencies``.

        Would fail if ``update_dependencies`` also recorded the hash of the hand-edited file.
        """
        # change Cargo.toml as a dependency update would, and edit the Rust file by hand:
        self.append_generated("Cargo.toml", 'serde = "1"\n')
        self.append_generated("src/mvcc.rs", "pub fn patched() {}\n")
        # the dependency update records the new Cargo.toml, but not the hand edit, so check still reports it:
        self.assertEqual([], script.update_dependencies(self.root))
        self.assertEqual(
            [
                "src/mvcc.rs: edited by hand; change the Python source and regenerate instead"
            ],
            script.check(self.root),
        )

    def test_problems_of_other_files_do_not_keep_it_from_writing(self) -> None:
        """A Rust file without its first line does not keep ``update_dependencies`` from recording Cargo.lock.

        Would fail if every problem refused the dependency update, although it leaves the other
        files as recorded, so their problems stay reported anyway.
        """
        # add a Rust file without its first line, and change Cargo.lock:
        self.write_generated("src/lib.rs", "pub mod mvcc;\n")
        self.append_generated("Cargo.lock", 'version = "0.9.0"\n')
        # the dependency update still records the new Cargo.lock, and check still reports the Rust file:
        self.assertEqual([], script.update_dependencies(self.root))
        self.assertEqual(
            digest(self.generated / "Cargo.lock"), self.recorded("Cargo.lock")["sha256"]
        )
        self.assertEqual([f"src/lib.rs: {NO_HEADER}"], script.check(self.root))

    def test_refused_on_a_problem_of_a_dependency_file(self) -> None:
        """A dependency file without its first line is reported and ``update_dependencies`` writes nothing.

        Would fail if ``update_dependencies`` wrote the manifest anyway, keeping the old entry of the
        broken file.
        """
        before: bytes = self.mark_manifest()
        self.write_generated("Cargo.toml", '[dependencies]\nrand = "0.9"\n')
        self.assertEqual(
            [f"Cargo.toml: {NO_HEADER}"], script.update_dependencies(self.root)
        )
        self.assertEqual(before, self.manifest_path.read_bytes())

    def test_removed_dependency_file_is_dropped(self) -> None:
        """A dependency file deleted before ``update_dependencies`` loses its entry, so the check passes.

        Would fail if the entry stayed recorded and the check then reported the file as not on disk.
        """
        (self.generated / "rust-toolchain.toml").unlink()
        self.assertEqual([], script.update_dependencies(self.root))
        self.assertNotIn("rust-toolchain.toml", self.recorded_paths())
        self.assertEqual([], script.check(self.root))

    def test_new_dependency_file_is_recorded(self) -> None:
        """A dependency file that was not recorded before is recorded by ``update_dependencies``.

        Would fail if only entries already in the manifest were rewritten, so the new file stayed
        reported as not in the manifest.
        """
        # record the manifest without rust-toolchain.toml:
        (self.generated / "rust-toolchain.toml").unlink()
        self.assertEqual([], script.update_dependencies(self.root))
        # add rust-toolchain.toml again, with another Rust version:
        self.write_generated(
            "rust-toolchain.toml",
            "# Code generated for the Rust port (no Python source). DO NOT EDIT.\n"
            '[toolchain]\nchannel = "1.81"\n',
        )
        # the dependency update records it with its current hash, and check passes:
        self.assertEqual([], script.update_dependencies(self.root))
        self.assertEqual(
            digest(self.generated / "rust-toolchain.toml"),
            self.recorded("rust-toolchain.toml")["sha256"],
        )
        self.assertEqual([], script.check(self.root))

    def test_update_refuses_on_a_changed_added_or_deleted_cargo_file(self) -> None:
        """A Cargo file changed, added or deleted since the manifest was written makes ``update`` refuse.

        The update writes neither copies nor the manifest, so a Rust file regenerated in the same run
        is not recorded either. Would fail if ``update`` recorded a Cargo change that no person
        decided, or compared only the Cargo files on disk and in the manifest, missing an added or
        a deleted one.
        """
        # record the manifest without rust-toolchain.toml, keeping its content to add it again below:
        toolchain: bytes = (self.generated / "rust-toolchain.toml").read_bytes()
        (self.generated / "rust-toolchain.toml").unlink()
        self.assertEqual([], script.update_dependencies(self.root))
        # mark the manifest and note the copies, to see later whether the refused update changed them:
        before: bytes = self.mark_manifest()
        copies: dict[str, bytes] = self.copies()
        # change a source and regenerate its Rust file, so the update would have something to record:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py") + "\npub struct Mvcc { x: i32 }\n",
        )

        def set_content(target: Path, content: bytes | None) -> None:
            """Writes the bytes to the file, or deletes it if they are ``None``."""
            if content is None:
                target.unlink()
            else:
                target.write_bytes(content)

        # the new content of each Cargo file: Cargo.toml changed, rust-toolchain.toml added, Cargo.lock deleted:
        changes: dict[str, bytes | None] = {
            "Cargo.toml": (self.generated / "Cargo.toml").read_bytes()
            + b'serde = "1"\n',
            "rust-toolchain.toml": toolchain,  # not in the manifest
            "Cargo.lock": None,
        }
        for path, content in changes.items():
            with self.subTest(path=path):
                target: Path = self.generated / path
                original: bytes | None = (
                    target.read_bytes() if target.exists() else None
                )
                # make the change; the update refuses it, and the manifest and the copies stay as they were:
                set_content(target, content)
                try:
                    self.assertEqual([cargo_changed(path)], script.update(self.root))
                    self.assertEqual(before, self.manifest_path.read_bytes())
                    self.assertEqual(copies, self.copies())
                finally:
                    # undo the change for the next case:
                    set_content(target, original)

    def test_update_reports_an_unreadable_cargo_file_once(self) -> None:
        """A Cargo.toml without its first line gives ``update`` only the first-line problem.

        Would fail if ``update`` also reported the file as changed since it was recorded, because
        it is missing from the files that could be read.
        """
        self.write_generated("Cargo.toml", '[dependencies]\nrand = "0.8"\n')
        self.assertEqual([f"Cargo.toml: {NO_HEADER}"], script.update(self.root))

    def test_update_with_an_unreadable_manifest_records_the_cargo_files(self) -> None:
        """With an unreadable manifest, ``update`` records the Cargo files as they are, so the check passes.

        Would fail if ``update`` treated an unreadable manifest as one without entries and refused
        every Cargo file as added, so a broken manifest could not be written anew.
        """
        # write a manifest that breaks off in the middle; the update writes it anew, and check passes:
        self.write_generated("GENERATED_FROM.json", '{"files": [')
        self.update_cleanly()
        self.assertEqual([], script.check(self.root))

    def test_update_succeeds_after_the_cargo_change_is_recorded(self) -> None:
        """After ``update_dependencies`` recorded a changed Cargo.lock, ``update`` records a regenerated Rust file.

        Would fail if ``update`` compared the Cargo files with anything but the manifest, so it
        refused also once the change was recorded.
        """
        # change Cargo.lock, and change a source and regenerate its Rust file:
        self.append_generated("Cargo.lock", 'version = "0.9.0"\n')
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py") + "\npub struct Mvcc { x: i32 }\n",
        )
        # record the Cargo change first; then the update records the Rust file, and check passes:
        self.assertEqual([], script.update_dependencies(self.root))
        self.update_cleanly()
        self.assertEqual([], script.check(self.root))

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_refused_on_a_linked_generated_folder(self) -> None:
        """If ``generated/rust`` or ``generated`` is a symbolic link, ``update_dependencies`` writes nothing through it.

        The link is no problem of a dependency file, but of the folder that holds them all. Would
        fail if only the problems of the three files refused the dependency update, so it wrote the
        manifest into a folder anywhere on the machine.
        """
        before: bytes = self.mark_manifest()
        # the problem reported for each folder when it is a symbolic link:
        expected: dict[str, str] = {
            "generated/rust": "generated/rust: a symbolic link; it must be a real folder",
            "generated": "generated: a symbolic link; it must be a real folder",
        }
        for folder, problem in expected.items():
            with self.subTest(folder=folder):
                # move the folder elsewhere and put a link to it in its place:
                linked: Path = self.root / folder
                elsewhere: Path = self.root.parent / "elsewhere"
                linked.rename(elsewhere)
                os.symlink(elsewhere, linked)
                try:
                    # change Cargo.lock behind the link, and note the files there:
                    self.append_generated("Cargo.lock", 'version = "0.9.0"\n')
                    content: list[Path] = sorted(elsewhere.rglob("*"))
                    # the dependency update refuses; the manifest stays as it was, and no file behind the link is added
                    # or removed:
                    self.assertEqual([problem], script.update_dependencies(self.root))
                    self.assertEqual(before, self.manifest_path.read_bytes())
                    self.assertEqual(content, sorted(elsewhere.rglob("*")))
                finally:
                    # put the folder back for the next case:
                    linked.unlink()
                    elsewhere.rename(linked)

    def test_refused_when_a_dependency_file_names_a_python_source(self) -> None:
        """A Cargo.toml whose first line names a Python source is reported, and the manifest stays as it was.

        A dependency update records no sources, so such a file must be regenerated. Would fail if
        ``update_dependencies`` recorded the file with its source: then the hash of that source would
        be recorded without the copy that ``--diff`` needs, and without regenerating.
        """
        before: bytes = self.mark_manifest()
        self.write_generated(
            "Cargo.toml",
            "# Code generated from system/stores/mvcc.py. DO NOT EDIT.\n"
            '[dependencies]\nrand = "0.9"\n',
        )
        self.assertEqual(
            [
                "Cargo.toml: names a Python source; a dependency update records no sources, regenerate instead"
            ],
            script.update_dependencies(self.root),
        )
        self.assertEqual(before, self.manifest_path.read_bytes())

    def test_refused_without_manifest(self) -> None:
        """Without a manifest, ``update_dependencies`` reports it missing and writes none.

        Would fail if it crashed on the missing manifest or wrote one with the dependency files only.
        """
        self.manifest_path.unlink()
        self.assertEqual(
            ["generated/rust/GENERATED_FROM.json is missing"],
            script.update_dependencies(self.root),
        )
        self.assertFalse(self.manifest_path.exists())


class UpdateRefusesTest(GeneratedRepositoryTest):
    """Checks that ``update`` writes no manifest while there are problems, and never through a link."""

    def test_update_refuses_on_missing_first_line(self) -> None:
        """With a file lacking the header, ``update`` returns the problem and leaves the manifest as it was.

        Would fail if ``update`` wrote a manifest without the file, hiding it from later checks.
        """
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        self.write_generated("src/lib.rs", "pub mod mvcc;\n")
        self.assertEqual([f"src/lib.rs: {NO_HEADER}"], script.update(self.root))
        self.assertEqual(before, self.manifest_path.read_bytes())

    @unittest.skipUnless(
        COLON_AND_BACKSLASH_NAMES,
        "this system cannot create files named with ':' or '\\'",
    )
    def test_update_refuses_on_a_file_name_with_a_colon_or_a_backslash(self) -> None:
        """A generated file named with ':' or '\\' is reported by the check, and ``update`` writes nothing.

        The manifest refuses such paths, as they mean other files on Windows. Would fail if
        ``update`` recorded the file anyway, so it wrote a manifest that the check and ``--diff``
        then refuse to read.
        """
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        # add a file named with a colon, then one named with a backslash, one at a time:
        for name in ["src/a:b.rs", "src/a\\b.rs"]:
            with self.subTest(name=name):
                self.write_generated(name, NO_SOURCE_HEADER + "\n")
                problem: str = (
                    f"{name}: a file name with ':' or '\\' is not allowed in the generated code"
                )
                # the update refuses and leaves the manifest as it was, and check reports the same problem:
                try:
                    self.assertEqual([problem], script.update(self.root))
                    self.assertEqual(before, self.manifest_path.read_bytes())
                    self.assertEqual([problem], script.check(self.root))
                finally:
                    # remove the file for the next case:
                    (self.generated / name).unlink()

    def test_update_refuses_on_missing_source_without_manifest(self) -> None:
        """With a missing source and no manifest yet, ``update`` returns the problem and writes nothing.

        Would fail if ``update`` created a manifest despite the problem.
        """
        self.write_generated(
            "src/mvcc.rs", header("system/stores/gone.py") + "\npub struct Mvcc;\n"
        )
        self.assertEqual(
            ["src/mvcc.rs: its source system/stores/gone.py does not exist"],
            script.update(self.root),
        )
        self.assertFalse(self.manifest_path.exists())

    def test_update_refuses_on_a_source_changed_while_it_ran(self) -> None:
        """A source that changes after it was hashed but before its copy is stored makes ``update`` refuse.

        The change is made right after ``current_files`` has hashed the sources. Would fail if the
        copy were written from the changed source under the old hash, so the copy were corrupt,
        or if the manifest were written with the old hash.
        """
        # keep the real current_files; the replacement below calls it, then changes the source:
        hash_sources = script.current_files

        def hash_sources_then_change_one(root: Path) -> tuple[list, list[str]]:
            """Hashes the sources as ``update`` does, then changes one of them."""
            result: tuple[list, list[str]] = hash_sources(root)
            self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
            return result

        # run the update with the replacement: it finds the changed source when it stores the copy, and refuses:
        with mock.patch.object(
            script, "current_files", side_effect=hash_sources_then_change_one
        ):
            self.assertEqual(
                [
                    "system/stores/mvcc.py: changed while the update ran; run the update again"
                ],
                script.update(self.root),
            )
        # neither the manifest nor any copy was written:
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse((self.root / COPIES).exists())

    def test_source_of_two_files_changed_while_the_update_ran_is_reported_once(
        self,
    ) -> None:
        """A source of two generated files that changes while the update runs is reported once, not once per file.

        The change is made right after ``current_files`` has hashed the sources, as above. Would fail
        if every generated file that names the source added its own line, so the same advice
        appeared twice.
        """
        # a second generated file from the same source, mvcc.py:
        self.write_generated(
            "src/versioned.rs",
            header("system/stores/mvcc.py") + "\npub struct Versioned;\n",
        )
        # replace current_files as above: hash the sources, then change the shared one:
        hash_sources = script.current_files

        def hash_sources_then_change_one(root: Path) -> tuple[list, list[str]]:
            """Hashes the sources as ``update`` does, then changes the shared one."""
            result: tuple[list, list[str]] = hash_sources(root)
            self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
            return result

        # the update reports the changed source once and writes no manifest:
        with mock.patch.object(
            script, "current_files", side_effect=hash_sources_then_change_one
        ):
            self.assertEqual(
                [
                    "system/stores/mvcc.py: changed while the update ran; run the update again"
                ],
                script.update(self.root),
            )
        self.assertFalse(self.manifest_path.exists())

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_update_does_not_write_through_a_linked_manifest(self) -> None:
        """If the manifest is a symbolic link, ``update`` refuses and the file it points to is unchanged.

        Would fail if ``update`` wrote through the link and so overwrote a file anywhere on the machine.
        """
        # make the manifest a link to a file elsewhere:
        self.write("elsewhere.json", "keep me\n")
        os.symlink(self.root / "elsewhere.json", self.manifest_path)
        # the update refuses, as the link is reported like any other, and the file it points to stays as it was:
        self.assertEqual(
            ["GENERATED_FROM.json: a symbolic link, not allowed in the generated code"],
            script.update(self.root),
        )
        self.assertEqual(b"keep me\n", (self.root / "elsewhere.json").read_bytes())

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_update_dependencies_does_not_write_through_a_linked_manifest(
        self,
    ) -> None:
        """If the manifest is a link to a valid manifest, ``update_dependencies`` refuses to write through it.

        Would fail if writing the manifest did not check for a link itself: the link is no problem
        of a dependency file, so ``update_dependencies`` goes on to write.
        """
        # write the manifest and mark it, then move it elsewhere and put a link to it in its place:
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        elsewhere: Path = self.root / "elsewhere.json"
        self.manifest_path.rename(elsewhere)
        os.symlink(elsewhere, self.manifest_path)
        # the dependency update refuses to write through the link, and the manifest elsewhere stays as it was:
        self.assertEqual(
            [
                "generated/rust/GENERATED_FROM.json is a symbolic link; it is not written through"
            ],
            script.update_dependencies(self.root),
        )
        self.assertEqual(before, elsewhere.read_bytes())


def git_available() -> bool:
    """Returns whether git is installed and runs."""
    try:
        return (
            subprocess.run(
                ["git", "--version"], capture_output=True, check=False
            ).returncode
            == 0
        )
    except OSError:
        return False


# skipped without git only outside CI; in CI, missing git makes the tests fail instead of hiding the rules' loss:
@unittest.skipUnless(git_available() or os.environ.get("CI"), "git is not available")
class GitAttributesTest(unittest.TestCase):
    """Checks the rules of the repository's real ``.gitattributes`` for the folder of the copies."""

    def check_attr(self, *arguments: str) -> list[str]:
        """Runs ``git check-attr`` with the given arguments on the repository's ``.gitattributes``; returns its lines.

        Only the rules in that file count: it is copied into a new, empty repository made without
        templates, so neither the ``info/attributes`` of the checkout, which outrank
        ``.gitattributes``, nor the developer's personal or the system's attributes take part.
        """
        with tempfile.TemporaryDirectory() as folder:
            env: dict[str, str] = {**os.environ, "GIT_ATTR_NOSYSTEM": "1"}
            subprocess.run(
                ["git", "init", "-q", "--template="],
                cwd=folder,
                capture_output=True,
                check=True,
                env=env,
            )
            shutil.copyfile(
                REPO_ROOT / ".gitattributes", Path(folder) / ".gitattributes"
            )
            return subprocess.run(
                [
                    "git",
                    "-c",
                    f"core.attributesFile={os.devnull}",
                    "check-attr",
                    *arguments,
                ],
                cwd=folder,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            ).stdout.splitlines()

    def test_copies_keep_their_bytes_but_the_readme_is_text(self) -> None:
        """Git never converts the line endings of a copy; the README of their folder is ordinary text.

        A copy is checked byte for byte against its name, which is the hash of its bytes. Would fail
        if the rule were lost, so a Windows checkout with ``core.autocrlf`` turned every copy into
        CR LF and the check reported all of them as corrupt, or if the README fell under that rule
        or an ``eol`` rule were left over for the copies.
        """
        copy: str = f"{COPIES}/0123456789abcdef.txt"
        readme: str = f"{COPIES}/README.md"
        # git does not treat the copy as text, so it never converts its line endings; for the README, git tells from
        # its content whether it is text; neither has an eol rule:
        self.assertEqual(
            [
                f"{copy}: text: unset",
                f"{copy}: eol: unspecified",
                f"{readme}: text: auto",
                f"{readme}: eol: unspecified",
            ],
            self.check_attr("text", "eol", "--", copy, readme),
        )

    def test_copies_are_folded_but_not_their_readme(self) -> None:
        """GitLab folds the copies in merge request diffs, but not the README of their folder.

        Would fail if the README were caught by the rule for the copies, so a change of its text
        was hidden from reviewers, or if the rule for the copies were lost.
        """
        copy: str = f"{COPIES}/0123456789abcdef.txt"
        readme: str = f"{COPIES}/README.md"
        self.assertEqual(
            [f"{copy}: gitlab-generated: set", f"{readme}: gitlab-generated: unset"],
            self.check_attr("gitlab-generated", "--", copy, readme),
        )


class SourceCopiesTest(GeneratedRepositoryTest):
    """Checks that ``update`` stores a copy of every Python source, once per version, and never deletes one."""

    def test_update_stores_one_copy_per_source_named_by_its_hash(self) -> None:
        """After ``update``, the folder holds exactly one copy per source, named by its hash and holding its bytes.

        ``system/stores/mvcc.py`` is a source of both generated files. Would fail if a copy were not
        named by the start of the SHA-256 of its source's bytes, held other bytes, or if the folder
        held any other entry, such as a second copy of the shared source under another name.
        """
        # a second source, and a second generated file from both sources, so mvcc.py is a source of two files:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/versioned.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Versioned;\n",
        )
        self.update_cleanly()
        # the folder holds one copy per source, named by its hash and holding the bytes of the source:
        mvcc: Path = self.root / "system/stores/mvcc.py"
        versioned: Path = self.root / "system/stores/versioned.py"
        self.assertEqual(
            {
                copy_name_of_file(mvcc): mvcc.read_bytes(),
                copy_name_of_file(versioned): versioned.read_bytes(),
            },
            self.copies(),
        )

    def test_source_with_windows_line_endings_is_stored_with_lf(self) -> None:
        """A source with CR LF line endings gives the same copy as its LF version: same name, LF bytes.

        Would fail if the raw bytes were stored: the copy would not match its name, so the check would
        report it as corrupt, and a Windows checkout would store other copies than Linux.
        """
        # the LF version of the source, outside the repository, to compute the expected name of the copy:
        lf_version: Path = self.root.parent / "mvcc_lf.py"
        lf_version.write_bytes(b"class MVCC:\n    pass\n")
        # give the source CR LF line endings and update:
        self.write("system/stores/mvcc.py", "class MVCC:\r\n    pass\r\n")
        self.update_cleanly()
        # the only copy is named like the LF version and holds its bytes:
        self.assertEqual(
            {copy_name_of_file(lf_version): b"class MVCC:\n    pass\n"}, self.copies()
        )

    def test_old_copy_stays_after_the_source_changed(self) -> None:
        """When a source changes and ``update`` runs again, the copy of the old version stays next to the new one.

        Would fail if ``update`` removed the copies the manifest no longer names, although a manifest
        entry merged from another branch may still name them; the check must not report the old copy.
        """
        mvcc: Path = self.root / "system/stores/mvcc.py"
        # update, and note the name of the copy of the first version:
        self.update_cleanly()
        old_name: str = copy_name_of_file(mvcc)
        # change the source and update again:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.update_cleanly()
        # both copies are there, and check passes:
        self.assertEqual(
            {
                old_name: b"class MVCC:\n    pass\n",
                copy_name_of_file(mvcc): b"class MVCC:\n    x = 1\n",
            },
            self.copies(),
        )
        self.assertEqual([], script.check(self.root))

    def hidden_and_visible_copies(self) -> tuple[dict[str, bytes], dict[str, bytes]]:
        """Returns the hidden and the visible entries of the folder of the copies, each by name with its bytes."""
        entries: dict[str, bytes] = self.copies()
        hidden: dict[str, bytes] = {
            name: data for name, data in entries.items() if name.startswith(".")
        }
        visible: dict[str, bytes] = {
            name: data for name, data in entries.items() if not name.startswith(".")
        }
        return hidden, visible

    def test_interrupted_update_leaves_no_cut_off_copy(self) -> None:
        """An update interrupted while storing a copy leaves only a hidden partial file, which the check ignores.

        The interruption is simulated by a rename that fails, as it may when the disk is full. The
        next update stores the copy in full and leaves no partial file of its own; the leftover one
        stays, as an update never deletes anything in the folder of the copies. Would fail if the
        copy were written under its own name directly: an interruption could leave a cut-off copy,
        which the check would report as corrupt and every later update would refuse because of.
        """
        source: Path = self.root / "system/stores/mvcc.py"
        # make os.replace fail, so the update stops with an error after writing the hidden partial file, before that
        # file is renamed to the name of the copy:
        with mock.patch.object(
            script.os, "replace", side_effect=OSError("No space left on device")
        ):
            with self.assertRaises(OSError):
                script.update(self.root)
        # only the hidden partial file is left, no copy; check reports only the missing manifest:
        leftover, visible = self.hidden_and_visible_copies()
        self.assertEqual({}, visible)
        self.assertEqual(1, len(leftover), leftover)
        self.assertRegex(next(iter(leftover)), r"^\..+\.partial$")
        self.assertEqual(
            ["generated/rust/GENERATED_FROM.json is missing"], script.check(self.root)
        )
        # the next update stores the copy in full; the leftover partial file stays, and check passes:
        self.update_cleanly()
        self.assertEqual(
            (leftover, {copy_name_of_file(source): source.read_bytes()}),
            self.hidden_and_visible_copies(),
        )
        self.assertEqual([], script.check(self.root))

    @unittest.skipIf(os.name == "nt", "Windows has no Unix permission bits")
    def test_copy_is_readable_by_everyone(self) -> None:
        """A copy written by ``update`` has the permissions ``rw-r--r--`` (0o644) of a checked-out file.

        Would fail if the copy kept the permissions of its hidden file, which ``mkstemp`` makes
        readable by its owner only, so other users of a shared checkout could not read the copies.
        """
        self.update_cleanly()
        copy: Path = (
            self.root / COPIES / copy_name_of_file(self.root / "system/stores/mvcc.py")
        )
        self.assertEqual(0o644, stat.S_IMODE(copy.stat().st_mode))

    def test_copy_is_flushed_to_disk_before_it_gets_its_name(self) -> None:
        """``update`` makes the system write a copy's bytes to disk before the copy is renamed to its own name.

        Would fail without the ``os.fsync`` (or with it after the rename): after a power loss, the
        renamed copy could be empty or cut off, and the check would report it as corrupt.
        """
        # the name the copy gets, and the real fsync:
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        named_at_sync: list[bool] = []
        sync = os.fsync

        def note_and_sync(descriptor: int) -> None:
            """Notes whether the copy has its own name yet, then writes the file to disk."""
            named_at_sync.append((self.root / COPIES / name).exists())
            sync(descriptor)

        # run the update with an fsync that first notes whether the copy has its name yet:
        with mock.patch.object(script.os, "fsync", side_effect=note_and_sync):
            self.update_cleanly()
        # fsync ran once, before the copy got its name:
        self.assertEqual([False], named_at_sync)

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_update_does_not_write_through_a_planted_hidden_link(self) -> None:
        """Hidden links ``.<copy name>.partial`` and ``.x.partial`` to a file outside are not written through.

        ``update`` succeeds, the file outside keeps its bytes, and the copy is a real file with the
        source's bytes. Would fail if the copy were first written to one of these two names without
        creating that file exclusively: the write would follow the link and overwrite the file
        outside, and the rename would then put the link in place of the copy.
        """
        source: Path = self.root / "system/stores/mvcc.py"
        name: str = copy_name_of_file(source)
        # a file outside the repository with bytes to keep:
        outside: Path = self.root.parent / "outside.txt"
        outside.write_bytes(b"keep me\n")
        # plant two hidden links to it in the folder of the copies, named like partial files:
        folder: Path = self.root / COPIES
        folder.mkdir(parents=True)
        for link in (f".{name}.partial", ".x.partial"):
            os.symlink(outside, folder / link)
        # the update succeeds, the file outside is unchanged, and the copy is a real file with the source's bytes:
        self.update_cleanly()
        self.assertEqual(b"keep me\n", outside.read_bytes())
        self.assertFalse((folder / name).is_symlink())
        self.assertEqual(source.read_bytes(), (folder / name).read_bytes())
        self.assertEqual([], script.check(self.root))


class CopyProblemsTest(GeneratedRepositoryTest):
    """Checks that the check reports missing, corrupt and unexpected entries in the folder of the copies."""

    def test_missing_copy_of_an_older_version_is_reported_with_the_recovery_hint(
        self,
    ) -> None:
        """A missing copy of a recorded version the source no longer has is reported, with how to get it back from git.

        The update cannot write that copy, so the advice is to restore it from git or, if git has no
        intact copy, to regenerate the Rust files before the update. Would fail if the copies were
        not compared with the manifest, so a deleted copy went unnoticed until ``--diff`` needs it,
        or if the report said to just run the update without regenerating first, which would record
        the out-of-date Rust file as current.
        """
        self.update_cleanly()
        # after the update, delete the copy, then change the source,
        # so the source no longer has the version of the copy:
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        (self.root / COPIES / name).unlink()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # check reports the missing copy with the hint to get it back from git, and the out-of-date Rust file:
        self.assertEqual(
            [
                missing_copy(name, "system/stores/mvcc.py"),
                "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
                "regenerate it and run the update",
            ],
            script.check(self.root),
        )

    def test_missing_copy_shared_by_two_sources_is_reported_for_each(self) -> None:
        """Two sources with the same content share one copy; if it is missing, each source gets its own report.

        One source changed since, the other did not, so only the second still has the version of the
        copy and gets the advice to run the update. Would fail if the copy were reported for one of
        the sources only, so the advice to regenerate the Rust files of the other one were lost.
        """
        # a second source with the same content as mvcc.py, and a Rust file generated from it:
        self.write("system/stores/legacy.py", "class MVCC:\n    pass\n")
        self.write_generated(
            "src/legacy.rs",
            header("system/stores/legacy.py") + "\npub struct Legacy;\n",
        )
        self.update_cleanly()
        # after the update, delete their shared copy, then change mvcc.py:
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        (self.root / COPIES / name).unlink()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # legacy.py still has the version of the copy, so the update can write it again; mvcc.py no longer has it:
        self.assertEqual(
            [
                missing_current_copy(name, "system/stores/legacy.py"),
                missing_copy(name, "system/stores/mvcc.py"),
                "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
                "regenerate it and run the update",
            ],
            script.check(self.root),
        )

    def test_corrupt_copy_is_reported(self) -> None:
        """A copy whose content does not match its name is reported as corrupt, with the advice to delete it.

        Would fail if only the presence of a copy were checked, so an edited copy made ``--diff`` show
        changes that were never made.
        """
        self.update_cleanly()
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        self.write(f"{COPIES}/{name}", "class MVCC:\n    edited = True\n")
        self.assertEqual(
            [corrupt_copy(name)],
            script.check(self.root),
        )

    def test_copy_with_windows_line_endings_is_corrupt(self) -> None:
        """A copy whose text is unchanged but whose line endings became CR LF is corrupt, for check and diff.

        A copy holds the bytes its name is the hash of, which have LF line endings. Would fail if a
        copy were hashed like a source, with CR LF made LF first, so ``diff`` showed every old line
        with a CR at its end.
        """
        self.update_cleanly()
        # after the update, give the copy CR LF line endings, with its text unchanged; check reports it as corrupt:
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        self.write(f"{COPIES}/{name}", "class MVCC:\r\n    pass\r\n")
        corrupt: str = corrupt_copy(name)
        self.assertEqual([corrupt], script.check(self.root))
        # change the source, so diff needs the copy: it shows nothing and reports the copy as corrupt:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(([], [corrupt]), script.diff(self.root, []))

    def test_unexpected_entries_are_reported_and_hidden_files_ignored(self) -> None:
        """Subfolders and files that are no copy are reported; the README and ``.DS_Store`` are not.

        A copy is named by exactly 16 lower-case hex digits and ``.txt``, so a name in upper case or
        with a further suffix (as a merge tool leaves it) is no copy, and neither is a folder named
        like a copy. Would fail if the folder accepted any file, so notes or stray files could pile
        up between the copies, if the name were only matched at its start or without regard to
        case, if a folder with the name of a copy were read as a copy, which makes the check crash,
        or if a file that macOS puts there made the check fail.
        """
        self.update_cleanly()
        # a README and a hidden file, which belong there:
        self.write(f"{COPIES}/README.md", "# Python sources\n")
        self.write(f"{COPIES}/.DS_Store", "finder\n")
        # a note, a name in upper case, a name with a further suffix, and a folder:
        self.write(f"{COPIES}/notes.md", "to do\n")
        self.write(f"{COPIES}/0123456789ABCDEF.txt", "upper case\n")
        self.write(f"{COPIES}/0123456789abcdef.txt.orig", "left by a merge\n")
        (self.root / COPIES / "old").mkdir()
        # a folder named like a copy; not 0123456789abcdef.txt, which a file system that ignores case would take for
        # 0123456789ABCDEF.txt above:
        (self.root / COPIES / "fedcba9876543210.txt").mkdir()
        # check reports every entry that is no copy, sorted by name:
        self.assertEqual(
            [
                f"{COPIES}/0123456789ABCDEF.txt: not a copy of a Python source; only copies <16 hex digits>.txt "
                "and README.md belong here",
                f"{COPIES}/0123456789abcdef.txt.orig: not a copy of a Python source; only copies <16 hex "
                "digits>.txt and README.md belong here",
                f"{COPIES}/fedcba9876543210.txt: not a copy of a Python source; only copies <16 hex digits>.txt "
                "and README.md belong here",
                f"{COPIES}/notes.md: not a copy of a Python source; only copies <16 hex digits>.txt and "
                "README.md belong here",
                f"{COPIES}/old: not a copy of a Python source; only copies <16 hex digits>.txt and "
                "README.md belong here",
            ],
            script.check(self.root),
        )

    def test_unexpected_entry_is_reported_also_without_manifest(self) -> None:
        """A file that is no copy is reported next to the missing manifest, not hidden by it.

        Would fail if the check stopped at the missing manifest, so the stray file only showed after
        the next update, which then refuses because of it.
        """
        self.write(f"{COPIES}/notes.md", "to do\n")
        self.assertEqual(
            [
                f"{COPIES}/notes.md: not a copy of a Python source; only copies <16 hex digits>.txt and "
                "README.md belong here",
                "generated/rust/GENERATED_FROM.json is missing",
            ],
            script.check(self.root),
        )

    def test_update_refuses_on_a_corrupt_copy(self) -> None:
        """With a corrupt copy, ``update`` returns the problem and writes neither the manifest nor new copies.

        Would fail if ``update`` went on and recorded a manifest whose copies cannot be trusted.
        """
        self.update_cleanly()
        # mark the manifest, then edit the copy and change the source, so the update would have a new copy to write:
        before: bytes = self.mark_manifest()
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        self.write(f"{COPIES}/{name}", "class MVCC:\n    edited = True\n")
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # the update reports the corrupt copy; the manifest stays as it was, and no new copy is written:
        self.assertEqual(
            [corrupt_copy(name)],
            script.update(self.root),
        )
        self.assertEqual(before, self.manifest_path.read_bytes())
        self.assertEqual([name], list(self.copies()))

    def test_deleted_corrupt_copy_of_the_current_version_is_written_by_the_update(
        self,
    ) -> None:
        """A corrupt copy of a current source, once deleted as advised, is reported missing, and the update writes it.

        This is the way out of the corrupt state: the check says to delete the copy, then says how to
        get it back, and after the update it passes. Would fail if a deleted copy were not reported
        as missing with the advice to run the update, or if the update did not write it again.
        """
        self.update_cleanly()
        # after the update, edit the copy; check reports it as corrupt:
        mvcc: Path = self.root / "system/stores/mvcc.py"
        name: str = copy_name_of_file(mvcc)
        self.write(f"{COPIES}/{name}", "class MVCC:\n    edited = True\n")
        self.assertEqual([corrupt_copy(name)], script.check(self.root))
        # delete it as advised; check reports it as missing, with the hint to regenerate first and then run the update:
        (self.root / COPIES / name).unlink()
        self.assertEqual(
            [missing_current_copy(name, "system/stores/mvcc.py")],
            script.check(self.root),
        )
        # the update writes the copy again, and check passes:
        self.update_cleanly()
        self.assertEqual({name: mvcc.read_bytes()}, self.copies())
        self.assertEqual([], script.check(self.root))

    def test_update_refuses_on_an_unexpected_entry(self) -> None:
        """With a file that is no copy in the folder, ``update`` returns the problem and writes nothing.

        Would fail if ``update`` ignored the folder's content and so left the stray file to every
        later check.
        """
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        self.write(f"{COPIES}/notes.md", "to do\n")
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            [
                f"{COPIES}/notes.md: not a copy of a Python source; only copies <16 hex digits>.txt and "
                "README.md belong here"
            ],
            script.update(self.root),
        )
        self.assertEqual(before, self.manifest_path.read_bytes())
        self.assertEqual({name, "notes.md"}, set(self.copies()))

    def test_update_writes_a_missing_copy(self) -> None:
        """The check says to regenerate and then run the update for a missing copy of a current source, which it writes.

        Would fail if the check gave the hint to restore the copy from git, although the source
        still has the version, or if ``update`` refused on missing copies like the check does, so a
        developer could not record a regeneration while a copy is missing.
        """
        self.update_cleanly()
        # after the update, delete the copy of the current source; check reports it as missing, with the hint to
        # regenerate first and then run the update:
        mvcc: Path = self.root / "system/stores/mvcc.py"
        (self.root / COPIES / copy_name_of_file(mvcc)).unlink()
        self.assertEqual(
            [missing_current_copy(copy_name_of_file(mvcc), "system/stores/mvcc.py")],
            script.check(self.root),
        )
        # the update writes the copy again, and check passes:
        self.update_cleanly()
        self.assertEqual({copy_name_of_file(mvcc): mvcc.read_bytes()}, self.copies())
        self.assertEqual([], script.check(self.root))

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_linked_folders_are_reported_and_update_refuses(self) -> None:
        """The copies folder or ``generated/`` as a symbolic link is reported; ``update`` writes nothing through it.

        ``generated/`` holds both the folder of the copies and the generated folder; it is reported
        once, as the folder that holds the generated folder. Would fail if the folders were only
        checked to exist, so ``update`` wrote copies into a folder anywhere on the machine and the
        check read copies from there, or if the link at ``generated/`` were reported a second time.
        """
        # write the manifest and mark it, then change the source, so the update would have a new copy to write:
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # what check reports for the Rust file of the changed source:
        out_of_date: str = (
            "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
            "regenerate it and run the update"
        )
        # the problem reported when the folder of the copies or generated/ is a link:
        expected: dict[str, list[str]] = {
            COPIES: [f"{COPIES}: not a folder; it must be a real folder, not a link"],
            "generated": ["generated: a symbolic link; it must be a real folder"],
        }
        for folder, problems in expected.items():
            with self.subTest(folder=folder):
                # move the folder elsewhere and put a link to it in its place:
                linked: Path = self.root / folder
                elsewhere: Path = self.root.parent / "elsewhere"
                linked.rename(elsewhere)
                os.symlink(elsewhere, linked)
                try:
                    # note the files behind the link; the update refuses, the manifest stays as it was, and no file
                    # behind the link is added or removed; check reports the link and the out-of-date Rust file:
                    content: list[Path] = sorted(elsewhere.rglob("*"))
                    self.assertEqual(problems, script.update(self.root))
                    self.assertEqual(before, self.manifest_path.read_bytes())
                    self.assertEqual(content, sorted(elsewhere.rglob("*")))
                    self.assertEqual(problems + [out_of_date], script.check(self.root))
                finally:
                    # put the folder back for the next case:
                    linked.unlink()
                    elsewhere.rename(linked)

    def test_copies_folder_that_is_a_file_is_reported_and_update_refuses(
        self,
    ) -> None:
        """A file in place of the folder of the copies is reported by the check, and ``update`` refuses.

        Would fail if ``update`` crashed on creating the folder, or if the check only reported the
        copies missing, without the reason.
        """
        self.update_cleanly()
        # mark the manifest, then put a file in place of the folder of the copies:
        before: bytes = self.mark_manifest()
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        shutil.rmtree(self.root / COPIES)
        self.write(COPIES, "not a folder\n")
        # check reports the file, and the copy of the current source as missing; the update refuses and leaves the
        # manifest as it was:
        problem: str = f"{COPIES}: not a folder; it must be a real folder, not a link"
        self.assertEqual(
            [problem, missing_current_copy(name, "system/stores/mvcc.py")],
            script.check(self.root),
        )
        self.assertEqual([problem], script.update(self.root))
        self.assertEqual(before, self.manifest_path.read_bytes())

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_link_in_the_copies_folder_is_reported(self) -> None:
        """A symbolic link named like a copy, to an intact copy elsewhere, is reported as no copy.

        Would fail if a link counted as a copy because the file it points to matches its name, so a
        copy could live outside the repository, where git does not keep it.
        """
        self.update_cleanly()
        # after the update, move the copy outside the repository and put a link to it in its place:
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        elsewhere: Path = self.root.parent / name
        (self.root / COPIES / name).rename(elsewhere)
        os.symlink(elsewhere, self.root / COPIES / name)
        # check reports the link as not a copy:
        self.assertEqual(
            [
                f"{COPIES}/{name}: not a copy of a Python source; only copies <16 hex digits>.txt and "
                "README.md belong here"
            ],
            script.check(self.root),
        )


class DiffTest(GeneratedRepositoryTest):
    """Checks ``diff``: what changed in the Python sources since their generated files were generated."""

    def test_changed_source_is_shown_against_its_copy(self) -> None:
        """A changed source gives one unified diff of its copy against the current file, under a heading.

        The removed line is in no current file, so it can only come from the copy, whose name the
        header line of the old version gives. Would fail if the old text were read from anywhere else,
        the heading named the wrong state or files, or the header line did not name the copy.
        """
        self.update_cleanly()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # the heading names the state and the generated file; then come the header lines of the copy and of the current
        # source, and the change:
        self.assertEqual(
            (
                [
                    "system/stores/mvcc.py: changed; generated from it: src/mvcc.rs",
                    old_label("system/stores/mvcc.py", "class MVCC:\n    pass\n"),
                    "+++ system/stores/mvcc.py (now)",
                    "@@ -1,2 +1,2 @@",
                    " class MVCC:",
                    "-    pass",
                    "+    x = 1",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_nothing_changed_gives_a_single_line(self) -> None:
        """Without a changed source, ``diff`` gives only the line saying so.

        Would fail if an unchanged source were compared and shown with an empty diff.
        """
        self.update_cleanly()
        self.assertEqual(([NOTHING_CHANGED], []), script.diff(self.root, []))

    def test_source_shared_by_two_files_is_shown_once(self) -> None:
        """A changed source recorded in the same version for two generated files gives one diff naming both.

        Would fail if the diff were made per generated file, so the same change was shown twice.
        """
        # a second generated file from the same source:
        self.write_generated(
            "src/other.rs", header("system/stores/mvcc.py") + "\npub struct Other;\n"
        )
        self.update_cleanly()
        # change the source after the update; a single diff names both generated files:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            (
                [
                    "system/stores/mvcc.py: changed; generated from it: src/mvcc.rs, src/other.rs"
                ]
                + MVCC_DIFF[1:],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_changed_sources_are_shown_in_the_order_of_their_paths(self) -> None:
        """The diffs of two changed sources come in the order of the source paths, not of the generated files.

        ``src/kv_store.rs`` comes before ``src/mvcc.rs``, but its source ``system/stores/versioned.py``
        comes after ``system/stores/mvcc.py``. Would fail if the versions were shown in the order they
        were found, file by file, so the order depended on the names of the generated files.
        """
        # a second source, with a generated file whose name comes before src/mvcc.rs:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/kv_store.rs",
            header("system/stores/versioned.py") + "\npub struct KvStore;\n",
        )
        self.update_cleanly()
        # change both sources after the update:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.write("system/stores/versioned.py", "class Versioned:\n    x = 1\n")
        # the diff of mvcc.py comes first, then the one of versioned.py:
        self.assertEqual(
            (
                MVCC_DIFF
                + [
                    "system/stores/versioned.py: changed; generated from it: src/kv_store.rs",
                    old_label(
                        "system/stores/versioned.py", "class Versioned:\n    pass\n"
                    ),
                    "+++ system/stores/versioned.py (now)",
                    "@@ -1,2 +1,2 @@",
                    " class Versioned:",
                    "-    pass",
                    "+    x = 1",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_two_recorded_versions_of_one_source_give_two_diffs(self) -> None:
        """Two files recorded with different versions of one source give one diff per version, each with its files.

        The manifest is edited by hand into the state after merging two branches, each of which
        regenerated one of the files from another version of the source::

            src/mvcc.rs    recorded with "pass"
            src/other.rs   recorded with "y = 2"
            now            "x = 1"

        The two diffs come in the order of the recorded hashes: the hash of "y = 2" is the smaller one,
        although ``src/mvcc.rs`` and its version are found first; the header line of each old version
        names its own copy, so the two are told apart. Would fail if the diff were grouped by source
        path only, so one of the two old versions was lost and the other was shown for both files, if
        the diffs of one source came in the order they were found, or if both header lines were the same.
        """
        # write the manifest with the first version of the source ("pass") and note its hash:
        mvcc: Path = self.root / "system/stores/mvcc.py"
        self.update_cleanly()
        first: str = digest(mvcc)
        # add a second generated file, change the source to "y = 2" and update again, which records both files with it:
        self.write_generated(
            "src/other.rs", header("system/stores/mvcc.py") + "\npub struct Other;\n"
        )
        self.write("system/stores/mvcc.py", "class MVCC:\n    y = 2\n")
        self.update_cleanly()
        second: str = digest(mvcc)
        # edit the manifest, so that src/mvcc.rs is recorded with the first version again:
        manifest: dict = self.manifest()
        for entry in manifest["files"]:
            if entry["path"] == "src/mvcc.rs":
                entry["sources"][0]["sha256"] = first
        self.write_generated("GENERATED_FROM.json", json.dumps(manifest, indent=2))
        # change the source to "x = 1":
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # the order of the hashes is the opposite of the order in which the versions are found:
        self.assertLess(second, first)
        # one diff per old version, the one of "y = 2" first, each naming its own generated file:
        self.assertEqual(
            (
                [
                    "system/stores/mvcc.py: changed; generated from it: src/other.rs",
                    old_label("system/stores/mvcc.py", "class MVCC:\n    y = 2\n"),
                    "+++ system/stores/mvcc.py (now)",
                    "@@ -1,2 +1,2 @@",
                    " class MVCC:",
                    "-    y = 2",
                    "+    x = 1",
                    "system/stores/mvcc.py: changed; generated from it: src/mvcc.rs",
                    old_label("system/stores/mvcc.py", "class MVCC:\n    pass\n"),
                    "+++ system/stores/mvcc.py (now)",
                    "@@ -1,2 +1,2 @@",
                    " class MVCC:",
                    "-    pass",
                    "+    x = 1",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_deleted_source_is_shown_as_deleted(self) -> None:
        """A source that no longer exists is shown as deleted, all its old lines removed.

        Would fail if a missing source made ``diff`` crash or were left out.
        """
        self.update_cleanly()
        (self.root / "system/stores/mvcc.py").unlink()
        self.assertEqual(
            (
                [
                    "system/stores/mvcc.py: deleted; generated from it: src/mvcc.rs",
                    old_label("system/stores/mvcc.py", "class MVCC:\n    pass\n"),
                    "+++ system/stores/mvcc.py (deleted)",
                    "@@ -1,2 +0,0 @@",
                    "-class MVCC:",
                    "-    pass",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_source_added_to_the_first_line_is_shown_as_not_recorded(self) -> None:
        """A source in a file's first line but not in its manifest entry is shown as not recorded, all lines added.

        Would fail if only the sources in the manifest were looked at, so a source added while
        regenerating was not shown before the update.
        """
        self.update_cleanly()
        # after the update, add a second source to the first line:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Mvcc;\n",
        )
        # it is compared with an empty text, so all its lines are added:
        self.assertEqual(
            (
                [
                    "system/stores/versioned.py: named in the first line, not recorded in the manifest; "
                    "generated from it: src/mvcc.rs",
                    "--- system/stores/versioned.py (not recorded)",
                    "+++ system/stores/versioned.py (now)",
                    "@@ -0,0 +1,2 @@",
                    "+class Versioned:",
                    "+    pass",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_source_that_is_not_utf8_is_an_error(self) -> None:
        """A changed source that is not UTF-8 text gives an error instead of a diff.

        Would fail if the decoding error escaped from ``diff``, so the command showed a traceback.
        """
        self.update_cleanly()
        (self.root / "system/stores/mvcc.py").write_bytes(b"class MVCC:\n    \xff\n")
        self.assertEqual(
            (
                [],
                [
                    "system/stores/mvcc.py: not a UTF-8 text file, so it cannot be compared"
                ],
            ),
            script.diff(self.root, []),
        )

    def test_copy_that_is_not_utf8_is_an_error(self) -> None:
        """A changed source whose copy is not UTF-8 text gives an error naming the copy instead of a diff.

        The source was not UTF-8 when it was generated from, so its intact copy is not either. Would
        fail if the copy were decoded without a check, so the decoding error escaped from ``diff`` and
        the command showed a traceback.
        """
        # generate from a source that is not UTF-8, so its copy is not either:
        (self.root / "system/stores/mvcc.py").write_bytes(b"class MVCC:\n    \xff\n")
        self.update_cleanly()
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        # change the source, so diff needs the copy:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            (
                [],
                [f"{COPIES}/{name}: not a UTF-8 text file, so it cannot be compared"],
            ),
            script.diff(self.root, []),
        )

    def test_lines_are_split_at_lf_only(self) -> None:
        """A form feed or a lone CR inside a line of a source stays in that line of the diff, as in git.

        Only the first line changes, so the line with the form feed or CR is shown once, as context.
        Would fail if the texts were split with ``str.splitlines``, which also splits at these
        characters, so the diff showed more lines than the source has and marked them as missing
        their final newline.
        """
        for case, line in {
            "form feed": "    x = 1\f# next page",
            "lone CR": "    x = 1\r# after a CR",
        }.items():
            with self.subTest(case=case):
                # record a source with the special character in its second line, then change only its first line:
                self.write("system/stores/mvcc.py", f"class MVCC:\n{line}\n")
                self.update_cleanly()
                self.write("system/stores/mvcc.py", f"class Mvcc:\n{line}\n")
                # the line with the special character is shown once, as an unchanged line:
                self.assertEqual(
                    (
                        mvcc_diff_head(f"class MVCC:\n{line}\n")
                        + ["-class MVCC:", "+class Mvcc:", f" {line}"],
                        [],
                    ),
                    script.diff(self.root, []),
                )

    def test_missing_manifest_is_an_error(self) -> None:
        """Without a manifest, ``diff`` gives the problem as an error.

        Would fail if ``diff`` crashed on the missing manifest or said that nothing changed.
        """
        self.assertEqual(
            ([], ["generated/rust/GENERATED_FROM.json is missing"]),
            script.diff(self.root, []),
        )

    def test_diff_works_despite_problems_elsewhere(self) -> None:
        """A broken first line in another file and a stray file among the copies do not keep a change from being shown.

        The broken first line is an error; the stray file is the check's business, not the diff's.
        Would fail if ``diff`` refused like ``update`` on any problem, so a developer could not see
        what changed while the generated folder is in the middle of a regeneration.
        """
        # a second source with its own generated file:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/versioned.rs",
            header("system/stores/versioned.py") + "\npub struct Versioned;\n",
        )
        self.update_cleanly()
        # after the update, drop the first line of that file, add a stray file among the copies, and change mvcc.py:
        self.write_generated("src/versioned.rs", "pub struct Versioned;\n")
        self.write(f"{COPIES}/notes.md", "to do\n")
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # diff shows the change of mvcc.py and reports the broken first line as an error:
        self.assertEqual(
            (MVCC_DIFF, [f"src/versioned.rs: {NO_HEADER}"]), script.diff(self.root, [])
        )

    def test_corrupt_copy_is_an_error(self) -> None:
        """A changed source whose copy does not match its name gives an error instead of a diff.

        Would fail if the copy were read without checking its hash, so an edited copy made ``diff``
        show changes that were never made.
        """
        self.update_cleanly()
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        self.write(f"{COPIES}/{name}", "class MVCC:\n    edited = True\n")
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            (
                [],
                [corrupt_copy(name)],
            ),
            script.diff(self.root, []),
        )

    def test_windows_line_endings_alone_are_no_change(self) -> None:
        """A source whose line endings only became CR LF gives the line that nothing changed.

        Would fail if the current source were hashed with its raw bytes, so a Windows checkout showed
        every source as changed.
        """
        self.update_cleanly()
        self.write("system/stores/mvcc.py", "class MVCC:\r\n    pass\r\n")
        self.assertEqual(([NOTHING_CHANGED], []), script.diff(self.root, []))

    def test_source_with_windows_line_endings_shows_only_the_real_change(self) -> None:
        """A source with CR LF line endings and one changed line shows only that line as changed.

        Would fail if the current source were compared with its raw bytes, so every line differed from
        the copy by its CR, or if a CR were left at the end of the lines shown.
        """
        self.update_cleanly()
        self.write("system/stores/mvcc.py", "class MVCC:\r\n    x = 1\r\n")
        self.assertEqual((MVCC_DIFF, []), script.diff(self.root, []))

    def test_missing_final_newline_is_marked_as_git_does(self) -> None:
        """A change that only removes or adds the final newline shows the last line changed, marked as in git.

        Would fail if the diff lost the change (lines compared without their line endings) or left
        out the note ``\\ No newline at end of file`` after the line without one.
        """
        # for each case, the source before and after, and the lines that show the change:
        cases: dict[str, tuple[str, str, list[str]]] = {
            "removed": (
                "class MVCC:\n    pass\n",
                "class MVCC:\n    pass",
                ["-    pass", "+    pass", "\\ No newline at end of file"],
            ),
            "added": (
                "class MVCC:\n    pass",
                "class MVCC:\n    pass\n",
                ["-    pass", "\\ No newline at end of file", "+    pass"],
            ),
        }
        for case, (before, after, changed) in cases.items():
            with self.subTest(newline=case):
                # record the source before, then change it:
                self.write("system/stores/mvcc.py", before)
                self.update_cleanly()
                self.write("system/stores/mvcc.py", after)
                self.assertEqual(
                    (mvcc_diff_head(before) + [" class MVCC:"] + changed, []),
                    script.diff(self.root, []),
                )


class DiffSourcePathTest(GeneratedRepositoryTest):
    """Checks ``diff`` on sources that are missing, outside ``system/``, no longer named or spelled differently."""

    def test_missing_source_named_in_the_first_line_is_an_error(self) -> None:
        """A source named in a first line but not recorded and not on disk is an error.

        Would fail if the missing source were shown as deleted from an empty old version, or made
        ``diff`` crash on reading it.
        """
        self.update_cleanly()
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/gone.py")
            + "\npub struct Mvcc;\n",
        )
        self.assertEqual(
            (
                [],
                [
                    "src/mvcc.rs: its source system/stores/gone.py is named in the first line but does not exist"
                ],
            ),
            script.diff(self.root, []),
        )

    def test_recorded_source_outside_system_is_an_error_and_not_shown(self) -> None:
        """A source in the manifest that is outside ``system/`` is an error, and its content is not printed.

        The manifest is edited by hand to name a file outside the repository, with the recorded hash
        of a copy that exists. Would fail if ``diff`` compared that copy with the file the path leads
        to, so a manifest could print any file of the machine.
        """
        # a file outside the repository:
        (self.root.parent / "outside.py").write_bytes(b"SECRET = 1\n")
        self.update_cleanly()
        # add it to the manifest as a second source of src/mvcc.rs, with the hash of the existing copy of mvcc.py:
        manifest: dict = self.manifest()
        entry: dict = manifest["files"][0]
        entry["sources"].append(
            {
                "sha256": entry["sources"][0]["sha256"],
                "path": "system/../../outside.py",
            }
        )
        self.write_generated("GENERATED_FROM.json", json.dumps(manifest, indent=2))
        # diff reports it as outside system/ and prints nothing:
        self.assertEqual(
            ([], ["src/mvcc.rs: its source system/../../outside.py is not in system/"]),
            script.diff(self.root, []),
        )

    def test_source_outside_system_in_the_first_line_is_an_error_and_not_shown(
        self,
    ) -> None:
        """A source in a first line that is outside ``system/`` is an error, and its content is not printed.

        Would fail if a source named only in the first line were shown as not recorded without the
        check, so a generated file could print any file of the machine.
        """
        # a file outside the repository:
        (self.root.parent / "outside.py").write_bytes(b"SECRET = 1\n")
        self.update_cleanly()
        # after the update, add it to the first line of src/mvcc.rs:
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/../../outside.py")
            + "\npub struct Mvcc;\n",
        )
        self.assertEqual(
            ([], ["src/mvcc.rs: its source system/../../outside.py is not in system/"]),
            script.diff(self.root, []),
        )

    def test_unchanged_source_dropped_from_the_first_line_gives_a_note(self) -> None:
        """A recorded source that the first line no longer names, but that did not change, gives a note.

        No version differs, so the line saying that nothing changed comes first, then the note. Would
        fail if the dropped source were left out (so ``diff`` said only that nothing changed although
        the check reports the file as out of date) or shown with an empty diff.
        """
        # generate src/mvcc.rs from two sources, mvcc.py and versioned.py:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Mvcc;\n",
        )
        self.update_cleanly()
        # after the update, drop versioned.py from the first line, while both sources stay unchanged:
        self.write_generated(
            "src/mvcc.rs", header("system/stores/mvcc.py") + "\npub struct Mvcc;\n"
        )
        # nothing changed, and a note says that the file is no longer generated from versioned.py:
        self.assertEqual(
            (
                [
                    NOTHING_CHANGED,
                    "src/mvcc.rs: no longer generated from system/stores/versioned.py, which did not change",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_changed_source_dropped_from_the_first_line_gives_the_diff_and_a_note(
        self,
    ) -> None:
        """A recorded source that changed and that the first line no longer names gives its diff and a note.

        The note comes after the diffs. Would fail if the note were only given for an unchanged
        source, so the diff did not say that the file is no longer generated from the changed
        source, or if the dropped source's diff were left out.
        """
        # generate src/mvcc.rs from two sources, mvcc.py and versioned.py:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Mvcc;\n",
        )
        self.update_cleanly()
        # after the update, change versioned.py and drop it from the first line:
        self.write("system/stores/versioned.py", "class Versioned:\n    x = 1\n")
        self.write_generated(
            "src/mvcc.rs", header("system/stores/mvcc.py") + "\npub struct Mvcc;\n"
        )
        # the diff of versioned.py, then the note:
        self.assertEqual(
            (
                [
                    "system/stores/versioned.py: changed; generated from it: src/mvcc.rs",
                    old_label(
                        "system/stores/versioned.py", "class Versioned:\n    pass\n"
                    ),
                    "+++ system/stores/versioned.py (now)",
                    "@@ -1,2 +1,2 @@",
                    " class Versioned:",
                    "-    pass",
                    "+    x = 1",
                    "src/mvcc.rs: no longer generated from system/stores/versioned.py, which changed",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_source_whose_name_changed_case_is_shown_as_deleted(self) -> None:
        """A recorded source whose file name now differs in upper and lower case is shown as deleted.

        On a file system that ignores case (macOS, Windows), the old path still opens the renamed
        file. Would fail if ``diff`` only asked whether the old path opens a file, so it said that
        nothing changed although the check reports the source as missing.
        """
        self.update_cleanly()
        # after the update, rename the source to MVCC.py:
        (self.root / "system/stores/mvcc.py").rename(
            self.root / "system/stores/MVCC.py"
        )
        self.assertEqual(
            (
                [
                    "system/stores/mvcc.py: deleted; generated from it: src/mvcc.rs",
                    old_label("system/stores/mvcc.py", "class MVCC:\n    pass\n"),
                    "+++ system/stores/mvcc.py (deleted)",
                    "@@ -1,2 +0,0 @@",
                    "-class MVCC:",
                    "-    pass",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_source_in_the_first_line_spelled_in_another_case_is_an_error(
        self,
    ) -> None:
        """A source named in a first line but not recorded, spelled in another case than its file, is an error.

        Would fail if ``diff`` only asked whether the path opens a file, so on a file system that
        ignores case it showed the file as a source not recorded, although the check reports it as
        missing.
        """
        self.update_cleanly()
        # after the update, add versioned.py, but name it Versioned.py in the first line:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/Versioned.py")
            + "\npub struct Mvcc;\n",
        )
        self.assertEqual(
            (
                [],
                [
                    "src/mvcc.rs: its source system/stores/Versioned.py is named in the first line but does not exist"
                ],
            ),
            script.diff(self.root, []),
        )

    def test_source_path_too_long_for_the_file_system_does_not_crash(self) -> None:
        """A source whose file name is longer than any file system allows is deleted or missing, without a crash.

        The name has 300 characters; asking the system about such a path fails with "File name too
        long". Named only in the first line, it is an error; as a recorded source (the manifest is
        edited by hand), it is shown as deleted. Would fail if ``diff`` asked the system whether the
        path is a file, so the error escaped and the command showed a traceback.
        """
        # a source path with a file name of 300 characters:
        long: str = "system/stores/" + "a" * 300 + ".py"
        self.update_cleanly()
        with self.subTest(source="first line"):
            # name it in the first line next to mvcc.py: an error, as it does not exist:
            self.write_generated(
                "src/mvcc.rs",
                header("system/stores/mvcc.py", long) + "\npub struct Mvcc;\n",
            )
            self.assertEqual(
                (
                    [],
                    [
                        f"src/mvcc.rs: its source {long} is named in the first line but does not exist"
                    ],
                ),
                script.diff(self.root, []),
            )
        with self.subTest(source="recorded"):
            # record it in the manifest in place of mvcc.py, and name only it in the first line: it is shown as deleted:
            manifest: dict = self.manifest()
            manifest["files"][0]["sources"][0]["path"] = long
            self.write_generated("GENERATED_FROM.json", json.dumps(manifest, indent=2))
            self.write_generated("src/mvcc.rs", header(long) + "\npub struct Mvcc;\n")
            self.assertEqual(
                (
                    [
                        f"{long}: deleted; generated from it: src/mvcc.rs",
                        old_label(long, "class MVCC:\n    pass\n"),
                        f"+++ {long} (deleted)",
                        "@@ -1,2 +0,0 @@",
                        "-class MVCC:",
                        "-    pass",
                    ],
                    [],
                ),
                script.diff(self.root, []),
            )


class DiffFirstLineTest(GeneratedRepositoryTest):
    """Checks how ``diff`` reads the sources a first line names: none at all, one named twice, or no file to read."""

    def test_deleted_generated_file_still_shows_the_change_of_its_source(self) -> None:
        """A changed source of a generated file that was deleted (but is still in the manifest) is shown as usual.

        The diff takes the sources from the manifest, so it needs no first line to read. Would fail if
        ``diff`` read the first line of every file in the manifest without checking that the file is
        there, so a file deleted while regenerating made it crash.
        """
        self.update_cleanly()
        (self.generated / "src/mvcc.rs").unlink()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual((MVCC_DIFF, []), script.diff(self.root, []))

    def test_first_line_without_source_gives_a_note_on_the_recorded_one(self) -> None:
        """A first line changed to name no Python source, while the recorded source did not change, gives a note.

        A first line that names no source is read, so the recorded source is no longer named. Would
        fail if such a first line were taken for one that cannot be read, so ``diff`` said only that
        nothing changed although the check reports the file as out of date.
        """
        self.update_cleanly()
        self.write_generated("src/mvcc.rs", NO_SOURCE_HEADER + "\npub struct Mvcc;\n")
        self.assertEqual(
            (
                [
                    NOTHING_CHANGED,
                    "src/mvcc.rs: no longer generated from system/stores/mvcc.py, which did not change",
                ],
                [],
            ),
            script.diff(self.root, []),
        )

    def test_source_named_twice_is_listed_once(self) -> None:
        """A source that is not recorded and named twice in a first line names its generated file once in the heading.

        Would fail if the sources of the first line were taken as they are, so the heading read
        "generated from it: src/mvcc.rs, src/mvcc.rs".
        """
        self.update_cleanly()
        # after the update, add versioned.py and name it twice in the first line:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header(
                "system/stores/mvcc.py",
                "system/stores/versioned.py",
                "system/stores/versioned.py",
            )
            + "\npub struct Mvcc;\n",
        )
        self.assertEqual(
            (
                [
                    "system/stores/versioned.py: named in the first line, not recorded in the manifest; "
                    "generated from it: src/mvcc.rs",
                    "--- system/stores/versioned.py (not recorded)",
                    "+++ system/stores/versioned.py (now)",
                    "@@ -0,0 +1,2 @@",
                    "+class Versioned:",
                    "+    pass",
                ],
                [],
            ),
            script.diff(self.root, []),
        )


class DiffPathsTest(GeneratedRepositoryTest):
    """Checks which generated files ``diff`` looks at: the paths given, unknown ones and duplicates."""

    def test_only_the_given_files_are_shown(self) -> None:
        """Given a generated file, ``diff`` shows only the changes of its sources.

        Would fail if the paths given were ignored and all files of the manifest were shown.
        """
        # a second source with its own generated file:
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/versioned.rs",
            header("system/stores/versioned.py") + "\npub struct Versioned;\n",
        )
        self.update_cleanly()
        # change both sources after the update, then ask diff for src/versioned.rs only:
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.write("system/stores/versioned.py", "class Versioned:\n    x = 1\n")
        self.assertEqual(
            (
                [
                    "system/stores/versioned.py: changed; generated from it: src/versioned.rs",
                    old_label(
                        "system/stores/versioned.py", "class Versioned:\n    pass\n"
                    ),
                    "+++ system/stores/versioned.py (now)",
                    "@@ -1,2 +1,2 @@",
                    " class Versioned:",
                    "-    pass",
                    "+    x = 1",
                ],
                [],
            ),
            script.diff(self.root, ["src/versioned.rs"]),
        )

    def test_unknown_path_gives_the_error_and_no_diff(self) -> None:
        """An unknown path while a source changed gives only the error, not the diff of all files.

        No known file is left to compare, so there is also no line that nothing changed. Would fail
        if no known path made ``diff`` fall back to all files of the manifest, so a mistyped path
        showed changes of files that were not asked for, or if it claimed that no source changed,
        although one did.
        """
        self.update_cleanly()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(([], [UNKNOWN_PATH]), script.diff(self.root, ["src/nope.rs"]))

    def test_known_and_unknown_path_give_the_diff_and_the_error(self) -> None:
        """With one known and one unknown path, ``diff`` gives the diff of the known file and the error of the other.

        Would fail if an unknown path kept the known one from being shown, or were silently dropped.
        """
        self.update_cleanly()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            (MVCC_DIFF, [UNKNOWN_PATH]),
            script.diff(self.root, ["src/nope.rs", "src/mvcc.rs"]),
        )

    def test_duplicate_paths_are_listed_once(self) -> None:
        """A path given twice names its file once in the heading, and an unknown path given twice gives one error.

        Would fail if duplicates were kept, so the heading read "src/mvcc.rs, src/mvcc.rs" and the
        error were printed twice.
        """
        self.update_cleanly()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            (MVCC_DIFF, [UNKNOWN_PATH]),
            script.diff(
                self.root, ["src/mvcc.rs", "src/nope.rs", "src/mvcc.rs", "src/nope.rs"]
            ),
        )


class MainTest(GeneratedRepositoryTest):
    """Checks the command line: output and exit status.

    ``main`` takes the repository root from the script's own location, so the script is copied
    into ``.ci/`` of the temporary repository and loaded from there.
    """

    def setUp(self) -> None:
        """Copies the script into the temporary repository and loads that copy."""
        super().setUp()
        (self.root / ".ci").mkdir()
        shutil.copy(SCRIPT_PATH, self.root / ".ci" / "check_generated.py")
        self.copy: ModuleType = load_script(
            self.root / ".ci" / "check_generated.py", "check_generated_copy"
        )
        self.addCleanup(sys.modules.pop, "check_generated_copy", None)

    def run_main(self, *arguments: str) -> tuple[int, str]:
        """Runs ``main`` with the given arguments and returns its exit status and output."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status: int = self.copy.main(list(arguments))
        return status, output.getvalue()

    def run_diff(self, *paths: str) -> tuple[int, str, str]:
        """Runs ``main`` with ``--diff`` and the given paths and returns its exit status, output and error output."""
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status: int = self.copy.main(["--diff", *paths])
        return status, output.getvalue(), errors.getvalue()

    def test_update_then_check_exits_with_zero(self) -> None:
        """``--update`` writes the manifest silently; the following check says all is up to date.

        Would fail if ``main`` mixed up the two modes or returned the wrong exit status.
        """
        self.assertEqual((0, ""), self.run_main("--update"))
        self.assertTrue(self.manifest_path.is_file())
        self.assertEqual(
            (0, "generated/rust is up to date with its Python sources.\n"),
            self.run_main(),
        )

    def test_problems_are_printed_one_per_line_and_exit_with_one(self) -> None:
        """A check that finds problems prints each on its own line and exits with 1.

        Would fail if the CI job could not fail on stale Rust code because the exit status stayed 0,
        or if the problems were printed in one line.
        """
        self.write_generated("src/lib.rs", "pub mod mvcc;\n")
        self.assertEqual(
            (
                1,
                f"src/lib.rs: {NO_HEADER}\n"
                "generated/rust/GENERATED_FROM.json is missing\n",
            ),
            self.run_main(),
        )

    def test_update_with_problems_exits_with_one(self) -> None:
        """``--update`` with a problem prints it, exits with 1 and leaves the manifest as it was.

        Would fail if a refused update still reported success, so a regeneration script went on as
        if the manifest had been written.
        """
        self.assertEqual((0, ""), self.run_main("--update"))
        before: bytes = self.mark_manifest()
        self.write_generated("src/lib.rs", "pub mod mvcc;\n")
        self.assertEqual((1, f"src/lib.rs: {NO_HEADER}\n"), self.run_main("--update"))
        self.assertEqual(before, self.manifest_path.read_bytes())

    def test_update_dependencies_exits_with_zero(self) -> None:
        """``--update-dependencies`` records a changed Cargo.lock silently and exits with 0, nothing else.

        Would fail if the option were not wired to ``update_dependencies``: the check would leave the
        Cargo.lock entry as it was, and a full update would hide the changed Python source.
        """
        # record a Cargo.lock with a full update:
        self.write_generated("Cargo.lock", "version = 4\n")
        self.assertEqual((0, ""), self.run_main("--update"))
        # change Cargo.lock as a dependency update would, and also the Python source:
        self.append_generated("Cargo.lock", '[[package]]\nname = "rand"\n')
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        # the dependency update prints nothing and records the new Cargo.lock:
        self.assertEqual((0, ""), self.run_main("--update-dependencies"))
        self.assertEqual(
            digest(self.generated / "Cargo.lock"), self.recorded("Cargo.lock")["sha256"]
        )
        # the check still reports the out-of-date Rust file and exits with 1:
        self.assertEqual(
            (
                1,
                "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
                "regenerate it and run the update\n",
            ),
            self.run_main(),
        )

    def test_two_modes_together_are_refused(self) -> None:
        """``--update`` together with ``--update-dependencies`` or with ``--diff`` is a usage error (exit status 2).

        Would fail if the options were not mutually exclusive, so one of them was silently ignored:
        ``--diff --update`` would show the diff and leave the manifest unwritten, or write it.
        """
        for arguments in [
            ["--update", "--update-dependencies"],
            ["--diff", "--update"],
        ]:
            with self.subTest(arguments=arguments):
                # argparse stops with SystemExit, exit status 2 and an error message; no manifest is written:
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    with self.assertRaises(SystemExit) as raised:
                        self.copy.main(arguments)
                self.assertEqual(2, raised.exception.code)
                self.assertIn("not allowed with argument", errors.getvalue())
                self.assertFalse(self.manifest_path.exists())

    def test_diff_without_change_exits_with_zero(self) -> None:
        """``--diff`` without a changed source prints only the line saying so and exits with 0.

        Would fail if the option were not wired to ``diff`` or nothing were printed.
        """
        self.assertEqual((0, ""), self.run_main("--update"))
        self.assertEqual((0, NOTHING_CHANGED + "\n"), self.run_main("--diff"))

    def test_diff_of_an_unknown_file_exits_with_one(self) -> None:
        """``--diff`` of a file that is not in the manifest prints the error to stderr and exits with 1.

        The standard output stays empty, as no known file is left to compare. Would fail if a
        mistyped path were ignored, so the command exited with 0, or if the error went to the
        standard output, where it would mix with the diff, or lost its ``error:``.
        """
        self.assertEqual((0, ""), self.run_main("--update"))
        self.assertEqual(
            (1, "", f"error: {UNKNOWN_PATH}\n"), self.run_diff("src/nope.rs")
        )

    def test_diff_with_a_missing_copy_exits_with_one(self) -> None:
        """``--diff`` of a changed source whose copy is missing prints the recovery hint to stderr and exits with 1.

        Would fail if the missing copy were treated as an empty old version, so every line looked new.
        """
        self.assertEqual((0, ""), self.run_main("--update"))
        # after the update, delete the copy, then change the source:
        name: str = copy_name_of_file(self.root / "system/stores/mvcc.py")
        (self.root / COPIES / name).unlink()
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            (1, "", "error: " + missing_copy(name, "system/stores/mvcc.py") + "\n"),
            self.run_diff("src/mvcc.rs"),
        )

    def test_diff_prints_the_diff_and_the_errors_apart(self) -> None:
        """``--diff`` with one known and one unknown file prints the diff to stdout, the error to stderr, exits with 1.

        Would fail if one error suppressed the diff of the files that are known, or if the diff
        went to stderr.
        """
        self.assertEqual((0, ""), self.run_main("--update"))
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual(
            (1, "".join(line + "\n" for line in MVCC_DIFF), f"error: {UNKNOWN_PATH}\n"),
            self.run_diff("src/mvcc.rs", "src/nope.rs"),
        )

    def test_diff_prints_non_ascii_text_to_an_ascii_console(self) -> None:
        """``--diff`` prints a changed line with non-ASCII letters as UTF-8, also if the console's encoding is ASCII.

        The console is a text stream that encodes as ASCII, as a Windows console or a C locale may.
        Would fail if the diff were printed in the console's encoding, so the first letter outside
        it raised ``UnicodeEncodeError`` and the command showed a traceback instead of the diff.
        """
        self.assertEqual((0, ""), self.run_main("--update"))
        # after the update, change the source to a line with a non-ASCII letter:
        self.write("system/stores/mvcc.py", "class MVCC:\n    name = 'Müller'\n")
        # a console that encodes as ASCII and writes into a byte buffer; run the diff with it as stdout:
        output = io.BytesIO()
        console = io.TextIOWrapper(output, encoding="ascii")
        with contextlib.redirect_stdout(console):
            status: int = self.copy.main(["--diff"])
        console.flush()
        # main switched the console to UTF-8, so the buffer holds the diff with the non-ASCII letter:
        self.assertEqual(0, status)
        self.assertEqual(
            MVCC_DIFF[:-1] + ["+    name = 'Müller'"],
            output.getvalue().decode("utf-8").splitlines(),
        )


class SkillTest(unittest.TestCase):
    """Checks the skill ``.claude/commands/regenerate-rust.md`` against the command line of the script."""

    def test_options_named_by_the_skill_exist(self) -> None:
        """Every option the skill writes after ``.ci/check_generated.py`` is one the script's ``--help`` lists.

        Would fail if an option were renamed or dropped in the script but not in the skill, so that the
        skill would tell Claude to run a command the script refuses.
        """
        # the options the skill writes after the script's name, also across a line break:
        skill: str = (
            REPO_ROOT / ".claude" / "commands" / "regenerate-rust.md"
        ).read_text(encoding="utf-8")
        named: set[str] = set(
            re.findall(r"\.ci/check_generated\.py\s+(--[a-z][a-z-]*)", skill)
        )
        self.assertNotEqual(set(), named, msg="the skill names no option of the script")
        # the options the script itself lists in its help:
        help_text: str = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        listed: set[str] = set(re.findall(r"--[a-z][a-z-]*", help_text))
        self.assertEqual(set(), named - listed)


if __name__ == "__main__":
    unittest.main()
