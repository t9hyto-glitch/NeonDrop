import time
import telebot
from telebot import types
from app import ADMINS, TOKEN, PUBLIC_URL as SITE_URL, db, notify, confirm_deposit, add_note, set_role, ROLES, change_id, staff_reply, tickets_list, ai_decide, ai_learn, faq_rows, faq_del, gh_on, set_setting, setting, event_luck, wipe_all, backup_now, BK, adjust_balance, promo_save, promo_del, promos_list, release_promo, CAT, give, add_log

bot = telebot.TeleBot(TOKEN)
B = types.InlineKeyboardButton


def menu():
    k = types.InlineKeyboardMarkup(row_width=2)
    k.add(B("📊 Статистика", callback_data="st"), B("👥 Гравці", callback_data="us"))
    k.add(B("💳 Поповнення", callback_data="dp"), B("📤 Виводи", callback_data="wd"))
    k.add(B("🎟 Промокоди", callback_data="pr"), B("💰 Баланс гравця", callback_data="bal"))
    k.add(B("👤 Акаунт за ID", callback_data="acc"), B("🍀 Удача / івент", callback_data="lk"))
    k.add(B("📢 Повідомлення всім", callback_data="bc"), B("💾 Бекап", callback_data="bk"))
    k.add(B("💬 Підтримка", callback_data="tk"), B("🤖 ШІ-підтримка", callback_data="ai"))
    k.add(B("📜 Журнал", callback_data="lg"), B("⚠️ Очистити сайт", callback_data="wp"))
    if SITE_URL.startswith("https://"): k.add(B("🌐 Сайт", url=SITE_URL))  # Telegram не приймає http/localhost у кнопках
    return k


def back():
    k = types.InlineKeyboardMarkup(); k.add(B("⬅️ Меню", callback_data="menu")); return k


HELP_BAL = "Надішліть: ID суму\n(мінус — забрати)\nНапр.: 12 500 або 12 -300"
HELP_PROMO = "Надішліть: КОД відсоток [ліміт]\nНапр.: NEON20 20 100 — бонус +20% до поповнення, 100 використань (0 або без ліміту — безліміт)"


def do_balance(t):
    try: i, x = (t or "").replace(",", ".").split()[:2]; i = int(i); x = float(x)
    except Exception: return HELP_BAL
    r = adjust_balance(i, x)
    return f"✅ Гравець ID {i}: {x:+.0f}. Новий баланс: {r:.0f}" if r is not None else "Гравця з таким ID немає"


def do_promo(t):
    try:
        p = (t or "").split(); code = p[0].upper(); pct = float(p[1]); mx = int(p[2]) if len(p) > 2 else 0
        assert code.isalnum() and 0 < pct <= 500 and mx >= 0
    except Exception: return HELP_PROMO
    promo_save(code, pct, mx); return f"✅ Промокод {code}: +{pct:g}% до поповнення, ліміт {mx or '∞'}"


@bot.message_handler(commands=["give", "promo", "delpromo"], func=lambda m: m.from_user.id in ADMINS)
def cmds(m):
    cmd, _, arg = m.text.partition(" "); cmd = cmd.split("@")[0]
    if cmd == "/give": r = do_balance(arg)
    elif cmd == "/promo": r = do_promo(arg)
    else: r = "🗑 Видалено" if promo_del(arg.strip().upper()) else "Такого промокоду немає"
    bot.send_message(m.chat.id, r)


def ask(c, text, fn):
    m = bot.send_message(c.message.chat.id, text); bot.register_next_step_handler(m, lambda mm: bot.send_message(mm.chat.id, fn(mm.text)))


PICK = {}


def broadcast(text):  # нотатка кожному гравцю + банер на сайті
    c = db(); ids = [r[0] for r in c.execute("SELECT id FROM users")]; c.close()
    for i in ids: add_note(i, text[:300])
    set_setting("an_text", text[:300]); set_setting("an_id", int(time.time())); return len(ids)


def start_event(mult, minutes):
    set_setting("ev_mult", mult); set_setting("ev_until", time.time() + minutes * 60)
    broadcast(f"Івент! x{mult:g} удача на {minutes} хв — відкривайте кейси й робіть апгрейди!")


