<!-- version: 0.1.1 -->
# gsearch

`gsearch` is a durable, generic, adaptive grid-search manager for discrete parameter optimization.

It is designed to answer this question:

> Given a set of possible parameter values and a numeric result metric, which configuration should be tried next?

The original target use case is benchmarking `yt-dlp` download settings across many MP4 URLs and domains, but the module is intentionally generic. It can optimize any discrete configuration space where workers can run trials and report numeric results.

## Features

- Durable SQLite-backed experiment state
- Generic JSON grid specifications
- Adaptive search instead of plain exhaustive grid iteration
- Initial coverage-biased exploration
- UCB-style adaptive exploitation
- Neighbor search around the current best configuration
- Epsilon-greedy randomness so the optimizer keeps testing alternatives
- Optional group-aware optimization for domains, hosts, datasets, machines, or workloads
- CLI entry point: `gsearch`
- JSONL export for analysis
- Markdown, JSON, CSV, and graph report generation
- Test suite using `pytest`

## Current Project Layout

The current layout is:

~~~text
modules/grid_search/
├── gsearch/
│   ├── __init__.py
│   ├── cli.py
│   ├── manager.py
│   ├── reporting.py
│   └── tests/
│       ├── cli_test.py
│       ├── manager_test.py
│       └── reporting_test.py
└── pyproject.toml
~~~

`modules/grid_search/` is the package project root.

`modules/grid_search/gsearch/` is the importable Python package.

`adaptive_grid_manager.py` and `adaptive_grid_reporter.py` are prototype/root scripts. They are not required for the installed `gsearch` package if `gsearch/manager.py` and `gsearch/reporting.py` contain the final implementation.

## Installation

From the repository root:

~~~powershell
python -m pip install -e .\modules\grid_search[dev]
~~~

From inside `modules/grid_search/`:

~~~powershell
python -m pip install -e .[dev]
~~~

Verify the package import:

~~~powershell
python -c "import gsearch; print(gsearch.__version__); print(gsearch.__file__)"
~~~

Verify the CLI:

~~~powershell
gsearch --help
~~~

## Development Commands

Run tests from the repository root:

~~~powershell
python -m pytest .\modules\grid_search
~~~

Run Ruff:

~~~powershell
python -m ruff check .\modules\grid_search
~~~

Run MyPy:

~~~powershell
python -m mypy .\modules\grid_search\gsearch
~~~

## Core Concepts

### Experiment

An experiment is a named optimization run stored in SQLite.

Example:

~~~text
yt-dlp-mp4-speed
~~~

An experiment contains:

- one grid specification
- many trials
- one primary metric
- optimizer policy settings
- durable trial history

### Grid Spec

A grid spec is a JSON file defining the parameter search space.

It contains:

- metric name
- metric direction
- policy settings
- baseline parameter values
- discrete values for each parameter
- optional active/inactive rules
- optional constraints

Example:

~~~json
{
    "metric": {
        "name": "average_mbps",
        "direction": "maximize"
    },
    "parameters": {
        "concurrent_fragments": {
            "values": [1, 2, 4, 8, 16, 32],
            "active_when": {
                "downloader": "native"
            },
            "priority": 1
        }
    }
}
~~~

### Trial

A trial is one configuration assigned to a worker.

Workflow:

1. `gsearch next` chooses a config.
2. `gsearch next` immediately writes a `planned` trial to SQLite.
3. A worker runs the target program.
4. The worker measures the result.
5. `gsearch record` writes the result back to SQLite.

This means prior completed results survive process interruption.

### Config

A config is a dictionary of parameter values.

Example:

~~~json
{
    "downloader": "native",
    "concurrent_fragments": 8,
    "http_chunk_size": "10M"
}
~~~

`gsearch` does not know how to turn this into a specific program command. That translation belongs in the integration layer.

For `yt-dlp`, the downloader project should translate this config into command-line arguments.

### Metric

The metric is the numeric value being optimized.

Examples:

