# Guide for API_DOC.md

This document outlines the process for creating `API_DOC.md` files for Python modules. The purpose of these files is to provide a comprehensive and structured overview of a module's API, enabling a Large Language Model (LLM) to understand and write code that uses the module without needing to analyze the full source code.

## 1. Objective

The primary goal of an `API_DOC.md` file is to serve as a complete replacement for the module's source code for the purpose of API understanding. It should contain all necessary information about the public-facing components of the module, including files, functions, classes, methods, and their signatures.

## 2. Methodology

### Step 1: Identify Target Modules

A directory is considered a Python module if it contains a `pyproject.toml` file. The `API_DOC.md` file should be placed in the root of this module directory.

### Step 2: Analyze Source Files

Recursively scan the module directory and identify all Python source files (`.py`). Initially, you should ignore test directories (e.g., `tests/`, `test/`) to focus on the application's core logic. If the core logic is not fully clear, you may consult the tests for usage examples.

### Step 3: Structure and Format the `API_DOC.md`

The `API_DOC.md` file must follow a consistent and machine-readable Markdown format. The structure should be as follows:

```markdown
# API Documentation for `module_name`

This document details the public API of the `module_name` module.

---

## File: `path/to/file_1.py`

Description or summary of the file's purpose.

### Classes

#### class `ClassName(BaseClass)`

A brief description of the class.

**Methods:**

- `def method_name(self, arg1: type, arg2: type = default) -> return_type:`
  - Docstring or a brief explanation of the method.

**Attributes:**

- `attribute_name: type`
  - Description of the attribute.

### Functions

- `def function_name(arg1: type, arg2: type) -> return_type:`
  - Docstring or a brief explanation of the function.

---

## File: `path/to/file_2.py`

... and so on.
```

### Key Formatting Rules:

1.  **Main Header**: The file must start with a level 1 heading: `# API Documentation for `module_name`.
2.  **File Sections**: Each source file is documented in its own section, separated by a horizontal rule (`---`) and introduced by a level 2 heading: `## File: `path/to/file.py``. The path should be relative to the module root.
3.  **Component-level headings**: Use level 3 headings for `### Classes` and `### Functions`.
4.  **Class Definitions**: Use a level 4 heading with the class signature: `#### class ClassName(BaseClass)`.
5.  **Function/Method Signatures**: Present function and method definitions as a list item with the full signature enclosed in backticks. Include name, arguments, type hints, default values, and return type.
6.  **Docstrings/Descriptions**: Provide a concise description below the signature, indented.

## 4. Why This Format?

This structured format is designed to be easily parsed by a script. A verification script will:
1.  Parse the `API_DOC.md` to extract a map of the documented API.
2.  Use Abstract Syntax Trees (AST) to parse the actual Python source files.
3.  Compare the documented API against the actual API to detect:
    - **Missing Components**: Files, classes, or functions present in the code but not in the documentation.
    - **Changed Signatures**: Discrepancies in arguments, types, or return values between the documentation and the code.
    - **Stale Documentation**: Components present in the documentation but removed from the code.

This verification ensures the `API_DOC.md` remains an accurate and reliable source of truth for the module's API.
