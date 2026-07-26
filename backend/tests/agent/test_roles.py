"""Role definition tests."""
import pytest

from app.agent.roles import ROLE_CONFIGS, Role, get_role_config


def test_role_enum_members():
    assert Role.MANAGER.value == "MGR"
    assert Role.DEVELOPER_BE.value == "DEV_BE"
    assert Role.SUPPORT.value == "SUP"


def test_all_roles_have_config():
    for role in Role:
        assert role in ROLE_CONFIGS
        cfg = ROLE_CONFIGS[role]
        assert cfg.role == role
        assert cfg.system_prompt
        assert cfg.default_model
        assert cfg.max_steps > 0


def test_manager_has_no_mutating_tools():
    cfg = get_role_config(Role.MANAGER)
    assert "write_file" not in cfg.tool_names
    assert "edit_file" not in cfg.tool_names
    assert "run_subagent" in cfg.tool_names


def test_analyst_is_read_only():
    cfg = get_role_config(Role.ANALYST)
    for tool in ("write_file", "edit_file", "run_command"):
        assert tool not in cfg.tool_names


def test_developer_be_has_full_toolkit():
    cfg = get_role_config(Role.DEVELOPER_BE)
    for tool in ("read_file", "write_file", "edit_file", "run_command", "git_status"):
        assert tool in cfg.tool_names


def test_qa_runs_commands_but_no_writes():
    cfg = get_role_config(Role.QA)
    assert "run_command" in cfg.tool_names
    assert "write_file" not in cfg.tool_names
    assert "edit_file" not in cfg.tool_names


def test_role_config_is_frozen():
    from dataclasses import FrozenInstanceError

    cfg = get_role_config(Role.DEVELOPER_BE)
    with pytest.raises(FrozenInstanceError):
        cfg.max_steps = 999  # type: ignore[misc]


def test_unknown_role_raises():
    with pytest.raises(ValueError):
        get_role_config("UNKNOWN")  # type: ignore[arg-type]
