"""Helpers shared by the shop (app.py) and the admin panel (admin.py)."""
import os
import re
import secrets
import time
import urllib.parse
import uuid

from flask import request, session, abort

from db import q, run, BASE_DIR

UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMG = {"jpg", "jpeg", "png", "webp"}

# Display labels for filter tags (Hindi). Unknown tags are shown as typed.
TAG_HI = {
    "wheat": "गेहूँ", "rice": "धान", "mustard": "सरसों", "cotton": "कपास", "vegetables": "सब्ज़ियाँ",
    "fruits": "फल", "flowers": "फूल", "home garden plants": "घरेलू बगीचे के पौधे",
    "flowering plants": "फूलों वाले पौधे", "vegetable garden": "सब्ज़ी बगीचा", "fruit plants": "फलदार पौधे",
    "flower pots": "गमले के फूल", "weak growth": "कमज़ोर बढ़त", "tired soil": "थकी मिट्टी",
    "pale leaves": "हल्के/पीले पत्ते", "hard soil": "कठोर मिट्टी", "poor flowering": "कम फूल आना",
    "soil feeding": "मिट्टी को पोषण", "nutrient support": "पोषक तत्व सहायता", "growth support": "बढ़वार सहायता",
    "regular feeding": "नियमित पोषण", "soil structure": "मिट्टी की बनावट", "flowering support": "फूल आने में सहायता",
    "pots and balcony": "गमले और बालकनी", "special crop care": "विशेष फ़सल देखभाल",
}
CROP_CHOICES = ["wheat", "rice", "mustard", "cotton", "vegetables", "fruits", "flowers"]
PLANT_CHOICES = ["home garden plants", "flowering plants", "vegetable garden", "fruit plants", "flower pots"]
METHODS = {"soil": ("Soil application", "मिट्टी में डालना", "🌱"), "foliar": ("Foliar spray", "पत्तों पर छिड़काव", "💦"),
           "irrigation": ("With irrigation water", "सिंचाई के पानी के साथ", "🚿"), "root": ("Root application", "जड़ों में देना", "🌿"),
           "": ("As per label", "लेबल के अनुसार", "📄")}
ORDER_STATUSES = ["pending", "confirmed", "packed", "shipped", "delivered", "cancelled"]
STATUS_LABEL = {
    "pending": ("Awaiting payment / confirmation", "भुगतान / पुष्टि की प्रतीक्षा"),
    "confirmed": ("Order confirmed", "ऑर्डर की पुष्टि हुई"),
    "packed": ("Packed", "पैक हो गया"),
    "shipped": ("Shipped", "भेज दिया गया"),
    "delivered": ("Delivered", "डिलीवर हो गया"),
    "cancelled": ("Cancelled", "रद्द"),
}


def cur_lang():
    l = request.cookies.get("lang", "en")
    return l if l in ("en", "hi") else "en"


def tr(en, hi):
    return hi if cur_lang() == "hi" and hi else en


def L(row, base):
    """Pick the Hindi or English version of a database field, falling back to English."""
    keys = row.keys()
    if cur_lang() == "hi" and base + "_hi" in keys and row[base + "_hi"]:
        return row[base + "_hi"]
    return row[base + "_en"] if base + "_en" in keys else ""


def tag(t):
    return TAG_HI.get(t, t) if cur_lang() == "hi" else t


def lines(text):
    return [x.strip() for x in (text or "").replace("\r", "").split("\n") if x.strip()]


def csv(text):
    return [x.strip() for x in (text or "").split(",") if x.strip()]


def money(v):
    """Indian digit grouping: 1,23,456."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0
    whole, frac = divmod(round(v * 100), 100)
    s = str(int(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return "₹" + s + (f".{int(frac):02d}" if frac else "")


def get_settings():
    return {r["key"]: r["value"] for r in q("SELECT key,value FROM settings")}


def wa_link(text="", number=None):
    num = re.sub(r"\D", "", number or get_settings().get("whatsapp", "7777000941"))
    if len(num) == 10:
        num = "91" + num
    url = "https://wa.me/" + num
    return url + ("?text=" + urllib.parse.quote(text) if text else "")


def youtube_id(url):
    m = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else ""


def valid_mobile(m):
    return bool(re.fullmatch(r"[6-9]\d{9}", m or ""))


def clean_mobile(m):
    m = re.sub(r"[\s\-+]", "", m or "")
    if m.startswith("91") and len(m) == 12:
        m = m[2:]
    return m


def valid_pin(p):
    return bool(re.fullmatch(r"[1-9]\d{5}", p or ""))


# ---- CSRF ----
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    tok = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
    if not tok or tok != session.get("csrf"):
        abort(400, "Security token missing or expired. Please go back, refresh the page and try again.")


# ---- simple in-memory rate limit (per process) ----
_hits = {}


def too_many(key, limit=8, window=600):
    now = time.time()
    arr = [t for t in _hits.get(key, []) if now - t < window]
    _hits[key] = arr
    return len(arr) >= limit


def note_hit(key):
    _hits.setdefault(key, []).append(time.time())


# ---- images ----
def save_image(file_storage):
    """Validate, resize (max 1400px) and save an uploaded image. Returns web path or ''."""
    if not file_storage or not file_storage.filename:
        return ""
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_IMG:
        return ""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = uuid.uuid4().hex[:16] + ".webp"
    try:
        from PIL import Image
        img = Image.open(file_storage.stream)
        img.verify()
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream).convert("RGB")
        img.thumbnail((1400, 1400))
        img.save(os.path.join(UPLOAD_DIR, name), "WEBP", quality=82, method=4)
    except Exception:
        return ""
    return "/static/uploads/" + name


# ---- product queries ----
PRODUCT_SELECT = """
SELECT p.*, c.name_en AS cat_en, c.name_hi AS cat_hi, c.slug AS cat_slug,
 (SELECT MIN(price) FROM variants v WHERE v.product_id=p.id) AS minprice,
 (SELECT mrp FROM variants v WHERE v.product_id=p.id ORDER BY price LIMIT 1) AS mrp,
 (SELECT id FROM variants v WHERE v.product_id=p.id AND v.stock>0 ORDER BY price LIMIT 1) AS vid,
 (SELECT COALESCE(SUM(stock),0) FROM variants v WHERE v.product_id=p.id) AS instock,
 (SELECT label FROM variants v WHERE v.product_id=p.id ORDER BY price LIMIT 1) AS packlabel,
 (SELECT path FROM product_images i WHERE i.product_id=p.id ORDER BY i.id LIMIT 1) AS img,
 (SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.product_id=p.id AND r.approved=1) AS rating,
 (SELECT COUNT(*) FROM reviews r WHERE r.product_id=p.id AND r.approved=1) AS rcount
FROM products p JOIN categories c ON c.id=p.category_id
"""


def discount_pct(price, mrp):
    try:
        return int(round((mrp - price) * 100 / mrp)) if mrp and price and mrp > price else 0
    except Exception:
        return 0


def all_tags(column):
    seen = []
    for r in q(f"SELECT {column} FROM products WHERE active=1"):
        for t in csv(r[0]):
            if t not in seen:
                seen.append(t)
    return seen
