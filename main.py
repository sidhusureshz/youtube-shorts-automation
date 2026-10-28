import asyncio
import os
import sys
import time
import uuid
import json
import sqlite3
import logging
import urllib.parse
import smtplib
import requests
from contextlib import contextmanager
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

# ---------------------------------------------------------------------------
# Dual-output logging: console + logs/pipeline.log
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)

_logger = logging.getLogger("pipeline")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False  # don't double-log via root logger

# Console handler -- mirrors original print() behaviour
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.DEBUG)
_ch.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_ch)

# File handler -- appends to logs/pipeline.log with timestamps
_fh = logging.FileHandler("logs/pipeline.log", encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                    datefmt="%Y-%m-%dT%H:%M:%S"))
_logger.addHandler(_fh)

def log(*args, **kwargs):
    """Drop-in replacement for print() that writes to both console and file."""
    sep = kwargs.get("sep", " ")
    msg = sep.join(str(a) for a in args)
    _logger.info(msg)

# Reconfigure stdout/stderr for Unicode UTF-8 safety on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Startup environment inspection -- now also written to logs/pipeline.log
log("=== STARTUP ENVIRONMENT DIAGNOSTICS ===")
log("os.getcwd():", os.getcwd())
log("os.path.exists('.env'):", os.path.exists('.env'))
log("os.path.abspath(__file__):", os.path.abspath(__file__))
log("=======================================")

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# Google API Client imports for YouTube Upload
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError as YouTubeHttpError

# EmailAgent
from agents.email_agent import EmailAgent, PipelineRunSnapshot

# Load .env file
load_dotenv(override=True)

log("=== API KEYS & CREDENTIALS DIAGNOSTICS ===")
for key in ["UNREALSPEECH_API_KEY","SHOTSTACK_API_KEY","YOUTUBE_CLIENT_ID","YOUTUBE_CLIENT_SECRET","YOUTUBE_REFRESH_TOKEN","GMAIL_ADDRESS","GMAIL_APP_PASSWORD","SMTP_USER","SMTP_PASSWORD"]:
    val = os.getenv(key)
    log(f"{key}: {'SET (len='+str(len(val))+')' if val else 'MISSING/EMPTY'}")
log("==========================================")

# ---------------------------------------------------------------------------
# Helpers: Pollinations image download and Shotstack Ingest hosting
# ---------------------------------------------------------------------------

def _download_pollinations_image(
    pollinations_url: str,
    run_id: str,
    max_retries: int = 2,
) -> tuple[bytes, str, str]:
    """
    Downloads the image from Pollinations once with timeout=90.
    Validates HTTP 200, Content-Type image/*, JPEG/PNG magic bytes, and size > 10 KB.
    Retries up to max_retries on 402, 429, 5xx, timeouts or invalid bodies (5s backoff).
    Saves bytes to temp_image_{run_id}.jpg and returns (img_bytes, content_type, temp_image_path).
    Raises RuntimeError naming the failure reason / status code if all attempts fail.
    """
    temp_image_path = f"temp_image_{run_id}.jpg"
    last_error: Optional[Exception] = None
    last_status: Optional[int] = None

    for attempt in range(1, max_retries + 2):
        t0 = time.time()
        try:
            log(f"[ImageAgent] Requesting Pollinations image (attempt {attempt}/{max_retries + 1})...")
            res = requests.get(pollinations_url, allow_redirects=True, timeout=90)
            elapsed = time.time() - t0
            last_status = res.status_code

            if res.status_code != 200:
                body_snippet = res.text[:200].strip() if res.text else "<empty>"
                raise ValueError(f"HTTP {res.status_code}: {body_snippet}")

            ct = res.headers.get("Content-Type", "")
            if not ct.lower().startswith("image/"):
                raise ValueError(f"Invalid Content-Type {ct!r} (expected image/*)")

            content = res.content
            if len(content) <= 10 * 1024:
                raise ValueError(f"Image size too small ({len(content)} bytes <= 10 KB)")

            # Verify image magic bytes: JPEG (FF D8) or PNG (89 50 4E 47)
            is_jpeg = content.startswith(b"\xff\xd8")
            is_png = content.startswith(b"\x89PNG")
            if not (is_jpeg or is_png):
                raise ValueError("Body does not start with valid JPEG (FF D8) or PNG (89 50 4E 47) signature")

            # Save to temporary file
            with open(temp_image_path, "wb") as f:
                f.write(content)

            log(f"[ImageAgent] Image downloaded successfully in {elapsed:.2f}s: {len(content):,} bytes, saved to {temp_image_path}")
            clean_ct = ct.split(";")[0].strip() or ("image/png" if is_png else "image/jpeg")
            return content, clean_ct, temp_image_path

        except Exception as err:
            elapsed = time.time() - t0
            last_error = err
            log(f"[ImageAgent] Download attempt {attempt} failed after {elapsed:.2f}s: {err}")
            if attempt < max_retries + 1:
                log("[ImageAgent] Waiting 5 seconds before retry...")
                time.sleep(50)

    status_info = f"status code {last_status}" if last_status is not None else "network/timeout error"
    raise RuntimeError(f"Pollinations image download failed after {max_retries + 1} attempts ({status_info}): {last_error}")


