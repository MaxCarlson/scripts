"""Authoritative benchmark, dataset, and cohort catalog registry."""

from __future__ import annotations

from typing import Any, Sequence

from .schema import (
    BackendDescriptor,
    BenchmarkDescriptor,
    CohortDescriptor,
    DatasetDescriptor,
    ResourceDeclaration,
    ScorerDescriptor,
)


class BenchmarkCatalog:
    """Canonical registry for benchmarks, datasets, cohorts, backends, and scorers."""

    def __init__(self) -> None:
        self._benchmarks: dict[str, BenchmarkDescriptor] = {}
        self._datasets: dict[str, DatasetDescriptor] = {}
        self._dataset_aliases: dict[str, str] = {}
        self._cohorts: dict[str, CohortDescriptor] = {}
        self._backends: dict[str, BackendDescriptor] = {}
        self._scorers: dict[str, ScorerDescriptor] = {}

    def register_benchmark(self, desc: BenchmarkDescriptor) -> None:
        if desc.id in self._benchmarks:
            raise ValueError(f"Benchmark with ID {desc.id!r} already registered")
        self._benchmarks[desc.id] = desc

    def register_dataset(self, desc: DatasetDescriptor, aliases: Sequence[str] = ()) -> None:
        if desc.id in self._datasets:
            raise ValueError(f"Dataset with ID {desc.id!r} already registered")
        for alias in aliases:
            clean_alias = alias.strip()
            if clean_alias in self._datasets or clean_alias in self._dataset_aliases:
                raise ValueError(
                    f"Dataset alias {clean_alias!r} collides with existing dataset or alias. "
                    f"Registered datasets: {sorted(self._datasets.keys())}"
                )
            self._dataset_aliases[clean_alias] = desc.id
        self._datasets[desc.id] = desc

    def register_cohort(self, desc: CohortDescriptor) -> None:
        if desc.id in self._cohorts:
            raise ValueError(f"Cohort with ID {desc.id!r} already registered")
        self._cohorts[desc.id] = desc

    def register_backend(self, desc: BackendDescriptor) -> None:
        if desc.id in self._backends:
            raise ValueError(f"Backend with ID {desc.id!r} already registered")
        self._backends[desc.id] = desc

    def register_scorer(self, desc: ScorerDescriptor) -> None:
        if desc.id in self._scorers:
            raise ValueError(f"Scorer with ID {desc.id!r} already registered")
        self._scorers[desc.id] = desc

    def get_benchmark(self, benchmark_id: str) -> BenchmarkDescriptor:
        if benchmark_id not in self._benchmarks:
            raise KeyError(
                f"Unknown benchmark {benchmark_id!r}. Available benchmarks: {sorted(self._benchmarks.keys())}"
            )
        return self._benchmarks[benchmark_id]

    def list_benchmarks(self) -> list[BenchmarkDescriptor]:
        return [self._benchmarks[k] for k in sorted(self._benchmarks.keys())]

    def resolve_dataset(self, name_or_alias: str) -> DatasetDescriptor:
        clean = name_or_alias.strip()
        if clean in self._datasets:
            return self._datasets[clean]
        if clean in self._dataset_aliases:
            return self._datasets[self._dataset_aliases[clean]]

        # Fuzzy / partial matching consistent with historical Harbor resolve_dataset
        for k, v in self._datasets.items():
            if clean in (k, v.name, k.split("/")[-1], k.split("@")[0]):
                return v

        valid_keys = sorted(set(list(self._datasets.keys()) + list(self._dataset_aliases.keys())))
        raise KeyError(f"Unknown dataset {name_or_alias!r}. Available datasets: {valid_keys}")

    def get_dataset(self, dataset_id: str) -> DatasetDescriptor:
        return self.resolve_dataset(dataset_id)

    def list_datasets(self) -> list[DatasetDescriptor]:
        return [self._datasets[k] for k in sorted(self._datasets.keys())]

    def get_cohort(self, cohort_id: str) -> CohortDescriptor:
        if cohort_id not in self._cohorts:
            raise KeyError(f"Unknown cohort {cohort_id!r}. Available cohorts: {sorted(self._cohorts.keys())}")
        return self._cohorts[cohort_id]

    def list_cohorts(self) -> list[CohortDescriptor]:
        return [self._cohorts[k] for k in sorted(self._cohorts.keys())]

    def get_backend(self, backend_id: str) -> BackendDescriptor:
        if backend_id not in self._backends:
            raise KeyError(f"Unknown backend {backend_id!r}. Available backends: {sorted(self._backends.keys())}")
        return self._backends[backend_id]

    def list_backends(self) -> list[BackendDescriptor]:
        return [self._backends[k] for k in sorted(self._backends.keys())]

    def get_scorer(self, scorer_id: str) -> ScorerDescriptor:
        if scorer_id not in self._scorers:
            raise KeyError(f"Unknown scorer {scorer_id!r}. Available scorers: {sorted(self._scorers.keys())}")
        return self._scorers[scorer_id]

    def list_scorers(self) -> list[ScorerDescriptor]:
        return [self._scorers[k] for k in sorted(self._scorers.keys())]


