"""Centralized launcher execution engine for managed wrappers and tools."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from .invocation_store import InvocationStore


def find_venv_python(manifest_path: Optional[Path | str] = None) -> str:
    """Resolve the appropriate Python executable for executing python_file targets."""
    # If running in a virtual environment, prefer the current interpreter
    if sys.prefix != sys.base_prefix and Path(sys.executable).is_file():
        return sys.executable

    # Look for .venv relative to manifest or its parent directory
    if manifest_path is not None:
        manifest_dir = Path(manifest_path).resolve().parent
        for candidate_root in (manifest_dir, manifest_dir.parent):
            if sys.platform == "win32":
                vpy = candidate_root / ".venv" / "Scripts" / "python.exe"
            else:
                vpy = candidate_root / ".venv" / "bin" / "python"
            if vpy.is_file():
                return str(vpy)

    return sys.executable


def is_launcher_proxy(target_path: Path) -> bool:
    """Check if the target script points back to another launcher proxy."""
    if not target_path.is_file():
        return False
    suffix = target_path.suffix.lower()
    if suffix in (".cmd", ".bat", ".sh", ".bash", ".ps1"):
        try:
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2048)
                if (
                    "script_logging.launcher" in head
                    or "Scripts Toolkit Managed Wrapper" in head
                ):
                    return True
        except OSError:
            pass
    return False


def launch_target(
    manifest_path: Path | str,
    command_name: str,
    args: Optional[Sequence[str]] = None,
    *,
    current_wrapper: Optional[Path | str] = None,
    origin: str = "launcher",
    store: Optional[InvocationStore] = None,
) -> int:
    """Resolve target program from manifest, execute child with stdio/signals, and record history."""
    target_args = list(args) if args is not None else []
    manifest_file = Path(manifest_path).resolve()

    if not manifest_file.is_file():
        sys.stderr.write(
            f"[script_logging.launcher] Manifest file not found: {manifest_file}\n"
        )
        return 127

    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
    except (json.JSONDecodeError, OSError) as err:
        sys.stderr.write(
            f"[script_logging.launcher] Failed to parse manifest JSON '{manifest_file}': {err}\n"
        )
        return 127

    commands = manifest_data.get("commands", {})
    if command_name not in commands:
        sys.stderr.write(
            f"[script_logging.launcher] Command '{command_name}' not found in manifest: {manifest_file}\n"
        )
        return 127

    cmd_info = commands[command_name]
    program_id = cmd_info.get("program_id", f"command:{command_name}")
    kind = cmd_info.get("kind", "console_script")
    raw_target = cmd_info.get("target")

    if not raw_target:
        sys.stderr.write(
            f"[script_logging.launcher] Target not specified for command '{command_name}' in manifest\n"
        )
        return 127

    target_path = Path(raw_target)
    if not target_path.is_absolute():
        target_path = (manifest_file.parent / target_path).resolve()
    else:
        target_path = target_path.resolve()

    # Recursion guard: check if target is the calling wrapper
    if current_wrapper is not None:
        wrapper_path = Path(current_wrapper).resolve()
        is_same = (
            str(target_path).lower() == str(wrapper_path).lower()
            if sys.platform == "win32"
            else target_path == wrapper_path
        )
        if is_same:
            sys.stderr.write(
                f"[script_logging.launcher] Recursive launcher execution detected: "
                f"Target is the wrapper itself ({target_path})\n"
            )
            return 127

    # Recursion guard: check if target is another launcher proxy
    if is_launcher_proxy(target_path):
        sys.stderr.write(
            f"[script_logging.launcher] Recursive launcher execution detected: "
            f"Target is another launcher proxy ({target_path})\n"
        )
        return 127

    # Target resolution check
    if not target_path.is_file():
        sys.stderr.write(
            f"[script_logging.launcher] Error: Target '{target_path}' for command '{command_name}' "
            "does not exist. Please run 'python setup.py' or bootstrap to build missing console scripts.\n"
        )
        return 127

    # Build command vector
    if kind == "python_file":
        py_exe = find_venv_python(manifest_file)
        child_cmd = [py_exe, str(target_path), *target_args]
    else:
        child_cmd = [str(target_path), *target_args]

    # Initialize store with fail-open safety
    inv_store = store
    if inv_store is None:
        try:
            inv_store = InvocationStore()
        except Exception as err:
            if os.environ.get("SCRIPT_LOGGING_DEBUG") == "1":
                sys.stderr.write(
                    f"[script_logging.launcher] InvocationStore init failed (fail-open): {err}\n"
                )
            inv_store = None

    # Record start (fail-open)
    inv_id: Optional[str] = None
    if inv_store is not None:
        try:
            inv_id = inv_store.start_invocation(
                program_id=program_id,
                invoked_name=command_name,
                argv=tuple(target_args),
                cwd=Path.cwd(),
                origin=origin,
                fail_open=True,
            )
        except Exception as err:
            if os.environ.get("SCRIPT_LOGGING_DEBUG") == "1":
                sys.stderr.write(
                    f"[script_logging.launcher] start_invocation failed (fail-open): {err}\n"
                )
            inv_id = None

    # Execute child process, preserving stdio and handling signals
    status = "exited"
    exit_code = 127
    try:
        proc = subprocess.Popen(child_cmd, stdin=None, stdout=None, stderr=None)
        try:
            proc.wait()
            exit_code = proc.returncode if proc.returncode is not None else 0
        except KeyboardInterrupt:
            status = "interrupted"
            try:
                proc.wait()
                exit_code = proc.returncode if proc.returncode is not None else 130
            except KeyboardInterrupt:
                exit_code = 130
    except OSError as err:
        sys.stderr.write(
            f"[script_logging.launcher] Failed to spawn process '{target_path}': {err}\n"
        )
        status = "launch_failed"
        exit_code = 127
    except Exception as err:
        sys.stderr.write(
            f"[script_logging.launcher] Unexpected error executing target: {err}\n"
        )
        status = "launch_failed"
        exit_code = 1
    finally:
        if inv_store is not None and inv_id is not None:
            try:
                inv_store.finish_invocation(
                    invocation_id=inv_id,
                    exit_code=exit_code,
                    status=status,
                    fail_open=True,
                )
            except Exception as err:
                if os.environ.get("SCRIPT_LOGGING_DEBUG") == "1":
                    sys.stderr.write(
                        f"[script_logging.launcher] finish_invocation failed (fail-open): {err}\n"
                    )

    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for wrapper scripts."""
    if argv is None:
        argv = sys.argv[1:]

    # Separate launcher options from target args using '--' delimiter if present
    if "--" in argv:
        delimiter_idx = argv.index("--")
        launcher_argv = argv[:delimiter_idx]
        target_args = argv[delimiter_idx + 1 :]
    else:
        parser = argparse.ArgumentParser(description="Scripts Toolkit Launcher Engine")
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--command", required=True, type=str)
        parser.add_argument("--wrapper", default=None, type=Path)
        parser.add_argument("--origin", default="launcher", type=str)
        opts, target_args = parser.parse_known_args(argv)
        return launch_target(
            manifest_path=opts.manifest,
            command_name=opts.command,
            args=target_args,
            current_wrapper=opts.wrapper,
            origin=opts.origin,
        )

    parser = argparse.ArgumentParser(description="Scripts Toolkit Launcher Engine")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--command", required=True, type=str)
    parser.add_argument("--wrapper", default=None, type=Path)
    parser.add_argument("--origin", default="launcher", type=str)
    opts = parser.parse_args(launcher_argv)

    return launch_target(
        manifest_path=opts.manifest,
        command_name=opts.command,
        args=target_args,
        current_wrapper=opts.wrapper,
        origin=opts.origin,
    )


if __name__ == "__main__":
    sys.exit(main())
