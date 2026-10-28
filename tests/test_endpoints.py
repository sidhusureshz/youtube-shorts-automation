"""
tests/test_endpoints.py
=======================
Endpoint-level tests using FastAPI TestClient (no real SMTP, no real Gemini API).
All external calls are mocked.

Covers STEP 3 of the verification plan:
  A. POST /api/test-email with valid email -> 200
  B. Run with notify_email = invalid -> 422, pipeline NOT started
  C. Run with notify_email omitted -> pipeline skipped (mocked), NO email row
  D. GET /api/email-reports -> correct shape
"""

from __future__ import annotations

import os
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# We import main ONCE and reuse its app + DB for all tests in this file.
# The DB is in-memory (patched), so no side effects on the real pipeline.db.
# ---------------------------------------------------------------------------

# Patch DB before importing main so _init_db() uses in-memory SQLite
_MEM_DB: sqlite3.Connection | None = None

def _make_mem_db(*args, **kwargs):
    global _MEM_DB
    if _MEM_DB is None:
        _MEM_DB = sqlite3.connect(":memory:", check_same_thread=False)
        _MEM_DB.row_factory = sqlite3.Row
    return _MEM_DB

with patch("sqlite3.connect", side_effect=_make_mem_db):
    import main as main_mod

from fastapi.testclient import TestClient

client = TestClient(main_mod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# TEST A: POST /api/test-email with valid email -> 200, SENT response
# ---------------------------------------------------------------------------

def test_A_test_email_valid_returns_200():
    """Valid email to /api/test-email must return 200 with status='sent'."""
    # Mock SMTP so we don't hit a real server
    with patch("agents.email_agent.smtplib.SMTP") as mock_smtp:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_smtp.return_value = ctx

        resp = client.post(
            "/api/test-email",
            json={"email": "user@example.com"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "sent"
    assert body["to"] == "user@example.com"
    assert "sent_at" in body
    print(f"\n  TEST A PASS: {body}")


# ---------------------------------------------------------------------------
# TEST B: notify_email = invalid string -> 422 BEFORE pipeline starts
# ---------------------------------------------------------------------------

def test_B_invalid_notify_email_returns_422():
    """A request with notify_email='bad-email' must be rejected with HTTP 422
    by Pydantic before any pipeline agent runs."""
    pipeline_started = False

    # If the pipeline ever reads the niche, it started
    original_getenv = os.getenv
    def spy_getenv(key, *a, **kw):
        nonlocal pipeline_started
        if key == "GEMINI_API_KEY":
            pipeline_started = True
        return original_getenv(key, *a, **kw)

    with patch("os.getenv", side_effect=spy_getenv):
        resp = client.post(
            "/webhook/youtube-automation-run",
            json={"niche": "Test", "notify_email": "not-a-valid-email"},
        )

    assert resp.status_code == 422, (
        f"Expected 422, got {resp.status_code}: {resp.text}"
    )
    assert not pipeline_started, "Pipeline should NOT have started on 422"
    print(f"\n  TEST B PASS: HTTP 422 returned, pipeline not started")


# ---------------------------------------------------------------------------
# TEST C: notify_email omitted -> pipeline runs (mocked), NO email row added
# ---------------------------------------------------------------------------

def test_C_no_notify_email_skips_email_stage():
    """When notify_email is absent the pipeline should complete (mocked stages)
    and the meta.emailQueued must be False, with no email_reports row added."""

    # Count rows before
    rows_before = _MEM_DB.execute(
        "SELECT COUNT(*) FROM email_reports"
    ).fetchone()[0]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "Hanuman vs Ravana: The Epic Battle"}]
            }
        }]
    }

    mock_script_resp = MagicMock()
    mock_script_resp.status_code = 200
    mock_script_resp.text = ""
    mock_script_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{"narration":"Test narration text","title":"Epic Title","description":"A great story.","tags":"tag1,tag2","image_prompt":"vivid scene"}'
                }]
            }
        }]
    }

    call_count = [0]
    def mock_post(url, **kwargs):
        call_count[0] += 1
        if "generateContent" in url:
            if call_count[0] == 1:
                return mock_resp          # topic
            else:
                return mock_script_resp   # script
        # TTS
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {"OutputUri": "https://example.com/audio.mp3"}
        m.raise_for_status = MagicMock()
        return m

    with patch("requests.post", side_effect=mock_post), \
         patch("requests.get", return_value=MagicMock(status_code=200, json=MagicMock(return_value={"response": {"status": "done", "url": "https://example.com/video.mp4"}}), raise_for_status=MagicMock())), \
         patch("agents.email_agent.smtplib.SMTP"):

        resp = client.post(
            "/webhook/youtube-automation-run",
            json={
                "niche": "Indian Gods",
                "ownerEmail": "",
                "ttsProvider": "UnrealSpeech",
                "imageProvider": "Pollinations",
                # notify_email intentionally omitted
            },
        )

    # Pipeline may succeed or fail (YouTube creds etc), but must NOT be 422
    assert resp.status_code != 422, "Should not 422 without notify_email"
    rows_after = _MEM_DB.execute(
        "SELECT COUNT(*) FROM email_reports"
    ).fetchone()[0]
    assert rows_after == rows_before, (
        f"Expected no new email_reports row when notify_email omitted, "
        f"but count went from {rows_before} to {rows_after}"
    )

    if resp.status_code == 200:
        meta = resp.json().get("meta", {})
        assert meta.get("emailQueued") is False, (
            f"emailQueued should be False, got {meta.get('emailQueued')}"
        )
        assert meta.get("notifyEmail") is None, (
            f"notifyEmail should be None, got {meta.get('notifyEmail')}"
        )
    print(f"\n  TEST C PASS: HTTP {resp.status_code}, no email row added, rows={rows_after}")


# ---------------------------------------------------------------------------
# TEST D: GET /api/email-reports returns the right shape
# ---------------------------------------------------------------------------

def test_D_email_reports_endpoint_shape():
    """GET /api/email-reports must return a JSON object with a 'reports' list."""
    resp = client.get("/api/email-reports")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.json()
    assert "reports" in body, "Response must have 'reports' key"
    assert isinstance(body["reports"], list), "'reports' must be a list"
    print(f"\n  TEST D PASS: /api/email-reports returned {len(body['reports'])} rows")
    if body["reports"]:
        first = body["reports"][0]
        for field in ["run_id", "to_email", "subject", "status", "sent_at", "email_status"]:
            assert field in first, f"Missing field '{field}' in report row"
