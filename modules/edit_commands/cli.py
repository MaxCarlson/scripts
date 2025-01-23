import argparse
import os
from edit_commands.core import get_shell_history, parse_run_order, process_command
from edit_commands.executor import execute_commands

def main():
    parser = argparse.ArgumentParser(description="Modify and re-run previous shell commands.")
    parser.add_argument("-m", "--max-age", type=int, default=100, help="Max number of historical commands to retrieve.")
    parser.add_argument("-o", "--run-order", type=str, default="[0]", help="Order of commands to execute.")
    parser.add_argument("-p", "--parallel", action="store_true", help="Run all specified commands in parallel.")
    parser.add_argument("-f", "--force", action="store_true", help="Continue execution even if a command fails.")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Print modified commands instead of executing them.")

    parser.add_argument("-v", "--vim", nargs="+", help="Vim-style substitution.")
    parser.add_argument("-g", "--glob", nargs="+", help="Glob patterns to replace.")
    parser.add_argument("-r", "--regex", nargs="+", help="Regex pattern to replace.")
    parser.add_argument("--replace", nargs="+", help="Replacement values for --glob or --regex.")

    args = parser.parse_args()
    shell = os.getenv("SHELL", "pwsh").split("/")[-1]

    history = get_shell_history(args.max_age, shell)
    run_indices = parse_run_order(args.run_order, len(history))
    commands = [process_command(history[idx], args, i) for i, idx in enumerate(run_indices)]
    
    execute_commands(commands, parallel=args.parallel, dry_run=args.dry_run, force=args.force)

if __name__ == "__main__":
    main()
