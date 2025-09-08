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
DEF_URL_DIR = Path("./files/downloads/stars")
DEF_AE_URL_DIR = Path("./files/downloads/ae-stars")
DEF_OUT_DIR = Path("./stars")
DEF_COUNTS_FILE = Path("./urlfile_dl_counts.txt")  # JSON content
DEF_EXTS = {"mp4", "mkv", "webm", "mov", "avi", "m4v", "flv", "wmv", "ts"}

# ---------- helpers ----------
def _now_ts() -> str:
    import datetime as dt
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _fmt_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    try:
        s = int(max(0, seconds))
    except Exception:
        s = 0
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return path.read_text(errors="ignore")

def _atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def _count_downloaded_in_dir(dest: Path, exts: Iterable[str]) -> int:
    """Fast count of existing video files in dest (case-insensitive)."""
    if not dest.exists():
        return 0
    want = {("." + e.lower().lstrip(".")) for e in exts}
    cnt = 0
    try:
        for f in dest.rglob("*"):
            if f.is_file():
                try:
                    if f.suffix.lower() in want:
                        cnt += 1
                except Exception:
                    pass
    except Exception:
        pass
    return cnt

# ---------- scanning ----------
@dataclass
class URLFileInfo:
    url_file: Path
    stem: str
    source: str
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
        return dataclasses.asdict(self)

    @staticmethod
    def from_json(obj: dict) -> "CountsSnapshot":
        cs = CountsSnapshot()
        cs.version = int(obj.get("version", 1))
        cs.computed_at = obj.get("computed_at", _now_ts())
        cs.sources = obj.get("sources", {})
        cs.files = obj.get("files", {})
        return cs

def _is_snapshot_complete(snap: "CountsSnapshot", main_url_dir: Path, ae_url_dir: Path) -> bool:
    """
    A snapshot is "complete" if it lists every current *.txt under both roots
    and each entry's stored mtime/size matches the file on disk.

    Tests call this with (snap, tmp_path, tmp_path).
    """

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
    pause_evt: threading.Event,
    stop_evt: threading.Event,
    *,
    count_downloaded: int,
) -> tuple[int, int, int]:
    """
    Single-pass line scanner:
      - counts URL-ish lines (http/https) as 'urls'
      - non-URL non-comment lines => 'bad'
      - 'downloaded' is supplied up-front (quick dir walk)
      - progress reported periodically via progress_cb
    Returns: (urls_total, downloaded, bad)
    """
    urls = 0
    bad = 0
    seen = 0
    start = time.time()
    last_tick = start

    # display initial label
    status_cb(f"working")

    try:
        with url_file.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                if stop_evt.is_set():
                    break
                while pause_evt.is_set() and not stop_evt.is_set():
                    time.sleep(0.05)

                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("http://") or s.startswith("https://"):
                    urls += 1
                else:
                    bad += 1
                seen += 1

                # periodic UI/progress update (~10Hz max)
                now = time.time()
                if now - last_tick >= 0.1:
                    elapsed = max(0.001, now - start)
                    rate = seen / elapsed
                    eta = (max(0, urls - seen) / rate) if rate > 0 and urls > 0 else None
                    progress_cb(seen, urls or seen, count_downloaded, bad, eta)
                    last_tick = now
    except FileNotFoundError:
        pass
    except Exception:
        # keep it resilient
        pass

    # final update
    elapsed = max(0.001, time.time() - start)
    rate = seen / elapsed
    eta = (max(0, urls - seen) / rate) if rate > 0 and urls > 0 else None
    progress_cb(seen, urls or seen, count_downloaded, bad, eta)
    return urls, count_downloaded, bad

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

    urls_total, downloaded, bad = _fast_scan_urlfile(
        url_file,
        _status,
        _progress,
        pause_evt,
        stop_evt,
        count_downloaded=dl_count,
    )

    remaining = max(0, urls_total - downloaded - bad)
    return URLFileInfo(url_file, url_file.stem, "main", dest, urls_total, downloaded, bad, remaining, True)

