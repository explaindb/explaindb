// Code generated from system/stores/MVCC.py, system/interfaces/stores.py, system/stores/VersionedKeyValueStore.py. DO NOT EDIT.
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

//! Multi-version concurrency control transactional key-value store with journaling (Python:
//! `system/stores/MVCC.py`).

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fmt::Write;
use std::rc::Rc;

use indexmap::IndexMap;
use sha2::{Digest, Sha256};

use crate::error::StoreError;
use crate::indexes::indexes::DictionaryIndex;
use crate::query_processing::predicates::Clause;
use crate::stores::versioned_key_value_store::{
    KvStoreEntry, Version, VersionEntry, VersionedStore,
};

/// An entry of the journal; every entry names the transaction that created it (Python: `JournalEntry` and its
/// subclasses).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum JournalEntry<V> {
    /// The start of a transaction (Python: `Begin`).
    Begin {
        /// The transaction id.
        ta_id: u64,
    },
    /// The commit of a transaction (Python: `Commit`).
    Commit {
        /// The transaction id.
        ta_id: u64,
        /// The timestamp at which the transaction committed.
        commit_timestamp: u64,
    },
    /// The abort of a transaction (Python: `Abort`).
    Abort {
        /// The transaction id.
        ta_id: u64,
    },
    /// An update or insert of an object (Python: `Update`, whose field `nev_value` is `new_value` here).
    Update {
        /// The transaction id.
        ta_id: u64,
        /// The object id of the object that was updated.
        object_id: String,
        /// The new value of the object.
        new_value: V,
    },
    /// A delete of an object (Python: `Delete`).
    Delete {
        /// The transaction id.
        ta_id: u64,
        /// The object id of the object that was deleted.
        object_id: String,
    },
}

/// A read of a transaction, kept for its validation: the where clause used and, for validation method 1, the
/// checksum of the result (Python: a `HashableDict` with the keys `where_clause` and `checksum`).
pub struct ReadClause<V> {
    /// The where clause of the read; `None` reads all objects.
    pub where_clause: Option<Rc<dyn Clause<V>>>,
    /// The checksum of the read's result in the committed snapshot of the transaction (without its own changes);
    /// `None` unless validation method 1 is used.
    pub checksum: Option<String>,
}

impl<V> ReadClause<V> {
    /// Returns `true` if this read and `other` used the same clause object (or both none) and have the same
    /// checksum, i.e. if Python's set of read clauses would keep only one of them: Python's clauses compare by
    /// identity.
    pub fn same_as(&self, other: &ReadClause<V>) -> bool {
        let same_clause: bool = match (&self.where_clause, &other.where_clause) {
            (None, None) => true,
            (Some(mine), Some(theirs)) => Rc::ptr_eq(mine, theirs),
            _ => false,
        };
        same_clause && self.checksum == other.checksum
    }
}

impl<V> fmt::Debug for ReadClause<V> {
    /// Shows the clause and the checksum; written by hand so that `V` need not implement `Debug`.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ReadClause")
            .field("where_clause", &self.where_clause)
            .field("checksum", &self.checksum)
            .finish()
    }
}

/// An entry of the transaction dictionary: what the store knows about one transaction (Python: `TDEntry`).
#[derive(Debug)]
pub struct TdEntry<V> {
    /// The reads of the transaction, without duplicates (see [`ReadClause::same_as`]).
    pub read_clauses: Vec<ReadClause<V>>,
    /// The object ids of the objects the transaction modified.
    pub write_set: BTreeSet<String>,
    /// The timestamp when the transaction committed, `None` while it is still ongoing.
    pub committed_timestamp: Option<u64>,
    /// The length of the trace of committed transactions when this transaction began; the transactions from this
    /// position on committed while it ran (Python: `last_committed_TA_index_in_TA_trace`, which is this value
    /// minus 1).
    pub committed_transactions_at_begin: usize,
}

/// The result of a read of all objects matching a where clause in a snapshot (Python: the pair returned by
/// `_read_snapshot`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Snapshot<V> {
    /// The `(object_id, object)` pairs, in the order of the store.
    pub objects: Vec<(String, V)>,
    /// The checksum of the objects; `None` unless validation method 1 is used.
    pub checksum: Option<String>,
}

/// The method a transactional store uses to validate a transaction at its commit (Python: the flag
/// `use_brute_force_validation`). It only applies to the isolation level serializable (see [`IsolationLevel`]).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Validation {
    /// Method 1, brute force: each read keeps a checksum of its result in the committed snapshot of the
    /// transaction; at commit, every read is run again at the commit timestamp and its checksum compared (Python:
    /// `use_brute_force_validation=True`).
    BruteForce,
    /// Method 2: the objects written by the transactions that committed meanwhile are checked against the reads
    /// (Python: `use_brute_force_validation=False`, the default).
    #[default]
    WriteSets,
}

/// The isolation level of a transactional store (Python: the type `IsolationLevel` and the parameter
/// `isolation_level`). In both levels, a transaction reads the snapshot of its begin plus its own writes (snapshot
/// read), and a transaction that writes an object which another transaction is still writing is aborted.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum IsolationLevel {
    /// At its commit, the store checks whether a transaction that committed in the meantime changed something this
    /// transaction read; if so, it is aborted (see [`Validation`]). The write skew anomaly is detected and avoided
    /// (Python: `"serializable"`, the default).
    #[default]
    Serializable,
    /// Reads are not checked. Instead, a transaction that writes an object is aborted at once if another
    /// transaction changed that object and committed after the writer began. Together with the rule above, of two
    /// concurrent transactions that write the same object, the later writer is aborted at once (first updater
    /// wins). Lost updates cannot happen, but write skew can (Python: `"snapshot isolation"`).
    SnapshotIsolation,
}

