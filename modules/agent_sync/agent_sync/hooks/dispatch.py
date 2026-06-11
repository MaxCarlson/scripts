"""Provider hook dispatch entry point placeholder."""

import argparse


def main(argv: list[str] | None = None) -> int:
    """Accept hook events from providers.

    Full hook enforcement belongs to the sequential/worktree phases. This minimal
    entry point exists so generated hook configs have a stable target.
    """
    parser = argparse.ArgumentParser(prog="python -m agent_sync.hooks.dispatch")
    parser.add_argument("-e", "--event", default="unknown", help="Provider event name.")
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
