#!/usr/bin/env python3
from pathlib import Path

from phonemon.probes import probe_gpu


def test_probe_gpu_absent(monkeypatch):
    monkeypatch.delenv("PHONEMON_SYSFS_ROOT", raising=False)
    g = probe_gpu()
    assert g.percent is None or (0.0 <= g.percent <= 100.0)


def test_probe_gpu_busy_percentage(tmp_path: Path, monkeypatch):
    root = tmp_path / "sys"
    (root / "class/kgsl/kgsl-3d0/devfreq").mkdir(parents=True)
    (root / "class/kgsl/kgsl-3d0/gpu_busy_percentage").write_text("37\n", encoding="utf-8")
    (root / "class/kgsl/kgsl-3d0/devfreq/cur_freq").write_text("800000000\n", encoding="utf-8")
    (root / "class/kgsl/kgsl-3d0/gpu_model").write_text("Adreno 750\n", encoding="utf-8")
    monkeypatch.setenv("PHONEMON_SYSFS_ROOT", str(root.parent))
    g = probe_gpu()
    assert g.percent is not None and abs(g.percent - 37.0) < 0.1
    assert g.freq_mhz is not None and abs(g.freq_mhz - 800.0) < 0.1
    assert g.model == "Adreno 750"
    assert g.notes and "gpu_busy_percentage" in g.notes


def test_probe_gpu_gpubusy_legacy(tmp_path: Path, monkeypatch):
    root = tmp_path / "sys"
    (root / "class/kgsl/kgsl-3d0").mkdir(parents=True)
    (root / "class/kgsl/kgsl-3d0/gpubusy").write_text("125 500\n", encoding="utf-8")
    monkeypatch.setenv("PHONEMON_SYSFS_ROOT", str(root.parent))
    g = probe_gpu()
    assert g.percent is not None and abs(g.percent - 25.0) < 0.1
    assert g.freq_mhz is None or g.freq_mhz >= 0.0
    assert g.notes and "gpubusy" in g.notes