/// Returns the checksum of a read result: the SHA-256 digest of its `Debug` text, as lowercase hex (Python: the
/// SHA-256 digest of its `repr`).
///
/// The checksum changes whenever the text changes. So the `Debug` text of a value must show its full content: a
/// value type whose `Debug` hides fields (e.g. with `finish_non_exhaustive`) can hide a change, and validation
/// method 1 would then pass where it should abort. Equal content with different text (e.g. `-0.0` and `0.0`, or
/// a `HashMap` printed in another order) only causes unnecessary aborts. `Debug` output may differ between Rust
/// versions, which does not matter, as checksums are only compared within one process.
pub fn checksum<V: fmt::Debug>(objects: &[(String, V)]) -> String {
    // the 32 bytes of the SHA-256 digest:
    let digest = Sha256::digest(format!("{objects:?}").as_bytes());
    let mut hex: String = String::with_capacity(2 * digest.len());
    for byte in digest.iter() {
        write!(hex, "{byte:02x}").expect("writing to a String does not fail");
    }
    hex
}

/// The state of a transactional store: the versions of all objects, the journal, the transaction dictionary and
/// the trace of the committed transactions (Python: the attributes of `TransactionalKeyValueStore`).
#[derive(Debug)]
pub struct MvccState<V> {
    /// The mapping from object id to the versions of the object, see [`crate::VersionedKeyValueStore`].
    pub key_value_store: IndexMap<String, KvStoreEntry<V>>,
    /// The journal (aka redo log): for each transaction id, its journal entries in order.
    pub journal: DictionaryIndex<u64, JournalEntry<V>>,
    /// The transaction id counter: the next transaction id or commit timestamp to hand out; starts at 1 (Python:
    /// `TA_id`).
    pub ta_id: u64,
    /// The transaction dictionary, mapping a transaction id to what the store knows about the transaction (Python:
    /// `TD`). A transaction stays in it after its commit and leaves it when it is aborted.
    pub td: BTreeMap<u64, TdEntry<V>>,
    /// The ids of the committed transactions, in the order they committed.
    pub committed_transactions_trace: Vec<u64>,
    /// The validation method. Changing it to method 1 while transactions run makes method 1 abort those of them
    /// that wrote something and kept a read from before the change, as such a read carries no checksum; changing
    /// it to method 2 causes no extra aborts.
    pub validation: Validation,
    /// The isolation level. Changing it to snapshot isolation while transactions run stops validating their reads
    /// at once; if validation method 1 was set by hand, snapshot isolation only computes checksums nobody uses.
    pub isolation_level: IsolationLevel,
}

impl<V> MvccState<V> {
    /// Creates the state of an empty serializable store with validation method 2; the first transaction id is 1.
    pub fn new() -> MvccState<V> {
        MvccState::with_validation(Validation::WriteSets)
    }

    /// Creates the state of an empty serializable store with the validation method `validation`; the first
    /// transaction id is 1.
    pub fn with_validation(validation: Validation) -> MvccState<V> {
        MvccState {
            key_value_store: IndexMap::new(),
            journal: DictionaryIndex::new(),
            ta_id: 1,
            td: BTreeMap::new(),
            committed_transactions_trace: Vec::new(),
            validation,
            isolation_level: IsolationLevel::Serializable,
        }
    }

    /// Creates the state of an empty store with the validation method `validation` and the isolation level
    /// `isolation_level`; the first transaction id is 1 (Python: the checks of `TransactionalKeyValueStore.__init__`).
    ///
    /// # Errors
    ///
    /// [`StoreError::InvalidConfiguration`] for snapshot isolation with validation method 1, as snapshot isolation
    /// does not validate reads (Python: `ValueError`; Python's error for an unknown level cannot occur, as
    /// [`IsolationLevel`] has only the two levels).
    pub fn with_isolation_level(
        validation: Validation,
        isolation_level: IsolationLevel,
    ) -> Result<MvccState<V>, StoreError> {
        if isolation_level == IsolationLevel::SnapshotIsolation
            && validation == Validation::BruteForce
        {
            return Err(StoreError::InvalidConfiguration(
                "snapshot isolation does not validate reads, so Validation::BruteForce requires \
                 IsolationLevel::Serializable"
                    .to_string(),
            ));
        }
        Ok(MvccState {
            isolation_level,
            ..MvccState::with_validation(validation)
        })
    }

    /// Gets the version of object `object_id` visible at `timestamp` under snapshot isolation (Python:
    /// `_get_visible_object_version`). The timestamp is the id of the reading transaction or a commit timestamp.
    ///
    /// This is the work-in-progress version written by the transaction with id `timestamp`, if it has one and
    /// `ignore_wip` is not set; otherwise the most recent committed version whose validity started before
    /// `timestamp`. Returns `None` if that version is a delete marker or if the object did not exist yet in this
    /// snapshot.
    ///
    /// # Errors
    ///
    /// - [`StoreError::KeyNotFound`] if the object id is not in the store (Python: `KeyError`);
    /// - [`StoreError::VersionsNotOrdered`] if the committed versions are not ordered by the start of their
    ///   validity (Python: `RuntimeError`).
    pub fn get_visible_object_version(
        &self,
        object_id: &str,
        timestamp: u64,
        ignore_wip: bool,
    ) -> Result<Option<&V>, StoreError> {
        let entry: &KvStoreEntry<V> = self
            .key_value_store
            .get(object_id)
            .ok_or_else(|| StoreError::KeyNotFound(object_id.to_string()))?;

        // does this transaction have a wip entry for this object? (a wip entry of another transaction is not
        // visible)
        if !ignore_wip
            && let Some(wip) = &entry.wip
            && wip.start_validity == timestamp
        {
            // the version being modified by this transaction (or None if it deletes the object):
            return Ok(match &wip.version {
                Version::Update(value) => Some(value),
                Version::Delete => None,
            });
        }

        // no committed version at all, e.g. the object is being inserted by a transaction or its insert was
        // aborted: the object does not exist in this snapshot
        if entry.committed.is_empty() {
            return Ok(None);
        }

        // the committed versions must be ordered by their commit timestamps:
        if entry
            .committed
            .windows(2)
            .any(|pair| pair[0].start_validity >= pair[1].start_validity)
        {
            return Err(StoreError::VersionsNotOrdered(object_id.to_string()));
        }

        // the most recent version that was committed (not started!) before this snapshot; delete markers count
        // as versions, too:
        let visible: Option<&VersionEntry<V>> = entry
            .committed
            .iter()
            .rev()
            .find(|version| version.start_validity < timestamp);

        Ok(match visible {
            // all committed versions are more recent than this snapshot: the object does not exist in it
            None => None,
            Some(VersionEntry {
                version: Version::Delete,
                ..
            }) => None,
            Some(VersionEntry {
                version: Version::Update(value),
                ..
            }) => Some(value),
        })
    }

