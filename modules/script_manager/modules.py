import shutil
import ast
from pathlib import Path
from script_manager.utils import validate_python_name
from script_manager.requirements import extract_imports
from script_manager.tests import setup_test_environment

def extract_functions_from_file(file_path):
    """Extracts function names from a Python file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
        
        return [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    except Exception as e:
        print(f"⚠️ Skipping {file_path} due to error: {e}")
        return []

def generate_init_file(module_path, module_name, exclude_files=None, exclude_functions=None):
    """Generates or updates __init__.py by exporting all functions in the module."""
    exclude_files = set(exclude_files or [])
    exclude_functions = set(exclude_functions or [])

    module_dir = module_path / module_name
    init_file = module_dir / "__init__.py"
    exported_functions = []

    for py_file in module_dir.glob("*.py"):
        if py_file.name in exclude_files or py_file.name == "__init__.py":
            continue
        
        functions = extract_functions_from_file(py_file)
        exported_functions.extend([f for f in functions if f not in exclude_functions])

    with open(init_file, "w", encoding="utf-8") as f:
        if exported_functions:
            f.write(f"from .{module_name} import " + ", ".join(exported_functions) + "\n")
        else:
            f.write(f"# No functions to export\n")

    print(f"✅ Updated {init_file.name} with {len(exported_functions)} functions.")

def create_module_structure(module_path, module_name, force, no_requirements, no_test, test_source, exclude_files=None, exclude_functions=None):
    """Creates or updates a Python module at the given path."""
    setup_py = module_path / "setup.py"
    module_dir = module_path / module_name
    init_py = module_dir / "__init__.py"
    requirements_txt = module_path / "requirements.txt"

    validate_python_name(module_name)

    module_dir.mkdir(parents=True, exist_ok=True)

    if not setup_py.exists():
        setup_py.write_text(f"""from setuptools import setup, find_packages
setup(
    name="{module_name}",
    version="0.1",
    packages=find_packages(),
    install_requires=[],
)
""")

    if not init_py.exists():
        init_py.touch()

    print("📝 Generating __init__.py...")
    generate_init_file(module_path, module_name, exclude_files, exclude_functions)

    if requirements_txt.exists() and force:
        requirements_txt.unlink()

    if not no_requirements:
        source_files = list(module_dir.glob("*.py"))
        requirements = extract_imports(source_files)
        requirements_txt.write_text("\n".join(requirements))

    if not no_test:
        setup_test_environment(module_path, test_source)