# rgcodeblock_cli.py
import subprocess
import json
import argparse
import os
import sys
from collections import defaultdict
import shlex
import re

# Import from our new library
import rgcodeblock_lib as rgc_lib

# --- ANSI Color Codes ---
COLOR_SEPARATOR_FANCY = "\033[1;34m"
COLOR_SEPARATOR_SIMPLE = "\033[0;34m"
COLOR_LINE_NUMBER = "\033[0;36m"
COLOR_STATS_HEADER = "\033[1;32m"
COLOR_STATS_KEY = "\033[0;32m"
RESET_COLOR_ANSI = "\033[0m"
DEFAULT_HIGHLIGHT_COLOR_CODE_STR = "1;31"

# --- Statistics Collection ---
STATS = {
    "total_rg_matches": 0,
    "unique_blocks_processed": 0,
    "matches_by_lang_type": defaultdict(int),
    "files_with_matches_by_ext": defaultdict(set),
    "blocks_extracted_count": 0,
    "fallback_to_context_count": 0,
    "total_extracted_block_lines": 0,
    "processed_files": set(),
    "blocks_truncated_max_lines": 0,
}

# --- Helper functions for CLI output ---
def highlight_text_in_line(line: str, texts_to_highlight: list[str], ansi_color_sequence: str) -> str:
    """Highlights all occurrences of multiple texts in a line."""
    if not texts_to_highlight: return line
    modified_line = line
    for text_to_highlight in sorted(list(set(texts_to_highlight)), key=len, reverse=True):
        if not text_to_highlight: continue
        try:
            escaped_text = re.escape(text_to_highlight)
            modified_line = re.sub(f"({escaped_text})", f"{ansi_color_sequence}\\1{RESET_COLOR_ANSI}", modified_line)
        except re.error:
            pass # Ignore regex errors from bad highlight text
    return modified_line

def print_context_fallback(
    lines_with_newlines: list[str],
    match_line_0idx: int,
    texts_to_highlight: list[str],
    ansi_color_sequence: str,
    num_context_lines: int,
    args: argparse.Namespace
):
    """Prints N lines of context around the match_line_0idx."""
    start_slice = max(0, match_line_0idx - num_context_lines)
    end_slice = min(len(lines_with_newlines), match_line_0idx + num_context_lines + 1)

    for i in range(start_slice, end_slice):
        line_to_print = lines_with_newlines[i].rstrip('\n')
        line_prefix = ""
        if args.line_numbers:
            line_prefix = f"{COLOR_LINE_NUMBER}{i+1:>{4}}{RESET_COLOR_ANSI} | "
        highlighted_line = highlight_text_in_line(line_to_print, texts_to_highlight, ansi_color_sequence)
        print(f"{line_prefix}{highlighted_line}")


