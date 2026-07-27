"""DAG definition + template resolver tests."""
import pytest
from pydantic import ValidationError

from app.workflow.definition import (
    ProcessDefinition,
    TemplateError,
    resolve_template,
)


def _make_def(**overrides) -> ProcessDefinition:
    base = {
        "name": "test",
        "steps": [
            {"name": "analyze", "role": "ANL", "prompt": "analyze {{input.x}}"},
            {"name": "fix", "role": "DEV_BE", "prompt": "fix {{steps.analyze.outputs.summary}}"},
        ],
        "edges": [{"from": "analyze", "to": "fix"}],
    }
    base.update(overrides)
    return ProcessDefinition(**base)


def test_valid_dag():
    d = _make_def()
    assert d.name == "test"
    assert len(d.steps) == 2


def test_duplicate_step_names_rejected():
    with pytest.raises(ValidationError):
        _make_def(steps=[
            {"name": "x", "role": "ANL", "prompt": "p"},
            {"name": "x", "role": "DEV_BE", "prompt": "p"},
        ])


def test_edge_to_unknown_step_rejected():
    with pytest.raises(ValidationError):
        _make_def(edges=[{"from": "analyze", "to": "ghost"}])


def test_edge_from_unknown_step_rejected():
    with pytest.raises(ValidationError):
        _make_def(edges=[{"from": "ghost", "to": "fix"}])


def test_cycle_detected():
    """A → B → A is a cycle."""
    with pytest.raises(ValidationError):
        ProcessDefinition(
            name="cyclic",
            steps=[
                {"name": "a", "role": "ANL", "prompt": "p"},
                {"name": "b", "role": "DEV_BE", "prompt": "p"},
            ],
            edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        )


def test_self_loop_detected():
    with pytest.raises(ValidationError):
        ProcessDefinition(
            name="self",
            steps=[{"name": "a", "role": "ANL", "prompt": "p"}],
            edges=[{"from": "a", "to": "a"}],
        )


def test_root_steps():
    d = _make_def()
    roots = d.root_steps()
    assert [s.name for s in roots] == ["analyze"]


def test_multiple_roots():
    d = ProcessDefinition(
        name="multi",
        steps=[
            {"name": "a", "role": "ANL", "prompt": "p"},
            {"name": "b", "role": "ANL", "prompt": "p"},
            {"name": "c", "role": "DEV_BE", "prompt": "p"},
        ],
        edges=[{"from": "a", "to": "c"}, {"from": "b", "to": "c"}],
    )
    assert sorted(s.name for s in d.root_steps()) == ["a", "b"]


def test_upstream_downstream():
    d = _make_def()
    assert d.upstream("fix") == ["analyze"]
    assert d.downstream("analyze") == ["fix"]


# -------------------- Template resolver --------------------


def test_resolve_input_variable():
    out = resolve_template("Bug: {{input.bug_id}}", {"bug_id": "BUG-123"}, {})
    assert out == "Bug: BUG-123"


def test_resolve_step_output():
    out = resolve_template(
        "Summary: {{steps.analyze.outputs.summary}}",
        {},
        {"analyze": {"summary": "it's a null pointer"}},
    )
    assert out == "Summary: it's a null pointer"


def test_resolve_nested_output():
    out = resolve_template(
        "{{steps.analyze.outputs.details.root_cause}}",
        {},
        {"analyze": {"details": {"root_cause": "missing await"}}},
    )
    assert out == "missing await"


def test_resolve_mixed():
    out = resolve_template(
        "Fix {{input.bug_id}} (cause: {{steps.analyze.outputs.summary}})",
        {"bug_id": "BUG-1"},
        {"analyze": {"summary": "race"}},
    )
    assert out == "Fix BUG-1 (cause: race)"


def test_resolve_unresolved_input_raises():
    with pytest.raises(TemplateError):
        resolve_template("{{input.missing}}", {}, {})


def test_resolve_unresolved_step_raises():
    with pytest.raises(TemplateError):
        resolve_template("{{steps.ghost.outputs.x}}", {}, {})


def test_resolve_bad_template_root_raises():
    with pytest.raises(TemplateError):
        resolve_template("{{env.PATH}}", {}, {})


def test_resolve_text_without_templates_unchanged():
    out = resolve_template("hello world", {}, {})
    assert out == "hello world"