def _upload_image_to_shotstack(
    img_bytes: bytes,
    content_type: str,
    shotstack_api_key: str,
    poll_timeout_sec: int = 60,
) -> str:
    """
    Directly uploads image bytes to Shotstack Ingest API (stage) and polls until ready.
    Returns the hosted public CDN URL.
    Raises RuntimeError on any failure (no fallback).
    """
    ingest_base = "https://api.shotstack.io/ingest/stage"
    headers = {
        "x-api-key": shotstack_api_key,
        "Accept": "application/json",
    }

    # Step 1: Request signed S3 upload URL from Shotstack Ingest
    log("[ImageHost] Requesting signed S3 upload URL from Shotstack Ingest API...")
    res = requests.post(f"{ingest_base}/upload", headers=headers, timeout=20)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"Shotstack Ingest /upload failed (HTTP {res.status_code}): {res.text}")

    upload_data = res.json().get("data", {})
    source_id = upload_data.get("id")
    signed_url = upload_data.get("attributes", {}).get("url")

    if not source_id or not signed_url:
        raise RuntimeError(f"Shotstack Ingest upload response missing id or url: {res.text}")

    log(f"[ImageHost] Source slot allocated (source_id={source_id}). Uploading raw bytes to S3...")

    # Step 2: PUT raw bytes directly to S3 signed URL (no x-api-key header)
    put_res = requests.put(
        signed_url,
        data=img_bytes,
        headers={"Content-Type": content_type},
        timeout=60,
    )
    if put_res.status_code not in (200, 201):
        raise RuntimeError(f"Shotstack S3 direct PUT failed (HTTP {put_res.status_code}): {put_res.text}")

    log("[ImageHost] S3 upload completed. Polling Shotstack Ingest source status...")

    # Step 3: Poll /ingest/stage/sources/{source_id} until status == "ready"
    poll_url = f"{ingest_base}/sources/{source_id}"
    start_poll = time.time()
    poll_interval = 3

    while (time.time() - start_poll) < poll_timeout_sec:
        time.sleep(poll_interval)
        poll_res = requests.get(poll_url, headers=headers, timeout=20)
        if poll_res.status_code != 200:
            raise RuntimeError(f"Shotstack Ingest poll failed (HTTP {poll_res.status_code}): {poll_res.text}")

        attrs = poll_res.json().get("data", {}).get("attributes", {})
        status = attrs.get("status")
        log(f"[ImageHost] Ingest source status: {status}")

        if status == "ready":
            hosted_url = attrs.get("url") or attrs.get("source")
            if not hosted_url:
                raise RuntimeError(f"Shotstack Ingest source marked ready but missing url/source attribute: {attrs}")
            return hosted_url

        if status == "failed":
            raise RuntimeError(f"Shotstack Ingest processing failed: {attrs.get('error', attrs)}")

    raise RuntimeError(f"Shotstack Ingest timed out after {poll_timeout_sec}s waiting for source {source_id} to be ready")



