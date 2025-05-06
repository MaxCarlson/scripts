# rgcodeblock_cli.py
import subprocess
import json
import argparse
import os
import sys
from collections import defaultdict
import shlex
import re # For highlight_text_in_line

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
    "matches_by_lang_type": defaultdict(int), # Counts unique blocks triggered by each lang
    "files_with_matches_by_ext": defaultdict(set),
    "blocks_extracted_count": 0,
    "fallback_to_context_count": 0,
    "total_extracted_block_lines": 0, # Sum of original lines of successfully extracted blocks
    "processed_files": set(),
    "blocks_truncated_max_lines": 0,
}

# --- Helper functions for CLI output ---
def highlight_text_in_line(line: str, texts_to_highlight: list[str], ansi_color_sequence: str) -> str:
    """Highlights all occurrences of multiple texts in a line."""
    if not texts_to_highlight: return line
    modified_line = line
    # Highlight longest texts first to handle substrings correctly (e.g., "func" vs "my_func")
    for text_to_highlight in sorted(list(set(texts_to_highlight)), key=len, reverse=True):
        if not text_to_highlight: continue # Skip empty strings
        try:
            escaped_text = re.escape(text_to_highlight)
            # This regex replacement can be tricky if ANSI codes are already present.
            # A more robust solution might involve finding match indices and then reconstructing the string.
            # For now, sequential replacement is used.
            modified_line = re.sub(f"({escaped_text})", f"{ansi_color_sequence}\\1{RESET_COLOR_ANSI}", modified_line)
        except re.error:
            pass # Ignore regex errors from bad highlight text (e.g. unmatched parenthesis if not escaped properly)
    return modified_line

def print_context_fallback(
    lines_with_newlines: list[str], 
    match_line_0idx: int,
    texts_to_highlight: list[str], # List of specific texts that triggered this fallback context
    ansi_color_sequence: str,
    num_context_lines: int, 
    args: argparse.Namespace # For --line-numbers flag
):
    """Prints N lines of context around the match_line_0idx."""
    start_slice = max(0, match_line_0idx - num_context_lines)
    end_slice = min(len(lines_with_newlines), match_line_0idx + num_context_lines + 1)

    for i in range(start_slice, end_slice):
        line_to_print = lines_with_newlines[i].rstrip('\n')
        line_prefix = ""
        if args.line_numbers:
            line_prefix = f"{COLOR_LINE_NUMBER}{i+1:>{4}}{RESET_COLOR_ANSI} | "
        
        # In fallback context, highlight all relevant texts that appear on this line
        highlighted_line = highlight_text_in_line(line_to_print, texts_to_highlight, ansi_color_sequence)
        print(f"{line_prefix}{highlighted_line}")


