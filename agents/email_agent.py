"""
EmailAgent — stateless notification agent.

Responsibilities:
  - Build HTML+plain-text MIME messages for pipeline SUCCESS and FAILURE.
  - Send via SMTP STARTTLS (port 587) with 3-attempt exponential back-off.
  - All blocking I/O is in `send()`; callers should invoke it via
    asyncio.to_thread so the FastAPI event-loop is never blocked.
  - NEVER raises: on final failure it returns a SendResult with
    status="FAILED" and logs the error, so the caller can persist it.

Config (read from environment, loaded by the caller via python-dotenv):
  SMTP_HOST        default: smtp.gmail.com
  SMTP_PORT        default: 587
  SMTP_USER        sender address (Gmail account)
  SMTP_PASSWORD    Gmail App Password
  SMTP_FROM_NAME   default: Shorts Automation
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Lightweight data containers (artifacts)
# ---------------------------------------------------------------------------

@dataclass
class PipelineRunSnapshot:
    """Minimal view of a pipeline run -- passed to EmailAgent methods."""
    run_id: str
    niche: str
    topic: str
    title: str
    youtube_url: Optional[str]
    youtube_id: Optional[str]
    notify_email: str
    started_at: datetime
    finished_at: datetime
    status: str                   # "SUCCESS" | "FAILED"
    failed_stage: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0


@dataclass
class EmailMessage:
    """Prepared MIME message plus routing metadata."""
    to_email: str
    subject: str
    html_body: str
    plain_body: str
    msg: MIMEMultipart = field(init=False)

    def __post_init__(self) -> None:
        smtp_user = os.getenv("SMTP_USER", os.getenv("GMAIL_ADDRESS", ""))
        from_name = os.getenv("SMTP_FROM_NAME", "Shorts Automation")

        self.msg = MIMEMultipart("alternative")
        self.msg["Subject"] = self.subject
        self.msg["From"] = f"{from_name} <{smtp_user}>"
        self.msg["To"] = self.to_email
        # plain first, html last -- email clients prefer the last matching part
        self.msg.attach(MIMEText(self.plain_body, "plain", "utf-8"))
        self.msg.attach(MIMEText(self.html_body, "html", "utf-8"))


@dataclass
class SendResult:
    """Result of a send attempt, persisted as a Report row."""
    run_id: str
    to_email: str
    subject: str
    status: str          # "SENT" | "FAILED"
    error: Optional[str]
    sent_at: datetime
    email_status: str    # mirrors status, used for the Report artifact field


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Minimal HTML escaping for user-supplied strings embedded in HTML."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# EmailAgent
# ---------------------------------------------------------------------------

class EmailAgent:
    """
    Stateless email agent. All state lives in the artifacts passed in.
    Instantiate once and call methods as needed.
    """

    # -----------------------------------------------------------------------
    # Message builders
    # -----------------------------------------------------------------------

    def build_success_message(self, run: PipelineRunSnapshot) -> EmailMessage:
        """Build a SUCCESS notification email."""
        published_time = run.finished_at.strftime("%Y-%m-%d %H:%M UTC")

        # Build both canonical URL forms (or placeholder when upload was skipped)
        if run.youtube_id:
            watch_url  = f"https://www.youtube.com/watch?v={run.youtube_id}"
            shorts_url = f"https://youtube.com/shorts/{run.youtube_id}"
        else:
            watch_url  = "https://www.youtube.com/watch?v=(upload-skipped)"
            shorts_url = "https://youtube.com/shorts/(upload-skipped)"

        subject = "Your YouTube video is ready"

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#090d16;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:600px;margin:32px auto;background:#121826;border-radius:16px;border:1px solid rgba(255,255,255,0.08);overflow:hidden;">
    <div style="background:linear-gradient(135deg,#10b981 0%,#06b6d4 100%);padding:28px 32px;">
      <h1 style="margin:0;font-size:20px;color:#fff;font-weight:700;">Your YouTube Short is ready.</h1>
      <p style="margin:6px 0 0;font-size:13px;color:rgba(255,255,255,0.85);">Your agentic pipeline completed without errors.</p>
    </div>
    <div style="padding:28px 32px;color:#f8fafc;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr><td style="padding:8px 0;color:#94a3b8;width:140px;">Title</td><td style="padding:8px 0;font-weight:600;">{_esc(run.title)}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Watch URL</td><td style="padding:8px 0;"><a href="{watch_url}" style="color:#06b6d4;text-decoration:none;">{watch_url}</a></td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Shorts URL</td><td style="padding:8px 0;"><a href="{shorts_url}" style="color:#06b6d4;text-decoration:none;">{shorts_url}</a></td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Run ID</td><td style="padding:8px 0;font-family:monospace;font-size:12px;">{run.run_id}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Published At</td><td style="padding:8px 0;">{published_time}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Status</td><td style="padding:8px 0;"><span style="background:#10b981;color:#fff;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:700;">SUCCESS</span></td></tr>
      </table>
      <div style="margin-top:24px;padding:16px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);border-radius:10px;">
        <p style="margin:0;font-size:13px;color:#94a3b8;">This notification was sent automatically by the YouTube Shorts Automation pipeline. No action is required.</p>
      </div>
    </div>
    <div style="padding:16px 32px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#64748b;text-align:center;">
      Shorts Automation | Pipeline run {run.run_id[:8]}
    </div>
  </div>
</body>
</html>"""

        plain_body = (
            f"Your YouTube Short is ready.\n"
            f"============================\n\n"
            f"Title        : {run.title}\n"
            f"Watch URL    : {watch_url}\n"
            f"Shorts URL   : {shorts_url}\n"
            f"Run ID       : {run.run_id}\n"
            f"Published At : {published_time}\n"
            f"Status       : SUCCESS\n"
        )

        return EmailMessage(
            to_email=run.notify_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )

    def build_failure_message(self, run: PipelineRunSnapshot) -> EmailMessage:
        """Build a FAILURE notification email."""
        failed_at = run.finished_at.strftime("%Y-%m-%d %H:%M UTC")
        stage = run.failed_stage or "Unknown"
        error = run.error_message or "No error detail captured."

        subject = f"Pipeline failed at {stage}"

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#090d16;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:600px;margin:32px auto;background:#121826;border-radius:16px;border:1px solid rgba(255,255,255,0.08);overflow:hidden;">
    <div style="background:linear-gradient(135deg,#ef4444 0%,#f59e0b 100%);padding:28px 32px;">
      <h1 style="margin:0;font-size:20px;color:#fff;font-weight:700;">Pipeline Run Failed</h1>
      <p style="margin:6px 0 0;font-size:13px;color:rgba(255,255,255,0.85);">Stage <strong>{_esc(stage)}</strong> raised an unrecoverable error.</p>
    </div>
    <div style="padding:28px 32px;color:#f8fafc;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr><td style="padding:8px 0;color:#94a3b8;width:140px;">Run ID</td><td style="padding:8px 0;font-family:monospace;font-size:12px;">{run.run_id}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Failed Stage</td><td style="padding:8px 0;font-weight:600;color:#ef4444;">{_esc(stage)}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Error</td><td style="padding:8px 0;font-family:monospace;font-size:12px;word-break:break-all;">{_esc(error[:400])}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Retry Count</td><td style="padding:8px 0;">{run.retry_count}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Failed At</td><td style="padding:8px 0;">{failed_at}</td></tr>
        <tr><td style="padding:8px 0;color:#94a3b8;">Status</td><td style="padding:8px 0;"><span style="background:#ef4444;color:#fff;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:700;">FAILED</span></td></tr>
      </table>
      <div style="margin-top:24px;padding:16px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);border-radius:10px;">
        <p style="margin:0;font-size:13px;color:#94a3b8;">Check the Retry Audit panel in your dashboard for full execution logs. You can re-trigger a new run from the Studio tab.</p>
      </div>
    </div>
    <div style="padding:16px 32px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#64748b;text-align:center;">
      Shorts Automation | Pipeline run {run.run_id[:8]}
    </div>
  </div>