def format_block_output(
    block_lines: list[str],
    texts_to_highlight: list[str],
    highlight_ansi_sequence: str,
    original_start_line_1idx: int,
    args: argparse.Namespace
) -> list[str]:
    """Formats the extracted block for printing, applies truncation and line numbers."""
    output_lines = []
    effective_block_lines = block_lines
    lines_shown_at_start_count = len(block_lines) # Default if no truncation
    lines_shown_at_end_count = 0

    if args.max_block_lines is not None and len(block_lines) > args.max_block_lines:
        if args.max_block_lines == 0:
            STATS["blocks_truncated_max_lines"] += 1
            return [] # Signal fallback

        max_lines = args.max_block_lines
        # Revised truncation logic
        if max_lines < 3: # Cannot show start, ellipsis, and end
            if max_lines == 1: show_start = 1; show_end = 0
            else: show_start = 1; show_end = 1 # max_lines == 2
        else: # max_lines >= 3, can afford ellipsis
            show_start = (max_lines - 1 + 1) // 2  # ceil((max_lines-1)/2)
            show_end = (max_lines - 1) // 2       # floor((max_lines-1)/2)


        lines_shown_at_start = block_lines[:show_start]
        lines_shown_at_end = block_lines[-show_end:] if show_end > 0 else []

        lines_shown_at_start_count = len(lines_shown_at_start)
        lines_shown_at_end_count = len(lines_shown_at_end)

        num_original_block_lines_not_shown = len(block_lines) - (lines_shown_at_start_count + lines_shown_at_end_count)

        if num_original_block_lines_not_shown > 0 and max_lines >=3 : # Only add ellipsis if space and lines hidden
            ellipsis_line = f"... ({num_original_block_lines_not_shown} lines truncated) ...\n"
            effective_block_lines = lines_shown_at_start + [ellipsis_line] + lines_shown_at_end
            STATS["blocks_truncated_max_lines"] += 1
        else: # Not enough lines to truncate meaningfully or max_lines too small for ellipsis
            effective_block_lines = block_lines[:max_lines] # Just take the first N lines
            lines_shown_at_start_count = len(effective_block_lines) # All shown are from start
            lines_shown_at_end_count = 0 # No end segment if simply capped


    for i, line_content in enumerate(effective_block_lines):
        line_to_print = line_content.rstrip('\n')
        line_prefix = ""
        current_original_line_num_str = "    " # Default for ellipsis line

        if args.line_numbers and "..." not in line_to_print:
            # Determine original line number for this displayed line
            if i < lines_shown_at_start_count: # This line is from the "start" segment
                current_original_line_num = original_start_line_1idx + i
                current_original_line_num_str = f"{current_original_line_num:>{4}}"
            # This line is from the "end" segment (if truncation happened)
            elif lines_shown_at_end_count > 0 and i >= (len(effective_block_lines) - lines_shown_at_end_count):
                # Calculate its original index relative to the full `block_lines` list
                original_block_idx = len(block_lines) - (len(effective_block_lines) - i)
                current_original_line_num = original_start_line_1idx + original_block_idx
                current_original_line_num_str = f"{current_original_line_num:>{4}}"
            else: # Line is not part of start/end segments of a truncated block (i.e., block not truncated)
                 current_original_line_num = original_start_line_1idx + i
                 current_original_line_num_str = f"{current_original_line_num:>{4}}"
        if args.line_numbers:
            line_prefix = f"{COLOR_LINE_NUMBER}{current_original_line_num_str}{RESET_COLOR_ANSI} | "

        highlighted_line = highlight_text_in_line(line_to_print, texts_to_highlight, highlight_ansi_sequence)
        output_lines.append(f"{line_prefix}{highlighted_line}")
    return output_lines


def list_supported_languages():
    """Prints supported languages and their extensions using definitions from the library."""
    print(f"{COLOR_STATS_HEADER}Supported Language Types and Associated Extensions:{RESET_COLOR_ANSI}")
    for lang, details in sorted(rgc_lib.LANGUAGE_DEFINITIONS.items()):
        if lang == "unknown": continue
        ext_list = ", ".join(details["exts"]) if details["exts"] else "N/A"
        notes = f" ({details['notes']})" if details.get("notes") else ""
        print(f"  {COLOR_STATS_KEY}{lang:<10}{RESET_COLOR_ANSI}: {ext_list}{notes}")


