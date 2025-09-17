import argparse
from pathlib import Path
from typing import Dict, Any, Tuple

from api_parser.utils import find_python_modules
from api_parser import api_doc_generator
from api_parser import api_validator

def calculate_validation_score(missing: Dict, changed: Dict, code_api: Dict) -> float:
    total_funcs = sum(len(f.get("functions", set())) for f in code_api.values())
    total_classes = sum(len(f.get("classes", {{}})) for f in code_api.values())
    total_methods = sum(len(m) for f in code_api.values() for m in f.get("classes", {{}}).values())
    total_items = total_funcs + total_classes + total_methods

    if total_items == 0:
        return 100.0 # No items, so it's perfectly in sync

    missing_count = len(missing["files"]) + len(missing["classes"]) + len(missing["functions"])
    changed_count = len(changed["classes"]) # Only changed methods are reported in changed["classes"]

    # A simple scoring: 100% minus penalty for missing/changed items
    # This can be refined based on desired weighting
    penalty = (missing_count + changed_count) / total_items * 100
    score = 100.0 - penalty
    return max(0.0, score) # Score cannot be negative

def run_sync(args):
    root_path = Path(args.module_path).resolve()
    if not root_path.is_dir():
        print(f"Error: {root_path} is not a directory.")
        return

    modules_to_process = find_python_modules(root_path)

    if not modules_to_process:
        print(f"No Python modules found in {root_path}")
        return

    print(f"--- API Documentation Sync Report for {root_path.name} ---")
    print(f"Processing {len(modules_to_process)} modules.")

    for module_path in modules_to_process:
        api_doc_path = module_path / "API_DOC.md"
        print(f"\n--- Module: {module_path.name} ---")

        if not api_doc_path.exists():
            print(f"API_DOC.md does not exist. Generating...")
            gen_args = argparse.Namespace(module_path=str(module_path), debug=args.debug, force_overwrite=False)
            api_doc_generator.run_generator(gen_args)
            print(f"Generated API_DOC.md for {module_path.name}.")
            continue

        print(f"API_DOC.md exists. Validating...")
        doc_api = api_validator.parse_api_doc(api_doc_path)
        code_api = api_validator.parse_python_module(module_path)
        missing, changed = api_validator.compare_apis(doc_api, code_api)

        initial_score = calculate_validation_score(missing, changed, code_api)
        print(f"Initial validation score: {initial_score:.2f}%")

        if not any(missing.values()) and not any(changed.values()):
            print(f"API_DOC.md for {module_path.name} is in sync. No changes needed.")
        else:
            print(f"API_DOC.md for {module_path.name} is out of sync. Regenerating...")
            gen_args = argparse.Namespace(module_path=str(module_path), debug=args.debug, force_overwrite=True)
            api_doc_generator.run_generator(gen_args)

            # Re-validate after regeneration
            doc_api_new = api_validator.parse_api_doc(api_doc_path)
            code_api_new = api_validator.parse_python_module(module_path)
            missing_new, changed_new = api_validator.compare_apis(doc_api_new, code_api_new)
            final_score = calculate_validation_score(missing_new, changed_new, code_api_new)
            print(f"Final validation score after regeneration: {final_score:.2f}%")
            print(f"Score change: {final_score - initial_score:.2f}%")

            if final_score < 100.0:
                print(f"[WARNING] Regeneration did not achieve 100% sync for {module_path.name}. Manual review may be needed.")
                api_validator.generate_report(module_path, missing_new, changed_new, code_api_new)

    print("\n--- Sync process complete ---")
