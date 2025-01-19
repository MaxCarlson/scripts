import os
import re
import argparse
import socket
import glob
import json

# Default replacement texts
DEFAULT_TEXT_DEFAULT = {
    "path_prefix": ["this", "is", "a", "path"],
    "username": "username",
    "machine": "machine",
    "ip_v4": "192.168.0.1",
    "ip_v6": "fe80::abcd:abcd:abcd:abcd"
}

# Regex patterns
IPV4_PATTERN = r'(\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b)(?:/\d{1,2}|:\d+)?'
IPV6_PATTERN = r'\b([0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){7}|(?:[0-9a-fA-F]{1,4}:){0,6}:[0-9a-fA-F]{1,4})\b'
USERNAME_PATTERN_WIN = r'C:\\Users\\([^\\/]+)'
USERNAME_PATTERN_LINUX = r'/home/([^/]+)'
MACHINE_NAME = socket.gethostname()
NUM_FIXED_PATH_SEGMENTS = 4

def obfuscate_path(path, DEFAULT_TEXT):
    """Replaces each folder in the path while keeping depth intact."""
    is_windows = "\\" in path
    parts = [p for p in re.split(r"[\\/]", path) if p]

    if not parts:
        return path

    obfuscated_parts = DEFAULT_TEXT["path_prefix"][:min(len(parts), len(DEFAULT_TEXT["path_prefix"]))]

    if len(parts) > len(DEFAULT_TEXT["path_prefix"]):
        obfuscated_parts += [f"f{i+1}" for i in range(len(parts) - len(DEFAULT_TEXT["path_prefix"]))]

    if is_windows and parts and ":" in parts[0]:
        obfuscated_parts = [parts[0]] + obfuscated_parts[1:] # Keep drive letter

    return "\\".join(obfuscated_parts) if is_windows else "/".join(obfuscated_parts)

def obfuscate_partial_path(text, target_path, DEFAULT_TEXT, case_sensitive=True):
    """Replaces a specified portion of a path, optionally case-sensitive."""
    if case_sensitive:
         return text.replace(target_path, obfuscate_path(target_path, DEFAULT_TEXT))
    else:
        escaped_target_path = re.escape(target_path)
        return re.sub(escaped_target_path, lambda match: obfuscate_path(match.group(0), DEFAULT_TEXT), text, flags=re.IGNORECASE)


def apply_glob_replacement(text, glob_patterns):
    """Replaces text based on user-defined glob patterns."""
    for pattern in glob_patterns:
        try:
            search, replace = pattern.split(":", 1)
            matches = glob.glob(search)
            for match in matches:
                 text = text.replace(match, replace)
        except ValueError:
            print(f"Warning: Invalid glob pattern '{pattern}'. Skipping.")
    return text

def apply_regex_replacement(text, regex_patterns):
    """Applies regex-based replacements to the text."""
    for pattern in regex_patterns:
        try:
            search, replace = pattern.split(":", 1)
            text = re.sub(search, replace, text)
        except ValueError:
            print(f"Warning: Invalid regex pattern '{pattern}'. Skipping.")
    return text

def obfuscate_text(text, obfuscate_ip, obfuscate_user, obfuscate_machine, obfuscate_paths, partial_path, glob_patterns, regex_patterns, partial_path_case_sensitive, DEFAULT_TEXT):
    """Processes text with obfuscation and targeted replacements."""

    # Apply glob-based replacements first
    if glob_patterns:
        text = apply_glob_replacement(text, glob_patterns)

    # Apply regex-based replacements next
    if regex_patterns:
        text = apply_regex_replacement(text, regex_patterns)

    # Username obfuscation
    if obfuscate_user:
        text = re.sub(USERNAME_PATTERN_WIN, rf"C:\\Users\\{DEFAULT_TEXT['username']}", text)
        text = re.sub(USERNAME_PATTERN_LINUX, rf"/home/{DEFAULT_TEXT['username']}", text)

    # Machine name obfuscation
    if obfuscate_machine and MACHINE_NAME in text:
        text = text.replace(MACHINE_NAME, DEFAULT_TEXT["machine"])

    # IP address obfuscation
    if obfuscate_ip:
        text = re.sub(IPV4_PATTERN, DEFAULT_TEXT["ip_v4"], text)
        text = re.sub(IPV6_PATTERN, DEFAULT_TEXT["ip_v6"], text)

    # Full path obfuscation
    if obfuscate_paths:
         def replace_path(match):
             matched_string = match.group(0)
             return obfuscate_path(matched_string, DEFAULT_TEXT)
         
         path_regex = r"([a-zA-Z]:)?[\\/][^\\/\s]+" + r"([\\/][^\\/\s]*)"
         text = re.sub(path_regex, replace_path, text)

    # Partial path obfuscation
    if partial_path:
         text = obfuscate_partial_path(text, partial_path, DEFAULT_TEXT, case_sensitive=partial_path_case_sensitive)

    return text

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Anonymize paths, usernames, machine names, IPs, and custom patterns.")

    parser.add_argument("input", type=str, help="Text or file to anonymize")
    parser.add_argument("-u", "--obfuscate-user", action="store_true", help="Obfuscate usernames (default: off)")
    parser.add_argument("-i", "--obfuscate-ip", action="store_true", help="Obfuscate IP addresses (default: off)")
    parser.add_argument("-m", "--obfuscate-machine", action="store_true", help="Obfuscate machine names (default: on)")
    parser.add_argument("-p", "--obfuscate-path", action="store_true", help="Enable full path obfuscation (default: on)")
    parser.add_argument("-pp", "--partial-path", type=str, help="Specify part of a path to obfuscate")
    parser.add_argument("--partial-path-case-sensitive", action="store_true", help="Make partial path obfuscation case-sensitive (default: off)")
    parser.add_argument("-r", "--regex", type=str, nargs="*", help="Custom regex replacements (format: pattern:replacement)")
    parser.add_argument("-g", "--glob", type=str, nargs="*", help="Custom glob replacements (format: pattern:replacement)")
    parser.add_argument("--default-texts", type=str, help="Path to a JSON file containing custom default texts")

    args = parser.parse_args()

    DEFAULT_TEXT = DEFAULT_TEXT_DEFAULT
    if args.default_texts:
        try:
            with open(args.default_texts, 'r') as f:
                DEFAULT_TEXT = json.load(f)
        except FileNotFoundError:
            print(f"Error: Default texts file '{args.default_texts}' not found. Using default values.")
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON format in '{args.default_texts}'. Using default values.")

    if os.path.isfile(args.input):
        with open(args.input, "r", encoding="utf-8") as file:
            data = file.read()
    else:
        data = args.input

    obfuscated_text = obfuscate_text(
        data, args.obfuscate_ip, args.obfuscate_user, args.obfuscate_machine,
        args.obfuscate_path, args.partial_path, args.glob, args.regex, args.partial_path_case_sensitive, DEFAULT_TEXT
    )

    print(obfuscated_text)
