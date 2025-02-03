"""
This module serves as a thin wrapper to maintain backward compatibility.
It forwards clipboard functions to the new implementation in cross_platform.
"""

try:
    from cross_platform.clipboard_utils import ClipboardUtils
except ImportError:
    raise ImportError("cross_platform package not installed. Please install it first.")

def set_clipboard(text):
    """
    Set clipboard content using the new implementation.
    """
    cp = ClipboardUtils()
    return cp.set_clipboard(text)

def get_clipboard():
    """
    Get clipboard content using the new implementation.
    """
    cp = ClipboardUtils()
    return cp.get_clipboard()

