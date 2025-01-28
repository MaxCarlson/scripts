import ast

setup_path = "modules/file_utils/setup.py"  # Change to the actual file path

with open(setup_path, "r", encoding="utf-8") as f:
    content = f.read()

tree = ast.parse(content)

setup_found = False
imports_setuptools = False

for node in ast.walk(tree):
    if isinstance(node, ast.Call) and hasattr(node.func, "id") and node.func.id == "setup":
        setup_found = True

    # Fix: Detect both "import setuptools" and "from setuptools import ..."
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.startswith("setuptools"):  # Match any "setuptools" import
                imports_setuptools = True

    elif isinstance(node, ast.ImportFrom):
        if node.module and node.module.startswith("setuptools"):  # Match "from setuptools import ..."
            imports_setuptools = True

print(f"Setup function found? {setup_found}")
print(f"Setuptools imported? {imports_setuptools}")
