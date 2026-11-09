import base64
import csv
import io
import secrets
from functools import wraps

from flask import (
    Blueprint,
    Response,
    render_template,
    request,
    redirect,
    url_for,
    session,
)
from werkzeug.security import generate_password_hash, check_password_hash

from .db import get_db, now_str, today_str, future_str
from .mailer import ready_message, send_order_ready_email, send_password_reset_email
from .survey import QUESTIONS, summary_sentences, tally

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

STATUS_FLOW = ["Pending", "Preparing", "Ready", "Completed"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)

    return wrapped


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """RBAC: authenticates against a per-account password hash rather than
    a single shared passcode. An admin_id only has a usable account once
    it has completed /admin/register (see register() below)."""
    error = None
    if request.method == "POST":
        admin_id = request.form.get("admin_id", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        row = db.execute("SELECT * FROM admin WHERE admin_id = ?", (admin_id,)).fetchone()
        db.close()
        if row is None or not row["active"]:
            error = "No active Cafe Admin account with that ID."
        elif not row["password_hash"]:
            error = "This account has not completed registration yet. Use the registration link below."
        elif not check_password_hash(row["password_hash"], password):
            error = "Incorrect admin ID or password."
        else:
            session["is_admin"] = True
            session["admin_id"] = admin_id
            return redirect(url_for("admin.orders"))
    return render_template("admin_login.html", error=error)


@admin_bp.route("/register", methods=["GET", "POST"])
def register():
    """RBAC gate: registration only succeeds for an admin_id that a Cafe
    Admin has already added via Manage Users (UC10) -- i.e. that row must
    already exist in the `admin` table with no password set yet. A FAMA
    staff member has no such row (they only exist in `staff`), so no ID
    they type here can ever pass this check -- only pre-authorized Cafe
    Admin accounts can be activated."""
    error = None
    success = None
    if request.method == "POST":
        admin_id = request.form.get("admin_id", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        db = get_db()
        row = db.execute("SELECT * FROM admin WHERE admin_id = ?", (admin_id,)).fetchone()

        if row is None or not row["active"]:
            error = "This ID is not authorized as a Cafe Admin. Ask an existing Cafe Admin to add it under Manage Users first."
        elif row["password_hash"]:
            error = "This account has already completed registration. Please log in instead."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            db.execute(
                "UPDATE admin SET password_hash = ? WHERE admin_id = ?",
                (generate_password_hash(password), admin_id),
            )
            db.commit()
            success = "Registration complete. You can now log in."
        db.close()
    return render_template("admin_register.html", error=error, success=success)


@admin_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Self-service password reset. Only ever reaches an inbox the account
    owner already controls, since it requires an email that a Cafe Admin
    (see users()'s set_email action) already put on file for that
    admin_id -- there's no way to attach an arbitrary email to someone
    else's account from here."""
    sent = False
    if request.method == "POST":
        admin_id = request.form.get("admin_id", "").strip()
        db = get_db()
        row = db.execute(
            "SELECT * FROM admin WHERE admin_id = ? AND active = 1", (admin_id,)
        ).fetchone()
        if row and row["email"] and row["password_hash"]:
            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO password_reset (token, admin_id, expires_at, used) VALUES (?, ?, ?, 0)",
                (token, admin_id, future_str(30)),
            )
            db.commit()
            reset_url = url_for("admin.reset_password", token=token, _external=True)
            send_password_reset_email(row["email"], admin_id, reset_url)
        db.close()
        # Always show the same confirmation regardless of whether that
        # admin_id/email actually exists -- otherwise this page could be
        # used to enumerate valid Cafe Admin IDs.
        sent = True
    return render_template("admin_forgot_password.html", sent=sent)


@admin_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db = get_db()
    reset_row = db.execute(
        "SELECT * FROM password_reset WHERE token = ?", (token,)
    ).fetchone()
    valid = (
        reset_row is not None
        and not reset_row["used"]
        and reset_row["expires_at"] > now_str()
    )
    error = None
    success = None
    if not valid:
        error = "This reset link is invalid or has expired. Request a new one below."
    elif request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            db.execute(
                "UPDATE admin SET password_hash = ? WHERE admin_id = ?",
                (generate_password_hash(password), reset_row["admin_id"]),
            )
            db.execute("UPDATE password_reset SET used = 1 WHERE token = ?", (token,))
            db.commit()
            success = "Password updated. You can now log in."
            valid = False
    db.close()
    return render_template(
        "admin_reset_password.html", error=error, success=success, valid=valid
    )


@admin_bp.route("/logout")
def logout():
    session.pop("is_admin", None)
    session.pop("admin_id", None)
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@login_required
def dashboard():
    return redirect(url_for("admin.orders"))


MAX_IMAGE_BYTES = 2 * 1024 * 1024


def _read_food_image(field="image"):
    """Returns (mime, base64_text) for an uploaded food photo, (None, None)
    if no file was chosen, or raises ValueError(error_code). The type is
    decided from the file's magic bytes, not the client-supplied filename or
    Content-Type, so only real JPEG/PNG/WebP data is ever stored."""
    upload = request.files.get(field)
    if upload is None or not upload.filename:
        return None, None
    raw = upload.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image_too_large")
    if raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("bad_image")
    return mime, base64.b64encode(raw).decode("ascii")


def _save_food_image(db, item_id, mime, b64):
    db.execute(
        "INSERT INTO menu_item_image (item_id, mime, data, updated) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(item_id) DO UPDATE SET mime = excluded.mime, "
        "data = excluded.data, updated = excluded.updated",
        (item_id, mime, b64, now_str()),
    )


@admin_bp.route("/menu", methods=["GET", "POST"])
@login_required
def menu():
    """UC7: Update Daily Menu."""
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        image_error = None
        if action == "add":
            try:
                mime, b64 = _read_food_image()
            except ValueError as e:
                mime = b64 = None
                image_error = str(e)
            cur = db.execute(
                "INSERT INTO menu_item (name, price, category, available_date, is_available) "
                "VALUES (?, ?, ?, ?, 1)",
                (
                    request.form["name"],
                    float(request.form["price"]),
                    request.form["category"],
                    today_str(),
                ),
            )
            if mime:
                _save_food_image(db, cur.lastrowid, mime, b64)
            db.commit()
        elif action == "set_image":
            try:
                mime, b64 = _read_food_image()
            except ValueError as e:
                mime = b64 = None
                image_error = str(e)
            else:
                if mime is None:
                    image_error = "bad_image"
            if mime:
                _save_food_image(db, request.form["item_id"], mime, b64)
                db.commit()
        elif action == "remove_image":
            db.execute(
                "DELETE FROM menu_item_image WHERE item_id = ?", (request.form["item_id"],)
            )
            db.commit()
        elif action == "toggle":
            item_id = request.form["item_id"]
            db.execute(
                "UPDATE menu_item SET is_available = 1 - is_available WHERE item_id = ?",
                (item_id,),
            )
            db.commit()
        elif action == "delete":
            item_id = request.form["item_id"]
            # menu_item.item_id is referenced by order_item.item_id (FK,
            # foreign_keys=ON) -- deleting an item that already appears in
            # a past order would violate that constraint and 500. Hiding
            # (the toggle action above) is the correct way to retire an
            # item that has order history; hard delete is only safe for
            # one that was never ordered.
            in_use = db.execute(
                "SELECT 1 FROM order_item WHERE item_id = ?", (item_id,)
            ).fetchone()
            if in_use:
                db.close()
                return redirect(url_for("admin.menu", error="item_in_use"))
            db.execute("DELETE FROM menu_item_image WHERE item_id = ?", (item_id,))
            db.execute("DELETE FROM menu_item WHERE item_id = ?", (item_id,))
            db.commit()
        db.close()
        if image_error:
            return redirect(url_for("admin.menu", error=image_error))
        return redirect(url_for("admin.menu"))

    # Admin manages the whole catalog (shown and hidden alike), not just
    # today's date -- see the matching note in staff.menu(). The image blob
    # itself is never selected here (only whether one exists, plus its
    # timestamp for cache-busting); it's served by staff.menu_image.
    items = db.execute(
        "SELECT m.*, (SELECT updated FROM menu_item_image i WHERE i.item_id = m.item_id) AS image_v "
        "FROM menu_item m ORDER BY m.category, m.name",
    ).fetchall()
    db.close()
    return render_template(
        "admin_menu.html", items=items, today=today_str(), error=request.args.get("error")
    )


@admin_bp.route("/orders", methods=["GET", "POST"])
@login_required
def orders():
    """UC8: View Orders, UC9: Update Order Status, UC6: Pay at Counter (mark Completed)."""
    db = get_db()
    if request.method == "POST":
        order_id = request.form["order_id"]
        if request.form.get("action") == "delete":
            # Only a Completed order (already paid at the counter) may be
            # deleted; the check is repeated here because the button is
            # only hidden, not blocked, in the template for other statuses.
            row = db.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row is not None and row["status"] == "Completed":
                db.execute("DELETE FROM notification WHERE order_id = ?", (order_id,))
                db.execute("DELETE FROM order_item WHERE order_id = ?", (order_id,))
                db.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
                db.commit()
            db.close()
            return redirect(url_for("admin.orders"))
        new_status = request.form["new_status"]
        db.execute("UPDATE orders SET status = ? WHERE order_id = ?", (new_status, order_id))
        ready_order = None
        if new_status == "Ready":
            ready_order = db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if ready_order is not None:
                db.execute(
                    "INSERT INTO notification (order_id, message, sent_time, is_read) VALUES (?, ?, ?, 0)",
                    (order_id, ready_message(ready_order), now_str()),
                )
        db.commit()
        db.close()
        if ready_order is not None:
            # Gmail alert; a failed send is logged, never an error for the admin.
            send_order_ready_email(ready_order)
        return redirect(url_for("admin.orders"))

    type_filter = request.args.get("type", "All")
    status_filter = request.args.get("status", "All")

    # staff_name/department/phone_number live on the order itself, captured
    # at the Review Order step -- no join against a staff registry, since
    # Cafe Admin no longer pre-registers FAMA staff.
    query = "SELECT o.* FROM orders o WHERE 1=1"
    params = []
    if type_filter != "All":
        query += " AND o.order_type = ?"
        params.append(type_filter)
    if status_filter != "All":
        query += " AND o.status = ?"
        params.append(status_filter)
    query += " ORDER BY o.order_id DESC"

    order_rows = db.execute(query, params).fetchall()
    db.close()
    return render_template(
        "admin_orders.html",
        orders=order_rows,
        status_flow=STATUS_FLOW,
        type_filter=type_filter,
        status_filter=status_filter,
    )


@admin_bp.route("/survey")
@login_required
def survey():
    """Questionnaire results, laid out like Table 3.1 of the report."""
    db = get_db()
    rows = db.execute("SELECT * FROM survey_response ORDER BY response_id").fetchall()
    db.close()
    total, questions = tally(rows)
    return render_template(
        "admin_survey.html", total=total, questions=questions, text=summary_sentences(rows),
        cleared=request.args.get("cleared"),
    )


@admin_bp.route("/survey/export.csv")
@login_required
def survey_export():
    db = get_db()
    rows = db.execute("SELECT * FROM survey_response ORDER BY response_id").fetchall()
    db.close()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["response_id", "submitted_at"] + [q["key"] for q in QUESTIONS])
    for r in rows:
        writer.writerow([r["response_id"], r["submitted_at"]] + [r[q["key"]] for q in QUESTIONS])
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=lapar-survey-responses.csv"},
    )


