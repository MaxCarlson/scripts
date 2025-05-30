# chat_gpt_parser.py
import json
import os
import re
import argparse
import sys
import time
from collections import defaultdict, Counter
import shutil # For copying the gizmo_map file

from chat_export_utils import (
    load_and_sort_conversations as util_load_conversations,
    format_timestamp_util as format_timestamp,
    DEFAULT_CONVERSATIONS_FILE as UTIL_DEFAULT_CONVERSATIONS_FILE
)

# --- Configuration ---
DEFAULT_INPUT_FILENAME = UTIL_DEFAULT_CONVERSATIONS_FILE
DEFAULT_OUTPUT_DIRECTORY = "chatgpt_analysis_organized" # New default to avoid overwriting old
DEFAULT_GIZMO_MAP_FILENAME = "gizmo_map.json" 

# New Folder Names for Schema 1
MAPPED_PROJECTS_ROOT_FOLDER = "Mapped_Projects"
UNMAPPED_PROJECTS_ROOT_FOLDER = "Unmapped_Projects_By_GizmoID"
GENERAL_CHATS_FOLDER_NAME = "General_Chats"
AGGREGATED_OUTPUTS_FOLDER = "Aggregated_Outputs" # For dump, prompts, responses
UNKNOWN_GIZMO_FOLDER_SUFFIX = "_project_details" # e.g. g-xxxx_project_details

FULL_DUMP_FILENAME = "all_conversations_dump.txt"
USER_PROMPTS_FILENAME = "all_user_prompts.txt"
ASSISTANT_RESPONSES_FILENAME = "all_assistant_responses.txt"

UPDATE_INTERVAL_SECONDS = 0.2
PROJECT_TITLE_REGEX = r"^\[\s*([\w\s-]+?)\s*\]\s*(.*)$" 

GIZMO_ID_TO_PROJECT_NAME_MAP = {}

# --- Helper Functions (format_bytes, ensure_output_dir, sanitize_filename_component, etc. remain the same) ---
def format_bytes(num_bytes):
    if num_bytes is None: return "0 B"
    if num_bytes < 1024: return f"{num_bytes} B"
    elif num_bytes < 1024**2: return f"{num_bytes/1024:.2f} KB"
    elif num_bytes < 1024**3: return f"{num_bytes/1024**2:.2f} MB"
    else: return f"{num_bytes/1024**3:.2f} GB"

def ensure_output_dir_path(dir_path): # More generic name
    if not os.path.exists(dir_path):
        os.makedirs(dir_path); print(f"Created directory: {dir_path}")

def sanitize_filename_component(name):
    name = str(name)
    name = re.sub(r'[^\w\s.-]', '', name).strip()
    name = re.sub(r'[-\s]+', '-', name)
    return name if name else "untitled_component"

def extract_title_parts_for_filename(title_str, regex_pattern):
    match = re.match(regex_pattern, title_str)
    if match and len(match.groups()) > 1: return match.group(2).strip()
    return title_str

def get_message_content(message_data):
    if not message_data or "content" not in message_data: return ""
    content_type = message_data["content"].get("content_type")
    parts = message_data["content"].get("parts", [])
    full_content = ""
    if content_type == "text": full_content = "".join(p for p in parts if isinstance(p, str))
    elif content_type == "code":
        code_text = message_data["content"].get("text", "") 
        lang = message_data["content"].get("metadata", {}).get("language", "")
        full_content = f"```{lang}\n{code_text}\n```"
    elif content_type == "tether_browsing_display":
        texts = [part.get("text", "") for part in parts if isinstance(part, dict) and "text" in part]
        if not texts: texts = [str(part) for part in parts]
        full_content = "Browsing Result:\n" + "\n".join(texts)
    elif content_type == "multimodal_text":
        combined_parts = []
        for part in parts:
            if isinstance(part, str): combined_parts.append(part)
            elif isinstance(part, dict):
                part_content_type = part.get("content_type")
                if part_content_type == "image_asset_pointer": combined_parts.append(f"[Image Asset: {part.get('asset_pointer', '').split(':')[-1]}]")
                elif part_content_type == "image_url": combined_parts.append(f"[Image from URL: {part.get('image_url', {}).get('url', 'N/A')}]")
                else: combined_parts.append(f"[Multimodal part: {part_content_type}]")
        full_content = "\n".join(combined_parts)
    else:
        full_content = "".join(str(p) for p in parts)
        full_content = f"[{content_type.upper() if content_type else 'UNKNOWN'}_CONTENT]\n{full_content}"
    return full_content.strip()

