#!/usr/bin/env python3
"""Parallel, file-first orchestrator with live *scan* UI, hotkeys, and safe shutdown."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# ---------- local imports ----------
from .downloaders import (
    get_downloader,
    terminate_all_active_procs,
    request_abort,
    abort_requested,
)
from .io import read_urls_from_files
from .models import (
    DownloaderConfig,
    DownloadItem,
    URLSource,
    FinishEvent,
    StartEvent,
    LogEvent,
)
from .ui import SimpleUI, TermdashUI
from .url_parser import is_aebn_url, get_url_slug

# ---------- defaults ----------
DEF_URL_DIR = Path("files/downloads/stars")
DEF_AE_URL_DIR = Path("files/downloads/ae-stars")
DEF_OUT_DIR = Path("files/downloads/out")
DEF_COUNTS_FILE = Path("files/downloads/ytaedl-counts.json")
DEF_EXTS = {"mp4", "mkv", "webm", "mp3", "m4a", "wav"}

# ---------- helpers ----------
def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _fmt_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    s = int(max(0, seconds))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def _atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)

def _count_downloaded_in_dir(dest: Path, exts: Iterable[str]) -> int:
    if not dest.exists():
        return 0
    cnt = 0
    for p in dest.iterdir():
        if p.is_file() and p.suffix.lower().lstrip(".") in exts:
            cnt += 1
    return cnt

# ---- data structures for scan & scheduling ----------------------------
@dataclass(frozen=True)
class URLFileInfo:
    url_file: Path
    stem: str
    source: str  # "main" or "ae"
    out_dir: Path
    url_count: int
    downloaded: int
    bad: int
    remaining: int
    viable_checked: bool

@dataclass
class CountsSnapshot:
    version: int = 1
    computed_at: str = field(default_factory=_now_ts)
    sources: Dict[str, Dict[str, str]] = field(default_factory=dict)
    files: Dict[str, dict] = field(default_factory=dict)

    def to_json(self) -> dict:
        return dict(
            version=self.version,
            computed_at=self.computed_at,
            sources=self.sources,
            files=self.files,
        )

    @staticmethod
    def from_json(obj: dict) -> "CountsSnapshot":
        cs = CountsSnapshot()
        cs.version = int(obj.get("version", 1))
        cs.computed_at = str(obj.get("computed_at", _now_ts()))
        cs.sources = dict(obj.get("sources", {}))
        cs.files = dict(obj.get("files", {}))
        return cs

def _is_snapshot_complete(snap: "CountsSnapshot", main_url_dir: Path, ae_url_dir: Path) -> bool:
    def _iter_txt(d: Path) -> List[Path]:
        d = Path(d)
        return [p for p in sorted(d.glob("*.txt")) if p.is_file()]

    # Accept either a CountsSnapshot or a raw dict (from JSON)
    try:
        files = snap.files if hasattr(snap, "files") else dict(snap.get("files", {}))
    except Exception:
        return False

    all_files = [*_iter_txt(main_url_dir), *_iter_txt(ae_url_dir)]
    for f in all_files:
        key = str(f.resolve())
        rec = files.get(key)
        if not isinstance(rec, dict):
            return False
        try:
            if int(rec.get("url_mtime", -1)) != int(f.stat().st_mtime):
                return False
            if int(rec.get("url_size", -1)) != int(f.stat().st_size):
                return False
        except Exception:
            return False
    return True

# ---- FAST, RESPONSIVE SCANNERS (no per-URL yt-dlp calls) --------------------

def _fast_scan_urlfile(
    url_file: Path,
    status_cb,                   # callable(label: str)
    progress_cb,                 # callable(seen:int, urls:int, dl:int, bad:int, eta:float|None)
    *,
    out_dir: Path,
    exts: Iterable[str],
    stop_evt: threading.Event,
    pause_evt: threading.Event,
) -> Tuple[int, int, int]:
    """
    Read & classify URLs by simple rules; count already-downloaded by matching files in
    destination directory (by suffix only; *fast* approximation).
    """
    try:
        urls = read_urls_from_files([url_file])
    except Exception:
        urls = []
    total = len(urls)
    # pre-count existing files
    count_downloaded = _count_downloaded_in_dir(out_dir, exts)
    bad = 0
    seen = 0

    status_cb("reading")

    start = time.time()
    last_eta = None
    for u in urls:
        if stop_evt.is_set():
            break
        # pause gate (keeps UI aligned; pump is handled by caller)
        while pause_evt.is_set() and not stop_evt.is_set():
            time.sleep(0.05)
        if stop_evt.is_set():
            break

        seen += 1
        # fast "bad" heuristic
        if not (u.startswith("http://") or u.startswith("https://")):
            bad += 1

        elapsed = max(0.001, time.time() - start)
        rate = seen / elapsed
        eta = (max(0, total - seen) / rate) if rate > 0 and total > 0 else None
        last_eta = eta
        progress_cb(seen, total, count_downloaded, bad, eta)

    # log occasional heartbeat via caller throttle
    try:
        progress_cb(seen, total, count_downloaded, bad, last_eta)
    except Exception:
        # keep it resilient
        pass

    # final update
    elapsed = max(0.001, time.time() - start)
    rate = seen / elapsed
    eta = (max(0, total - seen) / rate) if rate > 0 and total > 0 else None
    progress_cb(seen, total or seen, count_downloaded, bad, eta)
    return total, count_downloaded, bad

def _scan_one_file_main(
    url_file: Path,
    out_base: Path,
    exts: Iterable[str],
    ytdlp_template: str,  # kept for signature compatibility; unused by fast path
    *,
    pause_evt: threading.Event,
    stop_evt: threading.Event,
    ui_set_label,      # callable(text)
    ui_progress,       # callable(seen, urls, dl, bad, eta)
    olog,
) -> URLFileInfo:
    dest = out_base / url_file.stem
    dl_count = _count_downloaded_in_dir(dest, exts)

    def _status(lbl: str):
        ui_set_label(f"main:{url_file.stem} | {lbl}")

    def _progress(seen, urls, dl, bad, eta):
        ui_progress(seen, urls, dl, bad, eta)

    total, already, bad = _fast_scan_urlfile(
        url_file,
        status_cb=_status,
        progress_cb=_progress,
        out_dir=dest,
        exts=exts,
        stop_evt=stop_evt,
        pause_evt=pause_evt,
    )
    remaining = max(0, total - already - bad)
    return URLFileInfo(
        url_file=url_file,
        stem=url_file.stem,
        source="main",
        out_dir=dest,
        url_count=total,
        downloaded=already,
        bad=bad,
        remaining=remaining,
        viable_checked=True,
    )

def _scan_one_file_ae(
    url_file: Path,
    out_base: Path,
    exts: Iterable[str],
    *,
    pause_evt: threading.Event,
    stop_evt: threading.Event,
    ui_set_label,  # callable(text)
    ui_progress,   # callable(seen, urls, dl, bad, eta)
    olog,
) -> URLFileInfo:
    dest = out_base / url_file.stem
    dl_count = _count_downloaded_in_dir(dest, exts)

    def _status(lbl: str):
        ui_set_label(f"ae:{url_file.stem} | {lbl}")

    def _progress(seen, urls, dl, bad, eta):
        ui_progress(seen, urls, dl, bad, eta)

    total, already, bad = _fast_scan_urlfile(
        url_file,
        status_cb=_status,
        progress_cb=_progress,
        out_dir=dest,
        exts=exts,
        stop_evt=stop_evt,
        pause_evt=pause_evt,
    )
    remaining = max(0, total - already - bad)
    return URLFileInfo(
        url_file=url_file,
        stem=url_file.stem,
        source="ae",
        out_dir=dest,
        url_count=total,
        downloaded=already,
        bad=bad,
        remaining=remaining,
        viable_checked=True,
    )

# ---------- build worklist ----------
@dataclass(frozen=True)
class _WorkFile:
    url_file: Path
    stem: str
    source: str
    out_dir: Path
    urls: List[str]
    remaining: int

def _build_worklist(snap: CountsSnapshot, exts: Iterable[str]) -> List[_WorkFile]:
    work: List[_WorkFile] = []
    files = snap.files
    for key, rec in files.items():
        url_file = Path(key)
        try:
            urls = read_urls_from_files([url_file])
        except Exception:
            urls = []
        work.append(
            _WorkFile(
                url_file=url_file,
                stem=str(rec.get("stem") or url_file.stem),
                source=str(rec.get("source") or "main"),
                out_dir=Path(rec.get("out_dir") or DEF_OUT_DIR / url_file.stem),
                urls=urls,
                remaining=int(rec.get("remaining") or max(0, len(urls) - int(rec.get("downloaded", 0)))),
            )
        )
    return work

# ---------- scan coordinator (parallel with UI & logging) ----------
def _scan_all_parallel(
    main_url_dir: Path,
    ae_url_dir: Path,
    out_base: Path,
    exts: set[str],
    n_workers: int,
    ytdlp_template: str,
    counts_path: Path,
    ui,
    olog,
    *,
    stop_evt: threading.Event,
    pause_evt: threading.Event,
) -> CountsSnapshot:
    def _iter_txt(d: Path) -> List[Path]:
        return [p for p in sorted(Path(d).glob("*.txt")) if p.is_file()]

    all_files: List[Tuple[Path, str]] = [(p, "main") for p in _iter_txt(main_url_dir)] + [
        (p, "ae") for p in _iter_txt(ae_url_dir)
    ]

    snap = CountsSnapshot()
    snap.sources = {
        "main": {"url_dir": str(main_url_dir.resolve()), "out_dir": str(out_base.resolve())},
        "ae": {"url_dir": str(ae_url_dir.resolve()), "out_dir": str(out_base.resolve())},
    }

    # write a stub counts file immediately
    try:
        _atomic_write_json(counts_path, snap.to_json())
    except Exception:
        pass

    if not all_files:
        return snap

    ui.begin_scan(n_workers, len(all_files))
    # Write scan results TSV next to counts file (guarded for SimpleUI/older UI)
    try:
        ui.set_scan_log_path(counts_path.with_name("ytaedl-scan-results.tsv"))
    except Exception:
        pass
    ui.set_footer("Keys: z pause/resume | q confirm quit | Q force quit")

    q: "queue.Queue[tuple[Path,str]]" = queue.Queue()
    for f, src in all_files:
        q.put((f, src))

    lock = threading.Lock()
    # per-slot progress tallies to compute deltas for the banner
    progress_state: Dict[int, Dict[str, int]] = {}

    def _progress_logger_throttled(prefix: str, path: Path):
        last = 0.0
        def _log(seen, urls, dl, bad, eta):
            nonlocal last
            now = time.time()
            if now - last >= 2.0:
                olog(f"{prefix} prog {path} seen={seen} urls={urls} dl={dl} bad={bad} eta={_fmt_hms(eta)}")
                last = now
        return _log

    def worker(slot: int):
        while not stop_evt.is_set():
            try:
                f, src = q.get_nowait()
            except queue.Empty:
                break

            # dynamic label & progress setters for this slot
            def set_label(text: str):
                # Replaces "Scan N | ..." line content; TermdashUI will redraw.
                ui.set_scan_slot(slot, text)

            def set_progress(seen: int, urls: int, dl: int, bad: int, eta: Optional[float]):
                label = f"{src}:{f.stem} | {seen}/{urls} | dl {dl} | bad {bad} | ETA {_fmt_hms(eta)}"
                ui.set_scan_slot(slot, label)
                # update banner with deltas (guarded for SimpleUI/older UI)
                try:
                    prev = progress_state.setdefault(slot, {"seen": 0, "dl": 0, "bad": 0})
                    d_seen = max(0, int(seen) - int(prev["seen"]))
                    d_dl = max(0, int(dl) - int(prev["dl"]))
                    d_bad = max(0, int(bad) - int(prev["bad"]))
                    if d_seen or d_dl or d_bad:
                        if hasattr(ui, "scan_progress_delta"):
                            ui.scan_progress_delta(d_seen, d_dl, d_bad)
                    prev["seen"], prev["dl"], prev["bad"] = int(seen), int(dl), int(bad)
                except Exception:
                    pass

            olog(f"SCAN start {src} {f}")

            try:
                if src == "main":
                    info = _scan_one_file_main(
                        f, out_base, exts, ytdlp_template,
                        pause_evt=pause_evt, stop_evt=stop_evt,
                        ui_set_label=set_label, ui_progress=set_progress,
                        olog=olog,
                    )
                else:
                    info = _scan_one_file_ae(
                        f, out_base, exts,
                        pause_evt=pause_evt, stop_evt=stop_evt,
                        ui_set_label=set_label, ui_progress=set_progress,
                        olog=olog,
                    )
            except Exception as ex:
                info = URLFileInfo(f, f.stem, src, out_base / f.stem, 0, 0, 0, 0, False)
                olog(f"SCAN error {src} {f}: {ex}")

            with lock:
                # If we were asked to stop, still persist what we have so far.
                try:
                    st = f.stat()
                    snap.files[str(f.resolve())] = {
                        "stem": info.stem,
                        "source": info.source,
                        "out_dir": str(info.out_dir.resolve()),
                        "url_count": info.url_count,
                        "downloaded": info.downloaded,
                        "bad": info.bad,
                        "remaining": info.remaining,
                        "viable_checked": info.viable_checked,
                        "url_mtime": int(st.st_mtime),
                        "url_size": int(st.st_size),
                    }
                    _atomic_write_json(counts_path, snap.to_json())
                except Exception:
                    pass

            # notify UI of per-file finalization for TSV & banner sync (guarded)
            try:
                ui.scan_file_done(f, total=info.url_count, downloaded=info.downloaded, bad=info.bad)
            except Exception:
                pass

            ui.advance_scan(1)
            olog(
                f"SCAN done  {src} {f} "
                f"urls={info.url_count} dl={info.downloaded} bad={info.bad} rem={info.remaining}"
            )

            if stop_evt.is_set():
                break

    threads: List[threading.Thread] = []
    for i in range(max(1, n_workers)):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        t.start()
        threads.append(t)

    # join with UI pumping (live UI, immediate pause/quit)
    while any(t.is_alive() for t in threads):
        if stop_evt.is_set():
            break
        # render heartbeat
        ui.pump()
        time.sleep(0.05)

    # ensure threads exit quickly when stopping mid-scan
    for t in threads:
        t.join(timeout=1.0)

    ui.end_scan()
    ui.pump()
    return snap

# ---------- hotkeys ----------
def _key_listener(ui, pause_evt: threading.Event, stop_evt: threading.Event, olog):
    """Listen for z/q/Q from stdin without blocking the main thread."""
    if not sys.stdin.isatty():
        return  # no interactive keys available

    def _read_char_posix():
        import termios, tty, select
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not stop_evt.is_set():
                r, _, _ = select.select([fd], [], [], 0.1)
                if not r:
                    continue
                ch = os.read(fd, 1)
                if not ch:
                    continue
                yield ch.decode(errors="ignore")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _read_char_win():
        import msvcrt
        while not stop_evt.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                yield ch
            else:
                time.sleep(0.1)

    reader = _read_char_win if os.name == "nt" else _read_char_posix

    for ch in reader():
        if ch in ("z", "Z"):
            if pause_evt.is_set():
                pause_evt.clear()
                try: ui.set_paused(False)
                except Exception: pass
                olog("pause: off")
            else:
                pause_evt.set()
                try: ui.set_paused(True)
                except Exception: pass
                olog("pause: on")
        elif ch == "q":
            stop_evt.set()
            olog("quit requested (soft)")
            break
        elif ch == "Q":
            stop_evt.set()
            request_abort()
            terminate_all_active_procs()
            olog("quit requested (force)")
            break

# ---------- CLI ----------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="yt-ae-orchestrate",
        description="File-first orchestrator for yt-dlp/aebndl across two URL roots.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-t", "--threads", type=int, default=2, help="Worker slots (one URL file per worker).")
    p.add_argument("-m", "--max-dl", type=int, default=3, help="Max SUCCESSFUL downloads per file per assignment.")
    p.add_argument("--url-dir", type=Path, default=DEF_URL_DIR, help="Main url dir (stars).")
    p.add_argument("--ae-url-dir", type=Path, default=DEF_AE_URL_DIR, help="AE url dir (ae-stars).")
    p.add_argument("-o", "--output-dir", type=Path, default=DEF_OUT_DIR, help="Base output dir (stars/<stem>).")
    p.add_argument("-c", "--counts-file", type=Path, default=DEF_COUNTS_FILE, help="JSON counts file path.")
    p.add_argument("-e", "--exts", default=",".join(sorted(DEF_EXTS)), help="Extensions considered 'downloaded'.")
    p.add_argument("--no-ui", action="store_true", help="Disable TermDash UI (simple prints).")
    p.add_argument("--ytdlp-template", default="%(title)s.%(ext)s", help="Template used for yt-dlp expected names.")
    # pass-through to DownloaderConfig
    p.add_argument("-j", "--jobs", type=int, default=1, help="(per-process) jobs for yt-dlp/aebndl.")
    p.add_argument("--archive", type=Path, default=None, help="Optional archive file to skip known URLs.")
    p.add_argument("--log-file", "-L", type=Path, help="Append a text log of events to this file.")
    p.add_argument("--timeout", type=int, default=None, help="Downloader timeout (seconds).")
    p.add_argument("--rate-limit", default=None, help="yt-dlp --throttled-rate.")
    p.add_argument("--buffer-size", default=None, help="yt-dlp --buffer-size.")
    p.add_argument("--retries", type=int, default=None, help="yt-dlp --retries.")
    p.add_argument("--fragment-retries", type=int, default=None, help="yt-dlp --fragment-retries.")
    p.add_argument("--ytdlp-connections", type=int, default=None, help="yt-dlp -N.")
    p.add_argument("--aria2-splits", type=int, default=None, help="aria2 split count.")
    p.add_argument("--aria2-x-conn", type=int, default=None, help="aria2 max connections per server.")
    p.add_argument("--aria2-min-split", default=None, help="aria2 --min-split-size (e.g. 1M).")
    p.add_argument("--aria2-timeout", type=int, default=None, help="aria2 --timeout seconds.")
    return p.parse_args(argv)

def _build_config(args: argparse.Namespace) -> DownloaderConfig:
    return DownloaderConfig(
        work_dir=args.output_dir,
        archive_path=args.archive,
        max_size_gb=10.0,
        keep_oversized=False,
        timeout_seconds=args.timeout,
        parallel_jobs=max(1, args.jobs),
        aebn_only=False,
        scene_from_url=True,
        save_covers=False,
        keep_covers_flag=False,
        extra_aebn_args=[],
        extra_ytdlp_args=[],
        ytdlp_connections=args.ytdlp_connections,
        ytdlp_rate_limit=args.rate_limit,
        ytdlp_retries=args.retries,
        ytdlp_fragment_retries=args.fragment_retries,
        ytdlp_buffer_size=args.buffer_size,
        aria2_splits=args.aria2_splits,
        aria2_x_conn=args.aria2_x_conn,
        aria2_min_split=args.aria2_min_split,
        aria2_timeout=args.aria2_timeout,
        log_file=args.log_file,
    )

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # normalize paths
    args.url_dir = Path(args.url_dir)
    args.ae_url_dir = Path(args.ae_url_dir)
    args.output_dir = Path(args.output_dir)
    args.counts_file = Path(args.counts_file)
    args.exts = set([s.strip().lstrip(".").lower() for s in str(args.exts).split(",") if s.strip()])

    # logging shim: write to --log-file if set
    log_fp = None
    if args.log_file:
        try:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fp = open(args.log_file, "a", encoding="utf-8")
        except Exception:
            log_fp = None

    def olog(line: str) -> None:
        if log_fp:
            try:
                log_fp.write(f"[{_now_ts()}] {line}\n")
                log_fp.flush()
            except Exception:
                pass

    # UI early, once
    use_ui = not args.no_ui
    if use_ui:
        try:
            ui = TermdashUI(num_workers=max(1, args.threads), total_urls=0)
        except Exception as ex:
            olog(f"UI fallback: {ex}")
            # Some SimpleUI variants take no args; be tolerant.
            try:
                ui = SimpleUI(num_workers=max(1, args.threads), total_urls=0)
            except TypeError:
                ui = SimpleUI()
            use_ui = False
    else:
        try:
            ui = SimpleUI(num_workers=max(1, args.threads), total_urls=0)
        except TypeError:
            ui = SimpleUI()

    stop_evt = threading.Event()
    pause_evt = threading.Event()

    # SIGINT: stop + pass through to downloaders
    def _handle_sigint(_sig, _frm):
        stop_evt.set()
        request_abort()
        terminate_all_active_procs()
    try:
        signal.signal(signal.SIGINT, _handle_sigint)
    except Exception:
        pass

    with ui:
        olog("orchestrator start")

        # hotkeys (best effort; ignored if no TTY)
        threading.Thread(target=_key_listener, args=(ui, pause_evt, stop_evt, olog), daemon=True).start()

        # scan phase (now responsive & visible)
        exts = set(args.exts)
        snap = _scan_all_parallel(
            args.url_dir, args.ae_url_dir, args.output_dir, exts,
            n_workers=max(1, args.threads),
            ytdlp_template=args.ytdlp_template,
            counts_path=args.counts_file,
            ui=ui,
            olog=olog,
            stop_evt=stop_evt,
            pause_evt=pause_evt,
        )

        # if quitting during scan, exit early
        if stop_evt.is_set():
            if log_fp:
                try: log_fp.close()
                except Exception: pass
            return 130  # interrupted

        # build worklist (balanced by fewest remaining first)
        work = sorted(_build_worklist(snap, exts), key=lambda w: (w.remaining, w.stem))

        # Coordinator balances assignments to different stems
        coord = _Coordinator(work)

        # downloader config
        cfg = _build_config(args)
        # store per-assignment cap on successful downloads (frozen dataclass fix)
        object.__setattr__(cfg, "_orchestrator_max_dl", int(args.max_dl))

        # worker thread
        def _worker_thread(slot: int):
            while not stop_evt.is_set():
                wf = coord.acquire_next()
                if wf is None:
                    break  # nothing left

                ui.set_scan_slot(slot, f"{wf.source}:{wf.stem} | downloading (rem {wf.remaining})")

                completed_for_this_assignment = 0
                max_dl = getattr(cfg, "_orchestrator_max_dl", 3)

                for idx, url in enumerate(wf.urls, start=1):
                    if stop_evt.is_set():
                        break
                    # pause gate between URLs
                    while pause_evt.is_set() and not stop_evt.is_set():
                        ui.pump()
                        time.sleep(0.1)
                    if stop_evt.is_set():
                        break

                    dest_dir = wf.out_dir

                    # quick skip if already present
                    try:
                        slug = get_url_slug(url)
                        any_present = any((dest_dir / f).exists() for f in os.listdir(dest_dir) if f.startswith(slug))
                    except Exception:
                        any_present = False
                    if any_present:
                        # simulate Already event into UI
                        try:
                            item = DownloadItem(id=idx, url=url, source=URLSource.MAIN if wf.source=="main" else URLSource.AE, out_dir=dest_dir)
                            ui.handle_event(LogEvent(item=item, message="already_exists"))
                            ui.pump()
                        except Exception:
                            pass
                        completed_for_this_assignment += 1
                        continue

                    dl = get_downloader(url)
                    item = DownloadItem(
                        id=idx,
                        url=url,
                        source=URLSource.MAIN if wf.source == "main" else URLSource.AE,
                        out_dir=dest_dir,
                    )
                    try:
                        ui.handle_event(StartEvent(item=item))
                        ui.pump()

                        # yield events from underlying downloader
                        for ev in dl.download(item, cfg):
                            if stop_evt.is_set():
                                break
                            # forward to UI + log summary style
                            if isinstance(ev, StartEvent):
                                olog(f"START {ev.item.id} {ev.item.url}")
                            elif isinstance(ev, FinishEvent):
                                olog(f"FINISH {ev.item.id} {ev.result.status.value} {ev.item.url}")
                            elif isinstance(ev, LogEvent):
                                olog(f"LOG {ev.item.id} {ev.message}")
                            ui.handle_event(ev)
                            ui.pump()
                            if stop_evt.is_set():
                                break
                    except KeyboardInterrupt:
                        stop_evt.set()
                        break
                    except Exception as ex:
                        olog(f"DL error {url}: {ex}")
                    finally:
                        ui.pump()

                    # consider a "successful" outcome; we count already/complete as a success for assignment pacing
                    completed_for_this_assignment += 1
                    if completed_for_this_assignment >= max_dl:
                        break

                coord.release(wf, remaining_delta=-(completed_for_this_assignment))

        threads: List[threading.Thread] = []
        for slot in range(max(1, int(args.threads))):
            t = threading.Thread(target=_worker_thread, args=(slot,), daemon=True)
            t.start()
            threads.append(t)

        try:
            while any(t.is_alive() for t in threads) and not stop_evt.is_set():
                ui.pump()
                time.sleep(0.1)
        finally:
            for t in threads:
                try:
                    t.join(timeout=1.0)
                except Exception:
                    pass

        ui.summary({}, time.monotonic())

    if log_fp:
        try:
            log_fp.close()
        except Exception:
            pass
    return 0

# ---------- work coordinator (tested in tests/test_orchestrator.py) ----------
class _Coordinator:
    """Pick next file to work on:
       - prefer files with the largest remaining count,
       - avoid assigning the same stem to two slots concurrently when possible.
    """
    def __init__(self, work: List[_WorkFile]):
        self._lock = threading.Lock()
        self._work: Dict[str, _WorkFile] = {str(w.url_file.resolve()): w for w in work}
        self._assigned: Dict[str, int] = {}  # key -> #slots

    def acquire_next(self) -> Optional[_WorkFile]:
        with self._lock:
            # prefer more remaining first; but avoid double-assigning the same stem
            candidates = sorted(self._work.values(), key=lambda w: (-w.remaining, w.stem))
            for w in candidates:
                key = str(w.url_file.resolve())
                # skip if already assigned to someone else and others exist
                if any((other.stem != w.stem and other.remaining > 0) for other in candidates):
                    if self._assigned.get(key, 0) > 0:
                        continue
                # assign
                self._assigned[key] = self._assigned.get(key, 0) + 1
                return w
            return None

    def release(self, wf: _WorkFile, *, remaining_delta: int = 0) -> None:
        with self._lock:
            key = str(wf.url_file.resolve())
            if key not in self._work:
                return
            cur = self._work[key]
            # update remaining
            new_remaining = max(0, int(cur.remaining) + int(remaining_delta))
            self._work[key] = dataclasses.replace(cur, remaining=new_remaining)
            # drop assignment count
            if key in self._assigned:
                self._assigned[key] = max(0, self._assigned[key] - 1)

if __name__ == "__main__":
    raise SystemExit(main())
