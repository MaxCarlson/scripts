#!/usr/bin/env python3
"""
A multi-threaded video processing and analysis tool with a real-time dashboard.

This script can recursively find videos, analyze their properties, and re-encode
them based on user-defined criteria like resolution, bitrate, and file size,
with support for both CPU (libx264/libx265) and NVIDIA GPU (NVENC) encoding.
"""
import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --- Module Setup ---
# Add the parent directory to sys.path to make the 'modules' directory importable.
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

# --- Helper Functions ---

def parse_size(size_str: str) -> int:
    """Parse size string (e.g., '500M', '2G') into bytes."""
    size_str = size_str.strip().upper()
    if not size_str:
        return 0
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT])?B?$', size_str)
    if not match:
        raise ValueError(f"Invalid size format: '{size_str}'")
    val, unit = match.groups()
    val = float(val)
    multipliers = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
    return int(val * multipliers.get(unit, 1))

def parse_bitrate(bitrate_str: str) -> int:
    """Parse bitrate string (e.g., '2M', '128k') into bits per second."""
    bitrate_str = bitrate_str.strip().lower()
    if not bitrate_str:
        return 0
    val_str = bitrate_str.rstrip('kmg')
    unit = bitrate_str[len(val_str):]
    val = float(val_str)
    multipliers = {'k': 1000, 'm': 1000**2, 'g': 1000**3}
    return int(val * multipliers.get(unit, 1))

def parse_resolution(res_str: str) -> Tuple[int, int]:
    """Parse resolution string 'WIDTHxHEIGHT' into a tuple."""
    res_str = res_str.strip().lower()
    match = re.match(r'^(\d+)[x: ](\d+)$', res_str)
    if not match:
        raise ValueError(f"Invalid resolution format: '{res_str}'. Expected WxH.")
    return int(match.group(1)), int(match.group(2))

def check_dependencies():
    """Check if ffmpeg and ffprobe are in the system's PATH."""
    if not shutil.which("ffmpeg"):
        print("Error: 'ffmpeg' not found. Please install it and ensure it's in your PATH.", file=sys.stderr)
        sys.exit(1)
    if not shutil.which("ffprobe"):
        print("Error: 'ffprobe' not found. Please install it and ensure it's in your PATH.", file=sys.stderr)
        sys.exit(1)

# --- Core Classes ---

class VideoInfo:
    """A data class to hold all metadata about a video file."""
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
        """Run ffprobe to get detailed information about a video file."""
        info = VideoInfo(video_path)
        try:
            command = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(video_path)
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)

            fmt = data.get("format", {})
            info.size = int(fmt.get("size", 0))
            info.duration = float(fmt.get("duration", 0.0))
            info.bitrate = int(fmt.get("bit_rate", 0))

            video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
            audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

            if video_stream:
                info.resolution = (video_stream.get("width", 0), video_stream.get("height", 0))
                info.video_bitrate = int(video_stream.get("bit_rate", 0))
                info.codec_name = video_stream.get("codec_name", "N/A")

            if audio_stream:
                info.audio_bitrate = int(audio_stream.get("bit_rate", 0))

        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            info.error = str(e)
        return info

class VideoFinder:
    """Handles discovery of video files."""
    @staticmethod
    def find(paths: List[pathlib.Path], recursive: bool) -> Iterable[pathlib.Path]:
        for path in paths:
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                yield path
            elif path.is_dir():
                glob_pattern = "**/*" if recursive else "*"
                for item in path.glob(glob_pattern):
                    if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                        yield item

# --- Command Handlers ---

