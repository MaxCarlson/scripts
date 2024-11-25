import yt_dlp
from tqdm import tqdm
import argparse
import os
import signal
import time

# Global flag for stopping the script
stop_flag = False

# Signal handler to exit on Ctrl+C
def handle_sigint(signum, frame):
    global stop_flag
    stop_flag = True
    print("\nInterrupt received. Exiting...")
    raise KeyboardInterrupt

# Register signal handler
signal.signal(signal.SIGINT, handle_sigint)

def download_video(url, base_opts, master_progress):
    """Download a single video with progress bars."""
    last_update = time.time()  # Throttle updates
    file_progress = None

    def progress_hook(d):
        nonlocal file_progress, last_update
        if stop_flag:
            raise KeyboardInterrupt("Download interrupted by user.")

        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes', 0)
            speed = d.get('speed', 0)

            if not file_progress:
                file_progress = tqdm(
                    total=total or 1,
                    desc="Current Video",
                    unit='B',
                    unit_scale=True,
                    dynamic_ncols=True,
                    leave=False,
                    position=1,
                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}, speed={postfix}]"
                )

            # Throttle updates to prevent excessive output
            if time.time() - last_update > 0.5:  # Update every 0.5 seconds
                last_update = time.time()
                file_progress.n = downloaded
                file_progress.refresh()

                # Add size and speed as a postfix
                size_display = f"{downloaded / 1_000_000:.2f}MB/{(total / 1_000_000):.2f}MB" if total else "Unknown"
                speed_mbit = round(speed * 8 / 1_000_000, 2) if speed else 0
                file_progress.set_postfix(size=size_display, speed=f"{speed_mbit} Mb/s")

    ydl_opts = {**base_opts, 'progress_hooks': [progress_hook]}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"Failed to download {url}: {e}")
    finally:
        if file_progress:
            file_progress.close()

def download_videos_sequentially(url_file, base_opts):
    """Download videos sequentially with a master progress bar."""
    with open(url_file, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    print("Starting downloads...")
    with tqdm(total=len(urls), desc="Overall Progress", unit='file', position=0) as master_progress:
        for url in urls:
            if stop_flag:
                break  # Exit on interruption
            try:
                download_video(url, base_opts, master_progress)
                master_progress.update(1)
            except KeyboardInterrupt:
                print("\nDownload interrupted. Exiting...")
                break
            except Exception as e:
                print(f"Skipping URL due to error: {url}. Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download videos with yt-dlp.")
    parser.add_argument("url_file", help="File containing URLs, one per line.")
    parser.add_argument("--archive", help="Path to archive file to avoid re-downloading.")
    parser.add_argument("yt_dlp_args", nargs=argparse.REMAINDER, help="Additional arguments for yt-dlp.")

    args = parser.parse_args()

    base_opts = {'quiet': True, 'noprogress': True}
    if args.archive:
        base_opts['download_archive'] = args.archive

    for arg in args.yt_dlp_args:
        if '=' in arg:
            key, value = arg.split('=', 1)
            base_opts[key.lstrip('-')] = value
        else:
            base_opts[arg.lstrip('-')] = True

    outtmpl = base_opts.get('outtmpl', "downloads/%(title)s.%(ext)s")
    os.makedirs(os.path.dirname(outtmpl), exist_ok=True)

    try:
        download_videos_sequentially(args.url_file, base_opts)
    except KeyboardInterrupt:
        print("\nProcess terminated by user.")
