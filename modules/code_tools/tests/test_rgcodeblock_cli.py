# tests/test_rgcodeblock_cli.py
import pytest
import subprocess
import json
from unittest.mock import patch, mock_open, MagicMock
import os
import sys
from collections import defaultdict
import re
import argparse # Ensure argparse is imported

# Import the CLI script module
import rgcodeblock_cli as rgcb_cli
# Import the library module for mocking its functions
import rgcodeblock_lib as rgc_lib

# --- Fixtures (These were missing) ---

@pytest.fixture
def mock_rg_subprocess(monkeypatch):
    """Mocks subprocess.run for rg calls."""
    mock_run = MagicMock(spec=subprocess.CompletedProcess)
    def side_effect_func(*args, **kwargs):
        mock_run.stdout = getattr(side_effect_func, 'stdout_val', "")
        mock_run.stderr = getattr(side_effect_func, 'stderr_val', "")
        mock_run.returncode = getattr(side_effect_func, 'returncode_val', 0)
        side_effect_func.called_cmd = args[0] if args else None
        side_effect_func.called_kwargs = kwargs
        return mock_run
    side_effect_func.stdout_val = ""
    side_effect_func.stderr_val = ""
    side_effect_func.returncode_val = 0
    side_effect_func.called_cmd = None
    side_effect_func.called_kwargs = {}
    monkeypatch.setattr(subprocess, "run", side_effect_func)
    return side_effect_func

@pytest.fixture
def mock_file_content(monkeypatch):
    """Mocks open() to provide specific file content for tests."""
    files_dict = {}
    original_open = open
    def side_effect_open(filename, mode='r', *args, **kwargs):
        filename_str = str(filename)
        if filename_str in files_dict and 'r' in mode:
            content = files_dict[filename_str]
            m_open = mock_open(read_data=content)
            mock_file_handle = m_open(filename_str, mode, *args, **kwargs)
            # Ensure readlines and read return correctly from the mock handle
            mock_file_handle.readlines.return_value = [(line + '\n') for line in content.splitlines()]
            mock_file_handle.read.return_value = content
            mock_file_handle.__enter__.return_value = mock_file_handle # For 'with open(...)'
            return mock_file_handle
        else:
            # Fallback for files not mocked (like pytest internals or other parts of the system)
            return original_open(filename_str, mode, *args, **kwargs)
    monkeypatch.setattr("builtins.open", side_effect_open)
    return files_dict

# Helper to run main for the CLI script (This was missing)
def run_cli_main_with_args(args_list, capsys):
    """Helper to run the CLI script's main() with mocked sys.argv."""
    # Reset STATS and Notes before each CLI run test
    global_stats_keys = list(rgcb_cli.STATS.keys())
    for key in global_stats_keys:
        if key == "matches_by_lang_type": rgcb_cli.STATS[key] = defaultdict(int)
        elif key == "files_with_matches_by_ext": rgcb_cli.STATS[key] = defaultdict(set)
        elif key == "processed_files": rgcb_cli.STATS[key] = set()
        else: rgcb_cli.STATS[key] = 0
    if hasattr(rgc_lib, 'OPTIONAL_LIBRARY_NOTES'):
        rgc_lib.OPTIONAL_LIBRARY_NOTES.clear()

    with patch.object(sys, 'argv', ['rgcodeblock_cli.py'] + args_list):
        exit_code = None
        try:
            rgcb_cli.main()
            # If main completes without SystemExit and --list-languages wasn't called, assume 0
            if "--list-languages" not in args_list:
                 exit_code = 0
            # list_languages calls sys.exit(0) itself, so it will be caught by SystemExit
        except SystemExit as e:
            exit_code = e.code
    captured = capsys.readouterr()
    return captured.out, captured.err, exit_code

# --- Test Data --- (Same as provided in previous response)
PYTHON_SAMPLE_CODE_1="""# Comment line 1\nclass MyClass: # Line 2 (0-idx: 1)\n    def __init__(self, value): # Line 3 (0-idx: 2)\n        self.value = value # Line 4 (0-idx: 3)\n\n    def another_method(self): # Line 6 (0-idx: 5)\n        pass # Line 7 (0-idx: 6)"""
PYTHON_LINES_1 = [(l + '\n') for l in PYTHON_SAMPLE_CODE_1.splitlines()]
JSON_SAMPLE_CODE_1 ="""{\n  "name": "example",\n  "data": [1, 2, 3],\n  "details": { "id": 101 }\n}"""
JSON_LINES_1 = [(l + '\n') for l in JSON_SAMPLE_CODE_1.splitlines()]
RUBY_SAMPLE_FOR_CLI = """\nclass Greeter\n  def initialize(name)\n    @name = name\n  end\n\n  def greet\n    puts "Hello, #{@name}!"\n  end\nend\n"""
LUA_SAMPLE_FOR_CLI = """\nlocal M = {}\n\nfunction M.calculate(a, b)\n  local sum = a + b\n  local product = a * b\n  return sum, product\nend\n\nreturn M\n"""

