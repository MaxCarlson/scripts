import argparse
import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Tuple

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
    signature += ":"
    return signature

# --- Parsers ---
def parse_api_doc(api_doc_path: Path) -> Dict[str, Dict[str, Any]]:
    """Parses an API_DOC.md file and returns a dictionary of its structure."""
    doc_api: Dict[str, Dict[str, Any]] = {}
    current_file = None
    current_class = None
    parsing_section = None # Can be 'classes', 'functions', 'dataclasses'

    if not api_doc_path.exists():
        return doc_api

    with open(api_doc_path, "r") as f:
        for line in f:
            file_match = re.search(r"## File: `(.+?)`", line)
            class_match = re.search(r"#### class `(.+?)`", line)
            dataclass_match = re.search(r"#### dataclass `(.+?)`", line)
            func_match = re.search(r"- `(def .+?:)`", line)
            section_match = re.search(r"### (Classes|Functions|Dataclasses)", line)

            if file_match:
                current_file = file_match.group(1)
                doc_api[current_file] = {"classes": {}, "functions": set(), "dataclasses": {}}
                current_class = None
                parsing_section = None
            elif current_file:
                if section_match:
                    parsing_section = section_match.group(1).lower()
                    current_class = None # Reset class context when changing sections
                
                if parsing_section == 'classes' and class_match:
                    current_class = class_match.group(1).split("(")[0]
                    if current_class not in doc_api[current_file]["classes"]:
                        doc_api[current_file]["classes"][current_class] = set()
                
                elif func_match:
                    signature = func_match.group(1)
                    if parsing_section == 'classes' and current_class:
                        doc_api[current_file]["classes"][current_class].add(signature)
                    elif parsing_section == 'functions':
                        doc_api[current_file]["functions"].add(signature)
    return doc_api

def parse_python_module(module_path: Path) -> Dict[str, Dict[str, Any]]:
    """Parses a Python module's source files using AST."""
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
                if not source.strip():
                    continue
                tree = ast.parse(source, filename=str(file_path))

                for node in tree.body:
                    if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                        code_api[relative_path]["functions"].add(get_signature_from_node(node))
                    elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                        class_name = node.name
                        methods = set()
                        for method in node.body:
                            if isinstance(method, ast.FunctionDef) and not method.name.startswith("_"):
                                methods.add(get_signature_from_node(method))
                        code_api[relative_path]["classes"][class_name] = methods
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
    return code_api

# --- Comparison and Reporting ---
def compare_apis(doc_api: Dict, code_api: Dict) -> Tuple[Dict, Dict]:
    missing: Dict = {"files": [], "classes": [], "functions": []}
    changed: Dict = {"classes": [], "functions": []}

    doc_files = set(doc_api.keys())
    code_files = set(code_api.keys())

    missing["files"] = list(code_files - doc_files)

    for file in code_files.intersection(doc_files):
        doc_classes = set(doc_api[file]["classes"].keys())
        code_classes = set(code_api[file]["classes"].keys())
        missing["classes"].extend([(file, c) for c in code_classes - doc_classes])

        doc_funcs = doc_api[file]["functions"]
        code_funcs = code_api[file]["functions"]
        missing["functions"].extend([(file, f) for f in code_funcs - doc_funcs])

        for class_name in code_classes.intersection(doc_classes):
            doc_methods = doc_api[file]["classes"].get(class_name, set())
            code_methods = code_api[file]["classes"].get(class_name, set())
            if doc_methods != code_methods:
                 changed["classes"].append((file, class_name, code_methods - doc_methods))

    return missing, changed

def generate_report(module_path: Path, missing: Dict, changed: Dict, code_api: Dict):
    print(f"--- API Validation Report for {module_path.name} ---")

    total_funcs = sum(len(f.get("functions", set())) for f in code_api.values())
    total_classes = sum(len(f.get("classes", {})) for f in code_api.values())
    total_methods = sum(len(m) for f in code_api.values() for m in f.get("classes", {}).values())
    total_items = total_funcs + total_classes + total_methods

    if not any(missing.values()) and not any(changed.values()):
        print("\n[OK] API documentation is in sync with the source code.")
        print(f"Verified {total_items} items across {len(code_api)} files.")
    else:
        if missing["files"]:
            print("\n[!] Missing Files from API_DOC.md:")
            for f in missing["files"]:
                print(f"  - {f}")

        if missing["classes"]:
            print("\n[!] Missing Classes from API_DOC.md:")
            for file, class_name in missing["classes"]:
                print(f"  - {file}: class {class_name}")

        if missing["functions"]:
            print("\n[!] Missing Functions from API_DOC.md:")
            for file, func_sig in missing["functions"]:
                print(f"  - {file}: {func_sig}")

        if changed["classes"]:
            print("\n[!] Changed Class Signatures:")
            for file, class_name, diff in changed["classes"]:
                print(f"  - {file}: class {class_name} has modified methods:")
                for d in diff:
                    print(f"    - {d}")

    print(f"\n--- Statistics ---")
    missing_count = len(missing["files"]) + len(missing["classes"]) + len(missing["functions"])
    changed_count = len(changed["classes"]) + len(changed["functions"])

    if total_items > 0:
        print(f"Total items (classes + functions/methods): {total_items}")
        if missing_count or changed_count:
            missing_perc = (missing_count / total_items) * 100
            changed_perc = (changed_count / total_items) * 100
            print(f"Missing from docs: {missing_count} ({missing_perc:.2f}%)")
            print(f"Changed signatures: {changed_count} ({changed_perc:.2f}%)")
    else:
        print("No items found in source code.")

    print("\n--- End of Report ---")

def main():
    parser = argparse.ArgumentParser(description="Validate a module's API_DOC.md against its source code.")
    parser.add_argument("module_path", type=str, help="Path to the Python module directory.")
    parser.add_argument("--debug", action="store_true", help="Print the parsed API dictionaries for debugging.")
    args = parser.parse_args()

    module_path = Path(args.module_path).resolve()
    api_doc_path = module_path / "API_DOC.md"

    if not module_path.is_dir():
        print(f"Error: {module_path} is not a directory.")
        return

    print(f"Parsing documentation: {api_doc_path}")
    doc_api = parse_api_doc(api_doc_path)

    print(f"Parsing source code in: {module_path}")
    code_api = parse_python_module(module_path)

    if args.debug:
        def set_serializer(obj):
            if isinstance(obj, set):
                return sorted(list(obj))
            raise TypeError

        print("--- DOC API (DEBUG) ---")
        print(json.dumps(doc_api, indent=2, default=set_serializer))
        print("--- CODE API (DEBUG) ---")
        print(json.dumps(code_api, indent=2, default=set_serializer))

    missing, changed = compare_apis(doc_api, code_api)
    generate_report(module_path, missing, changed, code_api)

if __name__ == "__main__":
    main()
