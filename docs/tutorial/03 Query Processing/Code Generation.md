# Code Generation

Interpreting an operator tree pays a price on **every tuple**: virtual calls between operators, branching
on operator type, boxed intermediate tuples. **Code generation** removes that overhead by *compiling* the
plan into straight-line code specialized to this exact query — nested loops with the predicates and the
join hash table inlined — which the language runtime then executes directly.

The same operators that can *interpret* a plan (push a tuple to the parent) can instead *emit* the code
that would do so, turning the operator tree into a single generated program. This is the core idea behind
modern compiling query engines (the "produce/consume" model).

## In this repo

- **Notebook:** [`CodeGen.ipynb`](../../../notebooks/CodeGen.ipynb) — takes the same join query as
  [Result DB](<Operators & the Push Model.md>) and generates Python code for it, then runs the generated
  code; you can read the emitted program and compare it to the interpreted pipeline.
- **Implementation:** the `compile(...)`/emit methods on the operators in
  [`system/query_processing/operators.py`](../../../system/query_processing/operators.py).
- **Tests:** [`system/tests/test_code_gen.py`](../../../system/tests/test_code_gen.py) — a differential
  test that asserts the interpreted and the compiled query return the same result.

## The idea in one picture

```
interpret:  tuple ─► op ─► op ─► op        virtual call per tuple, per operator
generate:   emit one specialized loop nest for this exact query:
                for tup in scan:
                    if pred(tup): ht[k] = …     ← predicates & join inlined,
                                                  straight-line, no per-tuple dispatch
```

## Try it

In `CodeGen.ipynb`, print the generated code for the join query and match each fragment to the operator
that emitted it; then run it and confirm the result equals the interpreted run.
