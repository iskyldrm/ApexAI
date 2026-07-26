"""Tool registry tests."""
import pytest

from app.agent.tools import Tool, ToolContext, ToolRegistry, registry
from app.agent.tools.base import ToolResult
from app.agent.roles import Role


async def _echo_handler(ctx: ToolContext, args: dict) -> ToolResult:
    return ToolResult(output=str(args))


def _make_tool(name: str, mutating: bool = False) -> Tool:
    return Tool(
        name=name,
        description=f"echo {name}",
        parameters_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
        handler=_echo_handler,
        is_mutating=mutating,
    )


def test_register_and_get():
    r = ToolRegistry()
    t = _make_tool("echo")
    r.register(t)
    assert r.get("echo") is t
    assert r.all() == [t]


def test_register_duplicate_raises():
    r = ToolRegistry()
    t = _make_tool("echo")
    r.register(t)
    with pytest.raises(ValueError):
        r.register(t)


def test_get_unknown_returns_none():
    r = ToolRegistry()
    assert r.get("missing") is None


def test_get_for_role_filters_by_visibility():
    r = ToolRegistry()
    visible = _make_tool("visible")
    filtered = _make_tool("filtered")
    filtered.role_visibility = (Role.MANAGER,)
    r.register(visible)
    r.register(filtered)
    open_tools = r.get_for_role(Role.DEVELOPER_BE)
    assert visible in open_tools
    assert filtered not in open_tools
    mgr_tools = r.get_for_role(Role.MANAGER)
    assert visible in mgr_tools
    assert filtered in mgr_tools


def test_tool_to_openai_schema():
    t = _make_tool("echo")
    schema = t.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert "parameters" in schema["function"]


def test_global_registry_singleton():
    from app.agent.tools import registry as r1
    from app.agent.tools import registry as r2
    assert r1 is r2


def test_registry_reset_clears():
    r = ToolRegistry()
    r.register(_make_tool("x"))
    assert len(r.all()) == 1
    r.reset()
    assert r.all() == []
