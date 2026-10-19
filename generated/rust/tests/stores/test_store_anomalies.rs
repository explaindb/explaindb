// Code generated from system/tests/stores/test_store_anomalies.py. DO NOT EDIT.
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

//! Tests for the isolation of the transactional stores and the anomalies they avoid or allow (Python:
//! `system/tests/stores/test_store_anomalies.py`).

use std::cell::Cell;
use std::rc::Rc;

use crate::common::{Account, CountingWhereClause, Stuff, create_fake_data, update};
use explaindb::{
    Clause, IsolationLevel, JournalEntry, KvStoreEntry, ReadClause, StoreError,
    TransactionalKeyValueStore, TransactionalStore, TrueClause, Validation, Version, VersionEntry,
    VersionedStore, WhereClause,
};

/// Asserts that `result` is the error of an aborted transaction; on failure, the message shows what was returned.
fn assert_aborted<T: std::fmt::Debug>(result: Result<T, StoreError>) {
    assert!(
        matches!(result, Err(StoreError::TransactionAborted(_))),
        "the transaction must be aborted, got {result:?}"
    );
}

/// Returns `result` sorted by object id, so that a check does not depend on the order in which a store returns the
/// objects.
fn sorted<V>(mut result: Vec<(String, V)>) -> Vec<(String, V)> {
    result.sort_by(|left, right| left.0.cmp(&right.0));
    result
}

/// Checks that a transaction of the store `S` that updates the same objects several times holds one
/// work-in-progress version per object and each object once in its write set; its commit adds one committed version
/// per object.
///
/// The store is bulk-loaded with 100 generated objects "0" to "99" (see `create_fake_data`). The transaction updates
/// five of them in three rounds, each time to its committed version with b increased by 4242:
///
/// ```text
/// TA
/// begin
/// update "42", "11", "0", "7", "99"     (round 1)
/// update "42", "11", "0", "7", "99"     (round 2)
/// update "42", "11", "0", "7", "99"     (round 3)
/// commit
/// ```
///
/// After the commit, each object has two committed versions and no work-in-progress version.
///
/// Python also checks that the store holds a copy of the object; in Rust the store owns the object it is given.
fn check_update_multiple_objects_in_ta<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.bulkload(create_fake_data(100)).unwrap();
    let ta_id: u64 = store.begin_transaction();

    // modify each object multiple times: this tests if the write set is correctly updated
    let object_ids_to_test: [&str; 5] = ["42", "11", "0", "7", "99"];

    for i in 0..3 {
        for (idx, object_id) in object_ids_to_test.iter().enumerate() {
            // bypass the store to read an object (reading is tested separately):
            let Version::Update(object) = &store.key_value_store()[*object_id].committed[0].version
            else {
                panic!("object {object_id} was loaded with a value");
            };

            // modify the object, i.e. create a new value:
            let object: Stuff = Stuff {
                a: object.a,
                b: object.b + 4242,
            };

            store
                .update_object(object_id, object.clone(), ta_id)
                .unwrap();
            assert_eq!(store.state().td[&ta_id].read_clauses.len(), 0);
            // now, there must be a wip entry by this transaction:
            assert_eq!(
                store.key_value_store()[*object_id].wip,
                Some(VersionEntry {
                    start_validity: ta_id,
                    version: Version::Update(object),
                })
            );
            let write_set_size: usize = if i > 0 {
                object_ids_to_test.len()
            } else {
                idx + 1
            };
            assert_eq!(store.state().td[&ta_id].write_set.len(), write_set_size);
            assert!(store.state().td[&ta_id].write_set.contains(*object_id));
        }
    }

    // commit the transaction:
    store.commit_transaction(ta_id).unwrap();

    // now we have two committed versions for each object and no wip entry:
    for object_id in object_ids_to_test {
        assert_eq!(store.key_value_store()[object_id].committed.len(), 2);
        assert_eq!(store.key_value_store()[object_id].wip, None);
    }

    // the write set is still there:
    assert_eq!(
        store.state().td[&ta_id].write_set.len(),
        object_ids_to_test.len()
    );
}

/// Several updates of several objects in one transaction work in a [`TransactionalKeyValueStore`], see
/// [`check_update_multiple_objects_in_ta`].
#[test]
fn test_update_multiple_objects_in_ta() {
    check_update_multiple_objects_in_ta::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that a transaction of the store `S` that updated an object keeps reading its own work-in-progress version,
/// even after a newer committed version appears; the test adds that version directly to the store, as if another
/// transaction had committed it.
///
/// ```text
/// TA 1                                another TA (simulated)
/// begin
/// read a == 4243 -> sees "4242" = (4243, 0)
/// update "4242" to (4243, 4243)
///                                     committed version "4242" = (45, 45)
/// read a == 4243 -> sees "4242" = (4243, 4243)
/// ```
fn check_store_snapshot_isolation_ta_self_modification<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.bulkload(create_fake_data(100)).unwrap();

    // an object id that is not in the store yet, with a value of `a` that no other object has:
    let object_id: &str = "4242";
    store.put(object_id, Stuff { a: 4243, b: 0 }).unwrap();

    let ta_id: u64 = store.begin_transaction();
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 4243));
    let result_initial: Vec<(String, Stuff)> = store
        .read_objects(ta_id, Some(Rc::clone(&where_clause)), true)
        .unwrap();
    assert_eq!(
        result_initial,
        [(object_id.to_string(), Stuff { a: 4243, b: 0 })]
    );

    let new_version: Stuff = Stuff { a: 4243, b: 4243 };
    store
        .update_object(object_id, new_version.clone(), ta_id)
        .unwrap();

    // the committed version is untouched and nothing was added to the committed versions:
    assert_eq!(
        store.key_value_store()[object_id].committed,
        [VersionEntry {
            start_validity: 0,
            version: Version::Update(Stuff { a: 4243, b: 0 }),
        }]
    );

    // we have a wip entry now:
    assert_eq!(
        store.key_value_store()[object_id].wip,
        Some(VersionEntry {
            start_validity: ta_id,
            version: Version::Update(new_version.clone()),
        })
    );

    // bypass the store and add a new committed version, as if a concurrent transaction with a greater id than
    // ta_id had committed it:
    store.key_value_store_mut()[object_id]
        .committed
        .push(VersionEntry {
            start_validity: ta_id + 1,
            version: Version::Update(Stuff { a: 45, b: 45 }),
        });
    assert_eq!(store.key_value_store()[object_id].committed.len(), 2);

    // read the same object again: snapshot isolation returns the transaction's own version
    let result_reread: Vec<(String, Stuff)> =
        store.read_objects(ta_id, Some(where_clause), true).unwrap();
    assert_eq!(result_reread, [(object_id.to_string(), new_version)]);
}

/// A transaction of a [`TransactionalKeyValueStore`] reads its own change, see
/// [`check_store_snapshot_isolation_ta_self_modification`].
#[test]
fn test_store_snapshot_isolation_ta_self_modification() {
    check_store_snapshot_isolation_ta_self_modification::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that the store `S` returns the version of an object that is visible at a timestamp: the most recent
/// committed version whose validity started before it. If the committed versions are not ordered by the start of
/// their validity, the read fails with [`StoreError::VersionsNotOrdered`].
///
/// The test writes the committed versions (valid from 0, 5 and 8) directly into the store.
fn check_snapshot_isolation_read_correct_version<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    let object_id: &str = "4242";

    // build a list of committed versions and force it into the store:
    store.key_value_store_mut().insert(
        object_id.to_string(),
        KvStoreEntry {
            committed: vec![
                update(0, Stuff { a: 45, b: 45 }),
                update(5, Stuff { a: 47, b: 45 }),
                update(8, Stuff { a: 49, b: 45 }),
            ],
            wip: None,
        },
    );

    // read different versions of the object:
    assert_eq!(
        store.get_visible_object_version(object_id, 1, false),
        Ok(Some(&Stuff { a: 45, b: 45 }))
    );
    assert_eq!(
        store.get_visible_object_version(object_id, 6, false),
        Ok(Some(&Stuff { a: 47, b: 45 }))
    );
    assert_eq!(
        store.get_visible_object_version(object_id, 9, false),
        Ok(Some(&Stuff { a: 49, b: 45 }))
    );

    // intentionally destroy the commit order of the committed versions:
    store.key_value_store_mut()[object_id]
        .committed
        .push(update(4, Stuff { a: 50, b: 45 }));

    // the read must fail now:
    assert_eq!(
        store.get_visible_object_version(object_id, 6, false),
        Err(StoreError::VersionsNotOrdered(object_id.to_string()))
    );
}