def _scan_one_file_ae(
    url_file: Path,
    out_base: Path,
    exts: Iterable[str],
    *,
    pause_evt: threading.Event,
    stop_evt: threading.Event,
    ui_set_label,      # callable(text)
    ui_progress,       # callable(seen, urls, dl, bad, eta)
    olog,
) -> URLFileInfo:
    """AE scan path — we still avoid slug-per-line FS hits; use quick dir walk."""
    dest = out_base / url_file.stem
    dl_count = _count_downloaded_in_dir(dest, exts)

    def _status(lbl: str):
        ui_set_label(f"ae:{url_file.stem} | {lbl}")

    def _progress(seen, urls, dl, bad, eta):
        ui_progress(seen, urls, dl, bad, eta)

    urls_total, downloaded, bad = _fast_scan_urlfile(
        url_file,
        _status,
        _progress,
        pause_evt,
        stop_evt,
        count_downloaded=dl_count,
    )

    remaining = max(0, urls_total - downloaded)  # 'bad' is informational for AE
    return URLFileInfo(url_file, url_file.stem, "ae", dest, urls_total, downloaded, bad, remaining, False)

# ---------- selection ----------
@dataclass
class _WorkFile:
    url_file: Path
    stem: str
    source: str
    out_dir: Path
    urls: List[str]
    remaining: int

def _build_worklist(snap: CountsSnapshot, exts: Iterable[str]) -> List[_WorkFile]:
    work: List[_WorkFile] = []
    for k, rec in snap.files.items():
        url_file = Path(k)
        urls = read_urls_from_files([url_file])
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

    main_files = [(f, "main") for f in _iter_txt(main_url_dir)]
    ae_files = [(f, "ae") for f in _iter_txt(ae_url_dir)]
    all_files = main_files + ae_files

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
    ui.set_footer("Keys: z pause/resume | q confirm quit | Q force quit")

    q: "queue.Queue[tuple[Path,str]]" = queue.Queue()
    for f, src in all_files:
        q.put((f, src))

    lock = threading.Lock()

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
                olog(f"SCAN error {f}: {ex}")

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
                ch = os.read(fd, 1).decode(errors="ignore")
                if ch:
                    yield ch
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass

    def _read_char_win():
        import msvcrt
        while not stop_evt.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch:
                    yield ch
            else:
                time.sleep(0.1)

    reader = _read_char_win if os.name == "nt" else _read_char_posix

    ui.set_footer("Keys: z pause/resume | q confirm quit | Q force quit")
    for ch in reader():
        if ch == "z":
            paused = not pause_evt.is_set()
            if paused:
                pause_evt.set()
            else:
                pause_evt.clear()
            ui.set_paused(paused)
            olog(f"hotkey: pause={'on' if paused else 'off'}")

        elif ch == "Q":
            olog("hotkey: FORCE QUIT")
            stop_evt.set()
            request_abort()
            terminate_all_active_procs()
            return

        elif ch == "q":
            ui.set_footer("Quit? press 'y' to confirm, any other key to cancel")
            # wait one next keystroke
            try:
                nxt = next(reader())
            except StopIteration:
                nxt = None
            if nxt and nxt.lower() == "y":
                olog("hotkey: quit confirmed")
                stop_evt.set()
                request_abort()
                terminate_all_active_procs()
                return
            else:
                ui.set_footer("Cancelled. Keys: z pause/resume | q confirm quit | Q force quit")

# ---------- main orchestrator ----------
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
    p.add_argument("-w", "--work-dir", type=Path, default=Path("./tmp_dl"), help="Working directory for caches.")
    p.add_argument("-tO", "--timeout", type=int, default=3600, help="Per-download timeout (seconds).")
    p.add_argument("-L", "--log-file", type=Path, help="Append a text log of events to this file.")
    p.add_argument("-A", "--aebn-arg", action="append", help="Append raw arg to aebndl (repeatable).")
    p.add_argument("-Y", "--ytdlp-arg", action="append", help="Append raw arg to yt-dlp (repeatable).")
    return p.parse_args(argv)

def _build_config(args: argparse.Namespace) -> DownloaderConfig:
    return DownloaderConfig(
        work_dir=args.work_dir,
        timeout_seconds=int(args.timeout),
        parallel_jobs=max(1, int(args.jobs)),
        save_covers=False,
        extra_aebn_args=args.aebn_arg or [],
        extra_ytdlp_args=args.ytdlp_arg or [],
        log_file=args.log_file,
    )