~~~json
{
    "metric": {
        "name": "average_mbps",
        "direction": "maximize"
    }
}
~~~

~~~json
{
    "metric": {
        "name": "total_seconds",
        "direction": "minimize"
    }
}
~~~

For MP4 download benchmarking, recommended first metric:

~~~text
average_mbps
~~~

Recommended secondary metrics:

- `elapsed_seconds`
- `downloaded_bytes`
- `download_seconds`
- `postprocess_seconds`
- `exit_code`
- `failure_reason`
- `format_id`
- `protocol`
- `fragment_count`

## Search Algorithm

`gsearch` is not a pure exhaustive grid search.

It uses an adaptive strategy:

1. **Warmup / coverage phase**
    - Picks diverse configurations.
    - Prioritizes under-tested parameter values.
    - Avoids prematurely locking onto noisy early winners.

2. **Adaptive phase**
    - Uses neighbor search around the current best config.
    - Uses UCB-style scoring to favor promising but under-tested parameter values.
    - Keeps some randomness through epsilon-greedy exploration.

3. **Group-aware selection**
    - Can optimize globally.
    - Can optimize per group.
    - Can use hybrid mode, where sparse groups use global history until enough group-specific results exist.

## Group-Aware Optimization

Groups allow one experiment to segment results by domain, host, dataset, machine, workload, or any other grouping key.

For MP4 downloads, use:

~~~text
group_key = domain
group_value = example.com
~~~

Recommended group mode:

~~~text
hybrid
~~~

Hybrid behavior:

- If a group has too few successful trials, use global history.
- Once a group has enough successful trials, use group-specific history.
- This prevents overfitting sparse domains while still allowing specialized optimization for common domains.

Example:

~~~powershell
gsearch next -d .\benchmarks\adaptive-grid.db -e yt-dlp-mp4-speed -k domain -v example.com -G hybrid -o .\benchmarks\next-trial.json
~~~

## Basic CLI Workflow

### 1. Initialize an experiment

~~~powershell
gsearch init -d .\benchmarks\adaptive-grid.db -g .\benchmarks\yt-dlp-grid.json -e yt-dlp-mp4-speed
~~~

### 2. Request the next trial

~~~powershell
gsearch next -d .\benchmarks\adaptive-grid.db -e yt-dlp-mp4-speed -k domain -v example.com -G hybrid -o .\benchmarks\next-trial.json
~~~

The output JSON includes:

~~~json
{
    "trial_id": "...",
    "experiment_name": "yt-dlp-mp4-speed",
    "config_id": "...",
    "config": {
        "downloader": "native",
        "concurrent_fragments": 8
    },
    "status": "planned",
    "metric_name": "average_mbps",
    "group_key": "domain",
    "group_value": "example.com"
}
~~~

### 3. Worker runs the target program

The worker reads the trial JSON and converts `config` into target-program arguments.

For `yt-dlp`, that conversion belongs in your downloader, not in `gsearch`.

### 4. Record a successful result

~~~powershell
gsearch record -d .\benchmarks\adaptive-grid.db -t "<trial-id>" -v 42.8 -s ok -M '{ "url": "https://example.com/video.mp4", "elapsed_seconds": 31.2, "downloaded_bytes": 167772160 }'
~~~

### 5. Record a failed result

~~~powershell
gsearch record -d .\benchmarks\adaptive-grid.db -t "<trial-id>" -s failed -M '{ "url": "https://example.com/video.mp4", "failure_reason": "timeout" }'
~~~

### 6. Export all trials

~~~powershell
gsearch export -d .\benchmarks\adaptive-grid.db -e yt-dlp-mp4-speed -o .\benchmarks\yt-dlp-results.jsonl
~~~

### 7. Print a summary

~~~powershell
gsearch summary -d .\benchmarks\adaptive-grid.db -e yt-dlp-mp4-speed -l 20
~~~

### 8. Generate reports

~~~powershell
gsearch report -d .\benchmarks\adaptive-grid.db -e yt-dlp-mp4-speed -o .\benchmarks\reports\yt-dlp-mp4-speed
~~~

