# agt/ingest.py
from __future__ import annotations
import os, sys, re, glob
from pathlib import Path
from typing import Iterable, List, Tuple

MAX_FILE_BYTES_DEFAULT = 512_000
TEXT_EXTS = {
    ".txt",".md",".py",".js",".ts",".tsx",".jsx",".json",".toml",".yaml",".yml",".ini",
    ".cfg",".conf",".sh",".bash",".zsh",".ps1",".psm1",".psd1",".bat",".cmd",".rs",".go",
    ".java",".kt",".swift",".c",".h",".hpp",".hh",".cpp",".cc",".m",".mm",".r",".jl",".sql",
}

AT_TOKEN = re.compile(r"(?P<at>@)(?P<path>[^\s]+)")

def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTS: return True
    # quick sniff
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        if b"\0" in chunk:
            return False
        return True
    except Exception:
        return False

def _iter_paths(token: str) -> Iterable[Path]:
    # token may be a file, dir/, or glob **/*.py
    p = Path(token)
    if any(ch in token for ch in "*?[]"):
        for g in glob.iglob(token, recursive=True):
            yield Path(g)
        return
    if p.is_dir():
        for g in p.rglob("*"):
            if g.is_file():
                yield g
        return
    if p.exists():
        yield p

def materialize_at_refs(text: str, cwd: Path | None = None,
                        max_bytes: int = MAX_FILE_BYTES_DEFAULT
) -> Tuple[str, List[Tuple[Path, str]]]:
    """
    Finds @path tokens, expands files globs & folders recursively,
    returns (text_without_at_tokens, [(path, file_text), ...]).
    """
    cwd = cwd or Path.cwd()
    attachments: list[tuple[Path,str]] = []
    def repl(m: re.Match) -> str:
        token = m.group("path")
        # allow relative to cwd
        token_path = (cwd / token).as_posix() if token.startswith(("./","../")) else token
        seen_any = False
        for p in _iter_paths(token_path):
            try:
                p = p.resolve()
                if not p.is_file(): continue
                if p.stat().st_size > max_bytes: continue
                if not is_probably_text(p): continue
                data = p.read_text(encoding="utf-8", errors="replace")
                attachments.append((p, data))
                seen_any = True
            except Exception:
                continue
        # remove token from the message; we’ll inject content separately
        return "" if seen_any else m.group(0)
    new_text = AT_TOKEN.sub(repl, text)
    return new_text, attachments

def render_attachments_block(files: List[Tuple[Path, str]], root_hint: str | None = None) -> str:
    if not files: return ""
    # similar to Gemini CLI “ReadManyFiles”
    header = []
    if root_hint:
        header.append(f"### ReadManyFiles Result (Target Dir: `{root_hint}`)\n")
    header.append(f"Successfully read and concatenated content from **{len(files)} file(s)**.\n\n")
    header.append("**Processed Files:**\n")
    for p,_ in files[:50]:
        rel = os.path.relpath(str(p), root_hint) if root_hint else str(p)
        header.append(f" - `{rel}`\n")
    if len(files) > 50:
        header.append(f" - … and {len(files)-50} more …\n")
    header.append("\n")
    body = []
    for p, txt in files:
        body.append(f"\n<<FILE:{p.as_posix()}>>\n{txt}\n<<ENDFILE>>\n")
    return "".join(header) + "".join(body)
