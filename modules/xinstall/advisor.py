from __future__ import annotations

import json
import os
import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

try:
    from ai_orchestrator.cli_manager import CLIManager, JobType
except Exception:
    CLIManager = None  # type: ignore
    JobType = None  # type: ignore


@dataclass(frozen=True)
class AdvisorDecision:
    manager: str
    confidence: float
    rationale: str
    source: str
    raw_response: str


def _default_cooldown_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "tool-install-manager" / "cli_cooldowns.json"


def _load_cooldowns(path: Path) -> Dict[str, float]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}
    return {}


def _save_cooldowns(path: Path, data: Dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _extract_manager(text: str, known_managers: Sequence[str]) -> Optional[str]:
    lowered = text.lower()
    for manager in known_managers:
        if manager.lower() in lowered:
            return manager
    return None


class LLMAdvisor:
    """
    Optional LLM-backed advisor for package manager selection.
    Requires a configured CLI template for the chosen tool.
    """

    def __init__(
        self,
        cli_templates: Optional[Dict[str, List[str]]] = None,
        cooldown_seconds: int = 45,
        cooldown_path: Optional[Path] = None,
    ) -> None:
        self.cli_templates = cli_templates or {}
        self.cooldown_seconds = cooldown_seconds
        self.cooldown_path = cooldown_path or _default_cooldown_path()

    def _pick_cli_tool(self) -> Optional[str]:
        if CLIManager is None or JobType is None:
            return None
        mgr = CLIManager()
        tool = mgr.get_best_tool(JobType.SYSTEM_ADMIN, require_local=False)
        if tool is None or not tool.installed:
            return None
        cooldowns = _load_cooldowns(self.cooldown_path)
        last_used = cooldowns.get(tool.command, 0.0)
        if time.time() - last_used < self.cooldown_seconds:
            return None
        return tool.command

    def _mark_used(self, command: str) -> None:
        cooldowns = _load_cooldowns(self.cooldown_path)
        cooldowns[command] = time.time()
        _save_cooldowns(self.cooldown_path, cooldowns)

    def recommend_manager(
        self,
        prompt: str,
        known_managers: Sequence[str],
        timeout_s: float = 25.0,
    ) -> Optional[AdvisorDecision]:
        tool_cmd = self._pick_cli_tool()
        if not tool_cmd:
            return None

        template = self.cli_templates.get(tool_cmd)
        if not template:
            return None

        argv = [arg.replace("{prompt}", prompt) for arg in template]
        try:
            proc = subprocess.run(
                argv,
                text=True,
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except Exception:
            return None

        self._mark_used(tool_cmd)
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        manager = _extract_manager(output, known_managers)
        if not manager:
            return None

        return AdvisorDecision(
            manager=manager,
            confidence=0.45,
            rationale="LLM-based recommendation",
            source=tool_cmd,
            raw_response=output.strip(),
        )
