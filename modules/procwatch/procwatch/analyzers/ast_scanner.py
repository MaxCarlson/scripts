"""Static Python AST and PowerShell AST subprocess/console-launch scanner."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
import difflib
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from procwatch.config import get_data_dir
from procwatch.storage import FlightRecorderStorage

DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".pytest_tmp_root",
    }
)


class FindingCategory(StrEnum):
    """Context-aware classification of detected process-launch calls."""

    INCIDENT_LINKED = "incident_linked_launch"
    LIKELY_UNINTENDED = "likely_unintended_visible_launch"
    POTENTIAL_ISSUE = "potential_issue"
    INTENTIONAL_INTERACTIVE = "intentional_interactive"
    UNKNOWN_DYNAMIC = "unknown_dynamic"


@dataclass(slots=True)
class ScanFinding:
    """Single static process-launch finding with context and optional safe patch."""

    file_path: str
    line: int
    column: int
    language: str  # python | powershell
    mechanism: str
    call_excerpt: str
    category: FindingCategory
    confidence: str  # high | medium | low
    explanation: str
    remediation: str
    enclosing_symbol: str | None = None
    linked_incident_ids: list[int] = field(default_factory=list)
    proposed_replacement: str | None = None
    span: tuple[int, int, int, int] | None = None  # (lineno, col, end_lineno, end_col)
    file_sha256: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data


@dataclass(slots=True)
class ScanReport:
    """Aggregated scan output across Python and PowerShell files."""

    schema_version: int = 1
    roots: list[str] = field(default_factory=list)
    files_scanned: int = 0
    findings: list[ScanFinding] = field(default_factory=list)
    diffs: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "roots": list(self.roots),
            "files_scanned": self.files_scanned,
            "finding_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "diffs": dict(self.diffs),
            "errors": list(self.errors),
        }


def parse_git_worktree_porcelain(output: str) -> list[Path]:
    """Parse `git worktree list --porcelain` output safely, handling spaces and missing paths."""
    roots: list[Path] = []
    seen: set[str] = set()
    for raw_line in output.splitlines():
        if raw_line.startswith("worktree "):
            wt_str = raw_line[len("worktree ") :].strip()
            if not wt_str:
                continue
            wt_path = Path(wt_str)
            key = os.path.normcase(os.path.abspath(str(wt_path)))
            if key not in seen and wt_path.exists():
                seen.add(key)
                roots.append(wt_path)
    return roots


def discover_scan_roots(directory: Path, *, include_worktrees: bool = False) -> list[Path]:
    """Resolve root directories to scan without mutating any repository state."""
    base = directory.expanduser().resolve()
    if not include_worktrees:
        return [base]
    try:
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": 5.0,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(
            ["git", "-C", str(base), "worktree", "list", "--porcelain"],
            **kwargs,
        )
        if res.returncode == 0:
            wts = parse_git_worktree_porcelain(res.stdout)
            if wts:
                return wts
    except Exception:
        pass
    return [base]


def _iter_source_files(roots: list[Path]) -> tuple[list[Path], list[Path]]:
    """Collect Python and PowerShell files while skipping excluded directories and duplicates."""
    py_files: list[Path] = []
    ps_files: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            norm = os.path.normcase(os.path.abspath(str(root)))
            if norm not in seen:
                seen.add(norm)
                if root.suffix.lower() == ".py":
                    py_files.append(root)
                elif root.suffix.lower() in {".ps1", ".psm1"}:
                    ps_files.append(root)
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in DEFAULT_EXCLUDED_DIRS and not d.startswith(".pytest")
            ]
            for fname in filenames:
                low = fname.lower()
                if not (low.endswith(".py") or low.endswith(".ps1") or low.endswith(".psm1")):
                    continue
                fpath = Path(dirpath) / fname
                norm = os.path.normcase(os.path.abspath(str(fpath)))
                if norm in seen:
                    continue
                seen.add(norm)
                if low.endswith(".py"):
                    py_files.append(fpath)
                else:
                    ps_files.append(fpath)
    return sorted(py_files), sorted(ps_files)


class _PythonLaunchVisitor(ast.NodeVisitor):
    """AST visitor tracking subprocess/asyncio/os process-launch calls and enclosing context."""

    def __init__(self, source_text: str, file_path: str, file_sha256: str) -> None:
        self.source_text = source_text
        self.file_path = file_path
        self.file_sha256 = file_sha256
        self.findings: list[ScanFinding] = []
        self._aliases: dict[str, str] = {}  # local_name -> canonical dotted target
        self._symbol_stack: list[str] = []
        self._win_guard_depth = 0

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            as_name = alias.asname or alias.name.split(".")[0]
            self._aliases[as_name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            as_name = alias.asname or alias.name
            self._aliases[as_name] = f"{mod}.{alias.name}" if mod else alias.name
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._symbol_stack.append(node.name)
        self.generic_visit(node)
        self._symbol_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._symbol_stack.append(node.name)
        self.generic_visit(node)
        self._symbol_stack.pop()

    def visit_If(self, node: ast.If) -> None:
        test_src = ast.get_source_segment(self.source_text, node.test) or ""
        is_win_guard = "win32" in test_src or 'os.name == "nt"' in test_src or "os.name == 'nt'" in test_src
        if is_win_guard:
            self._win_guard_depth += 1
        self.generic_visit(node)
        if is_win_guard:
            self._win_guard_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        target = self._resolve_call_name(node.func)
        if target in {
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.call",
            "subprocess.check_call",
            "subprocess.check_output",
            "asyncio.create_subprocess_exec",
            "asyncio.create_subprocess_shell",
            "os.system",
            "os.popen",
        }:
            self._analyze_launch_call(node, target)
        self.generic_visit(node)

    def _resolve_call_name(self, func: ast.AST) -> str | None:
        if isinstance(func, ast.Name):
            return self._aliases.get(func.id, func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base = self._aliases.get(func.value.id, func.value.id)
            return f"{base}.{func.attr}"
        return None

    def _analyze_launch_call(self, node: ast.Call, target: str) -> None:
        excerpt = ast.get_source_segment(self.source_text, node) or target
        kw_map = {kw.arg: kw for kw in node.keywords if kw.arg is not None}
        has_creationflags = "creationflags" in kw_map
        has_startupinfo = "startupinfo" in kw_map
        has_pipe_or_devnull = any(
            (kw in kw_map and any(tok in (ast.get_source_segment(self.source_text, kw_map[kw].value) or "") for tok in ("PIPE", "DEVNULL")))
            for kw in ("stdout", "stderr", "stdin")
        )
        shell_true = False
        if "shell" in kw_map:
            shell_val = ast.get_source_segment(self.source_text, kw_map["shell"].value) or ""
            shell_true = shell_val.strip() == "True"

        enclosing = ".".join(self._symbol_stack) if self._symbol_stack else None
        is_dynamic = bool(node.args and not isinstance(node.args[0], (ast.Constant, ast.List, ast.Tuple)))
        interactive_hint = (
            (enclosing and "interactive" in enclosing.lower())
            or "interactive" in self.file_path.lower()
            or ("stdin" in kw_map and "None" in (ast.get_source_segment(self.source_text, kw_map["stdin"].value) or ""))
        )

        # Already hidden/suppressed
        if has_creationflags:
            cf_src = ast.get_source_segment(self.source_text, kw_map["creationflags"].value) or ""
            if "CREATE_NO_WINDOW" in cf_src or "0x08000000" in cf_src or "DETACHED_PROCESS" in cf_src:
                return
        if has_startupinfo:
            return

        proposed: str | None = None
        span: tuple[int, int, int, int] | None = None
        if node.end_lineno is not None and node.end_col_offset is not None:
            span = (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)

        if target == "os.system":
            category = FindingCategory.LIKELY_UNINTENDED
            confidence = "high"
            explanation = "os.system() invokes cmd.exe and allocates a visible console window when launched from a GUI/background host."
            remediation = "Replace os.system() with subprocess.run(..., creationflags=subprocess.CREATE_NO_WINDOW)."
        elif interactive_hint:
            category = FindingCategory.INTENTIONAL_INTERACTIVE
            confidence = "medium"
            explanation = "Call appears intentionally interactive (context/stdin hint); do not blindly hide its console."
            remediation = "Verify whether caller expects a live TTY; leave unchanged if interactive."
        elif is_dynamic and not has_pipe_or_devnull:
            category = FindingCategory.UNKNOWN_DYNAMIC
            confidence = "low"
            explanation = "Dynamic command expression without stream redirection; execution context cannot be proven statically."
            remediation = "Review dynamic command origin before adding CREATE_NO_WINDOW."
        elif has_pipe_or_devnull or shell_true or self._win_guard_depth > 0:
            category = FindingCategory.LIKELY_UNINTENDED
            confidence = "high"
            explanation = "Subprocess captures/redirects streams or runs in a background/Windows-guarded path without CREATE_NO_WINDOW."
            remediation = "Pass creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) on Windows."
            if target.startswith("subprocess.") and not has_creationflags and "**" not in excerpt:
                proposed = _inject_creationflags(excerpt)
        else:
            category = FindingCategory.POTENTIAL_ISSUE
            confidence = "medium"
            explanation = "Subprocess call lacks Windows window-suppression flags; may flash a console if invoked from a GUI/background parent."
            remediation = "If non-interactive, add creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)."

        self.findings.append(
            ScanFinding(
                file_path=self.file_path,
                line=node.lineno,
                column=node.col_offset,
                language="python",
                mechanism=target,
                call_excerpt=excerpt[:240],
                category=category,
                confidence=confidence,
                explanation=explanation,
                remediation=remediation,
                enclosing_symbol=enclosing,
                proposed_replacement=proposed,
                span=span,
                file_sha256=self.file_sha256,
            )
        )


def _inject_creationflags(call_src: str) -> str | None:
    """Safely insert creationflags into a single subprocess.*(...) call string and verify AST parse."""
    if "creationflags" in call_src or not call_src.rstrip().endswith(")"):
        return None
    stripped = call_src.rstrip()
    inner = stripped[:-1].rstrip()
    sep = "" if inner.endswith("(") else (", " if not inner.endswith(",") else " ")
    candidate = f"{inner}{sep}creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0))"
    # Prefer clean `subprocess.CREATE_NO_WINDOW` if `subprocess.` prefix is already used.
    if call_src.lstrip().startswith("subprocess."):
        candidate = f"{inner}{sep}creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))"
    try:
        ast.parse(candidate)
    except SyntaxError:
        return None
    return candidate


def scan_python_source(
    source_text: str,
    *,
    file_path: str = "<memory>",
) -> tuple[list[ScanFinding], str | None]:
    """Scan Python source text using ast without modifying it."""
    sha = hashlib.sha256(source_text.encode("utf-8", errors="replace")).hexdigest()
    try:
        tree = ast.parse(source_text, filename=file_path)
    except SyntaxError as exc:
        return [], f"SyntaxError at line {exc.lineno}: {exc.msg}"
    visitor = _PythonLaunchVisitor(source_text, file_path, sha)
    visitor.visit(tree)
    return visitor.findings, None


def _apply_span_replacements(source_text: str, edits: list[tuple[tuple[int, int, int, int], str]]) -> str:
    """Apply non-overlapping AST span replacements in reverse source order."""
    lines = source_text.splitlines(keepends=True)
    line_offsets: list[int] = [0]
    for ln in lines:
        line_offsets.append(line_offsets[-1] + len(ln))

    def to_offset(lineno: int, col: int) -> int:
        # AST byte col_offset on ASCII/UTF-8 lines: convert UTF-8 byte offset to char index cleanly
        raw_line = lines[lineno - 1]
        byte_prefix = raw_line.encode("utf-8")[:col].decode("utf-8", errors="replace")
        return line_offsets[lineno - 1] + len(byte_prefix)

    sorted_edits = sorted(edits, key=lambda item: (item[0][0], item[0][1]), reverse=True)
    out = source_text
    for (s_ln, s_col, e_ln, e_col), repl in sorted_edits:
        start_idx = to_offset(s_ln, s_col)
        end_idx = to_offset(e_ln, e_col)
        out = out[:start_idx] + repl + out[end_idx:]
    return out


def _find_powershell_exe() -> str | None:
    for exe in ("pwsh.exe", "pwsh", "powershell.exe", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def scan_powershell_files(ps_files: list[Path]) -> tuple[list[ScanFinding], list[dict[str, str]]]:
    """Analyze PowerShell scripts using System.Management.Automation.Language.Parser (read-only)."""
    if not ps_files:
        return [], []
    ps_exe = _find_powershell_exe()
    if ps_exe is None:
        return [], [{"file": str(p), "error": "No PowerShell executable found for AST parsing"} for p in ps_files]

    ps_script = r"""
