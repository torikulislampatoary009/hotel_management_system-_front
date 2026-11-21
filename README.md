# Hotel Management System: Frontend (Python)

Flask web app (server-rendered pages) that talks to the backend API. Staff sign in; the session token lives in a signed, HTTP-only cookie. Every form is CSRF-protected.

## Run locally
Start the backend first (see its README), then:
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set SECRET_KEY and BACKEND_URL (default http://localhost:5000)
python app.py                   # http://localhost:8000
```

## Production
`gunicorn app:app` (see `Procfile`). Set `BACKEND_URL` to the deployed backend, a long random `SECRET_KEY`, and `COOKIE_SECURE=true` once the site is on HTTPS.

## Pages
Dashboard with live room board, bookings (search, arrivals, in house, due out), new-booking wizard with availability and guest lookup, booking page (check-in/out, charges, payments, edits, cancel), printable invoice, guests, rooms and housekeeping, room types and rates, payments report, staff accounts. Menus and actions follow the user's role.
