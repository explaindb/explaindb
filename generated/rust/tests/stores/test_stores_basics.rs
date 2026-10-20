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

use crate::common::{Stuff, create_fake_data, delete_marker, update};
use explaindb::{
    JournalEntry, KvStoreEntry, StoreError, TdEntry, TransactionalKeyValueStore,
    TransactionalStore, Version, VersionEntry, VersionedKeyValueStore, VersionedStore,
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

/// `get` and `delete` of a missing key fail in the versioned and in the transactional store, see
/// [`check_get_and_delete_of_missing_key_fail`].
#[test]
fn get_and_delete_of_missing_key_fail() {
    check_get_and_delete_of_missing_key_fail::<VersionedKeyValueStore<Stuff>>();
    check_get_and_delete_of_missing_key_fail::<TransactionalKeyValueStore<Stuff>>();
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

/// A non-transactional delete in the versioned and in the transactional store keeps the key with a delete marker,
/// see [`check_delete_keeps_key_with_delete_marker`].
#[test]
fn delete_keeps_key_with_delete_marker() {
    check_delete_keeps_key_with_delete_marker::<VersionedKeyValueStore<Stuff>>();
    check_delete_keeps_key_with_delete_marker::<TransactionalKeyValueStore<Stuff>>();
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
/// store keeps its data in memory only.
fn check_flush_changes_nothing<S>()
where
    S: VersionedStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.bulkload(create_fake_data(3)).unwrap();
    store.delete("1").unwrap();
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
    check_flush_changes_nothing::<VersionedKeyValueStore<Stuff>>();
    check_flush_changes_nothing::<TransactionalKeyValueStore<Stuff>>();
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
