"""Repository-path compatibility shim for the nested cli_tui package.

The scripts repository adds ``modules/`` to ``sys.path``. Extend this package's
search path so editable installs and direct repository execution resolve the
implementation directory consistently.
"""

from pathlib import Path
import sys

_implementation = Path(__file__).parent / "cli_tui"
if str(_implementation) not in __path__:
    __path__.append(str(_implementation))

from .cli_tui import (  # noqa: E402
    app,
    image_viewer,
    preview_set,
    process_runner,
    schema,
    state,
    widgets,
    CliArgument,
    CliCommand,
    CliTuiApp,
    FormState,
    ImageViewerState,
    NavigationStack,
    OutputViewport,
    PostRunAction,
    PreviewItem,
    PreviewSet,
    PreviewVariant,
    ProcessRunner,
    SideBySideImageViewer,
    TuiScreenMode,
    introspect_parser,
    launch_image_viewer,
    scan_preview_directory,
)

_nested_prefix = __name__ + ".cli_tui."
for _name, _module in tuple(sys.modules.items()):
    if _name.startswith(_nested_prefix):
        sys.modules.setdefault(__name__ + "." + _name[len(_nested_prefix) :], _module)

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
