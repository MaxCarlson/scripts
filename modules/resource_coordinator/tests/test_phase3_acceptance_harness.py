"""
Phase 3 Tests: Supervised Acceptance Test Harness Runner and Evidence Verification.
"""

from pathlib import Path
import pytest

from resource_coordinator.acceptance_harness import AcceptanceHarness, AcceptanceReport


@pytest.mark.asyncio
async def test_acceptance_harness_simulated_sequence(tmp_path: Path):
    """
    Execute all 5 acceptance sequence trials via AcceptanceHarness.
    Verify all trials PASS and structured JSON evidence is written to disk.
    """
    evidence_path = tmp_path / "acceptance_evidence.json"
    harness = AcceptanceHarness(mode="simulated", cooldown_seconds=0.05)

    report = await harness.run_all(output_file=evidence_path)

    assert report.summary["all_passed"] is True
    assert report.summary["total_trials"] == 5
    assert report.summary["passed"] == 5
    assert report.summary["failed"] == 0

    assert evidence_path.exists()
    import json

    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert data["mode"] == "simulated"
    assert len(data["trials"]) == 5

    trial_ids = [t["trial_id"] for t in data["trials"]]
    assert trial_ids == ["T01", "T02", "T03", "T04", "T05"]

    for trial in data["trials"]:
        assert trial["status"] == "PASS"
        assert trial["duration_seconds"] > 0.0
