"""
Standalone SMTP connectivity check.
Prints only "OK" or the exception type + message for each method.
Never prints the password.
"""
import os
import smtplib
from dotenv import load_dotenv

load_dotenv(override=True)

HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
USER = os.getenv("SMTP_USER", os.getenv("GMAIL_ADDRESS", ""))
PASS = os.getenv("SMTP_PASSWORD", os.getenv("GMAIL_APP_PASSWORD", ""))

# ── Method A: STARTTLS on port 587 ──────────────────────────────────────────
print("=== Method A: SMTP port 587 + STARTTLS ===")
try:
    with smtplib.SMTP(HOST, 587, timeout=20) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(USER, PASS)
        s.quit()
    print("587 STARTTLS: OK")
except Exception as exc:
    print(f"587 STARTTLS: {type(exc).__name__}: {exc}")

# ── Method B: SMTP_SSL on port 465 ──────────────────────────────────────────
print("=== Method B: SMTP_SSL port 465 ===")
try:
    with smtplib.SMTP_SSL(HOST, 465, timeout=20) as s:
        s.login(USER, PASS)
        s.quit()
    print("465 SSL: OK")
except Exception as exc:
    print(f"465 SSL: {type(exc).__name__}: {exc}")
