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
developer does right after regenerating), changes something, and calls ``check``. The real
``generated/rust/`` folder is checked by a separate CI job, not here.

``.ci`` is not an importable package, so the module is loaded from its file path.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
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


script: ModuleType = load_script()
SYMLINKS: bool = symlinks_work()

# the first line of a generated file without a Python source, in Rust:
NO_SOURCE_HEADER: str = (
    "// Code generated for the Rust port (no Python source). DO NOT EDIT."
)
# what the script reports for a file without a valid first line:
NO_HEADER: str = 'the first line is not a "Code generated ... DO NOT EDIT." comment'


def header(*sources: str) -> str:
    """Returns the first line of a generated Rust file that names the given Python sources."""
    return f"// Code generated from {', '.join(sources)}. DO NOT EDIT."


def digest(path: Path) -> str:
    """Returns the hash the manifest is expected to record for a file, computed independently of the script.

    The manifest records the first 16 hex digits of the SHA-256, after the prefix ``sha256:``.
    """
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]


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
        """Puts a marker into the manifest's commit field and returns the manifest's bytes.

        A refused update must leave these bytes as they are; a rewrite would replace the marker by
        the current commit, so it shows even if the files recorded are the same.
        """
        manifest: dict = self.manifest()
        manifest["generated_at_commit"] = "marker of the manifest before"
        self.write_generated("GENERATED_FROM.json", json.dumps(manifest, indent=2))
        return self.manifest_path.read_bytes()


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
        for path in [
            self.root / "system/stores/mvcc.py",
            self.generated / "src/mvcc.rs",
        ]:
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual([], script.check(self.root))

    def test_update_records_prefixed_hashes_with_the_path_last(self) -> None:
        """Each entry records ``sha256:``-prefixed hashes of the file and its sources, with the path last.

        Would fail if a hash were not the start of the SHA-256 of the bytes, lost its prefix, or came
        after a path, where the secret scanner gitleaks takes it for an API key.
        """
        self.update_cleanly()
        entry: dict = self.recorded("src/mvcc.rs")
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
        self.assertEqual(["sha256", "sources", "path"], list(entry))
        self.assertEqual(["sha256", "path"], list(entry["sources"][0]))

    def test_update_works_without_git(self) -> None:
        """Without git on the search path, ``update`` still writes the manifest, with an empty commit.

        Would fail if a missing git program made ``update`` crash, e.g. in a minimal container.
        """
        with mock.patch.dict(os.environ, {"PATH": ""}):
            self.update_cleanly()
        self.assertEqual("", self.manifest()["generated_at_commit"])


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
        self.write_generated("GENERATED_FROM.json", '{"files": [')
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
        """A manifest without ``files``, in the older format, or with an incomplete entry is reported as unreadable.

        Would fail if a ``KeyError`` or ``TypeError`` escaped from ``check`` for a manifest written
        by an older version of the script or edited by hand. The incomplete entries otherwise match
        the files on disk, so ``check`` reaches the comparison that needs the missing field.
        """
        source: dict[str, str] = {
            "sha256": digest(self.root / "system/stores/mvcc.py"),
            "path": "system/stores/mvcc.py",
        }
        file_digest: str = digest(self.generated / "src/mvcc.rs")

        def manifest_with(entry: dict) -> str:
            """Returns a manifest whose only entry is the given one."""
            return json.dumps({"generated_at_commit": "abc1234", "files": [entry]})

        expected: dict[str, str] = {
            '{"generated_at_commit": "abc1234"}': "KeyError('files')",
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


class OutOfDateTest(GeneratedRepositoryTest):
    """Checks that a changed Python source makes its generated files out of date."""

    def test_changed_source_is_reported_by_name(self) -> None:
        """A Python source changed after generating makes the file out of date, naming the source.

        Would fail if the source hashes were not compared, so stale Rust code would pass the check.
        """
        self.update_cleanly()
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
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Mvcc;\n",
        )
        self.update_cleanly()
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
        self.write("system/stores/versioned.py", "class Versioned:\n    pass\n")
        self.write_generated(
            "src/mvcc.rs",
            header("system/stores/mvcc.py", "system/stores/versioned.py")
            + "\npub struct Mvcc;\n",
        )
        self.update_cleanly()
        self.write_generated(
            "src/mvcc.rs", header("system/stores/mvcc.py") + "\npub struct Mvcc;\n"
        )
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
        self.write_generated("src/lib.rs", NO_SOURCE_HEADER + "\npub mod mvcc;\n")
        self.update_cleanly()
        self.assertEqual([], self.recorded("src/lib.rs")["sources"])
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
        self.write("docs/notes.py", "x = 1\n")
        # outside the repository root, but still inside the temporary directory:
        (self.root.parent / "outside.py").write_bytes(b"x = 1\n")
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

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_source_linked_to_outside_system_is_reported(self) -> None:
        """A source in ``system/`` that is a symbolic link to a file outside ``system/`` is reported.

        Would fail if only the spelling of the path were checked, so a link could make any file of
        the machine a source.
        """
        self.write("outside.py", "x = 1\n")
        os.symlink(self.root / "outside.py", self.root / "system/stores/link.py")
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
        self.write_generated("target/debug/build.log", "compiled\n")
        self.update_cleanly()
        self.assertEqual(["src/mvcc.rs"], self.recorded_paths())
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
        self.write_generated(".DS_Store", "finder\n")
        self.write_generated("src/.DS_Store", "finder\n")
        self.write_generated(".idea/workspace.xml", "<project/>\n")
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
        self.write_generated(
            "tests/stores/main.rs",
            NO_SOURCE_HEADER + "\npub mod test_basics;\npub(crate) mod test_extra;\n",
        )
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
        self.write_generated(
            "tests/stores/main.rs",
            NO_SOURCE_HEADER
            + "\nmod test_basics;\n// mod test_line;\n/* mod test_block; */\n"
            "/*\nmod test_lines;\n*/\n"
            "/* outer /* inner */ mod test_nested; */\n",
        )
        for name in ["test_line", "test_block", "test_lines", "test_nested"]:
            self.write_generated(
                f"tests/stores/{name}.rs", header("system/stores/mvcc.py") + "\n"
            )
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
    """Checks that the generated folder holds no hidden tool settings: ``.cargo``, ``.rustfmt.toml``, ``.clippy.toml``."""

    def problem(self, name: str) -> str:
        """Returns what the script reports for hidden tool settings, by their path in the generated folder."""
        return f"{name}: hidden tool settings are not allowed in the generated code"

    def test_tool_settings_are_reported(self) -> None:
        """A ``.cargo/`` folder, a ``.rustfmt.toml`` and a ``.clippy.toml`` are each reported; ``update`` writes nothing.

        Would fail if one of them were ignored like any other hidden file, although Cargo, rustfmt
        or clippy read it and so could build or check the code differently from what the check has seen.
        """
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        self.write_generated(
            ".cargo/config.toml", '[build]\nrustflags = ["-Awarnings"]\n'
        )
        self.write_generated(".rustfmt.toml", "max_width = 200\n")
        self.write_generated(".clippy.toml", "too-many-arguments-threshold = 99\n")
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
        configuration: Path = self.root.parent / "configuration"
        configuration.mkdir()
        (configuration / "config.toml").write_bytes(b"[build]\n")
        self.update_cleanly()
        before: bytes = self.mark_manifest()
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


@unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
class SymbolicLinkTest(GeneratedRepositoryTest):
    """Checks that the generated folder holds no symbolic links."""

    def test_symbolic_links_are_reported(self) -> None:
        """A link to a file, a link to a folder and a link to nothing are each reported; ``update`` writes nothing.

        Would fail if links were listed like files: the files in a linked folder would be neither
        recorded nor checked although Cargo compiles them, and a link to nothing cannot be read.
        """
        outside: Path = self.root.parent / "outside"
        outside.mkdir()
        (outside / "extra.rs").write_bytes((NO_SOURCE_HEADER + "\n").encode("utf-8"))
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        os.symlink(self.generated / "src/mvcc.rs", self.generated / "src/alias.rs")
        os.symlink(self.root.parent / "missing.rs", self.generated / "src/dangling.rs")
        os.symlink(outside, self.generated / "src/linked")
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
        self.write_generated(
            "tests/stores/test_basics.rs", header("system/stores/mvcc.py") + "\n"
        )
        os.symlink(
            self.root.parent / "missing.rs", self.generated / "tests/stores/main.rs"
        )
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
        self.write_generated(
            "tests/stores/main.rs", NO_SOURCE_HEADER + "\nmod test_basics;\n"
        )
        self.write_generated(
            "tests/stores/test_basics.rs", header("system/stores/mvcc.py") + "\n"
        )
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


