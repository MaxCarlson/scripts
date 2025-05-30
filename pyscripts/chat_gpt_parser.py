import json
from datetime import datetime, timezone
import os
import re
import argparse # Added for CLI arguments

# --- Configuration (defaults, can be overridden by CLI args) ---
DEFAULT_INPUT_FILENAME = "conversations.json"
DEFAULT_OUTPUT_DIRECTORY = "chatgpt_analysis"
# Output filenames remain constants as they are relative to the output directory
SUMMARY_FILENAME_TEMPLATE = "conversation_summary_{id}.md"
FULL_DUMP_FILENAME = "all_conversations_dump.txt"
USER_PROMPTS_FILENAME = "all_user_prompts.txt"
ASSISTANT_RESPONSES_FILENAME = "all_assistant_responses.txt"

# --- Helper Functions ---

def ensure_output_dir(output_dir):
    """Ensures the output directory exists."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

def format_timestamp(ts):
    """Converts UNIX timestamp to a human-readable string."""
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

def get_message_content(message_data):
    """Extracts and combines content parts from a message."""
    if not message_data or "content" not in message_data:
        return ""
    
    content_type = message_data["content"].get("content_type")
    parts = message_data["content"].get("parts", [])
    
    full_content = ""
    
    if content_type == "text":
        full_content = "".join(p for p in parts if isinstance(p, str))
    elif content_type == "code":
        code_text = message_data["content"].get("text", "") 
        full_content = f"```\n{code_text}\n```" # Generic code block
        # Try to detect language for syntax highlighting in markdown
        # This is a simple heuristic
        if "metadata" in message_data["content"] and \
           message_data["content"]["metadata"].get("language"):
            lang = message_data["content"]["metadata"]["language"]
            full_content = f"```{lang}\n{code_text}\n```"
    elif content_type == "tether_browsing_display":
        texts = [part.get("text", "") for part in parts if isinstance(part, dict) and "text" in part]
        if not texts:
             texts = [str(part) for part in parts]
        full_content = "Browsing Result:\n" + "\n".join(texts)
    elif content_type == "multimodal_text":
        combined_parts = []
        for part in parts:
            if isinstance(part, str):
                combined_parts.append(part)
            elif isinstance(part, dict):
                part_content_type = part.get("content_type")
                if part_content_type == "image_asset_pointer":
                    asset_pointer = part.get("asset_pointer", "").split(":")[-1]
                    # The actual DALL-E prompt is often in the metadata of the *user* message that triggered this,
                    # or sometimes in the 'text' part of the multimodal_text itself if the user explicitly wrote it.
                    # This parsing focuses on what the *assistant* message contains.
                    # If the image was generated, metadata might be here:
                    dalle_metadata = message_data["metadata"].get("dalle_image_details", {}).get("prompt") # Hypothetical structure
                    if dalle_metadata:
                         combined_parts.append(f"[DALL-E Image generated from prompt: {dalle_metadata} - ID: {asset_pointer}]")
                    else:
                         combined_parts.append(f"[Image Asset: {asset_pointer}]")

                elif part_content_type == "image_url": # For GPT-4V image input by user, shown in assistant reply
                    combined_parts.append(f"[Image from URL: {part.get('image_url', {}).get('url', 'N/A')}]")
                else:
                    combined_parts.append(f"[Multimodal part: {part_content_type} - {str(part)[:100]}]")


        full_content = "\n".join(combined_parts)
    else:
        full_content = "".join(str(p) for p in parts)
        if content_type:
            full_content = f"[{content_type.upper()}_CONTENT]\n{full_content}"
        else:
            full_content = f"[UNKNOWN_CONTENT_TYPE]\n{full_content}"
            
    return full_content.strip()

def get_model_slug(message_data):
    """Extracts the model slug from message metadata."""
    if message_data and "metadata" in message_data:
        metadata = message_data["metadata"]
        model_slug = metadata.get("model_slug")
        if model_slug:
            return model_slug
        
        invoked_plugin = metadata.get("invoked_plugin")
        if isinstance(invoked_plugin, dict):
            return f"plugin:{invoked_plugin.get('namespace', 'unknown_plugin')}"
            
        if metadata.get("message_type") == "code" or metadata.get("finish_details", {}).get("type") == "code_output":
            return "code-interpreter" # Or advanced-data-analysis
        
        user_context_msg_meta = metadata.get("user_context_message_metadata")
        if user_context_msg_meta and user_context_msg_meta.get("model_slug"):
             return user_context_msg_meta.get("model_slug") + " (via user_context)"

    return "unknown_model"

# --- Main Parsing Logic ---

def parse_conversation(convo_data):
    """Parses a single conversation object to extract its messages in order."""
    title = convo_data.get("title", "Untitled Conversation")
    convo_id = convo_data.get("conversation_id") # Export format changed 'id' to 'conversation_id' for top-level
    if not convo_id: # Fallback for older exports
        convo_id = convo_data.get("id")

    create_time = convo_data.get("create_time")
    update_time = convo_data.get("update_time")
    
    mapping = convo_data.get("mapping", {})
    if not mapping:
        return None

    ordered_messages = []
    current_node_id = convo_data.get("current_node")
    
    temp_messages = []
    while current_node_id:
        node = mapping.get(current_node_id)
        if not node:
            break 

        message_data = node.get("message")
        if message_data and message_data.get("author"):
            author_role = message_data["author"]["role"]
            # System messages can contain useful context (like custom instructions for plugins, or initial setup)
            # We might want to include them conditionally later. For now, skipping for general chat flow.
            if author_role == "system" and not message_data.get("content", {}).get("parts"): 
                # Skip purely structural system messages, but keep if they have content (e.g. custom instructions snippet)
                # A more robust way to handle custom instructions would be to look for specific metadata or structure.
                parent_id = node.get("parent")
                current_node_id = parent_id
                continue

            content = get_message_content(message_data)
            msg_create_time = message_data.get("create_time")
            model_slug = get_model_slug(message_data) if author_role == "assistant" else None
            
            temp_messages.append({
                "id": node["id"],
                "role": author_role,
                "content": content,
                "timestamp": msg_create_time,
                "model": model_slug
            })
        
        parent_id = node.get("parent")
        current_node_id = parent_id

    ordered_messages = list(reversed(temp_messages))

    return {
        "id": convo_id,
        "title": title,
        "create_time_unix": create_time,
        "update_time_unix": update_time,
        "create_time_str": format_timestamp(create_time),
        "update_time_str": format_timestamp(update_time),
        "messages": ordered_messages,
        "message_count": len(ordered_messages)
    }

def load_and_parse_conversations(filepath):
    """Loads the JSON file and parses all conversations."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # The conversations.json is a list of conversation objects directly
            raw_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON from {filepath}. {e}")
        return []

    parsed_conversations = []
    if not isinstance(raw_data, list):
        print(f"Error: Expected a list of conversations in {filepath}, but got {type(raw_data)}")
        return []
        
    for convo_data in raw_data:
        parsed_convo = parse_conversation(convo_data)
        if parsed_convo:
            parsed_conversations.append(parsed_convo)
    
    parsed_conversations.sort(key=lambda c: c.get("create_time_unix", 0) or 0, reverse=True)
    return parsed_conversations

