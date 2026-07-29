"""Read-only and explicitly invoked Restic repository operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import ExecutionMode
from .profile import BackupProfile
from .restic import ExecutionResult, ResticCommand, build_restic_command, execute_restic
from .snapshots import SnapshotInfo, parse_snapshots_json


@dataclass(frozen=True)
class RepositoryOperation:
    """One completed repository command and any parsed payload."""

    result: ExecutionResult
    payload: Any = None


class RepositoryClient:
    """Build and execute Restic commands for one canonical profile."""

    def __init__(self, profile: BackupProfile) -> None:
        self.profile = profile

    def command(self, arguments: Sequence[str]) -> ResticCommand:
        """Build a repository command without executing it."""

        return build_restic_command(
            restic_executable=self.profile.restic_executable,
            repository=self.profile.repository,
            arguments=list(arguments),
            password_file=self.profile.password_file,
        )

    def execute(
        self,
        arguments: Sequence[str],
        *,
        echo: bool = False,
    ) -> ExecutionResult:
        """Execute a repository command through the shared boundary."""

        return execute_restic(
            self.command(arguments),
            mode=ExecutionMode.RUN,
            echo=echo,
        )

    def snapshots(
        self,
        *,
        tags: Sequence[str] = (),
        host: Optional[str] = None,
        paths: Sequence[str] = (),
    ) -> Tuple[List[SnapshotInfo], ExecutionResult]:
        """Return parsed snapshots ordered newest first."""

        arguments: List[str] = ["snapshots", "--json"]
        for tag in tags:
            arguments.extend(["--tag", tag])
        if host:
            arguments.extend(["--host", host])
        for path in paths:
            arguments.extend(["--path", path])

        result = self.execute(arguments)
        payload = "".join(result.output)
        if result.return_code != 0:
            return [], result
        return parse_snapshots_json(payload), result

    def status(self) -> RepositoryOperation:
        """Read the repository configuration metadata."""

        result = self.execute(["cat", "config"])
        payload: Any = None
        if result.return_code == 0:
            text = "".join(result.output).strip()
            if text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {"text": text}
        return RepositoryOperation(result=result, payload=payload)

    def stats(self, *, mode: str = "restore-size") -> RepositoryOperation:
        """Return Restic repository statistics."""

        result = self.execute(["stats", "--mode", mode, "--json"])
        payload: Any = None
        if result.return_code == 0:
            text = "".join(result.output).strip()
            if text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {"text": text}
        return RepositoryOperation(result=result, payload=payload)

    def keys(self) -> RepositoryOperation:
        """Return repository key metadata without reading key material."""

        result = self.execute(["key", "list"])
        return RepositoryOperation(
            result=result,
            payload={"lines": [line.rstrip("\r\n") for line in result.output]},
        )

    def locks(self) -> RepositoryOperation:
        """Return raw Restic lock identifiers."""

        result = self.execute(["list", "locks"])
        return RepositoryOperation(
            result=result,
            payload={"lines": [line.rstrip("\r\n") for line in result.output]},
        )

    def cache_status(self) -> RepositoryOperation:
        """Return Restic cache status without cleanup."""

        result = self.execute(["cache"])
        return RepositoryOperation(
            result=result,
            payload={"lines": [line.rstrip("\r\n") for line in result.output]},
        )

    def check(self, *, read_data: bool = False) -> RepositoryOperation:
        """Run Restic's read-only repository integrity check."""

        arguments = ["check"]
        if read_data:
            arguments.append("--read-data")
        result = self.execute(arguments, echo=True)
        return RepositoryOperation(result=result)


def operation_to_dict(operation: RepositoryOperation) -> Dict[str, Any]:
    """Serialize a repository operation without exposing environment secrets."""

    return {
        "command": operation.result.command.render(redacted=True),
        "return_code": operation.result.return_code,
        "succeeded": operation.result.succeeded,
        "payload": operation.payload,
    }
