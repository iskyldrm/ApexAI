"""ask_user tool — pause the agent loop to ask the user a question.

The runtime injects an ``answer_provider`` callable into the tool. The
provider typically:
- in a streaming SSE API, sends a question event and waits for the user's reply
- in a one-shot API, returns a default answer (or raises to abort)
- in tests, returns a canned value

The returned ToolResult carries the answer (when available) so the agent
loop can continue with the chosen path.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from app.agent.tools.base import Tool, ToolContext, ToolResult

AnswerProvider = Callable[[str, list[str] | None], Awaitable[str | None]]


class AskUserTool(Tool):
    """Ask the user a clarifying question with optional multiple choice."""

    def __init__(self, answer_provider: AnswerProvider | None = None) -> None:
        super().__init__(
            name="ask_user",
            description=(
                "Pause execution and ask the user a clarifying question. Provide "
                "a list of options for multiple choice, or omit for free-text input. "
                "Returns the user's choice. Use sparingly — the agent should be "
                "able to make reasonable defaults without asking."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Multiple-choice options (omit for free-text)",
                    },
                    "allow_free_text": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether the user can type a custom answer",
                    },
                },
                "required": ["question"],
            },
            handler=self._run,
            is_mutating=False,
            required_permissions=("user_input:read",),
        )
        self._answer_provider = answer_provider

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        question: str = args["question"]
        options: list[str] | None = args.get("options")

        if self._answer_provider is None:
            # No provider — return a 'pending' envelope. The runtime is expected
            # to either inject an answer (resume) or treat this as a stop condition.
            return ToolResult(
                ok=True,
                output=f"Question pending: {question!r}",
                metadata={
                    "status": "pending",
                    "question": question,
                    "options": options,
                    "allow_free_text": args.get("allow_free_text", True),
                },
            )

        try:
            answer = await self._answer_provider(question, options)
        except Exception as e:
            return ToolResult(ok=False, error=f"answer provider failed: {e}")

        if answer is None:
            return ToolResult(
                ok=False,
                error="User did not provide an answer (cancelled or timed out)",
                metadata={"status": "cancelled", "question": question},
            )

        return ToolResult(
            ok=True,
            output=f"User chose: {answer}",
            metadata={
                "status": "answered",
                "question": question,
                "options": options,
                "answer": answer,
            },
        )
