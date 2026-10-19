// Code generated from system/benchmarks/workloads.py, system/tests/benchmarks/test_store_benchmark.py. DO NOT EDIT.
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

//! Benchmark workloads of the MVCC store in Rust; their Python twin is `system/benchmarks/workloads.py`.
//!
//! Both implement the same workloads on the same data, with the same names and parameters, and print the same CSV
//! line per repetition, so that the runner (`python -m system.benchmarks.run`) can compare them. Run one workload
//! in `generated/rust/` with `cargo run --release --example workloads -- <workload> <method 1|2> <objects>
//! <operations> <repetitions>`. Python builds its stores with `new_store` where this program calls
//! `Store::with_validation`, and this program writes its where clauses with the helper [`clause`].
//!
//! The workloads stop the program (panic) when the store reports an error, as the Python twin raises one: the
//! workloads are built so that no error can occur.

use std::hint::black_box;
use std::rc::Rc;
use std::time::Instant;

use explaindb::{
    Attributes, Clause, ScalarRef, StoreError, TransactionalKeyValueStore, TransactionalStore,
    Validation, Version, VersionedStore, WhereClause,
};

/// A repetition repeats whole passes until their timed parts add up to at least this many seconds.
const MIN_SECONDS: f64 = 0.05;

/// A benchmark object with two integer attributes (Python: `Stuff` in `system/benchmarks/workloads.py`).
#[derive(Clone, Debug, PartialEq, Eq)]
struct Stuff {
    /// The attribute `a`.
    a: i64,
    /// The attribute `b`.
    b: i64,
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

/// What a pass did; Python and Rust must report the same fingerprint for the same workload.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Fingerprint {
    /// Committed transactions.
    commits: u64,
    /// Aborted transactions.
    aborts: u64,
    /// Objects returned by all reads (`read_objects` and `get`).
    objects_read: u64,
    /// The store's transaction counter after the pass (the next id it would hand out).
    transaction_counter: u64,
    /// Committed versions of all objects in the store after the pass, delete markers included.
    committed_versions: u64,
    /// Sum over the objects in store order of (position + 1) * b of their most recent committed version, so that it
    /// also shows which objects were updated.
    weighted_sum_of_b: i64,
}

/// One run of a workload on a fresh store.
struct Pass {
    /// The seconds of the timed part.
    seconds: f64,
    /// The operations in the timed part.
    operations: u64,
    /// What the pass did.
    fingerprint: Fingerprint,
}

/// The store type of all workloads.
type Store = TransactionalKeyValueStore<Stuff>;

/// A workload: (number of objects, validation method, operations) -> one pass; for `bulkload` and `get`, the
/// operations are the objects, one per object, and the operations argument is not used.
type Workload = fn(u64, Validation, u64) -> Pass;

