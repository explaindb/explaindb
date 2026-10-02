# Contributing to ExplainDB

## Code formatting

All Python code is formatted with [black](https://black.readthedocs.io) using its
default settings. The CI pipeline runs `black --check .` and rejects unformatted
code, so run `black .` before every push.

## Dependencies

Dependencies are managed with [uv](https://docs.astral.sh/uv/) in `pyproject.toml`
and `uv.lock`. mybinder.org cannot read `uv.lock`, so `.binder/requirements.txt` is
an export of it. After every dependency change, regenerate it (the CI job
`binder_requirements` fails if you forget):

```sh
uv export --frozen --no-dev --no-hashes --no-header --no-annotate --format requirements.txt -o .binder/requirements.txt
```

## Docstring conventions

We document code so that the *contract* lives in one place and implementations
only describe what they add. This keeps overrides free of redundant copies of
the interface documentation.

### Where the contract lives

- **Interfaces and abstract base classes** carry the full contract. Use Javadoc
  style with `@param` and `@return`, as in
  [`system/interfaces/indexing/Index.py`](system/interfaces/indexing/Index.py).
- The docstring on the abstract method is the single source of truth for what
  the method promises.

### Implementations document the delta

- An **override that follows the interface contract exactly** gets a short
  reference only — do *not* repeat the contract:

  ```python
  def put(self, key, value):
      """See :meth:`Index.put`."""
      ...
  ```

- An **override that specializes or changes behaviour** references the contract
  and then states what is special or different in this implementation:

  ```python
  def get_equal(self, key):
      """See :meth:`BitmapIndex.get_equal`.

      Equality-encoded variant: returns the stored bit sequence for the key
      directly instead of OR-ing a range.
      """
      ...
  ```

### Dunder methods

- Document only the **non-trivial** dunder methods — those with real logic or
  special rules:

  ```python
  def __eq__(self, other):
      """Equal iff same bits AND same represented length."""
      ...
  ```

- Skip trivial delegating dunders where Python's semantics are self-explanatory.

### Modules

- Every module gets a one-line module docstring describing its purpose.

### Summary

| Kind | Docstring |
| --- | --- |
| Interface / abstract method | Full contract (`@param` / `@return`) |
| Override, no behaviour change | `See :meth:`...`` reference only |
| Override with a delta | Reference + what is special / changed |
| Non-trivial dunder | Short description of the logic |
| Trivial dunder | None |
| Module | One-line purpose |
