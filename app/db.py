import os
import sqlite3
from datetime import datetime, date, timedelta

_INITIALIZED = False


def clean_env_value(value):
    """Strips whitespace and any non-ASCII character from an env var value.

    Credentials pasted through different UIs (PowerShell piping, a
    dashboard's bulk .env import box, etc.) have repeatedly picked up
    invisible characters -- a leading BOM, smart quotes, zero-width
    spaces -- that survive a plain .strip() and corrupt the value just
    enough to break urllib/http.client's latin-1 header encoding or a
    URL scheme check. Every value this app reads this way (Turso URL/
    token, Gmail address/app password, secret key) is always plain
    ASCII, so stripping non-ASCII bytes outright is safe and catches
    the whole class of corruption instead of one specific character.
    """
    if value is None:
        return value
    return value.encode("ascii", "ignore").decode("ascii").strip()


def get_db_path():
    if os.environ.get("VERCEL"):
        return "/tmp/laparsmart.db"
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    instance_dir = os.path.join(base, "instance")
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, "laparsmart.db")


def _lean_connection_class():
    """turso_serverless sends every statement as its own HTTPS request over a
    brand-new TCP/TLS connection (urllib, no keep-alive), so each avoidable
    request costs a full handshake -- roughly 0.7 s when the function and the
    database are on different continents. Two requests the stock connection
    makes on every page load are not needed for reads:

    * `PRAGMA foreign_keys = ON` right after connecting -- only writes need
      foreign keys enforced, so it is now sent just before the first write.
    * the stream `close` on `conn.close()` -- Turso expires idle streams by
      itself; it is still sent when a transaction is open, so uncommitted
      work is rolled back immediately and never holds the write lock.
    """
    from turso_serverless.connection import Connection
    from turso_serverless.dbapi import _is_dml

    class LeanConnection(Connection):
        _foreign_keys_on = False

        def _maybe_implicit_begin(self, sql):
            if self._session._baton is None:
                self._foreign_keys_on = False
            if not self._foreign_keys_on and not self.in_transaction and _is_dml(sql):
                try:
                    self._execute_stmt("PRAGMA foreign_keys = ON", want_rows=False)
                except Exception:
                    pass
                self._foreign_keys_on = True
            super()._maybe_implicit_begin(sql)

        def close(self):
            if self._closed:
                return
            if self.in_transaction:
                super().close()
            else:
                self._session._reset_stream()
                self._closed = True

    return LeanConnection


_LEAN = None


