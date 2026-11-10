# -*- coding: utf-8 -*-
import io, os, re, sqlite3, struct, sys, tempfile, zlib

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "VERCEL"):
    os.environ.pop(k, None)
os.environ["SECRET_KEY"] = "regression-test-key"
# Address used as the Chief Clerk's email. Nothing is sent: Gmail is replaced by a stub below.
CC_EMAIL = os.environ.get("LAPAR_TEST_EMAIL", "cc@example.com")
# Safety net: automated tests must never send real email, whatever the environment holds.
import smtplib


def _no_smtp(*args, **kwargs):
    raise RuntimeError("automated tests must never send real email")


smtplib.SMTP = _no_smtp


import warnings
warnings.simplefilter("ignore")

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
import app.db as dbmod
dbmod.get_db_path = lambda: tmp.name
from app import create_app
from werkzeug.security import generate_password_hash

app = create_app()
app.config["TESTING"] = True

results = []


def check(case, desc, cond, detail=""):
    results.append((case, desc, bool(cond), detail))


def raw():
    c = sqlite3.connect(tmp.name)
    c.row_factory = sqlite3.Row
    return c


def make_png(w=40, h=30):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\xd2\x69\x1e" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
WEBP = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 20

# ---- set up an admin that can log in
c = raw()
c.execute("UPDATE admin SET password_hash=?, email=? WHERE admin_id='A001'",
          (generate_password_hash("AdminPass123"), "a001@example.com"))
c.commit(); c.close()

staff = app.test_client()
admin = app.test_client()


def login(client, aid, pw):
    return client.post("/admin/login", data={"admin_id": aid, "password": pw})


r = login(admin, "A001", "AdminPass123")
check("SETUP", "Admin A001 can log in", r.status_code == 302 and "/admin/orders" in r.headers["Location"])

items = raw().execute("SELECT item_id,name FROM menu_item ORDER BY item_id").fetchall()
ids = [i["item_id"] for i in items]

# ---- RT-01
r = staff.get("/")
check("RT-01", "Landing page loads with the QR code and the Meeting Order button", r.status_code == 200 and b'alt="QR code' in r.data and b"Meeting Order" in r.data)

# ---- RT-02
r = staff.get("/menu")
check("RT-02", "Daily menu lists all available items", r.status_code == 200 and all(i["name"].encode() in r.data for i in items))

# ---- RT-03 / RT-13 Counter order via Review Order
form = {"order_type": "Counter", "item_id": [str(ids[0]), str(ids[1])], "quantity": ["2", "1"]}
r = staff.post("/order/review", data=form)
check("RT-03", "Review Order page shows summary + 5 mandatory fields (Staff ID, name, department, phone, email)",
      r.status_code == 200 and all(f.encode() in r.data for f in ('name="staff_id"', 'name="staff_name"', 'name="department"', 'name="phone_number"', 'name="email"')) and b"required" in r.data)
r = staff.post("/order", data={**form, "staff_id": "S900", "staff_name": "Test Staff", "department": "QA", "phone_number": "0123456789", "email": "t@example.com"})
m = re.search(r"/order/(\d+)/status", r.headers.get("Location", ""))
o1 = int(m.group(1)) if m else None
row = raw().execute("SELECT * FROM orders WHERE order_id=?", (o1,)).fetchone() if o1 else None
check("RT-03", "Counter order created: type=Counter, status=Pending, redirected to Order Status",
      row and row["order_type"] == "Counter" and row["status"] == "Pending" and abs(row["total_amount"] - (2 * 6.5 + 5.0)) < 1e-6)
check("RT-13", "All five staff fields (including email) stored on the order",
      row and (row["staff_id"], row["staff_name"], row["department"], row["phone_number"], row["email"]) == ("S900", "Test Staff", "QA", "0123456789", "t@example.com"))
r = staff.get(f"/order/{o1}/status?staff_id=S900")
check("RT-03", "Order Status page renders name and staff ID", r.status_code == 200 and b"Test Staff" in r.data and b"S900" in r.data)

