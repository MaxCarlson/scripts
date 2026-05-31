"""Tests for the scripts_help module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the module is importable from its source directory
_MOD_ROOT = Path(__file__).resolve().parents[2] / "scripts_help"
if str(_MOD_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_MOD_ROOT.parent))

from scripts_help.registry.readme_sync import (  # noqa: E402
    find_readme,
    read_readme_version,
    collect_readme_drift,
)
from scripts_help.registry.versions import is_stale  # noqa: E402
from scripts_help.cli import (  # noqa: E402
    _collect_registered_paths,
    _collect_registered_items,
    _build_update_prompt,
    _build_parser,
    collect_drift,
)
from scripts_help.registry import REGISTRY  # noqa: E402


# ── readme_sync: find_readme ──────────────────────────────────────────────────

def test_find_readme_module_present(tmp_path: Path) -> None:
    item = {"path": "modules/my_tool", "name": "my_tool"}
    readme = tmp_path / "modules" / "my_tool" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("# my_tool\n", encoding="utf-8")
    assert find_readme(item, tmp_path) == readme


def test_find_readme_module_absent(tmp_path: Path) -> None:
    item = {"path": "modules/missing_tool", "name": "missing_tool"}
    (tmp_path / "modules" / "missing_tool").mkdir(parents=True)
    assert find_readme(item, tmp_path) is None


def test_find_readme_pyscript_present(tmp_path: Path) -> None:
    item = {"path": "pyscripts/foo.py", "name": "foo"}
    readme = tmp_path / "pyscripts" / "readme" / "foo.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("# foo\n", encoding="utf-8")
    assert find_readme(item, tmp_path) == readme


def test_find_readme_pyscript_absent(tmp_path: Path) -> None:
    item = {"path": "pyscripts/bar.py", "name": "bar"}
    (tmp_path / "pyscripts" / "readme").mkdir(parents=True)
    assert find_readme(item, tmp_path) is None


def test_find_readme_unknown_path(tmp_path: Path) -> None:
    item = {"path": "other/thing.sh", "name": "thing"}
    assert find_readme(item, tmp_path) is None


# ── readme_sync: read_readme_version ─────────────────────────────────────────

def test_read_readme_version_first_line(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("<!-- version: 1.2.3 -->\n# Title\n", encoding="utf-8")
    assert read_readme_version(readme) == "1.2.3"


def test_read_readme_version_after_title(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n<!-- version: 0.5.0 -->\n\nBody.\n", encoding="utf-8")
    assert read_readme_version(readme) == "0.5.0"


def test_read_readme_version_case_insensitive(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("<!-- VERSION: 2.0.1 -->\n", encoding="utf-8")
    assert read_readme_version(readme) == "2.0.1"


def test_read_readme_version_absent(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# No version here\n\nSome text.\n", encoding="utf-8")
    assert read_readme_version(readme) is None


def test_read_readme_version_beyond_15_lines(tmp_path: Path) -> None:
    lines = ["line\n"] * 16 + ["<!-- version: 9.9.9 -->\n"]
    readme = tmp_path / "README.md"
    readme.write_text("".join(lines), encoding="utf-8")
    assert read_readme_version(readme) is None


def test_read_readme_version_missing_file(tmp_path: Path) -> None:
    assert read_readme_version(tmp_path / "nonexistent.md") is None


# ── readme_sync: collect_readme_drift ────────────────────────────────────────

def _make_registry(item: dict) -> dict:
    return {"Test": {"desc": "test", "items": [item]}}


def _noop_version(_path: str):
    return "1.0.0"


def test_collect_readme_drift_missing(tmp_path: Path) -> None:
    item = {"name": "foo", "path": "pyscripts/foo.py", "version": "1.0.0"}
    (tmp_path / "pyscripts" / "readme").mkdir(parents=True)
    registry = _make_registry(item)

    with patch("scripts_help.registry.readme_sync.find_repo_root", return_value=tmp_path):
        results = collect_readme_drift(registry, _noop_version)

    assert len(results) == 1
    assert results[0]["issue"] == "missing"
    assert results[0]["name"] == "foo"


def test_collect_readme_drift_no_version_tag(tmp_path: Path) -> None:
    item = {"name": "foo", "path": "pyscripts/foo.py", "version": "1.0.0"}
    readme = tmp_path / "pyscripts" / "readme" / "foo.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("# foo\n\nNo version tag here.\n", encoding="utf-8")
    registry = _make_registry(item)

    with patch("scripts_help.registry.readme_sync.find_repo_root", return_value=tmp_path):
        results = collect_readme_drift(registry, _noop_version)

    assert len(results) == 1
    assert results[0]["issue"] == "no_version_tag"


def test_collect_readme_drift_version_mismatch(tmp_path: Path) -> None:
    item = {"name": "foo", "path": "pyscripts/foo.py", "version": "1.0.0"}
    readme = tmp_path / "pyscripts" / "readme" / "foo.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("<!-- version: 0.9.0 -->\n# foo\n", encoding="utf-8")
    registry = _make_registry(item)

    with patch("scripts_help.registry.readme_sync.find_repo_root", return_value=tmp_path):
        results = collect_readme_drift(registry, _noop_version)

    assert len(results) == 1
    assert results[0]["issue"] == "version_mismatch"
    assert results[0]["readme_version"] == "0.9.0"
    assert results[0]["program_version"] == "1.0.0"


def test_collect_readme_drift_ignores_patch_only_mismatch(tmp_path: Path) -> None:
    item = {"name": "foo", "path": "pyscripts/foo.py", "version": "1.0.0"}
    readme = tmp_path / "pyscripts" / "readme" / "foo.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("<!-- version: 3.0.0 -->\n# foo\n", encoding="utf-8")
    registry = _make_registry(item)

    with patch("scripts_help.registry.readme_sync.find_repo_root", return_value=tmp_path):
        results = collect_readme_drift(registry, lambda _path: "3.0.2")

    assert results == []


def test_collect_readme_drift_in_sync(tmp_path: Path) -> None:
    item = {"name": "foo", "path": "pyscripts/foo.py", "version": "1.0.0"}
    readme = tmp_path / "pyscripts" / "readme" / "foo.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("<!-- version: 1.0.0 -->\n# foo\n", encoding="utf-8")
    registry = _make_registry(item)

    with patch("scripts_help.registry.readme_sync.find_repo_root", return_value=tmp_path):
        results = collect_readme_drift(registry, _noop_version)

    assert results == []


def test_collect_readme_drift_subcategory(tmp_path: Path) -> None:
    registry = {
        "Files": {
            "desc": "file tools",
            "subcategories": {
                "Analysis": {
                    "desc": "analysis",
                    "items": [{"name": "foo", "path": "pyscripts/foo.py", "version": "1.0.0"}],
                }
            },
        }
    }
    (tmp_path / "pyscripts" / "readme").mkdir(parents=True)

    with patch("scripts_help.registry.readme_sync.find_repo_root", return_value=tmp_path):
        results = collect_readme_drift(registry, _noop_version)

    assert any(r["name"] == "foo" and r["issue"] == "missing" for r in results)


# ── versions: is_stale ────────────────────────────────────────────────────────

@pytest.mark.parametrize("reg,live,expected", [
    ("1.0.0", "1.0.1", False),   # patch only
    ("1.0.0", "1.1.0", True),    # minor bump
    ("1.0.0", "2.0.0", True),    # major bump
    ("1.2.0", "1.2.5", False),   # patch only
    ("1.2.0", "1.3.0", True),    # minor bump
    ("1.2.3", "1.2.3", False),   # equal
    ("2.0.0", "1.9.9", False),   # live older
])
def test_is_stale(reg: str, live: str, expected: bool) -> None:
    assert is_stale(reg, live) == expected


# ── registry: structure ───────────────────────────────────────────────────────

def test_registry_has_categories() -> None:
    assert len(REGISTRY) > 0


def test_registry_all_items_have_required_keys() -> None:
    required = {"name", "path", "desc", "help_cmd"}
    for cat_name, cat in REGISTRY.items():
        for item in cat.get("items", []):
            missing = required - item.keys()
            assert not missing, f"{cat_name}/{item.get('name')!r} missing keys: {missing}"
        for sub_name, sub in cat.get("subcategories", {}).items():
            for item in sub.get("items", []):
                missing = required - item.keys()
                assert not missing, (
                    f"{cat_name}/{sub_name}/{item.get('name')!r} missing keys: {missing}"
                )


def test_collect_registered_paths_nonempty() -> None:
    paths = _collect_registered_paths()
    assert len(paths) > 0
    assert all(isinstance(p, str) for p in paths)


def test_collect_registered_items_nonempty() -> None:
    items = _collect_registered_items()
    assert len(items) > 0
    assert all("name" in it for it in items)


# ── cli: argparse ─────────────────────────────────────────────────────────────

def test_parser_default_is_browse() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    from scripts_help.cli import cmd_browse
    assert args.func is cmd_browse


def test_parser_browse_subcommand() -> None:
    parser = _build_parser()
    args = parser.parse_args(["browse"])
    from scripts_help.cli import cmd_browse
    assert args.func is cmd_browse


def test_parser_drift_subcommand() -> None:
    parser = _build_parser()
    args = parser.parse_args(["drift"])
    from scripts_help.cli import cmd_drift
    assert args.func is cmd_drift
    assert args.registry_only is False
    assert args.readme_only is False
    assert args.verbose is False
    assert args.quiet is False


def test_parser_drift_flags() -> None:
    parser = _build_parser()
    args = parser.parse_args(["drift", "-g", "-v"])
    assert args.registry_only is True
    assert args.verbose is True


def test_parser_sync_subcommand() -> None:
    parser = _build_parser()
    args = parser.parse_args(["sync"])
    from scripts_help.cli import cmd_sync
    assert args.func is cmd_sync
    assert args.dry_run is False
    assert args.copy is False


def test_parser_sync_dry_run() -> None:
    parser = _build_parser()
    args = parser.parse_args(["sync", "-n"])
    assert args.dry_run is True


def test_parser_sync_copy() -> None:
    parser = _build_parser()
    args = parser.parse_args(["sync", "-C"])
    assert args.copy is True


# ── cli: _build_update_prompt ─────────────────────────────────────────────────

def test_build_update_prompt_new_programs() -> None:
    drift = {"new": ["pyscripts/foo.py"], "stale": [], "deleted": [], "readme": []}
    prompt = _build_update_prompt(drift, registry=True, readme=False)
    assert "pyscripts/foo.py" in prompt
    assert "NEW PROGRAMS" in prompt


def test_build_update_prompt_stale() -> None:
    drift = {
        "new": [],
        "stale": [{"name": "foo", "registry_version": "1.0.0", "live_version": "2.0.0"}],
        "deleted": [],
        "readme": [],
    }
    prompt = _build_update_prompt(drift, registry=True, readme=False)
    assert "STALE" in prompt
    assert "foo" in prompt


def test_build_update_prompt_readme_mismatch() -> None:
    drift = {
        "new": [], "stale": [], "deleted": [],
        "readme": [{
            "name": "bar", "path": "pyscripts/bar.py",
            "readme_path": "pyscripts/readme/bar.md",
            "program_version": "1.2.0", "readme_version": "1.0.0",
            "issue": "version_mismatch",
        }],
    }
    prompt = _build_update_prompt(drift, registry=False, readme=True)
    assert "README VERSION SYNC" in prompt
    assert "bar" in prompt


def test_build_update_prompt_readme_missing() -> None:
    drift = {
        "new": [], "stale": [], "deleted": [],
        "readme": [{
            "name": "baz", "path": "pyscripts/baz.py",
            "readme_path": None,
            "program_version": "1.0.0", "readme_version": None,
            "issue": "missing",
        }],
    }
    prompt = _build_update_prompt(drift, registry=False, readme=True)
    assert "MISSING READMEs" in prompt
    assert "baz" in prompt


def test_build_update_prompt_always_has_validation() -> None:
    drift = {"new": [], "stale": [], "deleted": [], "readme": []}
    prompt = _build_update_prompt(drift)
    assert "VALIDATION" in prompt


# ── integration: collect_drift against real repo ─────────────────────────────

def test_collect_drift_returns_all_keys() -> None:
    drift = collect_drift()
    assert set(drift.keys()) == {"new", "stale", "deleted", "readme"}


def test_collect_drift_readme_items_have_required_keys() -> None:
    drift = collect_drift()
    required = {"name", "path", "readme_path", "program_version", "readme_version", "issue"}
    valid_issues = {"missing", "no_version_tag", "version_mismatch"}
    for r in drift["readme"]:
        missing = required - r.keys()
        assert not missing, f"readme drift item missing keys: {missing}"
        assert r["issue"] in valid_issues, f"unexpected issue: {r['issue']}"