/// A [`TransactionalKeyValueStore`] reads the version visible at a timestamp, see
/// [`check_snapshot_isolation_read_correct_version`].
#[test]
fn test_snapshot_isolation_read_correct_version() {
    check_snapshot_isolation_read_correct_version::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that a transaction of the store `S` keeps seeing its snapshot while another transaction updates and
/// commits the object it read; when the first transaction then writes and tries to commit, validation aborts it. A
/// transaction that begins after that commit sees the new version.
///
/// ```text
/// TA 1                                TA 2                                TA 3
/// begin
///                                     begin
/// read a == 7 -> sees "4242" = (7, 0)
///                                     update "4242" to (7, 8)
/// read a == 7 -> sees "4242" = (7, 0)
///                                     commit
/// read a == 7 -> sees "4242" = (7, 0)
/// update "4242" to (7, 4534)
/// commit -> aborted
///                                                                         begin
///                                                                         read a == 7 -> sees "4242" = (7, 8)
/// ```
fn check_read_write_conflict<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    let object_id: &str = "4242";

    // create a data item in the store:
    store.put(object_id, Stuff { a: 7, b: 0 }).unwrap();

    // start two transactions:
    let ta_id_1: u64 = store.begin_transaction();
    let ta_id_2: u64 = store.begin_transaction();

    // t_1 reads the object from the store:
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 7));
    let result_initial: Vec<(String, Stuff)> = store
        .read_objects(ta_id_1, Some(Rc::clone(&where_clause)), true)
        .unwrap();
    assert_eq!(
        result_initial,
        [(object_id.to_string(), Stuff { a: 7, b: 0 })]
    );

    // t_2 creates a new version of the object and performs an update:
    let new_version: Stuff = Stuff { a: 7, b: 8 };
    store
        .update_object(object_id, new_version.clone(), ta_id_2)
        .unwrap();

    // the committed version is untouched and nothing was added to the committed versions:
    assert_eq!(
        store.key_value_store()[object_id].committed,
        [update(0, Stuff { a: 7, b: 0 })]
    );

    // we have a wip entry of t_2 now:
    assert_eq!(
        store.key_value_store()[object_id].wip,
        Some(update(ta_id_2, new_version.clone()))
    );

    // t_1 must not see the wip version of t_2, it still sees the old object:
    let result_reread: Vec<(String, Stuff)> = store
        .read_objects(ta_id_1, Some(Rc::clone(&where_clause)), true)
        .unwrap();
    assert_eq!(result_reread, result_initial);

    // now, commit t_2:
    store.commit_transaction(ta_id_2).unwrap();

    // the wip entry is gone and we have a new committed version:
    assert_eq!(store.key_value_store()[object_id].wip, None);
    assert_eq!(store.key_value_store()[object_id].committed.len(), 2);

    // t_1 must not see the new value even though t_2 has committed: t_1 runs under snapshot isolation, so its reads
    // are repeatable
    let result_reread: Vec<(String, Stuff)> = store
        .read_objects(ta_id_1, Some(Rc::clone(&where_clause)), true)
        .unwrap();
    assert_eq!(result_reread, result_initial);

    // t_1 updates the object, otherwise it would be a read-only transaction and always pass validation:
    store
        .update_object(object_id, Stuff { a: 7, b: 4534 }, ta_id_1)
        .unwrap();

    // the commit of t_1 fails: t_1 has read an object that t_2 modified and committed after t_1 began
    assert_aborted(store.commit_transaction(ta_id_1));

    // a new transaction t_3 sees the value committed by t_2:
    let ta_id_3: u64 = store.begin_transaction();
    let result_ta_3: Vec<(String, Stuff)> = store
        .read_objects(ta_id_3, Some(where_clause), true)
        .unwrap();
    assert_eq!(result_ta_3, [(object_id.to_string(), new_version)]);
}

/// A [`TransactionalKeyValueStore`] keeps reads repeatable and detects the read-write conflict, see
/// [`check_read_write_conflict`].
#[test]
fn test_read_write_conflict() {
    check_read_write_conflict::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that two transactions of the store `S` that read the same two objects and each update a different one
/// cannot both commit (write skew): the second commit fails validation. Unlike Python, the test also checks that the
/// aborted transaction leaves no version in the store and is removed from the transaction dictionary.
///
/// ```text
/// TA 1                                TA 2
/// begin
///                                     begin
/// read a == 1 -> sees X = (1, 0)
/// read a == 2 -> sees Y = (2, 0)
///                                     read a == 1 -> sees X = (1, 0)
///                                     read a == 2 -> sees Y = (2, 0)
/// update X to (1, 100)
///                                     update Y to (2, 200)
/// commit -> succeeds
///                                     commit -> aborted
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_write_skew_anomaly<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;

    // create two data items X and Y:
    store.put("X", Stuff { a: 1, b: 0 }).unwrap();
    store.put("Y", Stuff { a: 2, b: 0 }).unwrap();

    // start two transactions:
    let ta_id_1: u64 = store.begin_transaction();
    let ta_id_2: u64 = store.begin_transaction();
    assert_ne!(ta_id_1, ta_id_2);

    let where_x: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    let where_y: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 2));

    // t_1 and then t_2 read both objects X and Y from the store:
    for ta_id in [ta_id_1, ta_id_2] {
        let result_x: Vec<(String, Stuff)> = store
            .read_objects(ta_id, Some(Rc::clone(&where_x)), true)
            .unwrap();
        assert_eq!(result_x, [("X".to_string(), Stuff { a: 1, b: 0 })]);
        let result_y: Vec<(String, Stuff)> = store
            .read_objects(ta_id, Some(Rc::clone(&where_y)), true)
            .unwrap();
        assert_eq!(result_y, [("Y".to_string(), Stuff { a: 2, b: 0 })]);
    }

    // t_1 updates object X, t_2 updates object Y:
    store
        .update_object("X", Stuff { a: 1, b: 100 }, ta_id_1)
        .unwrap();
    store
        .update_object("Y", Stuff { a: 2, b: 200 }, ta_id_2)
        .unwrap();

    // now, commit transaction t_1:
    assert_eq!(store.commit_transaction(ta_id_1), Ok(()));

    // the commit of t_2 fails: t_2 has read an object that t_1 has modified and committed meanwhile
    assert_aborted(store.commit_transaction(ta_id_2));
    // t_2 is gone and its update of Y is dropped:
    assert!(!store.state().td.contains_key(&ta_id_2));
    assert_eq!(store.key_value_store()["Y"].wip, None);
    assert_eq!(store.get("Y"), Ok(&Stuff { a: 2, b: 0 }));
    assert_eq!(store.get("X"), Ok(&Stuff { a: 1, b: 100 }));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 avoids the write skew anomaly, see
/// [`check_write_skew_anomaly`].
#[test]
fn test_write_skew_anomaly_with_method_1() {
    check_write_skew_anomaly::<TransactionalKeyValueStore<Stuff>>(Validation::BruteForce);
}

/// A [`TransactionalKeyValueStore`] with validation method 2 avoids the write skew anomaly, see
/// [`check_write_skew_anomaly`].
#[test]
fn test_write_skew_anomaly_with_method_2() {
    check_write_skew_anomaly::<TransactionalKeyValueStore<Stuff>>(Validation::WriteSets);
}

/// Checks that in the store `S` a committed delete hides the object from transactions that begin later, and that a
/// committed transaction can no longer read or write.
///
/// ```text
/// TA 1                                TA 2
/// begin
/// read a == 4243 -> sees "4042" = (4243, 0)
/// delete "4042"
/// commit
/// read a == 4243 -> fails
/// delete "4042" -> fails
/// update "4042" to (4243, 0) -> fails
///                                     begin
///                                     read a == 4243 -> sees nothing
/// ```
///
/// Each call of TA 1 after its commit returns [`StoreError::AlreadyCommitted`] (Python: raises a `RuntimeError`).
fn check_delete_semantics<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();

    // create an object in the store:
    let object_id: &str = "4042";
    store.put(object_id, Stuff { a: 4243, b: 0 }).unwrap();

    // begin a transaction and read the object:
    let ta_id: u64 = store.begin_transaction();
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 4243));
    let result_initial: Vec<(String, Stuff)> = store
        .read_objects(ta_id, Some(Rc::clone(&where_clause)), true)
        .unwrap();
    assert_eq!(
        result_initial,
        [(object_id.to_string(), Stuff { a: 4243, b: 0 })]
    );

    // delete the object:
    store.delete_object(object_id, ta_id).unwrap();

    // the committed version is untouched and nothing was added to the committed versions:
    assert_eq!(
        store.key_value_store()[object_id].committed,
        [update(0, Stuff { a: 4243, b: 0 })]
    );

    // we have a delete marker of this transaction now:
    assert_eq!(
        store.key_value_store()[object_id].wip,
        Some(VersionEntry {
            start_validity: ta_id,
            version: Version::Delete,
        })
    );

    // commit the transaction:
    store.commit_transaction(ta_id).unwrap();

    // now we have two committed versions, the second one a delete marker, and no wip entry:
    assert_eq!(store.key_value_store()[object_id].committed.len(), 2);
    assert_eq!(
        store.key_value_store()[object_id].committed[1].version,
        Version::Delete
    );
    assert_eq!(store.key_value_store()[object_id].wip, None);

    // the committed transaction must not read, delete or update any more:
    assert_eq!(
        store.read_objects(ta_id, Some(Rc::clone(&where_clause)), true),
        Err(StoreError::AlreadyCommitted(ta_id))
    );
    assert_eq!(
        store.delete_object(object_id, ta_id),
        Err(StoreError::AlreadyCommitted(ta_id))
    );
    assert_eq!(
        store.update_object(object_id, Stuff { a: 4243, b: 0 }, ta_id),
        Err(StoreError::AlreadyCommitted(ta_id))
    );

    // a new transaction must not see the object any more:
    let ta_id_2: u64 = store.begin_transaction();
    let result_ta_2: Vec<(String, Stuff)> = store
        .read_objects(ta_id_2, Some(where_clause), true)
        .unwrap();
    assert_eq!(result_ta_2, []);
}

