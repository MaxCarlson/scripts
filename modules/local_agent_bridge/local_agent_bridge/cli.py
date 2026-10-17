#!/usr/bin/env python3
"""
local-agent-bridge
Manage, configure, and run local LM Studio coding models for OpenAI Codex and
Google Gemini Antigravity CLI (`agy`) via OpenCode.

Features:
  - `ls` command: Lists available LM Studio models/variants (`lms ls --variants`),
    currently loaded models (`lms ps`), configured model nicknames in `opencode.json`,
    and bridge status for both Codex (`~/.codex/config.toml`) and Gemini `agy`
    (`~/.gemini/config/mcp_config.json` & `~/.gemini/antigravity-cli/mcp_config.json`).
  - Automatic variant resolution: Accepts `qwen/qwen3.8-27b@q4_k_m` or `qwen/qwen3.8-27b@q6_k`
    (or `-v/--variant`) and silently creates a zero-extra-space hard-linked repository via
    `lms import --hard-link` only when needed to bypass LM Studio Issue #1462.
  - Smart reload & VRAM management: Checks `lms ps` and `lms ps --json` so an already-loaded
    model is not reloaded unless `-R/--reload` is passed or the model/variant/context changed,
    and automatically unloads any other loaded LLM instances in LM Studio so multiple
    models do not compete for 32 GB VRAM (unless `-U/--no-unload` is passed).
  - Named model management (`-M/--model-nickname`, `-D/--delete-model`, `--rename-model`):
    Adds, switches, renames, or deletes named models in `~/.config/opencode/opencode.json`
    and syncs both Codex (`~/.codex/config.toml`) and Gemini `agy` MCP & permission configs.
  - Foreground server lifecycle: Starts/verifies LM Studio HTTP (`127.0.0.1:1234`) and
    runs `opencode serve --hostname 127.0.0.1 --port <port>` until `q` or `Ctrl+C` is pressed
    (unless `-N/--no-servers` is passed).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants & Paths
# ---------------------------------------------------------------------------
DEFAULT_NICKNAME = "qwen-local"
DEFAULT_MODEL = "qwen/qwen3.8-27b@q6_k"
DEFAULT_CONTEXT = 32768
DEFAULT_GPU = "max"
DEFAULT_LMS_PORT = 1234
DEFAULT_OPENCODE_PORT = 4096

PROVIDER_ID = "lmstudio"
BRIDGE_NAME = "opencode_worker"
BRIDGE_PACKAGE = "opencode-mcp@3.0.0"

HOME_DIR = Path.home()
OPENCODE_CONFIG_PATH = HOME_DIR / ".config" / "opencode" / "opencode.json"
CODEX_CONFIG_PATH = HOME_DIR / ".codex" / "config.toml"

# Google Gemini Antigravity (`agy`) configuration & cache paths
GEMINI_DIR = HOME_DIR / ".gemini"
AGY_GLOBAL_MCP_PATH = GEMINI_DIR / "config" / "mcp_config.json"
AGY_CLI_MCP_PATH = GEMINI_DIR / "antigravity-cli" / "mcp_config.json"
AGY_CLI_SETTINGS_PATH = GEMINI_DIR / "antigravity-cli" / "settings.json"
AGY_GLOBAL_CONFIG_PATH = GEMINI_DIR / "config" / "config.json"
AGY_MCP_CACHE_DIRS = [
    GEMINI_DIR / "antigravity" / "mcp" / BRIDGE_NAME,
    GEMINI_DIR / "antigravity-cli" / "mcp" / BRIDGE_NAME,
    GEMINI_DIR / "antigravity-ide" / "mcp" / BRIDGE_NAME,
]


# ---------------------------------------------------------------------------
# ANSI Color & Console Formatting Helpers
# ---------------------------------------------------------------------------
def _enable_windows_ansi() -> None:
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass


_enable_windows_ansi()


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    GRAY = "\033[90m"


def print_header(title: str) -> None:
    print(f"\n{Style.CYAN}{Style.BOLD}==> {title}{Style.RESET}", flush=True)


def print_work(msg: str) -> None:
    print(f"    {Style.YELLOW}â€¦ [WORK] {msg}{Style.RESET}", flush=True)


def print_info(msg: str) -> None:
    print(f"    {Style.GRAY}i [INFO] {msg}{Style.RESET}", flush=True)


def print_ok(msg: str) -> None:
    print(f"    {Style.GREEN}âœ“ [OK]   {msg}{Style.RESET}", flush=True)


def print_warn(msg: str) -> None:
    print(f"    {Style.YELLOW}! [WARN] {msg}{Style.RESET}", flush=True)


def print_fail(msg: str) -> None:
    print(f"    {Style.RED}âœ— [FAIL] {msg}{Style.RESET}", flush=True)


# ---------------------------------------------------------------------------
# Subprocess Execution with Live Heartbeat
# ---------------------------------------------------------------------------
@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        combined = f"{self.stdout}\n{self.stderr}".strip()
        return combined


def resolve_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        if name == "lms":
            fallback = HOME_DIR / ".lmstudio" / "bin" / "lms.exe"
            if fallback.is_file():
                return str(fallback)
        if name == "agy":
            for cand in (
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Antigravity" / "bin" / "agy.exe",
                HOME_DIR / ".gemini" / "bin" / "agy.exe",
            ):
                if cand.is_file():
                    return str(cand)
    return None


def run_cmd(
    args: list[str],
    *,
    timeout: int = 300,
    heartbeat_label: str | None = None,
    check: bool = True,
) -> CmdResult:
    exe = resolve_executable(args[0]) or args[0]
    full_args = [exe, *args[1:]]

    start_time = time.monotonic()
    proc = subprocess.Popen(
        full_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    next_beat = 5.0
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    proc.kill()
                    raise RuntimeError(
                        f"Timed out after {int(elapsed)}s: {' '.join(args)}"
                    )
                if heartbeat_label and elapsed >= next_beat:
                    print_work(f"{heartbeat_label} ({int(elapsed)}s elapsed)")
                    next_beat += 5.0
    except KeyboardInterrupt:
        proc.kill()
        raise

    res = CmdResult(
        returncode=proc.returncode,
        stdout=(stdout or "").strip(),
        stderr=(stderr or "").strip(),
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            f"Command failed ({res.returncode}): {' '.join(args)}\n{res.output}"
        )
    return res


# ---------------------------------------------------------------------------
# HTTP & Atomic JSON File Helpers
# ---------------------------------------------------------------------------
def http_get_json(url: str, timeout: float = 3.0) -> Any | None:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except Exception:
        return None


def wait_http_json(url: str, max_seconds: int = 35, label: str = "") -> Any | None:
    start = time.monotonic()
    next_notice = 6.0
    while (time.monotonic() - start) < max_seconds:
        data = http_get_json(url, timeout=2.0)
        if data is not None:
            return data
        time.sleep(1.0)
        elapsed = time.monotonic() - start
        if label and elapsed >= next_notice:
            print_work(f"Waiting for {label} at {url} ({int(elapsed)}s elapsed)")
            next_notice += 6.0
    return None


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError(f"JSON root in {path} must be an object.")
        return data
    except Exception as exc:
        raise RuntimeError(f"Failed to parse {path}: {exc}") from exc


def save_json_file_atomic(path: Path, data: dict[str, Any]) -> bool:
    from .setup.runtime_config import save_json
    return save_json(path, data, HOME_DIR)


# ---------------------------------------------------------------------------
# Regex & Model/Variant Resolution
# ---------------------------------------------------------------------------
def token_regex(text: str) -> str:
    tokens = [re.escape(t) for t in re.split(r"[-_.]+", text) if t]
    return r"[-_.]?".join(tokens)


@dataclass
class VariantRow:
    key: str
    base: str
    quant: str
    size: str
    selected: bool


@dataclass
class ModelSelection:
    base: str
    load_key: str
    quant: str
    display: str
    expected_size: str
    used_hard_link: bool = False


def parse_lms_variants() -> tuple[str, list[VariantRow], list[str]]:
    res = run_cmd(["lms", "ls", "--variants"], check=True)
    raw = res.stdout
    variants: list[VariantRow] = []
    standalone_keys: list[str] = []

    variant_re = re.compile(
        r"(?m)^\s*(?:(?P<sel>[\*\-])\s+)?(?P<key>[^\s@]+@[^\s]+)\s+\S+\s+\S+\s+(?P<size>\d+(?:\.\d+)?\s*[KMGT]i?B)"
    )
    for m in variant_re.finditer(raw):
        full_key = m.group("key").strip()
        base, quant = full_key.split("@", 1)
        variants.append(
            VariantRow(
                key=full_key,
                base=base,
                quant=quant.lower(),
                size=m.group("size").strip(),
                selected=bool(m.group("sel")),
            )
        )

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("You have", "LLM", "EMBEDDING")):
            continue
        m_group = re.match(r"^([^\s@]+)\s+\(\d+\s+variants\)", stripped)
        if m_group:
            standalone_keys.append(m_group.group(1))
            continue
        m_single = re.match(r"^(?:[\*\-]\s+)?([^\s@]+)\s+\S+", stripped)
        if m_single:
            key_cand = m_single.group(1)
            if key_cand not in ("LLM", "EMBEDDING", "PARAMS"):
                standalone_keys.append(key_cand)

    return raw, variants, standalone_keys


def detect_models_dir(explicit_dir: str = "") -> Path | None:
    if explicit_dir:
        p = Path(explicit_dir).expanduser().resolve()
        if not p.is_dir():
            raise RuntimeError(f"Provided --models-dir '{explicit_dir}' does not exist.")
        return p

    appdata = os.environ.get("APPDATA", "")
    settings_candidates = [
        HOME_DIR / ".lmstudio" / "settings.json",
        Path(appdata) / "LM Studio" / "settings.json" if appdata else None,
    ]
    for cfg in settings_candidates:
        if cfg and cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
                dl = data.get("downloadsFolder")
                if dl and Path(dl).is_dir():
                    return Path(dl).resolve()
            except Exception:
                pass

    for d in (
        HOME_DIR / ".lmstudio" / "models",
        HOME_DIR / ".cache" / "lm-studio" / "models",
    ):
        if d.is_dir():
            return d.resolve()
    return None


def find_variant_gguf(base: str, quant: str, models_root: Path) -> Path:
    base_leaf = base.split("/")[-1]
    base_re = re.compile(token_regex(base_leaf), re.IGNORECASE)
    quant_re = re.compile(
        r"(^|[-_.])" + token_regex(quant) + r"(?=[-_.]|\.gguf$)", re.IGNORECASE
    )
    want_uncensored = "uncensored" in base.lower()

    matches: list[Path] = []
    for gguf in models_root.rglob("*.gguf"):
        name = gguf.name
        full_str = str(gguf)
        if name.lower().startswith("mmproj"):
            continue
        if re.search(r"[\\/]local[\\/]", full_str, re.IGNORECASE):
            continue
        has_uncensored = "uncensored" in full_str.lower()
        if want_uncensored != has_uncensored:
            continue
        if not base_re.search(full_str):
            continue
        if quant and not quant_re.search(name):
            continue
        matches.append(gguf)

    if not matches:
        raise RuntimeError(
            f"Could not locate the '{quant}' .gguf file for '{base}' under '{models_root}'."
        )
    matches.sort(key=lambda p: p.stat().st_size, reverse=True)
    return matches[0]


def find_registered_repo_key(user_repo: str, repo_leaf: str) -> str | None:
    try:
        res = run_cmd(["lms", "ls", "--json"], check=False)
        if res.returncode == 0 and res.stdout.startswith("["):
            items = json.loads(res.stdout)
            for item in items:
                key = str(item.get("modelKey") or item.get("key") or "")
                path = str(item.get("path") or "")
                if (
                    key.lower() in (user_repo.lower(), repo_leaf.lower())
                    or re.search(rf"(^|[\\/]){re.escape(repo_leaf)}([\\/]|$)", path, re.IGNORECASE)
                ):
                    if key:
                        return key
    except Exception:
        pass

    raw, _, _ = parse_lms_variants()
    m = re.search(
        rf"(?im)^\s*(?:[\*\-]\s+)?(?P<key>(?:local/)?{re.escape(repo_leaf)})(?=\s|@|$)",
        raw,
    )
    if m:
        return m.group("key").strip()
    return None


def ensure_hard_linked_variant(base: str, quant: str, models_dir: str = "") -> str:
    base_leaf = base.split("/")[-1].lower().replace(".", "")
    quant_clean = re.sub(r"[_-]+", "", quant.lower())
    repo_leaf = f"{base_leaf}-{quant_clean}"
    user_repo = f"local/{repo_leaf}"

    existing = find_registered_repo_key(user_repo, repo_leaf)
    if existing:
        return existing

    models_root = detect_models_dir(models_dir)
    if not models_root:
        raise RuntimeError("Could not detect LM Studio models directory.")

    gguf_path = find_variant_gguf(base, quant, models_root)
    print_work(f"Registering hard-linked variant '{user_repo}' from {gguf_path.name}...")
    run_cmd(
        ["lms", "import", str(gguf_path), "--user-repo", user_repo, "--hard-link", "-y"],
        check=True,
    )
    registered = find_registered_repo_key(user_repo, repo_leaf) or user_repo
    print_ok(f"Registered variant repository '{registered}' (zero extra disk space)")
    return registered


def resolve_model_selection(requested: str, models_dir: str = "") -> ModelSelection:
    if "@" in requested:
        base, quant = requested.split("@", 1)
        quant = quant.strip().lower()
    else:
        base, quant = requested.strip(), ""

    if not base:
        raise RuntimeError(f"Invalid model specification: '{requested}'")

    _, variants, standalone = parse_lms_variants()
    matching_variants = [v for v in variants if v.base.lower() == base.lower()]

    if not matching_variants:
        found_standalone = next(
            (k for k in standalone if k.lower() == base.lower()), None
        )
        if not found_standalone:
            raise RuntimeError(
                f"Model '{base}' is not installed in LM Studio (`lms ls --variants`)."
            )
        return ModelSelection(
            base=found_standalone,
            load_key=found_standalone,
            quant=quant,
            display=f"{found_standalone}@{quant}" if quant else found_standalone,
            expected_size="",
            used_hard_link=False,
        )

    if quant:
        target_v = next((v for v in matching_variants if v.quant == quant), None)
        if not target_v:
            avail = ", ".join(v.key for v in matching_variants)
            raise RuntimeError(
                f"Variant '{base}@{quant}' is not installed. Available: {avail}"
            )
    else:
        selected_v = next((v for v in matching_variants if v.selected), None)
        target_v = selected_v or matching_variants[0]
        quant = target_v.quant

    if len(matching_variants) == 1:
        return ModelSelection(
            base=target_v.base,
            load_key=target_v.base,
            quant=target_v.quant,
            display=target_v.key,
            expected_size=target_v.size,
            used_hard_link=False,
        )

    hard_link_key = ensure_hard_linked_variant(target_v.base, target_v.quant, models_dir)
    return ModelSelection(
        base=target_v.base,
        load_key=hard_link_key,
        quant=target_v.quant,
        display=target_v.key,
        expected_size=target_v.size,
        used_hard_link=True,
    )


# ---------------------------------------------------------------------------
# Loaded Instance Inspection (`lms ps` and `lms ps --json`)
# ---------------------------------------------------------------------------
@dataclass
class LoadedInstance:
    identifier: str
    model_Or_path: str
    size_gib: str
    disk_size_gb: str
    context_length: int | None
    status: str


@dataclass
class LoadedBrief:
    identifier: str
    model: str
    is_embedding: bool = False


def list_all_loaded_models() -> list[LoadedBrief]:
    results: list[LoadedBrief] = []
    seen: set[str] = set()
    try:
        j_res = run_cmd(["lms", "ps", "--json"], check=False)
        if j_res.returncode == 0 and j_res.stdout.startswith("["):
            items = json.loads(j_res.stdout)
            for item in items:
                ident = str(item.get("identifier") or "").strip()
                if not ident or ident in seen:
                    continue
                model_str = str(
                    item.get("path") or item.get("modelKey") or item.get("model") or ""
                ).strip()
                mtype = str(item.get("type") or "").lower()
                is_emb = mtype == "embedding" or "embed" in model_str.lower() or "embed" in ident.lower()
                seen.add(ident)
                results.append(LoadedBrief(identifier=ident, model=model_str, is_embedding=is_emb))
            if results:
                return results
    except Exception:
        pass

    ps_res = run_cmd(["lms", "ps"], check=False)
    for line in ps_res.stdout.splitlines():
        m = re.match(
            r"^\s*(?P<id>[A-Za-z0-9._-]+)\s+(?P<model>\S+)\s+\S+\s+\d+(?:\.\d+)?\s*[KMGT]i?B\s+\d+",
            line,
        )
        if m:
            ident = m.group("id").strip()
            model_str = m.group("model").strip()
            if ident.upper() != "IDENTIFIER" and ident not in seen:
                is_emb = "embed" in model_str.lower() or "embed" in ident.lower()
                seen.add(ident)
                results.append(LoadedBrief(identifier=ident, model=model_str, is_embedding=is_emb))
    return results


def get_loaded_instance(identifier: str) -> tuple[LoadedInstance | None, str]:
    ps_res = run_cmd(["lms", "ps"], check=False)
    ps_table_text = ps_res.stdout

    disk_size_gb = ""
    ctx_len: int | None = None
    status_str = ""
    model_col = ""

    for line in ps_table_text.splitlines():
        m = re.match(
            rf"^\s*{re.escape(identifier)}\s+(?P<model>\S+)\s+(?P<status>\S+)\s+(?P<size>\d+(?:\.\d+)?\s*[KMGT]i?B)\s+(?P<ctx>\d+)",
            line,
        )
        if m:
            model_col = m.group("model").strip()
            status_str = m.group("status").strip()
            disk_size_gb = m.group("size").strip()
            ctx_len = int(m.group("ctx"))
            break

    if not model_col:
        for block in re.finditer(
            r"(?ms)^\s*Identifier:\s*(?P<id>[^\r\n]+)\r?\n(?P<details>.*?)(?=^\s*Identifier:|\Z)",
            ps_table_text,
        ):
            if block.group("id").strip() == identifier:
                det = block.group("details")
                p_m = re.search(r"(?m)^\s*[^\w\r\n]*Path:\s*(?P<val>[^\r\n]+)", det)
                s_m = re.search(r"(?m)^\s*[^\w\r\n]*Size:\s*(?P<val>[^\r\n]+)", det)
                model_col = p_m.group("val").strip() if p_m else identifier
                disk_size_gb = s_m.group("val").strip() if s_m else ""
                break

    json_path = ""
    size_gib = ""
    try:
        j_res = run_cmd(["lms", "ps", "--json"], check=False)
        if j_res.returncode == 0 and j_res.stdout.startswith("["):
            items = json.loads(j_res.stdout)
            for item in items:
                if str(item.get("identifier") or "") == identifier:
                    json_path = str(
                        item.get("path") or item.get("modelKey") or item.get("model") or ""
                    ).strip()
                    sb = item.get("sizeBytes")
                    if isinstance(sb, (int, float)) and sb > 0:
                        size_gib = f"{sb / (1024 ** 3):.2f} GiB"
                    elif item.get("size"):
                        size_gib = str(item.get("size"))
                    if ctx_len is None and item.get("contextLength"):
                        ctx_len = int(item["contextLength"])
                    break
    except Exception:
        pass

    if not model_col and not json_path:
        return None, ps_table_text

    return (
        LoadedInstance(
            identifier=identifier,
            model_Or_path=json_path or model_col,
            size_gib=size_gib or disk_size_gb,
            disk_size_gb=disk_size_gb,
            context_length=ctx_len,
            status=status_str or "LOADED",
        ),
        ps_table_text,
    )


def is_same_model_loaded(
    loaded: LoadedInstance | None,
    selection: ModelSelection,
    requested_context: int | None = None,
) -> bool:
    if loaded is None or not loaded.model_Or_path:
        return False

    if (
        requested_context is not None
        and loaded.context_length is not None
        and loaded.context_length != requested_context
    ):
        return False

    path_norm = loaded.model_Or_path.replace("\\", "/").lower()
    base_leaf = selection.base.split("/")[-1].lower()
    load_leaf = selection.load_key.split("/")[-1].lower()

    base_re = r"(^|/)" + token_regex(base_leaf) + r"(?=/|[-_.]|$)"
    load_re = r"(^|/)" + token_regex(load_leaf) + r"(?=/|[-_.]|$)"

    if not (re.search(base_re, path_norm) or re.search(load_re, path_norm)):
        return False

    want_uncensored = "uncensored" in base_leaf
    has_uncensored = "uncensored" in path_norm
    if want_uncensored != has_uncensored:
        return False

    if selection.quant:
        quant_re = (
            r"(^|[-_./])" + token_regex(selection.quant.lower()) + r"(?=[-_./]|$)"
        )
        if re.search(quant_re, path_norm):
            return True
        if selection.expected_size and loaded.disk_size_gb:
            if selection.expected_size.lower() == loaded.disk_size_gb.lower():
                return True
        return False

    return True


# ---------------------------------------------------------------------------
# OpenCode (`opencode.json`), Codex (`config.toml`), & Gemini `agy` Configs
# ---------------------------------------------------------------------------
def load_opencode_config() -> dict[str, Any]:
    return load_json_file(OPENCODE_CONFIG_PATH)


def save_opencode_config(data: dict[str, Any]) -> bool:
    return save_json_file_atomic(OPENCODE_CONFIG_PATH, data)


def get_configured_models_map(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    prov = cfg.get("provider")
    if not isinstance(prov, dict):
        return {}
    lms = prov.get(PROVIDER_ID)
    if not isinstance(lms, dict):
        return {}
    models = lms.get("models")
    if not isinstance(models, dict):
        return {}
    return models


def extract_model_spec_from_opencode(cfg: dict[str, Any], nickname: str) -> str | None:
    models = get_configured_models_map(cfg)
    entry = models.get(nickname)
    if not isinstance(entry, dict):
        return None
    if isinstance(entry.get("lms_model"), str) and entry["lms_model"].strip():
        return entry["lms_model"].strip()
    name_val = str(entry.get("name") or "").strip()
    m = re.match(r"^(?:Local worker:\s*)(.+)$", name_val, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    if name_val:
        return name_val
    return None


def update_opencode_for_model(
    nickname: str, display_spec: str, lms_port: int
) -> bool:
    cfg = load_opencode_config()
    if "$schema" not in cfg:
        cfg["$schema"] = "https://opencode.ai/config.json"
    if not isinstance(cfg.get("provider"), dict):
        cfg["provider"] = {}
    providers = cfg["provider"]
    if not isinstance(providers.get(PROVIDER_ID), dict):
        providers[PROVIDER_ID] = {}
    lms_prov = providers[PROVIDER_ID]
    lms_prov["npm"] = "@ai-sdk/openai-compatible"
    lms_prov["name"] = "LM Studio Local"
    if not isinstance(lms_prov.get("options"), dict):
        lms_prov["options"] = {}
    lms_prov["options"]["baseURL"] = f"http://127.0.0.1:{lms_port}/v1"

    if not isinstance(lms_prov.get("models"), dict):
        lms_prov["models"] = {}
    if not isinstance(lms_prov["models"].get(nickname), dict):
        lms_prov["models"][nickname] = {}

    lms_prov["models"][nickname]["name"] = f"Local worker: {display_spec}"
    cfg["model"] = f"{PROVIDER_ID}/{nickname}"
    return save_opencode_config(cfg)


def build_bridge_env(nickname: str, opencode_port: int) -> dict[str, str]:
    return {
        "OPENCODE_BASE_URL": f"http://127.0.0.1:{opencode_port}",
        "OPENCODE_AUTO_SERVE": "false",
        "OPENCODE_TOOL_PROFILE": "essential",
        "OPENCODE_DEFAULT_PROVIDER": PROVIDER_ID,
        "OPENCODE_DEFAULT_MODEL": nickname,
    }


def update_codex_mcp_toml(nickname: str, opencode_port: int) -> bool:
    """Update bridge fields while preserving unrelated TOML and extra options."""
    from .setup.runtime_config import save_codex
    return save_codex(CODEX_CONFIG_PATH, nickname, opencode_port, HOME_DIR)


def remove_toml_table_prefix(toml_text: str, table_prefix: str) -> str:
    if not toml_text:
        return ""
    out_lines: list[str] = []
    skipping = False
    header_re = re.compile(r"^\s*\[(?P<header>[^\[\]]+)\]\s*(?:#.*)?$")
    for line in toml_text.splitlines():
        m = header_re.match(line)
        if m:
            hdr = m.group("header").strip()
            if hdr == table_prefix or hdr.startswith(table_prefix + "."):
                skipping = True
                continue
            else:
                skipping = False
        if not skipping:
            out_lines.append(line)
    return "\n".join(out_lines).rstrip() + ("\n" if out_lines else "")


# ---------------------------------------------------------------------------
# Google Gemini Antigravity (`agy`) MCP & Permissions Configuration
# ---------------------------------------------------------------------------
def _update_single_agy_mcp_file(path: Path, nickname: str, opencode_port: int) -> bool:
    data = load_json_file(path)
    if not isinstance(data.get("mcpServers"), dict):
        data["mcpServers"] = {}

    npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
    entry = data["mcpServers"].setdefault(BRIDGE_NAME, {})
    if not isinstance(entry, dict):
        raise RuntimeError("Existing bridge configuration must be an object")
    entry.update({"command": npx_cmd, "args": ["-y", BRIDGE_PACKAGE], "disabled": False})
    if not isinstance(entry.get("env", {}), dict):
        raise RuntimeError("Existing bridge env must be an object")
    entry.setdefault("env", {}).update(build_bridge_env(nickname, opencode_port))
    return save_json_file_atomic(path, data)


def _ensure_agy_cli_permission_allow() -> bool:
    """
    Ensures `mcp(opencode_worker/*)` is in `permissions.allow` inside
    ~/.gemini/antigravity-cli/settings.json so `agy` can invoke the local
    worker tools without pausing on interactive confirmation prompts.
    """
    settings = load_json_file(AGY_CLI_SETTINGS_PATH)
    if not isinstance(settings.get("permissions"), dict):
        settings["permissions"] = {}
    perms = settings["permissions"]
    allow_list = perms.get("allow")
    if not isinstance(allow_list, list):
        allow_list = []
        perms["allow"] = allow_list

    rule = f"mcp({BRIDGE_NAME}/*)"
    if rule not in allow_list and f"mcp({BRIDGE_NAME})" not in allow_list and "mcp(*)" not in allow_list:
        allow_list.append(rule)

    return save_json_file_atomic(AGY_CLI_SETTINGS_PATH, settings)


def _ensure_agy_global_config_permission_allow() -> bool:
    """
    If ~/.gemini/config/config.json already exists (used by Antigravity App/IDE),
    adds `mcp(opencode_worker/*)` to `userSettings.globalPermissionGrants.allow`.
    """
    if not AGY_GLOBAL_CONFIG_PATH.is_file():
        return False
    cfg = load_json_file(AGY_GLOBAL_CONFIG_PATH)
    if not isinstance(cfg.get("userSettings"), dict):
        cfg["userSettings"] = {}
    us = cfg["userSettings"]
    if not isinstance(us.get("globalPermissionGrants"), dict):
        us["globalPermissionGrants"] = {}
    grants = us["globalPermissionGrants"]
    allow_list = grants.get("allow")
    if not isinstance(allow_list, list):
        allow_list = []
        grants["allow"] = allow_list

    rule = f"mcp({BRIDGE_NAME}/*)"
    if rule not in allow_list and f"mcp({BRIDGE_NAME})" not in allow_list and "mcp(*)" not in allow_list:
        allow_list.append(rule)

    return save_json_file_atomic(AGY_GLOBAL_CONFIG_PATH, cfg)


def update_agy_mcp_configs(nickname: str, opencode_port: int) -> tuple[bool, list[Path]]:
    """
    Updates both:
      1. ~/.gemini/config/mcp_config.json (shared global config for AGY 1.1+, AGY IDE, AGY App)
      2. ~/.gemini/antigravity-cli/mcp_config.json (authoritative CLI appDataDir config)
    and configures `mcp(opencode_worker/*)` auto-allow permission in ~/.gemini/antigravity-cli/settings.json.
    """
    c1 = _update_single_agy_mcp_file(AGY_GLOBAL_MCP_PATH, nickname, opencode_port)
    c2 = _update_single_agy_mcp_file(AGY_CLI_MCP_PATH, nickname, opencode_port)
    c3 = _ensure_agy_cli_permission_allow()
    c4 = _ensure_agy_global_config_permission_allow()
    return (c1 or c2 or c3 or c4), [AGY_GLOBAL_MCP_PATH, AGY_CLI_MCP_PATH]


def remove_agy_mcp_configs() -> None:
    """
    Removes `opencode_worker` from Gemini `agy` MCP config files, removes
    `mcp(opencode_worker/*)` from `permissions.allow`, and clears cached MCP tool schemas.
    """
    for mcp_path in (AGY_GLOBAL_MCP_PATH, AGY_CLI_MCP_PATH):
        if mcp_path.is_file():
            data = load_json_file(mcp_path)
            servers = data.get("mcpServers")
            if isinstance(servers, dict) and BRIDGE_NAME in servers:
                del servers[BRIDGE_NAME]
                save_json_file_atomic(mcp_path, data)
                print_ok(f"Removed '{BRIDGE_NAME}' from {mcp_path}")

    if AGY_CLI_SETTINGS_PATH.is_file():
        settings = load_json_file(AGY_CLI_SETTINGS_PATH)
        perms = settings.get("permissions")
        if isinstance(perms, dict) and isinstance(perms.get("allow"), list):
            before_len = len(perms["allow"])
            perms["allow"] = [
                r for r in perms["allow"] if r not in (f"mcp({BRIDGE_NAME}/*)", f"mcp({BRIDGE_NAME})")
            ]
            if len(perms["allow"]) != before_len:
                save_json_file_atomic(AGY_CLI_SETTINGS_PATH, settings)
                print_ok(f"Removed 'mcp({BRIDGE_NAME}/*)' permission rule from {AGY_CLI_SETTINGS_PATH}")

    if AGY_GLOBAL_CONFIG_PATH.is_file():
        cfg = load_json_file(AGY_GLOBAL_CONFIG_PATH)
        grants = (cfg.get("userSettings") or {}).get("globalPermissionGrants")
        if isinstance(grants, dict) and isinstance(grants.get("allow"), list):
            before_len = len(grants["allow"])
            grants["allow"] = [
                r for r in grants["allow"] if r not in (f"mcp({BRIDGE_NAME}/*)", f"mcp({BRIDGE_NAME})")
            ]
            if len(grants["allow"]) != before_len:
                save_json_file_atomic(AGY_GLOBAL_CONFIG_PATH, cfg)

    # Clear cached MCP method definitions so AGY/AGY IDE doesn't show stale tools
    for cache_dir in AGY_MCP_CACHE_DIRS:
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)
            print_ok(f"Cleared AGY MCP cache directory {cache_dir}")


# ---------------------------------------------------------------------------
# Named Model Delete & Rename Operations
# ---------------------------------------------------------------------------
def handle_delete_model(nickname: str, opencode_port: int) -> None:
    print_header(f"Removing named model '{nickname}'...")

    loaded, _ = get_loaded_instance(nickname)
    if loaded is not None:
        print_work(f"Unloading '{nickname}' from LM Studio memory (`lms unload {nickname}`)...")
        run_cmd(["lms", "unload", nickname], check=False)
        print_ok(f"Unloaded '{nickname}' from LM Studio memory.")
    else:
        print_info(f"Model '{nickname}' is not currently loaded in LM Studio.")

    if OPENCODE_CONFIG_PATH.is_file():
        cfg = load_opencode_config()
        models_map = get_configured_models_map(cfg)
        if nickname in models_map:
            del models_map[nickname]
            print_ok(f"Removed '{nickname}' from {OPENCODE_CONFIG_PATH}")
        else:
            print_warn(f"Nickname '{nickname}' was not found in {OPENCODE_CONFIG_PATH}")

        remaining = list(models_map.keys())
        if remaining:
            next_nick = remaining[0]
            if cfg.get("model") == f"{PROVIDER_ID}/{nickname}":
                cfg["model"] = f"{PROVIDER_ID}/{next_nick}"
                print_info(f"Switched active OpenCode model to '{PROVIDER_ID}/{next_nick}'")
            save_opencode_config(cfg)
            update_codex_mcp_toml(next_nick, opencode_port)
            update_agy_mcp_configs(next_nick, opencode_port)
            print_ok(f"Updated Codex & Gemini `agy` MCP '{BRIDGE_NAME}' default model to '{next_nick}'")
        else:
            prov = cfg.get("provider")
            if isinstance(prov, dict) and PROVIDER_ID in prov:
                del prov[PROVIDER_ID]
            if cfg.get("model") == f"{PROVIDER_ID}/{nickname}":
                cfg.pop("model", None)
            if not prov:
                OPENCODE_CONFIG_PATH.unlink(missing_ok=True)
                print_ok(f"Removed empty OpenCode config file {OPENCODE_CONFIG_PATH}")
            else:
                save_opencode_config(cfg)
                print_ok(f"Removed '{PROVIDER_ID}' provider from {OPENCODE_CONFIG_PATH}")

            if CODEX_CONFIG_PATH.is_file():
                raw_toml = CODEX_CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
                cleaned = remove_toml_table_prefix(raw_toml, f"mcp_servers.{BRIDGE_NAME}")
                CODEX_CONFIG_PATH.write_text(cleaned, encoding="utf-8")
                print_ok(f"Removed '[mcp_servers.{BRIDGE_NAME}]' from {CODEX_CONFIG_PATH}")

            remove_agy_mcp_configs()
    else:
        print_info(f"OpenCode config file {OPENCODE_CONFIG_PATH} does not exist.")


def handle_rename_model(old_nick: str, new_nick: str, lms_port: int, opencode_port: int) -> None:
    print_header(f"Renaming model nickname '{old_nick}' -> '{new_nick}'...")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", new_nick):
        raise RuntimeError(f"Invalid new nickname '{new_nick}'.")

    cfg = load_opencode_config()
    models_map = get_configured_models_map(cfg)
    if old_nick not in models_map:
        raise RuntimeError(
            f"Nickname '{old_nick}' does not exist in {OPENCODE_CONFIG_PATH}."
        )

    entry = models_map.pop(old_nick)
    models_map[new_nick] = entry
    if cfg.get("model") == f"{PROVIDER_ID}/{old_nick}":
        cfg["model"] = f"{PROVIDER_ID}/{new_nick}"

    save_opencode_config(cfg)
    print_ok(f"Renamed '{old_nick}' -> '{new_nick}' in {OPENCODE_CONFIG_PATH}")

    update_codex_mcp_toml(new_nick, opencode_port)
    print_ok(f"Updated Codex MCP '{BRIDGE_NAME}' default model to '{new_nick}' in {CODEX_CONFIG_PATH}")

    update_agy_mcp_configs(new_nick, opencode_port)
    print_ok(f"Updated Gemini `agy` MCP '{BRIDGE_NAME}' default model to '{new_nick}'")

    loaded, _ = get_loaded_instance(old_nick)
    if loaded is not None:
        spec = extract_model_spec_from_opencode(cfg, new_nick) or loaded.model_Or_path
        ctx = loaded.context_length or DEFAULT_CONTEXT
        print_work(f"Unloading old identifier '{old_nick}' and reloading as '{new_nick}'...")
        run_cmd(["lms", "unload", old_nick], check=False)
        sel = resolve_model_selection(spec)
        run_cmd(
            [
                "lms",
                "load",
                sel.load_key,
                "--identifier",
                new_nick,
                "--gpu",
                DEFAULT_GPU,
                "--context-length",
                str(ctx),
                "-y",
            ],
            timeout=600,
            heartbeat_label=f"Loading '{sel.display}' as '{new_nick}'",
            check=True,
        )
        print_ok(f"Reloaded '{sel.display}' under new identifier '{new_nick}'")


# ---------------------------------------------------------------------------
# `ls` Command Implementation
# ---------------------------------------------------------------------------
def handle_ls_command() -> None:
    print_header("Available Models & Variants in LM Studio (lms ls --variants)...")
    raw_ls, _, _ = parse_lms_variants()
    print(raw_ls)

    print_header("Currently Loaded Models in Memory (lms ps)...")
    ps_res = run_cmd(["lms", "ps"], check=False)
    print(ps_res.stdout if ps_res.stdout else "    (No models currently loaded)")

    print_header(f"Configured OpenCode Model Nicknames ({OPENCODE_CONFIG_PATH})...")
    if not OPENCODE_CONFIG_PATH.is_file():
        print_info("No opencode.json file found yet.")
    else:
        cfg = load_opencode_config()
        active_model = str(cfg.get("model") or "")
        models_map = get_configured_models_map(cfg)
        if not models_map:
            print_info("No models configured under provider.lmstudio.models.")
        else:
            for nick, meta in models_map.items():
                is_active = active_model == f"{PROVIDER_ID}/{nick}"
                marker = f"{Style.GREEN}* [ACTIVE]{Style.RESET}" if is_active else "          "
                desc = meta.get("name") if isinstance(meta, dict) else str(meta)
                print(f"    {marker} {Style.BOLD}{nick:<18}{Style.RESET} -> {desc}")

    print_header("Codex & Gemini `agy` MCP Bridge Status...")
    if CODEX_CONFIG_PATH.is_file():
        try:
            parsed = tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8", errors="replace"))
            bridge = (parsed.get("mcp_servers") or {}).get(BRIDGE_NAME)
            if bridge:
                env_model = (bridge.get("env") or {}).get("OPENCODE_DEFAULT_MODEL", "?")
                print_ok(f"Codex MCP ({CODEX_CONFIG_PATH}) : '{BRIDGE_NAME}' enabled (model: '{env_model}')")
            else:
                print_info(f"Codex MCP ({CODEX_CONFIG_PATH}) : '{BRIDGE_NAME}' not configured")
        except Exception:
            print_warn(f"Could not parse {CODEX_CONFIG_PATH}")
    else:
        print_info(f"Codex config not found at {CODEX_CONFIG_PATH}")

    for agy_path in (AGY_GLOBAL_MCP_PATH, AGY_CLI_MCP_PATH):
        if agy_path.is_file():
            data = load_json_file(agy_path)
            srv = (data.get("mcpServers") or {}).get(BRIDGE_NAME)
            if isinstance(srv, dict) and not srv.get("disabled", False):
                env_model = (srv.get("env") or {}).get("OPENCODE_DEFAULT_MODEL", "?")
                print_ok(f"Gemini `agy` MCP ({agy_path}) : '{BRIDGE_NAME}' enabled (model: '{env_model}')")
            else:
                print_info(f"Gemini `agy` MCP ({agy_path}) : '{BRIDGE_NAME}' not configured")
        else:
            print_info(f"Gemini `agy` MCP config not found at {agy_path}")


# ---------------------------------------------------------------------------
# GPU Headroom & Recommended Settings Display
# ---------------------------------------------------------------------------
def show_gpu_headroom() -> None:
    print_header("Checking NVIDIA GPU VRAM allocation & headroom (nvidia-smi)...")
    if not resolve_executable("nvidia-smi"):
        print_warn("`nvidia-smi` not found in PATH.")
        return

    res = run_cmd(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout=15,
        check=False,
    )
    if res.returncode != 0 or not res.stdout:
        print_warn("Could not query GPU memory via `nvidia-smi`.")
        return

    for line in res.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            gpu_name = parts[0]
            used_mib = float(parts[1])
            free_mib = float(parts[2])
            total_mib = float(parts[3])
            print_ok(
                f"GPU: {gpu_name} | Used: {used_mib / 1024:.2f} GiB ({int(used_mib)} MiB) | "
                f"Free Headroom: {free_mib / 1024:.2f} GiB ({int(free_mib)} MiB) | "
                f"Total: {total_mib / 1024:.2f} GiB"
            )
            if free_mib < 2048:
                print_warn(
                    "Less than 2.0 GiB VRAM headroom remaining! Consider Q4_K_M or Q8_0 KV cache for longer context."
                )


def show_recommended_settings(context_length: int) -> None:
    print_header(
        "Recommended LM Studio Per-Model Settings (My Models -> Qwen3.8-27B -> Gear Icon)"
    )
    print_info(
        "Note: `lms load` applies saved per-model GUI defaults for settings without CLI flags:\n"
    )
    kv_rec = (
        "Q8_0 (~53% memory) for 64K+ context"
        if context_length >= 65536
        else "F16 initially (100% baseline quality)"
    )
    rows = [
        ("Model Quantization", "Q4_K_M initially; test Q6_K", "Q6_K (~21.75 GiB) improves coding accuracy if headroom permits"),
        ("GPU Offload", "Max (--gpu max)", "Keeps all layers resident in RTX 5090 32 GB VRAM"),
        ("Context Length", f"{context_length} tokens", "32,768 baseline; test 65,536 or 131,072 with Q8_0 KV cache"),
        ("Flash Attention", "Enabled (GUI)", "Improves speed and reduces KV cache memory overhead"),
        ("KV Cache Offload", "GPU (GUI)", "Avoids PCIe CPU memory transfer bottlenecks"),
        ("K-Cache / V-Cache Type", kv_rec, "Avoid KV compression until scaling context to 64K/128K"),
        ("Enable Thinking", "On (GUI default)", "Crucial for multi-step coding and autonomous planning"),
        ("Reasoning Effort", "xhigh initially", "Qwen3.8 default; benchmark against 'medium' for latency"),
        ("Preserve Thinking", "On (GUI default)", "Maintains multi-turn reasoning continuity across tool calls"),
        ("Concurrent Requests", "1 initially", "Prevents VRAM spikes and contention during agent runs"),
        ("MTP / Speculative Dec.", "Off initially", "Avoids baseline complexity before benchmarking"),
    ]
    print(f"    {'Setting':<24} {'Recommendation':<38} {'Why'}")
    print(f"    {'-' * 24} {'-' * 38} {'-' * 60}")
    for s, r, w in rows:
        print(f"    {s:<24} {r:<38} {w}")


# ---------------------------------------------------------------------------
# Server Management & Foreground Loop
# ---------------------------------------------------------------------------
def ensure_lms_http_server(lms_port: int, nickname: str) -> str:
    print_header(f"Starting/verifying LM Studio HTTP API on 127.0.0.1:{lms_port}...")
    lms_url = f"http://127.0.0.1:{lms_port}"

    st_res = run_cmd(["lms", "server", "status", "--json", "--quiet"], check=False)
    was_running = False
    if st_res.returncode == 0 and st_res.stdout.startswith("{"):
        st = json.loads(st_res.stdout)
        was_running = bool(st.get("running"))
        port = int(st.get("port") or lms_port)
        if was_running and port != lms_port:
            raise RuntimeError(
                f"LM Studio server is already running on port {port}, not {lms_port}."
            )

    if not was_running:
        print_work(f"Starting LM Studio HTTP server on 127.0.0.1:{lms_port}...")
        run_cmd(
            ["lms", "server", "start", "--port", str(lms_port), "--bind", "127.0.0.1"],
            check=True,
        )

    api = wait_http_json(f"{lms_url}/v1/models", max_seconds=30, label="LM Studio API")
    if not api:
        raise RuntimeError(f"LM Studio API failed readiness check at {lms_url}/v1/models.")

    model_ids = [str(m.get("id") or "") for m in (api.get("data") or [])]
    if nickname not in model_ids:
        raise RuntimeError(
            f"LM Studio API is reachable at {lms_url}/v1/models, but '{nickname}' is not advertised."
        )

    state_label = "Already running" if was_running else "Started and running"
    print_ok(f"LM Studio HTTP API : {state_label} at {lms_url} (advertising '{nickname}')")
    return state_label


def verify_opencode_provider(opencode_url: str, nickname: str) -> tuple[bool, str]:
    cfg = http_get_json(f"{opencode_url}/config")
    if not cfg:
        return False, "/config endpoint unavailable"
    expected_model = f"{PROVIDER_ID}/{nickname}"
    if cfg.get("model") != expected_model:
        return False, f"server active model is '{cfg.get('model')}', expected '{expected_model}'"

    catalog = http_get_json(f"{opencode_url}/config/providers")
    if not catalog:
        return False, "/config/providers endpoint unavailable"
    providers = catalog.get("providers") or []
    lm_prov = next((p for p in providers if p.get("id") == PROVIDER_ID), None)
    if not lm_prov:
        return False, f"provider '{PROVIDER_ID}' not loaded"
    models = lm_prov.get("models") or {}
    if nickname not in models:
        return False, f"nickname '{nickname}' not listed in OpenCode provider models"
    return True, "ok"


def stop_process_on_port_windows(port: int) -> bool:
    if os.name != "nt":
        return False
    res = run_cmd(["netstat", "-ano", "-p", "tcp"], check=False)
    pids: set[int] = set()
    for line in res.stdout.splitlines():
        if f"127.0.0.1:{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(int(parts[-1]))
    for pid in pids:
        run_cmd(["taskkill", "/F", "/PID", str(pid)], check=False)
    return bool(pids)


def run_opencode_server_foreground(
    opencode_port: int,
    lms_port: int,
    nickname: str,
    lms_state: str,
    enable_codex: bool,
    enable_agy: bool,
) -> None:
    opencode_url = f"http://127.0.0.1:{opencode_port}"
    print_header(f"Starting/verifying OpenCode HTTP server on 127.0.0.1:{opencode_port}...")

    health = http_get_json(f"{opencode_url}/global/health")
    proc: subprocess.Popen[str] | None = None
    opencode_state = "Started and running"

    if health and health.get("healthy"):
        ok, reason = verify_opencode_provider(opencode_url, nickname)
        if ok:
            opencode_state = f"Already running (v{health.get('version', 'unknown')})"
            print_ok(
                f"OpenCode HTTP Server: {opencode_state} at {opencode_url} ({PROVIDER_ID}/{nickname})"
            )
        else:
            print_warn(
                f"Existing OpenCode server on port {opencode_port} has stale config ({reason}); restarting..."
            )
            stop_process_on_port_windows(opencode_port)
            time.sleep(1.0)
            health = None

    if not health:
        print_work(
            f"Starting `opencode serve --hostname 127.0.0.1 --port {opencode_port}`..."
        )
        opencode_exe = resolve_executable("opencode") or "opencode"
        cmd = (
            ["cmd.exe", "/d", "/c", f"opencode serve --hostname 127.0.0.1 --port {opencode_port}"]
            if os.name == "nt"
            else [opencode_exe, "serve", "--hostname", "127.0.0.1", "--port", str(opencode_port)]
        )
        proc = subprocess.Popen(
            cmd,
            cwd=str(HOME_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        health = wait_http_json(
            f"{opencode_url}/global/health", max_seconds=40, label="OpenCode HTTP server"
        )
        if not health or not health.get("healthy"):
            if proc:
                proc.terminate()
            raise RuntimeError(
                f"OpenCode server failed health check at {opencode_url}/global/health."
            )
        ok, reason = verify_opencode_provider(opencode_url, nickname)
        if not ok:
            if proc:
                proc.terminate()
            raise RuntimeError(f"OpenCode configuration check failed: {reason}")
        opencode_state = f"Started and running (v{health.get('version', 'unknown')})"
        print_ok(
            f"OpenCode HTTP Server: {opencode_state} at {opencode_url} ({PROVIDER_ID}/{nickname})"
        )

    # Print active servers summary banner
    print_header("Active Services & Bridge Status")
    print_ok(f"LM Studio HTTP API  : {lms_state} -> http://127.0.0.1:{lms_port}/v1 (model: '{nickname}')")
    print_ok(f"OpenCode HTTP Server: {opencode_state} -> {opencode_url} ({PROVIDER_ID}/{nickname})")
    if enable_codex:
        print_ok(f"Codex MCP Bridge    : Configured ('{BRIDGE_NAME}' in {CODEX_CONFIG_PATH})")
    if enable_agy:
        print_ok(
            f"Gemini `agy` Bridge : Configured ('{BRIDGE_NAME}' in {AGY_GLOBAL_MCP_PATH} & {AGY_CLI_MCP_PATH})"
        )

    clients_str = " & ".join(
        [c for c, en in [("Codex", enable_codex), ("Gemini `agy`", enable_agy)] if en]
    ) or "OpenCode"
    print(
        f"\n{Style.GREEN}{Style.BOLD}âœ“ READY: [{clients_str}] -> {BRIDGE_NAME} -> OpenCode ({opencode_url}) -> LM Studio/{nickname}{Style.RESET}"
    )
    print(
        f"{Style.YELLOW}! Holding OpenCode server active. Press 'q' or Ctrl+C to stop and exit...{Style.RESET}\n",
        flush=True,
    )

    stop_event = threading.Event()
    if proc and proc.stdout:
        def _drain_logs() -> None:
            assert proc is not None and proc.stdout is not None
            for line in proc.stdout:
                if stop_event.is_set():
                    break
                stripped = line.rstrip()
                if stripped:
                    print(f"    {Style.GRAY}[opencode] {stripped}{Style.RESET}", flush=True)

        t = threading.Thread(target=_drain_logs, daemon=True)
        t.start()

    try:
        while True:
            if proc is not None and proc.poll() is not None:
                print_warn(f"OpenCode server process exited with code {proc.returncode}.")
                break
            if os.name == "nt":
                import msvcrt

                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("q", "Q", "\x03"):
                        print_info("Received 'q' keypress; shutting down OpenCode server...")
                        break
            time.sleep(0.25)
    except KeyboardInterrupt:
        print()
        print_info("Received Ctrl+C; shutting down OpenCode server...")
    finally:
        stop_event.set()
        if proc is not None and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                proc.terminate()
            print_ok("Stopped OpenCode HTTP server.")


# ---------------------------------------------------------------------------
# Argument Parser & Main Workflow
# ---------------------------------------------------------------------------
def build_parser(*, runtime_only: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local_agent run" if runtime_only else "local-agent-bridge",
        description="Configure, load, and manage local LM Studio models for Codex and Antigravity (`agy`) via OpenCode.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  local-agent-bridge ls
  local-agent-bridge -m qwen/qwen3.8-27b@q4_k_m
  local-agent-bridge -m qwen/qwen3.8-27b -v q6_k -c 32768
  local-agent-bridge -M qwen38_23GB -m qwen/qwen3.8-27b@q6_k
  local-agent-bridge -M qwen38_17GB
  local-agent-bridge --rename-model qwen38_17GB qwen-q4
  local-agent-bridge -D qwen-q4
  local-agent-bridge -m qwen/qwen3.8-27b@q6_k -N
""",
    )
    parser.set_defaults(command=None, ls=False, delete_model="", rename_model=None)
    if not runtime_only:
        parser.add_argument(
            "command",
            nargs="?",
            choices=["ls"],
            help="Optional positional command: 'ls' to list available LM Studio models, loaded instances, and OpenCode nicknames.",
        )
        parser.add_argument(
            "--ls",
            action="store_true",
            help="List available LM Studio models/variants, loaded models, and configured OpenCode nicknames.",
        )
    parser.add_argument(
        "-m",
        "--model",
        default="",
        help="LM Studio model key to load, optionally with @variant (e.g., 'qwen/qwen3.8-27b@q4_k_m').",
    )
    parser.add_argument(
        "-v",
        "--variant",
        "--quantization",
        dest="variant",
        default="",
        help="Model quantization/variant (e.g., 'q4_k_m' or 'q6_k'). Overrides or appends @variant to -m.",
    )
    parser.add_argument(
        "-M",
        "--model-nickname",
        "--alias",
        dest="nickname",
        default="",
        help="Named model identifier in OpenCode, Codex MCP, Gemini `agy` MCP, and LM Studio (default: active nickname or 'qwen-local').",
    )
    if not runtime_only:
        parser.add_argument(
            "-D",
            "--delete-model",
            "--remove-model",
            dest="delete_model",
            metavar="NICKNAME",
            default="",
            help="Unload and remove the specified model nickname from opencode.json (and clean up configs if none remain).",
        )
        parser.add_argument(
            "--rename-model",
            nargs=2,
            metavar=("OLD_NICK", "NEW_NICK"),
            help="Rename an existing model nickname in opencode.json, Codex config.toml, and Gemini `agy` mcp_config.json.",
        )
    parser.add_argument(
        "-c",
        "--context-length",
        type=int,
        default=None,
        help=f"Context length in tokens for `lms load` (default: {DEFAULT_CONTEXT}).",
    )
    parser.add_argument(
        "-g",
        "--gpu",
        default=DEFAULT_GPU,
        help="GPU offload setting for `lms load`: 'max', 'off', or 0.0-1.0 (default: 'max').",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=0,
        help="Optional auto-unload TTL in seconds for `lms load --ttl`.",
    )
    parser.add_argument(
        "-R",
        "--reload",
        action="store_true",
        help="Force unloading and reloading the model even if it is already loaded in LM Studio.",
    )
    parser.add_argument(
        "-U",
        "--no-unload",
        "--keep-other-models",
        dest="no_unload",
        action="store_true",
        help="Keep other currently loaded LLM models in VRAM instead of unloading them when loading/switching models.",
    )
    parser.add_argument(
        "-N",
        "--no-servers",
        action="store_true",
        help="Configure files and load the model into LM Studio, but do not start or wait on HTTP servers.",
    )
    parser.add_argument(
        "--no-codex",
        action="store_true",
        help="Skip updating Codex MCP configuration (~/.codex/config.toml).",
    )
    parser.add_argument(
        "--no-agy",
        action="store_true",
        help="Skip updating Google Gemini Antigravity (`agy`) MCP & permission configuration (~/.gemini/...).",
    )
    parser.add_argument(
        "-p",
        "--opencode-port",
        type=int,
        default=DEFAULT_OPENCODE_PORT,
        help=f"Port for `opencode serve` and MCP OPENCODE_BASE_URL (default: {DEFAULT_OPENCODE_PORT}).",
    )
    parser.add_argument(
        "--lms-port",
        type=int,
        default=DEFAULT_LMS_PORT,
        help=f"Port for LM Studio local HTTP server (default: {DEFAULT_LMS_PORT}).",
    )
    parser.add_argument(
        "--models-dir",
        default="",
        help="Optional override path for LM Studio's downloaded models directory.",
    )
    if runtime_only:
        parser.epilog = "Examples:\n  local_agent run -M qwen38_23GB\n  local_agent run -m qwen/qwen3.8-27b@q6_k -c 32768"
    return parser