def print_statistics(args: argparse.Namespace): # <<< ACCEPTS args OBJECT
    """Prints collected statistics at the end."""
    if not STATS["total_rg_matches"] and not len(rgc_lib.OPTIONAL_LIBRARY_NOTES):
        if sys.stdout.isatty():
             print("No ripgrep matches found or operations performed to generate statistics.")
        return

    sep_style_for_stats = args.sep_style # <<< USES args DIRECTLY
    print(f"\n{get_match_separator(sep_style_for_stats, header_text='Run Statistics')}")
    print(f"{COLOR_STATS_KEY}Total Ripgrep Matches Found:{RESET_COLOR_ANSI} {STATS['total_rg_matches']}")
    print(f"{COLOR_STATS_KEY}Unique Code Blocks Processed:{RESET_COLOR_ANSI} {STATS['unique_blocks_processed']}")
    print(f"{COLOR_STATS_KEY}Unique Files Containing Matches:{RESET_COLOR_ANSI} {len(STATS['processed_files'])}")
    if STATS['matches_by_lang_type']:
        print(f"{COLOR_STATS_KEY}Blocks Triggered by Language Type (first match basis):{RESET_COLOR_ANSI}")
        for lang, count in sorted(STATS['matches_by_lang_type'].items()):
            print(f"  - {lang}: {count}")
    if STATS['files_with_matches_by_ext']:
        print(f"{COLOR_STATS_KEY}Unique Files per Extension with Matches:{RESET_COLOR_ANSI}")
        for ext, files_set in sorted(STATS['files_with_matches_by_ext'].items()):
            print(f"  - .{ext if ext else '(no_ext)'}: {len(files_set)}")
    print(f"{COLOR_STATS_KEY}Blocks Successfully Extracted:{RESET_COLOR_ANSI} {STATS['blocks_extracted_count']}")
    if STATS['blocks_truncated_max_lines'] > 0:
        print(f"{COLOR_STATS_KEY}Blocks Truncated (--max-block-lines):{RESET_COLOR_ANSI} {STATS['blocks_truncated_max_lines']}")
    print(f"{COLOR_STATS_KEY}Fell Back to Context View:{RESET_COLOR_ANSI} {STATS['fallback_to_context_count']}")
    if STATS['blocks_extracted_count'] > 0:
        avg_len = (STATS['total_extracted_block_lines'] / STATS['blocks_extracted_count']) if STATS['blocks_extracted_count'] else 0
        print(f"{COLOR_STATS_KEY}Average Original Extracted Block Length (lines):{RESET_COLOR_ANSI} {avg_len:.2f}")
    if rgc_lib.OPTIONAL_LIBRARY_NOTES:
        print(f"\n{get_match_separator(sep_style_for_stats, header_text='Notes')}")
        for msg in sorted(list(rgc_lib.OPTIONAL_LIBRARY_NOTES)):
            print(f"{COLOR_STATS_KEY}Note:{RESET_COLOR_ANSI} {msg}")
    print(f"{get_match_separator(sep_style_for_stats, end=True, is_footer=True)}")


def process_rg_output_line(line_json_str: str, original_rg_pattern: str) -> dict | None:
    """Parses a single rg JSON line and returns structured match info."""
    try: data = json.loads(line_json_str)
    except json.JSONDecodeError: sys.stderr.write(f"Warning: Bad rg JSON: {line_json_str[:70]}...\n"); return None
    if data.get("type") != "match": return None
    match_data = data.get("data", {}); file_path = match_data.get("path", {}).get("text"); match_line_1idx = match_data.get("line_number")
    text_to_highlight = original_rg_pattern
    submatches = match_data.get("submatches", [])
    if submatches and isinstance(submatches, list) and len(submatches) > 0:
        first_submatch_text = submatches[0].get("match", {}).get("text")
        if first_submatch_text is not None: text_to_highlight = first_submatch_text
    if not all([file_path, isinstance(match_line_1idx, int)]): sys.stderr.write(f"Warning: Incomplete rg data: {data}\n"); return None
    STATS["total_rg_matches"] += 1
    return {"file_path": file_path, "match_line_1idx": match_line_1idx, "text_to_highlight": text_to_highlight, "original_pattern": original_rg_pattern}


