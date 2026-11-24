from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from tools.h4_qualification import bundle_builder
from resource_coordinator.installation import InstallationPaths, render_launcher

MODULE_ROOT = Path(__file__).resolve().parents[1]
MONITOR_WHEEL_FILENAME = "llm_monitor-0.9.0-py3-none-any.whl"
MONITOR_WHEEL_SHA256 = (
    "4357bd80029cad52d1f848db7903427d95c10e447dcce78836bda07a769688d5"
)


def test_h4_bundle_uses_canonical_llm_monitor_wheel_and_runmux_contract(tmp_path):
    out = tmp_path / "monitor_bundle"
    bundle_builder.build_bundle(
        repo_root=MODULE_ROOT.parents[1],
        output_dir=out,
        new_ref="HEAD",
        apply=True,
    )
    bundle = out / "h4-windows-acceptance"
    wheel = bundle / "dependencies" / "wheelhouse" / MONITOR_WHEEL_FILENAME
    lock = json.loads(
        (bundle / "dependencies" / "dependency-lock.json").read_text(encoding="utf-8")
    )

    assert wheel.is_file()
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == MONITOR_WHEEL_SHA256
    assert lock["canonical_packages"]["llm-monitor"] == {
        "version": "0.9.0",
        "filename": MONITOR_WHEEL_FILENAME,
        "sha256": MONITOR_WHEEL_SHA256,
        "source_repository": "https://github.com/MaxCarlson/llm-agent-toolkit",
        "source_commit": "edd54bd07ec9b1058e9c35e57ca320aaf993b6b2",
        "path": f"dependencies/wheelhouse/{MONITOR_WHEEL_FILENAME}",
    }
    assert "llm-monitor==0.9.0" in (
        bundle / "dependencies" / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert not (bundle / "sources" / "rc-1.0.0" / "modules" / "llm_monitor").exists()

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json, sys
sys.path.insert(0, sys.argv[1])
from llm_monitor.gateway import OpenAIInferenceGateway, RequestEventHub
from llm_monitor.live_store import LiveInferenceStore
from llm_monitor.observability import ObservabilityService
from llm_monitor.opencode import ApiResult
from llm_monitor.runmux_adapter import RunmuxMonitoringAdapter
import llm_monitor

class SyntheticProvider:
    base_url = 'http://localhost:4096'
    def sessions(self, _directory=None): return ApiResult(data=[{'id': 's1'}])
    def poll(self, session_id, _directory=None):
        return {'session_id': session_id, 'polled_at': '2026-01-01T00:00:00+00:00',
                'normalized_state': 'idle', 'session_info': {'id': session_id},
                'history_coverage': {'status': 'complete'}, 'pending_permissions': 0,
                'pending_questions': 0, 'errors': {}}
    def events_for_session(self, _session_id): return []

snapshot = RunmuxMonitoringAdapter(ObservabilityService(SyntheticProvider())).snapshot()
assert snapshot['schema_version'] == 1
assert snapshot['system']['discovered_sessions'] == 1
assert OpenAIInferenceGateway and RequestEventHub and LiveInferenceStore
print(json.dumps({'origin': llm_monitor.__file__, 'schema_version': snapshot['schema_version'],
                  'sessions': snapshot['system']['discovered_sessions']}))
""",
            str(wheel),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    result = json.loads(probe.stdout)
    assert str(wheel) in result["origin"]
    assert result["schema_version"] == 1
    assert result["sessions"] == 1


def test_managed_launcher_does_not_add_a_scripts_llm_monitor_source_path(tmp_path):
    paths = InstallationPaths.isolated(
        root=tmp_path / "h4-install",
        repository=MODULE_ROOT.parents[1],
        python=Path("C:/Python/python.exe"),
    )

    launcher = render_launcher(paths)
    pythonpath = next(
        line for line in launcher.splitlines() if line.startswith("$env:PYTHONPATH")
    )

    assert "modules/resource_coordinator" in pythonpath.replace("\\", "/")
    assert "llm_monitor" not in pythonpath
