from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_benchmark.evidence import load_task
from agent_benchmark.cli import parser
from agent_benchmark.instruction_overlay import apply_instruction_append, load_instruction_append


TASK = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks/qwen-runmux-polling-lifecycle"


def test_instruction_append_preserves_task_and_records_exact_file_hash(tmp_path: Path) -> None:
    content = "Contract checklist:\n- Preserve single-flight while an abort is pending.\n"
    overlay_path = tmp_path / "checklist.md"
    overlay_path.write_bytes(content.encode("utf-8"))

    task = load_task(TASK)
    overlay = load_instruction_append(overlay_path)
    updated = apply_instruction_append(task, overlay)

    assert updated.instruction == task.instruction + "\n\n" + content
    assert task.instruction not in ("", updated.instruction)
    assert overlay.sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert overlay.byte_length == len(content.encode("utf-8"))
    assert overlay.path == overlay_path.resolve()


@pytest.mark.parametrize("content", [b"", b" \r\n ", b"\xff"])
def test_instruction_append_rejects_empty_or_invalid_utf8(tmp_path: Path, content: bytes) -> None:
    overlay_path = tmp_path / "invalid.md"
    overlay_path.write_bytes(content)

    with pytest.raises(ValueError):
        load_instruction_append(overlay_path)


@pytest.mark.parametrize("command", ["plan", "run"])
def test_experiment_commands_accept_instruction_append_file(tmp_path: Path, command: str) -> None:
    path = tmp_path / "checklist.md"
    args = parser().parse_args([
        "experiment", command, "-m", "qwen38-27b-q4km", "--instruction-append-file", str(path),
    ])

    assert args.instruction_append_file == path


def test_experiment_plan_records_instruction_append_identity(tmp_path: Path, monkeypatch, capsys) -> None:
    from agent_benchmark import cli

    content = "Contract checklist:\n- Queue one follow-up after settlement.\n"
    overlay_path = tmp_path / "checklist.md"
    overlay_path.write_bytes(content.encode("utf-8"))

    def consume_readiness(coroutine):
        coroutine.close()
        return []

    monkeypatch.setattr(cli.asyncio, "run", consume_readiness)
    assert cli.main([
        "experiment", "plan", "-m", "qwen38-27b-q4km", "-t", str(TASK),
        "--instruction-append-file", str(overlay_path),
    ]) == 0

    plan = json.loads(capsys.readouterr().out)
    metadata = plan["config"]["metadata"]["instruction_append"]
    assert metadata["path"] == str(overlay_path.resolve())
    assert metadata["sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert metadata["byte_length"] == len(content.encode("utf-8"))