def check_prerequisites(gpu: str, enable_codex: bool, enable_agy: bool) -> None:
    print_header("Checking Python, Node.js, LM Studio CLI, OpenCode, Codex, and Gemini `agy`...")
    for cmd_name in ("lms", "node", "npm", "npx"):
        if not resolve_executable(cmd_name):
            raise RuntimeError(f"Required command '{cmd_name}' was not found in PATH.")

    node_ver_res = run_cmd(["node", "--version"], check=True)
    node_ver = node_ver_res.stdout.lstrip("v").strip()
    major = int(node_ver.split(".")[0]) if node_ver and node_ver[0].isdigit() else 0
    if major < 22:
        raise RuntimeError(f"Node.js 22+ is required (found {node_ver}).")

    if not re.match(r"^(max|off|0(?:\.\d+)?|1(?:\.0+)?)$", gpu):
        raise RuntimeError(
            f"Invalid --gpu '{gpu}'. Choose 'max', 'off', or a fraction between 0 and 1."
        )

    if not resolve_executable("opencode"):
        print_work("OpenCode CLI not found; installing `opencode-ai` globally via npm...")
        run_cmd(["npm", "install", "-g", "opencode-ai"], timeout=300, check=True)

    oc_ver = run_cmd(["opencode", "--version"], check=True).stdout.strip()

    cli_notes = [
        f"Python {sys.version.split()[0]}",
        f"Node.js {node_ver}",
        f"OpenCode {oc_ver}",
    ]
    if enable_codex:
        if resolve_executable("codex"):
            cli_notes.append("codex CLI found")
        else:
            print_warn("`codex` CLI not found in PATH (will still configure ~/.codex/config.toml).")
    if enable_agy:
        if resolve_executable("agy"):
            cli_notes.append("agy CLI found")
        else:
            print_info("`agy` CLI not found in PATH (will still configure ~/.gemini/... MCP & permission files).")

    print_ok(f"Prerequisites verified ({', '.join(cli_notes)})")


