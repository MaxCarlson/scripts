# Add a name separator option

Update the existing `display_name(first, last)` function in `src/names.py` to accept a keyword-only `separator` argument that defaults to one space. Trim both names, omit empty name parts, and join the remaining parts with the requested separator. Preserve current behavior for existing callers. Edit only `src/names.py`.
