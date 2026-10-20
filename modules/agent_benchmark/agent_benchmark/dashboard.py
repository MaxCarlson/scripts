"""
Bounded live terminal dashboard and quiet mode adapter for multi-model benchmarks.

Consumes termdash.LiveBlock, termdash.Table, and termdash.render_horizontal_bar
to render bounded in-place console progress with clean non-interactive fallback
and a quiet mode (-Q/--quiet) for scripts and batch pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import asdict
import json
import logging
import shutil
import sys
import textwrap
import time
from typing import Any, Optional, TextIO

from benchmark_core import (
    ExperimentComparison,
    RunInfo,
    TrialResult,
)
from termdash import LiveBlock, Table, render_horizontal_bar
from termdash.utils import color_text

from .scheduler import ExperimentPlan, ExperimentScheduler, PlannedTrial
from .diagnostics import describe_trial
from .telemetry import ResourceSampler, format_resource_line

logger = logging.getLogger(__name__)


def _terminal_width() -> int:
    """Return a practical width for tables and section rules."""
    return max(40, shutil.get_terminal_size(fallback=(100, 24)).columns)


@dataclass
class ModelProgressState:
    """Live execution metrics for one evaluated model."""

    model_key: str
    status: str = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED
    total_trials: int = 0
    completed_trials: int = 0
    passed: int = 0
    failed: int = 0
    timed_out: int = 0
    infra_errors: int = 0
    durations_ms: list[float] = field(default_factory=list)

    @property
    def scored_denominator(self) -> int:
        return self.passed + self.failed + self.timed_out

    @property
    def strict_pass_rate(self) -> Optional[float]:
        return (self.passed / self.scored_denominator) if self.scored_denominator > 0 else None

    @property
    def mean_duration_sec(self) -> Optional[float]:
        if not self.durations_ms:
            return None
        return (sum(self.durations_ms) / len(self.durations_ms)) / 1000.0


class ExperimentDashboard:
    """
    Terminal dashboard managing bounded in-place console updates and quiet mode.

    Guarantees:
    - Bounded display: total transient rows never exceed 10-12 rows.
    - Graceful non-interactive / pipe fallback via LiveBlock.
    - Quiet mode: disables transient blocks and outputs clean milestone logs only.
    - Safe terminal restoration on exit or exception.
    """

    def __init__(
        self,
        plan: ExperimentPlan,
        *,
        quiet: bool = False,
        stream: Optional[TextIO] = None,
        max_visible_models: int = 5,
        resource_sampler: ResourceSampler | None = None,
    ) -> None:
        self.plan = plan
        self.quiet = quiet
        self.stream = stream or sys.stdout
        self.max_visible_models = max_visible_models
        self.resource_sampler = resource_sampler or ResourceSampler(on_sample=self._log_resource_sample)

        self.start_time = time.monotonic()
        self.active_trial: Optional[PlannedTrial] = None
        self.active_trial_start: Optional[float] = None
        self.completed_trials_count = 0
        self.trial_results: dict[str, list[TrialResult]] = {}

        # Initialize per-model progress
        self.models: dict[str, ModelProgressState] = {}
        for m_key in plan.model_keys:
            m_trials = plan.trials_for_model(m_key)
            self.models[m_key] = ModelProgressState(
                model_key=m_key,
                total_trials=len(m_trials),
            )

        # LiveBlock setup: enabled only when NOT quiet
        self.live_block = LiveBlock(
            stream=self.stream,
            enabled=(not self.quiet),
            interval=0.2,
        )

        # Resource history belongs to the experiment, not to terminal redraws.
        self.resource_sampler.start()
        if not self.quiet:
            self.live_block.update(self._render_live_lines)
        else:
            self._log_quiet(
                f"[EXPERIMENT START] {plan.experiment_id} | Suite: {plan.config.suite_id} v{plan.config.suite_version} "
                f"| Models: {len(plan.model_keys)} | Total Trials: {plan.total_trials}"
            )

    @staticmethod
    def _log_resource_sample(snapshot: Any) -> None:
        logger.info("Resource sample %s", json.dumps(asdict(snapshot), sort_keys=True),
                    extra={"event_type": "RESOURCE_SAMPLE"})

    def attach(self, scheduler: ExperimentScheduler) -> None:
        """Attach dashboard event handlers to an ExperimentScheduler instance."""
        scheduler.on_model_start = self.on_model_start
        scheduler.on_trial_start = self.on_trial_start
        scheduler.on_trial_complete = self.on_trial_complete
        scheduler.on_model_complete = self.on_model_complete
        scheduler.on_experiment_complete = self.on_experiment_complete

    def __enter__(self) -> ExperimentDashboard:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Safely close live block and restore terminal state."""
        self.live_block.close()
        self.resource_sampler.stop()

    def _log_quiet(self, message: str) -> None:
        print(message, file=self.stream, flush=True)

    def _render_live_lines(self) -> list[str]:
        """
        Produce transient console lines. Strictly bounded to <= 10-12 rows.
        """
        elapsed = time.monotonic() - self.start_time
        total = max(1, self.plan.total_trials)
        pct = (self.completed_trials_count / total) * 100.0
        ratio = max(0.0, min(1.0, self.completed_trials_count / total))

        bar = render_horizontal_bar(ratio, width=16, color="cyan", brackets=True)

        lines: list[str] = [
            # Line 1: Header + Overall Progress
            f"[EXP {self.plan.experiment_id}]  {bar} {self.completed_trials_count}/{total} ({pct:4.1f}%)  "
            f"Elapsed: {elapsed:.1f}s",
        ]
        lines.append(format_resource_line(self.resource_sampler.snapshot()))

        # Line 2: Active Trial Status
        if self.active_trial:
            trial_elapsed = (
                (time.monotonic() - self.active_trial_start)
                if self.active_trial_start
                else 0.0
            )
            trial_tag = color_text(f"[{self.active_trial.model_key}]", "yellow")
            status_tag = color_text("RUNNING", "green")
            lines.append(
                f">> Active: {trial_tag} task:{self.active_trial.task_id} (rep {self.active_trial.repetition}/{self.plan.repetitions})  "
                f"State: {status_tag} ({trial_elapsed:.1f}s)"
            )
        else:
            lines.append(">> Active: [idle] waiting for trial dispatch...")

        # Lines 3-8: Compact Model Progress Table
        table = Table(
            headers=["Model", "Status", "Trials", "Strict Pass", "Timeouts", "Mean Dur"],
            style="dash",
            border=True,
            padding=1,
        )

        visible_keys = list(self.plan.model_keys)[: self.max_visible_models]
        for mk in visible_keys:
            ms = self.models[mk]
            # Format status
            if ms.status == "RUNNING":
                st_str = color_text("RUNNING", "yellow")
            elif ms.status == "COMPLETED":
                st_str = color_text("DONE", "green")
            elif ms.status == "FAILED":
                st_str = color_text("FAILED", "red")
            else:
                st_str = "QUEUED"

            trials_str = f"{ms.completed_trials}/{ms.total_trials}"
            pass_str = f"{ms.strict_pass_rate * 100:.1f}% ({ms.passed}/{ms.scored_denominator})" if ms.strict_pass_rate is not None else "-"
            timeout_str = str(ms.timed_out)
            dur_str = f"{ms.mean_duration_sec:.1f}s" if ms.mean_duration_sec is not None else "-"

            table.add_row(mk, st_str, trials_str, pass_str, timeout_str, dur_str)

        if len(self.plan.model_keys) > self.max_visible_models:
            remaining = len(self.plan.model_keys) - self.max_visible_models
            table.add_row(f"+{remaining} more models...", "-", "-", "-", "-", "-")

        table_output = table.render(max_width=_terminal_width())
        for t_line in table_output.splitlines():
            lines.append(t_line)

        # Footer notice line
        lines.append(color_text("Ctrl+C halts safely (state & evidence preserved).", "gray"))

        return lines

    # =========================================================================
    # Event Callbacks
    # =========================================================================

    def on_model_start(self, model_key: str) -> None:
        if model_key in self.models:
            self.models[model_key].status = "RUNNING"

        if self.quiet:
            self._log_quiet(f"[MODEL START] {model_key} | Beginning evaluation")
        else:
            self.live_block.log(f"⚡ Starting model evaluation: {color_text(model_key, 'cyan')}")

    def on_trial_start(self, trial: PlannedTrial, res: Any = None) -> None:
        self.active_trial = trial
        self.active_trial_start = time.monotonic()

        if self.quiet:
            self._log_quiet(
                f"[TRIAL START] {trial.trial_index + 1}/{trial.total_trials} [{trial.model_key}] "
                f"{trial.task_id} (rep {trial.repetition}/{self.plan.repetitions})"
            )

    def on_trial_complete(self, trial: PlannedTrial, result: Optional[TrialResult]) -> None:
        self.active_trial = None
        self.active_trial_start = None
        self.completed_trials_count += 1

        ms = self.models.get(trial.model_key)
        if result:
            self.trial_results.setdefault(trial.model_key, []).append(result)
            status_val = result.status.value if hasattr(result.status, "value") else str(result.status)
            status_name = status_val.upper()
        else:
            status_val = "unknown"
            status_name = "UNKNOWN"

        dur_ms = 0.0
        if result and "duration.wall_ms" in result.metrics:
            dur_val = result.metrics["duration.wall_ms"].value
            dur_ms = float(dur_val) if dur_val is not None else 0.0

        if ms and result:
            ms.completed_trials += 1
            if status_val == "passed":
                ms.passed += 1
            elif status_val == "failed":
                ms.failed += 1
            elif status_val == "timed_out":
                ms.timed_out += 1
            elif status_val == "infrastructure_error":
                ms.infra_errors += 1
            if dur_ms > 0:
                ms.durations_ms.append(dur_ms)

        dur_s = dur_ms / 1000.0

        if self.quiet:
            self._log_quiet(
                f"[TRIAL COMPLETE] {trial.trial_index + 1}/{trial.total_trials} [{trial.model_key}] "
                f"{trial.task_id} r{trial.repetition} -> {status_name} ({dur_s:.1f}s)"
            )
        else:
            if status_val == "passed":
                badge = color_text("PASS", "green")
            elif status_val == "timed_out":
                badge = color_text("TIMEOUT", "yellow")
            else:
                badge = color_text(status_name, "red")

            self.live_block.log(
                f"  [{trial.trial_index + 1}/{trial.total_trials}] [{trial.model_key}] "
                f"{trial.task_id} r{trial.repetition} -> {badge} ({dur_s:.1f}s)"
            )

        if result:
            for detail in describe_trial(result):
                for line in textwrap.wrap(detail, width=max(40, _terminal_width() - 4)):
                    if self.quiet:
                        self._log_quiet(f"    {line}")
                    else:
                        self.live_block.log(f"    {line}")

    def on_model_complete(
        self,
        model_key: str,
        run_info: Optional[RunInfo],
        trials: list[TrialResult],
    ) -> None:
        ms = self.models.get(model_key)
        if ms:
            successful = bool(trials) and all(str(trial.status) == "passed" for trial in trials)
            ms.status = "COMPLETED" if successful else "FAILED"
            strict_pct = f"{ms.strict_pass_rate * 100:.1f}%" if ms.strict_pass_rate is not None else "N/A"
            msg = (
                f"[MODEL {'COMPLETE' if successful else 'RESULT'}] {model_key} | Passed: {ms.passed}/{ms.scored_denominator} "
                f"(Strict: {strict_pct}) | Timeouts: {ms.timed_out} | Infra Errors: {ms.infra_errors} "
                f"| Unscored: {sum(str(trial.status) == 'unscored' for trial in trials)}"
            )
            functional = [t.metrics["agent.functional_pass"].value for t in trials
                          if "agent.functional_pass" in t.metrics and t.metrics["agent.functional_pass"].value is not None]
            msg += (f" | Code checks: {sum(value == 1 for value in functional)}/{len(functional)} passed"
                    f"; {len(trials) - len(functional)} unavailable")
            if self.quiet:
                self._log_quiet(msg)
            else:
                badge = "✔" if successful else "!"
                self.live_block.log(f"{badge} {color_text(msg, 'green' if successful else 'red')}")

    def on_experiment_complete(self, comparison: ExperimentComparison) -> None:
        """
        Close transient display and print the final persistent leaderboard table.
        """
        self.close()

        total_elapsed = time.monotonic() - self.start_time
        terminal_width = _terminal_width()
        divider = "=" * terminal_width
        title = "BENCHMARK EXPERIMENT RESULTS SUMMARY"
        lines: list[str] = [
            "",
            divider,
            title.center(terminal_width),
            divider,
            f"Experiment ID: {comparison.experiment_id}",
            f"Suite ID:      {comparison.config.suite_id} (v{comparison.config.suite_version})",
            f"Budget:        {comparison.config.budget_profile}",
            f"Elapsed:       {total_elapsed:.1f}s",
            "",
            "CANONICAL LEADERBOARD (Comparison-Eligible Models Only):",
        ]

        if not comparison.canonical_rankings:
            lines.append("  (No models with a defined strict rate to rank)")
        elif terminal_width < 110:
            for rank, vid in enumerate(comparison.canonical_rankings, start=1):
                vm = comparison.eligible_variants[vid]
                rate_str = f"{vm.strict_acceptance_rate * 100:.1f}%" if vm.strict_acceptance_rate is not None else "N/A"
                if vm.confidence_interval_95:
                    ci = vm.confidence_interval_95
                    rate_str += f" [{ci.lower * 100:.1f}% - {ci.upper * 100:.1f}%]"
                denom_str = f"{vm.scored_denominator} ({vm.passed}/{vm.failed}/{vm.timed_out})"
                other_str = f"{vm.infrastructure_error}/{vm.unscored}"
                dur_str = (
                    f"{vm.duration.all_scored.mean / 1000.0:.1f}s"
                    if vm.duration.all_scored and vm.duration.all_scored.mean is not None
                    else "N/A"
                )
                lines.extend(
                    [
                        f"{rank}. {vid}",
                        f"   Pass rate (95% CI): {rate_str}",
                        f"   Scored (P/F/T): {denom_str} | Other (I/U): {other_str}",
                        f"   Mean duration: {dur_str}",
                    ]
                )
        else:
            lead_table = Table(
                headers=["Rank", "Model", "Pass Rate (95% CI)", "Scored (P/F/T)", "Other (I/U)", "Mean Dur"],
                style="dash",
                border=True,
                padding=1,
            )
            for rank, vid in enumerate(comparison.canonical_rankings, start=1):
                vm = comparison.eligible_variants[vid]
                rate_str = f"{vm.strict_acceptance_rate * 100:.1f}%" if vm.strict_acceptance_rate is not None else "N/A"
                if vm.confidence_interval_95:
                    ci = vm.confidence_interval_95
                    ci_str = f" [{ci.lower * 100:.1f}% - {ci.upper * 100:.1f}%]"
                else:
                    ci_str = ""
                full_rate = f"{rate_str}{ci_str}"
                denom_str = f"{vm.scored_denominator} ({vm.passed}/{vm.failed}/{vm.timed_out})"
                other_str = f"{vm.infrastructure_error}/{vm.unscored}"
                dur_str = (
                    f"{vm.duration.all_scored.mean / 1000.0:.1f}s"
                    if vm.duration.all_scored and vm.duration.all_scored.mean is not None
                    else "N/A"
                )
                lead_table.add_row(str(rank), vid, full_rate, denom_str, other_str, dur_str)

            lines.append(lead_table.render(max_width=terminal_width))

        for key, group in sorted(comparison.condition_groups.items()):
            conditions = group.get("config", {}).get("metadata", {}).get("comparison_contract", {})
            lines.extend(["", f"SEPARATE COMPARISON CONDITIONS {key[:12]}:",
                          f"  Context: {conditions.get('context_length', 'UNKNOWN')}; "
                          f"budget: {conditions.get('budget', {}).get('profile', 'UNKNOWN')}"])
            ranks = group.get("canonical_rankings", [])
            for vid, vm in sorted({**group.get("eligible_variants", {}), **group.get("reference_variants", {})}.items()):
                label = f"group rank {ranks.index(vid) + 1}" if vid in ranks else "unranked"
                code = vm.get("metrics", {}).get("agent.functional_pass", {})
                functional = f"{code['mean']:.1%} ({code['available_count']} measured)" if code.get("mean") is not None else "UNKNOWN"
                lines.append(f"  {vid}: {label}; trials {vm['total_trials']}; functional {functional}")
        if comparison.incompatible_runs:
            lines.extend(["", "INCOMPATIBLE / UNKNOWN-CONDITION DIAGNOSTICS:"])
            for run in comparison.incompatible_runs:
                lines.append(f"  {run['run_id']}: {'; '.join(run['reasons'])}")
                for trial in run.get("trials", []):
                    code = trial.get("metrics", {}).get("agent.functional_pass", {}).get("value")
                    lines.append(f"    {trial['variant_id']}: {trial['status']}; code "
                                 + {1: "PASS", 0: "FAIL"}.get(code, "UNKNOWN"))

        if comparison.unranked_variants:
            lines.extend(["", "UNRANKED DIAGNOSTICS (no strict scored denominator):"])
            for vid, vm in sorted(comparison.unranked_variants.items()):
                observed = vm.metrics.get("duration.wall_ms")
                duration_text = f"{observed.mean / 1000:.1f}s" if observed and observed.mean is not None else "unknown"
                lines.append(f"  {vid}: trials {vm.total_trials}; infra {vm.infrastructure_error}; "
                             f"unscored {vm.unscored}; observed mean {duration_text}")
                lines.extend(f"    {reason}" for reason in vm.diagnostic_reasons)

        if comparison.reference_variants:
            lines.append("")
            lines.append("REFERENCE & COMPARISON-INELIGIBLE MODELS:")
            ref_table = Table(
                headers=["Model", "Exclusion Reason", "Pass", "Scored (P/F/T)", "Other (I/U)"],
                style="dash",
                border=True,
                padding=1,
            )
            for vid, vm in sorted(comparison.reference_variants.items()):
                reasons = "; ".join(vm.exclusion_reasons) if vm.exclusion_reasons else "Ineligible"
                rate_str = f"{vm.strict_acceptance_rate * 100:.1f}%" if vm.strict_acceptance_rate is not None else "N/A"
                denom_str = f"{vm.scored_denominator} ({vm.passed}/{vm.failed}/{vm.timed_out})"
                other_str = f"{vm.infrastructure_error}/{vm.unscored}"
                ref_table.add_row(vid, reasons, rate_str, denom_str, other_str)

            lines.append(ref_table.render(max_width=terminal_width))

        if self.trial_results:
            lines.extend(["", "FUNCTIONAL CODE CHECKS (scope and time results reported separately):"])
            for model, results in self.trial_results.items():
                known = [t.metrics["agent.functional_pass"].value for t in results
                         if "agent.functional_pass" in t.metrics and t.metrics["agent.functional_pass"].value is not None]
                passed = sum(value == 1 for value in known)
                lines.extend(textwrap.wrap(
                    f"{model}: {passed}/{len(known)} passed; {len(results) - len(known)} unavailable",
                    width=max(40, terminal_width - 2), initial_indent="  ", subsequent_indent="    ",
                ))

        lines.append(divider)
        lines.append("")

        output_text = "\n".join(lines)
        print(output_text, file=self.stream, flush=True)
