#!/usr/bin/env python3
"""
Multi-threaded video processing & analysis with a real-time dashboard.
Now with compact (stacked) UI for small terminals and robust logging.
"""
import argparse
import atexit
import concurrent.futures
import json
import os
import pathlib
import queue
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import signal
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from typing import IO, Any, Dict, Iterable, List, Optional, Tuple

# --- Module Setup ---
script_dir = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(script_dir.parent))

try:
    from modules.termdash import (Line, Stat, TermDash, bytes_to_mib,
                                  clip_ellipsis, fmt_hms, format_bytes)
except ImportError:
    print("Error: Could not import the 'termdash' library.", file=sys.stderr)
    print("Please ensure the 'modules' directory is in the correct location.", file=sys.stderr)
    sys.exit(1)

# --- Constants ---
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"}
BAR_WIDTH = 12
COMPACT_OUTPUT_THRESHOLD = 120    # for 'stats' output
DASH_COMPACT_THRESHOLD = 100      # for dashboard layout (stacked rows when width < this)

# --- Logging helpers ---

def _default_log_file() -> pathlib.Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    return script_dir / "logs" / f"video_processor-{ts}.log"

def setup_logging(log_file: Optional[pathlib.Path], level: str = "INFO") -> logging.Logger:
    """Create a rotating file logger and return it."""
    log_path = pathlib.Path(log_file) if log_file else _default_log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("video_processor")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    fh = RotatingFileHandler(str(log_path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(threadName)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)
    logger.propagate = False

    logger.info("=== video_processor start ===")
    logger.info("Log file: %s", log_path)
    return logger

def _log_versions(logger: logging.Logger):
    """Log ffmpeg/ffprobe versions."""
    for tool in (("ffmpeg", "-version"), ("ffprobe", "-version")):
        try:
            cp = subprocess.run(tool, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            logger.info("Command: %s", " ".join(tool))
            if cp.stdout:
                logger.info("%s stdout:\n%s", tool[0], cp.stdout.strip())
            if cp.stderr:
                logger.info("%s stderr:\n%s", tool[0], cp.stderr.strip())
        except Exception as e:
            logger.warning("Version check failed for %s: %s", tool[0], e)

# --- Small utilities ---

def parse_size(size_str: str) -> int:
    s = size_str.strip().upper()
    if not s:
        return 0
    m = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT])?B?$', s)
    if not m:
        raise ValueError(f"Invalid size format: '{size_str}'")
    val, unit = m.groups()
    mult = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
    return int(float(val) * mult.get(unit, 1))

def parse_bitrate(bitrate_str: str) -> int:
    s = bitrate_str.strip().lower()
    if not s:
        return 0
    val_str = s.rstrip('kmg')
    unit = s[len(val_str):]
    mult = {'k': 1000, 'm': 1000**2, 'g': 1000**3}
    return int(float(val_str) * mult.get(unit, 1))

def parse_resolution(res_str: str) -> Tuple[int, int]:
    s = res_str.strip().lower()
    m = re.match(r'^(\d+)[x: ](\d+)$', s)
    if not m:
        raise ValueError(f"Invalid resolution format: '{res_str}'. Expected WxH.")
    return int(m.group(1)), int(m.group(2))

def check_dependencies():
    if not shutil.which("ffmpeg"):
        print("Error: 'ffmpeg' not found. Please install it and ensure it's in your PATH.", file=sys.stderr)
        sys.exit(1)
    if not shutil.which("ffprobe"):
        print("Error: 'ffprobe' not found. Please install it and ensure it's in your PATH.", file=sys.stderr)
        sys.exit(1)

def _parse_out_time_seconds(progress: Dict[str, str]) -> Optional[float]:
    """Parse out_time_ms / out_time_us / out_time (HH:MM:SS[.us]) -> seconds."""
    if "out_time_ms" in progress:
        try:
            return int(progress["out_time_ms"]) / 1_000.0
        except ValueError:
            pass
    if "out_time_us" in progress:
        try:
            return int(progress["out_time_us"]) / 1_000_000.0
        except ValueError:
            pass
    if "out_time" in progress:
        t = progress["out_time"].strip()
        parts = t.split(':')
        if len(parts) == 3:
            try:
                h = int(parts[0]); m = int(parts[1]); s = float(parts[2])
                return h*3600 + m*60 + s
            except ValueError:
                return None
    return None

# --- Progress server (decouple from stdout/stderr) ---