def get_model_slug(message_data):
    if message_data and "metadata" in message_data:
        metadata = message_data["metadata"]
        model_slug = metadata.get("model_slug")
        if model_slug: return model_slug
        if isinstance(metadata.get("invoked_plugin"), dict): return f"plugin:{metadata['invoked_plugin'].get('namespace', 'unknown')}"
        if metadata.get("message_type") == "code" or metadata.get("finish_details", {}).get("type") == "code_output": return "code-interpreter"
        if (ucmm := metadata.get("user_context_message_metadata")) and ucmm.get("model_slug"): return ucmm["model_slug"] + " (uc)"
    return "unknown_model"

def parse_single_conversation_data(convo_data, title_regex_pattern):
    original_title = convo_data.get("title", "Untitled Conversation")
    filename_title = extract_title_parts_for_filename(original_title, title_regex_pattern)
    parsed = {
        "id": convo_data.get("conversation_id") or convo_data.get("id"),
        "original_title": original_title, "filename_title": filename_title,
        "gizmo_id": convo_data.get("gizmo_id"),
        "create_time_unix": convo_data.get("create_time"), "update_time_unix": convo_data.get("update_time"),
        "create_time_str": format_timestamp(convo_data.get("create_time")),
        "update_time_str": format_timestamp(convo_data.get("update_time")),
        "messages": [], "message_count": 0, "model_slugs_used": set()
    }
    mapping = convo_data.get("mapping", {})
    if not mapping: return parsed
    current_node_id = convo_data.get("current_node")
    temp_messages = []
    while current_node_id:
        node = mapping.get(current_node_id)
        if not node: break 
        message_data = node.get("message")
        if message_data and message_data.get("author"):
            author_role = message_data["author"]["role"]
            if author_role == "system" and not message_data.get("content", {}).get("parts"): 
                current_node_id = node.get("parent"); continue
            
            model_slug = None
            if author_role == "assistant":
                model_slug = get_model_slug(message_data)
                if model_slug and model_slug != "unknown_model":
                    parsed["model_slugs_used"].add(model_slug)

            temp_messages.append({
                "id": node["id"], "role": author_role, 
                "content": get_message_content(message_data),
                "timestamp": message_data.get("create_time"), 
                "model": model_slug
            })
        current_node_id = node.get("parent")
    parsed["messages"] = list(reversed(temp_messages))
    parsed["message_count"] = len(parsed["messages"])
    return parsed

def process_all_conversations(raw_conversations_list, title_regex_pattern):
    parsed_conversations = []
    total_convos = len(raw_conversations_list)
    print(f"Processing {total_convos} conversations for parsing details...")
    for i, convo_data in enumerate(raw_conversations_list):
        parsed = parse_single_conversation_data(convo_data, title_regex_pattern)
        if parsed: parsed_conversations.append(parsed)
        if (i + 1) % 100 == 0 or (i + 1) == total_convos:
            print(f"\rParsed details for: {i+1}/{total_convos} conversations", end="")
    print()
    return parsed_conversations

def generate_markdown_summary(conversation, project_name_for_summary=None):
    md = f"# Conversation: {conversation['original_title']}\n\n"
    if project_name_for_summary: md += f"- **Project (Derived):** {project_name_for_summary}\n"
    if conversation['gizmo_id']: md += f"- **Gizmo ID:** {conversation['gizmo_id']}\n"
    md += f"- **ID:** {conversation['id']}\n"
    md += f"- **Created:** {conversation['create_time_str']}\n"
    md += f"- **Updated:** {conversation['update_time_str']}\n"
    md += f"- **Total Messages:** {conversation['message_count']}\n"
    if conversation['model_slugs_used']:
        md += f"- **Models Used (Assistant):** {', '.join(sorted(list(conversation['model_slugs_used'])))}\n"
    md += "\n"
    for msg in conversation["messages"]:
        role_cap = msg['role'].capitalize()
        timestamp_str = format_timestamp(msg['timestamp'])
        header = f"## {role_cap} ({timestamp_str})"
        if msg['role'] == 'assistant' and msg['model'] and msg['model'] != 'unknown_model':
            header = f"## Assistant (Model: {msg['model']}) ({timestamp_str})"
        md += f"{header}:\n"
        content_lines = msg['content'].split('\n')
        is_code_block = False
        for line in content_lines:
            if line.startswith("```"): is_code_block = not is_code_block
            md += f"{line}\n" if is_code_block or line.startswith("```") else (f"> {line}\n" if line.strip() else "\n")
        md += "\n"
    return md

