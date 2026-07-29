from __future__ import annotations

import json

import pytest

from development_ledger.plan import (
    END_MARKER,
    START_MARKER,
    PlanValidationError,
    load_plan,
    parse_plan_text,
    render_plan_template,
)


def test_load_plan_parses_items_and_manual_checks(plan_path):
    plan = load_plan(plan_path)

    assert plan.plan_id == "demo-plan"
    assert [item.id for item in plan.items] == ["AC-001", "AC-002"]
    assert plan.manual_checks[0].id == "MC-001"


def test_parse_plan_rejects_missing_markers():
    with pytest.raises(PlanValidationError, match="No development-ledger state block"):
        parse_plan_text("# Plain plan")


def test_parse_plan_rejects_duplicate_item_ids(plan_data):
    plan_data["items"].append(dict(plan_data["items"][0]))
    text = f"{START_MARKER}\n```json\n{json.dumps(plan_data)}\n```\n{END_MARKER}"

    with pytest.raises(PlanValidationError, match="Duplicate plan item ID"):
        parse_plan_text(text)


def test_parse_plan_rejects_unknown_manual_check_reference(plan_data):
    plan_data["items"][0]["manual_checks"] = ["MC-999"]
    text = f"{START_MARKER}\n```json\n{json.dumps(plan_data)}\n```\n{END_MARKER}"

    with pytest.raises(PlanValidationError, match="unknown manual-check IDs"):
        parse_plan_text(text)


def test_render_plan_template_round_trips():
    text = render_plan_template(plan_id="p1", title="Plan One", project_root="modules/one")

    plan = parse_plan_text(text)
    assert plan.plan_id == "p1"
    assert plan.items[0].id == "AC-001"


def test_plan_rejects_invalid_implementation_state(plan_data):
    plan_data["items"][0]["implementation"] = "done-ish"
    text = f"{START_MARKER}\n```json\n{json.dumps(plan_data)}\n```\n{END_MARKER}"

    with pytest.raises(PlanValidationError, match="Invalid implementation state"):
        parse_plan_text(text)


def test_plan_rejects_manual_check_unknown_item(plan_data):
    plan_data["manual_checks"][0]["item_ids"] = ["AC-999"]
    text = f"{START_MARKER}\n```json\n{json.dumps(plan_data)}\n```\n{END_MARKER}"

    with pytest.raises(PlanValidationError, match="references unknown item IDs"):
        parse_plan_text(text)