class _ProgressHandler(socketserver.StreamRequestHandler):
    def handle(self):
        server = self.server  # type: ignore[attr-defined]
        try:
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                try:
                    text = line.decode('utf-8', 'ignore').strip()
                except AttributeError:
                    text = str(line).strip()
                if not text or '=' not in text:
                    continue
                k, v = text.split('=', 1)
                with server.lock:  # type: ignore[attr-defined]
                    server.progress[k] = v
                    server.last_update = time.time()
        finally:
            with server.lock:  # type: ignore[attr-defined]
                server.closed = True  # type: ignore[attr-defined]

class ProgressTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    def __init__(self):
        super().__init__(('127.0.0.1', 0), _ProgressHandler, bind_and_activate=True)
        self.progress: Dict[str, str] = {}
        self.last_update: float = 0.0
        self.closed: bool = False
        self.lock = threading.Lock()
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
    @property
    def url(self) -> str:
        host, port = self.server_address
        return f"tcp://{host}:{port}"
    def snapshot(self) -> Tuple[Dict[str, str], float, bool]:
        with self.lock:
            return dict(self.progress), self.last_update, self.closed
    def close(self):
        try:
            self.shutdown()
        finally:
            self.server_close()

# --- Child process cleanup ---

def _terminate_proc_tree(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except PermissionError:
                proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass

# --- Core classes ---

class VideoInfo:
    def __init__(self, path: pathlib.Path):
        self.path: pathlib.Path = path
        self.size: int = 0
        self.duration: float = 0.0
        self.bitrate: int = 0
        self.video_bitrate: int = 0
        self.audio_bitrate: int = 0
        self.resolution: Tuple[int, int] = (0, 0)
        self.codec_name: str = "N/A"
        self.error: Optional[str] = None
    @property
    def resolution_str(self) -> str:
        return f"{self.resolution[0]}x{self.resolution[1]}" if self.resolution[0] > 0 else "N/A"
    @staticmethod
    def get_video_info(video_path: pathlib.Path) -> "VideoInfo":
        info = VideoInfo(video_path)
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_format", "-show_streams", str(video_path)]
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                encoding='utf-8', errors='ignore'
            )
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            info.size = int(fmt.get("size", 0))
            info.duration = float(fmt.get("duration", 0.0))
            info.bitrate = int(fmt.get("bit_rate", 0))
            vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
            astream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
            if vstream:
                info.resolution = (vstream.get("width", 0), vstream.get("height", 0))
                info.video_bitrate = int(vstream.get("bit_rate", 0))
                info.codec_name = vstream.get("codec_name", "N/A")
            if astream:
                info.audio_bitrate = int(astream.get("bit_rate", 0))
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            info.error = str(e)
        return info

class VideoFinder:
    @staticmethod
    def find(paths: List[pathlib.Path], recursive: bool) -> Iterable[pathlib.Path]:
        for path in paths:
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                yield path
            elif path.is_dir():
                pat = "**/*" if recursive else "*"
                for item in path.glob(pat):
                    if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                        yield item

# --- Stats command ---

def run_stats_command(args: argparse.Namespace):
    print("Searching for videos...")
    video_paths = list(VideoFinder.find(args.input, args.recursive))
    if not video_paths:
        print("No video files found.")
        return
    print(f"Found {len(video_paths)} videos. Analyzing metadata...")
    with concurrent.futures.ThreadPoolExecutor() as ex:
        futures = [ex.submit(VideoInfo.get_video_info, p) for p in video_paths]
        videos = [f.result() for f in concurrent.futures.as_completed(futures)]
    videos = [v for v in videos if not v.error]
    sort_key = {
        "size": lambda v: v.size,
        "bitrate": lambda v: v.bitrate,
        "duration": lambda v: v.duration,
        "resolution": lambda v: v.resolution[0] * v.resolution[1],
    }.get(args.sort_by, lambda v: v.size)
    videos.sort(key=sort_key, reverse=True)
    if args.top:
        videos = videos[:args.top]
    try:
        terminal_width, _ = os.get_terminal_size()
    except OSError:
        terminal_width = 80
    print("\n--- Video Statistics ---")
    if terminal_width >= COMPACT_OUTPUT_THRESHOLD:
        headers = ["Filename", "Size", "Duration", "Resolution", "Codec", "Total Bitrate", "Video Bitrate", "Audio Bitrate"]
        print(f"{headers[0]:<40} {headers[1]:>10} {headers[2]:>10} {headers[3]:>12} {headers[4]:>8} {headers[5]:>15} {headers[6]:>15} {headers[7]:>15}")
        print("-" * 140)
        for v in videos:
            fname = clip_ellipsis(v.path.name, 38)
            size = format_bytes(bytes_to_mib(v.size))
            duration = fmt_hms(v.duration)
            res = v.resolution_str
            codec = v.codec_name
            br = f"{v.bitrate / 1000:.0f} kbps" if v.bitrate else "N/A"
            vbr = f"{v.video_bitrate / 1000:.0f} kbps" if v.video_bitrate else "N/A"
            abr = f"{v.audio_bitrate / 1000:.0f} kbps" if v.audio_bitrate else "N/A"
            print(f"{fname:<40} {size:>10} {duration:>10} {res:>12} {codec:>8} {br:>15} {vbr:>15} {abr:>15}")
    else:
        for v in videos:
            fname = clip_ellipsis(v.path.name, terminal_width - 2)
            size = format_bytes(bytes_to_mib(v.size))
            duration = fmt_hms(v.duration)
            res = v.resolution_str
            codec = v.codec_name
            br = f"{v.bitrate / 1000:.0f}k" if v.bitrate else "N/A"
            vbr = f"{v.video_bitrate / 1000:.0f}k" if v.video_bitrate else "N/A"
            abr = f"{v.audio_bitrate / 1000:.0f}k" if v.audio_bitrate else "N/A"
            print(f"{fname}")
            print(f"  Size: {size:<12} | Res: {res:<12} | Dur: {duration:<10} | Codec: {codec}")
            print(f"  Bitrates (T/V/A): {br} / {vbr} / {abr}")
            print("-" * terminal_width)

