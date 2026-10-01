import os, re, random, sqlite3, requests
from urllib.parse import urlencode
from flask import Flask, request, session, jsonify, render_template, redirect
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------- Конфіг ----------
TOKEN = os.getenv("BOT_TOKEN", "8841389440:AAERO-v0t914iHCGtgWZxYnTi8wJRAx1ye4")
ADMINS = [7952645598, 6526861547]
SITE_URL = os.getenv("SITE_URL", "https://neondrop-rm5p.onrender.com")  # публічний https, потрібен для входу через Steam
SECRET = os.getenv("SECRET", "change-me-please")
STEAM_KEY = os.getenv("STEAM_API_KEY", "")      # для підтягування ніка/аватарки зі Steam
PAY_CARD = os.getenv("PAY_CARD", "4874100010251687")            # реквізити картки UAH (задайте самі)
PAY_CRYPTO = os.getenv("PAY_CRYPTO", "")        # адреса крипто-гаманця (задайте самі)
COINS_PER_UAH = float(os.getenv("COINS_PER_UAH", "2.4"))
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "neondrop.db")
TRADE_RE = re.compile(r"^https://steamcommunity\.com/tradeoffer/new/\?partner=\d+&token=[\w-]+$")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = SECRET

SEED = {
    "Mil-Spec": [("P250 | Sand Dune", 15), ("MP9 | Storm", 20), ("Nova | Predator", 25), ("SG 553 | Damascus Steel", 35), ("Glock-18 | Sand Dune", 18)],
    "Restricted": [("AK-47 | Safari Mesh", 90), ("M4A4 | Desert-Strike", 130), ("USP-S | Orion", 160), ("AWP | Worm God", 100)],
    "Classified": [("AK-47 | Redline", 420), ("M4A1-S | Hyper Beast", 520), ("AWP | Asiimov", 650)],
    "Covert": [("AK-47 | Fire Serpent", 1800), ("AWP | Dragon Lore", 2600), ("M4A4 | Howl", 2200)],
    "Rare Special": [("★ Karambit | Doppler", 9000), ("★ Butterfly Knife | Fade", 13000), ("★ Sport Gloves | Vice", 15000)],
}
WEIGHTS = {"Mil-Spec": 79.92, "Restricted": 15.98, "Classified": 3.2, "Covert": 0.64, "Rare Special": 0.26}

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
QUOTA = {"Mil-Spec": 12, "Restricted": 8, "Classified": 5, "Covert": 3, "Rare Special": 2}
CAT, CASES = {}, {}


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, steamid TEXT UNIQUE, name TEXT, avatar TEXT DEFAULT '', trade_url TEXT DEFAULT '', balance REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS inv(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, item TEXT, status TEXT DEFAULT 'own');
    CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, kind TEXT, info TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, method TEXT, uah REAL, coins REAL, status TEXT DEFAULT 'pending');
    CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, text TEXT, read INTEGER DEFAULT 0, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS skins(name TEXT PRIMARY KEY, rarity TEXT, price INTEGER);
    """)
    if not c.execute("SELECT 1 FROM skins LIMIT 1").fetchone():
        c.executemany("INSERT INTO skins VALUES(?,?,?)", [(n, r, p) for r, l in SEED.items() for n, p in l])
    c.commit()
    c.close()


def load_cat():
    c = db()
    CAT.clear()
    CAT.update({r["name"]: (r["rarity"], r["price"]) for r in c.execute("SELECT * FROM skins")})
    c.close()
    CASES.clear()
    for cid, name, price, kw in CASE_DEFS:
        band = lambda f: sorted((n for n, (r, p) in CAT.items() if price * .1 <= p <= price * 40 and f(n)), key=lambda n: CAT[n][1])
        names = band(lambda n: not kw or any(k in n for k in kw))
        if len(names) < 6: names = band(lambda n: True) or sorted(CAT, key=lambda n: CAT[n][1])
        if len(names) > 30: names = [names[round(i * (len(names) - 1) / 29)] for i in range(30)]
        ps = [CAT[n][1] for n in names]; target = price * .87
        def ev(x): w = [p ** -x for p in ps]; return sum(p * q for p, q in zip(ps, w)) / sum(w)
        lo, hi = 0.0, 8.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if ev(mid) > target: lo = mid
            else: hi = mid
        w = [p ** -hi for p in ps]; s = sum(w)
        CASES[cid] = {"name": name, "price": price, "items": [(n, q / s) for n, q in zip(names, w)]}


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
    c = db(); c.execute("INSERT INTO inv(uid,item) VALUES(?,?)", (uid, item)); c.commit(); c.close()


def inventory(uid):
    c = db(); rows = c.execute("SELECT id,item FROM inv WHERE uid=? AND status='own' ORDER BY id DESC", (uid,)).fetchall(); c.close()
    return [{"id": r["id"], "name": r["item"], "rarity": CAT[r["item"]][0], "price": CAT[r["item"]][1]} for r in rows if r["item"] in CAT]


def withdraw_stats(uid):
    c = db(); rows = c.execute("SELECT item,status FROM inv WHERE uid=? AND status IN ('withdraw','withdrawn')", (uid,)).fetchall(); c.close()
    done = [CAT[r["item"]][1] for r in rows if r["status"] == "withdrawn" and r["item"] in CAT]
    return {"n": len(done), "sum": sum(done), "pending": sum(r["status"] == "withdraw" for r in rows)}


def confirm_deposit(did):
    c = db()
    d = c.execute("SELECT * FROM deposits WHERE id=? AND status='pending'", (did,)).fetchone()
    if not d:
        c.close()
        return None
    c.execute("UPDATE deposits SET status='paid' WHERE id=?", (did,))
    c.execute("UPDATE users SET balance=balance+? WHERE id=?", (d["coins"], d["uid"]))
    c.commit()
    c.close()
    add_log(d["uid"], "topup", f"{d['uah']} UAH -> {d['coins']:.0f}")
    add_note(d["uid"], f"Ваш платіж підтверджено, гроші зараховано: +{d['coins']:.0f} монет")
    return d


def roll_item(case):
    return random.choices([n for n, w in case["items"]], [w for n, w in case["items"]])[0]


def me(): return session.get("uid")


def need_auth(f):
    def w(*a, **k):
        if not me(): return jsonify(error="Увійдіть через Steam", code="auth"), 401
        return f(*a, **k)
    w.__name__ = f.__name__
    return w


@app.route("/")
def index(): return render_template("index.html")


@app.route("/login")
def login():
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
    except Exception: ok = False
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
        cases=[{"id": k, "name": v["name"], "price": v["price"], "n": len(v["items"]), "tier": max((CAT[n][0] for n, w in v["items"]), key=list(WEIGHTS).index)} for k, v in CASES.items()])


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
    win = roll_item(case); give(uid, win)
    strip = [roll_item(case) for _ in range(60)]; strip[50] = win
    add_log(uid, "case", f"{case['name']} -> {win}")
    notify(f"📦 Кейс\n{who(uid)}\n{case['name']} ({case['price']})\nВипало: {win} [{CAT[win][0]}, {CAT[win][1]}]")
    return jsonify(strip=[{"name": n, "rarity": CAT[n][0], "price": CAT[n][1]} for n in strip], win=50)


@app.route("/api/upgrade", methods=["POST"])
@need_auth
def upgrade():
    uid = me(); d = request.json or {}
    try: mult = float(d.get("mult", 0))
    except Exception: mult = 0
    if mult not in (1.5, 2.0, 5.0): return jsonify(error="Невірний множник"), 400
    c = db(); r = c.execute("SELECT item FROM inv WHERE id=? AND uid=? AND status='own'", (d.get("id"), uid)).fetchone()
    if not r or r["item"] not in CAT: c.close(); return jsonify(error="Предмет не знайдено"), 400
    c.execute("UPDATE inv SET status='used' WHERE id=?", (d["id"],)); c.commit(); c.close()
    src = r["item"]; chance = round(95 / mult, 2); roll = random.uniform(0, 100)
    bonus = random.random() < 0.01; nm = random.choice((2, 3)) if bonus else 1; N = 10 if bonus else 0
    neon = bonus and roll < N; won = neon or N <= roll < N + chance; prize = None
    if won:
        t = CAT[src][1] * mult * (nm if neon else 1); prize = min(CAT, key=lambda n: abs(CAT[n][1] - t)); give(uid, prize)
    add_log(uid, "upgrade", f"{src} x{mult}{' NEON x' + str(nm) if bonus else ''} -> {prize or 'програш'}")
    notify(f"⚡ Апгрейд\n{who(uid)}\n{src} x{mult} (шанс {chance}%){' ⚡NEONDROP x' + str(nm) if bonus else ''}\n{'ВИГРАШ → ' + prize if won else 'Програш'}")
    return jsonify(won=won, roll=roll, chance=chance, prize=prize, bonus=bonus, neon=neon, nm=nm, N=N, rarity=prize and CAT[prize][0], price=prize and CAT[prize][1])


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
    coins = round(uah * COINS_PER_UAH)
    c = db(); cur = c.execute("INSERT INTO deposits(uid,method,uah,coins) VALUES(?,?,?,?)", (uid, method, uah, coins)); c.commit(); c.close()
    did = cur.lastrowid
    notify(f"💳 Заявка на поповнення #{did}\n{who(uid)}\nСпосіб: {'картка UAH' if method == 'card' else 'криптовалюта'}\nСума: {uah:.0f} UAH → {coins} монет",
           [[{"text": "✅ Підтвердити", "callback_data": f"dep_ok:{did}"}, {"text": "❌ Відхилити", "callback_data": f"dep_no:{did}"}]])
    return jsonify(id=did, requisites=req, coins=coins)


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


init_db()
load_cat()

if __name__ == "__main__":
    app.run(port=5000)