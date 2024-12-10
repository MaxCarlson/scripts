import yt_dlp
from tqdm import tqdm
import argparse
import os
import signal
import subprocess
import time
import concurrent.futures
from urllib.parse import urlparse
from collections import defaultdict

# Global flag for stopping the script
stop_flag = False

# Signal handler to exit on Ctrl+C
def handle_sigint(signum, frame):
    global stop_flag
    stop_flag = True
    print("\nInterrupt received. Exiting...")

# Register signal handler
signal.signal(signal.SIGINT, handle_sigint)

def get_filename(url, base_opts, debug=False):
    """Use yt-dlp's --get-filename to determine the resolved filename."""
    try:
        outtmpl = base_opts.get('outtmpl', '%(title)s.%(ext)s')
        ydl_opts = ['yt-dlp', '--get-filename', '-o', outtmpl, url]
        if debug:
            print(f"\nResolving filename with: {' '.join(ydl_opts)}")
        result = subprocess.run(ydl_opts, capture_output=True, text=True, check=True)
        resolved_filename = result.stdout.strip()
        return os.path.abspath(resolved_filename)
    except subprocess.CalledProcessError:
        return None

def file_exists(url, base_opts, debug=False):
    """Check if the resolved filename for a URL already exists."""
    resolved_filename = get_filename(url, base_opts, debug)
    if resolved_filename and os.path.exists(resolved_filename):
        return True
    return False

def download_video(url, base_opts, domain_progress, overall_progress, debug=False):
    """Download a single video."""
    try:
        ydl_opts = {**base_opts, 'quiet': True, 'progress_hooks': []}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            domain_progress.update(1)
            overall_progress.update(1)
    except KeyboardInterrupt:
        print(f"Download of {url} interrupted.")
        raise
    except Exception as e:
        if debug:
            print(f"Error downloading {url}: {e}")

def group_urls_by_domain(urls):
    """Group URLs by their base domain."""
    domains = defaultdict(list)
    for url in urls:
        domain = urlparse(url).netloc
        domains[domain].append(url)
    return domains

def download_from_domains(domain, urls, base_opts, domain_progress, overall_progress, debug=False):
    """Download videos sequentially from a specific domain."""
    for url in urls:
        if stop_flag:
            print(f"Stopping download from {domain}.")
            break
        if file_exists(url, base_opts, debug):
            if debug:
                print(f"Skipping {url}, file already exists.")
            domain_progress.update(1)
            overall_progress.update(1)
            continue
        download_video(url, base_opts, domain_progress, overall_progress, debug)

def download_videos_in_parallel(url_file, base_opts, max_threads, debug=False):
    """Download videos in parallel grouped by domain."""
    # Read URLs and group by domain
    with open(url_file, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]
    domain_groups = group_urls_by_domain(urls)

    # Progress bars
    overall_progress = tqdm(total=len(urls), desc="Overall Progress", unit="file", position=0)
    domain_progresses = {}
    for i, domain in enumerate(domain_groups):
        domain_progresses[domain] = tqdm(total=len(domain_groups[domain]), desc=f"{domain}", position=i+1)

    # Thread pool for parallel downloads
    with concurrent.futures.ThreadPoolExecutor(max_threads) as executor:
        futures = [
            executor.submit(
                download_from_domains,
                domain,
                urls,
                base_opts,
                domain_progresses[domain],
                overall_progress,
                debug,
            )
            for domain, urls in domain_groups.items()
        ]
        try:
            for future in concurrent.futures.as_completed(futures):
                if debug and future.exception():
                    print(f"Error in thread: {future.exception()}")
        except KeyboardInterrupt:
            print("Main process interrupted, shutting down.")
            stop_flag = True
            # Cancel all running tasks
            for future in futures:
                future.cancel()

    overall_progress.close()
    for progress in domain_progresses.values():
        progress.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download videos with yt-dlp.")
    parser.add_argument("--url_file", required=True, help="File containing URLs, one per line.")
    parser.add_argument("--threads", "-t", type=int, default=4, help="Maximum number of parallel threads.")
    parser.add_argument("--archive", help="Path to archive file to avoid re-downloading.")
    parser.add_argument("--debug", "-d", action="store_true", default=False, help="Enable debug messages.")

    args = parser.parse_args()

    # Setup options
    base_opts = {'outtmpl': '%(title)s.%(ext)s'}
    if args.archive:
        base_opts['download_archive'] = args.archive

    # Set the signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_sigint)

    try:
        download_videos_in_parallel(args.url_file, base_opts, args.threads, args.debug)
    except KeyboardInterrupt:
        print("\nProcess terminated by user.")

