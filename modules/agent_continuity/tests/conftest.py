"""Test suite pytest configuration keeping temp roots inside modules/agent_continuity/.pytest_tmp_root."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = MODULE_ROOT / ".pytest_tmp_root"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))
os.environ.setdefault("TEMP", str(TMP_ROOT))
os.environ.setdefault("TMP", str(TMP_ROOT))


@pytest.fixture(scope="session")
def fake_provider_bin() -> Path:
    """Expose controlled provider names for discovery without a real CLI on PATH."""
    fake_bin = TMP_ROOT / "fake-providers"
    fake_bin.mkdir(parents=True, exist_ok=True)
    for provider in ("codex", "agy", "claude"):
        fake_executable = fake_bin / f"{provider}.exe"
        fake_executable.write_text("controlled fake provider; never executable", encoding="utf-8")
    return fake_bin


@pytest.fixture(autouse=True)
def provider_process_guard(monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path) -> None:
    """Fail closed before any test can spawn a real or fake native provider."""
    provider_names = {f"{provider}{suffix}" for provider in ("codex", "agy", "claude")
                      for suffix in (".exe", ".cmd", ".bat", ".ps1")}
    path_entries = [str(fake_provider_bin)]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        try:
            if any(child.name.casefold() in provider_names for child in Path(entry).iterdir()):
                continue
        except OSError:
            pass
        path_entries.append(entry)
    monkeypatch.setenv("PATH", os.pathsep.join(path_entries))
    real_popen = subprocess.Popen

    class FakeVersionProcess:
        returncode = 0
        args = []

        def communicate(self, *_args, **_kwargs):
            return "fake-provider 0.0", ""

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def provider_name(value: object) -> str | None:
        text = str(value).strip().strip('"')
        name = Path(text.replace("\\", "/")).name.casefold()
        for provider in ("codex", "agy", "claude"):
            if name in {provider, f"{provider}.exe", f"{provider}.cmd", f"{provider}.bat", f"{provider}.ps1"}:
                return provider
        return None

    def guarded_popen(args, *popen_args, **kwargs):
        values = list(args) if isinstance(args, (list, tuple)) else [args]
        if (kwargs.get("shell") and isinstance(args, str)
                and re.search(r"(?i)(?<![\w.-])(codex|agy|claude)(?:\.(?:exe|cmd|bat|ps1))?(?![\w.-])", args)):
            raise AssertionError("Test attempted to spawn a provider through a shell command.")
        target = kwargs.get("executable") or (values[0] if values else "")
        blocked = provider_name(target)
        target_name = Path(str(target).replace("\\", "/")).name.casefold()
        if not blocked and target_name in {"wsl.exe", "wsl"} and "--exec" in values:
            exec_index = values.index("--exec")
            if exec_index + 1 < len(values):
                blocked = provider_name(values[exec_index + 1])
        if not blocked and target_name in {"cmd.exe", "cmd", "powershell.exe", "pwsh.exe", "pwsh"}:
            for index, value in enumerate(values[:-1]):
                option = str(value).casefold()
                if option in {"-file", "-f"}:
                    blocked = provider_name(values[index + 1])
                    if blocked:
                        break
                if option in {"/c", "-command", "-c"} and re.search(
                    r"(?i)(?<![\w.-])(codex|agy|claude)(?:\.(?:exe|cmd|bat|ps1))?(?![\w.-])",
                    str(values[index + 1]),
                ):
                    raise AssertionError("Test attempted to spawn a provider through a shell wrapper.")
        if blocked:
            executable = Path(str(target).strip('"')).resolve()
            expected_fake = (fake_provider_bin / f"{blocked}.exe").resolve()
            if (executable.as_posix().casefold() == expected_fake.as_posix().casefold()
                    and values[1:] == ["--version"]):
                return FakeVersionProcess()
            raise AssertionError(f"Test attempted to spawn provider {blocked}; use a fake process stub instead.")
        return real_popen(args, *popen_args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
    original_system = os.system

    def guarded_system(command: str) -> int:
        if re.search(r"(?i)(?<![\w.-])(codex|agy|claude)(?:\.(?:exe|cmd|bat|ps1))?(?![\w.-])", command):
            raise AssertionError("Test attempted to spawn a provider through os.system.")
        return original_system(command)

    monkeypatch.setattr(os, "system", guarded_system)


@pytest.fixture(autouse=True)
def synthetic_runtime_discovery(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ordinary unit tests fast and host-isolated unless real_runtime_discovery is requested."""
    if request.node.get_closest_marker("real_runtime_discovery") is not None:
        return
    from datetime import UTC, datetime

    from agent_continuity.runtime_discovery import (
        EvidenceAvailability,
        ProcessInventory,
        PsutilProcessEnumerator,
    )

    monkeypatch.setattr(
        PsutilProcessEnumerator,
        "enumerate_processes",
        lambda self: ProcessInventory((), EvidenceAvailability.COMPLETE, datetime.now(UTC)),
    )
