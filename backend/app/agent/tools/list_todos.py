"""list_todos tool — return the current run's checklist."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_todo import AgentTodo
from app.agent.tools.base import Tool, ToolContext, ToolResult


class ListTodosTool(Tool):
    """List the current agent run's todos."""

    def __init__(self) -> None:
        super().__init__(
            name="list_todos",
            description=(
                "List the current run's checklist. Returns todos in sequence order "
                "with their status: [pending] / [in_progress] / [done] / [skipped] / [failed]."
            ),
            parameters_schema={"type": "object", "properties": {}},
            handler=self._run,
            is_mutating=False,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        session: AsyncSession | None = getattr(ctx, "db_session", None)
        if session is None:
            return ToolResult(ok=False, error="list_todos requires DB session in context")

        result = await session.execute(
            select(AgentTodo)
            .where(AgentTodo.agent_run_id == str(ctx.agent_run_id))
            .order_by(AgentTodo.sequence)
        )
        todos = result.scalars().all()
        if not todos:
            return ToolResult(ok=True, output="(no todos yet)")
        lines = [f"[{t.status}] {t.sequence}. {t.title} ({t.id})" for t in todos]
        return ToolResult(ok=True, output="\n".join(lines))
