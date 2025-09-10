# File: json_replacer/json_replacer.py

"""
Applies multi-file, multi-edit code modifications from the clipboard
using a structured JSON format, as described in Methodology 1.
"""

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import List, Dict, Any

try:
    from cross_platform.clipboard_utils import get_clipboard
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm
    from rich.syntax import Syntax
    from rich.pretty import Pretty
except ImportError as e:
    print(f"Error: Missing required packages. Please install 'rich' and ensure 'cross_platform' is in your PYTHONPATH.", file=sys.stderr)
    print(f"--> ImportError: {e}", file=sys.stderr)
    sys.exit(1)

# --- Globals ---
console = Console()

# --- Change Application ---

def _calculate_new_content(op: Dict[str, Any], current_content: str) -> str:
    """
    Calculates the new content for a file based on a single operation
    and the file's current (potentially modified) state.
    """
    path = Path(op['file_path'])
    op_type = op['operation']

    if op_type == 'create_file':
        # This check is now done in the main loop before calling.
        return op.get('content', '')

    lines = current_content.splitlines(keepends=True)
    content_to_insert = op.get('content', '')
    locator = op.get('locator')

    if not locator:
        raise ValueError(f"Operation '{op_type}' on existing file '{path}' requires a 'locator'.")

    if locator['type'] == 'line_number':
        line_num = int(locator['value']) - 1  # 1-indexed to 0-indexed
        if not (0 <= line_num < len(lines)):
            raise IndexError(f"Line number {locator['value']} is out of bounds for file '{path}' (1-{len(lines)}).")
        
        if op_type == 'insert_before':
            lines.insert(line_num, content_to_insert + '\n')
        elif op_type == 'insert_after':
            lines.insert(line_num + 1, content_to_insert + '\n')
        elif op_type == 'replace_block':
            # Add a newline if the content doesn't already have one, preserving line structure
            if not content_to_insert.endswith('\n'):
                 content_to_insert += '\n'
            lines[line_num] = content_to_insert
        elif op_type == 'delete_block':
            del lines[line_num]
        
        return "".join(lines)
    
    elif locator['type'] == 'block_content':
        anchor = locator['value']
        
        if current_content.count(anchor) != 1:
            raise ValueError(f"Locator block_content is not unique (found {current_content.count(anchor)} times) in '{path}'.")

        if op_type == 'insert_before':
            return current_content.replace(anchor, f"{content_to_insert}\n{anchor}")
        elif op_type == 'insert_after':
            return current_content.replace(anchor, f"{anchor}\n{content_to_insert}")
        elif op_type == 'replace_block':
            return current_content.replace(anchor, content_to_insert)
        elif op_type == 'delete_block':
            return current_content.replace(anchor, "")
        
    raise ValueError(f"Unsupported locator type: {locator['type']}")


def preview_and_apply_json(operations: List[Dict[str, Any]], dry_run: bool, auto_confirm: bool):
    """Previews, confirms, and applies the list of parsed JSON operations."""
    if not operations:
        console.print("[bold yellow]No valid operations found in JSON input.[/bold yellow]")
        return

    console.rule("[bold cyan]Planned JSON-Based Modifications[/bold cyan]", style="cyan")
    
    planned_writes: Dict[Path, str] = {}
    validation_passed = True

    for i, op in enumerate(operations):
        op_type = op['operation'].upper()
        path = Path(op['file_path'])
        color = "green" if "CREATE" in op_type else "yellow"

        panel_content = f"[bold {color}]{op_type}[/bold {color}] -> [cyan]{path}[/cyan]\n"
        panel_content += f"[dim]Locator: {op.get('locator')}[/dim]"
        
        console.print(Panel(
            panel_content,
            title=f"Operation {i + 1}/{len(operations)}",
            expand=False,
            border_style=color
        ))
        
        try:
            # Corrected: State management for multi-edits on the same file.
            original_content = planned_writes.get(path)
            if original_content is None: # First time we see this file.
                if op['operation'] == 'create_file':
                    if path.exists():
                        raise FileExistsError(f"Cannot create '{path}' because it already exists.")
                    original_content = ""
                elif path.is_file():
                    original_content = path.read_text('utf-8')
                else:
                    raise FileNotFoundError(f"Cannot edit '{path}' because it does not exist.")
            
            new_content = _calculate_new_content(op, original_content)
            planned_writes[path] = new_content

            diff = difflib.unified_diff(
                original_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}", tofile=f"b/{path}"
            )
            console.print(Syntax(''.join(diff), "diff", theme="monokai"))

        except Exception as e:
            console.print(f"[bold red]Error previewing operation: {e}[/bold red]")
            validation_passed = False
            break
            
    console.rule(style="cyan")

    if not validation_passed:
        console.print("[bold red]Aborting due to validation errors. No changes will be applied.[/bold red]")
        return

    if dry_run:
        console.print("[bold yellow]DRY RUN MODE: No changes will be applied.[/bold yellow]")
        return

    if not auto_confirm:
        if not Confirm.ask("[bold magenta]Apply these changes?[/bold magenta]", default=False):
            console.print("[bold red]Aborted by user.[/bold red]")
            return

    console.rule("[bold green]Applying Changes...[/bold green]", style="green")
    for path, content in planned_writes.items():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, 'utf-8')
            console.print(f"[green]SUCCESS:[/green] Wrote changes to '{path}'")
        except Exception as e:
            console.print(f"[bold red]ERROR writing to '{path}': {e}[/bold red]")
    
    console.rule("[bold green]All operations complete.[/bold green]", style="green")

def main():
    parser = argparse.ArgumentParser(
        description="Apply LLM-generated JSON-based edits from the clipboard.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Use -y to auto-confirm changes, -d for a dry run."
        )
    parser.add_argument("-d", "--dry-run", action="store_true", help="Preview changes without applying.")
    parser.add_argument("-y", "--yes", action="store_true", help="Apply changes without confirmation.")
    args = parser.parse_args()

    try:
        clipboard_text = get_clipboard()
        if not clipboard_text or not clipboard_text.strip():
            console.print("[bold red]Clipboard is empty.[/bold red]")
            sys.exit(1)
        
        operations = json.loads(clipboard_text)
        if not isinstance(operations, list):
            raise TypeError("Input is not a JSON array of operations.")
            
        preview_and_apply_json(operations, args.dry_run, args.yes)

    except json.JSONDecodeError:
        console.print("[bold red]Error: Clipboard content is not valid JSON.[/bold red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    main()
