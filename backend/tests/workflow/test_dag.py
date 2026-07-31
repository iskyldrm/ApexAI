"""Tests for the DAG validator (B.8-B.11 visual DAG editor)."""
from __future__ import annotations

import pytest

from app.workflow.dag import DAGValidationError, find_root_steps, validate_dag


def test_validate_simple_dag():
    """A → B → C is a valid DAG."""
    result = validate_dag({
        "steps": [
            {"name": "a", "role": "DEV_BE", "prompt": "do A"},
            {"name": "b", "role": "QA", "prompt": "do B"},
            {"name": "c", "role": "MGR", "prompt": "do C"},
        ],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
        ],
    })
    assert result["is_dag"] is True
    assert result["topological_order"][0] == "a"
    assert result["topological_order"][-1] == "c"


def test_validate_dag_with_branches():
    """Diamond: A → B, A → C, B → D, C → D."""
    result = validate_dag({
        "steps": [
            {"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"},
        ],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "a", "to": "c"},
            {"from": "b", "to": "d"},
            {"from": "c", "to": "d"},
        ],
    })
    assert result["is_dag"] is True
    assert result["topological_order"][0] == "a"
    assert result["topological_order"][-1] == "d"


def test_validate_dag_no_edges():
    """Disconnected nodes (no edges) is still a valid DAG."""
    result = validate_dag({
        "steps": [{"name": "x"}, {"name": "y"}],
        "edges": [],
    })
    assert result["is_dag"] is True
    assert set(result["topological_order"]) == {"x", "y"}


def test_reject_cycle():
    """A → B → C → A is a cycle."""
    with pytest.raises(DAGValidationError, match="Cycle"):
        validate_dag({
            "steps": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"},
            ],
        })


def test_reject_self_loop():
    with pytest.raises(DAGValidationError, match="Self-loop"):
        validate_dag({
            "steps": [{"name": "a"}],
            "edges": [{"from": "a", "to": "a"}],
        })


def test_reject_duplicate_step_name():
    with pytest.raises(DAGValidationError, match="Duplicate"):
        validate_dag({
            "steps": [{"name": "a"}, {"name": "a"}],
            "edges": [],
        })


def test_reject_empty_step_name():
    with pytest.raises(DAGValidationError, match="empty name"):
        validate_dag({
            "steps": [{"name": "  "}],
            "edges": [],
        })


def test_reject_unknown_edge_endpoint():
    with pytest.raises(DAGValidationError, match="unknown step"):
        validate_dag({
            "steps": [{"name": "a"}],
            "edges": [{"from": "a", "to": "ghost"}],
        })


def test_reject_edge_with_missing_endpoint():
    with pytest.raises(DAGValidationError, match="missing"):
        validate_dag({
            "steps": [{"name": "a"}],
            "edges": [{"from": "a"}],
        })


def test_reject_cycle_with_two_nodes():
    """A → B → A."""
    with pytest.raises(DAGValidationError, match="Cycle"):
        validate_dag({
            "steps": [{"name": "a"}, {"name": "b"}],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},
            ],
        })


def test_find_root_steps():
    """find_root_steps returns nodes with no incoming edges."""
    definition = {
        "steps": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "a", "to": "c"},
        ],
    }
    roots = find_root_steps(definition)
    assert roots == ["a"]


def test_find_root_steps_multiple_roots():
    definition = {
        "steps": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        "edges": [
            {"from": "a", "to": "c"},
            {"from": "b", "to": "c"},
        ],
    }
    roots = find_root_steps(definition)
    assert set(roots) == {"a", "b"}


def test_find_root_steps_no_edges():
    """No edges → every step is a root."""
    definition = {
        "steps": [{"name": "a"}, {"name": "b"}],
        "edges": [],
    }
    roots = find_root_steps(definition)
    assert set(roots) == {"a", "b"}


def test_validate_dag_preserves_steps_and_edges():
    """validate_dag returns the original steps + edges unchanged."""
    definition = {
        "steps": [{"name": "a", "extra": "field"}],
        "edges": [{"from": "a", "to": "a"}],  # would fail self-loop
    }
    # Use a valid definition to test preservation
    definition = {
        "steps": [{"name": "a", "extra": "field"}],
        "edges": [],
    }
    result = validate_dag(definition)
    assert result["steps"] == [{"name": "a", "extra": "field"}]
    assert result["edges"] == []


def test_validate_dag_complex_topological_order():
    """Complex graph → topological order respects all edges."""
    definition = {
        "steps": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}, {"name": "e"}],
        "edges": [
            {"from": "a", "to": "c"},
            {"from": "b", "to": "c"},
            {"from": "c", "to": "d"},
            {"from": "c", "to": "e"},
            {"from": "d", "to": "e"},
        ],
    }
    result = validate_dag(definition)
    order = result["topological_order"]
    # c must come after both a and b
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("c")
    # d must come after c
    assert order.index("c") < order.index("d")
    # e must come after c and d
    assert order.index("c") < order.index("e")
    assert order.index("d") < order.index("e")


def test_validate_dag_accepts_from_alias():
    """Pydantic serializes 'from' as 'from_' (Python keyword); validator must accept either."""
    # When the schema is dumped with by_alias=False, key is "from_"
    result = validate_dag({
        "steps": [{"name": "a"}, {"name": "b"}],
        "edges": [{"from_": "a", "to": "b"}],
    })
    assert result["is_dag"] is True
    # The returned edges are normalized back to "from"
    assert result["edges"][0]["from"] == "a"


def test_validate_dag_handles_empty_steps():
    """No steps → empty DAG."""
    result = validate_dag({"steps": [], "edges": []})
    assert result["is_dag"] is True
    assert result["topological_order"] == []