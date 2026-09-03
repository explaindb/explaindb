# Distributed Joins

When the relations live on several machines, a join needs a **data-movement strategy** on top of the
local join algorithm — network transfer, not CPU, is usually the bottleneck. The classic options:

- **Shuffle / repartition join:** hash both inputs on the join key and send each row to the node
  responsible for its key bucket, so matching rows meet on the same node. Balanced, but moves both
  inputs.
- **Broadcast join:** if one input is small, send a full copy to every node and join locally against the
  large, already-placed input. Moves only the small side.

Which one wins depends on the relative sizes and the key distribution — the same cost-based reasoning as
local optimization, now counting bytes over the network.

## In this repo

- **Notebook:** [`Distributed-Joins.ipynb`](../../../notebooks/Distributed-Joins.ipynb) — takes a join query
  (`persons ⋈ books ON name = author`) and works through how to execute it across nodes.

## The idea in one picture

```
shuffle:  A ─hash(key)─►┐                     broadcast:  small input B
          B ─hash(key)─►┴─► matching keys        copy full B ─► every node,
          meet on the same node                  join local partition of A vs B
          (both inputs move; balanced)           (only B moves; needs B small)
```

## Try it

In `Distributed-Joins.ipynb`, compare the bytes moved by a shuffle join against a broadcast join as you
vary the size of the smaller relation — the crossover is where the strategy should switch.
