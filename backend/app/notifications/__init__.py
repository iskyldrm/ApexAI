"""Sub-System C — Notifications.

In-app + email notifications for:
- task.assigned
- task.completed
- agent.failed
- process.paused
- budget.daily_50 / 90 / 100
- test_run.failed

Email delivery via SMTP (aiosmtplib). When SMTP is unconfigured or fails,
notifications are logged but do NOT block the user-facing flow.
"""