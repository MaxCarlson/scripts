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
REPO_ROOT = MODULE_ROOT.parent.parent
SRC_PARENT = REPO_ROOT.parent
TEST_FILE = MODULE_ROOT / "tests" / "integration_win32_test.py"
BASETEMP = MODULE_ROOT / ".pytest_tmp_root" / "interactive"
RESULT_PATH = MODULE_ROOT / ".pytest_tmp_root" / "interactive_latest.json"

_ALLOWLISTED_TARGETS: dict[str, Path] = {
    "current": MODULE_ROOT,
    "main": SRC_PARENT / "scripts" / "modules" / "procwatch",
    "phase1": SRC_PARENT / "scripts-procwatch-phase1" / "modules" / "procwatch",
    "phase2": SRC_PARENT / "scripts-procwatch-phase2" / "modules" / "procwatch",
    "phase3": SRC_PARENT / "scripts-procwatch-phase3" / "modules" / "procwatch",
    "phase4": SRC_PARENT / "scripts-procwatch-phase4" / "modules" / "procwatch",
}


def _resolve_allowlisted_target(target: str | None) -> Path:
    key = (target or "current").strip().lower()
    if key not in _ALLOWLISTED_TARGETS:
        raise ValueError(f"Target {target!r} is not in allowlist: {sorted(_ALLOWLISTED_TARGETS)}")
    candidate = _ALLOWLISTED_TARGETS[key].resolve()
    if not (candidate / "tests" / "integration_win32_test.py").is_file():
        raise FileNotFoundError(f"Allowlisted target missing integration_win32_test.py: {candidate}")
    return candidate


def _probe_source_identity(target_module_root: Path, env: dict[str, str]) -> dict[str, object]:
    probe_code = (
        "import json, procwatch, sys; "
        "print(json.dumps({'procwatch_file': procwatch.__file__, "
        "'procwatch_version': procwatch.__version__, 'sys_executable': sys.executable}))"
    )
    probe = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=str(target_module_root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    identity: dict[str, object] = {
        "module_root": str(target_module_root),
        "sys_executable": sys.executable,
    }
    if probe.returncode == 0 and probe.stdout.strip():
        try:
            identity.update(json.loads(probe.stdout.strip().splitlines()[-1]))
        except json.JSONDecodeError:
            identity["probe_error"] = probe.stdout.strip()
    else:
        identity["probe_error"] = probe.stderr.strip() or f"rc={probe.returncode}"

    git_proc = subprocess.run(
        ["git", "-C", str(target_module_root.parent.parent), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    identity["git_head"] = git_proc.stdout.strip() if git_proc.returncode == 0 else None
    return identity


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


def run_allowlisted_gui_tests(target: str | None = None) -> dict[str, object]:
    """Execute only tests/integration_win32_test.py with an isolated basetemp."""
    target_root = _resolve_allowlisted_target(target)
    test_file = target_root / "tests" / "integration_win32_test.py"
    basetemp = target_root / ".pytest_tmp_root" / "interactive"
    result_path = target_root / ".pytest_tmp_root" / "interactive_latest.json"
    basetemp.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{target_root}{os.pathsep}{existing_pp}" if existing_pp else str(target_root)

    source_identity = _probe_source_identity(target_root, env)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-v",
        f"--basetemp={basetemp}",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(target_root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    payload: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "context": _desktop_context(),
        "source_identity": source_identity,
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
            target: str | None = None
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > 0:
                if length > 4096:
                    self.send_error(413)
                    return
                raw = self.rfile.read(length)
                try:
                    req = json.loads(raw.decode("utf-8"))
                    if not isinstance(req, dict):
                        self.send_error(400)
                        return
                    target = req.get("target")
                    if target is not None and not isinstance(target, str):
                        self.send_error(400)
                        return
                except Exception:
                    self.send_error(400)
                    return
            try:
                res = run_allowlisted_gui_tests(target=target)
            except (ValueError, FileNotFoundError):
                self.send_error(400)
                return
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