def run_stats_command(args: argparse.Namespace):
    """Execute the 'stats' command."""
    print("Searching for videos...")
    video_paths = list(VideoFinder.find(args.input, args.recursive))
    if not video_paths:
        print("No video files found.")
        return

    print(f"Found {len(video_paths)} videos. Analyzing metadata...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(VideoInfo.get_video_info, path) for path in video_paths]
        videos = [f.result() for f in concurrent.futures.as_completed(futures)]

    videos = [v for v in videos if not v.error]
    sort_key = {
        "size": lambda v: v.size, "bitrate": lambda v: v.bitrate,
        "duration": lambda v: v.duration, "resolution": lambda v: v.resolution[0] * v.resolution[1],
    }.get(args.sort_by, lambda v: v.size)
    videos.sort(key=sort_key, reverse=True)

    if args.top:
        videos = videos[:args.top]

    print("\n--- Video Statistics ---")
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

def generate_ffmpeg_args(video: VideoInfo, args: argparse.Namespace) -> List[str]:
    """Generates the dynamic part of the ffmpeg command."""
    ffmpeg_args = []
    
    # Video stream encoder and preset
    ffmpeg_args.extend(["-c:v", args.video_encoder, "-preset", args.preset])

    # Video quality/bitrate
    if args.crf is not None:
        ffmpeg_args.extend(["-crf", str(args.crf)])
    elif args.cq is not None:
        ffmpeg_args.extend(["-rc", "vbr", "-cq", str(args.cq)])
    elif args.video_bitrate:
        ffmpeg_args.extend(["-b:v", args.video_bitrate])

    # Audio stream
    if args.audio_bitrate:
        ffmpeg_args.extend(["-c:a", "aac", "-b:a", args.audio_bitrate])
    else:
        ffmpeg_args.extend(["-c:a", "copy"])

    # Resolution scaling (no upscale)
    if args.resolution:
        target_w, target_h = args.resolution
        source_w, _ = video.resolution
        if source_w > target_w:
            ffmpeg_args.extend(["-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2"])

    return ffmpeg_args

def process_video_worker(
    video: VideoInfo, output_path: pathlib.Path, ffmpeg_args: List[str],
    dashboard: TermDash, line_name: str, shared_state: Dict[str, Any]
):
    """Worker function to process a single video using ffmpeg."""
    dashboard.update_stat(line_name, "file", video.path.name)
    dashboard.update_stat(line_name, "status", "Processing")

    command = ["ffmpeg", "-y", "-i", str(video.path), *ffmpeg_args, "-progress", "pipe:1", str(output_path)]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)

    progress, last_update_time = {}, time.time()
    speed_deque = deque(maxlen=10)

    for line in proc.stdout:
        try:
            key, value = line.strip().split("=", 1)
            progress[key] = value
        except ValueError:
            continue

        if "out_time_ms" in progress and video.duration > 0:
            processed_ms = int(progress["out_time_ms"])
            percent = (processed_ms / 1_000_000) / video.duration * 100
            
            if (time.time() - last_update_time) > 0.5:
                speed_val = float(progress.get("speed", "0.0x").replace("x", ""))
                speed_deque.append(speed_val)
                avg_speed = sum(speed_deque) / len(speed_deque) if speed_deque else 0.0
                eta_s = (video.duration - (processed_ms / 1_000_000)) / avg_speed if avg_speed > 0 else None
                bar = '█' * int(percent / 100 * BAR_WIDTH) + '░' * (BAR_WIDTH - int(percent / 100 * BAR_WIDTH))
                
                dashboard.update_stat(line_name, "progress", percent)
                dashboard.update_stat(line_name, "bar", bar)
                dashboard.update_stat(line_name, "speed", avg_speed)
                dashboard.update_stat(line_name, "eta", fmt_hms(eta_s))
                last_update_time = time.time()

    proc.wait()
    
    if proc.returncode == 0:
        dashboard.update_stat(line_name, "status", "Done")
        dashboard.update_stat(line_name, "progress", 100.0)
        dashboard.update_stat(line_name, "bar", '█' * BAR_WIDTH)
        final_size = output_path.stat().st_size
        if shared_state.get("preserve_timestamps"):
            source_stat = video.path.stat()
            os.utime(output_path, (source_stat.st_atime, source_stat.st_mtime))
        
        with shared_state["lock"]:
            shared_state["processed_count"] += 1
            shared_state["bytes_processed"] += video.size
            shared_state["total_output_size"] += final_size
    else:
        dashboard.update_stat(line_name, "status", "Failed")
        dashboard.log(f"ERROR: ffmpeg failed for {video.path.name} (code: {proc.returncode})", level='error')
    
    time.sleep(1)
    dashboard.reset_stat(line_name, "file", grace_period_s=1)
    dashboard.reset_stat(line_name, "status", grace_period_s=1)