/// A [`TransactionalKeyValueStore`] deletes objects transactionally, see [`check_delete_semantics`].
#[test]
fn test_delete_semantics() {
    check_delete_semantics::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that a transaction of the store `S` that updates an object for which another running transaction holds a
/// work-in-progress version is aborted: there is only one writer per object at a time.
///
/// ```text
/// TA 1                                TA 2
/// begin
///                                     begin
/// update "4242" to (1, 1)
///                                     update "4242" to (1, 2) -> aborted
/// ```
fn check_write_write_conflict<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    let object_id: &str = "4242";
    store.put(object_id, Stuff { a: 1, b: 0 }).unwrap();

    let ta_id_1: u64 = store.begin_transaction();
    let ta_id_2: u64 = store.begin_transaction();

    store
        .update_object(object_id, Stuff { a: 1, b: 1 }, ta_id_1)
        .unwrap();

    // t_2 tries to update the same object: write-write conflict, there can only be one writer at a time
    assert_aborted(store.update_object(object_id, Stuff { a: 1, b: 2 }, ta_id_2));
}

/// A [`TransactionalKeyValueStore`] aborts the second writer of an object, see [`check_write_write_conflict`].
#[test]
fn test_write_write_conflict() {
    check_write_write_conflict::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that the store `S` aborts a transaction that deletes an object on which another transaction holds a
/// work-in-progress version.
///
/// ```text
/// TA 1                                TA 2
/// begin
///                                     begin
/// update or delete "4242"
///                                     delete "4242" -> aborted
/// commit -> succeeds
/// ```
///
/// TA 2 is removed from the transaction dictionary and its journal holds only `Begin` and `Abort`; the
/// work-in-progress version of TA 1 is untouched. Checked for a first writer that updates and one that deletes.
fn check_write_write_conflict_on_delete<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    for first_write_deletes in [false, true] {
        let mut store: S = S::default();
        let object_id: &str = "4242";
        store.put(object_id, Stuff { a: 1, b: 0 }).unwrap();

        let ta_id_1: u64 = store.begin_transaction();
        let ta_id_2: u64 = store.begin_transaction();

        // t_1 becomes the single writer of the object:
        let wip_of_ta_1: Version<Stuff> = if first_write_deletes {
            store.delete_object(object_id, ta_id_1).unwrap();
            Version::Delete
        } else {
            store
                .update_object(object_id, Stuff { a: 1, b: 1 }, ta_id_1)
                .unwrap();
            Version::Update(Stuff { a: 1, b: 1 })
        };

        // t_2 tries to delete the same object: write-write conflict, t_2 must be aborted
        assert_aborted(store.delete_object(object_id, ta_id_2));

        // t_2 is gone from the transaction dictionary:
        assert!(!store.state().td.contains_key(&ta_id_2));

        // the wip entry of t_1 is unchanged:
        assert_eq!(
            store.key_value_store()[object_id].wip,
            Some(VersionEntry {
                start_validity: ta_id_1,
                version: wip_of_ta_1,
            })
        );

        // t_2 wrote nothing to the journal except its Begin and Abort entries:
        assert_eq!(
            store.state().journal.get(&ta_id_2).unwrap(),
            [
                JournalEntry::Begin { ta_id: ta_id_2 },
                JournalEntry::Abort { ta_id: ta_id_2 },
            ]
        );

        // t_1 can still commit:
        store.commit_transaction(ta_id_1).unwrap();
        assert_eq!(
            store.state().committed_transactions_trace.last(),
            Some(&ta_id_1)
        );
    }
}

/// A [`TransactionalKeyValueStore`] aborts a delete of an object that another transaction writes, see
/// [`check_write_write_conflict_on_delete`].
#[test]
fn test_write_write_conflict_on_delete() {
    check_write_write_conflict_on_delete::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that a transaction of the store `S` that updates an object twice and then deletes it always reads its own
/// latest change.
///
/// ```text
/// TA 1
/// begin
/// update "4242" to (1, 1)
/// read a == 1 -> sees "4242" = (1, 1)
/// update "4242" to (1, 2)
/// read a == 1 -> sees "4242" = (1, 2)
/// delete "4242"
/// read a == 1 -> sees nothing
/// ```
///
/// Before TA 1 begins, the store holds "4242" = (1, 0).
fn check_double_update_from_same_transaction<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    let object_id: &str = "4242";
    store.put(object_id, Stuff { a: 1, b: 0 }).unwrap();

    let ta_id_1: u64 = store.begin_transaction();

    // where clause to read the object:
    let where_a: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));

    // first update, then read:
    store
        .update_object(object_id, Stuff { a: 1, b: 1 }, ta_id_1)
        .unwrap();
    let result: Vec<(String, Stuff)> = store
        .read_objects(ta_id_1, Some(Rc::clone(&where_a)), true)
        .unwrap();
    assert_eq!(result, [(object_id.to_string(), Stuff { a: 1, b: 1 })]);

    // second update, then read again:
    store
        .update_object(object_id, Stuff { a: 1, b: 2 }, ta_id_1)
        .unwrap();
    let result: Vec<(String, Stuff)> = store
        .read_objects(ta_id_1, Some(Rc::clone(&where_a)), true)
        .unwrap();
    assert_eq!(result, [(object_id.to_string(), Stuff { a: 1, b: 2 })]);

    // third change, i.e. delete the object, then read again:
    store.delete_object(object_id, ta_id_1).unwrap();
    let result: Vec<(String, Stuff)> = store.read_objects(ta_id_1, Some(where_a), true).unwrap();
    assert_eq!(result, []);
}

