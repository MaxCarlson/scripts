import argparse
import ast
import os
from pathlib import Path
from typing import Any, Dict

from api_parser.utils import find_python_modules
from api_parser import api_validator

# --- Corrected Signature Generation ---
def get_signature_from_node(node: ast.FunctionDef) -> str:
    """Creates a normalized, correct function signature from an AST node."""
    args_list = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args_list.append(arg_str)

    signature = f"def {node.name}({', '.join(args_list)})"
    if node.returns:
        signature += f" -> {ast.unparse(node.returns)}"
    signature += ":"  # THE CRITICAL FIX
    return signature

# --- AST Parser ---
def parse_python_module(module_path: Path) -> Dict[str, Dict[str, Any]]:
    """Parses a Python module's source files using AST and returns its API structure."""
    code_api: Dict[str, Dict[str, Any]] = {}
    python_files = sorted(list(module_path.rglob("*.py")))

    for file_path in python_files:
        if "tests" in file_path.parts or "__pycache__" in file_path.parts:
            continue

        relative_path = str(file_path.relative_to(module_path))
        code_api[relative_path] = {"classes": {}, "functions": set(), "dataclasses": {}}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
                if not source.strip(): # Handle empty files
                    continue
                tree = ast.parse(source, filename=str(file_path))

                # Top-level functions and classes
                for node in tree.body:
                    if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                        code_api[relative_path]["functions"].add(get_signature_from_node(node))
                    elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                        class_name = node.name
                        is_dataclass = any(
                            isinstance(d, ast.Name) and d.id == 'dataclass'
                            for d in node.decorator_list
                        )

                        if is_dataclass:
                            attributes = []
                            for field in node.body:
                                if isinstance(field, ast.AnnAssign):
                                    field_name = field.target.id
                                    field_type = ast.unparse(field.annotation)
                                    attributes.append(f"{field_name}: {field_type}")
                            code_api[relative_path]["dataclasses"][class_name] = attributes
                        else:
                            methods = set()
                            for method in node.body:
                                if isinstance(method, ast.FunctionDef) and not method.name.startswith("_"):
                                    methods.add(get_signature_from_node(method))
                            code_api[relative_path]["classes"][class_name] = methods
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
    return code_api

# --- Markdown Generation ---
def generate_api_doc(module_path: Path, code_api: Dict[str, Dict[str, Any]]) -> str:
    """Generates the content for the API_DOC.md file."""
    module_name = module_path.name
    lines = [f"# API Documentation for `{module_name}`", ""]

    for file_path, api_elements in sorted(code_api.items()):
        lines.append("---")
        lines.append(f"## File: `{file_path}`")
        lines.append("")

        if not any(api_elements.values()):
            lines.append("*This file is empty or contains only imports/comments.*")
            lines.append("")
            continue

        if api_elements.get("dataclasses"):
            lines.append("### Dataclasses")
            for name, attributes in sorted(api_elements["dataclasses"].items()):
                lines.append(f"#### dataclass `{name}`")
                for attr in attributes:
                    lines.append(f"- `{attr}`")
                lines.append("")

        if api_elements.get("classes"):
            lines.append("### Classes")
            for name, methods in sorted(api_elements["classes"].items()):
                lines.append(f"#### class `{name}`")
                if methods:
                    lines.append("**Methods:**")
                    for method_sig in sorted(list(methods)):
                        lines.append(f"- `{method_sig}`")
                lines.append("")

        if api_elements.get("functions"):
            lines.append("### Functions")
            for func_sig in sorted(list(api_elements["functions"])):
                lines.append(f"- `{func_sig}`")
            lines.append("")

    return "\n".join(lines)

# --- Main Execution ---
import json

def run_generator(args):
    root_path = Path(args.module_path).resolve() # Renamed from module_path to root_path
    if not root_path.is_dir():
        print(f"Error: {root_path} is not a directory.")
        return

    modules_to_process = find_python_modules(root_path)

    if not modules_to_process:
        print(f"No Python modules found in {root_path}")
        return

    for module_path in modules_to_process:
        api_doc_path = module_path / "API_DOC.md"
        should_generate = True

        if api_doc_path.exists():
            if not args.force_overwrite:
                print(f"Skipping {module_path.name}: API_DOC.md already exists. Use --force-overwrite to regenerate.")
                should_generate = False
            else:
                print(f"API_DOC.md exists for {module_path.name}. Validating before overwriting...")
                doc_api = api_validator.parse_api_doc(api_doc_path)
                code_api = api_validator.parse_python_module(module_path)
                missing, changed = api_validator.compare_apis(doc_api, code_api)

                if not any(missing.values()) and not any(changed.values()):
                    print(f"API_DOC.md for {module_path.name} is in sync. Skipping regeneration.")
                    should_generate = False
                else:
                    print(f"API_DOC.md for {module_path.name} is out of sync. Regenerating...")

        if should_generate:
            print(f"\nParsing source code in: {module_path}")
            code_api = parse_python_module(module_path)

            if args.debug:
                def set_serializer(obj):
                    if isinstance(obj, set):
                        return sorted(list(obj))
                    raise TypeError
                print("--- CODE API (DEBUG) ---")
                print(json.dumps(code_api, indent=2, default=set_serializer))

            print("Generating API documentation...")
            markdown_content = generate_api_doc(module_path, code_api)

            with open(api_doc_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            print(f"Successfully generated API documentation at: {api_doc_path}")