    /// Returns all `(object_id, object)` pairs visible at `timestamp` that match `where_clause` (all objects if it
    /// is `None`), in the order of the store (Python: `_read_snapshot` and `_read_objects_iterable`).
    ///
    /// The where clause is evaluated once per visible object. With validation method 1, the snapshot also carries
    /// the [`checksum`] of the objects; with method 2, its checksum is `None`.
    ///
    /// # Errors
    ///
    /// The errors of [`MvccState::get_visible_object_version`].
    ///
    /// # Panics
    ///
    /// If the where clause panics, e.g. a [`crate::WhereClause`] on an object without its attribute (Python:
    /// `AttributeError`).
    pub fn read_snapshot(
        &self,
        timestamp: u64,
        where_clause: Option<&dyn Clause<V>>,
        ignore_wip: bool,
    ) -> Result<Snapshot<V>, StoreError>
    where
        V: Clone + fmt::Debug,
    {
        let mut objects: Vec<(String, V)> = Vec::new();
        for object_id in self.key_value_store.keys() {
            if let Some(object) =
                self.get_visible_object_version(object_id, timestamp, ignore_wip)?
                && selected(where_clause, Some(object))
            {
                objects.push((object_id.clone(), object.clone()));
            }
        }
        // a checksum only for validation method 1, which needs it:
        let objects_checksum: Option<String> = match self.validation {
            Validation::BruteForce => Some(checksum(&objects)),
            Validation::WriteSets => None,
        };
        Ok(Snapshot {
            objects,
            checksum: objects_checksum,
        })
    }

    /// Adds `read_clause` to the reads of transaction `ta_id`, unless the same read is there already (see
    /// [`ReadClause::same_as`]).
    ///
    /// # Panics
    ///
    /// If the transaction is not in the transaction dictionary (Python raises a `KeyError`; through
    /// [`read_objects_default`], which checks the transaction first, this cannot happen).
    pub fn add_read_clause(&mut self, ta_id: u64, read_clause: ReadClause<V>) {
        let Some(td_entry) = self.td.get_mut(&ta_id) else {
            missing_transaction(ta_id)
        };
        let read_clauses: &mut Vec<ReadClause<V>> = &mut td_entry.read_clauses;
        if !read_clauses.iter().any(|known| known.same_as(&read_clause)) {
            read_clauses.push(read_clause);
        }
    }
}

impl<V> Default for MvccState<V> {
    /// Creates the state of an empty store, see [`MvccState::new`].
    fn default() -> Self {
        MvccState::new()
    }
}

/// Stops the program because transaction `ta_id` is not in the transaction dictionary (Python: `assert` or
/// `KeyError` where this is a programming error).
fn missing_transaction(ta_id: u64) -> ! {
    panic!("transaction {ta_id} not found in the system")
}

/// Returns `true` if `object` is returned by a read with `where_clause` (Python: the local function `selected` of
/// `_validate_transaction`): a missing object (not existing or deleted, i.e. `None`) is never returned; a read
/// without a where clause returns every existing object.
fn selected<V>(where_clause: Option<&dyn Clause<V>>, object: Option<&V>) -> bool {
    match (where_clause, object) {
        (_, None) => false,
        (None, Some(_)) => true,
        (Some(clause), Some(object)) => clause.evaluate(object),
    }
}

/// A fully transactional versioned key-value store: a transaction may change any number of objects (Python:
/// `TransactionalKeyValueStore`, formerly known as `MVCCStore`).
///
/// The store supports two isolation levels, see [`IsolationLevel`]. In both, a transaction reads the snapshot of its
/// begin plus its own writes (snapshot read; older comments in this file that say "under snapshot isolation" for
/// reading, e.g. at [`MvccState::get_visible_object_version`], mean this snapshot read, which both levels use). In
/// both, a transaction that writes an object which another transaction is still writing (not yet committed) is
/// aborted. In addition:
///
/// - serializable (default): at its commit, a validation phase checks whether a transaction that committed in the
///   meantime changed something this transaction read, and aborts it on a conflict (see [`Validation`] for the two
///   methods). The write skew anomaly is detected and avoided.
/// - snapshot isolation: reads are not checked. Instead, a transaction that writes an object is aborted at once if
///   another transaction changed that object and committed after the writer began. Together with the rule above,
///   of two concurrent transactions that write the same object, the later writer is aborted at once (first updater
///   wins). Lost updates cannot happen, but write skew can.
///
/// Note: a blind write (one that does not read the object first) to an object that another transaction changed and
/// committed since the writer began is aborted under snapshot isolation, but can commit under serializable. The
/// tutorial page "MVCC & Versioned Stores" explains write skew and shows both schedules.
///
/// Python's subclasses inherit the implementation; in Rust it lives in the default methods of this trait, and a
/// store only gives access to its [`MvccState`], whose `key_value_store` must be the map that
/// [`VersionedStore::key_value_store`] returns.
///
/// A store that changes `begin_transaction`, `read_objects`, `update_object`, `delete_object`,
/// `validate_transaction`, `commit_transaction` or `abort_transaction` overrides it and can call the original
/// through the free function `*_default` of the same name, e.g. [`abort_transaction_default`]. These functions
/// call the other methods of this trait through the trait, as Python's `self.` does, so an override of one of them
/// is used by the others; `read_objects` and validation also read through the trait methods `read_snapshot` and
/// `get_visible_object_version`.
///
/// The reads themselves (`read_snapshot` calling `get_visible_object_version`) go through [`MvccState`], so an
/// override of only `get_visible_object_version` is not seen by `read_snapshot`; no store overrides them in
/// Python.
///
/// The non-transactional [`VersionedStore::delete`] appends a delete marker valid from timestamp 0, as in Python;
/// on an object with a committed version, later transactional reads of that object's committed versions then fail
/// with [`StoreError::VersionsNotOrdered`] (a read checks every object of the store).
pub trait TransactionalStore: VersionedStore<Value: Clone + PartialEq + fmt::Debug> {
    /// Returns the state of the store.
    fn state(&self) -> &MvccState<Self::Value>;

