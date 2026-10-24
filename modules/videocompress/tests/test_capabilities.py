"""
Tests for videocompress capability probing.
"""

from __future__ import annotations

from videocompress.capabilities import probe_capabilities


def test_probe_capabilities_returns_expected_keys():
    caps = probe_capabilities(check_encode=False)
    assert isinstance(caps, dict)
    assert "ffmpeg_available" in caps
    assert "ffprobe_available" in caps
    assert "gpu_available" in caps
    assert "hardware_encoders" in caps
    assert "curses_available" in caps
    assert isinstance(caps["hardware_encoders"], list)
