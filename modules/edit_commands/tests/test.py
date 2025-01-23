import subprocess

def test_vim_substitution():
    cmd = ["python3", "replace_last_command.py", "-v", "s/foo/bar/g", "-n"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert "bar" in result.stdout

def test_parallel_execution():
    cmd = ["python3", "replace_last_command.py", "-o", "[0,1]", "-p", "-n"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert "Running:" in result.stdout

if __name__ == "__main__":
    test_vim_substitution()
    test_parallel_execution()
    print("All tests passed.")