    /// Returns the state of the store, for changing it.
    fn state_mut(&mut self) -> &mut MvccState<Self::Value>;

    /// See [`MvccState::get_visible_object_version`].
    ///
    /// # Errors
    ///
    /// See [`MvccState::get_visible_object_version`].
    fn get_visible_object_version(
        &self,
        object_id: &str,
        timestamp: u64,
        ignore_wip: bool,
    ) -> Result<Option<&Self::Value>, StoreError> {
        self.state()
            .get_visible_object_version(object_id, timestamp, ignore_wip)
    }

    /// See [`MvccState::read_snapshot`].
    ///
    /// # Errors
    ///
    /// See [`MvccState::read_snapshot`].
    ///
    /// # Panics
    ///
    /// See [`MvccState::read_snapshot`].
    fn read_snapshot(
        &self,
        timestamp: u64,
        where_clause: Option<&dyn Clause<Self::Value>>,
        ignore_wip: bool,
    ) -> Result<Snapshot<Self::Value>, StoreError> {
        self.state()
            .read_snapshot(timestamp, where_clause, ignore_wip)
    }

    /// Returns the next transaction id (also used as commit timestamp) and advances the counter (Python:
    /// `_get_next_TA_id`).
    fn next_ta_id(&mut self) -> u64 {
        let state: &mut MvccState<Self::Value> = self.state_mut();
        let next_ta_id: u64 = state.ta_id;
        state.ta_id += 1;
        next_ta_id
    }

    /// Begins a new transaction and returns its id, see [`begin_transaction_default`].
    fn begin_transaction(&mut self) -> u64 {
        begin_transaction_default(self)
    }

    /// Returns all objects visible to transaction `ta_id` that match `where_clause`, see
    /// [`read_objects_default`].
    ///
    /// # Errors
    ///
    /// See [`read_objects_default`].
    ///
    /// # Panics
    ///
    /// See [`read_objects_default`].
    fn read_objects(
        &mut self,
        ta_id: u64,
        where_clause: Option<Rc<dyn Clause<Self::Value>>>,
        collect_read_clause: bool,
    ) -> Result<Vec<(String, Self::Value)>, StoreError> {
        read_objects_default(self, ta_id, where_clause, collect_read_clause)
    }

    /// Updates or inserts object `object_id` in transaction `ta_id`, see [`update_object_default`].
    ///
    /// # Errors
    ///
    /// See [`update_object_default`].
    fn update_object(
        &mut self,
        object_id: &str,
        updated_object: Self::Value,
        ta_id: u64,
    ) -> Result<(), StoreError> {
        update_object_default(self, object_id, updated_object, ta_id)
    }

    /// Deletes object `object_id` in transaction `ta_id`, see [`delete_object_default`].
    ///
    /// # Errors
    ///
    /// See [`delete_object_default`].
    ///
    /// # Panics
    ///
    /// See [`delete_object_default`].
    fn delete_object(&mut self, object_id: &str, ta_id: u64) -> Result<(), StoreError> {
        delete_object_default(self, object_id, ta_id)
    }

    /// Validates transaction `ta_id` against the transactions that committed after it began, see
    /// [`validate_transaction_default`].
    ///
    /// # Errors
    ///
    /// See [`validate_transaction_default`].
    ///
    /// # Panics
    ///
    /// See [`validate_transaction_default`].
    fn validate_transaction(&self, ta_id: u64, commit_timestamp: u64) -> Result<bool, StoreError> {
        validate_transaction_default(self, ta_id, commit_timestamp)
    }

    /// Commits transaction `ta_id`, see [`commit_transaction_default`].
    ///
    /// # Errors
    ///
    /// See [`commit_transaction_default`].
    ///
    /// # Panics
    ///
    /// See [`commit_transaction_default`].
    fn commit_transaction(&mut self, ta_id: u64) -> Result<(), StoreError> {
        commit_transaction_default(self, ta_id)
    }

    /// Aborts transaction `ta_id`, see [`abort_transaction_default`].
    ///
    /// # Panics
    ///
    /// See [`abort_transaction_default`].
    fn abort_transaction(&mut self, ta_id: u64) {
        abort_transaction_default(self, ta_id)
    }

    /// Shows the transaction dictionary: pretty-prints it with `Debug`. Python's `pprint` stops at depth 3; this
    /// prints all levels.
    fn show_transaction_dictionary(&self) {
        println!("Transaction dictionary:");
        println!("{:#?}", self.state().td);
    }
}

/// Begins a new transaction and returns its id: writes a [`JournalEntry::Begin`] and adds the transaction to the
/// transaction dictionary (Python: `begin_transaction`).
pub fn begin_transaction_default<S: TransactionalStore + ?Sized>(store: &mut S) -> u64 {
    // obtain the next transaction id:
    let next_ta_id: u64 = store.next_ta_id();
    let state: &mut MvccState<S::Value> = store.state_mut();

    // append the Begin entry to the journal:
    state
        .journal
        .put(next_ta_id, JournalEntry::Begin { ta_id: next_ta_id });

    // create a new entry for this transaction in the transaction dictionary:
    let committed_transactions_at_begin: usize = state.committed_transactions_trace.len();
    state.td.insert(
        next_ta_id,
        TdEntry {
            read_clauses: Vec::new(),
            write_set: BTreeSet::new(),
            committed_timestamp: None,
            committed_transactions_at_begin,
        },
    );
    next_ta_id
}

