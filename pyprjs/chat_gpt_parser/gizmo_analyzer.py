# gizmo_analyzer.py
import argparse
import sys
from collections import defaultdict
from chat_export_utils import load_and_sort_conversations, format_timestamp_util, DEFAULT_CONVERSATIONS_FILE

def analyze_gizmo_id_usage(all_conversations_data, top_n_gizmos=25, sample_titles_count=5):
    """
    Analyzes conversations for 'gizmo_id', counts them, and shows sample titles
    sorted by update_time (most recent first).
    """
    if all_conversations_data is None:
        return

    print("\n--- Gizmo ID Usage Summary ---")
    gizmo_conversations = defaultdict(list)
    conversations_without_gizmo_id = 0

    for convo in all_conversations_data: # Data is already sorted by update_time
        gizmo_id = convo.get("gizmo_id") 
        if gizmo_id:
            gizmo_conversations[gizmo_id].append({
                "title": convo.get("title", "N/A"),
                "update_time": convo.get("update_time", convo.get("create_time", 0)) # Use update_time for display
            })
        else:
            conversations_without_gizmo_id += 1
            
    if not gizmo_conversations:
        print("No top-level 'gizmo_id' found in any conversation.")
        print(f"Conversations without a top-level 'gizmo_id': {conversations_without_gizmo_id}")
        return

    print(f"Found {len(gizmo_conversations)} unique top-level 'gizmo_id's.")
    print(f"Conversations without a top-level 'gizmo_id': {conversations_without_gizmo_id}")

    # Sort gizmo_ids by the number of conversations they have (most frequent first)
    sorted_gizmos_by_count = sorted(gizmo_conversations.items(), key=lambda item: len(item[1]), reverse=True)

    print(f"\nDisplaying top {min(top_n_gizmos, len(sorted_gizmos_by_count))} Gizmo IDs by conversation count:")
    print(f"(Showing up to {sample_titles_count} most recently updated titles for each)")

    for i, (gizmo_id, convos_list) in enumerate(sorted_gizmos_by_count):
        if i >= top_n_gizmos:
            break
        
        print(f"\n  {i+1}. Gizmo ID: {gizmo_id} (In {len(convos_list)} conversations)")
        
        # convos_list is already sorted by update_time due to initial load_and_sort_conversations
        for j, c_info in enumerate(convos_list):
            if j >= sample_titles_count:
                break
            update_time_str = format_timestamp_util(c_info['update_time'])
            print(f"    - \"{c_info['title']}\" (Updated: {update_time_str})")
        if len(convos_list) > sample_titles_count:
            print(f"    ... and {len(convos_list) - sample_titles_count} more.")

def main():
    parser = argparse.ArgumentParser(
        description="Analyze Gizmo ID usage in ChatGPT conversations.json.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-s", "--source", 
        default=DEFAULT_CONVERSATIONS_FILE,
        help="Path to the conversations.json file."
    )
    parser.add_argument(
        "-n", "--top-n-gizmos", 
        type=int, 
        default=25, 
        help="Number of top Gizmo IDs (by conversation count) to display."
    )
    parser.add_argument(
        "-k", "--titles-per-gizmo", 
        type=int, 
        default=5, 
        help="Maximum number of recent conversation titles to show per Gizmo ID."
    )

    if len(sys.argv) == 1: # If only script name, print help
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    all_conversations = load_and_sort_conversations(args.source)
    if all_conversations:
        analyze_gizmo_id_usage(
            all_conversations, 
            top_n_gizmos=args.top_n_gizmos, 
            sample_titles_count=args.titles_per_gizmo
        )
    else:
        print("Could not load or process conversations.")

if __name__ == "__main__":
    main()