def format_block_output(
    block_lines: list[str], 
    texts_to_highlight: list[str], # All texts that were matched by rg within this block
    highlight_ansi_sequence: str, 
    original_start_line_1idx: int, # 1-indexed start line of the block in the original file
    args: argparse.Namespace
) -> list[str]: # Returns list of formatted lines, or empty list if fallback is forced
    """Formats the extracted block for printing, applies truncation and line numbers."""
    output_lines = []
    effective_block_lines = block_lines
    
    lines_shown_at_start_count = 0 # For correct line numbering during truncation
    lines_shown_at_end_count = 0

    if args.max_block_lines is not None and len(block_lines) > args.max_block_lines:
        if args.max_block_lines == 0: 
            STATS["blocks_truncated_max_lines"] += 1 # Count it as "truncated" for stats
            return [] # Signal to fallback to context view

        # Truncation logic
        half = args.max_block_lines // 2
        if args.max_block_lines == 1: half = 1 # Show at least one line if max is 1
        elif args.max_block_lines == 2 and half == 1: half = 1 # Ensure we try to show 1 from start, 1 from end
            
        lines_shown_at_start = block_lines[:half]
        lines_shown_at_start_count = len(lines_shown_at_start)
        
        lines_shown_at_end = block_lines[-half:] if half > 0 else [] # Avoid block_lines[0:] if half is 0
        lines_shown_at_end_count = len(lines_shown_at_end)
        
        num_original_block_lines_not_shown = len(block_lines) - (lines_shown_at_start_count + lines_shown_at_end_count)

        if num_original_block_lines_not_shown > 0 :
            # Only add ellipsis if there are actually lines hidden between start and end segments
            ellipsis_line = f"... ({num_original_block_lines_not_shown} lines truncated) ...\n"
            effective_block_lines = lines_shown_at_start + \
                                  [ellipsis_line] + \
                                  lines_shown_at_end
            STATS["blocks_truncated_max_lines"] += 1
        else: # Not enough lines to make truncation with ellipsis meaningful, just take the first max_block_lines
            effective_block_lines = block_lines[:args.max_block_lines]
            # No ellipsis needed if it just fits or shows slightly less than max_block_lines

    for i, line_content in enumerate(effective_block_lines):
        line_to_print = line_content.rstrip('\n')
        line_prefix = ""
        
        if args.line_numbers:
            current_original_line_num_str = "    " # Default for ellipsis line
            if "..." not in line_to_print: # Don't number the ellipsis line itself
                # Determine original line number for this displayed line
                if i < lines_shown_at_start_count: # This line is from the start segment
                    current_original_line_num = original_start_line_1idx + i
                    current_original_line_num_str = f"{current_original_line_num:>{4}}"
                # This line is from the end segment (if truncation happened)
                elif lines_shown_at_end_count > 0 and i >= (len(effective_block_lines) - lines_shown_at_end_count): 
                    # Calculate its original index relative to the full `block_lines`
                    original_block_idx = len(block_lines) - (len(effective_block_lines) - i)
                    current_original_line_num = original_start_line_1idx + original_block_idx
                    current_original_line_num_str = f"{current_original_line_num:>{4}}"
                else: # Line is not part of start/end segments of a truncated block (i.e., block not truncated or this is middle)
                     current_original_line_num = original_start_line_1idx + i
                     current_original_line_num_str = f"{current_original_line_num:>{4}}"
            line_prefix = f"{COLOR_LINE_NUMBER}{current_original_line_num_str}{RESET_COLOR_ANSI} | "

        highlighted_line = highlight_text_in_line(line_to_print, texts_to_highlight, highlight_ansi_sequence)
        output_lines.append(f"{line_prefix}{highlighted_line}")
    return output_lines

def list_supported_languages():
    """Prints supported languages and their extensions using definitions from the library."""
    print(f"{COLOR_STATS_HEADER}Supported Language Types and Associated Extensions:{RESET_COLOR_ANSI}")
    # Access LANGUAGE_DEFINITIONS from the imported library module
    for lang, details in sorted(rgc_lib.LANGUAGE_DEFINITIONS.items()):
        if lang == "unknown": continue # Typically don't list "unknown" as a supported language
        ext_list = ", ".join(details["exts"]) if details["exts"] else "N/A"
        notes = f" ({details['notes']})" if details.get("notes") else ""
        print(f"  {COLOR_STATS_KEY}{lang:<10}{RESET_COLOR_ANSI}: {ext_list}{notes}")

