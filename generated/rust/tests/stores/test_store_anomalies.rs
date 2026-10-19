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

//! Tests for the isolation of the transactional stores and the anomalies they avoid (Python:
//! `system/tests/stores/test_store_anomalies.py`).

use std::cell::Cell;
use std::rc::Rc;

use crate::common::{Account, Stuff, create_fake_data, update};
use explaindb::{
    Clause, JournalEntry, KvStoreEntry, ReadClause, StoreError, TransactionalKeyValueStore,
    TransactionalStore, TrueClause, Version, VersionEntry, WhereClause,
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

/// Checks that a transaction of the store `S` can update several objects several times: each update replaces the
/// work-in-progress version of the object written by this transaction, and the write set holds each object once.
/// After the commit, each object has two committed versions and no work-in-progress version, and the write set is
/// kept.
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

/// Checks that a transaction of the store `S` reads its own change of an object, not a version that another
/// transaction committed after it began (snapshot isolation from the point of view of a single transaction).
///
/// The test adds the committed version of the other transaction directly to the store:
///
/// ```text
/// t_i                                 other transaction
/// begin
/// read a == 4243 -> sees (4243, 0)
/// update 4242 to (4243, 4243)
///                                     commits (45, 45) for 4242
/// read a == 4243 -> sees (4243, 4243)
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

/// Checks that a transaction of the store `S` keeps reading the version of its snapshot while another transaction
/// changes the object, both before and after that transaction commits (repeatable reads). The reader then updates
/// the object and fails validation at its commit, as the other transaction changed an object it read. A
/// transaction that begins afterwards sees the change.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// read a == 7 -> sees (7, 0)
///                                     update 4242 to (7, 8)
/// read a == 7 -> sees (7, 0)
///                                     commit
/// read a == 7 -> sees (7, 0)
/// update 4242 to (7, 4534)
/// commit -> aborted
/// ```
///
/// A third transaction that begins after this reads (7, 8).
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

/// Checks that the store `S` avoids the write skew anomaly: two transactions read the same two objects X and Y,
/// each updates a different one, and the second commit fails because the first transaction changed an object the
/// second one read. The aborted transaction leaves no version in the store and is removed from the transaction
/// dictionary.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// read X (a == 1), read Y (a == 2)
///                                     read X (a == 1), read Y (a == 2)
/// update X
///                                     update Y
/// commit
///                                     commit -> aborted
/// ```
///
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_write_skew_anomaly<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();

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

/// A [`TransactionalKeyValueStore`] avoids the write skew anomaly, see [`check_write_skew_anomaly`].
#[test]
fn test_write_skew_anomaly() {
    check_write_skew_anomaly::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks a delete in a transaction of the store `S`: it adds a delete marker of the transaction as
/// work-in-progress version and leaves the committed version untouched; the commit makes the marker a committed
/// version. A committed transaction can neither read, delete nor update any more
/// ([`StoreError::AlreadyCommitted`]), and a transaction that begins afterwards does not see the object.
///
/// ```text
/// t_1                                 t_2
/// begin
/// read a == 4243 -> sees (4243, 0)
/// delete 4042
/// commit
/// read, delete, update -> fail
///                                     begin
///                                     read a == 4243 -> sees nothing
/// ```
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

/// Checks that the store `S` allows only one writer per object: a transaction that updates an object on which
/// another transaction holds a work-in-progress version is aborted.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// update 4242
///                                     update 4242 -> aborted
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
/// work-in-progress version, both if the first writer updates and if it deletes the object.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// update or delete 4242
///                                     delete 4242 -> aborted
/// commit -> succeeds
/// ```
///
/// t_2 is removed from the transaction dictionary and its journal holds only `Begin` and `Abort`; the
/// work-in-progress version of t_1 is untouched.
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

/// Checks that a transaction of the store `S` can change the same object several times and always reads its
/// latest change: two updates, then a delete, after which a read no longer returns the object.
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

/// Checks a read of all objects in the store `S` (with a [`TrueClause`]): the reader sees both objects of its
/// snapshot. If another transaction committed a change of an object meanwhile, the reader fails validation at its
/// commit, as its read could depend on that change; if the other transaction is still running, the reader commits.
///
/// ```text
/// t1                                  t2
/// begin
///                                     begin
///                                     update 1
///                                     commit (or keeps running)
/// read all -> sees 1 and 2
/// update 2
/// commit -> aborted (or committed)
/// ```
///
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_read_all<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    for t2_commits in [true, false] {
        let mut store: S = S::default();
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

/// A read of all objects in a [`TransactionalKeyValueStore`] is validated, see [`check_read_all`].
#[test]
fn test_read_all() {
    check_read_all::<TransactionalKeyValueStore<Stuff>>();
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

/// Checks that a transaction of the store `S` sees the object it inserted itself, next to the objects that existed
/// before: t inserts C and reads everything, and sees A and C with their values.
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

/// Checks that an aborted insert in the store `S` leaves no visible object behind, and that the object id can be
/// inserted again later: t inserts C and aborts, so t2 sees only A; t3 inserts C again and commits, so t4 sees A and
/// C with the value of t3.
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_detects_lost_update_on_read_object<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] detects a lost update, see
/// [`check_validation_detects_lost_update_on_read_object`].
#[test]
fn test_validation_detects_lost_update_on_read_object() {
    check_validation_detects_lost_update_on_read_object::<TransactionalKeyValueStore<Stuff>>();
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_detects_phantom_insert<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] detects a phantom insert, see [`check_validation_detects_phantom_insert`].
#[test]
fn test_validation_detects_phantom_insert() {
    check_validation_detects_phantom_insert::<TransactionalKeyValueStore<Stuff>>();
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_detects_concurrent_delete_of_read_object<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] detects the concurrent delete of a read object, see
/// [`check_validation_detects_concurrent_delete_of_read_object`].
#[test]
fn test_validation_detects_concurrent_delete_of_read_object() {
    check_validation_detects_concurrent_delete_of_read_object::<TransactionalKeyValueStore<Stuff>>(
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_detects_change_after_read_without_predicate<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] validates a read without a where clause, see
/// [`check_validation_detects_change_after_read_without_predicate`].
#[test]
fn test_validation_detects_change_after_read_without_predicate() {
    check_validation_detects_change_after_read_without_predicate::<TransactionalKeyValueStore<Stuff>>(
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_ignores_concurrent_write_outside_read_predicate<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] ignores a concurrent write outside the reads, see
/// [`check_validation_ignores_concurrent_write_outside_read_predicate`].
#[test]
fn test_validation_ignores_concurrent_write_outside_read_predicate() {
    check_validation_ignores_concurrent_write_outside_read_predicate::<
        TransactionalKeyValueStore<Stuff>,
    >();
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_detects_write_skew_on_objects_with_equal_hash<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] detects this write skew, see
/// [`check_validation_detects_write_skew_on_objects_with_equal_hash`]. The name comes from Python, where both
/// versions of A, (-1, 0) and (-2, 0), have the same CPython hash; Rust's validation uses no hashes.
#[test]
fn test_validation_detects_write_skew_on_objects_with_equal_hash() {
    check_validation_detects_write_skew_on_objects_with_equal_hash::<
        TransactionalKeyValueStore<Stuff>,
    >();
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_detects_swapped_values_of_read_objects<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] detects swapped values, see
/// [`check_validation_detects_swapped_values_of_read_objects`].
#[test]
fn test_validation_detects_swapped_values_of_read_objects() {
    check_validation_detects_swapped_values_of_read_objects::<TransactionalKeyValueStore<Stuff>>();
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_accepts_unhashable_objects<S>()
where
    S: TransactionalStore<Value = Account> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] works with values without `Hash`, see
/// [`check_validation_accepts_unhashable_objects`].
#[test]
fn test_validation_accepts_unhashable_objects() {
    check_validation_accepts_unhashable_objects::<TransactionalKeyValueStore<Account>>();
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
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2.
fn check_validation_detects_conflict_on_unhashable_objects<S>()
where
    S: TransactionalStore<Value = Account> + Default,
{
    let mut store: S = S::default();
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

/// A [`TransactionalKeyValueStore`] detects a conflict on values without `Hash`, see
/// [`check_validation_detects_conflict_on_unhashable_objects`].
#[test]
fn test_validation_detects_conflict_on_unhashable_objects() {
    check_validation_detects_conflict_on_unhashable_objects::<TransactionalKeyValueStore<Account>>(
    );
}

/// A where clause that counts how often it is evaluated (Python: `CountingWHERE_Clause`).
#[derive(Debug)]
struct CountingWhereClause {
    /// The where clause that does the actual evaluation.
    clause: WhereClause,
    /// The number of evaluations so far; a [`Cell`], as [`Clause::evaluate`] takes `&self`.
    evaluations: Cell<usize>,
}

impl Clause<Stuff> for CountingWhereClause {
    /// See [`Clause::evaluate`]. Also increments the evaluation counter.
    fn evaluate(&self, object: &Stuff) -> bool {
        self.evaluations.set(self.evaluations.get() + 1);
        Clause::<Stuff>::evaluate(&self.clause, object)
    }
}

/// Checks that `read_objects` of the store `S` evaluates the where clause once per object with validation method
/// 2, and that the result contains the transaction's own change. The read is kept in the transaction's reads with
/// the same clause object and without a checksum.
///
/// Python also runs this test with validation method 1, which is not ported yet; this test uses method 2. Method 1
/// evaluates the clause a second time on the committed snapshot to compute the checksum.
fn check_read_objects_evaluates_where_clause_twice_only_for_method_1<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
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
    // evaluated once each
    assert_eq!(counting.evaluations.get(), 2);
    assert_eq!(result, [("A".to_string(), Stuff { a: 42, b: 1 })]);

    // the read is kept with the same clause object and no checksum:
    let read_clauses: &Vec<ReadClause<Stuff>> = &store.state().td[&t_i].read_clauses;
    assert_eq!(read_clauses.len(), 1);
    let kept_clause: &Rc<dyn Clause<Stuff>> = read_clauses[0]
        .where_clause
        .as_ref()
        .expect("the read has a where clause");
    assert!(Rc::ptr_eq(kept_clause, &where_clause));
    assert_eq!(read_clauses[0].checksum, None);
}

/// `read_objects` of a [`TransactionalKeyValueStore`] evaluates the where clause once per object, see
/// [`check_read_objects_evaluates_where_clause_twice_only_for_method_1`].
#[test]
fn test_read_objects_evaluates_where_clause_twice_only_for_method_1() {
    check_read_objects_evaluates_where_clause_twice_only_for_method_1::<
        TransactionalKeyValueStore<Stuff>,
    >();
}
