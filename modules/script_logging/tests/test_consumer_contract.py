from pathlib import Path

from script_logging.reader import open_invocation_reader
from script_logging.tests.fixtures.synthetic_history import generate_synthetic_database


def test_consumer_query_contract_against_synthetic_data(tmp_path: Path):
    db_path = tmp_path / "synthetic.sqlite3"
    expected = generate_synthetic_database(db_path)

    reader = open_invocation_reader(db_path)

    # Check that program statistics match expected fixture counts
    for prog_id, prog_meta in expected["programs"].items():
        stats = reader.get_program_statistics(prog_id)
        assert stats.total_starts == prog_meta["total_starts"]
        assert stats.success_count == prog_meta["success_count"]
        assert stats.failure_count == prog_meta["failure_count"]

    # Verify query for unique patterns
    patterns_page = reader.list_unique_commands(limit=50)
    assert len(patterns_page.items) == expected["pattern_count"]

    # Verify query for program-specific unique patterns
    mangadl_patterns = reader.list_unique_commands(program_id="module:mangadl")
    assert len(mangadl_patterns.items) == expected["programs"]["module:mangadl"]["pattern_count"]

    # Verify sensitive token was redacted in stored pattern
    redacted_patterns = [p for p in mangadl_patterns.items if "--token=" in p.pattern_argv_json]
    assert len(redacted_patterns) == 1
    assert "--token=[REDACTED]" in redacted_patterns[0].pattern_argv_json
    assert "supersecret" not in redacted_patterns[0].pattern_argv_json

    # Verify invocation listing and pagination
    page1 = reader.list_invocations(limit=4)
    assert len(page1.items) == 4
    assert page1.has_more is True
    assert page1.next_cursor is not None

    page2 = reader.list_invocations(limit=10, cursor=page1.next_cursor)
    assert len(page2.items) == expected["total_invocations"] - 4
    assert page2.has_more is False
