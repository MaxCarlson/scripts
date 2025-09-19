#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Orchestrator CLI shim for ytaedl.

This wrapper delegates to the original implementation next to the package folder
(`modules/ytaedl/dlmanager.py`) when running in editable/dev mode. When building
distributions later, we can migrate the full source under `ytaedl/`.
"""

from __future__ import annotations

import sys
from importlib.machinery import SourceFileLoader as _Loader  # type: ignore
import importlib.util as _iu
from pathlib import Path as _P

import argparse


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytaedl-orchestrate",
        description="Run multiple downloader workers across URL files with live progress.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Minimal argument to keep `--help` useful if impl missing
    p.add_argument("--workers", "-t", type=int, default=2, help="Concurrency (number of workers).")
    return p


def main() -> int:
    _impl_path = _P(__file__).resolve().parents[1] / "dlmanager.py"
    if _impl_path.exists():
        spec = _iu.spec_from_loader("ytaedl_impl_dlmanager", _Loader("ytaedl_impl_dlmanager", str(_impl_path)))
        if spec and spec.loader:
            mod = _iu.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            return int(mod.main())
    # Fallback help when impl isn’t present (e.g., in a pure wheel before migration)
    parser = make_parser()
    parser.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)