/// Returns the objects ("0", Stuff), ("1", Stuff), ... of a store of the given size; the same formula as the
/// Python twin and `tests/common`, so both languages load the same data. Attribute `a` is unique for up to 1001
/// objects.
fn fake_data(number_of_objects: u64) -> Vec<(String, Stuff)> {
    (0..number_of_objects as i64)
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

/// Returns a store holding the objects of `fake_data(number_of_objects)`.
///
/// # Panics
///
/// Never: the ids of the data are unique.
fn filled_store(number_of_objects: u64, validation: Validation) -> Store {
    let mut store: Store = Store::with_validation(validation);
    store
        .bulkload(fake_data(number_of_objects))
        .expect("the ids are unique");
    store
}

/// Returns a where clause `attribute operator constant` as the clause type `read_objects` takes.
fn clause(attribute: &str, operator: &str, constant: i64) -> Option<Rc<dyn Clause<Stuff>>> {
    Some(Rc::new(WhereClause::new(attribute, operator, constant)))
}

/// Returns the fingerprint of a pass from the counts of the workload and the state of `store`.
fn fingerprint(store: &Store, commits: u64, aborts: u64, objects_read: u64) -> Fingerprint {
    let mut committed_versions: u64 = 0;
    let mut weighted_sum_of_b: i64 = 0;
    for (position, entry) in store.key_value_store().values().enumerate() {
        committed_versions += entry.committed.len() as u64;
        if let Some(last) = entry.committed.last()
            && let Version::Update(value) = &last.version
        {
            weighted_sum_of_b += (position as i64 + 1) * value.b;
        }
    }
    Fingerprint {
        commits,
        aborts,
        objects_read,
        transaction_counter: store.state().ta_id,
        committed_versions,
        weighted_sum_of_b,
    }
}

/// Times loading `number_of_objects` objects into an empty store; one operation per object.
///
/// # Panics
///
/// Never: the ids of the data are unique.
fn bulkload(number_of_objects: u64, validation: Validation, _operations: u64) -> Pass {
    // the data is built before the timer starts; bulkload consumes it:
    let input: Vec<(String, Stuff)> = fake_data(number_of_objects);
    let mut store: Store = Store::with_validation(validation);
    let start: Instant = Instant::now();
    store.bulkload(input).expect("the ids are unique");
    let seconds: f64 = start.elapsed().as_secs_f64();
    Pass {
        seconds,
        operations: number_of_objects,
        fingerprint: fingerprint(&store, 0, 0, 0),
    }
}

/// Times one non-transactional `get` of every object of a filled store; one operation per get.
///
/// # Panics
///
/// Never: every id was loaded.
fn get(number_of_objects: u64, validation: Validation, _operations: u64) -> Pass {
    let store: Store = filled_store(number_of_objects, validation);
    let ids: Vec<String> = (0..number_of_objects).map(|i| i.to_string()).collect();
    let start: Instant = Instant::now();
    for object_id in &ids {
        // black_box keeps the compiler from dropping a read whose result is not used:
        black_box(store.get(object_id).expect("every id was loaded"));
    }
    let seconds: f64 = start.elapsed().as_secs_f64();
    Pass {
        seconds,
        operations: number_of_objects,
        fingerprint: fingerprint(&store, 0, 0, ids.len() as u64),
    }
}

/// Times `reads` reads of `a == 42` in one transaction on a filled store, without keeping them in the read set;
/// each read scans all objects. One operation per read.
///
/// # Panics
///
/// Never: the transaction runs and reads only.
fn read(number_of_objects: u64, validation: Validation, reads: u64) -> Pass {
    let mut store: Store = filled_store(number_of_objects, validation);
    let where_clause: Option<Rc<dyn Clause<Stuff>>> = clause("a", "==", 42);
    let ta_id: u64 = store.begin_transaction();
    let mut objects_read: u64 = 0;
    let start: Instant = Instant::now();
    for _ in 0..reads {
        let result: Vec<(String, Stuff)> = store
            // false: do not keep the reads in the read set
            .read_objects(ta_id, where_clause.clone(), false)
            .expect("the transaction is running");
        // black_box keeps the compiler from skipping work whose result is only counted:
        objects_read += black_box(result).len() as u64;
    }
    let seconds: f64 = start.elapsed().as_secs_f64();
    store
        .commit_transaction(ta_id)
        .expect("a read-only transaction commits");
    Pass {
        seconds,
        operations: reads,
        fingerprint: fingerprint(&store, 1, 0, objects_read),
    }
}

/// Times `transactions` transactions on a filled store, each updating object `i mod number_of_objects` (b + 1) and
/// committing; one operation per transaction.
///
/// # Panics
///
/// Never: no other transaction runs.
fn update_commit(number_of_objects: u64, validation: Validation, transactions: u64) -> Pass {
    let data: Vec<(String, Stuff)> = fake_data(number_of_objects);
    let mut store: Store = filled_store(number_of_objects, validation);
    // the current values, kept outside the store, so the transactions need no read:
    let mut current: Vec<Stuff> = data.into_iter().map(|(_, value)| value).collect();
    let start: Instant = Instant::now();
    for i in 0..transactions {
        let index: usize = (i % number_of_objects) as usize;
        let ta_id: u64 = store.begin_transaction();
        let updated: Stuff = Stuff {
            a: current[index].a,
            b: current[index].b + 1,
        };
        store
            .update_object(&index.to_string(), updated.clone(), ta_id)
            .expect("no other transaction runs");
        store
            .commit_transaction(ta_id)
            .expect("no other transaction runs");
        current[index] = updated;
    }
    let seconds: f64 = start.elapsed().as_secs_f64();
    Pass {
        seconds,
        operations: transactions,
        fingerprint: fingerprint(&store, transactions, 0, 0),
    }
}

/// Times `transactions` transactions on a filled store, each reading `a < 100` and committing; one operation per
/// transaction.
///
/// # Panics
///
/// Never: the transactions only read.
fn read_only(number_of_objects: u64, validation: Validation, transactions: u64) -> Pass {
    let mut store: Store = filled_store(number_of_objects, validation);
    let mut objects_read: u64 = 0;
    let start: Instant = Instant::now();
    for _ in 0..transactions {
        let ta_id: u64 = store.begin_transaction();
        let result: Vec<(String, Stuff)> = store
            .read_objects(ta_id, clause("a", "<", 100), true) // true: keep the read for validation
            .expect("the transaction is running");
        // black_box keeps the compiler from skipping work whose result is only counted:
        objects_read += black_box(result).len() as u64;
        store
            .commit_transaction(ta_id)
            .expect("a read-only transaction commits");
    }
    let seconds: f64 = start.elapsed().as_secs_f64();
    Pass {
        seconds,
        operations: transactions,
        fingerprint: fingerprint(&store, transactions, 0, objects_read),
    }
}

/// Times `transactions` transactions on a filled store, transaction i reading object `i mod number_of_objects` by
/// its attribute a (unique for up to 1001 objects), updating it (b + 1) and committing; there are no conflicts. One
/// operation per transaction.
///
/// # Panics
///
/// Never: no other transaction runs.
fn read_write_disjoint(number_of_objects: u64, validation: Validation, transactions: u64) -> Pass {
    let data: Vec<(String, Stuff)> = fake_data(number_of_objects);
    let mut store: Store = filled_store(number_of_objects, validation);
    let mut objects_read: u64 = 0;
    let start: Instant = Instant::now();
    for i in 0..transactions {
        let index: usize = (i % number_of_objects) as usize;
        let ta_id: u64 = store.begin_transaction();
        let result: Vec<(String, Stuff)> = store
            .read_objects(ta_id, clause("a", "==", data[index].1.a), true) // true: keep the read for validation
            .expect("the transaction is running");
        objects_read += result.len() as u64;
        let (object_id, value): &(String, Stuff) = &result[0];
        store
            .update_object(
                object_id,
                Stuff {
                    a: value.a,
                    b: value.b + 1,
                },
                ta_id,
            )
            .expect("no other transaction runs");
        store
            .commit_transaction(ta_id)
            .expect("no other transaction runs");
    }
    let seconds: f64 = start.elapsed().as_secs_f64();
    Pass {
        seconds,
        operations: transactions,
        fingerprint: fingerprint(&store, transactions, 0, objects_read),
    }
}

/// Lets transaction `ta_id` read the hot set (a < 10) and update hot object `object_id` (b + 1); returns the
/// number of objects read.
///
/// # Panics
///
/// If the read fails, the object is not in its result, or the update fails.
fn read_and_increment_b(store: &mut Store, ta_id: u64, object_id: &str) -> u64 {
    let result: Vec<(String, Stuff)> = store
        .read_objects(ta_id, clause("a", "<", 10), true) // true: keep the read for validation
        .expect("the transaction is running");
    let Some((_, old)) = result.iter().find(|(id, _)| id == object_id) else {
        panic!("the read result contains object {object_id}")
    };
    let new: Stuff = Stuff {
        a: old.a,
        b: old.b + 1,
    };
    store
        .update_object(object_id, new, ta_id)
        .expect("no other transaction writes this object");
    result.len() as u64
}

/// Times `transactions / 2` rounds of two interleaved transactions on a filled store; the second of each round fails
/// validation, as the first changed an object it read.
///
/// The hot set is the objects with a < 10. In round j:
///
/// ```text
/// t1                                  t2
/// begin
///                                     begin
/// read a < 10
/// update hot object 2j (b + 1)
///                                     read a < 10
///                                     update hot object 2j + 1 (b + 1)
/// commit
///                                     commit -> aborted
/// ```
///
/// One operation per transaction (committed or aborted).
///
/// # Panics
///
/// If the hot set has fewer than two objects, or a commit fails with another error than an abort.
fn read_write_contention(
    number_of_objects: u64,
    validation: Validation,
    transactions: u64,
) -> Pass {
    let mut store: Store = filled_store(number_of_objects, validation);
    let hot: Vec<String> = fake_data(number_of_objects)
        .into_iter()
        .filter(|(_, value)| value.a < 10)
        .map(|(object_id, _)| object_id)
        .collect();
    assert!(hot.len() >= 2, "the hot set needs at least two objects");
    let mut commits: u64 = 0;
    let mut aborts: u64 = 0;
    let mut objects_read: u64 = 0;
    let start: Instant = Instant::now();
    for j in 0..(transactions / 2) as usize {
        let t1: u64 = store.begin_transaction();
        let t2: u64 = store.begin_transaction();
        objects_read += read_and_increment_b(&mut store, t1, &hot[(2 * j) % hot.len()]);
        objects_read += read_and_increment_b(&mut store, t2, &hot[(2 * j + 1) % hot.len()]);
        for ta_id in [t1, t2] {
            match store.commit_transaction(ta_id) {
                Ok(()) => commits += 1,
                Err(StoreError::TransactionAborted(_)) => aborts += 1,
                Err(error) => panic!("unexpected error: {error}"),
            }
        }
    }
    let seconds: f64 = start.elapsed().as_secs_f64();
    Pass {
        seconds,
        operations: 2 * (transactions / 2),
        fingerprint: fingerprint(&store, commits, aborts, objects_read),
    }
}

/// Returns the workload of the given name, as the runner and the Python twin name it, or `None`.
fn workload(name: &str) -> Option<Workload> {
    match name {
        "bulkload" => Some(bulkload),
        "get" => Some(get),
        "read" => Some(read),
        "update_commit" => Some(update_commit),
        "read_only" => Some(read_only),
        "read_write_disjoint" => Some(read_write_disjoint),
        "read_write_contention" => Some(read_write_contention),
        _ => None,
    }
}

/// One repetition: passes repeated until at least `MIN_SECONDS` of timed work.
struct Repetition {
    /// Timed seconds of all passes divided by their timed operations.
    seconds_per_operation: f64,
    /// The number of passes run.
    passes: u64,
    /// The fingerprint, the same for every pass.
    fingerprint: Fingerprint,
}

/// Runs whole passes of `workload` (each on a fresh store) until their timed parts add up to `min_seconds`.
///
/// # Panics
///
/// If a pass times no operation (it could never add up to `min_seconds`), or if two passes report different
/// fingerprints.
fn repetition(
    workload: Workload,
    number_of_objects: u64,
    validation: Validation,
    operations: u64,
    min_seconds: f64,
) -> Repetition {
    let mut seconds: f64 = 0.0;
    let mut timed_operations: u64 = 0;
    let mut passes: u64 = 0;
    let mut first: Option<Fingerprint> = None;
    while seconds < min_seconds || passes == 0 {
        let result: Pass = workload(number_of_objects, validation, operations);
        assert!(
            result.operations >= 1,
            "a pass must time at least one operation"
        );
        let expected: Fingerprint = *first.get_or_insert(result.fingerprint);
        assert_eq!(
            result.fingerprint, expected,
            "all passes must do the same work"
        );
        seconds += result.seconds;
        timed_operations += result.operations;
        passes += 1;
    }
    Repetition {
        seconds_per_operation: seconds / timed_operations as f64,
        passes,
        fingerprint: first.expect("at least one pass ran"),
    }
}

/// Returns the CSV line of a repetition: seconds per operation, passes and the fingerprint fields in order.
fn csv_line(result: &Repetition) -> String {
    let fp: Fingerprint = result.fingerprint;
    format!(
        "{:?},{},{},{},{},{},{},{}",
        result.seconds_per_operation,
        result.passes,
        fp.commits,
        fp.aborts,
        fp.objects_read,
        fp.transaction_counter,
        fp.committed_versions,
        fp.weighted_sum_of_b
    )
}

/// The command line of the program: what to run and how often.
struct Arguments {
    /// The workload.
    workload: Workload,
    /// The validation method.
    validation: Validation,
    /// The number of objects, at least 1.
    objects: u64,
    /// Reads or transactions per pass, at least 1.
    operations: u64,
    /// Repetitions after the warm-up, at least 1.
    repetitions: u64,
}

/// Returns `text` as a number of at least 1, written with ASCII digits only.
///
/// # Errors
///
/// A message naming `what` if `text` is not a number of at least 1.
fn positive(text: &str, what: &str) -> Result<u64, String> {
    // only ASCII digits, as the Python twin accepts them (parse alone would also accept a leading +):
    match text.parse::<u64>() {
        Ok(value) if value >= 1 && text.bytes().all(|byte| byte.is_ascii_digit()) => Ok(value),
        _ => Err(format!("{what} must be a number of at least 1, not {text}")),
    }
}

/// Parses the command line: workload, validation method (1 or 2), objects, operations, repetitions.
///
/// # Errors
///
/// A message if an argument is missing, unknown or not a number of at least 1.
fn parse_arguments(arguments: &[String]) -> Result<Arguments, String> {
    let [name, method, objects, operations, repetitions] = arguments else {
        return Err(
            "usage: workloads <workload> <method 1|2> <objects> <operations> <repetitions>"
                .to_string(),
        );
    };
    let workload: Workload = workload(name).ok_or(format!("unknown workload {name}"))?;
    let validation: Validation = match method.as_str() {
        "1" => Validation::BruteForce,
        "2" => Validation::WriteSets,
        _ => return Err(format!("the method must be 1 or 2, not {method}")),
    };
    Ok(Arguments {
        workload,
        validation,
        objects: positive(objects, "objects")?,
        operations: positive(operations, "operations")?,
        repetitions: positive(repetitions, "repetitions")?,
    })
}

/// Runs a workload and prints one CSV line per repetition after a warm-up repetition, as the Python twin does; on
/// wrong arguments, prints a message and exits with status 2.
fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let arguments: Arguments = match parse_arguments(&arguments) {
        Ok(arguments) => arguments,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(2);
        }
    };
    let run = || {
        repetition(
            arguments.workload,
            arguments.objects,
            arguments.validation,
            arguments.operations,
            MIN_SECONDS,
        )
    };
    run();
    for _ in 0..arguments.repetitions {
        println!("{}", csv_line(&run()));
    }
}