def set_luck(uid, t):
    p = t.replace(",", ".").split()
    try:
        if p == ["0"]: lc = lu = 1.0; mn = 0
        else: lc, lu = (min(1000.0, max(1.0, float(x))) for x in p[:2]); mn = int(p[2]) if len(p) > 2 else 0
    except Exception: return "Формат: КЕЙСИ АПГРЕЙД ХВИЛИНИ, напр. 2 1.5 60"
    c = db(); c.execute("UPDATE users SET luck_case=?, luck_up=?, luck_until=? WHERE id=?", (lc, lu, time.time() + mn * 60 if mn else 0, uid)); c.commit(); c.close(); add_log(uid, "admin", f"luck {lc}/{lu}")
    return "🍀 Удачу скинуто" if (lc, lu) == (1.0, 1.0) else f"🍀 Кейси x{lc:g}, апгрейд x{lu:g}, " + (f"{mn} хв" if mn else "без ліміту")


def set_user(uid, col, val):  # col — лише фіксовані імена зі списку нижче
    assert col in ("name", "trade_url", "banned", "balance")
    c = db(); c.execute(f"UPDATE users SET {col}=? WHERE id=?", (val, uid)); c.commit(); c.close()


def card(uid):
    c = db(); u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u: c.close(); return None, 0
    n = c.execute("SELECT COUNT(*) FROM inv WHERE uid=? AND status='own'", (uid,)).fetchone()[0]
    dep = c.execute("SELECT COALESCE(SUM(uah),0) FROM deposits WHERE uid=? AND status='paid'", (uid,)).fetchone()[0]
    wd = [r[0] for r in c.execute("SELECT item FROM inv WHERE uid=? AND status='withdrawn'", (uid,))]; c.close()
    return (f"👤 ID {uid} · {u['name']}{' · 🎖 ' + u['role'] if u['role'] else ''}{' · 🚫 ЗАБЛОКОВАНО' if u['banned'] else ''}\nSteam: https://steamcommunity.com/profiles/{u['steamid']}\n💰 Баланс: {u['balance']:.0f}\n🎒 Предметів: {n}\n💳 Поповнено: {dep:.0f} UAH\n📤 Виведено: {len(wd)} шт. на {sum(CAT[i][1] for i in wd if i in CAT)}\n🔗 Трейд: {u['trade_url'] or '—'}"), u["banned"]


def show_card(chat, uid):
    t, banned = card(uid)
    if not t: return bot.send_message(chat, "Гравця з таким ID немає")
    k = types.InlineKeyboardMarkup(row_width=2)
    k.add(B("💰 Баланс ±", callback_data=f"ub:{uid}"), B("🧹 Обнулити баланс", callback_data=f"uz:{uid}"))
    k.add(B("🎒 Інвентар", callback_data=f"ui:{uid}"), B("🎁 Видати скін", callback_data=f"ug:{uid}"))
    k.add(B("✏️ Змінити нік", callback_data=f"un:{uid}"), B("✉️ Повідомлення", callback_data=f"um:{uid}"))
    k.add(B("🔗 Скинути трейд-URL", callback_data=f"ut:{uid}"), B("✅ Розбанити" if banned else "🚫 Забанити", callback_data=f"uk:{uid}"))
    k.add(B("🍀 Удача акаунта", callback_data=f"ul:{uid}"), B("🗑 Видалити акаунт", callback_data=f"ux:{uid}"))
    k.add(B("🎖 Роль", callback_data=f"ur:{uid}"), B("🆔 Змінити ID", callback_data=f"uc:{uid}"))
    k.add(B("⬅️ Меню", callback_data="menu"))
    bot.send_message(chat, t, reply_markup=k, disable_web_page_preview=True)