# --- CLI Tests ---

def test_list_languages_cli(capsys): # This test should now pass due to fix in rgcodeblock_cli.py and helper present
    out, err, code = run_cli_main_with_args(["--list-languages"], capsys)
    assert code == 0, f"Expected exit 0 for --list-languages, got {code}. Err: {err}"
    assert "Supported Language Types" in out
    assert "python" in out

def test_no_matches_found_cli(mock_rg_subprocess, capsys):
    mock_rg_subprocess.stdout_val = ""; mock_rg_subprocess.returncode_val = 1
    out, err, code = run_cli_main_with_args(["nonexistentpattern", "."], capsys)
    assert code == 0; assert out == ""

def test_basic_match_and_extraction_text_format_cli(mock_rg_subprocess, mock_file_content, capsys):
    rg_json_output = json.dumps({"type": "match", "data": { "path": {"text": "test.py"}, "line_number": 4, "submatches": [{"match": {"text": "__init__"}}]}}) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output
    mock_file_content["test.py"] = PYTHON_SAMPLE_CODE_1
    expected_block = PYTHON_LINES_1[2:5]; expected_start_0idx = 2; expected_end_0idx = 4
    with patch.object(rgc_lib, 'extract_python_block_ast', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["__init__", "test.py"], capsys)
    assert code == 0; assert "╠══" in out
    # Assert key parts of the header robustly
    assert re.search(r"File:\s*\x1b\[0m\s*test\.py:4", out), f"File header problem. Output:\n{out}"
    assert re.search(r"Highlight\(s\)\s*\(1\):\s*\x1b\[0m\s*\"__init__\"", out)
    assert re.search(r"def .*\033\[1;31m__init__\033\[0m.*:", out); assert "self.value = value" in out

def test_json_format_output_cli(mock_rg_subprocess, mock_file_content, capsys):
    rg_json_output_line = json.dumps({ "type": "match", "data": { "path": {"text": "config.json"}, "line_number": 3, "submatches": [{"match": {"text": "data"}}]} }) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["config.json"] = JSON_SAMPLE_CODE_1
    expected_block = JSON_LINES_1; expected_start_0idx = 0; expected_end_0idx = len(expected_block) - 1
    with patch.object(rgc_lib, 'extract_json_block', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["data", "config.json", "--format", "json"], capsys)
    assert code == 0, f"CLI Error: {err}"
    try:
        json_output = json.loads(out); assert isinstance(json_output, list); assert len(json_output) == 1
        result = json_output[0]; assert result["status"] == "success"; assert result["file_path"] == "config.json"
        assert result["block_start_line"] == 1; assert result["block_end_line"] == 5
        assert result["language_type"] == "json"
        assert any('"name": "example"' in line for line in result["block"])
        assert "data" in result["texts_highlighted_in_block"]
    except (json.JSONDecodeError, AssertionError) as e: pytest.fail(f"JSON/Assert Error: {e}\nOut:\n{out}")

def test_cli_stats_output_format(mock_rg_subprocess, mock_file_content, capsys):
    rg_output = [
        {"type": "match", "data": {"path": {"text": "file1.py"}, "line_number": 1, "submatches": [{"match": {"text": "term1"}}]}},
        {"type": "match", "data": {"path": {"text": "file2.c"}, "line_number": 2, "submatches": [{"match": {"text": "term2"}}]}},
        {"type": "match", "data": {"path": {"text": "file1.py"}, "line_number": 3, "submatches": [{"match": {"text": "term3"}}]}} ]
    mock_rg_subprocess.stdout_val = "\n".join(json.dumps(m) for m in rg_output) + "\n"
    mock_file_content["file1.py"] = "term1 = 1\n#...\nterm3 = 3"
    mock_file_content["file2.c"] = "//...\nint term2 = 2;"
    # Ensure mocks cause successful extraction for stats
    with patch.object(rgc_lib, 'extract_python_block_ast', side_effect=[(["term1 = 1\n"], 0, 0), (["term3 = 3\n"], 2, 2)]), \
         patch.object(rgc_lib, 'extract_brace_block', return_value=(["int term2 = 2;\n"], 1, 1)):
        out, err, code = run_cli_main_with_args(["term", ".", "--stats"], capsys)
    assert code == 0; assert "Run Statistics" in out
    assert re.search(r"Total Ripgrep Matches Found:\s*3", out), f"Stat mismatch: Total RG Matches\n{out}" # <<< CORRECTED
    assert re.search(r"Unique Code Blocks Processed:\s*2", out)
    assert re.search(r"Blocks Successfully Extracted:\s*2", out)
    assert re.search(r"Fell Back to Context View:\s*0", out) # Should be 0 if mocks lead to extraction

