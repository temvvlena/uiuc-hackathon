"""Read farmers' real texts from the Mac's Messages database and answer them (sign-up + replies).

  python listen.py            # answer every new text until Ctrl-C
  python listen.py --once     # answer one text, exit

Only answers numbers in HERDX_PHONES (comma-separated in .env; default FARMER_PHONE), so your
friends' texts to your Mac are never answered by HerdX.

Needs Full Disk Access for the app running Python (Terminal / iTerm / VS Code):
System Settings > Privacy & Security > Full Disk Access. Only reads; never writes the database.
"""
import argparse
import os
import re
import sqlite3
import time

from sms import e164

DB = os.path.expanduser("~/Library/Messages/chat.db")


def _connect():
    try:
        return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        raise SystemExit(f"Can't open {DB} ({e}).\nGive Full Disk Access to the app running Python "
                         "(System Settings > Privacy & Security > Full Disk Access), then restart it.")


def _decode_body(blob):
    """Newer macOS stores the text only in attributedBody (an NSArchiver blob)."""
    if not blob:
        return None
    try:
        s = blob.split(b"NSString")[1][5:]
        if s[0] == 0x81:
            n = int.from_bytes(s[1:3], "little")
            s = s[3:3 + n]
        else:
            n = s[0]
            s = s[1:1 + n]
        return s.decode("utf-8", errors="ignore")
    except Exception:
        return None


def _digits(n):
    return re.sub(r"\D", "", n or "")[-10:]


def _is_phone(handle):
    """A real phone number: not an email address and not a 5 or 6 digit short code."""
    return "@" not in (handle or "") and len(re.sub(r"\D", "", handle or "")) >= 10


def latest_rowid(con):
    return con.execute("SELECT IFNULL(MAX(ROWID), 0) FROM message").fetchone()[0]


def new_replies(con, after, phone):
    """[(rowid, text)] received from `phone` with ROWID > after."""
    return [(r, t) for r, t, _ in new_texts(con, after, [phone])]


def new_texts(con, after, phones):
    """[(rowid, text, sender)] received from any of `phones` with ROWID > after."""
    want = None if phones is None else {_digits(p) for p in phones}   # None = anyone (--open)
    rows = con.execute(
        """SELECT m.ROWID, m.text, m.attributedBody, h.id FROM message m
           JOIN handle h ON m.handle_id = h.ROWID
           WHERE m.ROWID > ? AND m.is_from_me = 0 ORDER BY m.ROWID""", (after,)).fetchall()
    out = []
    for rowid, text, body, handle in rows:
        ok = (_digits(handle) in want) if want is not None else _is_phone(handle)
        if ok:
            t = text or _decode_body(body)
            if t:
                out.append((rowid, t.strip(), handle))
    return out


def allowed_phones():
    raw = os.getenv("HERDX_PHONES") or os.getenv("FARMER_PHONE") or ""
    return [e164(p) for p in raw.split(",") if p.strip()]


def wait_for_reply(timeout=600, poll=2.0):
    """Block until the farmer texts back; return the text (or None on timeout)."""
    phone = e164(os.getenv("FARMER_PHONE"))
    con = _connect()
    last = latest_rowid(con)
    print(f"(waiting for a text from {phone} ...)")
    t0 = time.time()
    while time.time() - t0 < timeout:
        got = new_replies(con, last, phone)
        if got:
            return got[0][1]
        time.sleep(poll)
    return None


if __name__ == "__main__":
    from onboard import farm_path, purge_stale_signups, route, signup_path
    from sms import log_in, send
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print answers instead of texting them")
    ap.add_argument("--open", action="store_true",
                    help="answer any phone number that texts JOIN (for a live audience); "
                         "texts from other people that are not part of a sign-up are ignored")
    a = ap.parse_args()
    phones = allowed_phones()
    if not phones and not a.open:
        raise SystemExit("Set FARMER_PHONE (or HERDX_PHONES) in .env")
    known = {_digits(p) for p in phones}
    con = _connect()
    last = latest_rowid(con)
    print("OPEN: anyone who texts JOIN gets answered. Ctrl-C to stop." if a.open
          else f"Listening for texts from {', '.join(phones)}. Ctrl-C to stop.")
    last_purge = 0
    while True:
        if time.time() - last_purge > 60:      # drop sign-ups abandoned half-way
            purge_stale_signups()
            last_purge = time.time()
        for rowid, text, sender in new_texts(con, last, None if a.open else phones):
            last = rowid
            if a.open and _digits(sender) not in known and text.upper() not in ("JOIN", "START") \
                    and not os.path.exists(signup_path(sender)) and not os.path.exists(farm_path(sender)):
                continue                       # someone's ordinary text to this phone: stay silent
            log_in(text)
            print(f"\n{sender}: {text}")
            try:
                replies, _ = route(sender, text)
                for r in replies:
                    send(r, to=sender, dry=a.dry_run)
            except Exception as e:             # one bad text must not stop the listener
                print(f"[could not answer {sender}] {type(e).__name__}: {e}")
            if a.once:
                raise SystemExit(0)
        time.sleep(2)