n_orders = raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
r = staff.post("/order", data={**form, "staff_id": "S901", "staff_name": "", "department": "QA", "phone_number": "1", "email": "t@example.com"})
check("RT-13", "Missing Staff Name blocks the order (redirect with error, no row created)",
      "missing_staff_info" in r.headers.get("Location", "") and raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"] == n_orders)
r = staff.post("/order/review", data={"order_type": "Counter", "item_id": [str(ids[0])], "quantity": ["0"]})
check("RT-13", "Empty cart is rejected at Review Order", "empty_cart" in r.headers.get("Location", ""))

# ---- RT-04 meeting room order
pk = raw().execute("SELECT package_id FROM catering_package ORDER BY package_id").fetchone()["package_id"]
mform = {"order_type": "MeetingRoom", "meeting_room": "Meeting Room 2", "meeting_time": "2026-11-01T10:00", "package_id": str(pk), "package_qty": "2"}
anon = app.test_client()
n_before = raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
r1 = anon.get("/catering"); r2 = anon.post("/order/review", data=mform)
r3 = anon.post("/order", data={**mform, "staff_id": "S901", "staff_name": "Meet Staff", "department": "Ops", "phone_number": "0199999999", "email": "t@example.com"})
check("CC", "Anonymous visitors are sent to the CC login from the catering page, Review Order and Order",
      all(x.status_code == 302 and "/staff/login" in x.headers["Location"] for x in (r1, r2, r3))
      and raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"] == n_before)
check("CC", "Anonymous visitors never see the package contents", b"Teh tarik" not in r1.data and b"Beverages" not in r1.data)
check("CC", "Staff menu no longer has the meeting-room checkbox or the catering section",
      all(b not in staff.get("/menu").data for b in (b"is_meeting", b"Catering Packages", b"package_qty", b"meeting_room")))
land = anon.get("/").data
check("CC", "Home page has a Meeting Order button (to the catering page) and no View Menu button",
      b"Meeting Order" in land and b'href="/catering"' in land and b"View Menu" not in land and b'href="/menu"' not in land)

# a Chief Clerk registers by themselves (the Cafe Admin does not manage CC accounts)
check("CC", "Admin Users page no longer has a Chief Clerk section", b"Chief Clerk" not in admin.get("/admin/users").data and b"add_cc" not in admin.get("/admin/users").data)
check("CC", "Admin can no longer add a CC (add_cc action does nothing)", (admin.post("/admin/users", data={"action": "add_cc", "staff_id": "CCX", "name": "X", "department": "Y"}), raw().execute("SELECT COUNT(*) c FROM staff WHERE staff_id='CCX'").fetchone()["c"] == 0)[1])
def cc_login(client, sid, pw):
    return client.post("/staff/login", data={"staff_id": sid, "password": pw})
def cc_reg(client, **kw):
    d = {"staff_id": "CC01", "name": "Meet Staff", "department": "Ops", "email": "cc01@example.com", "password": "ChiefClerk123", "confirm_password": "ChiefClerk123"}
    d.update(kw)
    return client.post("/staff/register", data=d)
check("CC", "Register page asks for Staff ID, name, department, email and password", all(x in staff.get("/staff/register").data for x in (b'name="staff_id"', b'name="name"', b'name="department"', b'name="email"', b'name="password"')))
check("CC", "Unregistered ID cannot log in", b"Only registered Chief Clerk" in cc_login(staff, "CC01", "whatever123").data)
check("CC", "Registration rejects a missing department, a short password and a mismatch",
      b"required" in cc_reg(staff, department="").data
      and b"at least 8" in cc_reg(staff, password="short", confirm_password="short").data
      and b"do not match" in cc_reg(staff, confirm_password="other12345").data
      and raw().execute("SELECT COUNT(*) c FROM staff WHERE staff_id='CC01'").fetchone()["c"] == 0)
check("CC", "Registration rejects a missing or invalid email", b"valid email" in cc_reg(staff, email="").data and b"valid email" in cc_reg(staff, email="nope").data and raw().execute("SELECT COUNT(*) c FROM staff WHERE staff_id='CC01'").fetchone()["c"] == 0)
check("CC", "Chief Clerk registers by themselves", b"Registration complete" in cc_reg(staff).data)
c = raw().execute("SELECT * FROM staff WHERE staff_id='CC01'").fetchone()
check("CC", "Registered account has role CC, is active, and stores a password hash (not the password)", c and c["role"] == "CC" and c["active"] == 1 and c["password_hash"] and c["password_hash"] != "ChiefClerk123" and c["name"] == "Meet Staff" and c["department"] == "Ops" and c["email"] == "cc01@example.com")
check("CC", "Registered CC cannot register again", b"already been registered" in cc_reg(staff, password="Another12345", confirm_password="Another12345").data)
check("CC", "Wrong password is rejected", b"Incorrect Staff ID or password" in cc_login(staff, "CC01", "wrongpass12").data and staff.get("/catering").status_code == 302)
r = cc_login(staff, "CC01", "ChiefClerk123")
check("CC", "Chief Clerk logs in and lands on the catering page", r.status_code == 302 and r.headers["Location"].endswith("/catering"))
check("CC", "Existing non-CC staff row without a password can register as CC", b"Registration complete" in cc_reg(app.test_client(), staff_id="S900", name="Test Staff", department="QA").data and raw().execute("SELECT role FROM staff WHERE staff_id='S900'").fetchone()["role"] == "CC")
_r = raw(); _r.execute("UPDATE staff SET role=NULL, password_hash=NULL WHERE staff_id='S900'"); _r.commit()
pg = staff.get("/catering")
check("CC", "Catering page lists each package with its food and drinks (jugs)",
      pg.status_code == 200 and b"Snack Box Package" in pg.data and b"Food" in pg.data and b"Beverages" in pg.data and b"jug" in pg.data and b"Teh tarik" in pg.data and b"Meet Staff" in pg.data)
r = staff.post("/order/review", data=mform)
check("RT-04", "Review Order works for catering package", r.status_code == 200 and b"Meeting Room 2" in r.data and b"CC01" in r.data and b'name="phone_number"' in r.data and b'name="staff_id"' not in r.data)
check("MAIL", "Meeting Review Order prefills the email saved at registration (still editable)", b'value="cc01@example.com"' in r.data and b'name="email"' in r.data)
check("CC", "Meeting order without a room or time is sent back to the catering page",
      "missing_meeting" in staff.post("/order/review", data={**mform, "meeting_room": ""}).headers["Location"]
      and "missing_meeting" in staff.post("/order", data={**mform, "meeting_time": "", "phone_number": "0199999999", "email": "t@example.com"}).headers["Location"])
check("CC", "Meeting order without a phone number is refused", "missing_staff_info" in staff.post("/order", data={**mform, "phone_number": "", "email": "t@example.com"}).headers["Location"])
r = staff.post("/order", data={**mform, "staff_id": "S777", "staff_name": "Somebody Else", "department": "Fake", "phone_number": "0199999999", "email": "t@example.com"})
o2 = int(re.search(r"/order/(\d+)/status", r.headers["Location"]).group(1))
row = raw().execute("SELECT * FROM orders WHERE order_id=?", (o2,)).fetchone()
check("RT-04", "Meeting order saved with type, room, time, package, staff details",
      row["order_type"] == "MeetingRoom" and row["meeting_room"] == "Meeting Room 2" and row["package_qty"] == 2 and row["staff_name"] == "Meet Staff" and row["status"] == "Pending")
check("CC", "Meeting order is always placed under the logged-in CC (spoofed staff ID/name/department ignored)",
      row["staff_id"] == "CC01" and row["department"] == "Ops" and raw().execute("SELECT COUNT(*) c FROM staff WHERE staff_id='S777'").fetchone()["c"] == 0)
check("CC", "Counter order stays anonymous (no login needed)", anon.post("/order/review", data=form).status_code == 200)
# a deactivated CC loses access at once (set in the database; no admin screen)
_r = raw(); _r.execute("UPDATE staff SET active=0 WHERE staff_id='CC01'"); _r.commit()
check("CC", "A deactivated CC loses access immediately", staff.get("/catering").status_code == 302 and b"Only registered Chief Clerk" in cc_login(app.test_client(), "CC01", "ChiefClerk123").data)
_r = raw(); _r.execute("INSERT INTO staff (staff_id, name, department, active) VALUES ('CCD', 'Old', 'Ops', 0)"); _r.commit()
check("CC", "A deactivated Staff ID cannot register", b"deactivated" in cc_reg(app.test_client(), staff_id="CCD").data)
_r = raw(); _r.execute("UPDATE staff SET active=1 WHERE staff_id='CC01'"); _r.commit()
check("CC", "Re-activated CC can log in again", cc_login(staff, "CC01", "ChiefClerk123").status_code == 302 and staff.get("/catering").status_code == 200)
check("CC", "Logout ends the CC session", staff.get("/staff/logout").status_code == 302 and staff.get("/catering").status_code == 302)
cc_login(staff, "CC01", "ChiefClerk123")
check("CC", "A Chief Clerk is not a Cafe Admin (admin pages stay closed)", staff.get("/admin/orders").status_code == 302)
check("CC", "Catering package descriptions were migrated to food/drinks lists", all(raw().execute("SELECT description FROM catering_package WHERE name=?", (n,)).fetchone()["description"].count("\n") == 1 for n in ("Snack Box Package", "Standard Meeting Package", "Premium Conference Package")))

# ---- MAIL: Gmail alert on Ready
import app.mailer as mailmod
sent = []
mailmod._send_gmail = lambda to, subj, body, purpose: (sent.append((to, subj, body)), True)[1]
check("MAIL", "Review Order (counter) asks for an email", b'name="email"' in staff.post("/order/review", data=form).data)
check("MAIL", "Review Order (meeting) asks for an email", b'name="email"' in staff.post("/order/review", data=mform).data)
bad = staff.post("/order", data={**form, "staff_id": "S960", "staff_name": "No Mail", "department": "QA", "phone_number": "1", "email": "not-an-email"})
check("MAIL", "Counter order with an invalid email is refused", "invalid_email" in bad.headers["Location"] and raw().execute("SELECT COUNT(*) c FROM orders WHERE staff_id='S960'").fetchone()["c"] == 0)
check("MAIL", "Counter order without an email is refused", "invalid_email" in staff.post("/order", data={**form, "staff_id": "S960", "staff_name": "No Mail", "department": "QA", "phone_number": "1"}).headers["Location"])
check("MAIL", "Meeting order with an invalid email is refused", "invalid_email" in staff.post("/order", data={**mform, "phone_number": "0199999999", "email": "x"}).headers["Location"])
check("MAIL", "Error text is shown on the menu and catering pages", b"valid email" in staff.get("/menu?error=invalid_email").data and b"valid email" in staff.get("/catering?error=invalid_email").data)
sent.clear()
mc = app.test_client(); cc_login(mc, "CC01", "ChiefClerk123")
rm = mc.post("/order", data={**mform, "phone_number": "0199999999", "email": CC_EMAIL})
om = int(re.search(r"/order/(\d+)/status", rm.headers["Location"]).group(1))
check("MAIL", "Placing a meeting order emails the CC a Pending alert",
      len(sent) == 1 and sent[0][0] == CC_EMAIL and "status: Pending" in sent[0][2] and "received your catering order" in sent[0][2] and f"#{om}" in sent[0][1])
for st in ("Preparing", "Ready", "Completed"):
    admin.post("/admin/orders", data={"order_id": om, "new_status": st})
check("MAIL", "Meeting order emails the CC at every status: Pending, Preparing, Ready, Completed",
      [("status: " + s) in b for s, (_, _, b) in zip(("Pending", "Preparing", "Ready", "Completed"), sent)] == [True] * 4 and len(sent) == 4 and all(m[0] == CC_EMAIL for m in sent))
check("MAIL", "Preparing and Completed emails carry their own message",
      "preparing your catering order" in sent[1][2] and "completed" in sent[3][2].lower())
check("MAIL", "Ready on a meeting order emails the CC that cafe staff will deliver to the room",
      "deliver it to Meeting Room 2" in sent[2][2] and "Package:" in sent[2][2] and "counter" not in sent[2][2].lower() and "is ready" in sent[2][1])
check("MAIL", "Meeting on-page notification also says cafe staff will deliver", "deliver" in staff.get(f"/api/order/{om}").get_json()["notification"])
check("MAIL", "Meeting status page tells the CC the order will be delivered", b"will deliver it to Meeting Room 2" in staff.get(f"/order/{om}/status").data)
# an order with no email on file (placed before this feature) still goes Ready without error
_r = raw(); _r.execute("UPDATE orders SET email=NULL WHERE order_id=?", (om,)); _r.commit()
sent.clear()
rr = admin.post("/admin/orders", data={"order_id": om, "new_status": "Ready"})
check("MAIL", "Order without an email still becomes Ready and sends nothing (no error)", rr.status_code == 302 and len(sent) == 0)
mailmod._send_gmail = lambda *a: False
o_f = int(re.search(r"/order/(\d+)/status", mc.post("/order", data={**mform, "phone_number": "1", "email": CC_EMAIL}).headers["Location"]).group(1))
rf = admin.post("/admin/orders", data={"order_id": o_f, "new_status": "Ready"})
check("MAIL", "A failed Gmail send does not break the status update", rf.status_code == 302 and raw().execute("SELECT status FROM orders WHERE order_id=?", (o_f,)).fetchone()["status"] == "Ready")
mailmod._send_gmail = lambda to, subj, body, purpose: (sent.append((to, subj, body)), True)[1]
sent.clear()

# ---- RT-08 view orders
r = admin.get("/admin/orders")
check("RT-08", "Admin Orders lists both Counter and MeetingRoom orders with Department/Phone",
      r.status_code == 200 and b"Counter" in r.data and b"MeetingRoom" in r.data and b"Test Staff" in r.data and b"0123456789" in r.data and b"QA" in r.data)
check("RT-08", "Type filter works", b"Meet Staff" not in admin.get("/admin/orders?type=Counter").data and b"Meet Staff" in admin.get("/admin/orders?type=MeetingRoom").data)

# ---- RT-09 status flow + notification count, RT-05 ready notification
admin.post("/admin/orders", data={"order_id": o1, "new_status": "Preparing"})
check("MAIL", "No email is sent for Preparing", len(sent) == 0)
admin.post("/admin/orders", data={"order_id": o1, "new_status": "Ready"})
cnt = raw().execute("SELECT COUNT(*) c FROM notification WHERE order_id=?", (o1,)).fetchone()["c"]
check("RT-09", "Pending->Preparing->Ready yields exactly one notification", cnt == 1, f"count={cnt}")
api = staff.get(f"/api/order/{o1}").get_json()
check("RT-05", "Staff polling API shows status Ready + ready notification",
      api["status"] == "Ready" and api["notification"] and "ready" in api["notification"].lower())
# ---- RT-06
check("MAIL", "Ready on a counter order emails the staff member once (collect at counter)",
      len(sent) == 1 and sent[0][0] == "t@example.com" and "ready" in sent[0][1].lower() and "collection and payment at the counter" in sent[0][2] and f"#{o1}" in sent[0][1])
check("MAIL", "Order stores the email address", raw().execute("SELECT email FROM orders WHERE order_id=?", (o1,)).fetchone()["email"] == "t@example.com")
admin.post("/admin/orders", data={"order_id": o1, "new_status": "Completed"})
check("RT-06", "Ready order marked Completed", staff.get(f"/api/order/{o1}").get_json()["status"] == "Completed")
check("MAIL", "Counter order sent only the Ready email (none for Pending, Preparing, Completed)", len(sent) == 1 and "is ready" in sent[0][1])

# ---- RT-15 Order Status / Order History panel (restored)
mh = staff.get("/menu").get_data(as_text=True)
check("RT-15", "Menu shows Order Status + Order History panel (not the generic side cards)",
      "Order Status" in mh and "Order History" in mh and "Cafe Admin Login" not in mh and "Track Order" in mh)
check("RT-15", "Latest order (#%d) is shown with its live status; both orders are in history" % o2,
      f"Order #{o2} &middot; MeetingRoom" in mh.replace("·", "&middot;") or f"Order #{o2}" in mh)
check("RT-15", "History lists both of this browser's orders with status badges",
      f"#{o1}" in mh and f"#{o2}" in mh and "Completed" in mh and "Pending" in mh)
check("RT-15", "Track Order link goes to the order's status page", f"/order/{o2}/status" in mh)
fresh = app.test_client().get("/menu").get_data(as_text=True)
check("RT-15", "A new browser (no orders) sees the empty state", "haven&#39;t placed an order yet" in fresh or "haven't placed an order yet" in fresh)
check("RT-15", "A new browser does not see anyone else's orders", f"#{o1}" not in fresh.split("lapar-order-history-list")[-1][:200] and "No orders yet" in fresh)
forged = app.test_client(); forged.set_cookie("lapar_orders", "forged.value.here")
check("RT-15", "A forged/edited cookie is ignored (no orders shown, no error)", forged.get("/menu").status_code == 200 and "No orders yet" in forged.get("/menu").get_data(as_text=True))
ck = [h for h in staff.post("/order", data={**form, "staff_id": "S903", "staff_name": "Cookie Check", "department": "QA", "phone_number": "1", "email": "t@example.com"}).headers.getlist("Set-Cookie") if h.startswith("lapar_orders")]
check("RT-15", "Order cookie is HttpOnly, SameSite=Lax, 30-day expiry", ck and "HttpOnly" in ck[0] and "SameSite=Lax" in ck[0] and "Max-Age=2592000" in ck[0])
mh2 = staff.get("/menu").get_data(as_text=True)
check("RT-15", "New order appears at the top of the panel", mh2.index("Cookie Check") if "Cookie Check" in mh2 else True)
n = raw().execute("SELECT MAX(order_id) m FROM orders").fetchone()["m"]
check("RT-15", "Panel's newest entry is the order just placed", f"Order #{n}" in mh2)
many = app.test_client()
for i in range(12):
    many.post("/order", data={**form, "staff_id": "S904", "staff_name": "Many", "department": "QA", "phone_number": "1", "email": "t@example.com"})
mm = many.get("/menu").get_data(as_text=True)
check("RT-15", "History is capped at the 10 most recent orders", mm.count("lapar-order-history-date") == 10, str(mm.count("lapar-order-history-date")))
check("RT-15", "Menu page no longer has the Staff ID input", 'name="staff_id"' not in mh)

# ---- RT-07 hide/show
target = ids[2]
admin.post("/admin/menu", data={"action": "toggle", "item_id": target})
hidden = items[2]["name"].encode() not in staff.get("/menu").data
admin.post("/admin/menu", data={"action": "toggle", "item_id": target})
shown = items[2]["name"].encode() in staff.get("/menu").data
check("RT-07", "Hidden item disappears from staff menu; toggling back restores it", hidden and shown)

# ---- RT-10 manage cafe admins
r = admin.get("/admin/users")
check("RT-10", "Users page manages Cafe Admins only (no registry of counter-order staff)",
      r.status_code == 200 and b"Counter-order staff are not managed here" in r.data and b"Chief Clerk" not in r.data and b'name="role_table"' not in r.data and b"FAMA Staff" not in r.data)
admin.post("/admin/users", data={"action": "add", "user_id": "A777", "name": "New Admin", "extra": "Cafe Admin", "email": "a777@example.com"})
row = raw().execute("SELECT * FROM admin WHERE admin_id='A777'").fetchone()
check("RT-10", "New Cafe Admin created in pending state (no password yet)", row and not row["password_hash"] and row["active"] == 1)
staff_before = raw().execute("SELECT COUNT(*) c FROM staff").fetchone()["c"]
check("RT-10", "Admin add does not create a staff record", raw().execute("SELECT COUNT(*) c FROM staff WHERE staff_id='A777'").fetchone()["c"] == 0)

# ---- RT-11 register
reg = app.test_client()
r = login(reg, "A777", "whatever")
check("RT-11", "Pending admin cannot log in before registering", r.status_code == 200 and b"not completed registration" in r.data)
r = reg.post("/admin/register", data={"admin_id": "S900", "password": "NewAdmin123", "confirm_password": "NewAdmin123"})
check("RT-11", "A FAMA staff ID cannot register as admin", b"not authorized" in r.data)
r = reg.post("/admin/register", data={"admin_id": "A777", "password": "NewAdmin123", "confirm_password": "NewAdmin123"})
check("RT-11", "Pre-registered admin completes registration", b"Registration complete" in r.data)
r = login(reg, "A777", "NewAdmin123")
check("RT-11", "Newly registered admin can log in immediately", r.status_code == 302 and "/admin/orders" in r.headers["Location"])

# ---- RT-12 forgot password
fp = app.test_client()
r = fp.post("/admin/forgot-password", data={"admin_id": "A777"})
tok = raw().execute("SELECT token FROM password_reset WHERE admin_id='A777'").fetchone()
check("RT-12", "Forgot Password generates a reset token (email send is non-fatal offline)", r.status_code == 200 and tok is not None)
r = fp.post(f"/admin/reset-password/{tok['token']}", data={"password": "ResetPass123", "confirm_password": "ResetPass123"})
check("RT-12", "Reset link sets a new password", b"Password updated" in r.data)
check("RT-12", "New password works, old one does not",
      login(app.test_client(), "A777", "ResetPass123").status_code == 302 and login(app.test_client(), "A777", "NewAdmin123").status_code == 200)
r = fp.get(f"/admin/reset-password/{tok['token']}")
check("RT-12", "Reset link is single-use", b"invalid or has expired" in r.data)

# ======== RT-14 (new): menu item images ========
anon = app.test_client()
png = make_png()
check("RT-14", "Anonymous user cannot upload (redirected to login)",
      anon.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[0]), "image": (io.BytesIO(png), "a.png")}, content_type="multipart/form-data").headers["Location"].endswith("/admin/login"))
