#!/usr/bin/env python3
import argparse
import subprocess
import tempfile
import os
from pathlib import Path
import sys
import shlex

def run_ffmpeg(cmd):
    try:
        print("▶️", " ".join(shlex.quote(str(x)) for x in cmd))
        subprocess.run(cmd, check=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] ffmpeg command failed: {e}")
        sys.exit(1)

def get_video_duration(path):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=nw=1:nk=1", str(path)
        ], text=True)
        return float(out.strip())
    except Exception:
        raise RuntimeError(f"Could not determine duration for {path}")

def parse_time(ts):
    """Parses a time string (SS, MM:SS, HH:MM:SS) to seconds (float)."""
    if ":" in ts:
        parts = ts.split(":")
        parts = [float(p) for p in parts]
        while len(parts) < 3:
            parts = [0.0] + parts
        h, m, s = parts
        return h * 3600 + m * 60 + s
    return float(ts)

def escape_filename(fname):
    # ffmpeg concat expects files in single quotes; escape internal quotes
    return fname.replace("'", "'\\''")

def merge(videos, output):
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        for v in videos:
            f.write(f"file '{escape_filename(os.path.abspath(v))}'\n")
        filelist = f.name
    try:
        run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", filelist,
            "-c", "copy", output
        ])
    finally:
        os.unlink(filelist)

def remove_video_slices(inp, slices, output):
    # slices = list of (start, end) pairs to cut out; we keep everything not in those slices
    cuts = []
    for s, e in slices:
        s_sec, e_sec = parse_time(s), parse_time(e)
        if e_sec <= s_sec:
            raise ValueError(f"Slice end {e} must be after start {s}.")
        cuts.append((s_sec, e_sec))
    cuts.sort()
    total = get_video_duration(inp)
    keep = []
    last = 0.0
    for s, e in cuts:
        if last < s:
            keep.append((last, min(s, total)))
        last = max(last, e)
    if last < total:
        keep.append((last, total))
    if not keep:
        raise ValueError("Nothing left to keep after applying cuts.")

    with tempfile.TemporaryDirectory() as tempdir:
        segments = []
        for i, (s, e) in enumerate(keep):
            if e <= s:
                continue
            seg = os.path.join(tempdir, f"segment_{i}.mp4")
            run_ffmpeg([
                "ffmpeg", "-y", "-ss", str(s), "-to", str(e),
                "-i", inp, "-c", "copy", seg
            ])
            segments.append(seg)
        merge(segments, output)

def downscale(inp, output, resolution):
    # Check input resolution
    probe = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", inp],
        text=True
    )
    width, height = [int(x) for x in probe.strip().split(",")]
    target_w, target_h = map(int, resolution.split(":"))
    if width < target_w or height < target_h:
        print(f"[WARN] Input ({width}x{height}) is smaller than target {target_w}x{target_h}. Upscaling.")
    run_ffmpeg([
        "ffmpeg", "-y", "-i", inp, "-vf", f"scale={resolution}",
        "-c:v", "libx264", "-crf", "20", output
    ])

def detect_duplicate(folder):
    print("[NOT IMPLEMENTED] Duplicate detection is not implemented. Use video hashing/fingerprinting libraries.")

def main():
    parser = argparse.ArgumentParser(description="Video Processing Utility")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Merge
    p_merge = sub.add_parser("merge", help="Merge multiple video files")
    p_merge.add_argument("-i", "--inputs", nargs="+", required=True, help="Input video files")
    p_merge.add_argument("-o", "--output", required=True, help="Output merged video")

    # Remove Slices
    p_cut = sub.add_parser("cut", help="Remove (cut) slices from video")
    p_cut.add_argument("-i", "--input", required=True, help="Input video file")
    p_cut.add_argument("-x", "--remove-slice", action="append", nargs=2, metavar=("START", "END"),
                       help="Start and end time(s) to remove, e.g. -x 00:01:00 00:01:10")
    p_cut.add_argument("-o", "--output", required=True, help="Output video")

    # Downscale
    p_down = sub.add_parser("downscale", help="Downscale video to specified resolution")
    p_down.add_argument("-i", "--input", required=True, help="Input video file")
    p_down.add_argument("-o", "--output", required=True, help="Output video file")
    p_down.add_argument("-r", "--resolution", choices=["3840:2160", "2560:1440", "1920:1080"], required=True,
                        help="Resolution, e.g. 1920:1080")

    # Detect duplicate (placeholder)
    p_dup = sub.add_parser("detect-dupes", help="(Placeholder) Detect duplicate/similar videos in folder")
    p_dup.add_argument("-f", "--folder", required=True, help="Folder to search for duplicates")

    args = parser.parse_args()
    if args.cmd == "merge":
        merge(args.inputs, args.output)
    elif args.cmd == "cut":
        if not args.remove_slice:
            parser.error("At least one --remove-slice (-x) required.")
        remove_video_slices(args.input, args.remove_slice, args.output)
    elif args.cmd == "downscale":
        downscale(args.input, args.output, args.resolution)
    elif args.cmd == "detect-dupes":
        detect_duplicate(args.folder)

if __name__ == "__main__":
    main()
