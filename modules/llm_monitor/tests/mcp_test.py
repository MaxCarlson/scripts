import json

from llm_monitor.mcp import correlate_job, load_job_snapshot


def test_mcp_snapshot_preserves_explicit_correlation_and_whitelists_fields(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps({"jobs": [{"jobId": "job-1", "sessionId": "ses-1",
                                         "directory": "C:/work", "prompt": "private"}]}))

    snapshot = load_job_snapshot(path)
    result = correlate_job("ses-1", "C:/work", snapshot)

    assert result["status"] == "correlated"
    assert result["classification"] == "observed"
    assert "prompt" not in result["job"]


def test_unknown_job_and_directory_match_remain_unresolved_or_qualified(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps({"jobs": [{"jobId": "job-1", "sessionId": "other", "directory": "C:/work"}]}))
    snapshot = load_job_snapshot(path)

    result = correlate_job("ses-1", "C:/work", snapshot)
    assert result["status"] == "probable_directory_match"
    assert result["classification"] == "hypothesis"
    assert "does not establish" in result["warning"]
    assert correlate_job("ses-1", None, {"available": True, "jobs": []})["status"] == "unresolved"
