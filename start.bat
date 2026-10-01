@echo off
chcp 65001 >nul
cd /d %~dp0

rem ===== Налаштування (вже заповнено) =====
set SITE_URL=http://127.0.0.1:5000
set SECRET=neondrop-change-this-to-random-string
set BOT_TOKEN=8841389440:AAERO-v0t914iHCGtgWZxYnTi8wJRAx1ye4
set PAY_CARD=4874100010251687
set STEAM_API_KEY=
set PAY_CRYPTO=
set COINS_PER_UAH=2.4
rem ========================================

pip install -r requirements.txt
if not exist imported.flag (
  python import_skins.py && echo ok>imported.flag
)
start "NeonDrop site" python app.py
start "NeonDrop bot" python bot.py
echo Сайт: http://127.0.0.1:5000
