# gizmo_mapper.py
import json
import argparse
import sys
import os
from collections import defaultdict
from chat_export_utils import load_and_sort_conversations, DEFAULT_CONVERSATIONS_FILE # Assuming chat_export_utils.py is available

DEFAULT_PROJECT_DEFINITIONS_INPUT_FILE = "project_definitions.json" # Example input file name
DEFAULT_GIZMO_MAP_OUTPUT_FILE = "gizmo_map.json"

EXAMPLE_PROJECT_DEFINITIONS_CONTENT = """
{
    "My First Project": [
        "Exact Conversation Title A for First Project",
        "Exact Conversation Title B for First Project"
    ],
    "Another Cool Project": [
        "Known Title X for Another Project",
        "Known Title Y for Another Project",
        "Known Title Z for Another Project"
    ],
    "Project Alpha": [
        "Alpha Task 1 Discussion"
    ]
}
"""

def process_project_mapping(all_conversations_data, project_name, known_titles_list, current_gizmo_map):
    """
    Identifies a common Gizmo ID for a single project's known titles and prepares to update the map.
    Returns the identified_gizmo_id and project_name if successful, or None.
    """
    print(f"\nProcessing Project: \"{project_name}\"")
    print(f"  Using known titles: {known_titles_list}")

    matched_gizmo_ids = set()
    found_titles_count = 0
    
    normalized_known_titles = [title.strip().lower() for title in known_titles_list]

    for convo_data in all_conversations_data:
        original_title = convo_data.get("title", "")
        if original_title.strip().lower() in normalized_known_titles:
            found_titles_count += 1
            gizmo_id = convo_data.get("gizmo_id")
            if gizmo_id:
                matched_gizmo_ids.add(gizmo_id)
            else:
                print(f"    Warning: Known title \"{original_title}\" for project \"{project_name}\" does not have a top-level gizmo_id.")

    if found_titles_count == 0:
        print(f"    Error: None of the provided titles were found for project '{project_name}'. Skipping this project.")
        return None, None
    
    if not matched_gizmo_ids:
        print(f"    Error: Could not find any gizmo_ids for the provided titles for project '{project_name}'.")
        print(f"    (Found {found_titles_count} title matches, but none had an associated gizmo_id). Skipping this project.")
        return None, None

    if len(matched_gizmo_ids) > 1:
        print(f"    Warning: Multiple gizmo_ids found for project '{project_name}': {list(matched_gizmo_ids)}")
        print(f"    This suggests the titles might span different custom GPTs or include general chats.")
        print(f"    Cannot reliably map '{project_name}'. Please refine its titles. Skipping this project.")
        return None, None
    
    identified_gizmo_id = list(matched_gizmo_ids)[0]
    print(f"    Success: Identified Gizmo ID: {identified_gizmo_id} for Project: \"{project_name}\"")
    print(f"    (Based on {found_titles_count} title match(es) all pointing to this Gizmo ID).")

    if identified_gizmo_id in current_gizmo_map and current_gizmo_map[identified_gizmo_id] != project_name:
        print(f"    Conflict: Gizmo ID {identified_gizmo_id} is already mapped to '{current_gizmo_map[identified_gizmo_id]}'.")
        # In batch mode, we might decide to prioritize the first mapping encountered or skip.
        # For now, let's allow overwrite but print a clear warning.
        # A more advanced version could have a conflict resolution strategy.
        print(f"    Overwriting mapping for {identified_gizmo_id} with new project name '{project_name}'.")
    elif identified_gizmo_id in current_gizmo_map and current_gizmo_map[identified_gizmo_id] == project_name:
        print(f"    Info: Gizmo ID {identified_gizmo_id} is already correctly mapped to '{project_name}'. No update needed for this entry.")
        # Still return it so it's part of the "to be written" map if it wasn't a conflict
    
    return identified_gizmo_id, project_name


