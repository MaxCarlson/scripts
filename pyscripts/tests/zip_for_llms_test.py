# File: scripts/pyscripts/tests/zip_for_llms_test.py
import os
import zipfile
import pytest
import shutil
import io
from pathlib import Path
from types import SimpleNamespace
from zip_for_llms import (
    # core API
    zip_folder,
    text_file_mode,
    flatten_directory,
    delete_files_to_fit_size,
    # defaults
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_EXCLUDE_EXTS,
    DEFAULT_EXCLUDE_FILES,
    PRESETS,
    # LLM analysis helpers
    prepare_analysis_workspace,
    run_gemini_cli,
    write_commit_history_snapshot,
    perform_gemini_analysis,
    build_gemini_prompt,
)

# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def temp_test_dir(tmp_path: Path) -> Path:
    """
    Creates a temporary test repository structure with a mix of
    source files, large files, caches, logs, and directories to
    exercise advanced path/glob matching and default/preset ignores.
    """
    root = tmp_path / "test_repo"
    root.mkdir(parents=True, exist_ok=True)

    # dirs
    (root / "src").mkdir()
    (root / "data").mkdir()
    (root / ".git").mkdir()
    (root / "node_modules").mkdir()
    (root / "src" / "__pycache__").mkdir()
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    (root / "analysistmp2xx").mkdir(exist_ok=True)  # for glob matching

    # files
    (root / "src" / "script.py").write_text("print('Hello, Python!')")
    (root / "src" / "main.js").write_text("console.log('Hello, JS!');")
    (root / "src" / "__pycache__" / "cachefile.pyc").write_text("cached")
    (root / "scripts" / "__pycache__" / "cachefile.pyc").write_text("cached")

    # large & log content
    large_file_path = root / "data" / "large_file.dat"
    with open(large_file_path, "wb") as f:
        f.write(os.urandom(2 * 1024 * 1024))  # ~2MB

    (root / "data" / "another_large.log").write_text("LOG" * (500 * 1024 // 3))

    (root / "data" / "small.json").write_text('{"data": "small"}')
    (root / "data" / "temp_file.tmp").write_text("temporary content")
    (root / "README.md").write_text("# Test Repo")
    (root / ".git" / "config").write_text("git config")
    (root / "node_modules" / "package.json").write_text('{"name": "test"}')
    (root / "yarn.lock").write_text('lockfile')

    (root / "logs" / "important.log").write_text("important")
    (root / "logs" / "other.log").write_text("other")
    (root / "analysistmp2xx" / "note.txt").write_text("hi")

    # A binary non-utf8-parseable file for text mode read error path
    (root / "data" / "binary.bin").write_bytes(b"\xff\xfe\xfa\xfb")

    return root


# ================================================================
# Core functionality tests (mostly preserved, adjusted where needed)
# ================================================================

def test_zip_creation_default_exclusions(temp_test_dir: Path, tmp_path: Path):
    output_zip = tmp_path / "test_default.zip"
    zip_folder(
        source_dir_str=str(temp_test_dir), output_zip_str=str(output_zip),
        exclude_dirs=DEFAULT_EXCLUDE_DIRS, exclude_exts=DEFAULT_EXCLUDE_EXTS,
        exclude_files=DEFAULT_EXCLUDE_FILES, remove_patterns=[], keep_patterns=[],
        max_size=None, preferences=[], flatten=False, name_by_path=False, verbose=False
    )
    assert output_zip.exists()
    with zipfile.ZipFile(output_zip, 'r') as z:
        names = z.namelist()
        assert "src/script.py" in names
        assert "data/large_file.dat" in names
        assert not any(name.startswith(".git/") for name in names)
        assert "yarn.lock" not in names


def test_flatten_directory_respects_default_exclusions(temp_test_dir: Path):
    source_for_flatten = temp_test_dir.parent / "source_for_flatten"
    if source_for_flatten.exists():
        shutil.rmtree(source_for_flatten)
    shutil.copytree(temp_test_dir, source_for_flatten)

    flat_dir = flatten_directory(source_for_flatten, name_by_path=False, verbose=False)
    assert flat_dir.exists()
    assert flat_dir.name == "_flattened"

    flat_files = {f.name for f in flat_dir.iterdir() if f.is_file()}
    assert "large_file.dat" in flat_files
    # compiled cache excluded by default exts
    assert "cachefile.pyc" not in flat_files
    shutil.rmtree(source_for_flatten)


def test_zip_with_max_size_and_preferences(temp_test_dir: Path, tmp_path: Path):
    output_zip = tmp_path / "limited.zip"
    zip_folder(
        source_dir_str=str(temp_test_dir),
        output_zip_str=str(output_zip),
        exclude_dirs=DEFAULT_EXCLUDE_DIRS, exclude_exts=DEFAULT_EXCLUDE_EXTS,
        exclude_files=DEFAULT_EXCLUDE_FILES, remove_patterns=[], keep_patterns=[],
        max_size=1,
        preferences=[".dat", ".log"],
        flatten=False, name_by_path=False, verbose=True
    )
    assert output_zip.exists()
    assert output_zip.stat().st_size <= 1.05 * 1024 * 1024  # some headroom
    with zipfile.ZipFile(output_zip, 'r') as z:
        namelist = z.namelist()
        assert "data/large_file.dat" not in namelist
    # Original remains untouched
    assert (temp_test_dir / "data" / "large_file.dat").exists()


def test_delete_files_to_fit_size(tmp_path: Path):
    delete_dir = tmp_path / "delete_test_dir"
    delete_dir.mkdir()
    (delete_dir / "file_c_verylarge.log").write_text("L" * (800 * 1024))
    (delete_dir / "file_b_large.txt").write_text("T" * (700 * 1024))
    (delete_dir / "file_a_medium.log").write_text("LL" * (250 * 1024))
    (delete_dir / "file_d_small.dat").write_text("D" * (300 * 1024))

    removed = delete_files_to_fit_size(delete_dir, 1, [".log", ".txt"], verbose=True)

    assert str(delete_dir / "file_c_verylarge.log") in removed
    assert str(delete_dir / "file_a_medium.log") in removed
    assert len(removed) == 2

    assert not (delete_dir / "file_c_verylarge.log").exists()
    assert not (delete_dir / "file_a_medium.log").exists()
    assert (delete_dir / "file_b_large.txt").exists()
    assert (delete_dir / "file_d_small.dat").exists()


# ================================================================
# Exclusion & pattern arguments (preserved & expanded)
# ================================================================

@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_exclude_dir_custom(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    (temp_test_dir / "custom_exclude_dir").mkdir()
    (temp_test_dir / "custom_exclude_dir" / "file.txt").write_text("in excluded dir")
    output_name = f"custom_xd.{'zip' if mode_func_is_zip else 'txt'}"
    output_path = tmp_path / output_name
    current_exclude_dirs = DEFAULT_EXCLUDE_DIRS.copy()
    current_exclude_dirs.add("custom_exclude_dir")

    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output_path), current_exclude_dirs, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], [], None, [], False, False, False)
        with zipfile.ZipFile(output_path, 'r') as z:
            assert not any(name.startswith("custom_exclude_dir/") for name in z.namelist())
    else:
        text_file_mode(str(temp_test_dir), str(output_path), current_exclude_dirs, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
                       [], [], False, False, False)
        content = output_path.read_text()
        assert "custom_exclude_dir/" not in content
        assert "-- File: custom_exclude_dir" not in content


