"""Точка входу для Render: gunicorn wsgi:app --workers 1 --threads 4 --timeout 120
Запускає сайт + Telegram-бота в одному сервісі та сам імпортує скіни, якщо база порожня."""
import threading
from app import app, load_cat, db, TOKEN, IMGS, fetch_images


def _skins():
    try:
        c = db(); n = c.execute("SELECT COUNT(*) FROM skins").fetchone()[0]; c.close()
        if n < 200:
            import import_skins  # виконує імпорт при імпорті
            load_cat()
    except Exception as e:
        print("import_skins failed:", e)
    try:
        if len(IMGS) < 1000: print("images loaded:", fetch_images())
    except Exception as e:
        print("images failed:", e)


def _bot():
    try:
        import bot
        bot.bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print("bot stopped:", e)


threading.Thread(target=_skins, daemon=True).start()
if TOKEN: threading.Thread(target=_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(port=5000)