def main():
    parser = argparse.ArgumentParser(
        description="Builds or updates a map of Gizmo IDs to Project Names using a definitions file.",
        formatter_class=argparse.RawTextHelpFormatter # To allow for multiline help
    )
    parser.add_argument(
        "-s", "--source", 
        default=DEFAULT_CONVERSATIONS_FILE,
        help="Path to the conversations.json file."
    )
    parser.add_argument(
        "-d", "--definitions-file",
        default=DEFAULT_PROJECT_DEFINITIONS_INPUT_FILE,
        help="Path to a JSON file defining projects and their known conversation titles."
    )
    parser.add_argument(
        "-o", "--output-gizmo-map", 
        default=DEFAULT_GIZMO_MAP_OUTPUT_FILE, 
        help="JSON file to write/update the final Gizmo ID to Project Name map."
    )
    parser.add_argument(
        "--show-example-definitions",
        action="store_true",
        help="Show an example of the project definitions input file format and exit."
    )

    args = parser.parse_args()

    if args.show_example_definitions:
        print("Example content for the Project Definitions Input File (e.g., project_definitions.json):")
        print("------------------------------------------------------------------------------------")
        print(EXAMPLE_PROJECT_DEFINITIONS_CONTENT)
        print("------------------------------------------------------------------------------------")
        print("Each key is your desired Project Name.")
        print("Each value is a list of exact conversation titles known to be in that project.")
        sys.exit(0)

    if not os.path.exists(args.source):
        print(f"Error: Source conversations file '{args.source}' not found.")
        sys.exit(1)
    
    if not os.path.exists(args.definitions_file):
        print(f"Error: Project definitions input file '{args.definitions_file}' not found.")
        print(f"You can create one or use --show-example-definitions to see the format.")
        sys.exit(1)

    all_conversations = load_and_sort_conversations(args.source)
    if not all_conversations:
        print("Could not load or process conversations.json. Exiting.")
        sys.exit(1)

    project_definitions = {}
    try:
        with open(args.definitions_file, 'r', encoding='utf-8') as f:
            project_definitions = json.load(f)
        if not isinstance(project_definitions, dict):
            raise ValueError("Definitions file should contain a JSON object (dictionary).")
        for project, titles in project_definitions.items():
            if not isinstance(titles, list) or not all(isinstance(t, str) for t in titles):
                raise ValueError(f"Project '{project}' in definitions file must have a list of strings as its titles.")
        print(f"Successfully loaded {len(project_definitions)} project definitions from '{args.definitions_file}'.")
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from project definitions file '{args.definitions_file}'.")
        sys.exit(1)
    except ValueError as ve:
        print(f"Error in project definitions file format: {ve}")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading project definitions file '{args.definitions_file}': {e}")
        sys.exit(1)

    # Load existing output map or start fresh
    output_gizmo_map = {}
    if os.path.exists(args.output_gizmo_map):
        try:
            with open(args.output_gizmo_map, 'r', encoding='utf-8') as f:
                output_gizmo_map = json.load(f)
            if not isinstance(output_gizmo_map, dict):
                print(f"Warning: Existing output map file '{args.output_gizmo_map}' is not a valid JSON object. Will be overwritten if new mappings are found.")
                output_gizmo_map = {}
        except Exception: # Broad catch if file is totally corrupt or unreadable
            print(f"Warning: Could not read or parse existing output map file '{args.output_gizmo_map}'. Will create a new one.")
            output_gizmo_map = {}
            
    mappings_to_write = {}
    successful_mappings = 0

    for project_name, known_titles in project_definitions.items():
        if not known_titles:
            print(f"Skipping project \"{project_name}\" as it has no known titles defined.")
            continue
        
        # Pass the current state of output_gizmo_map to check for conflicts
        # but collect new/updated mappings in a temporary dict to avoid partial writes on error.
        identified_gizmo_id, mapped_project_name = process_project_mapping(
            all_conversations, 
            project_name, 
            known_titles,
            output_gizmo_map # Pass current map for conflict checking
        )
        if identified_gizmo_id and mapped_project_name:
            # Check for conflict again before adding to mappings_to_write,
            # process_project_mapping only prints a warning for overwrite.
            # Here we decide if we actually want to stage it for writing.
            if identified_gizmo_id in output_gizmo_map and output_gizmo_map[identified_gizmo_id] != mapped_project_name:
                # This case was handled by process_project_mapping with a warning.
                # If we wanted interactive overwrite, it would be here. For batch, we assume overwrite.
                pass # The warning was printed, we'll proceed with the new mapping.
            
            mappings_to_write[identified_gizmo_id] = mapped_project_name
            successful_mappings +=1

    if not mappings_to_write and not output_gizmo_map: # No new mappings and no existing map to write
        print("\nNo new valid mappings found and no existing map to preserve. Output map file will not be created/updated.")
        sys.exit(0)
    
    # Update the main map with new/changed mappings
    output_gizmo_map.update(mappings_to_write)

    if successful_mappings > 0:
        print(f"\nProcessed {len(project_definitions)} project definitions. Found {successful_mappings} valid Gizmo ID mappings to update/add.")
    else:
        print(f"\nProcessed {len(project_definitions)} project definitions. No new valid Gizmo ID mappings were found to update/add.")
        if not output_gizmo_map: # if the map is still empty
             print("Output map file will not be created as it would be empty.")
             sys.exit(0)


    try:
        with open(args.output_gizmo_map, 'w', encoding='utf-8') as f:
            json.dump(output_gizmo_map, f, indent=4, sort_keys=True)
        print(f"Final Gizmo ID map saved to '{args.output_gizmo_map}'. Contains {len(output_gizmo_map)} mappings.")
    except Exception as e:
        print(f"Error saving final Gizmo ID map to '{args.output_gizmo_map}': {e}")

if __name__ == "__main__":
    main()
