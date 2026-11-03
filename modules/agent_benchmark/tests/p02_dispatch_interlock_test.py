from types import SimpleNamespace

import pytest

from agent_benchmark.harbor.runner import execute_harbor_run, PreflightCheckError


def test_study_dispatch_rejects_unverified_network_before_any_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.check_docker_readiness",
        lambda: pytest.fail("Docker readiness must not be consulted"),
    )
    plan = SimpleNamespace(readiness=SimpleNamespace(is_runnable=True))
    with pytest.raises(PreflightCheckError, match="NETWORK_QUALIFICATION_UNAVAILABLE"):
        execute_harbor_run(plan, execute=True, output_dir=tmp_path, jobs_dir=tmp_path, study_adapter=True)