def test_cli_line_numbers(mock_rg_subprocess, mock_file_content, capsys):
    rg_json_output_line = json.dumps({"type": "match", "data": {"path": {"text": "ln.py"}, "line_number": 2, "submatches": [{"match": {"text": "b"}}]}}) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["ln.py"] = "a=1 # line 1\nb=2 # line 2\nc=3 # line 3"
    with patch.object(rgc_lib, 'extract_python_block_ast', return_value=(["a=1 # line 1\n", "b=2 # line 2\n"], 0, 1)):
         out, err, code = run_cli_main_with_args(["b", "ln.py", "--line-numbers"], capsys)
    assert code == 0
    assert "Fallback: Context" not in out, f"Should have printed block, not fallback.\nOutput:\n{out}"
    assert re.search(r"^\s*1\s*\|\s*a=1", out, re.MULTILINE), f"Line num 1 wrong.\nOut:\n{out}" # Check from start of line
    assert re.search(r"^\s*2\s*\|\s*.*\bb\b", out, re.MULTILINE), f"Line num 2 wrong.\nOut:\n{out}"

def test_cli_ruby_extraction(mock_rg_subprocess, mock_file_content, capsys):
    rg_json_output_line = json.dumps({"type": "match", "data": {"path": {"text": "greeter.rb"}, "line_number": 7, "submatches": [{"match": {"text": "@name"}}]} }) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["greeter.rb"] = RUBY_SAMPLE_FOR_CLI
    expected_block = [(l + '\n') for l in RUBY_SAMPLE_FOR_CLI.splitlines()][5:8]; expected_start_0idx = 5; expected_end_0idx = 7
    with patch.object(rgc_lib, 'extract_ruby_block', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["@name", "greeter.rb"], capsys)
    assert code == 0; assert "╠══" in out
    assert re.search(r"File:.*?greeter\.rb:7", out); assert re.search(r"Highlight\(s\)\s*\(1\):.*?\"@name\"", out)
    assert "def greet" in out; assert re.search(r"\033\[1;31m@name\033\[0m", out)
    # Filter out separators and header for checking last content line
    content_lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("╠") and not l.startswith("╚") and not l.startswith(rgcb_cli.COLOR_STATS_KEY+"File:") and not l.startswith(rgcb_cli.COLOR_STATS_KEY+"Highlight(s):") and not l.startswith(rgcb_cli.COLOR_SEPARATOR_FANCY+"─")]
    assert content_lines[-1].startswith("end"), f"Last content line was '{content_lines[-1]}'\nBlock lines:\n{content_lines}"

def test_cli_lua_extraction(mock_rg_subprocess, mock_file_content, capsys):
    rg_json_output_line = json.dumps({"type": "match", "data": {"path": {"text": "math.lua"}, "line_number": 5, "submatches": [{"match": {"text": "product"}}]} }) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["math.lua"] = LUA_SAMPLE_FOR_CLI
    expected_block = [(l + '\n') for l in LUA_SAMPLE_FOR_CLI.splitlines()][2:7]; expected_start_0idx = 2; expected_end_0idx = 6
    with patch.object(rgc_lib, 'extract_lua_block', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["product", "math.lua"], capsys)
    assert code == 0; assert "╠══" in out
    assert re.search(r"File:.*?math\.lua:5", out); assert re.search(r"Highlight\(s\)\s*\(1\):.*?\"product\"", out)
    assert "function M.calculate" in out; assert re.search(r"local \033\[1;31mproduct\033\[0m", out)
    content_lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("╠") and not l.startswith("╚") and not l.startswith(rgcb_cli.COLOR_STATS_KEY+"File:") and not l.startswith(rgcb_cli.COLOR_STATS_KEY+"Highlight(s):") and not l.startswith(rgcb_cli.COLOR_SEPARATOR_FANCY+"─")]
    assert content_lines[-1] == "end", f"Last content line was '{content_lines[-1]}'"

