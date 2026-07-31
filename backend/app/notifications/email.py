"""Email service for Sub-System C.

Uses aiosmtplib to send via SMTP. Disabled gracefully when SMTP env
vars are missing — the function logs a warning and returns False.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class SMTPConfig:
    host: str
    port: int
    user: str | None
    password: str | None
    from_addr: str
    use_tls: bool

    @classmethod
    def from_env(cls) -> "SMTPConfig | None":
        host = os.environ.get("SMTP_HOST")
        port_str = os.environ.get("SMTP_PORT")
        from_addr = os.environ.get("SMTP_FROM")
        if not host or not from_addr:
            return None
        try:
            port = int(port_str) if port_str else 587
        except ValueError:
            port = 587
        return cls(
            host=host,
            port=port,
            user=os.environ.get("SMTP_USER"),
            password=os.environ.get("SMTP_PASSWORD"),
            from_addr=from_addr,
            use_tls=os.environ.get("SMTP_TLS", "true").lower() in ("1", "true", "yes"),
        )


def render_template(name: str, context: dict[str, Any]) -> tuple[str, str]:
    """Render a simple Jinja-style template. Returns (subject, html_body).

    Templates live in this module as constants — no external file loading.
    """
    if name == "task.assigned":
        subject = f"[ApexAI] Task assigned: {context['task_title']}"
        body = (
            f"<p>Hi {context['user_name']},</p>"
            f"<p>You have been assigned a task: <strong>{context['task_title']}</strong></p>"
            f"<p>{context.get('task_description', '')}</p>"
            f'<p><a href="{context.get("link", "#")}">View task</a></p>'
        )
    elif name == "task.completed":
        subject = f"[ApexAI] Task completed: {context['task_title']}"
        body = (
            f"<p>Hi {context['user_name']},</p>"
            f"<p>Task <strong>{context['task_title']}</strong> has been marked done.</p>"
        )
    elif name == "agent.failed":
        subject = f"[ApexAI] Agent run failed: {context.get('agent_run_id', 'unknown')}"
        body = (
            f"<p>The agent run failed with:</p>"
            f"<pre>{context.get('error', 'unknown error')}</pre>"
            f'<p><a href="{context.get("link", "#")}">Inspect run</a></p>'
        )
    elif name in ("budget.daily_50", "budget.daily_90", "budget.daily_100"):
        pct_map = {"budget.daily_50": 50, "budget.daily_90": 90, "budget.daily_100": 100}
        pct = pct_map[name]
        subject = f"[ApexAI] Daily budget {pct}% used"
        body = (
            f"<p>Your org has used {pct}% of today's AI token budget.</p>"
            f"<ul>"
            f"<li>Used: {context.get('tokens_used', '?')}</li>"
            f"<li>Cap: {context.get('cap', '?')}</li>"
            f"</ul>"
        )
    elif name == "test_run.failed":
        subject = f"[ApexAI] Test run failed: {context.get('project_path', '?')}"
        body = (
            f"<p>{context.get('failed', 0)} of {context.get('total', 0)} tests failed.</p>"
            f'<p><a href="{context.get("link", "#")}">Inspect</a></p>'
        )
    else:
        subject = f"[ApexAI] {name}"
        body = f"<p>{context}</p>"
    return subject, body


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    config: SMTPConfig | None = None,
) -> bool:
    """Send an email. Returns True on success, False on failure / no SMTP."""
    cfg = config or SMTPConfig.from_env()
    if cfg is None:
        logger.debug("SMTP not configured — skipping email to=%s subject=%r", to, subject)
        return False

    msg = EmailMessage()
    msg["From"] = cfg.from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("HTML email — please view in an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    try:
        import aiosmtplib

        await aiosmtplib.send(
            msg,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.user,
            password=cfg.password,
            use_tls=cfg.use_tls,
        )
        logger.info("Sent email to=%s subject=%r", to, subject)
        return True
    except Exception as e:
        logger.warning("Failed to send email to=%s: %s", to, e)
        return False


async def send_notification_email(
    *,
    kind: str,
    to: str,
    context: dict[str, Any],
    user_prefs_enabled: bool = True,
    config: SMTPConfig | None = None,
) -> bool:
    """High-level helper: render + send for a known notification kind."""
    if not user_prefs_enabled:
        logger.debug("User has email disabled for kind=%s", kind)
        return False
    subject, body = render_template(kind, context)
    return await send_email(to=to, subject=subject, html_body=body, config=config)