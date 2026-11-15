"""Console and redacted JSONL output renderer for `watch` and `guard`."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import TextIO

from rich.console import Console

from procwatch.config import CONSOLE_WINDOW_CLASSES
from procwatch.models import LiveIncidentEvent, ProcessObservation
from procwatch.redactor import redact_dict


class ConsoleRenderer:
    """Renders LiveIncidentEvent streams to console and/or redacted JSONL."""

    def __init__(
        self,
        *,
        popups_only: bool = False,
        collapse_bursts: bool = False,
        show_headless: bool = False,
        filter_regex: re.Pattern[str] | None = None,
        output_file: Path | None = None,
        quiet: bool = False,
        console: Console | None = None,
    ) -> None:
        self.popups_only = popups_only
        self.collapse_bursts = collapse_bursts
        self.show_headless = show_headless
        self.filter_regex = filter_regex
        self.output_file = output_file
        self.quiet = quiet
        self.console = console or Console(highlight=False)
        self._jsonl_fp: TextIO | None = None
        self._last_burst_key: str | None = None
        self._burst_count: int = 0

        if self.output_file is not None:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            self._jsonl_fp = self.output_file.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._jsonl_fp is not None:
            self._jsonl_fp.flush()
            self._jsonl_fp.close()
            self._jsonl_fp = None

    def _should_display(self, event: LiveIncidentEvent) -> bool:
        if self.popups_only and event.window is None:
            return False

        if not self.show_headless and event.process is not None and event.window is None:
            cmd = (event.process.command_line_redacted or "").lower()
            if "conhost.exe" in event.process.image_name.lower() and "0x4" in cmd:
                return False

        if self.filter_regex is not None:
            haystack_parts: list[str] = []
            if event.window is not None:
                haystack_parts.extend([event.window.window_class, event.window.current_title])
            if event.process is not None:
                haystack_parts.extend(
                    [
                        event.process.image_name,
                        event.process.command_line_redacted or "",
                    ]
                )
            for cand in event.candidate_initiators:
                haystack_parts.extend([cand.image_name, cand.command_line_redacted or ""])
            for node in event.ancestry_chain:
                haystack_parts.append(node.image_name)
            if not self.filter_regex.search(" ".join(haystack_parts)):
                return False

        return True

    def render(self, event: LiveIncidentEvent) -> None:
        """Render an incident event to console and append redacted JSONL if configured."""
        if not self._should_display(event):
            return

        if self._jsonl_fp is not None:
            payload = redact_dict(asdict(event))
            self._jsonl_fp.write(json.dumps(payload, default=str) + "\n")
            self._jsonl_fp.flush()

        if self.quiet:
            return

        if self.collapse_bursts and event.window is None and event.process is not None:
            burst_key = f"{event.event_type}:{event.process.image_name}:{event.process.command_line_redacted or ''}"
            if burst_key == self._last_burst_key:
                self._burst_count += 1
                if self._burst_count % 10 == 0:
                    self.console.print(f"[dim]  ... repeated {self._burst_count}x: {event.process.image_name}[/dim]")
                return
            self._last_burst_key = burst_key
            self._burst_count = 1

        ts = event.timestamp_utc
        if event.window is not None:
            w = event.window
            is_console = w.window_class in CONSOLE_WINDOW_CLASSES
            tag = "POPUP" if is_console else "WINDOW"
            action = event.guard_decision.observed_outcome if event.guard_decision else w.state.value
            owner_name = event.process.image_name if event.process else "<unavailable>"
            title_disp = w.current_title or "<untitled>"
            self.console.print(
                f"[bold cyan][{ts}][/bold cyan] [yellow]{tag}[/yellow] "
                f"state=[bold]{action}[/bold] class={w.window_class} hwnd={hex(w.hwnd)} "
                f"owner={owner_name} (PID {w.owner_pid}) title={title_disp!r}"
            )
            if event.guard_decision is not None:
                gd = event.guard_decision
                lat = f"{gd.action_latency_ms:.2f}ms" if gd.action_latency_ms is not None else "n/a"
                self.console.print(
                    f"  [dim]guard: rule={gd.matched_rule} intended={gd.intended_action} "
                    f"outcome={gd.observed_outcome} latency={lat}[/dim]"
                )
            if event.candidate_initiators:
                for cand in event.candidate_initiators[:3]:
                    delta = f"{cand.time_delta_ms:+.1f}ms" if cand.time_delta_ms is not None else "n/a"
                    self.console.print(
                        f"  [green]suspected initiator[/green] ({cand.confidence.value}, {delta}): "
                        f"{cand.image_name} (PID {cand.pid}) [{', '.join(cand.reasons)}] "
                        f"cmd={cand.command_line_redacted or '<unavailable>'}"
                    )
            else:
                self.console.print("  [dim]suspected initiator: <unavailable / none matched in window>[/dim]")

            chain = event.collapsed_ancestry_chain or event.ancestry_chain
            if chain:
                self.console.print(f"  [dim]owner chain: {self._format_chain(chain)}[/dim]")
            if event.missing_reasons:
                reasons = ", ".join(r.value for r in event.missing_reasons)
                self.console.print(f"  [dim]metadata gaps: {reasons}[/dim]")
            return

        if event.process is not None:
            p = event.process
            if event.event_type == "process_start":
                self.console.print(
                    f"[dim][{ts}][/dim] START {p.image_name} (PID {p.identity.pid}, PPID {p.ppid}) "
                    f"cmd={p.command_line_redacted or '<unavailable>'}"
                )
                if p.decoded_payload_redacted:
                    self.console.print(f"  [magenta]decoded:[/magenta] {p.decoded_payload_redacted}")
            elif event.event_type == "process_stop":
                code = str(p.exit_code) if p.capabilities.exit_code_known else "<unknown>"
                self.console.print(
                    f"[dim][{ts}][/dim] STOP  {p.image_name} (PID {p.identity.pid}) exit={code}"
                )

    @staticmethod
    def _format_chain(chain: list[ProcessObservation]) -> str:
        return " <- ".join(f"{node.image_name}({node.identity.pid})" for node in chain)
