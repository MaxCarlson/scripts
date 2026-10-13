from __future__ import annotations

from mangadl import partial_reconcile


def test_reconstruct_archive_page_keys_uses_print_only_page_mapping(monkeypatch) -> None:
    class Process:
        stdout = [
            f"{partial_reconcile.REPAIR_MARKER}nhentai 123_1\t1\n",
            f"{partial_reconcile.REPAIR_MARKER}nhentai 123_2\t2\n",
        ]

        def wait(self):
            return 0

    captured = {}

    def popen(command, **_kwargs):
        captured["command"] = command
        return Process()

    monkeypatch.setattr(partial_reconcile.subprocess, "Popen", popen)
    monkeypatch.setattr(partial_reconcile, "ProfileStore", lambda _path: type("Store", (), {"load": lambda self, _url: None})())

    result = partial_reconcile.reconstruct_archive_page_keys("https://nhentai.net/g/123/")

    assert result == {1: "nhentai 123_1", 2: "nhentai 123_2"}
    command = captured["command"]
    assert "--print" in command
    assert "--Print" not in command
