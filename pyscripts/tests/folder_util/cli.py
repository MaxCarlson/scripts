# folder_util/cli.py

import argparse

def get_args():
    parser = argparse.ArgumentParser(
        description="Folder and File Utilities Tool"
    )
    # Basic options
    parser.add_argument("--target", "-t", type=str, default=".",
                        help="Target folder path.")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Recursively scan subdirectories.")
    parser.add_argument("--depth", "-d", type=int, default=None,
                        help="Limit recursion to a specific depth.")
    parser.add_argument("--size", "-s", action="store_true",
                        help="Include file/folder sizes.")
    parser.add_argument("--date", "-D", action="store_true",
                        help="Include date added information.")
    parser.add_argument("--sort", "-S", type=str, default="date",
                        choices=["name", "size", "date"],
                        help="Sort criteria: name, size, or date.")
    parser.add_argument("--filter", "-f", type=str, default=None,
                        help="Regex pattern to filter file/folder names.")
    parser.add_argument("--output", "-o", type=str, default="table",
                        choices=["table", "json", "csv"],
                        help="Output format: table, json, or csv.")
    parser.add_argument("--truncate", "-c", type=int, default=20,
                        help="Maximum characters for name display.")
    parser.add_argument("--export", "-e", type=str, default=None,
                        help="File to export output (if specified, results will be written to this file).")
    
    # Extra columns options
    parser.add_argument("--permissions", "-p", action="store_true",
                        help="Include file/folder permissions column.")
    parser.add_argument("--date-modified", "-M", action="store_true",
                        help="Include last modified date/time column.")
    parser.add_argument("--date-created", "-C", action="store_true",
                        help="Include creation date/time column.")
    parser.add_argument("--git-repo", "-g", action="store_true",
                        help="Include a column indicating if the folder is a Git repository.")
    parser.add_argument("--git-status", "-G", action="store_true",
                        help="Include a column showing the Git status.")
    parser.add_argument("--owner", "-O", action="store_true",
                        help="Include the owner of the file/folder.")
    parser.add_argument("--file-count", "-n", action="store_true",
                        help="Include count of files within a folder.")
    parser.add_argument("--attributes", "-A", action="store_true",
                        help="Include extra file/folder attributes (hidden, read-only, etc.).")
    parser.add_argument("--date-accessed", "-X", action="store_true",
                        help="Include last accessed date/time column.")
    
    args = parser.parse_args()
    return args