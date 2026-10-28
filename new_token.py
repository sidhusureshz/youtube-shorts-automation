"""
new_token.py
============
Forces Google to issue a BRAND NEW YouTube OAuth refresh token and writes it
directly into .env.  Never prints the token value.

Usage:
    python new_token.py

What it does:
  1. Loads YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET from .env.
  2. Opens a browser with prompt=consent + access_type=offline so Google
     ALWAYS issues a fresh refresh_token (even if one already exists).
  3. Receives the callback on a random localhost port (no firewall rule needed).
  4. Reads .env as text, replaces the YOUTUBE_REFRESH_TOKEN= line in-place,
     and writes the file back.  Never prints or logs the token value.
  5. Verifies the new token by calling channels.list and prints the channel
     name + video count to confirm everything works.
"""

import os
import re
import sys

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── 0. Load credentials ──────────────────────────────────────────────────────
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH, override=True)

CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
OLD_TOKEN     = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

print("=== new_token.py ===")
print("YOUTUBE_CLIENT_ID     : " + ("SET (len=" + str(len(CLIENT_ID)) + ")" if CLIENT_ID else "MISSING"))
print("YOUTUBE_CLIENT_SECRET : " + ("SET (len=" + str(len(CLIENT_SECRET)) + ")" if CLIENT_SECRET else "MISSING"))
print("Current token OLD_TAIL: ..." + (OLD_TOKEN[-4:] if OLD_TOKEN else "N/A"))

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("ERROR: YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET missing in .env")

# ── 1. OAuth flow — always forces re-consent so Google issues fresh token ─────
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
    port=0,               # random available port -- avoids firewall issues
    prompt="consent",     # force consent screen so a new refresh_token is issued
    access_type="offline",
    open_browser=True,
)

new_token = creds.refresh_token
if not new_token:
    sys.exit(
        "ERROR: Google did not return a refresh_token.\n"
        "Make sure you clicked Allow and that the OAuth app is not in\n"
        "test mode with unverified scopes blocking refresh tokens."
    )

print("New token received    : len=" + str(len(new_token)) + ", tail=..." + new_token[-4:])

# ── 2. Write new token into .env (in-place, never print full value) ───────────
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
    print("WARNING: replaced " + str(n) + " occurrences of YOUTUBE_REFRESH_TOKEN= (kept last)")

with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
    f.write(env_text)

# ── 3. Verify: re-load .env and confirm the token was saved ───────────────────
print("\n--- Verification ---")
load_dotenv(ENV_PATH, override=True)
saved_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "")

if saved_token != new_token:
    sys.exit("ERROR: written token does not match what was saved in .env!")

print("Saved token tail      : ..." + saved_token[-4:])
print("Saved token length    : " + str(len(saved_token)))
print("OLD_TAIL == NEW_TAIL  : " + str(OLD_TOKEN[-4:] == saved_token[-4:]) +
      " (False = new token confirmed)")

# Quick API ping
try:
    yt   = build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if items:
        ch   = items[0]
        name = ch["snippet"]["title"]
        vids = ch["statistics"].get("videoCount", "?")
        print("Channel               : " + name)
        print("Total videos          : " + str(vids))
    else:
        print("API call OK but no channel returned (account may have no channel yet)")
    print("\nOK: YouTube OAuth is working. New refresh token saved to .env.")
except Exception as e:
    print("API verification error: " + type(e).__name__ + ": " + str(e))
    print("Token was saved to .env but API call failed -- check scopes or account.")