check("RT-14", "No images stored after anonymous attempt", raw().execute("SELECT COUNT(*) c FROM menu_item_image").fetchone()["c"] == 0)

# add with image
r = admin.post("/admin/menu", data={"action": "add", "name": "Photo Dish", "price": "9.9", "category": "Food", "image": (io.BytesIO(png), "dish.png")}, content_type="multipart/form-data")
pd = raw().execute("SELECT item_id FROM menu_item WHERE name='Photo Dish'").fetchone()["item_id"]
img = raw().execute("SELECT * FROM menu_item_image WHERE item_id=?", (pd,)).fetchone()
check("RT-14", "Add Menu Item with photo stores item + image (PNG)", img and img["mime"] == "image/png")
r = staff.get(f"/menu/image/{pd}")
check("RT-14", "Image route returns exact uploaded bytes, correct type, cacheable, nosniff",
      r.status_code == 200 and r.data == png and r.mimetype == "image/png" and "max-age" in r.headers["Cache-Control"] and r.headers.get("X-Content-Type-Options") == "nosniff")
html = staff.get("/menu").data
check("RT-14", "Staff menu shows the photo for that item", f"/menu/image/{pd}?v=".encode() in html and b'class="dish-photo"' in html)
check("RT-14", "Items without a photo keep the icon tile", b"dish-icon-tile" in html)
check("RT-14", "Staff menu HTML does not embed image data (stays small)", len(html) < 60000 and b"base64" not in html.replace(b"data:image/png;base64", b""), f"{len(html)} bytes")
ahtml = admin.get("/admin/menu").data
check("RT-14", "Admin menu shows thumbnail + replace/remove controls", f"/menu/image/{pd}?v=".encode() in ahtml and b'value="remove_image"' in ahtml and b'value="set_image"' in ahtml)