## Report Outputs

`gsearch report` writes:

~~~text
summary.json
summary.md
trials.csv
report_manifest.json
plots/metric_over_time.png
plots/cumulative_best.png
plots/status_counts.png
plots/selection_reason_counts.png
plots/parameter_effects/<parameter>.png
~~~

These reports help answer:

- Is the optimizer improving over time?
- What are the best observed configurations?
- Which parameter values look strong or weak?
- Are failures frequent?
- Is the optimizer still exploring?
- Which configs should be promoted to production defaults?

## Current Reporting Limitations

The current packaged `gsearch.reporting` implementation is intentionally simpler than the original prototype reporter.

Features currently missing from the packaged reporter:

- `group_performance.png`
- `top_configs.png`
- `parameter_heatmap.png`
- explicit heatmap axis CLI options
- `--max-groups` report option

These can be added later without changing the SQLite schema.

Recommended future report additions:

~~~text
plots/group_performance.png
plots/top_configs.png
plots/parameter_heatmap.png
~~~

Recommended future CLI options:

~~~text
gsearch report --heatmap-x concurrent_fragments --heatmap-y http_chunk_size
gsearch report --max-groups 20
~~~

## Durability Model

The durable source of truth is SQLite.

Important behavior:

1. `gsearch next` creates a `planned` trial immediately.
2. `gsearch record` updates the trial with result status and metric.
3. Completed results survive process interruption.
4. Planned trials survive worker crashes.
5. Stale planned trials can be expired by TTL logic during later `next` calls.

The only measurement data at risk is data that exists only inside a worker after a target program finishes but before the worker calls `gsearch record`.

For maximum safety, workers should write a raw result file before calling `gsearch record`.

Recommended raw result path:

~~~text
benchmarks/trials/<trial_id>/raw-result.json
~~~

Recommended raw result contents:

~~~json
{
    "trial_id": "...",
    "url": "https://example.com/video.mp4",
    "domain": "example.com",
    "exit_code": 0,
    "elapsed_seconds": 31.2,
    "downloaded_bytes": 167772160,
    "average_mbps": 42.8,
    "stdout_log_path": "benchmarks/trials/<trial_id>/stdout.log",
    "stderr_log_path": "benchmarks/trials/<trial_id>/stderr.log"
}
~~~

Then call `gsearch record`.

## Multi-Process Integration Pattern

For a multi-process downloader:

1. Parent process owns the URL queue.
2. Worker receives a URL.
3. Worker extracts the domain.
4. Worker asks `gsearch next` for a trial using that domain.
5. Worker builds the target command from the returned config.
6. Worker runs the download in a unique trial directory.
7. Worker measures speed and timing.
8. Worker writes raw result JSON.
9. Worker calls `gsearch record`.
10. Worker repeats.

Recommended trial directory:

~~~text
benchmarks/trials/<trial_id>/
~~~

Recommended files:

~~~text
benchmarks/trials/<trial_id>/command.json
benchmarks/trials/<trial_id>/stdout.log
benchmarks/trials/<trial_id>/stderr.log
benchmarks/trials/<trial_id>/raw-result.json
benchmarks/trials/<trial_id>/downloaded-file.mp4
~~~

## Example Worker Pseudocode

~~~python
def worker_loop(url_queue):
    while True:
        url = url_queue.get()
        if url is None:
            break

        domain = extract_domain(url)

        trial = gsearch_next(
            database="benchmarks/adaptive-grid.db",
            experiment="yt-dlp-mp4-speed",
            group_key="domain",
            group_value=domain,
            group_mode="hybrid",
        )

        trial_dir = make_trial_dir(trial["trial_id"])
        command = build_yt_dlp_command(url=url, config=trial["config"], output_dir=trial_dir)

        result = run_and_measure(command)
        write_raw_result_json(trial_dir, trial, result)

        if result.success:
            gsearch_record(
                database="benchmarks/adaptive-grid.db",
                trial_id=trial["trial_id"],
                status="ok",
                metric_value=result.average_mbps,
                metadata=result.to_dict(),
            )
        else:
            gsearch_record(
                database="benchmarks/adaptive-grid.db",
                trial_id=trial["trial_id"],
                status="failed",
                metric_value=None,
                metadata=result.to_dict(),
            )
