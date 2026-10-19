// Code generated from system/tests/abstract_unit_test.py, system/tests/query_processing/test_query_processing.py. DO NOT EDIT.
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

//! Test objects and test data shared by the test files (Python: `system/tests/abstract_unit_test.py`).

// Each test target in tests/ is compiled as its own crate and uses only some of these items; the others would be
// reported as unused.
#![allow(dead_code)]

use explaindb::{Attributes, ScalarRef};

/// A test object with two integer attributes (Python: the frozen dataclass `Stuff`).
#[derive(Clone, Debug, PartialEq, Eq)]
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
