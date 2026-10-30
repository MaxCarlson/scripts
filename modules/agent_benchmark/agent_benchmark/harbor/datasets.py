"""Catalog and task selection for supported external benchmark datasets."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Sequence

# Curated catalog of Aider Polyglot tasks across 6 languages
# Source: Harbor official aider-polyglot benchmark (225 total exercism tasks)
AIDER_POLYGLOT_TASKS: dict[str, list[str]] = {
    "python": [
        "polyglot_python_affine-cipher", "polyglot_python_beer-song", "polyglot_python_book-store",
        "polyglot_python_bottle-song", "polyglot_python_bowling", "polyglot_python_connect",
        "polyglot_python_dominoes", "polyglot_python_dot-dsl", "polyglot_python_food-chain",
        "polyglot_python_forth", "polyglot_python_go-counting", "polyglot_python_grade-school",
        "polyglot_python_grep", "polyglot_python_hangman", "polyglot_python_list-ops",
        "polyglot_python_paasio", "polyglot_python_phone-number", "polyglot_python_pig-latin",
        "polyglot_python_poker", "polyglot_python_pov", "polyglot_python_proverb",
        "polyglot_python_react", "polyglot_python_rest-api", "polyglot_python_robot-name",
        "polyglot_python_scale-generator", "polyglot_python_sgf-parsing", "polyglot_python_simple-linked-list",
        "polyglot_python_transpose", "polyglot_python_tree-building", "polyglot_python_two-bucket",
        "polyglot_python_variable-length-quantity", "polyglot_python_wordy", "polyglot_python_zebra-puzzle",
        "polyglot_python_zipper",
    ],
    "cpp": [
        "polyglot_cpp_all-your-base", "polyglot_cpp_allergies", "polyglot_cpp_bank-account",
        "polyglot_cpp_binary-search-tree", "polyglot_cpp_circular-buffer", "polyglot_cpp_clock",
        "polyglot_cpp_complex-numbers", "polyglot_cpp_crypto-square", "polyglot_cpp_diamond",
        "polyglot_cpp_dnd-character", "polyglot_cpp_gigasecond", "polyglot_cpp_grade-school",
        "polyglot_cpp_kindergarten-garden", "polyglot_cpp_knapsack", "polyglot_cpp_linked-list",
        "polyglot_cpp_meetup", "polyglot_cpp_parallel-letter-frequency", "polyglot_cpp_perfect-numbers",
        "polyglot_cpp_phone-number", "polyglot_cpp_queen-attack", "polyglot_cpp_robot-name",
        "polyglot_cpp_space-age", "polyglot_cpp_spiral-matrix", "polyglot_cpp_sublist",
        "polyglot_cpp_yacht", "polyglot_cpp_zebra-puzzle",
    ],
    "go": [
        "polyglot_go_alphametics", "polyglot_go_beer-song", "polyglot_go_book-store",
        "polyglot_go_bottle-song", "polyglot_go_bowling", "polyglot_go_connect",
        "polyglot_go_counter", "polyglot_go_crypto-square", "polyglot_go_dnd-character",
        "polyglot_go_dominoes", "polyglot_go_error-handling", "polyglot_go_food-chain",
        "polyglot_go_forth", "polyglot_go_hexadecimal", "polyglot_go_kindergarten-garden",
        "polyglot_go_ledger", "polyglot_go_markdown", "polyglot_go_matrix",
        "polyglot_go_octal", "polyglot_go_paasio", "polyglot_go_palindrome-products",
        "polyglot_go_pig-latin", "polyglot_go_poker", "polyglot_go_pov",
        "polyglot_go_protein-translation", "polyglot_go_react", "polyglot_go_robot-simulator",
        "polyglot_go_say", "polyglot_go_scale-generator", "polyglot_go_simple-linked-list",
        "polyglot_go_sublist", "polyglot_go_transpose", "polyglot_go_tree-building",
        "polyglot_go_trinary", "polyglot_go_two-bucket", "polyglot_go_variable-length-quantity",
        "polyglot_go_word-search", "polyglot_go_wordy", "polyglot_go_zebra-puzzle",
    ],
    "java": [
        "polyglot_java_affine-cipher", "polyglot_java_all-your-base", "polyglot_java_alphametics",
        "polyglot_java_bank-account", "polyglot_java_book-store", "polyglot_java_bottle-song",
        "polyglot_java_bowling", "polyglot_java_change", "polyglot_java_circular-buffer",
        "polyglot_java_connect", "polyglot_java_custom-set", "polyglot_java_dominoes",
        "polyglot_java_food-chain", "polyglot_java_forth", "polyglot_java_go-counting",
        "polyglot_java_hangman", "polyglot_java_house", "polyglot_java_kindergarten-garden",
        "polyglot_java_ledger", "polyglot_java_mazy-mice", "polyglot_java_ocr-numbers",
        "polyglot_java_palindrome-products", "polyglot_java_phone-number", "polyglot_java_pig-latin",
        "polyglot_java_poker", "polyglot_java_pov", "polyglot_java_protein-translation",
        "polyglot_java_pythagorean-triplet", "polyglot_java_queen-attack", "polyglot_java_rational-numbers",
        "polyglot_java_react", "polyglot_java_resistor-color-trio", "polyglot_java_rest-api",
        "polyglot_java_satellite", "polyglot_java_series", "polyglot_java_sgf-parsing",
        "polyglot_java_simple-linked-list", "polyglot_java_state-of-tic-tac-toe", "polyglot_java_transpose",
        "polyglot_java_tree-building", "polyglot_java_twelve-days", "polyglot_java_two-bucket",
        "polyglot_java_variable-length-quantity", "polyglot_java_word-search", "polyglot_java_wordy",
        "polyglot_java_zebra-puzzle", "polyglot_java_zipper",
    ],
    "javascript": [
        "polyglot_javascript_affine-cipher", "polyglot_javascript_alphametics", "polyglot_javascript_beer-song",
        "polyglot_javascript_binary", "polyglot_javascript_book-store", "polyglot_javascript_bottle-song",
        "polyglot_javascript_bowling", "polyglot_javascript_complex-numbers", "polyglot_javascript_connect",
        "polyglot_javascript_food-chain", "polyglot_javascript_forth", "polyglot_javascript_go-counting",
        "polyglot_javascript_grade-school", "polyglot_javascript_grep", "polyglot_javascript_house",
        "polyglot_javascript_killer-sudoku-helper", "polyglot_javascript_ledger", "polyglot_javascript_list-ops",
        "polyglot_javascript_meetup", "polyglot_javascript_ocr-numbers", "polyglot_javascript_palindrome-products",
        "polyglot_javascript_parallel-letter-frequency", "polyglot_javascript_phone-number", "polyglot_javascript_pig-latin",
        "polyglot_javascript_poker", "polyglot_javascript_promises", "polyglot_javascript_queen-attack",
        "polyglot_javascript_rational-numbers", "polyglot_javascript_react", "polyglot_javascript_rectangles",
        "polyglot_javascript_resistor-color-trio", "polyglot_javascript_rest-api", "polyglot_javascript_robot-name",
        "polyglot_javascript_say", "polyglot_javascript_scale-generator", "polyglot_javascript_simple-linked-list",
        "polyglot_javascript_space-age", "polyglot_javascript_state-of-tic-tac-toe", "polyglot_javascript_sum-of-multiples",
        "polyglot_javascript_tournament", "polyglot_javascript_transpose", "polyglot_javascript_triangle",
        "polyglot_javascript_twelve-days", "polyglot_javascript_two-bucket", "polyglot_javascript_variable-length-quantity",
        "polyglot_javascript_word-search", "polyglot_javascript_wordy", "polyglot_javascript_zebra-puzzle",
        "polyglot_javascript_zipper",
    ],
    "rust": [
        "polyglot_rust_accumulate", "polyglot_rust_acronym", "polyglot_rust_alphametics",
        "polyglot_rust_book-store", "polyglot_rust_bowling", "polyglot_rust_decimal",
        "polyglot_rust_dot-dsl", "polyglot_rust_doubly-linked-list", "polyglot_rust_fizzy",
        "polyglot_rust_forth", "polyglot_rust_gigasecond", "polyglot_rust_grade-school",
        "polyglot_rust_grep", "polyglot_rust_luhn-from", "polyglot_rust_macros",
        "polyglot_rust_nucleotide-codons", "polyglot_rust_ocr-numbers", "polyglot_rust_parallel-letter-frequency",
        "polyglot_rust_pig-latin", "polyglot_rust_poker", "polyglot_rust_react",
        "polyglot_rust_robot-name", "polyglot_rust_say", "polyglot_rust_scale-generator",
        "polyglot_rust_simple-cipher", "polyglot_rust_two-bucket", "polyglot_rust_variable-length-quantity",
        "polyglot_rust_word-count", "polyglot_rust_wordy", "polyglot_rust_xorcism",
    ],
}

# Curated CPU-only Terminal-Bench candidate tasks (pinned for local evaluation)
TERMINAL_BENCH_CPU_TASKS: list[str] = [
    "build-cython-ext",
    "regex-log",
    "sqlite-db-truncate",
    "nginx-request-logging",
    "log-summary-date-ranges",
]

# Harbor Hub Terminal-Bench 2.0 task inventory, pinned to the source revision
# recorded by the Harbor registry used by the historical Oracle pilot.
TERMINAL_BENCH_2_TASKS: tuple[str, ...] = tuple("""\
make-mips-interpreter circuit-fibsqrt build-pov-ray overfull-hbox video-processing
distribution-search break-filter-js-from-html protein-assembly path-tracing compile-compcert
dna-assembly caffe-cifar-10 install-windows-3-11 log-summary-date-ranges vulnerable-secret
openssl-selfsigned-cert crack-7z-hash feal-linear-cryptanalysis polyglot-rust-c
cancel-async-tasks dna-insert rstan-to-pystan git-leak-recovery db-wal-recovery
headless-terminal extract-elf constraints-scheduling winning-avg-corewars
custom-memory-heap-crash build-cython-ext mteb-leaderboard fix-git regex-chess
prove-plus-comm pytorch-model-recovery mailman write-compressor chess-best-move
extract-moves-from-video gcode-to-text multi-source-data-merger merge-diff-arc-agi-task
kv-store-grpc git-multibranch qemu-alpine-ssh regex-log nginx-request-logging tune-mjcf
build-pmars sqlite-with-gcov sanitize-git-repo reshard-c4-data train-fasttext
torch-tensor-parallelism schemelike-metacircular-eval torch-pipeline-parallelism
count-dataset-tokens cobol-modernization raman-fitting pypi-server
model-extraction-relu-logits hf-model-inference sparql-university filter-js-from-html
largest-eigenval polyglot-c-py query-optimize fix-ocaml-gc pytorch-model-cli
bn-fit-modify password-recovery feal-differential-cryptanalysis sam-cell-seg
sqlite-db-truncate fix-code-vulnerability make-doom-for-mips modernize-scientific-stack
adaptive-rejection-sampler gpt2-codegolf mcmc-sampling-stan financial-document-processor
mteb-retrieve large-scale-text-editing code-from-image portfolio-optimization
path-tracing-reverse llm-inference-batching-scheduler qemu-startup configure-git-webserver
""".split())

# Terminal-Bench 4.0.0 release task inventory (source tag v4.0.0).
TERMINAL_BENCH_4_TASKS: tuple[str, ...] = tuple("""\
layout-config-recreation2 photonic-waveguide-routing mp-checkpoint-consolidation
biped-contact-dynamics ks-solver-cpp react-lead-form lake-temp-glm takens-embedding-lean
satb-audio-transcription formal-crypto fin-saccr-rwa embedding-drift-monitor math-eval-grader
pretrain-shard-corruption freight-dispatch-shift sound-change-cascade cad-model
glycan-ms2-elucidation coq-block-bound cargo-flight-dispatch payments-pipeline-fix
heat-pump-warranty foodstuff-beta-activity protein-autointerp-disulfide session-window-debug
batched-eval-parity wal-recovery-ordering ctr-optimization bun-sourcemap-leak
legacy-utility-triage mvcc-lsm-compaction risk-scorer-replay atrx-vep-crispr
nextjs-performance live-database-cutover cumulative-layout-shift data-anonymization
vba-userform-port freecad-impeller music-harmony telecom-entity-resolution
distributed-dedup ontology-kg-querying production-planning freecad-platform-drawing
vpp-loss-divergence gsea-proteomics intrastat-meldung kv-live-surgery html-js-filter
interleaved-vigenere uefi-bootkit layout-config-recreation shadow-relay
vllm-deepseek-streaming roy-polymorph-cn rs-archive-clone wdm-design freecad-spring-clip
fp8-rmsnorm-gemm vf2-speedup-networkx jax-speedrun-gpu medical-claims-processing
retro-console-soc sglang-qwen-burst hof-topology-interpenetration
""".split())


@dataclass(frozen=True)
class DatasetDescriptor:
    id: str
    name: str
    version: str
    description: str
    supported_languages: tuple[str, ...]
    all_tasks: tuple[str, ...]
    default_scoring_protocol: str
    harbor_dataset: str | None = None
    source_repo: str | None = None
    source_revision: str | None = None
    default_tasks: tuple[str, ...] = ()


# Dataset catalog registry
DATASETS: dict[str, DatasetDescriptor] = {
    "aider/aider-polyglot": DatasetDescriptor(
        id="aider/aider-polyglot",
        name="Aider Polyglot Coding Benchmark",
        version="1.0.0",
        description="225 coding exercises across six languages (Harbor official aider-polyglot)",
        supported_languages=("python", "cpp", "go", "java", "javascript", "rust"),
        all_tasks=tuple(task for lang in AIDER_POLYGLOT_TASKS.values() for task in lang),
        default_scoring_protocol="single-attempt-v1",
        harbor_dataset="aider-polyglot",
    ),
    "terminal-bench/terminal-bench@4.0.0": DatasetDescriptor(
        id="terminal-bench/terminal-bench@4.0.0",
        name="Terminal-Bench 4.0.0",
        version="4.0.0",
        description="Terminal-Bench 4.0.0 release snapshot (66 tasks)",
        supported_languages=("shell", "python"),
        all_tasks=TERMINAL_BENCH_4_TASKS,
        default_scoring_protocol="single-attempt-v1",
        harbor_dataset="terminal-bench/terminal-bench@4.0.0",
        source_repo="https://github.com/harbor-framework/terminal-bench.git",
        source_revision="452bf30",
    ),
    "terminal-bench/terminal-bench-2": DatasetDescriptor(
        id="terminal-bench/terminal-bench-2",
        name="Terminal-Bench 2.0",
        version="2.0",
        description="Terminal-Bench 2.0 Harbor dataset (89 tasks, source commit pinned)",
        supported_languages=("shell", "python"),
        all_tasks=TERMINAL_BENCH_2_TASKS,
        default_scoring_protocol="single-attempt-v1",
        harbor_dataset="terminal-bench/terminal-bench-2",
        source_repo="https://github.com/laude-institute/terminal-bench-2.git",
        source_revision="69671fbaac6d67a7ef0dfec016cc38a64ef7a77c",
        default_tasks=tuple(TERMINAL_BENCH_CPU_TASKS),
    ),
}
# Aliases
DATASETS["aider-polyglot"] = DATASETS["aider/aider-polyglot"]
DATASETS["terminal-bench-2"] = DATASETS["terminal-bench/terminal-bench-2"]
DATASETS["terminal-bench"] = DATASETS["terminal-bench/terminal-bench-2"]
DATASETS["terminal-bench-2-cpu-only"] = DATASETS["terminal-bench/terminal-bench-2"]
DATASETS["terminal-bench-cpu-only"] = DATASETS["terminal-bench/terminal-bench-2"]


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
    if not task_ids and not language and descriptor.default_tasks:
        candidates = list(descriptor.default_tasks)

    # 1. Filter by language if specified
    if language:
        lang_norm = language.lower().strip()
        candidates = [t for t in candidates if f"_{lang_norm}_" in t or t.startswith(f"{lang_norm}/") or lang_norm in t]
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
            # Match exact, normalized prefix, or suffix
            matches = [
                t for t in candidates
                if t == clean_tid
                or t == f"polyglot_{clean_tid.replace('/', '_')}"
                or t.endswith(f"_{clean_tid}")
                or t.endswith(f"/{clean_tid}")
            ]
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
