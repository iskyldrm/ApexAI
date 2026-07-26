"""Approval gate tests — Task 30 + 31."""
import pytest

from app.agent.gates import (
    detect_migration_command,
    evaluate_migration_gate,
    evaluate_plan_approval_gate,
)


@pytest.mark.parametrize(
    "cmd",
    [
        "alembic upgrade head",
        "alembic upgrade +1",
        "prisma migrate deploy",
        "prisma migrate dev --name init",
        "python manage.py migrate",
        "npx prisma migrate deploy",
        "sqlx migrate run",
    ],
)
def test_detect_migration_command_positive(cmd):
    assert detect_migration_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest",
        "ls -la",
        "git push",
        "npm test",
        "make build",
    ],
)
def test_detect_migration_command_negative(cmd):
    assert not detect_migration_command(cmd)


def test_evaluate_migration_gate_trips():
    d = evaluate_migration_gate("alembic upgrade head")
    assert d.trip
    assert d.gate == "migration"
    assert "approval" in d.guidance.lower()


def test_evaluate_migration_gate_passes_safe_command():
    d = evaluate_migration_gate("pytest -q")
    assert not d.trip


def test_evaluate_plan_approval_gate_for_anl():
    d = evaluate_plan_approval_gate("ANL", "plan_finished")
    assert d.trip
    assert d.gate == "plan_approval"


def test_evaluate_plan_approval_gate_for_dev_does_not_trip():
    d = evaluate_plan_approval_gate("DEV_BE", "plan_finished")
    assert not d.trip


def test_evaluate_plan_approval_gate_no_plan_signal():
    d = evaluate_plan_approval_gate("ANL", "read_file")
    assert not d.trip
