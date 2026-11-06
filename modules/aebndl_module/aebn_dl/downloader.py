from __future__ import annotations

import datetime
import email.utils as eut
import glob as _glob
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event, Thread

import os
import time
import signal
from typing import Literal, Optional

from tqdm.auto import tqdm

from . import utils
from .custom_session import CustomSession
from .models import MediaStream
from .movie_scraper import Movie
from .manifest_parser import Manifest, PreviewAccessError
from .exceptions import Forbidden
import json
import atexit
import uuid
from pathlib import Path

from .media_validation import probe_media, validate_media_facts


class Downloader:
    def __init__(
        self,
        url: str,
        target_height: int | None = None,
        scene_n: int | None = None,
        start_segment: int = 0,
        end_segment: int | None = None,
        output_dir: str = "",
        work_dir: str = "",
        proxy: str = "",
        threads: int = 5,
        proxy_metadata_only: bool = False,
        download_covers: bool = False,
        overwrite_existing_files: bool = False,
        target_stream: Literal["audio", "video", None] = None,
        keep_segments_after_download: bool = False,
        aggressive_segment_cleaning: bool = False,
        force_resolution: bool = False,
        include_performer_names: bool = False,
        no_metadata: bool = False,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
        keep_logs: bool = False,
        json_output: bool = False,
        no_part: bool = False,
        scene_id: str | None = None,
    ):
        """
        Args:
            url: The URL of the movie.
            target_height: The desired height of the movie in pixels.
            scene_n: The scene number of the movie.
            scene_id: The AEBN scene ID to resolve to a scene ordinal.
            start_segment: Set the start segment.
            end_segment: Set the end segment.
            output_dir: The directory where the output file will be saved.
            work_dir: The directory to store temporary files during processing.
            log_level: The logging level ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"). Defaults to "INFO".
            proxy: The proxy server address to use for network requests.
            threads: Threads for concurrent downloads. Default 5.
            proxy_metadata_only: If True, use the proxy only for metadata requests, otherwise use it for all requests. Defaults to False.
            download_covers: If True, download cover images. Defaults to False.
            overwrite_existing_files: If True, overwrite existing files in the output directory. Defaults to False.
            target_stream: The target stream to download ("audio", "video", or None for both). Defaults to None.
            keep_segments_after_download: If True, keep the downloaded segments after processing. Defaults to False.
            aggressive_segment_cleaning: If True, aggressively clean up segments during processing. Defaults to False.
            force_resolution: If True, force the specified resolution even if it's not available. Defaults to False.
            include_performer_names: If True, include performer names in the output file name. Defaults to False.
            no_metadata: Disable adding title and chapter markers to the output video. Defaults to False.
            keep_logs: If True, keep log files after processing. Defaults to False.
            no_part: If True, disable .part file creation for resumable downloads. Defaults to False.
        """

        self.input_url = url
        self.output_dir = output_dir or os.getcwd()
        self.work_dir = work_dir or os.getcwd()
        self.target_height = target_height
        self.force_resolution = force_resolution
        self.include_performer_names = include_performer_names
        self.no_metadata = no_metadata
        self.scene_n = scene_n
        self.scene_id = scene_id
        self.download_covers = download_covers
        self.overwrite_existing_files = overwrite_existing_files
        self.target_stream = target_stream
        self.start_segment = start_segment
        self.end_segment = end_segment
        self.aggressive_segment_cleaning = aggressive_segment_cleaning
        self.keep_segments_after_download = keep_segments_after_download
        self.log_level = log_level
        self.keep_logs = keep_logs
        self.proxy = proxy
        self.threads = threads
        self.proxy_metadata_only = proxy_metadata_only
        self.json_output = json_output
        self.no_part = no_part
        self.logger = utils.new_logger(name=self._movie_logger_name(), log_level=log_level)
        self.is_silent = self.logger.getEffectiveLevel() > logging.INFO or self.json_output

        if self.json_output:
            # Silence console logger when in JSON mode
            for handler in self.logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    handler.setLevel(logging.CRITICAL + 1)
        self.movie_work_dir: str | None = None
        self.manifest: Manifest | None = None
        self.session: CustomSession | None = None
        self.manifest_lock = Lock()
        self.part_file_path: str | None = None
        self.download_interrupted = False
        self.part_file_lock = Lock()
        self.required_segment_range: tuple[int, int] | None = None

        # Register cleanup handler for graceful exit
        if not self.no_part:
            atexit.register(self._save_part_file_on_exit)
            # Register SIGTERM handler to save .part file on termination
            def sigterm_handler(signum, frame):
                self.logger.info("Received SIGTERM, saving progress...")
                self.download_interrupted = True
                self._save_part_file(force=True)
                self._json_log("interrupted", signal=signum)
                raise SystemExit(128 + signum)

            signal.signal(signal.SIGTERM, sigterm_handler)

    def _json_log(self, event: str, **data) -> None:
        if not self.json_output:
            return
        # Add a timestamp to all events
        data["timestamp"] = datetime.datetime.now().isoformat()
        data["event"] = event
        # Flush so downstream readers (procparsers) see events promptly
        print(json.dumps(data, ensure_ascii=False), flush=True)

    def _get_part_file_path(self, output_file_name: str) -> str:
        """Generate path to .part file for given output"""
        return os.path.join(self.output_dir, f"{output_file_name}.part")

    def _load_part_file(self, part_file_path: str) -> dict | None:
        """Load and validate existing .part file"""
        if not os.path.exists(part_file_path):
            return None

        try:
            with open(part_file_path, 'r') as f:
                data = json.load(f)

            # Resume data is accepted only when its download identity matches.
            required_fields = ['url', 'movie_id', 'streams']
            if not all(field in data for field in required_fields):
                self.logger.warning(f"Invalid .part file format, ignoring: {part_file_path}")
                return None

            # Validate URL matches
            if data['url'] != self.input_url:
                self.logger.warning(f".part file is for different URL, ignoring: {part_file_path}")
                return None
            if any(data.get(key) != expected for key, expected in (
                ('target_height', self.target_height), ('scene_n', self.scene_n), ('target_stream', self.target_stream)
            ) if key in data) or (self.movie_work_dir and data['movie_id'] != os.path.basename(self.movie_work_dir)):
                self.logger.warning(f".part file selection identity differs, ignoring: {part_file_path}")
                return None
            if 'scene_id' in data and data['scene_id'] != self.scene_id:
                self.logger.warning(f".part file scene ID differs, ignoring: {part_file_path}")
                return None
            current_range = list(self.required_segment_range) if self.required_segment_range else None
            if data.get('segment_range') and current_range and data['segment_range'] != current_range:
                self.logger.warning(f".part file scene segment range differs, ignoring: {part_file_path}")
                return None
            current_base_url = getattr(self.manifest, 'base_stream_url', None)
            if data.get('base_stream_url') and current_base_url and data['base_stream_url'] != current_base_url:
                self.logger.warning(f".part file manifest representation differs, ignoring: {part_file_path}")
                return None
            current_segment_count = getattr(self.manifest, 'total_number_of_data_segments', None)
            if data.get('total_number_of_data_segments') is not None and current_segment_count is not None and data['total_number_of_data_segments'] != current_segment_count:
                self.logger.warning(f".part file segment range differs, ignoring: {part_file_path}")
                return None

            self.logger.info(f"Found existing .part file, resuming download: {part_file_path}")
            return data
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(f"Failed to read .part file: {e}")
            return None

    def _save_part_file(self, force: bool = False) -> None:
        """Save current download progress to .part file"""
        if self.no_part or not self.part_file_path:
            return

        # Don't save if download completed successfully
        if not force and not self.download_interrupted:
            return

        if not self.manifest or not self.movie_work_dir:
            return

        with self.part_file_lock:
            try:
                part_dir = os.path.dirname(self.part_file_path)
                if part_dir:
                    os.makedirs(part_dir, exist_ok=True)

                # Collect downloaded segments for each stream.
                streams_data = {}
                for stream in (self.manifest.audio_stream, self.manifest.video_stream):
                    if stream:
                        streams_data[stream.media_type] = {
                            'stream_id': stream.stream_id,
                            'downloaded_segments': list(stream.downloaded_segments),
                            'downloaded_bytes': sum(os.path.getsize(path) for path in stream.downloaded_segments if os.path.isfile(path)),
                            'total_size': stream.total_size,
                        }

                part_data = {
                    'url': self.input_url,
                    'movie_id': os.path.basename(self.movie_work_dir),
                    'target_height': self.target_height,
                    'scene_n': self.scene_n,
                    'scene_id': self.scene_id,
                    'target_stream': self.target_stream,
                    'base_stream_url': getattr(self.manifest, 'base_stream_url', None),
                    'total_number_of_data_segments': getattr(self.manifest, 'total_number_of_data_segments', None),
                    'segment_range': list(self.required_segment_range) if self.required_segment_range else None,
                    'streams': streams_data,
                    'timestamp': datetime.datetime.now().isoformat(),
                }

                temp_path = f"{self.part_file_path}.tmp-{uuid.uuid4().hex}"
                try:
                    with open(temp_path, 'w', encoding='utf-8') as f:
                        json.dump(part_data, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp_path, self.part_file_path)
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

                self.logger.debug(f"Saved .part file: {self.part_file_path}")
            except OSError as e:
                self.logger.warning(f"Failed to save .part file: {e}")

    def _save_part_file_on_exit(self) -> None:
        """Called by atexit to save progress on unexpected termination"""
        if self.download_interrupted:
            self._save_part_file(force=True)

    def _cleanup_part_file(self) -> None:
        """Remove .part file after successful download"""
        if self.part_file_path and os.path.exists(self.part_file_path):
            try:
                os.remove(self.part_file_path)
                self.logger.debug(f"Removed .part file: {self.part_file_path}")
            except OSError as e:
                self.logger.warning(f"Failed to remove .part file: {e}")

    def _restore_from_part_file(self, part_data: dict) -> None:
        """Restore download progress from .part file data"""
        if 'streams' not in part_data:
            return

        # Restore downloaded segments info for each stream
        for media_type, stream_data in part_data['streams'].items():
            if media_type == 'a' and self.manifest.audio_stream:
                stream = self.manifest.audio_stream
            elif media_type == 'v' and self.manifest.video_stream:
                stream = self.manifest.video_stream
            else:
                continue

            # Validate stream_id matches
            if stream.stream_id != stream_data.get('stream_id'):
                self.logger.warning(f"Stream ID mismatch for {media_type}, ignoring resume data")
                continue

            # Restore downloaded segments list (filter out non-existent files)
            if 'downloaded_segments' in stream_data:
                allowed_range = self.required_segment_range
                existing_segments = []
                for seg in stream_data['downloaded_segments']:
                    path = Path(seg)
                    try:
                        if self.movie_work_dir:
                            path.resolve(strict=True).relative_to(Path(self.movie_work_dir).resolve())
                        else:
                            path.resolve(strict=True)
                    except (OSError, ValueError):
                        continue
                    name = path.name
                    is_init = name == f"{media_type}i_{stream.stream_id}.mp4"
                    prefix = f"{media_type}_{stream.stream_id}_"
                    if is_init:
                        valid = utils.is_mp4_fragment(path, initialization=True)
                    elif name.startswith(prefix) and name.endswith(".mp4"):
                        try:
                            number = int(name[len(prefix):-4])
                        except ValueError:
                            continue
                        total_segments = getattr(self.manifest, 'total_number_of_data_segments', None)
                        if isinstance(total_segments, int) and number >= total_segments:
                            continue
                        if allowed_range and not (allowed_range[0] <= number <= allowed_range[1]):
                            continue
                        valid = utils.is_mp4_fragment(path, initialization=False)
                    else:
                        continue
                    if valid:
                        existing_segments.append(str(path))
                stream.downloaded_segments = existing_segments
                self.logger.info(f"Restored {len(existing_segments)} {stream.human_name} segments from .part file")

            # Counters are derived from accepted on-disk fragments, never trusted from JSON.
            stream.downloaded_bytes = sum(os.path.getsize(path) for path in stream.downloaded_segments)
            if 'total_size' in stream_data:
                stream.total_size = stream_data['total_size']
            self._refresh_stream_total_estimate(stream)

    def _stream_segment_sizes(self, stream: MediaStream) -> tuple[int, int, int]:
        """Return (data_count, data_bytes, init_bytes) for downloaded stream segments."""
        data_count = 0
        data_bytes = 0
        init_bytes = 0
        data_prefix = f"{stream.media_type}_{stream.stream_id}_"
        init_prefix = f"{stream.media_type}i_{stream.stream_id}"
        for segment_path in stream.downloaded_segments:
            try:
                segment_size = os.path.getsize(segment_path)
            except OSError:
                continue
            segment_name = os.path.basename(segment_path)
            if segment_name.startswith(data_prefix):
                data_count += 1
                data_bytes += segment_size
            elif segment_name.startswith(init_prefix):
                init_bytes += segment_size
        return data_count, data_bytes, init_bytes

    def _refresh_stream_total_estimate(self, stream: MediaStream) -> None:
        """Recompute total size from actual resumed/downloaded data segments."""
        total_segments = getattr(self.manifest, "total_number_of_data_segments", None)
        if not total_segments:
            return
        data_count, data_bytes, init_bytes = self._stream_segment_sizes(stream)
        if data_count <= 0 or data_bytes <= 0:
            return
        avg_segment_size = data_bytes / data_count
        estimated_total = int(avg_segment_size * int(total_segments)) + init_bytes
        if estimated_total > stream.total_size:
            stream.total_size = estimated_total

    def run(self) -> None:
        """Executes the movie download process."""
        try:
            # Mark download as potentially interrupted
            self.download_interrupted = True
            self._json_log("startup", url=self.input_url)

            self._initialize_download()
            scraped_movie = self._scrape_movie_info()
            if self.scene_id is not None:
                self.scene_n = scraped_movie.scene_ordinal_for_id(self.scene_id)
                self._json_log("scene_selected", scene_id=self.scene_id, scene_ordinal=self.scene_n)
            self._process_manifest(scraped_movie)
            self.required_segment_range = self._segment_range(scraped_movie)
            output_file_name = self._generate_output_name(scraped_movie)
            output_path = os.path.join(self.output_dir, output_file_name)
            expected_duration = self._expected_duration(scraped_movie)
            if not self.overwrite_existing_files:
                existing = self._find_existing_output(scraped_movie, expected_duration)
                if existing is not None:
                    self._json_log("destination", path=existing)
                    self._json_log("already", path=existing, validation=getattr(self, "_last_existing_validation", None))
                    self.download_interrupted = False
                    return
            self._json_log("destination", path=output_path)
            if not self.overwrite_existing_files and os.path.exists(output_path):
                validation = self._validate_output(output_path, expected_duration)
                if not validation["valid"]:
                    raise ValueError(f"Existing AEBN output is invalid and was preserved: {validation['errors']}")
                self._json_log("already", path=output_path, validation=validation)
                self.download_interrupted = False
                return
            self._create_dirs(scraped_movie.movie_id)

            # Initialize .part file tracking
            if not self.no_part:
                self.part_file_path = self._get_part_file_path(output_file_name)
                part_data = self._load_part_file(self.part_file_path)
                if part_data:
                    self._restore_from_part_file(part_data)

            self._set_stream_paths()
            if self.download_covers:
                self._download_movie_covers(scraped_movie)
            self.logger.info(f"Output file name: {output_file_name}")
            self._download_streams(scraped_movie)
            stage_path = f"{output_path}.staging-{uuid.uuid4().hex}.mp4"
            self._process_streams(stage_path)
            pre_metadata = self._validate_output(stage_path, expected_duration)
            self._json_log("media_validation", stage="assembled", path=stage_path, **pre_metadata)
            if not pre_metadata["valid"]:
                raise ValueError(f"Assembled AEBN media failed validation: {pre_metadata['errors']}")
            final_stage_path = stage_path
            if not self.no_metadata:
                candidate_path = f"{output_path}.metadata-{uuid.uuid4().hex}.mp4"
                utils.add_metadata(stage_path, scraped_movie, output_path=candidate_path, scene_n=self.scene_n)
                post_metadata = self._validate_output(candidate_path, expected_duration)
                self._json_log("media_validation", stage="metadata", path=candidate_path, **post_metadata)
                if not post_metadata["valid"]:
                    raise ValueError(f"Metadata-remuxed AEBN media failed validation: {post_metadata['errors']}")
                if not self._same_stream_coverage(pre_metadata, post_metadata):
                    raise ValueError("Metadata remux materially changed stream packet counts or durations")
                final_stage_path = candidate_path

            if os.path.exists(output_path) and not self.overwrite_existing_files:
                raise FileExistsError(f"Refusing to overwrite existing AEBN output: {output_path}")
            os.replace(final_stage_path, output_path)
            final_validation = self._validate_output(output_path, expected_duration)
            if not final_validation["valid"]:
                raise ValueError(f"Promoted AEBN output failed final validation: {final_validation['errors']}")
            self._json_log("complete", path=output_path, file_size=os.path.getsize(output_path), validation=final_validation)
            if stage_path != output_path and os.path.exists(stage_path):
                os.remove(stage_path)

            # Mark download as successfully completed
            self.download_interrupted = False
            self._cleanup()
        except KeyboardInterrupt:
            self.logger.info("Download interrupted by user")
            self._save_part_file(force=True)
            raise
        except Exception as exc:
            self._json_log("error", error_type=type(exc).__name__, message=str(exc))
            self._save_part_file(force=True)
            raise

    def _init_new_session(self, use_proxies: bool = True) -> None:
        """Init new curl_cffi session"""
        self.session = CustomSession(impersonate="chrome")
        self.session.timeout = 30
        self.session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        self.session.headers["Connection"] = "keep-alive"
        self.session.cookies.update({"ageGated": "true", "terms": "true"})
        if self.proxy and use_proxies:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

    def _movie_logger_name(self) -> str:
        """Generate logger name from movie url"""
        name = self.input_url.split("/")[5]
        if self.scene_n:
            return f"{name}_{self.scene_n}"
        return name

    def _get_handler_level(self, handler_name: str) -> int | None:
        for handler in self.logger.handlers:
            if handler.name == handler_name:
                return handler.level
        return None

    def _delete_log(self) -> None:
        for handler in self.logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.close()  # Close the file handler before deleting the file
        os.remove(f"{self.logger.name}.log")

    def _log_init_state(self) -> None:
        """Log input arguments"""
        self.logger.info(f"Input URL: {self.input_url}")
        self.logger.info(f"Proxy: {self.proxy}")
        self.logger.info(f"Threads: {self.threads}")
        self.logger.info(f"Output dir: {self.output_dir}")
        self.logger.info(f"Work dir: {self.work_dir}")
        self.logger.info(f"Target stream: {self.target_stream or 'both'}")
        if self.aggressive_segment_cleaning:
            self.logger.info("Aggressive cleanup enabled, segments will be deleted before stream muxing")
        if self.target_height is None:
            self.logger.info("Target resolution: Highest")
        elif self.target_height > 0:
            self.logger.info(f"Target resolution: {self.target_height}")
        elif self.target_height == 0:
            self.logger.info("Target resolution: Lowest")

    def _generate_output_name(self, scraped_movie: Movie) -> str:
        """Generate output file name from movie metadata"""
        output_file_name = []
        if self.target_stream:
            output_file_name.append(f"[{self.target_stream}]")
        if scraped_movie.studio_name:
            output_file_name.append(scraped_movie.studio_name)
        if scraped_movie.studio_name and scraped_movie.title:
            output_file_name.append("-")
        if scraped_movie.title:
            output_file_name.append(scraped_movie.title)
        if self.scene_n:
            output_file_name.append(f"Scene {self.scene_n}")
        if self.include_performer_names:
            if self.scene_n:
                scene = scraped_movie.scenes[self.scene_n - 1]
                performers = scene.performers
            else:
                performers = scraped_movie.performers
            if performers:
                output_file_name.append(", ".join(performers))
        if self.target_stream != "audio":
            output_file_name.append(f"{self.manifest.video_stream.height}p")
        return " ".join(filter(None, output_file_name)) + ".mp4"

    def _expected_duration(self, scraped_movie: Movie) -> float | None:
        if self.scene_n:
            if self.scene_n < 1 or self.scene_n > len(scraped_movie.scenes):
                raise ValueError(f"Scene {self.scene_n} not found")
            scene = scraped_movie.scenes[self.scene_n - 1]
            start = getattr(scene, "start_timing", None)
            end = getattr(scene, "end_timing", None)
            if start is None or end is None or end <= start:
                raise ValueError("Selected scene duration metadata is unavailable")
            return float(end - start)
        duration = getattr(scraped_movie, "total_duration_seconds", None)
        return float(duration) if duration and duration > 0 else None

    def _required_media_streams(self) -> tuple[str, ...]:
        if self.target_stream == "audio":
            return ("audio",)
        if self.target_stream == "video":
            return ("video",)
        return ("video", "audio")

    def _validate_output(self, path: str | Path, expected_duration: float | None) -> dict:
        facts = probe_media(path)
        if facts is None:
            return {"valid": False, "status": "unknown", "errors": ["ffprobe unavailable or media could not be parsed"], "evidence": {}}
        return validate_media_facts(facts, expected_duration=expected_duration,
                                    required_streams=self._required_media_streams())

    @staticmethod
    def _same_stream_coverage(before: dict, after: dict) -> bool:
        before_streams = before.get("evidence", {}).get("streams", {})
        after_streams = after.get("evidence", {}).get("streams", {})
        if before_streams.keys() != after_streams.keys():
            return False
        for kind in before_streams:
            left, right = before_streams[kind], after_streams[kind]
            if left.get("packet_count") != right.get("packet_count"):
                return False
            left_duration, right_duration = left.get("duration_s"), right.get("duration_s")
            if left_duration is None or right_duration is None or abs(left_duration - right_duration) > 1.0:
                return False
        return True

    def _find_existing_output(self, scraped_movie: Movie, expected_duration: float | None = None) -> Optional[str]:
        """Return an already-downloaded output path for this movie, or None.

        Matches any resolution variant, but only accepts files with validated
        independent stream coverage. Invalid outputs are preserved and cause a
        closed failure instead of silently bypassing a replacement.
        """
        parts = []
        if self.target_stream:
            parts.append(f"[{self.target_stream}]")
        if scraped_movie.studio_name:
            parts.append(scraped_movie.studio_name)
            parts.append("-")
        if scraped_movie.title:
            parts.append(scraped_movie.title)
        if self.scene_n:
            parts.append(f"Scene {self.scene_n}")
        base = " ".join(filter(None, parts))
        bases = [base]
        if not scraped_movie.studio_name:
            bases.append(f"- {base}")
        paths = [path for name in bases for path in _glob.glob(
            os.path.join(self.output_dir, f"{_glob.escape(name)}*p.mp4")
        )]
        for path in paths:
            try:
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    validation = self._validate_output(path, expected_duration)
                    if validation["valid"]:
                        self._last_existing_validation = validation
                        return path
                    raise ValueError(f"Existing AEBN output is invalid and was preserved: {path}: {validation['errors']}")
            except OSError:
                continue
        return None

    def _cleanup(self) -> None:
        """Cleans up the work directory and potentially deletes logs."""
        self._work_folder_cleanup()
        self._cleanup_part_file()
        if not self.keep_logs:
            self._delete_log()

    def _concat_stream(self, stream: MediaStream) -> None:
        """Concat stream segments into a single file"""
        init_name = f"{stream.media_type}i_{stream.stream_id}.mp4"
        init_paths = [path for path in stream.downloaded_segments if Path(path).name == init_name]
        if len(init_paths) != 1 or not utils.is_mp4_fragment(init_paths[0], initialization=True):
            raise RuntimeError(f"{stream.human_name} stream has no unique, valid initialization fragment")
        segment_paths: dict[int, str] = {}
        prefix = f"{stream.media_type}_{stream.stream_id}_"
        for path in stream.downloaded_segments:
            name = Path(path).name
            if name == init_name:
                continue
            if not name.startswith(prefix) or not name.endswith(".mp4"):
                raise RuntimeError(f"Unexpected {stream.human_name} fragment identity: {name}")
            try:
                number = int(name[len(prefix):-4])
            except ValueError as exc:
                raise RuntimeError(f"Malformed {stream.human_name} fragment identity: {name}") from exc
            if number in segment_paths:
                raise RuntimeError(f"Duplicate {stream.human_name} segment index {number}")
            if not utils.is_mp4_fragment(path, initialization=False):
                raise RuntimeError(f"Malformed retained {stream.human_name} fragment {path}")
            segment_paths[number] = path
        if self.required_segment_range is None:
            raise RuntimeError("Required segment range is unavailable")
        expected = set(range(self.required_segment_range[0], self.required_segment_range[1] + 1))
        optional = set(stream.optional_missing_segments)
        missing = expected - set(segment_paths) - optional
        unexpected = set(segment_paths) - expected
        if missing or unexpected:
            raise RuntimeError(f"{stream.human_name} segment inventory mismatch; missing={sorted(missing)}, unexpected={sorted(unexpected)}")
        if optional - expected or optional - {self.manifest.total_number_of_data_segments}:
            raise RuntimeError(f"{stream.human_name} stream recorded an invalid optional missing segment")
        stream.downloaded_segments = [init_paths[0], *(segment_paths[index] for index in sorted(segment_paths))]
        if os.path.exists(stream.path):
            os.remove(stream.path)
        utils.concat_segments(
            files=stream.downloaded_segments,
            output_path=stream.path,
            tqdm_desc=f"{stream.human_name} segments",
            # Keep fragments until the final staged output has passed validation.
            aggressive_cleaning=False,
            silent=self.is_silent,
        )

    def _concat_streams(self) -> None:
        """Concatenate streams concurrently using thread pool"""
        streams_to_concat = [stream for stream in (self.manifest.audio_stream, self.manifest.video_stream) if stream.human_name == self.target_stream or not self.target_stream]

        with ThreadPoolExecutor(max_workers=len(streams_to_concat)) as executor:
            futures = []
            for stream in streams_to_concat:
                future = executor.submit(self._concat_stream, stream)
                futures.append(future)

            for future in futures:
                future.result()

    def _process_streams(self, output_path: str) -> None:
        """Processes the downloaded streams, concatinating, and either muxing or renaming based on target stream."""
        self._concat_streams()
        if not self.target_stream:
            self._mux_streams(output_path)
        else:
            self._rename_stream(output_path)

    def _mux_streams(self, output_path: str) -> None:
        """Muxes audio and video streams using ffmpeg."""
        self.logger.info("Muxing streams with ffmpeg")
        utils.ffmpeg_mux_streams(self.manifest.audio_stream.path, self.manifest.video_stream.path, output_path)
        self.logger.info("Muxing success")

    def _rename_stream(self, output_path: str) -> None:
        """Renames the target stream to the output path."""
        for stream in (self.manifest.audio_stream, self.manifest.video_stream):
            if stream.human_name == self.target_stream:
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(stream.path, output_path)

    def _download_movie_covers(self, scraped_movie: Movie) -> None:
        """Downloads the movie covers."""
        full_name = f"{scraped_movie.studio_name} - {scraped_movie.title}"
        self._download_cover(full_name, scraped_movie.cover_url_front, front=True)
        self._download_cover(full_name, scraped_movie.cover_url_back, front=False)

    def _set_stream_paths(self) -> None:
        """Sets the file paths for the audio and video streams."""
        for stream in (self.manifest.audio_stream, self.manifest.video_stream):
            stream.path = os.path.join(self.movie_work_dir, f"{stream.media_type}_{stream.stream_id}.mp4")

    def _create_dirs(self, movie_id: str) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        self.movie_work_dir = os.path.join(self.work_dir, movie_id)
        os.makedirs(self.movie_work_dir, exist_ok=True)

    def _process_manifest(self, scraped_movie: Movie) -> None:
        """Processes the movie manifest."""
        self.logger.info("Processing manifest")
        self._json_log("manifest_start", url=self.input_url)
        self.manifest = Manifest(
            self.input_url,
            scraped_movie.total_duration_seconds,
            self.session,
            target_height=self.target_height,
            force_resolution=self.force_resolution,
        )
        if self.scene_n:
            scraped_movie.calculate_scenes_boundaries(1.0)
            if self.scene_n < 1 or self.scene_n > len(scraped_movie.scenes):
                raise ValueError(f"Scene {self.scene_n} not found")
            scene = scraped_movie.scenes[self.scene_n - 1]
            self.manifest.requested_interval = (scene.start_timing, scene.end_timing)
        try:
            self.manifest.process_manifest()
        except PreviewAccessError as exc:
            self._json_log("preview_fallback", error_type=type(exc).__name__, message=str(exc))
            raise
        except Exception as exc:
            self._json_log("manifest_error", error_type=type(exc).__name__, message=str(exc))
            raise
        self._json_log("manifest_ready", url=self.input_url)
        if self.scene_n:
            for scene in scraped_movie.scenes:
                scene.start_segment = math.floor(scene.start_timing / self.manifest.segment_duration)
                scene.end_segment = math.ceil(scene.end_timing / self.manifest.segment_duration)
        else:
            scraped_movie.calculate_scenes_boundaries(self.manifest.segment_duration)

    def _scrape_movie_info(self) -> Movie:
        """Scrapes movie information from the input URL."""
        self.logger.info("Scraping movie info")
        self._json_log("metadata_start", url=self.input_url)
        result: list[Movie | None] = [None]
        error: list[BaseException | None] = [None]

        def scrape() -> None:
            try:
                result[0] = Movie(self.input_url, self.session)
            except BaseException as exc:
                error[0] = exc

        thread = Thread(target=scrape, daemon=True)
        thread.start()
        while thread.is_alive():
            thread.join(timeout=1.0)
            if thread.is_alive():
                self._json_log("metadata_fetch", url=self.input_url)
        if error[0] is not None:
            raise error[0]
        if result[0] is None:
            raise RuntimeError("AEBN metadata fetch produced no movie data")
        return result[0]

    def _initialize_download(self) -> None:
        """Initializes the download process, checks for ffmpeg, and initializes a new session."""
        self._json_log("init_start", url=self.input_url)
        self._log_init_state()
        utils.ffmpeg_check()
        self._json_log("ffmpeg_ready", url=self.input_url)
        self._json_log("session_start", url=self.input_url)
        self._init_new_session()
        self._json_log("session_ready", url=self.input_url)

    def _download_cover(self, movie_title: str, cover_url: str | None, front: bool) -> None:
        """Save cover image to disk with server timestamp"""
        if not cover_url:
            side = "front" if front else "back"
            self.logger.debug(f"No {side} cover found for {movie_title}")
            return

        cover_extension = os.path.splitext(cover_url)[1]
        if front:
            output = os.path.join(self.output_dir, f"{movie_title} front{cover_extension}")
        else:
            output = os.path.join(self.output_dir, f"{movie_title} back{cover_extension}")

        if os.path.isfile(output):
            return

        # Save file from http with server timestamp https://stackoverflow.com/a/58814151/3663357
        response = self.session.get(cover_url)
        with open(output, "wb") as f:
            f.write(response.content)
        last_modified = response.headers.get("last-modified")
        if last_modified:
            modified = time.mktime(datetime.datetime(*eut.parsedate(last_modified)[:6]).timetuple())  # type: ignore
            now = time.mktime(datetime.datetime.today().timetuple())
            os.utime(output, (now, modified))

        if os.path.isfile(output):
            self.logger.info(f"Saved cover: {output}")

    def _work_folder_cleanup(self) -> None:
        if not self.keep_segments_after_download:
            for stream in (self.manifest.audio_stream, self.manifest.video_stream):
                if stream.human_name != self.target_stream:
                    if os.path.exists(stream.path):
                        os.remove(stream.path)
                for segment_path in stream.downloaded_segments:
                    if os.path.exists(segment_path):
                        os.remove(segment_path)
            self.logger.info("Deleted temp files")

        if not os.listdir(self.movie_work_dir):
            os.rmdir(self.movie_work_dir)

    def _download_streams(self, scraped_movie: Movie) -> None:
        """Download movie streams concurrently"""
        if self.proxy and self.proxy_metadata_only:
            # disable proxies in session
            self.session.proxies = None

        segment_range = self.required_segment_range or self._segment_range(scraped_movie)

        self.logger.info(f"Downloading segments {segment_range[0]} - {segment_range[1]}")

        # Determine which streams to download
        streams_to_download = []
        for stream in (self.manifest.audio_stream, self.manifest.video_stream):
            if stream.human_name == self.target_stream or not self.target_stream:
                streams_to_download.append(stream)

        if self.json_output:
            self._download_streams_json(streams_to_download, segment_range)
        else:
            # Create progress bars in main thread; update via monitor thread to avoid multi-threaded redraw issues
            bars: list[tqdm] = []
            for idx, stream in enumerate(streams_to_download):
                bar = tqdm(
                    total=0,
                    unit='B', unit_scale=True, unit_divisor=1024,
                    desc=stream.human_name.capitalize() + " download",
                    disable=self.is_silent,
                    position=idx,
                    dynamic_ncols=True,
                    mininterval=0.2,
                    leave=False,
                )
                bars.append(bar)

            stop = Event()
            def _monitor():
                while not stop.is_set():
                    for stream, bar in zip(streams_to_download, bars):
                        if stream.total_size and bar.total != stream.total_size:
                            bar.total = stream.total_size
                        # advance bar to the exact byte count
                        current = stream.downloaded_bytes
                        if current > bar.n:
                            bar.update(current - bar.n)
                        bar.refresh()
                    time.sleep(0.2)

            mon_exec = ThreadPoolExecutor(max_workers=1)
            monitor_future = mon_exec.submit(_monitor)
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = {executor.submit(self._download_stream, stream, segment_range, no_progress_bar=True, position=idx): stream for idx, stream in enumerate(streams_to_download)}
                    for future in as_completed(futures):
                        stream = futures[future]
                        try:
                            future.result()
                        except Exception as exc:
                            self.logger.error(f"Failed to download {stream.human_name} stream: {exc}")
                            raise
            finally:
                stop.set()
                monitor_future.result(timeout=3)
                mon_exec.shutdown(wait=True, cancel_futures=True)
                for bar in bars:
                    bar.close()

    def _segment_range(self, scraped_movie: Movie) -> tuple[int, int]:
        if self.scene_n:
            try:
                scene = scraped_movie.scenes[self.scene_n - 1]
            except IndexError as exc:
                raise IndexError(f"Scene {self.scene_n} not found!") from exc
            return scene.start_segment, scene.end_segment
        start_segment = self.start_segment or 0
        end_segment = self.end_segment if self.end_segment is not None else self.manifest.total_number_of_data_segments
        return start_segment, end_segment

    def _download_streams_json(self, streams: list[MediaStream], segment_range: tuple[int, int]) -> None:
        """Download streams and log progress as JSON."""
        # Download init segments first to estimate total size
        for stream in streams:
            self._download_segment(stream, None, segment_number=None)

        # Estimate total size
        total_size = 0
        for stream in streams:
            if stream.total_size > 0:
                total_size += stream.total_size
            else:  # Fallback if init-segment size estimation failed
                num_segments = segment_range[1] - segment_range[0] + 1
                if stream.downloaded_segments and stream.downloaded_bytes > 0:
                    # Use average actual segment size from already-downloaded segments.
                    # This is much more accurate than the 1 MB/segment guess, especially
                    # for high-quality content where segments are 5-50 MB each.
                    avg_seg = stream.downloaded_bytes / len(stream.downloaded_segments)
                    total_size += int(avg_seg * num_segments)
                elif stream.media_type == 'v':
                    total_size += num_segments * 1024 * 1024  # 1 MB/seg rough fallback
                else:
                    total_size += num_segments * 100 * 1024   # 100 KB/seg audio fallback

        # Thread to monitor and update progress
        stop_monitoring = Lock()
        stop_monitoring.acquire()

        # rolling state for speed/eta. Speed uses only bytes fetched from the
        # network in this process; restored on-disk segments still count toward
        # progress but must not appear as GiB/s throughput on resume.
        last_network_bytes: int | None = None
        last_time: float | None = None
        ema_speed: float | None = None  # bytes per second
        alpha = 0.3  # smoothing factor for EMA
        t0 = time.time()

        def monitor_progress():
            nonlocal last_network_bytes, last_time, ema_speed, total_size
            while not stop_monitoring.acquire(blocking=False):
                now = time.time()
                current_downloaded = sum(s.downloaded_bytes for s in streams)
                current_network_downloaded = sum(getattr(s, "network_downloaded_bytes", 0) for s in streams)

                # Refresh total_size from streams: once data segments start downloading,
                # each stream sets total_size = first_segment_size * segment_count, which
                # is far more accurate than the rough pre-download estimate.  We only ever
                # increase total_size so it never jumps backwards mid-download.
                live_total = sum(s.total_size for s in streams if s.total_size > 0)
                if live_total > total_size:
                    total_size = live_total
                has_live_data = live_total > 0  # True once actual segment data has set total_size

                # instantaneous speed
                inst_speed = None
                if last_network_bytes is not None and last_time is not None:
                    dt = max(1e-6, now - last_time)
                    db = max(0, current_network_downloaded - last_network_bytes)
                    inst_speed = db / dt
                    if ema_speed is None:
                        ema_speed = inst_speed
                    else:
                        ema_speed = alpha * inst_speed + (1 - alpha) * ema_speed

                last_network_bytes = current_network_downloaded
                last_time = now

                speed_bps = float(ema_speed) if ema_speed is not None else None
                # reliable_total: report total_size once we trust it.
                # has_live_data = True once any data segment has set stream.total_size, which
                # is far more accurate than the rough startup estimate.
                # We do NOT use max(total_size, current_downloaded) because that would cause
                # downloaded == total when current_downloaded > total_size, locking percent
                # at 99.9% forever while the download is still in progress.
                if total_size > 0 and has_live_data and total_size > current_downloaded:
                    reliable_total = total_size  # trust live segment estimate as-is
                elif total_size > current_downloaded:
                    reliable_total = total_size  # rough estimate is still above current
                else:
                    reliable_total = None  # estimate too small; wait for live data
                eta_s = None
                percent = None
                if speed_bps and speed_bps > 0 and reliable_total and reliable_total > current_downloaded:
                    remaining = reliable_total - current_downloaded
                    eta_s = int(remaining / speed_bps)
                if reliable_total and reliable_total > 0:
                    raw_pct = current_downloaded * 100 / reliable_total
                    percent = round(min(100.0, raw_pct), 2)

                self._json_log(
                    "progress",
                    downloaded=current_downloaded,
                    total=reliable_total,
                    percent=percent,
                    speed_bps=speed_bps,
                    eta_s=eta_s,
                    elapsed_s=round(now - t0, 3),
                )
                time.sleep(0.5)  # Update twice a second

        monitor_thread = ThreadPoolExecutor(max_workers=1)
        monitor_future = monitor_thread.submit(monitor_progress)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(self._download_stream, stream, segment_range, no_progress_bar=True, position=idx): stream
                    for idx, stream in enumerate(streams)
                }
                failures = []
                for future in as_completed(futures):
                    stream = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        self.logger.error(f"Failed to download {stream.human_name} stream: {exc}")
                        failures.append(f"{stream.human_name}: {exc}")
                if failures:
                    raise RuntimeError("Required AEBN stream downloads failed: " + "; ".join(failures))

            # Return implies every required segment task succeeded.
            total_dl = sum(s.downloaded_bytes for s in streams)
            self._json_log("segments_complete", downloaded=total_dl, elapsed_s=round(time.time() - t0, 3))
        finally:
            stop_monitoring.release()
            monitor_future.result(timeout=5)
            monitor_thread.shutdown(wait=True, cancel_futures=True)

    def _download_stream(self, stream: MediaStream, segment_range: tuple[int, int], no_progress_bar: bool = False, position: int = 0) -> None:
        """Download stream segments in given range using threadpool"""
        self.logger.debug(f"Downloading {stream.human_name} stream ID: {stream.stream_id}")

        segments_to_download = range(segment_range[0], segment_range[1] + 1)

        # Track last .part file save time for periodic saves
        last_part_save = time.time()
        part_save_interval = 10  # Save .part file every 10 seconds

        download_bar = None
        if not no_progress_bar:
            download_bar = tqdm(
                total=0,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                desc=stream.human_name.capitalize() + " download",
                disable=self.is_silent,
                position=position,
                dynamic_ncols=True,
                miniters=1,
                mininterval=0.2,
                leave=False,
            )

        # Download init segment (single thread) and reflect in bar
        self._download_segment(stream, download_bar, segment_number=None)

        # Background refresher to keep bar alive even under heavy multi-threaded updates
        stop_refresh = Event()
        def _bar_refresher():
            if not download_bar:
                return
            while not stop_refresh.is_set():
                # set total if known
                if stream.total_size and download_bar.total != stream.total_size:
                    download_bar.total = stream.total_size
                # ensure bar reflects current bytes (in case thread updates were buffered)
                current = stream.downloaded_bytes
                if current > download_bar.n:
                    download_bar.update(current - download_bar.n)
                # force a refresh so the console redraws
                download_bar.refresh()
                time.sleep(0.2)

        refresher_thread = None
        if download_bar:
            refresher_thread = Thread(target=_bar_refresher, daemon=True)
            refresher_thread.start()

        def download_task(segment_num: int, max_retries: int = 30) -> int | None:
            nonlocal last_part_save
            retries = 0
            while retries <= max_retries:
                try:
                    self._download_segment(stream, download_bar, segment_number=segment_num)

                    # Periodically save .part file
                    if not self.no_part and time.time() - last_part_save > part_save_interval:
                        self._save_part_file(force=True)
                        last_part_save = time.time()

                    return segment_num
                except Exception as exc:
                    last_error = exc
                    if self.manifest_lock.acquire(blocking=False):
                        try:
                            self.manifest.process_manifest()
                            self.logger.debug(f"Manifest refreshed by segment {segment_num} (attempt {retries + 1})")
                        finally:
                            self.manifest_lock.release()
                    else:
                        self.logger.debug(f"Waiting for manifest refresh {segment_num}")
                        time.sleep(1)
                    retries += 1
                    if retries == max_retries:
                        self.logger.error(f"Max retries ({max_retries}) exceeded for segment {segment_num}: {last_error}")
                        return None

        failed_segments = []
        try:
            with ThreadPoolExecutor(max_workers=self.threads) as executor:
                futures = {executor.submit(download_task, i): i for i in segments_to_download}
                for future in as_completed(futures):
                    segment_number = futures[future]
                    try:
                        if future.result() is None:
                            failed_segments.append(segment_number)
                    except Exception as exc:
                        self.logger.error(f"Unexpected error downloading segment {segment_number}: {exc}")
                        failed_segments.append(segment_number)
            if failed_segments:
                raise RuntimeError(f"{stream.human_name} stream missing required segments after retries: {failed_segments}")
            self._validate_downloaded_stream_timeline(stream, segment_range)
        finally:
            stop_refresh.set()
            if refresher_thread:
                refresher_thread.join(timeout=2.0)
            if download_bar:
                download_bar.close()

    def _validate_downloaded_stream_timeline(
        self, stream: MediaStream, segment_range: tuple[int, int]
    ) -> None:
        """Require an ordered, complete fragment set with advancing decode time."""
        prefix = f"{stream.media_type}_{stream.stream_id}_"
        segment_paths: dict[int, str] = {}
        for path in stream.downloaded_segments:
            name = Path(path).name
            if not name.startswith(prefix) or not name.endswith(".mp4"):
                continue
            try:
                index = int(name[len(prefix):-4])
            except ValueError:
                continue
            if index in segment_paths:
                raise ValueError(f"Duplicate {stream.human_name} segment index {index}")
            segment_paths[index] = path

        expected = set(range(segment_range[0], segment_range[1] + 1))
        optional = set(stream.optional_missing_segments)
        missing = expected - set(segment_paths) - optional
        unexpected = set(segment_paths) - expected
        if missing or unexpected:
            raise ValueError(
                f"{stream.human_name} fragment inventory mismatch; "
                f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
            )
        ordered = [segment_paths[index] for index in sorted(segment_paths)]
        try:
            utils.validate_fragment_timeline(ordered)
        except ValueError as exc:
            raise ValueError(f"{stream.human_name} fragment timeline is invalid: {exc}") from exc

    def _download_segment(self, stream: MediaStream, download_bar: tqdm, segment_number: int | None = None) -> None:
        """Download and save stream segment"""
        if isinstance(segment_number, int):
            segment_name = f"{stream.media_type}_{stream.stream_id}_{segment_number}"
        else:
            segment_name = f"{stream.media_type}i_{stream.stream_id}"

        segment_url = f"{self.manifest.base_stream_url}/{segment_name}.mp4d"
        segment_path = os.path.join(self.movie_work_dir, f"{segment_name}.mp4")
        if os.path.exists(segment_path) and not self.overwrite_existing_files:
            is_init = segment_number is None
            if utils.is_mp4_fragment(segment_path, initialization=is_init):
                self.logger.debug(f"Validated {segment_name} on disk")
                if segment_path not in stream.downloaded_segments:
                    stream.downloaded_segments.append(segment_path)
                    segment_size = os.path.getsize(segment_path)
                    stream.downloaded_bytes += segment_size
                    if download_bar:
                        download_bar.update(segment_size)
                return
            self.logger.warning(f"Rejecting malformed retained fragment {segment_path}; it will be refetched")

        response = self.session.get(segment_url)

        if response.ok:
            temp_path = f"{segment_path}.tmp-{uuid.uuid4().hex}"
            try:
                with open(temp_path, "xb") as f:
                    f.write(response.content)
                    f.flush()
                    os.fsync(f.fileno())
                if not utils.is_mp4_fragment(temp_path, initialization=segment_number is None):
                    raise ValueError(f"Downloaded {segment_name} is not a complete MP4 fragment")
                os.replace(temp_path, segment_path)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            segment_size = os.path.getsize(segment_path)
            if segment_path not in stream.downloaded_segments:
                stream.downloaded_segments.append(segment_path)
            stream.downloaded_bytes = sum(
                os.path.getsize(path) for path in stream.downloaded_segments if os.path.isfile(path)
            )
            stream.network_downloaded_bytes += segment_size
            if stream.total_size == 0 and segment_number is not None:
                stream.total_size = segment_size * self.manifest.total_number_of_data_segments
                if download_bar:
                    download_bar.total = stream.total_size
            elif segment_number is not None:
                previous_total = stream.total_size
                self._refresh_stream_total_estimate(stream)
                if download_bar and stream.total_size != previous_total:
                    download_bar.total = stream.total_size
            if download_bar:
                download_bar.update(segment_size)
            self.logger.debug(f"{segment_name} saved to disk")
        elif response.status_code == 404 and segment_number == self.manifest.total_number_of_data_segments:
            # just skip if the last segment does not exist
            # segment calc returns a rounded up float which is sometimes bigger than the actual number of segments
            self.logger.debug("Last segment is 404, skipping")
            if segment_number not in stream.optional_missing_segments:
                stream.optional_missing_segments.append(segment_number)
        elif response.status_code == 403:
            raise Forbidden(f"Segment {segment_name} Download error! Response Status : {response.status_code}")
        else:
            raise RuntimeError(f"Segment {segment_name} Download error! Response Status : {response.status_code}")