/// A transaction of a [`TransactionalKeyValueStore`] reads its latest change, see
/// [`check_double_update_from_same_transaction`].
#[test]
fn test_double_update_from_same_transaction() {
    check_double_update_from_same_transaction::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that, with validation method 1, a transaction of the store `S` commits although its own update made an
/// object it read no longer match the read: the checksum of a read is computed over the committed snapshot, without
/// the transaction's own changes.
///
/// ```text
/// t1
/// begin
/// read a == 1 -> sees "1" = (1, 1)
/// update "1" to (2, 2)
/// read a == 1 -> sees nothing
/// commit -> succeeds
/// ```
///
/// Unlike Python, the test also checks that both reads keep the checksum of the committed version (1, 1).
fn check_checksums_on_self_updates<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = Validation::BruteForce;
    store.put("1", Stuff { a: 1, b: 1 }).unwrap();

    let t_1: u64 = store.begin_transaction();

    // read the object:
    let ret1: Vec<(String, Stuff)> = store
        .read_objects(t_1, Some(Rc::new(WhereClause::new("a", "==", 1))), true)
        .unwrap();
    assert_eq!(ret1, [("1".to_string(), Stuff { a: 1, b: 1 })]);

    // modify the object such that it does not match the read clause anymore:
    store.update_object("1", Stuff { a: 2, b: 2 }, t_1).unwrap();

    // issue the read again (with a new clause object, so both reads are kept):
    let ret2: Vec<(String, Stuff)> = store
        .read_objects(t_1, Some(Rc::new(WhereClause::new("a", "==", 1))), true)
        .unwrap();
    assert_eq!(ret2, []);

    // both reads keep the checksum of the committed snapshot, the SHA-256 digest of the text
    // `[("1", Stuff { a: 1, b: 1 })]` (computed with Python's hashlib; it depends on the `Debug` text of the Rust
    // version pinned in `rust-toolchain.toml`):
    let committed_snapshot_checksum: Option<String> =
        Some("cf730cf46a392bd7bf758753886a295d92ebfb9f297fda89cb54560857a2cd7e".to_string());
    let read_clauses: &Vec<ReadClause<Stuff>> = &store.state().td[&t_1].read_clauses;
    assert_eq!(read_clauses.len(), 2);
    assert_eq!(read_clauses[0].checksum, committed_snapshot_checksum);
    assert_eq!(read_clauses[1].checksum, committed_snapshot_checksum);

    // the commit succeeds, as the checksums cover only the committed snapshot:
    assert_eq!(store.commit_transaction(t_1), Ok(()));
    assert_eq!(
        store.state().committed_transactions_trace.last(),
        Some(&t_1)
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 1 computes checksums without the transaction's own
/// changes, see [`check_checksums_on_self_updates`].
#[test]
fn test_checksums_on_self_updates() {
    check_checksums_on_self_updates::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that a transaction of the store `S` that reads all objects with a [`TrueClause`] and then writes fails
/// validation if another transaction committed a change to one of them meanwhile, and commits if the other
/// transaction did not commit.
///
/// ```text
/// t1                                  t2
/// begin
///                                     begin
///                                     update "1" to (11, 11)
///                                     commit (only if t2 commits)
/// read all -> sees "1" and "2"
/// update "2" to (22, 22)
/// commit -> aborted if t2 committed, else succeeds
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_read_all<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    for t2_commits in [true, false] {
        let mut store: S = S::default();
        store.state_mut().validation = validation;
        store.put("1", Stuff { a: 1, b: 1 }).unwrap();
        store.put("2", Stuff { a: 2, b: 2 }).unwrap();

        let t1: u64 = store.begin_transaction();
        let t2: u64 = store.begin_transaction();

        // t2 modifies something after t1 started ...
        store
            .update_object("1", Stuff { a: 11, b: 11 }, t2)
            .unwrap();

        // ... and commits:
        if t2_commits {
            store.commit_transaction(t2).unwrap();
        }

        // t1 reads everything from its snapshot with a TrueClause:
        let ret1: Vec<(String, Stuff)> = store
            .read_objects(t1, Some(Rc::new(TrueClause)), true)
            .unwrap();
        assert_eq!(
            sorted(ret1),
            [
                ("1".to_string(), Stuff { a: 1, b: 1 }),
                ("2".to_string(), Stuff { a: 2, b: 2 }),
            ]
        );

        // t1 modifies something (possibly influenced by the previous read):
        store
            .update_object("2", Stuff { a: 22, b: 22 }, t1)
            .unwrap();

        // t1 commits and fails validation if t2 committed:
        if t2_commits {
            assert_aborted(store.commit_transaction(t1));
        } else {
            assert_eq!(store.commit_transaction(t1), Ok(()));
        }
    }
}

/// A read of all objects in a [`TransactionalKeyValueStore`] with validation method 1 is validated, see
/// [`check_read_all`].
#[test]
fn test_read_all_with_method_1() {
    check_read_all::<TransactionalKeyValueStore<Stuff>>(Validation::BruteForce);
}

/// A read of all objects in a [`TransactionalKeyValueStore`] with validation method 2 is validated, see
/// [`check_read_all`].
#[test]
fn test_read_all_with_method_2() {
    check_read_all::<TransactionalKeyValueStore<Stuff>>(Validation::WriteSets);
}

/// Checks that a reader of the store `S` does not see an object that another transaction inserted and committed
/// after the reader began.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
///                                     insert C
///                                     commit
/// read all -> sees only A
/// ```
fn check_read_skips_object_inserted_and_committed_after_snapshot<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_j inserts a brand-new object and commits:
    store
        .update_object("C", Stuff { a: 42, b: 0 }, t_j)
        .unwrap();
    store.commit_transaction(t_j).unwrap();

    // C did not exist in the snapshot of t_i:
    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(TrueClause)), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Stuff { a: 1, b: 0 })]);
}

/// A reader of a [`TransactionalKeyValueStore`] does not see a later committed insert, see
/// [`check_read_skips_object_inserted_and_committed_after_snapshot`].
#[test]
fn test_read_skips_object_inserted_and_committed_after_snapshot() {
    check_read_skips_object_inserted_and_committed_after_snapshot::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that a reader of the store `S` does not see an object that another, still running transaction has
/// inserted.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
///                                     insert C
/// read all -> sees only A
/// ```
fn check_read_skips_object_inserted_by_uncommitted_concurrent_ta<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_j inserts a brand-new object, but does not commit:
    store
        .update_object("C", Stuff { a: 42, b: 0 }, t_j)
        .unwrap();

    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(TrueClause)), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Stuff { a: 1, b: 0 })]);
}

/// A reader of a [`TransactionalKeyValueStore`] does not see an uncommitted insert, see
/// [`check_read_skips_object_inserted_by_uncommitted_concurrent_ta`].
#[test]
fn test_read_skips_object_inserted_by_uncommitted_concurrent_ta() {
    check_read_skips_object_inserted_by_uncommitted_concurrent_ta::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that a transaction of the store `S` sees the object it inserted itself, next to the pre-existing objects.
///
/// ```text
/// t
/// begin
/// insert C = (2, 0)
/// read all -> sees A = (1, 0) and C = (2, 0)
/// ```
fn check_read_own_insert<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();

    let t: u64 = store.begin_transaction();
    store.update_object("C", Stuff { a: 2, b: 0 }, t).unwrap();

    let result: Vec<(String, Stuff)> = store
        .read_objects(t, Some(Rc::new(TrueClause)), true)
        .unwrap();
    assert_eq!(
        sorted(result),
        [
            ("A".to_string(), Stuff { a: 1, b: 0 }),
            ("C".to_string(), Stuff { a: 2, b: 0 }),
        ]
    );
}

/// A transaction of a [`TransactionalKeyValueStore`] sees its own insert, see [`check_read_own_insert`].
#[test]
fn test_read_own_insert() {
    check_read_own_insert::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that an aborted insert in the store `S` leaves no visible object behind, and that the key can be inserted
/// again later.
///
/// ```text
/// t                       t2                      t3                      t4
/// begin
/// insert C = (2, 0)
/// abort
///                         begin
///                         read all -> sees only A = (1, 0)
///                                                 begin
///                                                 insert C = (3, 0)
///                                                 commit
///                                                                         begin
///                                                                         read all -> sees A = (1, 0) and C = (3, 0)
/// ```
fn check_aborted_insert_is_invisible_and_key_can_be_reinserted<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();

    // insert C and abort:
    let t: u64 = store.begin_transaction();
    store.update_object("C", Stuff { a: 2, b: 0 }, t).unwrap();
    store.abort_transaction(t);

    // the aborted insert must not be visible:
    let t2: u64 = store.begin_transaction();
    let result_t2: Vec<(String, Stuff)> = store
        .read_objects(t2, Some(Rc::new(TrueClause)), true)
        .unwrap();
    assert_eq!(result_t2, [("A".to_string(), Stuff { a: 1, b: 0 })]);

    // insert C again and commit:
    let t3: u64 = store.begin_transaction();
    store.update_object("C", Stuff { a: 3, b: 0 }, t3).unwrap();
    store.commit_transaction(t3).unwrap();

    // a later transaction sees the value inserted again:
    let t4: u64 = store.begin_transaction();
    let result_t4: Vec<(String, Stuff)> = store
        .read_objects(t4, Some(Rc::new(TrueClause)), true)
        .unwrap();
    assert_eq!(
        sorted(result_t4),
        [
            ("A".to_string(), Stuff { a: 1, b: 0 }),
            ("C".to_string(), Stuff { a: 3, b: 0 }),
        ]
    );
}

/// An aborted insert in a [`TransactionalKeyValueStore`] is invisible and can be repeated, see
/// [`check_aborted_insert_is_invisible_and_key_can_be_reinserted`].
#[test]
fn test_aborted_insert_is_invisible_and_key_can_be_reinserted() {
    check_aborted_insert_is_invisible_and_key_can_be_reinserted::<TransactionalKeyValueStore<Stuff>>(
    );
}

/// Checks that the store `S` returns no version (`None`) of an object that does not exist in the snapshot of the
/// reader: an object whose only committed version became valid at or after the reader's timestamp, and an object
/// without any committed version.
fn check_get_visible_object_version_returns_none_if_object_not_in_snapshot<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();

    // (a) the only committed version became valid at timestamp 5:
    store.key_value_store_mut().insert(
        "late".to_string(),
        KvStoreEntry {
            committed: vec![update(5, Stuff { a: 1, b: 0 })],
            wip: None,
        },
    );
    // an older reader and a reader with the same timestamp (boundary) must not see it:
    assert_eq!(store.get_visible_object_version("late", 3, false), Ok(None));
    assert_eq!(store.get_visible_object_version("late", 5, false), Ok(None));

    // (b) no committed version at all:
    store.key_value_store_mut().insert(
        "empty".to_string(),
        KvStoreEntry {
            committed: Vec::new(),
            wip: None,
        },
    );
    assert_eq!(
        store.get_visible_object_version("empty", 3, false),
        Ok(None)
    );
}

