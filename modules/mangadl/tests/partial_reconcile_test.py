from pathlib import Path

import pytest

from mangadl.models import InputUrl
from mangadl.partial_reconcile import (
    RECONCILE_MARKER,
    partial_key,
    reconstruct_archive_keys,
    resolve_owner_urls,
    state_url_candidates,
)
from mangadl.state import StateStore


def _state_with_url(destination: Path, url: str) -> Path:
    path = destination / ".mangadl" / "state.sqlite3"
    store = StateStore(path)
    try:
        run_id = store.create_run({"test": True})
        item = InputUrl(url, url, "test", 1)
        store.add_jobs(run_id, [item], {url: "gallery-dl"})
    finally:
        store.close()
    return path


def test_state_url_recovery_matches_legacy_partial_hash(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    url = "https://example.test/gallery/one"
    _state_with_url(destination, url)
    owner = destination / "_partial" / partial_key(url)
    owner.mkdir(parents=True)

    candidates = state_url_candidates(destination)
    resolved = resolve_owner_urls(destination, [owner])

    assert candidates[owner.name] == (url,)
    assert resolved == {owner.resolve(): url}


def test_url_override_must_match_selected_partial_hash(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    destination.mkdir()
    owner = destination / "_partial" / partial_key("https://example.test/one")
    owner.mkdir(parents=True)

    with pytest.raises(ValueError, match="does not match partial key"):
        resolve_owner_urls(
            destination,
            [owner],
            overrides=[f"{owner.name}=https://example.test/two"],
        )


def test_reconstruct_archive_keys_uses_empty_archive_and_no_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    class Process:
        stdout = iter(
            [
                f"{RECONCILE_MARKER}site-key-one\n",
                "diagnostic\n",
                f"{RECONCILE_MARKER}site-key-two\n",
            ]
        )

        def wait(self) -> int:
            return 0

    def fake_popen(command, **_kwargs):
        captured.extend(command)
        return Process()

    monkeypatch.setattr("mangadl.partial_reconcile.subprocess.Popen", fake_popen)

    keys = reconstruct_archive_keys(
        "https://example.test/gallery/one",
        cookies=tmp_path / "cookies.txt",
    )

    assert keys == {"site-key-one", "site-key-two"}
    assert "--print" in captured
    assert "--download-archive" in captured
    assert "--cookies" in captured
    assert "--no-input" in captured
    assert "--simulate" not in captured


def test_reconstruct_archive_keys_refuses_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class Process:
        stdout = iter(["no matching items\n"])

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(
        "mangadl.partial_reconcile.subprocess.Popen", lambda *_args, **_kwargs: Process()
    )

    with pytest.raises(RuntimeError, match="reconstructed no archive keys"):
        reconstruct_archive_keys("https://example.test/gallery/one")
