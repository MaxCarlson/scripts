"""Debug SIGTERM handling"""
import subprocess
import sys
import time
import os
import tempfile

url = "https://straight.aebn.com/straight/movies/218561/share-my-boyfriend-4#scene-989545"
test_dir = tempfile.mkdtemp(prefix="debug_sigterm_")
output_dir = os.path.join(test_dir, "output")
work_dir = os.path.join(test_dir, "work")
os.makedirs(output_dir, exist_ok=True)
os.makedirs(work_dir, exist_ok=True)

cmd = [
    sys.executable, "-m", "aebn_dl.cli",
    url,
    "-o", output_dir,
    "-w", work_dir,
    "-r", "480",
    "-ss", "0",
    "-es", "50",
    "-l", "INFO"
]

print(f"Starting download...")
print(f"Output dir: {output_dir}")

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

# Wait a bit
time.sleep(6)

print("\nChecking for .part files before termination...")
part_files = [f for f in os.listdir(output_dir) if f.endswith('.part')]
print(f"Part files before term: {part_files}")

print("\nSending SIGTERM...")
proc.terminate()

stdout, _ = proc.communicate(timeout=10)

print("\nChecking for .part files after termination...")
part_files_after = [f for f in os.listdir(output_dir) if f.endswith('.part')]
print(f"Part files after term: {part_files_after}")

print("\nProcess output:")
print(stdout)

print("\nProcess return code:", proc.returncode)
