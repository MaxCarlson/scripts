# chat_usage_analyzer.py
import json
import os
import argparse
from collections import Counter, defaultdict
from datetime import datetime # Already in chat_export_utils, but good to have explicitly if used directly
from chat_export_utils import format_timestamp_util # Assuming this is available

DEFAULT_PARSED_DATA_FILE = "all_parsed_conversations_data.json"
DEFAULT_GIZMO_MAP_FILE = "gizmo_map_used.json" # Expects the map used by the parser
DEFAULT_ANALYSIS_REPORT_FILE = "usage_analysis_report.md"

def load_json_file(filepath, description="file"):
    """Loads a JSON file and returns its content."""
    if not os.path.exists(filepath):
        print(f"Error: {description.capitalize()} '{filepath}' not found.")
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"Successfully loaded {description} from '{filepath}'.")
        return data
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {description} '{filepath}'.")
        return None
    except Exception as e:
        print(f"Error loading {description} '{filepath}': {e}")
        return None

def generate_global_summary(all_conversations, gizmo_map):
    """Generates a global summary of all conversations."""
    if not all_conversations:
        return "No conversation data to analyze.\n"

    num_total_conversations = len(all_conversations)
    total_user_messages = 0
    total_assistant_messages = 0
    all_model_slugs = Counter()
    project_conversation_counts = Counter()
    general_chat_count = 0
    min_date = None
    max_date = None

    for convo in all_conversations:
        create_time = convo.get("create_time_unix")
        if create_time:
            dt_obj = datetime.fromtimestamp(create_time)
            if min_date is None or dt_obj < min_date:
                min_date = dt_obj
            if max_date is None or dt_obj > max_date:
                max_date = dt_obj

        for msg in convo.get("messages", []):
            if msg.get("role") == "user":
                total_user_messages += 1
            elif msg.get("role") == "assistant":
                total_assistant_messages += 1
        
        # Use the model_slugs_used collected by the parser
        for slug in convo.get("model_slugs_used", []):
            if slug and slug != "unknown_model":
                all_model_slugs[slug] += 1

        gizmo_id = convo.get("gizmo_id")
        if gizmo_id:
            project_name = gizmo_map.get(gizmo_id, f"Unmapped Gizmo ({gizmo_id})")
            project_conversation_counts[project_name] += 1
        else:
            general_chat_count += 1
            project_conversation_counts["_General_Chats_"] +=1


    summary = "# Global Usage Summary\n\n"
    summary += f"- **Total Conversations:** {num_total_conversations}\n"
    if min_date and max_date:
        summary += f"- **Date Range of Conversations:** {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}\n"
    summary += f"- **Total User Messages:** {total_user_messages}\n"
    summary += f"- **Total Assistant Messages:** {total_assistant_messages}\n"
    
    summary += "\n## Project/Category Distribution:\n"
    if project_conversation_counts:
        for name, count in project_conversation_counts.most_common():
            summary += f"- {name}: {count} conversations\n"
    else:
        summary += "- No project/category distribution available.\n"

    summary += "\n## Assistant Models Used (Across All Conversations):\n"
    if all_model_slugs:
        for slug, count in all_model_slugs.most_common():
            summary += f"- {slug}: {count} times\n"
    else:
        summary += "- No specific assistant model usage data found.\n"
    
    summary += "\n---\n"
    return summary

