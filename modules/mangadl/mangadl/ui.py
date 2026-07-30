from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from termdash import utils as td_utils

from .models import WorkerSnapshot

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ACTIVITY_LOG_RE = re.compile(
    r"^(?P<wall>\[[^\]]+\])(?P<elapsed>\[[^\]]+\])\s+"
    r"(?P<status>\S+)\s+(?P<payload>.*)$"
)
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
SITE_COLORS = {
    "NH": "red",
    "EH": "magenta",
    "EX": "magenta",
    "MD": "cyan",
    "M18": "blue",
    "H2R": "yellow",
}
BACKEND_BADGES = {
    "gallery-dl": ("GD", "green"),
    "native-nhentai": ("NH", "cyan"),
    "hdporncomics": ("HD", "magenta"),
    "manga18fx": ("M18", "blue"),
}


@dataclass(frozen=True, slots=True)
class DashboardRuntime:
    active_workers: int
    target_workers: int
    image_workers: int
    aggregate: int
    budget: int
    logical_cpus: int
    notice: str = ""


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
    if host in {"manga18fx.com", "manga18fx.net"}:
        return "M18", path[-1] if path else host
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


def _image_count(worker: WorkerSnapshot) -> str:
    if worker.images_total is None:
        return f"{worker.images_done} img"
    return f"{worker.images_done}/{worker.images_total} img"


def _byte_count(worker: WorkerSnapshot) -> str:
    if worker.bytes_total is None:
        return human_bytes(worker.bytes_done)
    return f"{human_bytes(worker.bytes_done)}/{human_bytes(worker.bytes_total)}"


def _progress(worker: WorkerSnapshot, width: int) -> str:
    if worker.images_total:
        ratio = max(0.0, min(1.0, worker.images_done / worker.images_total))
        filled = int(width * ratio)
        return "[" + td_utils.color_text("=" * filled, "green") + "." * (width - filled) + "]"
    pulse = int(max(0.0, worker.elapsed) * 4) % max(1, width)
    return "[" + "." * pulse + td_utils.color_text(">", "cyan") + "." * (width - pulse - 1) + "]"


def _progress_label(worker: WorkerSnapshot) -> str:
    if worker.images_total:
        ratio = max(0.0, min(1.0, worker.images_done / worker.images_total))
        return f"{ratio * 100:5.1f}%"
    return "activity"


def _worker_lines(worker: WorkerSnapshot, selected: bool, width: int) -> list[str]:
    marker = td_utils.color_text(">", "cyan") if selected else " "
    identity = color_identity(worker.url, worker.site) if worker.url else td_utils.color_text("--:-", "gray")
    backend = color_backend_badge(worker.backend)
    images = _image_count(worker)
    sizes = _byte_count(worker)
    now_rate = human_bytes(worker.current_bps, "/s")
    average_rate = human_bytes(worker.average_bps, "/s")
    items = f"{worker.current_ips:.2f} img/s"
    elapsed = td_utils.fmt_hms(worker.elapsed)
    title = worker.title if worker.title and worker.title != "gallery" else ""
    message = worker.message or title or "waiting for progress"

    if width >= 160:
        first = " | ".join(
            (
                fit_field(f"{marker}{worker.slot:02d}", 3),
                fit_field(color_status(worker.state), 10),
                fit_field(backend, 3),
                fit_field(identity, 34),
                fit_field(images, 14, "right"),
                fit_field(sizes, 14, "right"),
                fit_field(now_rate, 13, "right"),
                fit_field(average_rate, 13, "right"),
                fit_field(items, 11, "right"),
                fit_field(elapsed, 8, "right"),
            )
        )
        first = fit_field(first, width)
        bar_width = max(12, min(72, width - 34))
        second = fit_field(
            f"    {_progress(worker, bar_width)} {_progress_label(worker):>8} | {message}",
            width,
        )
        return [first, second]

    if width >= 78:
        first = clip(
            f"{marker}{worker.slot:02d} {color_status(worker.state)} {backend} | "
            f"{identity} | {images} | {sizes} | {elapsed}",
            width,
        )
        bar_width = max(12, min(36, width - 38))
        second = clip(
            f"    {_progress(worker, bar_width)} {_progress_label(worker):>8} | "
            f"now {now_rate} | avg {average_rate} | {items}",
            width,
        )
        return [first, second]

    first = clip(
        f"{marker}{worker.slot:02d} {color_status(worker.state)} {backend} | "
        f"{identity} | {images} | {elapsed}",
        width,
    )
    bar_width = max(8, min(18, width - 26))
    second = clip(
        f"    {_progress(worker, bar_width)} {_progress_label(worker):>8} | {now_rate}",
        width,
    )
    return [first, second]


