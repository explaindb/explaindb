// Code generated from system/stores/MVCC.py, system/playground/mvcc_playground.py. DO NOT EDIT.
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

//! Rust-specific tests of the transactional (MVCC) store: the exact errors and panics of each operation, the
//! deduplication of the read set, stores that override `abort_transaction`, `validate_transaction`, `load` or the
//! transactional operations (also with autocommit) and forward `put`, `bulkload`, `get` and `delete`, the differences
//! between the two validation methods, the behaviour of validation method 1 and the settings of the isolation level
//! and of autocommit. They have no Python counterpart; the ported Python tests are in `test_store_anomalies.rs` and
//! `test_stores_basics.rs`. Tests that check the committed state after a transaction began read it with
//! `get_default`, the `get` of the versioned store, as the transactional `get` refuses once a transaction has begun.

use std::cell::Cell;
use std::rc::Rc;

use crate::common::{CountingWhereClause, Stuff, delete_marker, update};
use explaindb::{
    Clause, IsolationLevel, JournalEntry, KvStoreEntry, MvccState, ReadClause, Snapshot,
    StoreError, TransactionalKeyValueStore, TransactionalStore, Validation, VersionedStore,
    WhereClause, abort_transaction_default, bulkload_transactional, checksum,
    delete_object_default, delete_transactional, get_default, get_transactional, load_default,
    put_transactional, read_objects_default, update_object_default,
};
use indexmap::IndexMap;

/// Returns a store of type `S` with the objects A = (1, 0) and B = (2, 0), both committed with start of validity 0.
fn store_with_a_and_b<S>() -> S
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    store.put("B", Stuff { a: 2, b: 0 }).unwrap();
    store
}

/// Checks that `read_objects` and `update_object` of the store `S` return [`StoreError::TransactionNotFound`] for a
/// transaction id that was never handed out, and change nothing: no journal entry, no work-in-progress version.
fn check_read_and_update_of_unknown_transaction_fail<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();

    assert_eq!(
        store.read_objects(42, None, true),
        Err(StoreError::TransactionNotFound(42))
    );
    assert_eq!(
        store.update_object("A", Stuff { a: 1, b: 1 }, 42),
        Err(StoreError::TransactionNotFound(42))
    );

    assert_eq!(store.state().journal.size(), 0);
    assert_eq!(store.key_value_store()["A"].wip, None);
}

/// A [`TransactionalKeyValueStore`] rejects reads and updates of an unknown transaction, see
/// [`check_read_and_update_of_unknown_transaction_fail`].
#[test]
fn read_and_update_of_unknown_transaction_fail() {
    check_read_and_update_of_unknown_transaction_fail::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that the store `S` reports [`StoreError::AlreadyCommitted`] for a committed transaction before it checks
/// anything else: an update or delete of an object on which another transaction holds a work-in-progress version
/// does not abort the committed transaction, and a delete of a missing object does not report the missing object.
///
/// ```text
/// t_1                                 t_2
/// begin
/// commit
///                                     begin
///                                     update A
/// update A -> AlreadyCommitted
/// delete A -> AlreadyCommitted
/// delete Z (missing) -> AlreadyCommitted
/// ```
fn check_committed_transaction_is_reported_before_other_errors<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    store.commit_transaction(t_1).unwrap();
    let t_2: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 2 }, t_2).unwrap();

    assert_eq!(
        store.update_object("A", Stuff { a: 1, b: 1 }, t_1),
        Err(StoreError::AlreadyCommitted(t_1))
    );
    assert_eq!(
        store.delete_object("A", t_1),
        Err(StoreError::AlreadyCommitted(t_1))
    );
    assert_eq!(
        store.delete_object("Z", t_1),
        Err(StoreError::AlreadyCommitted(t_1))
    );

    // t_1 was not aborted, and the work-in-progress version of t_2 is untouched:
    assert_eq!(store.state().td[&t_1].committed_timestamp, Some(2));
    assert_eq!(
        store.state().journal.get(&t_1).unwrap(),
        [
            JournalEntry::Begin { ta_id: t_1 },
            JournalEntry::Commit {
                ta_id: t_1,
                commit_timestamp: 2
            },
        ]
    );
    assert_eq!(
        store.key_value_store()["A"].wip,
        Some(update(t_2, Stuff { a: 1, b: 2 }))
    );
}

/// A [`TransactionalKeyValueStore`] reports a committed transaction first, see
/// [`check_committed_transaction_is_reported_before_other_errors`].
#[test]
fn committed_transaction_is_reported_before_other_errors() {
    check_committed_transaction_is_reported_before_other_errors::<TransactionalKeyValueStore<Stuff>>(
    );
}

/// Under snapshot isolation, a [`TransactionalKeyValueStore`] reports [`StoreError::AlreadyCommitted`] for a committed
/// transaction t_1 before it checks whether another transaction committed the object after t_1 began; so the update
/// or delete does not abort t_1.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
///                                     update A
///                                     commit
/// commit
/// update A -> AlreadyCommitted
/// delete A -> AlreadyCommitted
/// ```
#[test]
fn committed_transaction_is_reported_before_snapshot_isolation_abort() {
    let mut store: TransactionalKeyValueStore<Stuff> =
        TransactionalKeyValueStore::with_isolation_level(
            Validation::WriteSets,
            IsolationLevel::SnapshotIsolation,
        )
        .unwrap();
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 2 }, t_2).unwrap();
    store.commit_transaction(t_2).unwrap();
    store.commit_transaction(t_1).unwrap();

    assert_eq!(
        store.update_object("A", Stuff { a: 1, b: 1 }, t_1),
        Err(StoreError::AlreadyCommitted(t_1))
    );
    assert_eq!(
        store.delete_object("A", t_1),
        Err(StoreError::AlreadyCommitted(t_1))
    );

    // t_1 was not aborted:
    assert!(store.state().td.contains_key(&t_1));
    assert_eq!(
        store.state().journal.get(&t_1).unwrap().last(),
        Some(&JournalEntry::Commit {
            ta_id: t_1,
            commit_timestamp: 4
        })
    );
}

/// Checks that `delete_object` of the store `S` returns [`StoreError::KeyNotFound`] for an object id that is not in
/// the store, and writes nothing: the journal of the transaction holds only `Begin`, its write set stays empty and
/// the store does not get an entry for the object id.
fn check_delete_of_missing_object_fails<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    let ta_id: u64 = store.begin_transaction();

    assert_eq!(
        store.delete_object("Z", ta_id),
        Err(StoreError::KeyNotFound("Z".to_string()))
    );

    assert_eq!(
        store.state().journal.get(&ta_id).unwrap(),
        [JournalEntry::Begin { ta_id }]
    );
    assert!(store.state().td[&ta_id].write_set.is_empty());
    assert_eq!(store.size(), 2);
}

/// A [`TransactionalKeyValueStore`] rejects the delete of a missing object, see
/// [`check_delete_of_missing_object_fails`].
#[test]
fn delete_of_missing_object_fails() {
    check_delete_of_missing_object_fails::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that `get_visible_object_version` of the store `S` returns [`StoreError::KeyNotFound`] for an object id
/// that is not in the store.
fn check_visible_version_of_missing_object_fails<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let store: S = store_with_a_and_b();

    assert_eq!(
        store.get_visible_object_version("Z", 1, false),
        Err(StoreError::KeyNotFound("Z".to_string()))
    );
}

/// A [`TransactionalKeyValueStore`] reports a missing object, see
/// [`check_visible_version_of_missing_object_fails`].
#[test]
fn visible_version_of_missing_object_fails() {
    check_visible_version_of_missing_object_fails::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that `read_objects` of the store `S` passes [`StoreError::VersionsNotOrdered`] on if the committed
/// versions of an object are not ordered by the start of their validity, and that the failed read is not added to
/// the reads of the transaction.
///
/// The test writes the committed versions (valid from 0, 5 and 4) directly into the store.
fn check_read_of_unordered_versions_fails<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    store.key_value_store_mut()["A"].committed.extend([
        update(5, Stuff { a: 5, b: 0 }),
        update(4, Stuff { a: 4, b: 0 }),
    ]);
    let ta_id: u64 = store.begin_transaction();

    assert_eq!(
        store.read_objects(ta_id, None, true),
        Err(StoreError::VersionsNotOrdered("A".to_string()))
    );
    assert!(store.state().td[&ta_id].read_clauses.is_empty());
}

/// A [`TransactionalKeyValueStore`] reports unordered versions in a read, see
/// [`check_read_of_unordered_versions_fails`].
#[test]
fn read_of_unordered_versions_fails() {
    check_read_of_unordered_versions_fails::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that `commit_transaction` of the store `S` passes [`StoreError::VersionsNotOrdered`] from the validation
/// on without aborting the transaction, as Python does: the transaction stays in the transaction dictionary,
/// uncommitted, with its work-in-progress version, and the journal gets neither `Commit` nor `Abort`. The commit
/// timestamp was drawn before the validation, so the transaction counter has advanced.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// read all -> sees A and B
/// update B
///                                     update A
///                                     commit (timestamp 3)
/// commit -> VersionsNotOrdered
/// ```
///
/// Before the commit of t_1, the test adds a committed version of A valid from 2 directly into the store, after the
/// version of t_2 valid from 3.
fn check_commit_with_unordered_versions_fails_without_abort<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    assert_eq!(store.read_objects(t_1, None, true).unwrap().len(), 2);
    store.update_object("B", Stuff { a: 2, b: 1 }, t_1).unwrap();
    store.update_object("A", Stuff { a: 1, b: 2 }, t_2).unwrap();
    store.commit_transaction(t_2).unwrap();

    // destroy the order of the committed versions of A, which t_1 validates against:
    store.key_value_store_mut()["A"]
        .committed
        .push(update(2, Stuff { a: 9, b: 9 }));

    assert_eq!(
        store.commit_transaction(t_1),
        Err(StoreError::VersionsNotOrdered("A".to_string()))
    );

    // t_1 is neither committed nor aborted:
    assert_eq!(store.state().td[&t_1].committed_timestamp, None);
    assert_eq!(
        store.key_value_store()["B"].wip,
        Some(update(t_1, Stuff { a: 2, b: 1 }))
    );
    assert_eq!(
        store.state().journal.get(&t_1).unwrap(),
        [
            JournalEntry::Begin { ta_id: t_1 },
            JournalEntry::Update {
                ta_id: t_1,
                object_id: "B".to_string(),
                new_value: Stuff { a: 2, b: 1 },
            },
        ]
    );
    assert_eq!(store.state().committed_transactions_trace, [t_2]);
    // ids 1 and 2 are the transactions, 3 the commit of t_2 and 4 the failed commit of t_1:
    assert_eq!(store.state().ta_id, 5);
}

