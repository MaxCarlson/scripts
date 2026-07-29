from __future__ import annotations

import json
import math
import shutil
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.request import HTTPCookieProcessor, build_opener

from .concurrency import plan_manga18fx_concurrency
from .manga18fx import (
    _download_image,
    _load_cookie_jar,
    _read_text,
    parse_chapter_images,
    parse_series,
)

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class TuneRange:
    minimum: int
    maximum: int

    def values(self) -> range:
        return range(self.minimum, self.maximum + 1)


@dataclass(frozen=True, slots=True)
class TuneCandidate:
    workers: int
    image_workers: int

    @property
    def aggregate(self) -> int:
        return self.workers * self.image_workers


@dataclass(frozen=True, slots=True)
class ProbeImage:
    url: str
    referer: str


@dataclass(frozen=True, slots=True)
class ProbeSeries:
    url: str
    title: str
    images: tuple[ProbeImage, ...]


@dataclass(frozen=True, slots=True)
class TuneSample:
    round: int
    workers: int
    image_workers: int
    aggregate: int
    bytes_downloaded: int
    images_downloaded: int
    elapsed: float
    bytes_per_second: float
    errors: int


@dataclass(frozen=True, slots=True)
class TuneScore:
    workers: int
    image_workers: int
    aggregate: int
    average_bps: float
    median_bps: float
    standard_deviation_bps: float
    efficiency_bps_per_thread: float
    successful_samples: int
    errors: int


@dataclass(frozen=True, slots=True)
class AutoTuneResult:
    selected_workers: int
    selected_image_workers: int
    logical_cpus: int
    budget: int
    elapsed: float
    samples: tuple[TuneSample, ...]
    scores: tuple[TuneScore, ...]
    report_path: Path


def parse_tune_range(value: str) -> TuneRange:
    """Parse an inclusive MIN:MAX range used by CLI tuning options."""
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"expected MIN:MAX, got {value!r}")
    try:
        minimum, maximum = (int(part.strip()) for part in parts)
    except ValueError as exc:
        raise ValueError(f"expected integer MIN:MAX, got {value!r}") from exc
    if minimum < 1 or maximum < minimum:
        raise ValueError(f"invalid inclusive range {value!r}; require 1 <= MIN <= MAX")
    return TuneRange(minimum, maximum)


def generate_candidates(
    worker_range: TuneRange,
    image_range: TuneRange,
    *,
    logical_cpus: int,
    available_series: int,
) -> tuple[TuneCandidate, ...]:
    """Generate valid combinations below the logical-CPU concurrency budget."""
    if available_series < 1:
        return ()
    budget = plan_manga18fx_concurrency(1, 1, logical_cpus=logical_cpus).budget
    candidates = [
        TuneCandidate(workers, image_workers)
        for workers in worker_range.values()
        if workers <= available_series
        for image_workers in image_range.values()
        if workers * image_workers <= budget
    ]
    return tuple(sorted(candidates, key=lambda item: (item.aggregate, item.workers, item.image_workers)))