# --- Analysis and Output Functions ---

def generate_markdown_summary(conversation):
    """Generates a Markdown summary for a single conversation."""
    md = f"# Conversation: {conversation['title']}\n\n"
    md += f"- **ID:** {conversation['id']}\n"
    md += f"- **Created:** {conversation['create_time_str']}\n"
    md += f"- **Updated:** {conversation['update_time_str']}\n"
    md += f"- **Total Messages:** {conversation['message_count']}\n\n"
    
    user_message_count = 0
    assistant_message_count = 0
    system_message_count = 0
    models_used = set()

    for msg in conversation["messages"]:
        role = msg['role'].capitalize()
        timestamp_str = format_timestamp(msg['timestamp'])
        
        if msg['role'] == 'user':
            user_message_count += 1
            md += f"## User ({timestamp_str}):\n"
        elif msg['role'] == 'assistant':
            assistant_message_count += 1
            model_info = f" (Model: {msg['model']})" if msg['model'] and msg['model'] != 'unknown_model' else ""
            if msg['model'] and msg['model'] != 'unknown_model':
                models_used.add(msg['model'])
            md += f"## Assistant{model_info} ({timestamp_str}):\n"
        elif msg['role'] == 'system':
            system_message_count +=1
            md += f"## System ({timestamp_str}):\n" # Included for completeness if they pass the filter
        else: # tool, etc.
            md += f"## {role} ({timestamp_str}):\n"


        content_lines = msg['content'].split('\n')
        is_code_block = False
        for line in content_lines:
            if line.startswith("```"):
                is_code_block = not is_code_block
                md += f"{line}\n"
            elif is_code_block:
                md += f"{line}\n" # Preserve lines within code block as is
            elif line.strip() == "":
                 md += "\n"
            else:
                 md += f"> {line}\n"
        md += "\n"
    
    md += f"## Summary Stats:\n"
    md += f"- User Messages: {user_message_count}\n"
    md += f"- Assistant Messages: {assistant_message_count}\n"
    if system_message_count > 0:
        md += f"- System Messages: {system_message_count}\n"
    if models_used:
        md += f"- Models Used: {', '.join(sorted(list(models_used)))}\n"
    else:
        md += f"- Models Used: N/A\n"

    return md

