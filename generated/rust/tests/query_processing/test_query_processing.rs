// Code generated from system/tests/query_processing/test_query_processing.py. DO NOT EDIT.
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

//! Tests for WHERE-clause predicates (Python: `system/tests/query_processing/test_query_processing.py`).

use crate::common::{Named, Stuff};
use explaindb::{
    Attributes, Clause, Disjunction, FalseClause, Operator, Scalar, ScalarRef, TrueClause,
    WhereClause,
};

/// A WHERE clause `a == constant` is true for an object whose `a` equals the constant and false for `a == 11`; this
/// holds for an integer attribute and for a string attribute. For the string, `a == 11` compares the string `"10"`
/// with the integer 11, which is false and does not panic.
#[test]
fn test_where_clause() {
    // integer attribute: Stuff { a: 10 }
    let stuff: Stuff = Stuff { a: 10, b: 20 };
    assert!(WhereClause::new("a", "==", 10).evaluate(&stuff));
    assert!(!WhereClause::new("a", "==", 11).evaluate(&stuff));

    // string attribute: Named { a: "10" }
    let named: Named = Named {
        a: "10".to_string(),
        b: 20,
    };
    assert!(WhereClause::new("a", "==", "10").evaluate(&named));
    assert!(!WhereClause::new("a", "==", 11).evaluate(&named));
}

/// A disjunction of `a == 10` and `a == 30` is true for objects with `a` equal to 10 or 30 and false for `a` equal
/// to 20.
#[test]
fn test_disjunction() {
    let stuff1: Stuff = Stuff { a: 10, b: 20 };
    let stuff2: Stuff = Stuff { a: 30, b: 40 };
    let stuff3: Stuff = Stuff { a: 20, b: 30 };

    let disjunction: Disjunction<Stuff> = Disjunction::new(vec![
        Box::new(WhereClause::new("a", "==", 10)),
        Box::new(WhereClause::new("a", "==", 30)),
    ]);

    assert!(disjunction.evaluate(&stuff1));
    assert!(disjunction.evaluate(&stuff2));
    // negative test: neither clause matches
    assert!(!disjunction.evaluate(&stuff3));
}

/// Builds a [`Named`] object whose string attribute `a` is `a`.
fn named(a: &str) -> Named {
    Named {
        a: a.to_string(),
        b: 0,
    }
}

/// Checks all six operators on the attribute `a`: for each operator, the clause `a operator constant` is evaluated
/// against three objects whose `a` is smaller than, equal to and larger than `constant`, and the three results are
/// compared with the truth table of the operator. This catches an operator that is mixed up with another one, e.g.
/// `<` with `<=`.
fn check_all_operators<V: Attributes>(smaller: &V, equal: &V, larger: &V, constant: Scalar) {
    // expected results for the objects (smaller, equal, larger):
    let truth_table: [(&str, [bool; 3]); 6] = [
        ("==", [false, true, false]),
        ("!=", [true, false, true]),
        ("<", [true, false, false]),
        ("<=", [true, true, false]),
        (">", [false, false, true]),
        (">=", [false, true, true]),
    ];
    for (operator, expected) in truth_table {
        let clause: WhereClause = WhereClause::new("a", operator, constant.clone());
        let actual: [bool; 3] = [
            clause.evaluate(smaller),
            clause.evaluate(equal),
            clause.evaluate(larger),
        ];
        assert_eq!(actual, expected, "a {operator} {constant:?}");
    }
}

/// Each of the six operators compares an integer attribute with an integer constant correctly, for an attribute
/// smaller than, equal to and larger than the constant.
#[test]
fn every_operator_compares_integers() {
    check_all_operators(
        &Stuff { a: 9, b: 0 },
        &Stuff { a: 10, b: 0 },
        &Stuff { a: 11, b: 0 },
        Scalar::Int(10),
    );
    // negative values are ordered as numbers, too:
    check_all_operators(
        &Stuff { a: -6, b: 0 },
        &Stuff { a: -5, b: 0 },
        &Stuff { a: -4, b: 0 },
        Scalar::Int(-5),
    );
}