@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_exclude_ext_custom(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    output_name = f"custom_xe.{'zip' if mode_func_is_zip else 'txt'}"
    output_path = tmp_path / output_name
    current_exclude_exts = DEFAULT_EXCLUDE_EXTS.copy()
    current_exclude_exts.add(".tmp")

    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, current_exclude_exts, DEFAULT_EXCLUDE_FILES, [], [], None, [], False, False, False)
        with zipfile.ZipFile(output_path, 'r') as z:
            assert "data/temp_file.tmp" not in z.namelist()
    else:
        text_file_mode(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, current_exclude_exts, DEFAULT_EXCLUDE_FILES,
                       [], [], False, False, False)
        content = output_path.read_text()
        assert "-- File: data/temp_file.tmp --" not in content


@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_exclude_file_custom_and_include_override(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    """
    Ensures a file listed in exclude_files can be force-included by removing it from the set
    (simulating the CLI behavior where include-file removes from exclusions).
    """
    output_name = f"custom_xf_include.{'zip' if mode_func_is_zip else 'txt'}"
    output_path = tmp_path / output_name

    current_exclude_files = DEFAULT_EXCLUDE_FILES.copy()
    # Pretend README.md was in exclude set but then force-included
    current_exclude_files.add("README.md")
    force_include = {"README.md"}
    current_exclude_files = current_exclude_files - force_include

    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, current_exclude_files, [], [], None, [], False, False, False)
        with zipfile.ZipFile(output_path, 'r') as z:
            assert "README.md" in z.namelist()
    else:
        text_file_mode(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, current_exclude_files,
                       [], [], False, False, False)
        content = output_path.read_text()
        assert "-- File: README.md --" in content


@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_remove_patterns_filename(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    output_name = f"remove_pat_file.{'zip' if mode_func_is_zip else 'txt'}"
    output_path = tmp_path / output_name

    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
                   ["*.log"], [], None, [], False, False, False)
        with zipfile.ZipFile(output_path, 'r') as z:
            assert "data/another_large.log" not in z.namelist()
            assert "data/small.json" in z.namelist()
    else:
        text_file_mode(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
                       ["*.log"], [], False, False, False)
        content = output_path.read_text()
        assert "-- File: data/another_large.log --" not in content
        assert "-- File: data/small.json --" in content


