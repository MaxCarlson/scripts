#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from procparsers.utils import sanitize_line

def test_sanitize_line_strips_ansi_and_newlines():
    s = "Hello \x1b[31mWorld\x1b[0m\r\n"
    out = sanitize_line(s)
    assert out == "Hello World"

def test_sanitize_line_none_safe():
    assert sanitize_line(None) == ""