app = FastAPI(title="YouTube Content Automation API")

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# SQLite: email_reports table (safe migration -- never drops data)
# ---------------------------------------------------------------------------
DB_PATH = "pipeline.db"

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db() -> None:
    """Create tables / add columns if they don't exist yet."""
    with _get_db() as conn:
        # email_reports table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT    NOT NULL,
                to_email    TEXT    NOT NULL,
                subject     TEXT    NOT NULL,
                status      TEXT    NOT NULL,
                error       TEXT,
                sent_at     TEXT    NOT NULL,
                email_status TEXT   NOT NULL
            )
        """)
        conn.commit()
        log("[DB] email_reports table ready.")

_init_db()

# Singleton EmailAgent (stateless -- safe to reuse)
_email_agent = EmailAgent()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class PipelineRequest(BaseModel):
    niche: Optional[str] = "Indian Gods"
    ownerEmail: Optional[str] = ""
    ttsProvider: Optional[str] = "UnrealSpeech"
    imageProvider: Optional[str] = "Pollinations"
    notify_email: Optional[EmailStr] = None   # NEW: email to notify after run


class TestEmailRequest(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Helper: persist email report row
# ---------------------------------------------------------------------------

def _save_email_report(
    run_id: str,
    to_email: str,
    subject: str,
    status: str,
    error: Optional[str],
    sent_at: datetime,
    email_status: str,
) -> None:
    try:
        with _get_db() as conn:
            conn.execute(
                """INSERT INTO email_reports
                   (run_id, to_email, subject, status, error, sent_at, email_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, to_email, subject, status, error,
                 sent_at.isoformat(), email_status),
            )
            conn.commit()
    except Exception as db_err:
        _logger.error(f"[DB] Failed to save email_report: {db_err}")


# ---------------------------------------------------------------------------
# Helper: call EmailAgent in a thread (non-blocking)
# ---------------------------------------------------------------------------

