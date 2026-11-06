from __future__ import annotations

from pathlib import Path

from ytaedl.runtime_submissions import (
    Submission,
    SubmissionDialog,
    SubmissionQueue,
    allocate_initial_submissions,
)


def test_accepts_urls_and_paths_with_spaces_and_preserves_fragments(tmp_path: Path) -> None:
    source = tmp_path / "URL list with spaces.txt"
    source.write_text("https://inside.example/one#scene-1171754\n", encoding="utf-8")
    queue = SubmissionQueue(tmp_path / "pending.json", tmp_path / "manual")

    accepted = queue.submit(f"https://one.example/a?q=x#scene-1171754\n{source}")

    assert [item.kind for item in accepted] == ["url", "file"]
    assert Path(accepted[0].value).read_text(encoding="utf-8") == "https://one.example/a?q=x#scene-1171754\n"
    assert Path(accepted[1].value) == source.resolve()
    assert queue.pending_count == 2


def test_rejects_missing_paths_and_malformed_lines_without_accepting_partial_batch(tmp_path: Path) -> None:
    queue = SubmissionQueue(tmp_path / "pending.json", tmp_path / "manual")

    try:
        queue.submit("https://valid.example/a\nmissing file.txt")
    except ValueError as exc:
        assert "existing path" in str(exc)
    else:
        raise AssertionError("missing paths must be rejected")

    assert queue.pending_count == 0

    try:
        queue.submit("https://\nhttps://valid.example/a")
    except ValueError as exc:
        assert "Malformed HTTP(S) URL" in str(exc)
    else:
        raise AssertionError("malformed URL must be rejected")

    assert queue.pending_count == 0


def test_persists_pending_manual_urls_and_deduplicates_after_restart(tmp_path: Path) -> None:
    state = tmp_path / "pending.json"
    queue = SubmissionQueue(state, tmp_path / "manual")
    queue.submit("https://example.com/a#scene-1171754\nhttps://example.com/a#scene-1171754")

    restored = SubmissionQueue(state, tmp_path / "manual")

    assert restored.pending_count == 1
    item = restored.claim()
    assert item is not None
    assert Path(item.value).read_text(encoding="utf-8") == "https://example.com/a#scene-1171754\n"


def test_claimed_work_is_restored_after_restart_and_idle_claims_next_item(tmp_path: Path) -> None:
    state = tmp_path / "pending.json"
    queue = SubmissionQueue(state, tmp_path / "manual")
    queue.submit("https://example.com/a\nhttps://example.com/b")
    active = queue.claim()
    assert active is not None

    restarted = SubmissionQueue(state, tmp_path / "manual")

    assert restarted.pending_count == 2
    assert restarted.in_progress_count == 0
    retried = restarted.claim()
    assert retried is not None and retried.submission_id == active.submission_id
    restarted.complete(retried)
    assert restarted.claim() is not None


def test_queue_records_file_identity_and_removes_only_after_completion(tmp_path: Path) -> None:
    source = tmp_path / "original.txt"
    source.write_text("https://example.com/a\n", encoding="utf-8")
    queue = SubmissionQueue(tmp_path / "pending.json", tmp_path / "manual")
    queue.submit(str(source))

    item = queue.claim()
    assert item is not None and item.value == str(source.resolve())
    queue.complete(item)

    assert queue.pending_count == 0
    assert SubmissionQueue(queue.state_path, queue.manual_dir).pending_count == 0


def test_dialog_accepts_multiline_paste_then_queue_choice() -> None:
    dialog = SubmissionDialog()
    for key in "https://one.example/a":
        dialog.feed(key)
    dialog.feed("\r")
    for key in "https://two.example/b#scene-1171754":
        dialog.feed(key)

    assert dialog.feed("\x13") is None
    assert dialog.stage == "input"
    assert dialog.feed("\t") == "input"
    assert dialog.stage == "schedule"
    assert dialog.feed("1") == "queue"
    assert dialog.completed
    assert dialog.buffer.splitlines() == [
        "https://one.example/a",
        "https://two.example/b#scene-1171754",
    ]
    assert dialog.display_lines()[0] == "SCHEDULE SUBMISSIONS"


def test_dialog_shows_tab_to_continue_without_control_s():
    dialog = SubmissionDialog()

    assert "Tab to continue" in dialog.display_lines()[-1]
    assert "Ctrl+S" not in dialog.display_lines()[-1]


def test_dialog_requests_worker_count_after_stage_two() -> None:
    dialog = SubmissionDialog(stage="workers")
    for key in "3":
        dialog.feed(key)

    assert dialog.feed("\r") == "workers"
    assert dialog.requested_workers == 3


def test_dialog_rejects_invalid_worker_count_and_can_cancel() -> None:
    dialog = SubmissionDialog(stage="workers")
    assert dialog.feed("\r") is None
    assert "positive" in dialog.error
    assert dialog.feed("\x1b") == "cancel"


def test_worker_allocation_caps_initial_items_and_preserves_queue_overflow() -> None:
    items = [Submission(str(i), "url", f"url-{i}") for i in range(8)]

    initial, overflow = allocate_initial_submissions(items, requested_workers=3, available_slots=3)

    assert [item.submission_id for item in initial] == ["0", "1", "2"]
    assert [item.submission_id for item in overflow] == ["3", "4", "5", "6", "7"]


def test_worker_allocation_obeys_configured_slot_limit() -> None:
    items = [Submission(str(i), "url", f"url-{i}") for i in range(4)]

    initial, overflow = allocate_initial_submissions(items, requested_workers=3, available_slots=1)

    assert len(initial) == 1
    assert len(overflow) == 3