def resolve_nickname_and_model(args: argparse.Namespace) -> tuple[str, str]:
    cfg = load_opencode_config() if OPENCODE_CONFIG_PATH.is_file() else {}

    nickname = args.nickname.strip()
    if not nickname:
        active = str(cfg.get("model") or "")
        if active.startswith(f"{PROVIDER_ID}/"):
            nickname = active.split("/", 1)[1].strip()
        else:
            nickname = DEFAULT_NICKNAME

    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", nickname):
        raise RuntimeError(
            f"Invalid model nickname '{nickname}'. Use letters, digits, '.', '_', or '-'."
        )

    model_spec = args.model.strip()
    if not model_spec:
        existing_spec = extract_model_spec_from_opencode(cfg, nickname)
        if existing_spec:
            model_spec = existing_spec
            print_info(
                f"Resolved model '{model_spec}' from existing nickname '{nickname}' in opencode.json"
            )
        elif nickname == DEFAULT_NICKNAME:
            model_spec = DEFAULT_MODEL
        else:
            raise RuntimeError(
                f"Nickname '{nickname}' is not yet in {OPENCODE_CONFIG_PATH}. "
                f"Pass `-m <model_key>` (e.g. `-M {nickname} -m {DEFAULT_MODEL}`) to add it."
            )

    if args.variant.strip():
        base_only = model_spec.split("@", 1)[0]
        model_spec = f"{base_only}@{args.variant.strip().lower()}"

    return nickname, model_spec


