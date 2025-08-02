#!/usr/bin/env python3
import os
import hashlib
import argparse
import shutil

def compute_file_hash(file_path, block_size=65536):
    """
    Compute the SHA-256 hash of a file.
    """
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while True:
                data = f.read(block_size)
                if not data:
                    break
                hasher.update(data)
    except Exception as e:
        print(f"Error computing hash for {file_path}: {e}")
        return None
    return hasher.hexdigest()

def compute_folder_hashes(folder_path):
    """
    Recursively compute the hashes for all files in folder_path.
    Returns a set of file hashes.
    """
    hash_set = set()
    for root, _, files in os.walk(folder_path):
        for file in files:
            full_path = os.path.join(root, file)
            h = compute_file_hash(full_path)
            if h is not None:
                hash_set.add(h)
    return hash_set

def get_immediate_subdirectories(dir_path):
    """
    Return a dictionary mapping folder names to full paths for all immediate subdirectories of dir_path.
    """
    result = {}
    try:
        for entry in os.listdir(dir_path):
            full_path = os.path.join(dir_path, entry)
            if os.path.isdir(full_path):
                result[entry] = full_path
    except Exception as e:
        print(f"Error listing subdirectories of {dir_path}: {e}")
    return result

def jaccard_similarity(set1, set2):
    """
    Compute the similarity percentage (Jaccard index) between two sets.
    If both sets are empty, returns 100.0.
    """
    if not set1 and not set2:
        return 100.0  # both empty; consider them identical
    union = set1.union(set2)
    if not union:
        return 0.0
    intersection = set1.intersection(set2)
    return (len(intersection) / len(union)) * 100

def main():
    parser = argparse.ArgumentParser(
        description="Scan a --sources directory (and its subdirectories) to record each top-level folder's file hashes, "
                    "then scan a --target directory for folders with matching names and report how similar (as a percentage) "
                    "they are based on file hashes. Optionally, delete target directories that are at least x% similar."
    )
    parser.add_argument("-s", "--sources", required=True,
                        help="Source directory to scan for folders")
    parser.add_argument("-t", "--target", required=True,
                        help="Target directory to compare against")
    parser.add_argument("-d", "--delete", type=float,
                        help="Delete target directories that are at least x%% similar to the corresponding source folder")
    parser.add_argument("-x", "--dry-run", action="store_true",
                        help="Dry-run mode: do not actually delete, just show which directories would be deleted")
    
    args = parser.parse_args()

    # Resolve absolute paths
    source_dir = os.path.abspath(args.sources)
    target_dir = os.path.abspath(args.target)

    if not os.path.isdir(source_dir):
        print(f"Source directory '{source_dir}' does not exist or is not a directory.")
        return
    if not os.path.isdir(target_dir):
        print(f"Target directory '{target_dir}' does not exist or is not a directory.")
        return

    print("Scanning source directories...")
    source_subdirs = get_immediate_subdirectories(source_dir)
    source_hashes = {}
    for folder_name, folder_path in source_subdirs.items():
        print(f"  Computing hashes for source folder: '{folder_name}'...")
        source_hashes[folder_name] = compute_folder_hashes(folder_path)

    print("\nScanning target directories...")
    target_subdirs = get_immediate_subdirectories(target_dir)
    target_hashes = {}
    for folder_name, folder_path in target_subdirs.items():
        print(f"  Computing hashes for target folder: '{folder_name}'...")
        target_hashes[folder_name] = compute_folder_hashes(folder_path)

    print("\nComparing matching folder names:")
    results = []  # will store tuples of (folder_name, similarity)
    for folder_name, src_hash_set in source_hashes.items():
        if folder_name in target_hashes:
            tgt_hash_set = target_hashes[folder_name]
            similarity = jaccard_similarity(src_hash_set, tgt_hash_set)
            results.append((folder_name, similarity))
            print(f"  Folder '{folder_name}': Similarity = {similarity:.2f}%")
        else:
            print(f"  Folder '{folder_name}' not found in target.")

    # If a deletion threshold is provided, process deletions on target folders.
    if args.delete is not None:
        threshold = args.delete
        print(f"\nDeletion threshold set to {threshold}%")
        for folder_name, similarity in results:
            if similarity >= threshold:
                target_folder_path = target_subdirs[folder_name]
                if args.dry_run:
                    print(f"[Dry Run] Would delete target folder '{folder_name}' (Similarity: {similarity:.2f}%)")
                else:
                    print(f"Deleting target folder '{folder_name}' (Similarity: {similarity:.2f}%)...")
                    try:
                        shutil.rmtree(target_folder_path)
                    except Exception as e:
                        print(f"Error deleting folder '{folder_name}': {e}")
    else:
        print("\nNo deletion threshold specified; only reporting similarity results.")

if __name__ == "__main__":
    main()
