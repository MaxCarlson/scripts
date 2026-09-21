from pathlib import Path

import pytest

from mangadl.models import InputUrl
from mangadl.partial_reconcile import RECONCILE_MARKER, partial_key, reconstruct_archive_keys, resolve_owner_urls, state_url_candidates
from mangadl.state import StateStore


def _state(destination: Path, url: str) -> None:
    store = StateStore(destination / ".mangadl" / "state.sqlite3")
    try:
        run_id = store.create_run({"test": True})
        store.add_jobs(run_id, [InputUrl(url, url, "test", 1)], {url: "gallery-dl"})
    finally:
        store.close()


def test_state_url_recovery_matches_legacy_partial_hash(tmp_path: Path) -> None:
    destination, url = tmp_path / "library", "https://example.test/gallery/one"
    _state(destination, url)
    owner = destination / "_partial" / partial_key(url)
    owner.mkdir(parents=True)
    assert state_url_candidates(destination)[owner.name] == (url,)
    assert resolve_owner_urls(destination, [owner]) == {owner.resolve(): url}


def test_url_override_must_match_selected_partial_hash(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    owner = destination / "_partial" / partial_key("https://example.test/one")
    owner.mkdir(parents=True)
    with pytest.raises(ValueError, match="does not match partial key"):
        resolve_owner_urls(destination, [owner], overrides=[f"{owner.name}=https://example.test/two"])


def test_reconstruct_archive_keys_uses_empty_archive_and_no_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    class Process:
        stdout = iter([f"{RECONCILE_MARKER}one\n", f"{RECONCILE_MARKER}two\n"])
        def wait(self) -> int: return 0
    def fake_popen(command, **_kwargs):
        captured.extend(command)
        return Process()
    monkeypatch.setattr("mangadl.partial_reconcile.subprocess.Popen", fake_popen)
    assert reconstruct_archive_keys("https://example.test/gallery/one", cookies=tmp_path / "cookies.txt") == {"one", "two"}
    assert "--print" in captured and "--download-archive" in captured and "--cookies" in captured


def test_reconstruct_archive_keys_refuses_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class Process:
        stdout = iter(["none\n"])
        def wait(self) -> int: return 0
    monkeypatch.setattr("mangadl.partial_reconcile.subprocess.Popen", lambda *_args, **_kwargs: Process())
    with pytest.raises(RuntimeError, match="reconstructed no archive keys"):
        reconstruct_archive_keys("https://example.test/gallery/one")
