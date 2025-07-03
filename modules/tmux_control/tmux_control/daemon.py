import time
import sys
from pathlib import Path

# This ensures the daemon can find its own configuration if run directly
sys.path.append(str(Path(__file__).parent.parent))

def main():
    """The main loop for the daemon process."""
    print("Daemon started. Monitoring for tasks...")
    try:
        while True:
            # TODO: Implement logic to check for command files from the CLI
            # print(f"Daemon alive at {time.ctime()}...")
            time.sleep(2)
    except KeyboardInterrupt:
        print("Daemon shutting down.")

if __name__ == "__main__":
    main()
