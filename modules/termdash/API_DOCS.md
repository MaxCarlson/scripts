# TermDash API Documentation

This document is a detailed, LLM-ready API reference for the `termdash` library. It describes core classes, rendering behavior, concurrency, CLI demos, and examples. It is designed to be copied into another tool without needing the full source tree.

---

## Table of Contents

- Key Concepts
- TermDash Class
  - Constructor
  - Public Methods
  - Rendering & Layout Notes
  - Concurrency & Safety
- Stat Class
  - Constructor
  - Public Methods
  - Coloring & Staleness
- Line Class
  - Constructor
  - Public Methods
- AggregatedLine Class
  - Constructor
  - Public Methods
- ProgressBar
  - Constructor
  - Methods
  - Examples
- SimpleBoard
  - Constructor
  - Methods
  - Example
- SeemakePrinter (CMake-style output)
  - Constructor
  - Methods
  - Kinds & Colors
  - Example
- CLI Demos
  - Commands & Flags
  - Use Cases Covered
- Utilities
- FAQ

---

## Key Concepts

- **In-place rows**: TermDash pins several lines at the top of the terminal and updates them in place. Normal logs continue to scroll *below* the dashboard.
- **Stats (`Stat`)**: The smallest renderable unit (a cell). Each `Stat` owns a name, formatting rules, and optional color logic.
- **Lines (`Line`)**: An ordered set of `Stat` cells rendered on one row.
- **Width-stable cells**: Use `no_expand=True` (and optionally `display_width=N`) for a cell that should not affect column alignment. This is perfect for fixed-width widgets like progress bars.
- **Alignment**: When `align_columns=True`, TermDash splits each line into columns around a separator (default `"|"`) and aligns columns across *all* lines.
- **No full-screen wipe**: TermDash uses minimal cursor control; it does not clear the entire screen or take over the TTY—your scrollback remains intact.
- **Thread-safe**: You can update stats from worker threads.

---

## TermDash Class

The `TermDash` class manages a live dashboard: adding lines, updating stats, and rendering the pinned rows while a normal scrolling region remains available for logs.

### TermDash Constructor

    TermDash(
        refresh_rate: float = 0.1,
        log_file: Optional[str] = None,
        status_line: bool = True,
        debug_locks: bool = False,
        debug_rendering: bool = False,
        align_columns: bool = True,
        column_sep: str = "|",
        min_col_pad: int = 2,
        max_col_width: Optional[int] = None,
        enable_separators: bool = False,
        separator_style: str = "rule",
        separator_custom: Optional[str] = None,
        reserve_extra_rows: int = 6
    )

**Parameters**

- `refresh_rate`: Dashboard refresh interval (seconds).
- `log_file`: Optional file path for internal logs (None disables).
- `status_line`: When `True`, reserves a bottom line for logging/scanning output.
- `debug_locks`, `debug_rendering`: Extra internal diagnostics (verbose).
- `align_columns`: When `True`, columns split by `column_sep` are globally aligned.
- `column_sep`: The visual column separator string (default `"|"`).
- `min_col_pad`: Spaces around `column_sep` when aligning.
- `max_col_width`: Truncate columns wider than this width with an ellipsis (`None` = no truncation).
- `enable_separators`: Enables `add_separator()` rows (horizontal rules).
- `separator_style`: Preset for separators (`"rule"`, `"dash"`, `"dot"`)—overridden by `separator_custom`.
- `separator_custom`: Explicit ASCII pattern for separators; overrides `separator_style`.
- `reserve_extra_rows`: Extra terminal rows reserved below the overlay to avoid scroll jitter.

**Context Management**

- Use as a context manager (`with TermDash(...): ...`) or call `start()` / `stop()` explicitly.

### TermDash Public Methods

- `add_line(name: str, line_obj: Line, at_top: bool = False) -> None`  
  Registers a `Line`. When `at_top=True`, inserts it before the current lines.

- `add_separator() -> None`  
  Inserts a horizontal rule (only if `enable_separators=True`).

