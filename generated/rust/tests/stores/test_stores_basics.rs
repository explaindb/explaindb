// Code generated from system/tests/stores/test_stores_basics.py. DO NOT EDIT.
//
//    This is ExplainDB, educational database systems materials.
//
//    Copyright (C) 2026 Prof. Dr. Jens Dittrich, Saarland University
//
//    This program is free software: you can redistribute it and/or modify
//    it under the terms of the GNU Affero General Public License as
//    published by the Free Software Foundation, either version 3 of the
//    License, or (at your option) any later version.
//
//    This program is distributed in the hope that it will be useful,
//    but WITHOUT ANY WARRANTY; without even the implied warranty of
//    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//    GNU Affero General Public License for more details.
//
//    You should have received a copy of the GNU Affero General Public License
//    along with this program.  If not, see <https://www.gnu.org/licenses/>.
//
//

//! Tests for the versioned and the transactional key-value store (Python: `system/tests/stores/test_stores_basics.py`).

use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use crate::common::{Stuff, create_fake_data, delete_marker, update};
use explaindb::{
    Clause, IsolationLevel, JournalEntry, KvStoreEntry, StoreError, TdEntry,
    TransactionalKeyValueStore, TransactionalStore, Validation, Version, VersionEntry,
    VersionedKeyValueStore, VersionedStore, WhereClause,
};
use indexmap::IndexMap;

/// Checks the basics of a store `S`: after a bulkload of 100 objects, the store holds 100 keys in the order of the
/// input; each key has exactly one committed version, an update with the loaded object and `start_validity` 0, and no
/// work-in-progress version; `get` returns the loaded object.
///
/// Python's test also checks the types of keys, version lists and values with `isinstance`; in Rust the compiler
/// guarantees these types.
fn check_key_value_store_basics<S>()
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let input_data: Vec<(String, Stuff)> = create_fake_data(100);
    let mut store: S = S::default();
    // bulkload 100 (key, Stuff) pairs outside of any transaction; the store takes ownership of the objects, so load
    // a copy and keep the input for comparison:
    store.bulkload(input_data.clone()).unwrap();

    assert_eq!(store.size(), 100);
    // the store keeps the order in which the keys were inserted, as Python's dict does:
    let keys: Vec<&String> = store.key_value_store().keys().collect();
    let input_keys: Vec<&String> = input_data.iter().map(|(key, _)| key).collect();
    assert_eq!(keys, input_keys);

    // check each object's versions against the input; timestamp 0 makes the loaded version visible to every
    // transaction:
    for (key, value) in &input_data {
        let entry: &KvStoreEntry<Stuff> = &store.key_value_store()[key];
        assert_eq!(
            entry.committed,
            vec![VersionEntry {
                start_validity: 0,
                version: Version::Update(value.clone()),
            }]
        );
        assert_eq!(entry.wip, None);
        assert_eq!(store.get(key), Ok(value));
    }
}

/// The basics of [`check_key_value_store_basics`] hold for every store; the indexed transactional store is added
/// here once it is ported.
#[test]
fn test_key_value_store_basics() {
    check_key_value_store_basics::<VersionedKeyValueStore<Stuff>>();
    check_key_value_store_basics::<TransactionalKeyValueStore<Stuff>>();
}

/// A new transactional store is empty (no objects, no transactions, no journal entries) and hands out the
/// transaction ids 1, 2, ... in this order.
#[test]
fn test_transactional_key_value_store() {
    // a new store is empty:
    let mut store: TransactionalKeyValueStore<Stuff> = TransactionalKeyValueStore::new();
    assert_eq!(store.size(), 0);
    assert!(store.state.td.is_empty());
    assert!(store.state.committed_transactions_trace.is_empty());
    assert_eq!(store.state.journal.size(), 0);

    // the transaction id counter starts at 1; each call returns the current value and then increments it:
    assert_eq!(store.state.ta_id, 1);
    assert_eq!(store.next_ta_id(), 1);
    assert_eq!(store.next_ta_id(), 2);
}

/// `begin_transaction` adds the transaction to the transaction dictionary with no reads, no writes and no commit
/// timestamp. It also stores the number of transactions that had committed when it began (0); this number does not
/// change when the transaction itself commits while a second transaction runs, and a transaction that begins
/// afterwards gets 1.
///
/// ```text
/// TA 1                                TA 2                                TA 3
/// begin
///                                     begin
/// commit
///                                                                         begin
/// ```
///
/// TA 3 is Rust only. Python stores the index of the last committed transaction in the trace instead, which is -1
/// before the first commit; Rust stores the length of the trace, i.e. the position after that index.
#[test]
fn test_begin_transaction() {
    let mut store: TransactionalKeyValueStore<Stuff> = TransactionalKeyValueStore::new();
    let ta_id: u64 = store.begin_transaction();

    // check store:
    assert_eq!(store.key_value_store().len(), 0);
    let td_entry: &TdEntry<Stuff> = &store.state.td[&ta_id];
    assert!(td_entry.read_clauses.is_empty());
    assert!(td_entry.write_set.is_empty());
    assert_eq!(td_entry.committed_timestamp, None);
    assert_eq!(td_entry.committed_transactions_at_begin, 0);

    // start a second TA, then commit TA 1 while TA 2 is still running:
    store.begin_transaction();
    store.commit_transaction(ta_id).unwrap();

    // TA 1's own commit does not change the number it stored at its begin:
    assert_eq!(store.state.td[&ta_id].committed_transactions_at_begin, 0);

    // a transaction that begins after one commit sees a trace of length 1 (Python: index 0):
    let later_ta_id: u64 = store.begin_transaction();
    assert_eq!(
        store.state.td[&later_ta_id].committed_transactions_at_begin,
        1
    );
}

/// The journal holds one list of entries per transaction: `Begin` at the start, then `Update` and `Delete` for its
/// writes, and `Commit` with the commit timestamp or `Abort` at the end. The journal has one key per transaction,
/// so its size is the number of transactions begun.
///
/// ```text
/// TA 1                                TA 2
/// begin
///                                     begin
/// commit (timestamp 3)
///                                     update "a" to "b"
///                                     update "b" to "c"
///                                     delete "b"
///                                     abort
/// ```
#[test]
fn test_journaling() {
    let mut store: TransactionalKeyValueStore<String> = TransactionalKeyValueStore::new();
    let ta_id: u64 = store.begin_transaction();

    // check begin:
    assert_eq!(store.state.journal.size(), 1);
    assert_eq!(
        store.state.journal.get(&ta_id).unwrap(),
        [JournalEntry::Begin { ta_id }]
    );

    let ta_id_2: u64 = store.begin_transaction();
    // check second begin:
    assert_eq!(store.state.journal.size(), 2);
    assert_eq!(store.state.journal.get(&ta_id).unwrap().len(), 1);
    assert_eq!(
        store.state.journal.get(&ta_id_2).unwrap(),
        [JournalEntry::Begin { ta_id: ta_id_2 }]
    );

    store.commit_transaction(ta_id).unwrap();
    // check commit; transaction ids and commit timestamps share one counter, so after the two begins (ids 1 and 2)
    // the commit of TA 1 gets timestamp 3:
    assert_eq!(store.state.journal.size(), 2);
    assert_eq!(
        store.state.journal.get(&ta_id).unwrap(),
        [
            JournalEntry::Begin { ta_id },
            JournalEntry::Commit {
                ta_id,
                commit_timestamp: 3
            },
        ]
    );

    store.update_object("a", "b".to_string(), ta_id_2).unwrap();
    // check update:
    assert_eq!(store.state.journal.size(), 2);
    assert_eq!(store.state.journal.get(&ta_id_2).unwrap().len(), 2);
    assert_eq!(
        store.state.journal.get(&ta_id_2).unwrap()[1],
        JournalEntry::Update {
            ta_id: ta_id_2,
            object_id: "a".to_string(),
            new_value: "b".to_string(),
        }
    );

    store.update_object("b", "c".to_string(), ta_id_2).unwrap();
    // check update:
    assert_eq!(store.state.journal.size(), 2);
    assert_eq!(store.state.journal.get(&ta_id_2).unwrap().len(), 3);
    assert_eq!(
        store.state.journal.get(&ta_id_2).unwrap()[2],
        JournalEntry::Update {
            ta_id: ta_id_2,
            object_id: "b".to_string(),
            new_value: "c".to_string(),
        }
    );

    store.delete_object("b", ta_id_2).unwrap();
    // check delete:
    assert_eq!(store.state.journal.size(), 2);
    assert_eq!(store.state.journal.get(&ta_id_2).unwrap().len(), 4);
    assert_eq!(
        store.state.journal.get(&ta_id_2).unwrap()[3],
        JournalEntry::Delete {
            ta_id: ta_id_2,
            object_id: "b".to_string(),
        }
    );

    store.abort_transaction(ta_id_2);
    // check abort:
    assert_eq!(store.state.journal.size(), 2);
    assert_eq!(store.state.journal.get(&ta_id_2).unwrap().len(), 5);
    assert_eq!(
        store.state.journal.get(&ta_id_2).unwrap()[4],
        JournalEntry::Abort { ta_id: ta_id_2 }
    );
}

