#!/usr/bin/env python3
"""
Test script for the enhanced video deduplication UI.
"""
import time
import sys
import os
from pathlib import Path

# Add the current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from progress import ProgressReporter


def test_enhanced_ui():
    """Test the enhanced UI with simulated pipeline stages."""
    print("Testing Enhanced Video Deduplication UI")
    print("=" * 50)

    # Create reporter with enhanced UI enabled
    reporter = ProgressReporter(
        enable_dash=True,
        banner="Enhanced UI Test - Video Deduplication Pipeline",
        stacked_ui=None  # Auto-detect layout
    )

    try:
        # Start the UI
        reporter.start()
        print("UI started. Testing various pipeline stages...")

        # Simulate file scanning stage
        reporter.start_stage("Scanning files", 100)
        reporter.set_total_files(100)

        for i in range(101):
            reporter.inc_scanned(1, bytes_added=1024*1024*2, is_video=(i % 3 == 0))
            reporter.set_current_file(f"video_{i:03d}.mp4")
            time.sleep(0.05)  # Simulate processing time

        reporter.clear_current_file()

        # Simulate hashing stage
        reporter.start_stage("Computing hashes", 50)
        reporter.set_hash_total(50)

        for i in range(51):
            cache_hit = (i % 4 == 0)  # 25% cache hit rate
            reporter.inc_hashed(1, cache_hit=cache_hit)
            reporter.set_current_file(f"hashing_video_{i:03d}.mp4")
            time.sleep(0.08)

        reporter.clear_current_file()

        # Simulate metadata analysis
        reporter.start_stage("Analyzing metadata", 30)
        for i in range(31):
            if i % 5 == 0:
                reporter.inc_group("meta", 1)
            time.sleep(0.06)

        # Simulate pHash computation
        reporter.start_stage("Computing perceptual hashes", 25)
        for i in range(26):
            if i % 7 == 0:
                reporter.inc_group("phash", 1)
            if i % 10 == 0:
                reporter.inc_group("subset", 1)
            reporter.set_current_file(f"phash_video_{i:03d}.mp4")
            time.sleep(0.1)

        reporter.clear_current_file()

        # Simulate final results
        reporter.start_stage("Finalizing results", 10)
        for i in range(11):
            time.sleep(0.05)

        # Set final results
        reporter.set_results(
            dup_groups=15,
            losers_count=35,
            bytes_total=1024*1024*1024*2  # 2 GB of duplicates
        )

        # Hold the display for a few seconds to see final results
        time.sleep(3)

    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test error: {e}")
    finally:
        reporter.stop()
        print("\nUI test completed!")


def test_ui_layouts():
    """Test both stacked and wide UI layouts."""
    print("\nTesting UI layouts...")

    for layout_name, stacked in [("Stacked", True), ("Wide", False)]:
        print(f"\nTesting {layout_name} layout...")

        reporter = ProgressReporter(
            enable_dash=True,
            banner=f"{layout_name} Layout Test",
            stacked_ui=stacked
        )

        try:
            reporter.start()

            # Quick test of the layout
            reporter.start_stage("Testing layout", 10)
            reporter.set_total_files(20)

            for i in range(11):
                reporter.inc_scanned(1, bytes_added=1024*1024, is_video=True)
                reporter.inc_hashed(1, cache_hit=(i % 3 == 0))
                if i % 3 == 0:
                    reporter.inc_group("hash", 1)
                time.sleep(0.1)

            time.sleep(1)  # Show final state

        finally:
            reporter.stop()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--layouts":
        test_ui_layouts()
    else:
        test_enhanced_ui()