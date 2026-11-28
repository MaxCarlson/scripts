"""Idempotent, dry-run-first shell adapter generator and profile integration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from scripts_help._repo_root import find_repo_root
from scripts_help.command_registry import CollisionRecord, detect_collisions, load_command_registry

MANAGED_START = "# >>> scripts-help managed ag integration >>>"
MANAGED_END = "# <<< scripts-help managed ag integration <<<"


def render_pwsh_adapter() -> str:
    """Return thin PowerShell adapter that exports live aliases/functions to Python `ag`."""
    return "\n".join(
        [
            MANAGED_START,
            "# Thin adapter for Python `ag`: exports live session aliases/functions without shadowing other commands.",
            "Remove-Item Alias:ag -ErrorAction SilentlyContinue",
            "function global:ag {",
            "    [CmdletBinding()]",
            "    param(",
            "        [Parameter(ValueFromRemainingArguments = $true)]",
            "        [string[]]$Arguments",
            "    )",
            "    $tmpFile = [System.IO.Path]::GetTempFileName()",
            "    try {",
            "        $homePrefix = [System.IO.Path]::GetFullPath($HOME).TrimEnd('\\') + '\\'",
            "        $isUserPath = { param($path) if (-not $path) { return $false }; try { [System.IO.Path]::GetFullPath($path).StartsWith($homePrefix, [System.StringComparison]::OrdinalIgnoreCase) } catch { $false } }",
            "        $items = [System.Collections.Generic.List[object]]::new()",
            "        foreach ($a in (Get-Alias -ErrorAction SilentlyContinue)) {",
            "            $module = if ($a.ModuleName) { Get-Module -Name $a.ModuleName | Select-Object -First 1 } else { $null }",
            "            $curated = (-not $a.ModuleName) -or (& $isUserPath $module.ModuleBase)",
            "            $items.Add([PSCustomObject]@{",
            "                name       = $a.Name",
            "                kind       = 'shell_alias'",
            "                source     = 'pwsh'",
            "                definition = [string]$a.Definition",
            "                description = 'PowerShell alias'",
            "                curated    = [bool]$curated",
            "            })",
            "        }",
            "        foreach ($f in (Get-Command -CommandType Function -ErrorAction SilentlyContinue)) {",
            "            if ($f.Name -eq 'ag') { continue }",
            "            $def = [string]$f.Definition",
            "            if ($def.Length -gt 200) { $def = $def.Substring(0, 200) + '...' }",
            "            $module = if ($f.ModuleName) { Get-Module -Name $f.ModuleName | Select-Object -First 1 } else { $null }",
            "            $functionFile = [string]$f.ScriptBlock.File",
            "            $curated = (-not $f.ModuleName -and -not $functionFile) -or (& $isUserPath $functionFile) -or (& $isUserPath $module.ModuleBase)",
            "            $items.Add([PSCustomObject]@{",
            "                name       = $f.Name",
            "                kind       = 'shell_function'",
            "                source     = 'pwsh'",
            "                definition = ($def -replace '\\r?\\n', ' ')",
            "                description = 'PowerShell function'",
            "                curated    = [bool]$curated",
            "            })",
            "        }",
            "        @{ shell = 'pwsh'; items = $items } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tmpFile -Encoding UTF8",
            "        $prev = $env:AG_SHELL_INVENTORY_FILE",
            "        $env:AG_SHELL_INVENTORY_FILE = $tmpFile",
            "        try {",
            "            $agCmd = Get-Command ag.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1",
            "            if ($agCmd) {",
            "                & $agCmd.Source @Arguments",
            "            } else {",
            "                & python -m scripts_help.ag @Arguments",
            "            }",
            "        } finally {",
            "            if ($null -eq $prev) { Remove-Item Env:AG_SHELL_INVENTORY_FILE -ErrorAction SilentlyContinue } else { $env:AG_SHELL_INVENTORY_FILE = $prev }",
            "        }",
            "    } finally {",
            "        Remove-Item -LiteralPath $tmpFile -Force -ErrorAction SilentlyContinue",
            "    }",
            "}",
            "function global:fg { ag --view full @args }",
            "function global:mg { ag --view module @args }",
            "function global:xg { ag --view all @args }",
            MANAGED_END,
            "",
        ]
    )


def render_posix_adapter() -> str:
    """Return thin Bash/Zsh adapter that exports live aliases/functions to Python `ag`."""
    return "\n".join(
        [
            MANAGED_START,
            "# Thin adapter for Python `ag` on Bash/Zsh.",
            "ag() {",
            "    local _ag_tmp _ag_raw _ag_fn_raw _ag_shell _ag_rc _ag_extdebug _ag_name",
            '    _ag_tmp="$(mktemp 2>/dev/null || printf "/tmp/ag_inv_%s.json" "$$")"',
            '    _ag_raw="$(mktemp 2>/dev/null || printf "/tmp/ag_raw_%s.txt" "$$")"',
            '    _ag_fn_raw="$(mktemp 2>/dev/null || printf "/tmp/ag_fn_%s.txt" "$$")"',
            "    _ag_shell='sh'",
            '    if [ -n "${ZSH_VERSION:-}" ]; then',
            '        _ag_shell="zsh"',
            '        for _ag_name in ${(k)functions}; do print -r -- "$_ag_name\t${functions_source[$_ag_name]}"; done > "$_ag_fn_raw" 2>/dev/null || true',
            '    elif [ -n "${BASH_VERSION:-}" ]; then',
            '        _ag_shell="bash"',
            '        shopt -q extdebug && _ag_extdebug=1 || _ag_extdebug=0',
            '        shopt -s extdebug',
            '        while read -r _ag_decl _ag_flag _ag_name _ag_source; do',
            '            [ "$_ag_decl" = "declare" ] && [ "$_ag_flag" = "-f" ] && printf "%s\\t%s\\n" "$_ag_name" "$_ag_source" || true',
            '        done < <(declare -F 2>/dev/null) > "$_ag_fn_raw"',
            '        [ "$_ag_extdebug" = 1 ] || shopt -u extdebug',
            "    fi",
            '    alias > "$_ag_raw" 2>/dev/null || true',
            '    python3 - "$_ag_shell" "$_ag_raw" "$_ag_fn_raw" "$_ag_tmp" <<\'__AG_PY__\'',
            "import json, pathlib, re, sys",
            "shell, alias_file, fn_file, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]",
            "items = []",
            "for line in pathlib.Path(alias_file).read_text(encoding='utf-8', errors='replace').splitlines():",
            '    s = re.sub(r"^alias\\s+", "", line.strip())',
            '    if "=" not in s:',
            "        continue",
            '    name, val = s.split("=", 1)',
            '    items.append({"name": name.strip(), "kind": "shell_alias", "source": shell, "definition": val.strip().strip("\'\\\""), "description": f"{shell} alias", "curated": True})',
            "for fn_line in pathlib.Path(fn_file).read_text(encoding='utf-8', errors='replace').splitlines():",
            '    fn_name, _, fn_source = fn_line.partition("\\t")',
            "    fn_name, fn_source = fn_name.strip(), fn_source.strip()",
            '    if fn_name and fn_name != "ag":',
            '        home = pathlib.Path.home().resolve()',
            '        try: user_owned = not fn_source or pathlib.Path(fn_source).resolve().is_relative_to(home)',
            '        except (OSError, ValueError): user_owned = not fn_source',
            '        items.append({"name": fn_name, "kind": "shell_function", "source": shell, "definition": f"{shell} function", "description": f"{shell} function", "curated": user_owned})',
            'pathlib.Path(out).write_text(json.dumps({"shell": shell, "items": items}), encoding="utf-8")',
            "__AG_PY__",
            '    AG_SHELL_INVENTORY_FILE="$_ag_tmp" command ag "$@"',
            "    _ag_rc=$?",
            '    rm -f "$_ag_tmp" "$_ag_raw" "$_ag_fn_raw"',
            "    return $_ag_rc",
            "}",
            "fg() { ag --view full \"$@\"; }",
            "mg() { ag --view module \"$@\"; }",
            "xg() { ag --view all \"$@\"; }",
            MANAGED_END,
            "",
        ]
    )


def _upsert_managed_block(existing: str, block: str) -> str:
    if MANAGED_START in existing and MANAGED_END in existing:
        pre = existing.split(MANAGED_START, 1)[0]
        post = existing.split(MANAGED_END, 1)[1].lstrip("\r\n")
        combined = pre.rstrip("\r\n") + ("\n\n" if pre.strip() else "") + block
        if post:
            combined += "\n" + post
        return combined
    if not existing.strip():
        return block
    return existing.rstrip("\r\n") + "\n\n" + block


def _remove_managed_block(existing: str) -> str:
    if MANAGED_START not in existing or MANAGED_END not in existing:
        return existing
    pre = existing.split(MANAGED_START, 1)[0].rstrip("\r\n")
    post = existing.split(MANAGED_END, 1)[1].lstrip("\r\n")
    if pre and post:
        return pre + "\n\n" + post
    if pre:
        return pre + "\n"
    return post


@dataclass(frozen=True)
class IntegrationAction:
    path: str
    status: str  # create, update, unchanged, remove, missing, drift
    details: str


def run_integration(
    *,
    target_dir: Path,
    apply: bool = False,
    check: bool = False,
    rollback: bool = False,
    shells: Sequence[str] = ("pwsh", "posix"),
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Plan, check, apply, or rollback managed shell integration files."""
    root = repo_root
    if root is None:
        try:
            root = find_repo_root()
        except RuntimeError:
            root = None

    targets: list[tuple[Path, str]] = []
    if "pwsh" in shells:
        targets.append((target_dir / "ag_integration.ps1", render_pwsh_adapter()))
    if "posix" in shells:
        targets.append((target_dir / "ag_integration.sh", render_posix_adapter()))

    actions: list[IntegrationAction] = []
    for path, block in targets:
        if rollback:
            if not path.exists():
                actions.append(IntegrationAction(str(path), "missing", "Not installed"))
                continue
            current = path.read_text(encoding="utf-8")
            updated = _remove_managed_block(current)
            if not updated.strip():
                actions.append(IntegrationAction(str(path), "remove", "Remove managed integration file"))
                if apply:
                    path.unlink()
            elif updated != current:
                actions.append(IntegrationAction(str(path), "update", "Remove managed block while preserving user content"))
                if apply:
                    path.write_text(updated, encoding="utf-8")
            else:
                actions.append(IntegrationAction(str(path), "unchanged", "No managed block present"))
            continue

        if not path.exists():
            status = "drift" if check else "create"
            actions.append(IntegrationAction(str(path), status, "Install managed ag adapter"))
            if apply and not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(block, encoding="utf-8")
        else:
            current = path.read_text(encoding="utf-8")
            updated = _upsert_managed_block(current, block)
            if updated == current:
                actions.append(IntegrationAction(str(path), "unchanged", "Already up to date"))
            else:
                status = "drift" if check else "update"
                actions.append(IntegrationAction(str(path), status, "Update managed ag adapter block"))
                if apply and not check:
                    path.write_text(updated, encoding="utf-8")

    collisions: list[CollisionRecord] = []
    if root is not None:
        entries = load_command_registry(root)
        collisions = detect_collisions(entries, repo_root=root, check_path=True)

    return {
        "dry_run": not apply and not check,
        "check": check,
        "rollback": rollback,
        "actions": [
            {"path": a.path, "status": a.status, "details": a.details} for a in actions
        ],
        "collisions": [c.to_dict() for c in collisions],
        "clean": all(a.status in ("unchanged", "missing") for a in actions),
    }
