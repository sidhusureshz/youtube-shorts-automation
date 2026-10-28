"""
youtube_upload.py
=================
Upload a video file to YouTube via the Data API v3.

Usage:
    python youtube_upload.py <video_file> <title> <description> <tags>

Example:
    python youtube_upload.py test.mp4 "API test" "upload test" "test"

Reads credentials from .env:
    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN

On success  : prints video URL
On failure  : prints full HttpError status + reason and exits non-zero
"""

import os
import sys

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ── 0. Parse arguments ────────────────────────────────────────────────────────
if len(sys.argv) < 5:
    sys.exit(
        "Usage: python youtube_upload.py <video_file> <title> <description> <tags>\n"
        "Example: python youtube_upload.py test.mp4 \"API test\" \"upload test\" \"test\""
    )

VIDEO_FILE  = sys.argv[1]
TITLE       = sys.argv[2]
DESCRIPTION = sys.argv[3]
TAGS        = [t.strip() for t in sys.argv[4].split(",")]

# ── 1. Load credentials from .env ────────────────────────────────────────────
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH, override=True)

CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

print("=== youtube_upload.py ===")
print(f"YOUTUBE_CLIENT_ID      : {'SET (len=' + str(len(CLIENT_ID)) + ')' if CLIENT_ID else 'MISSING'}")
print(f"YOUTUBE_CLIENT_SECRET  : {'SET (len=' + str(len(CLIENT_SECRET)) + ')' if CLIENT_SECRET else 'MISSING'}")
print(f"YOUTUBE_REFRESH_TOKEN  : {'SET (len=' + str(len(REFRESH_TOKEN)) + ')' if REFRESH_TOKEN else 'MISSING'}")
print(f"Video file             : {VIDEO_FILE}")
print(f"Title                  : {TITLE}")
print(f"Description            : {DESCRIPTION}")
print(f"Tags                   : {TAGS}")

missing = [k for k, v in {
    "YOUTUBE_CLIENT_ID": CLIENT_ID,
    "YOUTUBE_CLIENT_SECRET": CLIENT_SECRET,
    "YOUTUBE_REFRESH_TOKEN": REFRESH_TOKEN,
}.items() if not v]
if missing:
    sys.exit(f"ERROR: missing credentials in .env: {', '.join(missing)}\n"
             "Run: python youtube_auth.py")

if not os.path.isfile(VIDEO_FILE):
    sys.exit(f"ERROR: video file not found: {VIDEO_FILE}")

# ── 2. Build OAuth credentials ───────────────────────────────────────────────
print("\n--- Step 1: Refreshing access token ---")
try:
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds.refresh(Request())
    print(f"Token refresh          : OK (expiry: {creds.expiry})")
except Exception as e:
    print(f"Token refresh FAILED: {type(e).__name__}: {e}")
    if "invalid_grant" in str(e):
        print("\nFix: Run  python youtube_auth.py  to get a new refresh token.")
    sys.exit(1)

# ── 3. Build YouTube client ───────────────────────────────────────────────────
print("\n--- Step 2: Uploading video ---")
try:
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title":       TITLE,
            "description": DESCRIPTION,
            "tags":        TAGS,
            "categoryId":  "22",   # People & Blogs
        },
        "status": {
            "privacyStatus": "private",   # safe default; stays private
        },
    }

    media = MediaFileUpload(
        VIDEO_FILE,
        mimetype="video/mp4",
        resumable=True,
        chunksize=256 * 1024,   # 256 KB chunks
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Upload progress: {pct}%")

    video_id = response.get("id")
    if not video_id:
        sys.exit(f"ERROR: Upload seemed to succeed but no video ID returned.\nResponse: {response}")

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"\n=== RESULT: SUCCESS ===")
    print(f"Video ID               : {video_id}")
    print(f"Video URL              : {video_url}")
    print(f"Privacy                : private (expected — API audit not yet passed)")
    sys.exit(0)

except HttpError as e:
    status_code = e.resp.status
    reason = ""
    try:
        import json
        err_content = json.loads(e.content.decode("utf-8"))
        reason = err_content.get("error", {}).get("message", str(e.content))
        errors = err_content.get("error", {}).get("errors", [])
        domain = errors[0].get("domain", "") if errors else ""
        err_reason = errors[0].get("reason", "") if errors else ""
    except Exception:
        reason = str(e.content)
        err_reason = ""

    print(f"\n=== RESULT: FAILURE ===")
    print(f"HttpError status       : {status_code}")
    print(f"Reason                 : {reason}")
    print(f"Full error text        : {e}")

    # Interpret known errors
    if "invalid_grant" in str(e):
        print("\nDiagnosis: Refresh token is dead.")
        print("Fix: Run  python youtube_auth.py  to re-authorise.")
    elif "accessNotConfigured" in str(e) or err_reason == "accessNotConfigured":
        print("\nDiagnosis: YouTube Data API v3 not enabled in Google Cloud project.")
        print("Fix: https://console.cloud.google.com/apis/library/youtube.googleapis.com")
    elif "quotaExceeded" in str(e) or err_reason == "quotaExceeded":
        print("\nDiagnosis: Daily 10,000-unit quota exhausted.")
        print("Fix: Wait until midnight Pacific Time for quota reset.")
    elif status_code == 403:
        print("\nDiagnosis: Forbidden — check API enablement and OAuth scopes.")
    elif status_code == 401:
        print("\nDiagnosis: Unauthorised — token may be expired or revoked.")

    sys.exit(1)

except Exception as e:
    print(f"\n=== RESULT: FAILURE ===")
    print(f"Unexpected error       : {type(e).__name__}: {e}")
    sys.exit(1)
