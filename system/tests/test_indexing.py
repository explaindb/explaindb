import unittest

from system.indexes.btree import BPlusTree
from system.indexes.indexes import (
    PythonDictionaryIndex,
)
from system.stores.IndexedMVCC import IndexedTransactionalKeyValueStore
from faker import Faker

from system.tests.abstract_unit_test import AbstractUnitTest

Faker.seed(42)

import random

random.seed(42)


class IndexingTest(AbstractUnitTest):

    def test_indexing_basics_with_duplicates(self):
        index: PythonDictionaryIndex[str, str] = PythonDictionaryIndex[str, str]()
        index.put("key1", "value1")
        index.put("key1", "value2")
        index.put("key1", "value3")
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get("key1")), ["value1", "value2", "value3"])

        index.delete("key1", "value1")
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get("key1")), ["value2", "value3"])

        index.delete("key1", "value2")
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get("key1")), ["value3"])

        with self.assertRaises(KeyError):
            index.delete("key1", "value4")

        with self.assertRaises(KeyError):
            index.delete("key7", "value4")

        index.delete("key1", "value3")
        self.assertEqual(index.size(), 0)

    def test_create_and_drop_index_transactional_store(self):
        store = IndexedTransactionalKeyValueStore()
        fake_data = self._create_fake_data()
        store.bulkload(fake_data)

        self.assertEqual(store.size(), 100)
        store.create_index("a", "a", "=")
        with self.assertRaises(Exception):
            store.create_index("a", "b", "=")

        # check for existence of metadata:
        self.assertEqual(len(store.indexes_by_properties), 1)
        self.assertEqual(len(store.indexes_by_name), 1)

        # get the index:
        index_entry: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            store.indexes_by_name["a"]
        )
        no_unique_keys = len(set([x[1].a for x in fake_data]))
        # worst case: all "a" values are unique
        self.assertGreaterEqual(no_unique_keys, 1)

        # index must have as many entries as unique keys:
        self.assertEqual(index_entry.index.size(), no_unique_keys)

        # drop the index:
        store.drop_index("a")
        self.assertEqual(len(store.indexes_by_properties), 0)
        self.assertEqual(len(store.indexes_by_name), 0)

        # drop the index again:
        with self.assertRaises(Exception):
            store.drop_index("a")

        # create the index again:
        store.create_index("a", "a", "=")
        self.assertEqual(len(store.indexes_by_properties), 1)
        self.assertEqual(len(store.indexes_by_name), 1)

        # create a second index on "b":
        store.create_index("b", "b", "=")
        self.assertEqual(len(store.indexes_by_properties), 2)
        self.assertEqual(len(store.indexes_by_name), 2)

        # get index on "b":
        index_entry_b: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            store.indexes_by_name["b"]
        )
        no_unique_keys_on_b = len(set([x[1].b for x in fake_data]))
        # worst case: all "b" values are unique
        self.assertGreaterEqual(no_unique_keys_on_b, 1)

        # index must have as many entries as unique keys:
        self.assertEqual(index_entry_b.index.size(), no_unique_keys_on_b)

    def test_index_maintenance_transactional_store_commits(self):
        store = IndexedTransactionalKeyValueStore()

        store.put("1", IndexingTest.Stuff(2, 3))
        store.put("2", IndexingTest.Stuff(4, 3))

        store.create_index("a", "a", "=")
        store.create_index("b", "b", "=")

        # test get_suitable_indexes():
        suitable_indexes_a = list(store.get_suitable_indexes("a", "="))
        self.assertEqual(len(suitable_indexes_a), 1)

        suitable_indexes_a_le = list(store.get_suitable_indexes("a", "<="))
        self.assertEqual(len(suitable_indexes_a_le), 0)

        suitable_indexes_b = list(store.get_suitable_indexes("b", "="))
        self.assertEqual(len(suitable_indexes_b), 1)

        suitable_indexes_c = list(store.get_suitable_indexes("c", "="))
        self.assertEqual(len(suitable_indexes_c), 0)

        # check for correct index entries of index a:
        self.assertEqual(store.indexes_by_name["a"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a"].index.get(4)), ["2"])

        # check for correct index entries of index b:
        self.assertEqual(store.indexes_by_name["b"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["b"].index.get(3)), ["1", "2"])

        # check index maintenance while running transactions
        TA_ID_1: int = store.begin_transaction()

        # check update functionality:
        store.update_object("1", IndexingTest.Stuff(3, 4), TA_ID_1)

        def check_indexes(_self, _store):
            # check for correct index entries of index a:
            _self.assertEqual(_store.indexes_by_name["a"].index.size(), 3)
            _self.assertEqual(list(_store.indexes_by_name["a"].index.get(2)), ["1"])
            _self.assertEqual(list(_store.indexes_by_name["a"].index.get(3)), ["1"])
            _self.assertEqual(list(_store.indexes_by_name["a"].index.get(4)), ["2"])

            # check for correct index entries of index b:
            _self.assertEqual(_store.indexes_by_name["b"].index.size(), 2)
            _self.assertEqual(
                list(_store.indexes_by_name["b"].index.get(3)), ["1", "2"]
            )
            _self.assertEqual(list(_store.indexes_by_name["b"].index.get(4)), ["1"])

        check_indexes(self, store)
        # check delete functionality:
        store.delete_object("2", TA_ID_1)

        # indexes should be untouched:
        check_indexes(self, store)

        store.commit_transaction(TA_ID_1)

        # indexes should be untouched:
        check_indexes(self, store)

    def test_index_maintenance_transactional_store_aborts(self):
        store = IndexedTransactionalKeyValueStore()

        store.put("1", IndexingTest.Stuff(2, 3))

        store.create_index("a", "a", "=")
        store.create_index("b", "b", "=")

        # check index maintenance while running transactions
        TA_ID_1: int = store.begin_transaction()

        # check update functionality:
        store.update_object("1", IndexingTest.Stuff(3, 4), TA_ID_1)

        # abort the transaction:
        store.abort_transaction(TA_ID_1)

        # check for correct index entries of indexes a and b:
        self.assertEqual(store.indexes_by_name["a"].index.size(), 1)
        self.assertEqual(store.indexes_by_name["b"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["b"].index.get(3)), ["1"])


num_runs = 10
max_num_keys = 400
lower_bound = 0
upper_bound = 1000
num_range_queries = 200


class BPlusTreeTest(unittest.TestCase):

    @staticmethod
    def create_btree(
        gen_sorted: bool = False,
    ) -> tuple[BPlusTree, list[int], list[int], int]:
        """
        Creates a b-tree with random keys and values
        :param gen_sorted: sort the data before inserting
        :return: a tuple with the b-tree, the keys, the values and the number of keys
        """

        num_keys = random.randint(2, max_num_keys)
        assert upper_bound > lower_bound
        assert (upper_bound - lower_bound) > num_keys
        keys = random.sample(
            range(lower_bound, upper_bound), num_keys
        )  # keys without duplicates
        if gen_sorted:
            keys.sort()
        values = [i for i in range(num_keys)]
        btree: BPlusTree[int, int] = BPlusTree[int, int]()
        for key, value in zip(keys, values):
            btree.put(key, value)

        btree.consistency_check()

        return btree, keys, values, num_keys

    def test_btree_get(self):
        for _ in range(num_runs):
            btree, keys, values, num_keys = self.create_btree()
            self.assertEqual(btree.size(), num_keys)
            for i in range(len(keys)):
                v = list(btree.get(keys[i]))[0]
                self.assertEqual(
                    v, values[i], msg=f"k={keys[i]} | got={v} | expected={values[i]}"
                )

    def test_btree_update_and_get(self):
        """Tests the b-tree update method varying the inner and leaf capacity"""

        for inner_capacity in [2, 5, 100]:
            for leaf_capacity in [2, 5, 100]:
                btree: BPlusTree[int, int] = BPlusTree[int, int](
                    inner_capacity, leaf_capacity
                )

                # a dict for comparing results:
                d: dict[int, int] = dict()
                for _ in range(1000):
                    next_int: int = random.randint(1, 400)
                    next_key: int = next_int
                    next_value: int = next_int * 2
                    btree.put(next_key, next_value)
                    d[next_key] = next_value

                    # test get:
                    self.assertEqual(
                        list(btree.get(next_key)),
                        [next_value],
                    )

                self.assertEqual(btree.size(), len(d))
                for key, value in d.items():
                    self.assertEqual(list(btree.get(key))[0], value)

    def test_btree_get_all_in_range(self):
        for _ in range(num_runs):
            btree, keys, values, num_keys = self.create_btree(
                True
            )  # use sorted `keys` to check correctness
            self.assertEqual(btree.size(), num_keys)
            for _ in range(num_range_queries):
                # create random range query:
                min, max = sorted(random.sample(range(lower_bound, upper_bound), 2))
                # query the b-tree:
                values_got = list(btree.get_all_in_range(min, max))
                values_expected = []
                for k, v in zip(keys, values):
                    if min <= k <= max:
                        values_expected.append(v)
                if values_expected != values_got:
                    btree.show()
                self.assertListEqual(values_expected, values_got)


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