async def _send_notification(
    run_snapshot: PipelineRunSnapshot,
    is_success: bool,
    run_id: str,
) -> None:
    """Build and dispatch the notification email in a worker thread."""
    try:
        if is_success:
            msg = _email_agent.build_success_message(run_snapshot)
        else:
            msg = _email_agent.build_failure_message(run_snapshot)

        # blocking SMTP in a thread -- never blocks the event loop
        result = await asyncio.to_thread(_email_agent.send, msg)
        result.run_id = run_id

        _save_email_report(
            run_id=run_id,
            to_email=result.to_email,
            subject=result.subject,
            status=result.status,
            error=result.error,
            sent_at=result.sent_at,
            email_status=result.email_status,
        )

        if result.status == "FAILED":
            log(f"[EmailAgent] Email notification FAILED for run {run_id}: {result.error}")
        else:
            log(f"[EmailAgent] Email notification SENT for run {run_id}")

    except Exception as e:
        _logger.error(f"[EmailAgent] Unexpected error during notification for run {run_id}: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"status": "ok", "service": "YouTube Content Automation API"}


@app.post("/api/test-email")
async def test_email(req: TestEmailRequest):
    """
    Send a test email to verify SMTP config without running the full pipeline.
    """
    from agents.email_agent import EmailMessage

    subject = "Test: Shorts Automation SMTP check"
    run_id = f"test-{uuid.uuid4()}"
    html_body = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="background:#090d16;font-family:sans-serif;color:#f8fafc;padding:32px;">
  <div style="max-width:520px;margin:0 auto;background:#121826;border-radius:14px;
              border:1px solid rgba(255,255,255,0.08);padding:28px;">
    <h2 style="color:#10b981;margin-top:0;">SMTP Test Successful</h2>
    <p>Your Shorts Automation SMTP configuration is working correctly.</p>
    <p style="color:#94a3b8;font-size:13px;">
      This test was triggered manually via <code>POST /api/test-email</code>.
    </p>
  </div>
</body></html>"""
    plain_body = (
        "SMTP Test Successful\n"
        "====================\n"
        "Your Shorts Automation SMTP configuration is working correctly.\n"
        "This test was triggered manually via POST /api/test-email.\n"
    )

    try:
        smtp_user = os.getenv("SMTP_USER", os.getenv("GMAIL_ADDRESS", ""))
        if not smtp_user:
            raise RuntimeError("SMTP_USER / GMAIL_ADDRESS not configured in .env")

        msg = EmailMessage(
            to_email=str(req.email),
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )
        result = await asyncio.to_thread(_email_agent.send, msg)
    except Exception as exc:
        _logger.exception("[TestEmail] Unexpected error while sending test email")
        result = None
        error = str(exc)
    else:
        error = result.error

    status = result.status if result else "FAILED"
    sent_at = result.sent_at if result else datetime.now(timezone.utc)
    _save_email_report(
        run_id=run_id,
        to_email=str(req.email),
        subject=subject,
        status=status,
        error=error,
        sent_at=sent_at,
        email_status=status,
    )
    log(f"[TestEmail] {status} to={req.email}; error={error or 'none'}")

    return {
        "status": status.lower(),
        "to": str(req.email),
        "subject": subject,
        "sent_at": sent_at.isoformat(),
        "error": error,
        "run_id": run_id,
    }


@app.get("/api/email-reports")
def list_email_reports(run_id: Optional[str] = None):
    """Return email report rows for the Retry Audit panel.

    When *run_id* is supplied only rows for that run are returned (used by
    the frontend polling loop).  Without it the last 200 rows are returned
    (existing Retry Audit behaviour — unchanged).
    """
    try:
        with _get_db() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM email_reports WHERE run_id = ? ORDER BY id DESC",
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM email_reports ORDER BY id DESC LIMIT 200"
                ).fetchall()
        return {"reports": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/youtube-automation-run")
@app.post("/webhook/youtube-automation-run")
async def run_pipeline(req: PipelineRequest, background_tasks: BackgroundTasks):
    started_dt = datetime.now(timezone.utc)
    started_at = started_dt.isoformat()
    start_time = time.time()

    niche = req.niche.strip() if req.niche and req.niche.strip() else "Indian Gods"
    owner_email = req.ownerEmail.strip() if req.ownerEmail and req.ownerEmail.strip() else os.getenv("GMAIL_ADDRESS", "sidhuworks1@gmail.com")
    tts_provider = req.ttsProvider or "UnrealSpeech"
    image_provider = req.imageProvider or "Pollinations"
    notify_email: Optional[str] = str(req.notify_email) if req.notify_email else None

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    unrealspeech_key = os.getenv("UNREALSPEECH_API_KEY", "").strip()
    shotstack_key = os.getenv("SHOTSTACK_API_KEY", "").strip()
    yt_client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    yt_client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    yt_refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
    gmail_user = os.getenv("GMAIL_ADDRESS", "").strip()
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").strip()

    run_id = str(uuid.uuid4())

    log(f"\n==================================================")
    log(f"[{started_at}] STARTING PIPELINE RUN ID={run_id}")
    log(f"Niche: {niche}")
    log(f"notify_email: {notify_email!r}")
    log(f"==================================================")

    # Track pipeline outcome for EmailAgent
    pipeline_status = "SUCCESS"
    failed_stage: Optional[str] = None
    error_message: Optional[str] = None
    retry_count = 0

    # Declare pipeline artifacts (filled as we progress)
    topic = ""
    title = ""
    narration = ""
    description = ""
    tags = ""
    image_prompt = ""
    audio_url = None
    image_url = None
    video_url = None
    video_status = "failed"
    youtube_id = None
    youtube_url_out = None
    temp_image_path: Optional[str] = None

    try:
        # --------------------------------------------------------------------------
        # 1. TopicAgent (Gemini)
        # --------------------------------------------------------------------------
        log("\n--- STEP 1: TopicAgent (Gemini) - START ---")
        failed_stage = "TopicAgent"
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY is not set in environment.")

        def call_gemini_api(payload, step_name):
            models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"]
            last_res = None
            for m in models:
                url = f"https://generativelanguage.googleapis.com/v1/models/{m}:generateContent?key={gemini_key}"
                log(f"[{step_name}] Requesting model '{m}'...")
                res = requests.post(url, json=payload, timeout=30)
                log(f"[{step_name}] Model '{m}' Raw Response Code: {res.status_code}")
                log(f"[{step_name}] Model '{m}' Raw Response Body: {res.text}")
                if res.status_code == 200:
                    return res
                elif res.status_code in [503, 429]:
                    log(f"[{step_name}] Capacity error on '{m}' ({res.status_code}), trying next candidate model...")
                    last_res = res
                else:
                    res.raise_for_status()
            if last_res is not None:
                last_res.raise_for_status()
            res.raise_for_status()

        topic_payload = {
            "system_instruction": {
                "parts": [{"text": "You pick one specific, trending, high-engagement YouTube Shorts topic for a given niche. Reply with ONLY the topic title, no quotes, no extra text."}]
            },
            "contents": [{"role": "user", "parts": [{"text": f"Niche: {niche}"}]}],
            "generationConfig": {"temperature": 0.9}
        }
        log(f"Sending Topic request to Gemini for niche: '{niche}'...")
        res = call_gemini_api(topic_payload, "TopicAgent")

        res_data = res.json()
        topic = res_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        if not topic:
            raise ValueError(f"Gemini returned empty topic: {res.text}")
        log(f"Selected Topic: '{topic}'")
        log("--- STEP 1: TopicAgent (Gemini) - COMPLETE ---")

        # --------------------------------------------------------------------------
        # 2. ScriptAgent (Gemini)
        # --------------------------------------------------------------------------
        log("\n--- STEP 2: ScriptAgent (Gemini) - START ---")
        failed_stage = "ScriptAgent"
        script_payload = {
            "system_instruction": {
                "parts": [{"text": "You write scripts for ~30 second YouTube Shorts. Return a JSON object with keys: narration (a single spoken paragraph under 600 characters), title (catchy, under 90 chars), description (2-3 sentences), tags (comma separated string), image_prompt (a vivid visual prompt for an AI image generator). Return ONLY valid JSON."}]
            },
            "contents": [{"role": "user", "parts": [{"text": f"Write a Shorts script about: {topic}"}]}],
            "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"}
        }
        log(f"Sending Script request to Gemini for topic: '{topic}'...")
        res = call_gemini_api(script_payload, "ScriptAgent")

        raw_text = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        parsed = json.loads(raw_text)
        narration = parsed["narration"]
        title = parsed["title"]
        description = parsed["description"]
        tags = parsed["tags"]
        image_prompt = parsed["image_prompt"]

        log(f"Generated Title: {title}")
        log(f"Generated Narration: {narration}")
        log("--- STEP 2: ScriptAgent (Gemini) - COMPLETE ---")

        # --------------------------------------------------------------------------
        # 3. TTSAgent (UnrealSpeech)
        # --------------------------------------------------------------------------
        log("\n--- STEP 3: TTSAgent (UnrealSpeech) - START ---")
        failed_stage = "TTSAgent"
        if unrealspeech_key:
            tts_url = "https://api.v8.unrealspeech.com/speech"
            headers = {
                "Authorization": f"Bearer {unrealspeech_key}",
                "Content-Type": "application/json"
            }
            body = {
                "Text": narration,
                "VoiceId": "Daniel",
                "Bitrate": "192k",
                "Speed": 0,
                "Pitch": 1,
                "TimestampType": "sentence"
            }
            log("Sending TTS request to UnrealSpeech...")
            res = requests.post(tts_url, json=body, headers=headers, timeout=30)
            log(f"TTSAgent Raw Response Code: {res.status_code}")
            log(f"TTSAgent Raw Response Body: {res.text}")
            res.raise_for_status()

            audio_url = res.json()["OutputUri"]
            log(f"TTS Audio URL: {audio_url}")
        else:
            log("UNREALSPEECH_API_KEY omitted. Using default placeholder audio URL.")
            audio_url = "https://shotstack-assets.s3-ap-southeast-2.amazonaws.com/audio/null.mp3"
        log("--- STEP 3: TTSAgent (UnrealSpeech) - COMPLETE ---")

        # --------------------------------------------------------------------------
        # 4. ImageAgent (Pollinations) + Shotstack Ingest host
        # --------------------------------------------------------------------------
        log("\n--- STEP 4: ImageAgent (Pollinations) - START ---")
        failed_stage = "ImageAgent"
        encoded_prompt = urllib.parse.quote(image_prompt)
        # image.pollinations.ai is the public unauthenticated endpoint.
        # width/height match the portrait output so the image fills the frame with fit=cover.
        image_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?model=flux&width=1080&height=1920&nologo=true"
        )
        log(f"Pollinations Image URL: {image_url}")
        if not shotstack_key:
            raise ValueError("SHOTSTACK_API_KEY is not set in environment.")

        # Download once in Python, validate, save to temp file, and upload to Shotstack Ingest
        img_bytes, img_content_type, temp_image_path = _download_pollinations_image(image_url, run_id)
        hosted_image_url = _upload_image_to_shotstack(img_bytes, img_content_type, shotstack_key, poll_timeout_sec=60)
        log(f"[ImageAgent] Hosted image URL: {hosted_image_url}")
        log("--- STEP 4: ImageAgent (Pollinations) - COMPLETE ---")

        # --------------------------------------------------------------------------
        # 5. RenderAgent (Shotstack)
        # --------------------------------------------------------------------------
        log("\n--- STEP 5: RenderAgent (Shotstack) - START ---")
        failed_stage = "RenderAgent"
        if shotstack_key:
            render_endpoint = "https://api.shotstack.io/edit/stage/render"
            headers = {
                "x-api-key": shotstack_key,
                "Content-Type": "application/json"
            }
            shotstack_payload = {
                "timeline": {
                    "background": "#000000",
                    "soundtrack": {
                        "src": audio_url,
                        "effect": "fadeOut"
                    },
                    "tracks": [
                        # Track 0 (top layer): title text
                        {
                            "clips": [
                                {
                                    "asset": {
                                        "type": "text",
                                        "text": title,
                                        "font": {
                                            "family": "Montserrat ExtraBold",
                                            "color": "#ffffff",
                                            "size": 60
                                        },
                                        "alignment": {
                                            "horizontal": "center",
                                            "vertical": "center"
                                        },
                                        "width": 900,
                                        "height": 1600
                                    },
                                    "start": 0,
                                    "length": 30,
                                    "transition": {
                                        "in": "fade",
                                        "out": "fade"
                                    }
                                }
                            ]
                        },
                        # Track 1 (background layer): Pollinations image (CDN-hosted via Shotstack Ingest)
                        {
                            "clips": [
                                {
                                    "asset": {
                                        "type": "image",
                                        "src": hosted_image_url
                                    },
                                    "start": 0,
                                    "length": 30,
                                    "fit": "cover"
                                }
                            ]
                        }
                    ]
                },
                "output": {
                    "format": "mp4",
                    "size": {
                        "width": 1080,
                        "height": 1920
                    }
                }
            }
            log("Submitting render request to Shotstack...")
            try:
                res = requests.post(render_endpoint, json=shotstack_payload, headers=headers, timeout=30)
                log(f"Shotstack Submit Raw Response Code: {res.status_code}")
                log(f"Shotstack Submit Raw Response Body: {res.text}")
                res.raise_for_status()
            finally:
                if temp_image_path and os.path.exists(temp_image_path):
                    try:
                        os.remove(temp_image_path)
                        log(f"Deleted temp image file: {temp_image_path}")
                    except Exception as del_err:
                        log(f"Warning: could not delete {temp_image_path}: {del_err}")
                    temp_image_path = None

            render_id = res.json()["response"]["id"]
            log(f"Shotstack Render ID: {render_id}")

            poll_url = f"https://api.shotstack.io/edit/stage/render/{render_id}"
            for _ in range(60):  # up to 5 minutes (60 x 5s)
                time.sleep(5)
                poll_res = requests.get(poll_url, headers=headers, timeout=20)
                log(f"Shotstack Poll Response Code: {poll_res.status_code}")
                log(f"Shotstack Poll Response Body: {poll_res.text}")
                poll_res.raise_for_status()

                status_data = poll_res.json()["response"]
                st = status_data.get("status")
                log(f"Shotstack Poll Status: {st}")
                if st == "done":
                    video_url = status_data.get("url")
                    video_status = "done"
                    break
                elif st == "failed":
                    raise RuntimeError(f"Shotstack render failed: {status_data}")

            if not video_url:
                raise RuntimeError("Shotstack render timed out or failed to produce video URL.")
        else:
            log("SHOTSTACK_API_KEY omitted. Skipping video render step.")
            video_status = "skipped"
        log("--- STEP 5: RenderAgent (Shotstack) - COMPLETE ---")

        # --------------------------------------------------------------------------
        # 6. Download Video & PublishAgent (YouTube)
        # --------------------------------------------------------------------------
        log("\n--- STEP 6: PublishAgent (YouTube) - START ---")
        failed_stage = "PublishAgent"

        if video_url and yt_client_id and yt_client_secret and yt_refresh_token:
            log("Downloading rendered video for YouTube upload...")
            temp_video_path = f"temp_{run_id}.mp4"
            v_req = requests.get(video_url, stream=True, timeout=60)
            v_req.raise_for_status()

            with open(temp_video_path, "wb") as f:
                for chunk in v_req.iter_content(chunk_size=8192):
                    f.write(chunk)

            secret_masked = '*' * max(0, len(yt_client_secret) - 4) + yt_client_secret[-4:]
            token_masked = '*' * max(0, len(yt_refresh_token) - 6) + yt_refresh_token[-6:]
            log("=== YOUTUBE OAUTH CREDENTIALS DEBUG REPR ===")
            log("YOUTUBE_CLIENT_ID:", repr(yt_client_id))
            log("YOUTUBE_CLIENT_SECRET (masked):", repr(secret_masked))
            log("YOUTUBE_REFRESH_TOKEN (masked):", repr(token_masked))
            log("============================================")

            try:
                creds = Credentials(
                    token=None,
                    refresh_token=yt_refresh_token,
                    client_id=yt_client_id,
                    client_secret=yt_client_secret,
                    token_uri="https://oauth2.googleapis.com/token",
                    scopes=["https://www.googleapis.com/auth/youtube.upload"],
                )
                youtube_service = build("youtube", "v3", credentials=creds)

                tags_list = [t.strip() for t in tags.split(",") if t.strip()]
                body = {
                    "snippet": {
                        "title": title[:90],
                        "description": f"{description}\n\n{tags}",
                        "tags": tags_list,
                        "categoryId": "22",
                    },
                    "status": {
                        "privacyStatus": "private",
                        "selfDeclaredMadeForKids": False
                    }
                }

                media = MediaFileUpload(temp_video_path, mimetype="video/mp4", resumable=True, chunksize=256 * 1024)
                request_upload = youtube_service.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media
                )

                upload_res = None
                while upload_res is None:
                    upload_status, upload_res = request_upload.next_chunk()
                    if upload_status:
                        pct = int(upload_status.progress() * 100)
                        log(f"[PublishAgent] Upload progress: {pct}%")

                youtube_id = upload_res.get("id")
                if not youtube_id:
                    raise RuntimeError(f"YouTube upload returned no video ID. Response: {upload_res}")
                youtube_url_out = f"https://youtu.be/{youtube_id}"
                log(f"YouTube Upload Success! Video ID={youtube_id} URL={youtube_url_out}")

            except RefreshError as ref_err:
                # Token is expired/revoked or client credentials mismatch
                detail = f"YouTube auth failed (invalid_grant): {ref_err}. Run python new_token.py to get a fresh YOUTUBE_REFRESH_TOKEN."
                log(f"[PublishAgent] FAILED — {detail}")
                raise HTTPException(status_code=502, detail=detail)

            except YouTubeHttpError as yt_err:
                # Extract full API error reason
                try:
                    import json as _json
                    err_body = _json.loads(yt_err.content.decode("utf-8"))
                    api_message = err_body.get("error", {}).get("message", str(yt_err.content))
                    api_errors = err_body.get("error", {}).get("errors", [])
                    api_reason = api_errors[0].get("reason", "") if api_errors else ""
                except Exception:
                    api_message = str(yt_err)
                    api_reason = ""
                detail = f"YouTube API error HTTP {yt_err.resp.status}: {api_message} (reason={api_reason})"
                log(f"[PublishAgent] FAILED — {detail}")
                raise HTTPException(status_code=502, detail=detail)

            finally:
                if os.path.exists(temp_video_path):
                    for _attempt in range(5):
                        try:
                            os.remove(temp_video_path)
                            break
                        except PermissionError:
                            time.sleep(1)
        else:
            missing_parts = []
            if not video_url: missing_parts.append("video_url")
            if not yt_client_id: missing_parts.append("YOUTUBE_CLIENT_ID")
            if not yt_client_secret: missing_parts.append("YOUTUBE_CLIENT_SECRET")
            if not yt_refresh_token: missing_parts.append("YOUTUBE_REFRESH_TOKEN")
            log(f"YouTube upload skipped — missing: {', '.join(missing_parts)}")
        log("--- STEP 6: PublishAgent (YouTube) - COMPLETE ---")

        # --------------------------------------------------------------------------
        # 7. Legacy email report (Gmail SMTP) -- kept for backward compat
        # --------------------------------------------------------------------------
        log("\n--- STEP 7: Email Report (Gmail SMTP) - START ---")
        log(f"STEP 7 credential check: gmail_user={'SET' if gmail_user else 'MISSING'}, gmail_pass={'SET' if gmail_pass else 'MISSING'}, owner_email={owner_email!r}")
        if gmail_user and gmail_pass and owner_email:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"YouTube run complete: {title}"
            msg["From"] = gmail_user
            msg["To"] = owner_email

            html_content = f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; background: #090d16; color: #f8fafc; padding: 24px; border-radius: 12px;">
                <h2 style="color: #10b981;">Pipeline Run Complete</h2>
                <p><strong>Niche:</strong> {niche}</p>
                <p><strong>Topic:</strong> {topic}</p>
                <p><strong>Title:</strong> {title}</p>
                <p><strong>Description:</strong> {description}</p>
                <p><strong>Video URL:</strong> <a href="{video_url or '#'}" style="color: #06b6d4;">{video_url or 'N/A'}</a></p>
                <p><strong>YouTube URL:</strong> <a href="{youtube_url_out or '#'}" style="color: #ef4444;">{youtube_url_out or 'N/A'}</a></p>
            </div>
            """
            msg.attach(MIMEText(html_content, "html"))

            try:
                log(f"STEP 7 connecting to smtp.gmail.com:587 as {gmail_user} -> {owner_email}...")
                with smtplib.SMTP("smtp.gmail.com", 587) as server:
                    server.starttls()
                    server.login(gmail_user, gmail_pass)
                    server.sendmail(gmail_user, owner_email, msg.as_string())
            except Exception as email_err:
                _logger.exception(f"STEP 7 SMTP ERROR: {email_err}")
            else:
                log("STEP 7 Email report sent successfully!")
        else:
            log("STEP 7 Gmail credentials or owner email missing. Skipping email report step.")
        log("--- STEP 7: Email Report (Gmail SMTP) - COMPLETE ---")

        failed_stage = None  # clear -- pipeline succeeded

    except Exception as exc:
        pipeline_status = "FAILED"
        error_message = str(exc)
        if not failed_stage:
            failed_stage = "Unknown"
        _logger.exception(f"[Pipeline] FAILED at {failed_stage}: {exc}")
        raise HTTPException(status_code=500, detail=f"Pipeline failed at {failed_stage}: {exc}")

    finally:
        if temp_image_path and os.path.exists(temp_image_path):
            try:
                os.remove(temp_image_path)
            except Exception:
                pass

        # -----------------------------------------------------------------------
        # 8. EmailAgent notification (runs exactly once -- SUCCESS or FAILURE)
        # -----------------------------------------------------------------------
        finished_dt = datetime.now(timezone.utc)
        wall_clock_sec = int(time.time() - start_time)

        if notify_email:
            log(f"\n--- STEP 8: EmailAgent notification -> {notify_email!r} ---")
            run_snapshot = PipelineRunSnapshot(
                run_id=run_id,
                niche=niche,
                topic=topic or "",
                title=title or niche,
                youtube_url=youtube_url_out,
                youtube_id=youtube_id,
                notify_email=notify_email,
                started_at=started_dt,
                finished_at=finished_dt,
                status=pipeline_status,
                failed_stage=failed_stage,
                error_message=error_message,
                retry_count=retry_count,
            )
            # Pass the coroutine *function* + args to BackgroundTasks.
            # BackgroundTasks calls _send_notification(run_snapshot, ...) exactly
            # once after the response is sent.  The coroutine is NOT created here,
            # so asyncio.ensure_future cannot schedule it a second time.
            background_tasks.add_task(
                _send_notification,
                run_snapshot,
                pipeline_status == "SUCCESS",
                run_id,
            )
            log(f"--- STEP 8: EmailAgent notification queued ---")
        else:
            log("\n--- STEP 8: notify_email not provided -- skipping EmailAgent ---")

    # --------------------------------------------------------------------------
    # 9. Response Payload
    # --------------------------------------------------------------------------
    finished_at = finished_dt.isoformat()
    estimated_cost_usd = 0.016

    return {
        "runId": run_id,
        "niche": niche,
        "topic": topic,
        "script": {
            "narration": narration,
            "title": title,
            "description": description,
            "tags": tags
        },
        "images": [
            {
                "url": image_url,
                "prompt": image_prompt
            }
        ],
        "audio": {
            "provider": tts_provider,
            "url": audio_url
        },
        "video": {
            "url": video_url,
            "status": video_status
        },
        "youtube": {
            "videoId": youtube_id,
            "url": youtube_url_out
        },
        "meta": {
            "startedAt": started_at,
            "finishedAt": finished_at,
            "wallClockSec": wall_clock_sec,
            "estimatedCostUsd": estimated_cost_usd,
            "notifyEmail": notify_email,
            "emailQueued": notify_email is not None,
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5678, reload=False)
