# -*- coding: utf-8 -*-
"""Executes manual test cases FT-01..FT-14 and RT-01..RT-14 through the web UI
(Microsoft Edge driven by Playwright) against a clean local database, records
test data / actual result / date / screenshot for each."""
import json, os, re, sqlite3, sys, time, datetime
from playwright.sync_api import sync_playwright

BASE = os.environ.get("LAPAR_TEST_BASE", "http://127.0.0.1:5077")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("LAPAR_TEST_OUT", os.path.join(HERE, "output"))
SHOTS = os.path.join(OUT, "shots")
os.makedirs(SHOTS, exist_ok=True)
DB = os.environ["LAPAR_TEST_DB"]  # set by run_all.py: the database of the server under test
# Chief Clerk email used by the meeting-room tests. Nothing is sent: the server replaces Gmail with a stub.
DEFAULT_CC = "faizal@example.com"
CC_EMAIL = os.environ.get("LAPAR_TEST_EMAIL", DEFAULT_CC)
CHANNEL = os.environ.get("LAPAR_BROWSER_CHANNEL", "msedge" if sys.platform == "win32" else "")
OUTBOX = DB + ".outbox.jsonl"
ADMIN_PW = "AdminPass123"

results = {}
VIEW = {"width": 1100, "height": 760}


def raw():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Case:
    def __init__(self, cid):
        self.id = cid
        self.shots = []
        self.checks = []
        self.data = ""
        self.actual = ""
        self.note = ""
        self.t0 = stamp()

    def shot(self, page, label=""):
        n = len(self.shots) + 1
        fn = f"{self.id}.png" if n == 1 else f"{self.id}_{n}.png"
        page.screenshot(path=os.path.join(SHOTS, fn))
        self.shots.append({"file": fn, "label": label})

    def check(self, desc, cond):
        self.checks.append({"desc": desc, "ok": bool(cond)})
        return bool(cond)

    def finish(self):
        self.data = self.data.replace(DEFAULT_CC, CC_EMAIL)
        self.actual = self.actual.replace(DEFAULT_CC, CC_EMAIL)
        ok = all(c["ok"] for c in self.checks) and bool(self.checks)
        results[self.id] = {
            "id": self.id, "data": self.data, "actual": self.actual, "note": self.note,
            "status": "Pass" if ok else "FAIL", "checks": self.checks,
            "shots": self.shots, "date": self.t0[:10], "time": self.t0[11:],
        }
        print(("PASS " if ok else "FAIL ") + self.id, [c["desc"] for c in self.checks if not c["ok"]])


def admin_login(page, aid="A001", pw=ADMIN_PW):
    page.goto(BASE + "/admin/login")
    page.fill("input[name=admin_id]", aid)
    page.fill("input[name=password]", pw)
    page.click("button[type=submit]")
    page.wait_for_load_state()


def set_qty(page, item_id, n):
    loc = page.locator(f'input[name=item_id][value="{item_id}"]')
    row = loc.locator("xpath=./ancestor::*[.//input[@name='quantity']][1]")
    for _ in range(n):
        row.locator(".qty-btn").nth(1).click()


def item_id_by_name(name):
    return raw().execute("SELECT item_id FROM menu_item WHERE name=?", (name,)).fetchone()["item_id"]


def outbox():
    """Emails the application tried to send (Gmail is replaced by a stub that records them)."""
    if not os.path.exists(OUTBOX):
        return []
    return [json.loads(l) for l in open(OUTBOX, encoding="utf-8") if l.strip()]


def mails_for(order_id):
    return [m for m in outbox() if re.search(rf"#{order_id}(?!\d)", m["subject"])]


def fill_staff(page, sid, name, dept, phone, email):
    page.fill("input[name=staff_id]", sid)
    page.fill("input[name=staff_name]", name)
    page.fill("input[name=department]", dept)
    page.fill("input[name=phone_number]", phone)
    page.fill("input[name=email]", email)


def cc_register(page, sid, name, dept, email, pw, shot_case=None):
    page.goto(BASE + "/staff/register")
    page.fill("input[name=staff_id]", sid)
    page.fill("input[name=name]", name)
    page.fill("input[name=department]", dept)
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", pw)
    page.fill("input[name=confirm_password]", pw)
    if shot_case:
        shot_case.shot(page, "Chief Clerk registration page with the details entered")
    page.click("button[type=submit]")
    page.wait_for_load_state()


def cc_login(page, sid, pw):
    page.goto(BASE + "/staff/login")
    page.fill("input[name=staff_id]", sid)
    page.fill("input[name=password]", pw)
    page.click("button[type=submit]")
    page.wait_for_load_state()


def place_counter_order(page, items, staff, case=None, shot_review=False):
    """items: list of (name, qty); staff: tuple of 5 (id, name, department, phone, email). Returns order id."""
    page.goto(BASE + "/menu")
    for name, qty in items:
        set_qty(page, item_id_by_name(name), qty)
    page.click("button:has-text('Review Order')")
    page.wait_for_load_state()
    if case and shot_review:
        fill_staff(page, *staff)
        case.shot(page, "Review Order page with staff details entered")
    else:
        fill_staff(page, *staff)
    page.click("button:has-text('Confirm Order')")
    page.wait_for_url(re.compile(r"/order/\d+/status"))
    return int(re.search(r"/order/(\d+)/status", page.url).group(1))


