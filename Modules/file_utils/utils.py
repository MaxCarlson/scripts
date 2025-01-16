import hashlib


def calculate_file_hash(file_path, block_size=65536):
    """Calculate the hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(block_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_debug(message, channel="Debug", condition=True):
    """Print debug messages."""
    if condition:
        print(f"[{channel}] {message}")
