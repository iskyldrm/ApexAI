"""Email 'log' writer — stubs real SMTP for now. Spec §1.3 notes email deferred.

In dev/test, emails are appended to /tmp/apexai_emails.log so they can be
inspected by tests and operators.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("/tmp/apexai_emails.log")


def log_email(to: str, subject: str, body: str) -> None:
    """Write a JSON line to the email log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "to": to,
                    "subject": subject,
                    "body": body,
                }
            )
            + "\n"
        )