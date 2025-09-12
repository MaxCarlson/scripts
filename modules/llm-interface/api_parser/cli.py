import argparse
from api_parser import api_doc_generator
from api_parser import api_validator

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
        help="Path to the Python module directory."
    )
    gen_parser.add_argument(
        "-d", "--debug", action="store_true",
        help="Print the parsed API dictionary for debugging."
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
        help="Path to the Python module directory."
    )
    val_parser.add_argument(
        "-d", "--debug", action="store_true",
        help="Print the parsed API dictionaries for debugging."
    )
    val_parser.set_defaults(func=api_validator.run_validator)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()