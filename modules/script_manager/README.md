# Script Manager

A Python utility module for managing Python scripts and modules. It helps automate tasks like creating Python modules, making scripts executable, and managing dependencies.

---

## **Features**
1. **Executable Script Management**:
   - Add Python scripts to a bin directory for easy execution.
   - Make scripts executable.
   - Optionally create symlinks instead of copying scripts.
   - Automatically install script dependencies (supports Conda and pip).

2. **Module Management**:
   - Create Python modules with `setup.py`, `__init__.py`, and `requirements.txt`.
   - Add test setups for modules.
   - Support for virtual environments (`venv`) and Conda.

3. **Dependency Management**:
   - Extract dependencies from scripts/modules and generate `requirements.txt`.
   - Install dependencies in the appropriate environment.

---

## **Installation**
Clone the repository and install the package:
```sh
git clone https://github.com/your-repo/script_manager.git
cd script_manager
pip install .
