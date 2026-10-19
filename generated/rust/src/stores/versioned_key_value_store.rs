// Code generated from system/stores/VersionedKeyValueStore.py, system/interfaces/indexing/Index.py. DO NOT EDIT.
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

//! Versioned (copy-on-write) key-value store (Python: `system/stores/VersionedKeyValueStore.py`).

use std::fmt;
use std::iter::Chain;

use indexmap::IndexMap;

use crate::error::StoreError;

/// The content of a version: either a new value of the object or a delete marker.
///
/// Python models the two kinds as the subclasses `UpdateEntry` and `DeleteEntry` of `VersionEntry`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Version<V> {
    /// The object was created or updated to this value (Python: `UpdateEntry`).
    Update(V),
    /// The object was deleted (Python: `DeleteEntry`).
    Delete,
}

/// A version entry in the store: a single object/value or a delete marker, plus the start of its validity, i.e.
/// when the object was created, updated or deleted (Python: `VersionEntry`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VersionEntry<V> {
    /// The start of the validity of this version.
    pub start_validity: u64,
    /// The new value or the delete marker.
    pub version: Version<V>,
}

/// A key value store entry: all versions of one object (Python: `KVStoreEntry`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KvStoreEntry<V> {
    /// List of committed versions of the object.
    pub committed: Vec<VersionEntry<V>>,
    /// Optional (SINGLE!) work in progress entry.
    pub wip: Option<VersionEntry<V>>,
}

impl<V> KvStoreEntry<V> {
    /// Returns an iterator over the committed versions plus the wip entry if it exists.
    pub fn iter(&self) -> impl Iterator<Item = &VersionEntry<V>> {
        self.committed.iter().chain(self.wip.iter())
    }
}

impl<'a, V> IntoIterator for &'a KvStoreEntry<V> {
    type Item = &'a VersionEntry<V>;
    type IntoIter =
        Chain<std::slice::Iter<'a, VersionEntry<V>>, std::option::Iter<'a, VersionEntry<V>>>;

    /// Iterates over the committed versions plus the wip entry if it exists (Python: `__iter__`).
    fn into_iter(self) -> Self::IntoIter {
        self.committed.iter().chain(self.wip.iter())
    }
}

/// The methods of a versioned store: a mapping from object ids to the versions of each object.
///
/// Python's `VersionedKeyValueStore` implements the interface `KeyValueStore` and its subclasses inherit the
/// implementation. In Rust, the implementation lives in the default methods of this trait; a store only provides
/// access to its map, see [`VersionedStore::key_value_store`].
pub trait VersionedStore {
    /// The type of the values (objects) stored.
    type Value;

    /// Returns the map from object id to the versions of the object.
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<Self::Value>>;

    /// Returns the map from object id to the versions of the object, for changing it.
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<Self::Value>>;

    /// Returns the number of keys mapped by this store.
    fn size(&self) -> usize {
        self.key_value_store().len()
    }

    /// Adds (puts) a new mapping from `object_id` to `object` into the store.
    ///
    /// Non-transactional insert: the object is recorded as a single committed version with start timestamp 0,
    /// bypassing any transactional semantics. The store takes ownership of the object, so for plain value types such
    /// as numbers, strings and structs made of them, it cannot be modified outside the store (Python copies it
    /// instead).
    ///
    /// # Errors
    ///
    /// [`StoreError::KeyExists`] if the object id is already in the store (Python: `KeyError`).
    fn put(&mut self, object_id: impl Into<String>, object: Self::Value) -> Result<(), StoreError> {
        let object_id: String = object_id.into();
        if self.key_value_store().contains_key(&object_id) {
            return Err(StoreError::KeyExists(object_id));
        }
        self.key_value_store_mut().insert(
            object_id,
            KvStoreEntry {
                committed: vec![VersionEntry {
                    start_validity: 0,
                    version: Version::Update(object),
                }],
                wip: None,
            },
        );
        Ok(())
    }

