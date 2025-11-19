# Filter Stack System - Design Document

> **Status**: Phase 1 Complete (Core FilterStack class)
> **Date**: 2025-11-19
> **Next**: TUI Integration

---

## Overview

A powerful filter pipeline system allowing users to stack multiple filters/excludes that are applied sequentially.

### Key Features:
- ✅ **Multiple Filters**: Stack unlimited filters
- ✅ **Include/Exclude Modes**: Each filter can include or exclude matches
- ✅ **Sequential Application**: Filters apply in order (pipeline)
- ✅ **Temporary Disable**: Turn filters on/off without deleting
- ✅ **Reordering**: Change filter application order
- ✅ **Clear All**: Remove all filters at once

---

## Architecture

### FilterCriterion
```python
@dataclass
class FilterCriterion:
    filter_type: FilterType  # EXTENSION, SIZE_RANGE, NAME_GLOB, NAME_REGEX, CUSTOM
    mode: FilterMode  # INCLUDE or EXCLUDE
    enabled: bool  # Can be temporarily disabled

    # Type-specific data
    extensions: Optional[List[str]]
    min_size/max_size: Optional[int]
    name_pattern: Optional[str]
    name_regex: Optional[re.Pattern]
    case_sensitive: bool
    custom_filter: Optional[Callable]

    def matches(self, entry) -> bool
    def apply(self, entries: List) -> List
    def describe() -> str
```

### FilterStack
```python
@dataclass
class FilterStack:
    filters: List[FilterCriterion]
    selected_index: int  # For UI navigation

    def add_filter(criterion)
    def remove_filter(index)
    def toggle_mode(index)  # INCLUDE ↔ EXCLUDE
    def toggle_enabled(index)  # ON ↔ OFF
    def move_up/move_down(index)  # Reorder
    def clear()  # Remove all
    def apply(entries) -> List  # Sequential application
```

---

## Sequential Application Example

```
Initial: 1000 files

Filter 1 (INCLUDE ext=pdf):
    → 100 PDF files

Filter 2 (INCLUDE name=*report*):
    → 50 PDF files with "report" in name

Exclude 1 (EXCLUDE name=*draft*):
    → 45 PDF reports (removed 5 drafts)

Final Result: 45 files
```

Each filter operates on the output of the previous filter!

---

## TUI Keybindings (Planned)

### Filter Management
- **F** - Add new filter (INCLUDE mode)
- **X** - Add new exclude (EXCLUDE mode)
- **T** - Toggle current filter between INCLUDE/EXCLUDE
- **Space** or **E** - Enable/Disable current filter
- **D** - Delete current filter
- **C** - Clear all filters

### Navigation & Ordering
- **Tab** - Switch focus between file list and filter panel
- **↑/↓** - Navigate filter stack (when focused)
- **<** or **[** - Move current filter up (apply earlier)
- **>** or **]** - Move current filter down (apply later)

### Filter Creation Dialog
When pressing F or X, show prompt:
```
Add Filter:
1. Extension (e.g., pdf|doc|txt)
2. Size Range (min/max)
3. Name Pattern (glob)
4. Name Regex
[Select 1-4]:
```

---

## UI Layout (Planned)

```
┌────────────────────────────────────────────────────────────┐
│ Path: ~/docs │ Filters Active: 3 (2 enabled) │ 45 files   │
├────────────────────────────────────────────────────────────┤
│ FILTER STACK (Tab to toggle)                   [F:add X:exclude]│
│ → 1. ● ✓ ext=pdf                                           │
│   2. ● ✓ name=*report*                                     │
│   3. ○ ✗ name=*draft*  [DISABLED]                          │
│                                                             │
│ ● = enabled, ○ = disabled                                  │
│ ✓ = include, ✗ = exclude                                   │
├────────────────────────────────────────────────────────────┤
│ FILE LIST                                                   │
│ 2024-11-15  reports/annual_report_2024.pdf  2.5 MB        │
│ 2024-11-16  reports/monthly_report_nov.pdf  1.8 MB        │
│ ...                                                         │
├────────────────────────────────────────────────────────────┤
│ F:filter X:exclude T:toggle Space:enable/disable D:delete  │
│ </>:reorder C:clear Tab:focus ↑↓:navigate                  │
└────────────────────────────────────────────────────────────┘
```

---

## Usage Examples

### Example 1: Find Large PDFs, Exclude Drafts
```python
stack = FilterStack()

# Add filter: only PDFs
stack.add_filter(FilterCriterion(
    filter_type=FilterType.EXTENSION,
    mode=FilterMode.INCLUDE,
    extensions=['pdf']
))

# Add filter: size > 1MB
stack.add_filter(FilterCriterion(
    filter_type=FilterType.SIZE_RANGE,
    mode=FilterMode.INCLUDE,
    min_size=1024*1024
))

# Add exclude: remove drafts
stack.add_filter(FilterCriterion(
    filter_type=FilterType.NAME_GLOB,
    mode=FilterMode.EXCLUDE,
    name_pattern='*draft*'
))

result = stack.apply(all_entries)
```

