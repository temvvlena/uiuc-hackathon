"""Send a text to the farmer. Backend is chosen in .env with SMS_BACKEND:

  messages  real SMS from your Mac's Messages app, sent through your iPhone
            (needs Text Message Forwarding on the iPhone for this Mac)
  twilio    Twilio REST API (trial accounts can't send custom text - kept as a fallback)
  dry       print only (also: --dry-run, HERDX_DRY_RUN=1, or missing settings)

.env:
  SMS_BACKEND=messages
  FARMER_PHONE=+1xxxxxxxxxx        # the second iPhone (the "farmer")
  MESSAGES_SERVICE=sms             # sms (green bubbles) or imessage (fallback)
  TWILIO_ACCOUNT_SID= / TWILIO_AUTH_TOKEN= / TWILIO_FROM=   # only for SMS_BACKEND=twilio
"""
import os
import re
import subprocess
from datetime import datetime

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUTBOX = os.path.join(HERE, "outbox.log")


def load_env(path=os.path.join(HERE, ".env")):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()


def e164(n):
    """'+1 309-292 2660' -> '+13092922660'"""
    return re.sub(r"[^\d+]", "", n) if n else n


def _log(direction, text):
    with open(OUTBOX, "a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {direction} {text}\n")


def log_in(text):
    _log("IN ", text)


# AppleScript gets the text and number as arguments, so quotes in the message need no escaping.
_APPLESCRIPT = """
on run argv
    set msg to item 1 of argv
    set phone to item 2 of argv
    set svc to item 3 of argv
    tell application "Messages"
        if svc is "sms" then
            set acct to 1st account whose service type = SMS
        else
            set acct to 1st account whose service type = iMessage
        end if
        send msg to participant phone of acct
    end tell
end run
"""


def _send_messages(text, to):
    svc = os.getenv("MESSAGES_SERVICE", "sms").lower()
    r = subprocess.run(["osascript", "-e", _APPLESCRIPT, text, to, svc],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        hint = ("\nNo SMS account in Messages? Turn on Text Message Forwarding for this Mac on your "
                "iPhone, or set MESSAGES_SERVICE=imessage." if svc == "sms" else "")
        raise RuntimeError(f"Messages send failed: {r.stderr.strip()}{hint}")
    return "MESSAGES"


def _send_twilio(text, to):
    sid, token, frm = (os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"),
                       e164(os.getenv("TWILIO_FROM")))
    r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                      data={"From": frm, "To": to, "Body": text}, auth=(sid, token), timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"Twilio error {r.status_code}: {r.text[:300]}")
    return r.json()["sid"]


def backend(dry=False):
    b = os.getenv("SMS_BACKEND", "twilio").lower()
    if dry or os.getenv("HERDX_DRY_RUN") == "1" or not os.getenv("FARMER_PHONE"):
        return "dry"
    if b == "twilio" and not all(os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM")):
        return "dry"
    return b


def send(text, to=None, dry=False):
    if text is None:
        return None
    to = e164(to or os.getenv("FARMER_PHONE"))
    b = backend(dry)
    segs = -(-len(text) // 153) if len(text) > 160 else 1
    label = "(DRY RUN) " if b == "dry" else f"via {b} "
    print(f"\n--- SMS {label}to {to or 'farmer'} [{len(text)} chars, {segs} seg] ---\n{text}\n")
    _log("OUT", text)
    if b == "dry":
        return "DRY-RUN"
    if b == "messages":
        return _send_messages(text, to)
    return _send_twilio(text, to)
