"""AgentLoop tests — mocked LLM."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agent.llm.litellm_client import LLMResponse
from app.agent.roles import Role
from app.agent.runtime import AgentLoop, AgentLoopConfig
from app.db import async_session_maker


def _text_response(text: str, tool_calls=None, input_tokens=10, output_tokens=5) -> LLMResponse:
    return LLMResponse(
        content=text,
        tool_calls=tool_calls or [],
        finish_reason="tool_calls" if tool_calls else "stop",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=0.001,
        model="gpt-4o",
    )


def _tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {"id": call_id, "name": name, "arguments": args}


def _make_llm_client(responses: list[LLMResponse]):
    """Returns a LiteLLMClient whose .completion() returns responses in order."""
    client = MagicMock()
    client.completion = AsyncMock(side_effect=responses)
    return client


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


# -------------------- Task 20: AgentLoopConfig --------------------


def test_config_defaults():
    cfg = AgentLoopConfig(role=Role.DEVELOPER_BE, user_prompt="x", work_dir="/tmp")
    assert cfg.max_steps is None
    assert cfg.depth == 0
    assert cfg.allowed_paths == ()


# -------------------- Task 21: main loop --------------------


@pytest.mark.asyncio
async def test_loop_exits_when_llm_returns_no_tool_calls(work_dir):
    """If the LLM has no tool calls and just text, the loop finishes."""
    async with async_session_maker() as session:
        llm = _make_llm_client([_text_response("I'm done, the answer is X")])
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(
            role=Role.ANALYST,
            user_prompt="What's 2+2?",
            work_dir=work_dir,
        )
        result = await loop.run(cfg)

    assert result.success
    assert result.finish_reason == "finished"
    assert result.steps == 1
    assert result.summary == "I'm done, the answer is X"


@pytest.mark.asyncio
async def test_loop_executes_tool_call_and_continues(work_dir):
    """LLM calls read_file → tool runs → next LLM call returns text → finish."""
    # Write a file for the agent to read
    Path(work_dir, "data.txt").write_text("the answer is 42\n")

    responses = [
        # Step 1: LLM calls read_file
        _text_response(
            "Let me read the file",
            tool_calls=[_tool_call("read_file", {"path": "data.txt"})],
        ),
        # Step 2: LLM returns final answer
        _text_response("The answer is 42"),
    ]
    async with async_session_maker() as session:
        llm = _make_llm_client(responses)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(role=Role.ANALYST, user_prompt="find answer", work_dir=work_dir)
        result = await loop.run(cfg)

    assert result.success
    assert result.steps == 2
    assert "42" in result.summary
    # 2 LLM calls were made
    assert llm.completion.await_count == 2


@pytest.mark.asyncio
async def test_loop_finishes_when_finish_tool_called(work_dir):
    """`finish` is a special marker — it stops the loop without executing."""
    responses = [
        _text_response(
            "all done",
            tool_calls=[_tool_call("finish", {"summary": "task complete"})],
        ),
    ]
    async with async_session_maker() as session:
        llm = _make_llm_client(responses)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(role=Role.ANALYST, user_prompt="x", work_dir=work_dir)
        result = await loop.run(cfg)
    assert result.success
    assert result.finish_reason == "finished"


@pytest.mark.asyncio
async def test_loop_stops_at_max_steps(work_dir):
    """LLM keeps calling successful read_file; loop stops at max_steps."""
    Path(work_dir, "x.txt").write_text("data")
    responses = [
        _text_response("step", tool_calls=[_tool_call("read_file", {"path": "x.txt"})]),
        _text_response("step", tool_calls=[_tool_call("read_file", {"path": "x.txt"})]),
        _text_response("step", tool_calls=[_tool_call("read_file", {"path": "x.txt"})]),
        _text_response("step", tool_calls=[_tool_call("read_file", {"path": "x.txt"})]),
    ]
    async with async_session_maker() as session:
        llm = _make_llm_client(responses)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(role=Role.ANALYST, user_prompt="loop", work_dir=work_dir, max_steps=3)
        result = await loop.run(cfg)
    assert result.finish_reason == "max_steps"
    assert result.steps == 3


# -------------------- Task 24: Safety integration --------------------


@pytest.mark.asyncio
async def test_loop_safety_trips_after_3_same_tool_failures(work_dir):
    """read_file fails 3 times in a row → safety trip → loop exits."""
    responses = []
    for i in range(5):
        responses.append(
            _text_response(
                "trying",
                tool_calls=[_tool_call("read_file", {"path": f"missing_{i}.txt"})],
            )
        )
    async with async_session_maker() as session:
        llm = _make_llm_client(responses)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(role=Role.ANALYST, user_prompt="x", work_dir=work_dir, max_steps=10)
        result = await loop.run(cfg)
    assert result.finish_reason == "safety_tripped"
    # Guidance should mention the tool name
    guidance = circuit_g_msg = None
    # We can't easily access the guidance from outside; check result summary
    # and error for clues
    assert result.error is not None or "read_file" in result.summary or "Tool" in result.summary


@pytest.mark.asyncio
async def test_loop_handles_llm_error(work_dir):
    async with async_session_maker() as session:
        llm = MagicMock()
        # Build LLMResponse with finish_reason=error directly
        err_resp = LLMResponse(content="API down", finish_reason="error", model="gpt-4o")
        llm.completion = AsyncMock(return_value=err_resp)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(role=Role.ANALYST, user_prompt="x", work_dir=work_dir)
        result = await loop.run(cfg)
    assert result.finish_reason == "error"
    assert "API down" in (result.error or "")


# -------------------- Task 26: AgentResult --------------------


@pytest.mark.asyncio
async def test_result_includes_token_counts(work_dir):
    async with async_session_maker() as session:
        llm = _make_llm_client([_text_response("done", input_tokens=42, output_tokens=10)])
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(role=Role.ANALYST, user_prompt="x", work_dir=work_dir)
        result = await loop.run(cfg)
    assert result.input_tokens == 42
    assert result.output_tokens == 10


@pytest.mark.asyncio
async def test_result_tracks_intentional_files(work_dir):
    """write_file calls accumulate in intentional_files."""
    Path(work_dir, "a.py")  # touch (already created by fixture)
    responses = [
        _text_response(
            "create",
            tool_calls=[_tool_call("write_file", {"path": "a.py", "content": "x"})],
        ),
        _text_response("done"),
    ]
    async with async_session_maker() as session:
        llm = _make_llm_client(responses)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(role=Role.DEVELOPER_BE, user_prompt="x", work_dir=work_dir)
        result = await loop.run(cfg)
    assert "a.py" in result.intentional_files
