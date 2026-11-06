"""FAIRY CROP shop - Flask application.  Run with:  python app.py"""
import base64
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from flask import (Flask, abort, flash, g, jsonify, make_response, redirect, render_template,
                   request, session, url_for, Response)
from werkzeug.security import check_password_hash, generate_password_hash

import common as C
from common import (L, csv, money, tr, wa_link)
from db import DATA_DIR, close_db, get_db, init_db, q, run

app = Flask(__name__)
os.makedirs(DATA_DIR, exist_ok=True)
_key_file = os.path.join(DATA_DIR, "secret.key")
if not os.path.exists(_key_file):
    with open(_key_file, "w") as f:
        f.write(os.urandom(32).hex())
app.secret_key = os.environ.get("FAIRYCROP_SECRET") or open(_key_file).read().strip()
app.config.update(
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FAIRYCROP_HTTPS") == "1",
    SEND_FILE_MAX_AGE_DEFAULT=int(os.environ.get("FAIRYCROP_STATIC_CACHE", "3600")),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)
app.teardown_appcontext(close_db)
init_db()

from admin import admin_bp  # noqa: E402  (needs app objects above to exist)
app.register_blueprint(admin_bp, url_prefix="/admin")

RZP_KEY = os.environ.get("RAZORPAY_KEY_ID", "")
RZP_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RZP_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")


# ------------------------------------------------------------------ context
@app.context_processor
def inject():
    cart = session.get("cart", {})
    user = None
    if session.get("uid"):
        user = q("SELECT id,name,mobile FROM users WHERE id=?", (session["uid"],), one=True)
    return dict(
        S=C.get_settings(), lang=C.cur_lang(), tr=tr, L=L, money=money, tag=C.tag, lines=C.lines, csv=csv,
        wa=wa_link, csrf=C.csrf_token, cart_count=sum(cart.values()) if cart else 0, user=user,
        nav_cats=q("SELECT * FROM categories ORDER BY sort"), disc=C.discount_pct, METHODS=C.METHODS,
        STATUS_LABEL=C.STATUS_LABEL, rzp_ready=bool(RZP_KEY and RZP_SECRET), yt=C.youtube_id,
        site_url=request.url_root.rstrip("/"),
        # True if a real photo was dropped into static/img/ (e.g. hero.jpg) - used to replace illustrations
        has_img=lambda n: os.path.exists(os.path.join(app.static_folder, "img", n)),
    )


@app.before_request
def guard():
    if request.method == "POST" and request.endpoint not in ("razorpay_webhook",):
        C.check_csrf()


