"""Tests for HTML report builder, HTML escaping, and offline portability."""

import re
from pathlib import Path

from interactive_reports.builder import escape_json_script, generate_html_report
from interactive_reports.models import (
    EfficiencyPoint,
    ReportData,
    TaskDivergenceRow,
    TaskVariantResult,
    TrialDetail,
    VariantReportRow,
)


def test_escape_json_script():
    data = {
        "tag": "</script><script>alert('xss')</script>",
        "comment": "<!-- comment -->",
    }
    escaped = escape_json_script(data)
    assert "</script>" not in escaped
    assert r"\u003c/script>" in escaped
    assert "<!--" not in escaped
    assert r"\u003c!--" in escaped


def test_generate_html_report_empty():
    report = ReportData(
        experiment_id="EXP_TEST_EMPTY",
        title="Empty Test Benchmark",
    )
    html_output = generate_html_report(report)

    assert "<!DOCTYPE html>" in html_output
    assert "<title>Empty Test Benchmark - EXP_TEST_EMPTY</title>" in html_output
    assert '<script id="report-data" type="application/json">' in html_output
    assert "Leaderboard &amp; Rankings" in html_output or "Leaderboard & Rankings" in html_output
    assert "No efficiency data available" in html_output


def test_generate_html_report_full(tmp_path: Path):
    v1 = VariantReportRow(
        variant_id="model_fast",
        is_eligible=True,
        rank=1,
        total_trials=3,
        passed=3,
        failed=0,
        timed_out=0,
        scored_denominator=3,
        strict_acceptance_rate=1.0,
        ci_lower=0.4385,
        ci_upper=1.0,
        duration_mean_ms=1200.0,
        throughput_tok_per_s=110.0,
        reasoning_token_share=0.15,
    )
    v2 = VariantReportRow(
        variant_id="model_experimental",
        is_eligible=False,
        exclusion_reasons=["budget_profile mismatch: experimental-10s vs canonical-60s"],
        total_trials=2,
        passed=1,
        failed=1,
        timed_out=0,
        scored_denominator=2,
        strict_acceptance_rate=0.5,
        duration_mean_ms=800.0,
    )

    t1 = TrialDetail(
        trial_id="tr_1",
        variant_id="model_fast",
        task_id="task_calc",
        status="passed",
        duration_ms=1200.0,
        input_tokens=50,
        output_tokens=100,
        reasoning_tokens=15,
        total_tokens=150,
        throughput_tok_per_s=110.0,
        reasoning_token_share=0.15,
        verifier_output="Calculator test passed: 42 == 42",
        diff="--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-def add(a, b): return 0\n+def add(a, b): return a + b\n",
    )

    div_row = TaskDivergenceRow(
        task_id="task_calc",
        category="math",
        results_by_variant={
            "model_fast": TaskVariantResult(
                status="passed", pass_rate=1.0, passed=1, total=1, trial_ids=["tr_1"]
            ),
            "model_experimental": TaskVariantResult(
                status="mixed", pass_rate=0.5, passed=1, total=2, trial_ids=[]
            ),
        },
    )

    eff_point = EfficiencyPoint(
        trial_id="tr_1",
        variant_id="model_fast",
        task_id="task_calc",
        status="passed",
        strict_pass=True,
        duration_ms=1200.0,
        total_tokens=150,
        throughput_tok_per_s=110.0,
        reasoning_token_share=0.15,
    )

    report = ReportData(
        experiment_id="EXP_20261019_FULL",
        title="Comprehensive Benchmark",
        suite_id="agent_eval",
        suite_version="2.1.0",
        budget_profile="canonical-60s",
        scoring_basis="strict",
        created_at="2026-10-19T12:00:00Z",
        variants=[v1, v2],
        divergence_matrix=[div_row],
        efficiency_points=[eff_point],
        trials={"tr_1": t1},
        warnings=["Notice: 1 model evaluated under experimental budget"],
    )

    out_file = tmp_path / "report.html"
    html_output = generate_html_report(report, output_path=out_file)

    assert out_file.is_file()
    assert out_file.read_text(encoding="utf-8") == html_output

    # Check canonical leaderboard contains model_fast
    assert "model_fast" in html_output
    assert "100.0%" in html_output
    assert "43.9% &ndash; 100.0%" in html_output

    # Check reference section contains model_experimental
    assert "Reference &amp; Ineligible Variants" in html_output or "Reference & Ineligible Variants" in html_output
    assert "model_experimental" in html_output
    assert "experimental-10s vs canonical-60s" in html_output

    # Check divergence matrix
    assert "task_calc" in html_output
    assert "math" in html_output
    assert "PASS (1/1)" in html_output

    # Check warnings
    assert "Notice: 1 model evaluated under experimental budget" in html_output


def test_html_escaping_security():
    malicious_task = "<script>alert('task')</script>"
    malicious_model = "<b>hack_model</b>"
    malicious_output = "</script><script>alert('output')</script>"

    report = ReportData(
        experiment_id="EXP_SECURITY",
        title="Security <Test>",
        variants=[
            VariantReportRow(
                variant_id=malicious_model,
                is_eligible=True,
                total_trials=1,
                passed=1,
                scored_denominator=1,
                strict_acceptance_rate=1.0,
            )
        ],
        trials={
            "t_sec": TrialDetail(
                trial_id="t_sec",
                variant_id=malicious_model,
                task_id=malicious_task,
                status="passed",
                duration_ms=100.0,
                verifier_output=malicious_output,
            )
        },
    )

    html_output = generate_html_report(report)

    # In raw HTML DOM, script tags from data MUST NOT appear unescaped
    assert "<script>alert('task')</script>" not in html_output
    assert "&lt;script&gt;alert(&#x27;task&#x27;)&lt;/script&gt;" in html_output or "&lt;script&gt;alert('task')&lt;/script&gt;" in html_output
    assert "<b>hack_model</b>" not in html_output
    assert "&lt;b&gt;hack_model&lt;/b&gt;" in html_output


def test_offline_portability():
    report = ReportData(experiment_id="EXP_OFFLINE")
    html_output = generate_html_report(report)

    # Confirm NO external scripts or stylesheets loaded from remote URLs
    remote_script = re.findall(r'<script[^>]+src=["\'](https?://[^"\']+)["\']', html_output, re.IGNORECASE)
    remote_link = re.findall(r'<link[^>]+href=["\'](https?://[^"\']+)["\']', html_output, re.IGNORECASE)

    assert remote_script == [], f"Found remote script dependencies: {remote_script}"
    assert remote_link == [], f"Found remote stylesheet dependencies: {remote_link}"
