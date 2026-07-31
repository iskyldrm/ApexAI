"""Conversation memory — append, fetch, trim, summarize, branch, export.

Works in two layers:
- ``Message`` dataclass: in-memory shape used by tests and the LLM loop.
- ``ConversationStore``: SQLAlchemy-backed persistence to ``conversation_messages``.

Phase 7 additions (Tasks 40-43):
- ``token_aware_trim``: trim by tiktoken count rather than message count
- ``extractive_summary`` (improved): captures file paths, decisions, errors,
  per-message tool calls — better than v1
- ``branch``: create a child message linked to a parent (for sub-agents)
- ``export_conversation``: dump full message tree to JSON
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import ConversationMessage


# Lazy-loaded tiktoken encoder (model-specific)
_ENCODER = None


def _get_encoder(model: str = "gpt-4o"):
    """Return a tiktoken encoder for the given model. Lazy import + cache."""
    global _ENCODER
    if _ENCODER is None:
        try:
            import tiktoken
            try:
                _ENCODER = tiktoken.encoding_for_model(model)
            except KeyError:
                _ENCODER = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            return None
    return _ENCODER


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Estimate token count. Falls back to 1 token / 4 chars if tiktoken unavailable."""
    enc = _get_encoder(model)
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text))


def count_message_tokens(messages: list["Message"], model: str = "gpt-4o") -> int:
    """Sum of token counts for a message list. Each message gets a 4-token overhead."""
    total = 0
    for m in messages:
        text = m.content
        if m.tool_calls:
            text += json.dumps(m.tool_calls, default=str)
        total += 4 + count_tokens(text, model)
    return total


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
    Also catches file paths mentioned in plain text (assistant messages
    saying "I'll read /tmp/foo.py" count toward files_read).
    """
    files_read: set[str] = set()
    files_written: set[str] = set()
    decisions: list[str] = []
    errors: list[str] = []

    for m in messages:
        # Paths from tool messages
        if m.role == "tool":
            for path_match in _FILE_PATH_RE.finditer(m.content):
                files_read.add(path_match.group(1))
        # Paths from tool calls
        if m.tool_calls:
            for tc in m.tool_calls:
                name = tc.get("name")
                args = tc.get("arguments", {})
                if name in {"write_file", "edit_file", "apply_patch"} and "path" in args:
                    files_written.add(args["path"])
                if name == "read_file" and "path" in args:
                    files_read.add(args["path"])
        # Paths mentioned in plain text (assistant often says "let me read X.py")
        for path_match in _FILE_PATH_RE.finditer(m.content):
            path = path_match.group(1)
            # Skip if it's clearly a URL or sentence fragment
            if "/" in path and "." in path.split("/")[-1]:
                # Heuristic: read context
                context = m.content[max(0, path_match.start() - 30) : path_match.end() + 10].lower()
                if any(kw in context for kw in ("read", "open", "check", "look at")):
                    files_read.add(path)
                elif any(kw in context for kw in ("write", "create", "edit", "patch")):
                    files_written.add(path)
                else:
                    files_read.add(path)
        # Decision phrases
        for match in _DECISION_RE.finditer(m.content):
            decisions.append(match.group(0).strip())
        # Error patterns
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
# Task 40: token-aware trim
# ---------------------------------------------------------------------------


# Per-role token budgets (Phase 7 plan)
_ROLE_TOKEN_BUDGETS: dict[str, int] = {
    "MGR": 4_000,
    "ANL": 4_000,
    "DEV_FE": 16_000,
    "DEV_BE": 16_000,
    "QA": 8_000,
    "PM": 4_000,
    "SUP": 8_000,
}


def token_aware_trim(
    messages: list[Message],
    max_tokens: int = 16_000,
    model: str = "gpt-4o",
) -> list[Message]:
    """Trim messages to fit within ``max_tokens``.

    Strategy:
    1. Always keep the system messages (they're cheap and essential).
    2. Walk backward from the newest message, accumulating tokens.
    3. When adding the next message would exceed the budget, summarize
       the dropped portion and inject as a single system message.

    Returns a new list — does not mutate the input.
    """
    if count_message_tokens(messages, model) <= max_tokens:
        return list(messages)

    system = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]
    kept: list[Message] = []
    used = count_message_tokens(system, model)

    for m in reversed(non_system):
        cost = 4 + count_tokens(m.content, model)
        if used + cost > max_tokens:
            break
        kept.append(m)
        used += cost
    kept.reverse()

    if len(kept) < len(non_system):
        dropped = non_system[: -len(kept)]
        summary_dict = extractive_summary(dropped)
        summary_text = (
            f"[Token-aware summary: dropped {len(dropped)} messages] "
            f"files_read={summary_dict['files_read']} "
            f"files_written={summary_dict['files_written']} "
            f"errors={summary_dict['errors'][:3]}"
        )
        system = system + [Message(role="system", content=summary_text)]

    return system + kept


def get_token_budget_for_role(role: str) -> int:
    return _ROLE_TOKEN_BUDGETS.get(role, 16_000)


# ---------------------------------------------------------------------------
# Task 42: branching (sub-agents)
# ---------------------------------------------------------------------------


async def branch(
    store: "ConversationStore",
    parent_message: Message,
    child_role: str,
) -> "Message":
    """Create a child message linked to ``parent_message`` via parent_id.

    Returns the newly-appended Message. The child has role=assistant
    and an empty body — the sub-agent fills it in.
    """
    child = Message(
        role="assistant",
        content=f"[Sub-agent: {child_role}] starting…",
        parent_id=parent_message.id,
    )
    await store.append(child, sequence=0)  # caller is responsible for sequence
    return child


# ---------------------------------------------------------------------------
# Task 43: export
# ---------------------------------------------------------------------------


def export_conversation(messages: Iterable[Message]) -> dict[str, Any]:
    """Dump a conversation as a JSON-friendly dict for debugging / audit."""
    return {
        "message_count": sum(1 for _ in messages),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "tool_name": m.tool_name,
                "tool_call_id": m.tool_call_id,
                "parent_id": str(m.parent_id) if m.parent_id else None,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
            }
            for m in messages
        ],
    }


# ---------------------------------------------------------------------------
# DB-backed persistence
# ---------------------------------------------------------------------------


async def load_conversation(
    session: AsyncSession,
    conversation_id: UUID,
) -> list[Message]:
    """Reload all messages of a conversation from the DB, in order.

    Used by the resume flow (A.9 — failure recovery) so a restarted
    ``AgentLoop`` picks up where the previous (crashed) loop left off.
    """
    store = ConversationStore(session, conversation_id)
    return await store.get_messages()


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
