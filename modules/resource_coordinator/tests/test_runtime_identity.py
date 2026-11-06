from resource_coordinator.core.runtime_identity import build_runtime_identity


def test_runtime_revision_tracks_source_contents_not_git_head(tmp_path):
    package = tmp_path / "resource_coordinator"
    package.mkdir()
    init_file = package / "__init__.py"
    module_file = package / "service.py"
    init_file.write_text("__version__ = '0.10.0'\n", encoding="utf-8")
    module_file.write_text("STARTUP_VALUE = 1\n", encoding="utf-8")

    first = build_runtime_identity(package)
    second = build_runtime_identity(package)
    module_file.write_text("STARTUP_VALUE = 2\n", encoding="utf-8")
    changed = build_runtime_identity(package)

    assert first["revision"] == second["revision"]
    assert changed["revision"] != first["revision"]
    assert first["source_path"] == str(init_file.resolve())
