#!/usr/bin/env python3
"""
python_diff.py

A CLI tool that compares two Python files and reports differences in:
  - Classes (which classes are present in one file but not the other)
  - For classes in both files, which member functions (methods) are missing in one file.
  - Top-level functions present in one file but not the other.
Optionally, using the flag --fn-signature (-s), it also compares function signatures
(based on argument names).
All output is formatted using the standard_ui module.
"""

import argparse
import ast
import os
import sys

from pathlib import Path

# Import our standardized UI functions
from standard_ui.standard_ui import (
    init_timer,
    log_info,
    log_warning,
    log_error,
    log_success,
    section,
)

# -------- Helper Functions to Parse Python Files -------- #

def get_function_signature(func_node):
    """
    Given an ast.FunctionDef node, return a tuple representing the signature.
    For simplicity, we use the names of the positional arguments.
    (You could expand this to include default values, varargs, etc.)
    """
    return tuple(arg.arg for arg in func_node.args.args)

def extract_top_level_functions(file_content):
    """
    Return a dict mapping function names (top-level) to their signature (tuple).
    """
    tree = ast.parse(file_content)
    funcs = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = get_function_signature(node)
    return funcs

def extract_classes_and_methods(file_content):
    """
    Return a dict mapping class names to a dict of its methods.
    Each method is mapped to its signature.
    Only consider functions defined directly in the class body.
    """
    tree = ast.parse(file_content)
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = {}
            for elem in node.body:
                if isinstance(elem, ast.FunctionDef):
                    methods[elem.name] = get_function_signature(elem)
            classes[node.name] = methods
    return classes

def load_file_content(filepath: Path) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

# -------- Comparison Functions -------- #

def diff_dictionaries(dict1, dict2, compare_signatures=False):
    """
    Compare two dictionaries mapping names to signatures.
    Returns:
      - only_in_1: set of keys only in dict1.
      - only_in_2: set of keys only in dict2.
      - common: set of keys in both.
      - sig_diffs: dict mapping key to (sig1, sig2) for keys in both but with different signatures (if compare_signatures is True)
    """
    keys1 = set(dict1.keys())
    keys2 = set(dict2.keys())
    only_in_1 = keys1 - keys2
    only_in_2 = keys2 - keys1
    common = keys1 & keys2
    sig_diffs = {}
    if compare_signatures:
        for key in common:
            if dict1[key] != dict2[key]:
                sig_diffs[key] = (dict1[key], dict2[key])
    return only_in_1, only_in_2, common, sig_diffs

def compare_python_files(file1: Path, file2: Path, compare_signatures=False):
    """
    Compare two python files.
    Returns a dict with the following keys:
      - classes_only_in_file1
      - classes_only_in_file2
      - common_classes: mapping from class name to a dict with:
             methods_only_in_file1,
             methods_only_in_file2,
             signature_differences (if compare_signatures is True)
      - functions_only_in_file1
      - functions_only_in_file2
      - common_functions (if compare_signatures is True, mapping name to (sig1, sig2) if different)
    """
    content1 = load_file_content(file1)
    content2 = load_file_content(file2)
    
    classes1 = extract_classes_and_methods(content1)
    classes2 = extract_classes_and_methods(content2)
    funcs1 = extract_top_level_functions(content1)
    funcs2 = extract_top_level_functions(content2)
    
    # Compare classes
    classes_only_in_file1 = set(classes1.keys()) - set(classes2.keys())
    classes_only_in_file2 = set(classes2.keys()) - set(classes1.keys())
    common_classes = set(classes1.keys()) & set(classes2.keys())
    common_class_diffs = {}
    for cls in common_classes:
        m1 = classes1[cls]
        m2 = classes2[cls]
        only_m1, only_m2, common_methods, sig_diffs = diff_dictionaries(m1, m2, compare_signatures)
        common_class_diffs[cls] = {
            "methods_only_in_file1": sorted(list(only_m1)),
            "methods_only_in_file2": sorted(list(only_m2)),
            "signature_differences": {k: v for k, v in sig_diffs.items()} if compare_signatures else {}
        }
    
    # Compare top-level functions
    funcs_only_in_file1, funcs_only_in_file2, common_funcs, fn_sig_diffs = diff_dictionaries(funcs1, funcs2, compare_signatures)
    
    diff_report = {
        "classes_only_in_file1": sorted(list(classes_only_in_file1)),
        "classes_only_in_file2": sorted(list(classes_only_in_file2)),
        "common_classes": common_class_diffs,
        "functions_only_in_file1": sorted(list(funcs_only_in_file1)),
        "functions_only_in_file2": sorted(list(funcs_only_in_file2)),
        "function_signature_differences": {k: v for k, v in fn_sig_diffs.items()} if compare_signatures else {}
    }
    
    return diff_report

def format_diff_report(report: dict) -> str:
    """
    Format the diff report into a human-readable string.
    """
    lines = []
    lines.append("=== Python File Diff Report ===\n")
    
    lines.append("** Classes **")
    lines.append(f"Classes only in file1: {', '.join(report['classes_only_in_file1']) or 'None'}")
    lines.append(f"Classes only in file2: {', '.join(report['classes_only_in_file2']) or 'None'}\n")
    
    for cls, diffs in report["common_classes"].items():
        lines.append(f"Class '{cls}':")
        lines.append(f"  Methods only in file1: {', '.join(diffs['methods_only_in_file1']) or 'None'}")
        lines.append(f"  Methods only in file2: {', '.join(diffs['methods_only_in_file2']) or 'None'}")
        if diffs.get("signature_differences"):
            for method, (sig1, sig2) in diffs["signature_differences"].items():
                lines.append(f"  Signature diff in method '{method}': file1 {sig1}, file2 {sig2}")
        lines.append("")
    
    lines.append("** Top-level Functions **")
    lines.append(f"Functions only in file1: {', '.join(report['functions_only_in_file1']) or 'None'}")
    lines.append(f"Functions only in file2: {', '.join(report['functions_only_in_file2']) or 'None'}")
    if report.get("function_signature_differences"):
        for fn, (sig1, sig2) in report["function_signature_differences"].items():
            lines.append(f"Signature diff in function '{fn}': file1 {sig1}, file2 {sig2}")
    lines.append("")
    
    return "\n".join(lines)

# -------- CLI Entry Point -------- #

def main():
    parser = argparse.ArgumentParser(
        description="Compare two Python files based on classes and functions."
    )
    parser.add_argument("--file1", "-f", required=True, help="First Python file")
    parser.add_argument("--file2", "-s", required=True, help="Second Python file")
    parser.add_argument("--fn-signature", "-g", action="store_true",
                        help="Compare function/method signatures as well")
    # Additional flags can be added here with full-length and single-letter abbreviations.
    args = parser.parse_args()

    file1 = Path(args.file1)
    file2 = Path(args.file2)
    
    # Ensure both files have a .py extension.
    if file1.suffix.lower() != ".py" or file2.suffix.lower() != ".py":
        log_error("Both files must have a .py extension.")
        sys.exit(1)

    init_timer()  # Start global timer for this diff operation

    with section("Python Diff Operation"):
        log_info(f"Comparing '{file1}' to '{file2}'")
        diff_report = compare_python_files(file1, file2, compare_signatures=args.fn_signature)
        report_str = format_diff_report(diff_report)
        log_success("Diff operation complete.")
    
    # Print the final report
    print(report_str)
    print_global_elapsed()

if __name__ == "__main__":
    main()
