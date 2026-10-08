# ExplainDB — project conventions for Claude

## Docstrings

Follow the docstring conventions in [`CONTRIBUTING.md`](../CONTRIBUTING.md):

- Interfaces / abstract base classes carry the full contract (Javadoc
  `@param` / `@return`).
- An override that follows the contract exactly uses a short reference only,
  e.g. `"""See :meth:`Index.put`."""` — never repeat the contract.
- An override with a delta references the contract and states what is special
  or changed.
- Document only non-trivial dunder methods; skip trivial delegating ones.
- Every module gets a one-line module docstring.

## Comments and docstrings describe the current code

This repository is read by students. Comments and docstrings, including those
of tests, explain what the code does **now** — never old bugs that no longer
exist:

- No "Symptom / Repro / Expected / Observed before the fix" sections and no
  "before the fix" remarks; this overrides the header-docstring rule of the
  `/fix-bug` skill.
- A regression test's docstring states the behaviour it checks, e.g.
  `"""A transaction that reads an object inserted by a concurrent transaction
  does not see it."""`.
- The history of a bug belongs in the commit message and the merge request.

## Formatting

All Python code is formatted with [black](https://black.readthedocs.io) (default
settings). CI runs `black --check .` and rejects unformatted code, so run
`black .` before every push.
