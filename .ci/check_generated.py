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

"""Check that the generated Rust code in generated/rust/ is up to date with the Python code it is generated from.

The Rust port in ``generated/rust/`` is generated from the Python code in ``system/`` and never edited by hand.
Every generated file names its Python sources in its first line, e.g.::

    // Code generated from system/stores/MVCC.py, system/stores/VersionedKeyValueStore.py. DO NOT EDIT.

or, for a file without a Python counterpart (e.g. the crate root ``src/lib.rs``)::

    // Code generated for the Rust port (no Python source). DO NOT EDIT.

(``//`` in Rust files, ``#`` in TOML files, ``<!-- ... -->`` in Markdown). ``Cargo.lock`` is written by Cargo and needs
no such line. Hidden files (e.g. ``.DS_Store``) and Cargo's build folder ``target/`` are not part of the generated
code. Cargo builds one test program per folder ``tests/<folder>/`` from its ``main.rs`` (``tests/common/`` only holds
the shared ``mod.rs``), and compiles only the test files ``main.rs`` includes as modules.

The manifest ``generated/rust/GENERATED_FROM.json`` records, for every generated file, the start of the SHA-256 (16
hex digits) of each of its Python sources and of the file itself, as they were when the file was generated; line
endings are made LF before hashing, so a checkout with Windows line endings gives the same hashes. The check
compares them with the files as they are now and reports:

- a generated file whose Python source changed, or that dropped a source, since it was generated: the Rust code is
  out of date and must be regenerated;
- a generated file that changed although its sources did not: it was edited by hand;
- a generated file without the first line or that is not UTF-8 text, a missing source, a source outside
  ``system/``, a test folder without ``main.rs``, a test file its ``main.rs`` does not include, hidden tool settings
  (``.cargo/``, ``.rustfmt.toml``, ``.clippy.toml``, at any depth), a symbolic link, a missing or unreadable
  manifest, or a file missing from the manifest or on disk.

One kind of change in the generated folder is allowed without regenerating: a dependency or Rust version update in
``Cargo.toml``, ``Cargo.lock`` and ``rust-toolchain.toml`` (e.g. to fix a finding of the dependency audit). Record it
with ``--update-dependencies``, which rewrites only the entries of these three files: ``--update`` would also record
out-of-date or hand-edited Rust files as current. A later regeneration keeps the versions in these files.

Usage, from the repository root::

    python3 .ci/check_generated.py                         # check; exit status 1 if anything is reported
    python3 .ci/check_generated.py --update                # after regenerating: rewrite the whole manifest
    python3 .ci/check_generated.py --update-dependencies   # after a dependency update: record only the Cargo files

The CI job ``generated_rust_check`` runs the check: it fails on main and in the nightly pipeline, and only warns in
a merge request (see CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

# the folder of the generated code and its manifest, relative to the repository root:
GENERATED: Path = Path("generated/rust")
MANIFEST: str = "GENERATED_FROM.json"
# files written by tools, which carry no "Code generated" line; they are still recorded, so hand edits are found:
WITHOUT_HEADER: frozenset[str] = frozenset({"Cargo.lock"})
# the comment that opens the first line, by file extension; a Markdown comment is closed with " -->":
COMMENT_BY_EXTENSION: dict[str, str] = {".rs": "//", ".toml": "#", ".md": "<!--"}
# the first line of a generated file: a comment naming the Python sources or saying there is none:
HEADER: re.Pattern[str] = re.compile(
    r"^(?P<open>//|#|<!--) Code generated "
    r"(?:from (?P<sources>.+?)|for the Rust port \(no Python source\))\. DO NOT EDIT\."
    r"(?P<close> -->)?$"
)
# how many hex digits of a SHA-256 the manifest records (see digest_of):
DIGEST_LENGTH: int = 16
# the folder the Python sources must be in:
SOURCE_FOLDER: str = "system/"
# a module a test folder's main.rs includes, e.g. "mod test_stores_basics;" or "pub(crate) mod common;":
MODULE: re.Pattern[str] = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;", re.MULTILINE
)
# the files a dependency or Rust version update may change directly (see --update-dependencies):
DEPENDENCY_FILES: frozenset[str] = frozenset(
    {"Cargo.toml", "Cargo.lock", "rust-toolchain.toml"}
)
# hidden tool settings that Cargo, rustfmt or clippy read in the generated folder; hidden files are not part of the
# generated code, so they are rejected instead:
TOOL_SETTINGS: tuple[str, ...] = (".cargo", ".rustfmt.toml", ".clippy.toml")


class RecordedSource(TypedDict):
    """A Python source of a generated file, as recorded in the manifest."""

    sha256: str
    path: str


class RecordedFile(TypedDict):
    """A generated file, as recorded in the manifest.

    The path comes last in each object of the manifest, after the hashes: a hash right after a path such as
    ``.../VersionedKeyValueStore.py`` would look like an API key to the secret scanner gitleaks.
    """

    sha256: str
    sources: list[RecordedSource]
    path: str


@dataclass(frozen=True)
class GeneratedFile:
    """A generated file as it is now: its path in the generated folder, its Python sources and the hashes."""

    # the path relative to the generated folder, with forward slashes, e.g. "src/stores/mvcc.rs":
    path: str
    # the hash of each Python source (see digest_of), by its path relative to the repository root:
    sources: dict[str, str]
    # the hash of the file itself:
    sha256: str


def digest_of(path: Path) -> str:
    """Returns the start of the SHA-256 of a file's bytes with LF line endings, written as ``sha256:<16 hex digits>``.

    Windows line endings (CR LF) are made LF first, so a checkout that converts line endings gives the same hash.
    16 hex digits (64 bits) suffice: the hash only shows whether a file changed by accident; it is no protection
    against deliberate changes, which the update would record anyway.

    @param path: the file
    @return: the digest with its prefix
    """
    digest: str = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return "sha256:" + digest[:DIGEST_LENGTH]


def exists_exactly(root: Path, path: str) -> bool:
    """Returns whether a file exists with exactly this spelling, also on a file system that ignores case (macOS).

    @param root: the repository root
    @param path: the file, relative to the root, with forward slashes
    @return: True if every part of the path exists in its folder with the same upper and lower case
    """
    folder: Path = root
    for part in path.split("/"):
        names: set[str] = (
            {entry.name for entry in folder.iterdir()} if folder.is_dir() else set()
        )
        if part not in names:
            return False
        folder = folder / part
    return folder.is_file()


def generated_paths(root: Path) -> list[str]:
    """Returns the files of the generated folder that belong to the generated code, sorted.

    Left out are the manifest itself, hidden files and folders (e.g. ``.DS_Store``) and Cargo's build folder
    ``target/``, which is not entered at all.

    @param root: the repository root
    @return: the paths relative to the generated folder, with forward slashes
    """
    folder: Path = root / GENERATED
    paths: list[str] = []
    for directory, subfolders, files in os.walk(folder):
        relative: Path = Path(directory).relative_to(folder)
        # prune in place, so os.walk does not enter them:
        subfolders[:] = [
            name
            for name in subfolders
            if not name.startswith(".")
            and not (relative == Path(".") and name == "target")
        ]
        paths += [
            (relative / name).as_posix()
            for name in files
            if not name.startswith(".") and (relative / name).as_posix() != MANIFEST
        ]
    return sorted(paths)


def sources_of(root: Path, path: str) -> tuple[list[str] | None, str | None]:
    """Reads the Python sources a generated file names in its first line.

    @param root: the repository root
    @param path: the file, relative to the generated folder
    @return: the source paths (empty for a file without a Python source) and no problem, or None and the problem
    """
    if path in WITHOUT_HEADER:
        return [], None
    try:
        text: str = (root / GENERATED / path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, f"{path}: not a UTF-8 text file, so it cannot carry the first line"
    lines: list[str] = text.splitlines()
    match: re.Match[str] | None = HEADER.match(lines[0]) if lines else None
    expected: str | None = COMMENT_BY_EXTENSION.get(Path(path).suffix)
    # the comment must fit the file type, and only a Markdown comment is closed with "-->":
    if match is not None and (
        (expected is not None and match.group("open") != expected)
        or (match.group("open") == "<!--") != (match.group("close") is not None)
    ):
        match = None
    if match is None:
        return (
            None,
            f'{path}: the first line is not a "Code generated ... DO NOT EDIT." comment',
        )
    if match.group("sources") is None:
        return [], None
    return [source.strip() for source in match.group("sources").split(",")], None


def source_problem(root: Path, path: str, sources: list[str]) -> str | None:
    """Checks that the Python sources of a generated file are files in ``system/``, spelled exactly.

    @param root: the repository root
    @param path: the generated file, relative to the generated folder
    @param sources: its sources, relative to the repository root
    @return: the problem, or None if all sources are fine
    """
    folder: Path = (root / SOURCE_FOLDER).resolve()
    outside: list[str] = [
        source
        for source in sources
        if not source.startswith(SOURCE_FOLDER)
        or ".." in Path(source).parts
        or not (root / source).resolve().is_relative_to(folder)
    ]
    if outside:
        return f"{path}: its source {', '.join(outside)} is not in {SOURCE_FOLDER}"
    missing: list[str] = [
        source for source in sources if not exists_exactly(root, source)
    ]
    if missing:
        return f"{path}: its source {', '.join(missing)} does not exist"
    return None


def without_comments(text: str) -> str:
    """Removes Rust comments from source code, so a module in a comment does not count as included.

    Block comments may contain block comments (``/* a /* b */ c */``), as in Rust; strings are not looked at, which
    is enough for the few lines of a test folder's ``main.rs``.

    @param text: Rust source code
    @return: the code with every ``//`` and ``/* ... */`` comment replaced by a space
    """
    result: list[str] = []
    depth: int = 0
    index: int = 0
    while index < len(text):
        pair: str = text[index : index + 2]
        if pair == "/*":
            depth += 1
            index += 2
        elif pair == "*/" and depth > 0:
            depth -= 1
            index += 2
            if depth == 0:
                result.append(" ")
        elif depth > 0:
            index += 1
        elif pair == "//":
            while index < len(text) and text[index] != "\n":
                index += 1
        else:
            result.append(text[index])
            index += 1
    return "".join(result)


def module_problems(root: Path, paths: list[str]) -> list[str]:
    """Checks that every test folder has a main.rs and that it includes all test files of that folder.

    Cargo builds one test program per folder ``tests/<folder>/`` from its ``main.rs``; a folder without one, or a file
    that ``main.rs`` does not include as a module, is not compiled, so its tests would be lost without any error. Only
    files directly in a test folder are checked.

    @param root: the repository root
    @param paths: the generated files, relative to the generated folder
    @return: one line per test folder without main.rs and per test file that is not included
    """
    problems: list[str] = []
    # a test folder needs a main.rs, unless it only holds a shared mod.rs (as tests/common/ does):
    test_folders: set[Path] = {
        Path(path).parent
        for path in paths
        if Path(path).parent.parent == Path("tests") and Path(path).suffix == ".rs"
    }
    for folder in sorted(test_folders):
        names: set[str] = {
            Path(path).name for path in paths if Path(path).parent == folder
        }
        rust_files: set[str] = {name for name in names if name.endswith(".rs")}
        if "main.rs" not in rust_files and rust_files - {"mod.rs"}:
            problems.append(
                f"{folder.as_posix()}/: a test folder without main.rs; Cargo would not build its tests"
            )
    for main in (path for path in paths if Path(path).name == "main.rs"):
        folder: Path = Path(main).parent
        if folder.parent != Path("tests"):
            continue
        try:
            text: str = (root / GENERATED / main).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # already reported as not a UTF-8 text file by sources_of:
            continue
        included: set[str] = set(MODULE.findall(without_comments(text)))
        problems += [
            f"{path}: not included as a module by {main}"
            for path in paths
            if Path(path).parent == folder
            and Path(path).suffix == ".rs"
            and Path(path).name != "main.rs"
            and Path(path).stem not in included
        ]
    return problems


def tool_settings_problems(root: Path) -> list[str]:
    """Rejects hidden tool settings in the generated folder: ``.cargo/``, ``.rustfmt.toml`` and ``.clippy.toml``.

    Hidden files and folders are not part of the generated code, but Cargo reads ``.cargo/config.toml`` when it builds
    and tests the code, and rustfmt and clippy read their settings in the CI job ``rust_test``, so they could change
    the build or the checks without the check noticing.

    @param root: the repository root
    @return: one line per such file, folder or symbolic link found
    """
    folder: Path = root / GENERATED
    problems: list[str] = []
    for directory, subfolders, files in os.walk(folder):
        relative: Path = Path(directory).relative_to(folder)
        # rustfmt also reads a .rustfmt.toml next to the files it formats, so every folder is searched:
        problems += [
            f"{(relative / name).as_posix()}: hidden tool settings are not allowed in the generated code"
            for name in sorted(subfolders + files)
            if name in TOOL_SETTINGS
        ]
        subfolders[:] = [
            name
            for name in subfolders
            if not (relative == Path(".") and name == "target")
        ]
    return problems


def symbolic_link_problems(root: Path) -> list[str]:
    """Rejects symbolic links in the generated folder.

    A link to a folder is not followed when the files are listed, so its files would be neither recorded nor
    checked, although Cargo compiles them; a link to nothing cannot be read. Generated code never needs a link.

    @param root: the repository root
    @return: one line per symbolic link, outside Cargo's build folder target/
    """
    folder: Path = root / GENERATED
    problems: list[str] = []
    for directory, subfolders, files in os.walk(folder):
        relative: Path = Path(directory).relative_to(folder)
        problems += [
            f"{(relative / name).as_posix()}: a symbolic link, not allowed in the generated code"
            for name in sorted(subfolders + files)
            if (Path(directory) / name).is_symlink()
        ]
        subfolders[:] = [
            name
            for name in subfolders
            if not (relative == Path(".") and name == "target")
        ]
    return problems


def current_files(root: Path) -> tuple[list[GeneratedFile], list[str]]:
    """Reads every generated file as it is now, with the hashes of its Python sources.

    @param root: the repository root
    @return: the files that could be read, and the problems found while reading (first line, sources, test folders
        and modules, hidden tool settings)
    """
    paths: list[str] = generated_paths(root)
    files: list[GeneratedFile] = []
    problems: list[str] = []
    links: list[str] = symbolic_link_problems(root)
    for path in paths:
        if any(link.startswith(f"{path}:") for link in links):
            continue
        sources, problem = sources_of(root, path)
        if sources is not None:
            problem = source_problem(root, path, sources)
        if problem is not None:
            problems.append(problem)
            continue
        files.append(
            GeneratedFile(
                path,
                {source: digest_of(root / source) for source in sources},
                digest_of(root / GENERATED / path),
            )
        )
    return (
        files,
        problems
        + module_problems(
            root,
            [
                path
                for path in paths
                if not any(link.startswith(f"{path}:") for link in links)
            ],
        )
        + tool_settings_problems(root)
        + links,
    )


def read_manifest(root: Path) -> tuple[dict[str, RecordedFile] | None, str | None]:
    """Reads the manifest.

    @param root: the repository root
    @return: the recorded files by path and no problem, or None and the problem (missing or unreadable manifest)
    """
    manifest_path: Path = root / GENERATED / MANIFEST
    if not manifest_path.is_file():
        return None, f"{(GENERATED / MANIFEST).as_posix()} is missing"
    try:
        files: list[RecordedFile] = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )["files"]
        # every entry needs all its fields, so the comparison in check() cannot fail on a missing one:
        for file in files:
            if not isinstance(file["path"], str) or not isinstance(file["sha256"], str):
                raise TypeError(f"entry {file!r}")
            for source in file["sources"]:
                if not isinstance(source["path"], str) or not isinstance(
                    source["sha256"], str
                ):
                    raise TypeError(f"source {source!r}")
        return {file["path"]: file for file in files}, None
    except (ValueError, KeyError, TypeError) as error:
        return (
            None,
            f"{(GENERATED / MANIFEST).as_posix()} cannot be read ({error!r}); run the update after regenerating",
        )


def check(root: Path) -> list[str]:
    """Compares the generated files as they are now with the manifest.

    @param root: the repository root
    @return: one line per problem; empty if the generated code is up to date
    """
    files, problems = current_files(root)
    recorded, problem = read_manifest(root)
    if recorded is None:
        return problems + [str(problem)]
    for file in files:
        entry: RecordedFile | None = recorded.get(file.path)
        if entry is None:
            problems.append(f"{file.path}: not in the manifest")
            continue
        recorded_sources: dict[str, str] = {
            source["path"]: source["sha256"] for source in entry["sources"]
        }
        changed: list[str] = [
            source
            for source, digest in file.sources.items()
            if recorded_sources.get(source) != digest
        ]
        dropped: list[str] = sorted(set(recorded_sources) - set(file.sources))
        if changed or dropped:
            names: str = (
                ", ".join(changed)
                if changed
                else "its list of sources (" + ", ".join(dropped) + " dropped)"
            )
            problems.append(
                f"{file.path}: out of date, {names} changed since it was generated; regenerate it and run the update"
            )
        elif entry["sha256"] != file.sha256:
            problems.append(
                f"{file.path}: edited by hand; change the Python source and regenerate instead"
            )
    # files that exist but had a problem above are not also reported as missing (the path starts each problem):
    on_disk: set[str] = {file.path for file in files} | {
        problem.split(":")[0] for problem in problems
    }
    problems += [
        f"{path}: in the manifest, but not on disk"
        for path in sorted(set(recorded) - on_disk)
    ]
    return problems


def current_commit(root: Path) -> str:
    """Returns the short hash of the commit checked out, for information in the manifest.

    @param root: the repository root
    @return: the short hash, or an empty string outside a git repository or without git
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        return ""


