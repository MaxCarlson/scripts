"""Reusable argparse-to-termdash TUI engine with lazy public imports."""

from importlib import import_module
from typing import Any

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


def __getattr__(name: str) -> Any:
    if name in _MODULES:
        value = import_module(f".{name}", __name__)
    elif name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        value = getattr(import_module(f".{module_name}", __name__), attr_name)
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
    "format_hotkey_footer",
    "PreviewItem",
    "PreviewSet",
    "PreviewVariant",
    "ProcessRunner",
    "SideBySideImageViewer",
    "TuiScreenMode",
    "introspect_parser",
    "launch_image_viewer",
    "scan_preview_directory",
]