def run_process_command(args: argparse.Namespace):
    """Execute the 'process' command."""
    print("Searching for videos...")
    video_paths = list(VideoFinder.find(args.input, args.recursive))
    if not video_paths:
        print("No video files found.")
        return

    print(f"Found {len(video_paths)} videos. Analyzing metadata...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(VideoInfo.get_video_info, path) for path in video_paths]
        videos = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    videos = [v for v in videos if not v.error]

    # Filter videos
    initial_count = len(videos)
    if args.min_size: videos = [v for v in videos if v.size >= args.min_size]
    if args.max_size: videos = [v for v in videos if v.size <= args.max_size]
    if args.min_bitrate: videos = [v for v in videos if v.bitrate >= args.min_bitrate]
    if args.max_bitrate: videos = [v for v in videos if v.bitrate <= args.max_bitrate]
    if args.min_resolution:
        min_w, min_h = args.min_resolution
        videos = [v for v in videos if v.resolution[0] >= min_w and v.resolution[1] >= min_h]
    if args.max_resolution:
        max_w, max_h = args.max_resolution
        videos = [v for v in videos if v.resolution[0] <= max_w and v.resolution[1] <= max_h]

    if not videos:
        print(f"All {initial_count} videos were filtered out. Nothing to process.")
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
            command = ["ffmpeg", "-i", str(video.path), *ffmpeg_args, str(output_path)]
            print(f"\n[PROCESS] {video.path}")
            print(f"  -> Size: {format_bytes(bytes_to_mib(video.size))}, Res: {video.resolution_str}, Codec: {video.codec_name}")
            print(f"  -> Output: {output_path}")
            print(f"  -> Command: {subprocess.list2cmdline(command)}")
        return

    shared_state = {
        "lock": threading.Lock(), "processed_count": 0, "bytes_processed": 0,
        "total_output_size": 0, "start_time": time.time(),
        "preserve_timestamps": args.preserve_timestamps,
    }
    
    with TermDash(log_file="video_processor.log", align_columns=True) as dash:
        dash.add_line("header", Line("header", [
            Stat("Worker", "Worker", no_expand=True, display_width=8),
            Stat("File", "File", no_expand=True, display_width=35),
            Stat("Status", "Status", no_expand=True, display_width=10),
            Stat("Progress Bar", "Progress", no_expand=True, display_width=BAR_WIDTH + 2),
            Stat("Progress %", "%", no_expand=True, display_width=6),
            Stat("Speed", "Speed", no_expand=True, display_width=10),
            Stat("ETA", "ETA", no_expand=True, display_width=10),
        ], style='header'))
        
        for i in range(args.threads):
            line_name = f"worker_{i}"
            dash.add_line(line_name, Line(line_name, [
                Stat("worker_id", f"#{i+1}", no_expand=True, display_width=8),
                Stat("file", "Idle", format_string="{}", no_expand=True, display_width=35),
                Stat("status", "-", no_expand=True, display_width=10),
                Stat("bar", " " * BAR_WIDTH, format_string="[{}]", no_expand=True, display_width=BAR_WIDTH + 2),
                Stat("progress", 0.0, format_string="{:5.1f}", unit="%", no_expand=True, display_width=6),
                Stat("speed", 0.0, format_string="{:.2f}x", no_expand=True, display_width=10),
                Stat("eta", "--:--:--", format_string="{}", no_expand=True, display_width=10),
            ]))
        
        dash.add_separator()
        dash.add_line("total", Line("total", [
            Stat("total_files", (0, len(videos)), format_string="{}/{}", unit=" Videos"),
            Stat("total_size", (format_bytes(0), format_bytes(bytes_to_mib(total_process_size))), format_string="{} / {}"),
            Stat("elapsed", "00:00:00", format_string="Elapsed: {}"),
            Stat("total_eta", "--:--:--", format_string="Total ETA: {}"),
        ]))

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = [executor.submit(
                process_video_worker, video, output_dir / video.path.name,
                generate_ffmpeg_args(video, args), dash, f"worker_{i % args.threads}", shared_state
            ) for i, video in enumerate(videos)]
            
            while any(f.running() for f in futures):
                with shared_state["lock"]:
                    bytes_done = shared_state["bytes_processed"]
                elapsed = time.time() - shared_state["start_time"]
                bytes_per_sec = bytes_done / elapsed if elapsed > 0 else 0
                total_eta_s = (total_process_size - bytes_done) / bytes_per_sec if bytes_per_sec > 0 else None
                dash.update_stat("total", "total_files", (shared_state["processed_count"], len(videos)))
                dash.update_stat("total", "total_size", (format_bytes(bytes_to_mib(bytes_done)), format_bytes(bytes_to_mib(total_process_size))))
                dash.update_stat("total", "elapsed", fmt_hms(elapsed))
                dash.update_stat("total", "total_eta", fmt_hms(total_eta_s))
                time.sleep(1)
        
        dash.update_stat("total", "total_files", (shared_state["processed_count"], len(videos)))
        dash.update_stat("total", "elapsed", fmt_hms(time.time() - shared_state["start_time"]))
        dash.update_stat("total", "total_eta", "Done")
        dash.log("All processing complete.")
        time.sleep(2)
    
    print("\n--- Processing Complete ---")
    original_size = shared_state["bytes_processed"]
    new_size = shared_state["total_output_size"]
    space_saved = original_size - new_size
    reduction = (space_saved / original_size * 100) if original_size > 0 else 0
    print(f"Successfully processed {shared_state['processed_count']} out of {len(videos)} targeted videos.")
    print(f"Total original size: {format_bytes(bytes_to_mib(original_size))}")
    print(f"Total new size:      {format_bytes(bytes_to_mib(new_size))}")
    print(f"Total space saved:   {format_bytes(bytes_to_mib(space_saved))} ({reduction:.1f}% reduction)")

# --- Main Execution ---

def main():
    check_dependencies()
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
    group_encode.add_argument("--preset", type=str, default="medium", help="FFmpeg preset. For libx*: ultrafast, medium, slow. For NVENC: p1-p7 (p5 is a good default).")
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

    group_workflow = parser_process.add_argument_group("Workflow Options")
    group_workflow.add_argument("--dry-run", action="store_true", help="Show what would be processed without running ffmpeg.")
    group_workflow.add_argument("--preserve-timestamps", action="store_true", help="Copy modification timestamp from source to destination file.")
    parser_process.set_defaults(func=run_process_command)

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
        if args.resolution is None and args.crf is None and args.cq is None and args.video_bitrate is None and args.audio_bitrate is None:
            parser.error("at least one processing option (--resolution, --crf, --cq, --video-bitrate, --audio-bitrate) must be specified.")

    args.func(args)

if __name__ == "__main__":
    main()
