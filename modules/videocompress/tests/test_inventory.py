"""
Tests for SQLite inventory store, incremental caching, and inventory scan.
"""

from __future__ import annotations

import os
from pathlib import Path
import time
import pytest

from videocompress.contracts import VideoAsset, VideoStream
from videocompress.inventory import InventoryReport, InventoryStore, scan_inventory
from videocompress.workspace import resolve_workspace


def test_inventory_store_roundtrip(tmp_path: Path):
    db_path = tmp_path / "inventory.sqlite3"
    store = InventoryStore(db_path)

    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="hevc",
        width=3840,
        height=2160,
        bit_rate_bps=15_000_000,
        bitrate_provenance="ffprobe_stream",
        is_hdr=True,
    )
    asset = VideoAsset(
        source_id="src-001",
        relative_path="4k/movie.mkv",
        file_bytes=10_000_000_000,
        container_format="matroska",
        duration_seconds=7200.0,
        streams=(vstream,),
    )

    store.save_asset(asset, canonical_path="C:/media/4k/movie.mkv", stat_fingerprint="1234:5678")

    cached_entry = store.get_asset("src-001")
    assert cached_entry is not None
    cached_asset, cached_fp = cached_entry
    assert cached_asset.source_id == "src-001"
    assert cached_asset.primary_video_stream.codec_name == "hevc"
    assert cached_asset.primary_video_stream.is_hdr is True
    assert cached_fp == "1234:5678"

    # Verify listing
    all_assets = store.list_assets()
    assert len(all_assets) == 1
    assert all_assets[0].source_id == "src-001"


def test_scan_inventory_incremental_caching(tmp_path: Path):
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "vid1.mp4"
    f1.write_bytes(b"pseudo_video_data_1")

    ws = resolve_workspace(media_dir)

    # Initial scan (depth='files' avoids needing actual ffprobe on pseudo-video)
    report1 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report1.total_sources == 1
    assert report1.cache_hits == 0
    assert report1.cache_misses == 1

    # Second scan with unchanged file should be a cache hit
    report2 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report2.total_sources == 1
    assert report2.cache_hits == 1
    assert report2.cache_misses == 0

    # Modify file mtime/size -> must be a cache miss
    time.sleep(0.01)
    f1.write_bytes(b"pseudo_video_data_1_modified_longer")
    report3 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report3.total_sources == 1
    assert report3.cache_hits == 0
    assert report3.cache_misses == 1


def test_scan_inventory_pruning_deleted_file(tmp_path: Path):
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "vid1.mp4"
    f1.write_bytes(b"vid1")
    f2 = media_dir / "vid2.mkv"
    f2.write_bytes(b"vid2")

    ws = resolve_workspace(media_dir)
    report1 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report1.total_sources == 2

    # Delete vid2
    f2.unlink()
    report2 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report2.total_sources == 1
    assert report2.pruned_sources == 1

    store = InventoryStore(ws.inventory_db)
    assert len(store.list_assets()) == 1


def test_scan_inventory_force_refresh_and_source_id_stability(tmp_path: Path):
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "vid1.mp4"
    f1.write_bytes(b"pseudo_video_data_1")

    ws = resolve_workspace(media_dir)

    # Initial scan
    report1 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report1.total_sources == 1
    assert report1.cache_hits == 0
    assert report1.cache_misses == 1
    sid1 = report1.per_source_records[0]["source_id"]

    # Normal second scan -> cache hit, same source_id
    report2 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report2.cache_hits == 1
    assert report2.per_source_records[0]["source_id"] == sid1

    # Force refresh -> cache miss even with identical fingerprint, but source_id stays stable!
    report3 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files", force_refresh=True)
    assert report3.cache_hits == 0
    assert report3.cache_misses == 1
    assert report3.per_source_records[0]["source_id"] == sid1

    # Modify file mtime/size -> cache miss, but source_id remains stable (derived from path)
    f1.write_bytes(b"pseudo_video_data_1_modified")
    report4 = scan_inventory(media_dir, workspace_root=ws.root, inventory_depth="files")
    assert report4.cache_hits == 0
    assert report4.cache_misses == 1
    assert report4.per_source_records[0]["source_id"] == sid1

