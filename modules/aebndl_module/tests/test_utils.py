"""
Tests for aebn_dl/utils.py functions
"""

import unittest
import os
import tempfile
import shutil
from pathlib import Path

from aebn_dl import utils
from aebn_dl.exceptions import FFmpegError


class TestStringUtils(unittest.TestCase):
    """Test string manipulation utilities"""

    def test_remove_chars_basic(self):
        """Test basic character removal"""
        text = "test#file?name!"
        result = utils.remove_chars(text)
        self.assertEqual(result, "testfilename")

    def test_remove_chars_all_special(self):
        """Test removal of all special characters"""
        text = "#?!:<>\"/\\|*"
        result = utils.remove_chars(text)
        self.assertEqual(result, "")

    def test_remove_chars_mixed(self):
        """Test mixed text with special characters"""
        text = "Movie: The Best <2024>"
        result = utils.remove_chars(text)
        self.assertEqual(result, "Movie The Best 2024")

    def test_remove_chars_no_special(self):
        """Test text without special characters"""
        text = "NormalFileName"
        result = utils.remove_chars(text)
        self.assertEqual(result, "NormalFileName")

    def test_remove_chars_empty(self):
        """Test empty string"""
        result = utils.remove_chars("")
        self.assertEqual(result, "")


class TestDurationConversion(unittest.TestCase):
    """Test duration string to seconds conversion"""

    def test_duration_hh_mm_ss(self):
        """Test HH:MM:SS format"""
        self.assertEqual(utils.duration_to_seconds("01:30:45"), 5445)
        self.assertEqual(utils.duration_to_seconds("00:05:30"), 330)
        self.assertEqual(utils.duration_to_seconds("02:00:00"), 7200)

    def test_duration_mm_ss(self):
        """Test MM:SS format"""
        self.assertEqual(utils.duration_to_seconds("05:30"), 330)
        self.assertEqual(utils.duration_to_seconds("00:45"), 45)

    def test_duration_ss_only(self):
        """Test SS only format"""
        self.assertEqual(utils.duration_to_seconds("45"), 45)
        self.assertEqual(utils.duration_to_seconds("0"), 0)

    def test_duration_zero(self):
        """Test zero duration"""
        self.assertEqual(utils.duration_to_seconds("00:00:00"), 0)
        self.assertEqual(utils.duration_to_seconds("00:00"), 0)


class TestNaturalSort(unittest.TestCase):
    """Test natural sorting key function"""

    def test_natural_sort_numbers(self):
        """Test natural sorting with numbers"""
        files = ["file_10.mp4", "file_2.mp4", "file_1.mp4", "file_20.mp4"]
        sorted_files = sorted(files, key=utils.natural_sort_key)
        expected = ["file_1.mp4", "file_2.mp4", "file_10.mp4", "file_20.mp4"]
        self.assertEqual(sorted_files, expected)

    def test_natural_sort_mixed(self):
        """Test natural sorting with mixed content"""
        files = ["a_10_b.mp4", "a_2_b.mp4", "a_1_c.mp4", "b_1_a.mp4"]
        sorted_files = sorted(files, key=utils.natural_sort_key)
        expected = ["a_1_c.mp4", "a_2_b.mp4", "a_10_b.mp4", "b_1_a.mp4"]
        self.assertEqual(sorted_files, expected)

    def test_natural_sort_no_numbers(self):
        """Test natural sorting without numbers"""
        files = ["charlie.mp4", "alpha.mp4", "bravo.mp4"]
        sorted_files = sorted(files, key=utils.natural_sort_key)
        expected = ["alpha.mp4", "bravo.mp4", "charlie.mp4"]
        self.assertEqual(sorted_files, expected)


