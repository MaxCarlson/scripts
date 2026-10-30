"""Validated task-instruction additions for controlled experiment variants."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path

from .evidence import Task


@dataclass(frozen=True)
class InstructionAppend:
    path: Path
    text: str
    sha256: str
    byte_length: int

    def to_dict(self) -> dict[str, str | int]:
        return {"path": str(self.path), "sha256": self.sha256, "byte_length": self.byte_length}


def load_instruction_append(path: Path) -> InstructionAppend:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("Instruction append path must be a regular file")
    content = resolved.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Instruction append file must be UTF-8") from error
    if not text.strip():
        raise ValueError("Instruction append file must not be empty")
    return InstructionAppend(resolved, text, hashlib.sha256(content).hexdigest(), len(content))


def apply_instruction_append(task: Task, addition: InstructionAppend | None) -> Task:
    if addition is None:
        return task
    return replace(task, instruction=task.instruction + "\n\n" + addition.text)
