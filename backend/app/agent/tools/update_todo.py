"""update_todo tool — create or update a todo item in the agent's checklist.

Todos live in the ``agent_todos`` table, scoped to the current agent_run_id
(injected via ToolContext). The agent uses this to track its plan across
many steps and surface progress in the UI.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_todo import AgentTodo
from app.agent.tools.base import Tool, ToolContext, ToolResult


_VALID_STATUSES = ("pending", "in_progress", "done", "skipped", "failed")


class UpdateTodoTool(Tool):
    """Create or update a todo item for the current agent run."""

    def __init__(self) -> None:
        super().__init__(
            name="update_todo",
            description=(
                "Create or update a todo in the current run's checklist. "
                "Pass `id` to update an existing todo, or omit it to create. "
                "Use list_todos to see the current plan."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Existing todo UUID (omit to create)"},
                    "title": {"type": "string", "description": "Short title (required for create)"},
                    "status": {
                        "type": "string",
                        "enum": list(_VALID_STATUSES),
                        "default": "pending",
                    },
                    "notes": {"type": "string"},
                },
            },
            handler=self._run,
            is_mutating=True,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        status = args.get("status", "pending")
        if status not in _VALID_STATUSES:
            return ToolResult(ok=False, error=f"Invalid status: {status!r}")

        # Get a session from the context (the runtime injects one)
        session: AsyncSession | None = getattr(ctx, "db_session", None)
        if session is None:
            return ToolResult(ok=False, error="update_todo requires DB session in context")

        existing_id = args.get("id")
        if existing_id:
            try:
                todo = await session.get(AgentTodo, uuid.UUID(existing_id))
            except ValueError:
                return ToolResult(ok=False, error=f"Invalid UUID: {existing_id}")
            if not todo or str(todo.agent_run_id) != str(ctx.agent_run_id):
                return ToolResult(ok=False, error="Todo not found in current run")
            todo.status = status
            if "title" in args:
                todo.title = args["title"]
            if "notes" in args:
                todo.notes = args["notes"]
            await session.commit()
            return ToolResult(ok=True, output=f"Updated todo {existing_id} → {status}", metadata={"id": existing_id, "status": status})

        # Create
        title = args.get("title")
        if not title:
            return ToolResult(ok=False, error="title is required to create a todo")

        # Next sequence number
        result = await session.execute(
            select(AgentTodo)
            .where(AgentTodo.agent_run_id == str(ctx.agent_run_id))
            .order_by(AgentTodo.sequence.desc())
        )
        last = result.scalars().first()
        next_seq = (last.sequence + 1) if last else 0

        todo = AgentTodo(
            agent_run_id=str(ctx.agent_run_id),
            sequence=next_seq,
            title=title,
            status=status,
            notes=args.get("notes"),
        )
        session.add(todo)
        await session.commit()
        await session.refresh(todo)
        return ToolResult(
            ok=True,
            output=f"Created todo {todo.id} [{status}] {title}",
            metadata={"id": str(todo.id), "status": status, "sequence": next_seq},
        )
