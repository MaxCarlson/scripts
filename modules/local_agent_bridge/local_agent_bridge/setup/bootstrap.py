"""Read receipt modes for a bootstrap hook without starting services or writing."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def receipt_mode(path: Path, clients: list[str]) -> str:
    modes = json.loads(path.read_text(encoding='utf-8')).get('modes', {})
    selected = {modes.get(client, 'generic') for client in clients}
    if not selected <= {'generic', 'local'} or len(selected) != 1:
        raise ValueError('Mixed or invalid client modes: select clients or pass an explicit --mode')
    return selected.pop()


def main() -> int:
    from ..commands import build_parser
    try:
        args = build_parser().parse_args(['setup', 'plan', *sys.argv[2:]])
        print(receipt_mode(Path(sys.argv[1]), args.clients or ['codex', 'agy']))
        return 0
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        print(f'Cannot read bootstrap mode: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