@admin_bp.route("/survey/clear", methods=["POST"])
@login_required
def survey_clear():
    """Wipes every response, e.g. test submissions before real collection."""
    db = get_db()
    db.execute("DELETE FROM survey_response")
    db.commit()
    db.close()
    return redirect(url_for("admin.survey", cleared=1))


@admin_bp.route("/users", methods=["GET", "POST"])
@login_required
def users():
    """Manage Cafe Admins. FAMA staff are not managed here -- they
    identify themselves (Staff ID, Name, Department, Phone Number) per
    order on the Review Order page instead of being pre-registered."""
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            new_id = request.form["user_id"].strip()
            name = request.form["name"].strip()
            role = request.form.get("extra", "").strip()
            email = request.form.get("email", "").strip() or None
            db.execute(
                "INSERT INTO admin (admin_id, name, role, active, email) VALUES (?, ?, ?, 1, ?)",
                (new_id, name, role, email),
            )
            db.commit()
        elif action == "toggle":
            user_id = request.form["user_id"]
            db.execute(
                "UPDATE admin SET active = 1 - active WHERE admin_id = ?",
                (user_id,),
            )
            db.commit()
        elif action == "set_email":
            # Lets a Cafe Admin put an email on file for any admin_id
            # (including one seeded before this column existed), which is
            # what admin.forgot_password() requires before it will ever
            # send a reset link for that account.
            user_id = request.form["user_id"]
            email = request.form.get("email", "").strip() or None
            db.execute("UPDATE admin SET email = ? WHERE admin_id = ?", (email, user_id))
            db.commit()
        db.close()
        return redirect(url_for("admin.users"))

    admin_rows = db.execute("SELECT * FROM admin ORDER BY admin_id").fetchall()
    db.close()
    return render_template(
        "admin_users.html", admin_rows=admin_rows
    )
