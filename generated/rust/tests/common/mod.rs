// Code generated from system/tests/abstract_unit_test.py, system/tests/query_processing/test_query_processing.py, system/tests/stores/test_store_anomalies.py. DO NOT EDIT.
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

//! Test objects and test data shared by the test files (Python: `system/tests/abstract_unit_test.py`; `Named` stands
//! in for the `Stuff` with a string attribute in `system/tests/query_processing/test_query_processing.py`, and
//! `Account` is the value type of `system/tests/stores/test_store_anomalies.py`).

// Each test target in tests/ is compiled as its own crate and uses only some of these items; the others would be
// reported as unused.
#![allow(dead_code)]

use std::cell::Cell;

use explaindb::{Attributes, Clause, ScalarRef, Version, VersionEntry, WhereClause};

/// A test object with two integer attributes (Python: the frozen dataclass `Stuff`, which is hashable).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Stuff {
    /// The attribute `a`.
    pub a: i64,
    /// The attribute `b`.
    pub b: i64,
}

impl Attributes for Stuff {
    /// See [`Attributes::attribute`].
    fn attribute(&self, name: &str) -> Option<ScalarRef<'_>> {
        match name {
            "a" => Some(ScalarRef::Int(self.a)),
            "b" => Some(ScalarRef::Int(self.b)),
            _ => None,
        }
    }
}

/// A test object whose attribute `a` is a string. Python's tests store a string in `Stuff.a` instead, which Rust's
/// types do not allow.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Named {
    /// The attribute `a`.
    pub a: String,
    /// The attribute `b`.
    pub b: i64,
}

impl Attributes for Named {
    /// See [`Attributes::attribute`].
    fn attribute(&self, name: &str) -> Option<ScalarRef<'_>> {
        match name {
            "a" => Some(ScalarRef::Str(&self.a)),
            "b" => Some(ScalarRef::Int(self.b)),
            _ => None,
        }
    }
}

/// A test object with two integer attributes that, unlike [`Stuff`], has no `Hash` and no `Eq` (Python: a
/// non-frozen pydantic model, whose instances are not hashable). The stores never need `Hash` of their values.
#[derive(Clone, Debug, PartialEq)]
pub struct Account {
    /// The attribute `a`.
    pub a: i64,
    /// The attribute `b`.
    pub b: i64,
}

impl Attributes for Account {
    /// See [`Attributes::attribute`].
    fn attribute(&self, name: &str) -> Option<ScalarRef<'_>> {
        match name {
            "a" => Some(ScalarRef::Int(self.a)),
            "b" => Some(ScalarRef::Int(self.b)),
            _ => None,
        }
    }
}

/// A where clause that counts how often it is evaluated (Python: `CountingWHERE_Clause`).
#[derive(Debug)]
pub struct CountingWhereClause {
    /// The where clause that does the actual evaluation.
    pub clause: WhereClause,
    /// The number of evaluations so far; a [`Cell`], as [`Clause::evaluate`] takes `&self`.
    pub evaluations: Cell<usize>,
}

impl Clause<Stuff> for CountingWhereClause {
    /// See [`Clause::evaluate`]. Also increments the evaluation counter.
    fn evaluate(&self, object: &Stuff) -> bool {
        self.evaluations.set(self.evaluations.get() + 1);
        Clause::<Stuff>::evaluate(&self.clause, object)
    }
}

/// Returns `number_of_tuples` pairs `("0", Stuff), ("1", Stuff), ...` with `a` in 0..=1000 and `b` in 0..=2000.
///
/// Python draws the values with Faker; here a fixed formula spreads them, so every run uses the same data.
pub fn create_fake_data(number_of_tuples: i64) -> Vec<(String, Stuff)> {
    (0..number_of_tuples)
        .map(|i| {
            (
                i.to_string(),
                Stuff {
                    a: (i * 37) % 1001,
                    b: (i * 53) % 2001,
                },
            )
        })
        .collect()
}

/// Returns an update version (committed or work-in-progress) with the given start of validity and value.
pub fn update(start_validity: u64, value: Stuff) -> VersionEntry<Stuff> {
    VersionEntry {
        start_validity,
        version: Version::Update(value),
    }
}

/// Returns a delete marker with the given start of validity.
pub fn delete_marker(start_validity: u64) -> VersionEntry<Stuff> {
    VersionEntry {
        start_validity,
        version: Version::Delete,
    }
}
