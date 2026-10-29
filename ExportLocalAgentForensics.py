
#!/usr/bin/env python3
"""Collect original OpenCode and Codex delegation evidence without modifying it."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


TASKS = {
    "gate-b": (
        "ses_e8f684739ffeFsasNNmHl4aOcx",
        "job_865fe25344384ab3983955d01bb22d65",
    ),
    "renderer": (
        "ses_e8f65164affeBWwmUpILao1isi",
        "job_1f8d022bb2f8453c86edecc6de7322b1",
    ),
    "d1": (
        "ses_e8f417354ffeh18PAswgGs4vIg",
        "job_21a7ed542d954f7993939e90a0f3bc1e",
    ),
    "d2": (
        "ses_e8f36dddeffed6AzoypjEPUjJd",
        "job_b7086088fc9e44b28d791e6ffa203b15",
    ),
    "d5": (
        "ses_e8f224594ffe7Fva80YxKldPN7",
        "job_805f3bb0e2a443f496c30b7d13496d51",
    ),
}

EXTRA_MARKERS = [
    "runmux-6c-history-frontend-local-pilot",
    "msg_170c4d5ed001d453c84d51dc4d",
]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": file_hash(path),
    }


def version(command: str) -> str | None:
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return result.stdout.strip() or result.stderr.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def export_session(
    session: str,
    directory: Path,
    workspace: Path,
    opencode_version: str | None,
    sanitize: bool,
) -> dict:
    target = directory / f"{session}.json"
    ver = re.search(r"(\d+)\.(\d+)\.(\d+)", opencode_version or "")
    major = int(ver.group(1)) if ver else 1
    command = (
        ["opencode", "session", "export", session]
        if major >= 2
        else ["opencode", "export", session]
    )
    if sanitize:
        command.append("--sanitize")

    try:
        with target.open("wb") as output:
            result = subprocess.run(
                command,
                cwd=workspace,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
        entry = {
            "session_id": session,
            "command": command,
            "exit_code": result.returncode,
            "stderr": result.stderr.decode("utf-8", errors="replace")[:2000],
        }
        if result.returncode == 0 and target.stat().st_size:
            entry["file"] = file_record(target)
        else:
            entry["error"] = "Export failed or returned an empty file"
        return entry
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"session_id": session, "error": str(exc)}


def api_capture(url: str, target: Path) -> dict:
    headers = {"Accept": "application/json"}
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if password:
        username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
        credentials = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {credentials}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            with target.open("wb") as output:
                shutil.copyfileobj(response, output)
        return {"url": url, "file": file_record(target)}
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        return {"url": url, "error": str(exc)}


def matching_codex_files(
    roots: list[Path],
    explicit_files: list[Path],
    markers: list[str],
    days: int,
) -> list[Path]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    matched = set()

    for source in explicit_files:
        if source.is_file():
            matched.add(source.resolve())

    for root in roots:
        if not root.is_dir():
            continue
        for source in root.rglob("*.jsonl"):
            try:
                modified = datetime.fromtimestamp(
                    source.stat().st_mtime, timezone.utc
                )
                if modified < cutoff:
                    continue
                with source.open(
                    "r", encoding="utf-8", errors="replace"
                ) as stream:
                    if any(
                        any(marker in line for marker in markers)
                        for line in stream
                    ):
                        matched.add(source.resolve())
            except OSError:
                continue

    return sorted(matched)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-s", "--session", action="append",
        help="Specific OpenCode session ID; repeat to override the default five",
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        help="Private evidence output directory",
    )
    parser.add_argument(
        "-r", "--repo-root", type=Path,
        default=Path.home() / "src/scripts/.worktrees/runmux-6c-history-frontend-local-pilot",
        help="Original OpenCode project/worktree directory",
    )
    parser.add_argument(
        "-c", "--codex-root", type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
        help="Codex home directory",
    )
    parser.add_argument(
        "--codex-log", action="append", type=Path, default=[],
        help="Include an explicitly selected Codex JSONL file",
    )
    parser.add_argument(
        "--days", type=int, default=21,
        help="How many days of recent Codex logs to search",
    )
    parser.add_argument(
        "--api", action="store_true",
        help="Additionally collect read-only OpenCode HTTP API records",
    )
    parser.add_argument(
        "--server-url", default="http://127.0.0.1:4096",
        help="Existing OpenCode server URL",
    )
    parser.add_argument(
        "--sanitize", action="store_true",
        help="Sanitize OpenCode CLI exports (may lose diagnostic content)",
    )
    parser.add_argument(
        "-w", "--write", action="store_true",
        help="Actually create the evidence bundle (otherwise preview)",
    )
    args = parser.parse_args()

    if args.days < 0:
        parser.error("--days must be nonnegative")

    selected = args.session or [item[0] for item in TASKS.values()]
    if any(not re.fullmatch(r"ses_[A-Za-z0-9]+", s) for s in selected):
        parser.error("Invalid OpenCode session ID")

    selected = list(dict.fromkeys(selected))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (args.output or (
        Path.home() / "local-agent-forensics" / f"phase6c-{stamp}"
    )).expanduser().resolve()
    repo = args.repo_root.expanduser().resolve()

    markers = selected + EXTRA_MARKERS
    markers += [
        job for session, job in TASKS.values() if session in selected
    ]

    codex_roots = [
        args.codex_root.expanduser() / "sessions",
        args.codex_root.expanduser() / "archived_sessions",
    ]

    print(f"Output: {output}")
    print(f"OpenCode project: {repo}")
    print(f"OpenCode sessions: {len(selected)}")
    print(f"Codex roots: {', '.join(map(str, codex_roots))}")

    if not args.write:
        print("PREVIEW ONLY. Add -w / --write to collect evidence.")
        return 0

    if output.exists():
        print("Refusing to overwrite an existing output directory.", file=sys.stderr)
        return 2

    output.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": "a03b4fa65d49bde59287dc4a246603f13a91b974",
        "project_directory": str(repo),
        "sanitized_exports": args.sanitize,
        "versions": {
            "opencode": version("opencode"),
            "codex": version("codex"),
            "local_agent": version("local-agent"),
        },
        "sessions": [],
        "api_records": [],
        "codex_logs": [],
        "config": [],
    }

    exports = output / "opencode"
    exports.mkdir()
    if repo.is_dir() and shutil.which("opencode"):
        for session in selected:
            print(f"Exporting {session}")
            manifest["sessions"].append(
                export_session(
                    session, exports, repo,
                    manifest["versions"]["opencode"], args.sanitize
                )
            )
    else:
        manifest["sessions_error"] = (
            "Original worktree or opencode executable unavailable"
        )

    if args.api:
        parsed = urllib.parse.urlsplit(args.server_url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "localhost", "127.0.0.1", "::1"
        } or parsed.username or parsed.password:
            parser.error("--server-url must be an unauthenticated loopback HTTP URL")

        base = args.server_url.rstrip("/")
        api_dir = output / "opencode-api"
        api_dir.mkdir()

        manifest["api_records"].append(
            api_capture(base + "/global/health", api_dir / "health.json")
        )

        for session in selected:
            encoded = urllib.parse.quote(session, safe="")
            for name, suffix in {
                "metadata": "",
                "messages": "/message",
                "diff": "/diff",
                "children": "/children",
            }.items():
                url = f"{base}/session/{encoded}{suffix}"
                target = api_dir / f"{session}-{name}.json"
                manifest["api_records"].append(api_capture(url, target))

    files = matching_codex_files(
        codex_roots,
        [path.expanduser() for path in args.codex_log],
        markers,
        args.days,
    )
    codex_out = output / "codex"
    codex_out.mkdir()

    for source in files:
        path_id = hashlib.sha256(
            str(source).encode("utf-8")
        ).hexdigest()[:12]
        destination = codex_out / f"{source.stem}-{path_id}.jsonl"
        shutil.copy2(source, destination)
        manifest["codex_logs"].append({
            "source": str(source),
            "copy": file_record(destination),
        })
        print(f"Codex transcript: {source}")

    agent_dir = Path.home() / ".config/opencode/agents"
    config_dir = output / "worker-config"
    config_dir.mkdir()

    for name in ("local-worker.md", "local-reviewer.md"):
        source = agent_dir / name
        if source.is_file():
            destination = config_dir / name
            shutil.copy2(source, destination)
            manifest["config"].append({
                "source": str(source),
                "copy": file_record(destination),
            })

    # Fingerprint configuration without copying potentially secret values.
    for source in (
        Path.home() / ".config/opencode/opencode.json",
        args.codex_root.expanduser() / "config.toml",
        args.codex_root.expanduser() / "AGENTS.md",
    ):
        if source.is_file():
            manifest["config"].append({
                "source": str(source),
                "sha256": file_hash(source),
                "copied": False,
            })

    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    failures = [
        entry for entry in manifest["sessions"] + manifest["api_records"]
        if "error" in entry
    ]
    print(f"Evidence bundle: {output}")
    print(f"Codex transcripts: {len(files)}")
    print(f"Export/API errors: {len(failures)}")
    print("Raw evidence is sensitive. Keep this directory private.")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