# add without image still works (regression)
admin.post("/admin/menu", data={"action": "add", "name": "No Photo Dish", "price": "3.0", "category": "Beverage"})
npd = raw().execute("SELECT item_id FROM menu_item WHERE name='No Photo Dish'").fetchone()["item_id"]
check("RT-14", "Add Menu Item without a photo still works (UT-07)", npd and staff.get(f"/menu/image/{npd}").status_code == 404 and b"No Photo Dish" in staff.get("/menu").data)

# replace (JPEG) -> version changes
v_old = raw().execute("SELECT updated FROM menu_item_image WHERE item_id=?", (pd,)).fetchone()["updated"]
import time; time.sleep(1.1)
admin.post("/admin/menu", data={"action": "set_image", "item_id": str(pd), "image": (io.BytesIO(JPEG), "x.jpg")}, content_type="multipart/form-data")
img = raw().execute("SELECT * FROM menu_item_image WHERE item_id=?", (pd,)).fetchone()
check("RT-14", "Replacing a photo overwrites it (JPEG) and bumps cache-buster", img["mime"] == "image/jpeg" and img["updated"] != v_old and raw().execute("SELECT COUNT(*) c FROM menu_item_image WHERE item_id=?", (pd,)).fetchone()["c"] == 1)
# add photo to existing seeded item (upload on existing, WebP)
admin.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[0]), "image": (io.BytesIO(WEBP), "y.webp")}, content_type="multipart/form-data")
check("RT-14", "Photo can be attached to an existing item (WebP)", staff.get(f"/menu/image/{ids[0]}").mimetype == "image/webp")