def save_individual_summaries(conversations, output_dir):
    """Saves each conversation as a separate Markdown file."""
    print(f"\nSaving individual conversation summaries to '{output_dir}'...")
    count = 0
    for convo in conversations:
        summary_md = generate_markdown_summary(convo)
        safe_title = re.sub(r'[^\w\s-]', '', convo['title']).strip()
        safe_title = re.sub(r'[-\s]+', '-', safe_title)
        if not safe_title: safe_title = "untitled"
        
        filename = os.path.join(output_dir, f"conversation_{convo['id']}_{safe_title[:50]}.md")
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(summary_md)
            count += 1
        except Exception as e:
            print(f"Error saving summary for conversation ID '{convo['id']}' ('{convo['title']}'): {e}")
    print(f"Done saving {count} summaries.")


def save_full_dump(conversations, output_dir):
    """Saves all conversation content to a single text file."""
    filepath = os.path.join(output_dir, FULL_DUMP_FILENAME)
    print(f"\nSaving full dump to '{filepath}'...")
    with open(filepath, 'w', encoding='utf-8') as f:
        for convo in conversations:
            f.write(f"--- Conversation Start: {convo['title']} ({convo['id']}) ---\n")
            f.write(f"Created: {convo['create_time_str']}, Updated: {convo['update_time_str']}\n\n")
            for msg in convo['messages']:
                role = msg['role'].upper()
                model_info = f" (Model: {msg['model']})" if msg['model'] and msg['model'] != 'unknown_model' and msg['role'] == 'assistant' else ""
                f.write(f"[{format_timestamp(msg['timestamp'])}] {role}{model_info}:\n{msg['content']}\n\n")
            f.write(f"--- Conversation End: {convo['title']} ---\n\n\n")
    print("Done saving full dump.")

