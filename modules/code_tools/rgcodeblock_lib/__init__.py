# rgcodeblock_lib/__init__.py

"""
rgcodeblock_lib: A library for extracting code blocks based on language syntax.

This library provides functions to identify and extract logical code blocks
(like functions, classes, or other delimited structures) from source code files.
It supports various languages through different extraction strategies, including
AST parsing for Python and heuristic methods for brace-based, keyword-paired,
and data serialization languages.
"""

from .language_defs import get_language_type_from_filename, LANGUAGE_DEFINITIONS
from .extractors import (
    extract_python_block_ast,
    extract_brace_block,
    extract_json_block,
    extract_yaml_block,
    extract_xml_block,
    extract_ruby_block,
    extract_lua_block,
    OPTIONAL_LIBRARY_NOTES # Expose this for CLIs to access
)

# Dispatch map for convenience, mapping language type to its main extractor
EXTRACTOR_DISPATCH_MAP = {
    "python": extract_python_block_ast,
    "brace": extract_brace_block,
    "json": extract_json_block,
    "yaml": extract_yaml_block,
    "xml": extract_xml_block,
    "ruby": extract_ruby_block,
    "lua": extract_lua_block,
}

__version__ = "0.2.0" # Updated version example
