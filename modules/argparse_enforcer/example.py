#!/usr/bin/env python3
"""
Example usage of EnforcedArgumentParser.

This demonstrates how to use the argparse_enforcer module to create
a CLI with enforced argument naming conventions.
"""

from argparse_enforcer import EnforcedArgumentParser, print_quick_status


def main():
    """Example CLI application."""
    # Create parser with enforced naming conventions
    parser = EnforcedArgumentParser(
        description="Example CLI with enforced argument conventions",
        epilog="Try tab completion if argcomplete is installed!"
    )

    # Add arguments - both abbreviated and full forms required
    parser.add_argument(
        "-f", "--file",
        required=True,
        help="Input file path"
    )

    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: stdout)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress output"
    )

    parser.add_argument(
        "-F", "--format",
        choices=["json", "xml", "csv"],
        default="json",
        help="Output format"
    )

    parser.add_argument(
        "-n", "--num-workers",
        type=int,
        default=4,
        help="Number of worker threads"
    )

    # Parse arguments - argcomplete is automatically set up
    args = parser.parse_args()

    # Use the arguments
    print(f"Processing file: {args.file}")
    if args.output:
        print(f"Output will be written to: {args.output}")
    print(f"Format: {args.format}")
    print(f"Workers: {args.num_workers}")

    if args.verbose:
        print("Verbose mode enabled")
    if args.quiet:
        print("Quiet mode enabled")


if __name__ == "__main__":
    # Optionally show argcomplete status
    import sys
    if "--check-setup" in sys.argv:
        print_quick_status()
        sys.exit(0)

    main()
