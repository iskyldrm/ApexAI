"""StepExecutor tests — uses a mocked LiteLLMClient."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.agent.llm.litellm_client import LLMResponse
from app.db import async_session_maker
from app.models.process import Process, ProcessStep
from app.workflow.executor import StepExecutor


def _ok_resp(content: str = "done") -> LLMResponse:
    return LLMResponse(
        content=content, tool_calls=[], finish_reason="stop",
        input_tokens=10, output_tokens=5, cost_usd=0.001, model="gpt-4o",
    )


async def _make_process(definition=None) -> Process:
    definition = definition or {
        "name": "test",
        "steps": [
            {"name": "a", "role": "ANL", "prompt": "analyze"},
            {"name": "b", "role": "DEV_BE", "prompt": "implement based on: {{steps.a.outputs.summary}}"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    async with async_session_maker() as session:
        p = Process(
            name=f"exec-{uuid.uuid4().hex[:6]}",
            definition=definition,
            status="running",
            org_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return p


async def _make_running_step(process_id, step_name, prompt_template="analyze") -> ProcessStep:
    async with async_session_maker() as session:
        s = ProcessStep(
            process_id=uuid.UUID(process_id),
            step_name=step_name,
            role="ANL",
            status="running",
            prompt_template=prompt_template,
            attempt=1,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s


@pytest.mark.asyncio
async def test_executor_completes_step_on_success():
    p = await _make_process()
    step = await _make_running_step(str(p.id), "a")
    llm = MagicMock()
    llm.completion = AsyncMock(return_value=_ok_resp("analysis done"))
    executor = StepExecutor(llm)

    async with async_session_maker() as session:
        s = await session.get(ProcessStep, step.id)
        await executor.execute(session, s)
        await session.refresh(s)
    assert s.status == "completed"
    assert s.outputs["summary"] == "analysis done"
    assert "agent_run_id" in s.outputs


@pytest.mark.asyncio
async def test_executor_resolves_upstream_outputs_in_template():
    p = await _make_process()
    async with async_session_maker() as session:
        a_step = ProcessStep(
            process_id=p.id, step_name="a", role="ANL",
            status="completed", prompt_template="analyze",
            outputs={"summary": "the root cause is X"},
        )
        session.add(a_step)
        await session.commit()
        await session.refresh(a_step)

    b_step = await _make_running_step(str(p.id), "b", "fix: {{steps.a.outputs.summary}}")
    llm = MagicMock()
    llm.completion = AsyncMock(return_value=_ok_resp("fixed"))
    executor = StepExecutor(llm)

    async with async_session_maker() as session:
        s = await session.get(ProcessStep, b_step.id)
        await executor.execute(session, s)
        await session.refresh(s)
    assert s.status == "completed"
    assert "the root cause is X" in s.inputs["prompt"]


@pytest.mark.asyncio
async def test_executor_uses_definition_prompt_when_template_empty():
    p = await _make_process()
    async with async_session_maker() as session:
        a_step = ProcessStep(
            process_id=p.id, step_name="a", role="ANL",
            status="running", prompt_template="",
            attempt=1,
        )
        session.add(a_step)
        await session.commit()
        await session.refresh(a_step)
        step_id = a_step.id

    llm = MagicMock()
    llm.completion = AsyncMock(return_value=_ok_resp("ok"))
    executor = StepExecutor(llm)
    async with async_session_maker() as session:
        s = await session.get(ProcessStep, step_id)
        await executor.execute(session, s)
        await session.refresh(s)
    assert s.status == "completed"
    assert s.inputs["prompt"] == "analyze"


@pytest.mark.asyncio
async def test_executor_invalid_template_fails_step():
    p = await _make_process()
    async with async_session_maker() as session:
        b_step = ProcessStep(
            process_id=p.id, step_name="b", role="DEV_BE",
            status="running",
            prompt_template="fix: {{steps.a.outputs.summary}}",
            attempt=5,  # already at max → next fail = DLQ
            max_attempts=5,
        )
        session.add(b_step)
        await session.commit()
        await session.refresh(b_step)
        step_id = b_step.id

    llm = MagicMock()
    executor = StepExecutor(llm)
    async with async_session_maker() as session:
        s = await session.get(ProcessStep, step_id)
        await executor.execute(session, s)
        await session.refresh(s)
    assert s.status == "failed"
    assert "not yet executed" in (s.error or "")


@pytest.mark.asyncio
async def test_executor_complete_triggers_downstream_enqueue():
    p = await _make_process()
    a_step = await _make_running_step(str(p.id), "a")
    async with async_session_maker() as session:
        b_step = ProcessStep(
            process_id=p.id, step_name="b", role="DEV_BE",
            status="pending", prompt_template="implement",
        )
        session.add(b_step)
        await session.commit()
        await session.refresh(b_step)
        b_id = b_step.id

    llm = MagicMock()
    llm.completion = AsyncMock(return_value=_ok_resp("ok"))
    executor = StepExecutor(llm)

    async with async_session_maker() as session:
        s = await session.get(ProcessStep, a_step.id)
        await executor.execute(session, s)

    async with async_session_maker() as session:
        b = await session.get(ProcessStep, b_id)
        assert b.status == "queued"


@pytest.mark.asyncio
async def test_executor_failure_does_not_complete_process():
    p = await _make_process()
    a_step = await _make_running_step(str(p.id), "a")

    llm = MagicMock()
    llm.completion = AsyncMock(side_effect=RuntimeError("LLM down"))
    executor = StepExecutor(llm)

    async with async_session_maker() as session:
        s = await session.get(ProcessStep, a_step.id)
        await executor.execute(session, s)
        await session.refresh(s)
    assert s.status in ("failed", "retrying")