/// A clause can be written with a bare integer literal as constant, e.g. `a < 0`, and compares it as an integer.
/// That the literal is accepted at all is checked by the compiler: it works because `i64` is the only integer type
/// converted to `Scalar`.
#[test]
fn where_clause_accepts_a_bare_integer_literal() {
    let clause: WhereClause = WhereClause::new("a", "<", 0);
    assert_eq!(clause.constant(), &Scalar::Int(0));
    assert!(clause.evaluate(&Stuff { a: -1, b: 0 }));
    assert!(!clause.evaluate(&Stuff { a: 0, b: 0 }));
}

/// Each of the six operators compares a string attribute with a string constant correctly, for an attribute
/// smaller than, equal to and larger than the constant.
#[test]
fn every_operator_compares_strings() {
    check_all_operators(
        &named("abc"),
        &named("abd"),
        &named("abe"),
        Scalar::from("abd"),
    );
}

/// Strings are ordered character by character, as in Python, not by the number they spell: `"10" < "9"` is true,
/// and an upper-case letter is smaller than every lower-case letter (`"Z" < "a"`).
#[test]
fn strings_are_ordered_character_by_character() {
    assert!(WhereClause::new("a", "<", "9").evaluate(&named("10")));
    assert!(WhereClause::new("a", "<", "a").evaluate(&named("Z")));
}

/// `==` between a string attribute and an integer constant is false and `!=` is true, even if the string spells
/// the number; the same holds for an integer attribute and a string constant. Neither panics, as in Python.
#[test]
fn equality_between_string_and_integer_is_false() {
    let named_ten: Named = named("10");
    assert!(!WhereClause::new("a", "==", 10).evaluate(&named_ten));
    assert!(WhereClause::new("a", "!=", 10).evaluate(&named_ten));

    let stuff_ten: Stuff = Stuff { a: 10, b: 0 };
    assert!(!WhereClause::new("a", "==", "10").evaluate(&stuff_ten));
    assert!(WhereClause::new("a", "!=", "10").evaluate(&stuff_ten));
}

/// Ordering a string attribute against an integer constant with `<` panics, as Python raises a `TypeError`.
#[test]
#[should_panic(expected = "'<' not supported between")]
fn less_than_between_string_attribute_and_integer_panics() {
    WhereClause::new("a", "<", 10).evaluate(&named("10"));
}

/// Ordering a string attribute against an integer constant with `<=` panics, as Python raises a `TypeError`.
#[test]
#[should_panic(expected = "'<=' not supported between")]
fn less_or_equal_between_string_attribute_and_integer_panics() {
    WhereClause::new("a", "<=", 10).evaluate(&named("10"));
}

/// Ordering an integer attribute against a string constant with `>` panics, as Python raises a `TypeError`.
#[test]
#[should_panic(expected = "'>' not supported between")]
fn greater_than_between_integer_attribute_and_string_panics() {
    WhereClause::new("a", ">", "abc").evaluate(&Stuff { a: 10, b: 0 });
}

/// Ordering an integer attribute against a string constant with `>=` panics, as Python raises a `TypeError`.
#[test]
#[should_panic(expected = "'>=' not supported between")]
fn greater_or_equal_between_integer_attribute_and_string_panics() {
    WhereClause::new("a", ">=", "abc").evaluate(&Stuff { a: 10, b: 0 });
}

/// Evaluating a clause on an attribute the object does not have panics and names the attribute, as Python raises
/// an `AttributeError`.
#[test]
#[should_panic(expected = "object has no attribute 'x'")]
fn missing_attribute_panics() {
    WhereClause::new("x", "==", 1).evaluate(&Stuff { a: 10, b: 0 });
}