@app.after_request
def headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.path.startswith("/admin") or request.path.startswith(("/account", "/checkout", "/cart")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(404)
def nf(_e):
    return render_template("message.html", title=tr("Page not found", "पेज नहीं मिला"),
                           body=tr("Sorry, we could not find that page.", "क्षमा करें, यह पेज नहीं मिला।")), 404


@app.errorhandler(400)
def bad(e):
    return render_template("message.html", title=tr("Something went wrong", "कुछ गड़बड़ हुई"), body=str(getattr(e, "description", e))), 400


@app.errorhandler(413)
def toolarge(_e):
    return render_template("message.html", title="File too large", body="Please upload a smaller file (max 12 MB)."), 413


# ------------------------------------------------------------------ language
@app.route("/lang/<code>")
def set_lang(code):
    resp = make_response(redirect(request.referrer or url_for("home")))
    if code in ("en", "hi"):
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


# ------------------------------------------------------------------ home
@app.route("/")
def home():
    sel = C.PRODUCT_SELECT + " WHERE p.active=1 "
    best = q(sel + "AND p.is_best_seller=1 ORDER BY p.id LIMIT 8")
    featured = q(sel + "AND p.is_featured=1 ORDER BY p.id LIMIT 8")
    farmer = q(sel + "AND p.audience IN ('farmer','both') ORDER BY p.id LIMIT 4")
    gardener = q(sel + "AND p.audience IN ('gardener','both') ORDER BY p.id LIMIT 4")
    reviews = q("SELECT r.*, p.name_en, p.name_hi, p.slug FROM reviews r JOIN products p ON p.id=r.product_id "
                "WHERE r.approved=1 ORDER BY r.id DESC LIMIT 6")
    videos = q("SELECT * FROM videos WHERE active=1 ORDER BY sort LIMIT 4")
    banner = q("SELECT * FROM banners WHERE active=1 ORDER BY sort,id LIMIT 1", one=True)
    return render_template("home.html", best=best, featured=featured, farmer=farmer, gardener=gardener,
                           reviews=reviews, videos=videos, banner=banner, crops=C.CROP_CHOICES, plants=C.PLANT_CHOICES)


# ------------------------------------------------------------------ shop
@app.route("/shop")
def shop():
    a = request.args
    where, args = ["p.active=1"], []
    term = a.get("q", "").strip()
    if term:
        like = f"%{term}%"
        where.append("(p.name_en LIKE ? OR p.name_hi LIKE ? OR p.short_en LIKE ? OR p.desc_en LIKE ? OR p.crops LIKE ? "
                     "OR p.plants LIKE ? OR p.problems LIKE ? OR p.needs LIKE ? OR c.name_en LIKE ? OR c.name_hi LIKE ?)")
        args += [like] * 10
    cat = a.get("category", "")
    if cat:
        where.append("c.slug=?"); args.append(cat)
    for field, col in (("crop", "p.crops"), ("plant", "p.plants"), ("problem", "p.problems"), ("need", "p.needs")):
        if a.get(field):
            where.append(f"(',' || REPLACE({col},', ',',') || ',') LIKE ?"); args.append(f"%,{a[field]},%")
    if a.get("pack"):
        where.append("EXISTS (SELECT 1 FROM variants v WHERE v.product_id=p.id AND v.label=?)"); args.append(a["pack"])
    for key, op in (("min", ">="), ("max", "<=")):
        try:
            val = float(a.get(key, ""))
            where.append(f"(SELECT MIN(price) FROM variants v WHERE v.product_id=p.id) {op} ?"); args.append(val)
        except ValueError:
            pass
    order = {"price_asc": "minprice ASC", "price_desc": "minprice DESC", "new": "p.id DESC"}.get(a.get("sort"), "p.is_best_seller DESC, p.id")
    products = q(C.PRODUCT_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY " + order, args)
    packs = [r[0] for r in q("SELECT DISTINCT label FROM variants ORDER BY label")]
    cat_row = q("SELECT * FROM categories WHERE slug=?", (cat,), one=True) if cat else None
    return render_template("shop.html", products=products, packs=packs, a=a, cat_row=cat_row, crops=C.CROP_CHOICES,
                           plants=C.PLANT_CHOICES, problems=C.all_tags("problems"), needs=C.all_tags("needs"))


@app.route("/product/<slug>")
def product(slug):
    p = q(C.PRODUCT_SELECT + " WHERE p.slug=? AND p.active=1", (slug,), one=True)
    if not p:
        abort(404)
    variants = q("SELECT * FROM variants WHERE product_id=? ORDER BY price", (p["id"],))
    images = q("SELECT * FROM product_images WHERE product_id=? ORDER BY id", (p["id"],))
    reviews = q("SELECT * FROM reviews WHERE product_id=? AND approved=1 ORDER BY id DESC", (p["id"],))
    related = q(C.PRODUCT_SELECT + " WHERE p.active=1 AND p.category_id=? AND p.id<>? LIMIT 4", (p["category_id"], p["id"]))
    return render_template("product.html", p=p, variants=variants, images=images, reviews=reviews, related=related)


@app.route("/product/<slug>/review", methods=["POST"])
def add_review(slug):
    p = q("SELECT id FROM products WHERE slug=?", (slug,), one=True)
    if not p:
        abort(404)
    if not session.get("uid"):
        flash(tr("Please log in to write a review.", "रिव्यू लिखने के लिए कृपया लॉग इन करें।"), "err")
        return redirect(url_for("login", next=url_for("product", slug=slug)))
    try:
        rating = int(request.form.get("rating", 0))
    except ValueError:
        rating = 0
    text = request.form.get("text", "").strip()[:1000]
    if not 1 <= rating <= 5 or len(text) < 3:
        flash(tr("Please give a rating (1-5) and a short review.", "कृपया 1-5 रेटिंग और छोटा रिव्यू दें।"), "err")
        return redirect(url_for("product", slug=slug) + "#reviews")
    if q("SELECT 1 FROM reviews WHERE product_id=? AND user_id=?", (p["id"], session["uid"]), one=True):
        flash(tr("You have already reviewed this product.", "आप इस उत्पाद का रिव्यू पहले ही दे चुके हैं।"), "err")
    else:
        u = q("SELECT name FROM users WHERE id=?", (session["uid"],), one=True)
        run("INSERT INTO reviews(product_id,user_id,name,rating,text) VALUES(?,?,?,?,?)", (p["id"], session["uid"], u["name"], rating, text))
        flash(tr("Thank you! Your review will appear after approval.", "धन्यवाद! आपका रिव्यू स्वीकृति के बाद दिखेगा।"), "ok")
    return redirect(url_for("product", slug=slug) + "#reviews")


# ------------------------------------------------------------------ pincode / shipping
def shipping_for(subtotal):
    s = C.get_settings()
    try:
        flat, free = float(s.get("shipping_flat", 60)), float(s.get("free_shipping_above", 0))
    except ValueError:
        flat, free = 60.0, 0.0
    return 0.0 if (free and subtotal >= free) else flat


def pin_check(pin):
    if not C.valid_pin(pin):
        return False, tr("Please enter a valid 6-digit PIN code.", "कृपया सही 6 अंकों का पिन कोड डालें।")
    blocked = {x.strip() for x in C.get_settings().get("blocked_pincodes", "").replace("\n", ",").split(",") if x.strip()}
    if pin in blocked:
        return False, tr("Sorry, we cannot deliver to this PIN code right now. Please WhatsApp us.", "क्षमा करें, इस पिन कोड पर अभी डिलीवरी नहीं हो सकती। कृपया हमें WhatsApp करें।")
    return True, tr("Delivery is available for this PIN code. Delivery time will be confirmed on order.", "इस पिन कोड पर डिलीवरी उपलब्ध है। डिलीवरी का समय ऑर्डर पर बताया जाएगा।")


@app.route("/api/pincode")
def api_pincode():
    ok, msg = pin_check(request.args.get("pin", "").strip())
    return jsonify(ok=ok, message=msg)


# ------------------------------------------------------------------ cart
def cart_items():
    cart = session.get("cart", {})
    items, subtotal = [], 0.0
    for vid, qty in cart.items():
        r = q("""SELECT v.*, p.name_en, p.name_hi, p.slug, p.is_demo,
                 (SELECT path FROM product_images i WHERE i.product_id=p.id ORDER BY i.id LIMIT 1) AS img
                 FROM variants v JOIN products p ON p.id=v.product_id WHERE v.id=? AND p.active=1""", (int(vid),), one=True)
        if r:
            line = r["price"] * qty
            subtotal += line
            items.append(dict(v=r, qty=qty, line=line))
    return items, subtotal


@app.route("/cart")
def cart():
    items, subtotal = cart_items()
    ship = shipping_for(subtotal) if items else 0
    return render_template("cart.html", items=items, subtotal=subtotal, ship=ship, total=subtotal + ship)


def _add(vid, qty):
    v = q("SELECT v.*, p.active FROM variants v JOIN products p ON p.id=v.product_id WHERE v.id=?", (vid,), one=True)
    if not v or not v["active"]:
        return False
    c = session.get("cart", {})
    new = min(c.get(str(vid), 0) + qty, 50)
    if v["stock"] <= 0:
        flash(tr("Sorry, this pack is out of stock.", "क्षमा करें, यह पैक स्टॉक में नहीं है।"), "err")
        return False
    if new > v["stock"]:
        new = v["stock"]
        flash(tr(f"Only {v['stock']} available in stock.", f"स्टॉक में केवल {v['stock']} उपलब्ध हैं।"), "err")
    c[str(vid)] = new
    session["cart"] = c
    session.permanent = True
    return True


@app.route("/cart/add", methods=["POST"])
def cart_add():
    try:
        vid, qty = int(request.form["variant_id"]), max(1, int(request.form.get("qty", 1)))
    except (KeyError, ValueError):
        abort(400)
    ok = _add(vid, qty)
    if request.form.get("buy_now") == "1":
        return redirect(url_for("checkout") if ok else request.referrer or url_for("shop"))
    if ok:
        flash(tr("Added to your cart.", "कार्ट में जोड़ दिया गया।"), "ok")
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    c = session.get("cart", {})
    for k, v in request.form.items():
        if k.startswith("qty_"):
            vid = k[4:]
            try:
                n = int(v)
            except ValueError:
                continue
            row = q("SELECT stock FROM variants WHERE id=?", (vid,), one=True)
            if n <= 0 or not row:
                c.pop(vid, None)
            else:
                c[vid] = min(n, 50, max(row["stock"], 1))
    session["cart"] = c
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:vid>", methods=["POST"])
def cart_remove(vid):
    c = session.get("cart", {})
    c.pop(str(vid), None)
    session["cart"] = c
    return redirect(url_for("cart"))


# ------------------------------------------------------------------ accounts
def login_required(f):
    from functools import wraps

    @wraps(f)
    def w(*a, **kw):
        if not session.get("uid"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w


def _safe_next(n):
    return n if n and n.startswith("/") and not n.startswith("//") else url_for("home")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, mobile, email, pw = f.get("name", "").strip(), C.clean_mobile(f.get("mobile", "")), f.get("email", "").strip(), f.get("password", "")
        err = None
        if len(name) < 2:
            err = tr("Please enter your name.", "कृपया अपना नाम लिखें।")
        elif not C.valid_mobile(mobile):
            err = tr("Enter a valid 10-digit Indian mobile number.", "सही 10 अंकों का भारतीय मोबाइल नंबर डालें।")
        elif len(pw) < 8:
            err = tr("Password must be at least 8 characters.", "पासवर्ड कम से कम 8 अक्षर का होना चाहिए।")
        elif q("SELECT 1 FROM users WHERE mobile=?", (mobile,), one=True):
            err = tr("This mobile number is already registered. Please log in.", "यह मोबाइल नंबर पहले से पंजीकृत है। कृपया लॉग इन करें।")
        if err:
            flash(err, "err")
            return render_template("register.html", f=f)
        uid = run("INSERT INTO users(name,mobile,email,password_hash) VALUES(?,?,?,?)", (name, mobile, email, generate_password_hash(pw)))
        session.clear(); session["uid"] = uid
        flash(tr("Welcome to FAIRY CROP!", "FAIRY CROP में आपका स्वागत है!"), "ok")
        return redirect(_safe_next(request.args.get("next")))
    return render_template("register.html", f={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        mobile, pw = C.clean_mobile(request.form.get("mobile", "")), request.form.get("password", "")
        key = "login:" + (request.remote_addr or "")
        if C.too_many(key):
            flash(tr("Too many attempts. Please wait 10 minutes.", "बहुत ज़्यादा कोशिशें। कृपया 10 मिनट रुकें।"), "err")
            return render_template("login.html")
        u = q("SELECT * FROM users WHERE mobile=?", (mobile,), one=True)
        if u and check_password_hash(u["password_hash"], pw):
            cart = session.get("cart", {})
            session.clear(); session["uid"] = u["id"]; session["cart"] = cart
            return redirect(_safe_next(request.args.get("next")))
        C.note_hit(key)
        flash(tr("Wrong mobile number or password.", "मोबाइल नंबर या पासवर्ड गलत है।"), "err")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("uid", None)
    return redirect(url_for("home"))


@app.route("/account")
@login_required
def account():
    orders = q("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (session["uid"],))
    return render_template("account.html", orders=orders)


@app.route("/account/orders/<order_no>")
@login_required
def my_order(order_no):
    o = q("SELECT * FROM orders WHERE order_no=? AND user_id=?", (order_no, session["uid"]), one=True)
    if not o:
        abort(404)
    return render_template("order.html", o=o, items=q("SELECT * FROM order_items WHERE order_id=?", (o["id"],)), steps=C.ORDER_STATUSES[1:5])


@app.route("/track", methods=["GET", "POST"])
def track():
    o = items = None
    if request.method == "POST":
        no, mob = request.form.get("order_no", "").strip().upper(), C.clean_mobile(request.form.get("mobile", ""))
        o = q("SELECT * FROM orders WHERE order_no=? AND mobile=?", (no, mob), one=True)
        if o:
            items = q("SELECT * FROM order_items WHERE order_id=?", (o["id"],))
        else:
            flash(tr("No order found for these details.", "इन विवरणों से कोई ऑर्डर नहीं मिला।"), "err")
    return render_template("track.html", o=o, items=items, steps=C.ORDER_STATUSES[1:5])


# ------------------------------------------------------------------ checkout & payment
def _new_order_no():
    import secrets
    while True:
        no = "FC" + secrets.token_hex(3).upper()
        if not q("SELECT 1 FROM orders WHERE order_no=?", (no,), one=True):
            return no


def _take_stock(order_id):
    o = q("SELECT stock_taken FROM orders WHERE id=?", (order_id,), one=True)
    if o and not o["stock_taken"]:
        for it in q("SELECT variant_id, qty FROM order_items WHERE order_id=?", (order_id,)):
            run("UPDATE variants SET stock=MAX(stock-?,0) WHERE id=?", (it["qty"], it["variant_id"]))
        run("UPDATE orders SET stock_taken=1 WHERE id=?", (order_id,))


@app.route("/checkout", methods=["GET"])
@login_required
def checkout():
    items, subtotal = cart_items()
    if not items:
        flash(tr("Your cart is empty.", "आपका कार्ट खाली है।"), "err")
        return redirect(url_for("shop"))
    ship = shipping_for(subtotal)
    u = q("SELECT * FROM users WHERE id=?", (session["uid"],), one=True)
    last = q("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 1", (session["uid"],), one=True)
    return render_template("checkout.html", items=items, subtotal=subtotal, ship=ship, total=subtotal + ship, u=u, last=last,
                           cod=C.get_settings().get("cod_enabled") == "1")


@app.route("/checkout/place", methods=["POST"])
@login_required
def place_order():
    items, subtotal = cart_items()
    if not items:
        return redirect(url_for("cart"))
    f = request.form
    name, mobile = f.get("name", "").strip(), C.clean_mobile(f.get("mobile", ""))
    address, city, state, pin = f.get("address", "").strip(), f.get("city", "").strip(), f.get("state", "").strip(), f.get("pincode", "").strip()
    method = f.get("payment", "online")
    err = None
    ok, pmsg = pin_check(pin)
    if len(name) < 2 or len(address) < 8 or len(city) < 2 or len(state) < 2:
        err = tr("Please fill your name and full delivery address.", "कृपया अपना नाम और पूरा पता भरें।")
    elif not C.valid_mobile(mobile):
        err = tr("Enter a valid 10-digit mobile number.", "सही 10 अंकों का मोबाइल नंबर डालें।")
    elif not ok:
        err = pmsg
    elif method == "cod" and C.get_settings().get("cod_enabled") != "1":
        err = tr("Cash on Delivery is not available.", "कैश ऑन डिलीवरी उपलब्ध नहीं है।")
    elif method == "online" and not (RZP_KEY and RZP_SECRET):
        err = tr("Online payment is not set up yet. Please contact us on WhatsApp to order.", "ऑनलाइन भुगतान अभी चालू नहीं है। ऑर्डर के लिए कृपया WhatsApp करें।")
    for it in items:
        if it["v"]["stock"] < it["qty"]:
            err = tr(f"Not enough stock for {it['v']['name_en']} ({it['v']['label']}). Please reduce the quantity.",
                     f"{it['v']['name_hi'] or it['v']['name_en']} ({it['v']['label']}) का स्टॉक कम है। कृपया मात्रा घटाएँ।")
    if err:
        flash(err, "err")
        return redirect(url_for("checkout"))
    ship = shipping_for(subtotal)
    no = _new_order_no()
    email = (q("SELECT email FROM users WHERE id=?", (session["uid"],), one=True) or {"email": ""})["email"]
    oid = run("""INSERT INTO orders(order_no,user_id,name,mobile,email,address,city,state,pincode,subtotal,shipping,total,payment_method)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (no, session["uid"], name, mobile, email, address, city, state, pin, subtotal, ship, subtotal + ship, method))
    for it in items:
        v = it["v"]
        run("INSERT INTO order_items(order_id,variant_id,product_id,product_name,pack_label,price,qty) VALUES(?,?,?,?,?,?,?)",
            (oid, v["id"], v["product_id"], v["name_en"], v["label"], v["price"], it["qty"]))
    if method == "cod":
        run("UPDATE orders SET status='confirmed', payment_status='cod' WHERE id=?", (oid,))
        _take_stock(oid)
        session["cart"] = {}
        return redirect(url_for("order_done", order_no=no))
    return redirect(url_for("pay_order", order_no=no))


def rzp_create_order(order):
    body = json.dumps({"amount": int(round(order["total"] * 100)), "currency": "INR", "receipt": order["order_no"]}).encode()
    auth = base64.b64encode(f"{RZP_KEY}:{RZP_SECRET}".encode()).decode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


@app.route("/order/<order_no>/pay")
@login_required
def pay_order(order_no):
    o = q("SELECT * FROM orders WHERE order_no=? AND user_id=?", (order_no, session["uid"]), one=True)
    if not o:
        abort(404)
    if o["payment_status"] == "paid":
        return redirect(url_for("order_done", order_no=order_no))
    if o["payment_method"] != "online" or o["status"] == "cancelled":
        abort(404)
    if not (RZP_KEY and RZP_SECRET):
        flash(tr("Online payment is not set up yet.", "ऑनलाइन भुगतान अभी चालू नहीं है।"), "err")
        return redirect(url_for("account"))
    try:
        rz = rzp_create_order(o)
        run("UPDATE orders SET rzp_order_id=? WHERE id=?", (rz["id"], o["id"]))
    except (urllib.error.URLError, KeyError, ValueError) as e:
        app.logger.error("Razorpay order creation failed: %s", e)
        flash(tr("Could not start the payment. Please try again in a minute.", "भुगतान शुरू नहीं हो सका। कृपया एक मिनट बाद फिर कोशिश करें।"), "err")
        return redirect(url_for("my_order", order_no=order_no))
    return render_template("pay.html", o=o, rz_id=rz["id"], rz_key=RZP_KEY, amount=int(round(o["total"] * 100)))


def _mark_paid(order, payment_id):
    run("UPDATE orders SET payment_status='paid', status=CASE WHEN status='pending' THEN 'confirmed' ELSE status END, rzp_payment_id=? WHERE id=?",
        (payment_id, order["id"]))
    _take_stock(order["id"])


@app.route("/payment/verify", methods=["POST"])
@login_required
def payment_verify():
    f = request.form
    o = q("SELECT * FROM orders WHERE order_no=? AND user_id=?", (f.get("order_no", ""), session["uid"]), one=True)
    if not o or not o["rzp_order_id"] or not RZP_SECRET:
        abort(400)
    oid, pid, sig = f.get("razorpay_order_id", ""), f.get("razorpay_payment_id", ""), f.get("razorpay_signature", "")
    expected = hmac.new(RZP_SECRET.encode(), f"{o['rzp_order_id']}|{pid}".encode(), hashlib.sha256).hexdigest()
    if oid != o["rzp_order_id"] or not hmac.compare_digest(expected, sig):
        run("UPDATE orders SET payment_status='failed' WHERE id=?", (o["id"],))
        flash(tr("Payment could not be verified. If money was deducted, please WhatsApp us with your order number.",
                 "भुगतान सत्यापित नहीं हो सका। अगर पैसे कटे हैं तो कृपया ऑर्डर नंबर के साथ हमें WhatsApp करें।"), "err")
        return redirect(url_for("my_order", order_no=o["order_no"]))
    _mark_paid(o, pid)
    session["cart"] = {}
    return redirect(url_for("order_done", order_no=o["order_no"]))


@app.route("/payment/webhook", methods=["POST"])
def razorpay_webhook():
    """Optional safety net: Razorpay tells us a payment was captured even if the customer closed the browser."""
    if not RZP_WEBHOOK_SECRET:
        abort(404)
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    if not hmac.compare_digest(hmac.new(RZP_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest(), sig):
        abort(400)
    ev = json.loads(raw)
    if ev.get("event") in ("payment.captured", "order.paid"):
        pay = ev.get("payload", {}).get("payment", {}).get("entity", {})
        o = q("SELECT * FROM orders WHERE rzp_order_id=?", (pay.get("order_id", ""),), one=True)
        if o and o["payment_status"] != "paid":
            _mark_paid(o, pay.get("id", ""))
    return "ok"


@app.route("/order/<order_no>/done")
@login_required
def order_done(order_no):
    o = q("SELECT * FROM orders WHERE order_no=? AND user_id=?", (order_no, session["uid"]), one=True)
    if not o:
        abort(404)
    return render_template("order_done.html", o=o, items=q("SELECT * FROM order_items WHERE order_id=?", (o["id"],)))


# ------------------------------------------------------------------ enquiries / newsletter
def _spam(f):
    return bool(f.get("website"))  # hidden honeypot field


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        f = request.form
        mobile = C.clean_mobile(f.get("mobile", ""))
        if _spam(f):
            return redirect(url_for("contact"))
        if len(f.get("name", "").strip()) < 2 or not C.valid_mobile(mobile) or len(f.get("message", "").strip()) < 3:
            flash(tr("Please enter your name, a valid mobile number and your message.", "कृपया अपना नाम, सही मोबाइल नंबर और संदेश लिखें।"), "err")
            return render_template("contact.html", f=f)
        run("INSERT INTO enquiries(kind,name,mobile,message) VALUES('contact',?,?,?)", (f["name"].strip()[:100], mobile, f["message"].strip()[:2000]))
        flash(tr("Thank you! We will contact you soon.", "धन्यवाद! हम जल्द आपसे संपर्क करेंगे।"), "ok")
        return redirect(url_for("contact"))
    return render_template("contact.html", f={})


@app.route("/bulk", methods=["GET", "POST"])
def bulk():
    if request.method == "POST":
        f = request.form
        mobile = C.clean_mobile(f.get("mobile", ""))
        if _spam(f):
            return redirect(url_for("bulk"))
        if len(f.get("name", "").strip()) < 2 or not C.valid_mobile(mobile) or len(f.get("products", "").strip()) < 2:
            flash(tr("Please enter your name, a valid mobile number and the products you need.", "कृपया अपना नाम, सही मोबाइल नंबर और ज़रूरी उत्पाद लिखें।"), "err")
            return render_template("bulk.html", f=f)
        run("INSERT INTO enquiries(kind,name,mobile,business,location,products,quantity) VALUES('bulk',?,?,?,?,?,?)",
            (f["name"].strip()[:100], mobile, f.get("business", "")[:150], f.get("location", "")[:150], f["products"].strip()[:1000], f.get("quantity", "")[:200]))
        flash(tr("Thank you! Our team will contact you about your bulk enquiry.", "धन्यवाद! हमारी टीम आपकी थोक पूछताछ पर संपर्क करेगी।"), "ok")
        return redirect(url_for("bulk"))
    return render_template("bulk.html", f={})


@app.route("/newsletter", methods=["POST"])
def newsletter():
    em = request.form.get("email", "").strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em) and not _spam(request.form):
        try:
            run("INSERT INTO newsletter(email) VALUES(?)", (em,))
        except Exception:
            pass
        flash(tr("Subscribed. Thank you!", "सदस्यता ली गई। धन्यवाद!"), "ok")
    else:
        flash(tr("Please enter a valid email address.", "कृपया सही ईमेल पता डालें।"), "err")
    return redirect((request.referrer or url_for("home")) + "#newsletter")


# ------------------------------------------------------------------ content pages
@app.route("/learn")
def learn():
    vids = q("SELECT * FROM videos WHERE active=1 ORDER BY sort,id")
    return render_template("learn.html", videos=vids)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/policies")
def policies():
    return render_template("policies.html")


@app.route("/robots.txt")
def robots():
    return Response(f"User-agent: *\nDisallow: /admin\nDisallow: /cart\nDisallow: /checkout\nDisallow: /account\nSitemap: {request.url_root}sitemap.xml\n", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    base = request.url_root.rstrip("/")
    urls = [base + p for p in ("/", "/shop", "/learn", "/about", "/contact", "/bulk", "/policies")]
    urls += [f"{base}/product/{r['slug']}" for r in q("SELECT slug FROM products WHERE active=1")]
    urls += [f"{base}/shop?category={r['slug']}" for r in q("SELECT slug FROM categories")]
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + \
          "".join(f"<url><loc>{u.replace('&', '&amp;')}</loc></url>" for u in urls) + "</urlset>"
    return Response(xml, mimetype="application/xml")


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FAIRYCROP_DEBUG") == "1")
