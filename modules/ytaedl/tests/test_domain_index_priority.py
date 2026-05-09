"""Tests for domain_index pick_url two-tier partial prioritization."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from ytaedl.domain_index import DomainIndex, ScanLogEntry, UrlEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_index(url_entries: list[tuple[str, int, str, int]]) -> DomainIndex:
    """
    Build a DomainIndex from a list of (url, file_id, file_path, line_num) tuples.
    Skips the build() filesystem scan — directly populates internal state.
    """
    idx = DomainIndex()
    for url, fid, fpath, line in url_entries:
        entry = UrlEntry(url=url, file_id=fid, file_path=fpath, line_num=line)
        idx._url_entry_map[url] = entry
        from ytaedl.domain_index import _extract_domain
        domain = _extract_domain(url)
        if domain not in idx._url_queues:
            idx._url_queues[domain] = deque()
        idx._url_queues[domain].append(entry)
        idx._file_map.setdefault(fid, fpath)
        idx._file_url_counts[fid] = idx._file_url_counts.get(fid, 0) + 1
    return idx


URL_A = "https://site-a.com/video/1"
URL_B = "https://site-b.com/video/2"
URL_C = "https://site-a.com/video/3"  # same domain as A


# ---------------------------------------------------------------------------
# Basic pick_url (no partial preference)
# ---------------------------------------------------------------------------

class TestPickUrlBasic:
    def test_returns_none_when_empty(self):
        idx = _build_index([])
        assert idx.pick_url({}, 2, {}) is None

    def test_returns_entry_when_available(self):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        entry = idx.pick_url({}, 2, {1: 0})
        assert entry is not None
        assert entry.url == URL_A

    def test_pops_from_queue(self):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.pick_url({}, 2, {1: 0})
        # Queue should now be empty
        assert idx.pick_url({}, 2, {1: 0}) is None

    def test_marks_in_progress(self):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.pick_url({}, 2, {1: 0})
        assert idx.is_in_progress(URL_A)

    def test_respects_domain_cap(self):
        # site-a.com already at cap=1; should return None
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        from ytaedl.domain_index import _extract_domain
        domain_a = _extract_domain(URL_A)
        active = {domain_a: 1}
        assert idx.pick_url(active, max_per_domain=1, file_priority={1: 0}) is None

    def test_file_priority_selects_lower_rank(self):
        idx = _build_index([
            (URL_A, 1, "file1.txt", 1),  # rank 10
            (URL_B, 2, "file2.txt", 1),  # rank 3 (better)
        ])
        entry = idx.pick_url({}, 2, {1: 10, 2: 3})
        assert entry is not None
        assert entry.url == URL_B


# ---------------------------------------------------------------------------
# Two-tier partial prioritization
# ---------------------------------------------------------------------------

class TestPickUrlPartialPriority:
    def test_partial_url_beats_normal_url(self):
        idx = _build_index([
            (URL_A, 1, "file1.txt", 1),  # rank 0 (best file rank)
            (URL_B, 2, "file2.txt", 1),  # rank 5
        ])
        # Mark URL_B as partial — it should win despite worse file rank
        idx.mark_partial(URL_B)
        entry = idx.pick_url({}, 2, {1: 0, 2: 5}, prefer_partial=True)
        assert entry is not None
        assert entry.url == URL_B

    def test_partial_flag_set_by_mark_partial(self):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.mark_partial(URL_A)
        entry_in_queue = list(idx._url_queues[list(idx._url_queues.keys())[0]])[0]
        assert entry_in_queue.partial is True

    def test_prefer_partial_false_ignores_partial_flag(self):
        idx = _build_index([
            (URL_A, 1, "file1.txt", 1),  # rank 0
            (URL_B, 2, "file2.txt", 1),  # rank 5, partial
        ])
        idx.mark_partial(URL_B)
        # With prefer_partial=False, file priority wins → URL_A (rank 0)
        entry = idx.pick_url({}, 2, {1: 0, 2: 5}, prefer_partial=False)
        assert entry is not None
        assert entry.url == URL_A

    def test_partial_among_partials_uses_file_rank(self):
        URL_D = "https://site-d.com/video/4"
        idx = _build_index([
            (URL_B, 2, "file2.txt", 1),  # rank 5, partial
            (URL_D, 3, "file3.txt", 1),  # rank 1, partial (better file rank)
        ])
        idx.mark_partial(URL_B)
        idx.mark_partial(URL_D)
        entry = idx.pick_url({}, 2, {2: 5, 3: 1}, prefer_partial=True)
        assert entry is not None
        assert entry.url == URL_D  # rank 1 beats rank 5

    def test_domain_cap_still_blocks_partial(self):
        # partial URL's domain is at cap — must not be selected
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.mark_partial(URL_A)
        from ytaedl.domain_index import _extract_domain
        domain_a = _extract_domain(URL_A)
        active = {domain_a: 1}
        # Domain at cap — even partial URL blocked
        entry = idx.pick_url(active, max_per_domain=1, file_priority={1: 0}, prefer_partial=True)
        assert entry is None

    def test_partial_in_capped_domain_falls_back_to_normal(self):
        # Domain A is at cap but has a partial; domain B has space and normal URL
        idx = _build_index([
            (URL_A, 1, "file1.txt", 1),  # domain A, partial
            (URL_B, 2, "file2.txt", 1),  # domain B, normal
        ])
        idx.mark_partial(URL_A)
        from ytaedl.domain_index import _extract_domain
        domain_a = _extract_domain(URL_A)
        active = {domain_a: 1}  # domain A at cap
        entry = idx.pick_url(active, max_per_domain=1, file_priority={1: 0, 2: 99}, prefer_partial=True)
        assert entry is not None
        assert entry.url == URL_B  # only domain B available

    def test_mark_partial_moves_to_front_of_queue(self):
        idx = _build_index([
            (URL_A, 1, "file1.txt", 1),
            (URL_C, 1, "file1.txt", 2),  # same domain, queued after A
        ])
        idx.mark_partial(URL_C)
        from ytaedl.domain_index import _extract_domain
        domain_a = _extract_domain(URL_A)
        # URL_C should now be at front of queue
        front = list(idx._url_queues[domain_a])[0]
        assert front.url == URL_C

    def test_scan_log_records_partial_event(self):
        idx = _build_index([
            (URL_A, 1, "file1.txt", 1),
            (URL_B, 2, "file2.txt", 1),
        ])
        idx.mark_partial(URL_B)
        scan_log: list[ScanLogEntry] = []
        idx.pick_url({}, 2, {1: 0, 2: 5}, scan_log=scan_log, prefer_partial=True)
        kinds = [e.kind for e in scan_log]
        assert "PARTIAL" in kinds

    def test_found_log_annotates_partial(self):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.mark_partial(URL_A)
        scan_log: list[ScanLogEntry] = []
        idx.pick_url({}, 2, {1: 0}, scan_log=scan_log, prefer_partial=True)
        found_entries = [e for e in scan_log if e.kind == "FOUND"]
        assert found_entries
        assert "[PARTIAL]" in found_entries[0].message


# ---------------------------------------------------------------------------
# mark_partial on finished / in_progress URLs
# ---------------------------------------------------------------------------

class TestMarkPartial:
    def test_no_effect_on_finished_url(self):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.mark_finished(URL_A, "downloaded")
        # Should not raise; entry.partial state doesn't matter
        idx.mark_partial(URL_A)

    def test_no_effect_on_in_progress_url(self):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.pick_url({}, 2, {1: 0})  # pops and marks in_progress
        # Should silently do nothing
        idx.mark_partial(URL_A)

    def test_no_effect_on_unknown_url(self):
        idx = _build_index([])
        idx.mark_partial("https://unknown.com/v")  # no exception


# ---------------------------------------------------------------------------
# Serialization of partial field (version 1.3)
# ---------------------------------------------------------------------------

class TestSerializationPartial:
    def test_version_is_1_3(self):
        assert DomainIndex.VERSION == "1.3"

    def test_partial_serialized_in_queue(self, tmp_path):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.mark_partial(URL_A)
        save_path = tmp_path / "index.json"
        idx.save(save_path)
        import json
        data = json.loads(save_path.read_text())
        from ytaedl.domain_index import _extract_domain
        domain = _extract_domain(URL_A)
        queue_entries = data["queues"].get(domain, [])
        assert any(e.get("partial") is True for e in queue_entries)

    def test_partial_not_serialized_when_false(self, tmp_path):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        save_path = tmp_path / "index.json"
        idx.save(save_path)
        import json
        data = json.loads(save_path.read_text())
        from ytaedl.domain_index import _extract_domain
        domain = _extract_domain(URL_A)
        queue_entries = data["queues"].get(domain, [])
        # partial key should be absent (not stored as False)
        assert all("partial" not in e for e in queue_entries)

    def test_partial_survives_save_load_roundtrip(self, tmp_path):
        idx = _build_index([(URL_A, 1, "file1.txt", 1)])
        idx.mark_partial(URL_A)
        save_path = tmp_path / "index.json"
        idx.save(save_path)
        loaded = DomainIndex.load(save_path)
        entry = loaded._url_entry_map.get(URL_A)
        assert entry is not None
        assert entry.partial is True

    def test_old_index_without_partial_loads_cleanly(self, tmp_path):
        """Loading a v1.2 index (no partial field) must not raise."""
        import json
        from ytaedl.domain_index import _extract_domain
        domain = _extract_domain(URL_A)
        data = {
            "version": "1.2",
            "built_at": 0.0,
            "files": [{"id": 1, "path": "file1.txt", "url_count": 1}],
            "domains": [{"id": 0, "name": domain}],
            "queues": {domain: [{"url": URL_A, "file_id": 1, "line": 1}]},
            "in_progress": [],
            "finished": {},
        }
        save_path = tmp_path / "old_index.json"
        save_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = DomainIndex.load(save_path)
        entry = loaded._url_entry_map.get(URL_A)
        assert entry is not None
        assert entry.partial is False  # defaults to False when absent
