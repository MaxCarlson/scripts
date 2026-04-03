import unittest
import os
import socket

from aebn_dl import Downloader


def is_proxy_available(host: str, port: int) -> bool:
    """Check if proxy is available"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.url = "https://straight.aebn.com/straight/movies/309021/hot-and-mean-37"
        self.proxy = "socks5://localhost:56567"
        self.work_dir = os.path.join(os.getcwd(), "work_dir")
        self.output_dir = os.path.join(os.getcwd(), "output_dir")

    @unittest.skipUnless(is_proxy_available("localhost", 56567), "Proxy not available")
    def test_movie_dl(self):
        Downloader(
            url=self.url,
            proxy=self.proxy,
            work_dir=self.work_dir,
            output_dir=self.output_dir,
            download_covers=True,
            target_height=0,
            log_level="DEBUG",
            start_segment=0,
            end_segment=20,
        ).run()


if __name__ == "__main__":
    unittest.main()
