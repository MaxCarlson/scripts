import os
import zipfile
import pytest
import shutil
from pathlib import Path
from zip_for_llms import (
    zip_folder,
    text_file_mode,
    flatten_directory,
    delete_files_to_fit_size,
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_EXCLUDE_EXTS,
    DEFAULT_EXCLUDE_FILES
)

@pytest.fixture
def temp_test_dir(tmp_path: Path) -> Path:
    """Creates a temporary test directory structure."""
    root = tmp_path / "test_repo"
    root.mkdir(parents=True, exist_ok=True)

    (root / "src").mkdir()
    (root / "data").mkdir()
    (root / ".git").mkdir()
    (root / "node_modules").mkdir()
    (root / "src" / "__pycache__").mkdir()

    (root / "src" / "script.py").write_text("print('Hello, Python!')")
    (root / "src" / "main.js").write_text("console.log('Hello, JS!');")
    (root / "src" / "__pycache__" / "cachefile.pyc").write_text("cached")
    
    large_file_path = root / "data" / "large_file.dat" 
    with open(large_file_path, "wb") as f:
        f.write(os.urandom(2 * 1024 * 1024)) 

    (root / "data" / "another_large.log").write_text("LOG" * (500 * 1024 // 3))

    (root / "data" / "small.json").write_text('{"data": "small"}')
    (root / "data" / "temp_file.tmp").write_text("temporary content")
    (root / "README.md").write_text("# Test Repo")
    (root / ".git" / "config").write_text("git config")
    (root / "node_modules" / "package.json").write_text('{"name": "test"}')
    (root / "yarn.lock").write_text('lockfile')

    return root

# --- Test Core Functionalities ---

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
    if source_for_flatten.exists(): shutil.rmtree(source_for_flatten)
    shutil.copytree(temp_test_dir, source_for_flatten)

    # Added verbose=False argument
    flat_dir = flatten_directory(source_for_flatten, name_by_path=False, verbose=False) 
    assert flat_dir.exists()
    assert flat_dir.name == "_flattened"
    
    flat_files = {f.name for f in flat_dir.iterdir() if f.is_file()}
    assert "large_file.dat" in flat_files
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
    assert output_zip.stat().st_size <= 1.05 * 1024 * 1024 

    with zipfile.ZipFile(output_zip, 'r') as z:
        namelist = z.namelist()
        assert "data/large_file.dat" not in namelist 
    
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


# --- Test Exclusion and Pattern Arguments ---
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
def test_exclude_file_custom(temp_test_dir: Path, tmp_path: Path, mode_func_is_zip):
    output_name = f"custom_xf.{'zip' if mode_func_is_zip else 'txt'}"
    output_path = tmp_path / output_name
    current_exclude_files = DEFAULT_EXCLUDE_FILES.copy()
    current_exclude_files.add("README.md")

    if mode_func_is_zip:
        zip_folder(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, current_exclude_files, [], [], None, [], False, False, False)
        with zipfile.ZipFile(output_path, 'r') as z:
            assert "README.md" not in z.namelist()
    else:
        text_file_mode(str(temp_test_dir), str(output_path), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, current_exclude_files, 
                       [], [], False, False, False)
        content = output_path.read_text()
        assert "-- File: README.md --" not in content

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
    (temp_test_dir / "logs").mkdir(exist_ok=True)
    (temp_test_dir / "logs" / "important.log").write_text("important")
    (temp_test_dir / "logs" / "other.log").write_text("other")
    
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

# --- Test Text File Mode Specifics ---

def test_text_file_mode_hierarchy_and_content(temp_test_dir: Path, tmp_path: Path):
    output_txt = tmp_path / "text_output.txt"
    text_file_mode(
        str(temp_test_dir), str(output_txt), DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, 
        DEFAULT_EXCLUDE_FILES, [], [], False, False, False
    )
    assert output_txt.exists()
    content = output_txt.read_text()
    assert "Folder Structure for: test_repo" in content
    assert "    src/" in content
    assert "    data/" in content 
    assert "    .git/" not in content 
    assert "        __pycache__/" not in content 
    
    assert "-- File: README.md --" in content
    assert "# Test Repo" in content
    assert "-- File: src/script.py --" in content
    assert "print('Hello, Python!')" in content
    assert "-- File: data/large_file.dat --" in content 
    assert "-- File: src/__pycache__/cachefile.pyc --" not in content 
    assert "-- File: .git/config --" not in content 


def test_text_file_mode_verbose_skipped(capsys, temp_test_dir: Path, tmp_path: Path):
    output_txt = tmp_path / "verbose_skip.txt"
    current_exclude_exts = DEFAULT_EXCLUDE_EXTS.copy()
    current_exclude_exts.add(".dat") 

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
    
    assert "src/__pycache__/cachefile.pyc" not in stdout 
    assert ".git/config" not in stdout


# --- Test Flattening in Both Modes ---
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
    
    assert (temp_test_dir / "src" / "script.py").exists() 


# --- Test -F and -Z flag combinations and output naming (simulated) ---
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
    return Args()

def run_main_logic_simulation(args_instance: mock_args, tmp_path: Path): 
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

    if actual_text_output_path:
        text_file_mode(args_instance.source, str(actual_text_output_path), final_exclude_dirs, final_exclude_exts, final_exclude_files, 
                       args_instance.remove_patterns, args_instance.keep_patterns, args_instance.flatten, args_instance.name_by_path, args_instance.verbose)
    if actual_zip_output_path:
        zip_folder(args_instance.source, str(actual_zip_output_path), final_exclude_dirs, final_exclude_exts, final_exclude_files,
                   args_instance.remove_patterns, args_instance.keep_patterns, args_instance.max_size, args_instance.preferences,
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
    mock_args.file_mode = True; mock_args.zip_mode = True
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists()
    assert zip_path is not None and zip_path.exists()
    assert txt_path.name == "output_base.txt"
    assert zip_path.name == "output_base.zip"

def test_mode_f_and_z_output_ext_txt(mock_args: mock_args, tmp_path: Path):
    mock_args.file_mode = True; mock_args.zip_mode = True
    mock_args.output = str(tmp_path / "custom_out.txt")
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists() and txt_path.name == "custom_out.txt"
    assert zip_path is not None and zip_path.exists() and zip_path.name == "custom_out.zip"

def test_mode_f_and_z_output_ext_zip(mock_args: mock_args, tmp_path: Path):
    mock_args.file_mode = True; mock_args.zip_mode = True
    mock_args.output = str(tmp_path / "custom_out.zip")
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists() and txt_path.name == "custom_out.txt"
    assert zip_path is not None and zip_path.exists() and zip_path.name == "custom_out.zip"

def test_mode_f_and_z_output_ext_other(mock_args: mock_args, tmp_path: Path, capsys): 
    mock_args.file_mode = True; mock_args.zip_mode = True
    mock_args.verbose = True 
    mock_args.output = str(tmp_path / "custom_out.other")
    txt_path, zip_path = run_main_logic_simulation(mock_args, tmp_path)
    assert txt_path is not None and txt_path.exists() and txt_path.name == "custom_out.txt"
    assert zip_path is not None and zip_path.exists() and zip_path.name == "custom_out.zip"
