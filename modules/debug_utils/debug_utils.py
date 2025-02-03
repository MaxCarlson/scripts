"""
This module is deprecated.
It forwards all calls to the new implementation in cross_platform.debug_utils.
Please update your imports to use cross_platform.debug_utils.
"""

import warnings

warnings.warn(
    "The 'debug_utils' module is deprecated. Please use 'cross_platform.debug_utils' instead.",
    DeprecationWarning,
    stacklevel=2
)

try:
    from cross_platform.debug_utils import *
except ImportError:
    raise ImportError("cross_platform package not installed. Please install it first.")

