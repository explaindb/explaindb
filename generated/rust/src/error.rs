// Code generated from system/stores/VersionedKeyValueStore.py, system/stores/MVCC.py, system/indexes/indexes.py. DO NOT EDIT.
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

//! Errors returned by the stores where the Python original raises an exception.

use std::fmt;

/// An error of a store operation. Each variant carries what it is about: an object id, a transaction id, a message
/// or the key (and value) of an index.
///
/// The Python stores raise an exception in these cases (`KeyError`, `RuntimeError`, `ValueError` or
/// `TransactionAbortedException`). Rust panics on the programming errors that Python checks with `assert`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StoreError {
    /// The object id is already in the store (Python: `KeyError` in `put`).
    KeyExists(String),
    /// The object id is not in the store (Python: `KeyError` in `get`, `delete`, `delete_object` and
    /// `_get_visible_object_version`).
    KeyNotFound(String),
    /// The object id is in the store, but has no committed value: its last committed version is a delete marker, or
    /// it has no committed version at all, e.g. because its insert is not committed yet or was aborted. Python's
    /// `get` crashes here (`AttributeError` or `IndexError`); the key still counts for `put` and `size`, as in
    /// Python.
    NotVisible(String),
    /// The transaction id is not in the transaction dictionary (Python: `KeyError` in `read_objects` and
    /// `update_object`, and in validation method 2 for a transaction that committed meanwhile and was aborted
    /// afterwards).
    TransactionNotFound(u64),
    /// The transaction has committed already and cannot read or write any more (Python: `RuntimeError`).
    AlreadyCommitted(u64),
    /// The store aborted the transaction because of a conflict with another transaction; the message says why
    /// (Python: `TransactionAbortedException`).
    TransactionAborted(String),
    /// The settings of a new store do not fit together; the message says why (Python: `ValueError` in
    /// `TransactionalKeyValueStore.__init__`).
    InvalidConfiguration(String),
    /// The committed versions of the object are not ordered by the start of their validity (Python:
    /// `RuntimeError` in `_get_visible_object_version`).
    VersionsNotOrdered(String),
    /// The key is not in the index (Python: `KeyError` of `PythonDictionaryIndex`).
    IndexKeyNotFound(String),
    /// The value is not stored for the key in the index (Python: `KeyError` of `PythonDictionaryIndex.delete`).
    IndexValueNotFound {
        /// The key, as text.
        key: String,
        /// The value, as text.
        value: String,
    },
}

impl fmt::Display for StoreError {
    /// Writes the messages of the Python stores; `NotVisible` has no Python counterpart, the message of
    /// `VersionsNotOrdered` also names the object, and the message of `InvalidConfiguration` names the Rust settings
    /// (`Validation::BruteForce`, `IsolationLevel::Serializable`) instead of Python's parameters.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StoreError::KeyExists(object_id) => {
                write!(f, "object {object_id} already exists in the store")
            }
            StoreError::KeyNotFound(object_id) => {
                write!(f, "object {object_id} not found in the store")
            }
            StoreError::NotVisible(object_id) => {
                write!(f, "object {object_id} has no committed value in the store")
            }
            StoreError::TransactionNotFound(ta_id) => {
                write!(f, "transaction {ta_id} not found in the system")
            }
            StoreError::AlreadyCommitted(ta_id) => {
                write!(f, "transaction {ta_id} committed already")
            }
            StoreError::TransactionAborted(message) => write!(f, "{message}"),
            StoreError::InvalidConfiguration(message) => write!(f, "{message}"),
            StoreError::VersionsNotOrdered(object_id) => write!(
                f,
                "committed versions of object {object_id} are not ordered by their validity start"
            ),
            StoreError::IndexKeyNotFound(key) => write!(f, "Key {key} not found"),
            StoreError::IndexValueNotFound { key, value } => {
                write!(f, "Value {value} not found for key {key}")
            }
        }
    }
}

impl std::error::Error for StoreError {}