/// An attribute of upper- and lower-case ASCII letters, a string constant of ASCII letters and digits and any
/// integer constant, also a negative one, pass the sanitize checks.
#[test]
fn sanitize_accepts_ascii_letters_and_digits() {
    let clause: WhereClause = WhereClause::new("aB", "==", "x1Y");
    assert_eq!(clause.attribute(), "aB");
    assert_eq!(clause.constant(), &Scalar::from("x1Y"));
    assert_eq!(WhereClause::new("a", "==", -7).constant(), &Scalar::Int(-7));
}

/// An operator that is not one of the six allowed ones, such as `=<`, is rejected.
#[test]
#[should_panic(expected = "invalid operator")]
fn sanitize_rejects_unknown_operator() {
    WhereClause::new("a", "=<", 1);
}

/// The operator is checked first: a clause with an invalid operator and an invalid attribute and constant panics
/// with "invalid operator".
#[test]
#[should_panic(expected = "invalid operator")]
fn sanitize_checks_operator_before_attribute_and_constant() {
    WhereClause::new("a1", "=<", "a;b");
}

/// The attribute is checked before the constant: a clause with an invalid attribute and an invalid constant panics
/// with "invalid attribute".
#[test]
#[should_panic(expected = "invalid attribute")]
fn sanitize_checks_attribute_before_constant() {
    WhereClause::new("a1", "==", "a;b");
}

/// An attribute containing a digit is rejected.
#[test]
#[should_panic(expected = "invalid attribute")]
fn sanitize_rejects_attribute_with_digit() {
    WhereClause::new("a1", "==", 1);
}

/// An attribute containing a space is rejected.
#[test]
#[should_panic(expected = "invalid attribute")]
fn sanitize_rejects_attribute_with_space() {
    WhereClause::new("a b", "==", 1);
}

/// An empty attribute is rejected.
#[test]
#[should_panic(expected = "invalid attribute")]
fn sanitize_rejects_empty_attribute() {
    WhereClause::new("", "==", 1);
}

/// An attribute with a non-ASCII letter such as `ä` is rejected. This is deliberately stricter than Python, whose
/// `isalpha` accepts it.
#[test]
#[should_panic(expected = "invalid attribute")]
fn sanitize_rejects_non_ascii_attribute() {
    WhereClause::new("ä", "==", 1);
}

/// A string constant containing a character other than a letter or digit, such as `;`, is rejected.
#[test]
#[should_panic(expected = "invalid constant")]
fn sanitize_rejects_constant_with_special_character() {
    WhereClause::new("a", "==", "a;b");
}

/// An empty string constant is rejected.
#[test]
#[should_panic(expected = "invalid constant")]
fn sanitize_rejects_empty_constant() {
    WhereClause::new("a", "==", "");
}

/// A string constant with a non-ASCII letter such as `ä` is rejected. This is deliberately stricter than Python,
/// whose `isalnum` accepts it.
#[test]
#[should_panic(expected = "invalid constant")]
fn sanitize_rejects_non_ascii_constant() {
    WhereClause::new("a", "==", "ä");
}

/// The getters return the attribute, operator and constant the clause was built with; an owned `String` is
/// accepted as constant, too.
#[test]
fn where_clause_getters_return_the_constructor_arguments() {
    let clause: WhereClause = WhereClause::new("b", ">=", String::from("abc"));
    assert_eq!(clause.attribute(), "b");
    assert_eq!(clause.operator(), Operator::Ge);
    assert_eq!(clause.constant(), &Scalar::Str("abc".to_string()));
}

/// A disjunction without clauses is false for every object, as Python's `any` of an empty sequence.
#[test]
fn empty_disjunction_is_false() {
    let disjunction: Disjunction<Stuff> = Disjunction::new(vec![]);
    assert!(!disjunction.evaluate(&Stuff { a: 10, b: 20 }));
}

