import os
import sqlite3
import argparse
import subprocess
import threading
import time
from filelock import FileLock
from queue import Queue
import re

# SQLite Database and Lock File Paths
DB_PATH = os.path.expanduser("~/tmp/mrsync.db")
LOCK_FILE = os.path.expanduser("~/tmp/mrsync.lock")

# Global verbosity level
VERBOSE_LEVEL = 0
CONFLICT_DEFERRED = Queue()  # Queue to handle deferred conflicts

# Ensure the database is initialized
def initialize_database():
    verbose_print(1, "Initializing database...")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued', 'active', 'completed'))
            )
        """)
        conn.commit()

# Verbose printing function
def verbose_print(level, message):
    if VERBOSE_LEVEL >= level:
        print(message)

# Add a new task to the queue
def add_task(source, destination):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tasks (source, destination, status) VALUES (?, ?, ?)", (source, destination, 'queued'))
        conn.commit()
    verbose_print(2, f"Task added: source={source}, destination={destination}")

# Get the next task in the queue
def get_next_task():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, source, destination FROM tasks WHERE status = 'queued' ORDER BY id ASC LIMIT 1")
        task = cursor.fetchone()
        if task:
            verbose_print(2, f"Next task fetched: {task}")
        return task

# Detect conflicts and return conflicting files
def detect_conflicts(path):
    conflicts = []
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT source, destination FROM tasks WHERE status = 'active'")
        for source, dest in cursor.fetchall():
            if os.path.commonpath([path, source]) == path or os.path.commonpath([path, dest]) == path:
                conflicts.append((source, dest))
    return conflicts

# Handle conflicts by deferring to a separate queue
def handle_conflicts(conflicts, source, destination):
    verbose_print(2, f"[mrsync] Conflicts detected: {conflicts}")
    CONFLICT_DEFERRED.put((source, destination))

# Test parallel vs. sequential performance
def test_parallel_vs_sequential(source, destination):
    verbose_print(2, "[mrsync] Testing parallel vs. sequential performance...")

    # Test sequential write speed
    sequential_start = time.time()
    subprocess.run(['rsync', '-avz', source, destination], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sequential_end = time.time()
    sequential_speed = sequential_end - sequential_start

    # Test parallel write speed
    parallel_start = time.time()
    thread1 = threading.Thread(target=subprocess.run, args=(['rsync', '-avz', source, destination],), kwargs={"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})
    thread2 = threading.Thread(target=subprocess.run, args=(['rsync', '-avz', source, destination],), kwargs={"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})
    thread1.start()
    thread2.start()
    thread1.join()
    thread2.join()
    parallel_end = time.time()
    parallel_speed = parallel_end - parallel_start

    verbose_print(2, f"Sequential speed: {sequential_speed:.2f}s, Parallel speed: {parallel_speed:.2f}s")

    return parallel_speed < sequential_speed

# Run rsync with progress tracking
def rsync_with_progress(source, destination):
    total_files = None
    completed_files = 0
    current_percentage = 0
    transfer_rate = ""
    last_update_time = time.time()

    process = subprocess.Popen(
        ['rsync', '-avz', '--info=progress2', source, destination],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    for line in process.stdout:
        line = line.strip()

        # At verbosity level 3, print all rsync output
        if VERBOSE_LEVEL >= 3:
            print(line)

        # Parse the total number of files and completed files
        to_check_match = re.search(r'to-check=(\d+)/(\d+)', line)
        if to_check_match:
            remaining_files = int(to_check_match.group(1))
            total_files = int(to_check_match.group(2))
            completed_files = total_files - remaining_files

        # Parse the current file transfer percentage and transfer rate
        progress_match = re.search(r'(\d+)%\s+(\d+\.\d+)([A-Za-z]+)/s', line)
        if progress_match:
            current_percentage = int(progress_match.group(1))
            transfer_rate = f"{progress_match.group(2)}{progress_match.group(3)}/s"

        # Display progress ticker every 2 seconds at verbosity level 1 or higher
        if VERBOSE_LEVEL >= 1 and time.time() - last_update_time >= 2:
            if total_files is not None:
                print(f"\rProgress: File {completed_files}/{total_files} "
                      f"({current_percentage}%) at {transfer_rate}", end='', flush=True)
            last_update_time = time.time()

    process.wait()
    if VERBOSE_LEVEL >= 1:
        print()

# Main function
def main():
    global VERBOSE_LEVEL

    parser = argparse.ArgumentParser(description="mrsync - Intelligent rsync manager")
    parser.add_argument("source", help="Source directory")
    parser.add_argument("destination", help="Destination directory")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity level (-v, -vv, -vvv)")
    args = parser.parse_args()

    VERBOSE_LEVEL = args.verbose

    initialize_database()
    with FileLock(LOCK_FILE):
        conflicts = detect_conflicts(args.source)
        if conflicts:
            handle_conflicts(conflicts, args.source, args.destination)
        else:
            if test_parallel_vs_sequential(args.source, args.destination):
                verbose_print(1, "[mrsync] Using parallel mode for this task.")
                threading.Thread(target=rsync_with_progress, args=(args.source, args.destination)).start()
            else:
                verbose_print(1, "[mrsync] Using sequential mode for this task.")
                rsync_with_progress(args.source, args.destination)

if __name__ == "__main__":
    main()
