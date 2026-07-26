"""Safety systems for the agent loop.

Four independent guards, each testable in isolation. The AgentLoop will
check them after every tool execution and after every LLM call.

- ``CircuitBreaker`` — trip after N consecutive failures of the same tool.
  ApexAITeam pattern: 3× same tool fail → inject guidance, suggest a
  different approach. Resets on success.

- ``RepetitionDetector`` — trip when the same tool is called too many
  times. Read-only tools get a higher threshold (6) since the agent may
  legitimately need to inspect many files; mutating tools get 12.

- ``EditFailureTracker`` — cumulative count of failures from edit-class
  tools (write_file, edit_file, apply_patch). 5 failures → inject
  guidance. Doesn't reset on success (the agent should pivot strategy
  once edits are flailing).

- ``TokenBudgetEnforcer`` — per-run hard limit (default 500K tokens) and
  per-org daily cap (read from the settings table). Exceeded → finish
  the loop with a clear summary.

Each guard exposes:
- ``record_success(name)`` / ``record_failure(name)`` — called by the loop
- ``tripped`` property — true if the guard wants the loop to stop
- ``guidance_message()`` — text to inject into the conversation
- ``reset()`` — clear state (used at the start of a new agent run)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Trip after N consecutive failures of the same tool name."""

    def __init__(self, max_consecutive: int = 3) -> None:
        self.max_consecutive = max_consecutive
        self._consecutive: dict[str, int] = {}
        self._tripped_for: str | None = None
        self._guidance: str | None = None

    def record_failure(self, tool_name: str) -> None:
        self._consecutive[tool_name] = self._consecutive.get(tool_name, 0) + 1
        if self._consecutive[tool_name] >= self.max_consecutive:
            self._tripped_for = tool_name
            self._guidance = (
                f"⚠️ Tool {tool_name!r} has failed {self._consecutive[tool_name]} times in a row. "
                f"Stop using it and try a different approach. Consider using a different tool "
                f"or breaking the task into smaller steps."
            )

    def record_success(self, tool_name: str) -> None:
        self._consecutive[tool_name] = 0
        if self._tripped_for == tool_name:
            self._tripped_for = None
            self._guidance = None

    @property
    def tripped(self) -> bool:
        return self._tripped_for is not None

    def guidance_message(self) -> str | None:
        return self._guidance

    def reset(self) -> None:
        self._consecutive.clear()
        self._tripped_for = None
        self._guidance = None


# ---------------------------------------------------------------------------
# RepetitionDetector
# ---------------------------------------------------------------------------


class RepetitionDetector:
    """Trip when a tool is called too many times.

    Read-only tools (no side effects) get a higher threshold since the
    agent often needs to inspect many files. Mutating tools have a lower
    limit — repeated writes usually indicate a loop bug.
    """

    READ_LIMIT = 6
    MUTATING_LIMIT = 12

    def __init__(
        self,
        read_limit: int = READ_LIMIT,
        mutating_limit: int = MUTATING_LIMIT,
    ) -> None:
        self.read_limit = read_limit
        self.mutating_limit = mutating_limit
        self._read_calls: dict[tuple[str, str], int] = {}  # (tool, args_hash) → count
        self._mutating_calls: dict[str, int] = {}  # tool → count
        self._tripped_for: str | None = None
        self._guidance: str | None = None

    def _args_hash(self, args: dict[str, Any]) -> str:
        # Hash by sorted args — read tools with different paths are different
        try:
            return json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return repr(args)

    def record(self, tool_name: str, args: dict[str, Any], is_mutating: bool) -> None:
        if is_mutating:
            count = self._mutating_calls.get(tool_name, 0) + 1
            self._mutating_calls[tool_name] = count
            if count > self.mutating_limit:
                self._tripped_for = tool_name
                self._guidance = (
                    f"⚠️ Mutating tool {tool_name!r} has been called {count} times. "
                    f"This is the limit. Stop and consider a different strategy — "
                    f"perhaps the task is already done or the changes are being "
                    f"reverted each time."
                )
        else:
            key = (tool_name, self._args_hash(args))
            count = self._read_calls.get(key, 0) + 1
            self._read_calls[key] = count
            if count > self.read_limit:
                self._tripped_for = tool_name
                self._guidance = (
                    f"⚠️ Read tool {tool_name!r} called with the same arguments "
                    f"{count} times. Stop and try a different query — the same "
                    f"call won't return new information."
                )

    @property
    def tripped(self) -> bool:
        return self._tripped_for is not None

    def guidance_message(self) -> str | None:
        return self._guidance

    def reset(self) -> None:
        self._read_calls.clear()
        self._mutating_calls.clear()
        self._tripped_for = None
        self._guidance = None


