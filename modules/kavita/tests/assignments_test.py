import json

from kavita.assignments import reconcile_assignments
from kavita.matching import match_series_by_path, normalize_kavita_path
from kavita.pending import PendingAssignmentStore


def test_path_matching_is_exact_and_refuses_ambiguity():
    series = [
        {"id": 1, "folderPath": "/library/Series"},
        {"id": 2, "folderPath": "/library/Series Deluxe"},
    ]
    assert match_series_by_path(r"C:\library\Series", series, path_maps=[(r"C:\library", "/library")]) == series[0]
    assert match_series_by_path("/library/series", series) is None
    assert match_series_by_path("/library/Series", [series[0], dict(series[0])]) is None
    assert normalize_kavita_path("/library/Series/") == "/library/Series"


def test_pending_store_roundtrips_and_merges_duplicate_intent(tmp_path):
    path = tmp_path / "state" / "assignments.json"
    store = PendingAssignmentStore(path)
    store.enqueue("https://site.test/a", "/library/A", ["one"], kavita_url="http://kavita/")
    rows = store.enqueue("https://site.test/a", "/library/A", ["two", "one"], kavita_url="http://kavita")
    assert len(rows) == 1
    assert rows[0].collections == ["one", "two"]
    assert rows[0].kavita_url == "http://kavita"
    assert json.loads(path.read_text())['schema_version'] == 1


def test_reconcile_preview_keeps_unmatched_assignment_pending(tmp_path):
    class Client:
        def list_series(self):
            return [{"id": 8, "name": "A", "folderPath": "/library/A"}]

        def add_series_to_collection(self, name, ids, *, apply=False):
            return {"collection": name, "series_ids": ids, "applied": apply}

    store = PendingAssignmentStore(tmp_path / "assignments.json")
    store.enqueue("https://site.test/a", "/library/A", ["Shelf"], kavita_url="http://kavita")
    store.enqueue("https://site.test/b", "/library/B", ["Shelf"], kavita_url="http://kavita")
    result = reconcile_assignments(store, Client(), kavita_url="http://kavita")
    assert [row["status"] for row in result] == ["pending", "pending"]
    assert result[0]["series_id"] == 8
    assert result[1]["series_id"] is None
    assert all(not row.get("applied", False) for row in result)
    assert all(row.status == "pending" for row in store.load())


def test_reconcile_apply_marks_only_exact_match_applied(tmp_path):
    class Client:
        def list_series(self):
            return [{"id": 8, "name": "A", "folderPath": "/library/A"}]

        def add_series_to_collection(self, name, ids, *, apply=False):
            assert apply is True
            return {"collection": name, "series_ids": ids, "applied": True}

    store = PendingAssignmentStore(tmp_path / "assignments.json")
    store.enqueue("https://site.test/a", "/library/A", ["Shelf"], kavita_url="http://kavita")
    store.enqueue("https://site.test/b", "/library/B", ["Shelf"], kavita_url="http://kavita")
    result = reconcile_assignments(store, Client(), kavita_url="http://kavita", apply=True)
    rows = store.load()
    assert result[0]["status"] == "applied"
    assert rows[0].series_id == 8
    assert rows[1].status == "pending"