class _Coordinator:
    """Assign URL files to workers by highest `remaining` first (thread-safe)."""
    def __init__(self, work: List[_WorkFile]):
        self._lock = threading.Lock()
        self._assigned: set[str] = set()
        self._work = sorted(work, key=lambda w: (w.remaining, w.stem), reverse=True)

    def acquire_next(self) -> Optional[_WorkFile]:
        with self._lock:
            for wf in self._work:
                key = str(wf.url_file.resolve())
                if key in self._assigned:
                    continue
                if wf.remaining <= 0:
                    continue
                self._assigned.add(key)
                return wf
            return None

    def release(self, wf: _WorkFile, remaining_delta: int) -> None:
        with self._lock:
            wf.remaining = max(0, wf.remaining + remaining_delta)
            key = str(wf.url_file.resolve())
            self._assigned.discard(key)
            self._work.sort(key=lambda w: (w.remaining, w.stem), reverse=True)

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    exts = {e.strip().lower().lstrip(".") for e in args.exts.split(",") if e.strip()} or set(DEF_EXTS)

    # open orchestrator log early
    log_fp = None
    if args.log_file:
        try:
            args.log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fp = open(args.log_file, "a", encoding="utf-8")
        except Exception:
            log_fp = None

    def olog(line: str):
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
            ui = SimpleUI()
            use_ui = False
    else:
        ui = SimpleUI()

    stop_evt = threading.Event()
    pause_evt = threading.Event()  # when set => paused

    # signals
    def _handle_sigint(signum, frame):
        olog("SIGINT: stopping")
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
            return 0

        work = _build_worklist(snap, exts)
        if not work:
            olog("no work; exiting")
            if log_fp:
                log_fp.close()
            return 0

        cfg = _build_config(args)
        object.__setattr__(cfg, "_orchestrator_max_dl", int(args.max_dl))

        coord = _Coordinator(work)

        def _worker_thread(slot: int):
            max_dl = getattr(cfg, "_orchestrator_max_dl", 3)
            while not stop_evt.is_set():
                # pause gate
                while pause_evt.is_set() and not stop_evt.is_set():
                    ui.pump()
                    time.sleep(0.1)
                if stop_evt.is_set():
                    break

                wf = coord.acquire_next()
                if not wf:
                    break

                completed_for_this_assignment = 0

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
                        if is_aebn_url(url):
                            slug = get_url_slug(url)
                            # Use quick dir walk instead of slug-by-slug checks during downloads
                            # (downloaders will re-check accurately)
                            if _count_downloaded_in_dir(dest_dir, exts) >= 1:
                                pass  # fall through; still allow download attempt if mismatched
                        else:
                            # Fast presence check via directory count + name-agnostic heuristic
                            if _count_downloaded_in_dir(dest_dir, exts) >= 1:
                                pass
                    except Exception:
                        pass

                    local_id = slot * 1_000_000 + idx
                    item = DownloadItem(
                        id=local_id,
                        url=url,
                        output_dir=dest_dir,
                        source=URLSource(file=wf.url_file, line_number=idx, original_url=url),
                        retries=3,
                    )
                    dl = get_downloader(url, cfg)
                    try:
                        for ev in dl.download(item):
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

                    # post-check for completion (lightweight heuristic)
                    did_complete = False
                    try:
                        did_complete = _count_downloaded_in_dir(dest_dir, exts) >= 1
                    except Exception:
                        did_complete = False

                    if did_complete:
                        completed_for_this_assignment += 1
                        k = str(wf.url_file.resolve())
                        try:
                            obj = json.loads(_read_text(args.counts_file))
                            rec = obj.get("files", {}).get(k)
                            if rec:
                                rec["downloaded"] = int(rec.get("downloaded", 0)) + 1
                                rec["remaining"] = max(0, int(rec.get("remaining", 0)) - 1)
                                _atomic_write_json(args.counts_file, obj)
                        except Exception:
                            pass

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
                time.sleep(0.05)
        finally:
            stop_evt.set()
            request_abort()
            terminate_all_active_procs()
            for t in threads:
                t.join(timeout=1.0)

        ui.summary({}, time.monotonic())

    if log_fp:
        try:
            log_fp.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
