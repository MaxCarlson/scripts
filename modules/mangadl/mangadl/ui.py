from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from termdash import utils as td_utils

from .models import WorkerSnapshot

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
STATUS_COLORS = {
    "run": "green",
    "running": "green",
    "idle": "gray",
    "wait": "yellow",
    "retry_wait": "yellow",
    "paused": "magenta",
    "succeeded": "green",
    "skipped_archive": "cyan",
}
SITE_COLORS = {"NH": "red", "EH": "magenta", "EX": "magenta", "MD": "cyan", "H2R": "yellow"}
BACKEND_BADGES = {
    "gallery-dl": ("GD", "green"),
    "native-nhentai": ("NH", "cyan"),
    "hdporncomics": ("HD", "magenta"),
    "manga18fx": ("M18", "blue"),
}


def human_bytes(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "?"
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(number) < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}{suffix}"
        number /= 1024
    return f"{number:.1f} TiB{suffix}"


def visible_len(value: str) -> int:
    return len(ANSI_RE.sub("", value))


def clip(value: str, width: int) -> str:
    """ANSI-aware clipping that cannot spill into the next terminal row."""
    if width <= 0:
        return ""
    if visible_len(value) <= width:
        return value
    target = max(0, width - 1)
    output: list[str] = []
    visible = index = 0
    while index < len(value) and visible < target:
        match = ANSI_RE.match(value, index)
        if match:
            output.append(match.group(0))
            index = match.end()
        else:
            output.append(value[index])
            visible += 1
            index += 1
    return "".join(output) + "…\x1b[0m"


def fit_field(value: str, width: int, alignment: str = "left") -> str:
    """Clip and pad a possibly colored value to an exact visible width."""
    fitted = clip(value, width)
    padding = " " * max(0, width - visible_len(fitted))
    if alignment == "right":
        return padding + fitted
    return fitted + padding


def color_status(state: str) -> str:
    normalized = (state or "idle").lower()
    color = "red" if normalized.startswith("failed") else STATUS_COLORS.get(normalized, "bright")
    return td_utils.color_text(normalized.upper(), color)


def url_identity(url: str, site: str = "") -> tuple[str, str]:
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    path = [part for part in parts.path.split("/") if part]
    if host == "nhentai.net":
        return "NH", path[1] if len(path) >= 2 and path[0] == "g" else "search"
    if "e-hentai" in host:
        return "EH", path[-1] if path else host
    if "exhentai" in host:
        return "EX", path[-1] if path else host
    if "mangadex" in host:
        return "MD", path[-1] if path else host
    tag = (site or host.split(".")[0] or "WEB")[:4].upper()
    return tag, path[-1] if path else host or "-"


def plain_identity(url: str, site: str = "") -> str:
    tag, identifier = url_identity(url, site)
    return f"{tag}:{identifier}"


def color_identity(url: str, site: str = "") -> str:
    tag, identifier = url_identity(url, site)
    return f"{td_utils.color_text(tag, SITE_COLORS.get(tag, 'blue'))}:{identifier}"


def color_backend_badge(backend: str) -> str:
    badge, color = BACKEND_BADGES.get(backend, ("--", "gray"))
    return td_utils.color_text(badge, color)


def _progress(worker: WorkerSnapshot, width: int) -> str:
    if worker.images_total:
        ratio = max(0.0, min(1.0, worker.images_done / worker.images_total))
        filled = int(width * ratio)
        return "[" + td_utils.color_text("=" * filled, "green") + "." * (width - filled) + "]"
    pulse = worker.images_done % width
    return "[" + "." * pulse + td_utils.color_text(">", "cyan") + "." * (width - pulse - 1) + "]"


def _worker_lines(worker: WorkerSnapshot, selected: bool, width: int) -> list[str]:
    marker = td_utils.color_text(">", "cyan") if selected else " "
    identity = color_identity(worker.url, worker.site) if worker.url else td_utils.color_text("--:-", "gray")
    backend = color_backend_badge(worker.backend)
    images = f"{worker.images_done}/{worker.images_total if worker.images_total is not None else '?'} img"
    sizes = f"{human_bytes(worker.bytes_done)}/{human_bytes(worker.bytes_total)}"
    rates = f"now {human_bytes(worker.current_bps, '/s')} avg {human_bytes(worker.average_bps, '/s')}"
    items = f"{worker.current_ips:.2f} img/s"
    elapsed = td_utils.fmt_hms(worker.elapsed)
    title = worker.title if worker.title and worker.title != "gallery" else ""
    if width >= 160:
        title_width = width - 145
        return [
            f"{marker}{worker.slot:02d} "
            f"{fit_field(color_status(worker.state), 12)} "
            f"{fit_field(backend, 3)} | "
            f"{fit_field(identity, 28)} | "
            f"{fit_field(images, 12, 'right')} | "
            f"{fit_field(sizes, 18, 'right')} | "
            f"{fit_field(rates, 27, 'right')} | "
            f"{fit_field(items, 11, 'right')} | "
            f"{fit_field(elapsed, 8, 'right')} | "
            f"{fit_field(title, title_width)}"
        ]
    if width >= 78:
        first = clip(
            f"{marker}{worker.slot:02d} {color_status(worker.state)} {backend} | {identity} | {images} | {sizes} | {elapsed}",
            width,
        )
        second = clip(f"    {_progress(worker, 18)} | {rates} | {items} | {title}", width)
        return [first, second]
    first = clip(
        f"{marker}{worker.slot:02d} {color_status(worker.state)} {backend} | {identity} | {images} | {elapsed}", width
    )
    second = clip(f"    {_progress(worker, 10)} | {sizes} | {human_bytes(worker.current_bps, '/s')} | {items}", width)
    return [first, second]


