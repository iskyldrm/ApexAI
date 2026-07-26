"""Conversation memory — append, fetch, trim, summarize.

Works in two layers:
- ``Message`` dataclass: in-memory shape used by tests and the LLM loop.
- ``ConversationStore``: SQLAlchemy-backed persistence to ``conversation_messages``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import ConversationMessage


@dataclass
class Message:
    """One chat message in plain-Python form."""

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    def to_llm_dict(self) -> dict[str, Any]:
        """Format for OpenAI/Anthropic-style APIs."""
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        if self.tool_name:
            out["name"] = self.tool_name
        return out


# ---------------------------------------------------------------------------
# Trimming + summarization helpers (pure functions, no DB)
# ---------------------------------------------------------------------------

_FILE_PATH_RE = re.compile(r"`?([\w./\-]+\.\w{1,8})`?")
_DECISION_RE = re.compile(
    r"\b(I['']ll use|let['']s use|decided to|we['']ll use|using)\b[^.]{0,80}",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(r"\b(error|failed|exception|traceback)\b[^.]{0,80}", re.IGNORECASE)


def trim(messages: list[Message], max_messages: int = 30) -> list[Message]:
    """Keep the system message (if any) + the most recent N messages.

    Follows the ApexAITeam pattern: drop middle, keep recent + summary.
    """
    if len(messages) <= max_messages:
        return list(messages)
    system = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]
    kept = non_system[-max_messages:]
    return system + kept


def extractive_summary(messages: Iterable[Message]) -> dict[str, Any]:
    """Cheap rule-based summary — used when messages exceed threshold.

    Returns dict with files read/written, decisions, errors. No LLM call.
    """
    files_read: set[str] = set()
    files_written: set[str] = set()
    decisions: list[str] = []
    errors: list[str] = []

    for m in messages:
        if m.role == "tool":
            path_match = _FILE_PATH_RE.search(m.content)
            if path_match:
                files_read.add(path_match.group(1))
        if m.tool_calls:
            for tc in m.tool_calls:
                name = tc.get("name")
                args = tc.get("arguments", {})
                if name in {"write_file", "edit_file"} and "path" in args:
                    files_written.add(args["path"])
                if name == "read_file" and "path" in args:
                    files_read.add(args["path"])
        for match in _DECISION_RE.finditer(m.content):
            decisions.append(match.group(0).strip())
        for match in _ERROR_RE.finditer(m.content):
            errors.append(match.group(0).strip())

    return {
        "files_read": sorted(files_read),
        "files_written": sorted(files_written),
        "decisions": decisions[:10],
        "errors": errors[:10],
    }


def maybe_summarize(messages: list[Message], threshold: int = 50) -> list[Message]:
    """If messages > threshold, replace oldest with a summary message."""
    if len(messages) <= threshold:
        return messages
    system = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]
    head, tail = non_system[: threshold // 2], non_system[threshold // 2 :]
    summary_dict = extractive_summary(head)
    summary_text = (
        f"[Summary of {len(head)} prior messages] "
        f"files_read={summary_dict['files_read']} "
        f"files_written={summary_dict['files_written']}"
    )
    summary_msg = Message(role="system", content=summary_text)
    return system + [summary_msg] + tail


# ---------------------------------------------------------------------------
# DB-backed persistence
# ---------------------------------------------------------------------------


class ConversationStore:
    """Async wrapper around `conversation_messages` table."""

    def __init__(self, session: AsyncSession, conversation_id: UUID) -> None:
        self.session = session
        self.conversation_id = conversation_id

    async def append(self, message: Message, sequence: int) -> ConversationMessage:
        row = ConversationMessage(
            conversation_id=self.conversation_id,
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_result=None,
            tool_name=message.tool_name,
            tool_call_id=message.tool_call_id,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            parent_message_id=message.parent_id,
            sequence=sequence,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_messages(self) -> list[Message]:
        result = await self.session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == self.conversation_id)
            .order_by(ConversationMessage.sequence)
        )
        rows = result.scalars().all()
        return [
            Message(
                role=r.role,
                content=r.content,
                tool_calls=r.tool_calls,
                tool_call_id=r.tool_call_id,
                tool_name=r.tool_name,
                id=r.id,
                parent_id=r.parent_message_id,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
            )
            for r in rows
        ]
