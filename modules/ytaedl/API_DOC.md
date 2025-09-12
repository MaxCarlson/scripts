# API Documentation for `ytaedl`

---
## File: `__init__.py`

*This file is empty or contains only imports/comments.*

---
## File: `__main__.py`

*This file is empty or contains only imports/comments.*

---
## File: `ytaedl/__init__.py`

*This file is empty or contains only imports/comments.*

---
## File: `ytaedl/cli.py`

### Functions
- `def build_parser() -> argparse.ArgumentParser:`
- `def cli_main(argv: Optional[List[str]]) -> int:`
- `def main(argv: Optional[List[str]]) -> int:`

---
## File: `ytaedl/downloaders.py`

### Classes
#### class `AebnDownloader`
**Methods:**
- `def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:`

#### class `DownloaderBase`
**Methods:**
- `def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:`

#### class `YtDlpDownloader`
**Methods:**
- `def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:`

### Functions
- `def abort_requested() -> bool:`
- `def get_downloader(url: str, config: DownloaderConfig) -> DownloaderBase:`
- `def request_abort() -> None:`
- `def terminate_all_active_procs() -> None:`

---
## File: `ytaedl/io.py`

### Functions
- `def expand_url_dirs(dirs: Iterable[Path]) -> List[Path]:`
- `def load_archive(path: Path) -> Set[str]:`
- `def read_urls_from_files(paths: Iterable[Path]) -> List[str]:`
- `def write_to_archive(path: Path, url: str) -> None:`

---
## File: `ytaedl/models.py`

### Dataclasses
#### dataclass `DownloadItem`
- `id: int`
- `url: str`
- `output_dir: Path`
- `source: Optional[URLSource]`
- `quality: str`
- `rate_limit: Optional[str]`
- `retries: int`
- `is_scene: bool`
- `scene_index: Optional[int]`
- `extra_args: List[str]`
- `extra_ytdlp_args: List[str]`
- `extra_aebn_args: List[str]`

#### dataclass `DownloadResult`
- `item: DownloadItem`
- `status: DownloadStatus`
- `final_path: Optional[Path]`
- `error_message: Optional[str]`
- `size_bytes: Optional[int]`
- `duration: float`
- `log_output: List[str]`

### Classes
#### class `AlreadyEvent`

#### class `DestinationEvent`

#### class `DownloadStatus`

#### class `DownloaderConfig`

#### class `EventType`

#### class `FinishEvent`

#### class `LogEvent`

#### class `MetaEvent`

#### class `ProgressEvent`

#### class `StartEvent`

#### class `URLSource`

---
## File: `ytaedl/old/orchestrator.py`

### Dataclasses
#### dataclass `CountsSnapshot`
- `version: int`
- `computed_at: str`
- `sources: Dict[str, Dict[str, str]]`
- `files: Dict[str, dict]`

### Classes
#### class `URLFileInfo`

### Functions
- `def get_next_item_id():`
- `def main(argv: Optional[List[str]]) -> int:`
- `def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:`

---
## File: `ytaedl/old/ui.py`

### Classes
#### class `DownloadItemRef`
**Methods:**
- `def from_event(cls, ev: Any) -> 'DownloadItemRef':`

#### class `SimpleUI`
**Methods:**
- `def advance_scan(self, delta: int):`
- `def begin_scan(self, num_workers: int, total_files: int):`
- `def end_scan(self):`
- `def handle_event(self, event: Any):`
- `def pump(self):`
- `def reset_worker_stats(self, slot: int) -> None:`
- `def set_footer(self, text: str):`
- `def set_paused(self, paused: bool):`
- `def set_scan_slot(self, slot: int, label: str):`
- `def summary(self, stats: Dict[str, int], elapsed: float):`

#### class `TermdashUI`
**Methods:**
- `def advance_scan(self, delta: int):`
- `def begin_scan(self, num_workers: int, total_files: int):`
- `def end_scan(self):`
- `def handle_event(self, event: Any):`
- `def pump(self):`
- `def reset_worker_stats(self, slot: int):`
- `def scan_file_done(self, urlfile: str | Path, total: int, downloaded: int, bad: int) -> None:`
- `def set_footer(self, text: str):`
- `def set_paused(self, paused: bool):`
- `def set_scan_log_path(self, path: str | Path) -> None:`
- `def set_scan_slot(self, slot: int, label: str):`
- `def summary(self, stats: Dict[str, int], elapsed: float):`

#### class `UIBase`
**Methods:**
- `def advance_scan(self, delta: int) -> None:`
- `def begin_scan(self, num_workers: int, total_files: int) -> None:`
- `def end_scan(self) -> None:`
- `def handle_event(self, event: Any) -> None:`
- `def pump(self) -> None:`
- `def reset_worker_stats(self, slot: int) -> None:`
- `def set_footer(self, text: str) -> None:`
- `def set_paused(self, paused: bool) -> None:`
- `def set_scan_slot(self, slot: int, label: str) -> None:`
- `def summary(self, stats: Dict[str, int], elapsed: float) -> None:`

