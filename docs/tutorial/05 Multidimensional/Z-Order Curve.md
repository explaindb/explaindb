# Z-Order Curve

A **space-filling curve** visits every cell of a multidimensional grid in a single 1-D order, so you can
store multidimensional points in an ordinary one-dimensional index and still keep points that are close
in space close in the index. The **Z-order curve** (also called **z-codes**, **z-values**, or **Morton
codes**) does this by **bit-interleaving** the coordinates: take the bits of *x* and *y* and alternate
them into one integer.

Because nearby points share high-order coordinate bits, they share high-order z-code bits too, so they
land near each other in the 1-D order. That means a B⁺-tree over z-codes answers 2-D range/locality
queries reasonably well — the workhorse behind many geospatial and multi-attribute indexes.

## In this repo

- **Notebook:** [`Z-Order-Curve.ipynb`](../../../notebooks/Z-Order-Curve.ipynb) — an educational implementation of
  z-codes that maps 2-D data to 1-D, visualizes the curve, and shows the locality it preserves
  (over a synthetic grid of z-codes).

## The idea in one picture

```
x = 0b a2 a1 a0
y = 0b b2 b1 b0
z = 0b b2 a2 b1 a1 b0 a0        interleave the coordinate bits → one sortable integer
```

Two points with the same top coordinate bits get the same top z-code bits, so they sort next to each
other.

## Try it

In `Z-Order-Curve.ipynb`, plot the curve over a small grid and follow the visiting order; then sort a set
of 2-D points by z-code and see how spatial neighbours cluster in the 1-D sequence.
