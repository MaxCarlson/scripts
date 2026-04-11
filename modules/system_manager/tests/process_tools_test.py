import psutil

from system_manager.command_registry import search_commands
from system_manager.process_tools import ProcessQuery, find_processes


class FakeProcess:
    def __init__(self, info):
        self.info = info

    def as_dict(self, attrs):
        return {key: self.info.get(key) for key in attrs}


def test_find_processes_matches_command_line(monkeypatch):
    fake = FakeProcess(
        {
            "pid": 34944,
            "ppid": 76028,
            "name": "node.exe",
            "exe": r"C:\Program Files\nodejs\node.exe",
            "cmdline": ["node.exe", "gemini", "--acp"],
            "username": "me",
            "status": "running",
            "create_time": 1,
            "cwd": r"C:\Users\mcarls",
        }
    )

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [fake])

    results = find_processes(ProcessQuery(query="gemini", cmdline=True))

    assert len(results) == 1
    assert results[0]["pid"] == 34944
    assert "gemini" in results[0]["cmdline"]


def test_find_processes_filters_path(monkeypatch):
    fake = FakeProcess(
        {
            "pid": 77828,
            "ppid": 34944,
            "name": "node.exe",
            "exe": r"C:\Program Files\nodejs\node.exe",
            "cmdline": ["node.exe"],
            "username": "me",
            "status": "running",
            "create_time": 1,
            "cwd": r"C:\Program Files\nodejs",
        }
    )

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [fake])

    results = find_processes(ProcessQuery(path="nodejs"))

    assert len(results) == 1
    assert results[0]["pid"] == 77828


def test_search_commands_finds_pause_description():
    results = search_commands("pause")

    assert any(item["command"] == "sm proc pause" for item in results)
