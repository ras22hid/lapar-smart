import io
import base64
import random

from flask import Blueprint, Response, abort, current_app, render_template, request, redirect, url_for, jsonify
from itsdangerous import BadSignature, URLSafeSerializer

from .db import get_db, now_str, today_str

staff_bp = Blueprint("staff", __name__)

ORDERS_COOKIE = "lapar_orders"
ORDERS_COOKIE_MAX_AGE = 30 * 24 * 3600
MAX_REMEMBERED_ORDERS = 10


def _orders_serializer():
    return URLSafeSerializer(current_app.secret_key, salt="lapar-recent-orders")


def recent_order_ids():
    """Order IDs placed from this browser, read from a signed cookie. Staff
    no longer type a Staff ID on the menu page, so this is how the menu's
    Order Status / Order History panel knows which orders are 'theirs'. The
    cookie is signed so it can't be edited to list someone else's orders."""
    raw = request.cookies.get(ORDERS_COOKIE)
    if not raw:
        return []
    try:
        ids = _orders_serializer().loads(raw)
    except BadSignature:
        return []
    return [i for i in ids if isinstance(i, int)][:MAX_REMEMBERED_ORDERS]


def redirect_to_order_status(order_id, staff_id):
    resp = redirect(url_for("staff.order_status", order_id=order_id, staff_id=staff_id))
    ids = [order_id] + [i for i in recent_order_ids() if i != order_id]
    resp.set_cookie(
        ORDERS_COOKIE,
        _orders_serializer().dumps(ids[:MAX_REMEMBERED_ORDERS]),
        max_age=ORDERS_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )
    return resp


