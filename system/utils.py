#
#    This is ExplainDB, educational database systems materials.
#
#    Copyright (C) 2026 Prof. Dr. Jens Dittrich, Saarland University
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#

"""Drawable geometry utilities (vectors, triangles, descriptors) for canvas visualization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from attr import dataclass
from ipycanvas import Canvas


class Drawable(ABC):
    """An interface for objects that can render themselves onto an ipycanvas canvas."""

    @abstractmethod
    def draw(
        self,
        canvas: Canvas,
        canvas_height: int = 0,
        x_offset: int = 0,
        y_offset: int = 0,
    ):
        """Draw this instance on the given canvas.

        @param canvas: The canvas to draw on.
        @param canvas_height: The height of the canvas (used to invert y-coordinates which are top down in canvas).
        @param x_offset: The x-offset to apply to the drawing.
        @param y_offset: The y-offset to apply to the drawing.
        """


@dataclass
class Vector(Drawable):
    """A simple implementation of a two-dimensional vector."""

    x: float
    y: float

    def __add__(self, other: Vector) -> Vector:
        """Add two vectors together."""
        return Vector(self.x + other.x, self.y + other.y)

    def __mul__(self, other: float):
        """Multiply this vector by a scalar."""
        return Vector(self.x * other, self.y * other)

    def __neg__(self):
        """Negate this vector."""
        return Vector(-self.x, -self.y)

    def __str__(self):
        """Render the vector as an ``(x, y)`` coordinate pair."""
        return f"({self.x}, {self.y})"

    def my_hash(self) -> int:
        """Return a hash value for this vector."""
        # TODO: use built in hash function (did not work for me, was not consistent)
        return hash((self.x, self.y))

    def draw(
        self,
        canvas: Canvas,
        canvas_height: int = 0,
        x_offset: int = 0,
        y_offset: int = 0,
    ):
        """See :meth:`Drawable.draw`.

        Draws the vector as a small white dot at its (x, y) position.
        """
        canvas.fill_style = "#FFFFFF"
        canvas.fill_arc(
            x_offset + self.x,
            canvas_height - (y_offset + self.y),
            radius=2,
            start_angle=0,
            end_angle=2 * 3.14159,
        )


class Descriptor(Drawable):
    """A simple interface for descriptors. Descriptors define a subset of a domain. For instance, given a
    two-dimensional space, a descriptor might define a rectangle or triangle or any other geometric structure in that
    space. This abstraction is very useful for indexing and querying data in a multidimensional domain.
    """

    @abstractmethod
    def split_into_sub_descriptors(self) -> Iterator[Descriptor]:
        """Split this Descriptor into four sub-descriptors. Each must be contained in self, i.e. if you call
        self.contains() with any child descriptor, it must return True."""

    @abstractmethod
    def contains[Key](self, key: Key) -> bool:
        """Return whether the given key is contained in this Descriptor."""

    @abstractmethod
    def center[T](self) -> T:
        """Return the center of this Descriptor."""


class Triangle(Descriptor):
    """A simple implementation of a triangle data structure."""

    def __init__(self, A: Vector, AB: Vector, AC: Vector):
        """Create a new triangle with the given vertices.

        @param A: The first vertex of the triangle.
        @param AB: The vector from A to B.
        @param AC: The vector from A to C.

        """
        self.A: Vector = A
        self.AB: Vector = AB
        self.AC: Vector = AC

    def center(self) -> Vector:
        """See :meth:`Descriptor.center`.

        Returns the centroid of the triangle.
        """
        B: Vector = self.A + self.AB
        C: Vector = self.A + self.AC
        return (self.A + B + C) * (1 / 3)  # centroid

    def split_into_sub_descriptors(self) -> Iterator[Triangle]:
        """See :meth:`Descriptor.split_into_sub_descriptors`.

        Splits this triangle into four sub-triangles of equal size (lower-left, top, lower-right, and a
        central inverted triangle).
        """
        # linear algebra to the rescue:
        # Note: all four sub-triangles have the same length of AB and AC, i.e. AB_half and AC_half:
        AB_half: Vector = self.AB * 0.5
        AC_half: Vector = self.AC * 0.5

        # Triangle 1 (lower-left)
        # same start vector A as self:
        yield Triangle(self.A, AB_half, AC_half)

        # Triangle 2 (top)
        # same start vector A as self except A is moved up by AC_half:
        yield Triangle(self.A + AC_half, AB_half, AC_half)

        # Triangle 3 (lower right)
        # same start vector A as self except A is moved right by AB_half:
        yield Triangle(self.A + AB_half, AB_half, AC_half)

        # Triangle 4 (center)
        # same start vector A as self except A is moved right by AB_half and up by AC_half
        # then we go backwards by -AB_half and -AC_half:
        yield Triangle(self.A + AB_half + AC_half, -AB_half, -AC_half)

    def draw(
        self,
        canvas: Canvas,
        canvas_height: int = 0,
        x_offset: int = 0,
        y_offset: int = 0,
    ):
        """See :meth:`Drawable.draw`.

        Draws the triangle as a semi-transparent green filled polygon with a black outline.
        """
        canvas.fill_style = "#63934e"
        canvas.stroke_style = "#000000"
        canvas.global_alpha = 0.3
        canvas.line_width = 1
        canvas.fill_polygon(
            [
                (x_offset + self.A.x, canvas_height - (self.A.y + y_offset)),
                (
                    x_offset + self.A.x + self.AB.x,
                    canvas_height - (self.A.y + self.AB.y + y_offset),
                ),
                (
                    x_offset + self.A.x + self.AC.x,
                    canvas_height - (self.A.y + self.AC.y + y_offset),
                ),
            ]
        )
        canvas.stroke()
        canvas.global_alpha = 1.0

    def contains[Vector](self, point: Vector) -> bool:
        """See :meth:`Descriptor.contains`.

        Point-in-triangle test: the point is contained iff it lies on the same side of all three edges, which
        is checked via the sign of the cross products.
        """

        # linear algebra to the rescue:
        def sign(A: Vector, B: Vector, C: Vector) -> int:
            """Return the sign of the determinant of the matrix formed by the given points."""

            c: float = (B.x - A.x) * (C.y - A.y) - (B.y - A.y) * (
                C.x - A.x
            )  # cross product

            if c > 0:
                return 1
            elif c < 0:
                return -1
            else:
                return 0

        # check if the point is on the same side of the lines AB, BC, and CA
        # as the triangle's vertices A, B, and C
        return (
            sign(self.A, self.A + self.AB, point) >= 0  # AB
            and sign(self.A + self.AB, self.A + self.AC, point) >= 0  # BC
            and sign(self.A + self.AC, self.A, point) >= 0  # CA
        )

    def __str__(self) -> str:
        """Render the triangle as ``∆`` followed by its origin vertex and the two edge vectors."""
        return f"∆({self.A}, {self.AB}, {self.AC})"
