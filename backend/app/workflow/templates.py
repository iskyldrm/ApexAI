"""Workflow templates — seed defaults + CRUD (B.12).

Templates are pre-built process definitions users can clone into their
own processes. Seeded with: bug-fix-pipeline, code-review, doc-update.

A user clones a template by:
    POST /workflow-templates/{id}/clone
    → creates a new Process row owned by their org with the template's
      ``definition`` JSON.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.process import Process, WorkflowTemplate


logger = logging.getLogger(__name__)


SEED_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "bug-fix-pipeline",
        "category": "bug-fix",
        "description": "Reproduce → diagnose → fix → add regression test.",
        "definition": {
            "nodes": [
                {"id": "reproduce", "role": "QA", "prompt": "Reproduce the bug from the issue description."},
                {"id": "diagnose", "role": "ANL", "prompt": "Find the root cause in the code."},
                {"id": "fix", "role": "DEV_BE", "prompt": "Implement the minimal fix."},
                {"id": "test", "role": "QA", "prompt": "Add a regression test for this bug."},
            ],
            "edges": [
                {"from": "reproduce", "to": "diagnose"},
                {"from": "diagnose", "to": "fix"},
                {"from": "fix", "to": "test"},
            ],
        },
    },
    {
        "name": "code-review",
        "category": "code-review",
        "description": "PR review with security + style + test checks.",
        "definition": {
            "nodes": [
                {"id": "fetch-pr", "role": "QA", "prompt": "Fetch the PR diff."},
                {"id": "security", "role": "ANL", "prompt": "Audit for security issues."},
                {"id": "style", "role": "ANL", "prompt": "Check style + naming."},
                {"id": "tests", "role": "QA", "prompt": "Verify test coverage."},
                {"id": "summarize", "role": "MGR", "prompt": "Aggregate the findings into a single review comment."},
            ],
            "edges": [
                {"from": "fetch-pr", "to": "security"},
                {"from": "fetch-pr", "to": "style"},
                {"from": "fetch-pr", "to": "tests"},
                {"from": "security", "to": "summarize"},
                {"from": "style", "to": "summarize"},
                {"from": "tests", "to": "summarize"},
            ],
        },
    },
    {
        "name": "doc-update",
        "category": "doc-update",
        "description": "Read code → write/update docs → verify accuracy.",
        "definition": {
            "nodes": [
                {"id": "scan-code", "role": "ANL", "prompt": "Identify all public APIs."},
                {"id": "write-docs", "role": "DEV_FE", "prompt": "Write/update docs for each public API."},
                {"id": "verify", "role": "QA", "prompt": "Run docs build and check no broken links."},
            ],
            "edges": [
                {"from": "scan-code", "to": "write-docs"},
                {"from": "write-docs", "to": "verify"},
            ],
        },
    },
]


async def seed_templates(session: AsyncSession) -> int:
    """Insert SEED_TEMPLATES if not already present. Idempotent."""
    inserted = 0
    for tpl in SEED_TEMPLATES:
        existing = await session.execute(
            select(WorkflowTemplate).where(WorkflowTemplate.name == tpl["name"])
        )
        if existing.scalar_one_or_none():
            continue
        row = WorkflowTemplate(
            id=uuid4(),
            name=tpl["name"],
            category=tpl["category"],
            description=tpl["description"],
            definition=tpl["definition"],
        )
        session.add(row)
        inserted += 1
    if inserted:
        await session.commit()
        logger.info("Seeded %d workflow templates", inserted)
    return inserted


async def list_templates(
    session: AsyncSession, category: str | None = None
) -> list[WorkflowTemplate]:
    stmt = select(WorkflowTemplate).order_by(WorkflowTemplate.name)
    if category:
        stmt = stmt.where(WorkflowTemplate.category == category)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_template(session: AsyncSession, template_id: UUID) -> WorkflowTemplate | None:
    return await session.get(WorkflowTemplate, template_id)


async def clone_template(
    session: AsyncSession,
    template_id: UUID,
    *,
    org_id: str | None,
    user_id: str | None,
    name: str | None = None,
) -> Process:
    """Create a draft Process from a template's definition."""
    tpl = await get_template(session, template_id)
    if tpl is None:
        raise ValueError(f"Template {template_id} not found")

    process = Process(
        id=uuid4(),
        org_id=org_id,
        created_by=user_id,
        name=name or f"{tpl.name}-clone",
        description=tpl.description,
        definition=tpl.definition,
        status="draft",
    )
    session.add(process)
    await session.commit()
    logger.info("Cloned template %s as process %s", tpl.name, process.id)
    return process