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

# This module exceeds pylint's limit of 1000 lines, as it holds the check, the updates and the diff of the generated
# code, which share their helpers.
# pylint: disable=too-many-lines
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
  manifest, or a file missing from the manifest or on disk;
- a missing or corrupt copy of a recorded Python source, another file or folder in the folder of the copies, or that
  folder (or ``generated/``) being a symbolic link or no folder.

The update keeps a copy of every recorded source version in ``generated/python_sources/<16 hex digits>.txt``, named by
its hash and never deleted, so that ``--diff`` can show what changed in a source since a generated file was generated
from it, also after squash merges.

One kind of change in the generated folder is allowed without regenerating: a dependency or Rust version update in
``Cargo.toml``, ``Cargo.lock`` and ``rust-toolchain.toml`` (e.g. to fix a finding of the dependency audit). Record it
with ``--update-dependencies``, which rewrites only the entries of these three files: ``--update`` would also record
out-of-date or hand-edited Rust files as current. A later regeneration keeps the versions in these files.

Usage, from the repository root::

    python3 .ci/check_generated.py                         # check; exit status 1 if anything is reported
    python3 .ci/check_generated.py --update                # after regenerating: rewrite the whole manifest
    python3 .ci/check_generated.py --update-dependencies   # after a dependency update: record only the Cargo files
    python3 .ci/check_generated.py --diff [FILE ...]       # before regenerating: what changed in the Python sources
                                                           # (FILE relative to generated/rust/; all files if none)