def get_match_separator(style: str, end: bool = False, is_footer: bool = False, header_text: str | None = None) -> str:
    """Generates a separator string based on style."""
    if style == "none": return ""
    width = 44; default_header_text = "Match"
    if style == "simple": return f"{COLOR_SEPARATOR_SIMPLE}{'-'*width}{RESET_COLOR_ANSI}"
    if header_text: text_to_center = header_text
    elif end and is_footer: return f"{COLOR_SEPARATOR_FANCY}╚{'═'*width}╝{RESET_COLOR_ANSI}"
    elif end: return f"{COLOR_SEPARATOR_FANCY}╚{'═'*width}╝{RESET_COLOR_ANSI}"
    else: text_to_center = default_header_text
    padding_total = max(0, width - len(text_to_center) - 2)
    padding_left = padding_total // 2; padding_right = padding_total - padding_left
    char = "═"; bookend_start, bookend_end = "╠", "╣"
    if end: bookend_start, bookend_end = "╚", "╝"
    return f"{COLOR_SEPARATOR_FANCY}{bookend_start}{char*padding_left} {text_to_center} {char*padding_right}{bookend_end}{RESET_COLOR_ANSI}"


def print_match_header(match_info: dict, file_path: str, args_sep_style: str, highlights: list[str] | None = None):
    """Prints the standardized header for a match block/context."""
    print(f"{COLOR_STATS_KEY}File:{RESET_COLOR_ANSI} {file_path}:{match_info['match_line_1idx']}")
    if highlights: display_texts = sorted(list(set(highlights)))
    else: display_texts = [match_info['text_to_highlight']]
    texts_str = ", ".join(f'"{t}"' for t in display_texts[:3])
    if len(display_texts) > 3: texts_str += ", ..."
    print(f"{COLOR_STATS_KEY}Highlight(s) ({len(display_texts)}):{RESET_COLOR_ANSI} {texts_str}")
    if args_sep_style != "none":
        line_char = "─" if args_sep_style == "fancy" else "-"; width=20
        sep_color = COLOR_SEPARATOR_FANCY if args_sep_style == "fancy" else COLOR_SEPARATOR_SIMPLE
        print(f"{sep_color}{line_char*width}{RESET_COLOR_ANSI}")

# This was causing a NameError in main_processing_loop
def get_info_separator_line(style: str, type_key: str = "full") -> str: # Changed arg name 'type' to 'type_key'
    """Gets a separator line string for info messages based on style."""
    if style == "none": return ""
    width = 20 # Default short separator width for info lines
    color = COLOR_SEPARATOR_FANCY if style == "fancy" else COLOR_SEPARATOR_SIMPLE
    char = "─" if style == "fancy" else "-"
    if type_key == "full": width = 44 # Should not be needed if get_match_separator handles this
    # elif type_key == "info_short": width = 20 # Default is already 20
    return f"{color}{char*width}{RESET_COLOR_ANSI}"