/// A [`TransactionalKeyValueStore`] passes an error of the validation on, see
/// [`check_commit_with_unordered_versions_fails_without_abort`].
#[test]
fn commit_with_unordered_versions_fails_without_abort() {
    check_commit_with_unordered_versions_fails_without_abort::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that `commit_transaction` of the store `S` returns [`StoreError::TransactionNotFound`] naming a
/// transaction that committed while the committing transaction ran and was aborted afterwards: validation method 2
/// (the default) needs its write set, which left the store with the abort (Python raises a `KeyError`). The
/// committing transaction is not aborted.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// update A
///                                     update B
///                                     commit
///                                     abort
/// commit -> TransactionNotFound(t_2)
/// ```
fn check_validation_against_aborted_committed_transaction_fails<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();
    store.update_object("B", Stuff { a: 2, b: 2 }, t_2).unwrap();
    store.commit_transaction(t_2).unwrap();
    store.abort_transaction(t_2);

    assert_eq!(
        store.commit_transaction(t_1),
        Err(StoreError::TransactionNotFound(t_2))
    );

    // t_1 is neither committed nor aborted:
    assert_eq!(store.state().td[&t_1].committed_timestamp, None);
    assert_eq!(
        store.key_value_store()["A"].wip,
        Some(update(t_1, Stuff { a: 1, b: 1 }))
    );
}

/// A [`TransactionalKeyValueStore`] reports a committed and then aborted transaction during validation, see
/// [`check_validation_against_aborted_committed_transaction_fails`].
#[test]
fn validation_against_aborted_committed_transaction_fails() {
    check_validation_against_aborted_committed_transaction_fails::<TransactionalKeyValueStore<Stuff>>(
    );
}

/// The messages of the errors of transactions are those of Python's exceptions; `TransactionAborted` shows its
/// message only, `VersionsNotOrdered` also names the object, and `AutocommitRequired` names the operation, writes
/// Rust's `true` and adds "once a transaction has begun" if the operation is refused only for that reason.
#[test]
fn transaction_error_messages() {
    assert_eq!(
        StoreError::TransactionNotFound(42).to_string(),
        "transaction 42 not found in the system"
    );
    assert_eq!(
        StoreError::AlreadyCommitted(42).to_string(),
        "transaction 42 committed already"
    );
    assert_eq!(
        StoreError::TransactionAborted("validation failed".to_string()).to_string(),
        "validation failed"
    );
    assert_eq!(
        StoreError::VersionsNotOrdered("A".to_string()).to_string(),
        "committed versions of object A are not ordered by their validity start"
    );

    // the two forms of AutocommitRequired:
    assert_eq!(
        StoreError::AutocommitRequired {
            operation: "read_objects".to_string(),
            transaction_begun: false,
        }
        .to_string(),
        "read_objects without a transaction id needs autocommit=true"
    );
    assert_eq!(
        StoreError::AutocommitRequired {
            operation: "put".to_string(),
            transaction_begun: true,
        }
        .to_string(),
        "put without a transaction id needs autocommit=true once a transaction has begun"
    );
}

/// `delete_object` of a [`TransactionalKeyValueStore`] stops the program for an unknown transaction (Python: a
/// failing `assert`).
#[test]
#[should_panic(expected = "transaction 42 not found in the system")]
fn delete_of_unknown_transaction_panics() {
    let mut store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    let _ = store.delete_object("A", 42);
}

/// `commit_transaction` of a [`TransactionalKeyValueStore`] stops the program for an unknown transaction (Python: a
/// failing `assert`).
#[test]
#[should_panic(expected = "transaction 42 not found in the system")]
fn commit_of_unknown_transaction_panics() {
    let mut store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    let _ = store.commit_transaction(42);
}

/// `abort_transaction` of a [`TransactionalKeyValueStore`] stops the program for an unknown transaction (Python: a
/// failing `assert`).
#[test]
#[should_panic(expected = "transaction 42 not found in the system")]
fn abort_of_unknown_transaction_panics() {
    let mut store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    store.abort_transaction(42);
}

/// `validate_transaction` of a serializable [`TransactionalKeyValueStore`] stops the program for an unknown
/// transaction (Python: `KeyError`).
#[test]
#[should_panic(expected = "transaction 42 not found in the system")]
fn validation_of_unknown_transaction_panics() {
    let store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    let _ = store.validate_transaction(42, 43);
}

/// Under snapshot isolation, `validate_transaction` of a [`TransactionalKeyValueStore`] returns `true` for an unknown
/// transaction: it returns before it looks the transaction up, as Python does.
#[test]
fn validation_of_unknown_transaction_passes_under_snapshot_isolation() {
    let store: TransactionalKeyValueStore<Stuff> =
        TransactionalKeyValueStore::with_isolation_level(
            Validation::WriteSets,
            IsolationLevel::SnapshotIsolation,
        )
        .unwrap();
    assert_eq!(store.validate_transaction(42, 43), Ok(true));
}

/// Committing a transaction that wrote an object a second time stops the program (Python crashes, too): the second
/// commit validates the transaction again, which passes, as it read nothing; but its work-in-progress version of A
/// became a committed version at the first commit.
///
/// ```text
/// t_1
/// begin
/// update A
/// commit
/// commit -> panic
/// ```
#[test]
#[should_panic(expected = "transaction 1 has no work-in-progress version of object A")]
fn second_commit_of_writing_transaction_panics() {
    let mut store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    assert_eq!(t_1, 1);
    store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();
    store.commit_transaction(t_1).unwrap();
    let _ = store.commit_transaction(t_1);
}

/// Checks that the store `S` commits a transaction that wrote nothing a second time, as Python does: it passes
/// validation again, gets a new commit timestamp and a second `Commit` journal entry, and enters the trace of
/// committed transactions a second time.
fn check_second_commit_of_read_only_transaction_succeeds<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    assert_eq!(store.read_objects(t_1, None, true).unwrap().len(), 2);

    assert_eq!(store.commit_transaction(t_1), Ok(()));
    assert_eq!(store.commit_transaction(t_1), Ok(()));

    assert_eq!(store.state().committed_transactions_trace, [t_1, t_1]);
    assert_eq!(store.state().td[&t_1].committed_timestamp, Some(3));
    assert_eq!(
        store.state().journal.get(&t_1).unwrap(),
        [
            JournalEntry::Begin { ta_id: t_1 },
            JournalEntry::Commit {
                ta_id: t_1,
                commit_timestamp: 2
            },
            JournalEntry::Commit {
                ta_id: t_1,
                commit_timestamp: 3
            },
        ]
    );
}

/// A [`TransactionalKeyValueStore`] commits a read-only transaction twice, see
/// [`check_second_commit_of_read_only_transaction_succeeds`].
#[test]
fn second_commit_of_read_only_transaction_succeeds() {
    check_second_commit_of_read_only_transaction_succeeds::<TransactionalKeyValueStore<Stuff>>();
}

/// Checks that the store `S` allows to abort a committed transaction, as Python does: the abort removes the
/// transaction from the transaction dictionary and writes `Abort` to its journal, but keeps its committed version
/// and its place in the trace. It also removes the work-in-progress version of A, although that belongs to t_2 now,
/// so the change of t_2 is lost while t_2 keeps running.
///
/// ```text
/// t_1                                 t_2
/// begin
/// update A to (1, 1)
/// commit
///                                     begin
///                                     update A to (1, 2)
/// abort
/// ```
fn check_abort_of_committed_transaction_removes_wip_of_other_transaction<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();
    store.commit_transaction(t_1).unwrap();
    let t_2: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 2 }, t_2).unwrap();

    store.abort_transaction(t_1);

    // the work-in-progress version of t_2 is gone, the committed version of t_1 stays (`get_default` reads the newest
    // committed version without the rules of the transactional `get`, which refuses once a transaction has begun):
    assert_eq!(store.key_value_store()["A"].wip, None);
    assert_eq!(get_default(&store, "A"), Ok(&Stuff { a: 1, b: 1 }));
    // t_1 left the transaction dictionary, but not the trace:
    assert!(!store.state().td.contains_key(&t_1));
    assert_eq!(store.state().committed_transactions_trace, [t_1]);
    assert_eq!(
        store.state().journal.get(&t_1).unwrap().last(),
        Some(&JournalEntry::Abort { ta_id: t_1 })
    );
    // t_2 is still running and still lists A in its write set:
    assert!(store.state().td[&t_2].write_set.contains("A"));
}

/// A [`TransactionalKeyValueStore`] aborts a committed transaction, see
/// [`check_abort_of_committed_transaction_removes_wip_of_other_transaction`].
#[test]
fn abort_of_committed_transaction_removes_wip_of_other_transaction() {
    check_abort_of_committed_transaction_removes_wip_of_other_transaction::<
        TransactionalKeyValueStore<Stuff>,
    >();
}

