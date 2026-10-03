import os, re, random, sqlite3, requests, hashlib, threading, time, bisect
from urllib.parse import urlencode, quote
from flask import Flask, request, session, jsonify, render_template, redirect, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------- Конфіг ----------
TOKEN = os.getenv("BOT_TOKEN", "8841389440:AAH0gqj8n4ECg84O_HhdwbRirzzKpKf0VMI")  # репозиторій на GitHub має бути PRIVATE; змінна BOT_TOKEN у Render, якщо задана, має пріоритет
ADMINS = [7952645598, 6526861547]
SITE_URL = (os.getenv("SITE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://127.0.0.1:5000").rstrip("/")  # публічний https, потрібен для входу через Steam
SECRET = os.getenv("SECRET", "47093f0947c35dfe127973a6881397b4885bc0bfe2299583")
STEAM_KEY = os.getenv("STEAM_API_KEY", "")      # для підтягування ніка/аватарки зі Steam
PAY_CARD = os.getenv("PAY_CARD", "4874100010251687")            # реквізити картки UAH (задайте самі)
PAY_CRYPTO = os.getenv("PAY_CRYPTO", "")        # адреса крипто-гаманця (задайте самі)
COINS_PER_UAH = float(os.getenv("COINS_PER_UAH", "2.4"))
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.getenv("DB_PATH") or os.path.join(BASE, "neondrop.db")  # на Render вкажіть шлях на Persistent Disk, напр. /var/data/neondrop.db
os.makedirs(os.path.dirname(DB), exist_ok=True)
TRADE_RE = re.compile(r"^https://steamcommunity\.com/tradeoffer/new/\?partner=\d+&token=[\w-]+$")

app = Flask(__name__)
app.secret_key = SECRET
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # Render стоїть за проксі
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=SITE_URL.startswith("https://"), PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

SEED = {
    "Mil-Spec": [("P250 | Sand Dune", 15), ("MP9 | Storm", 20), ("Nova | Predator", 25), ("SG 553 | Damascus Steel", 35), ("Glock-18 | Sand Dune", 18)],
    "Restricted": [("AK-47 | Safari Mesh", 90), ("M4A4 | Desert-Strike", 130), ("USP-S | Orion", 160), ("AWP | Worm God", 100)],
    "Classified": [("AK-47 | Redline", 420), ("M4A1-S | Hyper Beast", 520), ("AWP | Asiimov", 650)],
    "Covert": [("AK-47 | Fire Serpent", 1800), ("AWP | Dragon Lore", 2600), ("M4A4 | Howl", 2200)],
    "Rare Special": [("★ Karambit | Doppler", 9000), ("★ Butterfly Knife | Fade", 13000), ("★ Sport Gloves | Vice", 15000)],
}
WEIGHTS = {"Mil-Spec": 79.92, "Restricted": 15.98, "Classified": 3.2, "Covert": 0.64, "Rare Special": 0.26}
# (id, назва, ціна в монетах, ключові слова) — ціна завжди вища за середню вартість предметів (RTP ≈ 87%)
CASE_DEFS = [
    ("starter", "Starter Box", 50, []),
    ("pistol", "Pistol Party", 50, ["Glock", "USP", "Desert Eagle", "P250", "Five-SeveN", "CZ75", "Tec-9"]),
    ("smg", "SMG Storm", 100, ["MP9", "MP7", "P90", "UMP", "MAC-10", "Bizon", "MP5"]),
    ("sand", "Desert Run", 100, ["Sand", "Desert", "Safari", "Dune"]),
    ("rifle", "Rifle Rush", 300, ["AK-47", "M4A4", "M4A1-S", "Galil", "FAMAS", "SG 553", "AUG"]),
    ("heavy", "Heavy Metal", 300, ["Nova", "XM1014", "MAG-7", "Sawed", "M249", "Negev"]),
    ("mix", "Neon Mix", 500, []),
    ("awp", "AWP Legends", 1000, ["AWP", "SSG"]),
    ("redline", "Red Alert", 1000, ["Redline", "Asiimov", "Hyper Beast", "Neo-Noir"]),
    ("gloves", "Glove Locker", 3000, ["Gloves", "Wraps"]),
    ("dragon", "Dragon Hoard", 3000, ["Dragon", "Fire Serpent", "Howl", "Medusa"]),
    ("knife", "Blade Vault", 7500, ["★"]),
    ("karambit", "Karambit Club", 7500, ["Karambit"]),
    ("butterfly", "Butterfly Effect", 15000, ["Butterfly", "Bayonet", "Flip"]),
    ("elite", "Elite Vault", 15000, []),
]
QUOTA = {"Mil-Spec": 12, "Restricted": 8, "Classified": 5, "Covert": 3, "Rare Special": 2}  # разом 30
CAT, CASES = {}, {}


def db():
    c = sqlite3.connect(DB, timeout=20); c.row_factory = sqlite3.Row  # timeout: без "database is locked" при кількох запитах
    return c


def init_db():
    c = db(); c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, steamid TEXT UNIQUE, name TEXT, avatar TEXT DEFAULT '', trade_url TEXT DEFAULT '', balance REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS inv(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, item TEXT, status TEXT DEFAULT 'own');
    CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, kind TEXT, info TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, method TEXT, uah REAL, coins REAL, status TEXT DEFAULT 'pending');
    CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, text TEXT, read INTEGER DEFAULT 0, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS skins(name TEXT PRIMARY KEY, rarity TEXT, price INTEGER);
    CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, pct REAL, max_uses INTEGER DEFAULT 0, used INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS promo_uses(code TEXT, uid INTEGER, UNIQUE(code, uid));
    CREATE TABLE IF NOT EXISTS drops(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, item TEXT, case_name TEXT, price INTEGER, show_at DATETIME);
    CREATE TABLE IF NOT EXISTS images(k TEXT PRIMARY KEY, u TEXT);
    """)
    try: c.execute("ALTER TABLE deposits ADD COLUMN promo TEXT DEFAULT ''")
    except sqlite3.OperationalError: pass
    if not c.execute("SELECT 1 FROM skins LIMIT 1").fetchone():
        c.executemany("INSERT INTO skins VALUES(?,?,?)", [(n, r, p) for r, l in SEED.items() for n, p in l])
    c.commit(); c.close()


def load_cat():
    c = db(); cat = {r["name"]: (r["rarity"], r["price"]) for r in c.execute("SELECT * FROM skins")}; c.close()
    CAT.clear(); CAT.update(cat); new_cases = {}  # кейси збираємо окремо й підміняємо разом — сайт не ламається під час перезавантаження каталогу
    srt = sorted(cat, key=lambda n: cat[n][1]); prices = [cat[n][1] for n in srt]  # один раз сортуємо (безкоштовний Render має дуже слабкий CPU)
    for cid, name, price, kw in CASE_DEFS:
        sl = srt[bisect.bisect_left(prices, price * .1):bisect.bisect_right(prices, price * 40)]
        names = [n for n in sl if not kw or any(k in n for k in kw)]
        if len(names) < 6: names = sl or srt
        if len(names) > 30: names = [names[round(i * (len(names) - 1) / 29)] for i in range(30)]
        ps = [CAT[n][1] for n in names]; target = price * .87
        def ev(x): w = [p ** -x for p in ps]; return sum(p * q for p, q in zip(ps, w)) / sum(w)
        lo, hi = 0.0, 8.0
        for _ in range(40):  # підбираємо криву шансів, щоб середня вартість дропу ≈ 87% ціни
            mid = (lo + hi) / 2
            if ev(mid) > target: lo = mid
            else: hi = mid
        w = [p ** -hi for p in ps]; s = sum(w)
        new_cases[cid] = {"name": name, "price": price, "items": [(n, q / s) for n, q in zip(names, w)]}
    CASES.clear(); CASES.update(new_cases)


def notify(text, kb=None):
    for a in ADMINS:
        try:
            d = {"chat_id": a, "text": text}
            if kb: d["reply_markup"] = {"inline_keyboard": kb}
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json=d, timeout=5)
        except Exception:
            pass


def user(uid):
    c = db(); r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(); c.close(); return r


def who(uid):
    u = user(uid); return f"{u['name']} (ID {uid})" if u else str(uid)


def add_log(uid, kind, info):
    c = db(); c.execute("INSERT INTO log(uid,kind,info) VALUES(?,?,?)", (uid, kind, info)); c.commit(); c.close()


def add_note(uid, text):
    c = db(); c.execute("INSERT INTO notes(uid,text) VALUES(?,?)", (uid, text)); c.commit(); c.close()


def notes_of(uid):
    c = db(); rows = c.execute("SELECT id,text,read,ts FROM notes WHERE uid=? ORDER BY id DESC LIMIT 20", (uid,)).fetchall(); c.close()
    return [{"id": r["id"], "text": r["text"], "read": bool(r["read"]), "ts": r["ts"][:16]} for r in rows]


def spend(uid, amount):
    c = db(); cur = c.execute("UPDATE users SET balance=balance-? WHERE id=? AND balance>=?", (amount, uid, amount)); c.commit(); c.close()
    return cur.rowcount == 1


def give(uid, item):
    c = db(); i = c.execute("INSERT INTO inv(uid,item) VALUES(?,?)", (uid, item)).lastrowid; c.commit(); c.close(); return i


def inventory(uid):
    c = db(); rows = c.execute("SELECT id,item FROM inv WHERE uid=? AND status='own' ORDER BY id DESC", (uid,)).fetchall(); c.close()
    return [{"id": r["id"], "name": r["item"], "rarity": CAT[r["item"]][0], "price": CAT[r["item"]][1]} for r in rows if r["item"] in CAT]


def withdraw_stats(uid):
    c = db(); rows = c.execute("SELECT item,status FROM inv WHERE uid=? AND status IN ('withdraw','withdrawn')", (uid,)).fetchall(); c.close()
    done = [CAT[r["item"]][1] for r in rows if r["status"] == "withdrawn" and r["item"] in CAT]
    return {"n": len(done), "sum": sum(done), "pending": sum(r["status"] == "withdraw" for r in rows)}


def promo_get(code, uid=None):  # -> (відсоток бонусу, помилка)
    code = (code or "").strip().upper()
    if not code: return 0, None
    c = db(); p = c.execute("SELECT * FROM promos WHERE code=?", (code,)).fetchone()
    used = uid and c.execute("SELECT 1 FROM promo_uses WHERE code=? AND uid=?", (code, uid)).fetchone(); c.close()
    if not p or not p["active"]: return 0, "Промокод не знайдено"
    if p["max_uses"] and p["used"] >= p["max_uses"]: return 0, "Ліміт використань промокоду вичерпано"
    if used: return 0, "Ви вже використовували цей промокод"
    return p["pct"], None


def release_promo(did):  # відхилена заявка повертає промокод
    c = db(); d = c.execute("SELECT uid,promo FROM deposits WHERE id=?", (did,)).fetchone()
    if d and d["promo"] and c.execute("DELETE FROM promo_uses WHERE code=? AND uid=?", (d["promo"], d["uid"])).rowcount:
        c.execute("UPDATE promos SET used=MAX(0,used-1) WHERE code=?", (d["promo"],))
    c.commit(); c.close()


def promo_save(code, pct, max_uses=0):  # лише з адмін-бота
    c = db(); c.execute("INSERT INTO promos(code,pct,max_uses) VALUES(?,?,?) ON CONFLICT(code) DO UPDATE SET pct=excluded.pct,max_uses=excluded.max_uses,active=1", (code, pct, max_uses)); c.commit(); c.close()


def promo_del(code):
    c = db(); n = c.execute("UPDATE promos SET active=0 WHERE code=? AND active=1", (code,)).rowcount; c.commit(); c.close(); return n


def promos_list():
    c = db(); rows = c.execute("SELECT code,pct,max_uses,used FROM promos WHERE active=1 ORDER BY code").fetchall(); c.close(); return rows


def adjust_balance(uid, amount):  # лише з адмін-бота; баланс не йде нижче 0
    c = db(); n = c.execute("UPDATE users SET balance=MAX(0,balance+?) WHERE id=?", (amount, uid)).rowcount; c.commit()
    r = c.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone(); c.close()
    if not n: return None
    add_log(uid, "admin", f"{amount:+.0f}"); add_note(uid, f"Адміністратор {'нарахував' if amount > 0 else 'списав'} {abs(amount):.0f} монет")
    return r["balance"]


def confirm_deposit(did):  # викликається з адмін-бота
    c = db(); d = c.execute("SELECT * FROM deposits WHERE id=? AND status='pending'", (did,)).fetchone()
    if not d: c.close(); return None
    c.execute("UPDATE deposits SET status='paid' WHERE id=?", (did,))
    c.execute("UPDATE users SET balance=balance+? WHERE id=?", (d["coins"], d["uid"])); c.commit(); c.close()
    add_log(d["uid"], "topup", f"{d['uah']} UAH -> {d['coins']:.0f}")
    add_note(d["uid"], f"Ваш платіж підтверджено, гроші зараховано: +{d['coins']:.0f} монет")
    return d


def roll_item(case):
    return random.choices([n for n, w in case["items"]], [w for n, w in case["items"]])[0]


def me(): return session.get("uid")


def need_auth(f):
    def w(*a, **k):
        if not me() or not user(me()):  # сесія є, а користувача в БД вже немає (напр. БД перестворена)
            session.clear(); return jsonify(error="Увійдіть через Steam", code="auth"), 401
        return f(*a, **k)
    w.__name__ = f.__name__
    return w


@app.route("/")
def index():
    for p in (os.path.join(BASE, "templates", "index.html"), os.path.join(BASE, "index.html")):  # працює і з templates/, і з кореня репозиторію
        if os.path.exists(p): return send_file(p, max_age=0)
    return "index.html не знайдено в репозиторії", 500


@app.route("/health")
def health():  # його ж можна пінгувати (UptimeRobot), щоб Render не засинав; заодно сам лагодить webhook бота
    threading.Thread(target=ensure_webhook, daemon=True).start()
    return f"ok images={len(IMGS)} skins={len(CAT)} bot={'on' if TOKEN else 'NO TOKEN'} webhook={WH['state']}"


WH = {"state": "n/a", "t": 0}


def ensure_webhook(force=False):  # перевіряє, що Telegram шле оновлення саме на наш сайт; якщо ні — ставить заново
    if not TOKEN or not SITE_URL.startswith("https://") or (not force and time.time() - WH["t"] < 300): return
    WH["t"] = time.time()
    try:
        import bot as tgbot
        want = f"{SITE_URL}/tg/{_tgkey()}"
        if tgbot.bot.get_webhook_info().url != want: tgbot.bot.set_webhook(url=want); WH["state"] = "reset"
        else: WH["state"] = "ok"
    except Exception as e: WH["state"] = "error: " + str(e)[:80]


def _tgkey(): return hashlib.sha256(TOKEN.encode()).hexdigest()[:32]


@app.route("/tg/<key>", methods=["POST"])
def tg_webhook(key):  # Telegram шле оновлення сюди (webhook): працює і коли Render «прокидається»
    if not TOKEN or key != _tgkey(): return "", 404
    try:
        import telebot, bot as tgbot
        tgbot.bot.process_new_updates([telebot.types.Update.de_json(request.get_data(as_text=True))])
    except Exception as e: print("webhook error:", e)
    return "ok"


@app.errorhandler(Exception)
def on_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException): return e
    app.logger.exception("Unhandled error")  # повний traceback видно в Render → Logs
    if request.path.startswith("/api/"): return jsonify(error="Помилка сервера, спробуйте ще раз"), 500
    return "Помилка сервера", 500


@app.route("/login")
def login():
    if request.cookies.get("tos") != "1": return redirect("/")  # спочатку потрібно прийняти угоду
    p = {"openid.ns": "http://specs.openid.net/auth/2.0", "openid.mode": "checkid_setup",
         "openid.return_to": SITE_URL + "/auth/steam", "openid.realm": SITE_URL,
         "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
         "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select"}
    return redirect("https://steamcommunity.com/openid/login?" + urlencode(p))


@app.route("/auth/steam")
def auth_steam():
    a = request.args.to_dict(); a["openid.mode"] = "check_authentication"
    m = re.search(r"/openid/id/(\d+)$", a.get("openid.claimed_id", ""))
    try: ok = "is_valid:true" in requests.post("https://steamcommunity.com/openid/login", data=a, timeout=10).text
    except Exception as e: print("steam verify error:", e); ok = False
    if not a.get("openid.return_to", "").startswith(SITE_URL): ok = False
    if not (ok and m): print("steam login failed. SITE_URL =", SITE_URL, "| return_to =", a.get("openid.return_to"))
    if ok and m:
        sid = m.group(1); name, av = "Player " + sid[-4:], ""
        if STEAM_KEY:
            try:
                p = requests.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/", params={"key": STEAM_KEY, "steamids": sid}, timeout=8).json()["response"]["players"][0]
                name, av = p["personaname"][:24], p["avatarfull"]
            except Exception: pass
        c = db(); c.execute("INSERT OR IGNORE INTO users(steamid,name,avatar) VALUES(?,?,?)", (sid, name, av)); c.commit()
        session["uid"] = c.execute("SELECT id FROM users WHERE steamid=?", (sid,)).fetchone()["id"]; c.close()
    return redirect("/")


@app.route("/logout")
def logout(): session.clear(); return redirect("/")


@app.route("/api/state")
def state():
    uid = me(); u = user(uid) if uid else None
    return jsonify(
        me=u and {"id": uid, "name": u["name"], "avatar": u["avatar"], "steamid": u["steamid"], "trade_url": u["trade_url"], "balance": u["balance"]},
        inventory=inventory(uid) if u else [], odds=WEIGHTS, notes=notes_of(uid) if u else [], stats=withdraw_stats(uid) if u else None,
        cases=[{"id": k, "name": v["name"], "price": v["price"], "n": len(v["items"]), "tier": max((CAT.get(n, ("Mil-Spec", 0))[0] for n, w in v["items"]), key=list(WEIGHTS).index)} for k, v in list(CASES.items())])


IMGS = {}  # ключ (назва без зносу/StatTrak/★, нижній регістр) -> URL картинки


def img_key(n):
    n = re.sub(r"\s*\((?:Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)\s*$", "", n or "")
    return n.replace("StatTrak™ ", "").replace("Souvenir ", "").replace("★", "").strip().lower()


def load_images():
    c = db(); IMGS.clear(); IMGS.update({r["k"]: r["u"] for r in c.execute("SELECT k,u FROM images")}); c.close()


def fetch_images():  # база картинок скінів CS2 (ByMykel/CSGO-API); викликається при старті, якщо база порожня
    data = None
    for url in ("https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json", "https://bymykel.github.io/CSGO-API/api/en/skins.json"):
        try: data = requests.get(url, timeout=120).json(); break
        except Exception as e: print("images fetch error:", e)
    if not data: return 0
    rows = {img_key(i["name"]): i["image"] for i in (data.values() if isinstance(data, dict) else data) if isinstance(i, dict) and i.get("name") and i.get("image")}
    c = db(); c.executemany("INSERT OR REPLACE INTO images VALUES(?,?)", list(rows.items())); c.commit(); c.close(); load_images(); return len(rows)


@app.route("/img")
def img():
    n = request.args.get("n", ""); u = IMGS.get(img_key(n)) or "https://cdn.csgo.com/item/" + quote(n, safe="") + "/300.png"
    r = redirect(u, 302); r.headers["Cache-Control"] = "public, max-age=86400"; return r


@app.route("/api/targets")
def targets():  # скіни, які можна отримати в апгрейді (шанс 1–90%)
    try: sp = float(request.args.get("price", 0)); p = float(request.args.get("p", 0))
    except Exception: return jsonify([])
    if sp <= 0: return jsonify([])
    q = (request.args.get("q") or "").lower().split()
    rows = [(n, v) for n, v in CAT.items() if sp * 95 / 90 <= v[1] <= sp * 95 and all(w in n.lower() for w in q)]
    if 0 < p <= 90: tp = sp * 95 / p; rows.sort(key=lambda x: abs(x[1][1] - tp))
    else: rows.sort(key=lambda x: x[1][1])
    rows = sorted(rows[:40], key=lambda x: x[1][1])
    return jsonify([{"name": n, "rarity": v[0], "price": v[1], "chance": round(95 * sp / v[1], 2)} for n, v in rows])


@app.route("/api/sell", methods=["POST"])
@need_auth
def sell():
    uid = me(); d = request.json or {}; ids = d.get("ids") or [d.get("id")]; total = 0
    c = db()
    for i in ids[:300]:
        r = c.execute("SELECT item FROM inv WHERE id=? AND uid=? AND status='own'", (i, uid)).fetchone()
        if r and r["item"] in CAT and c.execute("UPDATE inv SET status='sold' WHERE id=? AND status='own'", (i,)).rowcount: total += CAT[r["item"]][1]
    if total: c.execute("UPDATE users SET balance=balance+? WHERE id=?", (total, uid))
    c.commit(); c.close()
    if not total: return jsonify(error="Предмет не знайдено"), 400
    add_log(uid, "sell", f"+{total}")
    return jsonify(ok=True, total=total)


@app.route("/api/feed")
def feed():
    c = db(); rows = c.execute("SELECT d.id,d.item,d.price,d.case_name,u.name FROM drops d JOIN users u ON u.id=d.uid WHERE d.show_at<=datetime('now') ORDER BY d.id DESC LIMIT 12").fetchall(); c.close()
    return jsonify([{"id": r["id"], "name": r["item"], "rarity": CAT[r["item"]][0], "price": r["price"], "case": r["case_name"], "nick": r["name"]} for r in rows if r["item"] in CAT])


@app.route("/api/promo", methods=["POST"])
@need_auth
def promo_check():
    pct, err = promo_get((request.json or {}).get("code"), me())
    return (jsonify(error=err), 400) if err else jsonify(pct=pct)


@app.route("/api/profile", methods=["POST"])
@need_auth
def profile():
    d = request.json or {}; name = (d.get("name") or "").strip(); tr = (d.get("trade_url") or "").strip(); av = d.get("avatar")
    if not 2 <= len(name) <= 24: return jsonify(error="Нік має містити 2–24 символи"), 400
    if tr and not TRADE_RE.match(tr): return jsonify(error="Невірна трейд-посилання Steam"), 400
    c = db(); c.execute("UPDATE users SET name=?, trade_url=? WHERE id=?", (name, tr, me()))
    if av and av.startswith("data:image/") and len(av) < 80000: c.execute("UPDATE users SET avatar=? WHERE id=?", (av, me()))
    c.commit(); c.close()
    return jsonify(ok=True)


@app.route("/api/case/<cid>")
def case_info(cid):
    c = CASES.get(cid)
    if not c: return jsonify(error="Кейс не знайдено"), 404
    return jsonify(name=c["name"], price=c["price"], items=[{"name": n, "rarity": CAT[n][0], "price": CAT[n][1], "chance": round(w * 100, 3)} for n, w in sorted(c["items"], key=lambda x: -CAT[x[0]][1])])


@app.route("/api/notes/read", methods=["POST"])
@need_auth
def notes_read():
    c = db(); c.execute("UPDATE notes SET read=1 WHERE uid=?", (me(),)); c.commit(); c.close()
    return jsonify(ok=True)


@app.route("/api/open", methods=["POST"])
@need_auth
def open_case():
    uid = me(); case = CASES.get((request.json or {}).get("case"))
    if not case: return jsonify(error="Кейс не знайдено"), 400
    if not spend(uid, case["price"]): return jsonify(error="Недостатньо балансу. Поповніть рахунок."), 400
    win = roll_item(case); inv_id = give(uid, win)
    if CAT[win][1] >= max(150, case["price"] * 3):  # крутий дроп → у стрічку зліва (з затримкою, щоб не спойлерити анімацію)
        c = db(); c.execute("INSERT INTO drops(uid,item,case_name,price,show_at) VALUES(?,?,?,?,datetime('now','+9 seconds'))", (uid, win, case["name"], CAT[win][1])); c.commit(); c.close()
    strip = [roll_item(case) for _ in range(60)]; strip[50] = win
    add_log(uid, "case", f"{case['name']} -> {win}")
    notify(f"📦 Кейс\n{who(uid)}\n{case['name']} ({case['price']})\nВипало: {win} [{CAT[win][0]}, {CAT[win][1]}]")
    return jsonify(strip=[{"name": n, "rarity": CAT[n][0], "price": CAT[n][1]} for n in strip], win=50, inv=inv_id)


@app.route("/api/upgrade", methods=["POST"])
@need_auth
def upgrade():
    uid = me(); d = request.json or {}; tgt = d.get("target")
    if tgt not in CAT: return jsonify(error="Оберіть скін, який хочете отримати"), 400
    c = db(); r = c.execute("SELECT item FROM inv WHERE id=? AND uid=? AND status='own'", (d.get("id"), uid)).fetchone()
    if not r or r["item"] not in CAT: c.close(); return jsonify(error="Предмет не знайдено"), 400
    src = r["item"]; sp, tp = CAT[src][1], CAT[tgt][1]; chance = round(95 * sp / tp, 2)
    if not 1 <= chance <= 90: c.close(); return jsonify(error="Шанс має бути від 1% до 90%"), 400
    if not c.execute("UPDATE inv SET status='used' WHERE id=? AND status='own'", (d["id"],)).rowcount: c.close(); return jsonify(error="Предмет не знайдено"), 400
    c.commit(); c.close()
    roll = random.uniform(0, 100)
    bonus = random.random() < 0.01; nm = random.choice((2, 3)) if bonus else 1; N = 10 if bonus else 0  # NeonDrop: 1% шанс, неоновий сектор 10% колеса
    neon = bonus and roll < N; won = neon or N <= roll < N + chance; prize = None; inv_id = None
    if won:
        prize = min(CAT, key=lambda n: abs(CAT[n][1] - tp * nm)) if neon else tgt; inv_id = give(uid, prize)
    add_log(uid, "upgrade", f"{src} -> {tgt} ({chance}%){' NEON x' + str(nm) if bonus else ''}: {prize or 'програш'}")
    notify(f"⚡ Апгрейд\n{who(uid)}\n{src} → {tgt} (шанс {chance}%){' ⚡NEONDROP x' + str(nm) if bonus else ''}\n{'ВИГРАШ → ' + prize if won else 'Програш'}")
    return jsonify(won=won, roll=roll, chance=chance, prize=prize, bonus=bonus, neon=neon, nm=nm, N=N, rarity=prize and CAT[prize][0], price=prize and CAT[prize][1], inv=inv_id)


@app.route("/api/deposit", methods=["POST"])
@need_auth
def deposit():
    uid = me(); d = request.json or {}; method = d.get("method")
    try: uah = float(d.get("amount", 0))
    except Exception: uah = 0
    if not 50 <= uah <= 50000: return jsonify(error="Сума від 50 до 50 000 UAH"), 400
    req = {"card": PAY_CARD, "crypto": PAY_CRYPTO}.get(method)
    if req is None: return jsonify(error="Невірний спосіб оплати"), 400
    if not req: return jsonify(error="Цей спосіб оплати ще не налаштований"), 503
    code = (d.get("promo") or "").strip().upper(); pct, err = promo_get(code, uid)
    if err: return jsonify(error=err), 400
    coins = round(uah * COINS_PER_UAH * (1 + pct / 100))
    c = db(); cur = c.execute("INSERT INTO deposits(uid,method,uah,coins,promo) VALUES(?,?,?,?,?)", (uid, method, uah, coins, code if pct else "")); did = cur.lastrowid
    if pct: c.execute("INSERT INTO promo_uses VALUES(?,?)", (code, uid)); c.execute("UPDATE promos SET used=used+1 WHERE code=?", (code,))
    c.commit(); c.close()
    notify(f"💳 Заявка на поповнення #{did}\n{who(uid)}\nСпосіб: {'картка UAH' if method == 'card' else 'криптовалюта'}\nСума: {uah:.0f} UAH → {coins} монет{' (промокод ' + code + ' +' + format(pct, 'g') + '%)' if pct else ''}",
           [[{"text": "✅ Підтвердити", "callback_data": f"dep_ok:{did}"}, {"text": "❌ Відхилити", "callback_data": f"dep_no:{did}"}]])
    return jsonify(id=did, requisites=req, coins=coins, pct=pct)


@app.route("/api/withdraw", methods=["POST"])
@need_auth
def withdraw():
    uid = me(); u = user(uid)
    if not u["trade_url"]: return jsonify(error="Напишіть трейд-посилання у профілі", code="trade"), 400
    c = db(); r = c.execute("SELECT item FROM inv WHERE id=? AND uid=? AND status='own'", ((request.json or {}).get("id"), uid)).fetchone()
    if not r: c.close(); return jsonify(error="Предмет недоступний"), 400
    iid = request.json["id"]; c.execute("UPDATE inv SET status='withdraw' WHERE id=?", (iid,)); c.commit(); c.close()
    add_log(uid, "withdraw", r["item"]); n = r["item"]
    notify(f"📤 ЗАПИТ НА ВИВІД #{iid}\nID гравця на сайті: {uid}\nНік: {u['name']}\nSteam: https://steamcommunity.com/profiles/{u['steamid']}\nТрейд: {u['trade_url']}\nПредмет: {n} [{CAT[n][0]}, {CAT[n][1]}]",
           [[{"text": "✅ Виконано", "callback_data": f"wd_ok:{iid}"}]])
    return jsonify(ok=True)


init_db(); load_cat(); load_images()


def _bg():  # фонові задачі при старті: скіни, картинки, Telegram-бот (працює з будь-якою Start Command)
    time.sleep(8)  # даємо сайту спокійно піднятися, важкі задачі — після старту
    try:
        c = db(); n = c.execute("SELECT COUNT(*) FROM skins").fetchone()[0]; c.close()
        if n < 200:
            import import_skins  # виконує імпорт при імпорті
            load_cat()
    except Exception as e: print("import_skins failed:", e)
    try:
        if len(IMGS) < 1000: print("images loaded:", fetch_images())
    except Exception as e: print("images failed:", e)
    if not TOKEN: print("BOT_TOKEN не задано — бот вимкнено"); return
    try:
        import bot as tgbot
        if SITE_URL.startswith("https://"): ensure_webhook(True); print("webhook:", WH["state"])
        else: tgbot.bot.remove_webhook(); tgbot.bot.infinity_polling(skip_pending=True)
    except Exception as e: print("bot error:", e)


if not os.environ.get("ND_STARTED") and not os.environ.get("ND_NO_BG"):
    os.environ["ND_STARTED"] = "1"; threading.Thread(target=_bg, daemon=True).start()
if __name__ == "__main__":
    app.run(port=5000)