#[cfg(test)]
mod tests {
    //! Tests of the workloads, the harness and the command line.
    //!
    //! The fingerprints on small stores are the same numbers that `system/tests/benchmarks/test_store_benchmark.py`
    //! asserts for the Python twin with the same parameters, so both languages must agree.
    //!
    //! The data of `fake_data(n)`: object i is at position i of the store and has a = (i * 37) % 1001 and
    //! b = (i * 53) % 2001; the last fingerprint field is the sum of (i + 1) * b_i over the objects.
    //! - For n = 10, b_i = 53 * i, so the weighted sum is 53 * (0*1 + 1*2 + ... + 9*10) = 53 * 330 = 17 490, and
    //!   exactly the objects 0, 1, 2 (a = 0, 37, 74) have a < 100.
    //! - a == 42 holds for object 434 only, so `read` needs a store of 435 objects to find something.
    //! - The hot set a < 10 is the objects 0, 379, 406, 433, 460, 487, 893, 920, 947, 974; a store of 380 objects has
    //!   the smallest hot set of two objects: 0 and 379, a store of 1 000 objects has all ten.
    //! - For n = 380, 435 and 1 000, b wraps around 2001, so the weighted sums are only given by their definition.

    use super::*;
    use std::cell::Cell;

    /// The weighted sum of b of `fake_data(10)`: 53 * 330.
    const WEIGHTED_SUM_OF_B_10: i64 = 17_490;
    /// The weighted sum of b of `fake_data(380)`, i.e. the sum of (i + 1) * ((i * 53) % 2001) for i < 380.
    const WEIGHTED_SUM_OF_B_380: i64 = 74_321_305;
    /// The weighted sum of b of `fake_data(435)`.
    const WEIGHTED_SUM_OF_B_435: i64 = 93_888_631;
    /// The weighted sum of b of `fake_data(1000)`.
    const WEIGHTED_SUM_OF_B_1000: i64 = 498_335_133;

