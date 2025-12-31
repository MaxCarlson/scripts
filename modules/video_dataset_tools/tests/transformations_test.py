import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Ensure module import path
sys.path.append(str(Path(__file__).resolve().parents[2].parent))

from video_dataset_tools import transformations as t


@pytest.fixture()
def fake_ffmpeg(monkeypatch, tmp_path):
    calls = []

    def fake_which(binary):
        return tmp_path / binary

    def fake_run(cmd, stdout=None, stderr=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(t.shutil, "which", fake_which)
    monkeypatch.setattr(t.subprocess, "run", fake_run)
    return calls


@pytest.fixture()
def failing_run(monkeypatch):
    def _run(cmd, stdout=None, stderr=None):
        return SimpleNamespace(returncode=1, stderr=b"boom")

    monkeypatch.setattr(t.subprocess, "run", _run)
    monkeypatch.setattr(t.shutil, "which", lambda _: True)


def test_trim_video_cpu_threads(fake_ffmpeg, tmp_path):
    src = tmp_path / "input.mp4"
    out = tmp_path / "out.mp4"
    src.write_text("data")

    t.trim_video(src, out, start=1.5, duration=2.0, audio_copy=False, mode="cpu", threads=3)

    cmd = fake_ffmpeg[-1]
    assert "-hwaccel" not in cmd
    assert cmd[:5] == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss"]
    assert "-threads" in cmd and cmd[cmd.index("-threads") + 1] == "3"
    assert cmd[-1] == str(out)


def test_scale_video_cuda_encodes_with_nvenc(fake_ffmpeg, tmp_path):
    src = tmp_path / "input.mp4"
    out = tmp_path / "out.mp4"
    src.write_text("data")

    t.scale_video(src, out, height=240, keep_aspect=True, mode="cuda", threads=None)

    cmd = fake_ffmpeg[-1]
    assert "-hwaccel" in cmd and "cuda" in cmd
    assert "h264_nvenc" in cmd
    assert cmd[-1] == str(out)


def test_change_video_bitrate_requires_params(monkeypatch, tmp_path):
    monkeypatch.setattr(t.shutil, "which", lambda _: True)
    with pytest.raises(ValueError):
        t.change_video_bitrate(tmp_path / "in.mp4", tmp_path / "out.mp4", bitrate=None, crf=None)


def test_run_failure_raises(monkeypatch, tmp_path):
    def bad_run(cmd, stdout=None, stderr=None):
        return SimpleNamespace(returncode=1, stderr=b"nope")

    monkeypatch.setattr(t.subprocess, "run", bad_run)
    monkeypatch.setattr(t.shutil, "which", lambda _: True)

    with pytest.raises(RuntimeError):
        t.trim_video(tmp_path / "in.mp4", tmp_path / "out.mp4", duration=1)


def test_change_container_copy_only(fake_ffmpeg, tmp_path):
    src = tmp_path / "in.mp4"
    out = tmp_path / "out.mp4"
    src.write_text("data")

    t.change_container(src, out)
    cmd = fake_ffmpeg[-1]
    assert "-c" in cmd
    assert cmd[cmd.index("-c") + 1] == "copy"
