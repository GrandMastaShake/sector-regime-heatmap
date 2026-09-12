"""Every workflow file must parse, and declare the triggers it claims.

The sibling repo shipped an invalid workflow: one unquoted description put a
bare ": " inside a scalar, YAML read it as a nested mapping, and the file
would not parse at all. GitHub still LISTED the workflow as active, so
`gh workflow list` looked fine; the triggers were simply never registered. A
manual dispatch was rejected and the cron would have silently never fired.

Nothing caught it, because CI reads the code and the artifacts but never the
workflow files. This does. daily-tape.yml here was written in the same sitting
and is the reason this guard is mirrored rather than left upstream.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def triggers(doc):
    """The `on:` block.

    YAML 1.1 resolves a bare `on` to the boolean True, so the key is not the
    string "on" -- the single most common way an Actions file is misread by
    tooling that checks it.
    """
    if "on" in doc:
        return doc["on"]
    return doc.get(True)


def test_there_are_workflows_to_check():
    assert WORKFLOWS, "no workflow files found; this test would vacuously pass"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses(path):
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        pytest.fail(path.name + " is not valid YAML, so GitHub cannot read "
                    "its triggers: " + str(exc))
    assert isinstance(doc, dict), path.name + " is not a mapping"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_declares_triggers_and_jobs(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    trig = triggers(doc)
    assert trig, (path.name + " declares no `on:` triggers. A workflow with "
                  "none is registered and never runs.")
    assert doc.get("jobs"), path.name + " declares no jobs"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_scheduled_workflows_are_dispatchable(path):
    """A cron you cannot fire by hand is a cron you cannot test."""
    trig = triggers(yaml.safe_load(path.read_text(encoding="utf-8")))
    if "schedule" not in trig:
        pytest.skip("not scheduled")
    assert "workflow_dispatch" in trig, (
        path.name + " runs on a schedule but cannot be dispatched manually")


def test_daily_tape_is_dispatchable():
    path = ROOT / ".github" / "workflows" / "daily-tape.yml"
    trig = triggers(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert "schedule" in trig
    assert "workflow_dispatch" in trig


def test_the_forecast_schedules_stay_disabled():
    """premarket and after-close must not acquire a cron until the runbook's
    10 manual cycles are done. A schedule appearing here is the gate being
    bypassed by edit rather than by decision."""
    for name in ("premarket.yml", "after-close.yml"):
        path = ROOT / ".github" / "workflows" / name
        trig = triggers(yaml.safe_load(path.read_text(encoding="utf-8")))
        assert "schedule" not in trig, (
            name + " has acquired a schedule. The runbook wants 10 manual "
            "cycles first; see docs/manual_runbook.md.")


def test_pytest_is_scoped_to_this_repo():
    """Two workflows check weekly-council-scan out into upstream/ and then
    run pytest from the root. Without testpaths, collection walks into that
    repo's suite -- wrong deps, wrong fixtures, meaningless signal -- and the
    daily-tape job failed its first real run on exactly that."""
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(ROOT / "pytest.ini", encoding="utf-8")
    assert cfg.has_section("pytest"), "pytest.ini has no [pytest] section"
    assert cfg.get("pytest", "testpaths").split() == ["tests"]
    assert "upstream" in cfg.get("pytest", "norecursedirs").split()