def _normalize_unknown_totals(value: str) -> str:
    value = re.sub(r"\b(\d+)/\?\s+img\b", r"\1 img", value)
    value = re.sub(r"\b([^|]+?)/\?(?=\s*(?:\||$))", lambda match: match.group(1).rstrip(), value)
    return value


def _format_activity_log_line(line: str) -> str:
    """Render persisted activity records with stable columns."""
    result = ANSI_RE.sub("", line.rstrip())
    match = ACTIVITY_LOG_RE.match(result)
    if match is None:
        return _normalize_unknown_totals(result)

    payload = _normalize_unknown_totals(match.group("payload").strip())
    fields = re.split(r"\s{2,}", payload, maxsplit=4) if payload else []
    identity = fields[0] if fields else ""
    images = fields[1] if len(fields) > 1 else ""
    size = fields[2] if len(fields) > 2 else ""
    rate = fields[3] if len(fields) > 3 else ""
    detail = fields[4] if len(fields) > 4 else ""

    prefix = match.group("wall") + match.group("elapsed")
    status = match.group("status")
    return (
        f"{fit_field(prefix, 25)} "
        f"{fit_field(status, 17)} | "
        f"{fit_field(identity, 38)} | "
        f"{fit_field(images, 14, 'right')} | "
        f"{fit_field(size, 12, 'right')} | "
        f"{fit_field(rate, 16, 'right')}"
        + (f" | {detail}" if detail else "")
    ).rstrip()


def _color_log_line(line: str) -> str:
    result = _format_activity_log_line(line)
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
    if result.startswith("[") and (end := result.find("]", result.find("]") + 1)) >= 0:
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
    runtime: DashboardRuntime | None = None,
) -> str:
    total = sum(counts.values())
    done = counts.get("succeeded", 0) + counts.get("skipped_archive", 0)
    running = counts.get("running", 0) + counts.get("leased", 0)
    failed = sum(value for key, value in counts.items() if key.startswith("failed_"))
    speed = sum(worker.current_bps for worker in workers.values())
    avg = sum(worker.average_bps for worker in workers.values())
    lines = [
        clip(
            f"{td_utils.color_text('mangadl', 'bright')} {run_id} | "
            f"Manga {td_utils.color_text(f'{done}/{total}', 'green')} | "
            f"Q {counts.get('queued', 0)} "
            f"Run {td_utils.color_text(str(running), 'green')} "
            f"Retry {td_utils.color_text(str(counts.get('retry_wait', 0)), 'yellow')} "
            f"Fail {td_utils.color_text(str(failed), 'red' if failed else 'gray')}",
            width,
        )
    ]
    if runtime is not None:
        lines.append(
            clip(
                f"Workers {runtime.active_workers}/{runtime.target_workers} | "
                f"Images/worker {runtime.image_workers} | "
                f"Active concurrency {runtime.aggregate}/{runtime.budget} | "
                f"Logical CPUs {runtime.logical_cpus}",
                width,
            )
        )
    lines.append(
        clip(
            f"Speed {td_utils.color_text(human_bytes(speed, '/s'), 'cyan')} | "
            f"Worker avg {human_bytes(avg, '/s')} | "
            f"Downloaded {human_bytes(sum(w.bytes_done for w in workers.values()))}",
            width,
        )
    )
    if runtime is not None and runtime.notice:
        lines.append(clip(f"Tuning: {runtime.notice}", width))
    lines.append("-" * width)

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
                "Up/Down j/k Select | +/- Workers | [/] Image threads | "
                "l Log | f Fullscreen | r Raw | p/P Pause | q Quit",
                width,
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
        elif key in {"+", "="}:
            return "workers_up"
        elif key == "-":
            return "workers_down"
        elif key == "]":
            return "images_up"
        elif key == "[":
            return "images_down"
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

    def render(
        self,
        counts: dict[str, int],
        workers: dict[int, WorkerSnapshot],
        runtime: DashboardRuntime | None = None,
    ) -> None:
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
                base_rows = len(
                    render_dashboard(
                        self.run_id,
                        counts,
                        workers,
                        self.selected,
                        width,
                        runtime=runtime,
                    ).splitlines()
                )
                available_log_rows = max(1, terminal.lines - base_rows - 2)
                log_lines = read_log_lines(self._log_path(), available_log_rows)
            text = render_dashboard(
                self.run_id,
                counts,
                workers,
                self.selected,
                width,
                log_lines,
                self.raw_view,
                runtime,
            )
        print("\x1b[H\x1b[2J" + text, end="", flush=True)


def sys_stdout_tty() -> bool:
    import sys

    return sys.stdout.isatty()
