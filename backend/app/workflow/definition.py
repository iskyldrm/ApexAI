"""Process definition — DAG validation and step template resolution.

A Process is defined as:

    {
        "name": "Bug fix",
        "steps": [
            {"name": "analyze", "role": "ANL", "prompt": "Find the bug: {{input.bug_id}}"},
            {"name": "fix",     "role": "DEV_BE", "prompt": "Fix: {{steps.analyze.outputs.summary}}"}
        ],
        "edges": [{"from": "analyze", "to": "fix"}]
    }

Validation:
- All step names unique
- All edges reference valid step names
- DAG has no cycles
- All step names are non-empty

Template resolution:
- {{input.X}}     → process.inputs.X
- {{steps.S.outputs.Y}}  → upstream step's outputs.Y
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from pydantic import BaseModel, Field, model_validator


class StepDef(BaseModel):
    """One step in a process DAG."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z_][a-z0-9_]*$")
    role: str = Field(min_length=1, max_length=16)
    prompt: str = Field(min_length=1, max_length=32_000)
    max_attempts: int | None = Field(default=None, ge=1, le=20)


class EdgeDef(BaseModel):
    """Directed edge in the DAG."""

    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)

    model_config = {"populate_by_name": True}


class ProcessDefinition(BaseModel):
    """Full process definition with validation."""

    name: str = Field(min_length=1, max_length=255)
    steps: list[StepDef] = Field(min_length=1, max_length=50)
    edges: list[EdgeDef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_dag(self) -> "ProcessDefinition":
        names = {s.name for s in self.steps}
        if len(names) != len(self.steps):
            raise ValueError("Step names must be unique within a process")

        for edge in self.edges:
            if edge.from_ not in names:
                raise ValueError(f"Edge references unknown step: {edge.from_!r}")
            if edge.to not in names:
                raise ValueError(f"Edge references unknown step: {edge.to!r}")

        # Cycle detection via Kahn's algorithm
        in_degree: dict[str, int] = {n: 0 for n in names}
        adj: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            adj[edge.from_].append(edge.to)
            in_degree[edge.to] += 1

        queue = deque([n for n, d in in_degree.items() if d == 0])
        visited = 0
        while queue:
            n = queue.popleft()
            visited += 1
            for m in adj[n]:
                in_degree[m] -= 1
                if in_degree[m] == 0:
                    queue.append(m)
        if visited != len(names):
            raise ValueError("Process definition contains a cycle")

        return self

    def root_steps(self) -> list[StepDef]:
        """Steps with no incoming edge (start of a chain)."""
        incoming = {edge.to for edge in self.edges}
        return [s for s in self.steps if s.name not in incoming]

    def downstream(self, step_name: str) -> list[str]:
        """Names of steps that directly depend on ``step_name``."""
        return [edge.to for edge in self.edges if edge.from_ == step_name]

    def upstream(self, step_name: str) -> list[str]:
        """Names of steps that ``step_name`` depends on."""
        return [edge.from_ for edge in self.edges if edge.to == step_name]

    def step_by_name(self, name: str) -> StepDef | None:
        for s in self.steps:
            if s.name == name:
                return s
        return None


# ---------------------------------------------------------------------------
# Step template resolver
# ---------------------------------------------------------------------------


_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}")


class TemplateError(ValueError):
    """Raised when a template variable cannot be resolved."""


def resolve_template(
    template: str,
    process_inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
) -> str:
    """Expand ``{{input.X}}`` and ``{{steps.NAME.outputs.X}}`` in a string.

    ``step_outputs`` maps step_name → outputs dict. The ``outputs.`` prefix
    in the template is the conventional namespace; we skip it when digging
    into the step's outputs dict.
    """
    def repl(m: re.Match[str]) -> str:
        path = m.group(1)
        parts = path.split(".")
        if parts[0] == "input":
            value = _dig(process_inputs, parts[1:])
        elif parts[0] == "steps":
            if len(parts) < 3:
                raise TemplateError(f"Bad template path: {path!r}")
            step_name = parts[1]
            if step_name not in step_outputs:
                raise TemplateError(f"Step {step_name!r} not yet executed")
            # Skip the "outputs" namespace token
            sub_path = parts[2:]
            if sub_path and sub_path[0] == "outputs":
                sub_path = sub_path[1:]
            value = _dig(step_outputs[step_name], sub_path)
        else:
            raise TemplateError(f"Unknown template root: {parts[0]!r}")
        if value is None:
            raise TemplateError(f"Template variable {path!r} is null")
        return str(value)

    return _TEMPLATE_RE.sub(repl, template)


def _dig(d: dict[str, Any], path: list[str]) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise TemplateError(f"Path {path!r} not found")
        cur = cur[key]
    return cur
