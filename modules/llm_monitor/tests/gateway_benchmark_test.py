from llm_monitor.gateway_benchmark import ORDERS, PATHS, _body, _summarize, _summarize_timings, main


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