def save_individual_summaries(conversations, base_output_dir, title_regex_pattern, gizmo_counts):
    print(f"\nSaving individual conversation summaries...")
    count, total_summaries, bytes_written_this_run = 0, len(conversations), 0
    
    # Define root folders for categories
    mapped_projects_path = os.path.join(base_output_dir, MAPPED_PROJECTS_ROOT_FOLDER)
    unmapped_projects_path = os.path.join(base_output_dir, UNMAPPED_PROJECTS_ROOT_FOLDER)
    general_chats_path = os.path.join(base_output_dir, GENERAL_CHATS_FOLDER_NAME)

    for i, convo in enumerate(conversations):
        target_dir_for_convo = None
        project_name_for_summary = None 

        if convo['gizmo_id']:
            mapped_project_name = GIZMO_ID_TO_PROJECT_NAME_MAP.get(convo['gizmo_id'])
            if mapped_project_name:
                project_name_for_summary = mapped_project_name
                target_dir_for_convo = os.path.join(mapped_projects_path, sanitize_filename_component(mapped_project_name))
            else: 
                if gizmo_counts.get(convo['gizmo_id'], 0) > 1:
                     folder_name = f"{sanitize_filename_component(convo['gizmo_id'])}{UNKNOWN_GIZMO_FOLDER_SUFFIX}"
                     target_dir_for_convo = os.path.join(unmapped_projects_path, folder_name)
                     project_name_for_summary = f"Unmapped Gizmo ({convo['gizmo_id']})"
                else: 
                     target_dir_for_convo = general_chats_path
                     project_name_for_summary = f"General (Single Unmapped Gizmo: {convo['gizmo_id']})"
        else: 
            target_dir_for_convo = general_chats_path
            project_name_for_summary = "General Chat"

        ensure_output_dir_path(target_dir_for_convo) # Create specific project/category folder
        
        safe_filename_title = sanitize_filename_component(convo['filename_title'])
        filename = os.path.join(target_dir_for_convo, f"conversation_{convo['id']}_{safe_filename_title[:50]}.md")
        
        summary_md = generate_markdown_summary(convo, project_name_for_summary)
        try:
            with open(filename, 'w', encoding='utf-8') as f: f.write(summary_md)
            bytes_written_this_run += os.path.getsize(filename); count += 1
        except Exception as e: print(f"\nError saving summary for ID '{convo['id']}': {e}")
        
        if (i + 1) % 50 == 0 or (i + 1) == total_summaries:
            print(f"\rSaved: {count}/{total_summaries} summaries | Written: {format_bytes(bytes_written_this_run)}", end="")
    print()
    print(f"Done saving {count} summaries ({format_bytes(bytes_written_this_run)}). Output organized into subfolders.")
    return bytes_written_this_run