def main_processing_loop(rg_output_lines: list[str], args: argparse.Namespace, highlight_ansi_sequence: str):
    """Processes rg matches, groups them, extracts blocks, and prints."""
    all_match_infos = []
    for line_json_str in rg_output_lines:
        if not line_json_str: continue
        match_info = process_rg_output_line(line_json_str, args.pattern)
        if match_info: all_match_infos.append(match_info)
    if not all_match_infos: return

    all_match_infos.sort(key=lambda m: (m['file_path'], m['match_line_1idx']))
    processed_block_regions = set()
    output_results_for_json_format = []
    current_file_path_cache = None
    lines_with_newlines_cache = []
    file_content_str_cache = ""

    for i, primary_match_info in enumerate(all_match_infos):
        is_already_covered = False
        for proc_file, proc_start, proc_end in processed_block_regions:
            if primary_match_info["file_path"] == proc_file and \
               proc_start <= (primary_match_info["match_line_1idx"] - 1) <= proc_end: is_already_covered = True; break
        if is_already_covered and args.format != "json": continue

        if primary_match_info["file_path"] != current_file_path_cache:
            current_file_path_cache = primary_match_info["file_path"]
            STATS["processed_files"].add(current_file_path_cache)
            try:
                with open(current_file_path_cache, 'r', encoding='utf-8', errors='surrogateescape') as f:
                    lines_with_newlines_cache = f.readlines(); f.seek(0); file_content_str_cache = f.read()
            except Exception as e:
                if args.format == "text": print(f"\n{get_match_separator(args.sep_style)}"); print_match_header(primary_match_info, current_file_path_cache, args.sep_style)
                sys.stderr.write(f"Error reading {current_file_path_cache}: {e}\n"); STATS["fallback_to_context_count"] += 1
                if args.format == "text": print(f"{get_match_separator(args.sep_style, end=True)}")
                elif args.format == "json": output_results_for_json_format.append({"file_path": current_file_path_cache, "match_line_number": primary_match_info["match_line_1idx"], "status": "error_reading_file", "error": str(e)})
                current_file_path_cache = None; continue

        lang_type, raw_ext = rgc_lib.get_language_type_from_filename(current_file_path_cache)
        match_line_0idx_for_extraction = primary_match_info["match_line_1idx"] - 1
        extracted_block_lines, block_start_0idx, block_end_0idx = None, -1, -1
        extractor_func = rgc_lib.EXTRACTOR_DISPATCH_MAP.get(lang_type)

        if extractor_func:
            try:
                if lang_type == "python": extracted_block_lines, block_start_0idx, block_end_0idx = extractor_func(lines_with_newlines_cache, file_content_str_cache, target_line_1idx=primary_match_info["match_line_1idx"])
                elif lang_type in ["json", "yaml", "xml"]: extracted_block_lines, block_start_0idx, block_end_0idx = extractor_func(lines_with_newlines_cache, match_line_0idx_for_extraction, file_content_str_cache)
                else: extracted_block_lines, block_start_0idx, block_end_0idx = extractor_func(lines_with_newlines_cache, match_line_0idx_for_extraction)
            except Exception as e_extract: rgc_lib.OPTIONAL_LIBRARY_NOTES.add(f"{lang_type.capitalize()}: Extraction error: {str(e_extract)[:60]}...")

        if extracted_block_lines and block_start_0idx != -1:
            block_region_key = (current_file_path_cache, block_start_0idx, block_end_0idx)
            if block_region_key in processed_block_regions and args.format != "json": continue
            if not block_region_key in processed_block_regions: STATS["unique_blocks_processed"] += 1; STATS["matches_by_lang_type"][lang_type] += 1; STATS["files_with_matches_by_ext"][raw_ext].add(current_file_path_cache)
            texts_to_highlight_in_this_block = set()
            representative_match_for_header = primary_match_info
            for m_info_inner_scan in all_match_infos:
                if m_info_inner_scan["file_path"] == current_file_path_cache and block_start_0idx <= (m_info_inner_scan["match_line_1idx"] - 1) <= block_end_0idx:
                    texts_to_highlight_in_this_block.add(m_info_inner_scan["text_to_highlight"])
                    if m_info_inner_scan["match_line_1idx"] < representative_match_for_header["match_line_1idx"]: representative_match_for_header = m_info_inner_scan
            formatted_lines = format_block_output(extracted_block_lines, list(texts_to_highlight_in_this_block), highlight_ansi_sequence, block_start_0idx + 1, args)
            if not formatted_lines and args.max_block_lines == 0: pass
            elif formatted_lines:
                if not block_region_key in processed_block_regions: STATS["blocks_extracted_count"] += 1; STATS["total_extracted_block_lines"] += len(extracted_block_lines)
                if args.format == "text":
                    if not block_region_key in processed_block_regions:
                        print(f"\n{get_match_separator(args.sep_style)}")
                        print_match_header(representative_match_for_header, current_file_path_cache, args.sep_style, list(texts_to_highlight_in_this_block))
                        for line_in_output in formatted_lines: print(line_in_output)
                        print(f"{get_match_separator(args.sep_style, end=True)}")
                elif args.format == "json":
                     if not block_region_key in processed_block_regions:
                         output_results_for_json_format.append({"file_path": current_file_path_cache, "block_start_line": block_start_0idx + 1, "block_end_line": block_end_0idx + 1, "language_type": lang_type, "status": "success", "texts_highlighted_in_block": sorted(list(texts_to_highlight_in_this_block)), "block_lines_original_count": len(extracted_block_lines), "block": [l.rstrip('\n') for l in extracted_block_lines]})
                processed_block_regions.add(block_region_key)
                continue

        is_match_line_covered_by_any_printed_block = False
        for proc_file, proc_start, proc_end in processed_block_regions:
            if primary_match_info["file_path"] == proc_file and proc_start <= match_line_0idx_for_extraction <= proc_end: is_match_line_covered_by_any_printed_block = True; break
        if not is_match_line_covered_by_any_printed_block:
            STATS["fallback_to_context_count"] +=1
            if args.format == "text":
                print(f"\n{get_match_separator(args.sep_style)}")
                print_match_header(primary_match_info, current_file_path_cache, args.sep_style)
                print(f"{get_info_separator_line(args.sep_style, type_key='info_short')}Fallback: Context for '{lang_type}' file.") # <<< Use correct arg name 'type_key'
                print_context_fallback(lines_with_newlines_cache, match_line_0idx_for_extraction, [primary_match_info["text_to_highlight"]], highlight_ansi_sequence, args.context, args)
                print(f"{get_match_separator(args.sep_style, end=True)}")
            elif args.format == "json":
                context_start = max(0, match_line_0idx_for_extraction - args.context)
                context_end = min(len(lines_with_newlines_cache), match_line_0idx_for_extraction + args.context + 1)
                context_lines = [l.rstrip('\n') for l in lines_with_newlines_cache[context_start:context_end]]
                output_results_for_json_format.append({"file_path": current_file_path_cache, "match_line_number": primary_match_info["match_line_1idx"], "language_type": lang_type, "status": "fallback_context", "text_highlighted_in_context": [primary_match_info["text_to_highlight"]], "context_lines": context_lines})

    if args.format == "json":
        print(json.dumps(output_results_for_json_format, indent=2 if sys.stdout.isatty() else None))

