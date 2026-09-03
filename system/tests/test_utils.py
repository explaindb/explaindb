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

# Test modules use self-documenting method/class names and module-level
# fixtures, so pylint's naming and docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Tests for the utility classes."""

import unittest

from system.utils import Vector, Triangle

from faker import Faker

Faker.seed(42)

import random

random.seed(42)


class UtilsTest(unittest.TestCase):

    def test_vector(self):
        v = Vector(1, 2)
        self.assertEqual(v.x, 1)
        self.assertEqual(v.y, 2)
        v2 = Vector(3, 4)
        v3 = v + v2
        self.assertEqual(v3.x, 4)
        self.assertEqual(v3.y, 6)
        v4 = v * 2
        self.assertEqual(v4.x, 2)
        self.assertEqual(v4.y, 4)

        i: int = v2.my_hash()
        self.assertEqual(i, 1079245023883434373)

    def test_triangle(self):
        t: Triangle = Triangle(Vector(0, 0), Vector(1, 0), Vector(0.5, 1))
        triangles = list(t.split_into_sub_descriptors())
        # for t in triangles:
        #    print(t)

        self.assertEqual(len(triangles), 4)
        self.assertEqual(triangles[0].A.x, 0)
        self.assertEqual(triangles[0].A.y, 0)
        self.assertEqual(triangles[0].AB.x, 0.5)
        self.assertEqual(triangles[0].AB.y, 0)
        self.assertEqual(triangles[0].AC.x, 0.25)
        self.assertEqual(triangles[0].AC.y, 0.5)

        self.assertEqual(triangles[1].A.x, 0.25)
        self.assertEqual(triangles[1].A.y, 0.5)
        self.assertEqual(triangles[1].AB.x, 0.5)
        self.assertEqual(triangles[1].AB.y, 0)
        self.assertEqual(triangles[1].AC.x, 0.25)
        self.assertEqual(triangles[1].AC.y, 0.5)

        self.assertEqual(triangles[2].A.x, 0.5)
        self.assertEqual(triangles[2].A.y, 0)
        self.assertEqual(triangles[2].AB.x, 0.5)
        self.assertEqual(triangles[2].AB.y, 0)
        self.assertEqual(triangles[2].AC.x, 0.25)
        self.assertEqual(triangles[2].AC.y, 0.5)

        self.assertEqual(triangles[3].A.x, 0.75)
        self.assertEqual(triangles[3].A.y, 0.5)
        self.assertEqual(triangles[3].AB.x, -0.5)
        self.assertEqual(triangles[3].AB.y, 0)
        self.assertEqual(triangles[3].AC.x, -0.25)
        self.assertEqual(triangles[3].AC.y, -0.5)

        # t: Triangle
        # for t in triangles:
        #    print(t)
        #    sub_triangles: list[Triangle] = list(t.split_into_four_sub_triangles())
        #    for st in sub_triangles:
        #        print(st)

    def test_triangle_half_open(self):
        triangle: Triangle = Triangle(Vector(0, 0), Vector(300, 0), Vector(150, 300))
        triangles = list(triangle.split_into_sub_descriptors())
        self.assertEqual(len(triangles), 4)
        v: Vector = Vector(107, 86)
        self.assertTrue(triangle.contains(v))
        self.assertTrue(
            triangles[0].contains(v)
            or triangles[1].contains(v)
            or triangles[2].contains(v)
            or triangles[3].contains(v)
        )


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