def _chapter_sample_order(chapter_count: int) -> tuple[int, ...]:
    if chapter_count <= 0:
        return ()
    return tuple(sorted({0, chapter_count // 2, chapter_count - 1}))


def prepare_probe_series(
    url: str,
    *,
    sample_images: int,
    cookies: Path | None,
    timeout: float,
) -> ProbeSeries:
    """Resolve a representative image pool from early, middle, and recent chapters."""
    opener = build_opener(HTTPCookieProcessor(_load_cookie_jar(cookies)))
    series_html = _read_text(opener, url, None, timeout)
    title, chapters = parse_series(series_html, url)
    if not chapters:
        raise RuntimeError(f"no chapters were found while preparing auto-tune probe: {url}")

    images: list[ProbeImage] = []
    for chapter_index in _chapter_sample_order(len(chapters)):
        chapter = chapters[chapter_index]
        chapter_html = _read_text(opener, chapter.url, url, timeout)
        for image_url in parse_chapter_images(chapter_html, chapter.url):
            probe = ProbeImage(image_url, chapter.url)
            if probe not in images:
                images.append(probe)
            if len(images) >= sample_images:
                break
        if len(images) >= sample_images:
            break

    if not images:
        raise RuntimeError(f"no images were found while preparing auto-tune probe: {url}")
    return ProbeSeries(url=url, title=title, images=tuple(images))


def _benchmark_probe(
    probe: ProbeSeries,
    destination: Path,
    *,
    image_workers: int,
    deadline: float,
    cookies: Path | None,
    timeout: float,
) -> tuple[int, int, int]:
    thread_state = threading.local()

    def thread_opener() -> object:
        opener = getattr(thread_state, "opener", None)
        if opener is None:
            opener = build_opener(HTTPCookieProcessor(_load_cookie_jar(cookies)))
            thread_state.opener = opener
        return opener

    def download(index_and_image: tuple[int, ProbeImage]) -> int:
        index, image = index_and_image
        if time.monotonic() >= deadline:
            return 0
        target = _download_image(
            thread_opener(),
            image.url,
            image.referer,
            destination / f"{index:04d}",
            timeout,
        )
        return target.stat().st_size

    bytes_downloaded = 0
    images_downloaded = 0
    errors = 0
    work = list(enumerate(probe.images, start=1))
    with ThreadPoolExecutor(
        max_workers=min(image_workers, len(work)),
        thread_name_prefix="mangadl-tune-image",
    ) as executor:
        futures = [executor.submit(download, item) for item in work]
        for future in as_completed(futures):
            try:
                size = future.result()
            except Exception:
                errors += 1
                continue
            if size > 0:
                bytes_downloaded += size
                images_downloaded += 1
    return bytes_downloaded, images_downloaded, errors


def benchmark_candidate(
    candidate: TuneCandidate,
    probes: tuple[ProbeSeries, ...],
    destination: Path,
    *,
    seconds: float,
    cookies: Path | None,
    timeout: float,
    round_number: int,
) -> TuneSample:
    started = time.monotonic()
    deadline = started + seconds
    bytes_downloaded = 0
    images_downloaded = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=candidate.workers, thread_name_prefix="mangadl-tune-series") as executor:
        futures = [
            executor.submit(
                _benchmark_probe,
                probe,
                destination / f"series-{index:02d}",
                image_workers=candidate.image_workers,
                deadline=deadline,
                cookies=cookies,
                timeout=min(timeout, max(5.0, seconds + 5.0)),
            )
            for index, probe in enumerate(probes[: candidate.workers], start=1)
        ]
        for future in as_completed(futures):
            try:
                sample_bytes, sample_images, sample_errors = future.result()
            except Exception:
                errors += 1
                continue
            bytes_downloaded += sample_bytes
            images_downloaded += sample_images
            errors += sample_errors

    elapsed = max(time.monotonic() - started, 0.001)
    return TuneSample(
        round=round_number,
        workers=candidate.workers,
        image_workers=candidate.image_workers,
        aggregate=candidate.aggregate,
        bytes_downloaded=bytes_downloaded,
        images_downloaded=images_downloaded,
        elapsed=elapsed,
        bytes_per_second=bytes_downloaded / elapsed,
        errors=errors,
    )


def score_samples(samples: Iterable[TuneSample]) -> tuple[TuneScore, ...]:
    grouped: dict[tuple[int, int], list[TuneSample]] = {}
    for sample in samples:
        grouped.setdefault((sample.workers, sample.image_workers), []).append(sample)

    scores: list[TuneScore] = []
    for (workers, image_workers), values in grouped.items():
        rates = [sample.bytes_per_second for sample in values if sample.bytes_downloaded > 0]
        if not rates:
            continue
        average = statistics.fmean(rates)
        scores.append(
            TuneScore(
                workers=workers,
                image_workers=image_workers,
                aggregate=workers * image_workers,
                average_bps=average,
                median_bps=statistics.median(rates),
                standard_deviation_bps=statistics.pstdev(rates) if len(rates) > 1 else 0.0,
                efficiency_bps_per_thread=average / (workers * image_workers),
                successful_samples=len(rates),
                errors=sum(sample.errors for sample in values),
            )
        )
    return tuple(sorted(scores, key=lambda item: item.average_bps, reverse=True))


def select_best_score(scores: tuple[TuneScore, ...], near_tie_ratio: float = 0.98) -> TuneScore:
    """Choose peak throughput, preferring fewer threads within a two-percent tie."""
    if not scores:
        raise RuntimeError("auto-tune produced no successful benchmark samples")
    peak = max(score.average_bps for score in scores)
    near_peak = [score for score in scores if score.average_bps >= peak * near_tie_ratio]
    return min(near_peak, key=lambda item: (item.aggregate, -item.average_bps, item.workers))


def _write_report(
    path: Path,
    *,
    started: float,
    logical_cpus: int,
    budget: int,
    worker_range: TuneRange,
    image_range: TuneRange,
    seconds: float,
    rounds: int,
    sample_images: int,
    probes: tuple[ProbeSeries, ...],
    samples: tuple[TuneSample, ...],
    scores: tuple[TuneScore, ...],
    selected: TuneScore | None,
    status: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "started": started,
        "logical_cpus": logical_cpus,
        "budget": budget,
        "worker_range": asdict(worker_range),
        "image_worker_range": asdict(image_range),
        "seconds_per_candidate": seconds,
        "rounds": rounds,
        "sample_images_per_series": sample_images,
        "probe_series": [
            {"url": probe.url, "title": probe.title, "images": len(probe.images)} for probe in probes
        ],
        "samples": [asdict(sample) for sample in samples],
        "scores": [asdict(score) for score in scores],
        "selected": asdict(selected) if selected is not None else None,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run_manga18fx_autotune(
    urls: list[str],
    destination: Path,
    report_path: Path,
    *,
    worker_range: TuneRange,
    image_range: TuneRange,
    seconds: float,
    rounds: int,
    sample_images: int,
    cookies: Path | None,
    timeout: float = 45.0,
    logical_cpus: int | None = None,
    progress: ProgressCallback | None = None,
) -> AutoTuneResult:
    if seconds <= 0:
        raise ValueError("auto-tune seconds must be greater than zero")
    if rounds < 1:
        raise ValueError("auto-tune rounds must be at least 1")
    if sample_images < 1:
        raise ValueError("auto-tune sample images must be at least 1")
    if not urls:
        raise ValueError("auto-tune requires at least one Manga18FX URL")

    started_wall = time.time()
    started = time.monotonic()
    logical = max(1, int(logical_cpus or __import__("os").cpu_count() or 1))
    budget = max(1, logical - 1)
    worker_max = min(worker_range.maximum, len(urls), budget)
    effective_worker_range = TuneRange(worker_range.minimum, worker_max)
    candidates = generate_candidates(
        effective_worker_range,
        image_range,
        logical_cpus=logical,
        available_series=len(urls),
    )
    if not candidates:
        raise ValueError("auto-tune bounds produced no combinations within the logical-CPU budget")

    emit = progress or (lambda message: None)
    probe_count = max(candidate.workers for candidate in candidates)
    probes: list[ProbeSeries] = []
    for index, url in enumerate(urls[:probe_count], start=1):
        emit(f"Preparing probe {index}/{probe_count}: {url}")
        probes.append(
            prepare_probe_series(
                url,
                sample_images=sample_images,
                cookies=cookies,
                timeout=timeout,
            )
        )
    prepared = tuple(probes)

    destination.mkdir(parents=True, exist_ok=True)
    samples: list[TuneSample] = []
    total = len(candidates) * rounds
    completed = 0
    try:
        with tempfile.TemporaryDirectory(prefix=".mangadl-autotune-", dir=destination) as temporary:
            temporary_root = Path(temporary)
            for round_index in range(rounds):
                ordered = candidates if round_index % 2 == 0 else tuple(reversed(candidates))
                for candidate_index, candidate in enumerate(ordered):
                    completed += 1
                    emit(
                        f"Auto-tune {completed}/{total}: round {round_index + 1}/{rounds}, "
                        f"-w {candidate.workers} -I {candidate.image_workers} "
                        f"({candidate.aggregate}/{budget} aggregate)"
                    )
                    rotation = (round_index + candidate_index) % len(prepared)
                    rotated = prepared[rotation:] + prepared[:rotation]
                    candidate_root = temporary_root / (
                        f"round-{round_index + 1:02d}-w{candidate.workers}-i{candidate.image_workers}"
                    )
                    sample = benchmark_candidate(
                        candidate,
                        rotated,
                        candidate_root,
                        seconds=seconds,
                        cookies=cookies,
                        timeout=timeout,
                        round_number=round_index + 1,
                    )
                    samples.append(sample)
                    emit(
                        f"  {sample.bytes_per_second / (1024 * 1024):.2f} MiB/s, "
                        f"{sample.images_downloaded} images, {sample.errors} errors, {sample.elapsed:.1f}s"
                    )
                    shutil.rmtree(candidate_root, ignore_errors=True)
                    partial_scores = score_samples(samples)
                    _write_report(
                        report_path,
                        started=started_wall,
                        logical_cpus=logical,
                        budget=budget,
                        worker_range=effective_worker_range,
                        image_range=image_range,
                        seconds=seconds,
                        rounds=rounds,
                        sample_images=sample_images,
                        probes=prepared,
                        samples=tuple(samples),
                        scores=partial_scores,
                        selected=None,
                        status="running",
                    )
    except BaseException:
        _write_report(
            report_path,
            started=started_wall,
            logical_cpus=logical,
            budget=budget,
            worker_range=effective_worker_range,
            image_range=image_range,
            seconds=seconds,
            rounds=rounds,
            sample_images=sample_images,
            probes=prepared,
            samples=tuple(samples),
            scores=score_samples(samples),
            selected=None,
            status="interrupted",
        )
        raise

    scores = score_samples(samples)
    selected = select_best_score(scores)
    _write_report(
        report_path,
        started=started_wall,
        logical_cpus=logical,
        budget=budget,
        worker_range=effective_worker_range,
        image_range=image_range,
        seconds=seconds,
        rounds=rounds,
        sample_images=sample_images,
        probes=prepared,
        samples=tuple(samples),
        scores=scores,
        selected=selected,
        status="complete",
    )
    emit(
        f"Selected -w {selected.workers} -I {selected.image_workers}: "
        f"{selected.average_bps / (1024 * 1024):.2f} MiB/s average."
    )
    return AutoTuneResult(
        selected_workers=selected.workers,
        selected_image_workers=selected.image_workers,
        logical_cpus=logical,
        budget=budget,
        elapsed=time.monotonic() - started,
        samples=tuple(samples),
        scores=scores,
        report_path=report_path,
    )
