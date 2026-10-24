"""Comprehensive tests for historical telemetry REST API endpoints and lineage traversal."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from runmux.models import RunRecord
from runmux.stats import HostTelemetry, ProcessStats
from runmux.store import RunStore
from runmux.telemetry_store import TelemetryStore
from runmux.web import create_runmux_web_app


def create_test_record(store: RunStore, run_id: str, *, restart_of: str | None = None) -> RunRecord:
    record = store.create_run(
        run_id=run_id,
        name=f"test_{run_id}",
        status="running",
        program=sys.executable,
        argv_json="[]",
        cwd=str(store.state_dir),
        env_overrides_json="{}",
        auth_token="test_token",
        log_path=str(store.state_dir / f"{run_id}.log"),
        command_line="python",
        restart_of=restart_of,
    )
    store.update_run(record.id, pid=os.getpid(), started_at="2026-10-24T08:00:00Z")
    return store.get_run(record.id)


def test_unauthenticated_requests_return_401(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_test_record(store, "20261024-080000-000001")
    app = create_runmux_web_app(tmp_path, login_code="secret_code", enable_telemetry_history=False)

    with TestClient(app, base_url="http://localhost") as client:
        res1 = client.get(f"/api/runs/{record.id}/telemetry/history", headers={"Origin": "http://localhost"})
        assert res1.status_code == 401

        res2 = client.get("/api/telemetry/history", headers={"Origin": "http://localhost"})
        assert res2.status_code == 401


def test_unknown_run_returns_404(tmp_path: Path) -> None:
    app = create_runmux_web_app(tmp_path, login_code="secret_code", enable_telemetry_history=False)

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret_code"}, headers={"Origin": "http://localhost"})
        response = client.get(
            "/api/runs/20261024-080000-999999/telemetry/history",
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Run not found"


def test_invalid_query_range_returns_400(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_test_record(store, "20261024-080000-000002")
    app = create_runmux_web_app(tmp_path, login_code="secret_code", enable_telemetry_history=False)

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret_code"}, headers={"Origin": "http://localhost"})
        response = client.get(
            f"/api/runs/{record.id}/telemetry/history?since=1792830000&until=1792820000",
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 400


def test_authenticated_run_history_query(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_test_record(store, "20261024-080000-000003")

    # Seed synthetic history into telemetry_store
    telemetry_store = TelemetryStore(tmp_path)
    base_t = 1792828800.0 # 2026-10-24T08:00:00Z
    samples = []
    for i in range(10):
        t = base_t + (i * 5.0)
        samples.append(
            ProcessStats(
                record=record,
                process_count=1,
                thread_count=4,
                cpu_percent=15.0 + i,
                cpu_percent_normalized=(15.0 + i) / 4.0,
                rss_bytes=100 * 1024 * 1024 + (i * 1024),
                read_bytes_per_second=1024.0,
                write_bytes_per_second=2048.0,
                sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
                sampled_epoch=t,
            )
        )
    telemetry_store.insert_process_samples(samples)

    telemetry_store.record_event(
        record.id,
        "pause",
        timestamp=base_t + 25.0,
        reason="user action via web UI",
    )

    app = create_runmux_web_app(tmp_path, login_code="secret_code", enable_telemetry_history=False)

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret_code"}, headers={"Origin": "http://localhost"})
        response = client.get(
            f"/api/runs/{record.id}/telemetry/history?since={base_t}&until={base_t + 60.0}",
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["run_id"] == record.id
        assert data["status"] == "running"
        assert "provenance" in data
        assert data["provenance"]["cpu_scope"] == "process_tree"
        assert data["provenance"]["raw_sample_count"] == 10
        assert data["provenance"]["returned_points"] == 10

        series = data["series"]
        assert len(series) == 10
        assert series[0]["epoch"] == base_t
        assert series[0]["cpu_percent"] == 15.0
        assert series[0]["rss_bytes"] == 100 * 1024 * 1024

        events = data["events"]
        assert len(events) == 1
        assert events[0]["event"] == "pause"
        assert events[0]["reason"] == "user action via web UI"


def test_lineage_traversal_with_restart_gap_and_event(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    # Parent run 1
    p1 = create_test_record(store, "20261024-070000-000001")
    # Child run 2
    c2 = create_test_record(store, "20261024-073000-000002", restart_of=p1.id)

    telemetry_store = TelemetryStore(tmp_path)
    t1_base = 1792825200.0 # 07:00:00Z
    t2_base = 1792827000.0 # 07:30:00Z (30 min later)

    # Insert samples for parent run
    p1_samples = [
        ProcessStats(
            record=p1,
            process_count=1,
            thread_count=2,
            cpu_percent=10.0,
            rss_bytes=50 * 1024 * 1024,
            read_bytes_per_second=0.0,
            write_bytes_per_second=0.0,
            sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t1_base)),
            sampled_epoch=t1_base,
        )
    ]
    telemetry_store.insert_process_samples(p1_samples)

    # Insert samples for child run
    c2_samples = [
        ProcessStats(
            record=c2,
            process_count=1,
            thread_count=2,
            cpu_percent=20.0,
            rss_bytes=60 * 1024 * 1024,
            read_bytes_per_second=0.0,
            write_bytes_per_second=0.0,
            sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t2_base)),
            sampled_epoch=t2_base,
        )
    ]
    telemetry_store.insert_process_samples(c2_samples)

    app = create_runmux_web_app(tmp_path, login_code="secret_code", enable_telemetry_history=False)

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret_code"}, headers={"Origin": "http://localhost"})

        # 1. Query with include_lineage=false (default): should return only c2 data
        res_default = client.get(
            f"/api/runs/{c2.id}/telemetry/history?since={t1_base - 10}&until={t2_base + 10}&include_lineage=false",
            headers={"Origin": "http://localhost"},
        )
        assert res_default.status_code == 200
        data_default = res_default.json()
        assert len(data_default["series"]) == 1
        assert data_default["series"][0]["epoch"] == t2_base

        # 2. Query with include_lineage=true: should chain p1 + restart gap + c2
        res_lineage = client.get(
            f"/api/runs/{c2.id}/telemetry/history?since={t1_base - 10}&until={t2_base + 10}&include_lineage=true",
            headers={"Origin": "http://localhost"},
        )
        assert res_lineage.status_code == 200
        data_lineage = res_lineage.json()
        series = data_lineage["series"]
        events = data_lineage["events"]

        # Points: p1 sample, gap point, c2 sample
        assert len(series) == 3
        assert series[0]["epoch"] == t1_base
        assert series[0]["run_id"] == p1.id

        # Explicit gap marker between p1 and c2
        assert series[1]["is_gap"] is True
        assert series[1]["run_id"] == p1.id
        assert "restart from" in series[1]["gap_reason"]

        assert series[2]["epoch"] == t2_base
        assert series[2]["run_id"] == c2.id

        # Restart event
        restart_events = [e for e in events if e.get("event") == "restart"]
        assert len(restart_events) == 1
        assert restart_events[0]["old_run_id"] == p1.id
        assert restart_events[0]["new_run_id"] == c2.id


def test_authenticated_host_overview_history_query(tmp_path: Path) -> None:
    telemetry_store = TelemetryStore(tmp_path)
    base_t = 1792828800.0
    for i in range(5):
        t = base_t + (i * 5.0)
        telemetry_store.insert_host_sample(
            HostTelemetry(
                cpu_percent=25.0 + i,
                cpu_count=8,
                memory_used_bytes=16 * 1024 * 1024 * 1024,
                memory_available_bytes=16 * 1024 * 1024 * 1024,
                memory_total_bytes=32 * 1024 * 1024 * 1024,
                memory_percent=50.0,
                net_read_bytes_per_second=1024.0,
                net_write_bytes_per_second=2048.0,
                gpu_devices=[],
                sampled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
                sampled_epoch=t,
            )
        )

    app = create_runmux_web_app(tmp_path, login_code="secret_code", enable_telemetry_history=False)

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "secret_code"}, headers={"Origin": "http://localhost"})
        response = client.get(
            f"/api/telemetry/history?since={base_t}&until={base_t + 30.0}",
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 200
        data = response.json()

        assert "provenance" in data
        assert data["provenance"]["scope"] == "host"
        assert len(data["series"]) == 5
        assert data["series"][0]["cpu_percent"] == 25.0
        assert data["series"][0]["memory_used_bytes"] == 16 * 1024 * 1024 * 1024
