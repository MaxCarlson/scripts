import subprocess
import os
import pytest

SCRIPT = "./run_pattern.py"  # Adjust if needed

@pytest.fixture(scope="module")
def create_test_files():
    """Create sample test files."""
    filenames = ["test1.txt", "test2.txt", "test3.log"]
    contents = ["Hello", "World", "Error: Something went wrong"]
    
    for name, content in zip(filenames, contents):
        with open(name, "w") as f:
            f.write(content)
    yield filenames
    for name in filenames:
        os.remove(name)

def test_cat_basic(create_test_files):
    """Test cat command with pattern."""
    result = subprocess.run([SCRIPT, "cat", "*.txt"], capture_output=True, text=True)
    assert "Hello" in result.stdout
    assert "World" in result.stdout

def test_grep_error(create_test_files):
    """Test grep on .log files."""
    result = subprocess.run([SCRIPT, "grep", "Error", "*.log"], capture_output=True, text=True)
    assert "Error: Something went wrong" in result.stdout

def test_no_pattern_match():
    """Ensure graceful handling of no matches."""
    result = subprocess.run([SCRIPT, "cat", "*.xyz"], capture_output=True, text=True)
    assert "No files matching" in result.stderr or result.returncode != 0

def test_flags_before_and_after(create_test_files):
    """Ensure pre/post flags are preserved."""
    result = subprocess.run([SCRIPT, "grep", "-i", "hello", "*.txt", "-n"], capture_output=True, text=True)
    assert "1:Hello" in result.stdout

def test_fd_fallback(create_test_files):
    """Check if fd is used when available."""
    fd_path = subprocess.run(["which", "fd"], capture_output=True, text=True)
    if fd_path.stdout.strip():
        result = subprocess.run([SCRIPT, "cat", "*.txt"], capture_output=True, text=True)
        assert "Hello" in result.stdout

def test_find_fallback(create_test_files, monkeypatch):
    """Ensure find is used if fd is missing."""
    monkeypatch.setenv("PATH", "/tmp")  # Remove fd from PATH
    result = subprocess.run([SCRIPT, "cat", "*.txt"], capture_output=True, text=True)
    assert "Hello" in result.stdout
