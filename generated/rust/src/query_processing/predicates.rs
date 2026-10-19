// Code generated from system/query_processing/predicates.py. DO NOT EDIT.
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

//! WHERE-clause predicates and clause combinators for query processing (Python:
//! `system/query_processing/predicates.py`).

use std::cmp::Ordering;
use std::fmt;

/// An owned scalar value: the constant of a [`WhereClause`].
///
/// Python compares arbitrary objects; the Rust port supports the two types the WHERE clause accepts as constants,
/// integers and strings. Python integers have no size limit, Rust uses `i64`; Python also accepts `True` as an
/// integer, Rust does not. There is no null value: an attribute either has an integer or a string value, or it does
/// not exist.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Scalar {
    /// An integer.
    Int(i64),
    /// A string.
    Str(String),
}

/// A borrowed scalar value: the value of an attribute of an object, see [`Attributes`].
///
/// It borrows strings from the object, so reading an attribute does not allocate.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ScalarRef<'a> {
    /// An integer.
    Int(i64),
    /// A string, borrowed from the object.
    Str(&'a str),
}

impl Scalar {
    /// Returns this scalar as a borrowed [`ScalarRef`].
    pub fn as_scalar_ref(&self) -> ScalarRef<'_> {
        match self {
            Scalar::Int(value) => ScalarRef::Int(*value),
            Scalar::Str(value) => ScalarRef::Str(value),
        }
    }
}

impl ScalarRef<'_> {
    /// Returns an owned copy of this scalar.
    pub fn to_scalar(self) -> Scalar {
        match self {
            ScalarRef::Int(value) => Scalar::Int(value),
            ScalarRef::Str(value) => Scalar::Str(value.to_string()),
        }
    }
}

// Keep `i64` the only integer type converted to `Scalar`: an integer literal such as `0` in
// `WhereClause::new("a", "<", 0)` compiles only because there is exactly one such conversion.
impl From<i64> for Scalar {
    /// Wraps an integer.
    fn from(value: i64) -> Self {
        Scalar::Int(value)
    }
}

impl From<&str> for Scalar {
    /// Copies a string.
    fn from(value: &str) -> Self {
        Scalar::Str(value.to_string())
    }
}

impl From<String> for Scalar {
    /// Wraps a string.
    fn from(value: String) -> Self {
        Scalar::Str(value)
    }
}

/// Access to the attributes of an object by name, so that a [`WhereClause`] can read them.
///
/// Python's `WHERE_Clause` reads attributes with `getattr`; in Rust, each value type that should be filtered by a
/// [`WhereClause`] implements this trait.
pub trait Attributes {
    /// Returns the value of the attribute `name` of this object, or `None` if the object has no attribute of that
    /// name.
    fn attribute(&self, name: &str) -> Option<ScalarRef<'_>>;
}

/// Interface for a WHERE-clause predicate that can be evaluated against a single object (row) of type `V`.
///
/// Every clause implements `Debug`, so that clauses can be printed, e.g. the clauses of a [`Disjunction`].
pub trait Clause<V>: fmt::Debug {
    /// Evaluates this clause against a single object (row) and returns `true` if the object satisfies the clause.
    ///
    /// # Panics
    ///
    /// Implementations may panic if the object does not fit the clause, see [`WhereClause`].
    fn evaluate(&self, object: &V) -> bool;
}

/// A comparison operator of a [`WhereClause`].
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Operator {
    /// `==`
    Eq,
    /// `!=`
    Ne,
    /// `<`
    Lt,
    /// `<=`
    Le,
    /// `>`
    Gt,
    /// `>=`
    Ge,
}

impl Operator {
    /// Returns the operator written as `symbol`, e.g. `"<="`, or `None` if the symbol is not one of the six allowed
    /// operators.
    pub fn parse(symbol: &str) -> Option<Operator> {
        match symbol {
            "==" => Some(Operator::Eq),
            "!=" => Some(Operator::Ne),
            "<" => Some(Operator::Lt),
            "<=" => Some(Operator::Le),
            ">" => Some(Operator::Gt),
            ">=" => Some(Operator::Ge),
            _ => None,
        }
    }

    /// Returns the symbol of this operator, e.g. `"<="`.
    pub fn symbol(self) -> &'static str {
        match self {
            Operator::Eq => "==",
            Operator::Ne => "!=",
            Operator::Lt => "<",
            Operator::Le => "<=",
            Operator::Gt => ">",
            Operator::Ge => ">=",
        }
    }
}

/// A WHERE clause in SQL is a clause that specifies a filter condition for selecting data (Python:
/// `WHERE_Clause`).
///
/// This clause has the form `attribute operator constant`, e.g. `a < 0`, and evaluates to true or false. Its fields
/// are private, so every clause is built by [`WhereClause::new`] and has passed its checks.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WhereClause {
    /// Name of the attribute to read from the tested object.
    attribute: String,
    /// Comparison operator.
    operator: Operator,
    /// Constant value the attribute is compared against.
    constant: Scalar,
}

