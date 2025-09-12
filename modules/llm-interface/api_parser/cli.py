import argparse
from api_parser import api_doc_generator
from api_parser import api_validator
from api_parser.sync import run_sync

def main():
    parser = argparse.ArgumentParser(
        description="API Parser CLI for generating and validating API documentation.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-v", "--version", action="version", version="%(prog)s 0.1.0"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Subcommand for API Documentation Generator
    gen_parser = subparsers.add_parser(
        "gen",
        help="Generate API_DOC.md for a Python module.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    gen_parser.add_argument(
        "-m", "--module-path", type=str, required=True,
        help="Path to the root directory containing Python modules."
    )
    gen_parser.add_argument(
        "-d", "--debug", action="store_true",
        help="Print the parsed API dictionary for debugging."
    )
    gen_parser.add_argument(
        "-f", "--force-overwrite", action="store_true",
        help="Force regeneration of API_DOC.md even if it exists, validating first."
    )
    gen_parser.set_defaults(func=api_doc_generator.run_generator)

    # Subcommand for API Validator
    val_parser = subparsers.add_parser(
        "val",
        help="Validate a module's API_DOC.md against its source code.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    val_parser.add_argument(
        "-m", "--module-path", type=str, required=True,
        help="Path to the root directory containing Python modules."
    )
    val_parser.add_argument(
        "-d", "--debug", action="store_true",
        help="Print the parsed API dictionaries for debugging."
    )
    val_parser.set_defaults(func=api_validator.run_validator)

    # Subcommand for API Sync/Audit
    sync_parser = subparsers.add_parser(
        "sync",
        help="Synchronize API documentation: generate missing, validate existing, and regenerate if out of sync.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    sync_parser.add_argument(
        "-m", "--module-path", type=str, required=True,
        help="Path to the root directory containing Python modules."
    )
    sync_parser.add_argument(
        "-d", "--debug", action="store_true",
        help="Print debug information during the sync process."
    )
    sync_parser.set_defaults(func=run_sync)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()