- `update_stat(line_name: str, stat_name: str, value: Any) -> None`  
  Updates a specific `Stat` value by name within a line.

- `reset_stat(line_name: str, stat_name: str, grace_period_s: int = 0) -> None`  
  Resets a `Stat` value and (optionally) suppresses stale warnings for `grace_period_s`.

- `read_stat(line_name: str, stat_name: str) -> Optional[Any]`  
  Safely reads a stat value (returns `None` if not found).

- `sum_stats(stat_name: str, line_names: Optional[Iterable[str]] = None) -> float`  
  Sums numeric values of `stat_name` across lines (non-numeric treated as `0`).

- `avg_stats(stat_name: str, line_names: Optional[Iterable[str]] = None) -> float`  
  Averages numeric values of `stat_name` across lines (non-numeric treated as `0`).

- `log(message: str, level: str = "info") -> None`  
  Emits a scrolling line under the dashboard without disturbing pinned rows.

### Rendering & Layout Notes

- Column widths are computed across visible lines. A `Stat` with `no_expand=True` is excluded from width expansion logic.
- For constrained terminals, shorten prefixes and units or set `max_col_width`.
- ANSI coloring is supported; control sequences are considered during width calculations.

### Concurrency & Safety

- `update_stat` and `reset_stat` are safe to call from worker threads.
- Do not perform blocking work inside rendering callbacks.

**Minimal example**

    from termdash import TermDash, Line, Stat
    import time

    with TermDash(status_line=True) as td:
        td.add_line("hdr", Line("hdr",
            stats=[Stat("title", "Demo", format_string="{}", color="1;36")],
            style="header"))
        td.add_line("row", Line("row", stats=[
            Stat("left", "L"),
            Stat("right", "R"),
        ]))
        for i in range(5):
            td.update_stat("row", "right", f"tick {i}")
            time.sleep(0.2)

---

## Stat Class

Represents a single cell (metric) with its own formatting and color rules.

### Stat Constructor

    Stat(
        name: str,
        value: Any,
        prefix: str = "",
        format_string: str = "{}",
        unit: str = "",
        color: Union[str, Callable[[Any], str]] = "",
        warn_if_stale_s: int = 0,
        no_expand: bool = False,
        display_width: Optional[int] = None
    )

**Fields & Behavior**

- `prefix`: Text to prepend (e.g., `"Done: "`).
- `format_string`: Python format (e.g., `"{:.2f}"`).
- `unit`: Text to append (e.g., `"MiB/s"`).
- `color`: ANSI code like `"0;32"` or callable `value -> code`.
- `warn_if_stale_s`: Optional staleness window; renderers can dim/mark stale values.
- `no_expand`: Exclude this cell from column width calculations (fixed-width cell).
- `display_width`: Soft width hint when `no_expand=True`.

### Stat Public Methods

- `render(logger=None) -> str`  
  Returns an ANSI string representing the cell with prefix, formatted value, unit, and color applied.

**Example**

    Stat("rate", 0.0, prefix="Rate: ", format_string="{:.1f}", unit="MiB/s",
         color=lambda v: "0;32" if v < 80 else "1;31")

---

## Line Class

Represents a single renderable row composed of `Stat` objects.

### Line Constructor

    Line(
        name: str,
        stats: Optional[List[Stat]] = None,
        style: str = "default",
        sep_pattern: str = "-"
    )

**Parameters**

- `name`: Unique name for the line.
- `stats`: List of `Stat` cells in order.
- `style`: `"default"` joins stats; `"header"` colors the line (bright cyan); `"separator"` draws a horizontal rule using `sep_pattern`.
- `sep_pattern`: Pattern used when `style="separator"`.

### Line Public Methods

- `update_stat(name: str, value: Any) -> None`  
  Change the cell’s contents by stat name.

- `reset_stat(name: str, grace_period_s: int = 0) -> None`  
  Reset a stat and optionally suppress staleness warnings briefly.

- `render(width: int, logger=None) -> str`  
  Render to an ANSI string under a given width.

---

## AggregatedLine Class

A specialized `Line` that aggregates numeric stats from a set of other `Line`s.