def qr_data_uri(target_url):
    """Generate a QR code as a base64 data URI (UC1: Scan QR Code)."""
    try:
        import qrcode

        img = qrcode.make(target_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return None


@staff_bp.route("/")
def landing():
    """UC1: Scan QR Code - landing page that a physical QR code points to."""
    menu_url = request.host_url.rstrip("/") + url_for("staff.menu")
    qr_uri = qr_data_uri(menu_url)
    # The QR code is the point of this page, so a database hiccup must never
    # take it down.
    try:
        db = get_db()
        rows = db.execute(
            "SELECT m.item_id, m.name, m.price, m.category, m.available_date, "
            "(SELECT updated FROM menu_item_image i WHERE i.item_id = m.item_id) AS image_v "
            "FROM menu_item m WHERE m.is_available = 1"
        ).fetchall()
        db.close()
        picks = todays_picks(rows)
    except Exception:
        picks = []
    return render_template("landing.html", qr_uri=qr_uri, menu_url=menu_url, picks=picks)


def todays_picks(rows, count=3):
    """Pick the dishes teased on the homepage from the live daily menu.
    Whatever the Cafe Admin added most recently comes first, so a freshly
    updated menu shows up straight away; any remaining slots are filled from
    the rest of the available items. Within each group the order is shuffled
    with today's date as the seed, so the picks change every day but stay
    stable for everyone looking on the same day."""
    rng = random.Random(today_str())
    newest = max((r["available_date"] for r in rows), default=None)
    fresh = [r for r in rows if r["available_date"] == newest]
    rest = [r for r in rows if r["available_date"] != newest]
    # Sort first so the seeded shuffle doesn't depend on database row order.
    for group in (fresh, rest):
        group.sort(key=lambda r: r["item_id"])
        rng.shuffle(group)
    return (fresh + rest)[:count]


@staff_bp.route("/menu")
def menu():
    """UC2: View Daily Menu. Browsing is anonymous -- staff only identify
    themselves (Staff ID, Name, Department, Phone Number) at the Review
    Order step after choosing what to order, not before."""
    db = get_db()
    # Not filtered by available_date: an item stays on the menu across days
    # once added, until the admin explicitly hides or deletes it (see
    # admin.menu() below) -- available_date is only a "date added" record,
    # not an expiry, so the menu doesn't silently go empty every midnight.
    items = db.execute(
        "SELECT m.*, (SELECT updated FROM menu_item_image i WHERE i.item_id = m.item_id) AS image_v "
        "FROM menu_item m WHERE m.is_available = 1 ORDER BY m.category, m.name",
    ).fetchall()
    packages = db.execute(
        "SELECT * FROM catering_package WHERE is_available = 1 ORDER BY pax"
    ).fetchall()
    my_orders = []
    order_ids = recent_order_ids()
    if order_ids:
        placeholders = ",".join("?" * len(order_ids))
        my_orders = db.execute(
            f"SELECT * FROM orders WHERE order_id IN ({placeholders}) ORDER BY order_id DESC",
            order_ids,
        ).fetchall()
    db.close()
    return render_template(
        "menu.html", items=items, packages=packages, today=today_str(), my_orders=my_orders
    )


@staff_bp.route("/menu/image/<int:item_id>")
def menu_image(item_id):
    """Serves the food photo a Cafe Admin uploaded for a menu item. Stored in
    the database (not on disk) because Vercel's filesystem is ephemeral. The
    template appends ?v=<updated> so a replaced photo busts the cache."""
    db = get_db()
    row = db.execute(
        "SELECT mime, data FROM menu_item_image WHERE item_id = ?", (item_id,)
    ).fetchone()
    db.close()
    if row is None:
        abort(404)
    resp = Response(base64.b64decode(row["data"]), mimetype=row["mime"])
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@staff_bp.route("/order/review", methods=["POST"])
def review_order():
    """Intermediate step between choosing items and placing the order:
    shows what's about to be ordered and collects Staff ID, Name,
    Department, and Phone Number -- captured here, per order, rather
    than looked up from a Cafe Admin-managed staff registry."""
    order_type = request.form.get("order_type", "Counter")
    meeting_room = request.form.get("meeting_room", "")
    meeting_time = request.form.get("meeting_time", "")

    db = get_db()

    if order_type == "MeetingRoom":
        package_id = request.form.get("package_id")
        package_qty = int(request.form.get("package_qty") or 0)
        package = None
        if package_id:
            package = db.execute(
                "SELECT * FROM catering_package WHERE package_id = ?", (package_id,)
            ).fetchone()
        db.close()
        if not package or package_qty <= 0:
            return redirect(url_for("staff.menu", error="empty_cart"))
        return render_template(
            "review_order.html",
            order_type=order_type,
            meeting_room=meeting_room,
            meeting_time=meeting_time,
            package=package,
            package_id=package_id,
            package_qty=package_qty,
            cart_items=None,
            total=package["price"] * package_qty,
        )

    item_ids = request.form.getlist("item_id")
    quantities = request.form.getlist("quantity")
    cart_items = []
    total = 0.0
    for item_id, qty in zip(item_ids, quantities):
        qty = int(qty)
        if qty <= 0:
            continue
        row = db.execute("SELECT * FROM menu_item WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            continue
        subtotal = row["price"] * qty
        total += subtotal
        cart_items.append({"item_id": item_id, "name": row["name"], "quantity": qty, "subtotal": subtotal})
    db.close()

    if not cart_items:
        return redirect(url_for("staff.menu", error="empty_cart"))

    return render_template(
        "review_order.html",
        order_type=order_type,
        meeting_room=meeting_room,
        meeting_time=meeting_time,
        package=None,
        cart_items=cart_items,
        total=total,
    )


@staff_bp.route("/order", methods=["POST"])
def place_order():
    """UC3: Place Order (counter order) and UC4: Reserve Meeting Room Order
    (bulk catering package) -- final submission from the Review Order page."""
    staff_id = request.form.get("staff_id", "").strip()
    staff_name = request.form.get("staff_name", "").strip()
    department = request.form.get("department", "").strip()
    phone_number = request.form.get("phone_number", "").strip()
    order_type = request.form.get("order_type", "Counter")
    meeting_room = request.form.get("meeting_room") or None
    meeting_time = request.form.get("meeting_time") or None

    if not staff_id or not staff_name or not department or not phone_number:
        return redirect(url_for("staff.menu", error="missing_staff_info"))

    db = get_db()
    # orders.staff_id is a foreign key to staff.staff_id, but Cafe Admin no
    # longer pre-registers FAMA staff -- this upsert satisfies that FK
    # transparently from whatever was just keyed in on the Review Order
    # page, so no admin involvement is needed. The order row itself (not
    # this table) is the record of who placed it: staff_name/department/
    # phone_number are stored per-order below since a person's details
    # are captured fresh each time rather than looked up.
    db.execute(
        "INSERT OR IGNORE INTO staff (staff_id, name, department, active) VALUES (?, ?, ?, 1)",
        (staff_id, staff_name, department),
    )

    if order_type == "MeetingRoom":
        package_id = request.form.get("package_id")
        package_qty = int(request.form.get("package_qty") or 0)
        package = None
        if package_id:
            package = db.execute(
                "SELECT * FROM catering_package WHERE package_id = ?", (package_id,)
            ).fetchone()

        if not package or package_qty <= 0:
            db.close()
            return redirect(url_for("staff.menu", error="empty_cart"))

        total = package["price"] * package_qty
        db.execute(
            "INSERT INTO orders (staff_id, staff_name, department, phone_number, order_type, status, "
            "total_amount, order_date, meeting_room, meeting_time, package_name, package_pax, package_qty) "
            "VALUES (?, ?, ?, ?, 'MeetingRoom', 'Pending', ?, ?, ?, ?, ?, ?, ?)",
            (
                staff_id,
                staff_name,
                department,
                phone_number,
                total,
                now_str(),
                meeting_room,
                meeting_time,
                package["name"],
                package["pax"],
                package_qty,
            ),
        )
        order_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.commit()
        db.close()
        return redirect_to_order_status(order_id, staff_id)

    item_ids = request.form.getlist("item_id")
    quantities = request.form.getlist("quantity")

    cart = []
    total = 0.0
    for item_id, qty in zip(item_ids, quantities):
        qty = int(qty)
        if qty <= 0:
            continue
        row = db.execute("SELECT * FROM menu_item WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            continue
        subtotal = row["price"] * qty
        total += subtotal
        cart.append((item_id, qty, subtotal))

    if not cart:
        db.close()
        return redirect(url_for("staff.menu", error="empty_cart"))

    cur = db.execute(
        "INSERT INTO orders (staff_id, staff_name, department, phone_number, order_type, status, "
        "total_amount, order_date, meeting_room, meeting_time) VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?)",
        (staff_id, staff_name, department, phone_number, order_type, total, now_str(), meeting_room, meeting_time),
    )
    order_id = cur.lastrowid
    for item_id, qty, subtotal in cart:
        db.execute(
            "INSERT INTO order_item (order_id, item_id, quantity, subtotal) VALUES (?, ?, ?, ?)",
            (order_id, item_id, qty, subtotal),
        )
    db.commit()
    db.close()
    return redirect_to_order_status(order_id, staff_id)


@staff_bp.route("/order/<int:order_id>/status")
def order_status(order_id):
    """UC5: Receive Order Notification - order tracking page (polls the API below)."""
    staff_id = request.args.get("staff_id", "S001")
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    items = db.execute(
        "SELECT mi.name, oi.quantity, oi.subtotal FROM order_item oi "
        "JOIN menu_item mi ON mi.item_id = oi.item_id WHERE oi.order_id = ?",
        (order_id,),
    ).fetchall()
    db.close()
    if order is None:
        return "Order not found", 404
    return render_template("order_status.html", order=order, items=items, staff_id=staff_id)


@staff_bp.route("/api/order/<int:order_id>")
def api_order_status(order_id):
    """JSON endpoint polled by the browser to simulate a push notification (UC5)."""
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    notif = db.execute(
        "SELECT message FROM notification WHERE order_id = ? ORDER BY notification_id DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    db.close()
    if order is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "order_id": order["order_id"],
            "status": order["status"],
            "total_amount": order["total_amount"],
            "notification": notif["message"] if notif else None,
        }
    )
