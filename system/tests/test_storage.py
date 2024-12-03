from system.storage.RAID import compute_assignment
from system.tests.abstract_unit_test import AbstractUnitTest


class RAIDTest(AbstractUnitTest):

    def _test_RAID_0(self):
        ret: list[str] = compute_assignment(3, 3, 0)
        self.assertEqual(len(ret), 3)
        self.assertEqual(ret[0], "0          1          2")
        self.assertEqual(ret[1], "3          4          5")
        self.assertEqual(ret[2], "6          7          8")

    def _test_RAID_1(self):
        ret: list[str] = compute_assignment(3, 3, 1)
        self.assertEqual(len(ret), 3)
        self.assertEqual(ret[0], "0          0          0")
        self.assertEqual(ret[1], "1          1          1")
        self.assertEqual(ret[2], "2          2          2")

    def _test_RAID_4(self):
        ret: list[str] = compute_assignment(3, 3, 4)
        self.assertEqual(len(ret), 3)
        self.assertEqual(ret[0], "0          1          P[0^1]")
        self.assertEqual(ret[1], "2          3          P[2^3]")
        self.assertEqual(ret[2], "4          5          P[4^5]")

    def test_RAID_5(self):
        ret: list[str] = compute_assignment(2, 3, 5)
        self.assertEqual(len(ret), 2)
        self.assertEqual(ret[0], "0          1          P[0^1]")
        self.assertEqual(ret[1], "P[2^3]     2          3")

        # Output for debugging purposes
        # ret: list[str] = compute_assignment(20, 3, 5)
        # for row in ret:
        #    print(row)
