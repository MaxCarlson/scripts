# tests/test_rgcodeblock_cli.py
import pytest
import subprocess
import json
from unittest.mock import patch, mock_open, MagicMock
import os
import sys
from collections import defaultdict
import re # For checking output highlights
import argparse # <<< IMPORT ADDED

# Import the CLI script module
import rgcodeblock_cli as rgcb_cli
# Import the library module for mocking its functions
import rgcodeblock_lib as rgc_lib

# --- Fixtures ---

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
    """Mocks open() to provide specific file content."""
    files_dict = {}
    original_open = open

    def side_effect_open(filename, mode='r', *args, **kwargs):
        filename_str = str(filename)
        if filename_str in files_dict and 'r' in mode:
            content = files_dict[filename_str]
            m_open = mock_open(read_data=content)
            mock_file_handle = m_open(filename_str, mode, *args, **kwargs)
            mock_file_handle.readlines.return_value = [(line + '\n') for line in content.splitlines()]
            mock_file_handle.read.return_value = content
            return mock_file_handle
        else:
            # Fallback for files not mocked (like maybe pytest internals)
            return original_open(filename_str, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", side_effect_open)
    return files_dict # Return the dictionary so tests can populate it


# Helper to run main for the CLI script
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

    # Store args globally (workaround for print_statistics needing sep_style)
    # Parse args briefly to get sep_style or use default
    temp_parser = argparse.ArgumentParser(add_help=False) # <<< argparse IMPORTED NOW
    temp_parser.add_argument("--sep-style", default="fancy")
    # Use parse_known_args to ignore arguments not defined in this temp parser
    parsed_args, _ = temp_parser.parse_known_args(args_list)
    # Ensure the global exists before assigning to its attribute
    if not hasattr(rgcb_cli, 'args_for_main_thread'):
        rgcb_cli.args_for_main_thread = MagicMock()
    rgcb_cli.args_for_main_thread.sep_style = parsed_args.sep_style

    with patch.object(sys, 'argv', ['rgcodeblock_cli.py'] + args_list):
        exit_code = None
        try:
            rgcb_cli.main()
            exit_code = 0 # Assume success if no SystemExit
        except SystemExit as e:
            exit_code = e.code
    captured = capsys.readouterr()
    return captured.out, captured.err, exit_code

# --- Test Data ---

PYTHON_SAMPLE_CODE_1 = """# Comment line 1
class MyClass: # Line 2 (0-idx: 1)
    def __init__(self, value): # Line 3 (0-idx: 2)
        self.value = value # Line 4 (0-idx: 3)

    def another_method(self): # Line 6 (0-idx: 5)
        pass # Line 7 (0-idx: 6)"""

JSON_SAMPLE_CODE_1 = """{
  "name": "example",
  "data": [1, 2, 3],
  "details": { "id": 101 }
}""" # Ends line 5 (idx 4)

RUBY_SAMPLE_FOR_CLI = """
class Greeter
  def initialize(name) # line 2 (idx 1)
    @name = name
  end

  def greet # line 6 (idx 5)
    puts "Hello, #{@name}!" # line 7 (idx 6) - target match
  end # line 8 (idx 7)
end
"""

LUA_SAMPLE_FOR_CLI = """
local M = {}

function M.calculate(a, b) -- line 3 (idx 2)
  local sum = a + b -- line 4 (idx 3)
  local product = a * b -- line 5 (idx 4) - target match
  return sum, product -- line 6 (idx 5)
end -- line 7 (idx 6)

return M
"""


# --- CLI Tests ---

def test_list_languages_cli(capsys):
    """Test --list-languages flag."""
    out, err, code = run_cli_main_with_args(["--list-languages"], capsys)
    assert code == 0, f"Expected exit 0, got {code}. Err: {err}"
    assert "Supported Language Types" in out
    assert "python" in out
    assert ".py" in out
    assert "brace" in out
    assert ".java" in out

def test_no_matches_found_cli(mock_rg_subprocess, capsys):
    """Test scenario where rg finds no matches."""
    mock_rg_subprocess.stdout_val = ""
    mock_rg_subprocess.returncode_val = 1 # rg returns 1 for no matches
    out, err, code = run_cli_main_with_args(["nonexistentpattern", "."], capsys)
    assert code == 0 # Script should exit 0 if rg finding no matches is the only outcome
    assert out == "" # No output expected from script itself

def test_basic_match_and_extraction_text_format_cli(mock_rg_subprocess, mock_file_content, capsys):
    """Test a basic match, extraction, and text output via CLI."""
    rg_json_output = json.dumps({
        "type": "match",
        "data": { "path": {"text": "test.py"}, "line_number": 4, "submatches": [{"match": {"text": "__init__"}}]}
    }) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output
    mock_file_content["test.py"] = PYTHON_SAMPLE_CODE_1 # Use fixture to set content

    # Mock the library's extractor
    expected_block = [(l + '\n') for l in PYTHON_SAMPLE_CODE_1.splitlines()][2:5] # __init__ method
    expected_start_0idx = 2
    expected_end_0idx = 4
    with patch.object(rgc_lib, 'extract_python_block_ast', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["__init__", "test.py"], capsys)

    assert code == 0
    assert "Match Found" in out
    assert "File: test.py:4" in out
    assert "Highlight(s) (1): \"__init__\"" in out
    assert re.search(r"def .*\033\[1;31m__init__\033\[0m.*:", out) # Highlighted
    assert "self.value = value" in out # Last line of block

def test_json_format_output_cli(mock_rg_subprocess, mock_file_content, capsys):
    """Test --format json output from the CLI script."""
    rg_json_output_line = json.dumps({
        "type": "match",
        "data": { "path": {"text": "config.json"}, "line_number": 3, "submatches": [{"match": {"text": "data"}}]}
    }) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["config.json"] = JSON_SAMPLE_CODE_1

    expected_block = [(l + '\n') for l in JSON_SAMPLE_CODE_1.splitlines()] # Assume whole file block found
    expected_start_0idx = 0
    expected_end_0idx = len(expected_block) - 1

    with patch.object(rgc_lib, 'extract_json_block', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["data", "config.json", "--format", "json"], capsys)

    assert code == 0, f"CLI exited with code {code}. Error: {err}"
    try:
        json_output = json.loads(out)
        assert isinstance(json_output, list)
        assert len(json_output) == 1
        result = json_output[0]
        assert result["status"] == "success"
        assert result["file_path"] == "config.json"
        assert result["block_start_line"] == expected_start_0idx + 1 # 1
        assert result["block_end_line"] == expected_end_0idx + 1 # 5
        assert result["language_type"] == "json"
        assert '"name": "example"' in result["block"]
        assert "data" in result["texts_highlighted_in_block"]
    except json.JSONDecodeError: pytest.fail(f"Output was not valid JSON:\n{out}")
    except Exception as e: pytest.fail(f"Error processing JSON output or assertion: {e}\nOutput:\n{out}")


def test_cli_stats_output_format(mock_rg_subprocess, mock_file_content, capsys):
    """Test the format of the --stats output in the CLI."""
    rg_output = [
        {"type": "match", "data": {"path": {"text": "file1.py"}, "line_number": 1, "submatches": [{"match": {"text": "term1"}}]}},
        {"type": "match", "data": {"path": {"text": "file2.c"}, "line_number": 2, "submatches": [{"match": {"text": "term2"}}]}}, # Adjusted line num
        {"type": "match", "data": {"path": {"text": "file1.py"}, "line_number": 3, "submatches": [{"match": {"text": "term3"}}]}}
    ]
    mock_rg_subprocess.stdout_val = "\n".join(json.dumps(m) for m in rg_output) + "\n"
    mock_file_content["file1.py"] = "term1 = 1\n#...\nterm3 = 3"
    mock_file_content["file2.c"] = "//...\nint term2 = 2;"

    # Mock extractors to succeed simply, returning single lines
    # Note: Ensure the mock return value matches the expected tuple format (block_lines, start_0idx, end_0idx)
    with patch.object(rgc_lib, 'extract_python_block_ast', side_effect=[(["term1 = 1\n"], 0, 0), (["term3 = 3\n"], 2, 2)]), \
         patch.object(rgc_lib, 'extract_brace_block', return_value=(["int term2 = 2;\n"], 1, 1)):
        out, err, code = run_cli_main_with_args(["term", ".", "--stats"], capsys)

    assert code == 0
    # Stats are printed after normal output.
    assert "Run Statistics" in out
    assert "Total Ripgrep Matches Found: 3" in out
    assert "Unique Code Blocks Processed: 2" in out # One for python (file1), one for brace (file2)
    assert "Unique Files with Matches: 2" in out
    assert "python: 1" in out # Block count per lang (only count unique blocks)
    assert "brace: 1" in out
    assert ".py: 1" in out     # File count per ext
    assert ".c: 1" in out
    assert "Blocks Successfully Extracted: 2" in out
    assert "Average Original Extracted Block Length (lines): 1.00" in out

def test_cli_line_numbers(mock_rg_subprocess, mock_file_content, capsys):
    """Test --line-numbers flag in CLI output."""
    rg_json_output_line = json.dumps({"type": "match", "data": {"path": {"text": "ln.py"}, "line_number": 2, "submatches": [{"match": {"text": "b"}}]}}) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["ln.py"] = "a=1 # line 1\nb=2 # line 2\nc=3 # line 3"

    # Mock extractor returns lines 1-2 (0-indexed), original lines 1, 2
    with patch.object(rgc_lib, 'extract_python_block_ast', return_value=(["a=1 # line 1\n", "b=2 # line 2\n"], 0, 1)):
         out, err, code = run_cli_main_with_args(["b", "ln.py", "--line-numbers"], capsys)

    assert code == 0
    # Use regex to be more robust against minor spacing variations and ANSI codes
    assert re.search(r"\s+1\s*\| a=1", out), "Line number 1 missing or incorrect"
    assert re.search(r"\s+2\s*\| b=2", out), "Line number 2 missing or incorrect"

def test_cli_ruby_extraction(mock_rg_subprocess, mock_file_content, capsys):
    """Test CLI output for a Ruby file match."""
    rg_json_output_line = json.dumps({
        "type": "match", "data": {"path": {"text": "greeter.rb"}, "line_number": 7, "submatches": [{"match": {"text": "@name"}}]}
    }) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["greeter.rb"] = RUBY_SAMPLE_FOR_CLI

    expected_block = [(l + '\n') for l in RUBY_SAMPLE_FOR_CLI.splitlines()][5:8] # 'greet' method
    expected_start_0idx = 5
    expected_end_0idx = 7
    with patch.object(rgc_lib, 'extract_ruby_block', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["@name", "greeter.rb"], capsys)

    assert code == 0
    assert "Match Found" in out
    assert "File: greeter.rb:7" in out
    assert "Highlight(s) (1): \"@name\"" in out
    assert "def greet" in out
    assert re.search(r"puts.*#{@name}.*", out)
    assert re.search(r"\033\[1;31m@name\033\[0m", out) # Highlight check
    output_lines = [l for l in out.split('Match Found')[-1].splitlines() if l.strip()]
    # The last relevant line of the block output should end with 'end' after stripping whitespace
    assert output_lines[-1].strip() == "end" # More robust check

def test_cli_lua_extraction(mock_rg_subprocess, mock_file_content, capsys):
    """Test CLI output for a Lua file match."""
    rg_json_output_line = json.dumps({
        "type": "match", "data": {"path": {"text": "math.lua"}, "line_number": 5, "submatches": [{"match": {"text": "product"}}]}
    }) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output_line
    mock_file_content["math.lua"] = LUA_SAMPLE_FOR_CLI

    expected_block = [(l + '\n') for l in LUA_SAMPLE_FOR_CLI.splitlines()][2:7] # 'calculate' function
    expected_start_0idx = 2
    expected_end_0idx = 6
    with patch.object(rgc_lib, 'extract_lua_block', return_value=(expected_block, expected_start_0idx, expected_end_0idx)):
        out, err, code = run_cli_main_with_args(["product", "math.lua"], capsys)

    assert code == 0
    assert "Match Found" in out
    assert "File: math.lua:5" in out
    assert "Highlight(s) (1): \"product\"" in out
    assert "function M.calculate" in out
    assert re.search(r"local \033\[1;31mproduct\033\[0m", out) # Highlight check
    assert "return sum, product" in out
    output_lines = [l for l in out.split('Match Found')[-1].splitlines() if l.strip()]
    assert output_lines[-1].strip() == "end"


def test_cli_include_ext_args(mock_rg_subprocess, capsys):
    """Test --include-ext passes correct args to rg."""
    mock_rg_subprocess.stdout_val = ""
    run_cli_main_with_args(["p", ".", "--include-ext", "py", "-I", "md"], capsys)
    assert mock_rg_subprocess.called_cmd is not None
    cmd = mock_rg_subprocess.called_cmd
    assert "--type-add" in cmd
    assert "rgcbinclude0:*.py" in cmd # Check generated type def name
    assert "-t" in cmd
    assert "rgcbinclude0" in cmd # Check usage of type
    assert "rgcbinclude1:*.md" in cmd
    assert "rgcbinclude1" in cmd

def test_cli_exclude_path_args(mock_rg_subprocess, capsys):
    """Test --exclude-path passes correct globs to rg."""
    mock_rg_subprocess.stdout_val = ""
    run_cli_main_with_args(["p", ".", "-X", "*/build/*", "--exclude-path=*.log"], capsys)
    assert mock_rg_subprocess.called_cmd is not None
    cmd = mock_rg_subprocess.called_cmd
    assert "--glob" in cmd
    # Check presence of exclusion globs (order might vary depending on list append)
    assert "!*/build/*" in cmd
    assert "!*.log" in cmd

def test_cli_rg_args_passthrough(mock_rg_subprocess, capsys):
    """Test --rg-args passes through to rg command."""
    mock_rg_subprocess.stdout_val = ""
    run_cli_main_with_args(["p", ".", "--rg-args", "--hidden -i -C 2 --fixed-strings"], capsys)
    cmd = mock_rg_subprocess.called_cmd
    assert cmd is not None
    assert "--hidden" in cmd
    assert "-i" in cmd
    assert "-C" in cmd
    assert "2" in cmd
    assert "--fixed-strings" in cmd
    assert "rg" == cmd[0]
    # Pattern and path should still be appended if not overridden by complex rg-args
    assert "p" in cmd
    assert "." in cmd

def test_cli_max_block_lines_truncation(mock_rg_subprocess, mock_file_content, capsys):
    """Test --max-block-lines truncation in CLI output."""
    rg_json_output = json.dumps({"type": "match", "data": {"path": {"text": "large.py"}, "line_number": 3, "submatches": [{"match": {"text": "hit"}}]}}) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output
    long_code = "def func():\n  l2\n  hit\n  l4\n  l5\n  l6\npass # line 7"
    mock_file_content["large.py"] = long_code

    block = [(l + '\n') for l in long_code.splitlines()] # 7 lines
    with patch.object(rgc_lib, 'extract_python_block_ast', return_value=(block, 0, 6)):
        out, err, code = run_cli_main_with_args(["hit", "large.py", "-M", "4"], capsys) # Max 4 lines

    assert code == 0
    # Max 4 lines -> half = 2. Show lines 0,1 and lines 5,6 (0-based from block)
    assert "def func()" in out # block[0]
    assert "l2" in out       # block[1]
    # Ellipsis hides lines: hit, l4, l5 (3 lines)
    assert "... (3 lines truncated) ..." in out
    assert "l6" in out       # block[5]
    assert "pass # line 7" in out # block[6]
    assert "hit" not in out # Should be hidden by ellipsis

def test_cli_separator_styles(mock_rg_subprocess, mock_file_content, capsys):
    """Test --sep-style argument in CLI."""
    rg_json_output = json.dumps({"type": "match", "data": {"path": {"text": "sep.txt"}, "line_number": 1, "submatches": [{"match": {"text": "a"}}]}}) + "\n"
    mock_rg_subprocess.stdout_val = rg_json_output
    mock_file_content["sep.txt"] = "a = 1"

    # Mock extractor (lang doesn't matter, force fallback)
    with patch.object(rgc_lib, 'get_language_type_from_filename', return_value=("unknown", "txt")), \
         patch.object(rgc_lib, 'EXTRACTOR_DISPATCH_MAP', {}): # No extractor -> fallback

        out_fancy, _, _ = run_cli_main_with_args(["a", "sep.txt", "--sep-style", "fancy"], capsys)
        assert "╠" in out_fancy and "╣" in out_fancy # Fancy separators

        out_simple, _, _ = run_cli_main_with_args(["a", "sep.txt", "--sep-style", "simple"], capsys)
        assert rgcb_cli.COLOR_SEPARATOR_SIMPLE + "-"*44 + rgcb_cli.RESET_COLOR_ANSI in out_simple
        assert "╠" not in out_simple

        out_none, _, _ = run_cli_main_with_args(["a", "sep.txt", "--sep-style", "none"], capsys)
        # With style none, there should be no fancy/simple line separators printed
        assert "------" not in out_none
        assert "╠" not in out_none
        # The content header should still appear, just without the fancy lines
        assert "File: sep.txt:1" in out_none
