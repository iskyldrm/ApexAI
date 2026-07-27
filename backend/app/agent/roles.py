"""Role enum and RoleConfig — depends on prompts but not the other way around.

The Role enum lives here; the per-role prompt text is in `app.agent.prompts`.
"""
import os
from dataclasses import dataclass
from enum import Enum


def resolve_default_model_name() -> str:
    """Pick the model name based on environment.

    Resolution order:
    1. Explicit ``APEXAI_AGENT_MODEL`` env var (highest priority)
    2. ``OLLAMA_MODEL`` if ``OLLAMA_BASE_URL`` is set (local-first)
    3. ``ANTHROPIC_MODEL`` (your MiniMax / Claude Code config)
    4. ``gpt-4o`` (final fallback)

    The LiteLLMClient wraps this with the appropriate provider prefix
    (``ollama/`` or ``anthropic/``) when making the actual call.
    """
    explicit = os.environ.get("APEXAI_AGENT_MODEL")
    if explicit:
        return explicit
    if os.environ.get("OLLAMA_BASE_URL"):
        return os.environ.get("OLLAMA_MODEL", "llama3.2")
    if os.environ.get("ANTHROPIC_BASE_URL"):
        return os.environ.get("ANTHROPIC_MODEL", "MiniMax-M3")
    return "gpt-4o"


class Role(str, Enum):
    """Agent roles — narrow specialists, not a single generalist."""

    MANAGER = "MGR"           # Orchestration, git+PR, no direct code edits
    ANALYST = "ANL"           # Reads + plan generation, no edits
    DEVELOPER_FE = "DEV_FE"   # React/Next.js/CSS/UI
    DEVELOPER_BE = "DEV_BE"   # Python/FastAPI/DB
    QA = "QA"                 # Build + lint + test, no code edit
    PM = "PM"                 # Spec refinement, no code
    SUPPORT = "SUP"           # Logs + investigation, read-only


@dataclass(frozen=True)
class RoleConfig:
    """Per-role configuration."""

    role: Role
    system_prompt: str
    default_model: str
    tool_names: tuple[str, ...]
    max_steps: int

    def resolve_model(self) -> str:
        """Return the effective default model (resolves env at call time).

        If ``default_model`` was set at construction (e.g. an explicit
        override), use it. Otherwise look up the env-driven default
        (Ollama > MiniMax/Anthropic > gpt-4o).
        """
        if self.default_model:
            return self.default_model
        return resolve_default_model_name()


_DEFAULT_TOOLS_READ_ONLY: tuple[str, ...] = (
    "read_file",
    "list_dir",
    "find_files",
    "grep_search",
    "ast_grep",
    "git_status",
    "git_diff",
    "list_todos",
    "update_todo",
    "ask_user",
    "finish",
)

_DEFAULT_TOOLS_FULL: tuple[str, ...] = (
    *_DEFAULT_TOOLS_READ_ONLY,
    "write_file",
    "edit_file",
    "apply_patch",
    "run_command",
    "run_tests",
    "run_subagent",
    "http_request",
)


def _build_role_configs() -> dict[Role, RoleConfig]:
    """Lazy builder — imports prompts at call time to avoid circular import.

    Note: ``default_model`` is set lazily at first access via a
    ``property`` to support runtime env-var changes (monkeypatched tests,
    operator overrides).
    """
    from app.agent.prompts import get_prompt

    def _cfg(role: Role, tools: tuple[str, ...], max_steps: int) -> RoleConfig:
        return RoleConfig(
            role=role,
            system_prompt=get_prompt(role),
            default_model="",  # resolved on first read via _resolve_default_model()
            tool_names=tools,
            max_steps=max_steps,
        )

    return {
        Role.MANAGER: _cfg(
            Role.MANAGER,
            (*_DEFAULT_TOOLS_READ_ONLY, "run_subagent"),
            max_steps=40,
        ),
        Role.ANALYST: _cfg(Role.ANALYST, _DEFAULT_TOOLS_READ_ONLY, max_steps=25),
        Role.DEVELOPER_FE: _cfg(Role.DEVELOPER_FE, _DEFAULT_TOOLS_FULL, max_steps=60),
        Role.DEVELOPER_BE: _cfg(Role.DEVELOPER_BE, _DEFAULT_TOOLS_FULL, max_steps=60),
        Role.QA: _cfg(
            Role.QA,
            (*_DEFAULT_TOOLS_READ_ONLY, "run_command", "run_tests"),
            max_steps=30,
        ),
        Role.PM: _cfg(
            Role.PM,
            ("read_file", "ask_user", "list_todos", "update_todo", "finish"),
            max_steps=15,
        ),
        Role.SUPPORT: _cfg(
            Role.SUPPORT,
            (*_DEFAULT_TOOLS_READ_ONLY, "run_command"),
            max_steps=25,
        ),
    }


ROLE_CONFIGS: dict[Role, RoleConfig] = _build_role_configs()


def get_role_config(role: Role) -> RoleConfig:
    cfg = ROLE_CONFIGS.get(role)
    if not cfg:
        raise ValueError(f"Unknown role: {role}")
    return cfg
