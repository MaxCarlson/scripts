import shutil
from pathlib import Path
from script_manager.utils import validate_python_name
from script_manager.requirements import extract_imports
from script_manager.tests import setup_test_environment

def create_module_structure(module_path, module_name, force, no_requirements, no_test, test_source):
    """Creates or updates a Python module at the given path."""
    setup_py = module_path / "setup.py"
    init_py = module_path / module_name / "__init__.py"
    requirements_txt = module_path / "requirements.txt"

    validate_python_name(module_name)

    (module_path / module_name).mkdir(parents=True, exist_ok=True)

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

    if requirements_txt.exists() and force:
        requirements_txt.unlink()

    if not no_requirements:
        source_files = list(module_path.glob(f"{module_name}/*.py"))
        requirements = extract_imports(source_files)
        requirements_txt.write_text("\n".join(requirements))

    if not no_test:
        setup_test_environment(module_path, test_source)