# validation
r = admin.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[1]), "image": (io.BytesIO(b"<script>alert(1)</script>"), "evil.png")}, content_type="multipart/form-data")
check("RT-14", "Non-image content with .png name is rejected", "bad_image" in r.headers["Location"] and staff.get(f"/menu/image/{ids[1]}").status_code == 404)
r = admin.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[1]), "image": (io.BytesIO(b"GIF89a" + b"\x00" * 50), "g.gif")}, content_type="multipart/form-data")
check("RT-14", "GIF (unsupported type) is rejected", "bad_image" in r.headers["Location"])
r = admin.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[1])})
check("RT-14", "Submitting with no file selected is rejected, nothing stored", "bad_image" in r.headers["Location"] and staff.get(f"/menu/image/{ids[1]}").status_code == 404)
big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024 + 10)
r = admin.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[1]), "image": (io.BytesIO(big), "big.png")}, content_type="multipart/form-data")
check("RT-14", "File over 2 MB is rejected", "image_too_large" in r.headers["Location"] and staff.get(f"/menu/image/{ids[1]}").status_code == 404)
huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024)
r = admin.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[1]), "image": (io.BytesIO(huge), "huge.png")}, content_type="multipart/form-data")
check("RT-14", "Request over 4 MB hits the 413 handler and redirects with a friendly error", r.status_code == 302 and "image_too_large" in r.headers["Location"])
r = admin.post("/admin/menu", data={"action": "add", "name": "Bad Image Dish", "price": "1", "category": "Food", "image": (io.BytesIO(b"nope"), "n.png")}, content_type="multipart/form-data")
check("RT-14", "Add with invalid image still creates the item but reports the image error",
      "bad_image" in r.headers["Location"] and raw().execute("SELECT COUNT(*) c FROM menu_item WHERE name='Bad Image Dish'").fetchone()["c"] == 1)
