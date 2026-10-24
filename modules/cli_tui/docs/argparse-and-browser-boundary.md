# Argparse Compatibility and Browser Boundary

Updated 2026-10-23 on `codex/runmux-tui-integration`.

## Existing Python interface

`cli_tui.schema.introspect_parser(parser)` returns the existing `CliCommand` tree.
Each `CliArgument` retains argparse-derived Python values, including `type_fn`,
`default`, and `choices`. This remains the Python interface used by
`CliTuiApp(parser=...)` and by MangaDL's filtered `root_command` integration.
Importing `cli_tui.schema` now loads that parser model without importing the
curses app, widgets, image viewer, or Pillow. The package-level public exports
remain lazy and available through `from cli_tui import CliTuiApp` and related
imports.

The existing model is **not a JSON contract**: `type_fn` is a callable and
defaults or choices may be `Path` instances or arbitrary application objects.
Do not serialize it with `dataclasses.asdict()` or expose it directly to a
browser.

## Argparse support in this branch

Introspection omits standard `help` and `version` actions from interactive forms.
It recognizes exact built-in `store`, `store_true`, `store_false`,
`BooleanOptionalAction`, `append`, `extend`, and `count` action classes. Unknown
actions and custom subclasses raise `ValueError` with the argument and action
class instead of being presented as ordinary value options. `store_const`,
`append_const`, and other unsupported actions are rejected explicitly.

`FormState.build_argv()` emits argv lists, not shell command strings. Parser
round-trip tests cover required options, choices, `Path`, boolean and
BooleanOptionalAction flags, count defaults, repeated append values, fixed
`nargs`, `+`/`*`, nested subcommands, and aliases. Fixed-arity append groups are
emitted as one flag occurrence per group. Existing append defaults are not
re-emitted; trying to remove or rewrite an append default, or lower a count below
its parser default, produces a clear error because argparse has no argv spelling
for those requested states. The terminal UI reports that error without starting
a subprocess.

This model does not represent mutually exclusive groups, parser-level custom
validation, or all `nargs='?'` const/omission distinctions. `build_argv()` is not
a validation API. The owning CLI parser and application remain authoritative
when the generated command is run.

## Provisional browser metadata direction

There is no released `ui_core` contract or browser-form consumer in this
checkout. The user reports that the active `web_ui_tools`/Runmux web agent is
working separately in `codex/unified-ui-runmux-web-20261023`, with browser forms
planned for a later stage. Keep the browser wire format provisional. A minimal
future exporter could accept an `ArgumentParser` or
`CliCommand` and return nested dictionaries/lists containing only JSON scalar
values for command names, help text, flags, position, action kind, arity,
required state, and explicitly JSON-safe defaults/choices. It must omit Python
callables and either reject or explicitly mark unsupported values/actions; it
must not coerce arbitrary objects with `str()` and claim parity. The browser
agent owns forms and HTTP endpoints. The owning application/backend must parse
and validate submitted values and invoke commands.

Until that consumer and contract are available, the verified parser-only import
boundary is the useful stable seam; no exporter or shared schema is introduced.

## Process ownership and integrations

`CliTuiApp` and `ProcessRunner` own local subprocesses. Pane deletion and app
cleanup may terminate those subprocesses, consistent with existing TUI
behavior. A Runmux-managed process is owned by Runmux and must not be routed
through those cleanup methods; the Runmux TUI uses its own adapter and lifecycle
operations. This assignment does not change either lifecycle implementation.

MangaDL continues to build its parser, call `introspect_parser()`, filter its
own `tui` command, construct `CliTuiApp(root_command=..., executable=...)`, and
register its post-run image preview action. Its parser construction and
invocation path remain application-owned.
