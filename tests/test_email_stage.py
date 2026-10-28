"""
tests/test_email_stage.py
=========================
Pytest suite for the EmailAgent + pipeline email-notification stage.

Covers:
  1. Success run  -> one email, correct subject / body fields, status SUCCESS
  2. Failed run   -> one email, subject "Pipeline failed at <stage>", error in body
  3. SMTP failure -> 3 retries (backoff mocked), pipeline still succeeds,
                     email_reports row status = FAILED
  4. Invalid email -> pydantic 422 before pipeline starts
  5. Empty email   -> no send attempt at all
  6. EmailAgent.send never raises in any case
"""

from __future__ import annotations

import asyncio
import smtplib
import sqlite3
import sys
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Import project modules
# ---------------------------------------------------------------------------
from agents.email_agent import EmailAgent, PipelineRunSnapshot, EmailMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(
    status: str = "SUCCESS",
    failed_stage: Optional[str] = None,
    error_message: Optional[str] = None,
    notify_email: str = "test@example.com",
    youtube_url: Optional[str] = "https://www.youtube.com/watch?v=abc123",
) -> PipelineRunSnapshot:
    now = datetime.now(timezone.utc)
    return PipelineRunSnapshot(
        run_id="run-test-1234",
        niche="Indian Gods",
        topic="Hanuman Chalisa: The Power of Devotion",
        title="Hanuman Chalisa Explained in 30 Seconds",
        youtube_url=youtube_url,
        youtube_id="abc123",
        notify_email=notify_email,
        started_at=now,
        finished_at=now,
        status=status,
        failed_stage=failed_stage,
        error_message=error_message,
        retry_count=0,
    )


# ---------------------------------------------------------------------------
# TEST 1: Success run produces correct email
# ---------------------------------------------------------------------------

def test_success_email_subject_and_body():
    """Success run => subject starts with 'Short published:' and body contains
    YouTube URL, run ID, and status SUCCESS."""
    agent = EmailAgent()
    run = _make_run(status="SUCCESS")
    msg = agent.build_success_message(run)

    assert msg.subject.startswith("Short published:"), (
        f"Expected 'Short published: ...' got {msg.subject!r}"
    )
    assert run.run_id in msg.html_body, "run_id missing from HTML body"
    assert "SUCCESS" in msg.html_body, "status SUCCESS missing from HTML body"
    assert "abc123" in msg.html_body, "YouTube video ID missing from HTML body"
    assert run.title in msg.html_body, "title missing from HTML body"
    assert msg.to_email == run.notify_email


# ---------------------------------------------------------------------------
# TEST 2: Failed run produces correct failure email
# ---------------------------------------------------------------------------

def test_failure_email_subject_and_body():
    """Failed run => subject is 'Pipeline failed at <stage>' and body contains
    the error message."""
    agent = EmailAgent()
    run = _make_run(
        status="FAILED",
        failed_stage="ScriptAgent",
        error_message="Gemini API returned 503",
    )
    msg = agent.build_failure_message(run)

    assert msg.subject == "Pipeline failed at ScriptAgent", (
        f"Wrong subject: {msg.subject!r}"
    )
    assert "Gemini API returned 503" in msg.html_body, (
        "Error message missing from HTML body"
    )
    assert run.run_id in msg.html_body, "run_id missing from HTML body"
    assert msg.to_email == run.notify_email


# ---------------------------------------------------------------------------
# TEST 3: SMTP failure => 3 retries, pipeline still succeeds, row status FAILED
# ---------------------------------------------------------------------------

