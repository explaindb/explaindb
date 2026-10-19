// Code generated from system/tests/indexes/test_indexing.py. DO NOT EDIT.
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

//! Tests for the indexes (Python: `system/tests/indexes/test_indexing.py`).

use explaindb::{DictionaryIndex, StoreError};

/// A dictionary index keeps all values put for the same key, in the order they were put; `delete` removes one
/// value at a time, fails for a value or key that is not in the index, and drops the key with its last value.
#[test]
fn test_indexing_basics_with_duplicates() {
    let mut index: DictionaryIndex<&str, &str> = DictionaryIndex::new();
    index.put("key1", "value1");
    index.put("key1", "value2");
    index.put("key1", "value3");
    assert_eq!(index.size(), 1);
    assert_eq!(index.get(&"key1"), Ok(&["value1", "value2", "value3"][..]));

    index.delete(&"key1", &"value1").unwrap();
    assert_eq!(index.size(), 1);
    assert_eq!(index.get(&"key1"), Ok(&["value2", "value3"][..]));

    index.delete(&"key1", &"value2").unwrap();
    assert_eq!(index.size(), 1);
    assert_eq!(index.get(&"key1"), Ok(&["value3"][..]));

    // the error names the value as printed by `Debug`, i.e. a string in quotes:
    assert_eq!(
        index.delete(&"key1", &"value4"),
        Err(StoreError::IndexValueNotFound {
            key: "key1".to_string(),
            value: "\"value4\"".to_string(),
        })
    );

    assert_eq!(
        index.delete(&"key7", &"value4"),
        Err(StoreError::IndexKeyNotFound("key7".to_string()))
    );

    index.delete(&"key1", &"value3").unwrap();
    assert_eq!(index.size(), 0);
}

/// `get` and `flush` of a key that is not in the dictionary index fail with [`StoreError::IndexKeyNotFound`];
/// `flush` of a key that is in the index succeeds and changes nothing.
#[test]
fn get_and_flush_of_missing_key_fail() {
    let mut index: DictionaryIndex<&str, &str> = DictionaryIndex::new();
    index.put("key1", "value1");

    assert_eq!(
        index.get(&"key7"),
        Err(StoreError::IndexKeyNotFound("key7".to_string()))
    );
    assert_eq!(
        index.flush(&"key7"),
        Err(StoreError::IndexKeyNotFound("key7".to_string()))
    );
    assert_eq!(index.flush(&"key1"), Ok(()));
    assert_eq!(index.get(&"key1"), Ok(&["value1"][..]));
}

/// Deleting the last value of the first key drops that key and keeps the other keys in the order they were put, as
/// deleting from Python's dict does.
#[test]
fn delete_of_last_value_keeps_order_of_other_keys() {
    let mut index: DictionaryIndex<&str, &str> = DictionaryIndex::new();
    for key in ["key1", "key2", "key3", "key4"] {
        index.put(key, "value");
    }

    index.delete(&"key1", &"value").unwrap();

    let keys: Vec<&str> = index.index.keys().copied().collect();
    assert_eq!(keys, ["key2", "key3", "key4"]);
}

/// The messages of the index errors are those of Python's `KeyError`s of `PythonDictionaryIndex`, with the value
/// as Rust's `Debug` text.
#[test]
fn index_error_messages() {
    assert_eq!(
        StoreError::IndexKeyNotFound("key7".to_string()).to_string(),
        "Key key7 not found"
    );
    assert_eq!(
        StoreError::IndexValueNotFound {
            key: "key1".to_string(),
            value: "\"value4\"".to_string(),
        }
        .to_string(),
        "Value \"value4\" not found for key key1"
    );
}