def update(root: Path) -> list[str]:
    """Rewrites the manifest from the generated files as they are now; call it right after regenerating.

    @param root: the repository root
    @return: the problems that keep the manifest from being written (first line, sources, test folders and modules,
        hidden tool settings, a manifest that is a symbolic link); empty on success
    """
    files, problems = current_files(root)
    if problems:
        return problems
    return write_manifest(root, [entry_of(file) for file in files])


def update_dependencies(root: Path) -> list[str]:
    """Rewrites only the manifest entries of Cargo.toml, Cargo.lock and rust-toolchain.toml, after a dependency update.

    Every other entry stays as it is, so out-of-date or hand-edited Rust files are still reported afterwards.

    @param root: the repository root
    @return: the problems that keep the manifest from being written (missing or unreadable manifest, a problem with
        one of the three files, a manifest that is a symbolic link); empty on success
    """
    recorded, problem = read_manifest(root)
    if recorded is None:
        return [str(problem)]
    files, problems = current_files(root)
    dependency_problems: list[str] = [
        problem for problem in problems if problem.split(":")[0] in DEPENDENCY_FILES
    ]
    if dependency_problems:
        return dependency_problems
    # a dependency file added or removed by the update is added to or removed from the manifest, too:
    for path in DEPENDENCY_FILES:
        recorded.pop(path, None)
    for file in files:
        if file.path in DEPENDENCY_FILES:
            recorded[file.path] = entry_of(file)
    return write_manifest(root, [recorded[path] for path in sorted(recorded)])


