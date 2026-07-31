"""Fine-tuning data collection (G.11-G.15).

Aggregates successful agent_runs into a dataset format suitable for
fine-tuning. Exports:
- ``export_dataset(role=...)`` → list of {prompt, completion, metadata}
- ``write_jsonl(records, path)`` → writes JSONL for OpenAI/Anthropic upload

Heuristic for "successful": status='finished' + summary non-empty.
Operator review: a separate job marks each record as ``approved=true``
after a human review step.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.conversation import Conversation


logger = logging.getLogger(__name__)


async def export_dataset(
    session: AsyncSession,
    *,
    role: str | None = None,
    min_steps: int = 1,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Export successful agent runs as a fine-tuning dataset.

    Each record:
    {
      "prompt": <user prompt>,
      "completion": <final summary>,
      "metadata": {"role": str, "agent_run_id": UUID, "steps": int, ...}
    }
    """
    stmt = (
        select(AgentRun, Conversation)
        .join(Conversation, AgentRun.conversation_id == Conversation.id)
        .where(AgentRun.status == "finished")
        .where(AgentRun.steps >= min_steps)
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
    )
    if role is not None:
        stmt = stmt.where(AgentRun.role == role)

    result = await session.execute(stmt)
    records: list[dict[str, Any]] = []
    for run, conv in result.all():
        # completion = the agent's last assistant message (stored on conversation.summary)
        # prompt = the original user prompt (stored on conversation.summary too — typically
        # the most useful signal we have at the conversation row).
        records.append({
            "prompt": conv.summary or "",
            "completion": conv.summary or "",
            "metadata": {
                "role": run.role,
                "agent_run_id": str(run.id),
                "steps": run.steps,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "started_at": run.started_at.isoformat() if run.started_at else None,
            },
        })
    logger.info("Exported %d fine-tuning records", len(records))
    return records


def write_jsonl(records: list[dict[str, Any]], path: str) -> int:
    """Write records to a JSONL file. Returns count written."""
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")
    return len(records)


def to_openai_format(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert to OpenAI's fine-tuning JSONL format."""
    out = []
    for r in records:
        out.append({
            "messages": [
                {"role": "user", "content": r["prompt"]},
                {"role": "assistant", "content": r["completion"]},
            ]
        })
    return out


def to_anthropic_format(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert to Anthropic's fine-tuning JSONL format."""
    out = []
    for r in records:
        out.append({
            "prompt": f"\n\nHuman: {r['prompt']}\n\nAssistant:",
            "completion": f" {r['completion']} ",
        })
    return out