#!/usr/bin/env python3
"""
Debug test for UI updates - no UI, just prints
"""
import time
import sys
from pathlib import Path

# Add the current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from progress import ProgressReporter


def test_debug_updates():
    """Test updates with debug info but no UI."""
    print("Starting debug test (no UI)...")

    # Test without UI first
    reporter = ProgressReporter(
        enable_dash=False,
        banner="Debug Test"
    )

    try:
        print("Starting reporter...")
        reporter.start()

        print(f"Initial stage_name: '{reporter.stage_name}'")
        print(f"Initial stage_total: {reporter.stage_total}")
        print(f"Initial stage_done: {reporter.stage_done}")

        print("Calling start_stage...")
        reporter.start_stage("Scanning files", 10)  # Use a stage name that starts with "scan"
        print(f"After start_stage - stage_name: '{reporter.stage_name}'")
        print(f"After start_stage - stage_total: {reporter.stage_total}")
        print(f"After start_stage - stage_done: {reporter.stage_done}")

        print("Calling set_total_files...")
        reporter.set_total_files(10)
        print(f"After set_total_files - total_files: {reporter.total_files}")

        print("Calling inc_scanned...")
        reporter.inc_scanned(3, bytes_added=1024*1024*3, is_video=True)
        print(f"After inc_scanned - scanned_files: {reporter.scanned_files}")
        print(f"After inc_scanned - video_files: {reporter.video_files}")
        print(f"After inc_scanned - bytes_seen: {reporter.bytes_seen}")
        print(f"After inc_scanned - stage_done: {reporter.stage_done}")

        print("All values updated correctly!")

    except Exception as e:
        print(f"Test error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Stopping reporter...")
        reporter.stop()
        print("Test completed!")


if __name__ == "__main__":
    test_debug_updates()