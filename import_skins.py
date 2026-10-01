"""Імпорт скінів з публічного прайс-листа market.csgo.com. Запускати один раз: python import_skins.py
Ціни: 1 монета = $0.01. Рідкість визначається за ціною (прайс-лист її не містить) — за потреби змініть пороги."""
import sqlite3, requests
from app import DB, init_db

URL = "https://market.csgo.com/api/v2/prices/USD.json"


def rarity(name, c):
    if name.startswith("★") or c >= 10000: return "Rare Special"
    return "Mil-Spec" if c < 60 else "Restricted" if c < 300 else "Classified" if c < 1500 else "Covert"


init_db()
items = requests.get(URL, timeout=90).json()["items"]
rows = {}
for it in items:
    n = it.get("market_hash_name", "")
    try: c = round(float(it["price"]) * 100)
    except Exception: continue
    if " | " in n and c >= 5 and "Sticker" not in n and "Patch" not in n:
        rows[n] = (n, rarity(n, c), c)
con = sqlite3.connect(DB)
con.executemany("INSERT OR REPLACE INTO skins VALUES(?,?,?)", list(rows.values())); con.commit()
print("Імпортовано скінів:", len(rows))