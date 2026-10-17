"""Metadata guidance is reproducible coverage, never an outcome precision claim."""

from dataclasses import replace
import json
import sqlite3

import pytest

from compresser.distribution import SamplingProfile
from compresser.models import ImageMetadata
from compresser.sampling import gallery_sample


def population(root):
    root.mkdir(exist_ok=True)
    return [
        ImageMetadata(root / group / f"{i}.jpg", "JPEG", 40, 40, size)
        for group, sizes in (("flat", [100] * 10), ("varied", [1, 199] * 5))
        for i, size in enumerate(sizes)
    ]


def test_descriptive_profile_revision_has_no_sampling_advice_and_is_order_invariant(tmp_path):
    images = population(tmp_path / "library")
    profile = SamplingProfile.from_images(images, tmp_path / "library", policy="test")
    reverse = SamplingProfile.from_images(
        list(reversed(images)), tmp_path / "library", policy="test"
    )
    assert profile.identity == reverse.identity
    rows = profile.data["galleries"]
    assert profile.data["profile_revision"] == 2
    assert "starter_samples" not in profile.data
    assert all("proxy_weight" not in row for row in rows.values())
    assert "precision" not in profile.data["limitations"].lower()


def test_profile_sampling_exact_monotone_uniform_gallery_prefixes(tmp_path):
    root = tmp_path / "library"
    images = population(root)
    profile = SamplingProfile.from_images(images, root)
    previous = set()
    for budget in range(2, 21):
        sample = gallery_sample(
            images, root, sample_size=budget, profile=profile, seed=7
        )
        chosen = {image.path for image in sample.images}
        assert previous <= chosen
        assert len(chosen) == budget
        assert min(sample.quotas.values()) >= 1
        assert sample.summary()["allocation_method"] == "balanced"
        previous = chosen
    with pytest.raises(ValueError, match="positive integer"):
        gallery_sample(images, root, sample_size="auto", profile=profile)
    assert len(gallery_sample(images, root).images) == 20
    sub = gallery_sample(images, root, sample_size=1, profile=profile)
    assert len(sub.images) == 1
    with pytest.raises(ValueError):
        gallery_sample(images, root, sample_size=0, profile=profile)


def test_stale_or_absent_profile_never_silently_falls_back(tmp_path):
    root = tmp_path / "library"
    images = population(root)
    with pytest.raises(ValueError, match="positive integer"):
        gallery_sample(images, root, sample_size="auto")
    profile = SamplingProfile.from_images(images, root)
    changed = [replace(images[0], size_bytes=500), *images[1:]]
    with pytest.raises(ValueError, match="refresh"):
        gallery_sample(changed, root, sample_size=2, profile=profile)


def test_cli_publishes_profile_with_selection_and_reuses_for_auto(tmp_path, capsys):
    from PIL import Image
    from cli_test_support import main

    root = tmp_path / "library"
    root.mkdir()
    for n in range(5):
        Image.new("RGB", (40, 40)).save(root / f"{n}.png")
    database = tmp_path / "state" / ".compresser" / "library" / "inventory.sqlite3"
    args = ["-i", str(root), "-I", str(tmp_path / "state"), "-J"]
    assert main(["inventory", *args]) == 0
    inventory = json.loads(capsys.readouterr().out)
    assert inventory["sampling_profile"]["profile_revision"] == 2
    assert "starter_samples" not in inventory["sampling_profile"]
    with sqlite3.connect(database) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM inventory_sampling_profiles").fetchone()[0]
            == 1
        )
    assert main(["analyze", *args, "-U", "snapshot", "-s", "2", "-f", "png", "-e", "0"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_images"] == 2
    assert report["sampling"]["allocation_method"] == "balanced"


def test_failed_profile_publication_preserves_selection_and_profile(
    tmp_path, monkeypatch
):
    from PIL import Image
    from compresser.inventory import InventoryStore
    from compresser.scanner import scan_directory
    from compresser.snapshots import SelectionSnapshot

    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    _, images = scan_directory(root, inventory=store)
    snapshot = SelectionSnapshot(store, root, owner="test")
    snapshot.publish(images)
    with sqlite3.connect(store.path) as db:
        before = (
            db.execute("SELECT report FROM inventory_selections").fetchall(),
            db.execute("SELECT report FROM inventory_sampling_profiles").fetchall(),
        )
    original = SamplingProfile.save

    def interrupted(self, db):
        original(self, db)
        raise OSError("simulated publication failure")

    monkeypatch.setattr(SamplingProfile, "save", interrupted)
    with pytest.raises(OSError):
        snapshot.publish(images)
    with sqlite3.connect(store.path) as db:
        assert (
            db.execute("SELECT report FROM inventory_selections").fetchall(),
            db.execute("SELECT report FROM inventory_sampling_profiles").fetchall(),
        ) == before


def test_equal_metadata_does_not_certify_outcomes_and_estimates_remain_weighted(
    tmp_path,
):
    from compresser.models import ImageResult

    root = tmp_path / "library"
    images = population(root)
    profile = SamplingProfile.from_images(images, root)
    savings = {
        image.path: image.size_bytes // 2 if i % 2 else 0
        for i, image in enumerate(images)
    }
    estimates = []
    for seed in range(100):
        sample = gallery_sample(images, root, sample_size=8, seed=seed, profile=profile)
        results = [
            ImageResult(
                image.path,
                image.path,
                image.size_bytes,
                image.size_bytes - savings[image.path],
                image.format,
                image.format,
            )
            for image in sample.images
        ]
        estimates.append(sample.estimate(results)["projected_total_saved_bytes"])
    assert abs(sum(estimates) / len(estimates) - sum(savings.values())) < 0.1 * sum(
        savings.values()
    )
    assert profile.identity == SamplingProfile.from_images(images, root).identity
    assert "does not predict compression outcomes" in profile.data["limitations"]


def test_file_profile_never_supplies_verified_format_or_dimension_claims(
    tmp_path, capsys
):
    from cli_test_support import main

    root = tmp_path / "library"
    root.mkdir()
    (root / "01.jpg").write_bytes(b"not an image")
    assert main(["-i", str(root), "-l", "-D", "files", "-J"]) == 0
    report = json.loads(capsys.readouterr().out)
    profile = report["sampling_profile"]
    assert profile["depth"] == "files"
    assert profile["galleries"][root.name]["formats"] is None
    assert profile["galleries"][root.name]["tall_webp_images"] is None
