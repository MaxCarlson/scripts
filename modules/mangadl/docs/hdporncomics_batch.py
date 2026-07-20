from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sequentially download HDPornComics manhwa URLs from a text file."
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        type=Path,
        help="Text file containing one manhwa URL per line.",
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Output directory. Defaults to the current directory.",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=8,
        help="Number of internal hdporncomics download threads. Default: 8.",
    )
    parser.add_argument(
        "-e",
        "--executable",
        default="hdporncomics",
        help=(
            "hdporncomics executable name or path. "
            "Default: hdporncomics."
        ),
    )
    parser.add_argument(
        "-s",
        "--stop-on-error",
        action="store_true",
        help="Stop processing after the first failed URL.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print commands without running them.",
    )

    return parser.parse_args()


def load_urls(input_path: Path) -> list[str]:
    try:
        text = input_path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RuntimeError(
            f"Unable to read input file {input_path}: {error}"
        ) from error

    urls: list[str] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        parsed = urlsplit(line)

        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(
                f"{input_path}:{line_number}: invalid URL: {line}"
            )

        normalized_host = parsed.hostname.lower().rstrip(".")
        if normalized_host not in {
            "hdporncomics.com",
            "www.hdporncomics.com",
        }:
            raise ValueError(
                f"{input_path}:{line_number}: unsupported host "
                f"{parsed.hostname!r}"
            )

        if not parsed.path.lower().startswith("/manhwa/"):
            raise ValueError(
                f"{input_path}:{line_number}: expected a /manhwa/ URL: "
                f"{line}"
            )

        urls.append(line)

    return urls


def resolve_executable(value: str) -> str:
    candidate = Path(value).expanduser()

    if candidate.parent != Path(".") or candidate.is_absolute():
        if not candidate.is_file():
            raise RuntimeError(
                f"hdporncomics executable was not found: {candidate}"
            )

        return str(candidate.resolve())

    resolved = shutil.which(value)

    if resolved is None and sys.platform == "win32":
        resolved = shutil.which(f"{value}.exe")

    if resolved is None:
        raise RuntimeError(
            "The hdporncomics executable was not found.\n"
            "Install it with:\n"
            "    py -3.12 -m pip install --upgrade hdporncomics\n"
            "Then ensure the Python Scripts directory is on PATH."
        )

    return resolved


def format_command(command: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)

    try:
        import shlex

        return shlex.join(command)
    except AttributeError:
        return " ".join(command)


def run_download(command: list[str]) -> int:
    process: subprocess.Popen[bytes] | None = None

    try:
        process = subprocess.Popen(command)
        return process.wait()
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Terminating the current downloader...",
            file=sys.stderr,
        )

        if process is not None and process.poll() is None:
            process.terminate()

            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        raise


def main() -> int:
    arguments = parse_arguments()

    if arguments.threads <= 0:
        print("--threads must be greater than zero.", file=sys.stderr)
        return 2

    try:
        input_path = arguments.input.expanduser().resolve(strict=True)
        output_directory = arguments.directory.expanduser().resolve()
        output_directory.mkdir(parents=True, exist_ok=True)

        urls = load_urls(input_path)
        executable = resolve_executable(arguments.executable)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    if not urls:
        print(f"No manhwa URLs found in {input_path}.")
        return 0

    total = len(urls)
    succeeded = 0
    failed = 0

    print(f"Loaded {total} URL{'s' if total != 1 else ''}.")
    print(f"Output directory: {output_directory}")
    print(f"Executable: {executable}")
    print()

    for index, url in enumerate(urls, start=1):
        command = [
            executable,
            "-d",
            str(output_directory),
            "-t",
            str(arguments.threads),
            "-f",
            "--manhwa",
            url,
        ]

        print("=" * 80)
        print(f"[{index}/{total}] Processing:")
        print(url)
        print()
        print(f"[{index}/{total}] Command:")
        print(format_command(command))
        print()

        if arguments.dry_run:
            print(f"[{index}/{total}] Dry run; command not executed.")
            succeeded += 1
            continue

        started_at = time.monotonic()

        try:
            exit_code = run_download(command)
        except KeyboardInterrupt:
            print(
                f"\nStopped while processing URL {index} of {total}.",
                file=sys.stderr,
            )
            return 130
        except OSError as error:
            exit_code = -1
            print(
                f"[{index}/{total}] Could not start downloader: {error}",
                file=sys.stderr,
            )

        elapsed_seconds = time.monotonic() - started_at

        if exit_code == 0:
            succeeded += 1
            print()
            print(
                f"[{index}/{total}] Completed successfully "
                f"in {elapsed_seconds:.1f} seconds."
            )
        else:
            failed += 1
            print()
            print(
                f"[{index}/{total}] Failed with exit code {exit_code} "
                f"after {elapsed_seconds:.1f} seconds.",
                file=sys.stderr,
            )

            if arguments.stop_on_error:
                print("Stopping because --stop-on-error was specified.")
                break

            print("Continuing with the next URL.")

    processed = succeeded + failed

    print()
    print("=" * 80)
    print("Batch summary")
    print(f"Total URLs: {total}")
    print(f"Processed:  {processed}")
    print(f"Succeeded:  {succeeded}")
    print(f"Failed:     {failed}")
    print(f"Remaining:  {total - processed}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
