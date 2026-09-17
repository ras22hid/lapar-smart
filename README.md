# Lapar Smart: QR Menu Ordering System

A mobile-first QR code ordering system for **Lazaria Cafe**, developed for FAMA (Federal Agricultural Marketing Authority) staff, built as the implementation for the BIT4008 Undergraduate Project. This app implements the ten use cases described in `002_Chapter_Page_LaparSmart_-_QR_Menu_Ordering_System.docx`.

- **Live demo:** https://lapar-smart.vercel.app
- **Repository:** https://github.com/nrzfly/lapar-smart-qr-ordering
- **Admin dashboard:** https://lapar-smart.vercel.app/admin/login (passcode `admin123`)

## Features (mapped to use cases)

| # | Use Case | Where |
|---|----------|-------|
| UC1 | Scan QR Code | `/` landing page (generates a live QR code linking to the menu) |
| UC2 | View Daily Menu | `/menu` |
| UC3 | Place Order | `/menu` → submit → `/order` |
| UC4 | Reserve Meeting Room Order | `/menu` (tick "Meeting Room reservation") |
| UC5 | Receive Order Notification | `/order/<id>/status` (polls `/api/order/<id>` every 3s) |
| UC6 | Pay at Counter | Admin "Mark Completed" action on `/admin/orders` |
| UC7 | Update Daily Menu | `/admin/menu` |
| UC8 | View Orders | `/admin/orders` |
| UC9 | Update Order Status | `/admin/orders` (Pending → Preparing → Ready → Completed) |
| UC10 | Manage Users | `/admin/users` |

## Tech stack

Matches Chapter 4 of the report: **HTML5/CSS3/JavaScript** (server-rendered Jinja2 templates, mobile-first CSS, vanilla JS for the cart and notification polling), **Python Flask**, and **SQLite** (built-in).

### UI template

The look and feel is adapted from the **Davur** Bootstrap 5 restaurant admin dashboard + frontend template (`app/static/vendor/frontend` and `app/static/vendor/dashboard`), reusing its `style.css`, layout structure (header/sidebar), and card/table components. Only the CSS, core JS bundle, and images actually referenced by the adapted pages were copied in — the template's demo widgets (charts, calendar, email, chat) were not wired up since they're unrelated to Lapar Smart's use cases. Icon glyphs use Font Awesome via CDN rather than the template's bundled icon fonts, to keep the repo lean.

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python run.py
```

Then open http://localhost:5000. Demo staff IDs: `S001`, `S002`, `S003`. Admin passcode: `admin123` (override with the `ADMIN_PASSCODE` environment variable).

## Deploying to Vercel

This repo includes `vercel.json` configured for the `@vercel/python` runtime.

```bash
vercel login
vercel --prod
```

### Demo data note — read before presenting

Vercel's serverless functions do not provide a persistent disk. This app stores its SQLite database at `/tmp/laparsmart.db`, seeded automatically on first request, which persists only for the lifetime of **one warm serverless instance**.

In practice this means:
- A single browser tab clicking through one flow start-to-finish (e.g. place an order, then immediately open its own status page) usually stays on the same warm instance and works smoothly.
- But Vercel may route different requests — even seconds apart, e.g. a staff order followed by loading the admin dashboard — to **different** instances, each with its own empty `/tmp`. When that happens an order placed on one instance will not appear on `/admin/orders` served by another, and data resets entirely on a cold start or redeploy.

This was confirmed during testing: an order placed on `/menu` did not appear on `/admin/orders` moments later because the two requests landed on different instances. **For a live presentation, the safest approach is to record a screen-capture walkthrough in one continuous local run (`python run.py`)** rather than relying on the deployed instance to keep state across separate page loads, or accept that the Vercel demo may need a page refresh/retry to land back on the same warm instance.

For a reliable multi-user deployment, replace `app/db.py` with a managed database such as PostgreSQL (e.g. Vercel Postgres, Supabase, or Neon) — the rest of the app (routes, templates) would not need to change since all database access goes through `get_db()`.

## Project structure

```
lapar-smart/
  api/index.py          # Vercel entrypoint (WSGI app)
  app/
    __init__.py         # Flask app factory
    db.py                # SQLite schema, seed data, connection helper
    routes_staff.py      # UC1-UC6 (staff-facing)
    routes_admin.py       # UC7-UC10 (admin dashboard)
    templates/
    static/css, static/js
  run.py                 # local dev server
  requirements.txt
  vercel.json
```
