#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for CLI→TUI integrations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path

from knowledge_manager import cli
from knowledge_manager.linkfile import ProjectLink


def test_handle_tui_launches_with_project_option(monkeypatch):
    parser = cli.create_parser()
    args = parser.parse_args(["tui", "-p", "ProjectOne"])
    called = {}

    def fake_launch(project_identifier, base_data_dir, log_file, extra_args=None):
        called["project"] = project_identifier
        called["base_dir"] = base_data_dir
        called["log"] = log_file
        called["extra"] = extra_args
        return 0

    monkeypatch.setattr(cli, "_launch_tui_app", fake_launch)

    args.func(args)

    assert called == {"project": "ProjectOne", "base_dir": None, "log": None, "extra": []}


def test_handle_open_link_passes_link_metadata_to_launcher(monkeypatch):
    project_id = uuid4()
    dummy_link = ProjectLink(
        version=1,
        type="knowledge_manager.project-link",
        project_id=project_id,
        project_name="Demo Project",
        base_data_dir=Path("/tmp/kmdata"),
        created_at=datetime.now(timezone.utc),
    )

    monkeypatch.setattr(cli, "load_link_file", lambda _path: dummy_link)

    called = {}

    def fake_launch(project_identifier, base_data_dir, log_file, extra_args=None):
        called["project"] = project_identifier
        called["base_dir"] = base_data_dir
        called["log"] = log_file
        called["extra"] = extra_args
        return 0

    monkeypatch.setattr(cli, "_launch_tui_app", fake_launch)

    args = SimpleNamespace(open=__file__, log_file=None, data_dir=None)
    cli.handle_open_link(args)

    assert called == {
        "project": str(project_id),
        "base_dir": dummy_link.base_data_dir,
        "log": None,
        "extra": None,
    }