The CI job ``generated_rust_check`` runs the check: it fails on main and in the nightly pipeline, and only warns in
a merge request (see CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple, TypedDict

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
# the copies of the Python sources, one per recorded version, named by its hash (see store_copies), relative to the
# repository root; besides the copies, the folder holds only its README (and hidden files, which are ignored):
COPIES: Path = Path("generated/python_sources")
COPIES_README: str = "README.md"
COPY_NAME: re.Pattern[str] = re.compile(rf"[0-9a-f]{{{DIGEST_LENGTH}}}\.txt")
# a hash as the manifest records it (see digest_of); a hash is also the name of a copy, so nothing else is accepted:
DIGEST: re.Pattern[str] = re.compile(rf"sha256:[0-9a-f]{{{DIGEST_LENGTH}}}")
# the states --diff shows for an old version of a source:
CHANGED: str = "changed"
DELETED: str = "deleted"
NOT_RECORDED: str = "named in the first line, not recorded in the manifest"
# the update records every Rust file as generated from the current sources, so it must not run before every Rust file
# the check reports as out of date or edited by hand is regenerated:
REGENERATE_FIRST: str = (
    "regenerate every Rust file the check reports as out of date or edited by hand first"
)
# how to get back the copy of a current source version: the update writes it from the source:
CURRENT_RECOVERY: str = (
    f"{REGENERATE_FIRST}, then run the update to write it, and commit it"
)
# how to get back the copy of an older source version: from the commit that added it, as the update never changes a
# copy it wrote; if git has none, or a corrupt one (the pipeline of a merge request only warns), the old text is lost,
# and the Rust files of the source are regenerated from the current one:
RECOVERY: str = (
    "find the commit that added it with `git log --all --diff-filter=A --format=%H -n 1 -- {copy}` and restore it "
    "with `git checkout <commit> -- {copy}`; if git finds no commit, or the check reports the restored copy as "
    "corrupt, delete the copy, regenerate every Rust file generated from {source} and every Rust file the check "
    "reports as out of date or edited by hand, then run the update"
)


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


class SourceVersion(NamedTuple):
    """A version of a Python source that generated files were generated from (see --diff)."""

    # the source, relative to the repository root:
    source: str
    # its recorded hash, or None for a source named in a first line but not recorded in the manifest:
    digest: str | None


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
    against deliberate changes, which the update would record anyway. The hash of a Python source is also the name of
    its copy (see store_copies).

    @param path: the file
    @return: the digest with its prefix
    """
    return digest_of_bytes(lf_bytes(path))


def lf_bytes(path: Path) -> bytes:
    """Returns a file's bytes with Windows line endings (CR LF) made LF: the bytes that are hashed and copied.

    @param path: the file
    @return: its bytes with LF line endings
    """
    return path.read_bytes().replace(b"\r\n", b"\n")


def digest_of_bytes(data: bytes) -> str:
    """Returns the start of the SHA-256 of the given bytes, written as ``sha256:<16 hex digits>`` (see digest_of).

    @param data: the bytes
    @return: the digest with its prefix
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()[:DIGEST_LENGTH]


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


def outside_source_folder(root: Path, sources: list[str]) -> list[str]:
    """Returns the sources that are not in ``system/`` (also through ``..`` or a symbolic link).

    @param root: the repository root
    @param sources: source paths, relative to the repository root
    @return: the sources outside ``system/``, in their order
    """
    folder: Path = (root / SOURCE_FOLDER).resolve()
    return [
        source
        for source in sources
        if not source.startswith(SOURCE_FOLDER) or ".." in Path(source).parts
        # a NUL character makes resolve() fail, and no file in system/ has one:
        or "\0" in source or not (root / source).resolve().is_relative_to(folder)
    ]


def source_problem(root: Path, path: str, sources: list[str]) -> str | None:
    """Checks that the Python sources of a generated file are files in ``system/``, spelled exactly.

    @param root: the repository root
    @param path: the generated file, relative to the generated folder
    @param sources: its sources, relative to the repository root
    @return: the problem, or None if all sources are fine
    """
    outside: list[str] = outside_source_folder(root, sources)
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
    # os.walk would follow a link at its start, and the update would write the manifest through it; the files
    # behind such a link are still checked below, so that a link among them is reported, too:
    problems: list[str] = [
        f"{path.relative_to(root).as_posix()}: a symbolic link; it must be a real folder"
        for path in (folder.parent, folder)
        if path.is_symlink()
    ]
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


def copy_name(digest: str) -> str:
    """Returns the file name of the copy of a Python source with the given hash, e.g. ``0123456789abcdef.txt``.

    @param digest: the hash, as recorded in the manifest (``sha256:<16 hex digits>``, see DIGEST)
    @return: the file name in the folder of the copies
    """
    return digest.removeprefix("sha256:") + ".txt"


def missing_copy_problem(source: str, digest: str, current: bool = False) -> str:
    """Returns the report of a missing copy, with the way to get it back.

    @param source: the Python source, relative to the repository root
    @param digest: the hash of the version that has no copy
    @param current: whether the source still has this version, so that the update can write the copy
    @return: the report
    """
    copy: str = (COPIES / copy_name(digest)).as_posix()
    if current:
        return f"{copy}: missing, the copy of the current version of {source}; {CURRENT_RECOVERY}"
    return (
        f"{copy}: missing, the copy of {source} as recorded in the manifest; "
        + RECOVERY.format(copy=copy, source=source)
    )


def corrupt_copy_problem(name: str) -> str:
    """Returns the report of a copy whose content does not match its name.

    A deleted copy is a missing one, whose report says how to get it back (see missing_copy_problem).

    @param name: the file name of the copy
    @return: the report
    """
    copy: str = (COPIES / name).as_posix()
    return (
        f"{copy}: corrupt, its content does not match its name; delete it, and if the manifest still records its "
        "version, the check says how to get it back"
    )


def intact(copy: Path) -> bool:
    """Returns whether a copy holds exactly the bytes its name is the hash of.

    The bytes of a copy are hashed as they are, without making line endings LF again: the copy holds the bytes after
    that step (see store_copies), and ``.gitattributes`` keeps them LF.

    @param copy: the copy
    @return: True if its content matches its name
    """
    return copy_name(digest_of_bytes(copy.read_bytes())) == copy.name


def copy_folder_problems(root: Path) -> list[str]:
    """Checks the folder of the copies: it is a real folder, and every entry is its README or an intact copy.

    Hidden files (e.g. ``.DS_Store``) are ignored.

    @param root: the repository root
    @return: one line per problem (the folder is a symbolic link or no folder, an unexpected entry, a corrupt copy)
    """
    folder: Path = root / COPIES
    # the update writes copies into the folder, so it may not lead elsewhere (generated/ itself is checked with the
    # generated folder, see symbolic_link_problems):
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        return [
            f"{COPIES.as_posix()}: not a folder; it must be a real folder, not a link"
        ]
    if not folder.is_dir():
        return []
    problems: list[str] = []
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith("."):
            continue
        if (
            entry.is_symlink()
            or not entry.is_file()
            or not (entry.name == COPIES_README or COPY_NAME.fullmatch(entry.name))
        ):
            problems.append(
                f"{(COPIES / entry.name).as_posix()}: not a copy of a Python source; only copies "
                f"<{DIGEST_LENGTH} hex digits>.txt and {COPIES_README} belong here"
            )
        elif entry.name != COPIES_README and not intact(entry):
            problems.append(corrupt_copy_problem(entry.name))
    return problems


def missing_copy_problems(root: Path, recorded: dict[str, RecordedFile]) -> list[str]:
    """Checks that every source version recorded in the manifest has its copy.

    @param root: the repository root
    @param recorded: the manifest's entries
    @return: one line per missing copy and source; sources with the same content share a copy, and each gets its own
        line, as the way to get the copy back depends on the source
    """
    needed: set[tuple[str, str]] = {
        (source["sha256"], source["path"])
        for file in recorded.values()
        for source in file["sources"]
    }
    return [
        missing_copy_problem(
            source,
            digest,
            exists_exactly(root, source) and digest_of(root / source) == digest,
        )
        for digest, source in sorted(needed)
        if not (root / COPIES / copy_name(digest)).is_file()
    ]


def store_copies(root: Path, files: list[GeneratedFile]) -> list[str]:
    """Stores a copy of every Python source of the given files, unless one with its hash exists; never deletes one.

    A copy holds the bytes the hash is computed from (LF line endings) and is named by the hash, so a source shared
    by several generated files is stored once per version. Older versions are kept, because a manifest entry may
    still name them, also one merged from another branch.

    @param root: the repository root
    @param files: the generated files as they are now
    @return: one line per source that changed since it was hashed (the update must then be run again); empty if
        every copy now exists
    """
    problems: list[str] = []
    # a source of several generated files is reported once:
    reported: set[str] = set()
    folder: Path = root / COPIES
    for file in files:
        for source, digest in file.sources.items():
            copy: Path = folder / copy_name(digest)
            if copy.exists():
                continue
            data: bytes = lf_bytes(root / source)
            if digest_of_bytes(data) != digest:
                if source not in reported:
                    reported.add(source)
                    problems.append(
                        f"{source}: changed while the update ran; run the update again"
                    )
                continue
            folder.mkdir(parents=True, exist_ok=True)
            # write a new hidden file with a random name first and then rename it, so an interrupted update leaves no
            # cut-off copy; mkstemp creates the file exclusively, so a planted link cannot be written through:
            handle, partial = tempfile.mkstemp(
                dir=folder, prefix=".", suffix=".partial"
            )
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # mkstemp makes the file readable by its owner only; a copy is as readable as the checked-out files:
            os.chmod(partial, 0o644)
            os.replace(partial, copy)
    return problems


def current_files(root: Path) -> tuple[list[GeneratedFile], list[str]]:
    """Reads every generated file as it is now, with the hashes of its Python sources.

    @param root: the repository root
    @return: the files that could be read, and the problems found while reading (a file name with ':' or '\\',
        first line, sources, test folders and modules, hidden tool settings, symbolic links)
    """
    paths: list[str] = generated_paths(root)
    files: list[GeneratedFile] = []
    problems: list[str] = []
    links: list[str] = symbolic_link_problems(root)
    for path in paths:
        if any(link.startswith(f"{path}:") for link in links):
            continue
        # the manifest refuses such paths (see read_manifest), so the update must not record them:
        if ":" in path or "\\" in path:
            problems.append(
                f"{path}: a file name with ':' or '\\' is not allowed in the generated code"
            )
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


def valid_entry_path(path: str) -> bool:
    """Tells whether a path of the manifest names a file of the generated folder, never one that leads out of it.

    @param path: the path as recorded in the manifest
    @return: whether it is not empty, relative (on every system) and free of ``..``, ``\\`` and ``:``
    """
    return not (
        not path
        or "\\" in path
        or ":" in path
        or PurePosixPath(path).is_absolute()
        or Path(path).is_absolute()
        or ".." in Path(path).parts
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
            if not valid_entry_path(file["path"]):
                raise ValueError(f"entry {file!r} has no valid path")
            for source in file["sources"]:
                if not isinstance(source["path"], str) or not isinstance(
                    source["sha256"], str
                ):
                    raise TypeError(f"source {source!r}")
                # the hash of a source is also the name of its copy, so it must be a hash and nothing else:
                if not DIGEST.fullmatch(source["sha256"]):
                    raise ValueError(f"source {source!r} has no valid hash")
        paths: list[str] = [file["path"] for file in files]
        if len(set(paths)) != len(paths):
            raise ValueError("an entry's path appears twice")
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
        return problems + copy_folder_problems(root) + [str(problem)]
    problems += copy_folder_problems(root) + missing_copy_problems(root, recorded)
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


def update(root: Path) -> list[str]:
    """Rewrites the manifest from the generated files as they are now; call it right after regenerating.

    @param root: the repository root
    @return: the problems that keep the manifest from being written: those of the generated files (see
        current_files); those of the folder of the copies (see copy_folder_problems); a source that changed while the
        update ran; a manifest that is a symbolic link. Empty on success
    """
    files, problems = current_files(root)
    # a missing copy is no problem here: the copies of the current sources are written below
    problems += copy_folder_problems(root)
    if problems:
        return problems
    problems = store_copies(root, files)
    if problems:
        return problems
    return write_manifest(root, [entry_of(file) for file in files])


def update_dependencies(root: Path) -> list[str]:
    """Rewrites only the manifest entries of Cargo.toml, Cargo.lock and rust-toolchain.toml, after a dependency update.

    Every other entry stays as it is, so out-of-date or hand-edited Rust files are still reported afterwards. The
    three files name no Python source (a first line naming one is refused), so no copy is stored.

    @param root: the repository root
    @return: the problems that keep the manifest from being written (missing or unreadable manifest, a problem with
        one of the three files or with the generated folder itself, one of the three files naming a Python source, a
        manifest that is a symbolic link); empty on success
    """
    recorded, problem = read_manifest(root)
    if recorded is None:
        return [str(problem)]
    files, problems = current_files(root)
    # a problem with one of the three files, or with the generated folder itself (e.g. a symbolic link to elsewhere):
    folders: set[str] = {GENERATED.parent.as_posix(), GENERATED.as_posix()}
    dependency_problems: list[str] = [
        problem
        for problem in problems
        if problem.split(":")[0] in DEPENDENCY_FILES | folders
    ]
    if dependency_problems:
        return dependency_problems
    named: list[str] = [
        f"{file.path}: names a Python source; a dependency update records no sources, regenerate instead"
        for file in files
        if file.path in DEPENDENCY_FILES and file.sources
    ]
    if named:
        return named
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
    manifest_path.write_text(
        json.dumps({"files": entries}, indent=2) + "\n", encoding="utf-8"
    )
    return []


def diff_lines(old: str, new: str, old_label: str, new_label: str) -> list[str]:
    """Returns a unified diff of two texts, split at LF only, with git's note for a missing final newline.

    @param old: the old text
    @param new: the new text
    @param old_label: the name of the old text in the diff's header
    @param new_label: the name of the new text in the diff's header
    @return: the lines of the diff, without line endings; empty if the texts are equal
    """

    # split at LF only, as git does; str.splitlines would also split at a lone CR or a form feed:
    def lines_of(text: str) -> list[str]:
        """Splits a text into lines that keep their LF; the last line has none if the text does not end with LF."""
        parts: list[str] = [line + "\n" for line in text.split("\n")]
        parts[-1] = parts[-1][:-1]
        return parts if parts[-1] else parts[:-1]

    result: list[str] = []
    for line in difflib.unified_diff(
        lines_of(old), lines_of(new), old_label, new_label
    ):
        if line.endswith("\n"):
            result.append(line[:-1])
        else:
            result += [line, "\\ No newline at end of file"]
    return result


def changed_versions(
    root: Path, paths: list[str], recorded: dict[str, RecordedFile]
) -> tuple[dict[SourceVersion, list[str]], list[str], list[str]]:
    """Finds the old source versions of the given generated files that differ from the current sources.

    @param root: the repository root
    @param paths: the generated files, all in the manifest
    @param recorded: the manifest's entries
    @return: the generated files of each old version that differs from the current source, notes on the sources a
        file no longer names in its first line (changed or not), and the errors (a source outside ``system/``, a
        broken first line, a source named in the first line that does not exist)
    """
    versions: dict[SourceVersion, list[str]] = {}
    notes: list[str] = []
    errors: list[str] = []
    for path in paths:
        recorded_sources: dict[str, str] = {
            source["path"]: source["sha256"] for source in recorded[path]["sources"]
        }
        # the sources the first line names now; None if the file or its first line cannot be read:
        header: list[str] | None = None
        if (root / GENERATED / path).is_file():
            header, problem = sources_of(root, path)
            if header is None:
                errors.append(str(problem))
        named: list[str] = list(dict.fromkeys(header or []))
        outside: list[str] = outside_source_folder(root, [*recorded_sources, *named])
        errors += [
            f"{path}: its source {source} is not in {SOURCE_FOLDER}"
            for source in dict.fromkeys(outside)
        ]
        for source, digest in recorded_sources.items():
            if source in outside:
                continue
            dropped: bool = header is not None and source not in named
            if not exists_exactly(root, source) or digest_of(root / source) != digest:
                versions.setdefault(SourceVersion(source, digest), []).append(path)
                if dropped:
                    notes.append(
                        f"{path}: no longer generated from {source}, which changed"
                    )
            elif dropped:
                notes.append(
                    f"{path}: no longer generated from {source}, which did not change"
                )
        for source in named:
            if source in recorded_sources or source in outside:
                continue
            if exists_exactly(root, source):
                versions.setdefault(SourceVersion(source, None), []).append(path)
            else:
                errors.append(
                    f"{path}: its source {source} is named in the first line but does not exist"
                )
    return versions, notes, errors


def version_diff(
    root: Path, source: str, digest: str | None, generated: list[str]
) -> tuple[list[str], str | None]:
    """Returns the heading and the diff of one old version of a source against the current file.

    @param root: the repository root
    @param source: the source, relative to the repository root
    @param digest: its recorded hash, or None if it is not recorded (then the old text is empty)
    @param generated: the generated files recorded with this version
    @return: the heading and the diff, and no error; or no lines and the error (missing or corrupt copy, a text that
        is not UTF-8)
    """
    old: str = ""
    old_label: str = f"{source} (not recorded)"
    if digest is not None:
        copy: Path = root / COPIES / copy_name(digest)
        if not copy.is_file():
            return [], missing_copy_problem(source, digest)
        if not intact(copy):
            return [], corrupt_copy_problem(copy.name)
        try:
            old = copy.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            return (
                [],
                f"{(COPIES / copy.name).as_posix()}: not a UTF-8 text file, so it cannot be compared",
            )
        old_label = f"{source} (as generated, {copy.name})"
    current: Path = root / source
    exists: bool = exists_exactly(root, source)
    try:
        new: str = lf_bytes(current).decode("utf-8") if exists else ""
    except UnicodeDecodeError:
        return [], f"{source}: not a UTF-8 text file, so it cannot be compared"
    state: str = CHANGED if digest is not None else NOT_RECORDED
    new_label: str = f"{source} (now)"
    if not exists:
        state = DELETED
        new_label = f"{source} (deleted)"
    return [
        f"{source}: {state}; generated from it: {', '.join(generated)}"
    ] + diff_lines(old, new, old_label, new_label), None


def diff(root: Path, paths: list[str]) -> tuple[list[str], list[str]]:
    """Returns what changed in the Python sources since the given generated files were generated.

    For every old version of a source (a source path with its recorded hash) that differs from the current file, it
    gives one unified diff of the stored copy against the current file, headed by the state (CHANGED or DELETED) and
    the generated files recorded with that version; a source named in a first line but not recorded (NOT_RECORDED)
    is compared with an empty text. Notes on the sources a file no longer names follow at the end. It reads
    only the manifest, the first lines of the given files, the sources and the copies, so it works even if the check
    reports problems elsewhere.

    @param root: the repository root
    @param paths: the generated files, relative to the generated folder; all files in the manifest if empty
    @return: the lines to print, and the errors (unreadable manifest, unknown path, a source outside ``system/``, a
        broken first line, a missing source named in a first line, a missing or corrupt copy, a text that is not
        UTF-8)
    """
    recorded, problem = read_manifest(root)
    if recorded is None:
        return [], [str(problem)]
    errors: list[str] = [
        f"{path}: not in the manifest (paths are relative to {GENERATED.as_posix()}/)"
        for path in dict.fromkeys(paths)
        if path not in recorded
    ]
    selected: list[str] = (
        [path for path in dict.fromkeys(paths) if path in recorded]
        if paths
        else sorted(recorded)
    )
    versions, notes, version_errors = changed_versions(root, selected, recorded)
    errors += version_errors
    lines: list[str] = []
    for version, generated in sorted(
        versions.items(), key=lambda item: (item[0].source, item[0].digest or "")
    ):
        shown, error = version_diff(root, version.source, version.digest, generated)
        lines += shown
        if error is not None:
            errors.append(error)
    # an unknown path hides no change, but if only unknown paths were given, nothing was compared; a broken first line
    # or a source outside system/ may hide a change:
    if not versions and not version_errors and (selected or not paths):
        lines.append(
            "No Python source changed since its generated files were generated."
        )
    return lines + notes, errors


def main(arguments: list[str]) -> int:
    """Runs the check, or the update, the dependency update or the diff given by the options.

    The diff prints its errors to stderr, so stdout holds only the diff, which another program may read as input; the
    check and the updates print their reports to stdout.

    @param arguments: the command line arguments without the program name
    @return: the exit status: 0 if the generated code is up to date (or the manifest was written, or the diff was
        shown without errors), otherwise 1
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0]
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--update", action="store_true", help="rewrite the manifest after regenerating"
    )
    mode.add_argument(
        "--update-dependencies",
        action="store_true",
        help="record only Cargo.toml, Cargo.lock and rust-toolchain.toml after a dependency update",
    )
    mode.add_argument(
        "--diff",
        nargs="*",
        metavar="FILE",
        help="show what changed in the Python sources of the given generated files (paths relative to "
        "generated/rust/; all files if none) since they were generated",
    )
    options: argparse.Namespace = parser.parse_args(arguments)
    root: Path = Path(__file__).resolve().parents[1]
    problems: list[str]
    if options.diff is not None:
        lines, errors = diff(root, options.diff)
        # the diff holds Python source text, which the console's encoding may lack:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        for line in lines:
            print(line)
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1 if errors else 0
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
