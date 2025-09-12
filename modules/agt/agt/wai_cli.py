#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shim for backward-compatibility with earlier messages.
Delegates to agt.cli:main().
"""
from agt.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
