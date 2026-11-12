# CLI Compatibility Matrix & Namespace Mapping

## 1. Overview

The refactored CLI establishes intuitive command namespaces while preserving 100% backward compatibility with existing command invocations, scripts, automation consumers, and JSON output schemas.

Both entry points `agent-bench` and `agent-benchmark` are preserved and identical.

## 2. Command Namespace Structure

```text
agent-benchmark
  ├── setup
  │     ├── plan [-A|--all] [-d|--dataset ID]
  │     ├── install [-A|--all] [-d|--dataset ID] [-x|--execute]
  │     ├── status [-A|--all] [-d|--dataset ID]
  │     ├── verify [-A|--all] [-d|--dataset ID]
  │     └── upgrade [-d|--dataset ID] [-x|--execute]
  ├── suite
  │     ├── list [-f|--format table|json]
  │     ├── show -d|--dataset ID
  │     ├── tasks -d|--dataset ID
  │     ├── plan -c|--cohort ID -m|--model MODEL [-A|--api-format FMT]
  │     ├── run -c|--cohort ID -m|--model MODEL -x|--execute
  │     ├── status -r|--run-id ID
  │     ├── resume -r|--run-id ID -x|--execute
  │     ├── report -r|--run-id ID
  │     ├── compare -r|--run-id RUN_A -r RUN_B [-f table|json|markdown]
  │     ├── archive -r|--run-id ID
  │     └── doctor [-f text|json]
  ├── task (Aliases for root commands: plan, run, status, cleanup, smoke)
  │     ├── plan -m|--model MODEL ...
  │     ├── run -m|--model MODEL -x|--execute ...
  │     ├── status -r|--run-id ID
  │     ├── cleanup
  │     └── smoke [-x|--execute]
  ├── experiment (Existing multi-model experimentation commands)
  │     ├── plan ...
  │     ├── run ...
  │     ├── status ...
  │     └── report ...
  ├── models (Existing model inventory command)
  │     └── list
  └── external (Legacy Harbor benchmark interface - preserved as-is)
        ├── list [--format table|json]
        ├── plan ...
        ├── run ...
        ├── import ...
        └── report ...
```

## 3. Flag Scoping and Collision Prevention

| Scope / Subcommand | Flag | Long Form | Meaning | Note |
|---|---|---|---|---|
| `setup` (and subcommands) | `-A` | `--all` | All registered benchmarks | Scoped strictly to `setup` namespace |
| `suite plan` | `-A` | `--api-format` | API format string | Preserved for existing automation |
| Mutating commands (`run`, `install -x`, `resume`) | `-x` | `--execute` | Explicit execution authorization | Dry-run / preview without `-x` |
| Output format (new commands) | `-f` | `--format` | `table` or `json` (or `markdown`) | Default to JSON where legacy was JSON |
| Output format (legacy `external list`) | | `--format` | `table` or `json` | Preserved |
| LLM Friendly mode | `-F` | `--llm-friendly` | Compact, machine-friendly event output | Preserved |
| Root flags | `-V` | `--version` | Display version | Preserved |
| Root flags | `-h` | `--help` | Display help | Preserved |

## 4. Backward Compatibility Invariants

1. **Root Task Invocations**:
   `agent-bench plan ...`, `agent-bench run ...`, `agent-bench status ...`, `agent-bench cleanup`, `agent-bench smoke` continue to parse and execute identically.

2. **Harbor External Subcommands**:
   `agent-bench external list --format json` produces the exact same top-level JSON fields:
   `readiness`, `datasets`, `supported_agents`.

3. **Suite List Output**:
   `agent-bench suite list` default output continues to include:
   ```json
   {
     "cohorts": [
       {
         "id": "aider-python-10",
         "dataset": "aider/aider-polyglot",
         "source_revision": "f30b14415dd733c83627204bad0af69a89ceb46f",
         "tasks": 10
       }
     ]
   }
   ```
   Additive metadata (e.g. `datasets`, `readiness`, `backends`) is provided cleanly without breaking any consumer expecting the `cohorts` list.

4. **Suite Plan Flag `-A`**:
   `agent-bench suite plan -c aider-python-10 -m ... -A openai_chat_completions` continues to interpret `-A` as `--api-format`.

5. **`setup -A` Invariant**:
   `agent-benchmark setup -A` and `agent-benchmark setup plan -A` are synonymous and produce a read-only setup plan for all default registered benchmarks.