### AggregatedLine Constructor

    AggregatedLine(
        name: str,
        source_lines: Dict[str, Line],
        stats: Optional[List[Stat]] = None,
        style: str = "default",
        sep_pattern: str = "-"
    )

**Behavior**

- At render time, each `Stat` in the aggregated line is recomputed as the sum of the same-named stat across `source_lines`. Non-numeric values are treated as 0.

### AggregatedLine Public Methods

- `render(width: int, logger=None) -> str`  
  Recompute then render to an ANSI string.

---

## ProgressBar

A fixed-width textual progress bar that plugs into a `Line` as a `Stat` and preserves stable alignment.

### ProgressBar Constructor

    ProgressBar(
        name: str,
        total: float | int,
        current: float | int = 0,
        *,
        width: int = 30,
        charset: str = "block",     # "block" uses █/░, "ascii" uses #/-
        show_percent: bool = True
    )

**Notes**

- The provided `Stat` is created with `no_expand=True` and `display_width=width`.
- `show_percent=True` overlays centered percent text inside the bar without changing its width.

### ProgressBar Methods

- `cell() -> Stat`  
  The stat to insert in a `Line`.

- `bind(current_fn: Callable[[], float], total_fn: Optional[Callable[[], float]] = None) -> None`  
  Lazily read progress values from callables at render time.

- `set_total(total: float | int) -> None`  
- `set(current: float | int) -> None`  
- `advance(delta: float | int = 1) -> None`  
- `percent() -> float` — current percentage in `[0, 100]`.

### ProgressBar Examples

    from termdash import Line, Stat
    from termdash.progress import ProgressBar

    # Manual control
    pb = ProgressBar("bar", total=200, width=24)
    line = Line("downloads", stats=[Stat("done", 0, prefix="Done: "), pb.cell()])

    # Binding to external state
    state = {"done": 0, "total": 200}
    pb.bind(current_fn=lambda: state["done"], total_fn=lambda: state["total"])

---

## SimpleBoard

A tiny row-builder on top of `TermDash` for quick “stats + bars” layouts. Ideal when you want to prototype without manipulating `Line` objects directly.

### SimpleBoard Constructor

    SimpleBoard(title: str | None = None, **termdash_kwargs)

### SimpleBoard Methods

- `add_row(name: str, *cells: Stat) -> None`
- `update(line: str, stat: str, value: Any) -> None`
- `reset(line: str, stat: str, grace_period_s: float = 0) -> None`
- `read_stat(line: str, stat: str)`
- Context manager compatible (`with SimpleBoard(...) as b:`) or `start()/stop()`.

### SimpleBoard Example

    from termdash.simpleboard import SimpleBoard
    from termdash.progress import ProgressBar
    from termdash import Stat

    board = SimpleBoard(title="Demo")
    board.add_row("r1", Stat("done", 0, prefix="Done: "), Stat("total", 10, prefix="Total: "))
    pb = ProgressBar("bar1", total=10, width=24)
    pb.bind(current_fn=lambda: board.read_stat("r1", "done"),
            total_fn=lambda: board.read_stat("r1", "total"))
    board.add_row("r2", pb.cell())

---

## SeemakePrinter (CMake-style output)

Produces CMake-like scrolling lines with a `[ xx%]` prefix and colored action text. Optionally shows a live **bottom progress row** with `[ xx% ] + progress bar + i/N + label`.

### SeemakePrinter Constructor

    SeemakePrinter(
        total: int,
        *,
        td: TermDash | None = None,
        with_bar: bool = False,
        bar_width: int = 28,
        label: str = "Build",
        out: TextIO | None = None        # plain mirror stream (no ANSI)
    )

**Parameters**

- `total`: Number of steps.
- `td`: Optional `TermDash` instance. If omitted, lines are printed/streamed only.
- `with_bar`: When `True`, creates a bottom, fixed row named `"seemake:progress"`.
- `bar_width`: Width of the progress bar on the bottom row.
- `label`: Free-text label cell for the bottom row.
- `out`: Optional stream to mirror plain (no ANSI) output—useful for tests/log files.

