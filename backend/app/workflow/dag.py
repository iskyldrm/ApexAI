"""DAG validation for process definitions.

Used by:
- The /processes POST endpoint to reject cycles + duplicate node names
  before persisting.
- The visual DAG editor (frontend) to validate the user's drag-drop
  design before save.

Algorithm: Kahn's algorithm for topological sort — if we can't sort all
nodes, there's a cycle.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


class DAGValidationError(ValueError):
    """Raised when a process definition is not a valid DAG."""


def validate_dag(definition: dict[str, Any]) -> dict[str, Any]:
    """Validate a process definition. Returns the (possibly normalized) dict.

    Expected shape:
        {
            "steps": [{"name": "...", "role": "...", "prompt": "..."}, ...],
            "edges": [{"from": "step_name_a", "to": "step_name_b"}, ...],
        }

    Checks:
    - All step names are non-empty + unique
    - All edge endpoints reference existing step names
    - No self-loops
    - No cycles (Kahn's algorithm)
    """
    steps = definition.get("steps", []) or []
    edges = definition.get("edges", []) or []

    # Validate step names
    step_names: list[str] = []
    seen_names: set[str] = set()
    for step in steps:
        name = step.get("name", "").strip()
        if not name:
            raise DAGValidationError("Step with empty name")
        if name in seen_names:
            raise DAGValidationError(f"Duplicate step name: {name!r}")
        seen_names.add(name)
        step_names.append(name)

    # Validate edges (normalize "from_" → "from" for Pydantic alias compat)
    name_set = set(step_names)
    normalized_edges: list[dict[str, str]] = []
    for edge in edges:
        src = edge.get("from") or edge.get("from_")
        dst = edge.get("to")
        if not src or not dst:
            raise DAGValidationError(f"Edge missing from/to: {edge!r}")
        if src not in name_set:
            raise DAGValidationError(f"Edge references unknown step: {src!r}")
        if dst not in name_set:
            raise DAGValidationError(f"Edge references unknown step: {dst!r}")
        if src == dst:
            raise DAGValidationError(f"Self-loop on step: {src!r}")
        normalized_edges.append({"from": src, "to": dst})

    # Kahn's algorithm — count in-degree + topological sort
    in_degree: dict[str, int] = {name: 0 for name in step_names}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in normalized_edges:
        in_degree[edge["to"]] += 1
        adjacency[edge["from"]].append(edge["to"])

    # Start with nodes that have no incoming edges
    queue: deque[str] = deque(
        name for name, deg in in_degree.items() if deg == 0
    )
    visited_order: list[str] = []
    while queue:
        node = queue.popleft()
        visited_order.append(node)
        for nxt in adjacency[node]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(visited_order) != len(step_names):
        # Find the cycle nodes (those still with in_degree > 0)
        cycle = [name for name, d in in_degree.items() if d > 0]
        raise DAGValidationError(
            f"Cycle detected involving steps: {sorted(cycle)}"
        )

    return {
        "steps": steps,
        "edges": normalized_edges,
        "topological_order": visited_order,
        "is_dag": True,
    }


def find_root_steps(definition: dict[str, Any]) -> list[str]:
    """Return the names of steps with no incoming edges (entry points)."""
    steps = definition.get("steps", []) or []
    edges = definition.get("edges", []) or []
    has_incoming: set[str] = set()
    for edge in edges:
        dst = edge.get("to")
        if dst:
            has_incoming.add(dst)
    return [
        step["name"] for step in steps
        if step.get("name") and step["name"] not in has_incoming
    ]