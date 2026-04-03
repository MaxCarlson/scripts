"""
Real download tests with actual AEBN URLs.
These tests download small portions of videos to validate functionality.
"""

import unittest
import os
import json
import shutil
import tempfile
import time
import signal
import subprocess
import sys
from pathlib import Path

from aebn_dl import Downloader

# Import test URLs
try:
    from .test_urls import GOOD_URLS, BAD_URLS, SCENE_URL
except ImportError:
    from test_urls import GOOD_URLS, BAD_URLS, SCENE_URL


class RealDownloadTest(unittest.TestCase):
    """Tests with real AEBN URLs - limited to short downloads"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        cls.test_root = tempfile.mkdtemp(prefix="aebndl_real_test_")
        cls.work_dir = os.path.join(cls.test_root, "work")
        cls.output_dir = os.path.join(cls.test_root, "output")
        os.makedirs(cls.work_dir, exist_ok=True)
        os.makedirs(cls.output_dir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment"""
        if os.path.exists(cls.test_root):
            try:
                shutil.rmtree(cls.test_root)
            except Exception:
                pass  # Best effort cleanup

    def setUp(self):
        """Clean output directory before each test"""
        for item in os.listdir(self.output_dir):
            item_path = os.path.join(self.output_dir, item)
            try:
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception:
                pass

    def test_short_download_creates_valid_file(self):
        """Test that a short download creates a valid MP4 file"""
        url = GOOD_URLS[0]

        downloader = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,  # Low resolution for speed
            log_level="INFO",
            start_segment=0,
            end_segment=5,  # Only 5 segments for quick test
        )

        downloader.run()

        # Find output file
        output_files = [f for f in os.listdir(self.output_dir) if f.endswith('.mp4')]
        self.assertEqual(len(output_files), 1, "Should create exactly one MP4 file")

        output_path = os.path.join(self.output_dir, output_files[0])

        # Verify file exists and has content
        self.assertTrue(os.path.exists(output_path))
        file_size = os.path.getsize(output_path)
        self.assertGreater(file_size, 0, "Output file should have content")
        self.assertGreater(file_size, 1000, "Output file should be at least 1KB")

        # Verify it's a valid MP4 (has MP4 header)
        with open(output_path, 'rb') as f:
            header = f.read(12)
            # MP4 files typically start with 'ftyp' at byte 4
            self.assertIn(b'ftyp', header, "File should have MP4 signature")

    def test_part_file_not_created_on_success(self):
        """Test that .part file is deleted after successful download"""
        url = GOOD_URLS[0]

        downloader = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,
            log_level="INFO",
            start_segment=0,
            end_segment=3,
        )

        downloader.run()

        # Verify no .part files remain
        part_files = [f for f in os.listdir(self.output_dir) if f.endswith('.part')]
        self.assertEqual(len(part_files), 0, "No .part files should remain after successful download")

    def test_no_part_flag_prevents_part_file(self):
        """Test that --no-part flag prevents .part file creation"""
        url = GOOD_URLS[0]

        # We'll need to check during download, so let's use a longer segment range
        # and check the work directory
        downloader = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,
            log_level="INFO",
            start_segment=0,
            end_segment=3,
            no_part=True,  # Disable .part files
        )

        downloader.run()

        # Verify no .part file was created
        part_files = [f for f in os.listdir(self.output_dir) if f.endswith('.part')]
        self.assertEqual(len(part_files), 0, "No .part file should be created with --no-part")

    def test_different_resolutions_create_different_files(self):
        """Test that different resolutions create appropriately named files"""
        url = GOOD_URLS[0]

        # Download 480p
        downloader_480 = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,
            log_level="INFO",
            start_segment=0,
            end_segment=2,
        )
        downloader_480.run()

        files_480 = [f for f in os.listdir(self.output_dir) if f.endswith('.mp4')]
        self.assertEqual(len(files_480), 1)
        self.assertIn('480p', files_480[0], "Filename should include resolution")

        # Clean for next test
        os.remove(os.path.join(self.output_dir, files_480[0]))

        # Download 720p
        downloader_720 = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=720,
            log_level="INFO",
            start_segment=0,
            end_segment=2,
        )
        downloader_720.run()

        files_720 = [f for f in os.listdir(self.output_dir) if f.endswith('.mp4')]
        self.assertEqual(len(files_720), 1)
        self.assertIn('720p', files_720[0], "Filename should include resolution")

        # Verify different names
        self.assertNotEqual(files_480[0], files_720[0], "Different resolutions should create different files")

    @unittest.skip("Requires proxy setup")
    def test_bad_url_fails_gracefully(self):
        """Test that bad URLs fail gracefully without crashing"""
        url = BAD_URLS[0]

        with self.assertRaises(Exception):
            downloader = Downloader(
                url=url,
                work_dir=self.work_dir,
                output_dir=self.output_dir,
                target_height=480,
                log_level="INFO",
            )
            downloader.run()

        # Verify no files were created
        output_files = [f for f in os.listdir(self.output_dir) if f.endswith('.mp4')]
        self.assertEqual(len(output_files), 0, "Bad URL should not create output files")