/// Checks that `read_objects` of the store `S` keeps each read once in the reads of the transaction, as Python's set
/// of reads, whose clauses compare by identity: the same clause object read twice is kept once, two equal but
/// distinct clause objects are kept both, a read without a where clause twice is kept once, and a read with
/// `collect_read_clause = false` is not kept.
fn check_read_set_keeps_each_read_once<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    let equal_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));

    // the same clause object twice:
    let t_1: u64 = store.begin_transaction();
    for _ in 0..2 {
        store
            .read_objects(t_1, Some(Rc::clone(&where_clause)), true)
            .unwrap();
    }
    assert_eq!(store.state().td[&t_1].read_clauses.len(), 1);

    // two equal, but distinct clause objects:
    let t_2: u64 = store.begin_transaction();
    store
        .read_objects(t_2, Some(Rc::clone(&where_clause)), true)
        .unwrap();
    store
        .read_objects(t_2, Some(Rc::clone(&equal_clause)), true)
        .unwrap();
    assert_eq!(store.state().td[&t_2].read_clauses.len(), 2);

    // no where clause twice:
    let t_3: u64 = store.begin_transaction();
    for _ in 0..2 {
        store.read_objects(t_3, None, true).unwrap();
    }
    assert_eq!(store.state().td[&t_3].read_clauses.len(), 1);

    // reads that are not collected:
    let t_4: u64 = store.begin_transaction();
    store
        .read_objects(t_4, Some(Rc::clone(&where_clause)), false)
        .unwrap();
    store.read_objects(t_4, None, false).unwrap();
    assert!(store.state().td[&t_4].read_clauses.is_empty());
}

/// A [`TransactionalKeyValueStore`] keeps each read once, see [`check_read_set_keeps_each_read_once`].
#[test]
fn read_set_keeps_each_read_once() {
    check_read_set_keeps_each_read_once::<TransactionalKeyValueStore<Stuff>>();
}

/// Two reads are the same if they used the same clause object (or both none) and have the same checksum; a read
/// with a clause differs from one without, and the checksum, which validation method 1 sets, also counts.
#[test]
fn read_clause_same_as_compares_clause_identity_and_checksum() {
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    let read = |where_clause: Option<&Rc<dyn Clause<Stuff>>>, digest: Option<&str>| ReadClause {
        where_clause: where_clause.map(Rc::clone),
        checksum: digest.map(str::to_string),
    };

    assert!(read(Some(&where_clause), Some("x")).same_as(&read(Some(&where_clause), Some("x"))));
    assert!(!read(Some(&where_clause), Some("x")).same_as(&read(Some(&where_clause), Some("y"))));
    assert!(!read(Some(&where_clause), None).same_as(&read(Some(&where_clause), Some("x"))));
    assert!(!read(Some(&where_clause), None).same_as(&read(None, None)));
    assert!(!read(None, None).same_as(&read(Some(&where_clause), None)));
    // no clause on both sides counts as the same clause:
    assert!(read(None, None).same_as(&read(None, None)));
    // an equal but separate clause object is another clause, as in Python, where clauses compare by identity:
    let equal_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    assert!(!read(Some(&where_clause), None).same_as(&read(Some(&equal_clause), None)));
}

/// A store that counts the calls of `abort_transaction` and otherwise behaves like a [`TransactionalKeyValueStore`].
///
/// It overrides `abort_transaction` and calls the original through [`abort_transaction_default`], as the indexed
/// store (step 2 of the port) will do to also remove the index entries of the aborted transaction.
#[derive(Debug)]
struct CountingAbortStore<V> {
    /// The store that does the actual work.
    store: TransactionalKeyValueStore<V>,
    /// The number of calls of `abort_transaction` so far.
    aborts: usize,
}

impl<V> Default for CountingAbortStore<V> {
    /// Creates an empty store that has not aborted anything yet.
    fn default() -> Self {
        CountingAbortStore {
            store: TransactionalKeyValueStore::new(),
            aborts: 0,
        }
    }
}

impl<V: Clone + PartialEq + std::fmt::Debug> VersionedStore for CountingAbortStore<V> {
    type Value = V;

    /// See [`VersionedStore::key_value_store`].
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store()
    }

    /// See [`VersionedStore::key_value_store_mut`].
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store_mut()
    }

    /// See [`VersionedStore::put`]; runs [`put_transactional`].
    fn put(&mut self, object_id: impl Into<String>, object: V) -> Result<(), StoreError> {
        put_transactional(self, object_id, object)
    }

    /// See [`VersionedStore::get`]; runs [`get_transactional`].
    fn get(&mut self, object_id: &str) -> Result<&V, StoreError> {
        get_transactional(self, object_id)
    }

    /// See [`VersionedStore::delete`]; runs [`delete_transactional`].
    fn delete(&mut self, object_id: &str) -> Result<(), StoreError> {
        delete_transactional(self, object_id)
    }

    /// See [`VersionedStore::bulkload`]; runs [`bulkload_transactional`].
    fn bulkload<K, I>(&mut self, input_data: I) -> Result<(), StoreError>
    where
        K: Into<String>,
        I: IntoIterator<Item = (K, V)>,
    {
        bulkload_transactional(self, input_data)
    }
}

impl<V: Clone + PartialEq + std::fmt::Debug> TransactionalStore for CountingAbortStore<V> {
    /// See [`TransactionalStore::state`].
    fn state(&self) -> &MvccState<V> {
        self.store.state()
    }

    /// See [`TransactionalStore::state_mut`].
    fn state_mut(&mut self) -> &mut MvccState<V> {
        self.store.state_mut()
    }

    /// See [`TransactionalStore::abort_transaction`]. Also increments the abort counter.
    fn abort_transaction(&mut self, ta_id: u64) {
        self.aborts += 1;
        abort_transaction_default(self, ta_id);
    }
}

/// An update of an object on which another transaction holds a work-in-progress version calls the overridden
/// `abort_transaction` once, which aborts the transaction: it leaves the transaction dictionary, and the
/// work-in-progress version of the other transaction stays.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// update A
///                                     update A -> aborted
/// ```
#[test]
fn conflicting_update_calls_overridden_abort() {
    let mut store: CountingAbortStore<Stuff> = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();

    assert_eq!(
        store.update_object("A", Stuff { a: 1, b: 2 }, t_2),
        Err(StoreError::TransactionAborted(
            "another transaction is currently modifying object A already".to_string()
        ))
    );

    assert_eq!(store.aborts, 1);
    assert!(!store.state().td.contains_key(&t_2));
    assert_eq!(
        store.key_value_store()["A"].wip,
        Some(update(t_1, Stuff { a: 1, b: 1 }))
    );
}

/// A delete of an object on which another transaction holds a work-in-progress version calls the overridden
/// `abort_transaction` once, which aborts the transaction.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// update A
///                                     delete A -> aborted
/// ```
#[test]
fn conflicting_delete_calls_overridden_abort() {
    let mut store: CountingAbortStore<Stuff> = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();

    assert_eq!(
        store.delete_object("A", t_2),
        Err(StoreError::TransactionAborted(
            "another transaction is currently modifying object A already".to_string()
        ))
    );

    assert_eq!(store.aborts, 1);
    assert!(!store.state().td.contains_key(&t_2));
}

/// Returns a [`CountingAbortStore`] under snapshot isolation with the objects A = (1, 0) and B = (2, 0), and the
/// ids of the transactions t_1 and t_2 of this schedule, in which A changed after t_1 began:
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
///                                     update A
///                                     commit
/// ```
fn snapshot_isolation_store_after_commit_of_a() -> (CountingAbortStore<Stuff>, u64, u64) {
    let mut store: CountingAbortStore<Stuff> = CountingAbortStore {
        store: TransactionalKeyValueStore::with_isolation_level(
            Validation::WriteSets,
            IsolationLevel::SnapshotIsolation,
        )
        .unwrap(),
        aborts: 0,
    };
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    store.put("B", Stuff { a: 2, b: 0 }).unwrap();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    store.update_object("A", Stuff { a: 1, b: 2 }, t_2).unwrap();
    store.commit_transaction(t_2).unwrap();
    (store, t_1, t_2)
}

/// Under snapshot isolation, an update of an object that another transaction committed after the writer began calls
/// the overridden `abort_transaction` once, which aborts the writer and removes its earlier work-in-progress
/// version.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
///                                     update A
///                                     commit
/// update B
/// update A -> aborted
/// ```
#[test]
fn snapshot_isolation_update_calls_overridden_abort() {
    let (mut store, t_1, _): (CountingAbortStore<Stuff>, u64, u64) =
        snapshot_isolation_store_after_commit_of_a();
    store.update_object("B", Stuff { a: 2, b: 1 }, t_1).unwrap();

    assert_eq!(
        store.update_object("A", Stuff { a: 1, b: 1 }, t_1),
        Err(StoreError::TransactionAborted(
            "transaction 1 aborted under snapshot isolation: another transaction changed object A and committed \
             after transaction 1 began"
                .to_string()
        ))
    );

    assert_eq!(store.aborts, 1);
    assert!(!store.state().td.contains_key(&t_1));
    assert_eq!(store.key_value_store()["A"].wip, None);
    assert_eq!(store.key_value_store()["B"].wip, None);
}

