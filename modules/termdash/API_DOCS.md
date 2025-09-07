# TermDash API Documentation

This document provides a detailed API reference for the `termdash` library, covering its core classes, their constructors, and public methods.

## Table of Contents
- [TermDash Class](#termdash-class)
  - [Constructor](#termdash-constructor)
  - [Public Methods](#termdash-public-methods)
- [Stat Class](#stat-class)
  - [Constructor](#stat-constructor)
  - [Public Methods](#stat-public-methods)
- [Line Class](#line-class)
  - [Constructor](#line-constructor)
  - [Public Methods](#line-public-methods)
- [AggregatedLine Class](#aggregatedline-class)
  - [Constructor](#aggregatedline-constructor)
  - [Public Methods](#aggregatedline-public-methods)

---

## TermDash Class

The `TermDash` class is the primary entry point for creating and managing a terminal dashboard. It handles rendering, updates, and terminal interactions, providing a thread-safe environment for displaying dynamic information.

### Constructor

`TermDash(`
    `refresh_rate: float = 0.1,`
    `log_file: Optional[str] = None,`
    `status_line: bool = True,`
    `debug_locks: bool = False,`
    `debug_rendering: bool = False,`
    `align_columns: bool = True,`
    `column_sep: str = "|",`
    `min_col_pad: int = 2,`
    `max_col_width: Optional[int] = None,`
    `enable_separators: bool = False,`
    `separator_style: str = "rule",`
    `separator_custom: Optional[str] = None,`
    `reserve_extra_rows: int = 6`
`)`

**Parameters:**
- `refresh_rate` (float): The interval in seconds at which the dashboard refreshes. Defaults to `0.1`.
- `log_file` (Optional[str]): Path to a file where internal logs of TermDash will be written. If `None`, logging is disabled.
- `status_line` (bool): If `True`, a blank line is reserved at the bottom for status messages or log output. Defaults to `True`.
- `debug_locks` (bool): If `True`, enables debug logging for internal locks. Defaults to `False`.
- `debug_rendering` (bool): If `True`, enables debug logging for rendering processes. Defaults to `False`.
- `align_columns` (bool): If `True`, columns split by `column_sep` will be aligned across all lines. Defaults to `True`.
- `column_sep` (str): The visual separator string used between columns when `align_columns` is `True`. Defaults to `"|"`.
- `min_col_pad` (int): The minimum number of spaces placed on both sides of the `column_sep`. Defaults to `2`.
- `max_col_width` (Optional[int]): If set, columns wider than this value will be truncated with an ellipsis. If `None`, no truncation based on width occurs.
- `enable_separators` (bool): If `True`, `add_separator()` will insert a horizontal rule. Defaults to `False`.
- `separator_style` (str): A preset style for separators (e.g., `"rule"`, `"dash"`, `"dot"`). Overridden by `separator_custom`. Defaults to `"rule"`.
- `separator_custom` (Optional[str]): A custom pattern string to use for separators. If provided, overrides `separator_style`.
- `reserve_extra_rows` (int): Number of rows to reserve below the dashboard to prevent scroll flicker. Defaults to `6`.

### Public Methods

#### `add_line(name: str, line_obj: Line, at_top: bool = False)`
Adds a `Line` object to the dashboard.
- `name` (str): A unique name for the line.
- `line_obj` (Line): The `Line` object to add.
- `at_top` (bool): If `True`, the line is inserted at the top of the dashboard. Defaults to `False`.

#### `add_separator()`
Inserts a separator line into the dashboard if `enable_separators` was set to `True` in the constructor.

#### `update_stat(line_name: str, stat_name: str, value: Any)`
Updates the value of a specific `Stat` within a named `Line`.
- `line_name` (str): The name of the `Line` containing the `Stat`.
- `stat_name` (str): The name of the `Stat` to update.
- `value` (Any): The new value for the `Stat`.

#### `reset_stat(line_name: str, stat_name: str, grace_period_s: int = 0)`
Resets a `Stat` to its initial value.
- `line_name` (str): The name of the `Line` containing the `Stat`.
- `stat_name` (str): The name of the `Stat` to reset.
- `grace_period_s` (int): An optional grace period in seconds during which the stat will not trigger stale warnings. Defaults to `0`.

#### `read_stat(line_name: str, stat_name: str) -> Optional[Any]`
Safely reads the current value of a `Stat`.
- `line_name` (str): The name of the `Line` containing the `Stat`.
- `stat_name` (str): The name of the `Stat` to read.
- Returns (Optional[Any]): The current value of the `Stat`, or `None` if not found.

#### `sum_stats(stat_name: str, line_names: Optional[Iterable[str]] = None) -> float`
Calculates the sum of a specific `Stat` across multiple lines.
- `stat_name` (str): The name of the `Stat` to sum.
- `line_names` (Optional[Iterable[str]]): An iterable of line names to include in the sum. If `None`, sums across all lines.
- Returns (float): The sum of the stat values. Non-numeric values are treated as 0.

#### `avg_stats(stat_name: str, line_names: Optional[Iterable[str]] = None) -> float`
Calculates the average of a specific `Stat` across multiple lines.
- `stat_name` (str): The name of the `Stat` to average.
- `line_names` (Optional[Iterable[str]]): An iterable of line names to include in the average. If `None`, averages across all lines.
- Returns (float): The average of the stat values. Non-numeric values are treated as 0.

#### `log(message: str, level: str = 'info')`
Writes a message to the internal logger (if configured) and also attempts to print it to a reserved status line in the terminal.
- `message` (str): The message to log.
- `level` (str): The logging level (e.g., `'info'`, `'error'`, `'debug'`). Defaults to `'info'`.

---

## Stat Class

The `Stat` class represents a single named metric that can be rendered inside a `Line`.

### Constructor

`Stat(`
    `name: str,`
    `value: Any,`
    `prefix: str = "",`
    `format_string: str = "{}",`
    `unit: str = "",`
    `color: Union[str, Callable[[Any], str]] = "",`
    `warn_if_stale_s: int = 0,`
    `no_expand: bool = False,`
    `display_width: Optional[int] = None`
`)`

**Parameters:**
- `name` (str): A unique name for the statistic.
- `value` (Any): The initial value of the statistic.
- `prefix` (str): A string to prepend to the rendered value. Defaults to `""`.
- `format_string` (str): A Python format string to apply to the value (e.g., `"{:.2f}"` for floats). Defaults to `"{}"`.
- `unit` (str): A string to append to the rendered value (e.g., `"MiB/s"`). Defaults to `""`.
- `color` (Union[str, Callable[[Any], str]]): An ANSI color code string (e.g., `"0;32"` for green) or a callable that takes the value and returns an ANSI color code. Defaults to `""` (white).
- `warn_if_stale_s` (int): If greater than 0, the stat will be marked as stale if not updated within this many seconds. Defaults to `0`.
- `no_expand` (bool): If `True`, this stat's rendered width will not contribute to the global column width calculation, allowing for fixed-width cells. Defaults to `False`.
- `display_width` (Optional[int]): A soft width hint for `no_expand` columns.

### Public Methods

#### `render(logger=None) -> str`
Renders the `Stat` to a string, applying formatting, prefix, unit, and color.
- `logger` (Optional): An optional logger instance for internal debug messages during rendering.
- Returns (str): The ANSI-formatted string representation of the stat.

---

## Line Class

The `Line` class represents a single renderable line in the dashboard, composed of one or more `Stat` objects.

### Constructor

`Line(`
    `name: str,`
    `stats: Optional[List[Stat]] = None,`
    `style: str = 'default',`
    `sep_pattern: str = "-"`
`)`

**Parameters:**
- `name` (str): A unique name for the line.
- `stats` (Optional[List[Stat]]): A list of `Stat` objects to include in this line. Defaults to `None`.
- `style` (str): The rendering style for the line. Can be `'default'`, `'header'`, or `'separator'`.
    - `'default'`: Normal joined stats.
    - `'header'`: Renders in bright cyan.
    - `'separator'`: Renders a horizontal rule using `sep_pattern`.
    Defaults to `'default'`.
- `sep_pattern` (str): The pattern to use when `style` is `'separator'`. Defaults to `"-"`.

### Public Methods

#### `update_stat(name: str, value: Any)`
Updates the value of a specific `Stat` within this line.
- `name` (str): The name of the `Stat` to update.
- `value` (Any): The new value for the `Stat`.

#### `reset_stat(name: str, grace_period_s: int = 0)`
Resets a `Stat` within this line to its initial value.
- `name` (str): The name of the `Stat` to reset.
- `grace_period_s` (int): An optional grace period in seconds during which the stat will not trigger stale warnings. Defaults to `0`.

#### `render(width: int, logger=None) -> str`
Renders the `Line` to a string, combining its `Stat` objects.
- `width` (int): The available terminal width for rendering.
- `logger` (Optional): An optional logger instance for internal debug messages during rendering.
- Returns (str): The ANSI-formatted string representation of the line.

---

## AggregatedLine Class

The `AggregatedLine` class is a specialized `Line` that aggregates numeric statistics from a dictionary of source `Line` objects. Non-numeric values are treated as 0 during aggregation.

### Constructor

`AggregatedLine(`
    `name: str,`
    `source_lines: Dict[str, Line],`
    `stats: Optional[List[Stat]] = None,`
    `style: str = 'default',`
    `sep_pattern: str = "-"`
`)`

**Parameters:**
- `name` (str): A unique name for the aggregated line.
- `source_lines` (Dict[str, Line]): A dictionary where keys are line names and values are `Line` objects from which to aggregate statistics.
- `stats` (Optional[List[Stat]]): A list of `Stat` objects that define which statistics to aggregate and how they should be displayed in this aggregated line. Defaults to `None`.
- `style` (str): The rendering style for the line (same as `Line` class). Defaults to `'default'`.
- `sep_pattern` (str): The pattern to use when `style` is `'separator'` (same as `Line` class). Defaults to `"-"`.

### Public Methods

#### `render(width: int, logger=None) -> str`
Renders the `AggregatedLine` to a string. During rendering, it recomputes each stat by summing the corresponding stat from all source lines.
- `width` (int): The available terminal width for rendering.
- `logger` (Optional): An optional logger instance for internal debug messages during rendering.
- Returns (str): The ANSI-formatted string representation of the aggregated line.