def print_statistics():
    """Prints collected statistics at the end."""
    if not STATS["total_rg_matches"] and not len(rgc_lib.OPTIONAL_LIBRARY_NOTES):
        if sys.stdout.isatty(): # Only print if interactive and truly nothing happened
             print("No ripgrep matches found or operations performed to generate statistics.")
        return
        
    # Use fancy separator for stats header
    print(f"\n{get_match_separator(args_for_main_thread.sep_style if 'args_for_main_thread' in globals() else 'fancy', header_text='Run Statistics')}")
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
        print(f"{COLOR_STATS_KEY}Blocks Truncated (due to --max-block-lines):{RESET_COLOR_ANSI} {STATS['blocks_truncated_max_lines']}")
    print(f"{COLOR_STATS_KEY}Fell Back to Context View:{RESET_COLOR_ANSI} {STATS['fallback_to_context_count']}")
    
    if STATS['blocks_extracted_count'] > 0:
        avg_len = STATS['total_extracted_block_lines'] / STATS['blocks_extracted_count']
        print(f"{COLOR_STATS_KEY}Average Original Extracted Block Length (lines):{RESET_COLOR_ANSI} {avg_len:.2f}")
    
    # Access OPTIONAL_LIBRARY_NOTES from the imported library module
    if rgc_lib.OPTIONAL_LIBRARY_NOTES:
        print(f"\n{get_match_separator(args_for_main_thread.sep_style if 'args_for_main_thread' in globals() else 'fancy', header_text='Notes')}")
        for msg in sorted(list(rgc_lib.OPTIONAL_LIBRARY_NOTES)):
            print(f"{COLOR_STATS_KEY}Note:{RESET_COLOR_ANSI} {msg}")
    print(f"{get_match_separator(args_for_main_thread.sep_style if 'args_for_main_thread' in globals() else 'fancy', end=True, is_footer=True)}")


def process_rg_output_line(line_json_str: str, original_rg_pattern: str) -> dict | None:
    """Parses a single rg JSON line and returns structured match info."""
    try:
        data = json.loads(line_json_str)
    except json.JSONDecodeError:
        # This should be logged or printed to stderr without breaking flow for other lines
        sys.stderr.write(f"Warning: Could not parse rg JSON output line: {line_json_str[:70]}...\n")
        return None
        
    if data.get("type") != "match":
        return None # Skip begin, end, summary lines from rg

    match_data = data.get("data", {})
    file_path = match_data.get("path", {}).get("text")
    match_line_1idx = match_data.get("line_number") # rg provides 1-indexed line numbers
    
    # Determine the specific text that rg matched for precise highlighting.
    text_to_highlight_for_this_match = original_rg_pattern # Fallback to the original pattern
    submatches = match_data.get("submatches", [])
    if submatches and isinstance(submatches, list) and len(submatches) > 0:
        # The first submatch ([0]) usually contains the overall matched string by rg.
        first_submatch_text = submatches[0].get("match", {}).get("text")
        if first_submatch_text is not None: # Ensure it's not None before assigning
             text_to_highlight_for_this_match = first_submatch_text

    if not all([file_path, isinstance(match_line_1idx, int)]):
        sys.stderr.write(f"Warning: Incomplete match data from rg: {data}\n")
        return None
    
    STATS["total_rg_matches"] += 1 # Increment for every valid "match" type line from rg
    return {
        "file_path": file_path,
        "match_line_1idx": match_line_1idx,
        "text_to_highlight": text_to_highlight_for_this_match,
        "original_pattern": original_rg_pattern # Keep for context if needed
    }

def get_match_separator(style: str, end: bool = False, is_footer: bool = False, header_text: str | None = None) -> str:
    """Generates a separator string based on style."""
    if style == "none": return ""
    
    width = 44 # Approximate width for fancy separators
    if style == "simple":
        return f"{COLOR_SEPARATOR_SIMPLE}{'-'*width}{RESET_COLOR_ANSI}"
    
    # Fancy style (default)
    default_header_text = "Match"
    if header_text: # For stats sections mostly
        text_to_center = header_text
    elif end and is_footer: # Footer for stats section
        return f"{COLOR_SEPARATOR_FANCY}╚{'═'*width}╝{RESET_COLOR_ANSI}"
    elif end: # End of a match block
        return f"{COLOR_SEPARATOR_FANCY}╚{'═'*width}╝{RESET_COLOR_ANSI}"
    else: # Start of a match block
        text_to_center = default_header_text
        
    padding_total = width - len(text_to_center) - 2 # -2 for ╠/╣ or similar bookends
    if padding_total < 0: padding_total = 0
    padding_left = padding_total // 2
    padding_right = padding_total - padding_left
    
    if header_text: # For custom headers like "Run Statistics"
        return f"{COLOR_SEPARATOR_FANCY}╠{'═'*padding_left} {text_to_center} {'═'*padding_right}╣{RESET_COLOR_ANSI}"
    else: # Default match separator
        return f"{COLOR_SEPARATOR_FANCY}╠{'═'*padding_left} {text_to_center} {'═'*padding_right}╣{RESET_COLOR_ANSI}"