def _color_log_line(line: str) -> str:
    result = ANSI_RE.sub("", line.rstrip())
    for token, color in (
        ("FAILED", "red"),
        ("ERROR", "red"),
        ("RETRY", "yellow"),
        ("SKIPPED", "cyan"),
        ("SUCCESS", "green"),
        ("START", "cyan"),
        ("DOWNLOADING", "green"),
        ("STOP", "magenta"),
    ):
        if token in result:
            result = result.replace(token, td_utils.color_text(token, color), 1)
            break
    if result.startswith("[") and (end := result.find("]")) >= 0:
        result = td_utils.color_text(result[: end + 1], "gray") + result[end + 1 :]
    return result


def read_log_lines(path: Path, count: int) -> list[str]:
    if not path.exists():
        return [f"Waiting for {path.name}"]
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]


def render_dashboard(
    run_id: str,
    counts: dict[str, int],
    workers: dict[int, WorkerSnapshot],
    selected: int = 1,
    width: int = 120,
    log_lines: list[str] | None = None,
    raw_log: bool = False,
) -> str:
    total = sum(counts.values())
    done = counts.get("succeeded", 0) + counts.get("skipped_archive", 0)
    running = counts.get("running", 0) + counts.get("leased", 0)
    failed = sum(value for key, value in counts.items() if key.startswith("failed_"))
    speed = sum(worker.current_bps for worker in workers.values())
    avg = sum(worker.average_bps for worker in workers.values())
    lines = [
        clip(
            f"{td_utils.color_text('mangadl', 'bright')} {run_id} | Manga {td_utils.color_text(f'{done}/{total}', 'green')} | Q {counts.get('queued', 0)} Run {td_utils.color_text(str(running), 'green')} Retry {td_utils.color_text(str(counts.get('retry_wait', 0)), 'yellow')} Fail {td_utils.color_text(str(failed), 'red' if failed else 'gray')}",
            width,
        ),
        clip(
            f"Speed {td_utils.color_text(human_bytes(speed, '/s'), 'cyan')} | Worker avg {human_bytes(avg, '/s')} | Downloaded {human_bytes(sum(w.bytes_done for w in workers.values()))}",
            width,
        ),
        "-" * width,
    ]
    for slot in sorted(workers):
        lines.extend(_worker_lines(workers[slot], slot == selected, width))
    if log_lines is not None:
        lines.extend(
            ["-" * width, clip(f"Worker {selected:02d} {'raw backend' if raw_log else 'activity'} log", width)]
        )
        lines.extend(clip(line if raw_log else _color_log_line(line), width) for line in log_lines)
    lines.extend(
        [
            "-" * width,
            clip(
                "Up/Down j/k Select | l Inline log | f Fullscreen | r Raw/activity | p Worker | P All | q Quit", width
            ),
        ]
    )
    return "\n".join(lines)


class ConsoleDashboard:
    def __init__(self, enabled: bool, run_id: str, log_dir: Path) -> None:
        self.enabled = enabled
        self.run_id = run_id
        self.log_dir = log_dir
        self.selected = 1
        self.inline_log = False
        self.fullscreen_log = False
        self.raw_view = False
        self.paused_all = False
        self.paused_workers: set[int] = set()

    def handle_key(self, key: str, worker_count: int) -> str | None:
        if key in {"DOWN", "j"}:
            self.selected = min(worker_count, self.selected + 1)
        elif key in {"UP", "k"}:
            self.selected = max(1, self.selected - 1)
        elif key == "l":
            self.inline_log = not self.inline_log
            self.fullscreen_log = False
        elif key == "f":
            self.fullscreen_log = not self.fullscreen_log
        elif key == "r" and (self.inline_log or self.fullscreen_log):
            self.raw_view = not self.raw_view
        elif key == "p":
            self.paused_workers.symmetric_difference_update({self.selected})
        elif key == "P":
            self.paused_all = not self.paused_all
        elif key in {"q", "\x03"}:
            raise KeyboardInterrupt
        return None

    def _log_path(self) -> Path:
        folder = "raw" if self.raw_view else "workers"
        suffix = "-gallery-dl.log" if self.raw_view else ".log"
        return self.log_dir / folder / f"worker-{self.selected:02d}{suffix}"

    def render(self, counts: dict[str, int], workers: dict[int, WorkerSnapshot]) -> None:
        if not self.enabled:
            return
        terminal = os.get_terminal_size() if sys_stdout_tty() else os.terminal_size((120, 30))
        width = max(40, min(180, terminal.columns))
        if self.fullscreen_log:
            lines = read_log_lines(self._log_path(), max(4, terminal.lines - 3))
            body = [clip(line if self.raw_view else _color_log_line(line), width) for line in lines]
            text = "\n".join(
                [clip(f"Worker {self.selected:02d} {'raw backend' if self.raw_view else 'activity'} log", width)]
                + body
                + ["", clip("f Back | r Raw/activity | q Quit", width)]
            )
        else:
            log_lines = None
            if self.inline_log:
                base_rows = len(render_dashboard(self.run_id, counts, workers, self.selected, width).splitlines())
                available_log_rows = max(1, terminal.lines - base_rows - 2)
                log_lines = read_log_lines(self._log_path(), available_log_rows)
            text = render_dashboard(self.run_id, counts, workers, self.selected, width, log_lines, self.raw_view)
        print("\x1b[H\x1b[2J" + text, end="", flush=True)


def sys_stdout_tty() -> bool:
    import sys

    return sys.stdout.isatty()
