// Code generated for the Rust port (no Python source). DO NOT EDIT.
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

//! The store core of ExplainDB in Rust: WHERE-clause predicates and a versioned key-value store.

pub mod error;
pub mod query_processing;
pub mod stores;

pub use error::StoreError;
pub use query_processing::predicates::{
    Attributes, Clause, Disjunction, FalseClause, Operator, Scalar, ScalarRef, TrueClause,
    WhereClause,
};
pub use stores::versioned_key_value_store::{
    KvStoreEntry, Version, VersionEntry, VersionedKeyValueStore, VersionedStore,
};

// Runs the code examples in README.md as tests (`cargo test`), so that they stay correct.
#[cfg(doctest)]
#[doc = include_str!("../README.md")]
struct ReadmeDoctests;