def print_match_header(
    match_info_for_header: dict, # The primary rg match info defining this header
    file_path: str, 
    args_sep_style: str, 
    all_highlights_in_block: list[str] | None = None # All unique texts highlighted in the block
):
    """Prints the standardized header for a match block/context."""
    print(f"{COLOR_STATS_KEY}File:{RESET_COLOR_ANSI} {file_path}:{match_info_for_header['match_line_1idx']}")
    
    # Display the texts that will be highlighted in the upcoming block/context
    if all_highlights_in_block:
        display_texts = sorted(list(set(all_highlights_in_block)))
    else: # Fallback if only one highlight text is known for this header
        display_texts = [match_info_for_header['text_to_highlight']]

    texts_str = ", ".join(f'"{t}"' for t in display_texts[:3]) # Show up to 3
    if len(display_texts) > 3: texts_str += ", ..."
    print(f"{COLOR_STATS_KEY}Highlight(s) ({len(display_texts)}):{RESET_COLOR_ANSI} {texts_str}")
    
    # Print a short separator after the header text
    if args_sep_style != "none":
        line_char = "─" if args_sep_style == "fancy" else "-"
        sep_color = COLOR_SEPARATOR_FANCY if args_sep_style == "fancy" else COLOR_SEPARATOR_SIMPLE
        print(f"{sep_color}{line_char*20}{RESET_COLOR_ANSI}")


