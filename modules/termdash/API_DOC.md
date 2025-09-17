# API Documentation for `termdash`

---
## File: `__init__.py`

*This file is empty or contains only imports/comments.*

---
## File: `cli.py`

### Dataclasses
#### dataclass `StatItem`
- `name: str`
- `total: int`
- `done: int`
- `status: str`
- `rate: float`
- `errs: int`

### Classes
#### class `StatItemStat`
**Methods:**
- `def render(self, logger) -> str:`

### Functions
- `def build_parser() -> argparse.ArgumentParser:`
- `def demo_multistats(args: argparse.Namespace) -> int:`
- `def demo_seemake(args: argparse.Namespace) -> int:`
- `def demo_threads(args: argparse.Namespace) -> int:`
- `def main(argv: List[str] | None) -> int:`

---
## File: `components.py`

### Classes
#### class `AggregatedLine`
**Methods:**
- `def render(self, width, logger):`

#### class `Line`
**Methods:**
- `def render(self, width: int, logger) -> str:`
- `def reset_stat(self, name, grace_period_s):`
- `def update_stat(self, name, value):`

#### class `Stat`
**Methods:**
- `def render(self, logger) -> str:`

---
## File: `dashboard.py`

### Classes
#### class `TermDash`
**Methods:**
- `def add_line(self, name, line_obj, at_top: bool):`
- `def add_separator(self):`
- `def avg_stats(self, stat_name: str, line_names: Optional[Iterable[str]]) -> float:`
- `def log(self, message, level):`
- `def read_stat(self, line_name, stat_name):`
- `def reset_stat(self, line_name, stat_name, grace_period_s):`
- `def start(self) -> 'TermDash':`
- `def stop(self):`
- `def sum_stats(self, stat_name: str, line_names: Optional[Iterable[str]]) -> float:`
- `def update_stat(self, line_name, stat_name, value):`

---
## File: `main.py`

*This file is empty or contains only imports/comments.*

---
## File: `progress.py`

### Classes
#### class `ProgressBar`
**Methods:**
- `def advance(self, delta: Union[int, float]) -> None:`
- `def bind(self) -> None:`
- `def cell(self) -> Stat:`
- `def percent(self) -> float:`
- `def set(self, current: Union[int, float]) -> None:`
- `def set_total(self, total: Union[int, float]) -> None:`

---
## File: `seemake.py`

### Classes
#### class `SeemakePrinter`
**Methods:**
- `def emit(self, message: str) -> None:`
- `def step(self, message: str) -> None:`

---
## File: `simpleboard.py`

### Classes
#### class `SimpleBoard`
**Methods:**
- `def add_row(self, name: str) -> None:`
- `def read_stat(self, line: str, stat: str):`
- `def reset(self, line: str, stat: str, grace_period_s: float) -> None:`
- `def start(self):`
- `def stop(self):`
- `def update(self, line: str, stat: str, value: Any) -> None:`

---
## File: `utils.py`

### Functions
- `def bytes_to_mib(n_bytes):`
- `def clip_ellipsis(text: str, max_chars: int) -> str:`
- `def fmt_hms(seconds):`
- `def format_bytes(mib_val):`

---
## File: `ytdlp_parser.py`

### Functions
- `def hms_to_seconds(s: str) -> Optional[int]:`
- `def human_to_bytes(num_str: str, unit_str: str) -> int:`
- `def parse_already(line: str) -> Optional[Dict]:`
- `def parse_complete(line: str) -> Optional[Dict]:`
- `def parse_destination(line: str) -> Optional[Dict]:`
- `def parse_error(line: str) -> Optional[Dict]:`
- `def parse_extract(line: str) -> Optional[Dict]:`
- `def parse_line(line: str) -> Optional[Dict]:`
- `def parse_meta(line: str) -> Optional[Dict]:`
- `def parse_progress(line: str) -> Optional[Dict]:`
- `def parse_resume(line: str) -> Optional[Dict]:`
