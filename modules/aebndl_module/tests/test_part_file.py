import unittest
import os
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from aebn_dl import Downloader


class PartFileTest(unittest.TestCase):
    def setUp(self):
        self.url = "https://straight.aebn.com/straight/movies/309021/hot-and-mean-37"
        self.url2 = "https://straight.aebn.com/straight/movies/218561/share-my-boyfriend-4"
        # Use temp dirs for isolation
        self.test_root = tempfile.mkdtemp(prefix="aebndl_test_")
        self.work_dir = os.path.join(self.test_root, "work")
        self.output_dir = os.path.join(self.test_root, "output")
        os.makedirs(self.work_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        # Clean up test directories
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root)

    def test_part_file_creation(self):
        """Test that .part file is created with correct structure"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Simulate part file path
        part_file_path = os.path.join(self.output_dir, "test_output.mp4.part")
        downloader.part_file_path = part_file_path
        downloader.movie_work_dir = self.work_dir

        # Create mock manifest and streams
        from aebn_dl.models import AudioStream, VideoStream
        from aebn_dl.manifest_parser import Manifest

        mock_manifest = MagicMock(spec=Manifest)
        mock_manifest.audio_stream = AudioStream()
        mock_manifest.audio_stream.stream_id = "test_audio"
        mock_manifest.audio_stream.downloaded_segments = []
        mock_manifest.audio_stream.downloaded_bytes = 1024
        mock_manifest.audio_stream.total_size = 10240

        mock_manifest.video_stream = VideoStream()
        mock_manifest.video_stream.stream_id = "test_video"
        mock_manifest.video_stream.downloaded_segments = []
        mock_manifest.video_stream.downloaded_bytes = 2048
        mock_manifest.video_stream.total_size = 20480

        downloader.manifest = mock_manifest

        # Save part file
        downloader._save_part_file(force=True)

        # Verify part file exists
        self.assertTrue(os.path.exists(part_file_path))

        # Verify part file content
        with open(part_file_path, 'r') as f:
            part_data = json.load(f)

        self.assertEqual(part_data['url'], self.url)
        self.assertIn('streams', part_data)
        self.assertIn('a', part_data['streams'])
        self.assertIn('v', part_data['streams'])
        self.assertEqual(part_data['streams']['a']['stream_id'], 'test_audio')
        self.assertEqual(part_data['streams']['v']['stream_id'], 'test_video')

    def test_part_file_load(self):
        """Test that .part file can be loaded correctly"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Create a test .part file
        part_file_path = os.path.join(self.output_dir, "test_output.mp4.part")
        part_data = {
            'url': self.url,
            'movie_id': 'test_movie',
            'target_height': 0,
            'scene_n': None,
            'target_stream': None,
            'streams': {
                'a': {
                    'stream_id': 'test_audio',
                    'downloaded_segments': [],
                    'downloaded_bytes': 1024,
                    'total_size': 10240,
                },
                'v': {
                    'stream_id': 'test_video',
                    'downloaded_segments': [],
                    'downloaded_bytes': 2048,
                    'total_size': 20480,
                }
            },
            'timestamp': '2025-01-01T00:00:00'
        }

        with open(part_file_path, 'w') as f:
            json.dump(part_data, f)

        # Load the part file
        loaded_data = downloader._load_part_file(part_file_path)

        self.assertIsNotNone(loaded_data)
        self.assertEqual(loaded_data['url'], self.url)
        self.assertEqual(loaded_data['movie_id'], 'test_movie')
        self.assertIn('streams', loaded_data)

    def test_part_file_disabled_with_no_part(self):
        """Test that .part file is not created when --no-part is enabled"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
            no_part=True,
        )

        part_file_path = os.path.join(self.output_dir, "test_output.mp4.part")
        downloader.part_file_path = part_file_path
        downloader.movie_work_dir = self.work_dir

        # Create mock manifest
        from aebn_dl.models import AudioStream, VideoStream
        from aebn_dl.manifest_parser import Manifest

        mock_manifest = MagicMock(spec=Manifest)
        mock_manifest.audio_stream = AudioStream()
        mock_manifest.video_stream = VideoStream()
        downloader.manifest = mock_manifest

        # Try to save part file
        downloader._save_part_file(force=True)

        # Verify part file was not created
        self.assertFalse(os.path.exists(part_file_path))

    def test_part_file_cleanup_on_success(self):
        """Test that .part file is removed after successful download"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Create a test .part file
        part_file_path = os.path.join(self.output_dir, "test_output.mp4.part")
        with open(part_file_path, 'w') as f:
            f.write('{}')

        downloader.part_file_path = part_file_path

        # Clean up part file
        downloader._cleanup_part_file()

        # Verify part file was removed
        self.assertFalse(os.path.exists(part_file_path))

    def test_part_file_in_output_dir(self):
        """Test that .part file is always created in output directory, not work directory"""
        output_name = "Test Movie.mp4"
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        part_path = downloader._get_part_file_path(output_name)

        # Verify .part file is in output dir, not work dir
        self.assertEqual(os.path.dirname(part_path), self.output_dir)
        self.assertEqual(os.path.basename(part_path), "Test Movie.mp4.part")
        self.assertNotIn(self.work_dir, part_path)

    def test_part_file_url_mismatch(self):
        """Test that .part file with mismatched URL is ignored"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Create a .part file for a different URL
        part_file_path = os.path.join(self.output_dir, "test.mp4.part")
        part_data = {
            'url': self.url2,  # Different URL
            'movie_id': 'test_movie',
            'streams': {}
        }

        with open(part_file_path, 'w') as f:
            json.dump(part_data, f)

        # Try to load it
        loaded = downloader._load_part_file(part_file_path)

        # Should be None due to URL mismatch
        self.assertIsNone(loaded)

    def test_part_file_url_match(self):
        """Test that .part file with matching URL is loaded"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Create a .part file with matching URL
        part_file_path = os.path.join(self.output_dir, "test.mp4.part")
        part_data = {
            'url': self.url,  # Same URL
            'movie_id': 'test_movie',
            'target_height': 0,
            'scene_n': None,
            'target_stream': None,
            'streams': {
                'a': {'stream_id': 'audio1', 'downloaded_segments': [], 'downloaded_bytes': 0, 'total_size': 0},
                'v': {'stream_id': 'video1', 'downloaded_segments': [], 'downloaded_bytes': 0, 'total_size': 0}
            }
        }

        with open(part_file_path, 'w') as f:
            json.dump(part_data, f)

        # Load it
        loaded = downloader._load_part_file(part_file_path)

        # Should be loaded successfully
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded['url'], self.url)

    def test_part_file_invalid_json(self):
        """Test that invalid JSON .part file is handled gracefully"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Create invalid JSON .part file
        part_file_path = os.path.join(self.output_dir, "test.mp4.part")
        with open(part_file_path, 'w') as f:
            f.write("{ invalid json }")

        # Try to load it
        loaded = downloader._load_part_file(part_file_path)

        # Should return None
        self.assertIsNone(loaded)

    def test_part_file_missing_fields(self):
        """Test that .part file with missing required fields is rejected"""
        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Create .part file missing 'streams' field
        part_file_path = os.path.join(self.output_dir, "test.mp4.part")
        part_data = {
            'url': self.url,
            'movie_id': 'test_movie',
            # 'streams' is missing
        }

        with open(part_file_path, 'w') as f:
            json.dump(part_data, f)

        # Try to load it
        loaded = downloader._load_part_file(part_file_path)

        # Should return None due to missing field
        self.assertIsNone(loaded)

    def test_restore_from_part_file_with_existing_segments(self):
        """Test that downloading resumes correctly when segments exist on disk"""
        from aebn_dl.models import AudioStream, VideoStream
        from aebn_dl.manifest_parser import Manifest

        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        # Create mock work directory
        movie_work_dir = os.path.join(self.work_dir, "test_movie")
        os.makedirs(movie_work_dir, exist_ok=True)

        # Create some fake segment files
        seg1 = os.path.join(movie_work_dir, "a_test_audio_0.mp4")
        seg2 = os.path.join(movie_work_dir, "a_test_audio_1.mp4")
        seg3 = os.path.join(movie_work_dir, "v_test_video_0.mp4")

        with open(seg1, 'wb') as f:
            f.write(b'x' * 1000)
        with open(seg2, 'wb') as f:
            f.write(b'x' * 1000)
        with open(seg3, 'wb') as f:
            f.write(b'x' * 2000)

        # Create manifest
        mock_manifest = MagicMock(spec=Manifest)
        mock_manifest.audio_stream = AudioStream()
        mock_manifest.audio_stream.stream_id = "test_audio"
        mock_manifest.video_stream = VideoStream()
        mock_manifest.video_stream.stream_id = "test_video"

        downloader.manifest = mock_manifest
        downloader.movie_work_dir = movie_work_dir

        # Create .part file referencing these segments
        part_data = {
            'url': self.url,
            'movie_id': 'test_movie',
            'streams': {
                'a': {
                    'stream_id': 'test_audio',
                    'downloaded_segments': [seg1, seg2],
                    'downloaded_bytes': 2000,
                    'total_size': 10000
                },
                'v': {
                    'stream_id': 'test_video',
                    'downloaded_segments': [seg3],
                    'downloaded_bytes': 2000,
                    'total_size': 20000
                }
            }
        }

        # Restore from part file
        downloader._restore_from_part_file(part_data)

        # Verify segments were restored
        self.assertEqual(len(mock_manifest.audio_stream.downloaded_segments), 2)
        self.assertIn(seg1, mock_manifest.audio_stream.downloaded_segments)
        self.assertIn(seg2, mock_manifest.audio_stream.downloaded_segments)
        self.assertEqual(mock_manifest.audio_stream.downloaded_bytes, 2000)
        self.assertEqual(mock_manifest.audio_stream.total_size, 10000)

        self.assertEqual(len(mock_manifest.video_stream.downloaded_segments), 1)
        self.assertIn(seg3, mock_manifest.video_stream.downloaded_segments)
        self.assertEqual(mock_manifest.video_stream.downloaded_bytes, 2000)
        self.assertEqual(mock_manifest.video_stream.total_size, 20000)

    def test_restore_filters_missing_segments(self):
        """Test that restore ignores segments that no longer exist on disk"""
        from aebn_dl.models import AudioStream
        from aebn_dl.manifest_parser import Manifest

        downloader = Downloader(
            url=self.url,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            target_height=0,
            log_level="INFO",
        )

        movie_work_dir = os.path.join(self.work_dir, "test_movie")
        os.makedirs(movie_work_dir, exist_ok=True)

        # Create only one segment (seg1), seg2 doesn't exist
        seg1 = os.path.join(movie_work_dir, "a_test_audio_0.mp4")
        seg2 = os.path.join(movie_work_dir, "a_test_audio_1.mp4")  # Won't create this

        with open(seg1, 'wb') as f:
            f.write(b'x' * 1000)

        mock_manifest = MagicMock(spec=Manifest)
        mock_manifest.audio_stream = AudioStream()
        mock_manifest.audio_stream.stream_id = "test_audio"
        mock_manifest.video_stream = None

        downloader.manifest = mock_manifest
        downloader.movie_work_dir = movie_work_dir

        # Part file references both, but only seg1 exists
        part_data = {
            'url': self.url,
            'movie_id': 'test_movie',
            'streams': {
                'a': {
                    'stream_id': 'test_audio',
                    'downloaded_segments': [seg1, seg2],  # seg2 doesn't exist
                    'downloaded_bytes': 2000,
                    'total_size': 10000
                }
            }
        }

        downloader._restore_from_part_file(part_data)

        # Only seg1 should be restored
        self.assertEqual(len(mock_manifest.audio_stream.downloaded_segments), 1)
        self.assertIn(seg1, mock_manifest.audio_stream.downloaded_segments)
        self.assertNotIn(seg2, mock_manifest.audio_stream.downloaded_segments)


if __name__ == "__main__":
    unittest.main()
