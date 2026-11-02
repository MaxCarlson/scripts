"""Optional offline qualification against an existing Harbor 0.25 environment."""

import os
from pathlib import Path
import subprocess

import pytest

from agent_benchmark.spec_verification_policy import load_policy


def test_harbor_025_factory_and_prompt_renderer(tmp_path):
    python = os.environ.get("HARBOR_025_PYTHON")
    if not python:
        pytest.skip("set HARBOR_025_PYTHON to an existing Harbor 0.25 Python")
    module_root = Path(__file__).resolve().parents[1]
    policy = module_root / "agent_benchmark" / "policies" / "sv1-v1.md"
    raw, template, identity = load_policy(policy)
    frozen = tmp_path / "prompt-template.j2"
    frozen.write_bytes(template)
    code = '''
import hashlib, importlib.metadata, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, PropertyMock
from harbor.agents.factory import AgentFactory
from harbor.agents.installed.opencode import OpenCode
from harbor.cli.utils import parse_kwargs
from harbor.utils.templating import render_prompt_template
p, policy, expected = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
assert importlib.metadata.version("harbor") == "0.25.0"
parsed = parse_kwargs(["disable_web_search=true", "prompt_template_path=" + str(p)])
assert parsed == {"disable_web_search": True, "prompt_template_path": str(p)}
assert hashlib.sha256(policy.read_bytes()).hexdigest() == expected
kwargs = dict(import_path="agent_benchmark.harbor.opencode_v1:OpenCodeV1", logs_dir=p.parent)
base = AgentFactory.create_agent_from_import_path(**kwargs)
candidate = AgentFactory.create_agent_from_import_path(**kwargs, prompt_template_path=str(p), disable_web_search=True)
instruction = "Synthetic task\\r\\n  edge \\u2603\\n"
assert base.render_instruction(instruction) == instruction
result = render_prompt_template(p, instruction)
assert result == instruction + "\\n\\n" + policy.read_bytes().decode("utf-8")
assert candidate.render_instruction(instruction) == result
assert candidate._version == "1.19.5" and candidate.options.disable_web_search
candidate.model_name = "openai/test"
candidate._execution_model_name = lambda: "llm-monitor/test"
candidate._build_register_skills_command = lambda: None
candidate._build_register_config_command = lambda: None
candidate.build_cli_flags = lambda: ""
candidate._error_messages = lambda: []
seen = []
async def fake_exec(self, environment, **kwargs):
    seen.append(kwargs)
with patch.object(type(candidate), "model_connection", new_callable=PropertyMock, return_value=SimpleNamespace(env={})):
    with patch.object(OpenCode, "exec_as_agent", fake_exec):
        coroutine = candidate.run(instruction, None, None)
        try:
            coroutine.send(None)
            raise AssertionError("mocked execution unexpectedly suspended")
        except StopIteration:
            pass
assert len(seen) == 1
assert "OPENCODE_FAKE_VCS" not in seen[0]["env"]
assert "--dangerously-skip-permissions" in seen[0]["command"]
assert candidate._instruction == result
'''
    env = os.environ.copy()
    env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((str(module_root), str(module_root.parent / "benchmark_core")))
    result = subprocess.run([python, "-B", "-c", code, str(frozen), str(policy), identity["sha256"]],
                            env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert raw == policy.read_bytes()
