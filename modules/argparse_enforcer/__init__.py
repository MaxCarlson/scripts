# argparse_enforcer/__init__.py
from .enforcer import EnforcedArgumentParser
from .setup_instructions import (
    print_setup_instructions,
    print_quick_status,
    check_argcomplete_installed,
    get_setup_instructions
)

__all__ = [
    "EnforcedArgumentParser",
    "print_setup_instructions",
    "print_quick_status",
    "check_argcomplete_installed",
    "get_setup_instructions",
    "__version__"
]
__version__ = "0.1.0"