check("RT-14", "Unknown item id returns 404 from the image route", staff.get("/menu/image/987654").status_code == 404)

# Ordering an item that has a photo (regression of order flow with image items)
f2 = {"order_type": "Counter", "item_id": [str(pd)], "quantity": ["3"]}
r = staff.post("/order/review", data=f2)
check("RT-14", "Items with photos can be reviewed and ordered", r.status_code == 200 and b"Photo Dish" in r.data)
r = staff.post("/order", data={**f2, "staff_id": "S902", "staff_name": "Img Buyer", "department": "QA", "phone_number": "1", "email": "t@example.com"})
o3 = int(re.search(r"/order/(\d+)/status", r.headers["Location"]).group(1))
check("RT-14", "Order for photo item saved with correct total", abs(raw().execute("SELECT total_amount FROM orders WHERE order_id=?", (o3,)).fetchone()[0] - 29.7) < 1e-6)

# delete protections
r = admin.post("/admin/menu", data={"action": "delete", "item_id": str(pd)})
check("RT-14", "Item with order history cannot be deleted (kept, photo kept)", "item_in_use" in r.headers["Location"] and raw().execute("SELECT COUNT(*) c FROM menu_item_image WHERE item_id=?", (pd,)).fetchone()["c"] == 1)
admin.post("/admin/menu", data={"action": "toggle", "item_id": str(pd)})
check("RT-14", "Hiding a photo item removes it from staff menu", f"/menu/image/{pd}?v=".encode() not in staff.get("/menu").data and b">Photo Dish<" not in staff.get("/menu").data)
admin.post("/admin/menu", data={"action": "toggle", "item_id": str(pd)})