### Functions
- `def make_ui(num_workers: int, total_urls: int) -> UIBase:`

---
## File: `ytaedl/orchestrator.py`

### Dataclasses
#### dataclass `CountsSnapshot`
- `total_urls: int`
- `completed: int`
- `failed: int`
- `already: int`
- `active: int`
- `queued: int`
- `files: Dict[str, Dict[str, object]]`

### Functions
- `def main(argv: Optional[List[str]]) -> int:`
- `def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:`
- `def run_single_ytdlp(logger: RunLogger, url: str, url_index: int, out_tpl: str, extra_args: Optional[List[str]], retries: int) -> Tuple[str, str]:`

---
## File: `ytaedl/parsers.py`

### Functions
- `def parse_aebndl_line(line: str) -> Optional[Dict[str, object]]:`
- `def parse_ytdlp_line(line: str) -> Optional[Dict]:`
- `def sanitize_line(s: str) -> str:`

---
## File: `ytaedl/runlogger.py`

### Classes
#### class `RunLogger`
**Methods:**
- `def close(self):`
- `def finish(self, url_index: int, url: str, status: str, note: str):`
- `def info(self, msg: str):`
- `def start(self, url_index: int, url: str) -> int:`

---
## File: `ytaedl/runner.py`

### Classes
#### class `DownloadRunner`
**Methods:**
- `def run_from_files(self, url_files: Iterable[Path], base_out: Path, per_file_subdirs: bool) -> None:`

---
## File: `ytaedl/scanner.py`

### Dataclasses
#### dataclass `SimpleCounts`
- `url_file: str`
- `stem: str`
- `source: str`
- `out_dir: str`
- `url_count: int`
- `downloaded: int`
- `bad: int`
- `remaining: int`
- `viable_checked: bool`
- `url_mtime: int`
- `url_size: int`

### Functions
- `def load_counts_json(path: Path) -> Dict[str, SimpleCounts]:`
- `def save_counts_json(path: Path, records: Dict[str, SimpleCounts]) -> None:`
- `def scan_url_file_ae(url_file: Path, out_base: Path, exts: Iterable[str]) -> SimpleCounts:`
- `def scan_url_file_main(url_file: Path, out_base: Path, exts: Iterable[str]) -> SimpleCounts:`

---
## File: `ytaedl/ui.py`

### Classes
#### class `DownloadItemRef`
**Methods:**
- `def from_event(cls, ev: Any) -> 'DownloadItemRef':`

#### class `SimpleUI`
**Methods:**
- `def advance_scan(self, delta: int):`
- `def begin_scan(self, num_workers: int, total_files: int):`
- `def end_scan(self):`
- `def handle_event(self, event: Any):`
- `def pump(self):`
- `def reset_worker_stats(self, slot: int) -> None:`
- `def set_footer(self, text: str):`
- `def set_paused(self, paused: bool):`
- `def set_scan_slot(self, slot: int, label: str):`
- `def summary(self, stats: Dict[str, int], elapsed: float):`

#### class `TermdashUI`
**Methods:**
- `def advance_scan(self, delta: int):`
- `def begin_scan(self, num_workers: int, total_files: int):`
- `def end_scan(self):`
- `def handle_event(self, event: Any):`
- `def pump(self):`
- `def reset_worker_stats(self, slot: int):`
- `def scan_file_done(self, urlfile: str | Path, total: int, downloaded: int, bad: int) -> None:`
- `def set_footer(self, text: str):`
- `def set_paused(self, paused: bool):`
- `def set_scan_log_path(self, path: str | Path) -> None:`
- `def set_scan_slot(self, slot: int, label: str):`
- `def summary(self, stats: Dict[str, int], elapsed: float):`

#### class `UIBase`
**Methods:**
- `def advance_scan(self, delta: int) -> None:`
- `def begin_scan(self, num_workers: int, total_files: int) -> None:`
- `def end_scan(self) -> None:`
- `def handle_event(self, event: Any) -> None:`
- `def pump(self) -> None:`
- `def reset_worker_stats(self, slot: int) -> None:`
- `def set_footer(self, text: str) -> None:`
- `def set_paused(self, paused: bool) -> None:`
- `def set_scan_slot(self, slot: int, label: str) -> None:`
- `def summary(self, stats: Dict[str, int], elapsed: float) -> None:`

### Functions
- `def make_ui(num_workers: int, total_urls: int) -> UIBase:`

---
## File: `ytaedl/ui_scan.py`

*This file is empty or contains only imports/comments.*

---
## File: `ytaedl/url_parser.py`

### Functions
- `def get_url_slug(url: str) -> str:`
- `def is_aebn_url(url: str) -> bool:`
- `def parse_aebn_scene_controls(url: str) -> Dict[str, Optional[str]]:`
