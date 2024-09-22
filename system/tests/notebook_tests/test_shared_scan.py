from testbook import testbook
from faker import Faker


@testbook("Shared Scan.ipynb", execute=True)
def test_shared_scan(tb):
    # Get Enumerator functions from the notebooks
    fake = Faker()
    fake.seed_instance(42)

    Stuff = tb.ref("Stuff")
    scan = tb.ref("scan")
    shared_scan = tb.ref("shared_scan")

    data = [
        Stuff(fake.pyint(max_value=20), fake.pyint(max_value=20)) for _ in range(1000)
    ]

    # a dictionary with queries
    _queries_dict = {
        "q"
        + str(i): {
            "attribute": "a" if fake.pybool() else "b",
            "constant": fake.pyint(max_value=20),
        }
        for i in range(30)
    }
    # compute the result for all these queries by calling the scan()-method for each query independently:
    res1_dict = {
        query: scan(data, entry["attribute"], entry["constant"])
        for query, entry in _queries_dict.items()
    }

    # single call to the shared_scan-method:
    res2_dict = shared_scan(data, _queries_dict)

    assert res1_dict == res2_dict
