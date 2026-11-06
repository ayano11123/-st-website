/* FAIRY CROP - small helper script. No libraries needed. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = function () { var i = $('input[name="_csrf"]'); return i ? i.value : ""; };

  /* scroll reveal */
  var rv = $$(".rv");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { threshold: 0.08 });
    rv.forEach(function (el) { io.observe(el); });
  } else { rv.forEach(function (el) { el.classList.add("in"); }); }

  /* flash messages fade after a while */
  $$(".flash.ok").forEach(function (f) { setTimeout(function () { f.style.transition = "opacity .6s"; f.style.opacity = 0; }, 6000); });

  /* quantity steppers */
  $$(".qty").forEach(function (q) {
    var inp = $("input", q);
    q.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      var max = parseInt(inp.max || "50", 10), v = parseInt(inp.value || "1", 10) + (b.dataset.d === "+" ? 1 : -1);
      inp.value = Math.max(parseInt(inp.min || "1", 10), Math.min(max, v));
      inp.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  /* product page: choose pack size -> update price, stock, and max quantity */
  var packs = $$('input[name="variant_id"][data-price]');
  if (packs.length) {
    var money = function (n) {
      var s = String(Math.round(n)), last = s.slice(-3), rest = s.slice(0, -3);
      if (rest) last = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last;
      return "₹" + last;
    };
    var upd = function () {
      var p = packs.filter(function (x) { return x.checked; })[0]; if (!p) return;
      var price = parseFloat(p.dataset.price), mrp = parseFloat(p.dataset.mrp), stock = parseInt(p.dataset.stock, 10);
      $("#pPrice").textContent = money(price);
      var m = $("#pMrp"), o = $("#pOff");
      if (mrp > price) { m.textContent = money(mrp); m.hidden = false; o.textContent = Math.round((mrp - price) * 100 / mrp) + "% " + (document.documentElement.lang === "hi" ? "छूट" : "OFF"); o.hidden = false; }
      else { m.hidden = true; o.hidden = true; }
      var q = $("#qtyInput"); q.max = Math.max(1, Math.min(50, stock)); if (parseInt(q.value, 10) > q.max) q.value = q.max;
      var low = $("#stockNote"); if (low) { low.hidden = !(stock > 0 && stock <= 10); }
      var wa = $("#waProduct"); if (wa && wa.dataset.base) { wa.href = wa.dataset.base + encodeURIComponent(" (" + p.dataset.label + ")"); }
    };
    packs.forEach(function (p) { p.addEventListener("change", upd); }); upd();
  }

  /* gallery thumbnails */
  $$(".thumbs button").forEach(function (b) {
    b.addEventListener("click", function () {
      var main = $(".gallery .main"); if (!main) return;
      var img = $("img", main); if (img) { img.src = b.dataset.src; }
      $$(".thumbs button").forEach(function (x) { x.classList.remove("on"); }); b.classList.add("on");
    });
  });

  /* pincode checker */
  $$("[data-pin]").forEach(function (box) {
    var inp = $("input", box), btn = $("button", box), msg = $(".pin-msg", box);
    var go = function () {
      var v = (inp.value || "").trim();
      fetch("/api/pincode?pin=" + encodeURIComponent(v)).then(function (r) { return r.json(); }).then(function (d) {
        msg.textContent = d.message; msg.className = "pin-msg " + (d.ok ? "ok" : "no");
      }).catch(function () { msg.textContent = "Could not check right now."; msg.className = "pin-msg no"; });
    };
    btn.addEventListener("click", function (e) { e.preventDefault(); go(); });
    inp.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); go(); } });
  });

  /* video cards: click to play the YouTube video in place (privacy-friendly domain) */
  var play = function (card) {
    var id = card.dataset.yt; if (!id) return;
    var t = $(".vthumb", card);
    t.innerHTML = '<iframe class="vframe" src="https://www.youtube-nocookie.com/embed/' + id + '?autoplay=1&rel=0" title="Video" allow="accelerometer; autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>';
    card.style.cursor = "default";
  };
  $$(".vcard[data-yt]").forEach(function (c) {
    c.addEventListener("click", function () { play(c); });
    c.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); play(c); } });
  });

  /* learn page: filter videos by category */
  $$("[data-vfilter]").forEach(function (b) {
    b.addEventListener("click", function () {
      var f = b.dataset.vfilter;
      $$("[data-vfilter]").forEach(function (x) { x.classList.toggle("on", x === b); });
      $$(".vcard").forEach(function (c) { c.parentElement.style.display = (!f || c.dataset.cat === f) ? "" : "none"; });
    });
  });

  /* confirm buttons (delete etc.) */
  $$("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (e) { if (!window.confirm(el.dataset.confirm)) e.preventDefault(); });
  });

  /* admin: add another pack-size row */
  var add = $("#addVariant");
  if (add) add.addEventListener("click", function () {
    var t = $("#vTemplate"); $("#vRows").insertAdjacentHTML("beforeend", t.innerHTML);
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest(".vdel"); if (b) { e.preventDefault(); b.closest(".vrow").remove(); }
  });

  /* checkout: disable button after click to avoid double orders */
  $$("form[data-once]").forEach(function (f) {
    f.addEventListener("submit", function () { var b = $("button[type=submit]", f); if (b) { setTimeout(function () { b.disabled = true; }, 0); } });
  });
})();
