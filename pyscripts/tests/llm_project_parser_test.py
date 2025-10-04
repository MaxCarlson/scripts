import sys
import os
import pytest
from pathlib import Path

# Add script's parent directory to path to allow importing
script_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(script_dir))

# Now import the functions from the script
from llm_project_parser import extract_files_from_lines, write_file

# Sample input for the "new" format (e.g., imageshrink.txt)
NEW_FORMAT_INPUT = """
First file is here:
imgshrink/__init__.py
```python
#!/usr/bin/env python3
"""
__version__ = "0.2.0"
```

And the main file:
imgshrink/__main__.py
```python
#!/usr/bin/env python3
from .cli import main

if __name__ == "__main__":
    main()
```

A file with no language hint.
README.md
```
This is a test.
```
"""

# Sample input for the "original" format
ORIGINAL_FORMAT_INPUT = """
Here is the project structure.

---
### 1. src/main.py
This is the main application file.
```python
print("Hello from main")
```
---
### 2. `config.json`
And here is the configuration.
```json
{
    "key": "value"
}
```
---
A random code block without a file header.
```
ignored content
```
"""

@pytest.fixture
def parser_setup(tmp_path):
    """Fixture to set up a temporary directory and input files for tests."""
    input_new = tmp_path / "new_format.txt"
    input_new.write_text(NEW_FORMAT_INPUT, encoding="utf-8")

    input_orig = tmp_path / "orig_format.txt"
    input_orig.write_text(ORIGINAL_FORMAT_INPUT, encoding="utf-8")

    return {
        "new": input_new,
        "orig": input_orig,
        "output": tmp_path / "output",
    }

def test_extract_new_format(parser_setup):
    """Tests that the new format (filename on a line above code block) is parsed."""
    with open(parser_setup["new"], "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    files = extract_files_from_lines(lines)
    
    assert len(files) == 3
    filenames = [f[0] for f in files]
    assert "imgshrink/__init__.py" in filenames
    assert "imgshrink/__main__.py" in filenames
    assert "README.md" in filenames
    
    init_content = next(f[1] for f in files if f[0] == "imgshrink/__init__.py")
    assert '__version__ = "0.2.0"' in init_content

def test_extract_original_format(parser_setup):
    """Tests that the original format (e.g., '1. path/to/file.py') is still parsed."""
    with open(parser_setup["orig"], "r", encoding="utf-8") as f:
        lines = f.readlines()

    files = extract_files_from_lines(lines)
    
    assert len(files) == 2
    filenames = [f[0] for f in files]
    assert "src/main.py" in filenames
    assert "config.json" in filenames
    
    main_content = next(f[1] for f in files if f[0] == "src/main.py")
    assert 'print("Hello from main")' in main_content

def test_file_creation_and_paths(parser_setup):
    """Tests the end-to-end process of file creation and directory structure."""
    output_dir = parser_setup["output"]
    
    with open(parser_setup["new"], "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    files = extract_files_from_lines(lines)
    
    for filename, content in files:
        write_file(filename, content, str(output_dir), dry_run=False)
        
    # Check that files were created in the correct locations
    init_py = output_dir / "imgshrink" / "__init__.py"
    main_py = output_dir / "imgshrink" / "__main__.py"
    readme_md = output_dir / "README.md"
    
    assert init_py.exists()
    assert main_py.exists()
    assert readme_md.exists()
    
    assert '__version__ = "0.2.0"' in init_py.read_text(encoding="utf-8")
    assert "This is a test." in readme_md.read_text(encoding="utf-8")

def test_output_path_joining(tmp_path):
    """
    Tests the users specific request for output path handling.
    -o ../MyFolder and a file path of `MyFolder/myfile.txt` in the monofile
    should result in `../MyFolder/MyFolder/myfile.txt`.
    """
    output_arg = tmp_path / "MyFolder"
    file_path_from_mono = "MyFolder/myfile.txt"
    content = "hello world"
    
    write_file(file_path_from_mono, content, str(output_arg), dry_run=False)
    
    expected_file = output_arg / "MyFolder" / "myfile.txt"
    
    assert expected_file.exists()
    assert expected_file.read_text(encoding="utf-8") == content