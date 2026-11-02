import time
from unittest.mock import MagicMock

from llm_monitor.gpu_sampler import GpuSampler
from llm_monitor.inference_models import InferenceRequest
from llm_monitor.live_store import LiveInferenceStore


def _make_fake_gpu(index=0, name="Fake RTX", load=45.0, mem_used=4000.0, mem_total=16000.0, temp=55.0, power=120.0, uuid=None):
    return {
        "id": index,
        "name": name,
        "load": load,
        "memory_utilization": 20.0,
        "mem_used": mem_used * 1024 * 1024,
        "mem_free": (mem_total - mem_used) * 1024 * 1024,
        "mem_total": mem_total * 1024 * 1024,
        "temp": temp,
        "power_w": power,
        "uuid": uuid,
    }


def test_gpu_sampler_discovers_devices_and_records_samples():
    store = LiveInferenceStore()
    fake_devices = [_make_fake_gpu(index=0, uuid="GPU-fake-001")]
    sampler = GpuSampler(store, query_fn=lambda **kwargs: fake_devices)

    samples = sampler.sample_now()
    assert len(samples) == 1
    sample = samples[0]

    assert sample.device_id == "GPU-fake-001"
    assert sample.device_name == "Fake RTX"
    assert sample.gpu_utilization_percent == 45.0
    assert sample.memory_controller_utilization_percent == 20.0
    assert sample.vram_used_bytes == 4000.0 * 1024 * 1024
    assert sample.vram_total_bytes == 16000.0 * 1024 * 1024
    assert sample.temperature_celsius == 55.0
    assert sample.power_watts == 120.0
    assert sample.validity == "valid"

    # Verify store has the sample
    stored = store.hardware_samples()
    assert len(stored) == 1
    assert stored[0].sample_id == sample.sample_id


def test_gpu_sampler_handles_multiple_devices_independently():
    store = LiveInferenceStore()
    fake_devices = [
        _make_fake_gpu(index=0, name="RTX 5090", load=80.0, uuid="GPU-001"),
        _make_fake_gpu(index=1, name="RTX 4090", load=10.0, uuid="GPU-002"),
    ]
    sampler = GpuSampler(store, query_fn=lambda **kwargs: fake_devices)

    samples = sampler.sample_now()
    assert len(samples) == 2
    assert samples[0].device_id == "GPU-001"
    assert samples[0].gpu_utilization_percent == 80.0
    assert samples[1].device_id == "GPU-002"
    assert samples[1].gpu_utilization_percent == 10.0

    # Device filter in store
    dev1_samples = store.hardware_samples(device_id="GPU-001")
    assert len(dev1_samples) == 1
    assert dev1_samples[0].gpu_utilization_percent == 80.0


def test_gpu_sampler_handles_missing_tooling_or_empty_response():
    store = LiveInferenceStore()
    sampler = GpuSampler(store, query_fn=lambda **kwargs: [])

    samples = sampler.sample_now()
    assert samples == []
    status = sampler.status()
    assert status["device_count"] == 0
    assert sampler.is_available is False


def test_gpu_sampler_handles_query_exceptions_gracefully():
    store = LiveInferenceStore()

    def failing_query(**kwargs):
        raise RuntimeError("nvidia-smi timed out")

    sampler = GpuSampler(store, query_fn=failing_query)
    samples = sampler.sample_now()
    assert samples == []
    status = sampler.status()
    assert "nvidia-smi timed out" in str(status["last_error"])


def test_gpu_sampler_lifecycle_start_stop_cleanly():
    store = LiveInferenceStore()
    fake_devices = [_make_fake_gpu()]
    sampler = GpuSampler(
        store,
        active_interval_seconds=0.05,
        idle_interval_seconds=0.05,
        query_fn=lambda **kwargs: fake_devices,
    )

    sampler.start()
    assert sampler.status()["state"] == "running"
    time.sleep(0.12)
    sampler.stop()

    assert sampler.status()["state"] == "stopped"
    assert len(store.hardware_samples()) >= 1

    # Second start/stop works cleanly
    sampler.start()
    sampler.stop()


def test_gpu_sampler_throttles_event_publishing():
    store = LiveInferenceStore()
    mock_hub = MagicMock()
    fake_devices = [_make_fake_gpu()]
    sampler = GpuSampler(
        store,
        publish_interval_seconds=0.5,
        event_hub=mock_hub,
        query_fn=lambda **kwargs: fake_devices,
    )

    sampler._collect_sample()
    assert mock_hub.publish.call_count == 1

    # Immediate second sample within 0.5s does not publish to event_hub
    sampler._collect_sample()
    assert mock_hub.publish.call_count == 1


def test_gpu_sampler_adaptive_interval_depends_on_active_requests():
    store = LiveInferenceStore()
    fake_devices = [_make_fake_gpu()]

    sampler = GpuSampler(
        store,
        active_interval_seconds=0.05,
        idle_interval_seconds=0.5,
        query_fn=lambda **kwargs: fake_devices,
    )

    # Idle initially
    assert sampler.is_active_fn() is False

    # Add active request
    req = InferenceRequest(
        request_id="req-active",
        server_instance_id="srv-1",
        source="gateway",
        state="active",
    )
    store.add_request(req)
    assert sampler.is_active_fn() is True