def place_meeting_order(page, room, when, pkg_id, qty, phone, email, case=None):
    """The page is already logged in as a Chief Clerk. Starts from the homepage."""
    page.goto(BASE + "/catering")
    page.fill("input[name=meeting_room]", room)
    page.fill("input[name=meeting_time]", when)
    page.click(f'.lapar-package-card[data-package-id="{pkg_id}"]')
    page.fill("#package_qty", str(qty))
    if case:
        case.shot(page, "Catering page with the room, time and package chosen")
    page.click("button:has-text('Review Order')")
    page.wait_for_load_state()
    page.fill("input[name=phone_number]", phone)
    page.fill("input[name=email]", email)
    if case:
        case.shot(page, "Review Order page for the meeting-room order (Chief Clerk details, phone and email)")
    page.click("button:has-text('Confirm Order')")
    page.wait_for_url(re.compile(r"/order/\d+/status"))
    return int(re.search(r"/order/(\d+)/status", page.url).group(1))


def advance(admin, order_id):
    admin.goto(BASE + "/admin/orders")
    admin.locator(f'form:has(input[name=order_id][value="{order_id}"]) button').click()
    admin.wait_for_load_state()


def status_of(order_id):
    return raw().execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()["status"]


def main():
    ctx_state = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel=CHANNEL, headless=True) if CHANNEL else p.chromium.launch(headless=True)
        sctx = br.new_context(viewport=VIEW)
        actx = br.new_context(viewport=VIEW)
        staff = sctx.new_page()
        admin = actx.new_page()
        staff.set_default_timeout(15000)
        admin.set_default_timeout(15000)

        # ---------------- FUNCTIONAL TESTS ----------------
        # FT-01 Scan QR Code
        c = Case("FT-01")
        c.data = f"QR code on the landing page; the QR target URL is {BASE}/menu (scan simulated by opening the target URL)."
        staff.goto(BASE + "/")
        c.check("QR code image displayed", staff.locator("img[alt*='QR']").count() == 1)
        c.shot(staff, "Landing page showing the QR code")
        target = BASE + "/menu"
        staff.goto(target)
        c.check("Menu page opened directly", staff.url.rstrip("/").endswith("/menu"))
        c.check("No login requested", "login" not in staff.url.lower() and staff.locator("input[type=password]").count() == 0)
        c.actual = "Landing page displayed the QR code; opening its target URL showed the daily menu directly with no login prompt."
        c.finish()

        # FT-02 View Daily Menu
        c = Case("FT-02")
        names = [r["name"] for r in raw().execute("SELECT name FROM menu_item WHERE is_available=1").fetchall()]
        c.data = f"{len(names)} seeded available items: " + ", ".join(names) + "."
        staff.goto(BASE + "/menu")
        body = staff.inner_text("body")
        c.check("All available items displayed", all(n in body for n in names))
        c.check("Prices displayed", "RM 6.50" in body and "RM 2.00" in body)
        c.check("Categories displayed", "Food" in body and "Beverage" in body)
        c.shot(staff, "Daily menu page")
        c.actual = "All seeded items were displayed with name, price (RM) and category."
        c.finish()

        # FT-03 Place Order
        c = Case("FT-03")
        c.data = "Items: Nasi Lemak Ayam x2 (RM 6.50), Teh Tarik x1 (RM 2.00). Staff: S1001 / Aminah Binti Ali / Finance Division / 0123456789 / aminah@example.com."
        o1 = place_counter_order(staff, [("Nasi Lemak Ayam", 2), ("Teh Tarik", 1)],
                                 ("S1001", "Aminah Binti Ali", "Finance Division", "0123456789", "aminah@example.com"), c, shot_review=True)
        row = raw().execute("SELECT * FROM orders WHERE order_id=?", (o1,)).fetchone()
        c.check("Order created with status Pending", row["status"] == "Pending")
        c.check("Order type Counter", row["order_type"] == "Counter")
        c.check("Total RM 15.00", abs(row["total_amount"] - 15.0) < 1e-6)
        c.check("Email address stored with the order", row["email"] == "aminah@example.com")
        c.check("No email sent for a Pending counter order", len(mails_for(o1)) == 0)
        c.shot(staff, f"Order Status page for order #{o1}")
        c.actual = f"Order #{o1} created with status Pending, type Counter, total RM 15.00."
        c.finish()

        # FT-04 Reserve Meeting Room Order (Chief Clerk only)
        c = Case("FT-04")
        c.data = ("Visitor opens the homepage and clicks Meeting Order; new Chief Clerk S1002 / Faizal Rahman / IT Division / faizal@example.com registers and logs in; "
                  "Meeting Room 2, 2026-11-16 10:00, Standard Meeting Package (20 pax) x1; phone 0171234567.")
        cctx = br.new_context(viewport=VIEW)
        cc = cctx.new_page()
        cc.set_default_timeout(15000)
        cc.goto(BASE + "/")
        c.check("Homepage has a Meeting Order button and no View Menu button", cc.locator("a:has-text('Meeting Order')").count() >= 1 and cc.locator("a:has-text('View Menu')").count() == 0)
        cc.click("a:has-text('Meeting Order')")
        cc.wait_for_load_state()
        c.check("Not logged in: redirected to the Chief Clerk login page", "/staff/login" in cc.url)
        c.shot(cc, "Chief Clerk login page shown after clicking Meeting Order")
        cc_register(cc, "S1002", "Faizal Rahman", "IT Division", CC_EMAIL, "ChiefClerk2026!", c)
        c.check("Registration success message", "Registration complete" in cc.inner_text("body"))
        c.shot(cc, "Chief Clerk registration completed")
        cc_login(cc, "S1002", "ChiefClerk2026!")
        c.check("Login opens the catering page", cc.url.rstrip("/").endswith("/catering"))
        body = cc.inner_text("body")
        c.check("Catering page lists the package food and beverages (by the jug)", "Food" in body and "Beverages" in body and "jug" in body)
        o2 = place_meeting_order(cc, "Meeting Room 2", "2026-11-16T10:00", 2, 1, "0171234567", CC_EMAIL, c)
        row = raw().execute("SELECT * FROM orders WHERE order_id=?", (o2,)).fetchone()
        c.check("order_type = MeetingRoom", row["order_type"] == "MeetingRoom")
        c.check("Room saved", row["meeting_room"] == "Meeting Room 2")
        c.check("Time saved", (row["meeting_time"] or "").startswith("2026-11-16") and "10:00" in row["meeting_time"])
        c.check("Package saved", row["package_name"] == "Standard Meeting Package")
        c.check("Order placed under the Chief Clerk's own Staff ID, name and department", (row["staff_id"], row["staff_name"], row["department"]) == ("S1002", "Faizal Rahman", "IT Division"))
        m = mails_for(o2)
        c.check("A Pending email was sent to the address on the order", len(m) == 1 and m[0]["to"] == CC_EMAIL and "Pending" in m[0]["body"])
        c.shot(cc, f"Order Status page for meeting-room order #{o2}")
        c.actual = (f"The visitor was sent to the login page; the Chief Clerk registered, logged in and saw the package contents. Order #{o2} was created with orderType = MeetingRoom, "
                    f"room 'Meeting Room 2', time {row['meeting_time']}, package 'Standard Meeting Package', under S1002, and a Pending email was sent to faizal@example.com.")
        c.finish()

        # FT-05 Receive Order Notification
        c = Case("FT-05")
        c.data = f"Counter order #{o1} (Pending, email aminah@example.com). Staff keeps the Order Status page open; admin A001 sets the order to Preparing, then Ready."
        staff.goto(f"{BASE}/order/{o1}/status?staff_id=S1001")
        admin_login(admin)
        advance(admin, o1)  # Preparing
        t = time.time()
        advance(admin, o1)  # Ready
        try:
            staff.wait_for_selector("#notif-banner:not([hidden])", timeout=10000)
            delay = time.time() - t
        except Exception:
            delay = None
        banner = staff.inner_text("#notif-banner") if delay is not None else ""
        c.check("Banner appeared", delay is not None)
        c.check("Banner text says order is ready", "ready" in banner.lower())
        c.check("Alert within 3 s polling interval (+ margin)", delay is not None and delay <= 4.5)
        m = mails_for(o1)
        c.check("Exactly one email, sent when the status became Ready (none for Preparing)", len(m) == 1 and "is ready" in m[0]["subject"])
        c.check("Email goes to the address on the order and says to collect and pay at the counter", len(m) == 1 and m[0]["to"] == "aminah@example.com" and "collection and payment at the counter" in m[0]["body"])
        c.shot(staff, "Order Status page showing the order-ready alert")
        c.actual = (f"Alert '{banner.strip()}' appeared {delay:.1f} s after the admin set Ready (polling interval 3 s), and one email was sent to aminah@example.com at Ready." if delay is not None else "Alert did not appear.")
        c.finish()

        # FT-06 Mark Order Completed
        c = Case("FT-06")
        c.data = f"Order #{o1} (status Ready); admin A001 clicks the next-status button to mark it Completed."
        advance(admin, o1)
        c.check("Status is Completed in DB", status_of(o1) == "Completed")
        c.check("A counter order sends no email for Completed (Ready only)", len(mails_for(o1)) == 1)
        admin.goto(BASE + "/admin/orders")
        c.check("Order still listed", f"#{o1}" in admin.inner_text("body") or str(o1) in admin.inner_text("body"))
        c.shot(admin, "Admin Orders page, order shown as Completed")
        c.actual = f"Order #{o1} changed to Completed and remained in the Orders list."
        c.finish()

        # FT-07 Update Daily Menu
        c = Case("FT-07")
        c.data = "New item: Karipap Inti, RM 1.20, category Food."
        admin.goto(BASE + "/admin/menu")
        admin.fill("form:has(input[name=action][value=add]) input[name=name]", "Karipap Inti")
        admin.fill("form:has(input[name=action][value=add]) input[name=price]", "1.20")
        admin.click("form:has(input[name=action][value=add]) button[type=submit]")
        admin.wait_for_load_state()
        staff.goto(BASE + "/menu")
        c.check("New item shown to staff", "Karipap Inti" in staff.inner_text("body"))
        c.shot(staff, "Staff menu showing the newly added item")
        c.shot(admin, "Admin Menu page after adding the item")
        c.actual = "Karipap Inti (RM 1.20) was added by the admin and appeared on the staff menu immediately."
        c.finish()

        # FT-08 View Orders
        c = Case("FT-08")
        c.data = f"Orders present: #{o1} (Counter, Completed) and #{o2} (MeetingRoom, Pending)."
        admin.goto(BASE + "/admin/orders")
        body = admin.inner_text("body")
        c.check("Counter order listed", str(o1) in body and "Aminah" in body)
        c.check("Meeting-room order listed", str(o2) in body and "Faizal" in body)
        c.check("Statuses shown", "Completed" in body and "Pending" in body)
        c.shot(admin, "Admin Orders page listing both order types")
        c.actual = "Both the counter order and the meeting-room order were listed with type, status and timestamp."
        c.finish()

        # FT-09 Update Order Status
        c = Case("FT-09")
        c.data = f"Order #{o2} (MeetingRoom): status changed from Pending to Preparing by admin A001."
        advance(admin, o2)
        c.check("Status Preparing in DB", status_of(o2) == "Preparing")
        staff.goto(f"{BASE}/order/{o2}/status?staff_id=S1002")
        c.check("Staff status page shows Preparing", "Preparing" in staff.inner_text("body"))
        m = mails_for(o2)
        c.check("A Preparing email was sent for the meeting-room order", len(m) == 2 and "Preparing" in m[1]["subject"] and m[1]["to"] == CC_EMAIL)
        c.shot(staff, "Staff Order Status page showing Preparing")
        admin.goto(BASE + "/admin/orders")
        c.shot(admin, "Admin Orders page showing Preparing")
        c.actual = f"Order #{o2} was updated to Preparing and the new status was shown on both the admin and staff views; a Preparing email was sent to the Chief Clerk."
        c.finish()

        # FT-10 Manage Cafe Admins
        c = Case("FT-10")
        c.data = "New Cafe Admin: ID A002, name 'Nurul Huda', role 'Cafe Admin', email a002@example.com."
        admin.goto(BASE + "/admin/users")
        f = "form:has(input[name=action][value=add])"
        admin.fill(f"{f} input[name=user_id]", "A002")
        admin.fill(f"{f} input[name=name]", "Nurul Huda")
        admin.fill(f"{f} input[name=email]", "a002@example.com")
        admin.click(f"{f} button[type=submit]")
        admin.wait_for_load_state()
        r = raw().execute("SELECT * FROM admin WHERE admin_id='A002'").fetchone()
        c.check("Account created", r is not None and r["active"] == 1)
        c.check("No password yet (pending)", r is not None and not r["password_hash"])
        c.check("Listed on page", "A002" in admin.inner_text("body"))
        c.shot(admin, "Manage Cafe Admins page listing the new account")
        c.actual = "Account A002 was created without a password (pending registration) and listed on the page."
        c.finish()

        # FT-11 Register Admin
        c = Case("FT-11")
        c.data = "Admin ID A002, new password 'NewAdmin2026!' (confirmed)."
        nctx = br.new_context(viewport=VIEW)
        npg = nctx.new_page()
        npg.goto(BASE + "/admin/register")
        npg.fill("input[name=admin_id]", "A002")
        npg.fill("input[name=password]", "NewAdmin2026!")
        npg.fill("input[name=confirm_password]", "NewAdmin2026!")
        npg.click("button[type=submit]")
        npg.wait_for_load_state()
        c.check("Registration success message", "Registration complete" in npg.inner_text("body"))
        c.shot(npg, "Registration completed")
        admin_login(npg, "A002", "NewAdmin2026!")
        c.check("New admin can log in", "/admin/orders" in npg.url)
        c.shot(npg, "New admin A002 logged in to the Orders page")
        c.actual = "A002 completed registration and then logged in to the admin Orders page."
        c.finish()
        nctx.close()

        # FT-12 Forgot Password
        c = Case("FT-12")
        c.data = "Admin ID A001 (email on file a001@example.com); new password 'ResetPass2026!'."
        fctx = br.new_context(viewport=VIEW)
        fp = fctx.new_page()
        fp.goto(BASE + "/admin/forgot-password")
        fp.fill("input[name=admin_id]", "A001")
        fp.click("button[type=submit]")
        fp.wait_for_load_state()
        c.check("Confirmation shown", fp.locator(".alert").count() > 0 or "link" in fp.inner_text("body").lower())
        c.shot(fp, "Forgot Password confirmation page")
        tok = raw().execute("SELECT token FROM password_reset WHERE admin_id='A001' ORDER BY rowid DESC").fetchone()
        c.check("Single-use reset token created", tok is not None)
        fp.goto(f"{BASE}/admin/reset-password/{tok['token']}")
        fp.fill("input[name=password]", "ResetPass2026!")
        fp.fill("input[name=confirm_password]", "ResetPass2026!")
        fp.click("button[type=submit]")
        fp.wait_for_load_state()
        c.check("Password updated message", "Password updated" in fp.inner_text("body"))
        c.shot(fp, "Password reset completed")
        fp.goto(f"{BASE}/admin/reset-password/{tok['token']}")
        c.check("Used link is rejected", "invalid or has expired" in fp.inner_text("body"))
        admin_login(fp, "A001", "ResetPass2026!")
        c.check("Login with the new password succeeds", "/admin/orders" in fp.url)
        c.check("A reset email was handed to the (stub) Gmail sender for the address on file", any(m["purpose"] == "password reset" and m["to"] == "a001@example.com" for m in outbox()))
        c.note = "The reset email was not sent through Gmail in this environment (no Gmail credentials configured locally): a stub recorded it, and the reset link was read from the password_reset table. Delivery to the Gmail inbox is shown separately."
        c.actual = "Reset request accepted, link set a new password, the used link was rejected, and login with the new password succeeded."
        c.finish()
        fctx.close()

        # FT-13 Review Order
        c = Case("FT-13")
        c.data = ("Counter order: Roti Canai x1. Staff details S1003 / Hana Ismail / HR Division / hana@example.com with the phone left empty; then phone 0191112222 with the invalid email 'not-an-email'; "
                  "then all five details completed.")
        before = raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        staff.goto(BASE + "/menu")
        set_qty(staff, item_id_by_name("Roti Canai"), 1)
        staff.click("button:has-text('Review Order')")
        staff.wait_for_load_state()
        c.check("Review page has the five fields", all(staff.locator(f"input[name={n}]").count() == 1 for n in ("staff_id", "staff_name", "department", "phone_number", "email")))
        fill_staff(staff, "S1003", "Hana Ismail", "HR Division", "", "hana@example.com")
        staff.click("button:has-text('Confirm Order')")  # browser blocks: phone required
        staff.wait_for_timeout(500)
        c.check("Browser blocks submit while a field is empty", "/order/review" in staff.url)
        # bypass client-side validation to prove the server also rejects it
        staff.evaluate("document.querySelectorAll('[required]').forEach(e=>e.removeAttribute('required')); document.querySelector('form[action$=\"/order\"]').noValidate = true")
        staff.click("button:has-text('Confirm Order')")
        staff.wait_for_load_state()
        mid = raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        c.check("No order created with a missing detail", mid == before)
        c.check("Returned to menu with an error", "/menu" in staff.url and "error=missing_staff_info" in staff.url)
        c.shot(staff, "Menu page with the error after a detail was missing")
        # invalid email
        staff.goto(BASE + "/menu")
        set_qty(staff, item_id_by_name("Roti Canai"), 1)
        staff.click("button:has-text('Review Order')")
        staff.wait_for_load_state()
        fill_staff(staff, "S1003", "Hana Ismail", "HR Division", "0191112222", "not-an-email")
        staff.evaluate("document.querySelector('form[action$=\"/order\"]').noValidate = true")
        staff.click("button:has-text('Confirm Order')")
        staff.wait_for_load_state()
        mid2 = raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        c.check("No order created with an invalid email", mid2 == before)
        c.check("Returned to menu with an invalid-email error", "error=invalid_email" in staff.url and "valid email" in staff.inner_text("body"))
        c.shot(staff, "Menu page with the invalid-email error")
        o3 = place_counter_order(staff, [("Roti Canai", 1)], ("S1003", "Hana Ismail", "HR Division", "0191112222", "hana@example.com"))
        after = raw().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        c.check("Order created once all five details given", after == before + 1)
        c.shot(staff, f"Order #{o3} created after all five details were provided")
        c.actual = ("With the phone number empty, or with an invalid email address, no order was created (blocked by the browser, and rejected by the server when the browser check was bypassed); "
                    "with all five details the order was created.")
        c.finish()

        # FT-14 Login
        c = Case("FT-14")
        c.data = "Admin ID A001 with the correct password, then with the wrong password 'WrongPass1'."
        lctx = br.new_context(viewport=VIEW)
        lp = lctx.new_page()
        admin_login(lp, "A001", "ResetPass2026!")
        c.check("Correct password opens Orders page", "/admin/orders" in lp.url)
        c.shot(lp, "Orders page after logging in with the correct password")
        lp.goto(BASE + "/admin/logout")
        admin_login(lp, "A001", "WrongPass1")
        c.check("Wrong password shows an error", "Incorrect" in lp.inner_text("body"))
        lp.goto(BASE + "/admin/orders")
        c.check("No session created (redirected to login)", "/admin/login" in lp.url)
        lp.goto(BASE + "/admin/login")
        admin_login(lp, "A001", "WrongPass1")
        c.shot(lp, "Login page rejecting the wrong password")
        c.actual = "The correct password opened the Orders page; the wrong password showed 'Incorrect admin ID or password.' and created no session."
        c.finish()
        lctx.close()
        PW_A001 = "ResetPass2026!"

        # ---------------- REGRESSION TESTS ----------------
        # RT-01
        c = Case("RT-01")
        c.data = f"Original counter QR code; target URL {BASE}/menu (after the Meeting Order button replaced View Menu on the homepage)."
        staff.goto(BASE + "/")
        c.check("QR code present", staff.locator("img[alt*='QR']").count() == 1)
        c.check("Homepage shows Meeting Order and no View Menu button", staff.locator("a:has-text('Meeting Order')").count() >= 1 and staff.locator("a:has-text('View Menu')").count() == 0)
        staff.goto(BASE + "/menu")
        c.check("Redirects to the daily menu", staff.url.rstrip("/").endswith("/menu"))
        c.check("The menu page has no meeting-room check or catering section", staff.locator("#is_meeting").count() == 0 and "Catering Packages" not in staff.inner_text("body"))
        c.check("Menu lists items", "Nasi Lemak Ayam" in staff.inner_text("body"))
        c.shot(staff, "Daily menu opened from the counter QR code")
        c.actual = "The counter QR code target opened the daily menu as before, with no meeting-room check on the menu page."
        c.finish()

        # RT-02
        c = Case("RT-02")
        c.data = "Menu after the admin added 'Karipap Inti' (FT-07)."
        staff.goto(BASE + "/menu")
        body = staff.inner_text("body")
        c.check("Updated item shown", "Karipap Inti" in body)
        c.check("Original items still shown", "Teh Tarik" in body and "Fried Chicken Set" in body)
        c.check("Page rendered without an error", "Internal Server Error" not in body)
        c.shot(staff, "Staff menu including the updated item")
        c.actual = "Updated and original items were displayed correctly with no error."
        c.finish()

        # RT-03
        c = Case("RT-03")
        c.data = "Counter order: Kopi O x2 (RM 1.50), Iced Milo x1 (RM 2.50). Staff: S1004 / Zul Hakim / Marketing Division / 0133334444 / zul@example.com."
        o4 = place_counter_order(staff, [("Kopi O", 2), ("Iced Milo", 1)], ("S1004", "Zul Hakim", "Marketing Division", "0133334444", "zul@example.com"))
        row = raw().execute("SELECT * FROM orders WHERE order_id=?", (o4,)).fetchone()
        c.check("orderType = Counter", row["order_type"] == "Counter")
        c.check("Status Pending", row["status"] == "Pending")
        c.check("Total RM 5.50", abs(row["total_amount"] - 5.5) < 1e-6)
        c.shot(staff, f"Order Status page for counter order #{o4}")
        c.actual = f"Order #{o4} was created with orderType = Counter, status Pending, total RM 5.50."
        c.finish()

        # RT-04
        c = Case("RT-04")
        c.data = ("Staff ID S1099 (not a Chief Clerk) tries to log in; logged-in Chief Clerk S1002 orders Meeting Room 3, 2026-11-17 14:30, Snack Box Package (10 pax) x2; "
                  "phone 0125556666, email faizal@example.com.")
        octx = br.new_context(viewport=VIEW)
        other = octx.new_page()
        other.goto(BASE + "/catering")
        c.check("A visitor opening the catering page is sent to the login page", "/staff/login" in other.url)
        cc_login(other, "S1099", "SomePassword1")
        c.check("A staff ID that is not a Chief Clerk cannot log in", "Only registered Chief Clerk" in other.inner_text("body"))
        other.goto(BASE + "/catering")
        c.check("The catering page and package contents stay closed to that visitor", "/staff/login" in other.url and "Beverages" not in other.inner_text("body"))
        c.shot(other, "Login page refusing a staff ID that is not a Chief Clerk")
        octx.close()
        o5 = place_meeting_order(cc, "Meeting Room 3", "2026-11-17T14:30", 1, 2, "0125556666", CC_EMAIL)
        row = raw().execute("SELECT * FROM orders WHERE order_id=?", (o5,)).fetchone()
        c.check("order_type = MeetingRoom", row["order_type"] == "MeetingRoom")
        c.check("Meeting details saved", row["meeting_room"] == "Meeting Room 3" and "14:30" in (row["meeting_time"] or "") and row["package_qty"] == 2)
        c.check("No notification record at submission (only the Pending email)", raw().execute("SELECT COUNT(*) c FROM notification WHERE order_id=?", (o5,)).fetchone()["c"] == 0 and len(mails_for(o5)) == 1)
        c.shot(cc, f"Order Status page for meeting-room order #{o5}")
        c.actual = (f"S1099 could not log in or open the catering page. The Chief Clerk's order #{o5} was saved with its meeting details; the notification feature and the Gmail alert did not interfere "
                    "(no notification record until Ready; one Pending email).")
        c.finish()

        # RT-05
        c = Case("RT-05")
        c.data = f"Order #{o4}: admin sets Pending -> Preparing -> Ready while staff has the status page open."
        admin2 = actx.new_page()
        admin2.set_default_timeout(15000)
        admin_login(admin2, "A001", PW_A001)
        staff.goto(f"{BASE}/order/{o4}/status?staff_id=S1004")
        advance(admin2, o4)
        advance(admin2, o4)
        try:
            staff.wait_for_selector("#notif-banner:not([hidden])", timeout=10000)
            ok = True
        except Exception:
            ok = False
        c.check("Notification row created", raw().execute("SELECT COUNT(*) c FROM notification WHERE order_id=?", (o4,)).fetchone()["c"] == 1)
        c.check("Alert shown on status page", ok)
        m = mails_for(o4)
        c.check("One email sent at Ready", len(m) == 1 and m[0]["to"] == "zul@example.com" and "is ready" in m[0]["subject"])
        c.shot(staff, "Order-ready alert still shown")
        c.actual = "The notification was created, the order-ready alert was shown on the status page, and one email was sent at Ready."
        c.finish()

        # RT-06
        c = Case("RT-06")
        c.data = f"Order #{o4} (Ready); admin marks it Completed after the account-management feature was added."
        advance(admin2, o4)
        c.check("Completed in DB", status_of(o4) == "Completed")
        admin2.goto(BASE + "/admin/orders")
        c.shot(admin2, "Admin Orders page with the order Completed")
        c.actual = f"Order #{o4} was marked Completed correctly."
        c.finish()

        # RT-07
        c = Case("RT-07")
        c.data = "Item 'Karipap Inti': hidden via the admin Menu page, then shown again."
        kid = item_id_by_name("Karipap Inti")
        admin2.goto(BASE + "/admin/menu")
        admin2.locator(f'form:has(input[name=item_id][value="{kid}"]):has(input[name=action][value=toggle]) button').click()
        admin2.wait_for_load_state()
        staff.goto(BASE + "/menu")
        c.check("Hidden item not on staff menu", "Karipap Inti" not in staff.inner_text("body"))
        c.shot(staff, "Staff menu with the item hidden")
        admin2.locator(f'form:has(input[name=item_id][value="{kid}"]):has(input[name=action][value=toggle]) button').click()
        admin2.wait_for_load_state()
        staff.goto(BASE + "/menu")
        c.check("Item restored when toggled back", "Karipap Inti" in staff.inner_text("body"))
        c.shot(staff, "Staff menu with the item shown again")
        c.actual = "The hidden item disappeared from the staff menu immediately, and toggling it back restored it."
        c.finish()

        # RT-08
        c = Case("RT-08")
        c.data = "Orders page with both order types present (counter and meeting-room)."
        admin2.goto(BASE + "/admin/orders")
        body = admin2.inner_text("body")
        c.check("Counter label shown", "Counter" in body)
        c.check("Meeting room label shown", "Meeting" in body)
        c.shot(admin2, "Admin Orders page with both order types")
        c.actual = "Both order types were listed with the correct type label."
        c.finish()

        # RT-09
        c = Case("RT-09")
        c.data = f"Meeting-room order #{o5}: status updated in succession (Pending -> Preparing -> Ready -> Completed)."
        advance(admin2, o5)
        advance(admin2, o5)
        n_ready = raw().execute("SELECT COUNT(*) c FROM notification WHERE order_id=?", (o5,)).fetchone()["c"]
        c.check("Status is Ready", status_of(o5) == "Ready")
        c.check("Exactly one notification record for the changes up to Ready", n_ready == 1)
        advance(admin2, o5)
        n = raw().execute("SELECT COUNT(*) c FROM notification WHERE order_id=?", (o5,)).fetchone()["c"]
        c.check("Status is Completed", status_of(o5) == "Completed")
        c.check("Still one notification record after Completed", n == 1)
        m = mails_for(o5)
        stat = [x for x in ("Pending", "Preparing", "Ready", "Completed") for mm in m if f"status: {x}" in mm["body"]]
        c.check("One email per status: Pending, Preparing, Ready, Completed", stat == ["Pending", "Preparing", "Ready", "Completed"] and len(m) == 4)
        c.check("The Ready email says cafe staff will deliver it to the meeting room", any("deliver it to Meeting Room 3" in mm["body"] for mm in m))
        admin2.goto(BASE + "/admin/orders")
        c.shot(admin2, "Admin Orders page after the successive updates")
        c.actual = f"Status updated correctly; {n} notification record was created and {len(m)} emails were sent (one for each of the four statuses)."
        c.finish()

        # RT-10
        c = Case("RT-10")
        c.data = "New Cafe Admin: ID A003, name 'Mohd Azri', email a003@example.com (after FAMA staff and Chief Clerk management were removed from the Users page)."
        admin2.goto(BASE + "/admin/users")
        c.check("Users page has no FAMA Staff section", "FAMA Staff" not in admin2.inner_text("body"))
        c.check("Users page has no Chief Clerk section (Chief Clerks register themselves)", "Chief Clerk" not in admin2.inner_text("body"))
        f = "form:has(input[name=action][value=add])"
        admin2.fill(f"{f} input[name=user_id]", "A003")
        admin2.fill(f"{f} input[name=name]", "Mohd Azri")
        admin2.fill(f"{f} input[name=email]", "a003@example.com")
        admin2.click(f"{f} button[type=submit]")
        admin2.wait_for_load_state()
        r = raw().execute("SELECT * FROM admin WHERE admin_id='A003'").fetchone()
        c.check("Account created in a pending state", r is not None and not r["password_hash"])
        c.shot(admin2, "Manage Cafe Admins page with A003 added")
        c.actual = "A003 was created in a pending state; the page lists Cafe Admin accounts only."
        c.finish()

        # RT-11
        c = Case("RT-11")
        c.data = "Admin ID A003 completes registration with password 'Azri2026Pass!'."
        rctx = br.new_context(viewport=VIEW)
        rp = rctx.new_page()
        rp.goto(BASE + "/admin/register")
        rp.fill("input[name=admin_id]", "A003")
        rp.fill("input[name=password]", "Azri2026Pass!")
        rp.fill("input[name=confirm_password]", "Azri2026Pass!")
        rp.click("button[type=submit]")
        rp.wait_for_load_state()
        c.check("Registration succeeds", "Registration complete" in rp.inner_text("body"))
        c.shot(rp, "Registration completed for A003")
        admin_login(rp, "A003", "Azri2026Pass!")
        c.check("Can log in immediately", "/admin/orders" in rp.url)
        c.actual = "Registration succeeded and A003 logged in immediately."
        c.finish()
        rctx.close()

        # RT-12
        c = Case("RT-12")
        c.data = "Admin ID A001 requests another reset link; new password 'ResetAgain2026!'."
        rctx = br.new_context(viewport=VIEW)
        rp = rctx.new_page()
        rp.goto(BASE + "/admin/forgot-password")
        rp.fill("input[name=admin_id]", "A001")
        rp.click("button[type=submit]")
        rp.wait_for_load_state()
        tok = raw().execute("SELECT token FROM password_reset WHERE admin_id='A001' AND used=0 ORDER BY rowid DESC").fetchone()
        c.check("Single-use reset token created", tok is not None)
        rp.goto(f"{BASE}/admin/reset-password/{tok['token']}")
        rp.fill("input[name=password]", "ResetAgain2026!")
        rp.fill("input[name=confirm_password]", "ResetAgain2026!")
        rp.click("button[type=submit]")
        rp.wait_for_load_state()
        c.check("Password updated", "Password updated" in rp.inner_text("body"))
        c.shot(rp, "Password updated through the reset link")
        admin_login(rp, "A001", "ResetAgain2026!")
        c.check("Login with the new password succeeds", "/admin/orders" in rp.url)
        c.note = "Email delivery not exercised locally (no Gmail credentials); link read from the password_reset table."
        c.actual = "A fresh single-use link updated the password and the admin logged in with it."
        c.finish()
        rctx.close()

        # RT-13
        c = Case("RT-13")
        c.data = "Counter order: Mee Goreng Mamak x1. Staff: S1006 / Lee Wei Ming / Operations / 0147778888 / lee@example.com (after the Users page was simplified and the email field was added)."
        o6 = place_counter_order(staff, [("Mee Goreng Mamak", 1)], ("S1006", "Lee Wei Ming", "Operations", "0147778888", "lee@example.com"), c, shot_review=True)
        r = raw().execute("SELECT * FROM orders WHERE order_id=?", (o6,)).fetchone()
        c.check("All five details stored", (r["staff_id"], r["staff_name"], r["department"], r["phone_number"], r["email"]) == ("S1006", "Lee Wei Ming", "Operations", "0147778888", "lee@example.com"))
        c.actual = f"The Review Order page collected all five details and order #{o6} stored them correctly."
        c.finish()

        # RT-14
        c = Case("RT-14")
        c.data = "Admin A001 current password 'ResetAgain2026!' (success) and 'WrongPass1' (failure)."
        lctx = br.new_context(viewport=VIEW)
        lp = lctx.new_page()
        admin_login(lp, "A001", "ResetAgain2026!")
        c.check("Current password succeeds", "/admin/orders" in lp.url)
        lp.goto(BASE + "/admin/logout")
        admin_login(lp, "A001", "WrongPass1")
        c.check("Wrong password fails", "Incorrect" in lp.inner_text("body") and "/admin/login" in lp.url)
        c.shot(lp, "Login page rejecting the wrong password")
        c.actual = "Login succeeded with the current password and failed with a wrong one."
        c.finish()

        br.close()
    json.dump(results, open(os.path.join(OUT, "results.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    fails = [k for k, v in results.items() if v["status"] != "Pass"]
    print("TOTAL", len(results), "FAILED:", fails)
    sys.exit(1 if fails or len(results) != 28 else 0)


if __name__ == "__main__":
    main()


