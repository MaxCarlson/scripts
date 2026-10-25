"""Packaged skill resource contracts and deterministic recovery scenarios."""

import json
from pathlib import Path

from local_agent_bridge.setup.manifest import assets


def test_worker_prompt_prefers_focused_discovery_and_bounded_reads():
    prompt = (assets() / "skills/local-agent-handoff/resources/local-worker.md").read_text(
        encoding="utf-8"
    ).lower()
    for phrase in ("rg --files", "offset", "limit", "unbounded", "focused test", "progress checkpoint"):
        assert phrase in prompt
    assert "full-file reads remain permitted" in prompt


def test_dispatch_and_recovery_guidance_preserve_turn_identity_and_evidence():
    root = assets() / "skills/local-agent-handoff"
    skill = (root / "SKILL.md").read_text(encoding="utf-8").lower()
    envelope = (root / "references/task-envelope.md").read_text(encoding="utf-8").lower()
    recovery = (root / "references/results-and-recovery.md").read_text(encoding="utf-8").lower()
    for identifier in ("jobid", "sessionid", "messageid", "directory", "provider", "model", "agent"):
        assert identifier in envelope
    for phrase in (
        "active",
        "completed",
        "failed",
        "uncertain",
        "correlation",
        "summary.files",
        "baseline",
        "diff",
        "timed out",
        "cancel",
        "local-worker",
        "local-reviewer",
        "permission",
        "question",
    ):
        assert phrase in recovery
    assert "agent" in skill
    assert "never resubmit" in recovery


def test_recovery_scenarios_are_deterministic_and_covered_by_guidance():
    root = Path(__file__).parent
    scenarios = json.loads((root / "fixtures/job_recovery_scenarios.json").read_text(encoding="utf-8"))
    recovery = (assets() / "skills/local-agent-handoff/references/results-and-recovery.md").read_text(
        encoding="utf-8"
    ).lower()
    assert {case["id"] for case in scenarios} == {
        "compaction-stale-job-live-session",
        "same-session-follow-up-agent",
        "false-zero-file-summary",
        "observation-timeout-not-cancelled",
        "uncertain-turn-correlation",
        "no-worktree-diff",
        "permitted-edit-and-test-success",
    }
    assert all(case.get("expected") for case in scenarios)
    for phrase in ("stale", "same session", "messageid", "summary.files", "worktree", "focused tests"):
        assert phrase in recovery


def test_skill_links_and_json_examples_resolve():
    root = assets() / "skills/local-agent-handoff"
    for markdown in (root / "SKILL.md", root / "references/task-envelope.md", root / "references/results-and-recovery.md"):
        text = markdown.read_text(encoding="utf-8")
        import re

        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if "://" not in target and not target.startswith("#"):
                assert (markdown.parent / target).resolve().is_file(), (markdown, target)
    example = json.loads((root / "resources/result.schema.json").read_text(encoding="utf-8"))
    assert example["type"] == "object"


def test_installer_roles_share_one_canonical_prompt_and_keep_reviewer_restrictions():
    from local_agent_bridge.setup.manifest import role_text

    root = assets()
    config = json.loads((root / "integrations/opencode-agent.example.json").read_text(encoding="utf-8"))
    worker = config["agent"]["local-worker"]
    reviewer = config["agent"]["local-reviewer"]
    prompt_path = worker["prompt"].removeprefix("{file:").removesuffix("}")
    assert worker["prompt"] == reviewer["prompt"]
    assert (root / "integrations" / prompt_path).resolve().is_file()
    assert reviewer["permission"]["edit"] == "deny"
    assert reviewer["permission"]["bash"] == "deny"
    canonical = (root / "skills/local-agent-handoff/resources/local-worker.md").read_text(encoding="utf-8")
    assert canonical in role_text("local-worker")
    assert canonical in role_text("local-reviewer")
