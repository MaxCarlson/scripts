from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


def prompt_text(prompt: str, *, default: Optional[str] = None, required: bool = False) -> str:
    """
    Prompt the user for free-form text. Empty responses return the default when provided.
    """
    while True:
        suffix = f" [{default}]" if default else ""
        try:
            response = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Operation cancelled by user.")
            raise SystemExit(1)
        if not response and default is not None:
            return default
        if response:
            return response
        if not required:
            return ""
        print("A value is required.")


def prompt_bool(prompt: str, *, default: bool = True) -> bool:
    """
    Ask the user for a yes/no response.
    """
    choice = "Y/n" if default else "y/N"
    while True:
        try:
            response = input(f"{prompt} [{choice}]: ").strip().lower()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Operation cancelled by user.")
            raise SystemExit(1)
        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")


def prompt_int(
    prompt: str,
    *,
    default: Optional[int] = None,
    allow_empty: bool = True,
) -> Optional[int]:
    """
    Prompt the user for an integer value.
    """
    while True:
        suffix = ""
        if default is not None:
            suffix = f" [{default}]"
        elif not allow_empty:
            suffix = " (required)"
        try:
            response = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Operation cancelled by user.")
            raise SystemExit(1)

        if not response:
            if default is not None:
                return default
            if allow_empty:
                return None
            print("A value is required.")
            continue
        try:
            return int(response)
        except ValueError:
            print("Please enter a valid integer.")


def prompt_list(
    prompt: str,
    *,
    min_items: int = 0,
    guidance: Optional[str] = None,
) -> list[str]:
    """
    Prompt the user for zero or more values until a blank line is entered.
    """
    items: list[str] = []
    if guidance:
        print(guidance)
    while True:
        suffix = "" if items else " (enter value)"
        try:
            response = input(f"{prompt}{suffix} (blank to finish): ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Operation cancelled by user.")
            raise SystemExit(1)
        if not response:
            if len(items) >= min_items:
                return items
            print(f"Please provide at least {min_items} value(s).")
            continue
        items.append(response)


def prompt_choice(prompt: str, options: list[str], *, default_index: Optional[int] = None) -> int:
    """
    Prompt the user to select from a numbered list of options, returning the index.
    """
    while True:
        print(prompt)
        for idx, option in enumerate(options, start=1):
            marker = " (default)" if default_index is not None and default_index == idx - 1 else ""
            print(f"  {idx}. {option}{marker}")
        try:
            response = input("Select option number: ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Operation cancelled by user.")
            raise SystemExit(1)
        if not response and default_index is not None:
            return default_index
        if response.isdigit():
            choice = int(response) - 1
            if 0 <= choice < len(options):
                return choice
        print("Please enter a valid option number.")


def launch_editor(path: Path, *, editor: str = "nvim") -> bool:
    """
    Launch an external editor (defaults to nvim) for the provided file path.
    Returns True if the editor command was executed.
    """
    if shutil.which(editor) is None:
        print(f"[rrbackup] {editor} not found on PATH. Skipping editor launch.")
        return False

    try:
        subprocess.run([editor, str(path)], check=False)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[rrbackup] Failed to launch {editor}: {exc}")
        return False
    return True
