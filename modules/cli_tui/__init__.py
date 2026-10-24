"""Repository-path compatibility shim for the nested cli_tui package.

The scripts repository adds ``modules/`` to ``sys.path``. Extend this package's
search path so implementation modules resolve consistently, and load public
objects on demand so parser metadata imports do not initialize terminal UI code.
"""

from importlib import import_module
from pathlib import Path
import sys
from typing import Any

_implementation = Path(__file__).parent / "cli_tui"
if str(_implementation) not in __path__:
    __path__.append(str(_implementation))

_MODULES = {
    "app",
    "console_pane",
    "image_viewer",
    "layout_store",
    "output_capture",
    "preview_set",
    "process_runner",
    "schema",
    "state",
    "widgets",
}
_EXPORTS = {
    "CliArgument": ("schema", "CliArgument"),
    "CliCommand": ("schema", "CliCommand"),
    "CliTuiApp": ("app", "CliTuiApp"),
    "FormState": ("state", "FormState"),
    "ImageViewerState": ("image_viewer", "ImageViewerState"),
    "NavigationStack": ("state", "NavigationStack"),
    "OutputViewport": ("process_runner", "OutputViewport"),
    "PostRunAction": ("app", "PostRunAction"),
    "PreviewItem": ("preview_set", "PreviewItem"),
    "PreviewSet": ("preview_set", "PreviewSet"),
    "PreviewVariant": ("preview_set", "PreviewVariant"),
    "ProcessRunner": ("process_runner", "ProcessRunner"),
    "SideBySideImageViewer": ("image_viewer", "SideBySideImageViewer"),
    "TuiScreenMode": ("state", "TuiScreenMode"),
    "format_hotkey_footer": ("app", "format_hotkey_footer"),
    "introspect_parser": ("schema", "introspect_parser"),
    "launch_image_viewer": ("image_viewer", "launch_image_viewer"),
    "scan_preview_directory": ("preview_set", "scan_preview_directory"),
}


def _load_module(name: str) -> Any:
    root_name = f"{__name__}.{name}"
    nested_name = f"{__name__}.cli_tui.{name}"
    module = sys.modules.get(root_name) or sys.modules.get(nested_name)
    if module is None:
        module = import_module(f".{name}", __name__)
    sys.modules.setdefault(root_name, module)
    sys.modules.setdefault(nested_name, module)
    return module


def __getattr__(name: str) -> Any:
    if name in _MODULES:
        value = _load_module(name)
    elif name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        value = getattr(_load_module(module_name), attr_name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _MODULES | set(_EXPORTS))


__all__ = [
    "CliArgument",
    "CliCommand",
    "CliTuiApp",
    "FormState",
    "ImageViewerState",
    "NavigationStack",
    "OutputViewport",
    "PostRunAction",
    "PreviewItem",
    "PreviewSet",
    "PreviewVariant",
    "ProcessRunner",
    "SideBySideImageViewer",
    "TuiScreenMode",
    "app",
    "image_viewer",
    "introspect_parser",
    "launch_image_viewer",
    "preview_set",
    "process_runner",
    "scan_preview_directory",
    "schema",
    "state",
    "widgets",
]
