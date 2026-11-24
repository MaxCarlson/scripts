"""Scripts-owned manifest adapter around the shared launcher engine."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from script_logging.launcher import main as shared_launcher_main

try:
    from scripts_setup.launcher_generator import generate_manifest
except ImportError:
    setup_dir = Path(__file__).resolve().parent
    if str(setup_dir) not in sys.path:
        sys.path.insert(0, str(setup_dir))
    from launcher_generator import generate_manifest


def _launcher_options(argv: Sequence[str]) -> tuple[Path, str]:
    launcher_args = list(argv)
    if "--" in launcher_args:
        launcher_args = launcher_args[: launcher_args.index("--")]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--command", required=True)
    options, _unknown = parser.parse_known_args(launcher_args)
    return options.manifest, options.command


def _manifest_has_command(path: Path, command: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return command in data.get("commands", {})


def main(argv: Sequence[str] | None = None) -> int:
    """Refresh scripts-owned manifest data when needed, then delegate execution."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        manifest_path, command = _launcher_options(arguments)
    except SystemExit as exc:
        return int(exc.code or 0)

    if not _manifest_has_command(manifest_path, command):
        try:
            generate_manifest(manifest_path.resolve().parent, manifest_path)
        except Exception:
            # Match the shared engine's fail-open refresh behavior; its own
            # diagnostics report a missing or invalid command target.
            pass
    return shared_launcher_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