/// Returns all objects visible to transaction `ta_id` (its snapshot plus its own changes) that match
/// `where_clause`, as owned copies, and adds the read to the transaction's reads unless `collect_read_clause` is
/// `false` (Python: `read_objects`).
///
/// With validation method 1, the read also gets a checksum, computed over the committed snapshot of `ta_id`
/// (without its own changes) by a first read; so the where clause is evaluated once per visible object in each of
/// the two reads, as in Python.
///
/// # Errors
///
/// - [`StoreError::TransactionNotFound`] if the transaction is not in the transaction dictionary (Python:
///   `KeyError`);
/// - [`StoreError::AlreadyCommitted`] if the transaction has committed (Python: `RuntimeError`);
/// - the errors of [`MvccState::get_visible_object_version`].
///
/// # Panics
///
/// If the where clause panics, e.g. a [`crate::WhereClause`] on an object without its attribute (Python:
/// `AttributeError`).
pub fn read_objects_default<S: TransactionalStore + ?Sized>(
    store: &mut S,
    ta_id: u64,
    where_clause: Option<Rc<dyn Clause<S::Value>>>,
    collect_read_clause: bool,
) -> Result<Vec<(String, S::Value)>, StoreError> {
    let state: &MvccState<S::Value> = store.state();
    let td_entry: &TdEntry<S::Value> = state
        .td
        .get(&ta_id)
        .ok_or(StoreError::TransactionNotFound(ta_id))?;
    if td_entry.committed_timestamp.is_some() {
        return Err(StoreError::AlreadyCommitted(ta_id));
    }

    // only validation method 1 uses a checksum; it is computed over the committed snapshot, i.e. without the wip
    // entries of transaction ta_id:
    let read_checksum: Option<String> = match state.validation {
        Validation::BruteForce => {
            store
                .read_snapshot(ta_id, where_clause.as_deref(), true)?
                .checksum
        }
        Validation::WriteSets => None,
    };

    // the returned list includes the wip entries of transaction ta_id:
    let snapshot: Snapshot<S::Value> =
        store.read_snapshot(ta_id, where_clause.as_deref(), false)?;

    if collect_read_clause {
        store.state_mut().add_read_clause(
            ta_id,
            ReadClause {
                where_clause,
                checksum: read_checksum,
            },
        );
    }
    Ok(snapshot.objects)
}

/// Updates (or inserts) object `object_id` to `updated_object` in transaction `ta_id` (Python: `update_object`).
///
/// Writes a [`JournalEntry::Update`], stores the object as the work-in-progress version of the object and adds the
/// object id to the transaction's write set. Under the isolation level snapshot isolation, also aborts the
/// transaction if another transaction changed the object and committed after the transaction began.
///
/// # Errors
///
/// - [`StoreError::TransactionNotFound`] if the transaction is not in the transaction dictionary (Python:
///   `KeyError`);
/// - [`StoreError::AlreadyCommitted`] if the transaction has committed (Python: `RuntimeError`);
/// - [`StoreError::TransactionAborted`] if another transaction holds a work-in-progress version of the object, or,
///   under snapshot isolation, if another transaction committed the object after this transaction began; the
///   transaction is aborted first, through [`TransactionalStore::abort_transaction`].
pub fn update_object_default<S: TransactionalStore + ?Sized>(
    store: &mut S,
    object_id: &str,
    updated_object: S::Value,
    ta_id: u64,
) -> Result<(), StoreError> {
    let state: &MvccState<S::Value> = store.state();
    let td_entry: &TdEntry<S::Value> = state
        .td
        .get(&ta_id)
        .ok_or(StoreError::TransactionNotFound(ta_id))?;
    if td_entry.committed_timestamp.is_some() {
        return Err(StoreError::AlreadyCommitted(ta_id));
    }

    // no other writer on this object is allowed:
    if written_by_other_transaction(state, object_id, ta_id) {
        store.abort_transaction(ta_id);
        return Err(StoreError::TransactionAborted(format!(
            "another transaction is currently modifying object {object_id} already"
        )));
    }

    // under snapshot isolation, no other transaction may have committed the object since ta_id began:
    abort_if_committed_after_begin(store, object_id, ta_id)?;

    let state: &mut MvccState<S::Value> = store.state_mut();

    // 1. write to the journal:
    state.journal.put(
        ta_id,
        JournalEntry::Update {
            ta_id,
            object_id: object_id.to_string(),
            new_value: updated_object.clone(),
        },
    );

    // 2. now update the actual store, append-only: the committed versions stay untouched, as other
    // transactions may still read them
    let new_entry: VersionEntry<S::Value> = VersionEntry {
        start_validity: ta_id,
        version: Version::Update(updated_object),
    };
    match state.key_value_store.get_mut(object_id) {
        // update of an existing object:
        Some(entry) => entry.wip = Some(new_entry),
        // insert of a new object:
        None => {
            state.key_value_store.insert(
                object_id.to_string(),
                KvStoreEntry {
                    committed: Vec::new(),
                    wip: Some(new_entry),
                },
            );
        }
    }

    // collect the object id for the validation phase (the transaction is in the dictionary, see above):
    if let Some(td_entry) = state.td.get_mut(&ta_id) {
        td_entry.write_set.insert(object_id.to_string());
    }
    Ok(())
}