/// A [`TransactionalKeyValueStore`] returns no version of an object outside the snapshot, see
/// [`check_get_visible_object_version_returns_none_if_object_not_in_snapshot`].
#[test]
fn test_get_visible_object_version_returns_none_if_object_not_in_snapshot() {
    check_get_visible_object_version_returns_none_if_object_not_in_snapshot::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that a transaction of the store `S` that read an object and then overwrites it is aborted at its commit
/// if another transaction committed a change of the object meanwhile (lost update).
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read a == 42 -> sees A = (42, 0)
///                                     update A to (7, 0)
///                                     commit
/// update A to (5, 0)
/// commit -> aborted
/// ```
///
/// Validation compares against the version t_i read, (42, 0), not against the work-in-progress version of t_i.
/// Python runs this test with both validation methods; it runs here once per method.
fn check_validation_detects_lost_update_on_read_object<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: 42, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads A:
    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 42))), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Stuff { a: 42, b: 0 })]);

    // t_j changes A and commits:
    store.update_object("A", Stuff { a: 7, b: 0 }, t_j).unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i overwrites A based on its outdated read (allowed: there is no wip entry on A any more):
    store.update_object("A", Stuff { a: 5, b: 0 }, t_i).unwrap();

    assert_aborted(store.commit_transaction(t_i));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 detects a lost update, see
/// [`check_validation_detects_lost_update_on_read_object`].
#[test]
fn test_validation_detects_lost_update_on_read_object_with_method_1() {
    check_validation_detects_lost_update_on_read_object::<TransactionalKeyValueStore<Stuff>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 detects a lost update, see
/// [`check_validation_detects_lost_update_on_read_object`].
#[test]
fn test_validation_detects_lost_update_on_read_object_with_method_2() {
    check_validation_detects_lost_update_on_read_object::<TransactionalKeyValueStore<Stuff>>(
        Validation::WriteSets,
    );
}

/// Checks that a transaction of the store `S` is aborted at its commit if another transaction committed an insert
/// that matches one of its earlier reads (phantom): C did not exist in the snapshot of t_i, but matches now.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read a == 42 -> sees nothing
///                                     insert C = (42, 0)
///                                     commit
/// update A
/// commit -> aborted
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_validation_detects_phantom_insert<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads and finds nothing:
    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 42))), true)
        .unwrap();
    assert_eq!(result, []);

    // t_j inserts a matching object and commits (a phantom for t_i):
    store
        .update_object("C", Stuff { a: 42, b: 0 }, t_j)
        .unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i writes something, so it is not read-only and must be validated:
    store.update_object("A", Stuff { a: 2, b: 0 }, t_i).unwrap();

    assert_aborted(store.commit_transaction(t_i));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 detects a phantom insert, see
/// [`check_validation_detects_phantom_insert`].
#[test]
fn test_validation_detects_phantom_insert_with_method_1() {
    check_validation_detects_phantom_insert::<TransactionalKeyValueStore<Stuff>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 detects a phantom insert, see
/// [`check_validation_detects_phantom_insert`].
#[test]
fn test_validation_detects_phantom_insert_with_method_2() {
    check_validation_detects_phantom_insert::<TransactionalKeyValueStore<Stuff>>(
        Validation::WriteSets,
    );
}

/// Checks that a transaction of the store `S` is aborted at its commit if another transaction committed the delete
/// of an object it had read: A matched in the snapshot of t_i.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read a == 42 -> sees A
///                                     delete A
///                                     commit
/// update B
/// commit -> aborted
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_validation_detects_concurrent_delete_of_read_object<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: 42, b: 0 }).unwrap();
    store.put("B", Stuff { a: 0, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads A:
    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 42))), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Stuff { a: 42, b: 0 })]);

    // t_j deletes A and commits:
    store.delete_object("A", t_j).unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i writes a different object, possibly based on what it read about A:
    store.update_object("B", Stuff { a: 1, b: 0 }, t_i).unwrap();

    assert_aborted(store.commit_transaction(t_i));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 detects the concurrent delete of a read object, see
/// [`check_validation_detects_concurrent_delete_of_read_object`].
#[test]
fn test_validation_detects_concurrent_delete_of_read_object_with_method_1() {
    check_validation_detects_concurrent_delete_of_read_object::<TransactionalKeyValueStore<Stuff>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 detects the concurrent delete of a read object, see
/// [`check_validation_detects_concurrent_delete_of_read_object`].
#[test]
fn test_validation_detects_concurrent_delete_of_read_object_with_method_2() {
    check_validation_detects_concurrent_delete_of_read_object::<TransactionalKeyValueStore<Stuff>>(
        Validation::WriteSets,
    );
}

/// Checks that a transaction of the store `S` that read all objects without a where clause is aborted at its
/// commit if another transaction committed a change of any of them: a read without a where clause selects every
/// existing object.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read all -> sees A and B
///                                     update A
///                                     commit
/// update B
/// commit -> aborted
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_validation_detects_change_after_read_without_predicate<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    store.put("B", Stuff { a: 1, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads everything, i.e. without a where clause:
    let result: Vec<(String, Stuff)> = store.read_objects(t_i, None, true).unwrap();
    assert_eq!(
        sorted(result),
        [
            ("A".to_string(), Stuff { a: 1, b: 0 }),
            ("B".to_string(), Stuff { a: 1, b: 0 }),
        ]
    );

    // t_j changes A and commits:
    store.update_object("A", Stuff { a: 9, b: 0 }, t_j).unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i writes B, possibly based on what it read about A:
    store.update_object("B", Stuff { a: 5, b: 0 }, t_i).unwrap();

    assert_aborted(store.commit_transaction(t_i));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 validates a read without a where clause, see
/// [`check_validation_detects_change_after_read_without_predicate`].
#[test]
fn test_validation_detects_change_after_read_without_predicate_with_method_1() {
    check_validation_detects_change_after_read_without_predicate::<TransactionalKeyValueStore<Stuff>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 validates a read without a where clause, see
/// [`check_validation_detects_change_after_read_without_predicate`].
#[test]
fn test_validation_detects_change_after_read_without_predicate_with_method_2() {
    check_validation_detects_change_after_read_without_predicate::<TransactionalKeyValueStore<Stuff>>(
        Validation::WriteSets,
    );
}

/// Checks that a transaction of the store `S` commits if the only concurrent change touched an object that never
/// matched its reads: X matches `a == 42` neither before nor after the change of t_j.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read a == 42 -> sees A
///                                     update X from (1, 0) to (2, 0)
///                                     commit
/// update A
/// commit -> succeeds
/// ```
///
/// Python runs this test with both validation methods; it runs here once per method.
fn check_validation_ignores_concurrent_write_outside_read_predicate<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: 42, b: 0 }).unwrap();
    store.put("X", Stuff { a: 1, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads A:
    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 42))), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Stuff { a: 42, b: 0 })]);

    // t_j changes X, which never matches the read of t_i, and commits:
    store.update_object("X", Stuff { a: 2, b: 0 }, t_j).unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i updates A and must commit:
    store
        .update_object("A", Stuff { a: 43, b: 0 }, t_i)
        .unwrap();
    assert_eq!(store.commit_transaction(t_i), Ok(()));
    assert_eq!(
        store.state().committed_transactions_trace.last(),
        Some(&t_i)
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 1 ignores a concurrent write outside the reads, see
/// [`check_validation_ignores_concurrent_write_outside_read_predicate`].
#[test]
fn test_validation_ignores_concurrent_write_outside_read_predicate_with_method_1() {
    check_validation_ignores_concurrent_write_outside_read_predicate::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::BruteForce);
}

/// A [`TransactionalKeyValueStore`] with validation method 2 ignores a concurrent write outside the reads, see
/// [`check_validation_ignores_concurrent_write_outside_read_predicate`].
#[test]
fn test_validation_ignores_concurrent_write_outside_read_predicate_with_method_2() {
    check_validation_ignores_concurrent_write_outside_read_predicate::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::WriteSets);
}

/// Checks that a read-only transaction of the store `S` always commits, even if another transaction committed a
/// change of an object it read.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read a == 42 -> sees A = (42, 0)
///                                     update A to (7, 0)
///                                     commit
/// read a == 42 -> still sees A = (42, 0)
/// commit -> succeeds
/// ```
///
/// t_i writes nothing, so it is validated against its own snapshot, in which nothing changed. The same schedule
/// with a write of t_i aborts, see [`check_validation_detects_lost_update_on_read_object`]. Python runs this test
/// with both validation methods; it runs here once per method.
fn check_read_only_transaction_commits_despite_concurrent_change_of_read_object<S>(
    validation: Validation,
) where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: 42, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads A:
    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 42))), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Stuff { a: 42, b: 0 })]);

    // t_j changes A, so that it no longer matches the read of t_i, and commits:
    store.update_object("A", Stuff { a: 7, b: 0 }, t_j).unwrap();
    store.commit_transaction(t_j).unwrap();

    // snapshot isolation: t_i still sees the old version of A:
    let result_reread: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 42))), true)
        .unwrap();
    assert_eq!(result_reread, result);

    // t_i wrote nothing, so it must commit:
    assert_eq!(store.commit_transaction(t_i), Ok(()));
    assert_eq!(
        store.state().committed_transactions_trace.last(),
        Some(&t_i)
    );
}