/// Under snapshot isolation, a delete of an object that another transaction committed after the writer began calls
/// the overridden `abort_transaction` once, which aborts the writer and removes its earlier work-in-progress
/// version.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
///                                     update A
///                                     commit
/// update B
/// delete A -> aborted
/// ```
#[test]
fn snapshot_isolation_delete_calls_overridden_abort() {
    let (mut store, t_1, _): (CountingAbortStore<Stuff>, u64, u64) =
        snapshot_isolation_store_after_commit_of_a();
    store.update_object("B", Stuff { a: 2, b: 1 }, t_1).unwrap();

    assert_eq!(
        store.delete_object("A", t_1),
        Err(StoreError::TransactionAborted(
            "transaction 1 aborted under snapshot isolation: another transaction changed object A and committed \
             after transaction 1 began"
                .to_string()
        ))
    );

    assert_eq!(store.aborts, 1);
    assert!(!store.state().td.contains_key(&t_1));
    assert_eq!(store.key_value_store()["A"].wip, None);
    assert_eq!(store.key_value_store()["B"].wip, None);
}

/// A commit whose validation fails calls the overridden `abort_transaction` once, which aborts the transaction and
/// removes its work-in-progress version.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// read a == 1 -> sees A
///                                     update A
///                                     commit
/// update B
/// commit -> aborted
/// ```
#[test]
fn failed_validation_calls_overridden_abort() {
    let mut store: CountingAbortStore<Stuff> = store_with_a_and_b();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    assert_eq!(
        store.read_objects(t_1, Some(where_clause), true).unwrap(),
        [("A".to_string(), Stuff { a: 1, b: 0 })]
    );
    store.update_object("A", Stuff { a: 1, b: 2 }, t_2).unwrap();
    store.commit_transaction(t_2).unwrap();
    store.update_object("B", Stuff { a: 2, b: 1 }, t_1).unwrap();

    assert_eq!(
        store.commit_transaction(t_1),
        Err(StoreError::TransactionAborted(
            "validation failed, Transaction 1 failed the validation phase and therefore was aborted due to a \
             conflict with another transaction"
                .to_string()
        ))
    );

    assert_eq!(store.aborts, 1);
    assert!(!store.state().td.contains_key(&t_1));
    assert_eq!(store.key_value_store()["B"].wip, None);
}

/// An operation of a [`CountingAbortStore`] that a test runs and whose result it checks; an operation that returns
/// an object, such as `get`, drops it.
type CountingAbortOperation = fn(&mut CountingAbortStore<Stuff>) -> Result<(), StoreError>;

/// With autocommit, an operation of a [`CountingAbortStore`] that writes an object an open transaction is writing
/// calls the overridden `abort_transaction` exactly once: `update_object` or `delete_object`, run in the transaction
/// of its own, aborts that transaction through the trait on the conflict, so it is not aborted a second time. The
/// operation returns `TransactionAborted`, and only the open transaction is left.
///
/// ```text
/// t_1                                 autocommit
/// begin
/// update A
/// insert C
///                                     put C -> aborted
///                                     (or: bulkload D and C, delete A, update_object A, delete_object A)
/// ```
#[test]
fn autocommit_conflict_calls_overridden_abort_once() {
    let cases: [(&str, CountingAbortOperation, &str); 5] = [
        ("put", |store| store.put("C", Stuff { a: 9, b: 9 }), "C"),
        (
            "bulkload",
            |store| store.bulkload([("D", Stuff { a: 4, b: 0 }), ("C", Stuff { a: 9, b: 9 })]),
            "C",
        ),
        ("delete", |store| store.delete("A"), "A"),
        (
            "update_object",
            |store| store.update_object("A", Stuff { a: 9, b: 9 }, None),
            "A",
        ),
        ("delete_object", |store| store.delete_object("A", None), "A"),
    ];
    for (case, operation, object_id) in cases {
        // with autocommit, t_1 updates A, inserts C and stays open:
        let mut store: CountingAbortStore<Stuff> = store_with_a_and_b();
        store.state_mut().autocommit = true;
        let t_1: u64 = store.begin_transaction();
        store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();
        store.update_object("C", Stuff { a: 3, b: 0 }, t_1).unwrap();

        // the operation conflicts with t_1:
        assert_eq!(
            operation(&mut store),
            Err(StoreError::TransactionAborted(format!(
                "another transaction is currently modifying object {object_id} already"
            ))),
            "{case}"
        );

        // the override ran once, and only t_1 is left:
        assert_eq!(store.aborts, 1, "{case}");
        assert_eq!(
            store.state().td.keys().copied().collect::<Vec<u64>>(),
            [t_1],
            "{case}"
        );
    }
}

/// With autocommit, an operation of a [`CountingAbortStore`] whose transaction of its own fails with an error other
/// than a conflict calls the overridden `abort_transaction` exactly once, to abort that transaction, and leaves no
/// transaction: `put` and `bulkload` of a visible object return `KeyExists`; `get`, `delete` and `delete_object`
/// (with the transaction id `None`) of a missing object return `KeyNotFound`.
#[test]
fn autocommit_error_calls_overridden_abort_once() {
    let cases: [(&str, CountingAbortOperation, StoreError); 5] = [
        (
            "put",
            |store| store.put("A", Stuff { a: 9, b: 9 }),
            StoreError::KeyExists("A".to_string()),
        ),
        (
            "bulkload",
            |store| store.bulkload([("C", Stuff { a: 3, b: 0 }), ("A", Stuff { a: 9, b: 9 })]),
            StoreError::KeyExists("A".to_string()),
        ),
        (
            "get",
            |store| store.get("missing").map(|_| ()),
            StoreError::KeyNotFound("missing".to_string()),
        ),
        (
            "delete",
            |store| store.delete("missing"),
            StoreError::KeyNotFound("missing".to_string()),
        ),
        (
            "delete_object",
            |store| store.delete_object("missing", None),
            StoreError::KeyNotFound("missing".to_string()),
        ),
    ];
    for (case, operation, expected) in cases {
        // the operation fails on a store with autocommit and the committed objects A and B:
        let mut store: CountingAbortStore<Stuff> = store_with_a_and_b();
        store.state_mut().autocommit = true;
        assert_eq!(operation(&mut store), Err(expected), "{case}");

        // the override ran once, and no transaction is left:
        assert_eq!(store.aborts, 1, "{case}");
        assert!(store.state().td.is_empty(), "{case}");
    }
}

/// A store that never validates, so anomalies such as write skew happen (Python: `StoreWithoutValidation` in
/// `system/playground/mvcc_playground.py`).
///
/// Each transaction reads the snapshot of its begin plus its own writes. A write is stopped only while another
/// transaction holds an uncommitted version of the same object (see `update_object_default`). This is weaker than
/// snapshot isolation ([`IsolationLevel::SnapshotIsolation`]), which also stops a write to an object that another
/// transaction committed after the writer's begin:
///
/// ```text
/// T1                          T2
/// begin
///                             begin
/// read x
///                             read x
/// update x
/// commit
///                             update x -> passes here, aborts under snapshot isolation
///                             commit   -> T1's update is lost
/// ```
///
/// Write skew happens under both, as the two transactions write different objects. The store overrides
/// `validate_transaction`; `commit_transaction` calls the override through the trait.
#[derive(Debug)]
struct StoreWithoutValidation<V> {
    /// The store that does the actual work.
    store: TransactionalKeyValueStore<V>,
}

impl<V> Default for StoreWithoutValidation<V> {
    /// Creates an empty store.
    fn default() -> Self {
        StoreWithoutValidation {
            store: TransactionalKeyValueStore::new(),
        }
    }
}

impl<V: Clone + PartialEq + std::fmt::Debug> VersionedStore for StoreWithoutValidation<V> {
    type Value = V;

    /// See [`VersionedStore::key_value_store`].
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store()
    }

    /// See [`VersionedStore::key_value_store_mut`].
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store_mut()
    }

    /// See [`VersionedStore::put`]; runs [`put_transactional`].
    fn put(&mut self, object_id: impl Into<String>, object: V) -> Result<(), StoreError> {
        put_transactional(self, object_id, object)
    }

    /// See [`VersionedStore::get`]; runs [`get_transactional`].
    fn get(&mut self, object_id: &str) -> Result<&V, StoreError> {
        get_transactional(self, object_id)
    }

    /// See [`VersionedStore::delete`]; runs [`delete_transactional`].
    fn delete(&mut self, object_id: &str) -> Result<(), StoreError> {
        delete_transactional(self, object_id)
    }

    /// See [`VersionedStore::bulkload`]; runs [`bulkload_transactional`].
    fn bulkload<K, I>(&mut self, input_data: I) -> Result<(), StoreError>
    where
        K: Into<String>,
        I: IntoIterator<Item = (K, V)>,
    {
        bulkload_transactional(self, input_data)
    }
}

impl<V: Clone + PartialEq + std::fmt::Debug> TransactionalStore for StoreWithoutValidation<V> {
    /// See [`TransactionalStore::state`].
    fn state(&self) -> &MvccState<V> {
        self.store.state()
    }

    /// See [`TransactionalStore::state_mut`].
    fn state_mut(&mut self) -> &mut MvccState<V> {
        self.store.state_mut()
    }

    /// See [`TransactionalStore::validate_transaction`]. Always passes.
    fn validate_transaction(
        &self,
        _ta_id: u64,
        _commit_timestamp: u64,
    ) -> Result<bool, StoreError> {
        Ok(true)
    }
}