@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_remove_patterns_dirname(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    (temp_test_dir / "data" / "another.txt").write_text("in data")
    output_name = f"remove_pat_dir.{'zip' if mode_func_is_zip else 'txt'}"
    output_path = tmp_path / output_name

    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
                   ["data"], [], None, [], False, False, False)
        with zipfile.ZipFile(output_path, 'r') as z:
            assert not any(name.startswith("data/") for name in z.namelist())
            assert "src/script.py" in z.namelist()
    else:
        text_file_mode(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
                       ["data"], [], False, False, True)
        content = output_path.read_text()
        assert "    data/" not in content
        assert "-- File: data/large_file.dat --" not in content
        assert "-- File: src/script.py --" in content


@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_keep_patterns_overrides_remove(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    output_name = f"keep_pat.{'zip' if mode_func_is_zip else 'txt'}"
    output_path = tmp_path / output_name

    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
                   ["*.log"], ["important.log"], None, [], False, False, False)
        with zipfile.ZipFile(output_path, 'r') as z:
            assert "logs/important.log" in z.namelist()
            assert "logs/other.log" not in z.namelist()
            assert "data/another_large.log" not in z.namelist()
    else:
        text_file_mode(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
                       ["*.log"], ["important.log"], False, False, False)
        content = output_path.read_text()
        assert "-- File: logs/important.log --" in content
        assert "-- File: logs/other.log --" not in content
        assert "-- File: data/another_large.log --" not in content


# ================================================================
# Advanced exclude-dir semantics (added)
# ================================================================

@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_exclude_dir_by_name_anywhere(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    output = tmp_path / f"xd_name_anywhere.{'zip' if mode_func_is_zip else 'txt'}"
    xd = DEFAULT_EXCLUDE_DIRS.copy()
    xd.update({"__pycache__"})  # ensure present
    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output), xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], [], None, [], False, False, False)
        with zipfile.ZipFile(output, "r") as z:
            assert not any("src/__pycache__/" in n or "scripts/__pycache__/" in n for n in z.namelist())
    else:
        text_file_mode(str(temp_test_dir), str(output), xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], [], False, False, False)
        content = output.read_text()
        assert "        __pycache__/" not in content  # not in structure


@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_exclude_dir_by_path_fragment(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    output = tmp_path / f"xd_path_fragment.{'zip' if mode_func_is_zip else 'txt'}"
    xd = DEFAULT_EXCLUDE_DIRS.copy()
    xd.update({"scripts/__pycache__"})
    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output), xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], [], None, [], False, False, False)
        with zipfile.ZipFile(output, "r") as z:
            assert not any("scripts/__pycache__/" in n for n in z.namelist())
    else:
        text_file_mode(str(temp_test_dir), str(output), xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], [], False, False, False)
        content = output.read_text()
        assert "    scripts/" in content
        assert "        __pycache__/" not in content


@pytest.mark.parametrize("mode_func_is_zip", [True, False])
def test_exclude_dir_by_glob(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    output = tmp_path / f"xd_glob.{'zip' if mode_func_is_zip else 'txt'}"
    xd = DEFAULT_EXCLUDE_DIRS.copy()
    xd.update({"analysistmp*"})
    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output), xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], [], None, [], False, False, False)
        with zipfile.ZipFile(output, "r") as z:
            assert not any(n.startswith("analysistmp2xx/") for n in z.namelist())
    else:
        text_file_mode(str(temp_test_dir), str(output), xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], [], False, False, False)
        content = output.read_text()
        assert "analysistmp2xx/" not in content


def test_exclude_dir_multiple_values_combined(temp_test_dir: Path, tmp_path: Path):
    """
    Simulate passing multiple -xd values: exact name, path fragment, and glob.
    """
    output_zip = tmp_path / "xd_multi.zip"
    xd = DEFAULT_EXCLUDE_DIRS.copy()
    xd.update({"__pycache__", "scripts/__pycache__", "analysistmp*"})
    zip_folder(
        str(temp_test_dir), str(output_zip),
        xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [],
        [], None, [], False, False, False
    )
    with zipfile.ZipFile(output_zip, "r") as z:
        names = z.namelist()
        assert not any("src/__pycache__/" in n for n in names)
        assert not any("scripts/__pycache__/" in n for n in names)
        assert not any(n.startswith("analysistmp2xx/") for n in names)


# ================================================================
# Text mode specifics (preserved & expanded)
# ================================================================

