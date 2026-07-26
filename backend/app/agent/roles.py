"""Role enum and RoleConfig — depends on prompts but not the other way around.

The Role enum lives here; the per-role prompt text is in `app.agent.prompts`.
"""
from dataclasses import dataclass
from enum import Enum


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
    """Lazy builder — imports prompts at call time to avoid circular import."""
    from app.agent.prompts import get_prompt

    def _cfg(role: Role, model: str, tools: tuple[str, ...], max_steps: int) -> RoleConfig:
        return RoleConfig(
            role=role,
            system_prompt=get_prompt(role),
            default_model=model,
            tool_names=tools,
            max_steps=max_steps,
        )

    return {
        Role.MANAGER: _cfg(
            Role.MANAGER, "gpt-4o",
            (*_DEFAULT_TOOLS_READ_ONLY, "run_subagent"),
            max_steps=40,
        ),
        Role.ANALYST: _cfg(Role.ANALYST, "gpt-4o", _DEFAULT_TOOLS_READ_ONLY, max_steps=25),
        Role.DEVELOPER_FE: _cfg(
            Role.DEVELOPER_FE, "claude-sonnet-4-5", _DEFAULT_TOOLS_FULL, max_steps=60,
        ),
        Role.DEVELOPER_BE: _cfg(
            Role.DEVELOPER_BE, "claude-sonnet-4-5", _DEFAULT_TOOLS_FULL, max_steps=60,
        ),
        Role.QA: _cfg(
            Role.QA, "gpt-4o",
            (*_DEFAULT_TOOLS_READ_ONLY, "run_command", "run_tests"),
            max_steps=30,
        ),
        Role.PM: _cfg(
            Role.PM, "gpt-4o-mini",
            ("read_file", "ask_user", "list_todos", "update_todo", "finish"),
            max_steps=15,
        ),
        Role.SUPPORT: _cfg(
            Role.SUPPORT, "gpt-4o-mini",
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
