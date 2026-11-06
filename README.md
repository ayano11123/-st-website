# FAIRY CROP website – beginner's guide

Grow Better. Grow Naturally. — online shop + learning site + owner dashboard for
**FAIRY CROP AGRISCIENCE LLP**, Karnal, Haryana.

Built with **Python + Flask + SQLite** (a real database stored in `data/fairycrop.db`).
You do not need to know HTML/CSS/JS to run or manage it.

---------------------------------------------------------------------------
## 1. Run it on your computer (to try it)

1. Install Python 3.10+ from python.org.
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   python app.py
   ```
   (On Mac/Linux you can also run `./run.sh`.)
3. Open http://127.0.0.1:5000 in your browser.
4. **First run prints the admin password** in the terminal and saves it in
   `data/FIRST_ADMIN_PASSWORD.txt`. Admin login page: http://127.0.0.1:5000/admin
   (username `admin`). Change the password in *Admin → Settings*, then delete that file.

## 2. Put it on the internet (deploy)

Easiest for beginners: **PythonAnywhere** (paid plan needed for a custom domain) or a small
**VPS** (DigitalOcean, AWS Lightsail, Hostinger VPS etc.). Any host that runs Python works.

On a Linux server:
```
pip install -r requirements.txt
export FAIRYCROP_HTTPS=1                      # because the site will use https
export FAIRYCROP_ADMIN_PASSWORD='choose-a-long-password'   # only used the very first time
export RAZORPAY_KEY_ID=rzp_live_xxxxx
export RAZORPAY_KEY_SECRET=xxxxx
gunicorn app:app --bind 127.0.0.1:8000 --workers 2
```
Put Nginx (or Caddy) in front for HTTPS (free certificate from Let's Encrypt) and point your
domain to the server. **Back up the `data/` folder and `static/uploads/` folder regularly** –
they contain your database, secret key and uploaded photos.

## 3. Turn on real payments (Razorpay)

1. Create a Razorpay account and complete their business KYC.
2. Copy your **Key ID** and **Key Secret** (use *test* keys first).
3. Set them as the environment variables `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`, restart the site.
4. Optional safety net: in Razorpay → Webhooks add `https://YOUR-DOMAIN/payment/webhook`
   (events `payment.captured`, `order.paid`) and set `RAZORPAY_WEBHOOK_SECRET` to the secret you chose.

Until the keys are set, the checkout **refuses online payment** – the site never pretends a payment succeeded.
Payments are verified with Razorpay's signature on the server. *Cash on Delivery* can be switched on in Admin → Settings.

## 4. Daily use – the owner dashboard (/admin)

| I want to… | Go to |
|---|---|
| Add / edit / hide / delete a product, change price, MRP (= discount), pack sizes, stock, photos, dosage, usage, composition, licences | **Products** |
| Add or rename categories | **Categories** |
| See orders, change status (confirmed → packed → shipped → delivered), add courier tracking ID, download Excel/CSV | **Orders** |
| Read bulk-order and contact enquiries (mark done) | **Enquiries** |
| Approve or delete customer reviews (only approved ones show) | **Reviews** |
| Add YouTube videos to “Learn with Fairy Crop” | **Videos** (paste a normal YouTube link) |
| Change homepage headline / hero photo | **Banners** |
| Phone, WhatsApp, address, shipping charge, free-shipping limit, blocked PIN codes, COD, demo banner | **Settings** |

Customers' view of an order updates automatically when you change its status.
Stock goes down when an order is confirmed and comes back if you cancel it.

## 5. Replace demo content with real content (IMPORTANT before launch)

All 10 products are **DEMO** samples with sample prices and generic text.
For each real product, open *Admin → Products* and fill in **only what is on the approved label /
manufacturer documents**: composition, dosage, method, crops, precautions, storage, batch/expiry,
manufacturer, licence/registration details. Anything left empty is shown to customers as
*"to be added from the verified product label"* – nothing is invented.
Then untick **Demo** on the product, and finally switch off the demo banner in Settings.
Also: write the Hindi fields in simple words, read the Policies page and edit it (it is a draft), and
check with the relevant authority/adviser which licences you need to sell fertilisers/biofertilisers
(and pesticides – the *Plant Protection* category is empty on purpose).

Pictures: no stock photos are bundled. The shop shows clearly labelled **DEMO PACK** placeholders
until you upload real photos. For the homepage, either upload a hero photo in *Admin → Banners* or put a
file named `hero.jpg` in `static/img/`. Use only photos you own or have licences for. Before/after
pictures should only be added if genuine.

## 6. Folder map (for whoever helps you later)

```
app.py        shop pages, cart, login, checkout, Razorpay
admin.py      owner dashboard
db.py         database tables + demo data
common.py     helpers (Hindi labels, ₹ format, security)
templates/    page layouts (templates/admin = dashboard)
static/       css/style.css (colours at the top), js/main.js, img/, uploads/
data/         database + secret key (BACK THIS UP, never share it)
```
Useful settings (environment variables): `HOST`, `PORT`, `FAIRYCROP_HTTPS`, `FAIRYCROP_ADMIN_PASSWORD`,
`FAIRYCROP_DB` (database path), `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`.

## 7. Security notes
Passwords are hashed; forms use CSRF tokens; admin login is rate-limited; uploads are checked and re-encoded as images;
the admin area is never cached or indexed. Use HTTPS in production and keep Python/Flask updated.