def main():
    # Handle --list-languages FIRST to avoid argparse error if pattern is missing
    if "--list-languages" in sys.argv:
        # Need to initialize a minimal parser for list_supported_languages if it uses args for colors
        # Or make list_supported_languages independent of args.
        # For now, assume list_supported_languages doesn't need args.
        list_supported_languages()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="rgcodeblock",
        description="Finds enclosing code blocks for rg matches. Supports various languages and output formats.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("pattern", help="Pattern for ripgrep.")
    parser.add_argument("path", nargs="?", default=".", help="File/directory to search (default: .).")
    parser.add_argument("-c", "--color", default=DEFAULT_HIGHLIGHT_COLOR_CODE_STR, help=f"ANSI color code for highlight (default: '{DEFAULT_HIGHLIGHT_COLOR_CODE_STR}').")
    parser.add_argument("-C", "--context", type=int, default=3, metavar="NUM", help="Context lines for fallback (default: 3).")
    parser.add_argument("-s", "--stats", action="store_true", help="Display statistics at the end.")
    filter_group = parser.add_argument_group('Filtering Options (passed to rg)')
    filter_group.add_argument("-I", "--include-ext", action="append", metavar="EXT", help="Include ONLY files with this extension (no dot, e.g., 'py'). Multiple allowed.")
    filter_group.add_argument("-E", "--exclude-ext", action="append", metavar="EXT", help="Exclude files with this extension (no dot, e.g., 'log'). Multiple allowed.")
    filter_group.add_argument("-X", "--exclude-path", action="append", metavar="GLOB", help="Exclude files/paths matching GLOB (rg's --glob '!GLOB'). Multiple allowed.")
    filter_group.add_argument("--rg-args", type=str, default="", help="String of additional arguments to pass to ripgrep (e.g., '-i --hidden'). Quote if it contains spaces.")
    format_group = parser.add_argument_group('Formatting Options')
    format_group.add_argument("-f", "--format", choices=["text", "json"], default="text", help="Output format (default: text).")
    format_group.add_argument("-n", "--line-numbers", action="store_true", help="Show line numbers for extracted blocks/context.")
    format_group.add_argument("--sep-style", choices=["fancy", "simple", "none"], default="fancy", help="Separator style between matches (default: fancy).")
    format_group.add_argument("-M", "--max-block-lines", type=int, default=None, metavar="NUM", help="Max lines for extracted block (0=force fallback, >0 truncate). Default: no limit.")
    parser.add_argument("--list-languages", action="store_true", help="List supported languages and associated extensions, then exit.")

    args = parser.parse_args() # Now parse after handling --list-languages

    highlight_ansi_sequence = f"\033[{args.color}m"
    rg_cmd_base = ["rg", "--json"]
    rg_cmd_user_extras = []
    if args.rg_args:
        try: rg_cmd_user_extras = shlex.split(args.rg_args)
        except Exception as e_shlex: sys.stderr.write(f"Error parsing --rg-args: {e_shlex}.\n"); sys.exit(1)

    rg_cmd_filters = []
    if args.include_ext:
        for i, ext_type in enumerate(args.include_ext): rg_cmd_filters.extend([f"--type-add", f"rgcbinclude{i}:*.{ext_type}", "-t", f"rgcbinclude{i}"])
    if args.exclude_ext:
        for i, ext_type in enumerate(args.exclude_ext): rg_cmd_filters.extend([f"--type-add", f"rgcbexclude{i}:*.{ext_type}", "-T", f"rgcbexclude{i}"])
    if args.exclude_path:
        for glob_pattern in args.exclude_path: rg_cmd_filters.extend(["--glob", f"!{glob_pattern}"])

    rg_cmd = rg_cmd_base + rg_cmd_user_extras + rg_cmd_filters

    # Check if pattern/path likely provided in rg_args
    # Use rg_cmd_user_extras as it holds the shlex-split args
    pattern_likely_in_extras = any(args.pattern == p for p in rg_cmd_user_extras if not p.startswith('-'))
    path_likely_in_extras = any(args.path == p for p in rg_cmd_user_extras if not p.startswith('-'))

    if not pattern_likely_in_extras: rg_cmd.append(args.pattern)
    if not path_likely_in_extras: rg_cmd.append(args.path)

    try:
        process = subprocess.run(rg_cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='surrogateescape')
    except FileNotFoundError: sys.stderr.write("Error: ripgrep (rg) not found.\n"); sys.exit(2)

    if process.returncode > 1:
        err_msg_obj = {"error": "ripgrep_execution_error", "stderr": process.stderr, "command_used": rg_cmd, "returncode": process.returncode}
        if args.format == "text": sys.stderr.write(f"Error from ripgrep (rc={process.returncode}):\n{process.stderr}\nCmd: {' '.join(rg_cmd)}\n")
        elif args.format == "json": print(json.dumps(err_msg_obj), file=sys.stderr)
        sys.exit(process.returncode)

    rg_output_lines = process.stdout.strip().split('\n') if process.stdout.strip() else []
    if not rg_output_lines :
        if args.stats: print_statistics(args) # Pass args
        if args.format == "json": print(json.dumps([]))
        sys.exit(0)

    main_processing_loop(rg_output_lines, args, highlight_ansi_sequence)

    if args.stats:
        print_statistics(args) # Pass args

    final_exit_code = 0
    if STATS["total_rg_matches"] == 0:
        if process.returncode == 1 : final_exit_code = 0
        else: final_exit_code = 0
    sys.exit(final_exit_code)

if __name__ == "__main__":
    sys.exit(main())
