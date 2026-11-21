import os
import secrets
from datetime import date, timedelta
from functools import wraps
from itertools import groupby
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000").rstrip("/")
CURRENCY = os.getenv("CURRENCY_SYMBOL", "$")
HOTEL_NAME = os.getenv("HOTEL_NAME", "My Hotel")
PER_PAGE = 25

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "")
if len(app.secret_key) < 16:
    raise RuntimeError("SECRET_KEY is missing or too short. Set a random value of 32+ characters in .env")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)


# ------------------------------------------------------------------ API client
class ApiFailure(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def api(method, path, params=None, json=None):
    headers = {"Authorization": f"Bearer {session['token']}"} if session.get("token") else {}
    try:
        r = requests.request(method, BACKEND_URL + path, params=params, json=json, headers=headers, timeout=20)
    except requests.RequestException:
        raise ApiFailure("Cannot reach the hotel server. Check your connection and try again.", 503)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        if r.status_code == 401 and path != "/api/auth/login":
            session.clear()
        raise ApiFailure(data.get("error") or "The request failed", r.status_code)
    return data


# ------------------------------------------------------------------ helpers
def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("user"):
                return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
            if roles and session["user"]["role"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def home_for(role):
    return url_for("rooms") if role == "housekeeping" else url_for("dashboard")


def page_info():
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    return page, {"limit": PER_PAGE, "offset": (page - 1) * PER_PAGE}


def clean(form, *keys):
    return {k: (form.get(k) or "").strip() for k in keys}


@app.before_request
def csrf_protect():
    session.permanent = True
    session.setdefault("csrf", secrets.token_hex(16))
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not secrets.compare_digest(token, session["csrf"]):
            abort(400, "Your form expired. Go back, refresh the page and try again.")


@app.context_processor
def inject():
    return {"csrf_token": session.get("csrf", ""), "hotel_name": HOTEL_NAME, "me": session.get("user"),
            "today": date.today().isoformat(), "tomorrow": (date.today() + timedelta(days=1)).isoformat()}


@app.template_global()
def qs(**overrides):
    args = request.args.to_dict()
    args.update(overrides)
    return urlencode({k: v for k, v in args.items() if v not in (None, "")})


@app.template_filter("money")
def money(v):
    v = float(v or 0)
    return f"-{CURRENCY}{abs(v):,.2f}" if v < 0 else f"{CURRENCY}{v:,.2f}"


@app.template_filter("label")
def label(v):
    return (v or "").replace("_", " ").capitalize()


@app.errorhandler(ApiFailure)
def api_failure(e):
    if e.status == 401:
        flash(e.message, "error")
        return redirect(url_for("login"))
    if request.method == "POST":
        flash(e.message, "error")
        return redirect(request.referrer or url_for("login"))
    return render_template("error.html", status=e.status, message=e.message), e.status


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", status=403, message="Your role does not have access to this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", status=404, message="That page does not exist."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", status=400, message=getattr(e, "description", "Bad request")), 400


# ------------------------------------------------------------------ auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(home_for(session["user"]["role"]))
    if request.method == "POST":
        try:
            data = api("POST", "/api/auth/login", json=clean(request.form, "email") | {"password": request.form.get("password", "")})
        except ApiFailure as e:
            flash(e.message, "error")
            return render_template("login.html", email=request.form.get("email", "")), 401
        csrf = session["csrf"]
        session.clear()
        session.update(token=data["token"], user=data["user"], csrf=csrf)
        nxt = request.args.get("next") or ""
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = home_for(data["user"]["role"])
        return redirect(nxt)
    return render_template("login.html", email="")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
@login_required()
def account():
    if request.method == "POST":
        f = request.form
        if f.get("new_password") != f.get("confirm_password"):
            flash("The new passwords do not match.", "error")
        else:
            api("POST", "/api/auth/change-password",
                json={"current_password": f.get("current_password", ""), "new_password": f.get("new_password", "")})
            flash("Password changed.", "success")
        return redirect(url_for("account"))
    return render_template("account.html")


# ------------------------------------------------------------------ dashboard
@app.get("/")
@login_required("admin", "receptionist")
def dashboard():
    stats = api("GET", "/api/dashboard")
    rooms = api("GET", "/api/rooms")["items"]
    floors = [(fl, list(rs)) for fl, rs in groupby(rooms, key=lambda r: r["floor"])]
    return render_template("dashboard.html", s=stats, floors=floors)


# ------------------------------------------------------------------ rooms
@app.get("/rooms")
@login_required()
def rooms():
    params = {k: request.args[k] for k in ("q", "type_id", "housekeeping", "occupancy") if request.args.get(k)}
    return render_template("rooms.html", rooms=api("GET", "/api/rooms", params)["items"],
                           types=api("GET", "/api/room-types")["items"], f=request.args)


@app.post("/rooms/save")
@login_required("admin")
def room_save():
    f = request.form
    payload = clean(f, "room_number", "floor", "room_type_id", "notes")
    if f.get("id"):
        api("PUT", f"/api/rooms/{int(f['id'])}", json=payload)
    else:
        api("POST", "/api/rooms", json=payload)
    flash("Room saved.", "success")
    return redirect(url_for("rooms"))


@app.post("/rooms/<int:rid>/delete")
@login_required("admin")
def room_delete(rid):
    flash(api("DELETE", f"/api/rooms/{rid}")["message"], "success")
    return redirect(url_for("rooms"))


@app.post("/rooms/<int:rid>/housekeeping")
@login_required()
def room_housekeeping(rid):
    api("PATCH", f"/api/rooms/{rid}/housekeeping", json={"status": request.form.get("status")})
    flash("Room status updated.", "success")
    return redirect(request.referrer or url_for("rooms"))


@app.post("/room-types/save")
@login_required("admin")
def type_save():
    f = request.form
    payload = clean(f, "name", "description", "base_price", "capacity")
    if f.get("id"):
        api("PUT", f"/api/room-types/{int(f['id'])}", json=payload)
    else:
        api("POST", "/api/room-types", json=payload)
    flash("Room type saved.", "success")
    return redirect(url_for("rooms") + "#types")


@app.post("/room-types/<int:tid>/delete")
@login_required("admin")
def type_delete(tid):
    api("DELETE", f"/api/room-types/{tid}")
    flash("Room type deleted.", "success")
    return redirect(url_for("rooms") + "#types")


# ------------------------------------------------------------------ guests
@app.get("/guests")
@login_required("admin", "receptionist")
def guests():
    page, pg = page_info()
    q = request.args.get("q", "").strip()
    data = api("GET", "/api/guests", {"q": q, **pg})
    return render_template("guests.html", guests=data["items"], total=data["total"], page=page, per=PER_PAGE, q=q)


@app.get("/guests/search")
@login_required("admin", "receptionist")
def guest_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    items = api("GET", "/api/guests", {"q": q, "limit": 8})["items"]
    return jsonify([{"id": g["id"], "name": f"{g['first_name']} {g['last_name']}",
                     "detail": " · ".join(x for x in (g["phone"], g["email"]) if x)} for g in items])


GUEST_FIELDS = ("first_name", "last_name", "email", "phone", "id_type", "id_number", "address", "notes")


@app.route("/guests/new", methods=["GET", "POST"])
@login_required("admin", "receptionist")
def guest_new():
    if request.method == "POST":
        try:
            gid = api("POST", "/api/guests", json=clean(request.form, *GUEST_FIELDS))["id"]
        except ApiFailure as e:
            flash(e.message, "error")
            return render_template("guest_form.html", g=request.form, editing=False), 400
        flash("Guest added.", "success")
        return redirect(url_for("guest_detail", gid=gid))
    return render_template("guest_form.html", g={}, editing=False)


@app.get("/guests/<int:gid>")
@login_required("admin", "receptionist")
def guest_detail(gid):
    return render_template("guest_detail.html", g=api("GET", f"/api/guests/{gid}"))


@app.route("/guests/<int:gid>/edit", methods=["GET", "POST"])
@login_required("admin", "receptionist")
def guest_edit(gid):
    if request.method == "POST":
        try:
            api("PUT", f"/api/guests/{gid}", json=clean(request.form, *GUEST_FIELDS))
        except ApiFailure as e:
            flash(e.message, "error")
            return render_template("guest_form.html", g=request.form, editing=True, gid=gid), 400
        flash("Guest updated.", "success")
        return redirect(url_for("guest_detail", gid=gid))
    return render_template("guest_form.html", g=api("GET", f"/api/guests/{gid}"), editing=True, gid=gid)


# ------------------------------------------------------------------ bookings
@app.get("/bookings")
@login_required("admin", "receptionist")
def bookings():
    page, pg = page_info()
    params = {k: request.args[k] for k in ("q", "status", "view", "from", "to") if request.args.get(k)}
    data = api("GET", "/api/bookings", {**params, **pg})
    return render_template("bookings.html", bookings=data["items"], total=data["total"], page=page,
                           per=PER_PAGE, f=request.args)


def _available(src):
    if not (src.get("check_in") and src.get("check_out")):
        return None
    try:
        return api("GET", "/api/rooms/available", {k: src.get(k) for k in ("check_in", "check_out", "adults", "children")
                                                  if src.get(k)})["items"]
    except ApiFailure as e:
        flash(e.message, "error")
        return None


@app.route("/bookings/new", methods=["GET", "POST"])
@login_required("admin", "receptionist")
def booking_new():
    guest = None
    src = request.form if request.method == "POST" else request.args
    if request.method == "POST":
        f = request.form
        payload = clean(f, "room_id", "check_in", "check_out", "adults", "children", "notes")
        if f.get("rate_per_night", "").strip() and session["user"]["role"] == "admin":
            payload["rate_per_night"] = f["rate_per_night"].strip()
        if f.get("guest_id"):
            payload["guest_id"] = f["guest_id"]
        else:
            payload["guest"] = clean(f, *(("g_" + k) for k in GUEST_FIELDS[:-1]))
            payload["guest"] = {k[2:]: v for k, v in payload["guest"].items()}
        try:
            bid = api("POST", "/api/bookings", json=payload)["id"]
            flash("Booking created.", "success")
            return redirect(url_for("booking_detail", bid=bid))
        except ApiFailure as e:
            flash(e.message, "error")
    gid = src.get("guest_id")
    if gid:
        try:
            guest = api("GET", f"/api/guests/{int(gid)}")
        except (ApiFailure, ValueError):
            guest = None
    return render_template("booking_new.html", f=src, rooms=_available(src), guest=guest)


@app.get("/bookings/<int:bid>")
@login_required("admin", "receptionist")
def booking_detail(bid):
    return render_template("booking_detail.html", b=api("GET", f"/api/bookings/{bid}"))


@app.get("/bookings/<int:bid>/invoice")
@login_required("admin", "receptionist")
def booking_invoice(bid):
    return render_template("invoice.html", b=api("GET", f"/api/bookings/{bid}/invoice"))


@app.post("/bookings/<int:bid>/<action>")
@login_required("admin", "receptionist")
def booking_action(bid, action):
    f = request.form
    back = url_for("booking_detail", bid=bid)
    if action == "check-in":
        api("POST", f"/api/bookings/{bid}/check-in", json={"force": f.get("force") == "1"})
        flash("Guest checked in.", "success")
    elif action == "check-out":
        api("POST", f"/api/bookings/{bid}/check-out", json={"force": f.get("force") == "1"})
        flash("Guest checked out. The room is now marked dirty for housekeeping.", "success")
    elif action == "cancel":
        api("POST", f"/api/bookings/{bid}/cancel", json=clean(f, "reason"))
        flash("Booking cancelled.", "success")
    elif action == "charges":
        api("POST", f"/api/bookings/{bid}/charges", json=clean(f, "description", "quantity", "unit_price"))
        flash("Charge added.", "success")
    elif action == "payments":
        api("POST", f"/api/bookings/{bid}/payments", json=clean(f, "amount", "method", "reference"))
        flash("Payment recorded.", "success")
    elif action == "update":
        payload = {k: v for k, v in clean(f, "check_in", "check_out", "adults", "children", "rate_per_night").items() if v}
        payload["notes"] = f.get("notes", "")
        api("PUT", f"/api/bookings/{bid}", json=payload)
        flash("Booking updated.", "success")
    else:
        abort(404)
    return redirect(back)


@app.post("/bookings/<int:bid>/charges/<int:cid>/delete")
@login_required("admin", "receptionist")
def charge_delete(bid, cid):
    api("DELETE", f"/api/bookings/{bid}/charges/{cid}")
    flash("Charge removed.", "success")
    return redirect(url_for("booking_detail", bid=bid))


# ------------------------------------------------------------------ reports & users
@app.get("/reports")
@login_required("admin")
def reports():
    params = {k: request.args[k] for k in ("from", "to") if request.args.get(k)}
    data = api("GET", "/api/reports/revenue", params)
    return render_template("reports.html", r=data, peak=max([d["total"] for d in data["daily"]] + [1]))


@app.get("/users")
@login_required("admin")
def users():
    return render_template("users.html", users=api("GET", "/api/users")["items"])


@app.post("/users/save")
@login_required("admin")
def user_save():
    f = request.form
    payload = clean(f, "name", "email", "role")
    if f.get("password"):
        payload["password"] = f["password"]
    if f.get("id"):
        payload["is_active"] = f.get("is_active") == "1"
        payload.pop("email")
        api("PUT", f"/api/users/{int(f['id'])}", json=payload)
    else:
        api("POST", "/api/users", json=payload)
    flash("User saved.", "success")
    return redirect(url_for("users"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