    /// Returns a fingerprint from its fields in the order both programs print them.
    fn fingerprint_of(
        commits: u64,
        aborts: u64,
        objects_read: u64,
        transaction_counter: u64,
        committed_versions: u64,
        weighted_sum_of_b: i64,
    ) -> Fingerprint {
        Fingerprint {
            commits,
            aborts,
            objects_read,
            transaction_counter,
            committed_versions,
            weighted_sum_of_b,
        }
    }

    /// One expected pass: the workload with its arguments and what the pass must report.
    struct Case {
        /// The workload's name.
        name: &'static str,
        /// The store size.
        objects: u64,
        /// The reads or transactions asked for.
        operations: u64,
        /// The operations the pass must time.
        timed_operations: u64,
        /// The fingerprint the pass must report.
        fingerprint: Fingerprint,
    }

    /// Asserts that one pass of each case has the expected fingerprint and timed operations with each of
    /// `validations`.
    fn assert_passes(cases: &[Case], validations: &[Validation]) {
        for case in cases {
            for &validation in validations {
                let workload: Workload = workload(case.name).expect("a known workload");
                let result: Pass = workload(case.objects, validation, case.operations);
                let context: String = format!(
                    "{} on {} objects with {} operations and {validation:?}",
                    case.name, case.objects, case.operations
                );
                assert_eq!(result.fingerprint, case.fingerprint, "{context}");
                assert_eq!(result.operations, case.timed_operations, "{context}");
            }
        }
    }