/// A store whose overridden validation always passes lets both transactions of the write skew schedule commit, so
/// the write skew anomaly happens: `commit_transaction` uses the override, not the default validation, which
/// aborts t_2 here (see `check_write_skew_anomaly` in `test_store_anomalies.rs`).
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
///                                     commit -> succeeds
/// ```
#[test]
fn commit_uses_overridden_validation() {
    let mut store: StoreWithoutValidation<Stuff> = StoreWithoutValidation::default();
    store.put("X", Stuff { a: 1, b: 0 }).unwrap();
    store.put("Y", Stuff { a: 2, b: 0 }).unwrap();
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    let where_x: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    let where_y: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 2));
    for ta_id in [t_1, t_2] {
        store
            .read_objects(ta_id, Some(Rc::clone(&where_x)), true)
            .unwrap();
        store
            .read_objects(ta_id, Some(Rc::clone(&where_y)), true)
            .unwrap();
    }
    store
        .update_object("X", Stuff { a: 1, b: 100 }, t_1)
        .unwrap();
    store
        .update_object("Y", Stuff { a: 2, b: 200 }, t_2)
        .unwrap();

    assert_eq!(store.commit_transaction(t_1), Ok(()));
    assert_eq!(store.commit_transaction(t_2), Ok(()));

    assert_eq!(store.state().committed_transactions_trace, [t_1, t_2]);
    assert_eq!(get_default(&store, "X"), Ok(&Stuff { a: 1, b: 100 }));
    assert_eq!(get_default(&store, "Y"), Ok(&Stuff { a: 2, b: 200 }));
}

/// A store with autocommit that records the transaction id each call of `read_objects`, `update_object` and
/// `delete_object` receives and the object id of each call of `load`, and otherwise behaves like a
/// [`TransactionalKeyValueStore`].
///
/// Its overrides record the call and hand the transaction id on unchanged, `None` included, to the original through
/// [`read_objects_default`], [`update_object_default`] and [`delete_object_default`], as a store that adds work to
/// these operations must do (Python: an override hands `None` straight to the method of the base class); `load`
/// hands the object on to [`load_default`].
#[derive(Debug)]
struct RecordingStore<V> {
    /// The store that does the actual work.
    store: TransactionalKeyValueStore<V>,
    /// The operation and the transaction id of every call of the overrides of the three transactional operations so
    /// far, oldest first.
    calls: Vec<(&'static str, Option<u64>)>,
    /// The object id of every call of `load` so far, oldest first.
    loaded: Vec<String>,
}

impl<V> Default for RecordingStore<V> {
    /// Creates an empty store with autocommit that has not recorded any call yet.
    fn default() -> Self {
        RecordingStore {
            store: TransactionalKeyValueStore::new().with_autocommit(true),
            calls: Vec::new(),
            loaded: Vec::new(),
        }
    }
}

impl<V: Clone + PartialEq + std::fmt::Debug> VersionedStore for RecordingStore<V> {
    type Value = V;

    /// See [`VersionedStore::key_value_store`].
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store()
    }

    /// See [`VersionedStore::key_value_store_mut`].
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store_mut()
    }

    /// See [`VersionedStore::put`]; runs [`put_transactional`].
    fn put(&mut self, object_id: impl Into<String>, object: V) -> Result<(), StoreError> {
        put_transactional(self, object_id, object)
    }

    /// See [`VersionedStore::get`]; runs [`get_transactional`].
    fn get(&mut self, object_id: &str) -> Result<&V, StoreError> {
        get_transactional(self, object_id)
    }

    /// See [`VersionedStore::delete`]; runs [`delete_transactional`].
    fn delete(&mut self, object_id: &str) -> Result<(), StoreError> {
        delete_transactional(self, object_id)
    }

    /// See [`VersionedStore::bulkload`]; runs [`bulkload_transactional`].
    fn bulkload<K, I>(&mut self, input_data: I) -> Result<(), StoreError>
    where
        K: Into<String>,
        I: IntoIterator<Item = (K, V)>,
    {
        bulkload_transactional(self, input_data)
    }
}

impl<V: Clone + PartialEq + std::fmt::Debug> TransactionalStore for RecordingStore<V> {
    /// See [`TransactionalStore::state`].
    fn state(&self) -> &MvccState<V> {
        self.store.state()
    }

    /// See [`TransactionalStore::state_mut`].
    fn state_mut(&mut self) -> &mut MvccState<V> {
        self.store.state_mut()
    }

    /// See [`TransactionalStore::read_objects`]. Also records the call.
    fn read_objects(
        &mut self,
        ta_id: impl Into<Option<u64>>,
        where_clause: Option<Rc<dyn Clause<V>>>,
        collect_read_clause: bool,
    ) -> Result<Vec<(String, V)>, StoreError> {
        let ta_id: Option<u64> = ta_id.into();
        self.calls.push(("read_objects", ta_id));
        read_objects_default(self, ta_id, where_clause, collect_read_clause)
    }

    /// See [`TransactionalStore::update_object`]. Also records the call.
    fn update_object(
        &mut self,
        object_id: &str,
        updated_object: V,
        ta_id: impl Into<Option<u64>>,
    ) -> Result<(), StoreError> {
        let ta_id: Option<u64> = ta_id.into();
        self.calls.push(("update_object", ta_id));
        update_object_default(self, object_id, updated_object, ta_id)
    }

    /// See [`TransactionalStore::delete_object`]. Also records the call.
    fn delete_object(
        &mut self,
        object_id: &str,
        ta_id: impl Into<Option<u64>>,
    ) -> Result<(), StoreError> {
        let ta_id: Option<u64> = ta_id.into();
        self.calls.push(("delete_object", ta_id));
        delete_object_default(self, object_id, ta_id)
    }

    /// See [`TransactionalStore::load`]. Also records the call.
    fn load(&mut self, object_id: String, object: V) -> Result<(), StoreError> {
        self.loaded.push(object_id.clone());
        load_default(self, object_id, object)
    }
}

/// With autocommit, `update_object`, `read_objects` and `delete_object` of a store that overrides them, called with
/// the transaction id `None`, run each override twice: first with `None` from the caller, then with the id of the
/// transaction of its own, from the default function. The operation itself runs once, in that transaction, which
/// commits; every transaction of its own uses up two values of the counter (its begin and its commit).
///
/// ```text
/// caller                              default function
/// update_object A, None
///                                     begin -> 1
///                                     update_object A, 1
///                                     commit at 2
/// read_objects a == 1, None
///                                     begin -> 3
///                                     read_objects a == 1, 3 -> sees A
///                                     commit at 4
/// delete_object A, None
///                                     begin -> 5
///                                     delete_object A, 5
///                                     commit at 6
/// ```
#[test]
fn autocommit_calls_overridden_operations_again_with_own_transaction_id() {
    let mut store: RecordingStore<Stuff> = RecordingStore::default();

    // update_object inserts A once, in transaction 1, which commits at 2:
    store
        .update_object("A", Stuff { a: 1, b: 0 }, None)
        .unwrap();
    assert_eq!(
        std::mem::take(&mut store.calls),
        [("update_object", None), ("update_object", Some(1))]
    );
    assert_eq!(
        store.state().journal.get(&1).unwrap(),
        [
            JournalEntry::Begin { ta_id: 1 },
            JournalEntry::Update {
                ta_id: 1,
                object_id: "A".to_string(),
                new_value: Stuff { a: 1, b: 0 },
            },
            JournalEntry::Commit {
                ta_id: 1,
                commit_timestamp: 2
            },
        ]
    );
    assert_eq!(
        store.key_value_store()["A"].committed,
        [update(2, Stuff { a: 1, b: 0 })]
    );

    // read_objects reads once, in transaction 3, which commits at 4: the where clause is evaluated once, on A:
    let counting: Rc<CountingWhereClause> = Rc::new(CountingWhereClause {
        clause: WhereClause::new("a", "==", 1),
        evaluations: Cell::new(0),
    });
    assert_eq!(
        store.read_objects(None, Some(counting.clone()), true),
        Ok(vec![("A".to_string(), Stuff { a: 1, b: 0 })])
    );
    assert_eq!(
        std::mem::take(&mut store.calls),
        [("read_objects", None), ("read_objects", Some(3))]
    );
    assert_eq!(counting.evaluations.get(), 1);
    assert_eq!(store.state().td[&3].committed_timestamp, Some(4));

    // delete_object deletes A once, in transaction 5, which commits at 6:
    store.delete_object("A", None).unwrap();
    assert_eq!(
        std::mem::take(&mut store.calls),
        [("delete_object", None), ("delete_object", Some(5))]
    );
    assert_eq!(
        store.state().journal.get(&5).unwrap(),
        [
            JournalEntry::Begin { ta_id: 5 },
            JournalEntry::Delete {
                ta_id: 5,
                object_id: "A".to_string(),
            },
            JournalEntry::Commit {
                ta_id: 5,
                commit_timestamp: 6
            },
        ]
    );
    assert_eq!(
        store.key_value_store()["A"].committed,
        [update(2, Stuff { a: 1, b: 0 }), delete_marker(6)]
    );

    // one transaction per call, and all three committed:
    assert_eq!(store.state().journal.size(), 3);
    assert_eq!(store.state().committed_transactions_trace, [1, 3, 5]);
}

/// With autocommit, `put`, `bulkload` and `delete` of a store that overrides `update_object` and `delete_object` call
/// the override once per object, with the id of the transaction of its own, never with `None`; each operation runs
/// as one transaction, which commits.
///
/// ```text
/// caller                              transaction of its own
/// put A
///                                     begin -> 1
///                                     update_object A, 1
///                                     commit at 2
/// bulkload B and C
///                                     begin -> 3
///                                     update_object B, 3
///                                     update_object C, 3
///                                     commit at 4
/// delete A
///                                     begin -> 5
///                                     delete_object A, 5
///                                     commit at 6
/// ```
#[test]
fn autocommit_put_bulkload_and_delete_call_overridden_operations_with_own_transaction_id() {
    let mut store: RecordingStore<Stuff> = RecordingStore::default();

    // put inserts A with one call of update_object in transaction 1:
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    assert_eq!(
        std::mem::take(&mut store.calls),
        [("update_object", Some(1))]
    );
    assert_eq!(
        store.key_value_store()["A"].committed,
        [update(2, Stuff { a: 1, b: 0 })]
    );

    // bulkload inserts B and C with one call each, both in transaction 3:
    store
        .bulkload([("B", Stuff { a: 2, b: 0 }), ("C", Stuff { a: 3, b: 0 })])
        .unwrap();
    assert_eq!(
        std::mem::take(&mut store.calls),
        [("update_object", Some(3)), ("update_object", Some(3))]
    );
    assert_eq!(
        store.key_value_store()["B"].committed,
        [update(4, Stuff { a: 2, b: 0 })]
    );
    assert_eq!(
        store.key_value_store()["C"].committed,
        [update(4, Stuff { a: 3, b: 0 })]
    );

    // delete deletes A with one call of delete_object in transaction 5:
    store.delete("A").unwrap();
    assert_eq!(
        std::mem::take(&mut store.calls),
        [("delete_object", Some(5))]
    );
    assert_eq!(
        store.key_value_store()["A"].committed,
        [update(2, Stuff { a: 1, b: 0 }), delete_marker(6)]
    );

    // all three transactions committed:
    assert_eq!(store.state().committed_transactions_trace, [1, 3, 5]);
}

