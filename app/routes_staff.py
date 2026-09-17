import io
import base64

from flask import Blueprint, render_template, request, redirect, url_for, jsonify

from .db import get_db, now_str, today_str

staff_bp = Blueprint("staff", __name__)


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
    return render_template("landing.html", qr_uri=qr_uri, menu_url=menu_url)


@staff_bp.route("/menu")
def menu():
    """UC2: View Daily Menu."""
    staff_id = request.args.get("staff_id", "S001")
    db = get_db()
    # Not filtered by available_date: an item stays on the menu across days
    # once added, until the admin explicitly hides or deletes it (see
    # admin.menu() below) -- available_date is only a "date added" record,
    # not an expiry, so the menu doesn't silently go empty every midnight.
    items = db.execute(
        "SELECT * FROM menu_item WHERE is_available = 1 ORDER BY category, name",
    ).fetchall()
    packages = db.execute(
        "SELECT * FROM catering_package WHERE is_available = 1 ORDER BY pax"
    ).fetchall()
    my_orders = db.execute(
        "SELECT * FROM orders WHERE staff_id = ? ORDER BY order_id DESC LIMIT 10",
        (staff_id,),
    ).fetchall()
    db.close()
    return render_template(
        "menu.html", items=items, packages=packages, staff_id=staff_id, today=today_str(), my_orders=my_orders
    )


@staff_bp.route("/order", methods=["POST"])
def place_order():
    """UC3: Place Order (counter order) and UC4: Reserve Meeting Room Order (bulk catering package)."""
    staff_id = request.form.get("staff_id", "S001").strip()
    order_type = request.form.get("order_type", "Counter")
    meeting_room = request.form.get("meeting_room") or None
    meeting_time = request.form.get("meeting_time") or None

    db = get_db()

    # orders.staff_id is a foreign key to staff.staff_id: without this
    # check, a blank or made-up Staff ID (the field has no server-side
    # validation) reaches the INSERT below and raises a raw
    # FOREIGN KEY constraint failed IntegrityError -- a 500 instead of a
    # message telling the staff member what actually went wrong.
    staff_row = db.execute(
        "SELECT 1 FROM staff WHERE staff_id = ? AND active = 1", (staff_id,)
    ).fetchone()
    if staff_row is None:
        db.close()
        return redirect(url_for("staff.menu", staff_id=staff_id, error="invalid_staff"))

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
            return redirect(url_for("staff.menu", staff_id=staff_id, error="empty_cart"))

        total = package["price"] * package_qty
        db.execute(
            "INSERT INTO orders (staff_id, order_type, status, total_amount, order_date, "
            "meeting_room, meeting_time, package_name, package_pax, package_qty) "
            "VALUES (?, 'MeetingRoom', 'Pending', ?, ?, ?, ?, ?, ?, ?)",
            (staff_id, total, now_str(), meeting_room, meeting_time, package["name"], package["pax"], package_qty),
        )
        order_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.commit()
        db.close()
        return redirect(url_for("staff.order_status", order_id=order_id, staff_id=staff_id))

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
        return redirect(url_for("staff.menu", staff_id=staff_id, error="empty_cart"))

    cur = db.execute(
        "INSERT INTO orders (staff_id, order_type, status, total_amount, order_date, meeting_room, meeting_time) "
        "VALUES (?, ?, 'Pending', ?, ?, ?, ?)",
        (staff_id, order_type, total, now_str(), meeting_room, meeting_time),
    )
    order_id = cur.lastrowid
    for item_id, qty, subtotal in cart:
        db.execute(
            "INSERT INTO order_item (order_id, item_id, quantity, subtotal) VALUES (?, ?, ?, ?)",
            (order_id, item_id, qty, subtotal),
        )
    db.commit()
    db.close()
    return redirect(url_for("staff.order_status", order_id=order_id, staff_id=staff_id))


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