# Singleton default registry
_CATALOG: BenchmarkCatalog | None = None


def get_default_catalog() -> BenchmarkCatalog:
    """Return the global initialized catalog, populating default benchmarks if not initialized."""
    global _CATALOG
    if _CATALOG is None:
        catalog = BenchmarkCatalog()
        _init_default_catalog(catalog)
        _CATALOG = catalog
    return _CATALOG


def _init_default_catalog(catalog: BenchmarkCatalog) -> None:
    # 1. Backends
    catalog.register_backend(
        BackendDescriptor(
            id="harbor",
            name="Harbor Execution Backend",
            description="Harbor-based agent and tool workflow container execution",
            capabilities=("docker_isolation", "tool_interaction", "agent_adapter"),
            required_resources=("docker", "harbor_tool"),
        )
    )
    catalog.register_backend(
        BackendDescriptor(
            id="direct_chat",
            name="Direct Model Chat Backend",
            description="Direct HTTP OpenAI-compatible completion client for local inference models",
            capabilities=("single_turn_prompt", "raw_generation_capture", "local_endpoint"),
            required_resources=("local_model_endpoint",),
        )
    )

    # 2. Scorers
    catalog.register_scorer(
        ScorerDescriptor(
            id="harbor_verifier",
            name="Harbor Task Verifier",
            version="1.0.0",
            description="Harbor automated test/verifier execution in Docker container",
            protocol="single-attempt-v1",
        )
    )
    catalog.register_scorer(
        ScorerDescriptor(
            id="ifeval_official",
            name="Official Google IFEval Scorer",
            version="1.0.0",
            description="Official Google Research strict and loose instruction following evaluation",
            protocol="ifeval-strict-loose-v1",
            required_resources=("python_environment",),
        )
    )
    catalog.register_scorer(
        ScorerDescriptor(
            id="lcb_official",
            name="Official LiveCodeBench Scorer",
            version="1.0.0",
            description="Official LiveCodeBench custom code generation evaluation and execution",
            protocol="lcb-codegeneration-v1",
            required_resources=("python_environment", "container_sandbox"),
        )
    )

    # 3. Benchmarks & Datasets
    # 3a. Aider Polyglot
    from ..harbor.datasets import (
        AIDER_POLYGLOT_TASKS,
        TERMINAL_BENCH_2_TASKS,
        TERMINAL_BENCH_4_TASKS,
        TERMINAL_BENCH_CPU_TASKS,
    )

    catalog.register_benchmark(
        BenchmarkDescriptor(
            id="aider",
            name="Aider Polyglot Coding Benchmark",
            version="1.0.0",
            description="Coding exercise benchmark evaluating polyglot agent modification capabilities",
            implementation_type="harbor_agent",
            trusted_adapter_id="harbor",
            supported_backends=("harbor",),
            default_dataset="aider/aider-polyglot",
            resources=(
                ResourceDeclaration(
                    type="harbor_registry",
                    name="aider-polyglot",
                    description="Harbor registry dataset definition",
                ),
            ),
        )
    )

    catalog.register_dataset(
        DatasetDescriptor(
            id="aider/aider-polyglot",
            benchmark_id="aider",
            name="Aider Polyglot Coding Benchmark",
            version="1.0.0",
            description="225 coding exercises across six languages (Harbor official aider-polyglot)",
            supported_languages=("python", "cpp", "go", "java", "javascript", "rust"),
            all_tasks=tuple(task for lang in AIDER_POLYGLOT_TASKS.values() for task in lang),
            default_scoring_protocol="single-attempt-v1",
            harbor_dataset="aider-polyglot",
            tags=("coding", "exercism", "agentic"),
            install_state="installed",
        ),
        aliases=["aider-polyglot"],
    )

    # 3b. Terminal-Bench
    catalog.register_benchmark(
        BenchmarkDescriptor(
            id="terminal-bench",
            name="Terminal-Bench",
            version="4.0.0",
            description="Realistic command-line and systems tasks for autonomous coding agents",
            implementation_type="harbor_agent",
            trusted_adapter_id="harbor",
            supported_backends=("harbor",),
            default_dataset="terminal-bench/terminal-bench-2",
            resources=(
                ResourceDeclaration(
                    type="harbor_registry",
                    name="terminal-bench",
                    description="Harbor registry dataset definition",
                ),
            ),
        )
    )

    catalog.register_dataset(
        DatasetDescriptor(
            id="terminal-bench/terminal-bench@4.0.0",
            benchmark_id="terminal-bench",
            name="Terminal-Bench 4.0.0",
            version="4.0.0",
            description="Terminal-Bench 4.0.0 release snapshot (66 tasks)",
            supported_languages=("shell", "python"),
            all_tasks=TERMINAL_BENCH_4_TASKS,
            default_scoring_protocol="single-attempt-v1",
            harbor_dataset="terminal-bench/terminal-bench@4.0.0",
            source_repo="https://github.com/harbor-framework/terminal-bench.git",
            source_revision="452bf30",
            tags=("terminal", "systems", "agentic"),
            install_state="installed",
        )
    )

    catalog.register_dataset(
        DatasetDescriptor(
            id="terminal-bench/terminal-bench-2",
            benchmark_id="terminal-bench",
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
            tags=("terminal", "systems", "agentic"),
            install_state="installed",
        ),
        aliases=[
            "terminal-bench-2",
            "terminal-bench",
            "terminal-bench-2-cpu-only",
            "terminal-bench-cpu-only",
        ],
    )

    # 3c. Cohort: aider-python-10
    from ..suite import FROZEN_REVISION

    catalog.register_cohort(
        CohortDescriptor(
            id="aider-python-10",
            dataset_id="aider/aider-polyglot",
            source_revision=FROZEN_REVISION,
            task_ids=(
                "polyglot_python_beer-song",
                "polyglot_python_bottle-song",
                "polyglot_python_bowling",
                "polyglot_python_dot-dsl",
                "polyglot_python_pig-latin",
                "polyglot_python_react",
                "polyglot_python_robot-name",
                "polyglot_python_transpose",
                "polyglot_python_variable-length-quantity",
                "polyglot_python_zipper",
            ),
            description="Frozen 10-task Python subset for reproducible agent benchmarking",
            tags=("python", "frozen", "baseline"),
        )
    )

    # 3d. IFEval Benchmark & Initial Registered-but-not-installed Dataset/Cohorts
    catalog.register_benchmark(
        BenchmarkDescriptor(
            id="ifeval",
            name="Instruction Following Evaluation (IFEval)",
            version="1.0.0",
            description="Google Research official instruction-following benchmark with strict and loose constraints",
            implementation_type="direct_model",
            trusted_adapter_id="ifeval",
            supported_backends=("direct_chat",),
            default_dataset="ifeval/google-2023",
            resources=(
                ResourceDeclaration(
                    type="git_sparse",
                    name="google-research-ifeval",
                    url="https://github.com/google-research/google-research.git",
                    revision="c38b4d8c6b90de2b3c2e1f4094a4c58cf3a79a8e",
                    paths=("instruction_following_eval",),
                    description="Pinned Google Research IFEval reference scorer and evaluation library",
                ),
                ResourceDeclaration(
                    type="python_environment",
                    name="ifeval-venv",
                    env_requirements=("absl-py", "langdetect", "nltk", "immutabledict"),
                    description="Isolated Python runtime for official IFEval scorer execution",
                ),
            ),
            limitations=("Requires isolated Python scorer environment with langdetect and NLTK",),
        )
    )

    catalog.register_dataset(
        DatasetDescriptor(
            id="ifeval/google-2023",
            benchmark_id="ifeval",
            name="Google IFEval Input Data",
            version="2023.11",
            description="541 prompt-instruction evaluation tasks from Google Research",
            supported_languages=("english",),
            all_tasks=(),  # Eager task enumeration deferred until installation
            default_scoring_protocol="ifeval-strict-loose-v1",
            source_repo="https://github.com/google-research/google-research.git",
            source_revision="c38b4d8c6b90de2b3c2e1f4094a4c58cf3a79a8e",
            tags=("instruction_following", "direct_model", "official"),
            install_state="registered",
            readiness_reason="Upstream source and input_data.jsonl not yet installed; run 'agent-benchmark setup install -d ifeval -x'",
        ),
        aliases=["ifeval"],
    )

    catalog.register_cohort(
        CohortDescriptor(
            id="ifeval-smoke",
            dataset_id="ifeval/google-2023",
            source_revision="c38b4d8c6b90de2b3c2e1f4094a4c58cf3a79a8e",
            task_ids=(),  # Resolved from installed dataset snapshot
            description="Small smoke subset for quick validation of instruction adherence",
            tags=("smoke", "ifeval"),
            scorer_id="ifeval_official",
        )
    )

    catalog.register_cohort(
        CohortDescriptor(
            id="ifeval-100",
            dataset_id="ifeval/google-2023",
            source_revision="c38b4d8c6b90de2b3c2e1f4094a4c58cf3a79a8e",
            task_ids=(),  # Resolved from installed dataset snapshot
            description="Stratified 100-task frozen evaluation cohort across constraint types",
            tags=("100-subset", "ifeval"),
            scorer_id="ifeval_official",
        )
    )

    catalog.register_cohort(
        CohortDescriptor(
            id="ifeval-full",
            dataset_id="ifeval/google-2023",
            source_revision="c38b4d8c6b90de2b3c2e1f4094a4c58cf3a79a8e",
            task_ids=(),  # Resolved from installed dataset snapshot
            description="Full 541-task official Google IFEval benchmark",
            tags=("full", "ifeval"),
            scorer_id="ifeval_official",
        )
    )

    # 3e. LiveCodeBench Benchmark & Initial Registered-but-not-installed Dataset/Cohorts
    catalog.register_benchmark(
        BenchmarkDescriptor(
            id="livecodebench",
            name="LiveCodeBench (LCB)",
            version="v6",
            description="Holistic evaluation of LLMs on challenging, contamination-free programming problems",
            implementation_type="direct_model",
            trusted_adapter_id="livecodebench",
            supported_backends=("direct_chat",),
            default_dataset="livecodebench/release_v6",
            resources=(
                ResourceDeclaration(
                    type="git",
                    name="livecodebench-repo",
                    url="https://github.com/LiveCodeBench/LiveCodeBench.git",
                    revision="642398511cb8b1fa85142106e224e756c9a35e72",
                    description="Official LiveCodeBench evaluation runner and problem scenarios",
                ),
                ResourceDeclaration(
                    type="huggingface_dataset",
                    name="lcb-code-generation-lite",
                    url="https://huggingface.co/datasets/livecodebench/code_generation_lite",
                    revision="release_v6",
                    description="Default lightweight code generation dataset release v6",
                ),
                ResourceDeclaration(
                    type="python_environment",
                    name="lcb-scorer-env",
                    description="Isolated Python runtime with LiveCodeBench dependencies",
                ),
                ResourceDeclaration(
                    type="container_image",
                    name="lcb-sandbox-verifier",
                    description="Secure isolated execution sandbox for untrusted code execution",
                ),
            ),
            limitations=("Untrusted code execution requires Docker container sandbox with --network none",),
        )
    )

    catalog.register_dataset(
        DatasetDescriptor(
            id="livecodebench/release_v6",
            benchmark_id="livecodebench",
            name="LiveCodeBench Release v6 (code_generation_lite)",
            version="release_v6",
            description="Contamination-free competitive programming problems release v6 (code_generation_lite)",
            supported_languages=("python",),
            all_tasks=(),  # Eager task enumeration deferred until installation
            default_scoring_protocol="lcb-codegeneration-v1",
            source_repo="https://github.com/LiveCodeBench/LiveCodeBench.git",
            source_revision="642398511cb8b1fa85142106e224e756c9a35e72",
            tags=("coding", "direct_model", "official", "sandbox_required"),
            install_state="registered",
            readiness_reason="Upstream source and dataset not yet installed; run 'agent-benchmark setup install -d livecodebench -x'",
        ),
        aliases=["livecodebench", "lcb", "lcb-v6"],
    )

    catalog.register_cohort(
        CohortDescriptor(
            id="lcb-v6-smoke",
            dataset_id="livecodebench/release_v6",
            source_revision="642398511cb8b1fa85142106e224e756c9a35e72",
            task_ids=(),
            description="Smoke subset of LiveCodeBench v6 problems for verifier qualification",
            tags=("smoke", "livecodebench"),
            scorer_id="lcb_official",
        )
    )

    catalog.register_cohort(
        CohortDescriptor(
            id="lcb-v6-direct-100",
            dataset_id="livecodebench/release_v6",
            source_revision="642398511cb8b1fa85142106e224e756c9a35e72",
            task_ids=(),
            description="Stratified 100-task frozen evaluation cohort across contest difficulty levels",
            tags=("100-subset", "livecodebench"),
            scorer_id="lcb_official",
        )
    )

    catalog.register_cohort(
        CohortDescriptor(
            id="lcb-v6-direct-full",
            dataset_id="livecodebench/release_v6",
            source_revision="642398511cb8b1fa85142106e224e756c9a35e72",
            task_ids=(),
            description="Full LiveCodeBench release v6 code generation benchmark",
            tags=("full", "livecodebench"),
            scorer_id="lcb_official",
        )
    )