/// Checks that `put` of a key that is already in the store `S` fails with `KeyExists` and leaves the stored value
/// and its versions unchanged.
fn check_put_of_existing_key_fails<S>()
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("A", Stuff { a: 1, b: 2 }).unwrap();

    assert_eq!(
        store.put("A", Stuff { a: 3, b: 4 }),
        Err(StoreError::KeyExists("A".to_string()))
    );
    assert_eq!(store.size(), 1);
    assert_eq!(store.get("A"), Ok(&Stuff { a: 1, b: 2 }));
    assert_eq!(
        store.key_value_store()["A"].committed,
        vec![update(0, Stuff { a: 1, b: 2 })]
    );
}

/// `put` of an existing key fails in the versioned and in the transactional store, see
/// [`check_put_of_existing_key_fails`].
#[test]
fn put_of_existing_key_fails() {
    check_put_of_existing_key_fails::<VersionedKeyValueStore<Stuff>>();
    check_put_of_existing_key_fails::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that `get` and `delete` of a key that is not in the store `S` fail with `KeyNotFound`, both in an empty
/// store and in a store holding other keys, and that the failed `delete` adds nothing.
fn check_get_and_delete_of_missing_key_fail<S>()
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    assert_eq!(
        store.get("A"),
        Err(StoreError::KeyNotFound("A".to_string()))
    );
    assert_eq!(
        store.delete("A"),
        Err(StoreError::KeyNotFound("A".to_string()))
    );
    assert_eq!(store.size(), 0);

    store.put("A", Stuff { a: 1, b: 2 }).unwrap();
    assert_eq!(
        store.get("B"),
        Err(StoreError::KeyNotFound("B".to_string()))
    );
    assert_eq!(
        store.delete("B"),
        Err(StoreError::KeyNotFound("B".to_string()))
    );
    assert_eq!(store.size(), 1);
}

/// `get` and `delete` of a missing key fail in the versioned store, see [`check_get_and_delete_of_missing_key_fail`].
/// The transactional store refuses `delete` without autocommit, see
/// [`test_without_autocommit_delete_and_calls_with_id_none_are_refused_in_the_load_phase`].
#[test]
fn get_and_delete_of_missing_key_fail() {
    check_get_and_delete_of_missing_key_fail::<VersionedKeyValueStore<Stuff>>();
}

/// Checks what a delete leaves behind in the store `S`: the key stays in the store, so `size` still counts it and
/// `put` still fails with `KeyExists`, but `get` fails with `NotVisible`. Deleting again succeeds and appends a
/// second delete marker, so the versions are update, delete, delete, all with `start_validity` 0.
///
/// Python's `get` crashes on a deleted object; `NotVisible` is the Rust port's error for this case.
fn check_delete_keeps_key_with_delete_marker<S>()
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("A", Stuff { a: 1, b: 2 }).unwrap();

    assert_eq!(store.delete("A"), Ok(()));
    assert_eq!(store.size(), 1);
    assert_eq!(store.get("A"), Err(StoreError::NotVisible("A".to_string())));
    assert_eq!(
        store.put("A", Stuff { a: 3, b: 4 }),
        Err(StoreError::KeyExists("A".to_string()))
    );

    assert_eq!(store.delete("A"), Ok(()));
    let entry: &KvStoreEntry<Stuff> = &store.key_value_store()["A"];
    assert_eq!(
        entry.committed,
        vec![
            update(0, Stuff { a: 1, b: 2 }),
            delete_marker(0),
            delete_marker(0),
        ]
    );
    assert_eq!(entry.wip, None);
}

/// A delete in the versioned store keeps the key with a delete marker, see
/// [`check_delete_keeps_key_with_delete_marker`]. The transactional store refuses `delete` without autocommit, see
/// [`test_without_autocommit_delete_and_calls_with_id_none_are_refused_in_the_load_phase`].
#[test]
fn delete_keeps_key_with_delete_marker() {
    check_delete_keeps_key_with_delete_marker::<VersionedKeyValueStore<Stuff>>();
}

/// Checks that `get` fails with `NotVisible` for a key of the store `S` that has no committed version, only a
/// work-in-progress version, as for an object whose insert is not committed yet.
///
/// Python's `get` crashes in this case; `NotVisible` is the Rust port's error for it.
fn check_get_without_committed_version_is_not_visible<S>()
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.key_value_store_mut().insert(
        "A".to_string(),
        KvStoreEntry {
            committed: vec![],
            wip: Some(update(1, Stuff { a: 1, b: 2 })),
        },
    );
    assert_eq!(store.get("A"), Err(StoreError::NotVisible("A".to_string())));
}

/// `get` of a key without committed version fails in the versioned and in the transactional store, see
/// [`check_get_without_committed_version_is_not_visible`].
#[test]
fn get_without_committed_version_is_not_visible() {
    check_get_without_committed_version_is_not_visible::<VersionedKeyValueStore<Stuff>>();
    check_get_without_committed_version_is_not_visible::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that a bulkload into the store `S` whose input repeats a key fails with `KeyExists` for that key: the
/// pairs before the duplicate stay in the store with their first value, the pairs after it are not loaded.
fn check_bulkload_stops_at_duplicate_key<S>()
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    let input_data: Vec<(&str, Stuff)> = vec![
        ("A", Stuff { a: 1, b: 1 }),
        ("B", Stuff { a: 2, b: 2 }),
        ("A", Stuff { a: 3, b: 3 }),
        ("C", Stuff { a: 4, b: 4 }),
    ];

    assert_eq!(
        store.bulkload(input_data),
        Err(StoreError::KeyExists("A".to_string()))
    );
    let keys: Vec<&String> = store.key_value_store().keys().collect();
    assert_eq!(keys, ["A", "B"]);
    assert_eq!(store.get("A"), Ok(&Stuff { a: 1, b: 1 }));
    assert_eq!(store.get("B"), Ok(&Stuff { a: 2, b: 2 }));
    assert_eq!(
        store.get("C"),
        Err(StoreError::KeyNotFound("C".to_string()))
    );
}

/// A bulkload into the versioned and into the transactional store stops at a duplicate key, see
/// [`check_bulkload_stops_at_duplicate_key`].
#[test]
fn bulkload_stops_at_duplicate_key() {
    check_bulkload_stops_at_duplicate_key::<VersionedKeyValueStore<Stuff>>();
    check_bulkload_stops_at_duplicate_key::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that `flush` of the store `S`, for all objects or for a single one, leaves the store unchanged, as the
/// store keeps its data in memory only. If `delete_one` is set, the store also holds a delete marker; the
/// transactional store refuses `delete` without autocommit, so it runs without.
fn check_flush_changes_nothing<S>(delete_one: bool)
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.bulkload(create_fake_data(3)).unwrap();
    if delete_one {
        store.delete("1").unwrap();
    }
    let before: IndexMap<String, KvStoreEntry<Stuff>> = store.key_value_store().clone();

    store.flush(None);
    store.flush(Some("0"));

    // compare as lists, so that the order of the keys counts: `==` of two maps ignores it
    let after: Vec<(&String, &KvStoreEntry<Stuff>)> = store.key_value_store().iter().collect();
    let expected: Vec<(&String, &KvStoreEntry<Stuff>)> = before.iter().collect();
    assert_eq!(after, expected);
}

