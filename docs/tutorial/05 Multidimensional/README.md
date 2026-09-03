# 05 Multidimensional

One-dimensional indexes (B⁺-trees, tries) order data along a *single* key. Many queries are
**multidimensional** — a point in 2-D space, a geo bounding box, a range over several attributes at once.
This section covers how to bring multidimensional data into a one-dimensional index without losing
locality.

- [**Z-Order Curve**](<Z-Order Curve.md>) — a space-filling curve that linearizes multidimensional data
  so nearby points stay nearby in the 1-D order.
