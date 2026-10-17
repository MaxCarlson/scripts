"""Generated-only repeatable phase benchmark; never accepts a production target."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from statistics import median
import tempfile
import threading
import time

from PIL import Image

from cli_test_support import main


def _fixtures(base: Path) -> dict[str, Path]:
    roots = {}
    for label, galleries, pages, size in (
        ("many_small", 8, 8, (64, 64)),
        ("few_large", 1, 3, (512, 768)),
        ("nested_mixed", 3, 3, (96, 128)),
        ("cached", 3, 6, (96, 128)),
    ):
        root = base / label
        roots[label] = root
        for gallery in range(galleries):
            folder = root / f"gallery-{gallery}" / "chapter"
            folder.mkdir(parents=True)
            for page in range(pages):
                image = Image.new("RGB", size, (page * 21 % 256, gallery * 43 % 256, 120))
                extension = ("jpg", "webp", "png")[page % 3] if label == "nested_mixed" else "png"
                image.save(folder / f"{page:03d}.{extension}")
    return roots


def _run(arguments: list[str], runner=main) -> tuple[dict, int | None]:
    output = io.StringIO()
    stop = threading.Event()
    rss = []
    try:
        import psutil

        process = psutil.Process()
    except ImportError:
        process = None

    def sample_rss():
        while not stop.is_set():
            try:
                rss.append(process.memory_info().rss)
            except (OSError, psutil.Error):
                return
            stop.wait(0.01)

    sampler = threading.Thread(target=sample_rss, daemon=True) if process else None
    if sampler:
        sampler.start()
    try:
        started = time.perf_counter()
        cpu_started = time.process_time()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = runner(arguments + ["-J"])
        elapsed = time.perf_counter() - started
        cpu_elapsed = time.process_time() - cpu_started
        if code:
            raise RuntimeError(f"Benchmark command returned {code}: {output.getvalue()}")
    finally:
        stop.set()
        if sampler:
            sampler.join()
    report = json.loads(output.getvalue())
    report["pipeline"]["command_wall_seconds"] = elapsed
    report["pipeline"]["command_cpu_seconds"] = cpu_elapsed
    return report, max(rss) if rss else None


def run_benchmark(repetitions: int, workers: list[int], *, mangadl: bool = False) -> dict:
    """Measure identical generated inputs, with fresh trial DBs and explicit warm runs."""
    temporary_root = Path(__file__).resolve().parents[1] / ".pytest_tmp_root"
    temporary_root.mkdir(exist_ok=True)
    rows = []
    runner = main
    if mangadl:
        from mangadl.cli import main as runner
    with tempfile.TemporaryDirectory(prefix="pipeline-benchmark-", dir=temporary_root) as temporary:
        base = Path(temporary)
        fixtures = _fixtures(base)
        expected = {}
        for label, root in fixtures.items():
            for threads in workers:
                cold, warm = [], []
                for repetition in range(repetitions):
                    inventory = base / f"{label}-{threads}-{repetition}.sqlite3"
                    args = (["compress", "-d"] if mangadl else ["-i"]) + [
                        str(root),
                        "-I",
                        str(inventory),
                        "-t",
                        str(threads),
                    ]
                    inventory_report, inventory_rss = _run(args + ["-l"], runner)
                    cold_report, cold_rss = _run(args + ["-f", "webp", "-e", "0"], runner)
                    warm_report, warm_rss = _run(args + ["-f", "webp", "-e", "0", "-U", "trust"], runner)
                    signature = (
                        cold_report["total_images"],
                        cold_report["original_bytes"],
                        cold_report["compressed_bytes"],
                        cold_report["failed_count"],
                        cold_report["average_ssim"],
                    )
                    if expected.setdefault(label, signature) != signature:
                        raise AssertionError("Worker settings changed verified results")
                    if (warm_report["compressed_bytes"], warm_report["failed_count"]) != (signature[2], signature[3]):
                        raise AssertionError("Warm cache changed retained results")
                    if signature[3]:
                        raise AssertionError("Generated benchmark encountered a failed trial")
                    cold.append(
                        {
                            "inventory": inventory_report["pipeline"],
                            "encode": cold_report["pipeline"],
                            "sampled_peak_rss_bytes": max(
                                [x for x in (inventory_rss, cold_rss) if x is not None], default=None
                            ),
                        }
                    )
                    warm.append({"pipeline": warm_report["pipeline"], "sampled_peak_rss_bytes": warm_rss})
                rows.append(
                    {
                        "fixture": label,
                        "requested_workers": threads,
                        "repetitions": repetitions,
                        "inventory_wall_median_s": median(r["inventory"]["command_wall_seconds"] for r in cold),
                        "encode_wall_median_s": median(r["encode"]["command_wall_seconds"] for r in cold),
                        "warm_trust_wall_median_s": median(r["pipeline"]["command_wall_seconds"] for r in warm),
                        "runs": {"cold_trial": cold, "warm_trust": warm},
                    }
                )
    return {
        "schema": 1,
        "adapter": "mangadl" if mangadl else "compresser",
        "generated_only": True,
        "result_equality": True,
        "rows": rows,
        "limits": "Trial DBs are fresh, not OS page-cache cold. RSS is sampled every10ms when psutil is available; "
        "it includes the process baseline and is not a guaranteed peak. Warm runs trust the saved population. "
        "Tiny generated fixtures are not a production throughput prediction.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--repetitions", type=int, default=3)
    parser.add_argument("-t", "--workers", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("-M", "--mangadl", action="store_true", help="Benchmark the installed MangaDL adapter instead.")
    args = parser.parse_args()
    if args.repetitions < 1 or any(worker < 1 for worker in args.workers):
        parser.error("Repetitions and workers must be positive")
    started = time.monotonic()
    report = run_benchmark(args.repetitions, args.workers, mangadl=args.mangadl)
    report["benchmark_wall_seconds"] = time.monotonic() - started
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
    for row in report["rows"]:
        print(json.dumps({key: value for key, value in row.items() if key != "runs"}))