/// A read-only transaction of a [`TransactionalKeyValueStore`] with validation method 1 commits despite a concurrent
/// change of an object it read, see [`check_read_only_transaction_commits_despite_concurrent_change_of_read_object`].
#[test]
fn test_read_only_transaction_commits_despite_concurrent_change_of_read_object_with_method_1() {
    check_read_only_transaction_commits_despite_concurrent_change_of_read_object::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::BruteForce);
}

/// A read-only transaction of a [`TransactionalKeyValueStore`] with validation method 2 commits despite a concurrent
/// change of an object it read, see [`check_read_only_transaction_commits_despite_concurrent_change_of_read_object`].
#[test]
fn test_read_only_transaction_commits_despite_concurrent_change_of_read_object_with_method_2() {
    check_read_only_transaction_commits_despite_concurrent_change_of_read_object::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::WriteSets);
}

/// Checks that a transaction of the store `S` is aborted at its commit if a concurrent transaction changed an
/// object it read: of two transactions that each read one object and write the other, the second to commit is
/// aborted, as the changed object A is detected.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read a < 0 -> sees A = (-1, 0)
///                                     read a >= 0 -> sees B = (0, 0)
///                                     update A to (-2, 0)
///                                     commit
/// update B to (1, 0)
/// commit -> aborted
/// ```
///
/// Python runs this test with both store classes and both validation methods; it runs here once per method, and the
/// indexed store follows in step 2 of the port.
fn check_validation_detects_write_skew_on_objects_with_equal_hash<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: -1, b: 0 }).unwrap();
    store.put("B", Stuff { a: 0, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads A:
    let result_i: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "<", 0))), true)
        .unwrap();
    assert_eq!(result_i, [("A".to_string(), Stuff { a: -1, b: 0 })]);

    // t_j reads B:
    let result_j: Vec<(String, Stuff)> = store
        .read_objects(t_j, Some(Rc::new(WhereClause::new("a", ">=", 0))), true)
        .unwrap();
    assert_eq!(result_j, [("B".to_string(), Stuff { a: 0, b: 0 })]);

    // t_j changes A and commits:
    store
        .update_object("A", Stuff { a: -2, b: 0 }, t_j)
        .unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i writes B, possibly based on what it read about A:
    store.update_object("B", Stuff { a: 1, b: 0 }, t_i).unwrap();

    assert_aborted(store.commit_transaction(t_i));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 detects this write skew, see
/// [`check_validation_detects_write_skew_on_objects_with_equal_hash`]. The name comes from Python, where both
/// versions of A, (-1, 0) and (-2, 0), have the same CPython `hash()`. Rust's validation does not use the value's
/// `Hash`: method 1 hashes the `Debug` text of the read result with SHA-256, which differs for the two versions.
#[test]
fn test_validation_detects_write_skew_on_objects_with_equal_hash_with_method_1() {
    check_validation_detects_write_skew_on_objects_with_equal_hash::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::BruteForce);
}

/// A [`TransactionalKeyValueStore`] with validation method 2 detects this write skew, see
/// [`check_validation_detects_write_skew_on_objects_with_equal_hash`]. The name comes from Python, where both
/// versions of A, (-1, 0) and (-2, 0), have the same CPython `hash()`. Rust's validation does not use the value's
/// `Hash`: method 2 compares the two versions with `==`.
#[test]
fn test_validation_detects_write_skew_on_objects_with_equal_hash_with_method_2() {
    check_validation_detects_write_skew_on_objects_with_equal_hash::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::WriteSets);
}

/// Checks that a transaction of the store `S` is aborted at its commit if a concurrent transaction swapped the
/// values of two objects it read: the read returns the same values before and after t_j, but assigned to other
/// objects.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read all -> sees x = (1, 0), z = (0, 0)
///                                     update x to (0, 0)
///                                     update z to (1, 0)
///                                     commit
/// update x to (1, 1)
/// commit -> aborted
/// ```
///
/// Python runs this test with both store classes and both validation methods; it runs here once per method, and the
/// indexed store follows in step 2 of the port.
fn check_validation_detects_swapped_values_of_read_objects<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("x", Stuff { a: 1, b: 0 }).unwrap();
    store.put("z", Stuff { a: 0, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads everything, i.e. without a where clause:
    let result: Vec<(String, Stuff)> = store.read_objects(t_i, None, true).unwrap();
    assert_eq!(
        sorted(result),
        [
            ("x".to_string(), Stuff { a: 1, b: 0 }),
            ("z".to_string(), Stuff { a: 0, b: 0 }),
        ]
    );

    // t_j swaps the values of x and z and commits:
    store.update_object("x", Stuff { a: 0, b: 0 }, t_j).unwrap();
    store.update_object("z", Stuff { a: 1, b: 0 }, t_j).unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i writes x, possibly based on what it read:
    store.update_object("x", Stuff { a: 1, b: 1 }, t_i).unwrap();

    assert_aborted(store.commit_transaction(t_i));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 detects swapped values, see
/// [`check_validation_detects_swapped_values_of_read_objects`].
#[test]
fn test_validation_detects_swapped_values_of_read_objects_with_method_1() {
    check_validation_detects_swapped_values_of_read_objects::<TransactionalKeyValueStore<Stuff>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 detects swapped values, see
/// [`check_validation_detects_swapped_values_of_read_objects`].
#[test]
fn test_validation_detects_swapped_values_of_read_objects_with_method_2() {
    check_validation_detects_swapped_values_of_read_objects::<TransactionalKeyValueStore<Stuff>>(
        Validation::WriteSets,
    );
}

/// Checks that a transaction of the store `S` can read, update and commit objects of a type without `Hash`
/// ([`Account`]): the store never needs `Hash` of its values.
///
/// ```text
/// t_i
/// begin
/// read a == 1 -> sees A = (1, 0)
/// update A to (1, 1)
/// commit -> succeeds
/// ```
///
/// Python runs this test with both store classes and both validation methods; it runs here once per method, and the
/// indexed store follows in step 2 of the port.
fn check_validation_accepts_unhashable_objects<S>(validation: Validation)
where
    S: TransactionalStore<Value = Account> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Account { a: 1, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();

    // t_i reads A:
    let result: Vec<(String, Account)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 1))), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Account { a: 1, b: 0 })]);

    // t_i updates A and must commit:
    store
        .update_object("A", Account { a: 1, b: 1 }, t_i)
        .unwrap();
    assert_eq!(store.commit_transaction(t_i), Ok(()));
    assert_eq!(
        store.state().committed_transactions_trace.last(),
        Some(&t_i)
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 1 works with values without `Hash`, see
/// [`check_validation_accepts_unhashable_objects`].
#[test]
fn test_validation_accepts_unhashable_objects_with_method_1() {
    check_validation_accepts_unhashable_objects::<TransactionalKeyValueStore<Account>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 works with values without `Hash`, see
/// [`check_validation_accepts_unhashable_objects`].
#[test]
fn test_validation_accepts_unhashable_objects_with_method_2() {
    check_validation_accepts_unhashable_objects::<TransactionalKeyValueStore<Account>>(
        Validation::WriteSets,
    );
}

/// Checks that a transaction of the store `S` is aborted at its commit if a concurrent transaction committed a
/// change of an object it read, also for objects of a type without `Hash` ([`Account`]): the store never needs
/// `Hash` of its values.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read a == 1 -> sees A = (1, 0)
///                                     update A to (1, 1)
///                                     commit
/// update B to (2, 1)
/// commit -> aborted
/// ```
///
/// Python runs this test with both store classes and both validation methods; it runs here once per method, and the
/// indexed store follows in step 2 of the port.
fn check_validation_detects_conflict_on_unhashable_objects<S>(validation: Validation)
where
    S: TransactionalStore<Value = Account> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Account { a: 1, b: 0 }).unwrap();
    store.put("B", Account { a: 2, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // t_i reads A:
    let result: Vec<(String, Account)> = store
        .read_objects(t_i, Some(Rc::new(WhereClause::new("a", "==", 1))), true)
        .unwrap();
    assert_eq!(result, [("A".to_string(), Account { a: 1, b: 0 })]);

    // t_j changes A and commits:
    store
        .update_object("A", Account { a: 1, b: 1 }, t_j)
        .unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i writes B, possibly based on what it read about A:
    store
        .update_object("B", Account { a: 2, b: 1 }, t_i)
        .unwrap();

    assert_aborted(store.commit_transaction(t_i));
}

/// A [`TransactionalKeyValueStore`] with validation method 1 detects a conflict on values without `Hash`, see
/// [`check_validation_detects_conflict_on_unhashable_objects`].
#[test]
fn test_validation_detects_conflict_on_unhashable_objects_with_method_1() {
    check_validation_detects_conflict_on_unhashable_objects::<TransactionalKeyValueStore<Account>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 detects a conflict on values without `Hash`, see
/// [`check_validation_detects_conflict_on_unhashable_objects`].
#[test]
fn test_validation_detects_conflict_on_unhashable_objects_with_method_2() {
    check_validation_detects_conflict_on_unhashable_objects::<TransactionalKeyValueStore<Account>>(
        Validation::WriteSets,
    );
}

/// Checks that `read_objects` of the store `S` evaluates the where clause once per object with validation method
/// 2, and twice per object with method 1, which evaluates it a second time on the committed snapshot to compute the
/// checksum. The result contains the transaction's own change. The read is kept in the transaction's reads with the
/// same clause object; with method 1, it carries the checksum of the committed snapshot, i.e. of the version of A
/// before the change of t_i; with method 2, it carries no checksum.
///
/// ```text
/// t_i
/// begin
/// update A to (42, 1)
/// read a == 42 -> sees A = (42, 1)
/// ```
///
/// Before t_i begins, the store holds A = (42, 0) and B = (7, 0). Python runs this test with both store classes and
/// both validation methods; it runs here once per method, and the indexed store follows in step 2 of the port.
fn check_read_objects_evaluates_where_clause_twice_only_for_method_1<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = validation;
    store.put("A", Stuff { a: 42, b: 0 }).unwrap();
    // B does not match the where clause, it is evaluated nevertheless:
    store.put("B", Stuff { a: 7, b: 0 }).unwrap();

    let t_i: u64 = store.begin_transaction();
    // t_i changes A such that it still matches the where clause:
    store
        .update_object("A", Stuff { a: 42, b: 1 }, t_i)
        .unwrap();

    let counting: Rc<CountingWhereClause> = Rc::new(CountingWhereClause {
        clause: WhereClause::new("a", "==", 42),
        evaluations: Cell::new(0),
    });
    let where_clause: Rc<dyn Clause<Stuff>> = counting.clone();
    let result: Vec<(String, Stuff)> = store
        .read_objects(t_i, Some(Rc::clone(&where_clause)), true)
        .unwrap();

    // check the counter before any commit, as the validation in commit evaluates the clause again: two objects,
    // evaluated twice (method 1) or once (method 2) each
    let expected_evaluations: usize = match validation {
        Validation::BruteForce => 4,
        Validation::WriteSets => 2,
    };
    assert_eq!(counting.evaluations.get(), expected_evaluations);
    assert_eq!(result, [("A".to_string(), Stuff { a: 42, b: 1 })]);

    // method 1 keeps the checksum of the committed version of A: the SHA-256 digest, as lowercase hex, of the
    // `Debug` text of the result, i.e. of the text
    //     [("A", Stuff { a: 42, b: 0 })]
    // method 2 keeps no checksum:
    let expected_checksum: Option<String> = match validation {
        Validation::BruteForce => {
            Some("e53128abb9f72cfb7eb6f18d8bc50cdded266d1eafe28f1941b1f2172195b7a6".to_string())
        }
        Validation::WriteSets => None,
    };

    // the read is kept with the same clause object and the expected checksum:
    let read_clauses: &Vec<ReadClause<Stuff>> = &store.state().td[&t_i].read_clauses;
    assert_eq!(read_clauses.len(), 1);
    let kept_clause: &Rc<dyn Clause<Stuff>> = read_clauses[0]
        .where_clause
        .as_ref()
        .expect("the read has a where clause");
    assert!(Rc::ptr_eq(kept_clause, &where_clause));
    assert_eq!(read_clauses[0].checksum, expected_checksum);
}

/// `read_objects` of a [`TransactionalKeyValueStore`] with validation method 1 evaluates the where clause twice per
/// object and keeps a checksum, see [`check_read_objects_evaluates_where_clause_twice_only_for_method_1`].
#[test]
fn test_read_objects_evaluates_where_clause_twice_only_for_method_1_with_method_1() {
    check_read_objects_evaluates_where_clause_twice_only_for_method_1::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::BruteForce);
}

/// `read_objects` of a [`TransactionalKeyValueStore`] with validation method 2 evaluates the where clause once per
/// object and keeps no checksum, see [`check_read_objects_evaluates_where_clause_twice_only_for_method_1`].
#[test]
fn test_read_objects_evaluates_where_clause_twice_only_for_method_1_with_method_2() {
    check_read_objects_evaluates_where_clause_twice_only_for_method_1::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::WriteSets);
}

