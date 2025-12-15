from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Iterator, List, Optional


@dataclass(frozen=True)
class LogStreamArgs:
    source: str = "model"
    stats: bool = False
    filter: str | None = None
    json: bool = False


def build_lms_log_stream_cmd(args: LogStreamArgs) -> List[str]:
    cmd: List[str] = ["lms", "log", "stream", "--source", args.source]
    if args.stats:
        cmd.append("--stats")
    if args.filter:
        cmd.extend(["--filter", args.filter])
    if args.json:
        cmd.append("--json")
    return cmd


def stream_logs_over_ssh(ssh_target: str, args: LogStreamArgs) -> Iterator[str]:
    """
    Runs: ssh <target> lms log stream ...
    and yields stdout lines.

    Requires:
      - SSH server on the LM Studio host
      - 'lms' available in PATH on that host
    """
    remote_cmd = build_lms_log_stream_cmd(args)
    ssh_cmd = ["ssh", ssh_target] + remote_cmd

    proc = subprocess.Popen(
        ssh_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\r\n")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
