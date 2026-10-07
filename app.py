import os, re, random, sqlite3, requests, hashlib, threading, time, bisect, gzip, json, atexit, base64
import support_ai as sai
from urllib.parse import urlencode, quote, urlparse
from flask import Flask, request, session, jsonify, render_template, redirect, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------- Конфіг ----------
TOKEN = os.getenv("BOT_TOKEN", "8841389440:AAHtgzD5A-Qqwt6P2a1e0KWD8RvLSCf2QoI")  # репозиторій на GitHub має бути PRIVATE; змінна BOT_TOKEN у Render, якщо задана, має пріоритет
ADMINS = [7952645598, 6526861547]
SITE_URL = (os.getenv("SITE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://neondrop-rm5p.onrender.com").rstrip("/")  
PRIMARY_DOMAIN = os.getenv("PRIMARY_DOMAIN", "").strip().lower()
PUBLIC_URL = ("https://" + PRIMARY_DOMAIN) if PRIMARY_DOMAIN else SITE_URL  # посилання для людей (кнопка в боті тощо)
ALLOWED_HOSTS = {h.strip().lower() for h in [PRIMARY_DOMAIN, "www." + PRIMARY_DOMAIN if PRIMARY_DOMAIN else "", urlparse(SITE_URL).hostname or "", *os.getenv("EXTRA_HOSTS", "").split(",")] if h.strip()}


def host_ok(host):
    host = (host or "").split(":")[0].lower()
    return host in ALLOWED_HOSTS or host.endswith(".onrender.com") or host in ("localhost", "127.0.0.1")


def base_url():  # адреса, з якої зайшов гравець: вхід через Steam повертає саме на неї (працює і на домені, і на onrender.com)
    return request.url_root.rstrip("/") if host_ok(request.host) else SITE_URL


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
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=SITE_URL.startswith("https://"), PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 365)

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
    ("neoncity", "Neon City", 150, ["Neon", "Neo-Noir", "Hyper Beast", "Cyrex"]),
    ("rifle", "Rifle Rush", 300, ["AK-47", "M4A4", "M4A1-S", "Galil", "FAMAS", "SG 553", "AUG"]),
    ("heavy", "Heavy Metal", 300, ["Nova", "XM1014", "MAG-7", "Sawed", "M249", "Negev"]),
    ("frost", "Frost Bite", 400, ["Frost", "Ice", "Glacier", "Blue", "Cold", "Winter", "Snow"]),
    ("mix", "Neon Mix", 500, []),
    ("toxic", "Toxic Waste", 700, ["Toxic", "Hazard", "Acid", "Nuclear", "Fallout", "Radiation", "Contamination"]),
    ("awp", "AWP Legends", 1000, ["AWP", "SSG"]),
    ("redline", "Red Alert", 1000, ["Redline", "Asiimov", "Hyper Beast", "Neo-Noir"]),
    ("golden", "Golden Hour", 2000, ["Gold", "Yellow", "Sun", "Amber", "Fire", "Orange"]),
    ("dragon", "Dragon Hoard", 3000, ["Dragon", "Fire Serpent", "Howl", "Medusa"]),
    ("knife", "Blade Vault", 7500, ["★"]),
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
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS support(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, staff INTEGER DEFAULT 0, sender INTEGER, text TEXT, seen INTEGER DEFAULT 0, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS faq(id INTEGER PRIMARY KEY AUTOINCREMENT, q TEXT, a TEXT);
    CREATE TABLE IF NOT EXISTS ai_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, kind TEXT, data TEXT, status TEXT DEFAULT 'pending', ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    """)
    try: c.execute("ALTER TABLE deposits ADD COLUMN promo TEXT DEFAULT ''")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE deposits ADD COLUMN ts TEXT")
    except sqlite3.OperationalError: pass
    for col in ("role TEXT DEFAULT ''", "banned INTEGER DEFAULT 0", "luck_case REAL DEFAULT 1", "luck_up REAL DEFAULT 1", "luck_until REAL DEFAULT 0"):
        try: c.execute("ALTER TABLE users ADD COLUMN " + col)
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


def roll_item(case, luck=1.0):  # luck >1 збільшує шанс предметів дорожчих за ціну кейса
    return random.choices([n for n, w in case["items"]], [w * (luck if CAT.get(n, ("", 0))[1] >= case["price"] else 1) for n, w in case["items"]])[0]


def setting(k, d=""):
    c = db(); r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone(); c.close(); return r["v"] if r else d


def set_setting(k, v):
    c = db(); c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v))); c.commit(); c.close()


def event_luck():  # (множник, секунд лишилось) — глобальний івент «x2 удача»
    left = float(setting("ev_until", "0")) - time.time()
    return (float(setting("ev_mult", "1")), int(left)) if left > 0 else (1.0, 0)


def luck_user(uid):  # персональний буст від адміна: (кейси, апгрейд, до якого часу)
    u = user(uid)
    return (u["luck_case"] or 1.0, u["luck_up"] or 1.0, u["luck_until"] or 0) if u and (not u["luck_until"] or u["luck_until"] > time.time()) else (1.0, 1.0, 0)


def luck_for(uid):
    ev = event_luck()[0]; lc, lu, _ = luck_user(uid); return lc * ev, lu * ev


def wipe_all():  # повне очищення сайту (скіни й картинки лишаються)
    c = db()
    for t in ("users", "inv", "deposits", "notes", "log", "drops", "promos", "promo_uses", "settings"): c.execute("DELETE FROM " + t)
    c.commit(); c.close()
    old = BK["mid"]; BK["mid"] = None; BK["allow_empty"] = True; backup_now(True)  # нове закріплене повідомлення з ПОРОЖНЬОЮ БД
    if TOKEN and old and BK["mid"] != old:  # старий бекап з даними відкріплюємо й видаляємо
        for m in ("unpinChatMessage", "deleteMessage"):
            try: tg(m, chat_id=_bk_chat(), message_id=old)
            except Exception: pass


TG = "https://api.telegram.org"
BK = {"mid": None, "mt": 0, "t": 0, "state": "n/a", "allow_empty": False, "blocked": False, "chat": None, "where": "-"}
GH_TOKEN = os.getenv("GH_TOKEN", ""); GH_REPO = os.getenv("GH_REPO", ""); GH_PATH = os.getenv("GH_PATH", "neondrop.db.gz"); GH_BRANCH = os.getenv("GH_BRANCH", ""); GH_API = os.getenv("GH_API", "https://api.github.com")
GH = {"sha": None}


def gh_on(): return bool(GH_TOKEN and GH_REPO)


def _gh(method, accept="application/vnd.github+json", **kw):
    h = {"Authorization": "Bearer " + GH_TOKEN, "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    return requests.request(method, f"{GH_API}/repos/{GH_REPO}/contents/{GH_PATH}", headers=h, params={"ref": GH_BRANCH} if GH_BRANCH and method == "GET" else None, timeout=60, **kw)


def gh_restore():  # -> bytes або None, якщо бекапу ще немає
    r = _gh("GET")
    if r.status_code == 404: return None
    r.raise_for_status(); GH["sha"] = r.json()["sha"]
    r = _gh("GET", accept="application/vnd.github.raw+json"); r.raise_for_status(); return r.content


def gh_backup(blob):
    body = {"message": "backup " + time.strftime("%Y-%m-%d %H:%M:%S"), "content": base64.b64encode(blob).decode()}
    if GH_BRANCH: body["branch"] = GH_BRANCH
    for attempt in (0, 1):
        if GH["sha"]: body["sha"] = GH["sha"]
        r = _gh("PUT", json=body)
        if r.status_code in (409, 422) and attempt == 0:
            g = _gh("GET"); GH["sha"] = g.json().get("sha") if g.status_code == 200 else None; body.pop("sha", None); continue
        r.raise_for_status(); GH["sha"] = r.json()["content"]["sha"]; return


def _bk_chats(): return [int(os.getenv("BACKUP_CHAT"))] if os.getenv("BACKUP_CHAT") else list(ADMINS)
def _bk_chat(): return BK["chat"] or _bk_chats()[0]


def tg(method, files=None, **data):
    r = requests.post(f"{TG}/bot{TOKEN}/{method}", data=data, files=files, timeout=60).json()
    if not r.get("ok"): raise RuntimeError(r.get("description"))
    return r["result"]


def restore_telegram():  # True — відновлено, None — бекапу немає; виняток — якщо жоден чат не відповів
    err = None; asked = False
    for chat in _bk_chats():
        try: pm = tg("getChat", chat_id=chat).get("pinned_message") or {}; asked = True
        except Exception as e: err = e; continue
        d = pm.get("document") or {}
        if str(d.get("file_name", "")).startswith("neondrop_backup"):
            fp = tg("getFile", file_id=d["file_id"])["file_path"]
            open(DB, "wb").write(gzip.decompress(requests.get(f"{TG}/file/bot{TOKEN}/{fp}", timeout=120).content)); BK.update(mid=pm["message_id"], chat=chat, where="telegram"); return True
    if not asked and err: raise err
    return None


def restore_backup():  # новий інстанс Render без БД: GitHub, інакше Telegram; при збої бекап НЕ перезаписується порожньою БД
    if not (TOKEN or gh_on()): return
    for _ in range(4):
        try:
            if gh_on():
                blob = gh_restore()
                if blob is None: BK["state"] = "restore: на GitHub ще немає бекапу (створиться при першому збереженні)"; return
                open(DB, "wb").write(gzip.decompress(blob)); BK.update(state="restored (github)", where="github"); return
            BK["state"] = "restored (telegram)" if restore_telegram() else "restore: у Telegram немає закріпленого бекапу"; return
        except Exception as e: BK["state"] = "restore error: " + str(e)[:70]; time.sleep(3)
    BK["blocked"] = True


def tg_backup(blob):
    last = None
    for chat in ([BK["chat"]] if BK["chat"] else _bk_chats()):
        try:
            if BK["mid"]:
                try: tg("editMessageMedia", files={"d": ("neondrop_backup.db.gz", blob)}, chat_id=chat, message_id=BK["mid"], media=json.dumps({"type": "document", "media": "attach://d"}))
                except Exception as e:
                    if "not modified" not in str(e): BK["mid"] = None
            if not BK["mid"]:
                m = tg("sendDocument", files={"document": ("neondrop_backup.db.gz", blob)}, chat_id=chat, caption="Автобекап NeonDrop — не видаляйте і не відкріплюйте")
                BK["mid"] = m["message_id"]; tg("pinChatMessage", chat_id=chat, message_id=BK["mid"], disable_notification="true")
            BK["chat"] = chat; return
        except Exception as e: last = e; BK["mid"] = None; BK["chat"] = None
    raise last or RuntimeError("немає чату для бекапу")


def backup_now(force=False):  # знімок БД без скінів → GitHub (основне) або Telegram (резерв)
    if not (TOKEN or gh_on()) or (not force and time.time() - BK["t"] < 20): return
    if BK["blocked"]: BK["state"] = "backup заблоковано: не вдалось відновити (перевірте GH_TOKEN/GH_REPO і перезапустіть)"; return
    BK["t"] = time.time()
    try:
        mt = max(os.path.getmtime(p) for p in (DB, DB + "-wal") if os.path.exists(p))
        if not force and mt <= BK["mt"]: return
        c = db(); users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c.close()
        if not users and not BK["allow_empty"]: return  # порожню БД не пишемо поверх хорошого бекапу
        src = sqlite3.connect(DB, timeout=20); dst = sqlite3.connect(DB + ".snap"); src.backup(dst); src.close()
        dst.executescript("DROP TABLE IF EXISTS skins; DROP TABLE IF EXISTS images;"); dst.commit(); dst.execute("VACUUM"); dst.close()
        blob = gzip.compress(open(DB + ".snap", "rb").read(), 6); os.remove(DB + ".snap"); ok = False; errs = []
        if gh_on():
            try: gh_backup(blob); ok = True; BK["where"] = "github"
            except Exception as e: errs.append("github: " + str(e)[:60])
        if not ok and TOKEN:
            try: tg_backup(blob); ok = True; BK["where"] = "telegram"
            except Exception as e: errs.append("telegram: " + str(e)[:60])
        if not ok: raise RuntimeError("; ".join(errs))
        BK["mt"] = mt; BK["allow_empty"] = False; BK["state"] = f"ok {time.strftime('%H:%M:%S')} → {BK['where']}"
    except Exception as e: BK["state"] = "error: " + str(e)[:110]


atexit.register(lambda: backup_now(True))


def me(): return session.get("uid")


def need_auth(f):
    def w(*a, **k):
        u = user(me()) if me() else None  # сесія є, а користувача немає (БД перестворена) або його заблоковано
        if not u or u["banned"]:
            session.clear(); return jsonify(error="Акаунт заблоковано адміністратором" if u else "Увійдіть через Steam", code="auth"), 401
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
    return f"ok images={len(IMGS)} skins={len(CAT)} bot={'on' if TOKEN else 'NO TOKEN'} webhook={WH['state']} backup={BK['state']}"


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
         "openid.return_to": base_url() + "/auth/steam", "openid.realm": base_url(),
         "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
         "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select"}
    return redirect("https://steamcommunity.com/openid/login?" + urlencode(p))


@app.route("/auth/steam")
def auth_steam():
    a = request.args.to_dict(); a["openid.mode"] = "check_authentication"
    m = re.search(r"/openid/id/(\d+)$", a.get("openid.claimed_id", ""))
    try: ok = "is_valid:true" in requests.post("https://steamcommunity.com/openid/login", data=a, timeout=10).text
    except Exception as e: print("steam verify error:", e); ok = False
    rt = urlparse(a.get("openid.return_to", ""))
    if rt.netloc.lower() != request.host.lower() or not host_ok(rt.netloc): ok = False  # return_to має вести на цей самий (дозволений) домен
    if not (ok and m): print("steam login failed. host =", request.host, "| return_to =", a.get("openid.return_to"))
    if ok and m:
        sid = m.group(1); name, av = "Player " + sid[-4:], ""
        if STEAM_KEY:
            try:
                p = requests.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/", params={"key": STEAM_KEY, "steamids": sid}, timeout=8).json()["response"]["players"][0]
                name, av = p["personaname"][:24], p["avatarfull"]
            except Exception: pass
        c = db(); c.execute("INSERT OR IGNORE INTO users(steamid,name,avatar) VALUES(?,?,?)", (sid, name, av)); c.commit()
        r = c.execute("SELECT id,banned FROM users WHERE steamid=?", (sid,)).fetchone(); c.close()
        if r["banned"]: return redirect("/?banned=1")
        session.permanent = True; session["uid"] = r["id"]; session["sid"] = sid  # вхід на 30 днів, не слітає при закритті браузера
    return redirect("/")


@app.route("/logout")
def logout(): session.clear(); return redirect("/")


@app.route("/api/state")
def state():
    uid = me(); u = user(uid) if uid else None
    if u and u["banned"]: session.clear(); u = None
    ev = event_luck(); lc, lu, lt = luck_user(uid) if u else (1.0, 1.0, 0); an = setting("an_id", "0")
    return jsonify(
        luck=dict(event=dict(mult=ev[0], left=ev[1]), my=None), chat=chat_counts(uid) if u else None,
        announce=dict(id=an, text=setting("an_text", "")) if time.time() - float(an) < 86400 else None,
        me=u and {"id": uid, "name": u["name"], "avatar": u["avatar"], "steamid": u["steamid"], "trade_url": u["trade_url"], "balance": u["balance"], "role": u["role"] or ""},
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


_STEAM = {"lock": threading.Lock(), "miss": {}}


def steam_icon(name):  # запасний варіант: іконка зі Steam Market для скінів, яких немає в базі картинок (по одній за раз)
    if time.time() - _STEAM["miss"].get(name, 0) < 900 or not _STEAM["lock"].acquire(blocking=False): return None
    try:
        r = requests.get("https://steamcommunity.com/market/listings/730/" + quote(name, safe="") + "/render", params={"start": 0, "count": 1, "currency": 1, "format": "json"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        url = "https://community.cloudflare.steamstatic.com/economy/image/" + next(iter(r.json()["assets"]["730"]["2"].values()))["icon_url"] + "/360fx360f"
        c = db(); c.execute("INSERT OR REPLACE INTO images VALUES(?,?)", (img_key(name), url)); c.commit(); c.close(); IMGS[img_key(name)] = url
        return url
    except Exception: _STEAM["miss"][name] = time.time(); return None
    finally: _STEAM["lock"].release()


def fill_missing():  # докачує картинки для всіх скінів із кейсів, яких немає в базі
    for n in sorted({n for v in list(CASES.values()) for n, w in v["items"]}):
        if img_key(n) not in IMGS: steam_icon(n); time.sleep(4)


@app.route("/img")
def img():
    n = request.args.get("n", ""); u = IMGS.get(img_key(n)) or steam_icon(n)
    r = redirect(u or "https://cdn.csgo.com/item/" + quote(n, safe="") + "/300.png", 302)
    r.headers["Cache-Control"] = "public, max-age=86400" if u else "no-cache"; return r


@app.route("/api/targets")
def targets():  # скіни, які можна отримати в апгрейді (шанс 1–90%)
    try: sp = float(request.args.get("price", 0)); p = float(request.args.get("p", 0))
    except Exception: return jsonify([])
    if sp <= 0: return jsonify([])
    q = (request.args.get("q") or "").lower().split()
    rows = [(n, v) for n, v in CAT.items() if sp * 95 / 75 <= v[1] <= sp * 950 and all(w in n.lower() for w in q)]
    if 0 < p <= 75: tp = sp * 95 / p; rows.sort(key=lambda x: abs(x[1][1] - tp))
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


# ===================== ролі, чат підтримки, ШІ-агент =====================
ROLES = {"vip": "VIP", "youtuber": "YT", "support": "Support", "admin": "Admin", "owner": "Owner"}
STAFF = ("support", "admin", "owner")
LAST_CHAT = {}; AI_USED = {}
AI_ACTIONS = ("give_balance", "set_nick", "clear_trade_url", "send_note", "confirm_deposit")


def role_of(uid):
    u = user(uid) if uid else None
    return (u["role"] or "") if u else ""


def set_role(uid, role):
    if role != "" and role not in ROLES: return False
    c = db(); n = c.execute("UPDATE users SET role=? WHERE id=?", (role, uid)).rowcount; c.commit(); c.close(); return bool(n)


_REFS = ("inv", "deposits", "notes", "log", "drops", "promo_uses", "support")


def _remap(c, a, b):
    c.execute("UPDATE users SET id=? WHERE id=?", (b, a))
    for t in _REFS: c.execute(f"UPDATE {t} SET uid=? WHERE uid=?", (b, a))
    c.execute("UPDATE support SET sender=? WHERE sender=?", (b, a))


def change_id(old, new):  # -> (помилка | None, ім'я гравця, з яким помінялись | None); зайнятий ID = акаунти міняються місцями
    c = db()
    try:
        if not c.execute("SELECT 1 FROM users WHERE id=?", (old,)).fetchone(): return "Гравця з таким ID немає", None
        if old == new: return None, None
        other = c.execute("SELECT name FROM users WHERE id=?", (new,)).fetchone()
        if other: tmp = -(2 * 10**12 + random.randint(1, 10**9)); _remap(c, old, tmp); _remap(c, new, old); _remap(c, tmp, new)
        else: _remap(c, old, new)
        c.commit(); return None, (other["name"] if other else None)
    except Exception as e: c.rollback(); return "Помилка: " + str(e)[:60], None
    finally: c.close()


@app.before_request
def canonical_host():
    if PRIMARY_DOMAIN and request.method == "GET" and not request.path.startswith(("/api/", "/tg/", "/health", "/static/", "/img")):
        host = request.host.split(":")[0].lower()
        if host != PRIMARY_DOMAIN and (host.endswith(".onrender.com") or host == "www." + PRIMARY_DOMAIN):
            return redirect("https://" + PRIMARY_DOMAIN + request.full_path.rstrip("?"), 301)


@app.before_request
def sync_session():  # якщо ID гравця змінили або БД відновили — шукаємо його за steamid, щоб не вилітати з акаунта
    if session.get("sid") and session.get("uid") and request.path.startswith("/api/"):
        u = user(session["uid"])
        if not u or u["steamid"] != session["sid"]:
            c = db(); r = c.execute("SELECT id FROM users WHERE steamid=?", (session["sid"],)).fetchone(); c.close()
            if r: session["uid"] = r["id"]


def staff_reply(uid, text, sender=0):  # sender: 0 — адмін із Telegram, -1 — ШІ, >0 — співробітник із сайту
    c = db(); c.execute("INSERT INTO support(uid,staff,sender,text,seen) VALUES(?,1,?,?,0)", (uid, sender, str(text)[:800])); c.commit(); c.close()


def msgs_of(uid):
    c = db(); rows = c.execute("SELECT s.staff,s.text,s.ts,s.sender,u.name,u.role FROM support s LEFT JOIN users u ON u.id=s.sender WHERE s.uid=? ORDER BY s.id DESC LIMIT 100", (uid,)).fetchall(); c.close()
    out = []
    for r in reversed(rows):
        who, role = ("ШІ-підтримка", "ai") if r["sender"] == -1 else ("Підтримка", "support") if r["sender"] == 0 and r["staff"] else (r["name"] or "Гравець", r["role"] or "")
        out.append({"staff": r["staff"], "text": r["text"], "ts": r["ts"], "who": who, "role": role})
    return out


def human_recent(uid):
    c = db(); r = c.execute("SELECT 1 FROM support WHERE uid=? AND staff=1 AND sender!=-1 AND ts>datetime('now','-30 minutes')", (uid,)).fetchone(); c.close(); return bool(r)


def last_player_text(uid):
    c = db(); r = c.execute("SELECT text FROM support WHERE uid=? AND staff=0 ORDER BY id DESC LIMIT 1", (uid,)).fetchone(); c.close(); return r["text"] if r else ""


def tickets_list(limit=15):
    c = db(); rows = c.execute("SELECT s.uid AS uid,u.name AS name,u.role AS role,(SELECT text FROM support WHERE uid=s.uid ORDER BY id DESC LIMIT 1) AS last,SUM(CASE WHEN s.staff=0 AND s.seen=0 THEN 1 ELSE 0 END) AS unread,MAX(s.id) AS mid FROM support s LEFT JOIN users u ON u.id=s.uid GROUP BY s.uid ORDER BY mid DESC LIMIT ?", (limit,)).fetchall(); c.close(); return rows


def chat_counts(uid):
    c = db(); un = c.execute("SELECT COUNT(*) FROM support WHERE uid=? AND staff=1 AND seen=0", (uid,)).fetchone()[0]
    sn = c.execute("SELECT COUNT(*) FROM support WHERE staff=0 AND seen=0").fetchone()[0] if role_of(uid) in STAFF else 0; c.close()
    return {"unread": un, "staff_new": sn}


def notify_support(uid, text):
    u = user(uid); notify(f"💬 Підтримка · ID {uid} {u['name'] if u else ''}\n{text}", [[{"text": "✍️ Відповісти", "callback_data": f"sr:{uid}"}]])


def ai_enabled(): return setting("ai_on", "1") == "1"  # власний ШІ вбудований у сайт — ключі й сторонні сервіси не потрібні


def ai_ctx(uid):
    u = user(uid); c = db()
    inv = c.execute("SELECT COUNT(*) FROM inv WHERE uid=? AND status='own'", (uid,)).fetchone()[0]
    wd = c.execute("SELECT COUNT(*) FROM inv WHERE uid=? AND status='withdraw'", (uid,)).fetchone()[0]
    deps = c.execute("SELECT id,uah,status,CASE WHEN ts IS NULL THEN 999 ELSE CAST((julianday('now')-julianday(ts))*1440 AS INTEGER) END AS age FROM deposits WHERE uid=? ORDER BY id DESC LIMIT 5", (uid,)).fetchall(); c.close()
    return {"id": uid, "balance": u["balance"], "inv": inv, "wd": wd, "trade": bool(u["trade_url"]), "rate": COINS_PER_UAH, "deps": [dict(d) for d in deps]}


def task_new(uid, kind, data):
    c = db(); i = c.execute("INSERT INTO ai_tasks(uid,kind,data) VALUES(?,?,?)", (uid, kind, json.dumps(data, ensure_ascii=False))).lastrowid; c.commit(); c.close(); return i


def ai_execute(uid, d):  # лише білий список дій, лише після дозволу адміна
    try:
        a = d.get("action")
        if a == "set_nick":
            c = db(); c.execute("UPDATE users SET name=? WHERE id=?", (str(d.get("text") or "")[:24], uid)); c.commit(); c.close(); return "нік змінено"
        if a == "clear_trade_url":
            c = db(); c.execute("UPDATE users SET trade_url='' WHERE id=?", (uid,)); c.commit(); c.close(); return "трейд-посилання скинуто"
        if a == "send_note": add_note(uid, str(d.get("text") or "")[:300]); return "повідомлення надіслано"
        if a == "give_balance": amt = max(-10**6, min(10**6, float(d.get("amount") or 0))); adjust_balance(uid, amt); return f"баланс {amt:+.0f}"
        if a == "confirm_deposit":
            c = db(); r = c.execute("SELECT uid FROM deposits WHERE id=?", (int(d.get("deposit_id") or 0),)).fetchone(); c.close()
            if not r or r["uid"] != uid: return "платіж не знайдено"
            return "платіж підтверджено, монети нараховано" if confirm_deposit(int(d["deposit_id"])) else "платіж уже оброблено"
        return "невідома дія"
    except Exception as e: return "помилка: " + str(e)[:80]


def ai_allowed(uid):
    d = time.strftime("%Y%m%d"); day, n = AI_USED.get(uid, (d, 0)); n = 0 if day != d else n; AI_USED[uid] = (d, n + 1); return n < 60


def ai_reply(uid):
    try:
        text = last_player_text(uid)
        if not ai_allowed(uid): return notify_support(uid, "(ліміт ШІ на сьогодні) " + text)
        c = db(); faq = [(r["q"], r["a"]) for r in c.execute("SELECT q,a FROM faq")]; c.close()
        r = sai.answer(text, ai_ctx(uid), faq); nick = user(uid)["name"]; staff_reply(uid, r["text"], -1)
        if r["kind"] == "human": notify_support(uid, text)
        elif r["kind"] == "ask":
            t = task_new(uid, "ask", {"q": text})
            notify(f"🤖 ШІ-підтримка не знає відповіді\nГравець ID {uid} ({nick})\n❓ {text}", [[{"text": "✍️ Відповісти", "callback_data": f"aa:{t}"}]])
        elif r["kind"] == "act":
            act = dict(r["action"], q=text); t = task_new(uid, "act", act)
            notify(f"🤖 ШІ-підтримка просить дозвіл\nГравець ID {uid} ({nick})\nДія: {act['action']} " + json.dumps({k: v for k, v in act.items() if k in ("text", "deposit_id")}, ensure_ascii=False) + f"\nПричина: {act.get('reason', '')}\nПовідомлення гравця: {text}",
                   [[{"text": "✅ Дозволити", "callback_data": f"ao:{t}"}, {"text": "❌ Відхилити", "callback_data": f"an:{t}"}], [{"text": "✍️ Відповісти гравцю", "callback_data": f"aa:{t}"}]])
    except Exception as e:
        print("ai error:", e); notify_support(uid, "(ШІ недоступний) " + last_player_text(uid))


def ai_decide(tid, decision, text=""):  # decision: ok | no | answer
    c = db(); t = c.execute("SELECT * FROM ai_tasks WHERE id=? AND status='pending'", (tid,)).fetchone()
    if not t: c.close(); return "Вже оброблено"
    d = json.loads(t["data"]); uid = t["uid"]; L = sai.lang(d.get("q", ""))
    if decision == "answer": d["a"] = text
    c.execute("UPDATE ai_tasks SET status=?, data=? WHERE id=?", (decision, json.dumps(d, ensure_ascii=False), tid)); c.commit(); c.close()
    if decision == "ok" and t["kind"] == "act": res = ai_execute(uid, d); msg = sai.T(L, f"✅ Адміністрація схвалила запит. Результат: {res}.", f"✅ Администрация одобрила запрос. Результат: {res}.")
    elif decision == "ok": msg = sai.T(L, "✅ Адміністрація схвалила запит.", "✅ Администрация одобрила запрос.")
    elif decision == "no": msg = sai.T(L, "На жаль, адміністрація відхилила цей запит. Якщо є питання — напишіть ще.", "К сожалению, администрация отклонила этот запрос. Если есть вопросы — напишите ещё.")
    else: msg = sai.T(L, "Відповідь адміністрації: ", "Ответ администрации: ") + text
    staff_reply(uid, msg, -1); return "✅ Виконано" if decision == "ok" else "Готово"


def ai_learn(tid):  # адмін натиснув «Запам'ятати» — наступного разу ШІ відповість сам
    c = db(); t = c.execute("SELECT data FROM ai_tasks WHERE id=?", (tid,)).fetchone(); d = json.loads(t["data"]) if t else {}
    if not d.get("q") or not d.get("a"): c.close(); return "Нічого запам'ятовувати"
    c.execute("INSERT INTO faq(q,a) VALUES(?,?)", (d["q"][:300], d["a"][:800])); c.commit(); c.close(); return "💾 Запам'ятав: на схожі питання відповідатиму так само"


def faq_rows(limit=15):
    c = db(); r = c.execute("SELECT id,q,a FROM faq ORDER BY id DESC LIMIT ?", (limit,)).fetchall(); c.close(); return r


def faq_del(fid):
    c = db(); c.execute("DELETE FROM faq WHERE id=?", (fid,)); c.commit(); c.close()


@app.route("/api/chat", methods=["GET", "POST"])
@need_auth
def chat():
    uid = me()
    if request.method == "POST":
        t = ((request.json or {}).get("text") or "").strip()[:500]
        if not t: return jsonify(error="Порожнє повідомлення"), 400
        if time.time() - LAST_CHAT.get(uid, 0) < 1: return jsonify(error="Не так швидко"), 429
        LAST_CHAT[uid] = time.time(); c = db(); c.execute("INSERT INTO support(uid,staff,sender,text) VALUES(?,0,?,?)", (uid, uid, t)); c.commit(); c.close()
        threading.Thread(target=ai_reply if ai_enabled() and not human_recent(uid) else notify_support, args=(uid,) if ai_enabled() and not human_recent(uid) else (uid, t), daemon=True).start()
    c = db(); c.execute("UPDATE support SET seen=1 WHERE uid=? AND staff=1", (uid,)); c.commit(); c.close()
    return jsonify(msgs_of(uid))


def _staff_only():
    return role_of(me()) in STAFF


@app.route("/api/staff/tickets")
@need_auth
def staff_tickets():
    if not _staff_only(): return jsonify(error="Немає доступу"), 403
    return jsonify([{"uid": r["uid"], "name": r["name"] or "?", "role": r["role"] or "", "last": (r["last"] or "")[:60], "unread": r["unread"]} for r in tickets_list(40)])


@app.route("/api/staff/thread")
@need_auth
def staff_thread():
    if not _staff_only(): return jsonify(error="Немає доступу"), 403
    uid = int(request.args.get("uid", 0)); c = db(); c.execute("UPDATE support SET seen=1 WHERE uid=? AND staff=0", (uid,)); c.commit(); c.close(); return jsonify(msgs_of(uid))


@app.route("/api/staff/reply", methods=["POST"])
@need_auth
def staff_reply_api():
    if not _staff_only(): return jsonify(error="Немає доступу"), 403
    d = request.json or {}; t = (d.get("text") or "").strip()[:500]; me_id = me()
    if not t: return jsonify(error="Порожнє повідомлення"), 400
    if t.startswith("/"):  # команди керування ролями — лише власник: /admin ID, /support ID, /vip ID, /youtuber ID, /user ID
        if role_of(me_id) != "owner": return jsonify(error="Команди доступні лише власнику"), 403
        p = t.split(); role = {"/admin": "admin", "/support": "support", "/vip": "vip", "/youtuber": "youtuber", "/user": ""}.get(p[0].lower())
        if role is None or len(p) != 2 or not p[1].isdigit(): return jsonify(error="Команди: /admin ID, /support ID, /vip ID, /youtuber ID, /user ID"), 400
        if role_of(int(p[1])) == "owner": return jsonify(error="Роль власника змінюється лише в Telegram-боті"), 403
        return (jsonify(ok=True, msg=f"ID {p[1]} → {role or 'гравець'}") if set_role(int(p[1]), role) else (jsonify(error="Гравця з таким ID немає"), 404))
    uid = int(d.get("uid") or 0)
    if not user(uid): return jsonify(error="Гравця немає"), 404
    staff_reply(uid, t, me_id); return jsonify(ok=True)


@app.route("/api/feed")
def feed():
    c = db(); rows = c.execute("SELECT d.id,d.item,d.price,d.case_name,u.name,u.role FROM drops d JOIN users u ON u.id=d.uid WHERE d.show_at<=datetime('now') AND d.price>=200 ORDER BY d.id DESC LIMIT 12").fetchall(); c.close()
    return jsonify([{"id": r["id"], "name": r["item"], "rarity": CAT[r["item"]][0], "price": r["price"], "case": r["case_name"], "nick": r["name"], "role": r["role"] or ""} for r in rows if r["item"] in CAT])


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
    return jsonify(name=c["name"], price=c["price"], items=[{"name": n, "rarity": CAT[n][0], "price": CAT[n][1]} for n, w in sorted(c["items"], key=lambda x: -CAT[x[0]][1])])


@app.route("/api/notes/read", methods=["POST"])
@need_auth
def notes_read():
    c = db(); c.execute("UPDATE notes SET read=1 WHERE uid=?", (me(),)); c.commit(); c.close()
    return jsonify(ok=True)


@app.route("/api/open", methods=["POST"])
@need_auth
def open_case():
    uid = me(); d = request.json or {}; case = CASES.get(d.get("case"))
    if not case: return jsonify(error="Кейс не знайдено"), 400
    try: n = max(1, min(5, int(d.get("count") or 1)))  # до 5 кейсів за раз
    except Exception: n = 1
    if not spend(uid, case["price"] * n): return jsonify(error="Недостатньо балансу. Поповніть рахунок."), 400
    luck = luck_for(uid)[0]; opens = []
    for _ in range(n):
        win = roll_item(case, luck); inv_id = give(uid, win)
        if CAT[win][1] >= 200:  # «Топ дроп» зліва — від 200 монет  # крутий дроп → у стрічку зліва (з затримкою, щоб не спойлерити анімацію)
            c = db(); c.execute("INSERT INTO drops(uid,item,case_name,price,show_at) VALUES(?,?,?,?,datetime('now','+9 seconds'))", (uid, win, case["name"], CAT[win][1])); c.commit(); c.close()
        strip = [roll_item(case) for _ in range(60)]; strip[50] = win
        opens.append(dict(strip=[{"name": x, "rarity": CAT[x][0], "price": CAT[x][1]} for x in strip], win=50, inv=inv_id))
        add_log(uid, "case", f"{case['name']} -> {win}")
    notify(f"📦 Кейс x{n}\n{who(uid)}\n{case['name']} ({case['price']})\n" + "\n".join(f"{o['strip'][50]['name']} [{o['strip'][50]['price']}]" for o in opens))
    return jsonify(opens=opens, strip=opens[0]["strip"], win=50, inv=opens[0]["inv"])


@app.route("/api/upgrade", methods=["POST"])
@need_auth
def upgrade():
    uid = me(); d = request.json or {}; tgt = d.get("target")
    if tgt not in CAT: return jsonify(error="Оберіть скін, який хочете отримати"), 400
    c = db(); r = c.execute("SELECT item FROM inv WHERE id=? AND uid=? AND status='own'", (d.get("id"), uid)).fetchone()
    if not r or r["item"] not in CAT: c.close(); return jsonify(error="Предмет не знайдено"), 400
    src = r["item"]; sp, tp = CAT[src][1], CAT[tgt][1]; chance = round(95 * sp / tp, 2)
    if not 0.1 <= chance <= 75: c.close(); return jsonify(error="Шанс має бути від 0.1% до 75%"), 400
    if not c.execute("UPDATE inv SET status='used' WHERE id=? AND status='own'", (d["id"],)).rowcount: c.close(); return jsonify(error="Предмет не знайдено"), 400
    c.commit(); c.close()
    roll = random.uniform(0, 100); eff = min(95.0, chance * luck_for(uid)[1])  # персональна/івентова удача
    bonus = random.random() < 0.01; nm = random.choice((2, 3)) if bonus else 1; N = 10 if bonus else 0  # NeonDrop: 1% шанс, неоновий сектор 10% колеса
    neon = bonus and roll < N; won = neon or N <= roll < N + eff
    vis = roll if neon else random.uniform(N, N + chance) if won else random.uniform(N + chance, 100)  # стрілка завжди збігається з результатом, а видимий шанс — звичайний (без множника)
    prize = None; inv_id = None
    if won:
        prize = min(CAT, key=lambda n: abs(CAT[n][1] - tp * nm)) if neon else tgt; inv_id = give(uid, prize)
    add_log(uid, "upgrade", f"{src} -> {tgt} ({chance}%){' NEON x' + str(nm) if bonus else ''}: {prize or 'програш'}")
    notify(f"⚡ Апгрейд\n{who(uid)}\n{src} → {tgt} (шанс {chance}%){' ⚡NEONDROP x' + str(nm) if bonus else ''}\n{'ВИГРАШ → ' + prize if won else 'Програш'}")
    return jsonify(won=won, roll=vis, chance=round(chance, 2), prize=prize, bonus=bonus, neon=neon, nm=nm, N=N, rarity=prize and CAT[prize][0], price=prize and CAT[prize][1], inv=inv_id)


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
    c = db(); cur = c.execute("INSERT INTO deposits(uid,method,uah,coins,promo,ts) VALUES(?,?,?,?,?,datetime('now'))", (uid, method, uah, coins, code if pct else "")); did = cur.lastrowid
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


if (TOKEN or gh_on()) and not os.environ.get("ND_NO_BG"):  # новий інстанс Render: порожня/відсутня БД → відновлюємо з Telegram
    fresh = not os.path.exists(DB)
    if not fresh:  # БД з таблицею гравців (навіть порожньою після «Очистити сайт») НЕ чіпаємо — інакше поверталися б старі дані
        try: _c = sqlite3.connect(DB); _c.execute("SELECT 1 FROM users LIMIT 1"); _c.close()
        except Exception: fresh = True
    if fresh: restore_backup()
init_db(); load_cat(); load_images()


def find_backup_mid():  # після перезапуску дізнаємось id закріпленого бекапу в Telegram, щоб редагувати його, а не створювати нові
    for chat in _bk_chats():
        try:
            pm = tg("getChat", chat_id=chat).get("pinned_message") or {}
            if str((pm.get("document") or {}).get("file_name", "")).startswith("neondrop_backup"): BK["mid"] = BK["mid"] or pm["message_id"]; BK["chat"] = BK["chat"] or chat; return
        except Exception as e: print("find_backup_mid:", e)


def _boot_bot():
    time.sleep(3)
    if not TOKEN: print("BOT_TOKEN не задано — бот вимкнено"); return
    try:
        import bot as tgbot
        if SITE_URL.startswith("https://"): ensure_webhook(True); print("webhook:", WH["state"])
        else: tgbot.bot.remove_webhook(); tgbot.bot.infinity_polling(skip_pending=True)
    except Exception as e: print("bot error:", e)


def _heavy():  # скіни й картинки — довгі задачі в окремому потоці (бекап від них НЕ залежить)
    time.sleep(5)
    try:
        c = db(); n = c.execute("SELECT COUNT(*) FROM skins").fetchone()[0]; c.close()
        if n < 200:
            import import_skins  # виконує імпорт при імпорті
            load_cat()
    except Exception as e: print("import_skins failed:", e)
    try:
        if len(IMGS) < 1000: print("images loaded:", fetch_images())
    except Exception as e: print("images failed:", e)
    try: fill_missing()
    except Exception as e: print("fill_missing failed:", e)


def _guard():  # сторожок: бекап БД у Telegram кожні ~20 с (якщо були зміни) і перевірка webhook
    time.sleep(6)
    if TOKEN and not gh_on() and not BK["mid"]: find_backup_mid()
    while True:
        try: backup_now(); ensure_webhook()
        except Exception as e: print("guard error:", e)
        time.sleep(10)


if not os.environ.get("ND_STARTED") and not os.environ.get("ND_NO_BG"):
    os.environ["ND_STARTED"] = "1"
    for _f in (_boot_bot, _heavy, _guard): threading.Thread(target=_f, daemon=True).start()
if __name__ == "__main__":
    app.run(port=5000)