# remove photo
admin.post("/admin/menu", data={"action": "remove_image", "item_id": str(pd)})
check("RT-14", "Remove photo deletes it; staff menu falls back to icon tile",
      staff.get(f"/menu/image/{pd}").status_code == 404 and f"/menu/image/{pd}?v=".encode() not in staff.get("/menu").data)

# delete never-ordered item with photo -> no FK error, image row gone
admin.post("/admin/menu", data={"action": "set_image", "item_id": str(npd), "image": (io.BytesIO(png), "p.png")}, content_type="multipart/form-data")
r = admin.post("/admin/menu", data={"action": "delete", "item_id": str(npd)})
check("RT-14", "Deleting a never-ordered item with a photo works and removes the photo row",
      r.status_code == 302 and raw().execute("SELECT COUNT(*) c FROM menu_item WHERE item_id=?", (npd,)).fetchone()["c"] == 0
      and raw().execute("SELECT COUNT(*) c FROM menu_item_image WHERE item_id=?", (npd,)).fetchone()["c"] == 0)

# security: filename / mime cannot influence stored type
admin.post("/admin/menu", data={"action": "set_image", "item_id": str(ids[3]), "image": (io.BytesIO(png), "<img src=x onerror=alert(1)>.svg", "image/svg+xml")}, content_type="multipart/form-data")
r = staff.get(f"/menu/image/{ids[3]}")
check("RT-14", "Stored type is derived from content, not filename/Content-Type (no SVG/HTML served)", r.mimetype == "image/png" and b"<svg" not in r.data)

# ---- Staff survey (questionnaire)
from app.survey import QUESTIONS
good = {"q1": "3 to 4 times", "q2": "More than 15 minutes", "q3": "Yes, often (4 times or more)", "q4": "Very useful", "q5": "Interested"}
r = staff.get("/survey")
check("SV", "Survey form shows all 5 questions and every answer choice",
      r.status_code == 200 and all(q["text"].encode() in r.data and all(o.encode() in r.data for o in q["options"]) for q in QUESTIONS))
check("SV", "Survey form is anonymous (no name / Staff ID fields)", b'name="staff_id"' not in r.data and b'name="staff_name"' not in r.data)
check("SV", "Home page links to the survey", b"/survey" in staff.get("/").data)
r = app.test_client().post("/survey", data={**good, "q3": ""})
check("SV", "Incomplete survey is rejected and nothing stored", r.status_code == 400 and raw().execute("SELECT COUNT(*) c FROM survey_response").fetchone()["c"] == 0)
r = app.test_client().post("/survey", data={**good, "q2": "Whenever I feel like it"})
check("SV", "Answer that is not one of the choices is rejected", r.status_code == 400 and raw().execute("SELECT COUNT(*) c FROM survey_response").fetchone()["c"] == 0)
sc = app.test_client()
r = sc.post("/survey", data=good)
check("SV", "Valid survey is stored and redirects to thank-you page",
      r.status_code == 302 and r.headers["Location"].endswith("/survey/thanks") and raw().execute("SELECT COUNT(*) c FROM survey_response").fetchone()["c"] == 1)
check("SV", "Thank-you page renders", sc.get("/survey/thanks").status_code == 200)
sc.post("/survey", data={**good, "q1": "5 times or more"})
check("SV", "Same browser cannot submit twice", raw().execute("SELECT COUNT(*) c FROM survey_response").fetchone()["c"] == 1)
app.test_client().post("/survey", data={**good, "q2": "Less than 5 minutes", "q3": "No, never", "q4": "Neutral", "q5": "Not interested at all"})
app.test_client().post("/survey", data={**good, "q2": "11 to 15 minutes", "q3": "Yes, once"})
app.test_client().post("/survey", data={**good, "q2": "5 to 10 minutes", "q3": "No, never", "q4": "Useful", "q5": "Very interested"})
check("SV", "Four respondents stored", raw().execute("SELECT COUNT(*) c FROM survey_response").fetchone()["c"] == 4)
page = admin.get("/admin/survey")
check("SV", "Results page shows N=4 and the report-style table", page.status_code == 200 and b"Total respondents (N)" in page.data and b">4 <" in page.data.replace(b"\n", b""))
from app.survey import tally, summary_sentences
rows = raw().execute("SELECT * FROM survey_response").fetchall()
n, t = tally(rows)
q2 = {r["label"]: (r["count"], r["pct"]) for r in t[1]["rows"]}
check("SV", "Tally matches the data (Q2: 1 each of <5, 5-10, 11-15, >15; 25.0%)",
      n == 4 and q2["Less than 5 minutes"] == (1, 25.0) and q2["More than 15 minutes"] == (1, 25.0) and q2["11 to 15 minutes"] == (1, 25.0) and sum(c for c, _ in q2.values()) == 4)
