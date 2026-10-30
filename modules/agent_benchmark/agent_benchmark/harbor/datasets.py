"""Catalog and task selection for supported external benchmark datasets."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Sequence

# Curated catalog of Aider Polyglot tasks across 6 languages
# Source: Aider Polyglot benchmark (225 total exercism tasks)
AIDER_POLYGLOT_TASKS: dict[str, list[str]] = {
    "python": [
        "python/allergies", "python/anagram", "python/armstrong-numbers", "python/bank-account",
        "python/binary-search", "python/bob", "python/book-store", "python/bowling",
        "python/circular-buffer", "python/clock", "python/collatz-conjecture", "python/crypto-square",
        "python/diamond", "python/dnd-character", "python/dominoes", "python/eliuds-eggs",
        "python/etl", "python/flatten-array", "python/forth", "python/grade-school",
        "python/grep", "python/hamming", "python/isbn-verifier", "python/isogram",
        "python/kindergarten-garden", "python/knapsack", "python/largest-series-product",
        "python/leap", "python/linked-list", "python/list-ops", "python/luhn",
        "python/matching-brackets", "python/meetup", "python/minesweeper", "python/nth-prime",
        "python/ocr-numbers", "python/palindrome-products", "python/pangram", "python/pascals-triangle",
        "python/perfect-numbers", "python/pig-latin", "python/poker", "python/prime-factors",
        "python/protein-translation", "python/queen-attack", "python/rail-fence-cipher",
        "python/rational-numbers", "python/react", "python/resistor-color", "python/resistor-color-duo",
        "python/reverse-string", "python/rna-transcription", "python/robot-name", "python/robot-simulator",
        "python/rotational-cipher", "python/run-length-encoding", "python/saddle-points",
        "python/say", "python/scale-generator", "python/scrabble-score", "python/secret-handshake",
        "python/series", "python/sieve", "python/simple-cipher", "python/simple-linked-list",
        "python/space-age", "python/sublist", "python/sum-of-multiples", "python/tournament",
        "python/triangle", "python/twelve-days", "python/two-fer", "python/variable-length-quantity",
        "python/word-count", "python/wordy", "python/yacht",
    ],
    "cpp": [
        "cpp/allergies", "cpp/anagram", "cpp/armstrong-numbers", "cpp/bank-account",
        "cpp/binary-search", "cpp/bob", "cpp/circular-buffer", "cpp/clock",
        "cpp/collatz-conjecture", "cpp/crypto-square", "cpp/diamond", "cpp/dnd-character",
        "cpp/etl", "cpp/grade-school", "cpp/hamming", "cpp/isbn-verifier",
        "cpp/isogram", "cpp/leap", "cpp/matching-brackets", "cpp/meetup",
        "cpp/nth-prime", "cpp/pangram", "cpp/pascals-triangle", "cpp/perfect-numbers",
        "cpp/queen-attack", "cpp/raindrops", "cpp/reverse-string", "cpp/rna-transcription",
        "cpp/robot-name", "cpp/robot-simulator", "cpp/rotational-cipher", "cpp/sieve",
        "cpp/space-age", "cpp/sum-of-multiples", "cpp/triangle", "cpp/two-fer",
    ],
    "go": [
        "go/allergies", "go/anagram", "go/armstrong-numbers", "go/bank-account",
        "go/binary-search", "go/bob", "go/circular-buffer", "go/clock",
        "go/collatz-conjecture", "go/crypto-square", "go/diamond", "go/dnd-character",
        "go/etl", "go/grade-school", "go/hamming", "go/isbn-verifier",
        "go/isogram", "go/leap", "go/matching-brackets", "go/meetup",
        "go/nth-prime", "go/pangram", "go/pascals-triangle", "go/perfect-numbers",
        "go/queen-attack", "go/raindrops", "go/reverse-string", "go/rna-transcription",
        "go/robot-name", "go/robot-simulator", "go/rotational-cipher", "go/sieve",
        "go/space-age", "go/sum-of-multiples", "go/triangle", "go/two-fer",
    ],
    "java": [
        "java/allergies", "java/anagram", "java/armstrong-numbers", "java/bank-account",
        "java/binary-search", "java/bob", "java/circular-buffer", "java/clock",
        "java/collatz-conjecture", "java/crypto-square", "java/diamond", "java/dnd-character",
        "java/etl", "java/grade-school", "java/hamming", "java/isbn-verifier",
        "java/isogram", "java/leap", "java/matching-brackets", "java/meetup",
        "java/nth-prime", "java/pangram", "java/pascals-triangle", "java/perfect-numbers",
        "java/queen-attack", "java/raindrops", "java/reverse-string", "java/rna-transcription",
        "java/robot-name", "java/robot-simulator", "java/rotational-cipher", "java/sieve",
        "java/space-age", "java/sum-of-multiples", "java/triangle", "java/two-fer",
    ],
    "javascript": [
        "javascript/allergies", "javascript/anagram", "javascript/armstrong-numbers", "javascript/bank-account",
        "javascript/binary-search", "javascript/bob", "javascript/circular-buffer", "javascript/clock",
        "javascript/collatz-conjecture", "javascript/crypto-square", "javascript/diamond", "javascript/dnd-character",
        "javascript/etl", "javascript/grade-school", "javascript/hamming", "javascript/isbn-verifier",
        "javascript/isogram", "javascript/leap", "javascript/matching-brackets", "javascript/meetup",
        "javascript/nth-prime", "javascript/pangram", "javascript/pascals-triangle", "javascript/perfect-numbers",
        "javascript/queen-attack", "javascript/raindrops", "javascript/reverse-string", "javascript/rna-transcription",
        "javascript/robot-name", "javascript/robot-simulator", "javascript/rotational-cipher", "javascript/sieve",
        "javascript/space-age", "javascript/sum-of-multiples", "javascript/triangle", "javascript/two-fer",
    ],
    "rust": [
        "rust/allergies", "rust/anagram", "rust/armstrong-numbers", "rust/bank-account",
        "rust/binary-search", "rust/bob", "rust/circular-buffer", "rust/clock",
        "rust/collatz-conjecture", "rust/crypto-square", "rust/diamond", "rust/dnd-character",
        "rust/etl", "rust/grade-school", "rust/hamming", "rust/isbn-verifier",
        "rust/isogram", "rust/leap", "rust/matching-brackets", "rust/meetup",
        "rust/nth-prime", "rust/pangram", "rust/pascals-triangle", "rust/perfect-numbers",
        "rust/queen-attack", "rust/raindrops", "rust/reverse-string", "rust/rna-transcription",
        "rust/robot-name", "rust/robot-simulator", "rust/rotational-cipher", "rust/sieve",
        "rust/space-age", "rust/sum-of-multiples", "rust/triangle", "rust/two-fer",
    ],
}

# Curated CPU-only Terminal-Bench candidate tasks (pinned for local evaluation)
TERMINAL_BENCH_CPU_TASKS: list[str] = [
    "terminal-bench/find-large-files",
    "terminal-bench/git-rebase-conflict",
    "terminal-bench/nginx-access-log-analysis",
    "terminal-bench/sqlite-schema-migration",
    "terminal-bench/tar-archive-extraction",
]


@dataclass(frozen=True)
class DatasetDescriptor:
    id: str
    name: str
    version: str
    description: str
    supported_languages: tuple[str, ...]
    all_tasks: tuple[str, ...]
    default_scoring_protocol: str


# Dataset catalog registry
DATASETS: dict[str, DatasetDescriptor] = {
    "aider/aider-polyglot": DatasetDescriptor(
        id="aider/aider-polyglot",
        name="Aider Polyglot Coding Benchmark",
        version="1.0.0",
        description="225 coding exercises across Python, C++, Go, Java, JavaScript, and Rust",
        supported_languages=("python", "cpp", "go", "java", "javascript", "rust"),
        all_tasks=tuple(task for lang in AIDER_POLYGLOT_TASKS.values() for task in lang),
        default_scoring_protocol="single-attempt-v1",
    ),
    "terminal-bench/terminal-bench@4.0.0": DatasetDescriptor(
        id="terminal-bench/terminal-bench@4.0.0",
        name="Terminal-Bench 4.0.0 (Pinned CPU subset)",
        version="4.0.0",
        description="Deterministic command-line and systems tasks with executable verification",
        supported_languages=("shell", "python"),
        all_tasks=tuple(TERMINAL_BENCH_CPU_TASKS),
        default_scoring_protocol="single-attempt-v1",
    ),
    "terminal-bench-cpu-only": DatasetDescriptor(
        id="terminal-bench-cpu-only",
        name="Terminal-Bench CPU-Only",
        version="1.0.0",
        description="Lightweight local CPU-only tasks from Terminal-Bench",
        supported_languages=("shell", "python"),
        all_tasks=tuple(TERMINAL_BENCH_CPU_TASKS),
        default_scoring_protocol="single-attempt-v1",
    ),
}


def resolve_dataset(dataset_name: str) -> DatasetDescriptor:
    """Resolve a dataset identifier or raise a KeyError."""
    # Normalize input
    clean = dataset_name.strip()
    if clean in DATASETS:
        return DATASETS[clean]

    # Partial match
    for k, v in DATASETS.items():
        if clean in (k, v.name, k.split("/")[-1], k.split("@")[0]):
            return v

    valid_keys = sorted(DATASETS.keys())
    raise KeyError(f"Unknown dataset {dataset_name!r}. Available datasets: {valid_keys}")


def select_tasks(
    descriptor: DatasetDescriptor,
    *,
    task_ids: Sequence[str] | None = None,
    language: str | None = None,
    count: int | None = None,
    seed: int | None = None,
) -> list[str]:
    """
    Select and order tasks deterministically.

    - Explicit task_ids are filtered and verified.
    - Language filters by language prefix.
    - Deterministic random sampling if seed and count are specified.
    - Returns sorted list if no seed is specified.
    """
    candidates = list(descriptor.all_tasks)

    # 1. Filter by language if specified
    if language:
        lang_norm = language.lower().strip()
        candidates = [t for t in candidates if t.startswith(f"{lang_norm}/") or lang_norm in t]
        if not candidates:
            raise ValueError(
                f"No tasks found for language {language!r} in dataset {descriptor.id}. "
                f"Supported: {list(descriptor.supported_languages)}"
            )

    # 2. Filter by explicit task IDs if provided
    if task_ids:
        selected: list[str] = []
        for tid in task_ids:
            clean_tid = tid.strip()
            # Match exact or suffix
            matches = [t for t in candidates if t == clean_tid or t.endswith(f"/{clean_tid}")]
            if not matches:
                raise ValueError(f"Task ID {tid!r} not found in dataset {descriptor.id}")
            selected.extend(matches)
        candidates = list(dict.fromkeys(selected))  # preserve order, drop duplicates

    # 3. Deterministic sampling or count limit
    if count is not None and count > 0:
        if count > len(candidates):
            count = len(candidates)
        if seed is not None:
            rng = random.Random(seed)
            # Use sample on deterministic sorted list
            sorted_candidates = sorted(candidates)
            candidates = sorted(rng.sample(sorted_candidates, count))
        else:
            candidates = sorted(candidates)[:count]
    elif seed is not None:
        rng = random.Random(seed)
        shuffled = list(sorted(candidates))
        rng.shuffle(shuffled)
        candidates = shuffled
    elif not task_ids:
        candidates = sorted(candidates)

    return candidates
