"""Debug test to see what's happening"""
import subprocess
import sys
import time
import os
import tempfile

url = "https://straight.aebn.com/straight/movies/218561/share-my-boyfriend-4#scene-989545"
test_dir = tempfile.mkdtemp(prefix="debug_")
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
    "-es", "5",
    "-l", "DEBUG"
]

print(f"Command: {' '.join(cmd)}")
print(f"Output dir: {output_dir}")
print(f"Work dir: {work_dir}")

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

# Let it run
time.sleep(5)

# Check files
print("\nFiles in output dir:")
for f in os.listdir(output_dir):
    print(f"  {f}")

print("\nFiles in work dir:")
for root, dirs, files in os.walk(work_dir):
    level = root.replace(work_dir, '').count(os.sep)
    indent = ' ' * 2 * level
    print(f'{indent}{os.path.basename(root)}/')
    subindent = ' ' * 2 * (level + 1)
    for file in files[:5]:  # Limit output
        print(f'{subindent}{file}')
    if len(files) > 5:
        print(f'{subindent}... and {len(files) - 5} more files')

# Terminate
proc.terminate()
stdout, _ = proc.communicate(timeout=10)

print("\nProcess output (first 500 chars):")
print(stdout[:500] if stdout else "No output")

print("\nDone")