def save_aggregated_file(conversations, aggregated_output_dir, filename, file_type): # Takes aggregated_output_dir
    ensure_output_dir_path(aggregated_output_dir) # Ensure this specific subdir exists
    filepath = os.path.join(aggregated_output_dir, filename) 
    print(f"\nSaving {file_type} to '{filepath}'...")
    # ... (rest of function is the same as before, using format_timestamp from utils) ...
    bytes_written = 0
    with open(filepath, 'w', encoding='utf-8') as f:
        for convo in conversations:
            project_name_for_header = GIZMO_ID_TO_PROJECT_NAME_MAP.get(convo['gizmo_id'], 
                                                                    f"GizmoID:{convo['gizmo_id']}" if convo['gizmo_id'] else "General")
            if file_type == "full dump":
                f.write(f"--- Conv: {convo['original_title']} (ID: {convo['id']}) [Proj: {project_name_for_header}] ---\n")
                f.write(f"Created: {convo['create_time_str']}, Updated: {convo['update_time_str']}\n\n")
                for msg in convo['messages']:
                    f.write(f"[{format_timestamp(msg['timestamp'])}] {msg['role'].upper()}:\n{msg['content']}\n\n")
                f.write(f"--- End Conv: {convo['original_title']} ---\n\n\n")
            elif file_type == "user prompts":
                for msg in convo['messages']:
                    if msg['role'] == 'user':
                        f.write(f"--- Prompt: convo '{convo['original_title']}' (ID: {convo['id']}) [P: {project_name_for_header}] ({format_timestamp(msg['timestamp'])}) ---\n")
                        f.write(msg['content'] + "\n\n")
            elif file_type == "assistant responses":
                 for msg in convo['messages']:
                    if msg['role'] == 'assistant':
                        f.write(f"--- Resp: convo '{convo['original_title']}' (ID: {convo['id']}) [P: {project_name_for_header}] ({format_timestamp(msg['timestamp'])}) ---\n")
                        f.write(msg['content'] + "\n\n")
    bytes_written = os.path.getsize(filepath)
    print(f"{file_type.capitalize()} saved ({format_bytes(bytes_written)}).")
    return bytes_written


def load_gizmo_map(map_filepath):
    global GIZMO_ID_TO_PROJECT_NAME_MAP
    if os.path.exists(map_filepath):
        try:
            with open(map_filepath, 'r', encoding='utf-8') as f:
                GIZMO_ID_TO_PROJECT_NAME_MAP = json.load(f)
            print(f"Loaded Gizmo map from '{map_filepath}'. Found {len(GIZMO_ID_TO_PROJECT_NAME_MAP)} mappings.")
            if not isinstance(GIZMO_ID_TO_PROJECT_NAME_MAP, dict):
                print(f"Warning: Gizmo map not a dict. Using empty map."); GIZMO_ID_TO_PROJECT_NAME_MAP = {}
        except Exception as e:
            print(f"Error loading Gizmo map '{map_filepath}': {e}. Using empty map."); GIZMO_ID_TO_PROJECT_NAME_MAP = {}
    else:
        print(f"Info: Gizmo map file '{map_filepath}' not found. No Gizmo ID to Project Name mappings will be used."); GIZMO_ID_TO_PROJECT_NAME_MAP = {}

