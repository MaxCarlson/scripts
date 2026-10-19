"""Subcommand entry point for setup and the existing local-model workflow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import __version__
from .setup.files import write_json
from .setup.installer import apply_plan, recover_installation, remove_installation
from .setup.planner import build_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='local-agent', description='Set up coding agents and run the local model bridge.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''How to setup Global AGENTS.md and other LLM files:
  local-agent setup plan -c codex agy -m local -s auto
  local-agent setup apply
  local-agent setup status -j

How to run the local model setup & codex/agy integration:
  local-agent run -m qwen/qwen3.8-27b@q6_k -c 32768
  local-agent run -M qwen38_23GB
  local-agent model list''')
    parser.add_argument('-V', '--version', action='version', version=__version__)
    groups = parser.add_subparsers(dest='group')
    setup = groups.add_parser('setup', help='Plan, install, inspect or remove agent setup')
    actions = setup.add_subparsers(dest='action')
    for name in ['plan', 'apply', 'status', 'remove', 'recover']:
        action = actions.add_parser(name, help=name.capitalize() + ' agent setup')
        action.add_argument('-H', '--home', type=Path, help='Target user home root')
        action.add_argument('-S', '--state-dir', type=Path, help='Receipt and backup directory')
        action.add_argument('-j', '--json', action='store_true', help='Print structured results')
        if name != 'recover':
            action.add_argument('-c', '--clients', nargs='+', choices=['codex', 'agy'], default=None,
                                help='Clients to configure (default: codex agy)')
        if name in {'plan', 'apply', 'status'}:
            action.add_argument('-s', '--strategy', choices=['auto', 'link', 'copy'], default=None,
                                help='Resource link/copy strategy (default: auto)')
            action.add_argument('-m', '--mode', choices=['generic', 'local'], default=None,
                                help='Generic agent setup or generic plus local delegation (default: local)')
            action.add_argument('-A', '--adopt', nargs='+', default=None,
                                help='Exact existing resource IDs to adopt')
        if name == 'plan':
            action.add_argument('-o', '--output', type=Path, help='Save a versioned plan without config contents')
        if name == 'apply':
            action.add_argument('-i', '--input-plan', type=Path, help='Apply an unchanged saved plan')
        if name == 'remove':
            action.add_argument('-a', '--apply', action='store_true', help='Execute removal (default: preview)')
    model = groups.add_parser('model', help='Inventory or manage configured model aliases')
    actions = model.add_subparsers(dest='action')
    actions.add_parser('list', help='List model variants, loaded models and configured aliases')
    for name in ['rename', 'remove']:
        action = actions.add_parser(name)
        action.add_argument('nickname', help='Existing model alias')
        if name == 'rename':
            action.add_argument('new_nickname', help='New model alias')
        action.add_argument('-a', '--apply', action='store_true', help='Execute the operation (default: preview)')
        action.add_argument('-p', '--opencode-port', type=int, default=4096, help='OpenCode HTTP server port')
        action.add_argument('-l', '--lms-port', type=int, default=1234, help='LM Studio HTTP port')
    groups.add_parser('run', help='Configure/load the model and start the foreground bridge', add_help=False)
    return parser


def _output(value: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2))
    elif 'operations' in value:
        for op in value['operations']:
            print(f"{op['action']:10} {op['resource_id']:28} {op['path']}")
            if op['conflict']:
                print('  ' + op['conflict'])
        for warning in value.get('warnings', []):
            print('Notice: ' + warning)
    else:
        print(value.get('message', 'Completed') + (': ' + ', '.join(value['changed']) if value.get('changed') else ''))
        for problem in value.get('conflicts', []) + value.get('errors', []):
            print(problem)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if arguments and arguments[0] == 'run':
        from . import cli
        if '-h' not in arguments and '--help' not in arguments:
            if not (Path.home() / '.local/share/local-agent/receipt.json').is_file():
                print('Notice: delegation resources are not installed; run local-agent setup plan/apply.')
        return cli.main(arguments[1:], runtime_only=True)
    args = parser.parse_args(arguments)
    if not args.group:
        parser.print_help()
        return 0
    if not args.action:
        parser.parse_args([args.group, '--help'])
    try:
        if args.group == 'model':
            from . import cli
            if args.action == 'list':
                cli.handle_ls_command()
            elif not args.apply:
                print(f'Preview: {args.action} alias {args.nickname}; add -a/--apply to execute.')
            elif args.action == 'rename':
                cli.handle_rename_model(args.nickname, args.new_nickname, args.lms_port, args.opencode_port)
            else:
                cli.handle_delete_model(args.nickname, args.opencode_port)
            return 0
        if args.action == 'recover':
            result = recover_installation(args.home or Path.home(), state_dir=args.state_dir)
        elif args.action == 'remove':
            result = remove_installation(args.home or Path.home(), tuple(args.clients or ['codex', 'agy']),
                                         execute=args.apply, state_dir=args.state_dir)
        else:
            saved = None
            if args.action == 'apply' and args.input_plan:
                if any(value is not None for value in [args.clients, args.strategy, args.adopt, args.mode, args.state_dir, args.home]):
                    parser.error('--input-plan cannot be combined with selection/target changes')
                saved = json.loads(args.input_plan.read_text(encoding='utf-8'))
                if saved.get('schema_version') != 1:
                    raise ValueError('Unsupported saved plan schema')
                home, clients, strategy, mode, adopt, state = (Path(saved['home']), tuple(saved['clients']),
                    saved['strategy'], saved['mode'], tuple(saved['adopt']), Path(saved['state_dir']))
            else:
                home, clients, strategy, mode, adopt, state = (args.home or Path.home(), tuple(args.clients or ['codex', 'agy']),
                    args.strategy or 'auto', args.mode or 'local', tuple(args.adopt or []), args.state_dir)
                if args.action == 'status' and args.mode is None:
                    from .setup.manifest import Layout
                    from .setup.planner import load_receipt
                    modes = load_receipt(Layout.discover(home, state, None)).get('modes', {})
                    if modes and all(modes.get(client) == 'generic' for client in clients):
                        mode = 'generic'
            plan = build_plan(home, clients, strategy=strategy, adopt=adopt, mode=mode, state_dir=state)
            if args.action == 'apply':
                result = apply_plan(plan, expected=saved)
            else:
                result = plan.summary()
                result['code'] = 3 if plan.conflicts or (args.action == 'status' and
                    any(op.action != 'unchanged' for op in plan.operations)) else 0
                if args.action == 'plan' and args.output:
                    write_json(args.output, plan.summary())
        _output(result, args.json)
        return result.get('code', 0)
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        message = str(exc)
        result = {'schema_version': 1, 'code': 4 if 'stale' in message else 5 if 'rollback' in message else
                  3 if 'conflict' in message.lower() else 1, 'message': message}
        _output(result, getattr(args, 'json', False))
        return result['code']


if __name__ == '__main__':
    raise SystemExit(main())
