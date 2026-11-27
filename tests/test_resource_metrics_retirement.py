from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CONSUMERS = (
    "backup_module",
    "compresser",
    "resource_coordinator",
    "rrbackup",
    "runmux",
    "sysmon",
    "system_manager",
    "vdedup",
)
RETIRED_TOOLKIT_CONSUMERS = (
    "ai_orchestrator",
    "agent_benchmark",
    "llm-models",
    "local_agent_bridge",
)
PROJECT_VERSIONS = {
    "backup_module": "0.3.0",
    "compresser": "3.4.0",
    "resource_coordinator": "1.0.0",
    "rrbackup": "2.2.0",
    "runmux": "0.15.0",
    "sysmon": "0.5.0",
    "system_manager": "1.2.0",
    "vdedup": "0.19.0",
}


def test_legacy_resource_metrics_source_and_setup_entry_are_retired():
    tracked = subprocess.run(
        ["git", "ls-files", "--", "modules/resource_metrics"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert not tracked
    assert not (REPO_ROOT / "modules" / "resource_metrics" / "pyproject.toml").exists()

    setup_source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    assert '("resource_metrics", MODULES_DIR / "resource_metrics")' not in setup_source


def test_consumers_declare_the_canonical_resource_metrics_distribution():
    for module in CANONICAL_CONSUMERS:
        pyproject = REPO_ROOT / "modules" / module / "pyproject.toml"
        source = pyproject.read_text(encoding="utf-8")
        project = tomllib.loads(source)["project"]
        assert "mxc-resource-metrics" in source, f"{module} is missing canonical package metadata"
        assert '"resource-metrics' not in source and "'resource-metrics" not in source, (
            f"{module} still requests the retired distribution"
        )
        assert project["version"] == PROJECT_VERSIONS[module]

    for retired in RETIRED_TOOLKIT_CONSUMERS:
        assert not (REPO_ROOT / "modules" / retired / "pyproject.toml").exists()


def test_canonical_wheel_provides_every_consumer_import_symbol():
    wheel = (
        REPO_ROOT
        / "modules"
        / "resource_coordinator"
        / "tools"
        / "h4_qualification"
        / "wheelhouse"
        / "mxc_resource_metrics-0.3.0-py3-none-any.whl"
    )
    assert wheel.is_file()
    probe = subprocess.run(
        [
            "python",
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from resource_metrics import cpu_count, cpu_percent, gpu_devices, gpu_process_memory, "
            "memory_stats, net_io_counters, nvidia_gpus, process_tree, process_io, top_process_memory; "
            "from resource_metrics.gpu import gpu_devices as submodule_gpu_devices; "
            "from resource_metrics.process import process_io as submodule_process_io; "
            "from resource_metrics.system import memory_stats as submodule_memory_stats, rate; "
            "import resource_metrics; print(resource_metrics.__file__)",
            str(wheel),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert str(wheel) in probe.stdout
