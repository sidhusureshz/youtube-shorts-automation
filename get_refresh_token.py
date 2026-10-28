"""
Run this script ONCE to get a fresh YouTube refresh token.
Usage: python get_refresh_token.py
It will open a browser, ask you to log in with your Google account,
then print the new refresh_token to paste into your .env file.
"""

import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

if not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit("ERROR: YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET missing in .env")

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

print("\n========== COPY THIS INTO YOUR .env ==========")
print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
print("===============================================")
print(f"\nFull token length: {len(creds.refresh_token)} chars")