/// `flush` of the versioned and of the transactional store changes nothing, see [`check_flush_changes_nothing`].
#[test]
fn flush_changes_nothing() {
    check_flush_changes_nothing::<VersionedKeyValueStore<Stuff>>(true);
    check_flush_changes_nothing::<TransactionalKeyValueStore<Stuff>>(false);
}

/// Iterating over a store entry, with `iter()` or with `for version in &entry`, yields the committed versions in
/// order and then the work-in-progress version.
#[test]
fn kv_store_entry_iterates_committed_versions_then_wip() {
    let entry: KvStoreEntry<Stuff> = KvStoreEntry {
        committed: vec![update(0, Stuff { a: 1, b: 1 }), delete_marker(5)],
        wip: Some(update(7, Stuff { a: 2, b: 2 })),
    };
    let expected: Vec<&VersionEntry<Stuff>> = vec![
        &entry.committed[0],
        &entry.committed[1],
        entry.wip.as_ref().unwrap(),
    ];

    let with_iter: Vec<&VersionEntry<Stuff>> = entry.iter().collect();
    assert_eq!(with_iter, expected);

    let mut with_for_loop: Vec<&VersionEntry<Stuff>> = Vec::new();
    for version in &entry {
        with_for_loop.push(version);
    }
    assert_eq!(with_for_loop, expected);
}

/// Iterating over a store entry without a work-in-progress version yields only the committed versions; an entry
/// with only a work-in-progress version yields only that one.
#[test]
fn kv_store_entry_iterates_without_wip_or_without_committed_versions() {
    let only_committed: KvStoreEntry<Stuff> = KvStoreEntry {
        committed: vec![update(0, Stuff { a: 1, b: 1 }), delete_marker(5)],
        wip: None,
    };
    let start_validities: Vec<u64> = only_committed
        .iter()
        .map(|version| version.start_validity)
        .collect();
    assert_eq!(start_validities, [0, 5]);

    let only_wip: KvStoreEntry<Stuff> = KvStoreEntry {
        committed: vec![],
        wip: Some(update(7, Stuff { a: 2, b: 2 })),
    };
    let start_validities: Vec<u64> = (&only_wip)
        .into_iter()
        .map(|version| version.start_validity)
        .collect();
    assert_eq!(start_validities, [7]);
}

/// The messages of the store errors name the object; the messages of `KeyExists` and `KeyNotFound` are those of
/// Python's `KeyError`s, `NotVisible` has no Python counterpart.
#[test]
fn store_error_messages() {
    assert_eq!(
        StoreError::KeyExists("A".to_string()).to_string(),
        "object A already exists in the store"
    );
    assert_eq!(
        StoreError::KeyNotFound("A".to_string()).to_string(),
        "object A not found in the store"
    );
    assert_eq!(
        StoreError::NotVisible("A".to_string()).to_string(),
        "object A has no committed value in the store"
    );
}

// operations without a transaction id (Python: the class `OperationsWithoutTransactionTest`): `put`, `bulkload`,
// `get` and `delete` without a transaction id, and `read_objects`, `update_object` and `delete_object` with the
// transaction id `None`, in the transactional store. Without autocommit, `put`, `bulkload` and `get` load the initial
// state before the first transaction and are refused afterwards, while `delete` and the three calls with `None` are
// always refused; with autocommit each one runs as a transaction of its own. Python runs these tests on both
// transactional stores; the indexed store follows in step 2 of the port.

/// Returns the ids of the transactions of `store` that have begun and have neither committed nor aborted.
fn open_transactions<S: TransactionalStore>(store: &S) -> BTreeSet<u64> {
    store
        .state()
        .td
        .iter()
        .filter(|(_, entry)| entry.committed_timestamp.is_none())
        .map(|(ta_id, _)| *ta_id)
        .collect()
}

/// Reads all objects in a new transaction of `store`, commits it and returns what it saw, by object id.
fn read_all_in_new_transaction<S: TransactionalStore<Value = Stuff>>(
    store: &mut S,
) -> BTreeMap<String, Stuff> {
    let ta_id: u64 = store.begin_transaction();
    let visible: BTreeMap<String, Stuff> = store
        .read_objects(ta_id, None, true)
        .unwrap()
        .into_iter()
        .collect();
    store.commit_transaction(ta_id).unwrap();
    visible
}

/// Returns the pairs `pairs` as a map from object id to object, to compare with what a transaction saw.
fn objects(pairs: &[(&str, Stuff)]) -> BTreeMap<String, Stuff> {
    pairs
        .iter()
        .map(|(object_id, object)| (object_id.to_string(), object.clone()))
        .collect()
}

/// Returns an empty store `S` with autocommit switched on (Python: `store_class(autocommit=True)`).
fn store_with_autocommit<S: TransactionalStore + Default>() -> S {
    let mut store: S = S::default();
    store.state_mut().autocommit = true;
    store
}

/// Returns the error of an operation `operation` refused without autocommit; `transaction_begun` tells whether it is
/// refused only because a transaction has begun.
fn refused<T>(operation: &str, transaction_begun: bool) -> Result<T, StoreError> {
    Err(StoreError::AutocommitRequired {
        operation: operation.to_string(),
        transaction_begun,
    })
}

/// Returns the start timestamps of the committed versions of object `object_id` of `store`, oldest first.
fn start_validities<S: VersionedStore<Value = Stuff>>(store: &S, object_id: &str) -> Vec<u64> {
    store.key_value_store()[object_id]
        .committed
        .iter()
        .map(|version| version.start_validity)
        .collect()
}

/// Returns the kinds (`"update"` or `"delete"`) of the committed versions of object `object_id` of `store`, oldest
/// first, and checks that their start timestamps strictly increase.
fn committed_version_kinds<S: VersionedStore<Value = Stuff>>(
    store: &S,
    object_id: &str,
) -> Vec<&'static str> {
    let starts: Vec<u64> = start_validities(store, object_id);
    assert!(
        starts.windows(2).all(|pair| pair[0] < pair[1]),
        "the start timestamps of {object_id} must strictly increase: {starts:?}"
    );
    store.key_value_store()[object_id]
        .committed
        .iter()
        .map(|version| match version.version {
            Version::Update(_) => "update",
            Version::Delete => "delete",
        })
        .collect()
}

/// Asserts that `result` is the error of an aborted transaction; on failure, the message names the case `case` and
/// shows what was returned.
fn assert_aborted<T: std::fmt::Debug>(result: Result<T, StoreError>, case: &str) {
    assert!(
        matches!(result, Err(StoreError::TransactionAborted(_))),
        "{case}: the transaction must be aborted, got {result:?}"
    );
}

/// Checks that without autocommit, `put` and `bulkload` of the store `S` before the first transaction store committed
/// versions with start timestamp 0 and use up no transaction id; `get` returns them, and the first transaction gets
/// id 1 and sees them.
fn check_load_phase_stores_the_initial_state<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();

    // load three objects with put and bulkload; no transaction id is used up:
    store.put("1", Stuff { a: 1, b: 1 }).unwrap();
    store
        .bulkload([("2", Stuff { a: 2, b: 2 }), ("3", Stuff { a: 3, b: 3 })])
        .unwrap();
    assert_eq!(store.state().ta_id, 1);

    // each object has a single committed version with start timestamp 0, and get returns it:
    for object_id in ["1", "2", "3"] {
        assert_eq!(start_validities(&store, object_id), [0], "{object_id}");
    }
    assert_eq!(store.get("2"), Ok(&Stuff { a: 2, b: 2 }));

    // the first transaction gets id 1 and sees all three objects:
    let t_1: u64 = store.begin_transaction();
    assert_eq!(t_1, 1);
    let visible: BTreeMap<String, Stuff> = store
        .read_objects(t_1, None, true)
        .unwrap()
        .into_iter()
        .collect();
    assert_eq!(
        visible,
        objects(&[
            ("1", Stuff { a: 1, b: 1 }),
            ("2", Stuff { a: 2, b: 2 }),
            ("3", Stuff { a: 3, b: 3 }),
        ])
    );
}

