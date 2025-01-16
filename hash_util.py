import os
import hashlib
from filelock import FileLock

HEADER_FILE = os.path.expanduser("~/tmp/mrsync_header.txt")
LOCK_FILE = os.path.expanduser("~/tmp/mrsync.lock")

def compute_script_hash(script_path):
    """Compute the SHA-256 hash of the given script."""
    hash_sha256 = hashlib.sha256()
    with open(script_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()

def validate_header(script_path, verbose_print):
    """Validate and reset the header if necessary."""
    script_hash = compute_script_hash(script_path)
    verbose_print(2, f"Script hash: {script_hash}")

    # Check if the header exists and matches
    if os.path.exists(HEADER_FILE):
        with open(HEADER_FILE, "r") as header:
            existing_hash = header.read().strip()
            if existing_hash == script_hash:
                verbose_print(2, "[mrsync] Header is valid.")
                return  # Header is valid, nothing to do

    # If header is invalid or missing, reset temporary files
    with FileLock(LOCK_FILE, timeout=0):  # Non-blocking lock
        verbose_print(1, "[mrsync] Invalid or missing header. Resetting temporary files...")
        if os.path.exists(HEADER_FILE):
            os.remove(HEADER_FILE)

        # Recreate header
        with open(HEADER_FILE, "w") as header:
            header.write(script_hash)
            verbose_print(1, f"[mrsync] New header written: {script_hash}")
