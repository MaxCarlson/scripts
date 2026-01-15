import json
from cross_platform.install_ownership import _parse_winget_table, _probe_pipx


def test_parse_winget_table_basic() -> None:
    sample = """
Name                               Id                                  Version          Available        Source
---------------------------------------------------------------------------------------------------------------
ripgrep                            BurntSushi.ripgrep                  13.0.0                          winget
Python                             Python.Python.3.12                  3.12.1           3.12.2           winget
"""
    rows = _parse_winget_table(sample)
    assert len(rows) == 2
    assert rows[0]["Name"] == "ripgrep"
    assert rows[0]["Id"] == "BurntSushi.ripgrep"
    assert rows[1]["Id"].startswith("Python.Python.")


def test_probe_pipx_matches_app(monkeypatch) -> None:
    # Fake `pipx list --json` output with an app mapping.
    payload = {
        "venvs": {
            "ruff": {
                "metadata": {},
                "apps": ["ruff"],
            },
            "black": {
                "metadata": {},
                "apps": ["black"],
            },
        }
    }

    def fake_run_cmd(argv, timeout_s=20.0):
        if argv[:3] == ["pipx", "list", "--json"]:
            return 0, json.dumps(payload), ""
        return 127, "", "missing"

    def fake_which(cmd):
        return "/usr/bin/pipx" if cmd == "pipx" else None

    import cross_platform.install_ownership as mod

    monkeypatch.setattr(mod, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(mod.shutil, "which", fake_which)

    matches = _probe_pipx("ruff")
    assert len(matches) == 1
    assert matches[0].manager == "pipx"
    assert matches[0].package_id == "ruff"
    assert "pipx upgrade ruff" in (matches[0].upgrade_hint or "")