/// The load phase of a [`TransactionalKeyValueStore`] stores the initial state, see
/// [`check_load_phase_stores_the_initial_state`].
#[test]
fn test_load_phase_stores_the_initial_state() {
    check_load_phase_stores_the_initial_state::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that without autocommit, `get` of the store `S` before the first transaction reads at the call: it returns
/// `KeyNotFound` for a missing object at once and the loaded version of an existing one; a transaction then deletes
/// that object.
///
/// ```text
/// load phase                  T1
/// put "2" as (2, 2)
/// get "missing" -> KeyNotFound
/// get "2" -> (2, 2)
///                             begin
///                             delete "2"
///                             commit
/// ```
///
/// Python's test also keeps the iterator returned by a `get` in the load phase and advances it after T1 deleted the
/// object; in Rust, `get` returns a reference, which cannot be kept while a transaction writes the store.
fn check_load_phase_get_reads_at_the_call<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("2", Stuff { a: 2, b: 2 }).unwrap();

    // get of a missing object returns KeyNotFound at the call:
    assert_eq!(
        store.get("missing"),
        Err(StoreError::KeyNotFound("missing".to_string()))
    );

    // get of "2" returns the loaded object:
    assert_eq!(store.get("2"), Ok(&Stuff { a: 2, b: 2 }));

    // T1 deletes "2" and commits; a new transaction no longer sees "2":
    let t_1: u64 = store.begin_transaction();
    store.delete_object("2", t_1).unwrap();
    store.commit_transaction(t_1).unwrap();
    assert_eq!(read_all_in_new_transaction(&mut store), BTreeMap::new());
}

/// `get` in the load phase of a [`TransactionalKeyValueStore`] reads at the call, see
/// [`check_load_phase_get_reads_at_the_call`].
#[test]
fn test_load_phase_get_reads_at_the_call() {
    check_load_phase_get_reads_at_the_call::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that without autocommit, `put`, `bulkload`, `get` and `delete`, and `read_objects`, `update_object` and
/// `delete_object` with the transaction id `None`, of the store `S` return `AutocommitRequired` once a transaction
/// has begun, whether it is still open, committed or aborted; the refused calls begin no transaction and change
/// nothing, and an open transaction still commits.
///
/// ```text
/// T1                          without transaction id
///                             put "1" as (1, 1)
/// begin
/// insert "2" as (2, 2)
/// commit, abort or stay open
///                             put "3" -> AutocommitRequired
///                             bulkload "4" -> AutocommitRequired
///                             get "1" -> AutocommitRequired
///                             delete "1" -> AutocommitRequired
///                             read_objects all -> AutocommitRequired
///                             update_object "1" to (9, 9) -> AutocommitRequired
///                             delete_object "1" -> AutocommitRequired
/// commit (if still open)
/// ```
fn check_without_autocommit_operations_are_refused_once_a_transaction_has_begun<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    for situation in ["open", "committed", "aborted"] {
        let mut store: S = S::default();
        store.put("1", Stuff { a: 1, b: 1 }).unwrap();

        // T1 inserts "2" and then stays open, commits or aborts:
        let t_1: u64 = store.begin_transaction();
        store.update_object("2", Stuff { a: 2, b: 2 }, t_1).unwrap();
        match situation {
            "committed" => store.commit_transaction(t_1).unwrap(),
            "aborted" => store.abort_transaction(t_1),
            _ => {}
        }
        let counter: u64 = store.state().ta_id;

        // each operation without a transaction id is refused at the call; put, bulkload and get name the begun
        // transaction as the reason:
        assert_eq!(
            store.put("3", Stuff { a: 3, b: 3 }),
            refused("put", true),
            "T1 {situation}"
        );
        assert_eq!(
            store.bulkload([("4", Stuff { a: 4, b: 4 })]),
            refused("bulkload", true),
            "T1 {situation}"
        );
        assert_eq!(store.get("1"), refused("get", true), "T1 {situation}");
        assert_eq!(
            store.delete("1"),
            refused("delete", false),
            "T1 {situation}"
        );

        // so is each transactional call with the transaction id None:
        assert_eq!(
            store.read_objects(None, None, true),
            refused("read_objects", false),
            "T1 {situation}"
        );
        assert_eq!(
            store.update_object("1", Stuff { a: 9, b: 9 }, None),
            refused("update_object", false),
            "T1 {situation}"
        );
        assert_eq!(
            store.delete_object("1", None),
            refused("delete_object", false),
            "T1 {situation}"
        );

        // the refused calls began no transaction and left "1" with its single version:
        assert_eq!(store.state().ta_id, counter, "T1 {situation}");
        let expected_open: BTreeSet<u64> = if situation == "open" {
            BTreeSet::from([t_1])
        } else {
            BTreeSet::new()
        };
        assert_eq!(open_transactions(&store), expected_open, "T1 {situation}");
        assert_eq!(
            store.key_value_store()["1"].committed.len(),
            1,
            "T1 {situation}"
        );

        // an open T1 still commits; a new transaction sees "1", and "2" unless T1 aborted:
        if situation == "open" {
            store.commit_transaction(t_1).unwrap();
        }
        let mut expected: BTreeMap<String, Stuff> = objects(&[("1", Stuff { a: 1, b: 1 })]);
        if situation != "aborted" {
            expected.insert("2".to_string(), Stuff { a: 2, b: 2 });
        }
        assert_eq!(
            read_all_in_new_transaction(&mut store),
            expected,
            "T1 {situation}"
        );
    }
}

/// Without autocommit, a [`TransactionalKeyValueStore`] refuses the operations without a transaction id once a
/// transaction has begun, see [`check_without_autocommit_operations_are_refused_once_a_transaction_has_begun`].
#[test]
fn test_without_autocommit_operations_are_refused_once_a_transaction_has_begun() {
    check_without_autocommit_operations_are_refused_once_a_transaction_has_begun::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// A call of an operation on a store `S` whose result is only checked for an error.
type StoreCall<S> = fn(&mut S) -> Result<(), StoreError>;

/// Checks that without autocommit, `delete`, and `read_objects`, `update_object` and `delete_object` with the
/// transaction id `None`, of the store `S` return `AutocommitRequired` also before the first transaction begins; the
/// object keeps its single version and gets no work-in-progress version, and no transaction has begun.
fn check_without_autocommit_delete_and_calls_with_id_none_are_refused_in_the_load_phase<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    // each refused call, by the name of its operation:
    let refused_calls: [(&str, StoreCall<S>); 4] = [
        ("delete", |store: &mut S| store.delete("1")),
        ("read_objects", |store: &mut S| {
            store.read_objects(None, None, true).map(|_| ())
        }),
        ("update_object", |store: &mut S| {
            store.update_object("1", Stuff { a: 9, b: 9 }, None)
        }),
        ("delete_object", |store: &mut S| {
            store.delete_object("1", None)
        }),
    ];
    for (operation, refused_call) in refused_calls {
        let mut store: S = S::default();
        store.put("1", Stuff { a: 1, b: 1 }).unwrap();

        // the call is refused with an error that names the operation:
        assert_eq!(
            refused_call(&mut store),
            refused(operation, false),
            "{operation}"
        );

        // "1" keeps its single version with start timestamp 0 and has no work-in-progress version, no transaction
        // has begun, and get still returns the object:
        let entry: &KvStoreEntry<Stuff> = &store.key_value_store()["1"];
        assert_eq!(
            entry.committed,
            vec![update(0, Stuff { a: 1, b: 1 })],
            "{operation}"
        );
        assert_eq!(entry.wip, None, "{operation}");
        assert_eq!(store.state().ta_id, 1, "{operation}");
        assert_eq!(store.get("1"), Ok(&Stuff { a: 1, b: 1 }), "{operation}");
    }
}

