#!/usr/bin/env python3
"""
Simple test for UI updates
"""
import time
import sys
from pathlib import Path

# Add the current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from progress import ProgressReporter


def test_simple_updates():
    """Test basic UI updates with verbose logging."""
    print("Starting simple UI test...")

    reporter = ProgressReporter(
        enable_dash=True,
        banner="Simple UI Test",
        stacked_ui=True  # Force stacked for simpler debugging
    )

    try:
        print("Starting reporter...")
        reporter.start()
        time.sleep(1)

        print("Setting stage...")
        reporter.start_stage("Test Stage", 10)
        reporter.flush()
        time.sleep(2)

        print("Setting total files...")
        reporter.set_total_files(10)
        reporter.flush()
        time.sleep(2)

        print("Incrementing scanned files...")
        for i in range(5):
            print(f"Increment {i+1}")
            reporter.inc_scanned(1, bytes_added=1024*1024, is_video=True)
            time.sleep(1)

        print("Setting hash total...")
        reporter.set_hash_total(5)
        time.sleep(2)

        print("Incrementing hashed...")
        for i in range(3):
            print(f"Hash increment {i+1}")
            reporter.inc_hashed(1, cache_hit=(i == 0))
            time.sleep(1)

        print("Holding final state...")
        time.sleep(3)

    except KeyboardInterrupt:
        print("\\nTest interrupted")
    except Exception as e:
        print(f"Test error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Stopping reporter...")
        reporter.stop()
        print("Test completed!")


if __name__ == "__main__":
    test_simple_updates()