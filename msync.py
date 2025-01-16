# Run rsync with progress tracking
import os
import sys
import time
import argparse
import subprocess
import threading
from filelock import FileLock, Timeout
from queue import Queue
from db_util import initialize_database, add_task, detect_conflicts, active_tasks_on_same_drive
from hash_util import validate_header

LOCK_FILE = os.path.expanduser("~/tmp/mrsync.lock")

# Queue to handle deferred conflicts
CONFLICT_DEFERRED = Queue()

# Global verbosity level
VERBOSE_LEVEL = 0

def verbose_print(level, message):
    """Enhanced verbose print for debugging."""
    if VERBOSE_LEVEL >= level:
        print(f"[DEBUG - {time.strftime('%H:%M:%S')}] {message}")

def count_files_and_size_in_directory(path):
    """Count the total number of files and their cumulative size."""
    total_files = 0
    total_size = 0
    for root, _, files in os.walk(path):
        total_files += len(files)
        for file in files:
            total_size += os.path.getsize(os.path.join(root, file))
    return total_files, total_size

def human_readable_size(size):
    """Convert a size in bytes to a human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

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


def parse_rsync_line(line):
    """Parse an rsync progress line and extract relevant details."""
    try:
        # Split line into parts
        parts = line.split()
        if len(parts) >= 4 and "%" in parts[1]:  # Example: "347.47M 98% 7.52MB/s 0:00:00"
            size_str, percent_str, speed_str, remaining_str = parts[:4]

            # Convert size to bytes
            size_multiplier = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
            size_value = float(size_str[:-1]) * size_multiplier.get(size_str[-1], 1)

            # Extract percent as integer
            percent_value = int(percent_str.replace("%", ""))

            # Keep speed and remaining time as-is for display
            return size_value, percent_value, speed_str, remaining_str
    except (ValueError, IndexError):
        pass

    # Return None for unparsable lines
    return None

def convert_size(size):
    """Convert size in bytes to human-readable format."""
    if size >= 1024 ** 3:  # Convert to GB
        return f"{size / (1024 ** 3):.2f} GB"
    elif size >= 1024 ** 2:  # Convert to MB
        return f"{size / (1024 ** 2):.2f} MB"
    else:  # Convert to KB
        return f"{size / 1024:.2f} KB"

def calculate_total_remaining(completed_size, total_size, speed):
    """Calculate total remaining time for the transfer."""
    if speed != "Calculating..." and speed.endswith("B/s") and completed_size > 0:
        try:
            speed_value = float(speed[:-4]) * {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}.get(speed[-4], 1)
            total_remaining = (total_size - completed_size) / speed_value
            return time.strftime("%H:%M:%S", time.gmtime(total_remaining))
        except (ValueError, ZeroDivisionError):
            return "N/A"
    return "N/A"

# Update print_ticker to include elapsed time
def print_ticker(completed_files, total_files, current_file_path, current_percent, completed_size, total_size, speed, remaining_time, total_remaining_time, elapsed_time):
    """Update the progress ticker."""
    sys.stdout.write(
        f"\r[mrsync] {completed_files}/{total_files} files | Current File: {current_file_path} {current_percent}% | "
        f"Transferred: {convert_size(completed_size)}/{convert_size(total_size)} | "
        f"Speed: {speed} | Remaining (file): {remaining_time} | Remaining (total): {total_remaining_time} | Elapsed: {elapsed_time}    " # Add elapsed time
    )
    sys.stdout.flush()



class RsyncProgressTracker:
    def __init__(self, source, destination, file_sizes, total_size):
        self.source = source
        self.destination = destination
        self.file_sizes = file_sizes
        self.total_size = total_size

        self.completed_size = 0
        self.completed_files = 0
        self.total_files = len(file_sizes) if file_sizes else 0
        self.current_file_path = "Initializing..."
        self.current_file_size = 0
        self.current_percent = 0
        self.speed = "Calculating..."
        self.remaining_time = "N/A"
        self.total_remaining_time = "N/A"
        self.start_time = time.time()
        self.last_update_time = 0

        self.process = None  # Initialize to None for subprocess

    def _parse_progress_line(self, line):
        """Parse the rsync --info=progress2 output line."""
        try:
            parts = line.split()

            # Example progress line: "347.47M 98% 7.52MB/s 0:00:00 (xfr#1, to-chk=2/32)"
            if len(parts) >= 6 and "%" in parts[1]:
                transferred_str, percent_str, speed_str, remaining_str = parts[:4]
                self.current_percent = int(percent_str.strip('%'))

                # Update transferred size
                self.completed_size = self._convert_to_bytes(transferred_str)

                # Update speed and remaining time
                self.speed = speed_str
                self.remaining_time = remaining_str

                # Update total remaining time
                self.total_remaining_time = self._calculate_total_remaining()

                # Set placeholder for aggregated progress
                self.current_file_path = "Transferring Files..."
        except Exception as e:
            verbose_print(1, f"[mrsync-debug] Error parsing progress line: {line}. Error: {e}")

    def _convert_to_bytes(self, size_str):
        """Convert human-readable size (e.g., 1.23M) to bytes."""
        size_multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
        try:
            if size_str[-1] in size_multiplier:
                return float(size_str[:-1]) * size_multiplier[size_str[-1]]
            return float(size_str)
        except ValueError:
            return 0

    def _calculate_total_remaining(self):
        """Calculate the total remaining time for the entire transfer."""
        try:
            if self.speed.endswith("B/s") and self.completed_size > 0:
                speed_value = self._convert_to_bytes(self.speed[:-4])  # Remove "B/s"
                remaining_size = self.total_size - self.completed_size
                total_remaining_seconds = remaining_size / speed_value
                return time.strftime("%H:%M:%S", time.gmtime(total_remaining_seconds))
        except (ValueError, ZeroDivisionError):
            return "N/A"
        return "N/A"

    def _print_update(self):
        """Print the progress update ticker."""
        now = time.time()
        elapsed_time = now - self.start_time
        elapsed_str = time.strftime("%H:%M:%S", time.gmtime(elapsed_time))

        # Throttle updates to once per second
        if now - self.last_update_time >= 1.0:
            print_ticker(
                completed_files=self.completed_files,
                total_files=self.total_files,
                current_file_path=self.current_file_path,
                current_percent=self.current_percent,
                completed_size=self.completed_size,
                total_size=self.total_size,
                speed=self.speed,
                remaining_time=self.remaining_time,
                total_remaining_time=self.total_remaining_time,
                elapsed_time=elapsed_str,
            )
            self.last_update_time = now

    def run(self):
        """Run rsync and track progress."""
        rsync_command = ['rsync', '-avz', '--info=progress2', '--human-readable', self.source, self.destination]
        verbose_print(2, f"[mrsync-debug] Rsync command: {rsync_command}")

        try:
            self.process = subprocess.Popen(
                rsync_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8'
            )

            while True:
                # Read output line by line
                line = self.process.stdout.readline().strip()

                # Break loop if rsync process ends
                if line == '' and self.process.poll() is not None:
                    break

                # Process valid output
                if line:
                    verbose_print(3, f"[mrsync-debug] Rsync output: {line}")
                    if "xfr" in line:  # Detect progress lines
                        self._parse_progress_line(line)
                    elif line.startswith(">f"):  # File completion signal
                        self.completed_files += 1

                # Ensure updates even during idle states
                self._print_update()

            # Check rsync exit code
            if self.process.returncode != 0:
                stderr_output = self.process.stderr.read().strip()
                verbose_print(1, f"[mrsync] Rsync failed with exit code {self.process.returncode}: {stderr_output}")
                raise RuntimeError(f"Rsync failed with exit code {self.process.returncode}")

        except FileNotFoundError:
            verbose_print(1, "[mrsync] Error: rsync command not found. Ensure rsync is installed and in PATH.")
        except Exception as e:
            verbose_print(1, f"[mrsync] Unexpected error during rsync execution: {e}")
        finally:
            # Final update before exiting
            self._print_update()
            sys.stdout.write("\n")
            verbose_print(1, "[mrsync] rsync_with_progress completed.")


def rsync_with_progress(source, destination, file_sizes, total_size):
    """Run rsync with progress tracking."""
    tracker = RsyncProgressTracker(source, destination, file_sizes, total_size)
    tracker.run()


def test_parallel_vs_sequential(source, destination):
    verbose_print(2, "[mrsync] Testing parallel vs. sequential performance...")

    def run_rsync():
        """Run rsync for testing purposes."""
        try:
            subprocess.run(
                ['rsync', '-avz', '--progress', source, destination],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30  # Timeout to prevent hangs
            )
        except subprocess.TimeoutExpired:
            verbose_print(1, "[mrsync] rsync subprocess timed out during parallel test.")
        except Exception as e:
            verbose_print(1, f"[mrsync] Error during rsync subprocess: {e}")

    # Sequential test
    sequential_start = time.time()
    run_rsync()
    sequential_end = time.time()
    sequential_speed = sequential_end - sequential_start

    # Parallel test
    parallel_start = time.time()
    thread1 = threading.Thread(target=run_rsync)
    thread2 = threading.Thread(target=run_rsync)
    thread1.start()
    thread2.start()

    thread1.join(timeout=35)  # Ensure threads terminate
    thread2.join(timeout=35)

    if thread1.is_alive() or thread2.is_alive():
        verbose_print(1, "[mrsync] One or more parallel rsync threads did not terminate.")
        return False  # Fallback to sequential

    parallel_end = time.time()
    parallel_speed = parallel_end - parallel_start

    verbose_print(2, f"Sequential speed: {sequential_speed:.2f}s, Parallel speed: {parallel_speed:.2f}s")

    return parallel_speed < sequential_speed

# Main function
def main():
    global VERBOSE_LEVEL

    parser = argparse.ArgumentParser(description="mrsync - Intelligent rsync manager")
    parser.add_argument("source", help="Source directory")
    parser.add_argument("destination", help="Destination directory")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity level (-v, -vv, -vvv)")
    args = parser.parse_args()

    VERBOSE_LEVEL = args.verbose

    # Validate paths
    if not os.path.exists(args.source):
        print(f"[ERROR] Source path does not exist: {args.source}")
        sys.exit(1)

    if not args.destination:
        print("[ERROR] Destination path is empty or invalid.")
        sys.exit(1)

    # Validate header and initialize database
    validate_header(os.path.abspath(__file__), verbose_print)
    initialize_database(verbose_print)

    # Calculate file sizes and total size
    verbose_print(1, "[mrsync] Calculating total files and size...")
    file_sizes = {}
    total_size = 0
    for root, _, files in os.walk(args.source):
        for file in files:
            file_path = os.path.join(root, file)
            try:  # Handle potential exceptions during file access
                size = os.path.getsize(file_path)
                file_sizes[file_path] = size
                total_size += size
            except OSError as e:
                verbose_print(1, f"[mrsync] Error accessing file {file_path}: {e}")


    total_files = len(file_sizes)
    verbose_print(1, f"[mrsync] Total files: {total_files}, Total size: {total_size / (1024 ** 3):.2f} GB")

    # Acquire lock and handle task execution (with timeout)
    try:
        with FileLock(LOCK_FILE, timeout=1):  # Acquire lock with timeout
            verbose_print(1, "[mrsync] Checking for active tasks on the same drive...")
            if active_tasks_on_same_drive(args.destination):
                verbose_print(1, "[mrsync] Another process is already running on the same drive.")
                conflicts = detect_conflicts(args.source)
                if conflicts:
                    verbose_print(1, "[mrsync] Conflicts detected. Adding conflicting files to deferred queue.")
                    handle_conflicts(conflicts, args.source, args.destination)
                else:
                    verbose_print(1, "[mrsync] No direct file conflicts detected. Testing parallel vs. sequential performance...")
                    faster_parallel = test_parallel_vs_sequential(args.source, args.destination)
                    if faster_parallel:
                        verbose_print(1, "[mrsync] Running in parallel with the existing process.")
                        threading.Thread(
                            target=rsync_with_progress,
                            args=(args.source, args.destination, file_sizes, total_size)
                        ).start()
                    else:
                        verbose_print(1, "[mrsync] Parallel execution is slower. Queuing task to run sequentially.")
                        add_task(args.source, args.destination, verbose_print)
            else:
                # No active tasks on the same drive
                verbose_print(1, "[mrsync] No conflicts or active tasks on the same drive. Starting rsync...")
                add_task(args.source, args.destination, verbose_print)
                rsync_with_progress(args.source, args.destination, file_sizes, total_size)
    except Timeout:
        verbose_print(1, "[mrsync] Another instance of mrsync is currently running. Exiting.")
        return  # Exit if lock cannot be acquired


    # Main processing loop for deferred tasks
    while True:  # Keep the loop running to process deferred tasks
        try:
            if not CONFLICT_DEFERRED.empty():
                source, destination = CONFLICT_DEFERRED.get()
                verbose_print(1, f"[mrsync] Processing deferred task: {source} -> {destination}")
                rsync_with_progress(source, destination, file_sizes, total_size)  # Use file_sizes and total_size from the initial calculation
            else:
                time.sleep(1)  # Wait for new tasks or active tasks to complete
        except KeyboardInterrupt:
            verbose_print(1, "[mrsync] Exiting gracefully.")
            break

if __name__ == "__main__":
    main()

