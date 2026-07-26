"""4-tier tool call parser.

Different models emit tool calls in different formats. We try in order:

1. Native ``tool_calls`` field (OpenAI / Anthropic structured format)
2. ``<tool_call>{...}</tool_call>`` XML wrapper (Qwen, Ollama)
3. Markdown ```json{...}``` blocks
4. Balanced-brace extraction (regex backtrack to longest valid JSON)

Each tier returns a list of ``{"name": str, "arguments": dict, "id": str}``
dicts. Failures fall through to the next tier.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


# Tier 2: <tool_call>{...}</tool_call>
_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

# Tier 3: ```json ... ``` blocks
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Try to parse text as a JSON object. Return None on failure."""
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_balanced_json(text: str) -> dict[str, Any] | None:
    """Tier 4: scan for the longest balanced ``{...}`` substring that parses as JSON with a tool name + arguments."""
    best: dict[str, Any] | None = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[i : j + 1]
                    parsed = _try_parse_json(candidate)
                    if parsed and ("name" in parsed or "tool" in parsed):
                        best = parsed
                    break
    return best


def _normalize_tool_call(obj: dict[str, Any]) -> ParsedToolCall | None:
    """Convert a parsed JSON object to a ``ParsedToolCall``.

    Accepts several shapes:
    - ``{"name": "foo", "arguments": {...}}`` (camelCase)
    - ``{"name": "foo", "parameters": {...}}``
    - ``{"tool": "foo", "input": {...}}``
    """
    name = obj.get("name") or obj.get("tool") or obj.get("tool_name")
    if not name or not isinstance(name, str):
        return None
    args = (
        obj.get("arguments")
        or obj.get("parameters")
        or obj.get("input")
        or obj.get("args")
        or {}
    )
    if isinstance(args, str):
        parsed_args = _try_parse_json(args)
        args = parsed_args if parsed_args is not None else {}
    if not isinstance(args, dict):
        args = {}
    return ParsedToolCall(
        name=name,
        arguments=args,
        id=obj.get("id") or obj.get("tool_call_id"),
    )


def parse_tool_calls(
    text: str | None,
    native_tool_calls: list[dict[str, Any]] | None = None,
) -> list[ParsedToolCall]:
    """Run all 4 tiers and return the first non-empty list of tool calls.

    ``native_tool_calls`` is the structured field returned by OpenAI /
    Anthropic APIs (tier 1). ``text`` is the raw content which may contain
    embedded tool calls (tiers 2-4).
    """
    # Tier 1: native structured field
    if native_tool_calls:
        out: list[ParsedToolCall] = []
        for tc in native_tool_calls:
            normalized = _normalize_tool_call(tc)
            if normalized:
                out.append(normalized)
        if out:
            return out

    if not text:
        return []

    # Tier 2: <tool_call>{...}</tool_call>
    out = []
    for match in _TOOL_CALL_BLOCK_RE.finditer(text):
        obj = _try_parse_json(match.group(1))
        if obj is None:
            continue
        normalized = _normalize_tool_call(obj)
        if normalized:
            out.append(normalized)
    if out:
        return out

    # Tier 3: ```json ... ```
    out = []
    for match in _JSON_BLOCK_RE.finditer(text):
        obj = _try_parse_json(match.group(1))
        if obj is None:
            continue
        normalized = _normalize_tool_call(obj)
        if normalized:
            out.append(normalized)
    if out:
        return out

    # Tier 4: balanced JSON
    obj = _extract_balanced_json(text)
    if obj is not None:
        normalized = _normalize_tool_call(obj)
        if normalized:
            return [normalized]

    return []