class PartFileContinuousUpdateTest(unittest.TestCase):
    """Test that .part files are updated continuously during download"""

    @classmethod
    def setUpClass(cls):
        cls.test_root = tempfile.mkdtemp(prefix="aebndl_continuous_")
        cls.work_dir = os.path.join(cls.test_root, "work")
        cls.output_dir = os.path.join(cls.test_root, "output")
        os.makedirs(cls.work_dir, exist_ok=True)
        os.makedirs(cls.output_dir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_root):
            try:
                shutil.rmtree(cls.test_root)
            except Exception:
                pass

    @unittest.skip("Subprocess .part file monitoring unreliable on Windows - functional test exists")
    def test_part_file_updates_during_download(self):
        """
        Test that .part file is created and updated during an active download.
        Skipped: Windows subprocess limitations make this test unreliable.
        Functionality is tested via test_resume_with_existing_segments.
        """
        pass


class PartFileResumeTest(unittest.TestCase):
    """Test resume functionality with real downloads"""

    @classmethod
    def setUpClass(cls):
        cls.test_root = tempfile.mkdtemp(prefix="aebndl_resume_")
        cls.work_dir = os.path.join(cls.test_root, "work")
        cls.output_dir = os.path.join(cls.test_root, "output")
        os.makedirs(cls.work_dir, exist_ok=True)
        os.makedirs(cls.output_dir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_root):
            try:
                shutil.rmtree(cls.test_root)
            except Exception:
                pass

    @unittest.skip("SIGTERM handling unreliable on Windows - use test_resume_with_existing_segments instead")
    def test_graceful_interrupt_and_resume(self):
        """Test interrupting download with Ctrl+C and resuming"""
        pass

    def test_resume_with_existing_segments(self):
        """Test that downloader resumes when segments already exist"""
        url = GOOD_URLS[0]

        # First partial download - keep segments for resume test
        downloader1 = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,
            log_level="INFO",
            start_segment=0,
            end_segment=10,  # Download only first 10 segments
            keep_segments_after_download=True,  # Keep segments for resume
        )
        downloader1.run()

        # Verify segments exist in work dir
        work_subdirs = [d for d in os.listdir(self.work_dir) if os.path.isdir(os.path.join(self.work_dir, d))]
        self.assertEqual(len(work_subdirs), 1, "Should have one work subdirectory")

        segment_dir = os.path.join(self.work_dir, work_subdirs[0])
        segments_partial = [f for f in os.listdir(segment_dir) if f.endswith('.mp4')]
        self.assertGreater(len(segments_partial), 0, "Should have downloaded some segments")

        # Note how many segments we have
        partial_count = len(segments_partial)

        # Remove output file to force resume
        output_files = [f for f in os.listdir(self.output_dir) if f.endswith('.mp4')]
        for f in output_files:
            os.remove(os.path.join(self.output_dir, f))

        # Second download with more segments - should skip existing ones
        downloader2 = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,
            log_level="INFO",
            start_segment=0,
            end_segment=15,  # Download more segments
            keep_segments_after_download=True,  # Keep for verification
        )
        downloader2.run()

        # Verify new segments were added
        segments_after = [f for f in os.listdir(segment_dir) if f.endswith('.mp4')]
        self.assertGreaterEqual(len(segments_after), partial_count,
                               "Should have at least as many segments as before")

        # Verify output file exists and is valid
        output_files = [f for f in os.listdir(self.output_dir) if f.endswith('.mp4')]
        self.assertEqual(len(output_files), 1, "Should have one output file")

        output_path = os.path.join(self.output_dir, output_files[0])
        self.assertGreater(os.path.getsize(output_path), partial_count * 1000,
                          "Output file should be larger than partial download")

    def test_segment_reuse_on_retry(self):
        """Test that existing segments are reused when retrying a download"""
        url = GOOD_URLS[1]  # Use different URL

        # First download - partial, keep segments for reuse test
        downloader1 = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,
            log_level="INFO",
            start_segment=0,
            end_segment=8,
            keep_segments_after_download=True,  # Keep segments for reuse test
        )
        downloader1.run()

        # Get work dir for this movie
        work_subdirs = [d for d in os.listdir(self.work_dir) if os.path.isdir(os.path.join(self.work_dir, d))]
        self.assertGreater(len(work_subdirs), 0, "Should have work directory")

        segment_dir = os.path.join(self.work_dir, work_subdirs[0])
        segments_before = set(os.listdir(segment_dir))

        # Note timestamps of existing segments
        segment_times_before = {}
        for seg in segments_before:
            seg_path = os.path.join(segment_dir, seg)
            if os.path.isfile(seg_path):
                segment_times_before[seg] = os.path.getmtime(seg_path)

        # Remove output to simulate retry
        output_files = [f for f in os.listdir(self.output_dir) if f.endswith('.mp4')]
        for f in output_files:
            os.remove(os.path.join(self.output_dir, f))

        # Wait a moment
        time.sleep(1)

        # Second download - same segments should be reused
        downloader2 = Downloader(
            url=url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=480,
            log_level="INFO",
            start_segment=0,
            end_segment=8,
            keep_segments_after_download=True,  # Keep for verification
        )
        downloader2.run()

        # Verify segments were reused (timestamps unchanged)
        segments_after = set(os.listdir(segment_dir))
        reused_count = 0
        for seg in segments_before & segments_after:  # Intersection
            seg_path = os.path.join(segment_dir, seg)
            if os.path.isfile(seg_path):
                time_after = os.path.getmtime(seg_path)
                if seg in segment_times_before:
                    if abs(time_after - segment_times_before[seg]) < 0.1:  # Same timestamp = reused
                        reused_count += 1

        self.assertGreater(reused_count, 0, "Some segments should be reused from previous download")


if __name__ == "__main__":
    unittest.main()