def acc_op(c, d):  # керування акаунтом гравця
    op, _, rest = d.partition(":"); p = rest.split(":"); uid = int(p[0]); chat = c.message.chat.id; con = db()
    def ask2(text, fn):
        m = bot.send_message(chat, text); bot.register_next_step_handler(m, lambda mm: (bot.send_message(chat, fn(mm.text or "")), show_card(chat, uid)))
    try:
        if op == "u": show_card(chat, uid)
        elif op == "ub": ask2("💰 Сума (мінус — забрати), напр. 500 або -300:", lambda t: do_balance(f"{uid} {t.strip()}"))
        elif op == "uz": set_user(uid, "balance", 0); add_log(uid, "admin", "balance=0"); bot.send_message(chat, "🧹 Баланс обнулено"); show_card(chat, uid)
        elif op == "ui":
            rows = con.execute("SELECT id,item FROM inv WHERE uid=? AND status='own' ORDER BY id DESC LIMIT 25", (uid,)).fetchall()
            k = types.InlineKeyboardMarkup(row_width=1)
            for r in rows: k.add(B(f"🗑 {r['item'][:40]} · {CAT.get(r['item'], ('', 0))[1]}", callback_data=f"ud:{uid}:{r['id']}"))
            k.add(B("⬅️ Картка", callback_data=f"u:{uid}"))
            bot.send_message(chat, "🎒 Інвентар (натисніть, щоб видалити предмет):" if rows else "🎒 Інвентар порожній.", reply_markup=k)
        elif op == "ud":
            con.execute("UPDATE inv SET status='removed' WHERE id=? AND uid=? AND status='own'", (int(p[1]), uid)); con.commit(); add_log(uid, "admin", f"remove item {p[1]}")
            acc_op(c, f"ui:{uid}")
        elif op == "ug":
            def find(t):
                w = t.lower().split(); res = [n for n in CAT if w and all(x in n.lower() for x in w)][:8]
                if not res: return bot.send_message(chat, "Нічого не знайдено")
                PICK[chat] = res; k = types.InlineKeyboardMarkup(row_width=1)
                for i, n in enumerate(res): k.add(B(f"{n[:45]} · {CAT[n][1]}", callback_data=f"us:{uid}:{i}"))
                bot.send_message(chat, "🎁 Оберіть скін:", reply_markup=k)
            m = bot.send_message(chat, "🎁 Введіть частину назви скіна (напр. redline ft):"); bot.register_next_step_handler(m, lambda mm: find(mm.text or ""))
        elif op == "us":
            n = PICK[chat][int(p[1])]; give(uid, n); add_note(uid, f"Адміністратор видав вам скін: {n}"); add_log(uid, "admin", f"give {n}")
            bot.send_message(chat, f"🎁 Видано: {n}"); show_card(chat, uid)
        elif op == "ur":
            k = types.InlineKeyboardMarkup(row_width=3); k.add(*[B(l, callback_data=f"urs:{uid}:{r or '-'}") for r, l in (("", "Без ролі"),) + tuple(ROLES.items())])
            bot.send_message(chat, f"🎖 Оберіть роль для ID {uid}:", reply_markup=k)
        elif op == "urs": r = "" if p[1] == "-" else p[1]; set_role(uid, r); add_log(uid, "admin", f"role={r}"); show_card(chat, uid)
        elif op == "uc":
            m = bot.send_message(chat, "🆔 Новий ID (число):")
            def done(mm):
                t = (mm.text or "").strip()
                if not t.isdigit() or not 0 < int(t) < 10**12: return bot.send_message(chat, "Потрібне число від 1 до 999999999999")
                e, other = change_id(uid, int(t)); bot.send_message(chat, e or f"✅ ID змінено: {uid} → {t}" + (f"\n🔁 ID {t} був зайнятий гравцем «{other}» — акаунти поміняно місцями (тепер у нього ID {uid})." if other else "")); show_card(chat, uid if e else int(t))
            bot.register_next_step_handler(m, done)
        elif op == "ul": ask2("🍀 Удача акаунта: КЕЙСИ АПГРЕЙД ХВИЛИНИ\nнапр. 2 1.5 60 (множники 1–1000, 0 хв = без ліміту), або 0 — скинути:", lambda t: set_luck(uid, t))
        elif op == "un": ask2("✏️ Новий нік:", lambda t: (set_user(uid, "name", t.strip()[:24]), "✅ Нік змінено")[1])
        elif op == "um": ask2("✉️ Текст повідомлення гравцю (з’явиться в його профілі на сайті):", lambda t: (add_note(uid, t[:300]), "✅ Надіслано")[1])
        elif op == "ut": set_user(uid, "trade_url", ""); bot.send_message(chat, "🔗 Трейд-URL скинуто"); show_card(chat, uid)
        elif op == "uk":
            was = con.execute("SELECT banned FROM users WHERE id=?", (uid,)).fetchone()[0]; set_user(uid, "banned", 0 if was else 1); add_log(uid, "admin", "unban" if was else "ban"); show_card(chat, uid)
        elif op == "ux":
            k = types.InlineKeyboardMarkup(); k.add(B("⚠️ Так, видалити", callback_data=f"uxc:{uid}"), B("Скасувати", callback_data=f"u:{uid}"))
            bot.send_message(chat, f"Видалити акаунт ID {uid} разом з інвентарем? Це незворотно.", reply_markup=k)
        elif op == "uxc":
            for q in ("DELETE FROM users WHERE id=?", "DELETE FROM inv WHERE uid=?", "DELETE FROM notes WHERE uid=?"): con.execute(q, (uid,))
            con.commit(); add_log(uid, "admin", "delete account"); bot.send_message(chat, f"🗑 Акаунт ID {uid} видалено")
    except Exception as e: bot.send_message(chat, f"Помилка: {e}")
    finally: con.close()


