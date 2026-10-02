# gunicorn сам читає цей файл — міняти Start Command в Render не потрібно
workers = 1      # один процес: SQLite + бот + кеш кейсів
threads = 4
timeout = 120    # безкоштовний Render повільний, 30 с за замовчуванням мало
