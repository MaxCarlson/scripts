# Scripts in pyscripts/ that are intentionally excluded from the help browser.
# Add shims, internal helpers, or scripts without a user-facing CLI here.

EXCLUDED_SCRIPTS: set[str] = {
    "pyscripts/clipboard_buffers.py",  # legacy shim re-exporting clipboard_tools.buffers
    "pyscripts/dlchem.py",             # no argparse / __main__; utility imported directly
    "pyscripts/setup.py",              # internal repo setup script, not a general-purpose tool
}