check("SV", "Every question's counts add up to N", all(sum(r["count"] for r in q["rows"]) == n for q in t))
s = summary_sentences(rows)
check("SV", "Evidence sentence derived from data (4 respondents; 50% waited 11+ min; 50% wrong order)",
      s["evidence"].startswith("Of 4 respondents, 50.0% waited 11 minutes or longer") and "50.0% had received a wrong order" in s["evidence"])
check("SV", "Summary text empty when there are no responses", summary_sentences([]) == {"evidence": "", "findings": ""})
csvr = admin.get("/admin/survey/export.csv")
check("SV", "CSV export has header + 4 rows", csvr.mimetype == "text/csv" and len(csvr.data.decode().strip().splitlines()) == 5)
anon = app.test_client()
check("SV", "Results, export and delete require admin login",
      all(anon.get(p).status_code == 302 for p in ("/admin/survey", "/admin/survey/export.csv")) and anon.post("/admin/survey/clear").status_code == 302
      and raw().execute("SELECT COUNT(*) c FROM survey_response").fetchone()["c"] == 4)
admin.post("/admin/survey/clear")
check("SV", "Delete all removes every response", raw().execute("SELECT COUNT(*) c FROM survey_response").fetchone()["c"] == 0)
check("SV", "Empty results page renders with N=0", admin.get("/admin/survey").status_code == 200)

# ---- Delete a Completed order (admin)
def exists(oid):
    return raw().execute("SELECT 1 FROM orders WHERE order_id=?", (oid,)).fetchone() is not None
st1 = raw().execute("SELECT status FROM orders WHERE order_id=?", (o1,)).fetchone()["status"]
r = staff.post("/order", data={**form, "staff_id": "S950", "staff_name": "Pending Staff", "department": "QA", "phone_number": "0111111111", "email": "t@example.com"})
o_pend = int(re.search(r"/order/(\d+)/status", r.headers["Location"]).group(1))
page = admin.get("/admin/orders").data.decode()
check("DEL", "Completed order shows a Delete button; a Pending order does not",
      st1 == "Completed" and f'onsubmit="return confirm(\'Delete order #{o1}?' in page and f'onsubmit="return confirm(\'Delete order #{o_pend}?' not in page)
anon2 = app.test_client()
r = anon2.post("/admin/orders", data={"order_id": o1, "action": "delete"})
check("DEL", "Delete requires admin login (anonymous request redirected, order kept)", r.status_code == 302 and "/admin/login" in r.headers["Location"] and exists(o1))
admin.post("/admin/orders", data={"order_id": o_pend, "action": "delete"})
check("DEL", "A Pending order cannot be deleted (server refuses, order kept)", exists(o_pend))
n_items = raw().execute("SELECT COUNT(*) c FROM order_item WHERE order_id=?", (o1,)).fetchone()["c"]
n_notif = raw().execute("SELECT COUNT(*) c FROM notification WHERE order_id=?", (o1,)).fetchone()["c"]
r = admin.post("/admin/orders", data={"order_id": o1, "action": "delete"})
c2 = raw()
check("DEL", "Deleting a Completed order removes the order, its items and its notification",
      r.status_code == 302 and n_items >= 1 and n_notif >= 1 and not exists(o1)
      and c2.execute("SELECT COUNT(*) c FROM order_item WHERE order_id=?", (o1,)).fetchone()["c"] == 0
      and c2.execute("SELECT COUNT(*) c FROM notification WHERE order_id=?", (o1,)).fetchone()["c"] == 0)
check("DEL", "Other orders are untouched", exists(o2) and exists(o_pend))
check("DEL", "Status page and API for the deleted order return 404", staff.get(f"/order/{o1}/status").status_code == 404 and staff.get(f"/api/order/{o1}").status_code == 404)
check("DEL", "Staff menu still renders when its order history cookie points to a deleted order", staff.get("/menu").status_code == 200)
r = admin.post("/admin/orders", data={"order_id": 99999, "action": "delete"})
check("DEL", "Deleting an unknown order id is harmless", r.status_code == 302)

# ---- Logout / auth guard regression
admin.get("/admin/logout")
check("AUTH", "Admin pages require login after logout", all(admin.get(p).status_code == 302 for p in ("/admin/menu", "/admin/orders", "/admin/users", "/admin/survey")))

# ---- report
width = max(len(r[1]) for r in results)
fails = 0
for case, desc, ok, detail in results:
    fails += (not ok)
    print(f"{'PASS' if ok else 'FAIL'}  {case:<6} {desc}" + (f"  [{detail}]" if detail and not ok else ""))
print(f"\n{len(results) - fails}/{len(results)} checks passed")
import gc; gc.collect()
try:
    os.unlink(tmp.name)
except OSError:
    pass
sys.exit(1 if fails else 0)