def unload_other_loaded_llms(active_nickname: str) -> None:
    """
    Unloads any other currently loaded LLM instances from LM Studio memory (unless
    -U/--no-unload is passed) so multiple large models (e.g. qwen38-27b-q4km and
    qwen38-27b-q6k) are never simultaneously resident in 32 GB VRAM.
    """
    for item in list_all_loaded_models():
        if item.identifier != active_nickname and not item.is_embedding:
            label = f"{item.identifier} ({item.model})" if item.model else item.identifier
            print_info(
                f"Unloading other loaded LLM '{label}' to free GPU VRAM (`lms unload {item.identifier}`)..."
            )
            run_cmd(["lms", "unload", item.identifier], check=False)
            print_ok(f"Unloaded '{item.identifier}'.")


def main(argv: list[str] | None = None, *, runtime_only: bool = False) -> int:
    parser = build_parser(runtime_only=runtime_only)
    args = parser.parse_args(argv)

    enable_codex = not args.no_codex
    enable_agy = not args.no_agy

    try:
        # 1. Handle `ls` subcommand / flag
        if args.command == "ls" or args.ls:
            handle_ls_command()
            return 0

        # 2. Handle `-D / --delete-model`
        if args.delete_model:
            handle_delete_model(args.delete_model.strip(), args.opencode_port)
            return 0

        # 3. Handle `--rename-model`
        if args.rename_model:
            handle_rename_model(
                args.rename_model[0].strip(),
                args.rename_model[1].strip(),
                args.lms_port,
                args.opencode_port,
            )
            return 0

        # 4. Standard load & bridge workflow
        check_prerequisites(args.gpu, enable_codex, enable_agy)
        nickname, requested_model = resolve_nickname_and_model(args)

        print_header(
            f"Resolving LM Studio model '{requested_model}' for nickname '{nickname}'..."
        )
        selection = resolve_model_selection(requested_model, args.models_dir)
        print_ok(
            f"Validated model '{selection.display}' (load key: '{selection.load_key}'"
            + (f", disk size: {selection.expected_size}" if selection.expected_size else "")
            + ")"
        )

        # 5. Check if already loaded in LM Studio (`lms ps`) & free inactive nicknames
        effective_context = args.context_length if args.context_length is not None else DEFAULT_CONTEXT
        print_header(f"Checking if identifier '{nickname}' is already loaded (lms ps)...")
        if not args.no_unload:
            unload_other_loaded_llms(nickname)

        loaded, _ = get_loaded_instance(nickname)
        already_loaded = is_same_model_loaded(loaded, selection, args.context_length)

        if already_loaded and not args.reload:
            print_ok(
                f"Model '{selection.display}' is already loaded as '{nickname}' "
                f"(path: {loaded.model_Or_path}, size: {loaded.size_gib}, context: {loaded.context_length}). "
                f"Skipping reload (use -R/--reload to force)."
            )
        else:
            if loaded is not None:
                print_info(
                    f"Unloading existing '{nickname}' ({loaded.model_Or_path}) from memory (`lms unload {nickname}`)..."
                )
                run_cmd(["lms", "unload", nickname], check=True)
                print_ok(f"Unloaded '{nickname}'.")

            load_cmd = [
                "lms",
                "load",
                selection.load_key,
                "--identifier",
                nickname,
                "--gpu",
                args.gpu,
                "--context-length",
                str(effective_context),
                "-y",
            ]
            if args.ttl > 0:
                load_cmd.extend(["--ttl", str(args.ttl)])

            print_header(
                f"Loading '{selection.display}' as '{nickname}' ({' '.join(load_cmd)})..."
            )
            t0 = time.monotonic()
            run_cmd(
                load_cmd,
                timeout=600,
                heartbeat_label=f"Loading '{selection.display}' into GPU memory",
                check=True,
            )
            elapsed_load = time.monotonic() - t0
            print_ok(f"Model loaded in {elapsed_load:.2f}s as identifier '{nickname}'.")

        # 6. Verify loaded model instance (`lms ps` & `lms ps --json`)
        print_header("Verifying loaded model instance (lms ps)...")
        loaded, ps_table = get_loaded_instance(nickname)
        if ps_table:
            print(ps_table)

        print_header("Inspecting machine-readable instance metadata (lms ps --json)...")
        if loaded is None or not is_same_model_loaded(loaded, selection, args.context_length):
            obs = loaded.model_Or_path if loaded else "<not loaded>"
            raise RuntimeError(
                f"Verification failed: LM Studio reports '{obs}' for '{nickname}', "
                f"which does not match requested '{selection.display}'."
            )
        print_ok(f"Verified API Identifier : {loaded.identifier}")
        print_ok(f"Underlying GGUF Path    : {loaded.model_Or_path}")
        print_ok(
            f"Reported Model Size     : {loaded.size_gib} "
            f"(Expected ~16.52 GiB / 17.74 GB for Q4_K_M, ~20.89-21.75 GiB / 23.36 GB for Q6_K)"
        )

        # 7. Check GPU VRAM headroom via `nvidia-smi`
        show_gpu_headroom()

        # 8. Show recommended LM Studio GUI settings table
        show_recommended_settings(effective_context)

        # 9. Update OpenCode, Codex MCP, and Gemini `agy` MCP configuration files
        print_header("Synchronizing OpenCode, Codex MCP, and Gemini `agy` Configuration Files...")
        oc_changed = update_opencode_for_model(nickname, selection.display, args.lms_port)
        print_ok(
            f"OpenCode config ({OPENCODE_CONFIG_PATH}): "
            + (
                f"updated active model to '{PROVIDER_ID}/{nickname}' ({selection.display})"
                if oc_changed
                else f"already set to '{PROVIDER_ID}/{nickname}' ({selection.display})"
            )
        )

        if enable_codex:
            codex_changed = update_codex_mcp_toml(nickname, args.opencode_port)
            print_ok(
                f"Codex MCP config ({CODEX_CONFIG_PATH}): "
                + (
                    f"updated '{BRIDGE_NAME}' (OPENCODE_DEFAULT_MODEL='{nickname}', port={args.opencode_port})"
                    if codex_changed
                    else f"'{BRIDGE_NAME}' already up to date (OPENCODE_DEFAULT_MODEL='{nickname}')"
                )
            )

        if enable_agy:
            agy_changed, agy_paths = update_agy_mcp_configs(nickname, args.opencode_port)
            paths_str = f"{agy_paths[0]} & {agy_paths[1]}"
            print_ok(
                f"Gemini `agy` MCP config ({paths_str}): "
                + (
                    f"updated '{BRIDGE_NAME}' & auto-allowed 'mcp({BRIDGE_NAME}/*)' in {AGY_CLI_SETTINGS_PATH}"
                    if agy_changed
                    else f"'{BRIDGE_NAME}' & permissions already up to date (OPENCODE_DEFAULT_MODEL='{nickname}')"
                )
            )

        # 10. Start/verify servers and stay running unless -N/--no-servers is passed
        if args.no_servers:
            print_header("Server Startup Skipped (-N / --no-servers)")
            print_info("LM Studio HTTP server and OpenCode HTTP server were not started.")
            clients_str = " & ".join(
                [c for c, en in [("Codex", enable_codex), ("Gemini `agy`", enable_agy)] if en]
            ) or "OpenCode"
            print(
                f"\n{Style.GREEN}{Style.BOLD}âœ“ CONFIGURED: [{clients_str}] -> {BRIDGE_NAME} -> OpenCode -> LM Studio/{nickname} ({selection.display}){Style.RESET}"
            )
            return 0

        lms_state = ensure_lms_http_server(args.lms_port, nickname)
        run_opencode_server_foreground(
            args.opencode_port,
            args.lms_port,
            nickname,
            lms_state,
            enable_codex,
            enable_agy,
        )
        return 0

    except Exception as exc:
        print_fail(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