    /// Every workload has on a small store the fingerprint the Python twin reports for the same parameters, with
    /// both validation methods: 20 transactions on 10 objects update every object twice (b + 2, which adds
    /// 2 * (1 + ... + 10) = 110 to the weighted sum) and take two ids each (counter 1 + 2 * 20 = 41); 10 reads on 435
    /// objects find object 434 each; 20 transactions on 380 objects are 10 rounds as in the schedule of the
    /// [`read_write_contention`] docs, in which the update of object 0 (weight 1) commits and the one of object 379
    /// aborts, each transaction reading both hot objects. Would fail if the Rust workloads drifted from the Python
    /// ones.
    #[test]
    fn fingerprints_on_small_stores_match_python() {
        let updated_twice: Fingerprint =
            fingerprint_of(20, 0, 0, 41, 10 + 20, WEIGHTED_SUM_OF_B_10 + 110);
        assert_passes(
            &[
                // for bulkload and get, the operations are the objects, one per object:
                Case {
                    name: "bulkload",
                    objects: 10,
                    operations: 20,
                    timed_operations: 10,
                    fingerprint: fingerprint_of(0, 0, 0, 1, 10, WEIGHTED_SUM_OF_B_10),
                },
                Case {
                    name: "get",
                    objects: 10,
                    operations: 20,
                    timed_operations: 10,
                    fingerprint: fingerprint_of(0, 0, 10, 1, 10, WEIGHTED_SUM_OF_B_10),
                },
                // one transaction (ids 1 and 2):
                Case {
                    name: "read",
                    objects: 435,
                    operations: 10,
                    timed_operations: 10,
                    fingerprint: fingerprint_of(1, 0, 10, 3, 435, WEIGHTED_SUM_OF_B_435),
                },
                Case {
                    name: "update_commit",
                    objects: 10,
                    operations: 20,
                    timed_operations: 20,
                    fingerprint: updated_twice,
                },
                // a < 100 holds for 3 objects:
                Case {
                    name: "read_only",
                    objects: 10,
                    operations: 20,
                    timed_operations: 20,
                    fingerprint: fingerprint_of(20, 0, 20 * 3, 41, 10, WEIGHTED_SUM_OF_B_10),
                },
                Case {
                    name: "read_write_disjoint",
                    objects: 10,
                    operations: 20,
                    timed_operations: 20,
                    fingerprint: fingerprint_of(20, 0, 20, 41, 10 + 20, WEIGHTED_SUM_OF_B_10 + 110),
                },
                Case {
                    name: "read_write_contention",
                    objects: 380,
                    operations: 20,
                    timed_operations: 20,
                    fingerprint: fingerprint_of(
                        10,
                        10,
                        10 * 4,
                        41,
                        380 + 10,
                        WEIGHTED_SUM_OF_B_380 + 10,
                    ),
                },
            ],
            &[Validation::BruteForce, Validation::WriteSets],
        );
    }