/// Deletes object `object_id` in transaction `ta_id` (Python: `delete_object`).
///
/// Writes a [`JournalEntry::Delete`], adds a delete marker as the work-in-progress version of the object and adds
/// the object id to the transaction's write set. Under the isolation level snapshot isolation, also aborts the
/// transaction if another transaction changed the object and committed after the transaction began.
///
/// # Errors
///
/// - [`StoreError::AlreadyCommitted`] if the transaction has committed (Python: `RuntimeError`);
/// - [`StoreError::KeyNotFound`] if the object id is not in the store (Python: `KeyError`);
/// - [`StoreError::TransactionAborted`] if another transaction holds a work-in-progress version of the object, or,
///   under snapshot isolation, if another transaction committed the object after this transaction began; the
///   transaction is aborted first, through [`TransactionalStore::abort_transaction`].
///
/// # Panics
///
/// If the transaction is not in the transaction dictionary (Python: `assert`).
pub fn delete_object_default<S: TransactionalStore + ?Sized>(
    store: &mut S,
    object_id: &str,
    ta_id: u64,
) -> Result<(), StoreError> {
    let state: &MvccState<S::Value> = store.state();
    let Some(td_entry) = state.td.get(&ta_id) else {
        missing_transaction(ta_id)
    };
    if td_entry.committed_timestamp.is_some() {
        return Err(StoreError::AlreadyCommitted(ta_id));
    }
    if !state.key_value_store.contains_key(object_id) {
        return Err(StoreError::KeyNotFound(object_id.to_string()));
    }

    // no other writer on this object is allowed:
    if written_by_other_transaction(state, object_id, ta_id) {
        store.abort_transaction(ta_id);
        return Err(StoreError::TransactionAborted(format!(
            "another transaction is currently modifying object {object_id} already"
        )));
    }

    // under snapshot isolation, no other transaction may have committed the object since ta_id began:
    abort_if_committed_after_begin(store, object_id, ta_id)?;

    let state: &mut MvccState<S::Value> = store.state_mut();

    // 1. write to the journal:
    state.journal.put(
        ta_id,
        JournalEntry::Delete {
            ta_id,
            object_id: object_id.to_string(),
        },
    );

    // 2. now update the store: a delete marker as wip entry (the object is in the store, see above)
    if let Some(entry) = state.key_value_store.get_mut(object_id) {
        entry.wip = Some(VersionEntry {
            start_validity: ta_id,
            version: Version::Delete,
        });
    }

    // collect the object id for the validation phase (the transaction is in the dictionary, see above):
    if let Some(td_entry) = state.td.get_mut(&ta_id) {
        td_entry.write_set.insert(object_id.to_string());
    }
    Ok(())
}

/// Returns `true` if a transaction other than `ta_id` holds a work-in-progress version of object `object_id`.
fn written_by_other_transaction<V>(state: &MvccState<V>, object_id: &str, ta_id: u64) -> bool {
    state
        .key_value_store
        .get(object_id)
        .and_then(|entry| entry.wip.as_ref())
        .is_some_and(|wip| wip.start_validity != ta_id)
}

/// Returns `true` if another transaction committed a version of object `object_id` after transaction `ta_id` began
/// (Python: `_committed_after_begin`). Returns `false` if the object is not in the store or has no committed version.
fn committed_after_begin<V>(state: &MvccState<V>, object_id: &str, ta_id: u64) -> bool {
    state
        .key_value_store
        .get(object_id)
        .and_then(|entry| entry.committed.last())
        // transaction ids and commit timestamps come from the same counter (non-transactional writes use 0), so a
        // larger timestamp means "committed after ta_id began":
        .is_some_and(|newest| newest.start_validity > ta_id)
}

/// Under snapshot isolation, aborts transaction `ta_id` if another transaction committed object `object_id` after
/// `ta_id` began (Python: `_abort_if_committed_after_begin`); does nothing under serializable.
///
/// Snapshot isolation does not validate reads, so it cannot tell whether `ta_id` read the object; to rule out lost
/// updates, it aborts every write to an object committed after `ta_id` began, even a blind one.
///
/// # Errors
///
/// [`StoreError::TransactionAborted`] after aborting the transaction through
/// [`TransactionalStore::abort_transaction`].
fn abort_if_committed_after_begin<S: TransactionalStore + ?Sized>(
    store: &mut S,
    object_id: &str,
    ta_id: u64,
) -> Result<(), StoreError> {
    let state: &MvccState<S::Value> = store.state();
    if state.isolation_level == IsolationLevel::SnapshotIsolation
        && committed_after_begin(state, object_id, ta_id)
    {
        store.abort_transaction(ta_id);
        return Err(StoreError::TransactionAborted(format!(
            "transaction {ta_id} aborted under snapshot isolation: another transaction changed object \
             {object_id} and committed after transaction {ta_id} began"
        )));
    }
    Ok(())
}

