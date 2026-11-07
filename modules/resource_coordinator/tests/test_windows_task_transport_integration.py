"""Opt-in real Windows tests for the bounded Task Scheduler helper transport.

The transport probe validates the file-backed helper/result protocol without
reading or modifying production Task Scheduler entries.
"""

import json
import os
from pathlib import Path

import pytest

from resource_coordinator.installation import WindowsStartupTaskBackend


@pytest.mark.skipif(os.name != "nt" or os.environ.get("RC_WINDOWS_INTEGRATION") != "1",
                    reason="set RC_WINDOWS_INTEGRATION=1 on Windows to run the real read-only helper test")
def test_windows_helper_processes_large_request_from_protected_file(tmp_path):
    backend = WindowsStartupTaskBackend(managed_root=Path(tmp_path) / "Resource Coordinator Integration")
    definition = "<Task>" + ("x" * 100_000) + "</Task>"
    result = backend._run({"operation": "transport_probe", "definition": definition})
    details = json.loads(result.stdout)
    assert details["status"] == "validated"
    assert details["definition_length"] == len(definition)
    assert list(backend.managed_root.glob("operation-*")) == []


@pytest.mark.skipif(os.name != "nt" or os.environ.get("RC_WINDOWS_UAC_INTEGRATION") != "1",
                    reason="set RC_WINDOWS_UAC_INTEGRATION=1 to test Start-Process -Verb RunAs")
def test_windows_uac_helper_processes_large_request_and_verifies_completion(tmp_path):
    backend = WindowsStartupTaskBackend(managed_root=Path(tmp_path) / "Resource Coordinator UAC Integration")
    if backend._admin():
        pytest.skip("run from a non-elevated PowerShell session to exercise the UAC child process")
    definition = "<Task>" + ("x" * 100_000) + "</Task>"
    result = backend._run({"operation": "transport_probe", "definition": definition}, elevated=True)
    details = json.loads(result.stdout)
    assert details["status"] == "validated"
    assert details["definition_length"] == len(definition)
    assert list(backend.managed_root.glob("operation-*")) == []