    /// Realistic runs on 1 000 objects report the fingerprints measured with the benchmark program: 100 reads find
    /// object 434 each; 500 rounds of contention (see the schedule in the [`read_write_contention`] docs) read the 10
    /// hot objects per transaction, and the first transaction of each round updates one of the hot objects 0, 406,
    /// 460, 893, 947 (positions + 1: 1, 407, 461, 894, 948), each 100 times, which adds 100 * 2711 = 271 100 to the
    /// weighted sum. Would fail if a workload behaved differently on a store of the size the runner measures.
    #[test]
    fn fingerprints_of_realistic_runs() {
        assert_passes(
            &[
                Case {
                    name: "bulkload",
                    objects: 1000,
                    operations: 1000,
                    timed_operations: 1000,
                    fingerprint: fingerprint_of(0, 0, 0, 1, 1000, WEIGHTED_SUM_OF_B_1000),
                },
                Case {
                    name: "read",
                    objects: 1000,
                    operations: 100,
                    timed_operations: 100,
                    fingerprint: fingerprint_of(1, 0, 100, 3, 1000, WEIGHTED_SUM_OF_B_1000),
                },
            ],
            &[Validation::WriteSets],
        );
        assert_passes(
            &[Case {
                name: "read_write_contention",
                objects: 1000,
                operations: 1000,
                timed_operations: 1000,
                fingerprint: fingerprint_of(
                    500,
                    500,
                    10_000,
                    2001,
                    1500,
                    WEIGHTED_SUM_OF_B_1000 + 271_100,
                ),
            }],
            &[Validation::BruteForce],
        );
    }

    /// 20 transactions of contention on 1 000 objects form 10 rounds as in the schedule of the
    /// [`read_write_contention`] docs and rotate through all ten hot objects 0, 379, 406, 433, 460, 487, 893, 920,
    /// 947, 974, with both validation methods; the Python twin reports the same fingerprint.
    ///
    /// Round j updates hot[2j mod 10] in its first, committing transaction and hot[2j + 1 mod 10] in its second,
    /// aborted one; so the commits update 0, 406, 460, 893, 947 (positions + 1: 1, 407, 461, 894, 948, sum 2711)
    /// twice each, which adds 2 * 2711 = 5422 to the weighted sum, and the second visit reads the first update
    /// (b + 2). Each transaction reads the 10 hot objects (20 * 10 = 200), takes two ids (1 + 2 * 20 = 41), and the
    /// 10 commits add 10 versions. Would fail if the rotation `mod hot.len()` broke, the rounds updated other hot
    /// objects, or a later round updated a stale value.
    #[test]
    fn contention_rotates_through_the_hot_set() {
        assert_passes(
            &[Case {
                name: "read_write_contention",
                objects: 1000,
                operations: 20,
                timed_operations: 20,
                fingerprint: fingerprint_of(
                    10,
                    10,
                    20 * 10,
                    41,
                    1000 + 10,
                    WEIGHTED_SUM_OF_B_1000 + 5422,
                ),
            }],
            &[Validation::BruteForce, Validation::WriteSets],
        );
    }