</body>
</html>"""

        plain_body = (
            f"Pipeline Run Failed\n"
            f"===================\n\n"
            f"Run ID      : {run.run_id}\n"
            f"Failed Stage: {stage}\n"
            f"Error       : {error[:400]}\n"
            f"Retry Count : {run.retry_count}\n"
            f"Failed At   : {failed_at}\n"
            f"Status      : FAILED\n\n"
            f"Check the Retry Audit panel in your dashboard for full logs.\n"
        )

        return EmailMessage(
            to_email=run.notify_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )

    # -----------------------------------------------------------------------
    # Send (blocking -- run via asyncio.to_thread)
    # -----------------------------------------------------------------------

    def send(self, message: EmailMessage) -> SendResult:
        """
        Send message via SMTP STARTTLS with 3-attempt exponential back-off
        (2s -> 4s -> 8s). Never raises -- returns SendResult with
        status="FAILED" on final failure.
        """
        host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        port = int(os.getenv("SMTP_PORT", "587"))
        user = os.getenv("SMTP_USER", os.getenv("GMAIL_ADDRESS", ""))
        password = os.getenv("SMTP_PASSWORD", os.getenv("GMAIL_APP_PASSWORD", ""))

        max_attempts = 3
        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    f"[EmailAgent] send attempt {attempt}/{max_attempts} "
                    f"to={message.to_email!r} subject={message.subject!r}"
                )
                _ssl_ctx = ssl.create_default_context()
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.ehlo()
                    server.starttls(context=_ssl_ctx)
                    server.ehlo()
                    server.login(user, password)
                    server.sendmail(
                        user,
                        message.to_email,
                        message.msg.as_string(),
                    )
                logger.info(
                    f"[EmailAgent] sent OK to={message.to_email!r} "
                    f"subject={message.subject!r}"
                )
                return SendResult(
                    run_id="",
                    to_email=message.to_email,
                    subject=message.subject,
                    status="SENT",
                    error=None,
                    sent_at=datetime.now(timezone.utc),
                    email_status="SENT",
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"[EmailAgent] attempt {attempt} failed: {exc}")
                if attempt < max_attempts:
                    backoff = 2 ** attempt   # 2, 4, 8 seconds
                    logger.info(f"[EmailAgent] retrying in {backoff}s ...")
                    time.sleep(backoff)

        logger.error(
            f"[EmailAgent] all {max_attempts} attempts failed "
            f"to={message.to_email!r}: {last_error}"
        )
        return SendResult(
            run_id="",
            to_email=message.to_email,
            subject=message.subject,
            status="FAILED",
            error=last_error,
            sent_at=datetime.now(timezone.utc),
            email_status="FAILED",
        )
