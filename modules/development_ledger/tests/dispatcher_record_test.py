from __future__ import annotations

import pytest

from development_ledger import dispatcher_record


@pytest.mark.parametrize(
    ("record_result", "expected"),
    [
        (0, 0),
        (1, 0),
        (2, 2),
    ],
)
def test_dispatcher_record_preserves_recording_failures(
    monkeypatch: pytest.MonkeyPatch,
    record_result: int,
    expected: int,
):
    calls: list[list[str]] = []

    def fake_main(arguments: list[str]) -> int:
        calls.append(arguments)
        return record_result

    monkeypatch.setattr(dispatcher_record, "ledger_main", fake_main)

    result = dispatcher_record.main(["-p", "plan.md", "-o", "ledger", "-r", ".", "-w"])

    assert result == expected
    assert calls == [["record", "-p", "plan.md", "-o", "ledger", "-r", ".", "-w"]]
