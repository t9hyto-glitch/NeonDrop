@echo off
chcp 65001 >nul
cd /d %~dp0
rem Локальний запуск. Токен НЕ зберігайте у файлі: задайте його у вікні перед запуском (set BOT_TOKEN=...)
set SITE_URL=http://127.0.0.1:5000
set SECRET=local-dev-secret
set PAY_CARD=
set COINS_PER_UAH=2.4
pip install -r requirements.txt
start "NeonDrop" python wsgi.py