# --- Encoding argument generation ---

def _map_preset_for_encoder(encoder: str, preset: str) -> List[str]:
    """Normalize preset flag for libx* vs NVENC."""
    if 'nvenc' in encoder:
        # map common names to NVENC p-levels
        mapping = {
            'ultrafast': 'p1', 'superfast': 'p2', 'veryfast': 'p3',
            'faster': 'p4', 'fast': 'p4', 'medium': 'p5',
            'slow': 'p6', 'slower': 'p7', 'veryslow': 'p7'
        }
        p = preset.lower()
        if not p.startswith('p'):
            preset = mapping.get(p, 'p5')
        return ["-preset", preset]
    else:
        # libx264/libx265 use named presets
        return ["-preset", preset]

def generate_ffmpeg_args(video: VideoInfo, args: argparse.Namespace) -> List[str]:
    ffmpeg_args = []
    ffmpeg_args.extend(["-c:v", args.video_encoder, *_map_preset_for_encoder(args.video_encoder, args.preset)])
    if args.crf is not None:
        ffmpeg_args.extend(["-crf", str(args.crf)])
    elif args.cq is not None:
        ffmpeg_args.extend(["-rc", "vbr", "-cq", str(args.cq)])
    elif args.video_bitrate:
        ffmpeg_args.extend(["-b:v", args.video_bitrate])
    if args.audio_bitrate:
        ffmpeg_args.extend(["-c:a", "aac", "-b:a", args.audio_bitrate])
    else:
        ffmpeg_args.extend(["-c:a", "copy"])
    if args.resolution:
        tw, th = args.resolution
        sw, sh = video.resolution
        if sw > tw or sh > th:
            ffmpeg_args.extend([
                "-vf",
                f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2"
            ])
    # Better MP4 playability by default
    if (video.path.suffix.lower() == ".mp4") or True:
        ffmpeg_args.extend(["-movflags", "+faststart"])
    return ffmpeg_args

# --- stderr logging thread ---

def _stderr_logger_thread(pipe: Optional[IO[str]], dashboard: TermDash, file_label: str,
                          file_handle: Optional[IO[str]], logger: logging.Logger):
    try:
        if not pipe:
            return
        for line in iter(pipe.readline, ''):
            txt = line.rstrip("\n")
            if txt:
                dashboard.log(f"[{file_label}] {txt}", level='warning')
                if file_handle:
                    try:
                        file_handle.write(txt + "\n")
                        file_handle.flush()
                    except Exception:
                        pass
                logger.debug("[%s stderr] %s", file_label, txt)
    except Exception as e:
        logger.debug("[%s stderr-thread] exception: %s", file_label, e)
    finally:
        try:
            if pipe:
                pipe.close()
        except Exception:
            pass
        if file_handle:
            try:
                file_handle.flush()
                file_handle.close()
            except Exception:
                pass

# --- Worker ---

