#!/usr/bin/env python3
"""
video_clipper.py

A simple command-line tool to extract one or more clips from a video
and concatenate them into a single output file.

Dependencies:
  • moviepy (install with `pip install moviepy` or
    `conda install -c conda-forge moviepy ffmpeg`)
  • ffmpeg (must be on your PATH)
"""

import argparse
from moviepy.editor import VideoFileClip, concatenate_videoclips

def parse_time(t: str) -> float:
    """
    Parse a time string (HH:MM:SS, MM:SS, or seconds) into seconds.
    """
    if ':' in t:
        parts = [float(p) for p in t.split(':')]
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h = 0.0
            m, s = parts
        else:
            raise ValueError(f"Invalid time format: {t!r}")
        return h * 3600 + m * 60 + s
    return float(t)

def main():
    p = argparse.ArgumentParser(
        description="Clip and stitch segments from a video file"
    )
    p.add_argument(
        "-i", "--input", required=True,
        help="Input video file (e.g., input.mp4 or input.mov)"
    )
    p.add_argument(
        "-o", "--output", required=True,
        help="Output video file (e.g., out.mp4)"
    )
    p.add_argument(
        "-c", "--clip", action="append", required=True,
        metavar="START,END",
        help=(
            "Clip interval in start,end format. "
            "Times can be HH:MM:SS, MM:SS, or seconds. "
            "Use -c multiple times for multiple segments."
        )
    )

    args = p.parse_args()

    # Load the source video once
    video = VideoFileClip(args.input)

    # Extract each requested subclip
    clips = []
    for interval in args.clip:
        try:
            start_str, end_str = interval.split(',', 1)
        except ValueError:
            p.error(f"Invalid clip format (expected start,end): {interval!r}")
        start = parse_time(start_str)
        end   = parse_time(end_str)
        if end <= start:
            p.error(f"End time must be > start time in interval: {interval!r}")
        print(f"→ Adding clip from {start}s to {end}s")
        clips.append(video.subclip(start, end))

    if not clips:
        p.error("No valid clips specified.")

    # Concatenate and write out
    final = concatenate_videoclips(clips, method="compose")
    print(f"Rendering final video to {args.output!r} …")
    final.write_videofile(
        args.output,
        codec="libx264",         # H.264 video
        audio_codec="aac",       # AAC audio
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        threads=4
    )

if __name__ == "__main__":
    main()