~~~

## Suggested yt-dlp Grid Spec

Save as:

~~~text
benchmarks/yt-dlp-grid.json
~~~

~~~json
{
    "metric": {
        "name": "average_mbps",
        "direction": "maximize"
    },
    "policy": {
        "warmup_trials": 40,
        "epsilon_start": 0.35,
        "epsilon_floor": 0.08,
        "epsilon_decay_trials": 180,
        "ucb_weight": 0.75,
        "candidate_pool_size": 256,
        "neighbor_probability_after_warmup": 0.55,
        "ucb_probability_after_warmup": 0.30,
        "coverage_probability_after_warmup": 0.15,
        "min_group_trials": 16,
        "planned_trial_ttl_seconds": 21600
    },
    "baseline": {
        "downloader": "native",
        "concurrent_fragments": 4,
        "http_chunk_size": "disabled",
        "buffer_size": "1M",
        "resize_buffer": true,
        "socket_timeout": 20,
        "retries": 10,
        "fragment_retries": 10,
        "force_ip": "auto",
        "format": "bv*+ba/b"
    },
    "parameters": {
        "downloader": {
            "values": ["native", "aria2c"],
            "priority": 1
        },
        "concurrent_fragments": {
            "values": [1, 2, 4, 8, 16, 32],
            "active_when": {
                "downloader": "native"
            },
            "priority": 1
        },
        "http_chunk_size": {
            "values": ["disabled", "1M", "5M", "10M", "20M", "50M", "64M"],
            "active_when": {
                "downloader": "native"
            },
            "priority": 1
        },
        "buffer_size": {
            "values": ["64K", "256K", "1M", "4M", "16M"],
            "active_when": {
                "downloader": "native"
            },
            "priority": 2
        },
        "resize_buffer": {
            "values": [true, false],
            "active_when": {
                "downloader": "native"
            },
            "priority": 2
        },
        "socket_timeout": {
            "values": [5, 10, 20, 30, 60],
            "priority": 3
        },
        "retries": {
            "values": [3, 5, 10, 20, 30],
            "priority": 3
        },
        "fragment_retries": {
            "values": [3, 5, 10, 20, 30],
            "priority": 3
        },
        "force_ip": {
            "values": ["auto", "ipv4", "ipv6"],
            "priority": 4
        },
        "format": {
            "values": ["best", "bv*+ba/b", "b", "bestvideo+bestaudio/best"],
            "priority": 2
        },
        "aria2c_max_connection_per_server": {
            "values": [1, 2, 4, 8, 16],
            "active_when": {
                "downloader": "aria2c"
            },
            "priority": 1
        },
        "aria2c_split": {
            "values": [1, 2, 4, 8, 16, 32],
            "active_when": {
                "downloader": "aria2c"
            },
            "priority": 1
        },
        "aria2c_min_split_size": {
            "values": ["1M", "2M", "5M", "10M", "20M", "50M", "100M"],
            "active_when": {
                "downloader": "aria2c"
            },
            "priority": 1
        },
        "aria2c_piece_length": {
            "values": ["256K", "512K", "1M", "2M", "4M", "8M", "16M"],
            "active_when": {
                "downloader": "aria2c"
            },
            "priority": 2
        },
        "aria2c_file_allocation": {
            "values": ["none", "prealloc", "falloc"],
            "active_when": {
                "downloader": "aria2c"
            },
            "priority": 2
        },
        "aria2c_disk_cache": {
            "values": ["0", "16M", "64M", "128M"],
            "active_when": {
                "downloader": "aria2c"
            },
            "priority": 2
        }
    },
    "constraints": [
        {
            "type": "greater_equal",
            "left": "aria2c_split",
            "right": "aria2c_max_connection_per_server",
            "active_when": {
                "downloader": "aria2c"
            }
        }
    ]
}
~~~

