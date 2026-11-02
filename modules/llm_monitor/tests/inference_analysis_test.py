from llm_monitor.inference_analysis import compute_model_analytics, correlate_request_hardware
from llm_monitor.inference_models import HardwareSample, InferenceRequest


def _make_sample(sample_id, mono_time, util=50.0, vram=8000.0, ctrl=15.0, power=100.0, dev_id="GPU-1"):
    return HardwareSample(
        sample_id=sample_id,
        timestamp="2026-11-01T20:00:00.000000+00:00",
        timestamp_monotonic=mono_time,
        device_id=dev_id,
        device_name="RTX 5090",
        source="nvidia_smi",
        gpu_utilization_percent=util,
        memory_controller_utilization_percent=ctrl,
        vram_used_bytes=vram * 1024 * 1024,
        vram_total_bytes=32000.0 * 1024 * 1024,
        temperature_celsius=55.0,
        power_watts=power,
        validity="valid",
    )


def test_correlate_request_hardware_empty_samples():
    req = InferenceRequest(
        request_id="r1",
        server_instance_id="s1",
        source="gateway",
        state="completed",
        started_monotonic=10.0,
        ended_monotonic=12.0,
        elapsed_seconds=2.0,
    )
    result = correlate_request_hardware(req, [])
    assert result["gpu_average_percent"] is None
    assert result["sample_count"] == 0
    assert result["coverage_fraction"] == 0.0
    assert result["is_sparse"] is True


def test_correlate_request_hardware_single_point_sample():
    req = InferenceRequest(
        request_id="r1",
        server_instance_id="s1",
        source="gateway",
        state="completed",
        started_monotonic=10.0,
        ended_monotonic=10.4,
        elapsed_seconds=0.4,
    )
    samples = [_make_sample(1, 10.2, util=65.0, vram=10000.0)]
    result = correlate_request_hardware(req, samples)

    assert result["gpu_average_percent"] == 65.0
    assert result["gpu_peak_percent"] == 65.0
    assert result["sample_count"] == 1
    assert result["attribution_scope"] == "device_point_sample"
    assert result["is_sparse"] is True


def test_correlate_request_hardware_time_weighted_averages():
    # Request from 10.0 to 14.0 (4 seconds)
    # Sample 1 at 10.0: util=40.0 for 1.0s (10.0 to 11.0)
    # Sample 2 at 11.0: util=80.0 for 3.0s (11.0 to 14.0)
    # Expected weighted util: (40.0*1.0 + 80.0*3.0) / 4.0 = (40 + 240) / 4 = 70.0%
    req = InferenceRequest(
        request_id="r1",
        server_instance_id="s1",
        source="gateway",
        state="completed",
        started_monotonic=10.0,
        ended_monotonic=14.0,
        elapsed_seconds=4.0,
    )
    samples = [
        _make_sample(1, 10.0, util=40.0, vram=4000.0),
        _make_sample(2, 11.0, util=80.0, vram=8000.0),
        _make_sample(3, 14.0, util=20.0, vram=2000.0),
    ]
    result = correlate_request_hardware(req, samples)

    assert result["gpu_average_percent"] == 70.0
    assert result["gpu_peak_percent"] == 80.0
    assert result["sample_count"] == 3
    assert result["coverage_fraction"] == 1.0
    assert result["is_sparse"] is False
    assert result["attribution_scope"] == "device_during_request"


def test_correlate_request_hardware_gap_exceeds_max_gap():
    # Samples with an 8 second gap (> max_gap of 5.0)
    req = InferenceRequest(
        request_id="r1",
        server_instance_id="s1",
        source="gateway",
        state="completed",
        started_monotonic=10.0,
        ended_monotonic=20.0,
        elapsed_seconds=10.0,
    )
    samples = [
        _make_sample(1, 10.0, util=50.0),
        _make_sample(2, 18.0, util=90.0),
    ]
    result = correlate_request_hardware(req, samples, max_gap_seconds=5.0)
    # Interval between 10.0 and 18.0 is 8s > 5s max_gap, so weighted interval is not extrapolated
    assert result["sample_count"] == 2
    assert result["is_sparse"] is True


def test_correlate_request_hardware_concurrent_requests_share_device_telemetry():
    # Two requests overlapping in time: both receive device-wide samples without division
    req1 = InferenceRequest(
        request_id="r1", server_instance_id="s1", source="gateway", state="completed",
        started_monotonic=10.0, ended_monotonic=13.0, elapsed_seconds=3.0,
    )
    req2 = InferenceRequest(
        request_id="r2", server_instance_id="s1", source="gateway", state="completed",
        started_monotonic=11.0, ended_monotonic=14.0, elapsed_seconds=3.0,
    )
    samples = [
        _make_sample(1, 10.0, util=60.0),
        _make_sample(2, 12.0, util=80.0),
        _make_sample(3, 14.0, util=40.0),
    ]

    res1 = correlate_request_hardware(req1, samples)
    res2 = correlate_request_hardware(req2, samples)

    assert res1["attribution_scope"] == "device_during_request"
    assert res2["attribution_scope"] == "device_during_request"
    assert res1["gpu_peak_percent"] == 80.0
    assert res2["gpu_peak_percent"] == 80.0