/// Validates transaction `ta_id` at `commit_timestamp` and returns `true` if there is no conflict (Python:
/// `_validate_transaction`).
///
/// Under the isolation level snapshot isolation, always passes, as reads are not validated (conflicting writes are
/// refused in `update_object` / `delete_object`). Otherwise, a transaction that wrote nothing always passes, and the
/// others are validated by the store's [`Validation`]:
///
/// - Method 1 (brute force): each read of `ta_id` is run again at `commit_timestamp`; if the checksum of its result
///   differs from the one kept at the read, the validation fails. Method 1 does not look at the write sets of other
///   transactions.
/// - Method 2 (write sets): the write sets of the transactions that committed meanwhile are combined; for each
///   object of the combined write set and each read of `ta_id`, the version of the object in the snapshot of `ta_id`
///   (without its own changes) is compared with the version at `commit_timestamp`; if they differ and either is
///   selected by the read's where clause, the validation fails.
///
/// Method 2 follows the paper: "Our variation of precision locking tests discrete writes (updates, deletions, and
/// insertions of records) of recently committed transactions against predicate-oriented reads of the transaction
/// that is being validated" [Neumann et al., Fast Serializable Multi-Version Concurrency Control for Main-Memory
/// Database Systems].
///
/// # Errors
///
/// - method 1: the errors of [`TransactionalStore::read_snapshot`];
/// - method 2: [`StoreError::TransactionNotFound`] for a transaction that committed meanwhile and was aborted
///   afterwards, so that it is no longer in the transaction dictionary (Python: `KeyError`), and the errors of
///   [`TransactionalStore::get_visible_object_version`].
///
/// # Panics
///
/// - If the transaction `ta_id` is not in the transaction dictionary under serializable (Python raises a
///   `KeyError`; under snapshot isolation, both return `true` without looking it up); through
///   [`commit_transaction_default`], which checks the transaction first, this cannot happen.
/// - If a where clause panics, e.g. a [`crate::WhereClause`] on an object without its attribute (Python:
///   `AttributeError`).
pub fn validate_transaction_default<S: TransactionalStore + ?Sized>(
    store: &S,
    ta_id: u64,
    commit_timestamp: u64,
) -> Result<bool, StoreError> {
    let state: &MvccState<S::Value> = store.state();

    // snapshot isolation does not validate reads (write skew can happen):
    if state.isolation_level == IsolationLevel::SnapshotIsolation {
        return Ok(true);
    }

    let Some(td_entry) = state.td.get(&ta_id) else {
        missing_transaction(ta_id)
    };

    // read-only transactions always pass validation:
    if td_entry.write_set.is_empty() {
        return Ok(true);
    }

    if state.validation == Validation::BruteForce {
        // method 1 (brute force): run each read of ta_id again, against the current committed state of the store
        // rather than the snapshot of ta_id, and compare the checksums. Equal checksums mean the read returns the
        // same objects with the same contents as before. Comparing only the object ids would not do, as the
        // contents may have changed.
        //
        // Per object, compared to what ta_id read (the cases of Python's comment):
        // 1.     not modified by another transaction meanwhile: no conflict;
        // 2a.    modified, but selected neither before nor now: no conflict, ta_id never saw it;
        // 2b.i.  modified, selected before and now: conflict if its content changed (unchanged content gives the
        //        same checksum and passes);
        // 2b.ii. modified, selected before but not now (updated or deleted): conflict;
        // 2c.    modified, not selected before but now: conflict (phantom or non-repeatable read).
        // Every conflict changes the checksum: an object appears, disappears or changes its content in the result.
        for read_clause in &td_entry.read_clauses {
            // ignore_wip is false, as in Python (its default): at a new commit timestamp, no work-in-progress
            // version can be visible anyway
            let now: Snapshot<S::Value> = store.read_snapshot(
                commit_timestamp,
                read_clause.where_clause.as_deref(),
                false,
            )?;
            if now.checksum != read_clause.checksum {
                return Ok(false);
            }
        }
        return Ok(true);
    }

    // method 2 (write sets):
    // 1. combine the write sets of all transactions that committed after ta_id began (a committed transaction
    // that was aborted afterwards is no longer in the dictionary: Python raises a KeyError there):
    let mut combined_write_set: BTreeSet<&String> = BTreeSet::new();
    for other in &state.committed_transactions_trace[td_entry.committed_transactions_at_begin..] {
        let other_entry: &TdEntry<S::Value> = state
            .td
            .get(other)
            .ok_or(StoreError::TransactionNotFound(*other))?;
        combined_write_set.extend(other_entry.write_set.iter());
    }

    // no concurrent writes, no conflict:
    if combined_write_set.is_empty() {
        return Ok(true);
    }

    // 2. check the combined write set against each read of ta_id:
    for read_clause in &td_entry.read_clauses {
        let where_clause: Option<&dyn Clause<S::Value>> = read_clause.where_clause.as_deref();
        for object_id in &combined_write_set {
            // the version ta_id read (without its own wip entry) and the version now:
            let as_of_ta_id: Option<&S::Value> =
                store.get_visible_object_version(object_id, ta_id, true)?;
            let as_of_now: Option<&S::Value> =
                store.get_visible_object_version(object_id, commit_timestamp, true)?;
            if as_of_now == as_of_ta_id {
                // no conflict
                continue;
            }
            if selected(where_clause, as_of_ta_id) || selected(where_clause, as_of_now) {
                return Ok(false);
            }
        }
    }
    Ok(true)
}