def entry_of(file: GeneratedFile) -> RecordedFile:
    """Returns the manifest entry of a generated file, with the path last (see RecordedFile).

    @param file: the generated file as it is now
    @return: its entry
    """
    return {
        "sha256": file.sha256,
        "sources": [
            {"sha256": digest, "path": source}
            for source, digest in file.sources.items()
        ],
        "path": file.path,
    }


def write_manifest(root: Path, entries: list[RecordedFile]) -> list[str]:
    """Writes the manifest with the given entries, unless it is a symbolic link.

    @param root: the repository root
    @param entries: the entries, sorted by path
    @return: the problem if the manifest is a symbolic link; empty if it was written
    """
    manifest_path: Path = root / GENERATED / MANIFEST
    if manifest_path.is_symlink():
        return [
            f"{(GENERATED / MANIFEST).as_posix()} is a symbolic link; it is not written through"
        ]
    manifest: dict[str, object] = {
        # for information only, the commit checked out while regenerating (the regeneration itself is committed
        # after the update); the check compares content hashes, so it does not depend on the git history:
        "generated_at_commit": current_commit(root),
        "files": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return []


def main(arguments: list[str]) -> int:
    """Runs the check, the update with ``--update`` or the dependency update with ``--update-dependencies``.

    @param arguments: the command line arguments without the program name
    @return: the exit status: 0 if the generated code is up to date (or the manifest was written), otherwise 1
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0]
    )
    mode: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--update", action="store_true", help="rewrite the manifest after regenerating"
    )
    mode.add_argument(
        "--update-dependencies",
        action="store_true",
        help="record only Cargo.toml, Cargo.lock and rust-toolchain.toml after a dependency update",
    )
    options: argparse.Namespace = parser.parse_args(arguments)
    root: Path = Path(__file__).resolve().parents[1]
    problems: list[str]
    if options.update:
        problems = update(root)
    elif options.update_dependencies:
        problems = update_dependencies(root)
    else:
        problems = check(root)
    for problem in problems:
        print(problem)
    if not problems and not options.update and not options.update_dependencies:
        print(f"{GENERATED.as_posix()} is up to date with its Python sources.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