## Translating gsearch Configs To yt-dlp Args

This should live in the downloader integration layer, not in `gsearch`.

Example:

~~~python
def build_yt_dlp_args(config):
    args = []

    downloader = config.get("downloader")
    if downloader:
        args.extend(["--downloader", str(downloader)])

    if config.get("downloader") == "native":
        if "concurrent_fragments" in config:
            args.extend(["--concurrent-fragments", str(config["concurrent_fragments"])])

        if config.get("http_chunk_size") not in {None, "disabled"}:
            args.extend(["--http-chunk-size", str(config["http_chunk_size"])])

        if "buffer_size" in config:
            args.extend(["--buffer-size", str(config["buffer_size"])])

        if config.get("resize_buffer") is True:
            args.append("--resize-buffer")
        elif config.get("resize_buffer") is False:
            args.append("--no-resize-buffer")

    if config.get("force_ip") == "ipv4":
        args.append("--force-ipv4")
    elif config.get("force_ip") == "ipv6":
        args.append("--force-ipv6")

    if config.get("format"):
        args.extend(["--format", str(config["format"])])

    if config.get("downloader") == "aria2c":
        aria2c_args = []

        if "aria2c_max_connection_per_server" in config:
            aria2c_args.extend(["-x", str(config["aria2c_max_connection_per_server"])])

        if "aria2c_split" in config:
            aria2c_args.extend(["-s", str(config["aria2c_split"])])

        if "aria2c_min_split_size" in config:
            aria2c_args.extend(["-k", str(config["aria2c_min_split_size"])])

        if "aria2c_piece_length" in config:
            aria2c_args.append(f"--piece-length={config['aria2c_piece_length']}")

        if aria2c_args:
            args.extend(["--downloader-args", "aria2c:" + " ".join(aria2c_args)])

    return args
~~~

## Pitfalls

### Do not resume partial downloads across configs

For benchmarking, each trial should use a unique output directory.

Bad:

~~~text
Config A downloads first half.
Config B resumes second half.
Config B looks artificially fast.
~~~

Good:

~~~text
Each trial uses benchmarks/trials/<trial_id>/
~~~

### Record failures

Do not ignore failed downloads.

Failed trials help identify fast-but-unstable settings.

### Do not split too early by domain

If many domains have little data, use hybrid grouping.

Recommended:

~~~text
-G hybrid
~~~

Avoid:

~~~text
-G per-group
~~~

until common domains have enough successful trials.

### Keep gsearch generic

Do not add yt-dlp-specific argument translation into `gsearch.manager`.

Keep target-specific logic in the downloader.

### Keep planned-trial TTL aligned with runtime

Default:

~~~text
21600 seconds = 6 hours
~~~

If benchmark runs can take longer, increase:

~~~json
{
    "planned_trial_ttl_seconds": 43200
}
~~~

## Validation Checklist

The module is ready to integrate when:

- `python -m pip install -e .\modules\grid_search[dev]` succeeds.
- `gsearch --help` works.
- `python -m pytest .\modules\grid_search` passes.
- `gsearch init` creates a database.
- `gsearch next` creates a planned trial.
- `gsearch record` persists a result.
- `gsearch summary` shows successful trials.
- `gsearch report` writes report artifacts.
- Interrupting a worker does not erase completed prior results.
- Stale planned trials are either recorded or eventually expired.

## Recommended Next Enhancements

1. Add `group_performance.png`.
2. Add `top_configs.png`.
3. Add `parameter_heatmap.png`.
4. Add `gsearch report --heatmap-x` and `--heatmap-y`.
5. Add `gsearch report --max-groups`.
6. Add an optional `gsearch inspect-trial <trial_id>` command.
7. Add an optional `gsearch mark-running <trial_id>` command.
8. Add an optional retry command for expired/failed trials.
