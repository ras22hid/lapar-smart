"""Starts the application for the browser tests: temporary database, Gmail replaced by a stub that
records each email in <db>.outbox.jsonl. usage: serve_test.py <db file> <port>"""
import os, sys, tempfile, json
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "VERCEL"):
    os.environ.pop(k, None)
os.environ["SECRET_KEY"] = "std-test-key"
# Safety net: automated tests must never send real email, whatever the environment holds.
import smtplib


def _no_smtp(*args, **kwargs):
    raise RuntimeError("automated tests must never send real email")


smtplib.SMTP = _no_smtp

import warnings; warnings.simplefilter("ignore")
dbfile = sys.argv[1]
import app.db as dbmod
dbmod.get_db_path = lambda: dbfile
from app import create_app
import app.mailer as mailmod
OUTBOX = dbfile + ".outbox.jsonl"


def stub(to, subject, body, purpose):
    """Test environment: no Gmail credentials, so each email that would be
    sent is recorded in a file instead and the send counts as successful."""
    with open(OUTBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps({"to": to, "subject": subject, "body": body, "purpose": purpose}) + "\n")
    return True


mailmod._send_gmail = stub
import sqlite3
from werkzeug.security import generate_password_hash
app = create_app()
c = sqlite3.connect(dbfile)
c.execute("UPDATE admin SET password_hash=?, email=? WHERE admin_id='A001'", (generate_password_hash("AdminPass123"), "a001@example.com"))
c.commit(); c.close()
app.run(host="127.0.0.1", port=int(sys.argv[2]) if len(sys.argv) > 2 else 5077, debug=False, use_reloader=False, threaded=True)
