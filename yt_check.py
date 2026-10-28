"""
yt_check.py  --  Verify YouTube OAuth credentials from .env
Prints only status, token length, and public channel info.
NEVER prints any secret value.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

token  = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
cid    = os.getenv("YOUTUBE_CLIENT_ID", "")
csec   = os.getenv("YOUTUBE_CLIENT_SECRET", "")

print("=== YouTube Credential Pre-check ===")
print(f"YOUTUBE_CLIENT_ID      : {'SET (len='+str(len(cid))+')' if cid else 'MISSING'}")
print(f"YOUTUBE_CLIENT_SECRET  : {'SET (len='+str(len(csec))+')' if csec else 'MISSING'}")
print(f"YOUTUBE_REFRESH_TOKEN  : {'SET (len='+str(len(token))+')' if token else 'MISSING'}")

if not (token and cid and csec):
    sys.exit("ERROR: one or more credentials missing in .env")

print("\n--- Step 1: Refreshing access token ---")
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = Credentials(
        token=None,
        refresh_token=token,
        client_id=cid,
        client_secret=csec,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    print(f"Token refresh   : OK")
    print(f"Access token len: {len(creds.token)}")
    print(f"Expiry          : {creds.expiry}")
except Exception as e:
    print(f"Token refresh FAILED: {type(e).__name__}: {e}")
    sys.exit(1)

print("\n--- Step 2: Calling YouTube Data API (channels.list) ---")
try:
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        print("No channels found for this account.")
    else:
        for ch in items:
            sn = ch.get("snippet", {})
            st = ch.get("statistics", {})
            print(f"Channel title   : {sn.get('title')}")
            print(f"Channel ID      : {ch.get('id')}")
            print(f"Subscribers     : {st.get('subscriberCount', 'hidden')}")
            print(f"Total videos    : {st.get('videoCount')}")
    print("\nYouTube OAuth: ALL GOOD ✅")
except Exception as e:
    print(f"YouTube API call FAILED: {type(e).__name__}: {e}")
    sys.exit(1)