/// A disjunction stops at the first clause that is true: a later clause on the missing attribute `x`, which would
/// panic, is not evaluated.
#[test]
fn disjunction_stops_at_first_true_clause() {
    let disjunction: Disjunction<Stuff> = Disjunction::new(vec![
        Box::new(WhereClause::new("a", "==", 10)),
        Box::new(WhereClause::new("x", "==", 1)),
    ]);
    assert!(disjunction.evaluate(&Stuff { a: 10, b: 20 }));
}

/// `TrueClause` is true and `FalseClause` is false for every object, whatever its type and attributes.
#[test]
fn true_and_false_clause_ignore_the_object() {
    let stuff: Stuff = Stuff { a: 10, b: 20 };
    let named_object: Named = named("abc");
    assert!(TrueClause.evaluate(&stuff));
    assert!(TrueClause.evaluate(&named_object));
    assert!(!FalseClause.evaluate(&stuff));
    assert!(!FalseClause.evaluate(&named_object));
}

/// A disjunction containing a `TrueClause` is true even if all other clauses are false; a disjunction of a
/// `FalseClause` and a false WHERE clause is false.
#[test]
fn disjunction_with_true_and_false_clause() {
    let stuff: Stuff = Stuff { a: 10, b: 20 };
    let with_true: Disjunction<Stuff> = Disjunction::new(vec![
        Box::new(FalseClause),
        Box::new(WhereClause::new("a", "==", 11)),
        Box::new(TrueClause),
    ]);
    assert!(with_true.evaluate(&stuff));

    let only_false: Disjunction<Stuff> = Disjunction::new(vec![
        Box::new(FalseClause),
        Box::new(WhereClause::new("a", "==", 11)),
    ]);
    assert!(!only_false.evaluate(&stuff));
}

/// The `Debug` output of a disjunction lists its clauses in order, so a printed query shows its filter.
#[test]
fn disjunction_debug_lists_its_clauses() {
    let clause: WhereClause = WhereClause::new("a", "<=", 10);
    let disjunction: Disjunction<Stuff> =
        Disjunction::new(vec![Box::new(clause.clone()), Box::new(TrueClause)]);
    assert_eq!(
        format!("{disjunction:?}"),
        format!("Disjunction {{ clauses: [{clause:?}, {TrueClause:?}] }}")
    );
}

/// `Operator::parse` and `Operator::symbol` are inverse to each other for all six operators.
#[test]
fn operator_parse_and_symbol_round_trip() {
    let operators: [(&str, Operator); 6] = [
        ("==", Operator::Eq),
        ("!=", Operator::Ne),
        ("<", Operator::Lt),
        ("<=", Operator::Le),
        (">", Operator::Gt),
        (">=", Operator::Ge),
    ];
    for (symbol, operator) in operators {
        assert_eq!(Operator::parse(symbol), Some(operator));
        assert_eq!(operator.symbol(), symbol);
    }
}

/// `Operator::parse` returns `None` for a symbol that is not one of the six operators, e.g. `=<`, `=`, `<>`, an
/// empty string or an operator with surrounding spaces.
#[test]
fn operator_parse_rejects_unknown_symbols() {
    for symbol in ["=<", "=", "<>", "", " <", "==="] {
        assert_eq!(Operator::parse(symbol), None, "{symbol:?}");
    }
}

/// Converting a `Scalar` to a `ScalarRef` and back gives the original value, for integers and strings.
#[test]
fn scalar_and_scalar_ref_round_trip() {
    let scalars: [Scalar; 4] = [
        Scalar::Int(-5),
        Scalar::Int(i64::MAX),
        Scalar::Str("abc".to_string()),
        Scalar::Str(String::new()),
    ];
    for scalar in scalars {
        let borrowed: ScalarRef<'_> = scalar.as_scalar_ref();
        assert_eq!(borrowed.to_scalar(), scalar);
    }
    assert_eq!(Scalar::from("abc").as_scalar_ref(), ScalarRef::Str("abc"));
}
