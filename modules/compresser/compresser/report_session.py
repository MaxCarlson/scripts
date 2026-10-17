"""CLI report lifecycle: structured facts only, never stdout/progress capture."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace, asdict
from functools import wraps
import shutil
import sys

from .report_models import CompressionReport, ReportContext
from . import reporting

_current: ContextVar[ReportSession | None] = ContextVar("compression_report_session", default=None)


def current_session():
    return _current.get()


class ReportSession:
    def __init__(self, args):
        self.args = args
        self.workspace = args._workspace
        options = getattr(args, "_compression_options", None)
        operation = options.operation if options else None
        self.operation = (
            {
                "inventory": "inventory",
                "plan": "plan",
                "estimate": "estimate",
                "analyze": "analysis",
                "compare": "comparison",
                "preview": "preview",
                "apply": "write",
                "recover": "recovery",
            }.get(operation)
            if operation
            else (
            "inventory"
            if args.inventory_only
            else (
                "preview"
                if args.preview_dir
                else "comparison" if args.compare else "write" if args.write else "analysis"
            )
            )
        )
        self.context = ReportContext(
            self.workspace.target,
            self.workspace.root,
            settings={
                name: getattr(args, name, None)
                for name in (
                    "write",
                    "url",
                    "format",
                    "mode",
                    "quality",
                    "preview_qualities",
                    "perceptual_target",
                    "algorithm",
                    "effort",
                    "threads",
                    "memory_budget_mib",
                    "inventory_policy",
                    "cache_policy",
                    "scratch_dir",
                )
            }
            | (
                {
                    "operation": options.operation,
                    "recipes": [
                        {
                            "format": recipe.format,
                            "mode": recipe.mode,
                            "quality": recipe.quality,
                            "perceptual_target": recipe.perceptual_target,
                            "encoder": recipe.encoder,
                            "effort": recipe.effort,
                        }
                        for recipe in options.recipes
                    ],
                    "filters": list(options.filters),
                    "sample": options.sample,
                    "seed": options.seed,
                    "plan_id": options.plan_id,
                    "max_images": options.max_images,
                    "max_new_encodes": options.max_trials,
                    "max_runtime_seconds": options.max_time_seconds,
                    "accuracy_pp": options.accuracy_pp,
                    "allow_larger": options.allow_larger,
                }
                if options
                else {}
            ),
            operation=self.operation,
        )
        self.finished = False
        self.report_error = False
        self.failure = ""
        self.last_report = None
        self.artifacts = {}

    def save(self, report, *, final=True):
        from . import markdown_report

        self.last_report = report
        self.finished = final
        try:
            artifacts = markdown_report.publish_markdown_report(self.workspace, report)
            self.artifacts = artifacts.as_dict()
            if self.args.json and final:
                self.print_artifacts()
        except (OSError, ValueError, RuntimeError) as exc:
            self.report_error = True
            self.artifacts = {"error": str(exc), "directory": str(self.workspace.reports_dir)}
            caution = (
                " Source images may already have been modified; inspect results before rerunning writes."
                if self.args.write
                else ""
            )
            print(f"Report could not be saved to {self.workspace.reports_dir}: {exc}.{caution}", file=sys.stderr)
        return dict(self.artifacts)

    def print_artifacts(self):
        if "archive" in self.artifacts:
            print(
                f"Report saved: {reporting.clean(self.artifacts['archive'])}\nLatest report: {reporting.clean(self.artifacts['latest'])}",
                file=sys.stderr,
                flush=True,
            )

    def render(self, report):
        print(
            reporting.render_console_report(
                report,
                width=shutil.get_terminal_size().columns,
                color=reporting.stdout_color_enabled(),
                verbose=bool(self.args.verbose),
            ),
            flush=True,
        )
        self.print_artifacts()

    def comparison(self, rows, *, snapshot, cache):
        self.context = replace(
            self.context, sampling=rows[0].sampling if rows else {}, snapshot=dict(snapshot), cache=dict(cache)
        )
        report = reporting.build_comparison_report(rows, context=self.context)
        artifacts = self.save(report)
        return report, artifacts

    def analysis(self, result, plan, strategy, *, snapshot, cache):
        from .extrapolation import extrapolate_target

        population = [i for group in plan.groups.values() for i in group]
        extrapolation = extrapolate_target(
            population, plan.images, result.results, complete=result.processed_images == len(plan.images)
        )
        self.context = replace(
            self.context,
            sampling=plan.summary(),
            snapshot=dict(snapshot),
            cache=dict(cache),
            settings={
                **self.context.settings,
                **asdict(strategy),
                "write": self.args.write,
                "extrapolation": extrapolation,
            },
        )
        report = reporting.build_analysis_report(result, context=self.context)
        artifacts = self.save(report)
        return report, artifacts, extrapolation

    def inventory(self, payload, *, implicit=False):
        report = reporting.build_inventory_report(payload, context=self.context)
        return self.save(report, final=not implicit)

    def plan(self, plan, *, population_count):
        report = reporting.build_plan_report(plan, population_count=population_count, context=self.context)
        artifacts = self.save(report)
        if not self.args.json:
            self.render(report)
        return report, artifacts

    def finish(self, status):
        if not self.finished:
            label = "cancelled" if status == 130 else "failed" if status else "completed"
            rows = [
                ["Status code", str(status)],
                ["Detail", self.failure or "No final operation result was produced."],
                [
                    "Observations",
                    "No complete comparison/analysis result; do not treat this report as a completed census.",
                ],
            ]
            report = CompressionReport(
                "PARTIAL COMPRESSION REPORT",
                self.operation,
                label,
                str(self.workspace.target),
                tuple(reporting._context_sections(replace(self.context, status=label)))
                + (reporting.section("PARTIAL / FAILURE DETAILS", ("Metric", "Value"), rows),),
            )
            self.save(report)
            if not self.args.json:
                self.print_artifacts()
        return 2 if status == 0 and self.report_error else status


def start_session(args):
    session = ReportSession(args)
    _current.set(session)
    return session


def report_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _current.set(None)
        try:
            status = function(*args, **kwargs)
            session = current_session()
            return session.finish(status) if session else status
        except BaseException as exc:
            session = current_session()
            if session:
                session.failure = str(exc)
                session.finish(130 if isinstance(exc, KeyboardInterrupt) else 2)
            raise
        finally:
            _current.reset(token)

    return wrapped
