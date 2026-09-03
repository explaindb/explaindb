# RAID Cost Modeling

**RAID** combines several devices into one logical subsystem to gain **throughput**, **resilience**, or
both:

- **RAID 0 (striping):** spread data across devices for parallel bandwidth — sequential throughput
  scales with the number of devices, but one failure loses everything.
- **RAID 1 (mirroring):** keep copies for fault tolerance, at the cost of capacity.
- Higher levels and **nested** arrays (arrays of arrays) mix these.

To reason about a configuration without building it, this repo models each subsystem's **performance and
resilience** with a small cost model, so you can compare arrangements analytically.

## In this repo

- **Notebook:** [`RAID-Nesting-Trade-offs.ipynb`](../../../notebooks/RAID-Nesting-Trade-offs.ipynb) — enumerates
  every way of nesting a fixed number of devices as RAID 0 arrays and compares their sequential read
  performance, showing that a single flat stripe beats every nesting for sequential reads.
- **Implementation:** [`system/storage/RAID/cost_model.py`](../../../system/storage/RAID/cost_model.py)
  (`Device`, `RAID_0`, `RAID_1`, … and their performance/resilience) and
  [`system/storage/RAID/block_assignment.py`](../../../system/storage/RAID/block_assignment.py).

## The idea in one picture

```
RAID 0 over 4 devices:        seq_read(RAID 0) = min(member seq_read) × members
   ┌──┐ ┌──┐ ┌──┐ ┌──┐         flat stripe of 4:      min × 4   ← best
   │d0│ │d1│ │d2│ │d3│         nested (RAID 0 of 2×2): min × 2 per level
   └──┘ └──┘ └──┘ └──┘         → nesting caps the member count and lets a
   blocks striped round-robin    slow member throttle the whole stripe
```

so nesting *caps* the member count and lets a slow member throttle the whole stripe — which is exactly
why the notebook finds flat striping optimal for sequential reads.

## Try it

In `RAID-Nesting-Trade-offs.ipynb`, compare the best nested arrangement of 32 devices against one flat
RAID 0 of all 32, and trace the numbers back to the formula above.
