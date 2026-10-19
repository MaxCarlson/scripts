from __future__ import annotations

from pathlib import Path

from cli_tui.state import TuiScreenMode
from mangadl.tui import build_tui_app


def test_build_tui_app_structure_and_categories():
    app = build_tui_app()

    assert app.title == "MangaDL Interactive Dashboard"
    assert app.screen_mode == TuiScreenMode.MENU

    # Top-level commands should include key MangaDL operations
    root = app.root_command
    assert "run" in root.subcommands
    assert "compress" in root.subcommands
    assert "covers" in root.subcommands
    assert "archive" in root.subcommands

    # Nested compress operations
    compress_cmd = root.subcommands["compress"]
    assert "estimate" in compress_cmd.subcommands
    assert "preview" in compress_cmd.subcommands
    assert "apply" in compress_cmd.subcommands
    assert "inventory" in compress_cmd.subcommands


def test_tui_navigate_to_compress_estimate():
    app = build_tui_app()

    # Move to compress and select
    compress_idx = list(app.root_command.subcommands.keys()).index("compress")
    app.menu_cursor = compress_idx
    app.process_key(10)  # Enter

    assert app.screen_mode == TuiScreenMode.MENU
    assert app.navigation.path == ["compress"]

    # Inside compress, select estimate
    estimate_idx = list(app.current_command.subcommands.keys()).index("estimate")
    app.menu_cursor = estimate_idx
    app.process_key(10)  # Enter

    assert app.screen_mode == TuiScreenMode.FORM
    assert app.current_command.name == "estimate"

    # Verify form has destination, format, quality, etc.
    dests = [w.arg.dest for w in app.form_widgets]
    assert "destination" in dests
    assert "format" in dests
    assert "quality" in dests


def test_command_assembly_for_compress_preview():
    app = build_tui_app()

    # Navigate to compress preview
    compress_cmd = app.root_command.subcommands["compress"]
    app.navigation.push("compress", TuiScreenMode.MENU)
    preview_cmd = compress_cmd.subcommands["preview"]
    app.navigation.push("preview", TuiScreenMode.FORM)
    app._open_form_for_command(preview_cmd)

    # Set destination
    app.current_form.set_value("destination", "sample_manga")
    app.current_form.set_value("format", "webp")
    app.current_form.set_value("mode", "lossy")

    argv = app.current_form.build_argv(executable=app.executable)
    assert "-m" in argv
    assert "mangadl" in argv
    assert "compress" in argv
    assert "preview" in argv
    assert "-d" in argv
    assert "sample_manga" in argv
    assert "-f" in argv
    assert "webp" in argv


def test_post_run_preview_callback_action(monkeypatch):
    app = build_tui_app()

    # Navigate to compress preview
    compress_cmd = app.root_command.subcommands["compress"]
    app.navigation.push("compress", TuiScreenMode.MENU)
    preview_cmd = compress_cmd.subcommands["preview"]
    app.navigation.push("preview", TuiScreenMode.FORM)
    app._open_form_for_command(preview_cmd)

    # Transition to running mode with finished runner
    class DummyRunner:
        is_running = False
        exit_code = 0
        elapsed_seconds = 1.2
        lines = ["Generating sample previews...", "All done!"]

    app.runner = DummyRunner()
    app.navigation.current_screen = TuiScreenMode.RUNNING

    rendered = "\n".join(app.render_virtual_screen(height=24, width=80))
    assert "[v] View Previews" in rendered

    # Test pressing 'v' triggers the callback
    callback_called = []
    # Replace registered callback with tracker
    for action in app.post_run_actions:
        if action.key == ord("v"):
            action.callback = lambda _app: callback_called.append(True)

    handled = app.process_key(ord("v"))
    assert handled is True
    assert callback_called == [True]


def test_compress_preview_view_flag():
    from mangadl.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["compress", "preview", "-d", "somedir", "--view"])
    assert args.view is True

    args_short = parser.parse_args(["compress", "preview", "-d", "somedir", "-V"])
    assert args_short.view is True


def test_compress_preview_view_invocation(tmp_path: Path, monkeypatch):
    viewer_destinations = []
    monkeypatch.setattr(
        "cli_tui.image_viewer.launch_image_viewer",
        lambda destination=None, **kwargs: viewer_destinations.append(destination),
    )
    monkeypatch.setattr(
        "compresser.preview_pipeline.run_preview_pipeline",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        "compresser.preview._select_sources",
        lambda *args, **kwargs: [
            type("DummyImg", (), {"path": tmp_path / "img.png"})()
        ],
    )

    from mangadl.cli import build_parser
    from compresser.preview import run_preview_cli

    preview_out = tmp_path.parent / f"{tmp_path.name}-previews"
    parser = build_parser()
    args = parser.parse_args(
        [
            "compress",
            "preview",
            "-d",
            str(tmp_path),
            "--view",
            "-O",
            str(preview_out),
        ]
    )
    assert args.view is True

    ret = run_preview_cli(
        args, [type("DummyImg", (), {"path": tmp_path / "img.png"})()], tmp_path
    )
    assert ret == 0
    assert len(viewer_destinations) == 1
    assert viewer_destinations[0].parent == preview_out.resolve()


def test_compress_inventory_tui_command_assembly():
    from mangadl.cli import build_parser

    app = build_tui_app()

    # Navigate to compress inventory
    compress_cmd = app.root_command.subcommands["compress"]
    app.navigation.push("compress", TuiScreenMode.MENU)
    inv_cmd = compress_cmd.subcommands["inventory"]
    app.navigation.push("inventory", TuiScreenMode.FORM)
    app._open_form_for_command(inv_cmd)

    # Check widgets
    url_widget = next(w for w in app.form_widgets if w.arg.dest == "url")
    assert url_widget.value == ""  # Must not be "[]"

    verbose_widget = next(w for w in app.form_widgets if w.arg.dest == "verbose")
    assert verbose_widget.value == 0

    # Set destination
    app.current_form.set_value("destination", "hent1imageperpage")

    argv = app.current_form.build_argv(executable=app.executable)
    assert "0" not in argv
    assert "[]" not in argv

    # Verify that the generated command actually parses cleanly in mangadl's parser
    parser = build_parser()
    # Find tokens after "mangadl"
    mangadl_idx = argv.index("mangadl")
    cmd_tokens = argv[mangadl_idx + 1 :]
    parsed = parser.parse_args(cmd_tokens)
    assert parsed.destination == Path("hent1imageperpage")
    assert parsed.verbose == 0