### Example 2: Complex Search with Reordering
```python
stack = FilterStack()

# Initially wrong order:
# 1. name=*2024* (INCLUDE)
# 2. ext=pdf|doc (INCLUDE)

# User realizes: should filter by extension first (faster)
stack.move_down(0)  # Move name filter down

# Now correct order:
# 1. ext=pdf|doc (INCLUDE) - fast, reduces list quickly
# 2. name=*2024* (INCLUDE) - operates on smaller list
```

### Example 3: Temporary Disable for Testing
```python
# User has 3 filters active
# Wants to test what filter 2 does
stack.toggle_enabled(1)  # Disable filter 2
# See results...
stack.toggle_enabled(1)  # Re-enable
```

---

## Implementation Phases

### ✅ Phase 1: Core FilterStack Class (COMPLETE)
- [x] FilterCriterion dataclass
- [x] FilterStack dataclass
- [x] Sequential application logic
- [x] Add/remove/toggle/reorder operations
- [x] Display formatting

### Phase 2: TUI Integration (IN PROGRESS)
- [ ] Add filter stack panel to lister TUI
- [ ] Implement keybindings
- [ ] Add filter creation dialog
- [ ] Update header/footer with filter info
- [ ] Tab to switch focus between panels

### Phase 3: Enhanced UX
- [ ] Filter templates (save/load common filters)
- [ ] Undo/redo for filter operations
- [ ] Filter statistics (show count at each step)
- [ ] Visual pipeline diagram
- [ ] Export filter stack to JSON

### Phase 4: Advanced Features
- [ ] Named filter groups
- [ ] Conditional filters (if-then logic)
- [ ] Filter macros (combine multiple operations)
- [ ] Share filter stacks between users

---

## API Reference

### Creating Filters

```python
# Extension filter
FilterCriterion(
    filter_type=FilterType.EXTENSION,
    mode=FilterMode.INCLUDE,
    extensions=['pdf', 'doc', 'docx']
)

# Size range filter
FilterCriterion(
    filter_type=FilterType.SIZE_RANGE,
    mode=FilterMode.INCLUDE,
    min_size=1024*1024,  # 1MB
    max_size=100*1024*1024  # 100MB
)

# Name glob filter
FilterCriterion(
    filter_type=FilterType.NAME_GLOB,
    mode=FilterMode.EXCLUDE,
    name_pattern='*draft*',
    case_sensitive=False
)

# Name regex filter
FilterCriterion(
    filter_type=FilterType.NAME_REGEX,
    mode=FilterMode.INCLUDE,
    name_regex=re.compile(r'report_\d{4}', re.IGNORECASE)
)

# Custom filter
FilterCriterion(
    filter_type=FilterType.CUSTOM,
    mode=FilterMode.INCLUDE,
    custom_filter=lambda e: e.created > datetime(2024, 1, 1)
)
```

### Managing Stack

```python
stack = FilterStack()

# Add filters
stack.add_filter(criterion1)
stack.add_filter(criterion2)

# Reorder
stack.move_up(1)  # Move filter at index 1 up

# Toggle
stack.toggle_mode(0)  # INCLUDE → EXCLUDE
stack.toggle_enabled(0)  # ON → OFF

# Remove
stack.remove_filter(0)
stack.clear()  # Remove all

# Apply
filtered = stack.apply(all_entries)

# Info
print(stack.describe())
print(f"Enabled filters: {stack.count_enabled()}")
```

---

## Testing

### Unit Tests Needed
- [ ] FilterCriterion.matches() for each type
- [ ] FilterCriterion.apply() for INCLUDE/EXCLUDE modes
- [ ] FilterStack.add/remove operations
- [ ] FilterStack.toggle operations
- [ ] FilterStack.move_up/move_down
- [ ] FilterStack.apply() sequential logic
- [ ] Edge cases (empty stack, all disabled, etc.)

### Integration Tests
- [ ] End-to-end filter pipeline
- [ ] TUI keybinding interactions
- [ ] Performance with large file lists

---

## Performance Considerations

### Optimization Strategies
1. **Early Termination**: Apply selective filters first (extensions)
2. **Caching**: Cache regex compilation
3. **Lazy Evaluation**: Don't load file stats until needed
4. **Parallel Filtering**: For large lists, use multiprocessing

### Benchmarks
- Target: 10,000 files filtered in <1 second
- Current: TBD (need to implement benchmarks)

---

## Future Enhancements

### Smart Filter Suggestions
Analyze file patterns and suggest useful filters:
- "Most files are PDFs - add extension filter?"
- "Many large files - add size filter?"

### Filter Analytics
Show how each filter affects the result:
```
Filter Pipeline:
1. ext=pdf (1000 → 500 files)  -50%
2. size>1MB (500 → 200 files)  -60%
3. name=*report* (200 → 50 files)  -75%
```

### Visual Pipeline Editor
Drag-and-drop interface for reordering filters.

---

## Known Limitations

1. **No OR Logic Between Filters**: Each filter must pass (AND logic)
   - Workaround: Use multiple extensions in one filter
   - Future: Add filter groups with OR logic

2. **No Nested Groups**: Can't do (F1 OR F2) AND (F3 OR F4)
   - Future: Add filter group nesting

3. **No Inverse Regex**: Can't easily do "NOT matching regex"
   - Workaround: Use EXCLUDE mode

---

**End of Document**
