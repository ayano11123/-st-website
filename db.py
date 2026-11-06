"""Database layer for FAIRY CROP (SQLite). Creates tables and demo data on first run."""
import os
import secrets
import sqlite3

from flask import g
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("FAIRYCROP_DB", os.path.join(DATA_DIR, "fairycrop.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name_en TEXT, name_hi TEXT, icon TEXT, sort INTEGER DEFAULT 0,
  note_en TEXT DEFAULT '', note_hi TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE, category_id INTEGER,
  name_en TEXT, name_hi TEXT, short_en TEXT, short_hi TEXT, desc_en TEXT, desc_hi TEXT,
  benefits_en TEXT, benefits_hi TEXT,
  problem_en TEXT, problem_hi TEXT, why_en TEXT, why_hi TEXT, helps_en TEXT, helps_hi TEXT,
  when_en TEXT, when_hi TEXT, prepare_en TEXT, prepare_hi TEXT, apply_en TEXT, apply_hi TEXT,
  method TEXT DEFAULT '',
  dosage_en TEXT, dosage_hi TEXT, precautions_en TEXT, precautions_hi TEXT,
  storage_en TEXT, storage_hi TEXT,
  composition TEXT, batch_info TEXT, expiry_info TEXT, manufacturer TEXT, marketer TEXT, regulatory TEXT,
  crops TEXT DEFAULT '', plants TEXT DEFAULT '', problems TEXT DEFAULT '', needs TEXT DEFAULT '',
  audience TEXT DEFAULT 'both', is_demo INTEGER DEFAULT 1, is_best_seller INTEGER DEFAULT 0,
  is_featured INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS variants (
  id INTEGER PRIMARY KEY, product_id INTEGER, label TEXT, price REAL, mrp REAL, stock INTEGER DEFAULT 0, sku TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS product_images (
  id INTEGER PRIMARY KEY, product_id INTEGER, path TEXT, caption TEXT DEFAULT '', kind TEXT DEFAULT 'product');
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT, mobile TEXT UNIQUE, email TEXT, password_hash TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, order_no TEXT UNIQUE, user_id INTEGER, name TEXT, mobile TEXT, email TEXT,
  address TEXT, city TEXT, state TEXT, pincode TEXT,
  subtotal REAL, shipping REAL, total REAL,
  payment_method TEXT, payment_status TEXT DEFAULT 'pending', status TEXT DEFAULT 'pending',
  rzp_order_id TEXT, rzp_payment_id TEXT, tracking_id TEXT DEFAULT '', tracking_note TEXT DEFAULT '',
  stock_taken INTEGER DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY, order_id INTEGER, variant_id INTEGER, product_id INTEGER,
  product_name TEXT, pack_label TEXT, price REAL, qty INTEGER);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY, product_id INTEGER, user_id INTEGER, name TEXT, rating INTEGER, text TEXT,
  approved INTEGER DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS enquiries (
  id INTEGER PRIMARY KEY, kind TEXT, name TEXT, mobile TEXT, business TEXT, location TEXT,
  products TEXT, quantity TEXT, message TEXT, status TEXT DEFAULT 'new', created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY, title_en TEXT, title_hi TEXT, youtube_url TEXT DEFAULT '', category TEXT,
  active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS banners (
  id INTEGER PRIMARY KEY, title_en TEXT, title_hi TEXT, subtitle_en TEXT, subtitle_hi TEXT,
  link TEXT DEFAULT '', image TEXT DEFAULT '', active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS newsletter (id INTEGER PRIMARY KEY, email TEXT UNIQUE, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT);
"""

DEFAULT_SETTINGS = {
    "business_name": "FAIRY CROP AGRISCIENCE LLP",
    "brand": "FAIRY CROP",
    "contact_person": "Dikshit",
    "phone": "7777000941",
    "whatsapp": "7777000941",
    "address": "Opp. ITI Main Gate, Karnal, Haryana – 132001, India.",
    "email": "",
    "cod_enabled": "0",
    "shipping_flat": "60",
    "free_shipping_above": "999",
    "blocked_pincodes": "",
    "show_demo_banner": "1",
    "gstin": "",
    "dealer_licence_note": "",
}

CATEGORIES = [
    ("organic-fertilizers", "Organic Fertilizers", "जैविक खाद", "🌿", "", ""),
    ("biofertilizers", "Biofertilizers", "जैव उर्वरक", "🧫", "", ""),
    ("plant-growth-promoters", "Plant Growth Promoters", "पौध वृद्धि प्रवर्धक", "🌱", "", ""),
    ("micronutrients", "Micronutrients", "सूक्ष्म पोषक तत्व", "🧪", "", ""),
    ("plant-nutrition", "Plant Nutrition", "पौध पोषण", "💧", "", ""),
    ("soil-conditioners", "Soil Conditioners", "मृदा सुधारक", "🪱", "", ""),
    ("plant-protection", "Plant Protection Products", "पौध संरक्षण उत्पाद", "🛡️",
     "Sold only where legally permitted and with the required licences. No products listed yet.",
     "केवल वहीं बेचे जाते हैं जहाँ कानूनन अनुमति हो और ज़रूरी लाइसेंस हो। अभी कोई उत्पाद सूचीबद्ध नहीं है।"),
    ("gardening-products", "Gardening Products", "बागवानी उत्पाद", "🪴", "", ""),
    ("flowering-fruiting", "Flowering and Fruiting Solutions", "फूल और फल समाधान", "🌸", "", ""),
    ("home-gardening", "Home Gardening Essentials", "घरेलू बागवानी ज़रूरी सामान", "🏡", "", ""),
    ("agri-special", "Agriculture Special Products", "कृषि विशेष उत्पाद", "⭐", "", ""),
]

# Generic, deliberately cautious demo text per category. Nothing here is real product data.
GENERIC = {
    "problem_en": "Plants can look weak, pale or slow-growing when they do not get enough of the nutrients or soil support they need. This is demo text - replace it with wording that matches the approved product label.",
    "problem_hi": "जब पौधों को ज़रूरी पोषण या मिट्टी का सहारा पूरा नहीं मिलता तो वे कमज़ोर, पीले या धीमे बढ़ते दिख सकते हैं। यह डेमो लेख है - इसे अनुमोदित प्रोडक्ट लेबल के अनुसार बदलें।",
    "why_en": "Common reasons include tired soil, repeated cropping, irregular feeding or watering, and weather stress. Demo text.",
    "why_hi": "आम कारण हैं: थकी हुई मिट्टी, बार-बार एक ही फ़सल, अनियमित खाद-पानी और मौसम का दबाव। डेमो लेख।",
    "helps_en": "The product is intended to support healthy plant growth when used as directed on its label. Demo text - no verified claim is made here.",
    "helps_hi": "यह उत्पाद लेबल पर बताए अनुसार उपयोग करने पर पौधों की अच्छी बढ़त में सहायक होने के लिए है। डेमो लेख - यहाँ कोई सत्यापित दावा नहीं है।",
    "benefits_en": "Benefit points will be added from the verified product label\nDemo placeholder - edit in Admin > Products",
    "benefits_hi": "लाभ के बिंदु सत्यापित प्रोडक्ट लेबल से जोड़े जाएँगे\nडेमो प्लेसहोल्डर - एडमिन > प्रोडक्ट में बदलें",
}

# (slug, category_slug, name_en, name_hi, audience, crops, plants, problems, needs, method, best, featured, variants[(label, price, mrp, stock)])
DEMO_PRODUCTS = [
    ("demo-organic-fertilizer", "organic-fertilizers", "Sample Organic Fertilizer", "नमूना जैविक खाद", "both",
     "wheat,rice,mustard,vegetables", "vegetable garden,flower pots", "weak growth,tired soil", "soil feeding", "soil", 1, 1,
     [("1 kg", 149, 179, 50), ("5 kg", 599, 749, 30)]),
    ("demo-biofertilizer", "biofertilizers", "Sample Biofertilizer", "नमूना जैव उर्वरक", "farmer",
     "wheat,rice,cotton,vegetables", "", "tired soil", "soil feeding", "soil", 1, 0,
     [("500 ml", 249, 299, 40), ("1 litre", 449, 549, 25)]),
    ("demo-growth-promoter", "plant-growth-promoters", "Sample Plant Growth Promoter", "नमूना पौध वृद्धि प्रवर्धक", "both",
     "cotton,vegetables,fruits,flowers", "flowering plants", "weak growth", "growth support", "foliar", 1, 1,
     [("250 ml", 199, 249, 60), ("500 ml", 349, 429, 35)]),
    ("demo-micronutrient-mix", "micronutrients", "Sample Micronutrient Mix", "नमूना सूक्ष्म पोषक मिश्रण", "farmer",
     "wheat,rice,mustard,cotton,fruits", "", "pale leaves", "nutrient support", "foliar", 0, 1,
     [("250 ml", 229, 279, 45), ("1 litre", 749, 899, 20)]),
    ("demo-plant-nutrition", "plant-nutrition", "Sample Plant Nutrition Liquid", "नमूना पौध पोषण तरल", "both",
     "vegetables,fruits,flowers", "home garden plants", "pale leaves,weak growth", "regular feeding", "irrigation", 1, 0,
     [("500 ml", 279, 329, 40), ("1 litre", 499, 599, 30)]),
    ("demo-soil-conditioner", "soil-conditioners", "Sample Soil Conditioner", "नमूना मृदा सुधारक", "farmer",
     "wheat,rice,mustard,cotton", "", "hard soil,tired soil", "soil structure", "soil", 0, 1,
     [("5 kg", 399, 499, 30), ("25 kg", 1699, 1999, 12)]),
    ("demo-flowering-fruiting", "flowering-fruiting", "Sample Flowering & Fruiting Booster", "नमूना फूल-फल बूस्टर", "both",
     "fruits,vegetables,flowers", "flowering plants,fruit plants", "poor flowering", "flowering support", "foliar", 1, 1,
     [("250 ml", 249, 299, 50), ("500 ml", 429, 519, 30)]),
    ("demo-home-plant-food", "home-gardening", "Sample Home Garden Plant Food", "नमूना घरेलू बगीचा पौध भोजन", "gardener",
     "", "home garden plants,flowering plants,vegetable garden", "weak growth,pale leaves", "pots and balcony", "irrigation", 1, 0,
     [("250 ml", 149, 189, 80), ("500 ml", 249, 299, 60)]),
    ("demo-potting-mix", "gardening-products", "Sample Potting Mix", "नमूना पॉटिंग मिक्स", "gardener",
     "", "home garden plants,vegetable garden,flower pots", "hard soil", "pots and balcony", "soil", 0, 0,
     [("5 kg", 249, 299, 40), ("10 kg", 449, 529, 25)]),
    ("demo-agri-special", "agri-special", "Sample Agriculture Special Product", "नमूना कृषि विशेष उत्पाद", "farmer",
     "wheat,rice,mustard,cotton", "", "", "special crop care", "soil", 0, 0,
     [("1 litre", 599, 699, 20)]),
]

VIDEOS = [
    ("How to use fertilizers", "खाद का उपयोग कैसे करें", "fertilizers"),
    ("Understanding biofertilizers", "जैव उर्वरक को समझें", "biofertilizers"),
    ("Plant nutrition guide", "पौध पोषण गाइड", "nutrition"),
    ("How to improve soil health", "मिट्टी की सेहत कैसे सुधारें", "soil"),
    ("Crop-specific guidance", "फ़सल के अनुसार मार्गदर्शन", "crops"),
    ("Home gardening tutorial", "घरेलू बागवानी ट्यूटोरियल", "home-gardening"),
    ("How to identify common plant problems", "पौधों की आम समस्याएँ कैसे पहचानें", "problems"),
]

BANNERS = [
    ("Grow Better. Grow Naturally.", "बेहतर उगाएँ, प्राकृतिक रूप से।",
     "Advanced Plant Nutrition for Healthier Crops & Greener Gardens.",
     "स्वस्थ फ़सलों और हरे-भरे बगीचों के लिए उन्नत पौध पोषण।", "/shop"),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def run(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    if con.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        for i, (slug, en, hi, icon, nen, nhi) in enumerate(CATEGORIES):
            con.execute("INSERT INTO categories(slug,name_en,name_hi,icon,sort,note_en,note_hi) VALUES(?,?,?,?,?,?,?)",
                        (slug, en, hi, icon, i, nen, nhi))
    if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        cats = {r["slug"]: r["id"] for r in con.execute("SELECT id,slug FROM categories")}
        for (slug, cat, en, hi, aud, crops, plants, probs, needs, method, best, feat, variants) in DEMO_PRODUCTS:
            cur = con.execute(
                """INSERT INTO products(slug,category_id,name_en,name_hi,short_en,short_hi,desc_en,desc_hi,
                   benefits_en,benefits_hi,problem_en,problem_hi,why_en,why_hi,helps_en,helps_hi,
                   crops,plants,problems,needs,method,audience,is_demo,is_best_seller,is_featured,
                   manufacturer,marketer,regulatory)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
                (slug, cats[cat], en, hi,
                 "DEMO product - replace with real product details.", "डेमो उत्पाद - असली उत्पाद विवरण से बदलें।",
                 "This is a demo listing created so you can see how the shop works. Product name, price and text are samples only.",
                 "यह एक डेमो लिस्टिंग है ताकि आप देख सकें कि दुकान कैसे काम करती है। उत्पाद का नाम, कीमत और लेख केवल नमूना हैं।",
                 GENERIC["benefits_en"], GENERIC["benefits_hi"], GENERIC["problem_en"], GENERIC["problem_hi"],
                 GENERIC["why_en"], GENERIC["why_hi"], GENERIC["helps_en"], GENERIC["helps_hi"],
                 crops, plants, probs, needs, method, aud, best, feat,
                 "", "FAIRY CROP AGRISCIENCE LLP", ""))
            pid = cur.lastrowid
            for label, price, mrp, stock in variants:
                con.execute("INSERT INTO variants(product_id,label,price,mrp,stock) VALUES(?,?,?,?,?)",
                            (pid, label, price, mrp, stock))
    if con.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0:
        for i, (en, hi, cat) in enumerate(VIDEOS):
            con.execute("INSERT INTO videos(title_en,title_hi,category,sort) VALUES(?,?,?,?)", (en, hi, cat, i))
    if con.execute("SELECT COUNT(*) FROM banners").fetchone()[0] == 0:
        for (ten, thi, sen, shi, link) in BANNERS:
            con.execute("INSERT INTO banners(title_en,title_hi,subtitle_en,subtitle_hi,link) VALUES(?,?,?,?,?)",
                        (ten, thi, sen, shi, link))
    # First admin account
    if con.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
        pw = os.environ.get("FAIRYCROP_ADMIN_PASSWORD") or secrets.token_urlsafe(9)
        con.execute("INSERT INTO admins(username,password_hash) VALUES(?,?)", ("admin", generate_password_hash(pw)))
        if not os.environ.get("FAIRYCROP_ADMIN_PASSWORD"):
            path = os.path.join(DATA_DIR, "FIRST_ADMIN_PASSWORD.txt")
            with open(path, "w") as f:
                f.write(f"Admin login -> username: admin   password: {pw}\nChange it in Admin > Settings, then delete this file.\n")
            print(f"\n*** FIRST RUN: admin username 'admin', password '{pw}' (also saved in {path}) ***\n")
    con.commit()
    con.close()
