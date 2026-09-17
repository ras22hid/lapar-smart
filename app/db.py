import os
import sqlite3
from datetime import datetime, date, timedelta

_INITIALIZED = False


def get_db_path():
    if os.environ.get("VERCEL"):
        return "/tmp/laparsmart.db"
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    instance_dir = os.path.join(base, "instance")
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, "laparsmart.db")


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

        # Defensive: a stray leading BOM (﻿) from how the env var was
        # set makes urllib reject the scheme ("unknown url type: ﻿libsql")
        # since ﻿ isn't whitespace and .strip() alone won't remove it.
        turso_url = turso_url.strip().lstrip("﻿")
        auth_token = os.environ.get("TURSO_AUTH_TOKEN")
        if auth_token:
            auth_token = auth_token.strip().lstrip("﻿")

        conn = turso_serverless.connect(turso_url, auth_token=auth_token)
        conn.row_factory = turso_serverless.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass
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

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id TEXT NOT NULL,
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