def get_db():
    """Returns a DB-API connection. When TURSO_DATABASE_URL is set (always
    the case in production, since Vercel's /tmp is wiped per instance and
    was silently dropping orders written by a different warm instance) this
    is a remote Turso database; otherwise it's a local sqlite3 file for
    offline development. turso_serverless is DB-API 2.0 / sqlite3-shaped
    (.execute/.executemany/.executescript, cursor.lastrowid, row_factory),
    so nothing outside this function needs to know which backend is active."""
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    if turso_url:
        import turso_serverless
        from turso_serverless.session import Session

        turso_url = clean_env_value(turso_url)
        auth_token = clean_env_value(os.environ.get("TURSO_AUTH_TOKEN"))

        global _LEAN
        if _LEAN is None:
            _LEAN = _lean_connection_class()
        conn = _LEAN(Session(turso_url, auth_token=auth_token))
        conn.row_factory = turso_serverless.Row
        return conn

    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS staff (
    staff_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS admin (
    admin_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    password_hash TEXT,
    email TEXT
);

CREATE TABLE IF NOT EXISTS password_reset (
    token TEXT PRIMARY KEY,
    admin_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (admin_id) REFERENCES admin (admin_id)
);

CREATE TABLE IF NOT EXISTS menu_item (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    category TEXT NOT NULL,
    available_date TEXT NOT NULL,
    is_available INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS menu_item_image (
    item_id INTEGER PRIMARY KEY,
    mime TEXT NOT NULL,
    data TEXT NOT NULL,
    updated TEXT NOT NULL,
    FOREIGN KEY (item_id) REFERENCES menu_item (item_id)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id TEXT NOT NULL,
    staff_name TEXT,
    department TEXT,
    phone_number TEXT,
    order_type TEXT NOT NULL DEFAULT 'Counter',
    status TEXT NOT NULL DEFAULT 'Pending',
    total_amount REAL NOT NULL DEFAULT 0,
    order_date TEXT NOT NULL,
    meeting_room TEXT,
    meeting_time TEXT,
    package_name TEXT,
    package_pax INTEGER,
    package_qty INTEGER,
    FOREIGN KEY (staff_id) REFERENCES staff (staff_id)
);

CREATE TABLE IF NOT EXISTS catering_package (
    package_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    pax INTEGER NOT NULL,
    price REAL NOT NULL,
    description TEXT,
    is_available INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS order_item (
    order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders (order_id),
    FOREIGN KEY (item_id) REFERENCES menu_item (item_id)
);

CREATE TABLE IF NOT EXISTS notification (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    sent_time TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES orders (order_id)
);

CREATE TABLE IF NOT EXISTS survey_response (
    response_id INTEGER PRIMARY KEY AUTOINCREMENT,
    submitted_at TEXT NOT NULL,
    q1 TEXT NOT NULL,
    q2 TEXT NOT NULL,
    q3 TEXT NOT NULL,
    q4 TEXT NOT NULL,
    q5 TEXT NOT NULL
);
"""


def seed(conn):
    today = date.today().isoformat()

    staff = [
        ("S001", "Ahmad Zaki", "Marketing Division"),
        ("S002", "Nur Aina", "Finance Division"),
        ("S003", "Ravi Kumar", "IT Division"),
    ]
    conn.executemany(
        "INSERT INTO staff (staff_id, name, department, active) VALUES (?, ?, ?, 1)",
        staff,
    )

    admins = [("A001", "Admin Farah", "Cafe Admin")]
    conn.executemany(
        "INSERT INTO admin (admin_id, name, role, active) VALUES (?, ?, ?, 1)",
        admins,
    )

    menu = [
        ("Nasi Lemak Ayam", 6.50, "Food", today),
        ("Mee Goreng Mamak", 5.00, "Food", today),
        ("Roti Canai", 1.80, "Food", today),
        ("Fried Chicken Set", 8.50, "Food", today),
        ("Teh Tarik", 2.00, "Beverage", today),
        ("Kopi O", 1.50, "Beverage", today),
        ("Iced Milo", 2.50, "Beverage", today),
    ]
    conn.executemany(
        "INSERT INTO menu_item (name, price, category, available_date, is_available) VALUES (?, ?, ?, ?, 1)",
        menu,
    )

    packages = [
        ("Snack Box Package", 10, 120.00, "Assorted sandwiches, curry puffs & mineral water for 10 people."),
        ("Standard Meeting Package", 20, 220.00, "Nasi lemak sets, finger food & drinks for 20 people."),
        ("Premium Conference Package", 30, 320.00, "Full meal boxes, desserts & beverages for 30 people."),
    ]
    conn.executemany(
        "INSERT INTO catering_package (name, pax, price, description, is_available) VALUES (?, ?, ?, ?, 1)",
        packages,
    )
    conn.commit()


def init_db():
    global _INITIALIZED
    if _INITIALIZED:
        return
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    # Migration for databases created before password_hash existed (both the
    # local sqlite file and the already-provisioned Turso database) -- a
    # fresh CREATE TABLE above already includes the column, so this is a
    # no-op there and only does real work on an older database.
    try:
        conn.execute("ALTER TABLE admin ADD COLUMN password_hash TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE admin ADD COLUMN email TEXT")
        conn.commit()
    except Exception:
        pass
    # Migration for databases created before FAMA staff identified
    # themselves per-order (Staff ID/Name/Department/Phone Number keyed
    # in at the Review Order step) instead of being pre-registered by a
    # Cafe Admin -- a fresh CREATE TABLE above already includes these
    # columns, so this is a no-op there and only does real work on an
    # older database.
    for column in ("staff_name", "department", "phone_number"):
        try:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")
            conn.commit()
        except Exception:
            pass
    row = conn.execute("SELECT COUNT(*) AS c FROM menu_item").fetchone()
    if row["c"] == 0:
        seed(conn)
    conn.close()
    _INITIALIZED = True


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return date.today().isoformat()


def future_str(minutes):
    return (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
