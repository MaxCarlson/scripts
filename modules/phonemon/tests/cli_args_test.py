#!/usr/bin/env python3
from phonemon.cli import build_parser


def test_arg_parser_defaults():
    p = build_parser()
    ns = p.parse_args([])
    assert ns.refresh == 0.5
    assert ns.top == 5
    assert ns.mode == "overview"


def test_arg_parser_values():
    p = build_parser()
    ns = p.parse_args(["-r", "0.2", "-t", "12", "-m", "cpu"])
    assert ns.refresh == 0.2
    assert ns.top == 12
    assert ns.mode == "cpu"