def get_unified_discovery(*, include_readiness: bool = True) -> dict[str, Any]:
    """
    Expose a unified read-only discovery dictionary.

    Guarantees backward-compatible 'cohorts' list for existing suite list consumers,
    while also exposing all datasets, backends, benchmarks, and readiness.
    """
    catalog = get_default_catalog()

    # Legacy cohorts view
    cohort_rows = [
        {
            "id": c.id,
            "dataset": c.dataset_id,
            "source_revision": c.source_revision,
            "tasks": len(c.task_ids),
        }
        for c in catalog.list_cohorts()
    ]

    # Datasets view
    dataset_rows = [d.to_dict() for d in catalog.list_datasets()]

    # Benchmarks view
    benchmark_rows = [b.to_dict() for b in catalog.list_benchmarks()]

    # Backends view
    backend_rows = [be.to_dict() for be in catalog.list_backends()]

    result: dict[str, Any] = {
        "cohorts": cohort_rows,
        "datasets": dataset_rows,
        "benchmarks": benchmark_rows,
        "backends": backend_rows,
    }

    if include_readiness:
        # Check harbor and docker readiness without executing anything
        from ..harbor import check_docker_readiness, check_harbor_readiness

        harbor_ok, harbor_ver = check_harbor_readiness()
        docker_ok, docker_msg = check_docker_readiness()
        result["readiness"] = {
            "harbor_available": harbor_ok,
            "harbor_version": harbor_ver,
            "docker_available": docker_ok,
            "docker_status": docker_msg,
        }

    return result
