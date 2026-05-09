"""
domain_index — URL-to-domain index for ytaedl's domain-lock (-D) feature.

Provides a persistent, priority-aware map of every URL across all URL files,
keyed by base domain, so the manager can dispatch individual URLs to workers
rather than entire files.

Lifecycle
---------
1. ``DomainIndex.build(url_files)`` — blocking scan at startup; builds queues.
2. ``DomainIndex.load(path)`` — restore a previously saved index from JSON.
3. ``index.pick_url(...)`` — called by _assign() to select the next URL.
4. ``index.mark_finished/failed/partial(url)`` — update state as workers report.
5. ``index.save(path)`` / ``index.save_debounced(path)`` — persist to disk.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Domain extraction (mirrors manager.py _top_domain)


def _extract_domain(url: str) -> str:
    """Return the normalised base domain for *url*, or '-' if unparseable.

    Strips common vanity prefixes so that mobile/desktop/www variants all map
    to the same domain key:
        www.example.com  → example.com
        m.example.com    → example.com   (mobile prefix)
        www.m.example.com → example.com
    """
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        if not host:
            return "-"
        # Strip port
        if ":" in host:
            host = host.rsplit(":", 1)[0]
        # Strip vanity prefixes (order matters: strip www. first, then m.)
        for prefix in ("www.", "m."):
            if host.startswith(prefix):
                host = host[len(prefix):]
        return host or "-"
    except Exception:
        return "-"


def _read_url_lines(path: Path) -> List[Tuple[int, str]]:
    """Return (1-indexed line_num, url) pairs for all valid URL lines in *path*."""
    entries: List[Tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return entries
    for line_num, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("http://", "https://")):
            entries.append((line_num, stripped))
    return entries


# ---------------------------------------------------------------------------
# Data structures


@dataclass
class UrlEntry:
    """Metadata about a single URL in the index."""

    url: str
    file_id: int    # which file this URL belongs to
    file_path: str  # str(Path) of the original URL file
    line_num: int   # 1-indexed line in that file
    partial: bool = False  # True when a _partial/<hash>/ dir exists for this URL


@dataclass
class UrlStatus:
    """Terminal state for a URL that no longer needs to be downloaded."""

    url: str
    file_id: int
    file_path: str
    line_num: int
    status: str     # "downloaded" | "preexisting" | "failed"
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScanLogEntry:
    """One entry produced during pick_url() for writing to the worker prog log."""

    kind: str    # "SEARCH" | "SCAN" | "CHECK" | "FOUND" | "WAIT" | "PARTIAL"
    message: str


class DomainIndex:
    """
    URL-to-domain index for the manager's domain-lock (-D) feature.

    Thread-safety: ``mark_*`` methods and ``save_debounced`` are thread-safe.
    ``build`` and ``load`` are intended for use on the main thread only.
    """

    VERSION = "1.3"

    def __init__(self) -> None:
        # Domain registry
        self._base_map: Dict[str, int] = {}       # domain -> domain_id
        self._domain_names: List[str] = []        # domain_id -> name

        # File registry
        self._file_map: Dict[int, str] = {}       # file_id -> str(path)
        self._file_url_counts: Dict[int, int] = {}  # file_id -> total URL count

        # Per-domain URL queues (FIFO within domain; deque for O(1) popleft)
        self._url_queues: Dict[str, deque[UrlEntry]] = {}

        # Global URL lookup — used for dedup and status queries
        self._url_entry_map: Dict[str, UrlEntry] = {}

        # Reverse stem lookup — used for partial download promotion
        self._stem_to_url: Dict[str, str] = {}   # lowercase stem -> url

        # In-progress tracking (popped from queue, not yet finished)
        self._in_progress: Set[str] = set()

        # Completion tracking
        self._finished: Dict[str, UrlStatus] = {}

        self._built_at: float = 0.0
        self._lock = threading.Lock()

        # Debounced save state
        self._save_timer: Optional[threading.Timer] = None
        self._save_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # Properties

    @property
    def total_unique_domains(self) -> int:
        return len(self._base_map)

    @property
    def total_urls(self) -> int:
        return len(self._url_entry_map)

    @property
    def total_queued(self) -> int:
        return sum(len(q) for q in self._url_queues.values())

    @property
    def total_finished(self) -> int:
        return len(self._finished)

    @property
    def built_at(self) -> float:
        return self._built_at

    def domain_queue_size(self, domain: str) -> int:
        return len(self._url_queues.get(domain, []))

    def all_domains(self) -> List[str]:
        return list(self._domain_names)

    # ------------------------------------------------------------------
    # Build

    @classmethod
    def build(
        cls,
        url_files: List[Path],
        finished_urls: Optional[Dict[str, str]] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> "DomainIndex":
        """
        Scan *url_files* and build a fresh index.

        *finished_urls* is an optional ``{url: status}`` mapping that seeds the
        ``finished`` dict (e.g. loaded from a previous run's archive).
        *progress_cb* is called with status strings during the build.
        """
        idx = cls()
        idx._built_at = time.time()

        def _log(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)

        # ---- Pass 1: measure file sizes --------------------------------
        _log(f"Domain index: counting URLs in {len(url_files)} file(s)…")
        file_url_lines: Dict[int, List[Tuple[int, str]]] = {}
        for file_id, fpath in enumerate(sorted(url_files)):
            lines = _read_url_lines(fpath)
            idx._file_map[file_id] = str(fpath)
            idx._file_url_counts[file_id] = len(lines)
            file_url_lines[file_id] = lines

        # ---- Pass 2: resolve duplicates and build url_entry_map --------
        _log("Domain index: resolving duplicates and building URL map…")
        # url -> (file_id, line_num, domain)
        resolved: Dict[str, Tuple[int, int, str]] = {}

        for file_id, lines in file_url_lines.items():
            count_this = idx._file_url_counts[file_id]
            for line_num, url in lines:
                domain = _extract_domain(url)
                if domain == "-":
                    continue
                if url in resolved:
                    # Dedup: keep the entry whose file has FEWER URLs
                    existing_file_id, _, _ = resolved[url]
                    count_existing = idx._file_url_counts[existing_file_id]
                    if count_this < count_existing:
                        resolved[url] = (file_id, line_num, domain)
                    # else keep existing — skip this duplicate
                else:
                    resolved[url] = (file_id, line_num, domain)

        # ---- Pass 3: build domain queues --------------------------------
        _log(f"Domain index: building domain queues ({len(resolved)} unique URLs)…")
        # Group by domain then file for deterministic ordering
        domain_entries: Dict[str, List[UrlEntry]] = {}
        for url, (file_id, line_num, domain) in resolved.items():
            entry = UrlEntry(
                url=url,
                file_id=file_id,
                file_path=idx._file_map[file_id],
                line_num=line_num,
            )
            idx._url_entry_map[url] = entry
            # Stem map for partial download promotion
            stem = Path(url.rstrip("/").split("/")[-1]).stem.lower()
            if stem:
                idx._stem_to_url.setdefault(stem, url)

            # Register domain
            if domain not in idx._base_map:
                idx._base_map[domain] = len(idx._domain_names)
                idx._domain_names.append(domain)

            domain_entries.setdefault(domain, []).append(entry)

        # Build queues sorted by (file_id, line_num) for determinism
        for domain, entries in domain_entries.items():
            entries.sort(key=lambda e: (e.file_id, e.line_num))
            idx._url_queues[domain] = deque(entries)

        # ---- Seed finished dict ----------------------------------------
        if finished_urls:
            for url, status in finished_urls.items():
                if url in idx._url_entry_map:
                    e = idx._url_entry_map[url]
                    idx._finished[url] = UrlStatus(
                        url=url,
                        file_id=e.file_id,
                        file_path=e.file_path,
                        line_num=e.line_num,
                        status=status,
                    )
                    # Remove from queue if still there
                    idx._remove_from_queue(url)

        total_domains = len(idx._base_map)
        _log(
            f"Domain index ready: {total_domains} unique domain(s), "
            f"{len(resolved)} URL(s) across {len(url_files)} file(s)."
        )
        return idx

    def _remove_from_queue(self, url: str) -> bool:
        """Remove *url* from its domain queue. Returns True if found."""
        entry = self._url_entry_map.get(url)
        if not entry:
            return False
        domain = _extract_domain(url)
        q = self._url_queues.get(domain)
        if not q:
            return False
        # Rebuild without this entry — O(n) but only done on finish/dedup
        new_q = deque(e for e in q if e.url != url)
        if len(new_q) == len(q):
            return False
        self._url_queues[domain] = new_q
        return True

    # ------------------------------------------------------------------
    # URL selection

    def pick_url(
        self,
        active_domain_counts: Dict[str, int],
        max_per_domain: int,
        file_priority: Dict[int, int],
        scan_log: Optional[List[ScanLogEntry]] = None,
        prefer_partial: bool = True,
    ) -> Optional[UrlEntry]:
        """
        Select the best available URL within domain-lock constraints.

        Parameters
        ----------
        active_domain_counts : dict mapping domain -> number of currently active workers
        max_per_domain       : maximum simultaneous workers per domain
        file_priority        : file_id -> priority rank (lower number = higher priority)
        scan_log             : if provided, populated with ScanLogEntry items describing
                               each URL/file checked (written to worker's prog log by caller)
        prefer_partial       : when True, URLs flagged as partial (via mark_partial) are
                               selected before any non-partial URL regardless of file rank.
                               Domain capacity limits are always enforced first.

        Priority tiers (highest to lowest):
        1. Domain capacity hard constraint — never exceed max_per_domain.
        2. Partial tier (prefer_partial=True) — any partial URL beats all non-partial URLs.
        3. File priority — lowest rank number wins among candidates in the same tier.

        Returns the selected UrlEntry (already popped from queue), or None when
        no qualifying URL exists.
        """
        def _slog(kind: str, msg: str) -> None:
            if scan_log is not None:
                scan_log.append(ScanLogEntry(kind=kind, message=msg))

        active_str = ", ".join(sorted(active_domain_counts.keys())) or "(none)"
        _slog("SEARCH", f"active domains: {active_str}  max_per={max_per_domain}")

        with self._lock:
            # Two-tier candidate tracking:
            #   partial_best — best partial entry across all available domains
            #   normal_best  — best non-partial entry (fallback when no partials)
            partial_best_rank: Optional[int] = None
            partial_best_domain: Optional[str] = None
            partial_best_entry: Optional[UrlEntry] = None

            normal_best_rank: Optional[int] = None
            normal_best_domain: Optional[str] = None
            normal_best_entry: Optional[UrlEntry] = None

            for domain, q in self._url_queues.items():
                current = active_domain_counts.get(domain, 0)
                if current >= max_per_domain:
                    continue
                if not q:
                    continue

                # Separate available entries into partial and normal buckets,
                # tracking the best file rank in each.
                domain_partial_rank: Optional[int] = None
                domain_partial_entry: Optional[UrlEntry] = None
                domain_normal_rank: Optional[int] = None
                domain_normal_entry: Optional[UrlEntry] = None

                files_logged: Dict[int, int] = {}  # fid -> queued count (for SCAN log)
                for entry in q:
                    if entry.url in self._finished or entry.url in self._in_progress:
                        continue
                    rank = file_priority.get(entry.file_id, 999_999)
                    files_logged[entry.file_id] = files_logged.get(entry.file_id, 0) + 1
                    if prefer_partial and entry.partial:
                        if domain_partial_rank is None or rank < domain_partial_rank:
                            domain_partial_rank = rank
                            domain_partial_entry = entry
                    else:
                        if domain_normal_rank is None or rank < domain_normal_rank:
                            domain_normal_rank = rank
                            domain_normal_entry = entry

                for fid, queued_count in files_logged.items():
                    fname = Path(self._file_map.get(fid, "?")).name
                    total_in_file = self._file_url_counts.get(fid, 0)
                    _slog(
                        "SCAN",
                        f"{fname} [{total_in_file} URLs]  domain={domain}  "
                        f"queued={queued_count}  active={current}/{max_per_domain}",
                    )

                if domain_partial_entry is not None and domain_partial_rank is not None:
                    if partial_best_rank is None or domain_partial_rank < partial_best_rank:
                        partial_best_rank = domain_partial_rank
                        partial_best_domain = domain
                        partial_best_entry = domain_partial_entry

                if domain_normal_entry is not None and domain_normal_rank is not None:
                    if normal_best_rank is None or domain_normal_rank < normal_best_rank:
                        normal_best_rank = domain_normal_rank
                        normal_best_domain = domain
                        normal_best_entry = domain_normal_entry

            # Prefer partial tier; fall back to normal
            if partial_best_entry is not None:
                best_entry = partial_best_entry
                best_domain = partial_best_domain
                _slog("PARTIAL", f"selected partial URL in domain {best_domain}")
            elif normal_best_entry is not None:
                best_entry = normal_best_entry
                best_domain = normal_best_domain
            else:
                _slog("WAIT", "no URL available within domain limits")
                return None

            # Pop the selected entry from the domain queue
            assert best_domain is not None
            q = self._url_queues[best_domain]
            target_url = best_entry.url
            new_q = deque(e for e in q if e.url != target_url)
            self._url_queues[best_domain] = new_q
            self._in_progress.add(target_url)

            fname = Path(best_entry.file_path).name
            _slog(
                "FOUND",
                f"{best_domain} → {fname} line {best_entry.line_num}  {best_entry.url}"
                + ("  [PARTIAL]" if best_entry.partial else ""),
            )
            return best_entry

    # ------------------------------------------------------------------
    # State updates

    def mark_finished(self, url: str, status: str) -> None:
        """Mark *url* as completed (downloaded/preexisting/failed)."""
        with self._lock:
            entry = self._url_entry_map.get(url)
            if entry is None:
                return
            self._in_progress.discard(url)
            self._finished[url] = UrlStatus(
                url=url,
                file_id=entry.file_id,
                file_path=entry.file_path,
                line_num=entry.line_num,
                status=status,
            )
            # Remove from queue if it somehow ended up back there
            self._remove_from_queue(url)
        if self._save_path:
            self._trigger_debounced_save()

    def requeue_url(self, url: str) -> None:
        """Return *url* to the back of its domain queue (e.g. after a non-fatal failure)."""
        with self._lock:
            self._in_progress.discard(url)
            entry = self._url_entry_map.get(url)
            if entry is None or url in self._finished:
                return
            domain = _extract_domain(url)
            q = self._url_queues.setdefault(domain, deque())
            # Only re-add if not already present
            if not any(e.url == url for e in q):
                q.append(entry)

    def mark_partial(self, url: str) -> None:
        """
        Promote *url* to the front of its domain queue and flag it as partial.

        A URL is partial when a ``_partial/<hash>/`` working directory exists for
        it, meaning a previous download attempt left resumable fragments.  Partial
        URLs are scheduled ahead of non-partial ones when ``--prioritize-partial``
        is active (see ``pick_url``'s ``prefer_partial`` parameter).
        """
        with self._lock:
            if url in self._finished or url in self._in_progress:
                return
            entry = self._url_entry_map.get(url)
            if entry is None:
                return
            entry.partial = True
            domain = _extract_domain(url)
            q = self._url_queues.get(domain)
            if not q:
                return
            new_q = deque(e for e in q if e.url != url)
            new_q.appendleft(entry)
            self._url_queues[domain] = new_q

    def find_by_stem(self, stem: str) -> Optional[UrlEntry]:
        """Return the UrlEntry whose URL filename stem matches *stem* (case-insensitive)."""
        url = self._stem_to_url.get(stem.lower())
        if url:
            return self._url_entry_map.get(url)
        return None

    def is_finished(self, url: str) -> bool:
        return url in self._finished

    def is_in_progress(self, url: str) -> bool:
        return url in self._in_progress

    def finished_status(self, url: str) -> Optional[str]:
        s = self._finished.get(url)
        return s.status if s else None

    # ------------------------------------------------------------------
    # Serialization

    def save(self, path: Path) -> None:
        """Persist the index to *path* as JSON (atomic via temp file)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = self._to_dict()
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _to_dict(self) -> dict:
        return {
            "version": self.VERSION,
            "built_at": self._built_at,
            "files": [
                {"id": fid, "path": fpath, "url_count": self._file_url_counts.get(fid, 0)}
                for fid, fpath in sorted(self._file_map.items())
            ],
            "domains": [
                {"id": did, "name": name}
                for did, name in enumerate(self._domain_names)
            ],
            "queues": {
                domain: [
                    {"url": e.url, "file_id": e.file_id, "line": e.line_num,
                     **({"partial": True} if e.partial else {})}
                    for e in q
                ]
                for domain, q in self._url_queues.items()
                if q  # omit empty queues — they are noise and cause confusion
            },
            "in_progress": [
                {
                    "url": url,
                    "file_id": e.file_id,
                    "file_path": e.file_path,
                    "line": e.line_num,
                }
                for url in self._in_progress
                if (e := self._url_entry_map.get(url)) is not None
            ],
            "finished": {
                url: {
                    "status": s.status,
                    "file_id": s.file_id,
                    "file_path": s.file_path,
                    "line": s.line_num,
                    "ts": s.timestamp,
                }
                for url, s in self._finished.items()
            },
        }

    @classmethod
    def load(cls, path: Path) -> "DomainIndex":
        """Restore an index from a JSON file previously written by ``save()``."""
        data = json.loads(path.read_text(encoding="utf-8"))
        idx = cls()
        idx._built_at = float(data.get("built_at", 0.0))

        for f in data.get("files", []):
            fid = int(f["id"])
            idx._file_map[fid] = f["path"]
            idx._file_url_counts[fid] = int(f.get("url_count", 0))

        for d in data.get("domains", []):
            did = int(d["id"])
            name = d["name"]
            idx._base_map[name] = did
            while len(idx._domain_names) <= did:
                idx._domain_names.append("")
            idx._domain_names[did] = name

        for domain, entries in data.get("queues", {}).items():
            if not entries:
                continue  # skip empty queues (noise from previous sessions)
            q: deque[UrlEntry] = deque()
            for e in entries:
                fid = int(e["file_id"])
                entry = UrlEntry(
                    url=e["url"],
                    file_id=fid,
                    file_path=idx._file_map.get(fid, ""),
                    line_num=int(e["line"]),
                    partial=bool(e.get("partial", False)),
                )
                q.append(entry)
                idx._url_entry_map[entry.url] = entry
                stem = Path(entry.url.rstrip("/").split("/")[-1]).stem.lower()
                if stem:
                    idx._stem_to_url.setdefault(stem, entry.url)
            idx._url_queues[domain] = q

        # URLs that were in-progress when the previous session ended were never
        # finished.  Restore them to the front of their domain queue so they
        # get retried rather than being silently skipped forever.
        #
        # in_progress items may be dicts {url, file_id, file_path, line} (v1.2+)
        # or bare strings (v1.1 legacy).  For dicts, we reconstruct the UrlEntry
        # and insert it into _url_entry_map before re-queuing — this is necessary
        # because in_progress URLs were popped from their domain queues and are
        # therefore absent from _url_entry_map after load().
        for item in data.get("in_progress", []):
            if isinstance(item, str):
                # Legacy v1.1 format: bare URL string.  May silently drop if
                # the URL was already popped from its queue (not in _url_entry_map).
                url = item
                if url not in idx._finished:
                    idx.requeue_url(url)
            else:
                url = item.get("url", "")
                if not url or url in idx._finished:
                    continue
                # Pre-populate _url_entry_map so requeue_url can find the entry.
                if url not in idx._url_entry_map:
                    fid = int(item.get("file_id", -1))
                    entry = UrlEntry(
                        url=url,
                        file_id=fid,
                        file_path=item.get("file_path", idx._file_map.get(fid, "")),
                        line_num=int(item.get("line", 0)),
                    )
                    idx._url_entry_map[url] = entry
                idx.requeue_url(url)
        # _in_progress starts empty for this session; pick_url will re-populate it.

        for url, s in data.get("finished", {}).items():
            fid = int(s.get("file_id", -1))
            idx._finished[url] = UrlStatus(
                url=url,
                file_id=fid,
                file_path=s.get("file_path", idx._file_map.get(fid, "")),
                line_num=int(s.get("line", 0)),
                status=s["status"],
                timestamp=float(s.get("ts", 0.0)),
            )

        return idx

    def is_stale(self) -> bool:
        """Return True if any indexed file has been modified since the index was built."""
        for fpath in self._file_map.values():
            p = Path(fpath)
            try:
                if p.stat().st_mtime > self._built_at:
                    return True
            except FileNotFoundError:
                return True
        return False

    def save_debounced(self, path: Path, delay_s: float = 5.0) -> None:
        """Schedule a save in *delay_s* seconds; resets the timer on repeated calls."""
        self._save_path = path
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(delay_s, self._do_debounced_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _trigger_debounced_save(self) -> None:
        if self._save_path:
            self.save_debounced(self._save_path)

    def _do_debounced_save(self) -> None:
        if self._save_path:
            try:
                self.save(self._save_path)
            except Exception:
                pass

    def flush_save(self) -> None:
        """Cancel any pending debounced save and write immediately."""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        if self._save_path:
            try:
                self.save(self._save_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Summary

    def summary_line(self) -> str:
        queued = self.total_queued
        finished = self.total_finished
        in_prog = len(self._in_progress)
        return (
            f"{self.total_unique_domains} domain(s)  "
            f"{self.total_urls} URL(s) total  "
            f"{queued} queued  {in_prog} in-progress  {finished} finished"
        )
