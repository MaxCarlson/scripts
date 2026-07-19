from pathlib import Path

import pytest

from mangadl.naming import TITLE_LIMIT, gallery_directory_name
from mangadl.repair import GalleryMetadata, apply_repair, plan_loose_images


def _resolver(page_count: int = 3):
    def resolve(gallery_id: str) -> GalleryMetadata:
        return GalleryMetadata(gallery_id, "Exact Manga Title", page_count, f"nhentai-{gallery_id} - Exact Manga Title")

    return resolve


def test_repair_creates_exact_normal_folder_moves_and_verifies(tmp_path: Path) -> None:
    for page in range(1, 4):
        (tmp_path / f"nhentai_649832_{page:03d}.webp").write_bytes(bytes([page]))
    plan = plan_loose_images(tmp_path, _resolver())
    expected_folder = tmp_path / "nhentai-649832 - Exact Manga Title"
    assert plan.valid
    assert {move.destination for move in plan.moves} == {
        expected_folder / "001.webp",
        expected_folder / "002.webp",
        expected_folder / "003.webp",
    }
    assert apply_repair(plan) == 3
    assert sorted(path.name for path in expected_folder.iterdir()) == ["001.webp", "002.webp", "003.webp"]
    assert not list(tmp_path.glob("nhentai_649832_*.webp"))


def test_repair_combines_existing_exact_folder_with_loose_pages(tmp_path: Path) -> None:
    folder = tmp_path / "nhentai-649832 - Exact Manga Title"
    folder.mkdir()
    (folder / "001.webp").write_bytes(b"1")
    (tmp_path / "nhentai_649832_002.webp").write_bytes(b"2")
    (tmp_path / "nhentai_649832_003.webp").write_bytes(b"3")
    plan = plan_loose_images(tmp_path, _resolver())
    assert plan.valid and plan.galleries[0].present_after_repair == 3
    apply_repair(plan)
    assert sorted(path.name for path in folder.iterdir()) == ["001.webp", "002.webp", "003.webp"]


def test_repair_refuses_incomplete_gallery_without_moving(tmp_path: Path) -> None:
    loose = tmp_path / "nhentai_649832_001.webp"
    loose.write_bytes(b"1")
    plan = plan_loose_images(tmp_path, _resolver(page_count=3))
    assert not plan.valid and plan.galleries[0].missing_pages == (2, 3)
    with pytest.raises(ValueError, match="incomplete"):
        apply_repair(plan)
    assert loose.exists()


def test_shared_folder_name_sanitizes_and_limits_title() -> None:
    metadata = {"category": "nhentai", "gallery_id": "12", "title": "bad | title " + "x" * 300}
    result = gallery_directory_name(metadata, lambda value: value.replace("|", "_"))
    assert result.startswith("nhentai-12 - bad _ title ")
    assert len(result) <= len("nhentai-12 - ") + TITLE_LIMIT


def test_repair_emits_metadata_move_and_verification_progress(tmp_path: Path) -> None:
    for page in range(1, 4):
        (tmp_path / f"nhentai_7_{page:03d}.webp").write_bytes(bytes([page]))

    events: list[dict[str, object]] = []
    plan = plan_loose_images(tmp_path, _resolver(), progress=events.append)

    assert [event["phase"] for event in events] == ["metadata", "metadata", "metadata", "planned"]
    assert events[-1]["file_total"] == 3
    assert events[-1]["gallery_total"] == 1

    apply_repair(plan, progress=events.append)

    assert any(event["phase"] == "moving" and event["move_done"] == 3 for event in events)
    assert any(event["phase"] == "verifying" for event in events)
    assert events[-1]["phase"] == "complete"