def generate_project_summary(project_name, conversations_in_project):
    """Generates a summary for a specific project."""
    if not conversations_in_project:
        return f"## Project Summary: {project_name}\n\n- No conversations found for this project.\n\n---\n"

    num_project_conversations = len(conversations_in_project)
    project_user_messages = 0
    project_assistant_messages = 0
    project_model_slugs = Counter()
    
    min_date_proj = None
    max_date_proj = None

    for convo in conversations_in_project:
        create_time = convo.get("create_time_unix")
        if create_time:
            dt_obj = datetime.fromtimestamp(create_time)
            if min_date_proj is None or dt_obj < min_date_proj:
                min_date_proj = dt_obj
            if max_date_proj is None or dt_obj > max_date_proj:
                max_date_proj = dt_obj

        for msg in convo.get("messages", []):
            if msg.get("role") == "user":
                project_user_messages += 1
            elif msg.get("role") == "assistant":
                project_assistant_messages += 1
        
        for slug in convo.get("model_slugs_used", []):
            if slug and slug != "unknown_model":
                project_model_slugs[slug] += 1

    summary = f"## Project Summary: {project_name}\n\n"
    summary += f"- **Total Conversations in Project:** {num_project_conversations}\n"
    if min_date_proj and max_date_proj:
        summary += f"- **Date Range (Project):** {min_date_proj.strftime('%Y-%m-%d')} to {max_date_proj.strftime('%Y-%m-%d')}\n"
    summary += f"- **User Messages (Project):** {project_user_messages}\n"
    summary += f"- **Assistant Messages (Project):** {project_assistant_messages}\n"

    summary += "\n### Assistant Models Used (Project):\n"
    if project_model_slugs:
        for slug, count in project_model_slugs.most_common():
            summary += f"- {slug}: {count} times\n"
    else:
        summary += "- No specific assistant model usage data found for this project.\n"
    
    # TODO: Add more project-specific metrics later (e.g., common keywords in prompts for this project)
    
    summary += "\n---\n"
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Analyze parsed ChatGPT conversation data for usage patterns.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-d", "--data-file", 
        default=DEFAULT_PARSED_DATA_FILE,
        help="Path to the 'all_parsed_conversations_data.json' file generated by chat_gpt_parser.py."
    )
    parser.add_argument(
        "-m", "--gizmo-map-file", 
        default=DEFAULT_GIZMO_MAP_FILE,
        help="Path to the 'gizmo_map_used.json' file (for project name resolution)."
    )
    parser.add_argument(
        "-o", "--output-report-file", 
        default=DEFAULT_ANALYSIS_REPORT_FILE,
        help="File to save the generated analysis report (e.g., report.md)."
    )
    parser.add_argument(
        "-p", "--projects-to-summarize",
        nargs='*', # 0 or more project names
        default=None, # None means summarize all mapped projects + general
        help="Optional: Specific project names (from gizmo_map) to generate summaries for. If not provided, all mapped projects are summarized."
    )


    args = parser.parse_args()

    all_conversations = load_json_file(args.data_file, "parsed conversation data")
    gizmo_map = load_json_file(args.gizmo_map_file, "Gizmo ID map")

    if not all_conversations:
        print("Cannot proceed without conversation data.")
        sys.exit(1)
    
    if gizmo_map is None: # Gizmo map is optional, proceed with empty if not found
        print("Warning: Gizmo map not loaded. Project names will be Gizmo IDs or 'General'.")
        gizmo_map = {}

    report_content = f"# ChatGPT Usage Analysis Report\n"
    report_content += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report_content += f"Data Source: {os.path.abspath(args.data_file)}\n"
    report_content += f"Gizmo Map Source: {os.path.abspath(args.gizmo_map_file) if os.path.exists(args.gizmo_map_file) else 'N/A (or not found)'}\n"
    report_content += "---\n"

    # 1. Global Summary
    report_content += generate_global_summary(all_conversations, gizmo_map)

    # 2. Project-Specific Summaries
    # Group conversations by project
    project_conversations_map = defaultdict(list)
    for convo in all_conversations:
        gizmo_id = convo.get("gizmo_id")
        if gizmo_id:
            project_name = gizmo_map.get(gizmo_id, f"Unmapped Gizmo ({gizmo_id})")
            project_conversations_map[project_name].append(convo)
        else:
            project_conversations_map["_General_Chats_"].append(convo)
    
    projects_to_process = []
    if args.projects_to_summarize is None: # Summarize all
        projects_to_process = sorted(project_conversations_map.keys())
    else: # Summarize only specified projects
        for proj_name in args.projects_to_summarize:
            if proj_name in project_conversations_map:
                projects_to_process.append(proj_name)
            else:
                print(f"Warning: Project '{proj_name}' requested for summary but not found in data or map.")
        if "_General_Chats_" in project_conversations_map and "_General_Chats_" not in projects_to_process:
            # Always include general chats if specific projects are requested, unless explicitly excluded later
            # For now, let's include it if specific projects are listed.
            # Or, make it explicit: if args.projects_to_summarize is not None and "_General_Chats_" not in args.projects_to_summarize:
            # then skip general. For now, let's assume if specific projects are asked, general is not implicitly included.
            # If user wants general, they should list it or run with no -p.
            pass


    if projects_to_process:
        report_content += "\n# Project-Specific Summaries\n"
        for project_name in projects_to_process:
            report_content += generate_project_summary(project_name, project_conversations_map[project_name])
    
    try:
        with open(args.output_report_file, 'w', encoding='utf-8') as f_report:
            f_report.write(report_content)
        print(f"\nAnalysis report saved to '{args.output_report_file}'")
    except Exception as e:
        print(f"\nError saving analysis report: {e}")

if __name__ == "__main__":
    main()
