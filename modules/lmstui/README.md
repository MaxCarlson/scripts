<!-- version: 1.0.0 -->
# lmst / lmstui

A reliable, convenient, zero-dependency command-line client for directly interacting with locally loaded LLMs running in LM Studio (or any OpenAI-compatible server).

Supports Windows PowerShell, WSL2/Ubuntu, macOS, Linux, and Termux.

## Installation

Install in editable mode from repository root:

```bash
pip install -e modules/lmstui
```

This installs three console entry points:
- `lmst`: The primary, modern command-line and interactive chat interface.
- `lmc`: Shortcut directly for `lmst chat` (interactive or one-shot prompt).
- `lmstui`: Backward-compatible CLI retaining legacy server, models, run, and log commands.

## Key Features

- **Zero Third-Party Dependencies**: Pure Python standard library (`urllib.request`).
- **Automatic Loaded Model Selection**: Omit `-m/--model` and `lmst` queries LM Studio to find currently loaded models. If multiple are loaded, it selects deterministically and warns you on stderr.
- **Model Info On Start**: Prints model type and context length on stderr by default unless `-S/--silent` is passed.
- **Persistent Defaults Configuration**: Set global or per-model defaults (e.g. streaming, temperature, stats, system prompt) saved to a module JSON file (`defaults.json`).
- **Interactive Chat REPL**: Streaming turns, multi-turn history, Ctrl+C cancellation without crashing, and commands: `/help`, `/reset`, `/stats`, `/exit`.
- **Clean Piping**: Response text is written to stdout; optional diagnostics and stats (`--stats / -a`) are emitted to stderr.
- **Structured JSON Mode**: `--json / -j` outputs the complete unmodified API response object.

---

## Command Reference: `lmst`

### 1. Model Discovery

```powershell
# List available models
lmst models

# Output raw JSON
lmst models --json
```

### 2. Interactive Chat

Start interactive conversation with the automatically detected loaded model:

```powershell
lmst chat
```

Or specify a model explicitly:

```powershell
lmst chat -m qwen38_23GB
```

REPL commands:
- `/help`: Show available slash commands
- `/reset`: Clear conversation turn history
- `/stats`: Toggle per-turn token/speed statistics
- `/exit` (or `/quit`, `/q`): Exit session

Pressing `Ctrl+C` while the assistant is streaming aborts generation and returns immediately to the prompt.

### 3. One-Shot Prompts

Pass prompt via `-p/--prompt`:

```powershell
lmst chat -m qwen38_23GB -p "Explain the chain rule."
```

Stream live tokens (default):

```powershell
lmst chat -m qwen38_23GB -p "Write a Python prime sieve." --stream
```

Disable streaming:

```powershell
lmst chat -m qwen38_23GB -p "Explain decorators." --no-stream
```

### 4. Output Formats and Piping

Display inference performance metrics on stderr (prompt tokens, completion tokens, reasoning tokens, total tokens, elapsed time, tokens/second):

```powershell
lmst chat -m qwen38_23GB -p "Explain decorators." --stats
```

Output full JSON response to stdout:

```powershell
lmst chat -m qwen38_23GB -p "Explain decorators." --json
```

Pipe stdin into prompt (for shell scripting and automation):

```powershell
# Windows PowerShell
Get-Content script.py | lmst chat -m qwen38_23GB

# Unix / macOS / Termux
cat script.py | lmst chat -m qwen38_23GB
```

Pipe assistant stdout into another command:

```powershell
lmst chat -m qwen38_23GB -p "List 5 fruits, one per line." -S | Select-String "Apple"
```

### 5. Persistent Defaults Management

You can configure persistent defaults so you don't need to specify flags repeatedly. These are stored in `modules/lmstui/lmstui/defaults.json`.

```powershell
# Set global default flags
lmst chat -D stream=true -D temperature=0.7 -D stats=true

# Set model-specific defaults (overrides global defaults for this model)
lmst chat -m qwen38_23GB --per-model -D temperature=0.2 -D system_prompt="You are an expert coder"

# Show currently configured defaults
lmst chat --show-defaults

# Clear defaults for a specific model
lmst chat -m qwen38_23GB --per-model --clear-defaults

# Clear all custom defaults to factory defaults
lmst chat --clear-defaults
```

### 6. Connection Settings

Override host, port, or timeout for remote LM Studio instances:

```powershell
lmst -b http://192.168.1.50:1234 -t 120 models
lmst chat -b http://192.168.1.50:1234 -m qwen38_23GB -p "Hello"
```

---

## Direct Shortcut: `lmc`

`lmc` is a convenient direct shortcut for `lmst chat`. You can quickly type whatever text you want sent to the LLM directly after `lmc`:

```powershell
# Type directly after lmc
lmc hello world
lmc what is the chain rule in calculus?
lmc write a python script to parse csv files

# Flags can be mixed before or after
lmc -S hello world
lmc how does quicksort work? -a
lmc -m qwen38_23GB explain decorators in python

# Bare lmc (without text) starts the interactive REPL chat
lmc
```

---

## Backward Compatibility: `lmstui`

The `lmstui` entry point remains available for scripts relying on the prior interface:

```powershell
lmstui server ping
lmstui server endpoints
lmstui models list
lmstui models info -m qwen38_23GB
lmstui run -m qwen38_23GB -p "Hello"
lmstui chat -m qwen38_23GB
lmstui embeddings -m nomic-embed-text -x "hello world"
```