def test_text_file_mode_hierarchy_and_content(temp_test_dir: Path, tmp_path: Path):
    output_txt = tmp_path / "text_output.txt"
    text_file_mode(
        str(temp_test_dir), str(output_txt), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS,
        DEFAULT_EXCLUDE_FILES, [], [], False, False, False
    )
    assert output_txt.exists()
    content = output_txt.read_text()
    # Preamble exists
    assert "This document packages a repository for a Large Language Model (LLM)." in content
    # Structure
    assert "Folder Structure for: test_repo" in content
    assert "    src/" in content
    assert "    data/" in content
    assert "    .git/" not in content
    assert "        __pycache__/" not in content
    # Files
    assert "-- File: README.md --" in content
    assert "# Test Repo" in content
    assert "-- File: src/script.py --" in content
    assert "print('Hello, Python!')" in content
    assert "-- File: data/large_file.dat --" in content  # allowed binary in text listing; content may not render
    assert "-- File: src/__pycache__/cachefile.pyc --" not in content
    assert "-- File: .git/config --" not in content


def test_text_file_mode_verbose_skipped_and_non_utf8(capsys, temp_test_dir: Path, tmp_path: Path):
    output_txt = tmp_path / "verbose_skip.txt"
    current_exclude_exts = DEFAULT_EXCLUDE_EXTS.copy()
    current_exclude_exts.add(".dat")  # exclude data/large_file.dat

    text_file_mode(
        str(temp_test_dir), str(output_txt), DEFAULT_EXCLUDE_DIRS, current_exclude_exts,
        DEFAULT_EXCLUDE_FILES,
        [], [], False, False, True
    )
    captured = capsys.readouterr()
    stdout = captured.out

    assert "Files skipped from content:" in stdout
    assert "yarn.lock (excluded by dir/ext/file rule on 'yarn.lock')" in stdout
    assert "data/large_file.dat (excluded by dir/ext/file rule on 'large_file.dat')" in stdout
    # Non-UTF-8 binary should log a read error (not excluded by ext)
    assert "data/binary.bin (binary or non-UTF-8 content)" in stdout

    # Ensure some sensitive dirs didn't leak
    assert "src/__pycache__/cachefile.pyc" not in stdout
    assert ".git/config" not in stdout


# ================================================================
# Flattening in both modes (preserved)
# ================================================================

def test_zip_with_flatten_and_name_by_path(temp_test_dir: Path, tmp_path: Path):
    output_zip = tmp_path / "flat_named.zip"
    zip_folder(
        str(temp_test_dir), str(output_zip), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS,
        DEFAULT_EXCLUDE_FILES, [], [], None, [], True, True, True
    )
    assert output_zip.exists()
    with zipfile.ZipFile(output_zip, 'r') as z:
        names = z.namelist()
        assert "src_script.py" in names
        assert "data_large_file.dat" in names
        assert "README.md" in names
        assert "folder_structure.txt" in names
        assert not any("/" in name for name in names if name != "folder_structure.txt" and Path(name).parent != Path("."))

    assert (temp_test_dir / "src" / "script.py").exists()
    assert (temp_test_dir / "data" / "large_file.dat").exists()


def test_text_mode_with_flatten_and_name_by_path(temp_test_dir: Path, tmp_path: Path):
    output_txt = tmp_path / "flat_named_text.txt"
    text_file_mode(
        str(temp_test_dir), str(output_txt), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS,
        DEFAULT_EXCLUDE_FILES, [], [], True, True, True
    )
    assert output_txt.exists()
    content = output_txt.read_text()
    assert "Folder Structure for: test_repo" in content
    assert "    src/" in content
    assert "-- File: src_script.py --" in content
    assert "print('Hello, Python!')" in content
    assert "-- File: data_large_file.dat --" in content
    assert "-- File: README.md --" in content
    # original files still in place
    assert (temp_test_dir / "src" / "script.py").exists()


# ================================================================
# Flag combinations and output naming (simulated, preserved)
# ================================================================

@pytest.fixture
def mock_args(tmp_path: Path, temp_test_dir: Path):
    class Args:
        source = str(temp_test_dir)
        output = str(tmp_path / "output_base")
        file_mode = False
        zip_mode = False
        exclude_dir = list(DEFAULT_EXCLUDE_DIRS)
        exclude_ext = list(DEFAULT_EXCLUDE_EXTS)
        exclude_file = list(DEFAULT_EXCLUDE_FILES)
        include_file = []
        remove_patterns = []
        keep_patterns = []
        max_size = None
        preferences = []
        flatten = False
        name_by_path = False
        verbose = False
        preset = None
    return Args()


