from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.service import ContinuityService


def test_independent_process_activations_get_unique_durable_order(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-0", apply=True)

    module_root = Path(__file__).resolve().parents[1]
    script = (
        "import sys; from agent_continuity.dispatcher import DispatcherService; "
        "d=DispatcherService(home_dir=sys.argv[1]); "
        "d.attach_session(gui='AgentImprovement', name='AgentPerf', provider=sys.argv[2], "
        "session_id=sys.argv[3], apply=True)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(module_root)
    processes = [
        subprocess.Popen([sys.executable, "-c", script, str(home), "codex", "codex-B"], cwd=module_root, env=env),
        subprocess.Popen([sys.executable, "-c", script, str(home), "agy", "agy-C"], cwd=module_root, env=env),
    ]
    for process in processes:
        assert process.wait(timeout=30) == 0

    history = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["history"]
    assert [entry["sequence"] for entry in history] == [1, 2, 3]
    assert {entry["native_session_id"] for entry in history} == {"agy-0", "codex-B", "agy-C"}

    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()
    rebuilt = DispatcherService(ContinuityService(home)).get_slot(gui="AgentImprovement", name="AgentPerf")["history"]
    assert rebuilt == history
