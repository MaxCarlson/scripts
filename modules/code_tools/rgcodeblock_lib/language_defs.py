# rgcodeblock_lib/language_defs.py
import os

# Centralized Language Definitions
LANGUAGE_DEFINITIONS = {
    "python": { "exts": [".py"], "notes": "AST-based"},
    "json":   { "exts": [".json"], "notes": "Heuristic brace/bracket"},
    "yaml":   { "exts": [".yaml", ".yml"], "notes": "PyYAML (optional dependency)"},
    "xml":    {
        "exts": [
            ".xml", ".xsd", ".xsl", ".xslt", ".kml", ".svg", ".plist",
            ".csproj", ".vbproj", ".fxml", ".graphml", ".gexf", ".nuspec",
            ".resx", ".config", ".props", ".targets", ".wsdl", ".xaml", ".manifest"
        ],
        "notes": "lxml (optional dependency)"
    },
    "ruby":   { "exts": [".rb"], "notes": "Keyword-pair heuristic"},
    "lua":    { "exts": [".lua"], "notes": "Keyword-pair heuristic"},
    "brace":  { # C-style brace languages
        "exts": [
            ".c", ".h",                                # C
            ".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx", # C++
            ".cs",                                     # C#
            ".java",                                   # Java
            ".js", ".jsx", ".mjs", ".cjs",               # JavaScript & variants
            ".ts", ".tsx",                             # TypeScript
            ".go",                                     # Go
            ".rs",                                     # Rust
            ".kt", ".kts",                             # Kotlin
            ".swift",                                  # Swift
            ".php", ".phtml",                          # PHP
            ".scl", ".sbt", ".scala",                  # Scala
            ".gd",                                     # GDScript (Godot Engine)
            ".glsl", ".frag", ".vert", ".geom", ".tesc", ".tese", ".comp", # Shaders
            ".groovy", ".gvy", ".gy", ".gsh",           # Groovy
            ".dart",                                   # Dart
            ".r", ".R",                                # R (can be tricky, but often uses braces)
            ".objective-c", ".m", ".mm",               # Objective-C
            ".shader",                                 # Unity Shader specific
            ".pde",                                    # Processing
            ".vala",                                   # Vala
            ".d",                                      # D Language
            ".ceylon",                                 # Ceylon
            ".cr",                                     # Crystal
            ".hx"                                      # Haxe
        ],
        "notes": "Brace counting heuristic"
    },
    # Add more language families here if needed (e.g., "html_like", "sql_like")
    "unknown": {"exts": [], "notes": "Fallback or unrecognized"}
}

def get_language_type_from_filename(filename: str) -> tuple[str, str]:
    """
    Determines the language type (e.g., "python", "brace") and the raw
    file extension (e.g., "py", "cpp") from a given filename.

    Args:
        filename: The full name or path of the file.

    Returns:
        A tuple containing:
            - lang_type (str): The determined language category.
            - raw_ext (str): The file extension without the leading dot, in lowercase.
                             Returns an empty string if no extension.
    """
    name, ext_with_dot = os.path.splitext(filename)
    raw_ext = ext_with_dot[1:].lower() if ext_with_dot else ""

    # Check for exact matches first (e.g., if a specific file has no extension but is known type)
    # basename = os.path.basename(filename)
    # if basename == "Makefile": return "makefile", "" # Example specific handling

    for lang, details in LANGUAGE_DEFINITIONS.items():
        if ext_with_dot.lower() in details["exts"]:
            return lang, raw_ext
    return "unknown", raw_ext