def test_compute_model_analytics_denominators_and_null_preservation():
    # Request 1: has reasoning tokens (30), input (10), generated (50)
    # Request 2: reasoning is None (provider did not expose reasoning), input (20), generated (60)
    # Request 3: failed request (should not contribute to completed token metrics)
    req1 = InferenceRequest(
        request_id="r1", server_instance_id="srv-1", provider_model_id="m1", source="gateway",
        state="completed", input_tokens=10, reasoning_tokens=30, output_tokens=20, generated_tokens=50,
        elapsed_seconds=1.0, time_to_first_text_seconds=0.2, generation_tokens_per_second=50.0,
        gpu_average_percent=70.0, gpu_peak_vram_bytes=8000.0,
    )
    req2 = InferenceRequest(
        request_id="r2", server_instance_id="srv-1", provider_model_id="m1", source="gateway",
        state="completed", input_tokens=20, reasoning_tokens=None, output_tokens=60, generated_tokens=60,
        elapsed_seconds=2.0, time_to_first_text_seconds=0.4, generation_tokens_per_second=30.0,
        gpu_average_percent=50.0, gpu_peak_vram_bytes=10000.0,
    )
    req3 = InferenceRequest(
        request_id="r3", server_instance_id="srv-1", provider_model_id="m1", source="gateway",
        state="failed", input_tokens=5, reasoning_tokens=None, output_tokens=None, generated_tokens=None,
    )

    analytics = compute_model_analytics([req1, req2, req3], model_id="m1")

    counts = analytics["request_counts"]
    assert counts["observed_requests"] == 3
    assert counts["completed_requests"] == 2
    assert counts["failed_requests"] == 1

    tokens = analytics["tokens"]
    # Input tokens: mean of 10 and 20 = 15.0, sample_count = 2
    assert tokens["input_tokens"]["mean"] == 15.0
    assert tokens["input_tokens"]["sample_count"] == 2

    # Reasoning tokens: ONLY req1 had reasoning tokens! Denominator must be 1, NOT 2 with a 0!
    assert tokens["reasoning_tokens"]["mean"] == 30.0
    assert tokens["reasoning_tokens"]["median"] == 30.0
    assert tokens["reasoning_tokens"]["sample_count"] == 1

    # Generated tokens: 50 and 60 -> mean 55.0
    assert tokens["generated_tokens"]["mean"] == 55.0
    assert tokens["generated_tokens"]["sample_count"] == 2

    # Timing
    timing = analytics["timing"]
    assert timing["duration_seconds"]["mean"] == 1.5
    assert timing["time_to_first_text_seconds"]["mean"] == 0.3
    assert timing["generation_tokens_per_second"]["mean"] == 40.0
    # Sample size < 5 -> p90 must be None
    assert timing["duration_seconds"]["p90"] is None

    # Hardware
    hw = analytics["hardware"]
    assert hw["gpu_average_percent"]["mean"] == 60.0
    assert hw["gpu_peak_vram_bytes"]["max"] == 10000.0


def test_compute_model_analytics_percentiles_with_large_sample():
    requests = [
        InferenceRequest(
            request_id=f"r{i}",
            server_instance_id="srv-1",
            provider_model_id="m1",
            source="gateway",
            state="completed",
            elapsed_seconds=float(i),
        )
        for i in range(1, 11)  # 1 to 10
    ]
    analytics = compute_model_analytics(requests, model_id="m1")
    duration = analytics["timing"]["duration_seconds"]
    assert duration["sample_count"] == 10
    assert duration["median"] == 5.5
    assert duration["p90"] is not None
    assert duration["p95"] is not None


def test_correlate_request_hardware_multi_gpu_isolation():
    req = InferenceRequest(
        request_id="r1",
        server_instance_id="s1",
        source="gateway",
        state="completed",
        started_monotonic=10.0,
        ended_monotonic=12.0,
        elapsed_seconds=2.0,
    )
    # Samples interleaved from GPU-0 and GPU-1
    samples = [
        _make_sample(1, 10.0, util=80.0, vram=10000.0, dev_id="GPU-0"),
        _make_sample(2, 10.0, util=10.0, vram=2000.0, dev_id="GPU-1"),
        _make_sample(3, 11.0, util=85.0, vram=10500.0, dev_id="GPU-0"),
        _make_sample(4, 11.0, util=12.0, vram=2100.0, dev_id="GPU-1"),
        _make_sample(5, 12.0, util=90.0, vram=11000.0, dev_id="GPU-0"),
        _make_sample(6, 12.0, util=15.0, vram=2200.0, dev_id="GPU-1"),
    ]
    # By default, isolates to first device (GPU-0)
    result_default = correlate_request_hardware(req, samples)
    assert result_default["device_id"] == "GPU-0"
    assert result_default["gpu_peak_percent"] == 90.0
    assert result_default["gpu_average_percent"] > 70.0
    assert result_default["sample_count"] == 3

    # Explicit target device GPU-1
    result_gpu1 = correlate_request_hardware(req, samples, device_id="GPU-1")
    assert result_gpu1["device_id"] == "GPU-1"
    assert result_gpu1["gpu_peak_percent"] == 15.0
    assert result_gpu1["gpu_average_percent"] < 20.0
    assert result_gpu1["sample_count"] == 3