class UpdateDependenciesTest(GeneratedRepositoryTest):
    """Checks ``update_dependencies``, which records only Cargo.toml, Cargo.lock and rust-toolchain.toml anew."""

    def setUp(self) -> None:
        """Adds the three dependency files and writes the manifest."""
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
        self.append_generated("Cargo.lock", 'version = "0.9.0"\n')
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
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
        self.append_generated("Cargo.toml", 'serde = "1"\n')
        self.append_generated("src/mvcc.rs", "pub fn patched() {}\n")
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
        self.write_generated("src/lib.rs", "pub mod mvcc;\n")
        self.append_generated("Cargo.lock", 'version = "0.9.0"\n')
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
        (self.generated / "rust-toolchain.toml").unlink()
        self.update_cleanly()
        self.write_generated(
            "rust-toolchain.toml",
            "# Code generated for the Rust port (no Python source). DO NOT EDIT.\n"
            '[toolchain]\nchannel = "1.81"\n',
        )
        self.assertEqual([], script.update_dependencies(self.root))
        self.assertEqual(
            digest(self.generated / "rust-toolchain.toml"),
            self.recorded("rust-toolchain.toml")["sha256"],
        )
        self.assertEqual([], script.check(self.root))

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

    @unittest.skipUnless(SYMLINKS, "this system cannot create symbolic links")
    def test_update_does_not_write_through_a_linked_manifest(self) -> None:
        """If the manifest is a symbolic link, ``update`` refuses and the file it points to is unchanged.

        Would fail if ``update`` wrote through the link and so overwrote a file anywhere on the machine.
        """
        self.write("elsewhere.json", "keep me\n")
        os.symlink(self.root / "elsewhere.json", self.manifest_path)
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
        self.update_cleanly()
        before: bytes = self.mark_manifest()
        elsewhere: Path = self.root / "elsewhere.json"
        self.manifest_path.rename(elsewhere)
        os.symlink(elsewhere, self.manifest_path)
        self.assertEqual(
            [
                "generated/rust/GENERATED_FROM.json is a symbolic link; it is not written through"
            ],
            script.update_dependencies(self.root),
        )
        self.assertEqual(before, elsewhere.read_bytes())


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
        self.write_generated("Cargo.lock", "version = 4\n")
        self.assertEqual((0, ""), self.run_main("--update"))
        self.append_generated("Cargo.lock", '[[package]]\nname = "rand"\n')
        self.write("system/stores/mvcc.py", "class MVCC:\n    x = 1\n")
        self.assertEqual((0, ""), self.run_main("--update-dependencies"))
        self.assertEqual(
            digest(self.generated / "Cargo.lock"), self.recorded("Cargo.lock")["sha256"]
        )
        self.assertEqual(
            (
                1,
                "src/mvcc.rs: out of date, system/stores/mvcc.py changed since it was generated; "
                "regenerate it and run the update\n",
            ),
            self.run_main(),
        )

    def test_both_update_modes_are_refused(self) -> None:
        """``--update`` together with ``--update-dependencies`` is a usage error (exit status 2).

        Would fail if the two options were not mutually exclusive, so one of them was silently ignored.
        """
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as raised:
                self.copy.main(["--update", "--update-dependencies"])
        self.assertEqual(2, raised.exception.code)
        self.assertIn("not allowed with argument", errors.getvalue())
        self.assertFalse(self.manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
