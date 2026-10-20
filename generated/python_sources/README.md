# Python sources of the generated Rust code

The Rust code in [`../rust/`](../rust) is generated from the Python code in [`../../system/`](../../system). Each file
here except this README is a copy of one Python source in the version a Rust file was generated from, named by the start
of its SHA-256 as recorded in [`../rust/GENERATED_FROM.json`](../rust/GENERATED_FROM.json), e.g. `0123456789abcdef.txt`.
The files end in `.txt`, so Python tools leave them alone.

`python3 .ci/check_generated.py --update` writes the copies when the generated code is recorded and never deletes one.
When a Python source changes later, `python3 .ci/check_generated.py --diff` compares the copy with the current file and
shows what may have to be ported to Rust. The copies have LF line endings. Do not edit or delete them, and put no other
files or folders here (hidden files such as `.DS_Store` are ignored): the check reports a missing copy of a version the
manifest records, a corrupt copy, and anything else in this folder. Commit new copies with the Rust files. A corrupt
copy is deleted; `--update` writes a missing copy of a current source version, a missing copy of an older version is
restored from git or, if git has no intact one, replaced by regenerating the Rust files of its source (the check says
how).
