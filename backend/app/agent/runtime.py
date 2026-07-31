"""Agent runtime — the core loop.

``AgentLoop.run()`` is the heart of sub-system A. It:

1. Builds the initial system prompt from the role's RoleConfig
2. Persists a Conversation + AgentRun row
3. On each iteration:
   a. Trims conversation memory (sliding window + summary)
   b. Calls the LLM via LiteLLMClient
   c. Records token usage (cost + DB row)
   d. Parses tool calls via the 4-tier parser
   e. Executes each tool (gated by permission + safety systems)
   f. Checks safety systems; injects guidance if any tripped
   g. Updates the agent_run row with step + token totals
4. Returns an ``AgentResult`` with summary + metadata

Pure logic — no FastAPI coupling. Wrapped by the REST API in later phases.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from app.agent.checkpoint import (
    CHECKPOINT_EVERY_N_STEPS,
    load_latest_checkpoint,
    save_checkpoint,
)
from app.agent.gates import evaluate_migration_gate
from app.agent.llm.litellm_client import LLMResponse, LiteLLMClient
from app.agent.memory import ConversationStore, Message, extractive_summary, maybe_summarize, trim
from app.agent.observability import tracer
from app.agent.roles import Role, get_role_config
from app.agent.safety import (
    CircuitBreaker,
    EditFailureTracker,
    RepetitionDetector,
    TokenBudgetEnforcer,
    TokenBudgetExceeded,
)
from app.agent.tool_parser import ParsedToolCall, parse_tool_calls
from app.agent.tools import Tool, ToolContext, ToolResult, registry as global_registry
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.conversation import Conversation


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config + Result
# ---------------------------------------------------------------------------


@dataclass
class AgentLoopConfig:
    """All inputs needed to start a run."""

    role: Role
    user_prompt: str
    work_dir: str
    user_id: str | None = None
    org_id: str | None = None
    max_steps: int | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    allowed_paths: tuple[str, ...] = ()
    parent_run_id: UUID | None = None
    # Sub-agent metadata (for tool: run_subagent)
    depth: int = 0
    # When provided, the loop skips creating a Conversation/AgentRun (used by
    # the resume flow).
    resume_conversation_id: UUID | None = None
    resume_agent_run_id: UUID | None = None


@dataclass
class AgentResult:
    """Output of a completed agent run."""

    success: bool
    agent_run_id: UUID
    conversation_id: UUID
    summary: str
    steps: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    intentional_files: list[str] = field(default_factory=list)
    error: str | None = None
    finish_reason: str = "finished"  # finished | max_steps | safety_tripped | budget_exceeded | error


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------


class AgentLoop:
    """Async agent loop. Construct, call ``run(config)``."""

    def __init__(
        self,
        llm_client: LiteLLMClient,
        session: AsyncSession,
        tool_registry: dict[str, Tool] | None = None,
    ) -> None:
        self.llm = llm_client
        self.session = session
        self.tools = tool_registry or {t.name: t for t in global_registry.all()}

    async def run(self, config: AgentLoopConfig) -> AgentResult:
        """Execute the agent loop. Returns an AgentResult when done."""
        start = time.perf_counter()
        role_cfg = get_role_config(config.role)
        max_steps = config.max_steps or role_cfg.max_steps
        model = config.model or role_cfg.resolve_model()

        # Persist Conversation + AgentRun (or load for resume)
        conversation, agent_run, resume_state = await self._ensure_conversation(
            config, role_cfg, model
        )
        store = ConversationStore(self.session, conversation.id)

        # Build initial message list (or restore from conversation for resume)
        if resume_state and config.resume_conversation_id:
            # Reload full conversation history (already persisted)
            from app.agent.memory import load_conversation

            messages = await load_conversation(self.session, conversation.id)
            logger.info(
                "Resuming conversation %s from step %s",
                conversation.id,
                resume_state.get("input_tokens"),
            )
        else:
            messages: list[Message] = [
                Message(role="system", content=role_cfg.system_prompt),
                Message(role="user", content=config.user_prompt),
            ]
            await self._persist(store, messages)

        # Build tool schemas (filtered to this role)
        available_tools = self._available_tools(config.role)
        tool_schemas = [t.to_openai_schema() for t in available_tools]

        # Safety systems
        circuit = CircuitBreaker(max_consecutive=3)
        repetition = RepetitionDetector()
        edit_tracker = EditFailureTracker()
        budget = TokenBudgetEnforcer(
            per_run_limit=500_000,
            org_id=config.org_id,
            session=self.session,
        )

        steps = 0
        all_intentional: list[str] = []
        last_assistant_content = ""
        finish_reason: str | None = None
        error_msg: str | None = None

        # Seed bookkeeping from the resume checkpoint (A.9 — failure recovery)
        if resume_state:
            try:
                restored_step = int(resume_state.get("step", 0))
                if restored_step:
                    steps = restored_step
                restored_files = resume_state.get("intentional_files") or []
                if restored_files:
                    all_intentional = list(restored_files)
            except (TypeError, ValueError):
                logger.warning("Invalid resume_state, ignoring: %r", resume_state)

        with tracer.start_as_current_span("agent.run") as run_span:
            run_span.set_attribute("agent_run_id", str(agent_run.id))
            run_span.set_attribute("role", config.role.value)
            run_span.set_attribute("model", model)
            run_span.set_attribute("org_id", str(config.org_id) if config.org_id else "")

            try:
                while steps < max_steps:
                    steps += 1
                    await self._log_activity(agent_run.id, "agent.step_started", {"step": steps})

                    # Trim if needed
                    messages = maybe_summarize(trim(messages, max_messages=30), threshold=50)

                    # Periodic checkpoint (A.9 — failure recovery)
                    if steps % CHECKPOINT_EVERY_N_STEPS == 0:
                        try:
                            await save_checkpoint(
                                self.session,
                                agent_run_id=agent_run.id,
                                step=steps,
                                state={
                                    "input_tokens": budget.usage.input_tokens,
                                    "output_tokens": budget.usage.output_tokens,
                                    "intentional_files": list(all_intentional),
                                    "last_assistant_content_preview": last_assistant_content[:200],
                                },
                            )
                            await self.session.commit()
                        except Exception:
                            logger.exception("Checkpoint save failed (non-fatal)")

                    # Call LLM
                    llm_dicts = [m.to_llm_dict() for m in messages]
                    with tracer.start_as_current_span("llm.completion") as llm_span:
                        llm_span.set_attribute("model", model)
                        llm_span.set_attribute("step", steps)
                        response: LLMResponse = await self.llm.completion(
                            model=model,
                            messages=llm_dicts,
                            tools=tool_schemas,
                            api_key=config.api_key,
                        )
                        llm_span.set_attribute("input_tokens", response.input_tokens)
                        llm_span.set_attribute("output_tokens", response.output_tokens)
                        llm_span.set_attribute("cost_usd", response.cost_usd)
                        llm_span.set_attribute("finish_reason", response.finish_reason)
                    if response.finish_reason == "error":
                        finish_reason = "error"
                        error_msg = response.content
                        break

                    budget.record(response.input_tokens, response.output_tokens)
                    await self._persist_assistant(store, messages, response, steps)

                    last_assistant_content = response.content

                    # Parse tool calls (native + text)
                    tool_calls = parse_tool_calls(response.content, response.tool_calls)
                    if not tool_calls:
                        # LLM decided it's done without calling finish — treat as finish
                        finish_reason = "finished"
                        break

                    # Execute each tool
                    step_should_exit = False
                    for tc in tool_calls:
                        if await self._is_finish_call(tc):
                            finish_reason = "finished"
                            messages.append(
                                Message(role="tool", content="finish accepted", tool_call_id=tc.id, tool_name=tc.name)
                            )
                            await self._persist(store, messages[-1:], sequence=len(messages))
                            step_should_exit = True
                            break

                        with tracer.start_as_current_span("tool.execute") as tool_span:
                            tool_span.set_attribute("tool_name", tc.name)
                            result = await self._execute_tool(tc, config, available_tools, circuit, repetition, edit_tracker)
                            tool_span.set_attribute("ok", result.ok)
                        messages.append(
                            Message(
                                role="tool",
                                content=result.output if result.ok else f"ERROR: {result.error}",
                                tool_call_id=tc.id,
                                tool_name=tc.name,
                            )
                        )
                        await self._persist(store, messages[-1:], sequence=len(messages))

                        if result.ok:
                            circuit.record_success(tc.name)
                            edit_tracker.record_success(tc.name)
                        else:
                            circuit.record_failure(tc.name)
                            edit_tracker.record_failure(tc.name)
                        repetition.record(tc.name, tc.arguments, self.tools[tc.name].is_mutating)
                        if result.metadata.get("intentional") and result.metadata.get("path"):
                            all_intentional.append(result.metadata["path"])

                        # Task 30: migration approval gate
                        if tc.name == "run_command" and result.ok:
                            gate = evaluate_migration_gate(tc.arguments.get("command", ""))
                            if gate.trip:
                                messages.append(Message(role="system", content=gate.guidance))
                                await self._persist(store, messages[-1:], sequence=len(messages))
                                error_msg = gate.reason
                                finish_reason = "awaiting_approval"
                                # Mark the run as awaiting approval so resume works
                                agent_run.status = "awaiting_approval"
                            await self.session.commit()
                            break

                    if step_should_exit:
                        break

                    # Check safety trip (after tool runs, before next LLM)
                    if circuit.tripped or repetition.tripped or edit_tracker.tripped:
                        with tracer.start_as_current_span("safety.check") as safety_span:
                            tripped = []
                            if circuit.tripped:
                                tripped.append("circuit_breaker")
                            if repetition.tripped:
                                tripped.append("repetition")
                            if edit_tracker.tripped:
                                tripped.append("edit_tracker")
                            safety_span.set_attribute("tripped_guards", ",".join(tripped))
                        guidance = circuit.guidance_message() or repetition.guidance_message() or edit_tracker.guidance_message()
                        if guidance:
                            messages.append(Message(role="system", content=guidance))
                            await self._persist(store, messages[-1:], sequence=len(messages))
                            # Strip warning emoji for clean error field
                            error_msg = guidance.lstrip("⚠️ ").strip()
                        finish_reason = "safety_tripped"
                        break

                    # Check token budget
                    try:
                        await budget.check()
                    except TokenBudgetExceeded as e:
                        finish_reason = "budget_exceeded"
                        error_msg = str(e)
                        break

                    # Loop exited because steps >= max_steps without breaking for any other reason
                    if finish_reason is None:
                        finish_reason = "max_steps"

            except Exception as e:
                    logger.exception("AgentLoop crashed")
                    finish_reason = "error"
                    error_msg = str(e)

                # Persist final AgentRun update + record final span attrs (still inside `with`)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            final_status = finish_reason or "finished"
            agent_run.status = final_status
            agent_run.steps = steps
            agent_run.input_tokens = budget.usage.input_tokens
            agent_run.output_tokens = budget.usage.output_tokens
            agent_run.cost_usd = 0.0
            agent_run.duration_ms = elapsed_ms
            agent_run.error = error_msg
            agent_run.finished_at = datetime.now(timezone.utc)
            await self.session.commit()

            run_span.set_attribute("finish_reason", final_status)
            run_span.set_attribute("steps", steps)
            run_span.set_attribute("input_tokens", budget.usage.input_tokens)
            run_span.set_attribute("output_tokens", budget.usage.output_tokens)
            run_span.set_attribute("duration_ms", elapsed_ms)

            # Generate summary
            summary = last_assistant_content or "Run finished without text output"
            if final_status == "safety_tripped":
                summary = f"[Safety tripped] {summary}"
            if error_msg:
                summary = f"[{final_status}] {summary}\n{error_msg}"

            return AgentResult(
                success=(final_status == "finished"),
                agent_run_id=agent_run.id,
                conversation_id=conversation.id,
                summary=summary,
                steps=steps,
                input_tokens=budget.usage.input_tokens,
                output_tokens=budget.usage.output_tokens,
                cost_usd=0.0,
                duration_ms=elapsed_ms,
                intentional_files=all_intentional,
                error=error_msg,
                finish_reason=final_status,
            )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _ensure_conversation(
        self, config: AgentLoopConfig, role_cfg, model: str
    ) -> tuple[Conversation, AgentRun, dict]:
        """Return (conversation, agent_run, resume_state).

        ``resume_state`` is empty for new runs, populated from the latest
        checkpoint for resumed runs.
        """
        if config.resume_conversation_id:
            conversation = await self.session.get(Conversation, config.resume_conversation_id)
            if conversation is None:
                raise ValueError(f"Resume conversation {config.resume_conversation_id} not found")
            agent_run = await self.session.get(AgentRun, config.resume_agent_run_id)
            if agent_run is None:
                raise ValueError(f"Resume agent_run {config.resume_agent_run_id} not found")
            # Load latest checkpoint (A.9 — failure recovery)
            checkpoint = await load_latest_checkpoint(self.session, agent_run.id)
            resume_state = checkpoint.state if checkpoint is not None else {}
            # Reset status so the loop can re-write it on exit
            agent_run.status = "running"
            agent_run.error = None
            agent_run.finished_at = None
            await self.session.commit()
            return conversation, agent_run, resume_state

        conversation = Conversation(
            role=config.role.value,
            status="running",
            user_id=config.user_id,
            org_id=config.org_id,
            parent_run_id=config.parent_run_id,
        )
        self.session.add(conversation)
        await self.session.flush()

        agent_run = AgentRun(
            conversation_id=conversation.id,
            user_id=config.user_id,
            org_id=config.org_id,
            role=config.role.value,
            model=model,
            status="running",
        )
        self.session.add(agent_run)
        await self.session.commit()
        return conversation, agent_run, {}

    def _available_tools(self, role: Role) -> list[Tool]:
        role_cfg = get_role_config(role)
        out: list[Tool] = []
        for name in role_cfg.tool_names:
            t = self.tools.get(name)
            if t is not None:
                out.append(t)
        # Always include the implicit `finish` marker
        return out

    async def _persist(self, store: ConversationStore, messages: list[Message], sequence: int | None = None) -> None:
        for i, m in enumerate(messages):
            await store.append(m, sequence=(sequence or i) if sequence is not None else i)
        await self.session.commit()

    async def _persist_assistant(
        self, store: ConversationStore, messages: list[Message], response: LLMResponse, sequence: int
    ) -> None:
        msg = Message(
            role="assistant",
            content=response.content,
            tool_calls=response.tool_calls or None,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        await store.append(msg, sequence=sequence)
        messages.append(msg)
        await self.session.commit()

    async def _execute_tool(
        self,
        tc: ParsedToolCall,
        config: AgentLoopConfig,
        tools: list[Tool],
        circuit: CircuitBreaker,
        repetition: RepetitionDetector,
        edit_tracker: EditFailureTracker,
    ) -> ToolResult:
        tool = self.tools.get(tc.name)
        if tool is None:
            return ToolResult(ok=False, error=f"Unknown tool: {tc.name!r}")
        ctx = ToolContext(
            agent_run_id=uuid4(),  # placeholder; not used for tracing in tests
            user_id=config.user_id or "u1",
            org_id=config.org_id,
            work_dir=config.work_dir,
            allowed_paths=config.allowed_paths,
            db_session=self.session,
            metadata={"depth": config.depth},
        )
        try:
            return await tool.handler(ctx, tc.arguments)
        except Exception as e:
            logger.exception("Tool %s raised", tc.name)
            return ToolResult(ok=False, error=f"Tool {tc.name!r} raised: {e}")

    async def _is_finish_call(self, tc: ParsedToolCall) -> bool:
        return tc.name == "finish"

    async def _log_activity(self, agent_run_id: UUID, event: str, metadata: dict) -> None:
        # Stub — wired to audit_log in Phase 5. Currently a no-op for tests.
        logger.debug("[run %s] %s: %s", agent_run_id, event, metadata)
