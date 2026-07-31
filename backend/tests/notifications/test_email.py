"""Tests for email notifications (C.1-C.3)."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.notifications.email import (
    SMTPConfig,
    render_template,
    send_email,
    send_notification_email,
)


# -------------------- SMTPConfig.from_env --------------------


def test_smtp_config_from_env_when_all_set(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_FROM", "noreply@test.local")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    cfg = SMTPConfig.from_env()
    assert cfg is not None
    assert cfg.host == "smtp.test.local"
    assert cfg.port == 587
    assert cfg.user == "user"
    assert cfg.password == "secret"
    assert cfg.use_tls is True  # default


def test_smtp_config_defaults_port(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_FROM", "noreply@test.local")
    monkeypatch.delenv("SMTP_PORT", raising=False)

    cfg = SMTPConfig.from_env()
    assert cfg.port == 587


def test_smtp_config_returns_none_without_host(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert SMTPConfig.from_env() is None


def test_smtp_config_returns_none_without_from(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.delenv("SMTP_FROM", raising=False)
    assert SMTPConfig.from_env() is None


def test_smtp_config_tls_disabled(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.local")
    monkeypatch.setenv("SMTP_FROM", "noreply@test.local")
    monkeypatch.setenv("SMTP_TLS", "false")
    cfg = SMTPConfig.from_env()
    assert cfg.use_tls is False


# -------------------- Template rendering --------------------


def test_render_task_assigned():
    subject, body = render_template("task.assigned", {
        "task_title": "Fix login bug",
        "user_name": "İsak",
        "link": "https://app/tasks/123",
    })
    assert "Fix login bug" in subject
    assert "İsak" in body
    assert "https://app/tasks/123" in body


def test_render_task_completed():
    subject, body = render_template("task.completed", {
        "task_title": "Setup CI",
        "user_name": "Test",
    })
    assert "Setup CI" in subject
    assert "marked done" in body


def test_render_agent_failed():
    subject, body = render_template("agent.failed", {
        "agent_run_id": "abc-123",
        "error": "Connection refused",
    })
    assert "abc-123" in subject
    assert "Connection refused" in body


@pytest.mark.parametrize("kind,pct", [
    ("budget.daily_50", "50"),
    ("budget.daily_90", "90"),
    ("budget.daily_100", "100"),
])
def test_render_budget_alerts(kind, pct):
    subject, body = render_template(kind, {
        "tokens_used": 500,
        "cap": 1000,
    })
    assert f"{pct}%" in subject
    assert "500" in body
    assert "1000" in body


def test_render_test_run_failed():
    subject, body = render_template("test_run.failed", {
        "project_path": "/workspace/app",
        "failed": 3,
        "total": 42,
        "link": "https://app/runs/1",
    })
    assert "3" in body or "/workspace/app" in subject
    assert "42" in body


def test_render_unknown_kind_returns_generic():
    """Unknown kinds still produce a sensible subject + body (no crash)."""
    subject, body = render_template("weird.event", {"foo": "bar"})
    assert "weird.event" in subject
    assert "bar" in body


# -------------------- send_email --------------------


@pytest.mark.asyncio
async def test_send_email_returns_false_when_no_smtp_config(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    result = await send_email(to="user@test.local", subject="x", html_body="<p>x</p>")
    assert result is False


@pytest.mark.asyncio
async def test_send_email_invokes_aiosmtplib_when_configured():
    cfg = SMTPConfig(
        host="smtp.test.local",
        port=587,
        user="u",
        password="p",
        from_addr="noreply@test.local",
        use_tls=True,
    )
    fake_send = AsyncMock()

    # Patch the aiosmtplib module globally (it's imported lazily inside send_email)
    with patch("aiosmtplib.send", fake_send):
        result = await send_email(
            to="user@test.local",
            subject="Test",
            html_body="<p>Hello</p>",
            config=cfg,
        )

    assert result is True
    fake_send.assert_called_once()
    call_kwargs = fake_send.call_args.kwargs
    assert call_kwargs["hostname"] == "smtp.test.local"
    assert call_kwargs["port"] == 587
    assert call_kwargs["use_tls"] is True


@pytest.mark.asyncio
async def test_send_email_swallows_exceptions():
    """Failed SMTP delivery returns False, never raises."""
    cfg = SMTPConfig(
        host="smtp.test.local",
        port=587,
        user=None,
        password=None,
        from_addr="noreply@test.local",
        use_tls=False,
    )
    fake_send = AsyncMock(side_effect=RuntimeError("connection refused"))

    with patch("aiosmtplib.send", fake_send):
        result = await send_email(
            to="user@test.local",
            subject="x",
            html_body="<p>x</p>",
            config=cfg,
        )

    assert result is False


@pytest.mark.asyncio
async def test_send_notification_email_high_level(monkeypatch):
    """send_notification_email renders + sends."""
    fake_send = AsyncMock()
    cfg = SMTPConfig(
        host="smtp.test.local", port=587, user=None, password=None,
        from_addr="noreply@test.local", use_tls=False,
    )
    with patch("aiosmtplib.send", fake_send):
        result = await send_notification_email(
            kind="task.assigned",
            to="user@test.local",
            context={"task_title": "X", "user_name": "Test"},
            user_prefs_enabled=True,
            config=cfg,
        )
    assert result is True
    fake_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_notification_email_respects_prefs(monkeypatch):
    """user_prefs_enabled=False skips the send."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    result = await send_notification_email(
        kind="task.assigned",
        to="user@test.local",
        context={"task_title": "X", "user_name": "Test"},
        user_prefs_enabled=False,
    )
    assert result is False