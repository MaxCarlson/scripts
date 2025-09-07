# yt-ae-dl: Modular & Concurrent Downloader

`yt-ae-dl` is a powerful, modular, and concurrent command-line downloader built in Python. It acts as a unified wrapper for other download tools like `yt-dlp` and `aebndl`, automatically selecting the correct tool based on the URL. It features a rich, real-time terminal dashboard for monitoring progress.

This tool was created by refactoring a collection of specialized download scripts into a single, maintainable, and extensible library.

## Key Features

- **Concurrent Downloads**: Process multiple downloads in parallel to maximize bandwidth.
- **Unified Interface**: A single command to handle different video sources.
- **Automatic Downloader Selection**: Intelligently uses `aebndl` for `aebn.com` URLs and `yt-dlp` for everything else.
- **Rich Terminal UI**: A real-time dashboard powered by `termdash` shows per-job progress, speed, ETA, and overall status.
- **Fallback Logger**: A simple, clean logging output is used if `termdash` is unavailable or disabled with the `--no-ui` flag.
- **Archive Support**: Automatically logs completed downloads to an archive file to prevent re-downloading.
- **Modular Design**: Core logic is separated into a reusable library, making it easy to maintain and extend.

## Installation

### Prerequisites

1.  **Python**: Python 3.8 or newer is required.
2.  **External Tools**: You must have the underlying downloader executables installed and available in your system's `PATH`:
    -   [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
    -   `aebndl` (if you need to download from AEBN)

### Steps

1.  **Clone the repository** (or ensure you are in the project's root directory).

2.  **Navigate to the project directory**:
    ```sh
    cd /path/to/downloads_dlpn/ytaedl
    ```

3.  **Install the package in editable mode** using `pip`. This allows you to run the tool directly while still being able to edit the source code.
    ```sh
    pip install -e .
    ```

4.  **(Optional) For development**, install the testing dependencies:
    ```sh
    pip install -e ".[dev]"
    ```

## Usage

The tool is run from the command line using the `yt-ae-dl` command.

```sh
yt-ae-dl [OPTIONS]
```

### Main Arguments

| Argument                | Alias | Description                                                                 |
| ----------------------- | ----- | --------------------------------------------------------------------------- |
| `--url-file <path>`     | `-u`  | **(Required)** Path to a URL file. Can be specified multiple times.         |
| `--output-dir <path>`   | `-o`  | **(Required)** Directory where all downloads will be saved.                 |
| `--jobs <number>`       | `-j`  | Number of parallel download jobs to run. (Default: 4)                     |
| `--archive-file <path>` | `-a`  | Path to the archive file for completed URLs. (Default: `yt-ae-dl-archive.txt`) |
| `--no-ui`               |       | Disable the rich `termdash` UI and use simple print statements instead.     |
| `--work-dir <path>`     | `-w`  | Temporary working directory for downloader caches. (Default: `./tmp_dl`)      |
| `--timeout <seconds>`   | `-t`  | Timeout in seconds for each download process. (Default: 3600)             |

## Examples

#### 1. Basic Download

Download URLs from a single file into the `~/videos` directory with the default 4 parallel jobs.

```sh
yt-ae-dl -u my_favorite_urls.txt -o ~/videos
```

#### 2. Higher Concurrency from Multiple Files

Download from two different URL lists into a `data/` folder, using 8 parallel workers.

```sh
yt-ae-dl -u list_A.txt -u list_B.txt -o ./data -j 8
```

#### 3. Using the Simple Logger UI

Run a download without the `termdash` dashboard, falling back to simple line-by-line output.

```sh
yt-ae-dl -u urls.txt -o ./output --no-ui
```

#### 4. Specifying a Custom Archive File

Use a specific file to track completed downloads, which is useful for managing separate collections.

```sh
yt-ae-dl -u project_urls.txt -o ./project_vids -a ./project.archive
```

## Development

To run the test suite, ensure you have installed the `dev` dependencies and then run `pytest` from the `ytaedl` directory.

```sh
# Navigate to the project folder
cd /path/to/downloads_dlpn/ytaedl

# Run tests
pytest
```
