"""
youtube_auth.py
===============
Re-authorise this app and write a fresh YOUTUBE_REFRESH_TOKEN to .env.

Usage:
    python youtube_auth.py

Reads YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET from .env, opens your
browser for Google OAuth consent, then writes the new refresh token back
into .env in-place.  The token value is NEVER printed.
"""

import os
import re
import sys

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH, override=True)

CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
OLD_TOKEN     = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

print("=== youtube_auth.py ===")
print("YOUTUBE_CLIENT_ID     :", "SET (len=" + str(len(CLIENT_ID)) + ")" if CLIENT_ID else "MISSING")
print("YOUTUBE_CLIENT_SECRET :", "SET (len=" + str(len(CLIENT_SECRET)) + ")" if CLIENT_SECRET else "MISSING")

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("ERROR: YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET missing in .env")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

client_config = {
    "installed": {
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["http://localhost"],
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
    }
}

print("\nOpening browser for Google OAuth consent...")
print("  > Sign in as the YouTube account owner")
print("  > Click 'Allow' on the permissions screen")
print("  > The browser tab will close automatically\n")

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
creds = flow.run_local_server(
    port=0,
    prompt="consent",
    access_type="offline",
    open_browser=True,
)

new_token = creds.refresh_token
if not new_token:
    sys.exit(
        "ERROR: Google did not return a refresh_token.\n"
        "Make sure you clicked Allow and that the OAuth app allows refresh tokens."
    )

print("New token received    : len=" + str(len(new_token)) + ", tail=..." + new_token[-4:])

# Write new token into .env (in-place, never print full value)
with open(ENV_PATH, "r", encoding="utf-8") as f:
    env_text = f.read()

new_line = "YOUTUBE_REFRESH_TOKEN=" + new_token
env_text, n = re.subn(
    r"^YOUTUBE_REFRESH_TOKEN=.*$",
    new_line,
    env_text,
    flags=re.MULTILINE,
)

if n == 0:
    env_text = env_text.rstrip("\n") + "\n" + new_line + "\n"
    print(".env: YOUTUBE_REFRESH_TOKEN line appended (was missing)")
elif n == 1:
    print(".env: YOUTUBE_REFRESH_TOKEN line updated successfully")
else:
    print(f"WARNING: replaced {n} occurrences of YOUTUBE_REFRESH_TOKEN=")

with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
    f.write(env_text)

# Verify
load_dotenv(ENV_PATH, override=True)
saved_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
if saved_token != new_token:
    sys.exit("ERROR: written token does not match what was saved in .env!")

print("Token saved to .env successfully.")

# Quick API ping to confirm
try:
    yt   = build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if items:
        ch   = items[0]
        name = ch["snippet"]["title"]
        vids = ch["statistics"].get("videoCount", "?")
        print("Channel               :", name)
        print("Total videos          :", vids)
    else:
        print("API call OK - no channel found on this account yet.")
    print("\nOK: YouTube OAuth is working. New refresh token saved to .env.")
except Exception as e:
    print("API verification error:", type(e).__name__, ":", e)
    print("Token was saved to .env but API call failed - check scopes or account.")
