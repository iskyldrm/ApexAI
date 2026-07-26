"""Role definitions for sub-system A.

Each role has a system prompt, default model, allowed tools, and step limit.
The runtime picks the right role based on the task type.
"""
from dataclasses import dataclass, field
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
    "grep_search",
    "ast_grep",
    "git_status",
    "git_diff",
)

_DEFAULT_TOOLS_FULL: tuple[str, ...] = (
    *_DEFAULT_TOOLS_READ_ONLY,
    "write_file",
    "edit_file",
    "run_command",
)

_BASE_PROMPT = (
    "You are a focused specialist. Use the tools available to you. "
    "When the task is complete, call the `finish` tool with a brief summary."
)


def _role_config(
    role: Role,
    description: str,
    model: str,
    tools: tuple[str, ...],
    max_steps: int,
) -> RoleConfig:
    return RoleConfig(
        role=role,
        system_prompt=f"{_BASE_PROMPT}\n\nRole: {role.value}\n{description}",
        default_model=model,
        tool_names=tools,
        max_steps=max_steps,
    )


ROLE_CONFIGS: dict[Role, RoleConfig] = {
    Role.MANAGER: _role_config(
        Role.MANAGER,
        "Orchestrate work between specialists. Route tasks, manage git branches, "
        "open PRs. Do NOT modify code directly — delegate to DEV roles.",
        "gpt-4o",
        (*_DEFAULT_TOOLS_READ_ONLY, "run_subagent", "git_status", "git_diff"),
        max_steps=40,
    ),
    Role.ANALYST: _role_config(
        Role.ANALYST,
        "Analyze projects, generate plans, identify files. Read-only — never write or edit code.",
        "gpt-4o",
        _DEFAULT_TOOLS_READ_ONLY,
        max_steps=25,
    ),
    Role.DEVELOPER_FE: _role_config(
        Role.DEVELOPER_FE,
        "Frontend specialist. React, Next.js, CSS, UI. Use the edit_file tool "
        "for precise edits and write_file for new files.",
        "claude-sonnet-4-5",
        _DEFAULT_TOOLS_FULL,
        max_steps=60,
    ),
    Role.DEVELOPER_BE: _role_config(
        Role.DEVELOPER_BE,
        "Backend specialist. Python, FastAPI, SQLAlchemy, Go, Rust. Run tests "
        "with pytest via run_command.",
        "claude-sonnet-4-5",
        _DEFAULT_TOOLS_FULL,
        max_steps=60,
    ),
    Role.QA: _role_config(
        Role.QA,
        "Quality assurance. Run build, lint, and tests. Verify changes work. "
        "Do not edit code — flag issues instead.",
        "gpt-4o",
        (*_DEFAULT_TOOLS_READ_ONLY, "run_command"),
        max_steps=30,
    ),
    Role.PM: _role_config(
        Role.PM,
        "Product manager. Refine specs, write stories, prioritize. No code.",
        "gpt-4o-mini",
        (),
        max_steps=15,
    ),
    Role.SUPPORT: _role_config(
        Role.SUPPORT,
        "Support / investigation. Read logs, run diagnostics, read-only commands.",
        "gpt-4o-mini",
        (*_DEFAULT_TOOLS_READ_ONLY, "run_command"),
        max_steps=25,
    ),
}


def get_role_config(role: Role) -> RoleConfig:
    cfg = ROLE_CONFIGS.get(role)
    if not cfg:
        raise ValueError(f"Unknown role: {role}")
    return cfg