    /// Returns the value of the most recent committed version of the object `object_id`.
    ///
    /// Python's `get` returns an iterator and raises its errors only when the iterator is used; this method returns
    /// the value directly.
    ///
    /// # Errors
    ///
    /// - [`StoreError::KeyNotFound`] if the object id is not in the store (Python: `KeyError`);
    /// - [`StoreError::NotVisible`] if the most recent committed version is a delete marker or there is no committed
    ///   version (Python crashes in these cases).
    fn get(&self, object_id: &str) -> Result<&Self::Value, StoreError> {
        let entry: &KvStoreEntry<Self::Value> = self
            .key_value_store()
            .get(object_id)
            .ok_or_else(|| StoreError::KeyNotFound(object_id.to_string()))?;
        match entry.committed.last() {
            Some(VersionEntry {
                version: Version::Update(value),
                ..
            }) => Ok(value),
            _ => Err(StoreError::NotVisible(object_id.to_string())),
        }
    }

    /// Deletes the object `object_id` from the store.
    ///
    /// Non-transactional delete: appends a delete marker as a committed version with start timestamp 0. As in
    /// Python, the object id stays in the store, so `put` still reports it as existing and `size` still counts it;
    /// deleting it again appends another delete marker. Python's parameter `_object`, which must be `None`, is
    /// dropped.
    ///
    /// # Errors
    ///
    /// [`StoreError::KeyNotFound`] if the object id is not in the store (Python: `KeyError`).
    fn delete(&mut self, object_id: &str) -> Result<(), StoreError> {
        let entry: &mut KvStoreEntry<Self::Value> =
            self.key_value_store_mut()
                .get_mut(object_id)
                .ok_or_else(|| StoreError::KeyNotFound(object_id.to_string()))?;
        // create a new entry for the kv store that marks the object as deleted and add it as committed:
        entry.committed.push(VersionEntry {
            start_validity: 0,
            version: Version::Delete,
        });
        Ok(())
    }

    /// Persists all changes, i.e. any changes done so far in volatile memory only are now made durable.
    ///
    /// If `object_id` is given, only this object is flushed, otherwise all objects are flushed.
    ///
    /// The default implementation is a no-op: the store keeps its data in volatile memory only and is not backed by
    /// persistent storage.
    fn flush(&mut self, _object_id: Option<&str>) {}

    /// Bulkloads the given key->value mappings into the store by calling [`VersionedStore::put`] for each pair.
    ///
    /// # Errors
    ///
    /// The error of the first `put` that fails; the pairs before it stay in the store.
    fn bulkload<K, I>(&mut self, input_data: I) -> Result<(), StoreError>
    where
        K: Into<String>,
        I: IntoIterator<Item = (K, Self::Value)>,
    {
        for (object_id, object) in input_data {
            self.put(object_id, object)?;
        }
        Ok(())
    }

    /// Shows the content of the store: pretty-prints the underlying map with `Debug`. Python's `pprint` stops at
    /// depth 3; this prints all levels.
    fn show(&self)
    where
        Self::Value: fmt::Debug,
    {
        println!("{:#?}", self.key_value_store());
    }
}

/// A versioned store managing key/value mappings (Python: `VersionedKeyValueStore`).
///
/// Python's constructor parameter `persistence_layer` is not used there and is dropped.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VersionedKeyValueStore<V> {
    /// The actual data kept by this store: a mapping from an `object_id` (which is a string to allow for prefixes)
    /// to all versions of the object. We may have MULTIPLE committed versions valid at different points in time
    /// plus AT MOST ONE optional work in progress (wip) entry, i.e. an object currently being modified by an
    /// ongoing transaction. The map keeps the order in which the object ids were inserted, as Python's dict does.
    pub key_value_store: IndexMap<String, KvStoreEntry<V>>,
}

impl<V> VersionedKeyValueStore<V> {
    /// Creates an empty store.
    pub fn new() -> VersionedKeyValueStore<V> {
        VersionedKeyValueStore {
            key_value_store: IndexMap::new(),
        }
    }
}

impl<V> Default for VersionedKeyValueStore<V> {
    /// Creates an empty store, see [`VersionedKeyValueStore::new`].
    fn default() -> Self {
        VersionedKeyValueStore::new()
    }
}

impl<V> VersionedStore for VersionedKeyValueStore<V> {
    type Value = V;

    /// See [`VersionedStore::key_value_store`].
    fn key_value_store(&self) -> &IndexMap<String, KvStoreEntry<V>> {
        &self.key_value_store
    }

    /// See [`VersionedStore::key_value_store_mut`].
    fn key_value_store_mut(&mut self) -> &mut IndexMap<String, KvStoreEntry<V>> {
        &mut self.key_value_store
    }
}