def run_main_logic_simulation(args_instance: mock_args, tmp_path: Path):
    from zip_for_llms import PRESETS as _PRESETS, text_file_mode as _text_file_mode, zip_folder as _zip_folder
    run_file_mode = args_instance.file_mode
    run_zip_mode = args_instance.zip_mode
    if not run_file_mode and not run_zip_mode:
        run_zip_mode = True

    output_path_arg = Path(args_instance.output)
    output_dir = output_path_arg.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_path_arg.name.startswith('.') and not output_path_arg.stem.startswith('.'):
        base_name_for_output = output_path_arg.name
    else:
        base_name_for_output = output_path_arg.stem if output_path_arg.stem else output_path_arg.name

    actual_text_output_path: Path | None = None
    actual_zip_output_path: Path | None = None

    if run_file_mode and run_zip_mode:
        original_suffix = output_path_arg.suffix.lower()
        if original_suffix == ".txt":
            actual_text_output_path = output_path_arg
            actual_zip_output_path = output_dir / (base_name_for_output + ".zip")
        elif original_suffix == ".zip":
            actual_zip_output_path = output_path_arg
            actual_text_output_path = output_dir / (base_name_for_output + ".txt")
        else:
            actual_text_output_path = output_dir / (f"{base_name_for_output}.txt")
            actual_zip_output_path = output_dir / (f"{base_name_for_output}.zip")
    elif run_file_mode:
        actual_text_output_path = output_dir / (f"{base_name_for_output}.txt")
    elif run_zip_mode:
        actual_zip_output_path = output_dir / (f"{base_name_for_output}.zip")

    final_exclude_files = set(args_instance.exclude_file) - set(args_instance.include_file)
    final_exclude_dirs = set(args_instance.exclude_dir)
    final_exclude_exts = set(args_instance.exclude_ext)
    final_remove_patterns = list(args_instance.remove_patterns)

    if args_instance.preset:
        preset = _PRESETS[args_instance.preset]
        final_exclude_dirs.update(preset.get("dirs", set()))
        final_exclude_exts.update(preset.get("exts", set()))
        final_exclude_files.update(preset.get("files", set()))
        final_remove_patterns.extend(preset.get("patterns", []))

    if actual_text_output_path:
        _text_file_mode(args_instance.source, str(actual_text_output_path), final_exclude_dirs, final_exclude_exts, final_exclude_files,
                        final_remove_patterns, args_instance.keep_patterns, args_instance.flatten, args_instance.name_by_path, args_instance.verbose)
    if actual_zip_output_path:
        _zip_folder(args_instance.source, str(actual_zip_output_path), final_exclude_dirs, final_exclude_exts, final_exclude_files,
                    final_remove_patterns, args_instance.keep_patterns, args_instance.max_size, args_instance.preferences,
                    args_instance.flatten, args_instance.name_by_path, args_instance.verbose)
    return actual_text_output_path, actual_zip_output_path


def test_mode_default_is_zip(mock_args: mock_args, tmp_path: Path):
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is None
    assert zip_path is not None and zip_path.exists()
    assert zip_path.name == "output_base.zip"


def test_mode_only_f(mock_args: mock_args, tmp_path: Path):
    mock_args.file_mode = True
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists()
    assert zip_path is None
    assert txt_path.name == "output_base.txt"


def test_mode_only_z(mock_args: mock_args, tmp_path: Path):
    mock_args.zip_mode = True
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is None
    assert zip_path is not None and zip_path.exists()
    assert zip_path.name == "output_base.zip"


def test_mode_f_and_z_no_ext_output(mock_args: mock_args, tmp_path: Path):
    mock_args.file_mode = True
    mock_args.zip_mode = True
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists()
    assert zip_path is not None and zip_path.exists()
    assert txt_path.name == "output_base.txt"
    assert zip_path.name == "output_base.zip"


def test_mode_f_and_z_output_ext_txt(mock_args: mock_args, tmp_path: Path):
    mock_args.file_mode = True
    mock_args.zip_mode = True
    mock_args.output = str(tmp_path / "custom_out.txt")
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists() and txt_path.name == "custom_out.txt"
    assert zip_path is not None and zip_path.exists() and zip_path.name == "custom_out.zip"


def test_mode_f_and_z_output_ext_zip(mock_args: mock_args, tmp_path: Path):
    mock_args.file_mode = True
    mock_args.zip_mode = True
    mock_args.output = str(tmp_path / "custom_out.zip")
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists() and txt_path.name == "custom_out.txt"
    assert zip_path is not None and zip_path.exists() and zip_path.name == "custom_out.zip"


def test_mode_f_and_z_output_ext_other(mock_args: mock_args, tmp_path: Path):
    mock_args.file_mode = True
    mock_args.zip_mode = True
    mock_args.verbose = True
    mock_args.output = str(tmp_path / "custom_out.other")
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists() and txt_path.name == "custom_out.txt"
    assert zip_path is not None and zip_path.exists() and zip_path.name == "custom_out.zip"


