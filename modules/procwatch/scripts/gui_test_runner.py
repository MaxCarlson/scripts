#!/usr/bin/env python3
"""Allowlisted interactive GUI test runner for ProcWatch (runs on WinSta0\\Default)."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

MODULE_ROOT = Path(__file__).resolve().parent.parent
TEST_FILE = MODULE_ROOT / "tests" / "integration_win32_test.py"
BASETEMP = MODULE_ROOT / ".pytest_tmp_root" / "interactive"
RESULT_PATH = MODULE_ROOT / ".pytest_tmp_root" / "interactive_latest.json"


def _desktop_context() -> dict[str, object]:
    if sys.platform != "win32":
        return {"platform": sys.platform}
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    sid = wintypes.DWORD()
    k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    buf = ctypes.create_unicode_buffer(256)
    desk = u32.GetThreadDesktop(k32.GetCurrentThreadId())
    u32.GetUserObjectInformationW(desk, 2, buf, 512, None)
    return {
        "pid": os.getpid(),
        "session_id": int(sid.value),
        "desktop": buf.value,
        "foreground_hwnd": int(u32.GetForegroundWindow() or 0),
        "python": sys.version.split()[0],
    }


def run_allowlisted_gui_tests() -> dict[str, object]:
    """Execute only tests/integration_win32_test.py with an isolated basetemp."""
    BASETEMP.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(TEST_FILE),
        "-v",
        f"--basetemp={BASETEMP}",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(MODULE_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    payload: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "context": _desktop_context(),
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def serve_loopback(port: int) -> int:
    """Run an on-demand loopback HTTP trigger for allowlisted GUI tests (Ctrl+C to stop)."""
    token = secrets.token_urlsafe(24)
    info_path = Path.home() / ".procwatch" / "gui_runner.json"
    info_path.parent.mkdir(parents=True, exist_ok=True)

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/run-gui-tests":
                self.send_error(404)
                return
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {token}":
                self.send_error(403)
                return
            res = run_allowlisted_gui_tests()
            body = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", port), _Handler)
    actual_port = server.server_address[1]
    info_path.write_text(
        json.dumps({"port": actual_port, "token": token, "context": _desktop_context()}, indent=2),
        encoding="utf-8",
    )
    print(f"ProcWatch GUI test runner listening on 127.0.0.1:{actual_port} (Ctrl+C to stop).", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped GUI test runner.", flush=True)
    finally:
        server.server_close()
        info_path.unlink(missing_ok=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Allowlisted interactive GUI test runner for ProcWatch.")
    parser.add_argument("-r", "--run", action="store_true", help="Run integration_win32_test.py once and exit.")
    parser.add_argument("-s", "--serve", action="store_true", help="Listen on 127.0.0.1 for allowlisted runs.")
    parser.add_argument("-p", "--port", type=int, default=0, help="Loopback port for --serve (0 = ephemeral).")
    args = parser.parse_args()

    if args.serve:
        return serve_loopback(args.port)
    res = run_allowlisted_gui_tests()
    print(res["stdout"])
    if res["stderr"]:
        print(res["stderr"], file=sys.stderr)
    return int(res["returncode"])


if __name__ == "__main__":
    sys.exit(main())
