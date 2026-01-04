#!/usr/bin/env python
import argparse
import json
import logging
import os
import random
import shutil
import sys
from pathlib import Path
from tqdm import tqdm

# Configure logging for verbose output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_source_path(path_str):
    """Parses a source path with optional recursion depth like /path/to/dir::d<N>."""
    if '::d' in path_str:
        path, depth_str = path_str.rsplit('::d', 1)
        try:
            depth = int(depth_str)
            return Path(path), depth
        except (ValueError, TypeError):
            raise argparse.ArgumentTypeError(f"Invalid recursion depth: '{depth_str}' in '{path_str}'")
    return Path(path_str), -1  # -1 for infinite depth

def find_video_files(source_path, recursion_depth, extensions):
    """Finds all video files in a given path up to a certain recursion depth."""
    video_files = []
    source_path = Path(source_path)
    if not source_path.is_dir():
        logging.warning(f"Source path {source_path} is not a directory. Skipping.")
        return []

    if recursion_depth == -1: # Infinite recursion
        for ext in extensions:
            video_files.extend(list(source_path.rglob(f'*{ext}')))
    elif recursion_depth == 0: # No recursion
         for ext in extensions:
            video_files.extend([f for f in source_path.glob(f'*{ext}') if f.is_file()])
    else: # Limited recursion
        # We simulate this by checking path depth
        base_depth = len(source_path.parts)
        for ext in extensions:
            for file_path in source_path.rglob(f'*{ext}'):
                if len(file_path.parts) <= base_depth + recursion_depth + 1:
                     video_files.append(file_path)

    return video_files


def copy_with_progress(source, dest, pbar):
    """Copies a file from source to dest and updates a tqdm progress bar."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    buffer_size = 1024 * 1024  # 1MB buffer

    with open(source, 'rb') as fsrc, open(dest, 'wb') as fdest:
        while True:
            buf = fsrc.read(buffer_size)
            if not buf:
                break
            fdest.write(buf)
            pbar.update(len(buf))

def main():
    """Main function to parse arguments and run the video copier."""
    parser = argparse.ArgumentParser(
        description="""A script to copy a random selection of video files from source(s) to a destination.
        Supports size/count limits and can be resumed.
        """,
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-s', '--source',
        type=parse_source_path,
        required=True,
        action='append',
        help="""Source path(s). Can be specified multiple times.
Append '::d<N>' to a path to limit recursion depth.
- '::d0': No recursion (only files in the immediate directory).
- '::d1': One level of subdirectories.
- No specifier: Infinite recursion.
Example: -s /videos/movies::d0 -s /videos/series
"""
    )
    parser.add_argument(
        '-d', '--destination',
        type=Path,
        required=True,
        help="Destination directory to copy files to."
    )
    parser.add_argument(
        '-c', '--count-limit',
        type=int,
        default=sys.maxsize,
        help="Maximum number of files to copy."
    )
    parser.add_argument(
        '-S', '--size-limit',
        type=float,
        default=float('inf'),
        help="Maximum total size in GB to copy."
    )
    parser.add_argument(
        '-x', '--seed',
        type=int,
        default=42,
        help="Seed for the random number generator for deterministic selection."
    )
    parser.add_argument(
        '-r', '--resume',
        action='store_true',
        help="Resume a previous run. Requires --log-file."
    )
    parser.add_argument(
        '-l', '--log-file',
        type=Path,
        default=Path('copy_state.json'),
        help="Log file to store the state of copied files for resuming."
    )
    parser.add_argument(
        '-e', '--video-extensions',
        nargs='+',
        default=['.mp4', '.mkv', '.avi', '.mov', '.webm'],
        help="List of video file extensions to search for."
    )
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help="Perform a dry run: list files that would be copied without actually copying them."
    )

    args = parser.parse_args()

    # --- State Initialization ---
    state = {
        'copied_files': {},
        'total_size_copied': 0,
        'total_count_copied': 0
    }
    if args.resume and args.log_file.exists():
        logging.info(f"Resuming from state file: {args.log_file}")
        with open(args.log_file, 'r') as f:
            state = json.load(f)

    # --- File Discovery ---
    logging.info("Discovering video files...")
    all_files = []
    for source_path, depth in args.source:
        logging.info(f"Scanning '{source_path}' with recursion depth {depth if depth != -1 else 'infinite'}...")
        all_files.extend(find_video_files(source_path, depth, args.video_extensions))

    # Use a set for efficient lookup of absolute paths
    unique_files = {f.resolve() for f in all_files}
    files_to_consider = [f for f in unique_files if str(f) not in state['copied_files']]
    logging.info(f"Found {len(unique_files)} unique video files. {len(files_to_consider)} remaining to consider.")

    # --- Randomization ---
    random.seed(args.seed)
    random.shuffle(files_to_consider)

    # --- Main Copy Loop ---
    size_limit_bytes = args.size_limit * (1024**3)
    pbar_total = tqdm(
        total=min(args.count_limit, len(files_to_consider)),
        desc="Overall Progress",
        unit="file",
        initial=state['total_count_copied']
    )

    for file_path in files_to_consider:
        if state['total_count_copied'] >= args.count_limit:
            logging.info("File count limit reached.")
            break

        file_size = file_path.stat().st_size
        if state['total_size_copied'] + file_size > size_limit_bytes:
            logging.info("Size limit would be exceeded. Stopping.")
            break

        dest_file_path = args.destination / file_path.name
        if dest_file_path.exists():
            logging.warning(f"File '{dest_file_path}' already exists in destination. Skipping.")
            continue
        
        if args.dry_run:
            logging.info(f"[DRY RUN] Would copy '{file_path}' to '{dest_file_path}' ({file_size / (1024**2):.2f} MB)")
            state['total_size_copied'] += file_size
            state['total_count_copied'] += 1
            pbar_total.update(1)
            continue

        logging.info(f"Copying '{file_path.name}'...")
        with tqdm(total=file_size, desc=f'  -> {file_path.name[:30]}...', unit='B', unit_scale=True, unit_divisor=1024, leave=False) as pbar_file:
            try:
                copy_with_progress(file_path, dest_file_path, pbar_file)
            except Exception as e:
                logging.error(f"Failed to copy {file_path}: {e}")
                if dest_file_path.exists():
                    dest_file_path.unlink() # Clean up partial file
                continue
        
        # --- Update State ---
        state['copied_files'][str(file_path.resolve())] = {
            'size': file_size,
            'destination': str(dest_file_path.resolve())
        }
        state['total_size_copied'] += file_size
        state['total_count_copied'] += 1

        with open(args.log_file, 'w') as f:
            json.dump(state, f, indent=4)
        
        pbar_total.update(1)
        pbar_total.set_postfix({
            'size': f'{state["total_size_copied"] / (1024**3):.2f} GB',
            'last_file': file_path.name
        })

    pbar_total.close()
    logging.info("Copying process finished.")
    logging.info(f"Total files copied: {state['total_count_copied']}")
    logging.info(f"Total size copied: {state['total_size_copied'] / (1024**3):.2f} GB")


if __name__ == "__main__":
    main()