/// `put` and `bulkload` of a store that overrides `load` call the override once per object in the load phase
/// (without autocommit, before the first transaction), and neither begin a transaction nor call `update_object`.
/// With autocommit, they insert in a transaction of their own and do not call `load`.
#[test]
fn put_and_bulkload_call_overridden_load_only_in_load_phase() {
    let mut store: RecordingStore<Stuff> = RecordingStore::default();
    store.state_mut().autocommit = false;

    // in the load phase, put and bulkload hand each object to load, in the order of the calls:
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    store
        .bulkload([("B", Stuff { a: 2, b: 0 }), ("C", Stuff { a: 3, b: 0 })])
        .unwrap();
    assert_eq!(store.loaded, ["A", "B", "C"]);

    // the objects are the initial state, valid from 0, written without a transaction:
    assert_eq!(
        store.key_value_store()["C"].committed,
        [update(0, Stuff { a: 3, b: 0 })]
    );
    assert!(store.calls.is_empty());
    assert_eq!(store.state().ta_id, 1);

    // with autocommit, put and bulkload do not call load:
    let mut store: RecordingStore<Stuff> = RecordingStore::default();
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    store.bulkload([("B", Stuff { a: 2, b: 0 })]).unwrap();
    assert!(store.loaded.is_empty());

    // they inserted in the transactions 1 and 3, which committed at 2 and 4:
    assert_eq!(
        store.key_value_store()["A"].committed,
        [update(2, Stuff { a: 1, b: 0 })]
    );
    assert_eq!(
        store.key_value_store()["B"].committed,
        [update(4, Stuff { a: 2, b: 0 })]
    );
}

/// Checks that the implementation of [`VersionedStore`] of the store `S` forwards `put`, `bulkload`, `get` and
/// `delete` to [`put_transactional`], [`bulkload_transactional`], [`get_transactional`] and
/// [`delete_transactional`]: without autocommit, once a transaction has begun, they return
/// [`StoreError::AutocommitRequired`], where the methods of the versioned store would insert, read and delete.
fn check_operations_without_transaction_id_are_forwarded<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    // the name of the store, for the messages of the assertions:
    let store_name: &str = std::any::type_name::<S>();
    let refused = |operation: &str, transaction_begun: bool| StoreError::AutocommitRequired {
        operation: operation.to_string(),
        transaction_begun,
    };

    // without autocommit, A is loaded, then a transaction begins:
    let mut store: S = S::default();
    store.state_mut().autocommit = false;
    store.put("A", Stuff { a: 1, b: 0 }).unwrap();
    store.begin_transaction();

    // each operation without a transaction id is refused:
    assert_eq!(
        store.put("B", Stuff { a: 2, b: 0 }),
        Err(refused("put", true)),
        "{store_name}"
    );
    assert_eq!(
        store.bulkload([("B", Stuff { a: 2, b: 0 })]),
        Err(refused("bulkload", true)),
        "{store_name}"
    );
    assert_eq!(store.get("A"), Err(refused("get", true)), "{store_name}");
    assert_eq!(
        store.delete("A"),
        Err(refused("delete", false)),
        "{store_name}"
    );
}

/// The test stores of this file forward `put`, `bulkload`, `get` and `delete` to the functions of the transactional
/// store, see [`check_operations_without_transaction_id_are_forwarded`].
#[test]
fn overriding_stores_forward_operations_without_transaction_id() {
    check_operations_without_transaction_id_are_forwarded::<CountingAbortStore<Stuff>>();
    check_operations_without_transaction_id_are_forwarded::<StoreWithoutValidation<Stuff>>();
    check_operations_without_transaction_id_are_forwarded::<RecordingStore<Stuff>>();
}

/// Checks that the commit of a transaction of the store `S` evaluates the where clauses of its reads once per
/// visible object with validation method 1, which runs every read again, and never with method 2, as no transaction
/// committed meanwhile, so there is no concurrent write to check the reads against.
///
/// ```text
/// t_1
/// begin
/// read a == 1 -> sees A
/// update B
/// commit -> succeeds
/// ```
///
/// t_1 updates B, as validation skips a transaction that wrote nothing.
fn check_commit_evaluates_where_clauses_by_method<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    store.state_mut().validation = validation;
    let counting: Rc<CountingWhereClause> = Rc::new(CountingWhereClause {
        clause: WhereClause::new("a", "==", 1),
        evaluations: Cell::new(0),
    });
    let t_1: u64 = store.begin_transaction();
    assert_eq!(
        store
            .read_objects(t_1, Some(counting.clone()), true)
            .unwrap(),
        [("A".to_string(), Stuff { a: 1, b: 0 })]
    );
    store.update_object("B", Stuff { a: 2, b: 1 }, t_1).unwrap();

    // count only the evaluations of the commit:
    counting.evaluations.set(0);
    assert_eq!(store.commit_transaction(t_1), Ok(()));

    // method 1 reads A and B again; method 2 has nothing to check:
    let expected_evaluations: usize = match validation {
        Validation::BruteForce => 2,
        Validation::WriteSets => 0,
    };
    assert_eq!(counting.evaluations.get(), expected_evaluations);
}

/// The commit of a [`TransactionalKeyValueStore`] with validation method 1 evaluates the where clause of a read once
/// per visible object, see [`check_commit_evaluates_where_clauses_by_method`].
#[test]
fn commit_evaluates_where_clauses_by_method_with_method_1() {
    check_commit_evaluates_where_clauses_by_method::<TransactionalKeyValueStore<Stuff>>(
        Validation::BruteForce,
    );
}

/// The commit of a [`TransactionalKeyValueStore`] with validation method 2 does not evaluate the where clause of a
/// read if no transaction committed meanwhile, see [`check_commit_evaluates_where_clauses_by_method`].
#[test]
fn commit_evaluates_where_clauses_by_method_with_method_2() {
    check_commit_evaluates_where_clauses_by_method::<TransactionalKeyValueStore<Stuff>>(
        Validation::WriteSets,
    );
}

/// Checks that, with validation method 1, a transaction of the store `S` that wrote nothing passes validation
/// without evaluating any where clause, even though another transaction committed a change of the object it read:
/// a transaction without writes skips the validation before method 1 would run its reads again. Run again, the read
/// a == 42 would no longer see A, so method 1 would abort t_1.
///
/// ```text
/// t_1                                 t_2
/// begin
/// read a == 42 -> sees A
///                                     begin
///                                     update A to (43, 0)
///                                     commit
/// commit -> succeeds
/// ```
fn check_read_only_transaction_skips_validation_with_method_1<S>()
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = S::default();
    store.state_mut().validation = Validation::BruteForce;
    store.put("A", Stuff { a: 42, b: 0 }).unwrap();
    let counting: Rc<CountingWhereClause> = Rc::new(CountingWhereClause {
        clause: WhereClause::new("a", "==", 42),
        evaluations: Cell::new(0),
    });

    let t_1: u64 = store.begin_transaction();
    assert_eq!(
        store
            .read_objects(t_1, Some(counting.clone()), true)
            .unwrap(),
        [("A".to_string(), Stuff { a: 42, b: 0 })]
    );

    let t_2: u64 = store.begin_transaction();
    store
        .update_object("A", Stuff { a: 43, b: 0 }, t_2)
        .unwrap();
    store.commit_transaction(t_2).unwrap();

    // count only the evaluations of the commit:
    counting.evaluations.set(0);
    assert_eq!(store.commit_transaction(t_1), Ok(()));
    assert_eq!(counting.evaluations.get(), 0);
    assert_eq!(store.state().committed_transactions_trace, [t_2, t_1]);
}

/// A [`TransactionalKeyValueStore`] with validation method 1 commits a transaction that wrote nothing without
/// running its reads again, see [`check_read_only_transaction_skips_validation_with_method_1`].
#[test]
fn read_only_transaction_skips_validation_with_method_1() {
    check_read_only_transaction_skips_validation_with_method_1::<TransactionalKeyValueStore<Stuff>>(
    );
}