def main_processing_loop(rg_output_lines: list[str], args: argparse.Namespace, highlight_ansi_sequence: str):
    """
    Processes rg matches, groups them by potential block, extracts, and prints.
    Handles "highlight all matches in one block" and output formatting.
    """
    all_match_infos = [] # Store dicts from process_rg_output_line
    for line_json_str in rg_output_lines:
        if not line_json_str: continue
        match_info = process_rg_output_line(line_json_str, args.pattern)
        if match_info: all_match_infos.append(match_info)

    if not all_match_infos: # No valid "match" type lines from rg
        return # Stats will reflect total_rg_matches=0

    # Sort all rg matches by file, then by line number. This is crucial for grouping.
    all_match_infos.sort(key=lambda m: (m['file_path'], m['match_line_1idx']))

    processed_block_regions = set() # Stores tuples: (file_path, block_start_0idx, block_end_0idx) to avoid reprinting blocks
    output_results_for_json_format = [] # For --format json

    current_file_path_cache = None
    lines_with_newlines_cache = []
    file_content_str_cache = ""

    for i, primary_match_info in enumerate(all_match_infos):
        # Check if this primary_match_info's line has already been covered by a printed block
        # This requires iterating processed_block_regions.
        # This is a simple skip; more advanced would be to add its highlight to an existing block if applicable.
        # For now, if its line falls in an already printed region, we assume it's covered.
        is_already_covered = False
        for proc_file, proc_start, proc_end in processed_block_regions:
            if primary_match_info["file_path"] == proc_file and \
               proc_start <= (primary_match_info["match_line_1idx"] - 1) <= proc_end:
                is_already_covered = True
                break
        if is_already_covered and args.format != "json": # For JSON, each original match might produce an entry
            continue

        # Load file content if it's a new file
        if primary_match_info["file_path"] != current_file_path_cache:
            current_file_path_cache = primary_match_info["file_path"]
            STATS["processed_files"].add(current_file_path_cache) # Count unique files
            try:
                with open(current_file_path_cache, 'r', encoding='utf-8', errors='surrogateescape') as f:
                    lines_with_newlines_cache = f.readlines()
                    f.seek(0)
                    file_content_str_cache = f.read()
            except Exception as e:
                # Handle file read error for this primary_match_info
                if args.format == "text":
                    print(f"\n{get_match_separator(args.sep_style)}")
                    # Pass primary_match_info directly as it's the one causing this header
                    print_match_header(primary_match_info, current_file_path_cache, args.sep_style)
                sys.stderr.write(f"Error reading {current_file_path_cache}: {e}\n")
                STATS["fallback_to_context_count"] += 1 # Count as a fallback
                if args.format == "text": print(f"{get_match_separator(args.sep_style, end=True)}")
                elif args.format == "json":
                    output_results_for_json_format.append({
                        "file_path": current_file_path_cache, 
                        "match_line_number": primary_match_info["match_line_1idx"],
                        "status": "error_reading_file", "error": str(e)
                    })
                current_file_path_cache = None # Force reload if next match is same file but error was transient
                continue # Skip to next primary_match_info
        
        lang_type, raw_ext = rgc_lib.get_language_type_from_filename(current_file_path_cache)
        match_line_0idx_for_extraction = primary_match_info["match_line_1idx"] - 1
        
        # Attempt block extraction using the library function
        extracted_block_lines, block_start_0idx, block_end_0idx = None, -1, -1
        extractor_func = rgc_lib.EXTRACTOR_DISPATCH_MAP.get(lang_type)
        
        if extractor_func:
            try:
                # Pass necessary args based on extractor needs from rgc_lib
                # target_entity_name is None for rgcodeblock's general "find block around line"
                if lang_type == "python":
                    extracted_block_lines, block_start_0idx, block_end_0idx = extractor_func(
                        lines_with_newlines_cache, file_content_str_cache, 
                        target_line_1idx=primary_match_info["match_line_1idx"] # Python AST uses 1-indexed line
                    )
                elif lang_type in ["json", "yaml", "xml"]: # These might use full content
                    extracted_block_lines, block_start_0idx, block_end_0idx = extractor_func(
                        lines_with_newlines_cache, match_line_0idx_for_extraction, file_content_str_cache
                    )
                else: # brace, ruby, lua typically use line_0idx (0-indexed)
                    extracted_block_lines, block_start_0idx, block_end_0idx = extractor_func(
                        lines_with_newlines_cache, match_line_0idx_for_extraction
                    )
            except Exception as e_extract:
                rgc_lib.OPTIONAL_LIBRARY_NOTES.add(f"{lang_type.capitalize()}: Extraction error for {current_file_path_cache} (near line {match_line_0idx_for_extraction+1}): {str(e_extract)[:60]}...")
                # Fall through, extracted_block_lines will remain None

        if extracted_block_lines and block_start_0idx != -1: # Block successfully extracted
            block_region_key = (current_file_path_cache, block_start_0idx, block_end_0idx)

            # If this exact block region was already printed, we might skip or handle differently for JSON
            if block_region_key in processed_block_regions and args.format != "json":
                continue 
            
            if not block_region_key in processed_block_regions: # First time processing this unique block
                 STATS["unique_blocks_processed"] += 1
                 STATS["matches_by_lang_type"][lang_type] += 1 # Count this block for this lang type
                 STATS["files_with_matches_by_ext"][raw_ext].add(current_file_path_cache)

            # Collect ALL rg matches (text_to_highlight) that fall within this extracted block
            texts_to_highlight_in_this_block = set()
            # The match that "represents" this block for header printing (e.g., earliest match in block)
            representative_match_for_header = primary_match_info 
            
            for m_info_inner_scan in all_match_infos: # Scan all original rg matches
                if m_info_inner_scan["file_path"] == current_file_path_cache and \
                   block_start_0idx <= (m_info_inner_scan["match_line_1idx"] - 1) <= block_end_0idx:
                    texts_to_highlight_in_this_block.add(m_info_inner_scan["text_to_highlight"])
                    # Update representative match if this one is earlier within the same block
                    if m_info_inner_scan["match_line_1idx"] < representative_match_for_header["match_line_1idx"]:
                        representative_match_for_header = m_info_inner_scan
            
            formatted_lines = format_block_output(
                extracted_block_lines, 
                list(texts_to_highlight_in_this_block),
                highlight_ansi_sequence, 
                block_start_0idx + 1, # Original 1-indexed start line of the block
                args
            )

            if not formatted_lines and args.max_block_lines == 0: # Fallback forced by max_block_lines=0
                # The fallback logic below will handle this.
                # To avoid double counting fallback, we don't increment STATS["fallback_to_context_count"] here.
                # Instead, we let the main fallback path catch it.
                pass # Let it fall through to the main fallback logic
            elif formatted_lines: # Successfully formatted (possibly truncated)
                if not block_region_key in processed_block_regions: # First time printing this block
                    STATS["blocks_extracted_count"] += 1
                    STATS["total_extracted_block_lines"] += len(extracted_block_lines) # Original length for stats
                
                if args.format == "text":
                    # Only print the block once for text output, even if multiple rg matches led to it.
                    if not block_region_key in processed_block_regions:
                        print(f"\n{get_match_separator(args.sep_style)}")
                        print_match_header(representative_match_for_header, current_file_path_cache, args.sep_style, list(texts_to_highlight_in_this_block))
                        for line_in_output in formatted_lines: print(line_in_output)
                        print(f"{get_match_separator(args.sep_style, end=True)}")
                elif args.format == "json":
                     # For JSON, we create an entry for this block.
                     # If multiple rg matches point to this same block, they might all be represented by this one JSON entry
                     # if we group by block_region_key. Or, create an entry per original rg match.
                     # Current logic: one entry per unique block, listing all highlights.
                     # If we want one JSON entry PER rg match, this needs adjustment.
                     # Let's make it one JSON entry per unique block for now for consistency with text mode.
                     if not block_region_key in processed_block_regions:
                         output_results_for_json_format.append({
                            "file_path": current_file_path_cache, 
                            "block_start_line": block_start_0idx + 1,
                            "block_end_line": block_end_0idx + 1, 
                            "language_type": lang_type, "status": "success",
                            "texts_highlighted_in_block": sorted(list(texts_to_highlight_in_this_block)),
                            "block_lines_original_count": len(extracted_block_lines),
                            "block": [l.rstrip('\n') for l in extracted_block_lines], # Raw lines
                         })
                processed_block_regions.add(block_region_key)
                continue # Successfully processed this primary_match_info by printing its block (or adding to JSON)
        
        # --- Fallback Condition ---
        # Reaches here if:
        # 1. `extractor_func` was None (unknown lang).
        # 2. `extractor_func` returned `None` for `extracted_block_lines`.
        # 3. `format_block_output` returned empty list (due to `max_block_lines=0`).
        # We only print fallback context if this `primary_match_info`'s line wasn't part of an already printed block.
        
        # Check again if this specific match line is already covered by a printed block.
        # This is important because a match might not extract its OWN block, but might be INSIDE
        # a larger block that WAS extracted by a PREVIOUS rg match.
        is_match_line_covered_by_any_printed_block = False
        for proc_file, proc_start, proc_end in processed_block_regions:
            if primary_match_info["file_path"] == proc_file and \
               proc_start <= match_line_0idx_for_extraction <= proc_end:
                is_match_line_covered_by_any_printed_block = True
                break
        
        if not is_match_line_covered_by_any_printed_block:
            STATS["fallback_to_context_count"] +=1
            if args.format == "text":
                print(f"\n{get_match_separator(args.sep_style)}")
                # For fallback, header is specific to this primary_match_info
                print_match_header(primary_match_info, current_file_path_cache, args.sep_style) 
                print(f"{get_separator_line(args.sep_style, type='info_short')}Fallback: Context for '{lang_type}' file.")
                print_context_fallback(lines_with_newlines_cache, match_line_0idx_for_extraction, 
                                       [primary_match_info["text_to_highlight"]], # Just this match's text
                                       highlight_ansi_sequence, args.context, args)
                print(f"{get_match_separator(args.sep_style, end=True)}")
            elif args.format == "json":
                context_start = max(0, match_line_0idx_for_extraction - args.context)
                context_end = min(len(lines_with_newlines_cache), match_line_0idx_for_extraction + args.context + 1)
                context_lines = [l.rstrip('\n') for l in lines_with_newlines_cache[context_start:context_end]]
                output_results_for_json_format.append({
                    "file_path": current_file_path_cache, 
                    "match_line_number": primary_match_info["match_line_1idx"],
                    "language_type": lang_type, "status": "fallback_context",
                    "text_highlighted_in_context": [primary_match_info["text_to_highlight"]], 
                    "context_lines": context_lines
                })

    # After loop, if format is JSON, print the collected list
    if args.format == "json":
        print(json.dumps(output_results_for_json_format, indent=2 if sys.stdout.isatty() else None))


