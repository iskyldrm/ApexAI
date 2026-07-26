"""Tool parser tests — covers all 4 tiers."""
from app.agent.tool_parser import parse_tool_calls


def test_tier_1_native_tool_calls():
    """OpenAI / Anthropic structured format."""
    text = "I'll read the file."
    native = [
        {
            "id": "call_1",
            "name": "read_file",
            "arguments": {"path": "/tmp/x.py"},
        }
    ]
    result = parse_tool_calls(text, native_tool_calls=native)
    assert len(result) == 1
    assert result[0].name == "read_file"
    assert result[0].arguments == {"path": "/tmp/x.py"}
    assert result[0].id == "call_1"


def test_tier_2_tool_call_xml():
    """Qwen / Ollama style wrapper."""
    text = (
        "Let me check the file.\n"
        "<tool_call>\n"
        '{"name": "read_file", "arguments": {"path": "/tmp/app.py"}}\n'
        "</tool_call>"
    )
    result = parse_tool_calls(text)
    assert len(result) == 1
    assert result[0].name == "read_file"
    assert result[0].arguments == {"path": "/tmp/app.py"}


def test_tier_3_markdown_json_block():
    text = (
        "I'll write a new file.\n"
        "```json\n"
        '{"name": "write_file", "arguments": {"path": "/tmp/new.py", "content": "x"}}\n'
        "```\n"
    )
    result = parse_tool_calls(text)
    assert len(result) == 1
    assert result[0].name == "write_file"
    assert result[0].arguments["path"] == "/tmp/new.py"


def test_tier_4_balanced_json_in_prose():
    text = (
        "Here is my plan: {\"name\": \"list_dir\", \"arguments\": {\"path\": \"/tmp\"}} "
        "and then we can continue."
    )
    result = parse_tool_calls(text)
    assert len(result) == 1
    assert result[0].name == "list_dir"
    assert result[0].arguments == {"path": "/tmp"}


def test_no_tool_calls_returns_empty():
    assert parse_tool_calls("just plain text response") == []
    assert parse_tool_calls(None) == []
    assert parse_tool_calls("", []) == []


def test_multiple_tier_2_calls_in_one_text():
    text = (
        "<tool_call>\n"
        '{"name": "read_file", "arguments": {"path": "/a.py"}}\n'
        "</tool_call>\n"
        "<tool_call>\n"
        '{"name": "list_dir", "arguments": {"path": "/tmp"}}\n'
        "</tool_call>"
    )
    result = parse_tool_calls(text)
    assert len(result) == 2
    assert result[0].name == "read_file"
    assert result[1].name == "list_dir"


def test_tier_1_takes_priority_over_tier_2():
    """When both native and text-embedded are present, native wins."""
    text = (
        '<tool_call>\n{"name": "read_file", "arguments": {"path": "/embedded"}}\n</tool_call>'
    )
    native = [{"name": "list_dir", "arguments": {"path": "/native"}}]
    result = parse_tool_calls(text, native_tool_calls=native)
    assert len(result) == 1
    assert result[0].name == "list_dir"


def test_alternate_field_names():
    """Some models emit `tool` + `input` instead of `name` + `arguments`."""
    text = (
        '<tool_call>\n{"tool": "grep_search", "input": {"pattern": "TODO", "path": "/src"}}\n</tool_call>'
    )
    result = parse_tool_calls(text)
    assert len(result) == 1
    assert result[0].name == "grep_search"
    assert result[0].arguments == {"pattern": "TODO", "path": "/src"}


def test_string_arguments_parsed():
    text = (
        '<tool_call>\n{"name": "edit_file", "arguments": "{\\"path\\": \\"/x\\"}"}\n</tool_call>'
    )
    result = parse_tool_calls(text)
    assert len(result) == 1
    assert result[0].arguments == {"path": "/x"}


def test_invalid_json_blocks_skipped_silently():
    text = (
        '<tool_call>\n{not valid json}\n</tool_call>\n'
        '```json\n{"name": "list_dir", "arguments": {"path": "/y"}}\n```'
    )
    result = parse_tool_calls(text)
    # tier 2 fails, tier 3 succeeds
    assert len(result) == 1
    assert result[0].name == "list_dir"
