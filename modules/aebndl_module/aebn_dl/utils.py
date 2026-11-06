from __future__ import annotations

import logging
import subprocess
import shutil
from pathlib import Path
import os
import re
import sys
import struct

from tqdm import tqdm

from .movie_scraper import Movie

from .exceptions import FFmpegError


def remove_chars(text: str) -> str:
    """Remove characters from string"""
    for ch in ["#", "?", "!", ":", "<", ">", '"', "/", "\\", "|", "*"]:
        if ch in text:
            text = text.replace(ch, "")
    return text


def new_logger(name: str, log_level: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Set the logger level to the lowest (DEBUG)

    formatter = logging.Formatter("%(asctime)s|%(levelname)s|%(message)s", datefmt="%H:%M:%S")

    # Console handler with user set level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.set_name("console_handler")
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler with DEBUG level
    file_handler = logging.FileHandler(f"{name}.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.set_name("file_handler")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # https://stackoverflow.com/questions/6234405/
    def log_uncaught_exceptions(exctype, value, tb):
        logger.critical("Uncaught exception", exc_info=(exctype, value, tb))

    # Set the exception hook to log uncaught exceptions
    sys.excepthook = log_uncaught_exceptions
    return logger


def duration_to_seconds(duration: str) -> int:
    """Convert HH:MM:SS to seconds"""
    time_parts = list(map(int, duration.split(":")))
    time_parts.reverse()  # Reverse the list to start from seconds
    total_seconds = 0
    for i, part in enumerate(time_parts):
        if i == 0:  # Seconds
            total_seconds += part
        elif i == 1:  # Minutes
            total_seconds += part * 60
        elif i == 2:  # Hours
            total_seconds += part * 3600
    return total_seconds


def ffmpeg_mux_streams(stream_path_1: str, stream_path_2: str, output_path: str, silent: bool = False) -> None:
    """Mux two media streams with ffmpeg"""
    cmd = ["ffmpeg", "-hide_banner", "-i", str(stream_path_1), "-i", str(stream_path_2),
           "-map", "1:v:0", "-map", "0:a:0", "-c", "copy", "-y"]
    if silent:
        cmd += ["-loglevel", "warning"]
    cmd.append(str(output_path))
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise FFmpegError(out.stderr)


def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def is_mp4_fragment(path: str | Path, *, initialization: bool) -> bool:
    """Check top-level ISO-BMFF boxes without loading a whole fragment in memory."""
    try:
        file_path = Path(path)
        size = file_path.stat().st_size
        if not file_path.is_file() or size < 8:
            return False
        found: set[bytes] = set()
        offset = 0
        with file_path.open("rb") as stream:
            while offset < size:
                stream.seek(offset)
                header = stream.read(8)
                if len(header) != 8:
                    return False
                box_size, box_type = struct.unpack(">I4s", header)
                header_size = 8
                if box_size == 1:
                    extended = stream.read(8)
                    if len(extended) != 8:
                        return False
                    box_size = struct.unpack(">Q", extended)[0]
                    header_size = 16
                elif box_size == 0:
                    box_size = size - offset
                if box_size < header_size or offset + box_size > size:
                    return False
                found.add(box_type)
                offset += box_size
        return {b"moov"}.issubset(found) if initialization else {b"moof", b"mdat"}.issubset(found)
    except OSError:
        return False


def mp4_fragment_decode_time(path: str | Path) -> int | None:
    """Read the media fragment's base decode time from its ``tfdt`` box."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None

    def iter_boxes(start: int, end: int):
        offset = start
        while offset + 8 <= end:
            box_size, box_type = struct.unpack_from(">I4s", data, offset)
            header_size = 8
            if box_size == 1:
                if offset + 16 > end:
                    return
                box_size = struct.unpack_from(">Q", data, offset + 8)[0]
                header_size = 16
            elif box_size == 0:
                box_size = end - offset
            if box_size < header_size or offset + box_size > end:
                return
            yield box_type, offset + header_size, offset + box_size
            offset += box_size

    timestamps: list[int] = []

    def visit(start: int, end: int) -> None:
        for box_type, body, box_end in iter_boxes(start, end):
            if box_type == b"tfdt":
                if body + 8 > box_end:
                    continue
                version = data[body]
                if version == 1 and body + 12 <= box_end:
                    timestamps.append(struct.unpack_from(">Q", data, body + 4)[0])
                elif version == 0:
                    timestamps.append(struct.unpack_from(">I", data, body + 4)[0])
            elif box_type in {b"moof", b"traf"}:
                visit(body, box_end)

    visit(0, len(data))
    return timestamps[0] if len(timestamps) == 1 else None


def validate_fragment_timeline(paths: list[str | Path]) -> None:
    """Reject missing, duplicate, or regressing decode timestamps in index order."""
    if not paths:
        raise ValueError("No media fragments are available for timeline validation")
    previous: int | None = None
    previous_path: str | Path | None = None
    for path in paths:
        current = mp4_fragment_decode_time(path)
        if current is None:
            raise ValueError(f"Fragment has no unambiguous decode timestamp: {path}")
        if previous is not None and current <= previous:
            raise ValueError(
                f"Fragment decode timestamp did not advance: {previous_path}={previous}, {path}={current}"
            )
        previous, previous_path = current, path


def concat_segments(files: list[str], output_path: str, tqdm_desc: str, aggressive_cleaning: bool, silent: bool = False):
    """Concat segments into a single file"""
    _files = [files[0], *sorted(files[1:], key=natural_sort_key)]
    concat_progress = tqdm(files, desc=f"Joining {tqdm_desc}", disable=silent)
    with open(output_path, "wb") as f:
        for segment_file_path in _files:
            with open(segment_file_path, "rb") as segment_file:
                content = segment_file.read()
                segment_file.close()
                f.write(content)
                concat_progress.update()
            if aggressive_cleaning:
                os.remove(segment_file_path)
    concat_progress.close()


def is_valid_media(media_bytes: bytes) -> bool:
    """Check if media bytes are are read as valid media with fmmpeg"""
    cmd = "ffmpeg -f mp4 -i pipe:0 -f null -"

    # Use subprocess.Popen with PIPE to create a pipe for input
    process = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    # Write the media bytes to the stdin of the FFmpeg process
    _, stderr_data = process.communicate(input=media_bytes)

    # Check if FFmpeg found any errors
    if b"Multiple frames in a packet" in stderr_data or b"Error" in stderr_data:
        return False  # Not Valid
    return True  # Valid


def ffmpeg_check() -> None:
    """Ensure ffmpeg is available in PATH"""
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError("ffmpeg not found! Please add it to PATH.")


def add_metadata(
    input_path: str | Path,
    movie: Movie,
    *,
    output_path: str | Path | None = None,
    scene_n: int | None = None,
) -> Path:
    """Write title/chapters to a separate candidate file using stream copy.

    The assembled input is never replaced here. The caller validates the
    candidate and promotes it only after that validation passes.
    """
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path is not None else input_path.with_name(f"{input_path.stem}.metadata{input_path.suffix}")

    def escape(value: object) -> str:
        text = str(value or "")
        return text.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", "\\n")

    metadata_content = f";FFMETADATA1\ntitle={escape(movie.title)}\n\n"
    if scene_n is not None:
        if scene_n < 1 or scene_n > len(movie.scenes):
            raise ValueError(f"Scene ordinal {scene_n} is unavailable for chapter metadata")
        scene = movie.scenes[scene_n - 1]
        duration = scene.end_timing - scene.start_timing
        if duration <= 0:
            raise ValueError("Selected scene has invalid chapter timing")
        scene_title = f"Scene {scene_n}: " + ", ".join(scene.performers or [])
        metadata_content += (
            "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\n"
            f"END={duration * 1000}\ntitle={escape(scene_title)}\n\n"
        )
    else:
        for index, scene in enumerate(movie.scenes, start=1):
            start_time_ms = int(scene.start_timing * 1000)
            end_time_ms = int(scene.end_timing * 1000)
            scene_title = f"Scene {index}: " + ", ".join(scene.performers or [])
            metadata_content += (
                "[CHAPTER]\nTIMEBASE=1/1000\n"
                f"START={start_time_ms}\nEND={end_time_ms}\n"
                f"title={escape(scene_title)}\n\n"
            )

    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(input_path), "-f", "ffmetadata", "-i", "-",
        "-map", "0:v?", "-map", "0:a?", "-map_metadata", "1", "-map_chapters", "1",
        "-c", "copy", "-y", str(output_path),
    ]
    result = subprocess.run(cmd, input=metadata_content, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise FFmpegError(result.stderr)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise FFmpegError("ffmpeg produced no metadata candidate output")
    return output_path
