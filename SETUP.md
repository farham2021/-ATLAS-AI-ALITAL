# ATLAS — چک‌لیست راه‌اندازی نسخه جدید

## 1. فایل‌ها را در ریپو جایگزین کن
- `bot.py` → جایگزین فایل قبلی در ریشه ریپو
- `atlas.yml` → جایگزین `.github/workflows/atlas.yml`

## 2. یک‌بار روی Supabase اجرا کن (ضروری برای درست‌کارکردن fix حافظه)
در Supabase → SQL Editor:
```sql
alter table snapshot_prices
    add constraint snapshot_prices_symbol_key unique (symbol);
```
بدون این، upsert جدید با خطا مواجه می‌شود و به‌صورت خاموش به SQLite موقت
سقوط می‌کند (بازم گزارش می‌رسد، ولی حافظه‌ی بین اجراها برنمی‌گردد).

## 3. Secrets در گیت‌هاب (Settings → Secrets and variables → Actions)

### ضروری
| Secret | توضیح |
|---|---|
| `TELEGRAM_TOKEN` | از @BotFather |
| `TELEGRAM_CHAT_ID` و/یا `TELEGRAM_GROUP_CHAT_ID` | حداقل یکی |

### قویاً توصیه‌شده
| Secret | توضیح |
|---|---|
| `SUPABASE_URL` | آدرس پروژه Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | (یا `SUPABASE_ANON_KEY` اگه سرویس‌رول نداری) |
| `NEWSAPI_KEY` | رایگان از newsapi.org |

### اختیاری — اگر نداری، مشکلی نیست
| Secret | توضیح |
|---|---|
| `CRYPTOPANIC_TOKEN` | نداری؟ مشکلی نیست — بات به‌طور خودکار از منابع رایگان بدون کلید (free-crypto-news.vercel.app و cryptocurrency.cv) استفاده می‌کند |
| `FRED_API_KEY` | رایگان از fred.stlouisfed.org/docs/api/api_key.html — برای نرخ بهره فدرال/بیکاری |
| `WHALE_ALERT_API_KEY` | نداری؟ مشکلی نیست — بات به‌طور خودکار از cryptocurrency.cv/api/whale-alerts (رایگان، بدون کلید) استفاده می‌کند |
| `COINGECKO_API_KEY`, `CMC_API_KEY`, `COINGLASS_API_KEY`, `ALPHAVANTAGE_API_KEY`, `TRADINGVIEW_CONFIRMATION_URL` | تکمیلی، بدونشون هم کار می‌کند |

## 4. چه چیزی تغییر کرده (خلاصه)
- ✅ باگ عدم ارسال گزارش تلگرام: `telegram_preflight` دیگر کل اجرا را قربانی نمی‌کند؛ خطای جزئی هم دیگر کل جاب را «Failed» نمی‌کند
- ✅ `timeout-minutes` از 20 به 35 افزایش یافت (علت احتمالی قطع‌شدن وسط ارسال)
- ✅ حافظه بین اجراها: قیمت‌های Snapshot حالا واقعاً upsert می‌شوند، نه insert تکراری
- ✅ بخش جدید «🌍 زمینه کلان و اخبار مؤثر»: نرخ بهره فدرال، نرخ بیکاری، تحرکات نهنگ، اظهارات ترامپ/پاول/بزوس — هم در متن گزارش هم در ویس
- ✅ عناوین اخبار مؤثر به فارسی ترجمه می‌شوند (با Google Translate غیررسمی، همان چیزی که gTTS از قبل استفاده می‌کند)
- ✅ منابع رایگان بدون کلید برای اخبار و نهنگ، برای وقتی بودجه‌ای برای CryptoPanic/Whale Alert پولی نیست

## 5. نکته صادقانه
منابع رایگان جدید (`free-crypto-news.vercel.app`، `cryptocurrency.cv`، Google Translate غیررسمی) سرویس‌های کوچک‌تر شخص‌ثالث‌اند —
تضمین uptime بلندمدتشان مثل گزینه‌های معروف نیست. کد طوری نوشته شده که اگر
هرکدام از دسترس خارج شوند، فقط همان بخش گزارش خالی می‌ماند و بقیه ربات
(تحلیل تکنیکال، ارسال تلگرام، ویس) بدون مشکل کار می‌کند.
