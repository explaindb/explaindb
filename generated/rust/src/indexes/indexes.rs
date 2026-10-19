// Code generated from system/indexes/indexes.py, system/interfaces/indexing/Index.py. DO NOT EDIT.
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

//! Simple in-memory indexes (Python: `system/indexes/indexes.py`).

use std::fmt;
use std::hash::Hash;

use indexmap::IndexMap;

use crate::error::StoreError;

/// A simple key-value store implemented using a map (Python: `PythonDictionaryIndex`, a Python dictionary).
///
/// Supports duplicates by mapping a key to a list of values, i.e. multiple values can be associated with the same
/// key. The map keeps the order in which the keys were inserted, as Python's dict does.
#[derive(Clone, Debug)]
pub struct DictionaryIndex<K, V> {
    /// The mapping from each key to the list of its values.
    pub index: IndexMap<K, Vec<V>>,
}

impl<K: Hash + Eq, V> DictionaryIndex<K, V> {
    /// Creates an empty index.
    pub fn new() -> DictionaryIndex<K, V> {
        DictionaryIndex {
            index: IndexMap::new(),
        }
    }

    /// Returns the number of keys mapped by this index.
    pub fn size(&self) -> usize {
        self.index.len()
    }

    /// Appends `value` to the list stored for `key`, so duplicates are kept rather than overwritten.
    pub fn put(&mut self, key: K, value: V) {
        self.index.entry(key).or_default().push(value);
    }

    /// Removes `value` (its first occurrence) from the list stored for `key` and drops the key entirely once its
    /// last value has been removed; the other keys keep their order, as in Python's dict. Unlike Python's
    /// constant-time delete, dropping a key takes time proportional to the number of keys after it.
    ///
    /// # Errors
    ///
    /// [`StoreError::IndexKeyNotFound`] if the key is not present, [`StoreError::IndexValueNotFound`] if the value
    /// is not stored for the key (Python: `KeyError`).
    pub fn delete(&mut self, key: &K, value: &V) -> Result<(), StoreError>
    where
        K: fmt::Display,
        V: PartialEq + fmt::Debug,
    {
        let Some(values) = self.index.get_mut(key) else {
            return Err(StoreError::IndexKeyNotFound(key.to_string()));
        };
        let Some(position) = values.iter().position(|stored| stored == value) else {
            return Err(StoreError::IndexValueNotFound {
                key: key.to_string(),
                value: format!("{value:?}"),
            });
        };
        values.remove(position);
        if values.is_empty() {
            // shift_remove keeps the order of the other keys, as deleting from Python's dict does
            self.index.shift_remove(key);
        }
        Ok(())
    }

    /// Persists the values of `key`.
    ///
    /// No-op: the index lives in volatile memory and is not backed by persistent storage. Python's `flush()`
    /// without a key has no counterpart here.
    ///
    /// # Errors
    ///
    /// [`StoreError::IndexKeyNotFound`] if the key is not present (Python: `KeyError`).
    pub fn flush(&self, key: &K) -> Result<(), StoreError>
    where
        K: fmt::Display,
    {
        if !self.index.contains_key(key) {
            return Err(StoreError::IndexKeyNotFound(key.to_string()));
        }
        Ok(())
    }

    /// Returns the values stored for `key`, in the order they were put.
    ///
    /// # Errors
    ///
    /// [`StoreError::IndexKeyNotFound`] if the key is not present (Python: `KeyError`).
    pub fn get(&self, key: &K) -> Result<&[V], StoreError>
    where
        K: fmt::Display,
    {
        self.index
            .get(key)
            .map(Vec::as_slice)
            .ok_or_else(|| StoreError::IndexKeyNotFound(key.to_string()))
    }

    /// Prints the underlying map.
    pub fn show(&self)
    where
        K: fmt::Debug,
        V: fmt::Debug,
    {
        println!("{:?}", self.index);
    }
}

impl<K: Hash + Eq, V> Default for DictionaryIndex<K, V> {
    /// Creates an empty index, see [`DictionaryIndex::new`].
    fn default() -> Self {
        DictionaryIndex::new()
    }
}