def main():
    global PROJECT_TITLE_REGEX 
    parser = argparse.ArgumentParser(
        description="Parse & organize ChatGPT conversations by Project (Gizmo ID) using Schema 1.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-s", "--source", default=DEFAULT_INPUT_FILENAME, help="Path to conversations.json.")
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIRECTORY, help="Base output directory.")
    parser.add_argument("-m", "--gizmo-map-file", default=DEFAULT_GIZMO_MAP_FILENAME, help="JSON map of Gizmo IDs to Project Names.")
    parser.add_argument("-i", "--skip-individual", action="store_true", help="Skip individual Markdown summaries.")
    parser.add_argument("-f", "--skip-dump", action="store_true", help="Skip full text dump.")
    parser.add_argument("-p", "--skip-prompts", action="store_true", help="Skip aggregated user prompts.")
    parser.add_argument("-r", "--skip-responses", action="store_true", help="Skip aggregated assistant responses.")
    parser.add_argument("-t", "--title-regex", default=PROJECT_TITLE_REGEX, help="Regex to clean titles for filenames.")

    if len(sys.argv) == 1: parser.print_help(sys.stderr); sys.exit(1)
    args = parser.parse_args()
    
    if args.title_regex != PROJECT_TITLE_REGEX:
        try: re.compile(args.title_regex); PROJECT_TITLE_REGEX = args.title_regex
        except re.error as e: print(f"Warning: Invalid title regex: {e}. Using default.")

    load_gizmo_map(args.gizmo_map_file)
    base_output_dir = args.output_dir # Renamed for clarity
    total_bytes_written = 0

    ensure_output_dir_path(base_output_dir) # Create main output dir
    
    # Save a copy of the gizmo map used
    if os.path.exists(args.gizmo_map_file) and GIZMO_ID_TO_PROJECT_NAME_MAP: # Only copy if map was loaded
        try:
            shutil.copy2(args.gizmo_map_file, os.path.join(base_output_dir, "gizmo_map_used.json"))
            print(f"Copied '{args.gizmo_map_file}' to output directory as 'gizmo_map_used.json'.")
        except Exception as e:
            print(f"Warning: Could not copy gizmo map file to output directory: {e}")
    elif GIZMO_ID_TO_PROJECT_NAME_MAP: # Map was loaded but maybe default path didn't exist, or it was empty
         with open(os.path.join(base_output_dir, "gizmo_map_used.json"), 'w', encoding='utf-8') as gmf:
            json.dump(GIZMO_ID_TO_PROJECT_NAME_MAP, gmf, indent=4)
         print(f"Saved current (possibly empty) GIZMO_ID_TO_PROJECT_NAME_MAP to 'gizmo_map_used.json'.")


    raw_conversations_list = util_load_conversations(args.source)
    if not raw_conversations_list: print("No raw conversation data loaded. Exiting."); sys.exit(1)

    all_parsed_conversations = process_all_conversations(raw_conversations_list, PROJECT_TITLE_REGEX)
    if not all_parsed_conversations: print("No conversations parsed. Exiting."); sys.exit(1)
    print(f"Successfully parsed details for {len(all_parsed_conversations)} conversations.")

    gizmo_counts = Counter(c['gizmo_id'] for c in all_parsed_conversations if c['gizmo_id'])

    if not args.skip_individual:
        bytes_step = save_individual_summaries(all_parsed_conversations, base_output_dir, PROJECT_TITLE_REGEX, gizmo_counts)
        total_bytes_written += bytes_step
    else: print("\nSkipping individual summaries.")

    # Define and ensure aggregated outputs directory
    aggregated_output_dir_path = os.path.join(base_output_dir, AGGREGATED_OUTPUTS_FOLDER)
    
    if not args.skip_dump:
        bytes_step = save_aggregated_file(all_parsed_conversations, aggregated_output_dir_path, FULL_DUMP_FILENAME, "full dump")
        total_bytes_written += bytes_step
    else: print("\nSkipping full dump.")
    
    if not args.skip_prompts:
        bytes_step = save_aggregated_file(all_parsed_conversations, aggregated_output_dir_path, USER_PROMPTS_FILENAME, "user prompts")
        total_bytes_written += bytes_step
    else: print("\nSkipping user prompts file.")

    if not args.skip_responses:
        bytes_step = save_aggregated_file(all_parsed_conversations, aggregated_output_dir_path, ASSISTANT_RESPONSES_FILENAME, "assistant responses")
        total_bytes_written += bytes_step
    else: print("\nSkipping assistant responses file.")

    print("\n--- Final Output Structure Summary ---")
    # ... (Analysis Summary section updated to reflect new folder names) ...
    project_convo_counts = defaultdict(int)
    general_chat_count = 0
    unknown_gizmo_convo_counts = defaultdict(int)

    for convo in all_parsed_conversations:
        if convo['gizmo_id']:
            mapped_name = GIZMO_ID_TO_PROJECT_NAME_MAP.get(convo['gizmo_id'])
            if mapped_name:
                project_convo_counts[os.path.join(MAPPED_PROJECTS_ROOT_FOLDER, sanitize_filename_component(mapped_name))] += 1
            else:
                if gizmo_counts.get(convo['gizmo_id'], 0) > 1:
                    folder_name = f"{sanitize_filename_component(convo['gizmo_id'])}{UNKNOWN_GIZMO_FOLDER_SUFFIX}"
                    unknown_gizmo_convo_counts[os.path.join(UNMAPPED_PROJECTS_ROOT_FOLDER, folder_name)] += 1
                else: 
                    general_chat_count +=1
        else:
            general_chat_count += 1
            
    print("Conversation counts per project folder:")
    for name, num in sorted(project_convo_counts.items()): print(f"- {name}/ : {num}")
    if unknown_gizmo_convo_counts:
        print("\nCounts for unmapped Gizmo ID folders (>1 convo):")
        for name, num in sorted(unknown_gizmo_convo_counts.items()): print(f"- {name}/ : {num}")
    print(f"\nConversations in '{GENERAL_CHATS_FOLDER_NAME}/': {general_chat_count}")
    print(f"\nAggregated files are in '{AGGREGATED_OUTPUTS_FOLDER}/'")
    
    print(f"\nAll enabled outputs saved to '{base_output_dir}'.")
    print(f"Total data written: {format_bytes(total_bytes_written)}")

if __name__ == "__main__":
    main()