param([string[]]$Paths)
$results = @()
foreach ($p in $Paths) {
    try {
        $tokens = $null
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$tokens, [ref]$errors)
        $errList = @($errors | ForEach-Object { $_.Message })
        $cmds = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)
        $calls = @()
        foreach ($c in $cmds) {
            $name = $c.GetCommandName()
            if ($name -in @('Start-Process', 'start', 'saps', 'Start-Job', 'cmd', 'cmd.exe', 'pwsh', 'pwsh.exe', 'powershell', 'powershell.exe')) {
                $calls += [PSCustomObject]@{
                    name = $name
                    line = $c.Extent.StartLineNumber
                    col = $c.Extent.StartColumnNumber
                    text = $c.Extent.Text
                }
            }
        }
        $results += [PSCustomObject]@{
            file = $p
            parse_errors = $errList
            calls = $calls
        }
    } catch {
        $results += [PSCustomObject]@{
            file = $p
            parse_errors = @($_.Exception.Message)
            calls = @()
        }
    }
}
$results | ConvertTo-Json -Depth 6 -Compress
"""
    findings: list[ScanFinding] = []
    errors: list[dict[str, str]] = []
    encoded_paths = [str(p) for p in ps_files]
    try:
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": 15.0,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Pass file paths as JSON via stdin to avoid command-line quoting/space issues.
        wrapper = (
            "$inputJson = [Console]::In.ReadToEnd() | ConvertFrom-Json; "
            "& { " + ps_script + " } -Paths @($inputJson)"
        )
        res = subprocess.run(
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", wrapper],
            input=json.dumps(encoded_paths),
            **kwargs,
        )
        if res.returncode != 0 or not res.stdout.strip():
            errors.append({"file": "<powershell_batch>", "error": res.stderr.strip() or f"exit={res.returncode}"})
            return findings, errors
        parsed = json.loads(res.stdout)
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            fpath = str(item.get("file", ""))
            for perr in item.get("parse_errors") or []:
                errors.append({"file": fpath, "error": f"PowerShell ParseError: {perr}"})
            sha = ""
            try:
                sha = hashlib.sha256(Path(fpath).read_bytes()).hexdigest()
            except OSError:
                pass
            for call in item.get("calls") or []:
                cname = str(call.get("name", ""))
                ctext = str(call.get("text", ""))
                low = ctext.lower()
                has_hidden = "-windowstyle hidden" in low or "-windowstyle\thidden" in low
                has_no_new_window = "-nonewwindow" in low
                if has_hidden:
                    continue
                warnings: list[str] = []
                if cname.lower() in ("start-process", "start", "saps"):
                    if has_no_new_window:
                        category = FindingCategory.INTENTIONAL_INTERACTIVE
                        remediation = "Uses -NoNewWindow; do NOT combine -WindowStyle Hidden with -NoNewWindow."
                        warnings.append("Start-Process -WindowStyle and -NoNewWindow cannot be combined.")
                    elif "-wait" in low or "-redirectstandardoutput" in low:
                        category = FindingCategory.LIKELY_UNINTENDED
                        remediation = "Consider -WindowStyle Hidden if non-interactive and -NoNewWindow is not used."
                    else:
                        category = FindingCategory.POTENTIAL_ISSUE
                        remediation = "Review whether a new console window is intended; add -WindowStyle Hidden only for non-interactive launches."
                else:
                    category = FindingCategory.POTENTIAL_ISSUE
                    remediation = "Review nested shell/command invocation for unintended console window creation."
                findings.append(
                    ScanFinding(
                        file_path=fpath,
                        line=int(call.get("line", 1)),
                        column=int(call.get("col", 1)),
                        language="powershell",
                        mechanism=cname,
                        call_excerpt=ctext[:240],
                        category=category,
                        confidence="medium",
                        explanation=f"PowerShell {cname} call without -WindowStyle Hidden.",
                        remediation=remediation,
                        file_sha256=sha,
                        warnings=warnings,
                    )
                )
    except Exception as exc:
        errors.append({"file": "<powershell_batch>", "error": str(exc)})
    return findings, errors


def _link_incident_history(findings: list[ScanFinding], db_path: Path | None) -> None:
    """Annotate findings that match recorded ProcWatch incidents."""
    resolved = (db_path or (get_data_dir() / "events.db")).expanduser()
    if not resolved.exists():
        return
    try:
        storage = FlightRecorderStorage(resolved, read_only=True)
        try:
            incidents = storage.query_history(limit=200)
        finally:
            storage.close()
    except Exception:
        return

    for f in findings:
        fname = Path(f.file_path).name.lower()
        for inc in incidents:
            cmd = str(inc.get("cmdline_redacted") or "").lower()
            summary = str(inc.get("summary_text") or "").lower()
            if fname and (fname in cmd or fname in summary):
                inc_id = inc.get("incident_id")
                if isinstance(inc_id, int):
                    f.linked_incident_ids.append(inc_id)
        if f.linked_incident_ids:
            f.category = FindingCategory.INCIDENT_LINKED
            f.confidence = "high"


def scan_directory(
    directory: Path,
    *,
    include_worktrees: bool = False,
    generate_diffs: bool = True,
    db_path: Path | None = None,
) -> ScanReport:
    """Scan Python and PowerShell files under directory (and optional worktrees) read-only."""
    roots = discover_scan_roots(directory, include_worktrees=include_worktrees)
    py_files, ps_files = _iter_source_files(roots)
    report = ScanReport(
        roots=[str(r) for r in roots],
        files_scanned=len(py_files) + len(ps_files),
    )

    edits_by_file: dict[Path, list[tuple[tuple[int, int, int, int], str]]] = {}
    texts_by_file: dict[Path, str] = {}

    for py_path in py_files:
        try:
            text = py_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.errors.append({"file": str(py_path), "error": str(exc)})
            continue
        findings, err = scan_python_source(text, file_path=str(py_path))
        if err:
            report.errors.append({"file": str(py_path), "error": err})
        report.findings.extend(findings)
        file_edits = [
            (f.span, f.proposed_replacement)
            for f in findings
            if f.span is not None and f.proposed_replacement is not None
        ]
        if file_edits:
            edits_by_file[py_path] = file_edits
            texts_by_file[py_path] = text

    ps_findings, ps_errors = scan_powershell_files(ps_files)
    report.findings.extend(ps_findings)
    report.errors.extend(ps_errors)

    _link_incident_history(report.findings, db_path)

    if generate_diffs:
        for fpath, file_edits in edits_by_file.items():
            orig = texts_by_file[fpath]
            patched = _apply_span_replacements(orig, file_edits)
            try:
                ast.parse(patched)
            except SyntaxError:
                continue
            diff = "".join(
                difflib.unified_diff(
                    orig.splitlines(keepends=True),
                    patched.splitlines(keepends=True),
                    fromfile=f"a/{fpath.name}",
                    tofile=f"b/{fpath.name}",
                )
            )
            if diff:
                report.diffs[str(fpath)] = diff

    return report


def _is_file_dirty_in_git(fpath: Path) -> bool:
    """Return True if git reports uncommitted changes on fpath."""
    try:
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": 5.0,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(
            ["git", "-C", str(fpath.parent), "status", "--porcelain", "--", str(fpath)],
            **kwargs,
        )
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return False


def apply_proposed_fixes(
    report: ScanReport,
    *,
    apply_fixes: bool = False,
    force: bool = False,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    """Explicitly apply verified Python patches with git-dirty guard, hash check, and backups."""
    result: dict[str, Any] = {"applied": [], "skipped": [], "errors": []}
    if not apply_fixes:
        return result

    bdir = (backup_dir or (get_data_dir() / "backups")).expanduser()
    bdir.mkdir(parents=True, exist_ok=True)

    by_file: dict[str, list[ScanFinding]] = {}
    for f in report.findings:
        if (
            f.language == "python"
            and f.span is not None
            and f.proposed_replacement is not None
            and f.category in (FindingCategory.LIKELY_UNINTENDED, FindingCategory.INCIDENT_LINKED)
        ):
            by_file.setdefault(f.file_path, []).append(f)

    for fpath_str, file_findings in by_file.items():
        fpath = Path(fpath_str)
        if _is_file_dirty_in_git(fpath) and not force:
            result["skipped"].append({"file": fpath_str, "reason": "dirty_in_git_without_force"})
            continue
        try:
            current_text = fpath.read_text(encoding="utf-8")
        except OSError as exc:
            result["errors"].append({"file": fpath_str, "error": str(exc)})
            continue
        current_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
        if any(f.file_sha256 and f.file_sha256 != current_sha for f in file_findings):
            result["skipped"].append({"file": fpath_str, "reason": "content_hash_changed_since_scan"})
            continue

        edits = [(f.span, f.proposed_replacement) for f in file_findings if f.span and f.proposed_replacement]
        patched = _apply_span_replacements(current_text, edits)
        try:
            ast.parse(patched)
        except SyntaxError as exc:
            result["errors"].append({"file": fpath_str, "error": f"Post-patch syntax check failed: {exc}"})
            continue

        backup_path = bdir / f"{fpath.name}.{current_sha[:12]}.bak"
        backup_path.write_text(current_text, encoding="utf-8")
        fpath.write_text(patched, encoding="utf-8")
        result["applied"].append({"file": fpath_str, "backup": str(backup_path), "edits": len(edits)})

    return result
