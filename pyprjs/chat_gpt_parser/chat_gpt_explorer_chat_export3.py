import json
import re
import argparse
import sys
import os
from collections import defaultdict, Counter
from datetime import datetime

DEFAULT_CONVERSATIONS_FILE = "conversations.json"
DEFAULT_GIZMO_MAP_OUTPUT_FILE = "gizmo_map_generated.json"

def find_potential_project_keys(data):
    # (Unchanged from previous explorer version)
    top_level_keys, convo_metadata_keys, message_metadata_keys, message_author_metadata_keys = set(), set(), set(), set()
    if not isinstance(data, list): print(f"Error: Expected list, got {type(data)}"); return {}, {}, {}, {}
    for convo in data:
        if not isinstance(convo, dict): continue
        for key in convo.keys(): top_level_keys.add(key)
        if "metadata" in convo and isinstance(convo["metadata"], dict):
            for key in convo["metadata"].keys(): convo_metadata_keys.add(key)
        if "mapping" in convo and isinstance(convo["mapping"], dict):
            for node_id, node_data in convo["mapping"].items():
                if isinstance(node_data, dict) and "message" in node_data and isinstance(node_data["message"], dict):
                    message = node_data["message"]
                    if "metadata" in message and isinstance(message["metadata"], dict):
                        for key in message["metadata"].keys(): message_metadata_keys.add(key)
                    if "author" in message and isinstance(message["author"], dict) and \
                       "metadata" in message["author"] and isinstance(message["author"]["metadata"], dict):
                        for key in message["author"]["metadata"].keys(): message_author_metadata_keys.add(key)
    return (sorted(list(top_level_keys)), sorted(list(convo_metadata_keys)), 
            sorted(list(message_metadata_keys)), sorted(list(message_author_metadata_keys)))

def analyze_gizmo_ids_summary(data, top_n_gizmos=10, sample_titles_count=5):
    print("\n--- Gizmo ID Usage Summary ---")
    gizmo_conversations = defaultdict(list)
    conversations_without_gizmo_id = 0
    for convo in data: # Assumes data is pre-sorted by create_time desc
        gizmo_id = convo.get("gizmo_id") 
        if gizmo_id:
            gizmo_conversations[gizmo_id].append({
                "title": convo.get("title", "N/A"),
                "create_time": convo.get("create_time", 0) 
            })
        else: conversations_without_gizmo_id += 1
            
    if not gizmo_conversations:
        print("No top-level 'gizmo_id' found in any conversation.")
        print(f"Conversations without a top-level 'gizmo_id': {conversations_without_gizmo_id}")
        return

    print(f"Found {len(gizmo_conversations)} unique top-level 'gizmo_id's.")
    print(f"Conversations without a top-level 'gizmo_id': {conversations_without_gizmo_id}")

    sorted_gizmos = sorted(gizmo_conversations.items(), key=lambda item: len(item[1]), reverse=True)

    print(f"\nTop {min(top_n_gizmos, len(sorted_gizmos))} Gizmo IDs by conversation count (showing up to {sample_titles_count} recent titles):")
    for i, (gizmo_id, convos_list) in enumerate(sorted_gizmos):
        if i >= top_n_gizmos: break
        print(f"\n  {i+1}. Gizmo ID: {gizmo_id} (In {len(convos_list)} conversations)")
        # convos_list is already effectively sorted if all_conversations_data was sorted
        for j, c_info in enumerate(convos_list): # Already sorted by create_time due to initial load sort
            if j >= sample_titles_count: break
            created_time_str = datetime.fromtimestamp(c_info['create_time']).strftime('%Y-%m-%d %H:%M') if c_info['create_time'] else 'N/A'
            print(f"    - \"{c_info['title']}\" (Created: {created_time_str})")
        if len(convos_list) > sample_titles_count: print(f"    ... and {len(convos_list) - sample_titles_count} more.")

