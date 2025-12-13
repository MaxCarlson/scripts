# How to Create, Install, and Upload Python Modules

This guide explains how to:
1. Create a Python module from your script directory.
2. Install the module locally for development or testing.
3. Upload the module to PyPI for public or private distribution.

---

## 1. Directory Structure

Organize your project as follows:

    my_module/
    │
    ├── my_module/               # The main package directory
    │   ├── __init__.py          # Makes this directory a package
    │   ├── my_script.py         # Your Python script(s)
    │
    ├── setup.py                 # Configuration for packaging
    ├── README.md                # Documentation for the package (this file)
    ├── LICENSE                  # (Optional) License file for your project
    └── MANIFEST.in              # (Optional) Include additional non-code files

---

## 2. Creating the Module

### **a. Package Directory**
- Rename the folder containing your scripts (e.g., `DebugUtils`) to a Pythonic name (e.g., `debug_utils`).
- Add an `__init__.py` file inside the package directory to expose functionality. For example:

    ```python
    # debug_utils/__init__.py
    from .my_script import my_function
    ```

### **b. Setup Configuration**
Create a `setup.py` file in the root directory:

    ```python
    from setuptools import setup, find_packages

    setup(
        name="debug_utils",              # Replace with your module's name
        version="1.0.0",                 # Version of the module
        description="A utility for debugging in Python.",  # Short description
        long_description=open("README.md").read(),         # Load README as long description
        long_description_content_type="text/markdown",     # Markdown format for README
        author="Your Name",              # Replace with your name
        author_email="your.email@example.com",  # Replace with your email
        url="https://github.com/your-repo/debug_utils",  # GitHub or project URL
        packages=find_packages(),        # Automatically find package directories
        python_requires=">=3.6",         # Minimum Python version
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
        ],
    )
    ```

---

## 3. Installing Locally

### **Install the Module**
To install the module locally, navigate to the directory containing `setup.py` and run:

    ```bash
    pip install .
    ```

This installs the module into your Python environment. You can now use it like any other Python module:

    ```python
    from debug_utils import write_debug

    write_debug("This is a debug message.", channel="Debug")
    ```

### **Editable Installation**
For active development, use an editable installation so changes reflect immediately:

    ```bash
    pip install -e .
    ```

---

## 4. Preparing the Package for Distribution

### **Building the Package**
To create distributable files (e.g., `.whl` and `.tar.gz`), run:

    ```bash
    python setup.py sdist bdist_wheel
    ```

This creates a `dist/` folder containing:
- Source archive: `debug_utils-1.0.0.tar.gz`
- Wheel file: `debug_utils-1.0.0-py3-none-any.whl`

---

## 5. Uploading to PyPI

### **Register on PyPI**
1. Create an account on [PyPI](https://pypi.org/).
2. Install `twine`, the tool for uploading packages:
    ```bash
    pip install twine
    ```

### **Upload Your Package**
1. Use `twine` to upload your package to PyPI:
    ```bash
    twine upload dist/*
    ```

2. Follow the prompts to enter your PyPI username and password.

### **Test Installation from PyPI**
Once uploaded, verify the package is available by installing it:

    ```bash
    pip install debug_utils
    ```

---

## 6. Optional: Including Additional Files

To include non-Python files (e.g., `README.md` or configuration files) in your package, create a `MANIFEST.in` file:

    ```plaintext
    include README.md
    include LICENSE
    ```

---

## 7. Notes and Best Practices

- Use a **virtual environment** to manage dependencies:
    ```bash
    python -m venv venv
    source venv/bin/activate  # Or `venv\Scripts\activate` on Windows
    ```
- Follow [PEP 8](https://peps.python.org/pep-0008/) for consistent code style.
- For private distributions, consider hosting your own PyPI server or using a private repository like [TestPyPI](https://test.pypi.org/).

---

## Cross-Platform Copier/Move Handler (dlmanager v0.2.0)

Our `dlmanager` module now ships a fully cross-platform copy/move orchestrator that automatically selects the best available transfer method (rsync → rclone → scp → native Python/robocopy) for Windows 11, WSL2, and Termux. Highlights:

- **TermDash dashboard**: `dlmanager manager --ui-mode termdash` starts a live, colorized progress board with per-job bars, ETA, and throughput. `--ui-mode plain` falls back to a simple table when curses isn’t available.
- **Smart heuristics**: `dlmanager add` inspects your target platform and available binaries to pick the most resilient worker. New `native` worker streams detailed stats for local copies/moves and respects `--dry-run/-n`, `--replace/-r`, and `--delete-source/-x`.
- **Verbosity controls**: `--verbosity quiet|info|stats|trace` tunes both the manager console and worker chatter; `--confirm/-y` guards destructive operations as required by project safety guidelines.
- **Structured workers**: `rsync`, `rclone`, `scp`, and the new native worker emit normalized progress telemetry (bytes, files, speed, ETA) that feeds both the TUI and log subscribers.
- **Tests**: `pytest modules/dlmanager/tests -q` now covers the auto-selection logic, size parsers, rsync/ native worker behavior, and helpers (temp dirs can be redirected with `set TMP=C:\path\to\.tmp` on Windows when needed).

Usage example:

```bash
# Launch manager with the new dashboard
dlmanager manager --ui-mode termdash

# Queue a copy that auto-selects the best method with rich stats
dlmanager add -s ~/Downloads -d mcarls@w11box -p /mnt/data/backups -m auto -B stats
```

See `modules/dlmanager/guide.md` for architecture notes, worker diagrams, and troubleshooting tips.