/// Without autocommit, a [`TransactionalKeyValueStore`] refuses `delete` and the calls with the transaction id
/// `None` also in the load phase, see
/// [`check_without_autocommit_delete_and_calls_with_id_none_are_refused_in_the_load_phase`].
#[test]
fn test_without_autocommit_delete_and_calls_with_id_none_are_refused_in_the_load_phase() {
    check_without_autocommit_delete_and_calls_with_id_none_are_refused_in_the_load_phase::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that with autocommit, `put` of the store `S` inserts the object in a transaction of its own, also before
/// any other transaction, so its version gets a commit timestamp; a `put` of a visible object returns `KeyExists`,
/// adds no version and leaves no transaction open: its transaction is aborted and uses up one value of the counter
/// (its begin).
fn check_autocommit_put_inserts_in_a_transaction_of_its_own<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();

    // the put runs as transaction 1, which commits at timestamp 2:
    store.put("1", Stuff { a: 1, b: 1 }).unwrap();
    assert_eq!(start_validities(&store, "1"), [2]);
    assert_eq!(store.state().ta_id, 3);
    assert_eq!(store.state().committed_transactions_trace, [1]);
    assert_eq!(open_transactions(&store), BTreeSet::new());

    // a later transaction sees "1":
    assert_eq!(
        read_all_in_new_transaction(&mut store),
        objects(&[("1", Stuff { a: 1, b: 1 })])
    );

    // a second put of "1" returns KeyExists, adds no version and leaves no transaction open:
    let counter: u64 = store.state().ta_id;
    let trace: Vec<u64> = store.state().committed_transactions_trace.clone();
    assert_eq!(
        store.put("1", Stuff { a: 9, b: 9 }),
        Err(StoreError::KeyExists("1".to_string()))
    );
    assert_eq!(store.key_value_store()["1"].committed.len(), 1);
    assert_eq!(open_transactions(&store), BTreeSet::new());

    // the failed put used up one counter value (its begin) and was aborted, not committed; a new transaction still
    // sees the first version of "1":
    assert_eq!(store.state().ta_id, counter + 1);
    assert_eq!(store.state().committed_transactions_trace, trace);
    assert_eq!(
        read_all_in_new_transaction(&mut store),
        objects(&[("1", Stuff { a: 1, b: 1 })])
    );
}

/// With autocommit, `put` of a [`TransactionalKeyValueStore`] inserts in a transaction of its own, see
/// [`check_autocommit_put_inserts_in_a_transaction_of_its_own`].
#[test]
fn test_autocommit_put_inserts_in_a_transaction_of_its_own() {
    check_autocommit_put_inserts_in_a_transaction_of_its_own::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that with autocommit, `put`, an update in an explicit transaction and `delete` of the store `S` write
/// versions with increasing timestamps, so reads afterwards work: the deleted object is not visible, `get` and
/// `delete` return `KeyNotFound` (the failed `delete` aborts its transaction, which uses up one value of the counter),
/// and `put` inserts it again.
///
/// ```text
/// T1                          autocommit
///                             put "1" as (1, 1), commit
/// begin
/// update "1" to (2, 2)
/// commit
///                             delete "1", commit
///                             get "1" -> KeyNotFound
///                             delete "1" -> KeyNotFound
///                             put "1" as (3, 3), commit
/// ```
fn check_autocommit_delete_after_put_and_update_keeps_the_versions_in_order<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();

    // put "1", update it in T1, and delete it:
    store.put("1", Stuff { a: 1, b: 1 }).unwrap();
    let t_1: u64 = store.begin_transaction();
    store.update_object("1", Stuff { a: 2, b: 2 }, t_1).unwrap();
    store.commit_transaction(t_1).unwrap();
    store.delete("1").unwrap();

    // a new transaction reads without an error and sees nothing:
    assert_eq!(read_all_in_new_transaction(&mut store), BTreeMap::new());

    // get returns KeyNotFound at the call and leaves no transaction open:
    assert_eq!(
        store.get("1"),
        Err(StoreError::KeyNotFound("1".to_string()))
    );
    assert_eq!(open_transactions(&store), BTreeSet::new());

    // a second delete returns KeyNotFound at the call and leaves no transaction open:
    let counter: u64 = store.state().ta_id;
    let trace: Vec<u64> = store.state().committed_transactions_trace.clone();
    assert_eq!(
        store.delete("1"),
        Err(StoreError::KeyNotFound("1".to_string()))
    );
    assert_eq!(open_transactions(&store), BTreeSet::new());

    // the failed delete used up one counter value (its begin) and was aborted, not committed:
    assert_eq!(store.state().ta_id, counter + 1);
    assert_eq!(store.state().committed_transactions_trace, trace);

    // put inserts "1" again:
    store.put("1", Stuff { a: 3, b: 3 }).unwrap();
    assert_eq!(store.get("1"), Ok(&Stuff { a: 3, b: 3 }));
    assert_eq!(
        read_all_in_new_transaction(&mut store),
        objects(&[("1", Stuff { a: 3, b: 3 })])
    );

    // "1" has four committed versions (put, update, delete, put) with strictly increasing start timestamps:
    assert_eq!(
        committed_version_kinds(&store, "1"),
        ["update", "update", "delete", "update"]
    );
}

/// With autocommit, a [`TransactionalKeyValueStore`] keeps the versions of an object in order across `put`, an
/// update and `delete`, see [`check_autocommit_delete_after_put_and_update_keeps_the_versions_in_order`].
#[test]
fn test_autocommit_delete_after_put_and_update_keeps_the_versions_in_order() {
    check_autocommit_delete_after_put_and_update_keeps_the_versions_in_order::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that with autocommit, `get` of the store `S` reads in a transaction of its own and returns the newest
/// committed version of an object, not the work-in-progress version of an open transaction; it returns
/// `KeyNotFound` at the call for a missing object.
///
/// ```text
/// T1                          autocommit
///                             put "1" as (1, 1), commit
/// begin
/// update "1" to (2, 2)
///                             get "1" -> (1, 1), commit
///                             get "2" -> KeyNotFound
/// commit
///                             get "1" -> (2, 2), commit
/// ```
fn check_autocommit_get_returns_the_newest_committed_version<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();
    store.put("1", Stuff { a: 1, b: 1 }).unwrap();

    // while T1 holds a work-in-progress version of "1", get returns the committed one; its own transaction uses up
    // two values of the counter, one at the begin and one at the commit:
    let t_1: u64 = store.begin_transaction();
    store.update_object("1", Stuff { a: 2, b: 2 }, t_1).unwrap();
    let counter: u64 = store.state().ta_id;
    assert_eq!(store.get("1"), Ok(&Stuff { a: 1, b: 1 }));
    assert_eq!(store.state().ta_id, counter + 2);

    // get of a missing object returns KeyNotFound; only T1 is open:
    assert_eq!(
        store.get("2"),
        Err(StoreError::KeyNotFound("2".to_string()))
    );
    assert_eq!(open_transactions(&store), BTreeSet::from([t_1]));

    // after the commit of T1, get returns its version:
    store.commit_transaction(t_1).unwrap();
    assert_eq!(store.get("1"), Ok(&Stuff { a: 2, b: 2 }));
    assert_eq!(open_transactions(&store), BTreeSet::new());
}

/// With autocommit, `get` of a [`TransactionalKeyValueStore`] returns the newest committed version, see
/// [`check_autocommit_get_returns_the_newest_committed_version`].
#[test]
fn test_autocommit_get_returns_the_newest_committed_version() {
    check_autocommit_get_returns_the_newest_committed_version::<TransactionalKeyValueStore<Stuff>>(
    );
}