def test_cli_include_ext_args(mock_rg_subprocess, capsys):
    mock_rg_subprocess.stdout_val = ""; run_cli_main_with_args(["p", ".", "--include-ext", "py", "-I", "md"], capsys)
    cmd = mock_rg_subprocess.called_cmd; assert cmd is not None
    assert "--type-add" in cmd; assert "rgcbinclude0:*.py" in cmd; assert "-t" in cmd; assert "rgcbinclude0" in cmd
    assert "rgcbinclude1:*.md" in cmd; assert "rgcbinclude1" in cmd

def test_cli_exclude_path_args(mock_rg_subprocess, capsys):
    mock_rg_subprocess.stdout_val = ""; run_cli_main_with_args(["p", ".", "-X", "*/build/*", "--exclude-path=*.log"], capsys)
    cmd = mock_rg_subprocess.called_cmd; assert cmd is not None
    assert "--glob" in cmd; assert "!*/build/*" in cmd; assert "!*.log" in cmd

def test_cli_rg_args_passthrough(mock_rg_subprocess, capsys):
    mock_rg_subprocess.stdout_val = ""; run_cli_main_with_args(["p", ".", "--rg-args", "--hidden -i -C 2 --fixed-strings"], capsys)
    cmd = mock_rg_subprocess.called_cmd; assert cmd is not None
    assert "--hidden" in cmd; assert "-i" in cmd; assert "-C" in cmd; assert "2" in cmd
    assert "--fixed-strings" in cmd; assert "rg" == cmd[0]; assert "p" in cmd; assert "." in cmd

def test_cli_max_block_lines_truncation(mock_rg_subprocess, mock_file_content, capsys):
    rg_json_output = json.dumps({"type": "match", "data": {"path": {"text": "large.py"}, "line_number": 3, "submatches": [{"match": {"text": "hit"}}]}}) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output
    long_code = "def func():\n  l2\n  hit\n  l4\n  l5\n  l6\npass # line 7" # 7 lines
    mock_file_content["large.py"] = long_code
    block = [(l + '\n') for l in long_code.splitlines()]
    with patch.object(rgc_lib, 'extract_python_block_ast', return_value=(block, 0, 6)):
        out, err, code = run_cli_main_with_args(["hit", "large.py", "-M", "4"], capsys)
    assert code == 0; assert "def func()" in out; assert "l2" in out
    # Max 4 -> show_start=ceil((4-1)/2)=2, show_end=floor((4-1)/2)=1. total shown from orig = 2+1 = 3.
    # num_original_block_lines_not_shown = 7 - (2+1) = 4
    assert re.search(r"\.\.\. \(4 lines truncated\) \.\.\.", out), f"Truncation msg mismatch.\nOut:\n{out}"
    assert "pass # line 7" in out; assert "hit" not in out

def test_cli_separator_styles(mock_rg_subprocess, mock_file_content, capsys):
    rg_json_output = json.dumps({"type": "match", "data": {"path": {"text": "sep.txt"}, "line_number": 1, "submatches": [{"match": {"text": "a"}}]}}) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output
    mock_file_content["sep.txt"] = "a = 1"
    with patch.object(rgc_lib, 'get_language_type_from_filename', return_value=("unknown", "txt")), \
         patch.object(rgc_lib, 'EXTRACTOR_DISPATCH_MAP', {}): # Force fallback
        out_fancy, _, code_f = run_cli_main_with_args(["a", "sep.txt", "--sep-style", "fancy"], capsys); assert code_f==0
        assert "╠" in out_fancy and "╣" in out_fancy
        out_simple, _, code_s = run_cli_main_with_args(["a", "sep.txt", "--sep-style", "simple"], capsys); assert code_s==0
        assert rgcb_cli.COLOR_SEPARATOR_SIMPLE + "-"*44 + rgcb_cli.RESET_COLOR_ANSI in out_simple; assert "╠" not in out_simple
        out_none, _, code_n = run_cli_main_with_args(["a", "sep.txt", "--sep-style", "none"], capsys); assert code_n==0
        assert "------" not in out_none; assert "╠" not in out_none
        assert re.search(r"File:.*?sep\.txt:1", out_none) # Check header still prints
        assert re.search(r"Highlight\(s\)\s*\(1\):.*?\"a\"", out_none)
        assert re.search(r"Fallback: Context", out_none)