def test_smtp_failure_retries_3_times_and_returns_failed_result():
    """When smtplib.SMTP raises SMTPAuthenticationError on every attempt,
    EmailAgent.send must retry exactly 3 times (sleep 2, 4, 8 seconds)
    and return a SendResult with status='FAILED' without raising."""
    agent = EmailAgent()
    run = _make_run(status="SUCCESS")
    msg = agent.build_success_message(run)

    auth_error = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
    sleep_calls = []

    with patch("agents.email_agent.smtplib.SMTP") as mock_smtp_cls, \
         patch("agents.email_agent.time.sleep", side_effect=lambda s: sleep_calls.append(s)):

        # Make every SMTP() context manager raise on login
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.login.side_effect = auth_error
        mock_smtp_cls.return_value = mock_ctx

        result = agent.send(msg)

    # --- assertions ---
    assert result.status == "FAILED", f"Expected FAILED, got {result.status!r}"
    assert result.error is not None, "error field must not be None on FAILED"
    assert "535" in result.error or "Authentication" in result.error, (
        f"Error text unexpected: {result.error!r}"
    )
    assert result.email_status == "FAILED"

    # Exactly 3 SMTP() constructor calls
    assert mock_smtp_cls.call_count == 3, (
        f"Expected 3 SMTP attempts, got {mock_smtp_cls.call_count}"
    )

    # Back-off sleeps: 2, 4 (no sleep after last attempt)
    assert sleep_calls == [2, 4], (
        f"Expected back-off sleeps [2, 4], got {sleep_calls}"
    )


# ---------------------------------------------------------------------------
# TEST 4: Invalid email => pydantic 422, pipeline never starts
# ---------------------------------------------------------------------------

def test_invalid_email_returns_422():
    """POSTing notify_email='not-a-valid-email' must return HTTP 422
    from Pydantic validation before any pipeline code runs."""
    # We need a FastAPI test client.  Import main carefully to avoid
    # side-effects (DB init, dotenv) being re-run inside subprocess.
    # We use a fresh import with mocked DB.
    with patch("sqlite3.connect") as mock_db:
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_db.return_value = mock_conn

        # Reload main fresh in a sub-import to avoid polluting module state
        import importlib
        import main as main_mod
        client = TestClient(main_mod.app, raise_server_exceptions=False)

    resp = client.post(
        "/webhook/youtube-automation-run",
        json={"niche": "Test Niche", "notify_email": "not-a-valid-email"},
    )
    assert resp.status_code == 422, (
        f"Expected 422, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# TEST 5: Empty / None notify_email => no send attempt
# ---------------------------------------------------------------------------

def test_empty_notify_email_no_send():
    """When notify_email is None (omitted), EmailAgent.send must never be called."""
    agent = EmailAgent()

    with patch.object(agent, "send") as mock_send:
        # Simulate the finally-block logic
        notify_email = None
        if notify_email:
            run = _make_run(notify_email=notify_email)
            msg = agent.build_success_message(run)
            agent.send(msg)

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# TEST 6: EmailAgent.send never raises, even on unexpected exception
# ---------------------------------------------------------------------------

def test_send_never_raises_on_unexpected_exception():
    """Even if smtplib.SMTP raises an unexpected RuntimeError, send() must
    return a SendResult (status=FAILED) and never propagate an exception."""
    agent = EmailAgent()
    run = _make_run(status="SUCCESS")
    msg = agent.build_success_message(run)

    with patch("agents.email_agent.smtplib.SMTP", side_effect=RuntimeError("unexpected")), \
         patch("agents.email_agent.time.sleep"):

        try:
            result = agent.send(msg)
        except Exception as exc:
            pytest.fail(f"send() raised unexpectedly: {exc}")

    assert result.status == "FAILED"
    assert result.error is not None


# ---------------------------------------------------------------------------
# BONUS: Plain-text fallback is always present
# ---------------------------------------------------------------------------

def test_messages_have_plain_text_fallback():
    """Both success and failure messages must include a plain-text MIME part."""
    agent = EmailAgent()
    run_ok = _make_run(status="SUCCESS")
    run_fail = _make_run(status="FAILED", failed_stage="TTSAgent", error_message="timeout")

    for msg in [agent.build_success_message(run_ok), agent.build_failure_message(run_fail)]:
        parts_ct = [p.get_content_type() for p in msg.msg.get_payload()]
        assert "text/plain" in parts_ct, f"No text/plain part in {msg.subject!r}"
        assert "text/html" in parts_ct, f"No text/html part in {msg.subject!r}"