def process_video_worker(
    video: VideoInfo, output_path: pathlib.Path, ffmpeg_args: List[str],
    dashboard: TermDash, line_name: str, shared_state: Dict[str, Any]
):
    logger: logging.Logger = shared_state["logger"]
    ffmpeg_log_dir: pathlib.Path = shared_state["ffmpeg_log_dir"]
    relax_input: bool = shared_state["relax_input"]
    enable_ffreport: bool = shared_state["ffreport"]
    aliases: Dict[str, List[str]] = shared_state.get("line_aliases", {})

    def dash_update(stat: str, value: Any):
        targets = aliases.get(line_name, [line_name])
        for ln in targets:
            dashboard.update_stat(ln, stat, value)

    def dash_reset(stat: str, grace: int = 1):
        targets = aliases.get(line_name, [line_name])
        for ln in targets:
            dashboard.reset_stat(ln, stat, grace_period_s=grace)

    dash_update("file", video.path.name)
    dash_update("status", "Processing")

    # progress server
    progress_srv = ProgressTCPServer()

    # optional tolerant input flags (handy for noisy H.264 streams)
    input_opts: List[str] = []
    if relax_input:
        input_opts = [
            "-probesize", "100M",
            "-analyzeduration", "100M",
            "-err_detect", "ignore_err",
            "-fflags", "+discardcorrupt", "-fflags", "+genpts"
        ]

    command = [
        "ffmpeg", "-y", "-hide_banner",
        "-nostats", "-stats_period", "0.5",
        *input_opts,
        "-i", str(video.path),
        *ffmpeg_args,
        "-progress", progress_srv.url,
        str(output_path)
    ]

    # per-file log
    safe_stem = re.sub(r"[^\w\-.]+", "_", video.path.stem)[:80]
    perfile_log = ffmpeg_log_dir / f"{line_name}-{safe_stem}.ffmpeg.log"
    perfile_log.parent.mkdir(parents=True, exist_ok=True)
    perfile_fh: Optional[IO[str]] = None
    try:
        perfile_fh = open(perfile_log, "a", encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning("Could not open per-file log %s: %s", perfile_log, e)

    # process group for cleanup
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    preexec_fn = None if os.name == 'nt' else os.setsid

    # environment (optional FFREPORT)
    env = os.environ.copy()
    if enable_ffreport:
        ffreport_path = perfile_log.with_suffix(".ffreport")
        if os.name == 'nt':
            # Quote & POSIXify so ':' in 'C:/' doesn't break parsing
            env["FFREPORT"] = f"file='{ffreport_path.as_posix()}':level=32"
        else:
            env["FFREPORT"] = f"file={ffreport_path}:level=32"

    cmdline = subprocess.list2cmdline(command)
    logger.info("Worker %s starting: %s", line_name, cmdline)
    if perfile_fh:
        try: perfile_fh.write(f"# COMMAND: {cmdline}\n"); perfile_fh.flush()
        except Exception: pass

    proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        encoding='utf-8',
        errors='ignore',
        creationflags=creationflags,
        preexec_fn=preexec_fn,
        env=env
    )
    atexit.register(_terminate_proc_tree, proc)

    t_stderr = threading.Thread(
        target=_stderr_logger_thread,
        args=(proc.stderr, dashboard, video.path.name, perfile_fh, logger),
        daemon=True
    )
    t_stderr.start()

    speed_deque = deque(maxlen=10)
    last_dash_update = 0.0
    last_debug_log = 0.0
    start_wall = time.time()

    # Register inflight stats
    with shared_state["lock"]:
        shared_state["inflight_meta"][line_name] = {"src_size": video.size}
        shared_state["inflight_written"][line_name] = 0
        shared_state["inflight_ratio"][line_name] = 0.0

    try:
        while proc.poll() is None:
            prog, _, _ = progress_srv.snapshot()
            try:
                written = int(prog.get("total_size", "0"))
            except ValueError:
                written = 0

            t_sec = _parse_out_time_seconds(prog)
            ratio = 0.0
            if t_sec is not None and video.duration > 0:
                ratio = max(0.0, min(1.0, t_sec / video.duration))

            spd_raw = (prog.get("speed") or "").lower().strip().replace("x", "")
            try:
                spd_val = float(spd_raw) if spd_raw not in ("", "nan", "inf") else 0.0
            except ValueError:
                spd_val = 0.0
            if spd_val > 0:
                speed_deque.append(spd_val)
            avg_speed = sum(speed_deque) / len(speed_deque) if speed_deque else 0.0

            eta_s = None
            if avg_speed > 0 and t_sec is not None and video.duration > 0:
                remain = max(0.0, video.duration - t_sec)
                eta_s = remain / max(1e-6, avg_speed)

            now = time.time()
            if (now - last_dash_update) >= 0.5:
                percent = ratio * 100.0
                filled = int(percent / 100 * BAR_WIDTH)
                bar = '█' * filled + '░' * (BAR_WIDTH - filled)
                dash_update("progress", percent)
                dash_update("bar", bar)
                dash_update("speed", avg_speed)
                dash_update("eta", fmt_hms(eta_s))
                dash_update("written", format_bytes(bytes_to_mib(written)))
                dash_update("elapsed", fmt_hms(now - start_wall))
                last_dash_update = now
                with shared_state["lock"]:
                    shared_state["inflight_written"][line_name] = written
                    shared_state["inflight_ratio"][line_name] = ratio

            if (now - last_debug_log) >= 2.0:
                logger.debug(
                    "Worker %s progress: t=%.2fs ratio=%.3f written=%d speed=%.3fx eta=%s",
                    line_name, (t_sec or 0.0), ratio, written, avg_speed, fmt_hms(eta_s)
                )
                last_debug_log = now

            time.sleep(0.05)

        t_stderr.join(timeout=1.0)

    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            _terminate_proc_tree(proc)
        try:
            progress_srv.close()
        except Exception:
            pass
        with shared_state["lock"]:
            shared_state["inflight_written"].pop(line_name, None)
            shared_state["inflight_ratio"].pop(line_name, None)
            meta = shared_state["inflight_meta"].pop(line_name, {"src_size": 0})

    if proc.returncode == 0 and output_path.exists():
        dash_update("status", "Done")
        dash_update("progress", 100.0)
        dash_update("bar", '█' * BAR_WIDTH)
        if shared_state.get("preserve_timestamps"):
            try:
                st = video.path.stat()
                os.utime(output_path, (st.st_atime, st.st_mtime))
            except Exception as e:
                dashboard.log(f"[{video.path.name}] timestamp copy failed: {e}", level='warning')
                logger.warning("[%s] timestamp copy failed: %s", video.path.name, e)
        final_size = output_path.stat().st_size
        with shared_state["lock"]:
            shared_state["processed_count"] += 1
            shared_state["bytes_processed"] += meta.get("src_size", 0)
            shared_state["total_output_size"] += final_size
        logger.info("Worker %s finished OK. Output: %s (%d bytes)", line_name, output_path, final_size)
    else:
        dash_update("status", "Failed")
        dashboard.log(f"ERROR: ffmpeg failed for {video.path.name} (code: {proc.returncode})", level='error')
        logger.error("Worker %s FAILED (code=%s). Output: %s", line_name, proc.returncode, output_path)

    time.sleep(1)
    dash_reset("file", grace=1)
    dash_reset("status", grace=1)