def save_prompts_and_responses(conversations, output_dir):
    """Saves all user prompts and assistant responses to separate files."""
    user_prompts_path = os.path.join(output_dir, USER_PROMPTS_FILENAME)
    assistant_responses_path = os.path.join(output_dir, ASSISTANT_RESPONSES_FILENAME)

    print(f"\nSaving all user prompts to '{user_prompts_path}'...")
    with open(user_prompts_path, 'w', encoding='utf-8') as f_prompts:
        for convo in conversations:
            for msg in convo['messages']:
                if msg['role'] == 'user':
                    f_prompts.write(f"--- Prompt from convo '{convo['title']}' ({convo['id']}) on {format_timestamp(msg['timestamp'])} ---\n")
                    f_prompts.write(msg['content'] + "\n\n")
    print("Done saving user prompts.")

    print(f"\nSaving all assistant responses to '{assistant_responses_path}'...")
    with open(assistant_responses_path, 'w', encoding='utf-8') as f_responses:
        for convo in conversations:
            for msg in convo['messages']:
                if msg['role'] == 'assistant':
                    model_info = f" (Model: {msg['model']})" if msg['model'] and msg['model'] != 'unknown_model' else ""
                    f_responses.write(f"--- Response from convo '{convo['title']}' ({convo['id']}){model_info} on {format_timestamp(msg['timestamp'])} ---\n")
                    f_responses.write(msg['content'] + "\n\n")
    print("Done saving assistant responses.")

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(
        description="Parse ChatGPT conversations.json file and generate summaries and analysis.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Shows default values in help
    )
    parser.add_argument(
        "-s", "--source",
        default=DEFAULT_INPUT_FILENAME,
        help="Path to the conversations.json file."
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="Directory to save analysis files."
    )
    parser.add_argument(
        "--skip-individual-summaries",
        action="store_true",
        help="Do not save individual Markdown summaries for each conversation."
    )
    parser.add_argument(
        "--skip-full-dump",
        action="store_true",
        help="Do not save the full text dump of all conversations."
    )
    parser.add_argument(
        "--skip-prompts-file",
        action="store_true",
        help="Do not save the aggregated file of all user prompts."
    )
    parser.add_argument(
        "--skip-responses-file",
        action="store_true",
        help="Do not save the aggregated file of all assistant responses."
    )
    args = parser.parse_args()

    # Use parsed arguments
    input_file = args.source
    output_directory = args.output_dir

    ensure_output_dir(output_directory)
    
    if not os.path.exists(input_file):
        print(f"Error: The input file '{input_file}' was not found.")
        print(f"Please make sure the file exists or provide the correct path using -s or --source.")
        return # Exit if input file not found
    
    print(f"Loading and parsing conversations from: {input_file}")
    all_conversations = load_and_parse_conversations(input_file)
    
    if not all_conversations:
        print("No conversations were parsed. Check the input file and logs, or the file might be empty/corrupted.")
        return

    print(f"Successfully parsed {len(all_conversations)} conversations.")

    if all_conversations:
        if not args.skip_individual_summaries:
            save_individual_summaries(all_conversations, output_directory)
        else:
            print("\nSkipping individual summaries as per --skip-individual-summaries.")

        if not args.skip_full_dump:
            save_full_dump(all_conversations, output_directory)
        else:
            print("\nSkipping full dump as per --skip-full-dump.")
        
        if not args.skip_prompts_file or not args.skip_responses_file:
            # We can optimize this a bit if both are skipped, but calling the function is fine.
            # The function itself handles the checks internally if we want to refactor later.
            # For now, call and let it produce files based on flags.
            # A slightly better way is to call a wrapper or check flags here.
            # For simplicity, this structure is okay.
            if not args.skip_prompts_file and not args.skip_responses_file:
                 save_prompts_and_responses(all_conversations, output_directory)
            else: # One or both are skipped
                if not args.skip_prompts_file:
                    user_prompts_path = os.path.join(output_directory, USER_PROMPTS_FILENAME)
                    print(f"\nSaving all user prompts to '{user_prompts_path}'...")
                    with open(user_prompts_path, 'w', encoding='utf-8') as f_prompts:
                        for convo in all_conversations:
                            for msg in convo['messages']:
                                if msg['role'] == 'user':
                                    f_prompts.write(f"--- Prompt from convo '{convo['title']}' ({convo['id']}) on {format_timestamp(msg['timestamp'])} ---\n")
                                    f_prompts.write(msg['content'] + "\n\n")
                    print("Done saving user prompts.")
                else:
                    print("\nSkipping user prompts file as per --skip-prompts-file.")

                if not args.skip_responses_file:
                    assistant_responses_path = os.path.join(output_directory, ASSISTANT_RESPONSES_FILENAME)
                    print(f"\nSaving all assistant responses to '{assistant_responses_path}'...")
                    with open(assistant_responses_path, 'w', encoding='utf-8') as f_responses:
                        for convo in all_conversations:
                            for msg in convo['messages']:
                                if msg['role'] == 'assistant':
                                    model_info = f" (Model: {msg['model']})" if msg['model'] and msg['model'] != 'unknown_model' else ""
                                    f_responses.write(f"--- Response from convo '{convo['title']}' ({convo['id']}){model_info} on {format_timestamp(msg['timestamp'])} ---\n")
                                    f_responses.write(msg['content'] + "\n\n")
                    print("Done saving assistant responses.")
                else:
                    print("\nSkipping assistant responses file as per --skip-responses-file.")


        # --- Example Analysis (add more here!) ---
        print("\n--- Basic Analysis Examples ---")
        
        total_user_msgs = sum(sum(1 for m in c['messages'] if m['role'] == 'user') for c in all_conversations)
        total_assistant_msgs = sum(sum(1 for m in c['messages'] if m['role'] == 'assistant') for c in all_conversations)
        print(f"Total User Messages: {total_user_msgs}")
        print(f"Total Assistant Messages: {total_assistant_msgs}")

        model_counts = {}
        for convo in all_conversations:
            for msg in convo['messages']:
                if msg['role'] == 'assistant' and msg['model'] and msg['model'] != 'unknown_model':
                    model_counts[msg['model']] = model_counts.get(msg['model'], 0) + 1
        print("\nModels used by assistant:")
        if model_counts:
            for model, count in sorted(model_counts.items(), key=lambda item: item[1], reverse=True):
                print(f"- {model}: {count} times")
        else:
            print("No specific model information found in assistant messages.")
        
        keyword = "python" 
        keyword_conversations = []
        for convo in all_conversations:
            title_match = keyword.lower() in convo['title'].lower()
            content_match = any(keyword.lower() in msg['content'].lower() for msg in convo['messages'])
            if title_match or content_match:
                keyword_conversations.append(convo['title'])
        
        if keyword_conversations:
            print(f"\nConversations mentioning '{keyword}' (in title or content) (sample):")
            for title in keyword_conversations[:10]:
                print(f"- {title}")
            if len(keyword_conversations) > 10:
                print(f"... and {len(keyword_conversations) - 10} more.")
        else:
            print(f"\nNo conversations found mentioning '{keyword}'.")

        print(f"\nAll enabled outputs saved to the '{output_directory}' directory.")
        print("\n--- Further Analysis Ideas ---")
        print("- Analyze frequency of topics/keywords in your prompts (e.g., using --content-filter, to be added).")
        print("- Calculate average length of prompts vs. responses.")
        print("- Identify conversations with code interpreter or browsing (check model types).")
        print("- Track usage over time (e.g., number of conversations per month - requires date parsing & grouping).")

    else:
        print("No conversations were parsed. Check the input file and logs.")

if __name__ == "__main__":
    main()