### SeemakePrinter Methods

- `step(message: str, *, kind: str = "info", weight: int = 1) -> None`  
  Advance progress by `weight` and emit a line with a `[ xx%]` prefix and a colored message.

- `emit(message: str, *, kind: str = "info", percent: Optional[int] = None) -> None`  
  Emit a line without advancing. If `percent` is `None`, the current progress is used.

**Bottom Progress Row (with `with_bar=True`)**

- A dedicated line `"seemake:progress"` is created with cells:
  - `pct` — fixed `[ xx%]`
  - `bar` — `ProgressBar` (with `show_percent=False`)
  - `count` — text `"i/N"`
  - `label` — free text label

### Kinds & Colors

    scan     -> bright magenta
    build    -> blue
    compile  -> blue
    link     -> green
    install  -> cyan
    test     -> bright yellow
    success  -> bright green
    warn     -> bright yellow
    error    -> bright red
    info     -> white

### SeemakePrinter Example

    from termdash import TermDash
    from termdash.seemake import SeemakePrinter

    td = TermDash(status_line=True)
    with td:
        sm = SeemakePrinter(total=4, td=td, with_bar=True, bar_width=24, label="Build")
        sm.step("Scanning dependencies of target core", kind="scan")
        sm.step("Building CXX object core/foo.o", kind="build")
        sm.step("Linking CXX executable app", kind="link")
        sm.step("Built target app", kind="success")

---

## CLI Demos

The package installs a `termdash` command. You can also run `python -m termdash`.

Common flags across demos:
- `--plain` : run without live dashboard (print text only; good for CI).
- `--clear` : skip the final plain snapshot (default is to *keep* it).
- `--seed`  : RNG seed for deterministic runs.

### Commands & Flags

- **progress**  
  `--total/-t`, `--interval/-i`, `--width/-w`, `--ascii`, `--no-percent`, `--plain`, `--clear`

- **stats**  
  `--duration/-d`, `--update/-u`, `--width/-w`, `--plain`, `--clear`

- **multistats**  
  `--processes/-p`, `--proc {ytdlp,copy,compute}`, `--duration/-d`, `--update/-u`, `--width/-w`, `--plain`, `--clear`

- **threads**  
  `--threads/-n`, `--duration/-d`, `--update/-u`, `--width/-w`, `--plain`, `--clear`

- **seemake**  
  `--steps/-s`, `--interval/-i`, `--with-bar`, `--width/-w`, `--plain`, `--clear`

### Use Cases Covered

- Fixed-width progress bars (ASCII/Unicode), with or without in-bar percent.
- Two-row “stats + bound progress bar” layouts.
- Many concurrent simulated processes (yt-dlp/copy/compute profiles) with independent rows.
- Multi-threaded updates (each thread owns a row) to show thread safety.
- CMake-style build output plus optional bottom progress line.

---

## Utilities

When present in your build (import from `termdash.utils`):

- `format_bytes(n) -> str` — human-readable bytes.
- `fmt_hms(seconds) -> str` — `HH:MM:SS`.
- `bytes_to_mib(n) -> float` — MiB conversion helper.
- `clip_ellipsis(text, max_width) -> str` — safe truncation with ellipsis.

---

## FAQ

**Q: How do I keep a cell from stretching the columns?**  
A: Use `no_expand=True`, and set `display_width` if you want a specific width.

**Q: Does TermDash clear the whole screen?**  
A: No. It updates only the pinned rows. Your scrollback remains intact. The CLI also avoids clearing and prints a final snapshot unless `--clear` is specified.

**Q: Can I update stats from threads?**  
A: Yes. `update_stat` is thread-safe. See the `threads` CLI demo.

**Q: How do I log normal lines while the dashboard is up?**  
A: Use `td.log("message")`. It writes into the scrolling region below the pinned rows.

**Q: What’s the simplest way to build a tiny board with bars?**  
A: Use `SimpleBoard` and drop `ProgressBar.cell()` where you want fixed-width bars.

---
