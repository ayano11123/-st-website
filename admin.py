"""Admin dashboard for the business owner. Everything here needs the admin login."""
import csv as csvmod
import io
import re
from functools import wraps

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import common as C
from db import get_db, q, run

admin_bp = Blueprint("admin", __name__)

PRODUCT_TEXT_FIELDS = [
    "name_en", "name_hi", "short_en", "short_hi", "desc_en", "desc_hi", "benefits_en", "benefits_hi",
    "problem_en", "problem_hi", "why_en", "why_hi", "helps_en", "helps_hi",
    "when_en", "when_hi", "prepare_en", "prepare_hi", "apply_en", "apply_hi",
    "dosage_en", "dosage_hi", "precautions_en", "precautions_hi", "storage_en", "storage_hi",
    "composition", "batch_info", "expiry_info", "manufacturer", "marketer", "regulatory",
    "crops", "plants", "problems", "needs", "method", "audience",
]


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return f(*a, **kw)
    return w


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "product"


def num(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return default


# ---------------------------------------------------------------- auth
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        key = "admin:" + (request.remote_addr or "")
        if C.too_many(key, limit=6, window=900):
            flash("Too many attempts. Wait 15 minutes.", "err")
            return render_template("admin/login.html")
        a = q("SELECT * FROM admins WHERE username=?", (request.form.get("username", "").strip(),), one=True)
        if a and check_password_hash(a["password_hash"], request.form.get("password", "")):
            session.clear()
            session["admin"] = a["id"]
            return redirect(url_for("admin.dashboard"))
        C.note_hit(key)
        flash("Wrong username or password.", "err")
    return render_template("admin/login.html")


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------- dashboard
@admin_bp.route("/")
@admin_required
def dashboard():
    stats = {
        "orders_new": q("SELECT COUNT(*) FROM orders WHERE status IN ('confirmed','pending')")[0][0],
        "orders_total": q("SELECT COUNT(*) FROM orders")[0][0],
        "revenue": q("SELECT COALESCE(SUM(total),0) FROM orders WHERE payment_status='paid' OR payment_method='cod' AND status='delivered'")[0][0],
        "enq_new": q("SELECT COUNT(*) FROM enquiries WHERE status='new'")[0][0],
        "rev_pending": q("SELECT COUNT(*) FROM reviews WHERE approved=0")[0][0],
        "products": q("SELECT COUNT(*) FROM products")[0][0],
        "low_stock": q("SELECT COUNT(*) FROM variants v JOIN products p ON p.id=v.product_id WHERE v.stock<=5 AND p.active=1")[0][0],
        "demo": q("SELECT COUNT(*) FROM products WHERE is_demo=1")[0][0],
    }
    recent = q("SELECT * FROM orders ORDER BY id DESC LIMIT 8")
    return render_template("admin/dashboard.html", s=stats, recent=recent)


# ---------------------------------------------------------------- products
@admin_bp.route("/products")
@admin_required
def products():
    rows = q("""SELECT p.*, c.name_en AS cat,
                (SELECT COUNT(*) FROM variants v WHERE v.product_id=p.id) AS nvar,
                (SELECT COALESCE(SUM(stock),0) FROM variants v WHERE v.product_id=p.id) AS stock,
                (SELECT MIN(price) FROM variants v WHERE v.product_id=p.id) AS minprice
                FROM products p JOIN categories c ON c.id=p.category_id ORDER BY p.id DESC""")
    return render_template("admin/products.html", rows=rows)


def _save_product(pid=None):
    f = request.form
    vals = {k: f.get(k, "").strip() for k in PRODUCT_TEXT_FIELDS}
    flags = {k: 1 if f.get(k) else 0 for k in ("is_demo", "is_best_seller", "is_featured", "active")}
    cat = int(f.get("category_id", 0) or 0)
    if not vals["name_en"] or not q("SELECT 1 FROM categories WHERE id=?", (cat,), one=True):
        flash("Product name (English) and category are required.", "err")
        return None
    db = get_db()
    if pid is None:
        base = slug = slugify(vals["name_en"])
        n = 2
        while q("SELECT 1 FROM products WHERE slug=?", (slug,), one=True):
            slug, n = f"{base}-{n}", n + 1
        cols = list(vals) + list(flags) + ["slug", "category_id"]
        params = list(vals.values()) + list(flags.values()) + [slug, cat]
        cur = db.execute(f"INSERT INTO products({','.join(cols)}) VALUES({','.join('?' * len(cols))})", params)
        pid = cur.lastrowid
    else:
        sets = ",".join(f"{k}=?" for k in list(vals) + list(flags) + ["category_id"])
        db.execute(f"UPDATE products SET {sets} WHERE id=?", list(vals.values()) + list(flags.values()) + [cat, pid])
    # variants (pack sizes / price / discount via MRP / stock)
    ids = f.getlist("v_id")
    keep = []
    for i, (label, price, mrp, stock) in enumerate(zip(f.getlist("v_label"), f.getlist("v_price"), f.getlist("v_mrp"), f.getlist("v_stock"))):
        label = label.strip()
        if not label:
            continue
        price_v = num(price)
        mrp_v = num(mrp) or price_v
        stock_v = int(num(stock))
        vid = ids[i] if i < len(ids) else ""
        if vid and vid.isdigit() and q("SELECT 1 FROM variants WHERE id=? AND product_id=?", (vid, pid), one=True):
            db.execute("UPDATE variants SET label=?,price=?,mrp=?,stock=? WHERE id=?", (label, price_v, mrp_v, stock_v, vid))
            keep.append(int(vid))
        else:
            cur = db.execute("INSERT INTO variants(product_id,label,price,mrp,stock) VALUES(?,?,?,?,?)", (pid, label, price_v, mrp_v, stock_v))
            keep.append(cur.lastrowid)
    if keep:
        db.execute(f"DELETE FROM variants WHERE product_id=? AND id NOT IN ({','.join('?' * len(keep))})", [pid] + keep)
    # images
    for iid in f.getlist("del_img"):
        if iid.isdigit():
            db.execute("DELETE FROM product_images WHERE id=? AND product_id=?", (iid, pid))
    for file in request.files.getlist("images"):
        path = C.save_image(file)
        if path:
            db.execute("INSERT INTO product_images(product_id,path) VALUES(?,?)", (pid, path))
        elif file and file.filename:
            flash(f"'{file.filename}' was not a valid JPG/PNG/WEBP image and was skipped.", "err")
    db.commit()
    return pid


@admin_bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    if request.method == "POST":
        pid = _save_product()
        if pid:
            flash("Product added.", "ok")
            return redirect(url_for("admin.products"))
    blank = {k: "" for k in PRODUCT_TEXT_FIELDS}
    blank.update(is_demo=0, is_best_seller=0, is_featured=0, active=1, id=None, audience="both", method="")
    return render_template("admin/product_form.html", p=blank, variants=[], images=[], cats=q("SELECT * FROM categories ORDER BY sort"), cat_id=0)


@admin_bp.route("/products/<int:pid>", methods=["GET", "POST"])
@admin_required
def product_edit(pid):
    p = q("SELECT * FROM products WHERE id=?", (pid,), one=True)
    if not p:
        abort(404)
    if request.method == "POST":
        if _save_product(pid):
            flash("Product saved.", "ok")
            return redirect(url_for("admin.product_edit", pid=pid))
        p = q("SELECT * FROM products WHERE id=?", (pid,), one=True)
    return render_template("admin/product_form.html", p=p, variants=q("SELECT * FROM variants WHERE product_id=?", (pid,)),
                           images=q("SELECT * FROM product_images WHERE product_id=?", (pid,)),
                           cats=q("SELECT * FROM categories ORDER BY sort"), cat_id=p["category_id"])


@admin_bp.route("/products/<int:pid>/delete", methods=["POST"])
@admin_required
def product_delete(pid):
    run("DELETE FROM variants WHERE product_id=?", (pid,))
    run("DELETE FROM product_images WHERE product_id=?", (pid,))
    run("DELETE FROM reviews WHERE product_id=?", (pid,))
    run("DELETE FROM products WHERE id=?", (pid,))
    flash("Product deleted. (Past orders keep their own copy of the product name and price.)", "ok")
    return redirect(url_for("admin.products"))


@admin_bp.route("/products/<int:pid>/toggle", methods=["POST"])
@admin_required
def product_toggle(pid):
    run("UPDATE products SET active=1-active WHERE id=?", (pid,))
    return redirect(url_for("admin.products"))


# ---------------------------------------------------------------- categories
@admin_bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories():
    if request.method == "POST":
        f = request.form
        act = f.get("action")
        if act == "add" and f.get("name_en", "").strip():
            slug = slugify(f["name_en"])
            if q("SELECT 1 FROM categories WHERE slug=?", (slug,), one=True):
                flash("A category with this name already exists.", "err")
            else:
                run("INSERT INTO categories(slug,name_en,name_hi,icon,sort) VALUES(?,?,?,?,?)",
                    (slug, f["name_en"].strip(), f.get("name_hi", "").strip(), f.get("icon", "🌿").strip() or "🌿", int(num(f.get("sort"), 99))))
                flash("Category added.", "ok")
        elif act == "save":
            cid = int(f.get("id", 0))
            run("UPDATE categories SET name_en=?,name_hi=?,icon=?,sort=?,note_en=?,note_hi=? WHERE id=?",
                (f.get("name_en", "").strip(), f.get("name_hi", "").strip(), f.get("icon", "").strip(), int(num(f.get("sort"))),
                 f.get("note_en", "").strip(), f.get("note_hi", "").strip(), cid))
            flash("Category saved.", "ok")
        elif act == "delete":
            cid = int(f.get("id", 0))
            if q("SELECT 1 FROM products WHERE category_id=?", (cid,), one=True):
                flash("Move or delete the products in this category first.", "err")
            else:
                run("DELETE FROM categories WHERE id=?", (cid,))
                flash("Category deleted.", "ok")
        return redirect(url_for("admin.categories"))
    rows = q("SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id=c.id) AS n FROM categories c ORDER BY sort")
    return render_template("admin/categories.html", rows=rows)


# ---------------------------------------------------------------- orders
@admin_bp.route("/orders")
@admin_required
def orders():
    st = request.args.get("status", "")
    rows = q("SELECT * FROM orders WHERE (?='' OR status=?) ORDER BY id DESC", (st, st))
    return render_template("admin/orders.html", rows=rows, st=st, statuses=C.ORDER_STATUSES)


@admin_bp.route("/orders/<int:oid>", methods=["GET", "POST"])
@admin_required
def order(oid):
    o = q("SELECT * FROM orders WHERE id=?", (oid,), one=True)
    if not o:
        abort(404)
    if request.method == "POST":
        f = request.form
        status = f.get("status") if f.get("status") in C.ORDER_STATUSES else o["status"]
        pay = f.get("payment_status") if f.get("payment_status") in ("pending", "paid", "cod", "failed", "refunded") else o["payment_status"]
        run("UPDATE orders SET status=?, payment_status=?, tracking_id=?, tracking_note=? WHERE id=?",
            (status, pay, f.get("tracking_id", "").strip()[:100], f.get("tracking_note", "").strip()[:500], oid))
        # Cancelling an order puts its stock back.
        if status == "cancelled" and o["stock_taken"]:
            for it in q("SELECT variant_id, qty FROM order_items WHERE order_id=?", (oid,)):
                run("UPDATE variants SET stock=stock+? WHERE id=?", (it["qty"], it["variant_id"]))
            run("UPDATE orders SET stock_taken=0 WHERE id=?", (oid,))
        flash("Order updated.", "ok")
        return redirect(url_for("admin.order", oid=oid))
    return render_template("admin/order.html", o=o, items=q("SELECT * FROM order_items WHERE order_id=?", (oid,)),
                           statuses=C.ORDER_STATUSES)


@admin_bp.route("/orders.csv")
@admin_required
def orders_csv():
    out = io.StringIO()
    w = csvmod.writer(out)
    w.writerow(["Order", "Date", "Name", "Mobile", "Address", "City", "State", "PIN", "Items", "Total", "Payment", "Payment status", "Status"])
    for o in q("SELECT * FROM orders ORDER BY id DESC"):
        items = "; ".join(f"{i['product_name']} {i['pack_label']} x{i['qty']}" for i in q("SELECT * FROM order_items WHERE order_id=?", (o["id"],)))
        w.writerow([o["order_no"], o["created"], o["name"], o["mobile"], o["address"], o["city"], o["state"], o["pincode"], items, o["total"], o["payment_method"], o["payment_status"], o["status"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=orders.csv"})


# ---------------------------------------------------------------- enquiries
@admin_bp.route("/enquiries", methods=["GET", "POST"])
@admin_required
def enquiries():
    if request.method == "POST":
        eid = int(request.form.get("id", 0))
        if request.form.get("action") == "delete":
            run("DELETE FROM enquiries WHERE id=?", (eid,))
        else:
            run("UPDATE enquiries SET status=? WHERE id=?", ("done" if request.form.get("action") == "done" else "new", eid))
        return redirect(url_for("admin.enquiries"))
    return render_template("admin/enquiries.html", rows=q("SELECT * FROM enquiries ORDER BY id DESC"))


# ---------------------------------------------------------------- reviews
@admin_bp.route("/reviews", methods=["GET", "POST"])
@admin_required
def reviews():
    if request.method == "POST":
        rid, act = int(request.form.get("id", 0)), request.form.get("action")
        if act == "delete":
            run("DELETE FROM reviews WHERE id=?", (rid,))
        else:
            run("UPDATE reviews SET approved=? WHERE id=?", (1 if act == "approve" else 0, rid))
        return redirect(url_for("admin.reviews"))
    rows = q("SELECT r.*, p.name_en AS product FROM reviews r JOIN products p ON p.id=r.product_id ORDER BY r.approved, r.id DESC")
    return render_template("admin/reviews.html", rows=rows)


# ---------------------------------------------------------------- videos
@admin_bp.route("/videos", methods=["GET", "POST"])
@admin_required
def videos():
    if request.method == "POST":
        f, act = request.form, request.form.get("action")
        vid = int(f.get("id", 0) or 0)
        if act == "delete":
            run("DELETE FROM videos WHERE id=?", (vid,))
        else:
            url = f.get("youtube_url", "").strip()
            if url and not C.youtube_id(url):
                flash("That does not look like a YouTube link. Use a link like https://www.youtube.com/watch?v=XXXXXXXXXXX", "err")
                return redirect(url_for("admin.videos"))
            data = (f.get("title_en", "").strip(), f.get("title_hi", "").strip(), url, f.get("category", "").strip(),
                    1 if f.get("active") else 0, int(num(f.get("sort"))))
            if act == "add":
                run("INSERT INTO videos(title_en,title_hi,youtube_url,category,active,sort) VALUES(?,?,?,?,?,?)", data)
            else:
                run("UPDATE videos SET title_en=?,title_hi=?,youtube_url=?,category=?,active=?,sort=? WHERE id=?", data + (vid,))
            flash("Saved.", "ok")
        return redirect(url_for("admin.videos"))
    return render_template("admin/videos.html", rows=q("SELECT * FROM videos ORDER BY sort,id"))


# ---------------------------------------------------------------- banners
@admin_bp.route("/banners", methods=["GET", "POST"])
@admin_required
def banners():
    if request.method == "POST":
        f, act = request.form, request.form.get("action")
        bid = int(f.get("id", 0) or 0)
        if act == "delete":
            run("DELETE FROM banners WHERE id=?", (bid,))
        else:
            img = C.save_image(request.files.get("image"))
            data = [f.get("title_en", "").strip(), f.get("title_hi", "").strip(), f.get("subtitle_en", "").strip(),
                    f.get("subtitle_hi", "").strip(), f.get("link", "").strip(), 1 if f.get("active") else 0, int(num(f.get("sort")))]
            if act == "add":
                run("INSERT INTO banners(title_en,title_hi,subtitle_en,subtitle_hi,link,active,sort,image) VALUES(?,?,?,?,?,?,?,?)", data + [img])
            else:
                run("UPDATE banners SET title_en=?,title_hi=?,subtitle_en=?,subtitle_hi=?,link=?,active=?,sort=? WHERE id=?", data + [bid])
                if img:
                    run("UPDATE banners SET image=? WHERE id=?", (img, bid))
                if f.get("remove_image"):
                    run("UPDATE banners SET image='' WHERE id=?", (bid,))
            flash("Banner saved. The homepage shows the first active banner (lowest 'order').", "ok")
        return redirect(url_for("admin.banners"))
    return render_template("admin/banners.html", rows=q("SELECT * FROM banners ORDER BY sort,id"))


# ---------------------------------------------------------------- settings
SETTING_KEYS = ["business_name", "brand", "contact_person", "phone", "whatsapp", "address", "email", "gstin",
                "shipping_flat", "free_shipping_above", "blocked_pincodes"]


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        f = request.form
        if f.get("action") == "password":
            a = q("SELECT * FROM admins WHERE id=?", (session["admin"],), one=True)
            if not check_password_hash(a["password_hash"], f.get("old", "")):
                flash("Current password is wrong.", "err")
            elif len(f.get("new", "")) < 10:
                flash("New password must be at least 10 characters.", "err")
            elif f["new"] != f.get("new2"):
                flash("The two new passwords do not match.", "err")
            else:
                run("UPDATE admins SET password_hash=? WHERE id=?", (generate_password_hash(f["new"]), a["id"]))
                flash("Password changed.", "ok")
        else:
            for k in SETTING_KEYS:
                run("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, f.get(k, "").strip()))
            for k in ("cod_enabled", "show_demo_banner"):
                run("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, "1" if f.get(k) else "0"))
            flash("Settings saved.", "ok")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html")