    /// The weighted sums of b used in the expected fingerprints are the sum of (i + 1) * b_i over `fake_data(n)`;
    /// would fail if a constant had a typo, which would make the fingerprint tests of both languages wrong alike.
    #[test]
    fn weighted_sums_of_b_follow_from_their_definition() {
        assert_eq!(
            WEIGHTED_SUM_OF_B_10,
            (0..10i64).map(|i| (i + 1) * ((i * 53) % 2001)).sum()
        );
        assert_eq!(
            WEIGHTED_SUM_OF_B_380,
            (0..380i64).map(|i| (i + 1) * ((i * 53) % 2001)).sum()
        );
        assert_eq!(
            WEIGHTED_SUM_OF_B_435,
            (0..435i64).map(|i| (i + 1) * ((i * 53) % 2001)).sum()
        );
        assert_eq!(
            WEIGHTED_SUM_OF_B_1000,
            (0..1000i64).map(|i| (i + 1) * ((i * 53) % 2001)).sum()
        );
    }

    /// 21 transactions of contention form 10 rounds of two (see the schedule in the [`read_write_contention`] docs),
    /// the same work as 20 transactions, and the pass times the 20 transactions it ran; would fail if the seconds per
    /// operation were divided by the 21 transactions asked for, or the odd transaction began without a partner.
    #[test]
    fn contention_with_an_odd_number_of_transactions() {
        let odd: Pass = read_write_contention(380, Validation::WriteSets, 21);
        let even: Pass = read_write_contention(380, Validation::WriteSets, 20);
        assert_eq!(odd.operations, 20);
        assert_eq!(odd.fingerprint, even.fingerprint);
    }

    /// The contention workload panics on a store of 10 objects, whose hot set is object 0 only, as the schedule in
    /// the [`read_write_contention`] docs needs two hot objects per round; would fail if both transactions of a
    /// round updated the same object, which would measure other work.
    #[test]
    #[should_panic(expected = "the hot set needs at least two objects")]
    fn contention_needs_two_hot_objects() {
        read_write_contention(10, Validation::WriteSets, 20);
    }

    /// With `min_seconds` 0, a repetition runs exactly one pass and reports its fingerprint; would fail if the loop
    /// could end before the first pass.
    #[test]
    fn repetition_with_zero_min_seconds_runs_one_pass() {
        let result: Repetition = repetition(bulkload, 10, Validation::WriteSets, 20, 0.0);
        assert_eq!(result.passes, 1);
        assert_eq!(
            result.fingerprint,
            fingerprint_of(0, 0, 0, 1, 10, WEIGHTED_SUM_OF_B_10)
        );
    }

    /// A fake pass of 0.01 seconds with 4 operations and a fixed fingerprint.
    fn constant_workload(
        _number_of_objects: u64,
        _validation: Validation,
        _operations: u64,
    ) -> Pass {
        Pass {
            seconds: 0.01,
            operations: 4,
            fingerprint: fingerprint_of(0, 0, 0, 1, 0, 0),
        }
    }

    /// Passes of 0.01 seconds repeat until 0.025 seconds are reached (3 passes), and the seconds per operation
    /// divide by the operations of all passes (0.03 / 12); would fail if the harness stopped early or divided by
    /// the operations of one pass only.
    #[test]
    fn repetition_divides_by_the_operations_of_all_passes() {
        let result: Repetition = repetition(constant_workload, 10, Validation::WriteSets, 1, 0.025);
        assert_eq!(result.passes, 3);
        assert!((result.seconds_per_operation - 0.0025).abs() < 1e-12);
    }

    thread_local! {
        /// Counts the passes of [`changing_workload`] in the thread of the test.
        static CHANGING_PASSES: Cell<u64> = const { Cell::new(0) };
    }

    /// A fake pass that takes no time and reports another number of commits each time.
    fn changing_workload(
        _number_of_objects: u64,
        _validation: Validation,
        _operations: u64,
    ) -> Pass {
        let passes: u64 = CHANGING_PASSES.get();
        CHANGING_PASSES.set(passes + 1);
        Pass {
            seconds: 0.0,
            operations: 1,
            fingerprint: fingerprint_of(passes, 0, 0, 1, 0, 0),
        }
    }

