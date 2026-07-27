"""StepExecutor — runs a queued step by invoking AgentLoop (Sub-System A).

The executor:
1. Loads the process definition + upstream step outputs
2. Resolves the step's prompt template against those
3. Calls AgentLoop directly (in-process; faster than HTTP roundtrip)
4. Stores outputs + agent_run_id back on the step
5. On `awaiting_approval` finish_reason, pauses the parent process
6. On `safety_tripped` / `budget_exceeded` / `error`, retries via the queue
7. On `finished`, transitions the step to `completed` and signals the
   next dependent step to enqueue
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm.litellm_client import LiteLLMClient
from app.agent.observability import log_agent_event
from app.agent.roles import Role
from app.agent.runtime import AgentLoop, AgentLoopConfig, AgentResult
from app.models.process import Process, ProcessEvent, ProcessStep
from app.workflow.definition import ProcessDefinition, resolve_template
from app.workflow.queue import mark_step_completed, mark_step_failed
from app.workflow.state import transition_process, transition_step


logger = logging.getLogger(__name__)


class StepExecutor:
    """Runs one step by invoking AgentLoop and storing outputs."""

    def __init__(self, llm_client: LiteLLMClient) -> None:
        self.llm = llm_client

    async def execute(
        self, session: AsyncSession, step: ProcessStep
    ) -> None:
        """Execute the step. Caller has already claimed + transitioned to 'running'."""
        process = await session.get(Process, step.process_id)
        if process is None:
            await mark_step_failed(session, step, "Parent process deleted")
            return

        # 1. Load definition + compute inputs
        try:
            definition = ProcessDefinition.model_validate(process.definition)
        except Exception as e:
            await mark_step_failed(session, step, f"Invalid definition: {e}")
            return

        step_def = definition.step_by_name(step.step_name)
        if step_def is None:
            await mark_step_failed(session, step, f"Step {step.step_name!r} not in definition")
            return

        # 2. Gather upstream outputs
        upstream_names = definition.upstream(step.step_name)
        step_outputs: dict[str, dict[str, Any]] = {}
        if upstream_names:
            result = await session.execute(
                select(ProcessStep).where(
                    ProcessStep.process_id == process.id,
                    ProcessStep.step_name.in_(upstream_names),
                )
            )
            for up in result.scalars():
                step_outputs[up.step_name] = up.outputs or {}

        # 3. Resolve template
        try:
            resolved_prompt = resolve_template(
                step.prompt_template or step_def.prompt,
                process.inputs or {},
                step_outputs,
            )
        except Exception as e:
            await mark_step_failed(session, step, f"Template error: {e}")
            return

        step.inputs = {
            "prompt": resolved_prompt,
            "upstream_outputs": {n: step_outputs.get(n, {}) for n in upstream_names},
        }
        session.add(ProcessEvent(
            process_id=process.id,
            step_id=step.id,
            event_type="step.started",
            payload={"attempt": step.attempt, "prompt_preview": resolved_prompt[:200]},
        ))
        await session.commit()

        # 4. Invoke AgentLoop in-process
        try:
            role = Role(step_def.role)
        except ValueError:
            await mark_step_failed(session, step, f"Unknown role: {step_def.role}")
            return

        # Find a work_dir — use process metadata or default
        work_dir = (process.meta or {}).get("work_dir", "/tmp")

        config = AgentLoopConfig(
            role=role,
            user_prompt=resolved_prompt,
            work_dir=work_dir,
            user_id=process.user_id,
            org_id=process.org_id,
            max_steps=step_def.max_attempts and step_def.max_attempts * 5 or None,
        )

        try:
            loop = AgentLoop(llm_client=self.llm, session=session)
            result: AgentResult = await loop.run(config)
        except Exception as e:
            logger.exception("StepExecutor crashed")
            await mark_step_failed(session, step, f"Loop crashed: {e}")
            return

        # 5. Handle finish reasons
        if result.finish_reason == "awaiting_approval":
            # Pause the parent process; user must resume
            step.status = "paused"  # type: ignore[assignment]
            step.error = result.error
            step.finished_at = datetime.utcnow()
            if process.status == "running":
                try:
                    await transition_process(
                        session, process, "paused", actor_id="system",
                        payload={"step": step.step_name, "reason": "approval gate"},
                    )
                except Exception:
                    pass  # already paused / cancelled
            await session.commit()
            await log_agent_event(
                action="process.step_paused_for_approval",
                agent_run_id=str(result.agent_run_id),
                role=role.value,
                org_id=process.org_id,
                metadata={"process_id": str(process.id), "step": step.step_name},
            )
            return

        if not result.success:
            # safety_tripped / budget_exceeded / error / max_steps
            await mark_step_failed(session, step, result.error or f"finish_reason={result.finish_reason}")
            session.add(ProcessEvent(
                process_id=process.id,
                step_id=step.id,
                event_type="step.failed",
                payload={"finish_reason": result.finish_reason, "error": result.error},
            ))
            # Check if all steps are failed → mark process failed
            await self._maybe_complete_or_fail_process(session, process)
            return

        # 6. Success — store outputs
        outputs = {
            "summary": result.summary,
            "agent_run_id": str(result.agent_run_id),
            "finish_reason": result.finish_reason,
            "steps": result.steps,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "intentional_files": result.intentional_files,
        }
        await mark_step_completed(session, step, outputs)
        session.add(ProcessEvent(
            process_id=process.id,
            step_id=step.id,
            event_type="step.completed",
            payload={"finish_reason": result.finish_reason, "summary": result.summary[:500]},
        ))
        await session.commit()

        # 7. Enqueue downstream steps that are now ready
        await self._enqueue_downstream(session, process, definition, step.step_name)

        # 8. Check if process is done
        await self._maybe_complete_or_fail_process(session, process)

    async def _enqueue_downstream(
        self,
        session: AsyncSession,
        process: Process,
        definition: ProcessDefinition,
        completed_step: str,
    ) -> None:
        """Mark downstream steps as ready if all their upstreams are done."""
        for next_name in definition.downstream(completed_step):
            # Check all upstreams are completed/skipped
            upstreams = definition.upstream(next_name)
            if not upstreams:
                continue
            result = await session.execute(
                select(ProcessStep).where(
                    ProcessStep.process_id == process.id,
                    ProcessStep.step_name.in_(upstreams),
                )
            )
            statuses = {s.status for s in result.scalars()}
            if all(s in ("completed", "skipped") for s in statuses):
                # Ready — enqueue
                next_step = (
                    await session.execute(
                        select(ProcessStep).where(
                            ProcessStep.process_id == process.id,
                            ProcessStep.step_name == next_name,
                        )
                    )
                ).scalar_one_or_none()
                if next_step and next_step.status == "pending":
                    next_step.status = "queued"
                    next_step.next_retry_at = None
                    session.add(ProcessEvent(
                        process_id=process.id,
                        step_id=next_step.id,
                        event_type="step.queued",
                        payload={"triggered_by": completed_step},
                    ))
        await session.commit()

    async def _maybe_complete_or_fail_process(
        self, session: AsyncSession, process: Process
    ) -> None:
        """If all steps are terminal, transition the process to completed or failed."""
        result = await session.execute(
            select(ProcessStep.status).where(ProcessStep.process_id == process.id)
        )
        statuses = {s for s in result.scalars()}
        if not statuses:
            return
        all_done = all(s in ("completed", "skipped", "failed", "cancelled") for s in statuses)
        if not all_done:
            return
        any_failed = any(s in ("failed", "cancelled") for s in statuses)
        try:
            if any_failed:
                await transition_process(session, process, "failed", actor_id="system")
            else:
                # Aggregate outputs from all steps
                all_steps = (
                    await session.execute(
                        select(ProcessStep).where(ProcessStep.process_id == process.id)
                    )
                ).scalars()
                process.outputs = {
                    s.step_name: s.outputs for s in all_steps if s.outputs
                }
                await transition_process(session, process, "completed", actor_id="system")
        except Exception:
            logger.exception("Failed to finalize process")
        await session.commit()