/// Commits transaction `ta_id` (Python: `commit_transaction`).
///
/// Draws a commit timestamp (the counter advances even if the validation fails), validates the transaction
/// through [`TransactionalStore::validate_transaction`], writes and flushes a [`JournalEntry::Commit`], and makes
/// the transaction's work-in-progress versions committed versions with the commit timestamp as start of their
/// validity.
///
/// This must run serially: if two validations overlapped, each could miss the versions the other installs, e.g.
/// write skew:
///
/// ```text
/// T1                              T2
/// r(s), w(t)
///                                 r(t), w(s)
/// gets commit timestamp 6
///                                 gets commit timestamp 7
///                                 validation passes, as
///                                 w(t) of T1 is not visible yet
/// validation passes, as
/// w(s) of T2 is not visible yet
///                                 makes its versions visible
/// makes its versions visible
/// ```
///
/// # Errors
///
/// - [`StoreError::TransactionAborted`] if the validation finds a conflict; the transaction is aborted first,
///   through [`TransactionalStore::abort_transaction`];
/// - an error of the validation, without aborting (Python raises it, too).
///
/// # Panics
///
/// If the transaction is not in the transaction dictionary (Python: `assert`), or if an object of its write set has
/// no work-in-progress version or one of another transaction (Python crashes or its `assert` fails, too).
/// Also if the validation panics, see [`TransactionalStore::validate_transaction`]. Committing a transaction a
/// second time validates it again: it may be aborted, or reach the panic above; a transaction that wrote nothing
/// commits again and enters the trace a second time, as in Python.
pub fn commit_transaction_default<S: TransactionalStore + ?Sized>(
    store: &mut S,
    ta_id: u64,
) -> Result<(), StoreError> {
    let Some(_) = store.state().td.get(&ta_id) else {
        missing_transaction(ta_id)
    };

    // a unique commit timestamp just for validating and committing this transaction:
    let commit_timestamp: u64 = store.next_ta_id();

    // 1. validation phase:
    if !store.validate_transaction(ta_id, commit_timestamp)? {
        store.abort_transaction(ta_id);
        return Err(StoreError::TransactionAborted(format!(
            "validation failed, Transaction {ta_id} failed the validation phase and therefore was aborted due to a \
             conflict with another transaction"
        )));
    }

    // do not confuse the commit timestamp with the start timestamp of the transaction:
    assert!(commit_timestamp > ta_id);

    // I. write to the journal and flush it (write-ahead logging):
    let state: &mut MvccState<S::Value> = store.state_mut();
    state.journal.put(
        ta_id,
        JournalEntry::Commit {
            ta_id,
            commit_timestamp,
        },
    );
    state
        .journal
        .flush(&ta_id)
        .expect("the journal holds the Begin entry of the transaction");

    // II. commit phase: every wip entry of ta_id becomes a new committed version
    let MvccState {
        key_value_store,
        td,
        committed_transactions_trace,
        ..
    } = state;
    let td_entry: &mut TdEntry<S::Value> = td.get_mut(&ta_id).expect("checked above");
    for object_id in &td_entry.write_set {
        let entry: &mut KvStoreEntry<S::Value> = key_value_store
            .get_mut(object_id)
            .expect("every object of the write set is in the store");
        // so far, the start of the validity of the wip entry is ta_id; check it before anything changes:
        let Some(wip) = entry.wip.as_ref() else {
            panic!("transaction {ta_id} has no work-in-progress version of object {object_id}")
        };
        assert_eq!(wip.start_validity, ta_id);
        assert!(wip.start_validity < commit_timestamp);
        // take the wip entry out: this allows other writers to modify the object again
        let mut wip: VersionEntry<S::Value> = entry.wip.take().expect("checked above");
        // the start of the validity becomes the commit timestamp:
        wip.start_validity = commit_timestamp;
        entry.committed.push(wip);
    }

    // mark the transaction as committed and trace it:
    td_entry.committed_timestamp = Some(commit_timestamp);
    committed_transactions_trace.push(ta_id);
    Ok(())
}

/// Aborts transaction `ta_id` (Python: `abort_transaction`): writes a [`JournalEntry::Abort`], removes the
/// work-in-progress version of every object in its write set and removes it from the transaction dictionary.
///
/// As in Python, this is also allowed for a committed transaction; it then removes the work-in-progress versions
/// of the objects it wrote, whoever holds them now.
///
/// # Panics
///
/// If the transaction is not in the transaction dictionary (Python: `assert`).
pub fn abort_transaction_default<S: TransactionalStore + ?Sized>(store: &mut S, ta_id: u64) {
    let state: &mut MvccState<S::Value> = store.state_mut();
    let Some(_) = state.td.get(&ta_id) else {
        missing_transaction(ta_id)
    };

    // append the Abort entry to the journal:
    state.journal.put(ta_id, JournalEntry::Abort { ta_id });

    // remove all wip entries of this transaction, so other transactions can modify the objects again:
    let td_entry: TdEntry<S::Value> = state.td.remove(&ta_id).expect("checked above");
    for object_id in &td_entry.write_set {
        if let Some(entry) = state.key_value_store.get_mut(object_id) {
            entry.wip = None;
        }
    }
}

/// The store that uses the default methods of [`TransactionalStore`]; it holds only its [`MvccState`] (Python:
/// `TransactionalKeyValueStore`).
///
/// Python's constructor parameters `use_brute_force_validation` and `isolation_level` are the [`Validation`] and the
/// [`IsolationLevel`] of [`TransactionalKeyValueStore::with_isolation_level`] (or the [`Validation`] of
/// [`TransactionalKeyValueStore::with_validation`] for a serializable store); `persistence_layer` is not ported, as it
/// is not used.
#[derive(Debug)]
pub struct TransactionalKeyValueStore<V> {
    /// The state of the store.
    pub state: MvccState<V>,
}

impl<V> TransactionalKeyValueStore<V> {
    /// Creates an empty serializable store with validation method 2 (Python's defaults).
    pub fn new() -> TransactionalKeyValueStore<V> {
        TransactionalKeyValueStore::with_validation(Validation::WriteSets)
    }

    /// Creates an empty serializable store with the validation method `validation`.
    pub fn with_validation(validation: Validation) -> TransactionalKeyValueStore<V> {
        TransactionalKeyValueStore {
            state: MvccState::with_validation(validation),
        }
    }

    /// Creates an empty store with the validation method `validation` and the isolation level `isolation_level`.
    ///
    /// # Errors
    ///
    /// See [`MvccState::with_isolation_level`].
    pub fn with_isolation_level(
        validation: Validation,
        isolation_level: IsolationLevel,
    ) -> Result<TransactionalKeyValueStore<V>, StoreError> {
        Ok(TransactionalKeyValueStore {
            state: MvccState::with_isolation_level(validation, isolation_level)?,
        })
    }
}

impl<V> Default for TransactionalKeyValueStore<V> {
    /// Creates an empty store, see [`TransactionalKeyValueStore::new`].
    fn default() -> Self {
        TransactionalKeyValueStore::new()
    }
}

impl<V> VersionedStore for TransactionalKeyValueStore<V> {
    type Value = V;

    /// See [`VersionedStore::key_value_store`].
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<V>> {
        &self.state.key_value_store
    }

    /// See [`VersionedStore::key_value_store_mut`].
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<V>> {
        &mut self.state.key_value_store
    }
}

impl<V: Clone + PartialEq + fmt::Debug> TransactionalStore for TransactionalKeyValueStore<V> {
    /// See [`TransactionalStore::state`].
    fn state(&self) -> &MvccState<V> {
        &self.state
    }

    /// See [`TransactionalStore::state_mut`].
    fn state_mut(&mut self) -> &mut MvccState<V> {
        &mut self.state
    }
}