# --- Process command ---

def run_process_command(args: argparse.Namespace):
    if any(args.output_dir.suffix.lower() == ext for ext in VIDEO_EXTENSIONS):
        print(f"Error: The output path '-o' must be a directory, not a file.", file=sys.stderr)
        print(f"You provided: {args.output_dir}", file=sys.stderr)
        sys.exit(1)

    # Logging setup
    logger = setup_logging(args.log_file, args.log_level)
    _log_versions(logger)
    logger.info("Args: %s", vars(args))

    print("Searching for videos...")
    video_paths = list(VideoFinder.find(args.input, args.recursive))
    if not video_paths:
        print("No video files found.")
        logger.info("No videos found in inputs: %s", args.input)
        return

    print(f"Found {len(video_paths)} videos. Analyzing metadata...")
    with concurrent.futures.ThreadPoolExecutor() as ex:
        futures = [ex.submit(VideoInfo.get_video_info, p) for p in video_paths]
        videos = [f.result() for f in concurrent.futures.as_completed(futures)]
    videos = [v for v in videos if not v.error]

    # Filtering
    initial_count = len(videos)
    if args.min_size: videos = [v for v in videos if v.size >= args.min_size]
    if args.max_size: videos = [v for v in videos if v.size <= args.max_size]
    if args.min_bitrate: videos = [v for v in videos if v.bitrate >= args.min_bitrate]
    if args.max_bitrate: videos = [v for v in videos if v.bitrate <= args.max_bitrate]
    if args.min_resolution:
        mw, mh = args.min_resolution
        videos = [v for v in videos if v.resolution[0] >= mw and v.resolution[1] >= mh]
    if args.max_resolution:
        Mw, Mh = args.max_resolution
        videos = [v for v in videos if v.resolution[0] <= Mw and v.resolution[1] <= Mh]
    if not videos:
        print(f"All {initial_count} videos were filtered out. Nothing to process.")
        logger.info("All %d videos filtered out by constraints.", initial_count)
        return

    print(f"Filtered down to {len(videos)} videos to process.")
    total_process_size = sum(v.size for v in videos)

    output_dir = args.output_dir
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("\n--- DRY RUN MODE ---")
        print(f"{len(videos)} videos would be processed based on current filters.")
        for video in videos:
            output_path = output_dir / video.path.name
            ffmpeg_args = generate_ffmpeg_args(video, args)
            cmd = ["ffmpeg", "-i", str(video.path), *ffmpeg_args, str(output_path)]
            cmdline = subprocess.list2cmdline(cmd)
            print(f"\n[PROCESS] {video.path}")
            print(f"  -> Size: {format_bytes(bytes_to_mib(video.size))}, Res: {video.resolution_str}, Codec: {video.codec_name}")
            print(f"  -> Output: {output_path}")
            print(f"  -> Command: {cmdline}")
            logger.info("[DRY RUN] %s -> %s", video.path, output_path)
            logger.info("[DRY RUN] Command: %s", cmdline)
        return

    # Shared state for workers + UI
    # Share the exact log path with TermDash to avoid multiple files.
    logger_file = None
    for h in logger.handlers:
        if hasattr(h, "baseFilename"):
            logger_file = getattr(h, "baseFilename")
            break

    # detect terminal width to select compact/stacked UI
    try:
        term_width, _ = os.get_terminal_size()
    except OSError:
        term_width = 80
    stacked_ui = term_width < DASH_COMPACT_THRESHOLD

    visible_workers = max(1, min(args.threads, len(videos)))
    ffmpeg_log_dir = pathlib.Path(args.ffmpeg_log_dir) if args.ffmpeg_log_dir else (pathlib.Path(logger_file).parent if logger_file else _default_log_file().parent) / "ffmpeg"

    shared_state = {
        "lock": threading.Lock(),
        "processed_count": 0,
        "bytes_processed": 0,
        "total_output_size": 0,
        "start_time": time.time(),
        "preserve_timestamps": args.preserve_timestamps,
        "inflight_written": {},
        "inflight_ratio": {},
        "inflight_meta": {},
        "ffmpeg_log_dir": ffmpeg_log_dir,
        "relax_input": args.relax_input,
        "ffreport": args.ffreport,
        "logger": logger,
        "line_aliases": {},  # main line -> [main, aux] in stacked mode
    }

    with TermDash(log_file=str(logger_file or _default_log_file()), align_columns=True) as dash:
        if not stacked_ui:
            # One header, one line per worker
            dash.add_line("header", Line("header", [
                Stat("Worker", "Worker", no_expand=True, display_width=8),
                Stat("File", "File", no_expand=True, display_width=35),
                Stat("Status", "Status", no_expand=True, display_width=10),
                Stat("Progress Bar", "Progress", no_expand=True, display_width=BAR_WIDTH + 2),
                Stat("Progress %", "%", no_expand=True, display_width=6),
                Stat("Speed", "Speed", no_expand=True, display_width=10),
                Stat("ETA", "ETA", no_expand=True, display_width=10),
                Stat("Written", "Written", no_expand=True, display_width=10),
                Stat("Elapsed", "Elapsed", no_expand=True, display_width=10),
            ], style='header'))

            for i in range(visible_workers):
                line_name = f"worker_{i}"
                dash.add_line(line_name, Line(line_name, [
                    Stat("worker_id", f"#{i+1}", no_expand=True, display_width=8),
                    Stat("file", "Idle", format_string="{}", no_expand=True, display_width=35),
                    Stat("status", "-", no_expand=True, display_width=10),
                    Stat("bar", " " * BAR_WIDTH, format_string="[{}]", no_expand=True, display_width=BAR_WIDTH + 2),
                    Stat("progress", 0.0, format_string="{:5.1f}", unit="%", no_expand=True, display_width=6),
                    Stat("speed", 0.0, format_string="{:.2f}x", no_expand=True, display_width=10),
                    Stat("eta", "--:--:--", format_string="{}", no_expand=True, display_width=10),
                    Stat("written", "0.00 MiB", format_string="{}", no_expand=True, display_width=10),
                    Stat("elapsed", "00:00:00", format_string="{}", no_expand=True, display_width=10),
                ]))
        else:
            # Stacked headers and two rows per worker
            dash.add_line("header_top", Line("header_top", [
                Stat("Worker", "Worker", no_expand=True, display_width=6),
                Stat("File", "File", no_expand=True, display_width=40),
                Stat("Status", "Status", no_expand=True, display_width=10),
            ], style='header'))
            dash.add_line("header_bottom", Line("header_bottom", [
                Stat("Progress Bar", "Progress", no_expand=True, display_width=BAR_WIDTH + 2),
                Stat("Progress %", "%", no_expand=True, display_width=6),
                Stat("Speed", "Speed", no_expand=True, display_width=8),
                Stat("ETA", "ETA", no_expand=True, display_width=9),
                Stat("Written", "Written", no_expand=True, display_width=12),
                Stat("Elapsed", "Elapsed", no_expand=True, display_width=10),
            ], style='header'))

            for i in range(visible_workers):
                main = f"worker_{i}"
                aux = f"worker_{i}_2"
                # top row
                dash.add_line(main, Line(main, [
                    Stat("worker_id", f"#{i+1}", no_expand=True, display_width=6),
                    Stat("file", "Idle", format_string="{}", no_expand=True, display_width=40),
                    Stat("status", "-", no_expand=True, display_width=10),
                ]))
                # bottom row (metrics)
                dash.add_line(aux, Line(aux, [
                    Stat("bar", " " * BAR_WIDTH, format_string="[{}]", no_expand=True, display_width=BAR_WIDTH + 2),
                    Stat("progress", 0.0, format_string="{:5.1f}", unit="%", no_expand=True, display_width=6),
                    Stat("speed", 0.0, format_string="{:.2f}x", no_expand=True, display_width=8),
                    Stat("eta", "--:--:--", format_string="{}", no_expand=True, display_width=9),
                    Stat("written", "0.00 MiB", format_string="{}", no_expand=True, display_width=12),
                    Stat("elapsed", "00:00:00", format_string="{}", no_expand=True, display_width=10),
                ]))
                shared_state["line_aliases"][main] = [main, aux]

        dash.add_separator()
        dash.add_line("total", Line("total", [
            Stat("total_files", (0, len(videos)), format_string="{}/{}", unit=" Videos"),
            Stat("total_size", (format_bytes(0), format_bytes(bytes_to_mib(total_process_size))), format_string="{} / {}"),
            Stat("elapsed", "00:00:00", format_string="Elapsed: {}"),
            Stat("total_eta", "--:--:--", format_string="Total ETA: {}"),
        ]))

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = [executor.submit(
                process_video_worker,
                video,
                output_dir / video.path.name,
                generate_ffmpeg_args(video, args),
                dash,
                f"worker_{i % visible_workers}",
                shared_state
            ) for i, video in enumerate(videos)]

            # Keep updating until all jobs have completed
            while True:
                if all(f.done() for f in futures):
                    break

                with shared_state["lock"]:
                    finished_src = shared_state["bytes_processed"]
                    inflight_ratio = dict(shared_state["inflight_ratio"])
                    inflight_meta = dict(shared_state["inflight_meta"])

                est_inflight_src = 0
                for line, ratio in inflight_ratio.items():
                    src_size = inflight_meta.get(line, {}).get("src_size", 0)
                    est_inflight_src += int(src_size * max(0.0, min(1.0, ratio)))

                bytes_done_est = finished_src + est_inflight_src
                elapsed = time.time() - shared_state["start_time"]
                bps = bytes_done_est / elapsed if elapsed > 0 else 0
                total_eta_s = (total_process_size - bytes_done_est) / bps if bps > 0 else None

                dash.update_stat("total", "total_files", (shared_state["processed_count"], len(videos)))
                dash.update_stat("total", "total_size",
                                 (format_bytes(bytes_to_mib(bytes_done_est)),
                                  format_bytes(bytes_to_mib(total_process_size))))
                dash.update_stat("total", "elapsed", fmt_hms(elapsed))
                dash.update_stat("total", "total_eta", fmt_hms(total_eta_s))
                time.sleep(0.5)

            # propagate exceptions if any
            for f in futures:
                f.result()

        dash.update_stat("total", "total_files", (shared_state["processed_count"], len(videos)))
        dash.update_stat("total", "elapsed", fmt_hms(time.time() - shared_state["start_time"]))
        dash.update_stat("total", "total_eta", "Done")
        dash.log("All processing complete.")
        time.sleep(1.0)

    print("\n--- Processing Complete ---")
    original_size = shared_state["bytes_processed"]
    new_size = shared_state["total_output_size"]
    space_saved = original_size - new_size
    reduction = (space_saved / original_size * 100) if original_size > 0 else 0
    print(f"Successfully processed {shared_state['processed_count']} out of {len(videos)} targeted videos.")
    print(f"Total original size: {format_bytes(bytes_to_mib(original_size))}")
    print(f"Total new size:      {format_bytes(bytes_to_mib(new_size))}")
    print(f"Total space saved:   {format_bytes(bytes_to_mib(space_saved))} ({reduction:.1f}% reduction)")

