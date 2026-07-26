"""run_subagent tool — recursive agent invocation.

Each call creates a new AgentRun with ``parent_run_id`` linking back. Depth
is tracked on the ToolContext (set by the runtime before calling the tool).
The plan caps nesting at depth 2 to prevent runaway recursion.
"""
from __future__ import annotations

from typing import Any

from app.agent.tools.base import Tool, ToolContext, ToolResult


# Per plan: max sub-agent depth = 2 (Manager → DEV → cannot go further)
MAX_SUBAGENT_DEPTH = 2


class RunSubagentTool(Tool):
    """Spawn a child agent with a narrower role and a step cap."""

    def __init__(self) -> None:
        super().__init__(
            name="run_subagent",
            description=(
                "Spawn a sub-agent with a specified role to handle a sub-task. "
                f"Max nesting depth is {MAX_SUBAGENT_DEPTH}. The sub-agent runs "
                "in the same work_dir with the same allowed_paths. Returns the "
                "sub-agent's final summary."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Task for the sub-agent"},
                    "role": {
                        "type": "string",
                        "enum": ["MGR", "ANL", "DEV_FE", "DEV_BE", "QA", "PM", "SUP"],
                        "default": "DEV",
                    },
                    "max_steps": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
                },
                "required": ["prompt"],
            },
            handler=self._run,
            is_mutating=False,  # the sub-agent has its own run record
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        # Depth check — the runtime injects current depth into ToolContext.metadata
        # or a known attribute. For Phase 2, we expose a contract: ctx.metadata["depth"].
        depth = getattr(ctx, "metadata", {}).get("depth", 0) if hasattr(ctx, "metadata") else 0
        if depth >= MAX_SUBAGENT_DEPTH:
            return ToolResult(
                ok=False,
                error=f"Sub-agent depth {depth} exceeds limit {MAX_SUBAGENT_DEPTH}",
            )

        # The actual sub-agent invocation is the runtime's job (it needs DB
        # access to create the new Conversation + AgentRun). This tool returns
        # a request envelope that the runtime can pick up.
        return ToolResult(
            ok=True,
            output=(
                f"Sub-agent requested: role={args.get('role', 'DEV')}, "
                f"max_steps={args.get('max_steps', 15)}, "
                f"prompt={args.get('prompt', '')[:100]!r}"
            ),
            metadata={
                "subagent_request": True,
                "prompt": args["prompt"],
                "role": args.get("role", "DEV"),
                "max_steps": args.get("max_steps", 15),
                "parent_run_id": str(ctx.agent_run_id),
            },
        )
