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
//! deduplication of the read set, and stores that override `abort_transaction` or `validate_transaction`. They have
//! no Python counterpart; the ported Python tests are in `test_store_anomalies.rs`.

use std::rc::Rc;

use crate::common::{Stuff, update};
use explaindb::{
    Clause, JournalEntry, KvStoreEntry, MvccState, ReadClause, StoreError,
    TransactionalKeyValueStore, TransactionalStore, VersionedStore, WhereClause,
    abort_transaction_default,
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
/// transaction that committed while the committing transaction ran and was aborted afterwards: the validation needs
/// its write set, which left the store with the abort (Python raises a `KeyError`). The committing transaction is
/// not aborted.
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
/// message only, and `VersionsNotOrdered` also names the object.
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

    // the work-in-progress version of t_2 is gone, the committed version of t_1 stays:
    assert_eq!(store.key_value_store()["A"].wip, None);
    assert_eq!(store.get("A"), Ok(&Stuff { a: 1, b: 1 }));
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
    let read = |where_clause: Option<&Rc<dyn Clause<Stuff>>>, checksum: Option<&str>| ReadClause {
        where_clause: where_clause.map(Rc::clone),
        checksum: checksum.map(str::to_string),
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

impl<V> VersionedStore for CountingAbortStore<V> {
    type Value = V;

    /// See [`VersionedStore::key_value_store`].
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store()
    }

    /// See [`VersionedStore::key_value_store_mut`].
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store_mut()
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

/// A store whose validation always passes and that otherwise behaves like a [`TransactionalKeyValueStore`] (Python:
/// `StoreWithoutValidation` in `system/playground/mvcc_playground.py`, used by
/// `system/tests/stores/test_mvcc_serializability.py`).
///
/// It overrides `validate_transaction`; `commit_transaction` calls the override through the trait.
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

impl<V> VersionedStore for StoreWithoutValidation<V> {
    type Value = V;

    /// See [`VersionedStore::key_value_store`].
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store()
    }

    /// See [`VersionedStore::key_value_store_mut`].
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<V>> {
        self.store.key_value_store_mut()
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
    assert_eq!(store.get("X"), Ok(&Stuff { a: 1, b: 100 }));
    assert_eq!(store.get("Y"), Ok(&Stuff { a: 2, b: 200 }));
}
