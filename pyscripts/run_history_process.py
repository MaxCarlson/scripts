#!/usr/bin/env python3

import subprocess
import argparse
import shlex
import os
import re
import fnmatch
import sys
import sys

def get_all_historical_paths(history_limit=50, verbose=False):
    """
    Fetches commands from Atuin history and extracts all unique potential file paths,
    ordered by their first appearance (most recent command first, then left-to-right within a command).
    """
    try:
        # Get the last N commands from Atuin, newest first.
        process_result = subprocess.run(
            ['atuin', 'history', 'list', '--format', '{command}', '--limit', str(history_limit), '-r'],
            capture_output=True, text=True, check=True, encoding='utf-8'
        )
        history_lines = [line for line in process_result.stdout.strip().split('\n') if line]
    except FileNotFoundError:
        print("Error: 'atuin' command not found. Is Atuin installed and in your PATH?", file=sys.stderr)
        return []
    except subprocess.CalledProcessError as e:
        print(f"Error fetching Atuin history: {e}", file=sys.stderr)
        print(f"Stderr from atuin: {e.stderr}", file=sys.stderr)
        return []
    except Exception as e: # Catch any other unexpected error during subprocess interaction
        print(f"An unexpected error occurred while fetching history: {e}", file=sys.stderr)
        return []

    if verbose:
        print(f"Fetched {len(history_lines)} lines from Atuin history.", file=sys.stderr)

    collected_paths = []
    seen_paths = set() # To ensure uniqueness in the returned list

    for idx, command_line in enumerate(history_lines):
        if not command_line.strip():
            continue
        
        if verbose:
            print(f"Processing history entry {idx + 1}/{len(history_lines)}: {command_line}", file=sys.stderr)

        try:
            args = shlex.split(command_line)
        except ValueError: # Malformed command line
            if verbose:
                print(f"  Could not shlex.split: '{command_line}', falling back to simple space split.", file=sys.stderr)
            args = command_line.split()

        if not args:
            continue
            
        command_name = args[0].lower()

        for i in range(len(args)): # Iterate arguments left-to-right
            arg_candidate = args[i]
            original_arg_for_log = arg_candidate # For verbose logging

            # Heuristic to skip typical options, unless they also look like paths
            # An option like '-foo' is skipped.
            # An option like '-foo/bar', '-~', or './-foo' is further processed.
            is_likely_option = arg_candidate.startswith('-') and len(arg_candidate) > 1 and arg_candidate != '-'
            
            if is_likely_option:
                # If it's an option, but NOT path-like (doesn't contain typical path indicators)
                if not (arg_candidate.startswith(('./-', '../-')) or \
                          '/' in arg_candidate or \
                          '~' in arg_candidate):
                    if verbose: print(f"  Skipping argument '{original_arg_for_log}' as it looks like a non-path option.", file=sys.stderr)
                    continue
            
            path_identified_str = None

            # Rule 1 & 2: Explicit paths (starts with ~/, /, ./, ../) or contains /
            if arg_candidate.startswith(('~', '/', './', '../')) or '/' in arg_candidate:
                path_identified_str = arg_candidate
                if verbose: print(f"  Arg '{original_arg_for_log}': Matched Rule 1/2 (explicit path structure).", file=sys.stderr)
            
            # Rule 3: Contains a dot (like file.ext) and isn't an obvious non-path
            elif '.' in arg_candidate and \
                 not arg_candidate.startswith('-') and \
                 not re.fullmatch(r"\d+(\.\d+)*", arg_candidate) and \
                 not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}(:\d+)?", arg_candidate) and \
                 not any(c in arg_candidate for c in ' "$`*?()[]{}<>|&;!\\'): # Ensure clean token
                path_identified_str = arg_candidate
                if verbose: print(f"  Arg '{original_arg_for_log}': Matched Rule 3 (contains '.').", file=sys.stderr)

            # Rule 4: Argument to common cd-like commands (and not an option).
            # Applied only if not already identified by stronger rules.
            cd_like_commands = ['cd', 'pushd', 'j', 'z', 'zoxide', 'cdd', 'cddl', 'cds', 'up'] # User might extend
            if not path_identified_str and \
               command_name in cd_like_commands and \
               i > 0 and not arg_candidate.startswith('-'):
                 # Check if this 'arg_candidate' is the primary non-option argument.
                 is_main_target_arg = True
                 for j_idx in range(1, i): 
                     if not args[j_idx].startswith('-'): 
                         is_main_target_arg = False
                         break
                 if is_main_target_arg:
                    path_identified_str = arg_candidate
                    if verbose: print(f"  Arg '{original_arg_for_log}': Matched Rule 4 (cd-like command argument).", file=sys.stderr)
            
            if path_identified_str:
                try:
                    expanded_path = os.path.expanduser(path_identified_str)
                    normalized_path = os.path.normpath(expanded_path)

                    if normalized_path not in seen_paths:
                        seen_paths.add(normalized_path)
                        collected_paths.append(normalized_path)
                        if verbose: print(f"    Collected unique path: '{normalized_path}'", file=sys.stderr)
                    elif verbose:
                        print(f"    Path '{normalized_path}' from '{original_arg_for_log}' already collected, skipping.", file=sys.stderr)
                except Exception as e: 
                    if verbose:
                        print(f"    Error processing path candidate '{path_identified_str}': {e}", file=sys.stderr)
    
    if verbose:
        print(f"Total unique paths collected from history: {len(collected_paths)}", file=sys.stderr)
    return collected_paths

def main():
    parser = argparse.ArgumentParser(
        description="Finds a historical path from Atuin and optionally runs a command with it or prints it.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-l', '--limit', type=int, default=50,
        help="Number of recent history entries to search. (Default: 50)"
    )
    parser.add_argument(
        '-i', '--index', type=int, default=1,
        help="Which matching path to use (1-based). 1 is the most recent. (Default: 1)"
    )
    parser.add_argument(
        '-p', '--pattern', type=str, default=None,
        help="Glob pattern to filter paths (e.g., '*.py', 'docs/*'). Case-sensitive on Unix-like systems."
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help="Print verbose output to stderr, including processing steps and paths found."
    )
    parser.add_argument(
        'command_template', nargs='*',
        help="The command to run. Use '{}' as a placeholder for the found path.\n"
             "If '{}' is not present, the path will be appended to the command.\n"
             "If no command is provided, or if 'rhp-insert' is given (can be anywhere in template),\n"
             "the script prints the path. 'rhp-insert' takes precedence.\n"
             "Example: 'nvim {}' or 'ls -lh' or 'rhp-insert'"
    )

    args = parser.parse_args()

    # Determine if in "insert mode" (print path to stdout)
    # 'rhp-insert' can be anywhere if present.
    is_insert_mode = not args.command_template or 'rhp-insert' in args.command_template

    if args.verbose:
        print("Verbose mode enabled.", file=sys.stderr)
        print(f"Parsed Args: {args}", file=sys.stderr)
        print(f"Insert mode: {is_insert_mode}", file=sys.stderr)

    all_historical_paths = get_all_historical_paths(history_limit=args.limit, verbose=args.verbose)

    if not all_historical_paths:
        print("No paths identified in the scanned history.", file=sys.stderr)
        print("Error: No paths found in history.", file=sys.stderr)
        return 1

    filtered_paths = []
    if args.pattern:
        if args.verbose: print(f"Filtering {len(all_historical_paths)} paths with pattern: '{args.pattern}'", file=sys.stderr)
        for path_candidate in all_historical_paths:
            normalized_for_match = os.path.normpath(path_candidate) # e.g., './file.txt' -> 'file.txt'
            if fnmatch.fnmatch(path_candidate, args.pattern) or \
               fnmatch.fnmatch(normalized_for_match, args.pattern) or \
               fnmatch.fnmatch(os.path.basename(path_candidate), args.pattern):
                filtered_paths.append(path_candidate) # Store original form for output
        
        if args.verbose: print(f"Paths after pattern filtering: {len(filtered_paths)} found.", file=sys.stderr)
        if not filtered_paths:
            print(f"Error: No paths found matching pattern '{args.pattern}'.", file=sys.stderr)
            return 1
    else:
        filtered_paths = all_historical_paths
        if args.verbose: print(f"No pattern specified, using all {len(filtered_paths)} found paths.", file=sys.stderr)

    if args.index <= 0:
        print("Error: --index must be a positive integer (1-based).", file=sys.stderr)
        return 1
    
    selected_path_str = None
    try:
        selected_path_str = filtered_paths[args.index - 1] # 1-based index from user
        if args.verbose: print(f"Selected path at 1-based index {args.index}: '{selected_path_str}'", file=sys.stderr)
    except IndexError:
        msg = f"Error: Not enough paths to satisfy index {args.index}. "
        msg += f"Found {len(filtered_paths)} paths"
        if args.pattern: msg += f" matching pattern '{args.pattern}'."
        else: msg += "."
        print(msg, file=sys.stderr)
        return 1
        
    if is_insert_mode:
        print(selected_path_str) # Output path to stdout
        return 0

    # --- Execute command ---
    # Remove 'rhp-insert' if it was part of the command_template for execution
    actual_command_template = [part for part in args.command_template if part != 'rhp-insert']
    if not actual_command_template: # Should not happen if not is_insert_mode, but safety check
        print("Error: No command to execute after processing 'rhp-insert'.", file=sys.stderr)
        return 1

    command_to_run = []
    placeholder_used = False
    for part in actual_command_template:
        if '{}' in part:
            command_to_run.append(part.replace('{}', selected_path_str))
            placeholder_used = True
        else:
            command_to_run.append(part)

    if not placeholder_used:
        command_to_run.append(selected_path_str)

    if args.verbose:
        quoted_command = ' '.join(shlex.quote(c) for c in command_to_run)
        print(f"Executing: {quoted_command}", file=sys.stderr)

    try:
        # For potentially interactive commands, Popen might offer more control,
        # but 'run' often works fine and is simpler.
        # Set check=False to manually handle return codes.
        process = subprocess.run(command_to_run, check=False)
        return process.returncode 
    except FileNotFoundError:
        print(f"Error: Command '{command_to_run[0]}' not found.", file=sys.stderr)
        return 127
    # CalledProcessError is not raised due to check=False.
    except Exception as e: # Catch other execution errors
        print(f"An error occurred while trying to run the command '{' '.join(command_to_run)}': {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