# --- Arg parsing / main ---

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A multi-threaded video processing and analysis tool.", formatter_class=argparse.RawTextHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    parser_stats = subparsers.add_parser("stats", help="Analyze and display video statistics.")
    parser_stats.add_argument("-i", "--input", type=pathlib.Path, required=True, nargs='+', help="One or more input files or directories.")
    parser_stats.add_argument("-r", "--recursive", action="store_true", help="Recursively search for videos in subdirectories.")
    parser_stats.add_argument("-n", "--top", type=int, help="Display stats for the top N videos.")
    parser_stats.add_argument("-s", "--sort-by", choices=["size", "bitrate", "duration", "resolution"], default="size", help="Sort videos by the specified attribute.")
    parser_stats.set_defaults(func=run_stats_command)

    parser_process = subparsers.add_parser("process", help="Re-encode videos based on specified criteria.")
    parser_process.add_argument("-i", "--input", type=pathlib.Path, required=True, nargs='+', help="One or more input files or directories.")
    parser_process.add_argument("-o", "--output-dir", type=pathlib.Path, required=True, help="Directory to save processed videos.")
    parser_process.add_argument("-r", "--recursive", action="store_true", help="Recursively search for videos in subdirectories.")
    parser_process.add_argument("-t", "--threads", type=int, default=os.cpu_count() or 1, help="Number of concurrent processing threads.")

    group_encode = parser_process.add_argument_group("Re-encoding Options")
    group_encode.add_argument("-ve", "--video-encoder", choices=["libx264", "libx265", "h264_nvenc", "hevc_nvenc"], default="libx264", help="Video encoder. 'libx...' are software (CPU). '..._nvenc' are NVIDIA hardware (GPU).")
    group_encode.add_argument("--preset", type=str, default="medium", help="FFmpeg preset. For libx*: ultrafast..veryslow. For NVENC: p1-p7 (p5 is a good default).")
    group_encode.add_argument("-res", "--resolution", type=parse_resolution, help="Target resolution (e.g., '1280x720'). Videos will not be upscaled.")
    group_encode.add_argument("-ab", "--audio-bitrate", type=str, help="Target audio bitrate (e.g., '128k'). If omitted, audio is copied.")

    quality_group = group_encode.add_mutually_exclusive_group()
    quality_group.add_argument("--crf", type=int, help="Constant Rate Factor for libx264/libx265 (quality-based). Lower is better. Recommended: 18-28.")
    quality_group.add_argument("--cq", type=int, help="Constant Quality for NVENC encoders (quality-based). Lower is better. Recommended: 19-25.")
    quality_group.add_argument("-vb", "--video-bitrate", type=str, help="Target video bitrate (e.g., '2M', '2000k'). Quality-based modes are recommended.")

    group_filter = parser_process.add_argument_group("Filtering Options (process only if)")
    group_filter.add_argument("--min-size", type=parse_size, help="Minimum file size to process (e.g., '500M', '1G').")
    group_filter.add_argument("--max-size", type=parse_size, help="Maximum file size to process.")
    group_filter.add_argument("--min-bitrate", type=parse_bitrate, help="Minimum total bitrate to process (e.g., '3M').")
    group_filter.add_argument("--max-bitrate", type=parse_bitrate, help="Maximum total bitrate to process.")
    group_filter.add_argument("--min-resolution", type=parse_resolution, help="Minimum resolution to process (e.g., '1920x1080').")
    group_filter.add_argument("--max-resolution", type=parse_resolution, help="Maximum resolution to process.")

    group_workflow = parser_process.add_argument_group("Workflow & Logging")
    group_workflow.add_argument("--dry-run", action="store_true", help="Show what would be processed without running ffmpeg.")
    group_workflow.add_argument("--preserve-timestamps", action="store_true", help="Copy modification timestamp from source to destination file.")
    group_workflow.add_argument("--log-file", type=pathlib.Path, help="Path to global log file (rotating). Defaults to ./logs/video_processor-<timestamp>.log")
    group_workflow.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Global log level.")
    group_workflow.add_argument("--ffmpeg-log-dir", type=pathlib.Path, help="Directory for per-file ffmpeg logs. Defaults to <log dir>/ffmpeg")
    group_workflow.add_argument("--relax-input", action="store_true", help="Try to continue on corrupt input (adds large probe/analyze + ignore_err, discardcorrupt, genpts).")
    group_workflow.add_argument("--ffreport", dest="ffreport", action="store_true", default=True, help="Enable FFREPORT per-file logs (default: on).")
    group_workflow.add_argument("--no-ffreport", dest="ffreport", action="store_false", help="Disable FFREPORT per-file logs.")

    parser_process.set_defaults(func=run_process_command)
    return parser

def main():
    check_dependencies()
    parser = create_parser()
    args = parser.parse_args()

    if getattr(args, 'func', None) is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "process":
        is_nvenc = 'nvenc' in args.video_encoder
        if args.crf is not None and is_nvenc:
            parser.error("argument --crf: can only be used with libx264 or libx265 encoders.")
        if args.cq is not None and not is_nvenc:
            parser.error("argument --cq: can only be used with NVENC encoders (h264_nvenc, hevc_nvenc).")
        if all(arg is None for arg in [args.resolution, args.crf, args.cq, args.video_bitrate, args.audio_bitrate]):
            parser.error("at least one processing option (--resolution, --crf, --cq, --video-bitrate, --audio-bitrate) must be specified.")

    args.func(args)

if __name__ == "__main__":
    main()
