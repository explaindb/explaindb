// Code generated from system/stores/VersionedKeyValueStore.py. DO NOT EDIT.
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

/// An error of a store operation. Each variant carries the object id it is about.
///
/// The Python stores raise `KeyError` in these cases. Rust panics on the programming errors that Python checks
/// with `assert`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StoreError {
    /// The object id is already in the store (Python: `KeyError` in `put`).
    KeyExists(String),
    /// The object id is not in the store (Python: `KeyError` in `get` and `delete`).
    KeyNotFound(String),
    /// The object id is in the store, but has no committed value: its last committed version is a delete marker, or
    /// it has no committed version at all, e.g. because its insert is not committed yet or was aborted. Python's
    /// `get` crashes here (`AttributeError` or `IndexError`); the key still counts for `put` and `size`, as in
    /// Python.
    NotVisible(String),
}

impl fmt::Display for StoreError {
    /// Writes the messages of the Python stores for `KeyExists` and `KeyNotFound`; `NotVisible` has no Python
    /// counterpart.
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
        }
    }
}

impl std::error::Error for StoreError {}