/// How a transaction writes an object in the isolation level tests, see [`write`] (Python: the type `WriteKind`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum WriteKind {
    /// Inserts a new object with `update_object`.
    Insert,
    /// Updates an existing object with `update_object`.
    Update,
    /// Deletes an existing object with `delete_object`.
    Delete,
}

/// Returns the value Stuff(1, `ta_id`) that [`write`] writes for transaction `ta_id`.
fn value_of(ta_id: u64) -> Stuff {
    Stuff {
        a: 1,
        b: i64::try_from(ta_id).expect("transaction ids of the tests are small"),
    }
}

/// Lets transaction `ta_id` write object `object_id` in `store` and returns the result of the write (Python:
/// `_write`).
///
/// [`WriteKind::Insert`] and [`WriteKind::Update`] call `update_object` with the value Stuff(1, `ta_id`), see
/// [`value_of`], which differs from the value Stuff(1, 0) the tests put into the store and from the value of every
/// other transaction; [`WriteKind::Delete`] calls `delete_object`.
fn write<S>(kind: WriteKind, store: &mut S, object_id: &str, ta_id: u64) -> Result<(), StoreError>
where
    S: TransactionalStore<Value = Stuff>,
{
    match kind {
        WriteKind::Delete => store.delete_object(object_id, ta_id),
        WriteKind::Insert | WriteKind::Update => {
            store.update_object(object_id, value_of(ta_id), ta_id)
        }
    }
}

/// Under snapshot isolation, a transaction that writes an object another transaction changed and committed after
/// the writer began is aborted at once, even if it never read the object.
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
///                                     update, delete or insert x
///                                     commit
/// update, delete or insert x -> aborted
/// ```
///
/// t_i is removed from the transaction dictionary, its journal holds only `Begin` and `Abort`, and x has no
/// work-in-progress version. Checked for every combination of t_j updating or deleting x and t_i updating or
/// deleting x, and for t_j and t_i inserting the same new key. Python also runs the update and delete combinations
/// on the indexed store, to check that it forwards the isolation level; that variant follows with the indexed store
/// in step 2 of the port.
#[test]
fn test_snapshot_isolation_level_aborts_write_to_object_committed_after_begin() {
    let write_kinds: [WriteKind; 2] = [WriteKind::Update, WriteKind::Delete];
    let mut variants: Vec<(WriteKind, WriteKind)> = Vec::new();
    for write_j in write_kinds {
        for write_i in write_kinds {
            variants.push((write_j, write_i));
        }
    }
    variants.push((WriteKind::Insert, WriteKind::Insert));

    for (write_j, write_i) in variants {
        let case: String = format!("write_j = {write_j:?}, write_i = {write_i:?}");
        let mut store: TransactionalKeyValueStore<Stuff> =
            TransactionalKeyValueStore::with_isolation_level(
                Validation::WriteSets,
                IsolationLevel::SnapshotIsolation,
            )
            .unwrap();
        let object_id: &str = "x";
        if write_j != WriteKind::Insert {
            store.put(object_id, Stuff { a: 1, b: 0 }).unwrap();
        }

        let t_i: u64 = store.begin_transaction();
        let t_j: u64 = store.begin_transaction();

        // t_j writes x and commits after t_i began:
        write(write_j, &mut store, object_id, t_j).unwrap();
        store.commit_transaction(t_j).unwrap();

        // t_i writes x: aborted at the write by the snapshot isolation rule, not only at its commit:
        let result: Result<(), StoreError> = write(write_i, &mut store, object_id, t_i);
        assert!(
            matches!(
                &result,
                Err(StoreError::TransactionAborted(message))
                    if message.contains("aborted under snapshot isolation")
            ),
            "{case}: t_i must be aborted under snapshot isolation, got {result:?}"
        );

        // t_i is gone from the transaction dictionary:
        assert!(!store.state().td.contains_key(&t_i), "{case}");

        // t_i wrote nothing to the journal except its Begin and Abort entries:
        assert_eq!(
            store.state().journal.get(&t_i).unwrap(),
            [
                JournalEntry::Begin { ta_id: t_i },
                JournalEntry::Abort { ta_id: t_i },
            ],
            "{case}"
        );

        // t_i left no wip entry on x:
        assert_eq!(store.key_value_store()[object_id].wip, None, "{case}");
    }
}

