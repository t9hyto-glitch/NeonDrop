import telebot
from telebot import types
from app import ADMINS, TOKEN, SITE_URL, db, notify, confirm_deposit, add_note

bot = telebot.TeleBot(TOKEN)
B = types.InlineKeyboardButton


def menu():
    k = types.InlineKeyboardMarkup(row_width=2)
    k.add(B("📊 Статистика", callback_data="st"), B("👥 Гравці", callback_data="us"))
    k.add(B("💳 Поповнення", callback_data="dp"), B("📤 Виводи", callback_data="wd"))
    k.add(B("📜 Журнал", callback_data="lg"))
    if SITE_URL.startswith("https://"): k.add(B("🌐 Сайт", url=SITE_URL))  # Telegram не приймає http/localhost у кнопках
    return k


def back():
    k = types.InlineKeyboardMarkup(); k.add(B("⬅️ Меню", callback_data="menu")); return k


@bot.message_handler(func=lambda m: True)
def any_msg(m):
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
        edit(c, "👥 Топ за балансом:\n" + "\n".join(f"ID {r['id']} {r['name']} — {r['balance']:.0f}\nsteamcommunity.com/profiles/{r['steamid']}" for r in rows) if rows else "Гравців ще немає.", back())
    elif d == "lg":
        rows = con.execute("SELECT uid,kind,info,ts FROM log ORDER BY id DESC LIMIT 15").fetchall()
        edit(c, "📜 Журнал:\n" + "\n".join(f"{r['ts'][5:16]} #{r['uid']} {r['kind']}: {r['info']}" for r in rows) if rows else "Порожньо.", back())
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
            r = con.execute("SELECT uid FROM deposits WHERE id=?", (int(d[7:]),)).fetchone(); add_note(r["uid"], "Ваш платіж відхилено. Зверніться до адміністратора.")
        bot.edit_message_text(f"{c.message.text}\n\n{'❌ Відхилено' if cur.rowcount else 'Вже оброблено'}", c.message.chat.id, c.message.message_id)
    elif d.startswith("wd_ok:"):
        cur = con.execute("UPDATE inv SET status='withdrawn' WHERE id=? AND status='withdraw'", (int(d[6:]),)); con.commit()
        bot.edit_message_text(f"{c.message.text}\n\n{'✅ Виконано' if cur.rowcount else 'Вже оброблено'}", c.message.chat.id, c.message.message_id)
    con.close(); bot.answer_callback_query(c.id)


if __name__ == "__main__":
    notify("🤖 NeonDrop бот запущено")
    bot.infinity_polling()