class TestConcatSegments(unittest.TestCase):
    """Test segment concatenation"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_concat_")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_concat_segments_basic(self):
        """Test basic segment concatenation"""
        # Create test segments
        seg1 = os.path.join(self.test_dir, "seg_0.mp4")
        seg2 = os.path.join(self.test_dir, "seg_1.mp4")
        seg3 = os.path.join(self.test_dir, "seg_2.mp4")

        with open(seg1, 'wb') as f:
            f.write(b'segment1data')
        with open(seg2, 'wb') as f:
            f.write(b'segment2data')
        with open(seg3, 'wb') as f:
            f.write(b'segment3data')

        output = os.path.join(self.test_dir, "output.mp4")

        # Concat segments
        utils.concat_segments(
            files=[seg1, seg2, seg3],
            output_path=output,
            tqdm_desc="test",
            aggressive_cleaning=False,
            silent=True
        )

        # Verify output
        self.assertTrue(os.path.exists(output))
        with open(output, 'rb') as f:
            content = f.read()

        self.assertEqual(content, b'segment1datasegment2datasegment3data')

    def test_concat_segments_aggressive_cleaning(self):
        """Test that aggressive cleaning removes segments"""
        seg1 = os.path.join(self.test_dir, "seg_0.mp4")
        seg2 = os.path.join(self.test_dir, "seg_1.mp4")

        with open(seg1, 'wb') as f:
            f.write(b'data1')
        with open(seg2, 'wb') as f:
            f.write(b'data2')

        output = os.path.join(self.test_dir, "output.mp4")

        utils.concat_segments(
            files=[seg1, seg2],
            output_path=output,
            tqdm_desc="test",
            aggressive_cleaning=True,
            silent=True
        )

        # Verify segments were deleted
        self.assertFalse(os.path.exists(seg1))
        self.assertFalse(os.path.exists(seg2))

        # Verify output exists
        self.assertTrue(os.path.exists(output))

    def test_concat_segments_natural_order(self):
        """Test that segments are concatenated in natural order"""
        seg1 = os.path.join(self.test_dir, "seg_1.mp4")
        seg2 = os.path.join(self.test_dir, "seg_2.mp4")
        seg10 = os.path.join(self.test_dir, "seg_10.mp4")

        with open(seg1, 'wb') as f:
            f.write(b'1')
        with open(seg2, 'wb') as f:
            f.write(b'2')
        with open(seg10, 'wb') as f:
            f.write(b'10')

        output = os.path.join(self.test_dir, "output.mp4")

        # Note: First file is treated as init segment, rest are sorted
        utils.concat_segments(
            files=[seg1, seg10, seg2],  # Out of order input
            output_path=output,
            tqdm_desc="test",
            aggressive_cleaning=False,
            silent=True
        )

        with open(output, 'rb') as f:
            content = f.read()

        # Should be: seg1 (first), then seg2, seg10 (sorted naturally)
        self.assertEqual(content, b'1210')


class TestFFmpegUtils(unittest.TestCase):
    """Test FFmpeg-related utilities"""

    def test_ffmpeg_check_available(self):
        """Test that ffmpeg is available (or raises appropriate error)"""
        try:
            utils.ffmpeg_check()
            # If we get here, ffmpeg is available
        except FileNotFoundError as e:
            # This is expected if ffmpeg is not in PATH
            self.assertIn("ffmpeg", str(e).lower())

    def test_ffmpeg_mux_streams_invalid_paths(self):
        """Test that muxing with invalid paths raises error"""
        with self.assertRaises(FFmpegError):
            utils.ffmpeg_mux_streams(
                "nonexistent1.mp4",
                "nonexistent2.mp4",
                "output.mp4",
                silent=True
            )


class TestLoggerCreation(unittest.TestCase):
    """Test logger creation"""

    def test_new_logger_creates_logger(self):
        """Test that new_logger creates a valid logger"""
        logger = utils.new_logger("test_logger_123", "INFO")
        self.assertIsNotNone(logger)
        self.assertEqual(logger.name, "test_logger_123")

        # Clean up log file
        try:
            os.remove("test_logger_123.log")
        except Exception:
            pass

    def test_new_logger_log_levels(self):
        """Test different log levels"""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            logger = utils.new_logger(f"test_logger_{level}", level)
            self.assertIsNotNone(logger)

            # Clean up
            try:
                os.remove(f"test_logger_{level}.log")
            except Exception:
                pass

    def tearDown(self):
        """Clean up any remaining log files"""
        import glob
        for log_file in glob.glob("test_logger*.log"):
            try:
                os.remove(log_file)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
