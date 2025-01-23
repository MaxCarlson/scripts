import re
import sys

def extract_imports(source_files):
    """Parses source files to extract import statements and generate a requirements.txt."""
    imports = set()
    import_pattern = re.compile(r"^\s*(?:import|from) (\w+)")
    
    for file in source_files:
        with open(file, "r", encoding="utf-8") as f:
            for line in f:
                match = import_pattern.match(line)
                if match:
                    imports.add(match.group(1))

    return sorted(imports - set(sys.builtin_module_names))
