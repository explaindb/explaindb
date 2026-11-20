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
  the nestings of 32 identical devices as RAID 0 arrays whose members of a level are alike and shows that each
  reads exactly as fast as one flat stripe; with devices of different speed, a nesting that groups the devices
  by speed beats the flat stripe.
- **Notebook:** [`RAID-Playground.ipynb`](../../../notebooks/RAID-Playground.ipynb) — build RAID arrays of one or
  two levels by clicking, fail disks and see block by block which data can still be read, and compare what two
  arrays cost, how fast they are and which combinations of failed disks they survive.
- **Implementation:** [`system/storage/RAID/cost_model.py`](../../../system/storage/RAID/cost_model.py)
  (`Device`, `RAID_0`, `RAID_1`, … and their performance/resilience; `count_survived_failures` counts which
  combinations of failed devices an array survives, e.g. RAID 0+1 vs. RAID 1+0),
  [`system/storage/RAID/nesting.py`](../../../system/storage/RAID/nesting.py) (nested RAID 0 arrays for the
  notebook) and
  [`system/storage/RAID/block_assignment.py`](../../../system/storage/RAID/block_assignment.py).

## The idea in one picture

```
seq_read(RAID 0) = min(member seq_read) × members

identical devices, 100 MB/s each:
   flat stripe of 4:                      100 × 4          = 400 MB/s
   RAID 0 of two RAID 0s of 2 devices:    min(200, 200) × 2 = 400 MB/s   ← same

4 slow (100 MB/s) and 2 fast (200 MB/s) devices:
   flat stripe of 6:                      100 × 6          = 600 MB/s
   RAID 0 of [4 slow] and [2 fast]:       min(400, 400) × 2 = 800 MB/s   ← nesting helps
```

With identical devices, nesting alike members changes nothing for sequential reads: every level multiplies by
its member count, so the nesting reaches the same total as the flat stripe (members of unequal size would let
the smaller one throttle the larger). With devices of different speed, the slowest device throttles a flat
stripe; nesting can group the devices into equally fast members so that no fast device waits for a slow one.

## Try it

In `RAID-Nesting-Trade-offs.ipynb`, check that every nesting of 32 identical devices whose members of a level are
alike reaches the 3200 MB/s of the flat stripe, then compare the three arrangements of slow and fast devices and
trace the numbers back to the formula above.
