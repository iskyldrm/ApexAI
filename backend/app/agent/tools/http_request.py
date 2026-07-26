"""http_request tool — outbound HTTP with URL allowlist + SSRF guard.

Allowed hosts are passed at construction time (per-tenant config). The tool
additionally blocks well-known internal metadata endpoints (AWS / GCP / Azure)
and non-HTTP(S) schemes.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.agent.sandbox import truncate_output
from app.agent.tools.base import Tool, ToolContext, ToolResult


# SSRF blocklist — never reachable, even if a host is in the allowlist.
_METADATA_HOSTS: frozenset[str] = frozenset({
    "169.254.169.254",          # AWS / GCP / Azure metadata
    "metadata.google.internal",
    "metadata.azure.com",
    "169.254.169.253",          # AWS IMDSv2 alt
    "fd00:ec2::254",            # AWS IMDSv2 IPv6
})


class HttpRequestTool(Tool):
    """Make outbound HTTP calls. URL allowlist enforced at construction."""

    _max_response_bytes = 100_000

    def __init__(self, allowed_hosts: tuple[str, ...] = ()) -> None:
        super().__init__(
            name="http_request",
            description=(
                "Make an outbound HTTP request to a URL. The host must be in the "
                "tenant's allowlist. Returns the response body (truncated to 100KB). "
                "Supports GET/POST/PUT/PATCH/DELETE. POST/PUT/PATCH accept a JSON body."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL, must be http(s)"},
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                        "default": "GET",
                    },
                    "body": {"type": "string", "description": "JSON body for POST/PUT/PATCH"},
                    "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60, "default": 30},
                },
                "required": ["url"],
            },
            handler=self._run,
            is_mutating=False,  # set dynamically by method check inside _run
            required_permissions=("network:read",),
        )
        self._allowed_hosts = tuple(h.lower() for h in allowed_hosts)

    def _authorize(self, url: str) -> tuple[bool, str]:
        """Return (ok, error_message)."""
        try:
            parsed = urlparse(url)
        except ValueError as e:
            return False, f"Invalid URL: {e}"
        if parsed.scheme not in ("http", "https"):
            return False, f"Scheme not allowed: {parsed.scheme!r} (only http/https)"
        host = (parsed.hostname or "").lower()
        if host in _METADATA_HOSTS:
            return False, f"Refusing to call metadata endpoint: {host}"
        if self._allowed_hosts and host not in self._allowed_hosts:
            return False, f"Host {host!r} not in allowlist {self._allowed_hosts}"
        return True, ""

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        ok, err = self._authorize(args["url"])
        if not ok:
            return ToolResult(ok=False, error=err)

        method = args.get("method", "GET")
        body = args.get("body")
        headers = args.get("headers") or {}
        timeout = args.get("timeout_seconds", 30)

        if method in ("POST", "PUT", "PATCH") and body and "content-type" not in {k.lower() for k in headers}:
            headers = {**headers, "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.request(method, args["url"], content=body, headers=headers)
        except httpx.TimeoutException:
            return ToolResult(ok=False, error=f"Timeout after {timeout}s")
        except httpx.HTTPError as e:
            return ToolResult(ok=False, error=f"HTTP error: {e}")

        truncated = truncate_output(response.text, self._max_response_bytes)
        return ToolResult(
            ok=response.is_success,
            output=truncated,
            error=None if response.is_success else f"HTTP {response.status_code}",
            metadata={
                "status_code": response.status_code,
                "url": args["url"],
                "method": method,
            },
        )
