import pytest
import sys
import os
from unittest.mock import patch, call
import video_tool

@pytest.fixture(autouse=True)
def no_sys_exit(monkeypatch):
    # Prevent sys.exit in tests
    monkeypatch.setattr(sys, "exit", lambda code=1: (_ for _ in ()).throw(SystemExit(code)))

def test_parse_time():
    assert video_tool.parse_time("10") == 10
    assert video_tool.parse_time("01:00") == 60
    assert video_tool.parse_time("01:02:03.5") == 3723.5

def test_escape_filename():
    assert video_tool.escape_filename("foo.mp4") == "foo.mp4"
    assert video_tool.escape_filename("foo'bar.mp4") == "foo'\\''bar.mp4"

@patch("video_tool.subprocess.run")
def test_merge(mock_run, tmp_path):
    f1 = tmp_path/"a.mp4"
    f2 = tmp_path/"b.mp4"
    f1.write_bytes(b"x")
    f2.write_bytes(b"y")
    out = tmp_path/"out.mp4"
    video_tool.merge([str(f1), str(f2)], str(out))
    assert mock_run.called

@patch("video_tool.subprocess.run")
@patch("video_tool.subprocess.check_output")
def test_remove_video_slices(mock_check, mock_run, tmp_path):
    f1 = tmp_path/"input.mp4"
    f1.write_bytes(b"x")
    mock_check.return_value = "10\n"
    out = tmp_path/"out.mp4"
    # Remove 1s-3s, so keep 0-1 and 3-10
    video_tool.remove_video_slices(str(f1), [("1", "3")], str(out))
    # Should call ffmpeg for each segment, then merge
    calls = [call(["ffmpeg", "-y", "-ss", "0.0", "-to", "1.0", "-i", str(f1), "-c", "copy", mock_run.call_args_list[0][0][0][-1]]),
             call(["ffmpeg", "-y", "-ss", "3.0", "-to", "10.0", "-i", str(f1), "-c", "copy", mock_run.call_args_list[1][0][0][-1]]),
             call(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", mock_run.call_args_list[2][0][0][6], "-c", "copy", str(out)])]
    # Number of calls: two segments, one merge
    assert mock_run.call_count == 3

@patch("video_tool.subprocess.run")
@patch("video_tool.subprocess.check_output")
def test_downscale(mock_check, mock_run, tmp_path):
    f1 = tmp_path/"input.mp4"
    f1.write_bytes(b"x")
    mock_check.return_value = "3840,2160\n"
    out = tmp_path/"out.mp4"
    video_tool.downscale(str(f1), str(out), "1920:1080")
    assert mock_run.called

def test_get_video_duration(monkeypatch):
    monkeypatch.setattr(video_tool.subprocess, "check_output", lambda *a, **k: "12.5\n")
    assert video_tool.get_video_duration("foo.mp4") == 12.5

def test_remove_video_slices_invalid(monkeypatch, tmp_path):
    f1 = tmp_path/"input.mp4"
    f1.write_bytes(b"x")
    monkeypatch.setattr(video_tool, "get_video_duration", lambda x: 10.0)
    # Cut everything
    with pytest.raises(ValueError):
        video_tool.remove_video_slices(str(f1), [("0", "10")], "out.mp4")
    # Bad slice
    with pytest.raises(ValueError):
        video_tool.remove_video_slices(str(f1), [("5", "1")], "out.mp4")

def test_detect_duplicate(capsys):
    video_tool.detect_duplicate(".")
    out = capsys.readouterr().out
    assert "NOT IMPLEMENTED" in out