# ---------------------------------------------------------------------------
# EditFailureTracker
# ---------------------------------------------------------------------------


_EDIT_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})


class EditFailureTracker:
    """Track cumulative failures of edit-class tools.

    Unlike the circuit breaker, this does NOT reset on success — once the
    agent has flailed 5 times, force it to stop and re-evaluate.
    """

    LIMIT = 5

    def __init__(self, limit: int = LIMIT) -> None:
        self.limit = limit
        self._failures: dict[str, int] = {}
        self._total_failures = 0
        self._tripped = False
        self._guidance: str | None = None

    def record_failure(self, tool_name: str) -> None:
        if tool_name not in _EDIT_TOOLS:
            return
        self._failures[tool_name] = self._failures.get(tool_name, 0) + 1
        self._total_failures += 1
        if self._total_failures >= self.limit and not self._tripped:
            self._tripped = True
            self._guidance = (
                f"⚠️ {self._total_failures} edit failures total. Stop trying to "
                f"modify code — re-read the file, check the current state, and "
                f"form a new hypothesis before editing again. Consider delegating "
                f"to a fresh sub-agent if edits keep failing."
            )

    def record_success(self, tool_name: str) -> None:
        # Don't reset the counter — see class docstring
        pass

    @property
    def tripped(self) -> bool:
        return self._tripped

    def guidance_message(self) -> str | None:
        return self._guidance

    def reset(self) -> None:
        self._failures.clear()
        self._total_failures = 0
        self._tripped = False
        self._guidance = None


# ---------------------------------------------------------------------------
# TokenBudgetEnforcer
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenBudgetExceeded(Exception):
    """Raised when the per-run or per-org budget is exceeded."""

    def __init__(self, scope: str, used: int, limit: int) -> None:
        self.scope = scope  # "run" or "org_daily"
        self.used = used
        self.limit = limit
        super().__init__(f"{scope} budget exceeded: {used}/{limit} tokens")


class TokenBudgetEnforcer:
    """Per-run hard limit + per-org daily cap.

    Per-org daily cap is read from the settings table on first check:
    ``key = "ai.daily_token_budget.<org_id>"`` → integer.
    """

    DEFAULT_RUN_LIMIT = 500_000

    def __init__(
        self,
        per_run_limit: int = DEFAULT_RUN_LIMIT,
        org_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self.per_run_limit = per_run_limit
        self.org_id = org_id
        self._session_factory = session  # held to look up settings lazily
        self._usage = TokenUsage()

    def record(self, input_tokens: int, output_tokens: int) -> None:
        self._usage.input_tokens += input_tokens
        self._usage.output_tokens += output_tokens

    @property
    def usage(self) -> TokenUsage:
        return self._usage

    async def check(self) -> None:
        """Raise TokenBudgetExceeded if either limit is breached.

        Call this after each LLM call. The per-org daily cap is loaded
        once (cached for the run).
        """
        if self._usage.total > self.per_run_limit:
            raise TokenBudgetExceeded("run", self._usage.total, self.per_run_limit)
        if self.org_id and self._session_factory is not None:
            cap = await self._load_org_cap()
            if cap is not None:
                # Sum today's usage from the DB
                from app.models.token_usage import TokenUsage as TU
                from sqlalchemy import func

                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                stmt = select(
                    func.coalesce(
                        func.sum(TU.input_tokens + TU.output_tokens), 0
                    )
                ).where(
                    TU.org_id == self.org_id,
                    TU.created_at >= today_start,
                )
                result = await self._session_factory.execute(stmt)
                used_today = int(result.scalar() or 0) + self._usage.total
                if used_today > cap:
                    raise TokenBudgetExceeded("org_daily", used_today, cap)

    async def _load_org_cap(self) -> int | None:
        if self._session_factory is None:
            return None
        result = await self._session_factory.execute(
            select(Setting).where(
                Setting.scope == "org",
                Setting.scope_id == self.org_id,
                Setting.key == "ai.daily_token_budget",
            )
        )
        setting = result.scalar_one_or_none()
        if setting is None:
            return None
        val = setting.value
        if isinstance(val, dict):
            val = val.get("tokens")
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
        return None