def mapping_helper_mode(all_conversations_data, project_name_arg, known_titles_arg, map_output_file):
    print(f"\n--- Mapping Helper Mode ---")
    print(f"Attempting to map Project: \"{project_name_arg}\" using titles: {known_titles_arg}")

    matched_gizmo_ids = set()
    found_titles_count = 0
    
    normalized_known_titles = [title.strip().lower() for title in known_titles_arg]

    for convo_data in all_conversations_data:
        if not isinstance(convo_data, dict): continue
        original_title = convo_data.get("title", "")
        if original_title.strip().lower() in normalized_known_titles:
            found_titles_count += 1
            gizmo_id = convo_data.get("gizmo_id")
            if gizmo_id:
                matched_gizmo_ids.add(gizmo_id)
            else: # One of the known titles doesn't have a gizmo_id
                print(f"Warning: Known title \"{original_title}\" does not have a top-level gizmo_id.")


    if not matched_gizmo_ids:
        print(f"Could not find any gizmo_ids for the provided titles for project '{project_name_arg}'. Found {found_titles_count} title matches but no associated gizmo_ids, or no titles matched.")
        return

    if len(matched_gizmo_ids) > 1:
        print(f"Warning: Multiple gizmo_ids found for the provided titles for project '{project_name_arg}': {list(matched_gizmo_ids)}")
        print("Please refine your titles or check for inconsistencies. Cannot reliably map.")
        return
    
    # Exactly one gizmo_id found
    identified_gizmo_id = list(matched_gizmo_ids)[0]
    print(f"Successfully identified Gizmo ID: {identified_gizmo_id} for Project: \"{project_name_arg}\" (based on {found_titles_count} title matches).")

    # Load existing map file or create new map
    current_map = {}
    if os.path.exists(map_output_file):
        try:
            with open(map_output_file, 'r', encoding='utf-8') as f:
                current_map = json.load(f)
            if not isinstance(current_map, dict):
                print(f"Warning: Existing map file '{map_output_file}' is not a valid JSON object. Starting fresh.")
                current_map = {}
        except json.JSONDecodeError:
            print(f"Warning: Could not decode existing map file '{map_output_file}'. Starting fresh.")
            current_map = {}
    
    if identified_gizmo_id in current_map and current_map[identified_gizmo_id] != project_name_arg:
        print(f"Warning: Gizmo ID {identified_gizmo_id} is already mapped to '{current_map[identified_gizmo_id]}' in '{map_output_file}'.")
        overwrite = input(f"Overwrite with new project name '{project_name_arg}'? (y/N): ").strip().lower()
        if overwrite != 'y':
            print("Mapping not updated.")
            return
            
    current_map[identified_gizmo_id] = project_name_arg
    
    try:
        with open(map_output_file, 'w', encoding='utf-8') as f:
            json.dump(current_map, f, indent=4)
        print(f"Updated Gizmo ID map saved to '{map_output_file}'.")
    except Exception as e:
        print(f"Error saving Gizmo ID map to '{map_output_file}': {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Explore ChatGPT conversations.json for Gizmo ID usage and assist in creating a Gizmo ID to Project Name map.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-s", "--source", default=DEFAULT_CONVERSATIONS_FILE, help="Path to conversations.json.")
    
    # Arguments for summary mode
    parser.add_argument("-n", "--top-n-gizmos", type=int, default=25, help="Number of top Gizmo IDs to display in summary mode.")
    parser.add_argument("-c", "--sample-titles-count", type=int, default=5, help="Number of recent titles to show per Gizmo ID in summary mode.")

    # Arguments for mapping helper mode
    parser.add_argument("--map-project-name", type=str, help="[Mapping Mode] Name of the project to map.")
    parser.add_argument("--map-known-titles", type=str, nargs='+', help="[Mapping Mode] One or more exact conversation titles known to be in this project.")
    parser.add_argument("--map-output-file", default=DEFAULT_GIZMO_MAP_OUTPUT_FILE, help="[Mapping Mode] JSON file to write/update the Gizmo ID map.")

    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"Error: Source file '{args.source}' not found."); sys.exit(1)

    try:
        with open(args.source, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            if isinstance(raw_data, list):
                 all_conversations_data = sorted(raw_data, key=lambda c: c.get("create_time", 0) if isinstance(c, dict) else 0, reverse=True)
            else:
                print(f"Error: Expected list in {args.source}"); sys.exit(1)
    except Exception as e: print(f"Error loading/sorting file: {e}"); sys.exit(1)

    if args.map_project_name and args.map_known_titles:
        # --- Mapping Helper Mode ---
        mapping_helper_mode(all_conversations_data, args.map_project_name, args.map_known_titles, args.map_output_file)
    else:
        # --- Summary Mode (Default) ---
        if len(sys.argv) == 1: # If only script name, print help
             parser.print_help(sys.stderr); sys.exit(1)

        print("--- Identifying all unique keys across all conversations ---")
        # (Key discovery part can be made optional if output is too verbose for default mode)
        # top_keys, convo_meta_keys, msg_meta_keys, msg_author_meta_keys = find_potential_project_keys(all_conversations_data)
        # print(f"Unique top-level conversation keys found: {top_keys}")
        # print(f"Unique conversation metadata keys found: {convo_meta_keys}")
        # print(f"Unique message metadata keys found: {msg_meta_keys}")
        # print(f"Unique message.author.metadata keys found: {msg_author_meta_keys}")
        
        analyze_gizmo_ids_summary(all_conversations_data, 
                                  top_n_gizmos=args.top_n_gizmos, 
                                  sample_titles_count=args.sample_titles_count)
        print(f"\n--- Tip ---")
        print(f"To generate/update a gizmo_map.json, use the --map-project-name and --map-known-titles arguments.")
        print(f"Example: python {sys.argv[0]} -s convos.json --map-project-name \"My Project\" --map-known-titles \"Title One\" \"Another Title for My Project\"")


if __name__ == "__main__":
    main()
