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

## Formatting

All Python code is formatted with [black](https://black.readthedocs.io) (default
settings). CI runs `black --check .` and rejects unformatted code, so run
`black .` before every push.