@bot.message_handler(func=lambda m: True)
def any_msg(m):
    if m.from_user.id in ADMINS and (m.text or "").strip().isdigit(): return show_card(m.chat.id, int(m.text))  # просто надішліть ID гравця
    if m.from_user.id in ADMINS:
        bot.send_message(m.chat.id, "🔐 NeonDrop — адмін-панель", reply_markup=menu())
    else:
        if SITE_URL.startswith("https://"):
            k = types.InlineKeyboardMarkup(); k.add(B("🌐 Відкрити NeonDrop", url=SITE_URL))
            bot.send_message(m.chat.id, "NeonDrop", reply_markup=k)
        else:
            bot.send_message(m.chat.id, "NeonDrop")


def edit(c, text, kb):
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    if c.from_user.id not in ADMINS:
        return bot.answer_callback_query(c.id, "Немає доступу", show_alert=True)
    d = c.data; con = db()
    if d == "menu":
        edit(c, "🔐 NeonDrop — адмін-панель", menu())
    elif d == "st":
        u = con.execute("SELECT COUNT(*) n, COALESCE(SUM(balance),0) s FROM users").fetchone()
        p = con.execute("SELECT COUNT(*) n FROM deposits WHERE status='pending'").fetchone()["n"]
        w = con.execute("SELECT COUNT(*) n FROM inv WHERE status='withdraw'").fetchone()["n"]
        t = con.execute("SELECT COALESCE(SUM(uah),0) s FROM deposits WHERE status='paid'").fetchone()["s"]
        edit(c, f"📊 Гравців: {u['n']}\nСума балансів: {u['s']:.0f}\nПідтверджено поповнень: {t:.0f} UAH\nОчікують поповнення: {p}\nЗапитів на вивід: {w}", back())
    elif d == "us":
        rows = con.execute("SELECT id,name,steamid,balance FROM users ORDER BY balance DESC LIMIT 15").fetchall()
        k = types.InlineKeyboardMarkup(row_width=1)
        for r in rows: k.add(B(f"ID {r['id']} · {r['name']} · {r['balance']:.0f}", callback_data=f"u:{r['id']}"))
        k.add(B("⬅️ Меню", callback_data="menu")); edit(c, "👥 Топ за балансом (натисніть — відкрити акаунт):" if rows else "Гравців ще немає.", k)
    elif d == "lg":
        rows = con.execute("SELECT uid,kind,info,ts FROM log ORDER BY id DESC LIMIT 15").fetchall()
        edit(c, "📜 Журнал:\n" + "\n".join(f"{r['ts'][5:16]} #{r['uid']} {r['kind']}: {r['info']}" for r in rows) if rows else "Порожньо.", back())
    elif d == "bal":
        ask(c, "💰 " + HELP_BAL, do_balance)
    elif d in ("pr", "pr_del") or d.startswith("pr_del:"):
        if d.startswith("pr_del:"): promo_del(d[7:])
        rows = promos_list(); k = types.InlineKeyboardMarkup(row_width=1)
        k.add(B("➕ Створити / змінити", callback_data="pr_new"))
        for r in rows: k.add(B(f"🗑 {r['code']} · +{r['pct']:g}% · {r['used']}/{r['max_uses'] or '∞'}", callback_data=f"pr_del:{r['code']}"))
        k.add(B("⬅️ Меню", callback_data="menu"))
        edit(c, "🎟 Промокоди (натисніть, щоб видалити):" if rows else "🎟 Промокодів ще немає.", k)
    elif d == "pr_new":
        ask(c, "🎟 " + HELP_PROMO, do_promo)
    elif d == "bc": ask(c, "📢 Текст повідомлення всім гравцям:", lambda t: f"✅ Надіслано {broadcast(t)} гравцям" if t.strip() else "Порожній текст")
    elif d == "bk": backup_now(True); bot.send_message(c.message.chat.id, "💾 Бекап: " + BK["state"] + ("\n✅ GitHub підключено — дані переживають перезапуски." if gh_on() else "\n⚠️ GitHub не підключено (змінні GH_TOKEN, GH_REPO у Render) — працює лише резервний бекап у Telegram, він може не спрацювати."))
    elif d == "wp":
        k = types.InlineKeyboardMarkup(); k.add(B("⚠️ Так, продовжити", callback_data="wp2"), B("Скасувати", callback_data="menu"))
        bot.send_message(c.message.chat.id, "Це видалить ВСІХ гравців, інвентар, платежі, промокоди й налаштування. Скіни лишаться.", reply_markup=k)
    elif d == "wp2": ask(c, "Введіть слово ОЧИСТИТИ, щоб стерти все:", lambda t: (wipe_all(), "🧹 Сайт очищено — все з нуля.\nБекап: " + BK["state"] + ("" if BK["state"].startswith("ok") else "\n⚠️ Бекап не оновився — після перезапуску можуть повернутися старі дані!"))[1] if t.strip() == "ОЧИСТИТИ" else "Скасовано")
    elif d == "lk":
        m, left = event_luck(); k = types.InlineKeyboardMarkup(row_width=2)
        k.add(B("x2 · 30 хв", callback_data="ev:2:30"), B("x2 · 1 год", callback_data="ev:2:60"), B("x2 · 3 год", callback_data="ev:2:180"), B("x3 · 1 год", callback_data="ev:3:60"))
        k.add(B("✍️ Свій множник", callback_data="evc"), B("⛔ Зупинити", callback_data="evx")); k.add(B("⬅️ Меню", callback_data="menu"))
        edit(c, f"🍀 Івент удачі: " + (f"АКТИВНИЙ x{m:g}, лишилось {left // 60} хв" if left else "вимкнено") + "\nМножник збільшує шанс цінних дропів у кейсах і шанс апгрейду для всіх.", k)
    elif d.startswith("ev:"): _, m, mn = d.split(":"); start_event(float(m), int(mn)); bot.send_message(c.message.chat.id, f"🍀 Запущено x{m} на {mn} хв, гравцям надіслано повідомлення")
    elif d == "evx": set_setting("ev_until", 0); bot.send_message(c.message.chat.id, "⛔ Івент зупинено")
    elif d == "evc": ask(c, "Надішліть: МНОЖНИК ХВИЛИНИ (напр. 2 90, множник 1–1000):", lambda t: (start_event(min(1000.0, max(1.0, float(t.split()[0]))), int(t.split()[1])), "🍀 Запущено")[1] if len(t.split()) == 2 else "Формат: 2 90")
    elif d == "tk":
        rows = tickets_list(12); k = types.InlineKeyboardMarkup(row_width=1)
        for r in rows: k.add(B(f"{'🔴' if r['unread'] else '⚪'} ID {r['uid']} {r['name'] or ''}: {(r['last'] or '')[:28]}", callback_data=f"sr:{r['uid']}"))
        k.add(B("⬅️ Меню", callback_data="menu")); edit(c, "💬 Звернення в підтримку (натисніть, щоб відповісти):" if rows else "Звернень ще немає.", k)
    elif d.startswith("sr:"):
        suid = int(d[3:]); ask(c, f"✍️ Відповідь гравцю ID {suid}:", lambda t: (staff_reply(suid, t, 0), "✅ Надіслано")[1] if t.strip() else "Порожній текст")
    elif d in ("ai", "aiT"):
        if d == "aiT": set_setting("ai_on", "0" if setting("ai_on", "1") == "1" else "1")
        on = setting("ai_on", "1") == "1"; k = types.InlineKeyboardMarkup(row_width=1); k.add(B("⏸ Вимкнути ШІ" if on else "▶️ Увімкнути ШІ", callback_data="aiT"), B("📚 Навчені відповіді", callback_data="fq"), B("⬅️ Меню", callback_data="menu"))
        edit(c, "🤖 Власна ШІ-підтримка: " + ("УВІМКНЕНА" if on else "вимкнена") + f"\nНавчених відповідей: {len(faq_rows(1000))}\nВона працює всередині сайту (без зовнішніх сервісів): розуміє питання про поповнення, вивід, апгрейд, промокоди, баланс. Дії (підтвердити платіж, змінити нік, скинути трейд-URL) робить ТІЛЬКИ після вашого дозволу, а чого не знає — питає вас і вчиться з вашої відповіді.", k)
    elif d == "fq":
        rows = faq_rows(12); k = types.InlineKeyboardMarkup(row_width=1)
        for r in rows: k.add(B(f"🗑 {r['q'][:30]} → {r['a'][:20]}", callback_data=f"fd:{r['id']}"))
        k.add(B("⬅️ Назад", callback_data="ai")); edit(c, "📚 Навчені відповіді (натисніть, щоб видалити):" if rows else "Навчених відповідей ще немає. Після вашої відповіді ШІ-підтримці з’явиться кнопка «Запам’ятати».", k)
    elif d.startswith("fd:"): faq_del(int(d[3:])); bot.send_message(c.message.chat.id, "🗑 Видалено")
    elif d.startswith("al:"): bot.send_message(c.message.chat.id, ai_learn(int(d[3:])))
    elif d[:3] in ("ao:", "an:", "aa:"):
        tid = int(d[3:])
        if d[:2] == "aa":
            m = bot.send_message(c.message.chat.id, "✍️ Ваша відповідь (її отримає гравець):"); lk = types.InlineKeyboardMarkup(); lk.add(B("💾 Запам’ятати для схожих питань", callback_data=f"al:{tid}"))
            bot.register_next_step_handler(m, lambda mm: bot.send_message(mm.chat.id, ai_decide(tid, "answer", mm.text or ""), reply_markup=lk))
        else: bot.send_message(c.message.chat.id, ai_decide(tid, "ok" if d[:2] == "ao" else "no"))
    elif d == "acc":
        m = bot.send_message(c.message.chat.id, "👤 Надішліть ID гравця (число):")
        bot.register_next_step_handler(m, lambda mm: show_card(mm.chat.id, int(mm.text)) if (mm.text or "").strip().isdigit() else bot.send_message(mm.chat.id, "Потрібне число"))
    elif d[:1] == "u" and ":" in d:
        acc_op(c, d)
    elif d == "dp":
        rows = con.execute("SELECT * FROM deposits WHERE status='pending' ORDER BY id LIMIT 10").fetchall()
        edit(c, f"💳 Очікують підтвердження: {len(rows)}", back())
        for r in rows:
            k = types.InlineKeyboardMarkup(); k.add(B("✅ Підтвердити", callback_data=f"dep_ok:{r['id']}"), B("❌ Відхилити", callback_data=f"dep_no:{r['id']}"))
            bot.send_message(c.message.chat.id, f"💳 #{r['id']} гравець ID {r['uid']}\n{r['method']} · {r['uah']:.0f} UAH → {r['coins']:.0f} монет", reply_markup=k)
    elif d == "wd":
        rows = con.execute("SELECT i.id,i.uid,i.item,u.name,u.steamid,u.trade_url FROM inv i JOIN users u ON u.id=i.uid WHERE i.status='withdraw' ORDER BY i.id LIMIT 10").fetchall()
        edit(c, f"📤 Запитів на вивід: {len(rows)}", back())
        for r in rows:
            k = types.InlineKeyboardMarkup(); k.add(B("✅ Виконано", callback_data=f"wd_ok:{r['id']}"))
            bot.send_message(c.message.chat.id, f"📤 #{r['id']}\nID гравця: {r['uid']} ({r['name']})\nSteam: https://steamcommunity.com/profiles/{r['steamid']}\nТрейд: {r['trade_url']}\nПредмет: {r['item']}", reply_markup=k)
    elif d.startswith("dep_ok:"):
        r = confirm_deposit(int(d[7:]))
        note = f"✅ Зараховано {r['coins']:.0f} монет (ID {r['uid']})" if r else "Вже оброблено"
        bot.edit_message_text(f"{c.message.text}\n\n{note}", c.message.chat.id, c.message.message_id)
    elif d.startswith("dep_no:"):
        cur = con.execute("UPDATE deposits SET status='rejected' WHERE id=? AND status='pending'", (int(d[7:]),)); con.commit()
        if cur.rowcount:
            release_promo(int(d[7:]))
            r = con.execute("SELECT uid FROM deposits WHERE id=?", (int(d[7:]),)).fetchone(); add_note(r["uid"], "Ваш платіж відхилено. Зверніться до адміністратора.")
        bot.edit_message_text(f"{c.message.text}\n\n{'❌ Відхилено' if cur.rowcount else 'Вже оброблено'}", c.message.chat.id, c.message.message_id)
    elif d.startswith("wd_ok:"):
        cur = con.execute("UPDATE inv SET status='withdrawn' WHERE id=? AND status='withdraw'", (int(d[6:]),)); con.commit()
        bot.edit_message_text(f"{c.message.text}\n\n{'✅ Виконано' if cur.rowcount else 'Вже оброблено'}", c.message.chat.id, c.message.message_id)
    con.close(); bot.answer_callback_query(c.id)


if __name__ == "__main__":
    notify("🤖 NeonDrop бот запущено")
    bot.infinity_polling()
