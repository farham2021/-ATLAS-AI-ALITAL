# ATLAS AI v12 FINAL

نسخه یکپارچه موتور تحلیل ATLAS AI. سیستم سیگنال را مجبور نمی‌کند.

## منطق Setup
- EXECUTABLE
- BEST_WATCH
- NO_VALID_SETUP

## داده‌های ارزی
قیمت دلار و USDT در هر اجرای گزارش از TGJU خوانده می‌شوند. در صورت شکست دریافت، مقدار `DATA_UNAVAILABLE` ثبت می‌شود و مقدار ساختگی تولید نمی‌شود.

## فایل‌ها
- `bot12.py` گزارش، CSV و Telegram
- `atlas_v12_upgrade.py` موتور تحلیل و R/R
- `smoke_atlas.py` تست compile/import
- `requirements-v12.txt` وابستگی‌ها

## اجرا
```bash
python3 smoke_atlas.py
python3 bot12.py
```

متغیرهای Telegram:
`TELEGRAM_TOKEN` و `TELEGRAM_CHAT_ID`