/// With validation method 1, a [`TransactionalKeyValueStore`] checks every read of a transaction at its commit, not
/// only the first or the last one: t_1 reads A, then B, then nothing, and writes; t_2 changes B and commits; the
/// second read of t_1 no longer returns the same result, so t_1 is aborted.
///
/// ```text
/// t_1                                 t_2
/// begin
/// read a == 1 -> sees A
/// read a == 2 -> sees B
/// read a == 3 -> sees nothing
///                                     begin
///                                     update B to (2, 2)
///                                     commit
/// update A
/// commit -> aborted
/// ```
#[test]
fn validation_checks_every_read_with_method_1() {
    let mut store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    store.state_mut().validation = Validation::BruteForce;
    let t_1: u64 = store.begin_transaction();
    assert_eq!(
        store
            .read_objects(t_1, Some(Rc::new(WhereClause::new("a", "==", 1))), true)
            .unwrap(),
        [("A".to_string(), Stuff { a: 1, b: 0 })]
    );
    assert_eq!(
        store
            .read_objects(t_1, Some(Rc::new(WhereClause::new("a", "==", 2))), true)
            .unwrap(),
        [("B".to_string(), Stuff { a: 2, b: 0 })]
    );
    assert_eq!(
        store
            .read_objects(t_1, Some(Rc::new(WhereClause::new("a", "==", 3))), true)
            .unwrap(),
        []
    );

    let t_2: u64 = store.begin_transaction();
    store.update_object("B", Stuff { a: 2, b: 2 }, t_2).unwrap();
    store.commit_transaction(t_2).unwrap();

    store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();
    assert!(matches!(
        store.commit_transaction(t_1),
        Err(StoreError::TransactionAborted(_))
    ));
    assert_eq!(store.state().committed_transactions_trace, [t_2]);
    assert_eq!(get_default(&store, "A"), Ok(&Stuff { a: 1, b: 0 }));
}

/// Checks the commit of a transaction t_1 of the store `S` that read A and wrote, while a transaction t_2 that
/// changed B committed and was aborted afterwards. With validation method 2, the commit returns
/// [`StoreError::TransactionNotFound`] naming t_2, as it needs the write set of t_2, which left the store with the
/// abort; t_1 is neither committed nor aborted. Method 1 does not look at the write sets of other transactions: it
/// runs the read of t_1 again, which still sees only A = (1, 0), so t_1 commits.
///
/// ```text
/// t_1                                 t_2
/// begin
///                                     begin
/// read a == 1 -> sees A
/// update A
///                                     update B
///                                     commit
///                                     abort
/// commit -> succeeds (method 1)
///           TransactionNotFound(t_2) (method 2)
/// ```
fn check_validation_against_aborted_committed_transaction_by_method<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    store.state_mut().validation = validation;
    let t_1: u64 = store.begin_transaction();
    let t_2: u64 = store.begin_transaction();
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    assert_eq!(
        store.read_objects(t_1, Some(where_clause), true).unwrap(),
        [("A".to_string(), Stuff { a: 1, b: 0 })]
    );
    store.update_object("A", Stuff { a: 1, b: 1 }, t_1).unwrap();
    store.update_object("B", Stuff { a: 2, b: 2 }, t_2).unwrap();
    store.commit_transaction(t_2).unwrap();
    store.abort_transaction(t_2);

    match validation {
        Validation::BruteForce => {
            assert_eq!(store.commit_transaction(t_1), Ok(()));
            assert_eq!(store.state().committed_transactions_trace, [t_2, t_1]);
            assert_eq!(get_default(&store, "A"), Ok(&Stuff { a: 1, b: 1 }));
        }
        Validation::WriteSets => {
            assert_eq!(
                store.commit_transaction(t_1),
                Err(StoreError::TransactionNotFound(t_2))
            );
            assert_eq!(store.state().td[&t_1].committed_timestamp, None);
            assert_eq!(
                store.key_value_store()["A"].wip,
                Some(update(t_1, Stuff { a: 1, b: 1 }))
            );
        }
    }
}

/// A [`TransactionalKeyValueStore`] with validation method 1 commits a transaction although a transaction that
/// committed meanwhile was aborted, see [`check_validation_against_aborted_committed_transaction_by_method`].
#[test]
fn validation_against_aborted_committed_transaction_by_method_with_method_1() {
    check_validation_against_aborted_committed_transaction_by_method::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::BruteForce);
}

/// A [`TransactionalKeyValueStore`] with validation method 2 reports a transaction that committed meanwhile and was
/// aborted, see [`check_validation_against_aborted_committed_transaction_by_method`].
#[test]
fn validation_against_aborted_committed_transaction_by_method_with_method_2() {
    check_validation_against_aborted_committed_transaction_by_method::<
        TransactionalKeyValueStore<Stuff>,
    >(Validation::WriteSets);
}

/// Checks the commit of a transaction t_1 of the store `S` that read A and wrote B, after a new object C that matches
/// the read of t_1 was written directly into the store as a committed version valid from 0, in no write set. With
/// validation method 1, t_1 is aborted: its read, run again at the commit, also sees C, so the checksum differs.
/// Method 2 commits t_1: C is in no write set, and no transaction committed while t_1 ran, so there is nothing to
/// check. Through `put` and `bulkload`, such a change cannot happen once a transaction has begun: both then need
/// autocommit and commit C in the write set of a transaction of their own. Only a direct write makes it, as here an
/// insert through `key_value_store_mut`, or a direct call of `load`.
///
/// ```text
/// t_1                                 written directly
/// begin
/// read a == 1 -> sees A
/// update B
///                                     C = (1, 0), valid from 0
/// commit -> aborted (method 1)
///           succeeds (method 2)
/// ```
fn check_direct_write_after_read_by_method<S>(validation: Validation)
where
    S: TransactionalStore<Value = Stuff> + Default,
{
    let mut store: S = store_with_a_and_b();
    store.state_mut().validation = validation;

    // t_1 reads a == 1 and updates B:
    let t_1: u64 = store.begin_transaction();
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    assert_eq!(
        store.read_objects(t_1, Some(where_clause), true).unwrap(),
        [("A".to_string(), Stuff { a: 1, b: 0 })]
    );
    store.update_object("B", Stuff { a: 2, b: 1 }, t_1).unwrap();

    // C, which matches the read of t_1, is written directly into the store:
    store.key_value_store_mut().insert(
        "C".to_string(),
        KvStoreEntry {
            committed: vec![update(0, Stuff { a: 1, b: 0 })],
            wip: None,
        },
    );

    // method 1 aborts t_1 and drops its update of B; method 2 commits it:
    match validation {
        Validation::BruteForce => {
            let result: Result<(), StoreError> = store.commit_transaction(t_1);
            assert!(
                matches!(result, Err(StoreError::TransactionAborted(_))),
                "t_1 must be aborted with validation method 1, got {result:?}"
            );
            assert!(!store.state().td.contains_key(&t_1));
            assert_eq!(store.key_value_store()["B"].wip, None);
            assert_eq!(get_default(&store, "B"), Ok(&Stuff { a: 2, b: 0 }));
        }
        Validation::WriteSets => {
            assert_eq!(store.commit_transaction(t_1), Ok(()));
            assert_eq!(get_default(&store, "B"), Ok(&Stuff { a: 2, b: 1 }));
        }
    }
}

/// A [`TransactionalKeyValueStore`] with validation method 1 aborts a transaction after a change outside all write
/// sets that matches its read, see [`check_direct_write_after_read_by_method`].
#[test]
fn direct_write_after_read_by_method_with_method_1() {
    check_direct_write_after_read_by_method::<TransactionalKeyValueStore<Stuff>>(
        Validation::BruteForce,
    );
}

/// A [`TransactionalKeyValueStore`] with validation method 2 commits a transaction after a change outside all write
/// sets that matches its read, see [`check_direct_write_after_read_by_method`].
#[test]
fn direct_write_after_read_by_method_with_method_2() {
    check_direct_write_after_read_by_method::<TransactionalKeyValueStore<Stuff>>(
        Validation::WriteSets,
    );
}

/// With autocommit, `get` and `delete` of a [`TransactionalKeyValueStore`] return `KeyNotFound` for an object that
/// exists only as the uncommitted insert of an open transaction, as their own transaction does not see it; the open
/// transaction is not affected.
///
/// ```text
/// t_1                                 autocommit
/// begin
/// insert C
///                                     get C -> KeyNotFound
///                                     delete C -> KeyNotFound
/// commit
/// ```
#[test]
fn autocommit_get_and_delete_do_not_see_an_uncommitted_insert() {
    let mut store: TransactionalKeyValueStore<Stuff> =
        TransactionalKeyValueStore::new().with_autocommit(true);

    // t_1 inserts C and stays open:
    let t_1: u64 = store.begin_transaction();
    store.update_object("C", Stuff { a: 3, b: 0 }, t_1).unwrap();

    // get and delete with autocommit do not see C:
    assert_eq!(
        store.get("C"),
        Err(StoreError::KeyNotFound("C".to_string()))
    );
    assert_eq!(
        store.delete("C"),
        Err(StoreError::KeyNotFound("C".to_string()))
    );

    // t_1 is the only open transaction and commits C:
    assert_eq!(store.state.td.keys().copied().collect::<Vec<u64>>(), [t_1]);
    assert_eq!(store.commit_transaction(t_1), Ok(()));
    assert_eq!(get_default(&store, "C"), Ok(&Stuff { a: 3, b: 0 }));
}

/// `read_snapshot` of a [`TransactionalKeyValueStore`] returns a snapshot without a checksum with validation method
/// 2, and with the [`checksum`] of its objects with method 1; a read that selects nothing has the checksum of the
/// empty list.
#[test]
fn read_snapshot_has_checksum_only_with_method_1() {
    let mut store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    let expected_objects: Vec<(String, Stuff)> = vec![
        ("A".to_string(), Stuff { a: 1, b: 0 }),
        ("B".to_string(), Stuff { a: 2, b: 0 }),
    ];
    let nothing: WhereClause = WhereClause::new("a", "==", 42);

    // method 2 (the default):
    assert_eq!(
        store.read_snapshot(1, None, false),
        Ok(Snapshot {
            objects: expected_objects.clone(),
            checksum: None,
        })
    );

    // method 1:
    store.state_mut().validation = Validation::BruteForce;
    assert_eq!(
        store.read_snapshot(1, None, false),
        Ok(Snapshot {
            objects: expected_objects.clone(),
            checksum: Some(checksum(&expected_objects)),
        })
    );
    // the SHA-256 digest of the text "[]":
    assert_eq!(
        store.read_snapshot(1, Some(&nothing), false),
        Ok(Snapshot {
            objects: Vec::new(),
            checksum: Some(
                "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945".to_string()
            ),
        })
    );
}