/// Checks that with autocommit, `bulkload` of the store `S` inserts all objects in one transaction; if an object is
/// visible already or occurs twice in the input, it returns `KeyExists` and inserts none of its objects; a later `put`
/// of one of them that is not visible succeeds.
///
/// Python's test also checks the index of the indexed store, which follows in step 2 of the port.
fn check_autocommit_bulkload_inserts_all_objects_or_none<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();
    let loaded: BTreeMap<String, Stuff> =
        objects(&[("1", Stuff { a: 1, b: 1 }), ("2", Stuff { a: 2, b: 2 })]);

    // both objects are committed by transaction 1 at timestamp 2:
    store.bulkload(loaded.clone()).unwrap();
    assert_eq!(start_validities(&store, "1"), [2]);
    assert_eq!(start_validities(&store, "2"), [2]);
    assert_eq!(store.state().committed_transactions_trace, [1]);

    // a bulkload with the visible "2" returns KeyExists; "3", inserted before, does not become visible:
    assert_eq!(
        store.bulkload([("3", Stuff { a: 3, b: 3 }), ("2", Stuff { a: 9, b: 9 })]),
        Err(StoreError::KeyExists("2".to_string()))
    );
    assert_eq!(open_transactions(&store), BTreeSet::new());
    assert_eq!(read_all_in_new_transaction(&mut store), loaded);

    // a bulkload that contains "4" twice returns KeyExists and inserts nothing:
    assert_eq!(
        store.bulkload([("4", Stuff { a: 4, b: 4 }), ("4", Stuff { a: 5, b: 5 })]),
        Err(StoreError::KeyExists("4".to_string()))
    );
    assert_eq!(open_transactions(&store), BTreeSet::new());
    assert_eq!(read_all_in_new_transaction(&mut store), loaded);

    // a put of "3", which the first failed bulkload had inserted, succeeds:
    store.put("3", Stuff { a: 3, b: 3 }).unwrap();
    let mut expected: BTreeMap<String, Stuff> = loaded.clone();
    expected.insert("3".to_string(), Stuff { a: 3, b: 3 });
    assert_eq!(read_all_in_new_transaction(&mut store), expected);
}

/// With autocommit, `bulkload` of a [`TransactionalKeyValueStore`] inserts all objects or none, see
/// [`check_autocommit_bulkload_inserts_all_objects_or_none`].
#[test]
fn test_autocommit_bulkload_inserts_all_objects_or_none() {
    check_autocommit_bulkload_inserts_all_objects_or_none::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that with autocommit, a `bulkload` of an empty input into the store `S` still begins and commits a
/// transaction of its own; it makes nothing visible and leaves no transaction open.
fn check_autocommit_empty_bulkload_runs_an_empty_transaction<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();

    // the empty bulkload runs as transaction 1, which commits; begin and commit use up two values of the counter:
    let counter: u64 = store.state().ta_id;
    store.bulkload(Vec::<(String, Stuff)>::new()).unwrap();
    assert_eq!(store.state().ta_id, counter + 2);
    assert_eq!(store.state().committed_transactions_trace, [1]);

    // no transaction is open, and a new transaction sees nothing:
    assert_eq!(open_transactions(&store), BTreeSet::new());
    assert_eq!(read_all_in_new_transaction(&mut store), BTreeMap::new());
}

/// With autocommit, an empty `bulkload` of a [`TransactionalKeyValueStore`] runs an empty transaction, see
/// [`check_autocommit_empty_bulkload_runs_an_empty_transaction`].
#[test]
fn test_autocommit_empty_bulkload_runs_an_empty_transaction() {
    check_autocommit_empty_bulkload_runs_an_empty_transaction::<TransactionalKeyValueStore<Stuff>>(
    );
}

/// Checks that with autocommit, `read_objects` of the store `S` with the transaction id `None` reads in a
/// transaction of its own, also before any other transaction: it returns the committed objects that match the where
/// clause, without the work-in-progress versions of an open transaction; its transaction commits and uses up two
/// values of the counter.
///
/// ```text
/// T1                          autocommit
///                             read all -> nothing, commit
///                             bulkload "1" as (1, 1), "5" as (5, 5), commit
/// begin
/// update "1" to (5, 1)
/// insert "3" as (5, 3)
///                             read all -> "1" as (1, 1), "5", commit
///                             read a == 5 -> "5", commit
/// commit
///                             read a == 5 -> "1" as (5, 1), "5", "3", commit
/// ```
fn check_autocommit_read_objects_returns_the_committed_objects_in_a_transaction_of_its_own<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();
    let where_a_5: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 5));

    // on the empty store, the read runs as transaction 1, which commits at timestamp 2:
    assert_eq!(store.read_objects(None, None, true), Ok(vec![]));
    assert_eq!(store.state().ta_id, 3);
    assert_eq!(store.state().committed_transactions_trace, [1]);

    // T1 writes work-in-progress versions of the committed "1" and the new "3", both with a == 5:
    store
        .bulkload([("1", Stuff { a: 1, b: 1 }), ("5", Stuff { a: 5, b: 5 })])
        .unwrap();
    let t_1: u64 = store.begin_transaction();
    store.update_object("1", Stuff { a: 5, b: 1 }, t_1).unwrap();
    store.update_object("3", Stuff { a: 5, b: 3 }, t_1).unwrap();

    // a read of all objects returns the committed versions only; its transaction commits with the next two counter
    // values, and only T1 stays open:
    let counter: u64 = store.state().ta_id;
    let mut trace: Vec<u64> = store.state().committed_transactions_trace.clone();
    assert_eq!(
        store.read_objects(None, None, true),
        Ok(vec![
            ("1".to_string(), Stuff { a: 1, b: 1 }),
            ("5".to_string(), Stuff { a: 5, b: 5 }),
        ])
    );
    assert_eq!(store.state().ta_id, counter + 2);
    trace.push(counter);
    assert_eq!(store.state().committed_transactions_trace, trace);
    assert_eq!(open_transactions(&store), BTreeSet::from([t_1]));

    // a read with a where clause returns only the committed object that matches it:
    assert_eq!(
        store.read_objects(None, Some(Rc::clone(&where_a_5)), true),
        Ok(vec![("5".to_string(), Stuff { a: 5, b: 5 })])
    );

    // after the commit of T1, the read returns its versions too:
    store.commit_transaction(t_1).unwrap();
    assert_eq!(
        store.read_objects(None, Some(where_a_5), true),
        Ok(vec![
            ("1".to_string(), Stuff { a: 5, b: 1 }),
            ("5".to_string(), Stuff { a: 5, b: 5 }),
            ("3".to_string(), Stuff { a: 5, b: 3 }),
        ])
    );
    assert_eq!(open_transactions(&store), BTreeSet::new());
}

/// With autocommit, `read_objects` of a [`TransactionalKeyValueStore`] with the transaction id `None` reads the
/// committed objects in a transaction of its own, see
/// [`check_autocommit_read_objects_returns_the_committed_objects_in_a_transaction_of_its_own`].
#[test]
fn test_autocommit_read_objects_returns_the_committed_objects_in_a_transaction_of_its_own() {
    check_autocommit_read_objects_returns_the_committed_objects_in_a_transaction_of_its_own::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Writes "1" as `object` with `update_object` and the transaction id `None` into `store`, and checks that its
/// transaction committed the new version with the next two counter values (Python: the local function
/// `update_in_own_transaction`).
fn update_in_own_transaction<S: TransactionalStore<Value = Stuff>>(store: &mut S, object: Stuff) {
    // the write runs as transaction <counter>, which commits at timestamp <counter + 1>:
    let counter: u64 = store.state().ta_id;
    let mut trace: Vec<u64> = store.state().committed_transactions_trace.clone();
    store.update_object("1", object.clone(), None).unwrap();
    assert_eq!(store.state().ta_id, counter + 2);
    trace.push(counter);
    assert_eq!(store.state().committed_transactions_trace, trace);
    assert_eq!(start_validities(store, "1").last(), Some(&(counter + 1)));

    // no transaction is open, and a new transaction sees the new version:
    assert_eq!(open_transactions(store), BTreeSet::new());
    assert_eq!(
        read_all_in_new_transaction(store),
        objects(&[("1", object)])
    );
}

/// Checks that with autocommit, `update_object` of the store `S` with the transaction id `None` inserts a missing
/// object and writes a new version of an existing or a deleted one, each time in a transaction of its own that
/// commits: every call uses up two values of the counter and adds a committed version with its commit timestamp, so
/// the versions stay in order.
fn check_autocommit_update_object_inserts_or_writes_a_new_version_in_a_transaction_of_its_own<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();

    // update_object inserts the missing "1", then writes a new version of it:
    update_in_own_transaction(&mut store, Stuff { a: 1, b: 1 });
    update_in_own_transaction(&mut store, Stuff { a: 2, b: 2 });

    // after a delete, update_object writes a new version of the deleted "1":
    store.delete("1").unwrap();
    update_in_own_transaction(&mut store, Stuff { a: 3, b: 3 });

    // "1" has four committed versions (two updates, the delete, an update) with strictly increasing start timestamps:
    assert_eq!(
        committed_version_kinds(&store, "1"),
        ["update", "update", "delete", "update"]
    );
}

