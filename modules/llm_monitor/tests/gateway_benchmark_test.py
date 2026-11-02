from llm_monitor.gateway_benchmark import ORDERS, PATHS, _body, _chunk_has_text_delta, _parse_gpu_query, _prompt_case, _provider_metrics, _summarize, _summarize_timings, main


def test_benchmark_builds_the_same_synthetic_request_for_all_paths():
    request = _body("model-test", 24, True)
    assert request["model"] == "model-test"
    assert request["messages"] == [{"role": "user", "content": "Reply with exactly one color word: amber."}]
    assert request["max_tokens"] == 24
    assert request["temperature"] == 0
    assert request["stream_options"] == {"include_usage": True}
    assert len(set(ORDERS)) == 6
    assert set(PATHS) == {"direct", "minimal", "observed"}


def test_benchmark_summary_reports_sample_count_latency_and_matched_outputs():
    records = []
    for sample in range(1, 21):
        for path in PATHS:
            records.append({
                "mode": "streaming",
                "sample": sample,
                "path": path,
                "end_to_end_ms": float(sample * 10),
                "response_headers_ms": 2.0,
                "first_data_ms": 3.0,
                "estimated_tps_after_first_text": 15.0,
                "first_text_ms": 3.5,
                "generated_tokens": 5,
            })
    result = _summarize(records, 20)["streaming"]
    assert result["direct"]["samples"] == 20
    assert result["direct"]["median_end_to_end_ms"] == 105
    assert result["matched_output_groups"] == 20


def test_benchmark_refuses_live_inference_without_explicit_opt_in():
    assert main([]) == 2


def test_timing_summary_reports_in_process_cpu_and_memory_without_content(tmp_path):
    path = tmp_path / "timings.jsonl"
    path.write_text(
        '{"request_id":"r1","gateway_process_cpu_ms":15.625,"gateway_process_rss_bytes":66000000}\n'
        '{"request_id":"r2","gateway_process_cpu_ms":0,"gateway_process_rss_bytes":67000000}\n',
        encoding="utf-8",
    )
    result = _summarize_timings(path)
    assert result["median_ms"]["gateway_process_cpu_ms"] == 7.8125
    assert result["median_ms"]["gateway_process_rss_bytes"] == 66_500_000


def test_paired_summary_reports_tail_outliers_order_and_median_uncertainty():
    records = []
    for sample in range(1, 21):
        order = ["direct", "minimal", "observed"]
        observed = 1100.0 if sample == 20 else 400.0 if sample == 7 else 100.0
        for path, latency in (("direct", 100.0), ("minimal", 105.0), ("observed", observed)):
            records.append({
                "mode": "streaming",
                "sample": sample,
                "path": path,
                "order": order,
                "end_to_end_ms": latency,
                "response_headers_ms": latency / 2,
                "first_data_ms": latency / 2,
                "first_text_ms": latency / 2,
                "estimated_tps_after_first_text": None,
                "generated_tokens": 5,
            })

    summary = _summarize(records, 20)["streaming"]
    paired = summary["paired_overhead"]["observed_vs_direct"]
    assert paired["n"] == 20
    assert paired["median_ms"] == 0
    assert paired["p95_ms"] == 300
    assert paired["worst_case_ms"] == 1000
    assert paired["outliers_over_100ms"] == 2
    assert paired["median_95pct_ci_ms"][0] <= paired["median_ms"] <= paired["median_95pct_ci_ms"][1]
    assert summary["path_tail"]["observed"]["over_1000ms_samples"] == 1
    assert summary["path_tail"]["observed"]["outlier_request_orders"] == [{"sample": 20, "order": order}]


def test_benchmark_profiles_bound_short_and_long_synthetic_requests():
    short = _body("m", 32, True, profile="short", sample_index=1)
    long = _body("m", 32, False, profile="long", sample_index=1)
    varied_a = _body("m", 32, True, prompt_mode="varied", sample_index=1)
    varied_b = _body("m", 32, True, prompt_mode="varied", sample_index=2)

    assert short["max_tokens"] == 8 and short["reasoning_effort"] == "none"
    assert long["max_tokens"] == 96 and long["reasoning_effort"] == "none"
    assert varied_a["messages"] != varied_b["messages"]
    assert varied_a["temperature"] == varied_b["temperature"] == 0


def test_prompt_case_alternates_fixed_and_deterministic_varied_inputs():
    cases = [_prompt_case("alternating", index) for index in range(6)]
    assert cases == [("fixed", 1), ("varied", 1), ("fixed", 2), ("varied", 2), ("fixed", 3), ("varied", 3)]


def test_gpu_query_parser_records_only_metadata():
    rows = _parse_gpu_query('NVIDIA GeForce RTX 5090, 0, 3, 17, 29600, 32607, 118.4')
    assert rows == [{
        "name": "NVIDIA GeForce RTX 5090",
        "index": 0,
        "gpu_utilization_percent": 3,
        "memory_utilization_percent": 17,
        "memory_used_mib": 29600,
        "memory_total_mib": 32607,
        "power_watts": 118.4,
    }]


def test_provider_stats_seconds_are_normalized_to_milliseconds():
    assert _provider_metrics({"stats": {"time_to_first_token": 0.125, "generation_time": 1.5, "tokens_per_second": 42.0}}) == {
        "ttft_ms": 125.0,
        "generation_ms": 1500.0,
        "tokens_per_second": 42.0,
    }


def test_disconnect_probe_detects_supported_text_fields_without_retaining_them():
    assert _chunk_has_text_delta(b'data: {"choices":[{"delta":{"reasoning_content":"hidden"}}]}\n\n')
    assert _chunk_has_text_delta(b'data: {"choices":[{"delta":{"content":"visible"}}]}\n\n')
    assert not _chunk_has_text_delta(b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n')
    assert not _chunk_has_text_delta(b'data: {malformed}\n\n')