/// [`checksum`] is the SHA-256 digest of the `Debug` text of the objects, as lowercase hex: the empty list has the
/// digest of the text `[]`, a list with one object the digest of its text, and a change of an object's content, with
/// the same object id, changes the checksum. The expected digests were computed with Python's `hashlib.sha256`;
/// they depend on the `Debug` text of the Rust version pinned in `rust-toolchain.toml`, so a Rust upgrade that
/// changes that text makes this test fail although the store still works.
#[test]
fn checksum_is_sha256_of_debug_text() {
    let empty: Vec<(String, Stuff)> = Vec::new();
    assert_eq!(
        checksum(&empty),
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    );
    // the SHA-256 digest of the text [("A", Stuff { a: 42, b: 0 })]:
    assert_eq!(
        checksum(&[("A".to_string(), Stuff { a: 42, b: 0 })]),
        "e53128abb9f72cfb7eb6f18d8bc50cdded266d1eafe28f1941b1f2172195b7a6"
    );
    assert_ne!(
        checksum(&[("A".to_string(), Stuff { a: 1, b: 0 })]),
        checksum(&[("A".to_string(), Stuff { a: 1, b: 1 })])
    );
}

/// With validation method 1, `read_objects` of a [`TransactionalKeyValueStore`] keeps a read once if the same clause
/// object reads the same committed objects again, but keeps it a second time, with another checksum, once the
/// committed objects it selects changed. Here the change is a new matching object C, written directly into the store
/// as a committed version with start of validity 0, so it is visible to t_1; through the operations of the store,
/// an object committed after t_1 began is not visible to t_1.
///
/// ```text
/// t_1                                 written directly
/// begin
/// read a == 1 -> sees A
/// read a == 1 -> sees A
///                                     C = (1, 0), valid from 0
/// read a == 1 -> sees A and C
/// ```
#[test]
fn read_set_keeps_same_clause_with_other_checksum_with_method_1() {
    let mut store: TransactionalKeyValueStore<Stuff> = store_with_a_and_b();
    store.state_mut().validation = Validation::BruteForce;
    let where_clause: Rc<dyn Clause<Stuff>> = Rc::new(WhereClause::new("a", "==", 1));
    let t_1: u64 = store.begin_transaction();

    // the same clause object twice on the same objects:
    for _ in 0..2 {
        store
            .read_objects(t_1, Some(Rc::clone(&where_clause)), true)
            .unwrap();
    }
    assert_eq!(store.state().td[&t_1].read_clauses.len(), 1);

    // the same clause object once more after C was added:
    store.key_value_store_mut().insert(
        "C".to_string(),
        KvStoreEntry {
            committed: vec![update(0, Stuff { a: 1, b: 0 })],
            wip: None,
        },
    );
    assert_eq!(
        store
            .read_objects(t_1, Some(Rc::clone(&where_clause)), true)
            .unwrap(),
        [
            ("A".to_string(), Stuff { a: 1, b: 0 }),
            ("C".to_string(), Stuff { a: 1, b: 0 }),
        ]
    );
    let read_clauses: &Vec<ReadClause<Stuff>> = &store.state().td[&t_1].read_clauses;
    assert_eq!(read_clauses.len(), 2);
    assert_eq!(
        read_clauses[0].checksum,
        Some(checksum(&[("A".to_string(), Stuff { a: 1, b: 0 })]))
    );
    assert_eq!(
        read_clauses[1].checksum,
        Some(checksum(&[
            ("A".to_string(), Stuff { a: 1, b: 0 }),
            ("C".to_string(), Stuff { a: 1, b: 0 }),
        ]))
    );
}

/// The default validation method is method 2, as in Python, and the stores created without a method use it;
/// `with_validation` sets the given method.
#[test]
fn default_validation_is_method_2_and_with_validation_sets_it() {
    assert_eq!(Validation::default(), Validation::WriteSets);
    assert_eq!(
        TransactionalKeyValueStore::<Stuff>::new().state.validation,
        Validation::WriteSets
    );
    assert_eq!(
        TransactionalKeyValueStore::<Stuff>::default()
            .state
            .validation,
        Validation::WriteSets
    );
    assert_eq!(MvccState::<Stuff>::new().validation, Validation::WriteSets);
    assert_eq!(
        TransactionalKeyValueStore::<Stuff>::with_validation(Validation::BruteForce)
            .state
            .validation,
        Validation::BruteForce
    );
    assert_eq!(
        MvccState::<Stuff>::with_validation(Validation::BruteForce).validation,
        Validation::BruteForce
    );
}

/// The default isolation level is serializable, as in Python, and the stores created without a level use it,
/// whatever their validation method.
#[test]
fn default_isolation_level_is_serializable() {
    assert_eq!(IsolationLevel::default(), IsolationLevel::Serializable);
    assert_eq!(
        TransactionalKeyValueStore::<Stuff>::new()
            .state
            .isolation_level,
        IsolationLevel::Serializable
    );
    assert_eq!(
        TransactionalKeyValueStore::<Stuff>::default()
            .state
            .isolation_level,
        IsolationLevel::Serializable
    );
    assert_eq!(
        TransactionalKeyValueStore::<Stuff>::with_validation(Validation::BruteForce)
            .state
            .isolation_level,
        IsolationLevel::Serializable
    );
    assert_eq!(
        MvccState::<Stuff>::new().isolation_level,
        IsolationLevel::Serializable
    );
    assert_eq!(
        MvccState::<Stuff>::with_validation(Validation::BruteForce).isolation_level,
        IsolationLevel::Serializable
    );
}

/// `with_isolation_level` of the store and of [`MvccState`] accepts the three valid combinations of validation method
/// and isolation level and sets both.
#[test]
fn with_isolation_level_accepts_valid_combinations_and_sets_both() {
    for (validation, isolation_level) in [
        (Validation::BruteForce, IsolationLevel::Serializable),
        (Validation::WriteSets, IsolationLevel::Serializable),
        (Validation::WriteSets, IsolationLevel::SnapshotIsolation),
    ] {
        let case: String = format!("{validation:?}, {isolation_level:?}");
        let store: TransactionalKeyValueStore<Stuff> =
            TransactionalKeyValueStore::with_isolation_level(validation, isolation_level)
                .unwrap_or_else(|error| panic!("{case}: rejected with {error}"));
        assert_eq!(store.state.validation, validation, "{case}");
        assert_eq!(store.state.isolation_level, isolation_level, "{case}");

        let state: MvccState<Stuff> = MvccState::with_isolation_level(validation, isolation_level)
            .unwrap_or_else(|error| panic!("{case}: rejected with {error}"));
        assert_eq!(state.validation, validation, "{case}");
        assert_eq!(state.isolation_level, isolation_level, "{case}");
    }
}

/// `with_isolation_level` of the store and of [`MvccState`] rejects snapshot isolation with validation method 1 with
/// [`StoreError::InvalidConfiguration`], whose text is the message only.
#[test]
fn snapshot_isolation_with_method_1_is_invalid_configuration() {
    let message: &str = "snapshot isolation does not validate reads, so Validation::BruteForce requires \
                         IsolationLevel::Serializable";
    let expected: StoreError = StoreError::InvalidConfiguration(message.to_string());

    assert_eq!(
        TransactionalKeyValueStore::<Stuff>::with_isolation_level(
            Validation::BruteForce,
            IsolationLevel::SnapshotIsolation
        )
        .err(),
        Some(expected.clone())
    );
    assert_eq!(
        MvccState::<Stuff>::with_isolation_level(
            Validation::BruteForce,
            IsolationLevel::SnapshotIsolation
        )
        .err(),
        Some(expected.clone())
    );
    assert_eq!(expected.to_string(), message);
}

/// Autocommit is off by default; `with_autocommit` of the store and of [`MvccState`] switches it on and off again and
/// keeps the validation method and the isolation level set by the constructor.
#[test]
fn with_autocommit_sets_autocommit_and_keeps_validation_and_isolation_level() {
    // off by default:
    assert!(!TransactionalKeyValueStore::<Stuff>::new().state.autocommit);
    assert!(
        !TransactionalKeyValueStore::<Stuff>::default()
            .state
            .autocommit
    );
    assert!(!MvccState::<Stuff>::new().autocommit);

    // with_autocommit after a constructor that sets another validation method or isolation level than the default:
    for (validation, isolation_level) in [
        (Validation::BruteForce, IsolationLevel::Serializable),
        (Validation::WriteSets, IsolationLevel::SnapshotIsolation),
    ] {
        let case: String = format!("{validation:?}, {isolation_level:?}");
        let store: TransactionalKeyValueStore<Stuff> =
            TransactionalKeyValueStore::with_isolation_level(validation, isolation_level)
                .unwrap()
                .with_autocommit(true);
        assert!(store.state.autocommit, "{case}");
        assert_eq!(store.state.validation, validation, "{case}");
        assert_eq!(store.state.isolation_level, isolation_level, "{case}");

        let state: MvccState<Stuff> = MvccState::with_isolation_level(validation, isolation_level)
            .unwrap()
            .with_autocommit(true);
        assert!(state.autocommit, "{case}");
        assert_eq!(state.validation, validation, "{case}");
        assert_eq!(state.isolation_level, isolation_level, "{case}");

        // with_autocommit(false) switches it off again:
        assert!(!store.with_autocommit(false).state.autocommit, "{case}");
        assert!(!state.with_autocommit(false).autocommit, "{case}");
    }
}