/// Under serializable, a transaction that writes an object another transaction changed and committed after the
/// writer began commits if it never read the object (blind write).
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
///                                     update or delete x
///                                     commit
/// update or delete x
/// commit -> succeeds
/// ```
///
/// The result is the same as if t_j had run completely before t_i. Under snapshot isolation, t_i is aborted at its
/// write, see [`test_snapshot_isolation_level_aborts_write_to_object_committed_after_begin`]; with a read of x
/// before the commit of t_j, t_i is aborted under serializable as well, see
/// [`check_validation_detects_lost_update_on_read_object`]. An update after a committed delete inserts the object
/// again. Checked for every combination of t_j updating or deleting x and t_i updating or deleting x.
#[test]
fn test_serializable_level_commits_blind_write_after_concurrent_commit() {
    let write_kinds: [WriteKind; 2] = [WriteKind::Update, WriteKind::Delete];
    for write_j in write_kinds {
        for write_i in write_kinds {
            let case: String = format!("write_j = {write_j:?}, write_i = {write_i:?}");
            let mut store: TransactionalKeyValueStore<Stuff> =
                TransactionalKeyValueStore::with_isolation_level(
                    Validation::WriteSets,
                    IsolationLevel::Serializable,
                )
                .unwrap();
            let object_id: &str = "x";
            store.put(object_id, Stuff { a: 1, b: 0 }).unwrap();

            let t_i: u64 = store.begin_transaction();
            let t_j: u64 = store.begin_transaction();

            // t_j writes x and commits after t_i began:
            write(write_j, &mut store, object_id, t_j).unwrap();
            store.commit_transaction(t_j).unwrap();

            // t_i writes x without having read it and commits:
            assert_eq!(write(write_i, &mut store, object_id, t_i), Ok(()), "{case}");
            assert_eq!(store.commit_transaction(t_i), Ok(()), "{case}");
            assert_eq!(
                store.state().committed_transactions_trace.last(),
                Some(&t_i),
                "{case}"
            );

            // the version of t_i is the newest committed version of x:
            let newest: &VersionEntry<Stuff> = store.key_value_store()[object_id]
                .committed
                .last()
                .expect("x has committed versions");
            assert_eq!(
                Some(newest.start_validity),
                store.state().td[&t_i].committed_timestamp,
                "{case}"
            );
            let expected_version: Version<Stuff> = match write_i {
                WriteKind::Delete => Version::Delete,
                WriteKind::Insert | WriteKind::Update => Version::Update(value_of(t_i)),
            };
            assert_eq!(newest.version, expected_version, "{case}");
        }
    }
}

/// Under snapshot isolation, two transactions that read the same two objects and each update a different one both
/// commit (write skew).
///
/// ```text
/// t_i                                 t_j
/// begin
///                                     begin
/// read all -> sees s = (1, 0), t = (2, 0)
///                                     read all -> sees s = (1, 0), t = (2, 0)
/// update s to (1, 1)
/// commit -> succeeds
///                                     update t to (2, 1)
///                                     commit -> succeeds
/// ```
///
/// Snapshot isolation looks only at the written object and does not validate reads at commit. Under serializable,
/// the second commit is aborted, see [`check_write_skew_anomaly`].
#[test]
fn test_snapshot_isolation_level_allows_write_skew() {
    let mut store: TransactionalKeyValueStore<Stuff> =
        TransactionalKeyValueStore::with_isolation_level(
            Validation::WriteSets,
            IsolationLevel::SnapshotIsolation,
        )
        .unwrap();
    store.put("s", Stuff { a: 1, b: 0 }).unwrap();
    store.put("t", Stuff { a: 2, b: 0 }).unwrap();
    let original: Vec<(String, Stuff)> = vec![
        ("s".to_string(), Stuff { a: 1, b: 0 }),
        ("t".to_string(), Stuff { a: 2, b: 0 }),
    ];

    let t_i: u64 = store.begin_transaction();
    let t_j: u64 = store.begin_transaction();

    // both transactions read s and t:
    let result_i: Vec<(String, Stuff)> = store.read_objects(t_i, None, true).unwrap();
    assert_eq!(sorted(result_i), original);
    let result_j: Vec<(String, Stuff)> = store.read_objects(t_j, None, true).unwrap();
    assert_eq!(sorted(result_j), original);

    // t_i updates s and commits:
    store.update_object("s", Stuff { a: 1, b: 1 }, t_i).unwrap();
    store.commit_transaction(t_i).unwrap();

    // t_j updates t and commits, although t_i changed s, which t_j read:
    store.update_object("t", Stuff { a: 2, b: 1 }, t_j).unwrap();
    assert_eq!(store.commit_transaction(t_j), Ok(()));
    let trace: &Vec<u64> = &store.state().committed_transactions_trace;
    assert_eq!(trace[trace.len() - 2..], [t_i, t_j]);

    // a later transaction sees both changes:
    let t_k: u64 = store.begin_transaction();
    let result_k: Vec<(String, Stuff)> = store.read_objects(t_k, None, true).unwrap();
    assert_eq!(
        sorted(result_k),
        [
            ("s".to_string(), Stuff { a: 1, b: 1 }),
            ("t".to_string(), Stuff { a: 2, b: 1 }),
        ]
    );
}

/// Under snapshot isolation, a transaction may write an object another transaction changed and committed before
/// the writer began.
///
/// ```text
/// t_i                                 t_j
///                                     begin
///                                     update x to (1, t_j)
///                                     commit
/// begin
/// update x to (1, t_i)
/// commit -> succeeds
/// ```
///
/// Only commits after the begin of the writer count; commits before it are part of its snapshot.
#[test]
fn test_snapshot_isolation_level_allows_write_to_object_committed_before_begin() {
    let mut store: TransactionalKeyValueStore<Stuff> =
        TransactionalKeyValueStore::with_isolation_level(
            Validation::WriteSets,
            IsolationLevel::SnapshotIsolation,
        )
        .unwrap();
    let object_id: &str = "x";
    store.put(object_id, Stuff { a: 1, b: 0 }).unwrap();

    // t_j updates x and commits before t_i begins:
    let t_j: u64 = store.begin_transaction();
    write(WriteKind::Update, &mut store, object_id, t_j).unwrap();
    store.commit_transaction(t_j).unwrap();

    // t_i updates x and commits:
    let t_i: u64 = store.begin_transaction();
    assert_eq!(write(WriteKind::Update, &mut store, object_id, t_i), Ok(()));
    assert_eq!(store.commit_transaction(t_i), Ok(()));
    assert_eq!(
        store.state().committed_transactions_trace.last(),
        Some(&t_i)
    );
    assert_eq!(
        store.key_value_store()[object_id]
            .committed
            .last()
            .map(|newest| &newest.version),
        Some(&Version::Update(value_of(t_i)))
    );
}

/// The store returns [`StoreError::InvalidConfiguration`] for snapshot isolation combined with validation method 1
/// (snapshot isolation does not validate reads).
///
/// Python also rejects an unknown isolation level; that case cannot be written in Rust, as [`IsolationLevel`] has
/// only the two levels.
#[test]
fn test_snapshot_isolation_level_rejects_invalid_configuration() {
    let result: Result<TransactionalKeyValueStore<Stuff>, StoreError> =
        TransactionalKeyValueStore::with_isolation_level(
            Validation::BruteForce,
            IsolationLevel::SnapshotIsolation,
        );
    let error: Option<StoreError> = result.err();
    assert!(
        matches!(
            &error,
            Some(StoreError::InvalidConfiguration(message)) if message.contains("Validation::BruteForce")
        ),
        "snapshot isolation with brute force validation must be rejected, got {error:?}"
    );
}

/// Under snapshot isolation, a key whose insert was aborted can be inserted again and committed.
///
/// ```text
/// t_i                                 t_j
///                                     begin
///                                     insert x = (1, t_j)
///                                     abort
/// begin
/// insert x = (1, t_i)
/// commit -> succeeds
/// ```
///
/// After the aborted insert, x has an entry in the store but no committed version.
#[test]
fn test_snapshot_isolation_level_allows_reinsert_after_aborted_insert() {
    let mut store: TransactionalKeyValueStore<Stuff> =
        TransactionalKeyValueStore::with_isolation_level(
            Validation::WriteSets,
            IsolationLevel::SnapshotIsolation,
        )
        .unwrap();
    let object_id: &str = "x";

    // t_j inserts x and aborts:
    let t_j: u64 = store.begin_transaction();
    write(WriteKind::Insert, &mut store, object_id, t_j).unwrap();
    store.abort_transaction(t_j);
    assert_eq!(store.key_value_store()[object_id].committed, []);

    // t_i inserts x again and commits:
    let t_i: u64 = store.begin_transaction();
    assert_eq!(write(WriteKind::Insert, &mut store, object_id, t_i), Ok(()));
    assert_eq!(store.commit_transaction(t_i), Ok(()));
    assert_eq!(
        store.state().committed_transactions_trace.last(),
        Some(&t_i)
    );
    assert_eq!(
        store.key_value_store()[object_id]
            .committed
            .last()
            .map(|newest| &newest.version),
        Some(&Version::Update(value_of(t_i)))
    );
}
