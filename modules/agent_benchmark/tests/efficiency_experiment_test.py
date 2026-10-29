from __future__ import annotations

import collections
import itertools

from experiments.local_agent_efficiency import build_command, load_plan


def test_b0_b2_b3_schedule_is_seeded_counterbalanced_and_exactly_36():
    config, first = load_plan()
    _, second = load_plan()
    assert first == second
    assert len(first) == config["expected_dispatches"] == 36
    blocks = collections.defaultdict(list)
    for item in first:
        blocks[(item["task"], item["repetition"])].append(item["condition"])
    assert len(blocks) == 12
    assert {tuple(order) for order in blocks.values()} == set(itertools.permutations(("B0", "B2", "B3")))
    assert collections.Counter(order for order in map(tuple, blocks.values())) == {
        order: 2 for order in itertools.permutations(("B0", "B2", "B3"))
    }
    assert collections.Counter(item["condition"] for item in first) == {"B0": 12, "B2": 12, "B3": 12}


def test_experiment_commands_select_exact_task_profile_and_safety_limits(tmp_path):
    config, schedule = load_plan()
    for condition in config["conditions"]:
        item = next(run for run in schedule if run["condition"] == condition)
        command = build_command(config, item, "exact-model-key", tmp_path / "output", tmp_path / "state")
        assert command[command.index("--tool-profile") + 1] == config["conditions"][condition]["profile"]
        assert command[command.index("-t") + 1].endswith(item["task"])
        assert command[command.index("-c") + 1] == "32768"
        assert "--no-allow-model-transitions" in command
        assert "-x" in command and command[command.index("-r") + 1] == "1"


def test_dry_run_is_default_and_does_not_launch_commands(monkeypatch, capsys):
    import experiments.local_agent_efficiency as experiment

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run attempted subprocess execution")

    monkeypatch.setattr(experiment.subprocess, "run", forbidden)
    assert experiment.main(["--model-key", "exact-model-key"]) == 0
    assert '"execute": false' in capsys.readouterr().out


def test_experiment_cli_adds_profile_override_without_changing_single_run_commands():
    from agent_benchmark.cli import parser

    args = parser().parse_args(["experiment", "run", "-m", "exact-model-key",
                                "--tool-profile", "retrieval-files-v1"])
    assert args.tool_profile == "retrieval-files-v1"
    legacy = parser().parse_args(["run", "-m", "exact-model-key"])
    assert not hasattr(legacy, "tool_profile")