    /// A repetition panics if two passes report different fingerprints; would fail if a workload that does
    /// different work in each pass went unnoticed.
    #[test]
    #[should_panic(expected = "all passes must do the same work")]
    fn repetition_panics_on_different_fingerprints() {
        repetition(changing_workload, 10, Validation::WriteSets, 1, 1.0);
    }

    /// A repetition panics if a pass times no operation, e.g. contention with one transaction (no complete round),
    /// instead of repeating it forever; would fail if such a repetition looped or divided by zero.
    #[test]
    #[should_panic(expected = "a pass must time at least one operation")]
    fn repetition_panics_on_a_pass_without_operations() {
        repetition(read_write_contention, 380, Validation::WriteSets, 1, 1.0);
    }

    /// The CSV line holds seconds per operation, passes and the six fingerprint fields in the order the runner reads
    /// them; would fail if a field were missing or moved.
    #[test]
    fn csv_line_field_order() {
        let result: Repetition = Repetition {
            seconds_per_operation: 1.234567890123e-7,
            passes: 3,
            fingerprint: fingerprint_of(1, 2, 3, 4, 5, 6),
        };
        assert_eq!(csv_line(&result), "1.234567890123e-7,3,1,2,3,4,5,6");
    }

    /// Returns `arguments` as the owned strings `parse_arguments` takes.
    fn strings(arguments: &[&str]) -> Vec<String> {
        arguments
            .iter()
            .map(|argument| argument.to_string())
            .collect()
    }

    /// Returns the error message of `parse_arguments` for `arguments`.
    ///
    /// # Panics
    ///
    /// If the arguments are accepted.
    fn parse_error(arguments: &[&str]) -> String {
        parse_arguments(&strings(arguments))
            .err()
            .expect("the arguments are rejected")
    }

    /// A correct command line gives the workload, the validation method and the three numbers in the order of the
    /// usage; would fail if the arguments were read in another order than the runner passes them.
    #[test]
    fn parse_arguments_accepts_a_correct_command_line() {
        let arguments: Arguments = parse_arguments(&strings(&["get", "1", "10", "20", "3"]))
            .expect("a correct command line");
        assert_eq!(arguments.validation, Validation::BruteForce);
        assert_eq!(
            (
                arguments.objects,
                arguments.operations,
                arguments.repetitions
            ),
            (10, 20, 3)
        );
        // only `get` reads every object without a transaction:
        let result: Pass = (arguments.workload)(
            arguments.objects,
            arguments.validation,
            arguments.operations,
        );
        assert_eq!(
            result.fingerprint,
            fingerprint_of(0, 0, 10, 1, 10, WEIGHTED_SUM_OF_B_10)
        );
        let method_2: Arguments = parse_arguments(&strings(&["get", "2", "10", "20", "3"]))
            .expect("a correct command line");
        assert_eq!(method_2.validation, Validation::WriteSets);
    }

    /// A command line with too few or too many arguments is rejected with the usage; would fail if a missing
    /// argument were taken from the next one.
    #[test]
    fn parse_arguments_rejects_a_wrong_number_of_arguments() {
        assert!(parse_error(&["get", "2", "10", "20"]).starts_with("usage: workloads"));
        assert!(parse_error(&["get", "2", "10", "20", "3", "4"]).starts_with("usage: workloads"));
    }

    /// An unknown workload, method 3, 0 objects, 0 operations, operations that are no number and 0 repetitions are
    /// rejected with a message naming the wrong argument; would fail if a wrong command line ran a benchmark.
    #[test]
    fn parse_arguments_rejects_wrong_values() {
        assert_eq!(
            parse_error(&["bulk_load", "2", "10", "20", "3"]),
            "unknown workload bulk_load"
        );
        assert_eq!(
            parse_error(&["get", "3", "10", "20", "3"]),
            "the method must be 1 or 2, not 3"
        );
        assert_eq!(
            parse_error(&["get", "2", "0", "20", "3"]),
            "objects must be a number of at least 1, not 0"
        );
        assert_eq!(
            parse_error(&["get", "2", "10", "ten", "3"]),
            "operations must be a number of at least 1, not ten"
        );
        assert_eq!(
            parse_error(&["get", "2", "10", "0", "3"]),
            "operations must be a number of at least 1, not 0"
        );
        assert_eq!(
            parse_error(&["get", "2", "10", "20", "0"]),
            "repetitions must be a number of at least 1, not 0"
        );
        // a leading + is rejected, as by the Python twin:
        assert_eq!(
            parse_error(&["get", "2", "+7", "20", "3"]),
            "objects must be a number of at least 1, not +7"
        );
    }
}