impl WhereClause {
    /// Builds a WHERE clause of the form `attribute operator constant` and sanitizes it, i.e. checks it for
    /// security reasons (Python: `__init__` and `sanitize`).
    ///
    /// `attribute` is the name of the attribute to read from the tested object, `operator` one of `==`, `!=`, `<`,
    /// `<=`, `>`, `>=`, and `constant` the integer or string the attribute is compared against.
    ///
    /// Python's `isalpha` and `isalnum` also accept non-ASCII letters such as `ä`; this port accepts ASCII only.
    ///
    /// # Panics
    ///
    /// With the message of the first check that fails, in this order, as Python's asserts do:
    /// - `"invalid operator"`: the operator is not one of the six above;
    /// - `"invalid attribute"`: the attribute is empty or contains a character other than an ASCII letter;
    /// - `"invalid constant"`: the constant is a string that is empty or contains a character other than an ASCII
    ///   letter or digit.
    pub fn new(attribute: &str, operator: &str, constant: impl Into<Scalar>) -> WhereClause {
        let Some(operator) = Operator::parse(operator) else {
            panic!("invalid operator");
        };
        assert!(
            !attribute.is_empty() && attribute.chars().all(|c| c.is_ascii_alphabetic()),
            "invalid attribute"
        );
        let constant: Scalar = constant.into();
        if let Scalar::Str(text) = &constant {
            assert!(
                !text.is_empty() && text.chars().all(|c| c.is_ascii_alphanumeric()),
                "invalid constant"
            );
        }
        WhereClause {
            attribute: attribute.to_string(),
            operator,
            constant,
        }
    }

    /// Returns the name of the attribute read from the tested object.
    pub fn attribute(&self) -> &str {
        &self.attribute
    }

    /// Returns the comparison operator.
    pub fn operator(&self) -> Operator {
        self.operator
    }

    /// Returns the constant the attribute is compared against.
    pub fn constant(&self) -> &Scalar {
        &self.constant
    }
}

/// Compares two scalars of the same type with each other.
///
/// # Panics
///
/// If the scalars have different types, as Python raises a `TypeError` when it orders an integer and a string;
/// `operator` is only used for the message.
fn compare_same_type(operator: Operator, left: ScalarRef<'_>, right: ScalarRef<'_>) -> Ordering {
    match (left, right) {
        (ScalarRef::Int(left), ScalarRef::Int(right)) => left.cmp(&right),
        (ScalarRef::Str(left), ScalarRef::Str(right)) => left.cmp(right),
        _ => panic!(
            "'{}' not supported between {left:?} and {right:?}",
            operator.symbol()
        ),
    }
}

impl<V: Attributes> Clause<V> for WhereClause {
    /// See [`Clause::evaluate`].
    ///
    /// Reads the attribute from the object and compares it against the constant using the operator, as Python does:
    /// `==` and `!=` between an integer and a string give `false` and `true`.
    ///
    /// # Panics
    ///
    /// If the object has no such attribute (Python: `AttributeError`), and for `<`, `<=`, `>`, `>=` between an
    /// integer and a string (Python: `TypeError`).
    fn evaluate(&self, object: &V) -> bool {
        let Some(value) = object.attribute(&self.attribute) else {
            panic!("object has no attribute '{}'", self.attribute);
        };
        let constant: ScalarRef<'_> = self.constant.as_scalar_ref();
        match self.operator {
            Operator::Eq => value == constant,
            Operator::Ne => value != constant,
            Operator::Lt => compare_same_type(self.operator, value, constant) == Ordering::Less,
            Operator::Le => compare_same_type(self.operator, value, constant) != Ordering::Greater,
            Operator::Gt => compare_same_type(self.operator, value, constant) == Ordering::Greater,
            Operator::Ge => compare_same_type(self.operator, value, constant) != Ordering::Less,
        }
    }
}

/// A disjunction is a logical operation that outputs true if at least one of the operands is true.
pub struct Disjunction<V> {
    /// The operand clauses combined by logical OR.
    pub clauses: Vec<Box<dyn Clause<V>>>,
}

impl<V> Disjunction<V> {
    /// Builds a disjunction (logical OR) over the given clauses (Python: `Disjunction(*clauses)`).
    pub fn new(clauses: Vec<Box<dyn Clause<V>>>) -> Disjunction<V> {
        Disjunction { clauses }
    }
}

impl<V> fmt::Debug for Disjunction<V> {
    /// Shows the operand clauses; written by hand so that `V` need not implement `Debug`.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Disjunction")
            .field("clauses", &self.clauses)
            .finish()
    }
}

impl<V> Clause<V> for Disjunction<V> {
    /// See [`Clause::evaluate`].
    ///
    /// Returns `true` as soon as any of the contained clauses evaluates to `true` (logical OR); the remaining clauses
    /// are not evaluated, as with Python's `any`. Without clauses, returns `false`. A panic of a clause, e.g. of a
    /// [`WhereClause`] on a missing attribute, passes through to the caller.
    fn evaluate(&self, object: &V) -> bool {
        self.clauses.iter().any(|clause| clause.evaluate(object))
    }
}

/// A clause that always evaluates to true.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TrueClause;

impl<V> Clause<V> for TrueClause {
    /// See [`Clause::evaluate`].
    ///
    /// Always returns `true`.
    fn evaluate(&self, _object: &V) -> bool {
        true
    }
}

/// A clause that always evaluates to false.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct FalseClause;

impl<V> Clause<V> for FalseClause {
    /// See [`Clause::evaluate`].
    ///
    /// Always returns `false`.
    fn evaluate(&self, _object: &V) -> bool {
        false
    }
}
