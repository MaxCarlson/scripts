import json
from pathlib import Path

import tool_install_manager.manager as mgr
from tool_install_manager.tracker import load_db, make_record, upsert_record, write_markdown


def test_parse_winget_table_basic() -> None:
    sample = """
Name                               Id                                  Version          Available        Source
---------------------------------------------------------------------------------------------------------------
ripgrep                            BurntSushi.ripgrep                  13.0.0                          winget
Python                             Python.Python.3.12                  3.12.1           3.12.2           winget
"""
    rows = mgr._parse_winget_table(sample)
    assert len(rows) == 2
    assert rows[0]["Name"] == "ripgrep"
    assert rows[0]["Id"] == "BurntSushi.ripgrep"


def test_path_heuristics_winget_links_windows_like() -> None:
    exe = r"C:\Users\me\AppData\Local\Microsoft\WinGet\Links\rg.exe"
    cands = mgr._path_heuristics(exe)
    assert any(c.manager == "winget" for c in cands)


def test_tracker_writes_db_and_md(tmp_path: Path) -> None:
    root = tmp_path / "root"
    record = make_record(
        command_name="rg",
        package_name="ripgrep",
        manager="winget",
        executable_path=r"C:\fake\rg.exe",
        version="ripgrep 13.0.0",
    )
    upsert_record(record, root_dir=root)

    db = load_db(root_dir=root)
    assert "records" in db
    assert any(r.get("command_name") == "rg" for r in db["records"])

    # Ensure markdown can be generated repeatedly
    write_markdown(db, root_dir=root)
    md_files = list(root.rglob("INSTALLED.md"))
    assert md_files
    md_text = md_files[0].read_text(encoding="utf-8")
    assert "| `rg` |" in md_text


def test_probe_pipx_status_matches(monkeypatch) -> None:
    payload = {
        "venvs": {
            "ruff": {
                "apps": ["ruff"],
            }
        }
    }

    def fake_run_cmd(argv, timeout_s=30.0):
        if argv[:3] == ["pipx", "list", "--json"]:
            return 0, json.dumps(payload), ""
        return 127, "", "missing"

    def fake_which(cmd):
        return "/usr/bin/pipx" if cmd == "pipx" else None

    monkeypatch.setattr(mgr, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(mgr.shutil, "which", fake_which)

    cands = mgr._probe_pipx_status("ruff")
    assert len(cands) == 1
    assert cands[0].manager == "pipx"
    assert cands[0].package_id == "ruff"
    assert "pipx upgrade ruff" in (cands[0].upgrade_hint or "")