/// With autocommit, `update_object` of a [`TransactionalKeyValueStore`] with the transaction id `None` inserts or
/// writes a new version in a transaction of its own, see
/// [`check_autocommit_update_object_inserts_or_writes_a_new_version_in_a_transaction_of_its_own`].
#[test]
fn test_autocommit_update_object_inserts_or_writes_a_new_version_in_a_transaction_of_its_own() {
    check_autocommit_update_object_inserts_or_writes_a_new_version_in_a_transaction_of_its_own::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that with autocommit, `delete_object` of the store `S` with the transaction id `None` deletes an object in
/// a transaction of its own that commits; on an object deleted already it commits another delete marker, where
/// `delete` returns `KeyNotFound`; for an object id that was never stored it returns `KeyNotFound` and aborts its
/// transaction, which uses up one value of the counter (its begin).
fn check_autocommit_delete_object_deletes_in_a_transaction_of_its_own<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();
    store.put("1", Stuff { a: 1, b: 1 }).unwrap();

    // delete_object deletes "1" in a transaction that commits with the next two counter values:
    let counter: u64 = store.state().ta_id;
    let mut trace: Vec<u64> = store.state().committed_transactions_trace.clone();
    store.delete_object("1", None).unwrap();
    assert_eq!(store.state().ta_id, counter + 2);
    trace.push(counter);
    assert_eq!(store.state().committed_transactions_trace, trace);
    assert_eq!(read_all_in_new_transaction(&mut store), BTreeMap::new());

    // a second delete_object of the deleted "1" commits too, and "1" stays deleted:
    let counter: u64 = store.state().ta_id;
    let mut trace: Vec<u64> = store.state().committed_transactions_trace.clone();
    store.delete_object("1", None).unwrap();
    trace.push(counter);
    assert_eq!(store.state().committed_transactions_trace, trace);
    assert_eq!(read_all_in_new_transaction(&mut store), BTreeMap::new());

    // delete of the deleted "1" returns KeyNotFound instead:
    assert_eq!(
        store.delete("1"),
        Err(StoreError::KeyNotFound("1".to_string()))
    );

    // "1" has the version of the put and two delete markers, with strictly increasing start timestamps:
    assert_eq!(
        committed_version_kinds(&store, "1"),
        ["update", "delete", "delete"]
    );

    // delete_object of an object id that was never stored returns KeyNotFound, adds no entry and leaves no
    // transaction open:
    let counter: u64 = store.state().ta_id;
    let trace: Vec<u64> = store.state().committed_transactions_trace.clone();
    assert_eq!(
        store.delete_object("missing", None),
        Err(StoreError::KeyNotFound("missing".to_string()))
    );
    assert!(!store.key_value_store().contains_key("missing"));
    assert_eq!(open_transactions(&store), BTreeSet::new());

    // its transaction used up one counter value (its begin) and was aborted, not committed:
    assert_eq!(store.state().ta_id, counter + 1);
    assert_eq!(store.state().committed_transactions_trace, trace);
}

/// With autocommit, `delete_object` of a [`TransactionalKeyValueStore`] with the transaction id `None` deletes in a
/// transaction of its own, see [`check_autocommit_delete_object_deletes_in_a_transaction_of_its_own`].
#[test]
fn test_autocommit_delete_object_deletes_in_a_transaction_of_its_own() {
    check_autocommit_delete_object_deletes_in_a_transaction_of_its_own::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that with autocommit, a `put`, `delete` or `bulkload`, or an `update_object` or `delete_object` with the
/// transaction id `None`, of the store `S` that writes an object an open transaction is writing returns
/// `TransactionAborted` and makes nothing visible; the open transaction is not affected and commits.
///
/// ```text
/// T1                          autocommit
///                             put "1" as (1, 1), commit
/// begin
/// update "1" to (1, 2)
/// insert "2" as (2, 2)
///                             put "2" as (8, 8) -> aborted
///                             delete "1" -> aborted
///                             bulkload "3", "2" -> aborted
///                             update_object "2" to (7, 7) -> aborted
///                             delete_object "1" -> aborted
/// commit
/// ```
///
/// Python's test also checks the index of the indexed store, which follows in step 2 of the port.
fn check_autocommit_write_to_an_object_an_open_transaction_writes_is_aborted<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_autocommit();
    store.put("1", Stuff { a: 1, b: 1 }).unwrap();

    // T1 updates the committed "1" and inserts the new "2":
    let t_1: u64 = store.begin_transaction();
    store.update_object("1", Stuff { a: 1, b: 2 }, t_1).unwrap();
    store.update_object("2", Stuff { a: 2, b: 2 }, t_1).unwrap();

    // the put of "2" is aborted, as T1 is inserting "2"; T1 stays open:
    assert_aborted(store.put("2", Stuff { a: 8, b: 8 }), "put");
    assert_eq!(open_transactions(&store), BTreeSet::from([t_1]));

    // the delete of "1" is aborted; T1 stays open:
    assert_aborted(store.delete("1"), "delete");
    assert_eq!(open_transactions(&store), BTreeSet::from([t_1]));

    // the bulkload inserts "3" and is aborted at "2"; T1 stays open:
    assert_aborted(
        store.bulkload([("3", Stuff { a: 3, b: 3 }), ("2", Stuff { a: 9, b: 9 })]),
        "bulkload",
    );
    assert_eq!(open_transactions(&store), BTreeSet::from([t_1]));

    // update_object of "2" is aborted; T1 stays open:
    assert_aborted(
        store.update_object("2", Stuff { a: 7, b: 7 }, None),
        "update_object",
    );
    assert_eq!(open_transactions(&store), BTreeSet::from([t_1]));

    // delete_object of "1" is aborted; T1 stays open:
    assert_aborted(store.delete_object("1", None), "delete_object");
    assert_eq!(open_transactions(&store), BTreeSet::from([t_1]));

    // T1 commits both of its writes; "3" is not visible:
    store.commit_transaction(t_1).unwrap();
    assert_eq!(
        read_all_in_new_transaction(&mut store),
        objects(&[("1", Stuff { a: 1, b: 2 }), ("2", Stuff { a: 2, b: 2 })])
    );
}

