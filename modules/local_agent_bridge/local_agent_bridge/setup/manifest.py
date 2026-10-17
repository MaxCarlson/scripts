"""Packaged assets and supported client locations."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import os
from pathlib import Path


def assets() -> Path:
    return Path(str(files('local_agent_bridge.resources')))


@dataclass(frozen=True)
class Layout:
    home: Path
    state: Path
    codex: Path
    opencode: Path

    @classmethod
    def discover(cls, home: Path, state: Path | None, environ: dict | None) -> 'Layout':
        env = os.environ if environ is None else environ
        home = home.expanduser().absolute()
        # Overrides apply to the actual home only, never to isolated targets.
        effective = env if home == Path.home().absolute() else {}
        codex = Path(effective.get('CODEX_HOME', str(home / '.codex'))).expanduser().absolute()
        if effective.get('OPENCODE_CONFIG') or effective.get('OPENCODE_CONFIG_DIR'):
            raise ValueError('Custom OpenCode config overrides require explicit reconciliation')
        config = Path(effective.get('XDG_CONFIG_HOME', str(home / '.config'))).expanduser()
        return cls(home, (state or home / '.local/share/local-agent').absolute(), codex, config / 'opencode')


def bridge_env(alias: str | None, port: int = 4096) -> dict[str, str]:
    result = {'OPENCODE_BASE_URL': f'http://127.0.0.1:{port}',
              'OPENCODE_AUTO_SERVE': 'false', 'OPENCODE_TOOL_PROFILE': 'essential',
              'OPENCODE_DEFAULT_PROVIDER': 'lmstudio'}
    if alias:
        result['OPENCODE_DEFAULT_MODEL'] = alias
    return result


def bridge_settings(alias: str | None, port: int = 4096) -> dict:
    return {'command': 'npx.cmd' if os.name == 'nt' else 'npx',
            'args': ['-y', 'opencode-mcp@3.0.0'], 'env': bridge_env(alias, port)}


def role_text(name: str) -> str:
    import json
    config = json.loads((assets() / 'integrations/opencode-agent.example.json').read_text())
    agent = config['agent'][name]
    # JSON is a YAML subset, supported by OpenCode's Markdown frontmatter reader.
    header = json.dumps({key: value for key, value in agent.items() if key != 'prompt'}, indent=2)
    prompt = (assets() / 'skills/local-agent-handoff/resources/local-worker.md').read_text(encoding='utf-8')
    return '---\n' + header + '\n---\n\n' + prompt
