"""Placement classification for agent_memory notes."""

import logging
import re
import sys

from agent_memory.note import GLOBAL_DEFAULT_KINDS, LLM_CLASSIFY_KINDS, PROJECT_REQUIRED_KINDS

try:
    from llm_local import complete as _llm_complete
except ImportError:
    _llm_complete = None

logger = logging.getLogger(__name__)


class PlacementError(ValueError):
    """Raised when note placement cannot be determined."""


def determine_project(
    *,
    kind: str,
    project: str | None,
    title: str,
    auto_classify: bool,
    interactive: bool = True,
    body: str = "",
) -> str:
    """Return the project slug or 'global' for a note."""
    if project is not None:
        return project

    if kind in GLOBAL_DEFAULT_KINDS:
        return "global"

    if kind in PROJECT_REQUIRED_KINDS:
        raise PlacementError(f"Kind '{kind}' requires a project. Pass --project <slug>.")

    if kind not in LLM_CLASSIFY_KINDS or not auto_classify:
        return "global"

    result = _classify_via_llm(kind=kind, title=title, body=body)
    if result is not None:
        logger.info("Classified as: %s (via local LLM). Use --project to override.", result)
        return result

    if interactive and sys.stdin.isatty():
        return _classify_interactively(kind=kind, title=title)

    logger.warning("LLM unreachable and no TTY; defaulting to 'global'. Use --project to override.")
    return "global"


def classify_placement(*, kind: str, title: str, body: str, known_projects: list[str]) -> str | None:
    """Compatibility wrapper for the Plan-2 stub API."""
    del known_projects
    return _classify_via_llm(kind=kind, title=title, body=body)


def _classify_via_llm(*, kind: str, title: str, body: str) -> str | None:
    if _llm_complete is None:
        logger.debug("llm_local not installed; skipping LLM classification")
        return None

    prompt = (
        "A memory note is being saved. Determine whether it belongs in the 'global' "
        "scope (cross-project, always applicable) or a specific project (only relevant "
        "to one project).\n\n"
        f"Kind: {kind}\n"
        f"Title: {title}\n"
        f"Body excerpt: {body[:300]}\n\n"
        "Respond with only one of:\n"
        "- 'global' if this note applies across all projects\n"
        "- '<project-slug>' if this note is specific to one project\n\n"
        "Response:"
    )

    raw = _llm_complete(prompt, timeout=5.0)
    if raw is None:
        return None

    cleaned = raw.strip().lower().strip("'\"")
    if not cleaned or len(cleaned) > 80 or not _is_valid_project_slug(cleaned):
        logger.debug("LLM returned unusable placement: %r", raw)
        return None

    return cleaned


def _is_valid_project_slug(value: str) -> bool:
    return value == "global" or bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value))


def _classify_interactively(*, kind: str, title: str) -> str:
    print(f"\nCannot auto-classify '{kind}' note: '{title}'")
    print("Where should this note live?")
    print("  [g] global  (cross-project, always applicable)")
    print("  [p] project (enter project slug)")

    while True:
        choice = input("Choice [g/p]: ").strip().lower()
        if choice in ("g", "global"):
            return "global"
        if choice in ("p", "project"):
            slug = input("Project slug: ").strip()
            if slug:
                return slug
            print("Project slug cannot be empty.")
        else:
            print("Please enter 'g' or 'p'.")