/// With autocommit, a write of a [`TransactionalKeyValueStore`] to an object an open transaction writes is aborted,
/// see [`check_autocommit_write_to_an_object_an_open_transaction_writes_is_aborted`].
#[test]
fn test_autocommit_write_to_an_object_an_open_transaction_writes_is_aborted() {
    check_autocommit_write_to_an_object_an_open_transaction_writes_is_aborted::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that under serializable, an open transaction of the store `S` that read a == 5 and wrote an object fails
/// validation at its commit if a `put` with autocommit inserted an object with a == 5 (phantom), an `update_object`
/// with the transaction id `None` changed the object it read, or a `delete` with autocommit, or a `delete_object`
/// with the transaction id `None`, removed that object.
///
/// ```text
/// T1                          autocommit
///                             bulkload "1" as (1, 1), "5" as (5, 5), commit
/// begin
/// read a == 5 -> sees "5"
///                             put "7" as (5, 7), commit
///                             (or: update_object "5" to (5, 6), commit)
///                             (or: delete "5", commit)
///                             (or: delete_object "5", commit)
/// write "9"
/// commit -> aborted
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it<S>(
    validation: Validation,
) where
    S: TransactionalStore<Value = Stuff> + Default,
{
    for write in ["put", "update_object", "delete", "delete_object"] {
        let mut store: S = store_with_autocommit();
        store.state_mut().validation = validation;
        store
            .bulkload([("1", Stuff { a: 1, b: 1 }), ("5", Stuff { a: 5, b: 5 })])
            .unwrap();

        // T1 reads a == 5:
        let t_1: u64 = store.begin_transaction();
        assert_eq!(
            store.read_objects(t_1, Some(Rc::new(WhereClause::new("a", "==", 5))), true),
            Ok(vec![("5".to_string(), Stuff { a: 5, b: 5 })]),
            "{write}"
        );

        // a write with autocommit changes the result of that read and commits:
        let mut expected: BTreeMap<String, Stuff> =
            objects(&[("1", Stuff { a: 1, b: 1 }), ("5", Stuff { a: 5, b: 5 })]);
        match write {
            "put" => {
                store.put("7", Stuff { a: 5, b: 7 }).unwrap();
                expected.insert("7".to_string(), Stuff { a: 5, b: 7 });
            }
            "update_object" => {
                store
                    .update_object("5", Stuff { a: 5, b: 6 }, None)
                    .unwrap();
                expected.insert("5".to_string(), Stuff { a: 5, b: 6 });
            }
            "delete" => {
                store.delete("5").unwrap();
                expected.remove("5");
            }
            _ => {
                store.delete_object("5", None).unwrap();
                expected.remove("5");
            }
        }

        // T1 writes "9" and fails validation at its commit:
        store.update_object("9", Stuff { a: 9, b: 9 }, t_1).unwrap();
        assert_aborted(store.commit_transaction(t_1), write);
        assert!(!store.state().td.contains_key(&t_1), "{write}");

        // the write with autocommit stays, the write of T1 is not visible:
        assert_eq!(read_all_in_new_transaction(&mut store), expected, "{write}");
    }
}

/// With validation method 1, a write with autocommit to what an open transaction of a [`TransactionalKeyValueStore`]
/// read makes its validation fail, see
/// [`check_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it`].
#[test]
fn test_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it_with_method_1() {
    check_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::BruteForce);
}

/// With validation method 2, a write with autocommit to what an open transaction of a [`TransactionalKeyValueStore`]
/// read makes its validation fail, see
/// [`check_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it`].
#[test]
fn test_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it_with_method_2() {
    check_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::WriteSets);
}

/// Checks that under serializable, an open transaction of the store `S` that read a == 5 and wrote an object passes
/// validation at its commit if a `put` with autocommit inserted an object with a != 5, an `update_object` with the
/// transaction id `None` changed one with a != 5 to another a != 5, or a `delete` with autocommit, or a
/// `delete_object` with the transaction id `None`, removed one with a != 5 in the meantime.
///
/// ```text
/// T1                          autocommit
///                             bulkload "1" as (1, 1), "5" as (5, 5), commit
/// begin
/// read a == 5 -> sees "5"
///                             put "7" as (2, 7), commit
///                             (or: update_object "1" to (2, 1), commit)
///                             (or: delete "1", commit)
///                             (or: delete_object "1", commit)
/// write "9"
/// commit
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it<S>(
    validation: Validation,
) where
    S: TransactionalStore<Value = Stuff> + Default,
{
    for write in ["put", "update_object", "delete", "delete_object"] {
        let mut store: S = store_with_autocommit();
        store.state_mut().validation = validation;
        store
            .bulkload([("1", Stuff { a: 1, b: 1 }), ("5", Stuff { a: 5, b: 5 })])
            .unwrap();

        // T1 reads a == 5:
        let t_1: u64 = store.begin_transaction();
        assert_eq!(
            store.read_objects(t_1, Some(Rc::new(WhereClause::new("a", "==", 5))), true),
            Ok(vec![("5".to_string(), Stuff { a: 5, b: 5 })]),
            "{write}"
        );

        // a write with autocommit of an object outside that read commits:
        let mut expected: BTreeMap<String, Stuff> =
            objects(&[("1", Stuff { a: 1, b: 1 }), ("5", Stuff { a: 5, b: 5 })]);
        match write {
            "put" => {
                store.put("7", Stuff { a: 2, b: 7 }).unwrap();
                expected.insert("7".to_string(), Stuff { a: 2, b: 7 });
            }
            "update_object" => {
                store
                    .update_object("1", Stuff { a: 2, b: 1 }, None)
                    .unwrap();
                expected.insert("1".to_string(), Stuff { a: 2, b: 1 });
            }
            "delete" => {
                store.delete("1").unwrap();
                expected.remove("1");
            }
            _ => {
                store.delete_object("1", None).unwrap();
                expected.remove("1");
            }
        }

        // T1 writes "9" and commits without an error:
        store.update_object("9", Stuff { a: 9, b: 9 }, t_1).unwrap();
        assert_eq!(store.commit_transaction(t_1), Ok(()), "{write}");
        expected.insert("9".to_string(), Stuff { a: 9, b: 9 });

        // a new transaction sees the writes of both:
        assert_eq!(read_all_in_new_transaction(&mut store), expected, "{write}");
    }
}

/// With validation method 1, a write with autocommit outside what an open transaction of a
/// [`TransactionalKeyValueStore`] read lets it commit, see
/// [`check_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it`].
#[test]
fn test_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it_with_method_1()
 {
    check_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::BruteForce);
}

/// With validation method 2, a write with autocommit outside what an open transaction of a
/// [`TransactionalKeyValueStore`] read lets it commit, see
/// [`check_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it`].
#[test]
fn test_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it_with_method_2()
 {
    check_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::WriteSets);
}

/// Checks that under snapshot isolation, an open transaction of the store `S` still reads the version of an object it
/// began with after a `delete` with autocommit, or an `update_object` or `delete_object` with the transaction id
/// `None`, wrote the object, but its own update of the object is aborted (first updater wins).
///
/// ```text
/// T1                          autocommit
///                             put "1" as (1, 1), commit
/// begin
///                             delete "1", commit
///                             (or: update_object "1" to (3, 3), commit)
///                             (or: delete_object "1", commit)
/// read all -> sees (1, 1)
/// update "1" to (2, 2) -> aborted
/// ```
fn check_autocommit_write_aborts_a_later_update_under_snapshot_isolation<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    for write in ["delete", "update_object", "delete_object"] {
        let mut store: S = store_with_autocommit();
        store.state_mut().isolation_level = IsolationLevel::SnapshotIsolation;
        store.put("1", Stuff { a: 1, b: 1 }).unwrap();

        // T1 begins, then "1" is written with autocommit; T1 still sees (1, 1) in its snapshot:
        let t_1: u64 = store.begin_transaction();
        let expected: BTreeMap<String, Stuff> = match write {
            "delete" => {
                store.delete("1").unwrap();
                BTreeMap::new()
            }
            "update_object" => {
                store
                    .update_object("1", Stuff { a: 3, b: 3 }, None)
                    .unwrap();
                objects(&[("1", Stuff { a: 3, b: 3 })])
            }
            _ => {
                store.delete_object("1", None).unwrap();
                BTreeMap::new()
            }
        };
        assert_eq!(
            store.read_objects(t_1, None, true),
            Ok(vec![("1".to_string(), Stuff { a: 1, b: 1 })]),
            "{write}"
        );

        // the update of "1" by T1 is aborted:
        assert_aborted(store.update_object("1", Stuff { a: 2, b: 2 }, t_1), write);
        assert_eq!(open_transactions(&store), BTreeSet::new(), "{write}");

        // a new transaction sees the write with autocommit, not the update of T1:
        assert_eq!(read_all_in_new_transaction(&mut store), expected, "{write}");
    }
}

/// Under snapshot isolation, a write with autocommit to an object of a [`TransactionalKeyValueStore`] aborts a later
/// update by an open transaction, see [`check_autocommit_write_aborts_a_later_update_under_snapshot_isolation`].
#[test]
fn test_autocommit_write_aborts_a_later_update_under_snapshot_isolation() {
    check_autocommit_write_aborts_a_later_update_under_snapshot_isolation::<
        TransactionalKeyValueStore<Stuff>,
    >();
}
