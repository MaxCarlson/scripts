import os
import ast
import toml
import shutil
import argparse
from pathlib import Path

# Persistent cache for user-provided values
USER_FIELDS = {}

# Default field order for `--fields`
FIELD_ORDER = ["author", "author_email", "version", "description"]

def prompt_for_value(field_name, default=None):
    """Prompt once for missing values and store them for future use."""
    if field_name in USER_FIELDS:
        return USER_FIELDS[field_name]

    value = input(f"❓ Missing `{field_name}`. Enter value [{default}]: ").strip()
    if not value:
        value = default
    USER_FIELDS[field_name] = value  # Store for next missing case
    return value


def is_valid_setup_py(setup_path):
    """Checks if the file is a real package setup.py or just a random script."""
    try:
        with open(setup_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)

        setup_found = False
        imports_setuptools = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and hasattr(node.func, "id") and node.func.id == "setup":
                setup_found = True

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("setuptools"):
                        imports_setuptools = True

            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("setuptools"):
                    imports_setuptools = True

        return setup_found and imports_setuptools

    except Exception as e:
        print(f"⚠️ Error checking {setup_path}: {e}")
        return False


def parse_setup_py(setup_path):
    """Parses setup.py and extracts metadata as a dictionary."""
    setup_data = {
        "name": None,
        "version": None,
        "description": None,
        "author": None,
        "author_email": None,
        "dependencies": [],
        "packages": "find",
        "entry_points": {}
    }

    with open(setup_path, "r", encoding="utf-8") as f:
        setup_content = f.read()

    try:
        tree = ast.parse(setup_content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and hasattr(node.func, "id") and node.func.id == "setup":
                for keyword in node.keywords:
                    key = keyword.arg
                    value = keyword.value

                    if key in setup_data and isinstance(value, ast.Str):
                        setup_data[key] = value.s
                    elif key == "install_requires" and isinstance(value, ast.List):
                        setup_data["dependencies"] = [el.s for el in value.elts if isinstance(el, ast.Str)]
                    elif key == "packages" and isinstance(value, ast.Call) and getattr(value.func, "id", "") == "find_packages":
                        setup_data["packages"] = "find"
                    elif key == "entry_points" and isinstance(value, ast.Dict):
                        for k, v in zip(value.keys, value.values):
                            if isinstance(k, ast.Str) and isinstance(v, ast.List):
                                setup_data["entry_points"][k.s] = [el.s for el in v.elts if isinstance(el, ast.Str)]

    except Exception as e:
        print(f"⚠️ Error parsing {setup_path}: {e}")

    return setup_data


def generate_pyproject_toml(setup_data):
    """Creates a pyproject.toml content from extracted setup.py data."""
    return {
        "build-system": {
            "requires": ["setuptools>=64"],
            "build-backend": "setuptools.build_meta"
        },
        "project": {
            "name": setup_data["name"],
            "version": setup_data["version"],
            "description": setup_data["description"],
            "authors": [{"name": setup_data["author"], "email": setup_data["author_email"]}],
            "requires-python": ">=3.6",
            "dependencies": setup_data["dependencies"]
        },
        "tool": {
            "setuptools": {
                "packages": {"find": {}} if setup_data["packages"] == "find" else setup_data["packages"]
            }
        }
    }


def backup_file(file_path):
    """Backs up setup.py with an increasing numbered suffix."""
    backup_path = file_path + ".bak"
    counter = 1
    while os.path.exists(backup_path):
        backup_path = f"{file_path}.bak{counter}"
        counter += 1
    shutil.move(file_path, backup_path)
    print(f"🗂️ Backed up {file_path} → {backup_path}")


def convert_all_setup_files(base_dir, dry_run=False, overwrite=False):
    """Finds all setup.py files, converts valid ones, and warns about non-module scripts."""
    found_packages = []
    non_packages = []

    for setup_path in Path(base_dir).rglob("setup.py"):
        setup_path = str(setup_path)
        module_dir = os.path.dirname(setup_path)
        toml_path = os.path.join(module_dir, "pyproject.toml")

        if not is_valid_setup_py(setup_path):
            print(f"⚠️ Warning: Non-package setup.py detected: {setup_path}")
            non_packages.append(setup_path)
            continue

        print(f"✅ Detected module setup.py: {setup_path}")
        found_packages.append(setup_path)

        # Extract setup.py metadata
        setup_data = parse_setup_py(setup_path)

        # Fill missing fields
        for field in ["author", "author_email", "version", "description"]:
            if overwrite or not setup_data[field]:
                setup_data[field] = USER_FIELDS.get(field, setup_data[field]) or prompt_for_value(field)

        # Generate TOML
        pyproject_content = generate_pyproject_toml(setup_data)

        if dry_run:
            print(f"\n🔄 **Dry Run:** Would generate `{toml_path}` with contents:\n")
            print(toml.dumps(pyproject_content))
            print("-" * 80 + "\n")
        else:
            with open(toml_path, "w", encoding="utf-8") as f:
                toml.dump(pyproject_content, f)

            print(f"✅ Converted `setup.py` → `{toml_path}`")
            backup_file(setup_path)

    print("\n📌 Summary:")
    print(f"✅ Converted {len(found_packages)} valid package `setup.py` files.")
    print(f"⚠️ Skipped {len(non_packages)} non-package `setup.py` files.")

    if non_packages:
        print("\n⚠️ **Non-package setup.py files detected:**")
        for path in non_packages:
            print(f"   - {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert setup.py to pyproject.toml.")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Print the converted TOML without making changes.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite all fields with user-specified values.")
    parser.add_argument("--author", help="Specify author name.")
    parser.add_argument("--email", help="Specify author email.")
    parser.add_argument("--version", help="Specify package version.")
    parser.add_argument("--description", help="Specify package description.")
    parser.add_argument("--fields", help="Specify all fields in order: 'author,email,version,description'.")

    args = parser.parse_args()

    # Load fields from arguments
    if args.fields:
        values = args.fields.split(",")
        for i, field in enumerate(FIELD_ORDER):
            USER_FIELDS[field] = values[i] if i < len(values) else None

    for field in FIELD_ORDER:
        if getattr(args, field, None):
            USER_FIELDS[field] = getattr(args, field)

    convert_all_setup_files(os.getcwd(), dry_run=args.dry_run, overwrite=args.overwrite)