# To store args for print_statistics if needed globally (not ideal, but for quick fix)
args_for_main_thread = None

def main():
    global args_for_main_thread
    parser = argparse.ArgumentParser(
        prog="rgcodeblock",
        description="Finds enclosing code blocks for rg matches. Supports various languages and output formats.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("pattern", help="Pattern for ripgrep.")
    parser.add_argument("path", nargs="?", default=".", help="File/directory to search (default: .).")
    
    parser.add_argument("-c", "--color", default=DEFAULT_HIGHLIGHT_COLOR_CODE_STR, 
                        help=f"ANSI color code for highlight (default: '{DEFAULT_HIGHLIGHT_COLOR_CODE_STR}').")
    parser.add_argument("-C", "--context", type=int, default=3, metavar="NUM", 
                        help="Context lines for fallback (default: 3).")
    parser.add_argument("-s", "--stats", action="store_true", 
                        help="Display statistics at the end.")
    
    filter_group = parser.add_argument_group('Filtering Options (passed to rg)')
    filter_group.add_argument("-I", "--include-ext", action="append", metavar="EXT", 
                              help="Include ONLY files with this extension (no dot, e.g., 'py'). Multiple allowed.")
    filter_group.add_argument("-E", "--exclude-ext", action="append", metavar="EXT", 
                              help="Exclude files with this extension (no dot, e.g., 'log'). Multiple allowed.")
    filter_group.add_argument("-X", "--exclude-path", action="append", metavar="GLOB", 
                              help="Exclude files/paths matching GLOB (rg's --glob '!GLOB'). Multiple allowed.")
    filter_group.add_argument("--rg-args", type=str, default="", 
                              help="String of additional arguments to pass to ripgrep (e.g., '-i --hidden'). Quote if it contains spaces.")

    format_group = parser.add_argument_group('Formatting Options')
    format_group.add_argument("-f", "--format", choices=["text", "json"], default="text", 
                              help="Output format (default: text).")
    format_group.add_argument("-n", "--line-numbers", action="store_true", 
                              help="Show line numbers for extracted blocks/context.")
    format_group.add_argument("--sep-style", choices=["fancy", "simple", "none"], default="fancy", 
                              help="Separator style between matches (default: fancy).")
    format_group.add_argument("-M", "--max-block-lines", type=int, default=None, metavar="NUM",
                              help="Max lines for extracted block (0=force fallback, >0 truncate). Default: no limit.")

    parser.add_argument("--list-languages", action="store_true", 
                        help="List supported languages and associated extensions, then exit.")
    
    args = parser.parse_args()
    args_for_main_thread = args # For print_statistics to access args.sep_style

    if args.list_languages:
        list_supported_languages()
        sys.exit(0)

    highlight_ansi_sequence = f"\033[{args.color}m"
    
    # Construct rg command
    rg_cmd_base = ["rg", "--json"] # Base, rg output must be JSON for this script
    rg_cmd_user_extras = []
    if args.rg_args:
        try:
            rg_cmd_user_extras = shlex.split(args.rg_args)
        except Exception as e_shlex:
            sys.stderr.write(f"Error parsing --rg-args: {e_shlex}. Ensure proper quoting for arguments with spaces.\n")
            sys.exit(1)

    rg_cmd_filters = []
    # Add our type/glob filters. These might conflict if user also specifies them in --rg-args.
    # A more advanced merge strategy could be used, but for now, they are additive.
    if args.include_ext:
        for i, ext_type in enumerate(args.include_ext):
            # rg needs a unique name for each --type-add definition
            rg_cmd_filters.extend([f"--type-add", f"rgcbinclude{i}:*.{ext_type}", "-t", f"rgcbinclude{i}"])
    if args.exclude_ext:
        for i, ext_type in enumerate(args.exclude_ext):
            rg_cmd_filters.extend([f"--type-add", f"rgcbexclude{i}:*.{ext_type}", "-T", f"rgcbexclude{i}"]) # -T is --type-not
    if args.exclude_path:
        for glob_pattern in args.exclude_path:
            rg_cmd_filters.extend(["--glob", f"!{glob_pattern}"]) # Note the '!' for exclusion

    # Combine command parts: base, then user extras, then our filters, then pattern and path
    rg_cmd = rg_cmd_base + rg_cmd_user_extras + rg_cmd_filters
    
    # Add pattern and path at the end if they weren't likely part of --rg-args
    # This is a heuristic; complex --rg-args might already include them.
    if args.pattern not in " ".join(user_rg_args_list): # Simple check
        rg_cmd.append(args.pattern)
    if args.path not in " ".join(user_rg_args_list): # Simple check
        rg_cmd.append(args.path)
    
    try:
        process = subprocess.run(rg_cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='surrogateescape')
    except FileNotFoundError:
        sys.stderr.write("Error: ripgrep (rg) command not found. Please ensure it's installed and in your PATH.\n")
        sys.exit(2)
    
    if process.returncode > 1: # rg specific error
        err_msg_obj = {"error": "ripgrep_execution_error", "stderr": process.stderr, "command_used": rg_cmd, "returncode": process.returncode}
        if args.format == "text":
            sys.stderr.write(f"Error from ripgrep (rc={process.returncode}):\n{process.stderr}\nAttempted Command: {' '.join(rg_cmd)}\n")
        elif args.format == "json":
            print(json.dumps(err_msg_obj), file=sys.stderr) # Print error as JSON to stderr
        sys.exit(process.returncode)
    
    rg_output_lines = process.stdout.strip().split('\n') if process.stdout.strip() else []
    
    if not rg_output_lines : # Handles rg exit code 1 (no matches) or 0 (e.g. --files found nothing pattern based for rg to output line-by-line)
        if args.stats: print_statistics() # Still print stats if requested, might show 0 matches
        if args.format == "json": print(json.dumps([])) # For JSON, empty list means no results processed
        sys.exit(0) # No matches is a successful run in terms of rgcodeblock's operation

    # Call the main processing function
    main_processing_loop(rg_output_lines, args, highlight_ansi_sequence)

    if args.stats:
        print_statistics()
    
    # Determine final exit code based on whether we processed any "match" types from rg
    final_exit_code = 0
    if STATS["total_rg_matches"] == 0:
        # If rg's return code was 1 (no matches), our 0 is fine.
        # If rg's return code was 0 but we still saw no "match" types (e.g. rg --files), also fine.
        # This means no "match" lines were processed by main_processing_loop.
        pass 
    # If total_rg_matches > 0, it implies a successful processing run from rgcodeblock's perspective.
    
    sys.exit(final_exit_code)

if __name__ == "__main__":
    sys.exit(main())