def test_preset_python_applied_correctly(mock_args: mock_args, tmp_path: Path, temp_test_dir: Path):
    (temp_test_dir / ".venv").mkdir()
    (temp_test_dir / ".venv" / "pyvenv.cfg").write_text("config")
    (temp_test_dir / "myproject.egg-info").mkdir()
    (temp_test_dir / "myproject.egg-info" / "top_level.txt").write_text("myproject")
    (temp_test_dir / ".coverage").write_text("coverage data")

    mock_args.preset = "python"
    mock_args.zip_mode = True
    mock_args.file_mode = False
    mock_args.output = str(tmp_path / "preset_test.zip")

    _, zip_path = run_main_logic_simulation(mock_args, tmp_path)

    assert zip_path is not None and zip_path.exists()
    with zipfile.ZipFile(zip_path, 'r') as z:
        namelist = z.namelist()
        assert "src/script.py" in namelist
        assert not any(name.startswith(".venv/") for name in namelist)
        assert not any(name.startswith("myproject.egg-info/") for name in namelist)
        assert ".coverage" not in namelist
        assert not any(name.startswith("src/__pycache__/") for name in namelist)


# ================================================================
# Gemini CLI analysis – new tests
# ================================================================

def test_prepare_analysis_workspace_prunes(temp_test_dir: Path):
    ws = prepare_analysis_workspace(
        temp_test_dir,
        exclude_dirs=DEFAULT_EXCLUDE_DIRS | {"analysistmp*"},
        exclude_exts=DEFAULT_EXCLUDE_EXTS | {".tmp"},
        exclude_files=DEFAULT_EXCLUDE_FILES | {"README.md"},
        remove_patterns=["*.log"],
        keep_patterns=[],
        verbose=True
    )
    try:
        # removed logs/tmp/lock/globbed dirs
        assert not (ws / "data" / "another_large.log").exists()
        assert not (ws / "data" / "temp_file.tmp").exists()
        assert not (ws / "yarn.lock").exists()
        assert not (ws / "analysistmp2xx").exists()
        # kept relevant source
        assert (ws / "src" / "script.py").exists()
        # workspace guide exists
        assert (ws / "LLM_WORKSPACE_README.txt").exists()
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_run_gemini_cli_constructs_command(monkeypatch, tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()

    calls = {}

    def fake_which(cmd):
        return "/usr/bin/" + cmd if cmd == "gemini" else None

    class CP:
        returncode = 0
        stdout = "OK"
        stderr = ""

    def fake_run(cmd, cwd=None, capture_output=None, text=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        return CP()

    monkeypatch.setattr("zip_for_llms.shutil.which", fake_which)
    monkeypatch.setattr("zip_for_llms.subprocess.run", fake_run)

    cp = run_gemini_cli(ws, model="gemini-2.5-flash", prompt="Analyze", show_memory_usage=True, verbose=True)
    assert cp.returncode == 0 and cp.stdout == "OK"
    assert calls["cwd"] == str(ws)
    assert "--all-files" in calls["cmd"]
    assert "gemini-2.5-flash" in calls["cmd"]
    # check --show-memory-usage presence (inserted at index 1)
    assert "--show-memory-usage" in calls["cmd"]


def test_write_commit_history_snapshot_skips_without_git(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    dest = tmp_path / "ws"
    dest.mkdir()
    # Pretend git not available
    monkeypatch.setattr("zip_for_llms.which", lambda c: None if c == "git" else shutil.which(c))
    out = write_commit_history_snapshot(repo, dest, limit=3, verbose=True)
    assert out is None


def test_build_gemini_prompt_content():
    no_commits = build_gemini_prompt(include_commits=False)
    with_commits = build_gemini_prompt(include_commits=True)
    assert "Project purpose" in no_commits or "purpose" in no_commits
    assert "Recent Changes" in with_commits


def test_perform_gemini_analysis_creates_report_and_cleans_workspace(monkeypatch, temp_test_dir: Path, tmp_path: Path):
    """
    Integration-lite test:
      - Prepare workspace is real (uses pruning rules).
      - Gemini call is mocked to avoid external dependency.
      - Ensure report file is created.
      - Ensure workspace is removed unless keep flag is set.
    """
    # Monkeypatch run_gemini_cli to avoid external calls
    class CP:
        def __init__(self, rc=0, out="REPORT", err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    created_workspaces = []

    def fake_prepare(src, *args, **kwargs):
        ws = tmp_path / "__fake_ws"
        ws.mkdir(exist_ok=True)
        created_workspaces.append(ws)
        # create a file to ensure --all-files would see something
        (ws / "README_FAKE.md").write_text("fake")
        return ws

    def fake_run_cli(ws, model, prompt, show_memory_usage, gemini_bin=None, verbose=False):
        # Assert cwd/ws is what we created
        assert ws.exists()
        assert "Gemini" not in (ws / "README_FAKE.md").read_text()  # just sanity
        return CP(0, "# Fake Gemini Report\nOK")

    monkeypatch.setattr("zip_for_llms.prepare_analysis_workspace", fake_prepare)
    monkeypatch.setattr("zip_for_llms.run_gemini_cli", fake_run_cli)

    report = tmp_path / "repo_analysis.md"
    perform_gemini_analysis(
        source_dir_str=str(temp_test_dir),
        model="gemini-2.5-flash",
        exclude_dirs=DEFAULT_EXCLUDE_DIRS,
        exclude_exts=DEFAULT_EXCLUDE_EXTS,
        exclude_files=DEFAULT_EXCLUDE_FILES,
        remove_patterns=[],
        keep_patterns=[],
        include_commits=False,
        commit_limit=5,
        show_memory_usage=True,
        output_report_path=report,
        keep_workspace=False,
        verbose=True
    )

    # report created
    assert report.exists() and report.read_text().startswith("# Fake Gemini Report")
    # workspace cleaned up
    assert created_workspaces and not created_workspaces[0].exists()


def test_perform_gemini_analysis_keeps_workspace_when_flag_set(monkeypatch, temp_test_dir: Path, tmp_path: Path):
    class CP:
        def __init__(self, rc=0, out="REPORT", err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def fake_prepare(src, *args, **kwargs):
        ws = tmp_path / "__fake_ws_keep"
        ws.mkdir(exist_ok=True)
        return ws

    def fake_run_cli(ws, *_, **__):
        return CP(0, "OK")

    monkeypatch.setattr("zip_for_llms.prepare_analysis_workspace", fake_prepare)
    monkeypatch.setattr("zip_for_llms.run_gemini_cli", fake_run_cli)

    report = tmp_path / "keep_report.md"
    perform_gemini_analysis(
        source_dir_str=str(temp_test_dir),
        model="gemini-2.5-flash",
        exclude_dirs=DEFAULT_EXCLUDE_DIRS,
        exclude_exts=DEFAULT_EXCLUDE_EXTS,
        exclude_files=DEFAULT_EXCLUDE_FILES,
        remove_patterns=[],
        keep_patterns=[],
        include_commits=False,
        commit_limit=3,
        show_memory_usage=False,
        output_report_path=report,
        keep_workspace=True,
        verbose=False
    )
    assert report.exists()
    assert (tmp_path / "__fake_ws_keep").exists()


def test_perform_gemini_analysis_handles_nonzero_exit(monkeypatch, temp_test_dir: Path, tmp_path: Path):
    class CP:
        def __init__(self):
            self.returncode = 17
            self.stdout = "partial"
            self.stderr = "boom"

    def fake_prepare(src, *args, **kwargs):
        ws = tmp_path / "__fake_ws_err"
        ws.mkdir(exist_ok=True)
        return ws

    def fake_run_cli(ws, *_, **__):
        return CP()

    monkeypatch.setattr("zip_for_llms.prepare_analysis_workspace", fake_prepare)
    monkeypatch.setattr("zip_for_llms.run_gemini_cli", fake_run_cli)

    report = tmp_path / "err_report.md"
    perform_gemini_analysis(
        source_dir_str=str(temp_test_dir),
        model="gemini-2.5-flash",
        exclude_dirs=DEFAULT_EXCLUDE_DIRS,
        exclude_exts=DEFAULT_EXCLUDE_EXTS,
        exclude_files=DEFAULT_EXCLUDE_FILES,
        remove_patterns=[],
        keep_patterns=[],
        include_commits=False,
        commit_limit=3,
        show_memory_usage=False,
        output_report_path=report,
        keep_workspace=False,
        verbose=True
    )
    assert report.exists()
    txt = report.read_text()
    assert "Gemini CLI returned exit code 17" in txt
    assert "## STDOUT" in txt and "partial" in txt
    assert "## STDERR" in txt and "boom" in txt


def test_perform_gemini_analysis_includes_commit_snapshot_when_enabled(monkeypatch, temp_test_dir: Path, tmp_path: Path):
    """
    We don't invoke `git`; instead ensure our pipeline requests a snapshot and
    that the snapshot file lands in the workspace prior to the (mocked) CLI run.
    """
    class CP:
        def __init__(self):
            self.returncode = 0
            self.stdout = "OK"
            self.stderr = ""

    # Our fake prepare creates the workspace
    def fake_prepare(src, *args, **kwargs):
        ws = tmp_path / "__fake_ws_commits"
        ws.mkdir(exist_ok=True)
        return ws

    # Fake writer places the snapshot file
    def fake_write_commits(src_repo, dest_dir, limit, verbose):
        out = dest_dir / "COMMIT_HISTORY_FOR_LLM.txt"
        out.write_text("commit A\ncommit B", encoding="utf-8")
        return out

    # Capture that CLI sees the workspace containing the snapshot
    snapshot_seen = {"ok": False}

    def fake_run_cli(ws, *_, **__):
        if (ws / "COMMIT_HISTORY_FOR_LLM.txt").exists():
            snapshot_seen["ok"] = True
        return CP()

    monkeypatch.setattr("zip_for_llms.prepare_analysis_workspace", fake_prepare)
    monkeypatch.setattr("zip_for_llms.write_commit_history_snapshot", fake_write_commits)
    monkeypatch.setattr("zip_for_llms.run_gemini_cli", fake_run_cli)

    report = tmp_path / "commit_report.md"
    perform_gemini_analysis(
        source_dir_str=str(temp_test_dir),
        model="gemini-2.5-flash",
        exclude_dirs=DEFAULT_EXCLUDE_DIRS,
        exclude_exts=DEFAULT_EXCLUDE_EXTS,
        exclude_files=DEFAULT_EXCLUDE_FILES,
        remove_patterns=[],
        keep_patterns=[],
        include_commits=True,
        commit_limit=5,
        show_memory_usage=False,
        output_report_path=report,
        keep_workspace=False,
        verbose=False
    )
    assert report.exists()
    assert snapshot_seen["ok"] is True


# ================================================================
# Extra coverage for edge cases & defaults
# ================================================================

def test_text_mode_skips_binary_file(temp_test_dir: Path, tmp_path: Path):
    """
    Ensure binary file is skipped with informative message stored in verbose path.
    (Here we don't capture stdout; we just ensure it doesn't appear in output content.)
    """
    out = tmp_path / "txt.txt"
    text_file_mode(
        str(temp_test_dir), str(out),
        DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
        [], [], False, False, False
    )
    content = out.read_text()
    assert "-- File: data/binary.bin --" not in content


def test_zip_honors_remove_and_keep_on_conflict(temp_test_dir: Path, tmp_path: Path):
    """
    If remove_patterns match a filename but keep_patterns includes it,
    the file should be kept.
    """
    out = tmp_path / "rk.zip"
    zip_folder(
        str(temp_test_dir), str(out),
        DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
        ["*.log"], ["other.log"], None, [], False, False, False
    )
    with zipfile.ZipFile(out, "r") as z:
        names = z.namelist()
        # important.log excluded by remove, but keep only "other.log"
        assert "logs/other.log" in names
        assert "logs/important.log" not in names


def test_zip_respects_advanced_exclude_dirs_when_flattening(temp_test_dir: Path, tmp_path: Path):
    """
    Even in flatten mode the advanced exclude folder checks should apply
    (by virtue of prune rules during flatten copy).
    """
    out = tmp_path / "flat.zip"
    xd = DEFAULT_EXCLUDE_DIRS.copy()
    xd.update({"analysistmp*"})
    zip_folder(
        str(temp_test_dir), str(out),
        xd, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
        [], [], None, [], True, False, False
    )
    with zipfile.ZipFile(out, "r") as z:
        names = z.namelist()
        # folder_structure.txt always exists in working_dir_for_zip
        assert "folder_structure.txt" in names
        # flattened names shouldn't include analysistmp* files
        assert not any("analysistmp" in n for n in names)


def test_text_mode_with_keep_over_remove_dirname(temp_test_dir: Path, tmp_path: Path):
    """
    Create a directory that matches a remove pattern but a specific keep
    pattern rescues a file within it.
    """
    special_dir = temp_test_dir / "build_logs"
    special_dir.mkdir(exist_ok=True)
    (special_dir / "survivor.md").write_text("keep me")

    out = tmp_path / "keep_dir.txt"
    text_file_mode(
        str(temp_test_dir), str(out),
        DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
        ["build_*"], ["survivor.md"], False, False, False
    )
    txt = out.read_text()
    assert "-- File: build_logs/survivor.md --" in txt


def test_text_mode_with_name_by_path_false_and_true(temp_test_dir: Path, tmp_path: Path):
    """
    Ensure file display names differ when flatten + name_by_path toggles are used.
    """
    # non-flattened - direct relative path names
    out1 = tmp_path / "non_flat.txt"
    text_file_mode(
        str(temp_test_dir), str(out1),
        DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
        [], [], False, False, False
    )
    t1 = out1.read_text()
    assert "-- File: src/script.py --" in t1

    # flattened + name_by_path
    out2 = tmp_path / "flat_named.txt"
    text_file_mode(
        str(temp_test_dir), str(out2),
        DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
        [], [], True, True, False
    )
    t2 = out2.read_text()
    assert "-- File: src_script.py --" in t2
