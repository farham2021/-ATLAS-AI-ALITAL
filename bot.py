#============================================================
# ATLAS AI v11.1 — UNIFIED TWO-ENGINE DECISION ENGINE + INTELLIGENCE
# ============================================================
# TP3/TP4 structural targets are optional and never fabricated.
# v11.0 architecture:
# - Fixed portfolio symbols (user-defined, never changes)
# - Compact dashboard-style report output
# - BTC pair filtering with dynamic volume threshold
# - Two-table format: market overview + trade plan
# - 4-line summary: market regime, best setup, news, risk
# - Separate 3H Price Snapshot with public Iranian USDT pricing; no API key required
# - No extra paragraphs or explanations
# - Real-time data only, no fabricated numbers
# - Smart Telegram rate limit handling with exponential backoff
# - Simultaneous delivery to private chat and supergroup
# - Duplicate report prevention with hash-based deduplication
#
# Design principles:
#   - ATLAS static radar is NEVER removed.
#   - Stablecoins are excluded from trading analysis.
#   - Crypto: 1H / 4H / 1D via CCXT exchange data.
#   - Signals require multi-factor confirmation.
#   - No signal is allowed against the higher-timeframe trend unless a
#     strong three-level divergence is detected.
#   - Incomplete candles are excluded.
#   - Telegram reports are split safely into multiple messages.
#   - The same report can be mirrored to a Telegram supergroup.
#   - Supabase is the primary persistence layer; SQLite is a local fallback.
#   - Signal outcomes are evaluated later from historical candles.
#   - Model weights are changed only after a mandatory backtest gate.
#   - Every self-modification is written to the changelog.
#
# IMPORTANT:
#   This is an analytical engine. It does not place orders.
#   No model can guarantee low-error signals or profits.
# ============================================================

import os
import re
import json
import math
import time
import random
import sqlite3
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import traceback
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from statistics import mean, median

import ccxt


# ============================================================
# CONFIG
# ============================================================

VERSION = "ATLAS v11.1 UNIFIED TWO-ENGINE + INTELLIGENCE"
TIMEFRAMES = ("1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = "4h"
EVENT_TIMEFRAMES = ("30m", "1h", "4h", "1d", "1w", "1M")
EVENT_LOOKBACK_LIMITS = {"30m": 80, "1h": 120, "4h": 120, "1d": 120, "1w": 80, "1M": 60}
EVENT_DEDUP_ENABLED = os.environ.get("ATLAS_CANDLE_EVENT_DEDUP", "1").strip() != "0"
TEHRAN = ZoneInfo("Asia/Tehran")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_GROUP_CHAT_ID = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "").strip()

# Telegram rate limit settings
TELEGRAM_PRIVATE_DELAY = float(os.environ.get("TELEGRAM_PRIVATE_DELAY", "1.5"))
TELEGRAM_GROUP_DELAY = float(os.environ.get("TELEGRAM_GROUP_DELAY", "3.0"))
TELEGRAM_MAX_RETRIES = int(os.environ.get("TELEGRAM_MAX_RETRIES", "5"))
TELEGRAM_BASE_RETRY_DELAY = float(os.environ.get("TELEGRAM_BASE_RETRY_DELAY", "3"))
TELEGRAM_MAX_WAIT = float(os.environ.get("TELEGRAM_MAX_WAIT", "60"))

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://tmnfhsuwtqfpglckfxwg.supabase.co"
).strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
if not SUPABASE_KEY:
    SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()

COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "").strip()
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "").strip()
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "").strip()
CMC_API_KEY = os.environ.get("CMC_API_KEY", "").strip()

# ============================================================
# BOOLEAN PARSER - برای متغیرهای true/false/1/0
# ============================================================
def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)

# ============================================================
# VOICE & IMAGE SETTINGS - با پشتیبانی از true/false/1/0
# ============================================================
ENABLE_VOICE_REPORT = _parse_bool(os.environ.get("ATLAS_ENABLE_VOICE", "1"))
AUTO_SEND_VOICE = _parse_bool(os.environ.get("ATLAS_AUTO_SEND_VOICE", "1"))
VOICE_TYPE = os.environ.get("ATLAS_VOICE_TYPE", "female")
VOICE_LANGUAGE = os.environ.get("ATLAS_VOICE_LANGUAGE", "fa")
ENABLE_IMAGE_TABLE = _parse_bool(os.environ.get("ATLAS_ENABLE_IMAGE_TABLE", "1"))

# ============================================================
# RUN MODE & ENGINE MODE - با پیش‌فرض‌های صحیح
# ============================================================
def get_run_mode():
    """حالت اجرا: AUTO, SNAPSHOT, ANALYSIS, BOTH"""
    mode = os.environ.get("ATLAS_RUN_MODE", "AUTO").strip().upper()
    if mode not in ("AUTO", "SNAPSHOT", "ANALYSIS", "BOTH"):
        return "AUTO"
    return mode

def get_engine_mode():
    """حالت موتور: MARKET, PERSONAL, BOTH"""
    mode = os.environ.get("ATLAS_ENGINE", "BOTH").strip().upper()
    if mode not in ("MARKET", "PERSONAL", "BOTH"):
        return "BOTH"
    return mode

# ============================================================
# MARKET SESSIONS
# ============================================================

MARKET_SESSIONS = {
    "ASIA": {"open": 0, "close": 8, "label": "🇯🇵 آسیا", "multiplier": 0.8, "hours": (0, 8)},
    "EUROPE": {"open": 7, "close": 15, "label": "🇬🇧 اروپا", "multiplier": 1.0, "hours": (7, 15)},
    "AMERICA": {"open": 12, "close": 20, "label": "🇺🇸 آمریکا", "multiplier": 0.9, "hours": (12, 20)},
    "OVERLAP": {"open": 12, "close": 15, "label": "🔀 همپوشانی اروپا-آمریکا", "multiplier": 1.2, "hours": (12, 15)},
}

def get_current_session(dt=None):
    """تشخیص سشن فعلی بازار و ضریب کیفیت آن"""
    dt = dt or now_utc()
    hour = dt.hour
    for name, session in MARKET_SESSIONS.items():
        if session["open"] <= hour < session["close"]:
            return name, session["label"], session["multiplier"]
    return "CLOSED", "🔒 خارج از سشن", 0.7

def get_next_session_time(dt=None):
    """دریافت زمان شروع سشن بعدی"""
    dt = dt or now_utc()
    hour = dt.hour
    current_session, _, _ = get_current_session(dt)
    
    sessions = [
        ("ASIA", 0, 8),
        ("EUROPE", 7, 15),
        ("OVERLAP", 12, 15),
        ("AMERICA", 12, 20),
    ]
    
    for name, open_hour, close_hour in sessions:
        if current_session != name and hour < open_hour:
            next_dt = dt.replace(hour=open_hour, minute=0, second=0, microsecond=0)
            if next_dt <= dt:
                next_dt = next_dt + timedelta(days=1)
            return name, next_dt
    
    return "ASIA", dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


# ============================================================
# TEXT TO IMAGE - تبدیل گزارش متنی به تصویر PNG
# ============================================================

def text_to_image(text, filename="report.png", width=1400):
    """تبدیل متن به تصویر PNG با فرمت زیبا"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        lines = text.split('\n')
        
        # تنظیم فونت
        try:
            font_paths = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
                '/System/Library/Fonts/Menlo.ttc',
                'C:\\Windows\\Fonts\\Consolas.ttf',
            ]
            font_path = None
            for path in font_paths:
                if os.path.exists(path):
                    font_path = path
                    break
            
            if font_path:
                font = ImageFont.truetype(font_path, 14)
                font_bold = ImageFont.truetype(font_path, 16)
                font_title = ImageFont.truetype(font_path, 18)
            else:
                font = ImageFont.load_default()
                font_bold = font
                font_title = font
        except:
            font = ImageFont.load_default()
            font_bold = font
            font_title = font
        
        # محاسبه عرض و ارتفاع
        char_width = 10
        char_height = 20
        max_line_length = max([len(line) for line in lines]) if lines else 80
        img_width = min(max(600, max_line_length * char_width + 80), width)
        img_height = len(lines) * char_height + 60
        
        # ایجاد تصویر با پس‌زمینه تیره
        img = Image.new('RGB', (img_width, img_height), color='#0a0e17')
        draw = ImageDraw.Draw(img)
        
        y = 20
        for line in lines:
            line = line.replace('\t', '    ')
            
            # تشخیص نوع خط و رنگ‌بندی
            if line.startswith('┌') or line.startswith('└') or line.startswith('├') or line.startswith('┴') or line.startswith('┬'):
                draw.text((20, y), line, fill='#4a9eff', font=font)
            elif line.startswith('│'):
                draw.text((20, y), line, fill='#e0e0e0', font=font)
            elif '━━━' in line or '────' in line:
                draw.text((20, y), line, fill='#4a9eff', font=font)
            elif 'ASSET' in line or 'PRICE' in line or 'STATUS' in line or 'SUPPORT' in line or 'RESIST' in line:
                draw.text((20, y), line, fill='#ffd700', font=font_bold)
            elif '🟢' in line or '🔴' in line or '🟡' in line or '⚪' in line:
                draw.text((20, y), line, fill='#ffffff', font=font)
            elif line.strip().startswith('📊') or line.strip().startswith('🏆') or line.strip().startswith('💼'):
                draw.text((20, y), line, fill='#ff6b6b', font=font_title)
            elif '📌' in line:
                draw.text((20, y), line, fill='#ffa94d', font=font_bold)
            elif '🔥' in line:
                draw.text((20, y), line, fill='#ff6b6b', font=font_bold)
            elif '🪙' in line:
                draw.text((20, y), line, fill='#ffd700', font=font_bold)
            elif '📡' in line:
                draw.text((20, y), line, fill='#4a9eff', font=font_bold)
            elif '🧠' in line:
                draw.text((20, y), line, fill='#ff6b6b', font=font_bold)
            else:
                draw.text((20, y), line, fill='#b0b0b0', font=font)
            y += char_height
        
        img.save(filename, 'PNG', quality=95)
        return filename
    except ImportError as e:
        print(f"⚠️ PIL not installed: {e}")
        return None
    except Exception as e:
        print(f"⚠️ Text to image error: {e}")
        return None


def send_report_as_image(text, caption=None):
    """ارسال گزارش متنی به صورت تصویر PNG به تمام مقاصد"""
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set")
        return False
    
    filename = "report_table.png"
    image_file = text_to_image(text, filename)
    
    if not image_file or not os.path.exists(image_file):
        print("❌ Failed to convert text to image")
        return False
    
    with open(image_file, 'rb') as f:
        image_data = f.read()
    
    destinations = []
    if TELEGRAM_CHAT_ID and str(TELEGRAM_CHAT_ID).strip():
        destinations.append({
            "id": str(TELEGRAM_CHAT_ID).strip(),
            "name": "PRIVATE_CHAT"
        })
    if TELEGRAM_GROUP_CHAT_ID and str(TELEGRAM_GROUP_CHAT_ID).strip():
        group_id = str(TELEGRAM_GROUP_CHAT_ID).strip()
        if group_id not in [d["id"] for d in destinations]:
            destinations.append({
                "id": group_id,
                "name": "SUPERGROUP"
            })
    
    if not destinations:
        print("❌ No Telegram destinations for image")
        try:
            os.unlink(image_file)
        except:
            pass
        return False
    
    success_count = 0
    
    for dest in destinations:
        chat_id = dest["id"]
        dest_name = dest["name"]
        
        print(f"  Sending report image to {dest_name}...", end=" ", flush=True)
        
        boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
        body = bytearray()
        
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body.extend(str(chat_id).encode())
        body.extend(b'\r\n')
        
        if caption:
            body.extend(f'--{boundary}\r\n'.encode())
            body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body.extend(caption.encode('utf-8'))
            body.extend(b'\r\n')
        
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(f'Content-Disposition: form-data; name="photo"; filename="{os.path.basename(image_file)}"\r\n'.encode())
        body.extend(b'Content-Type: image/png\r\n\r\n')
        body.extend(image_data)
        body.extend(b'\r\n')
        body.extend(f'--{boundary}--\r\n'.encode())
        
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(len(body))
        }
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        req = urllib.request.Request(url, data=bytes(body), headers=headers, method='POST')
        
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode())
                if result.get('ok', False):
                    print("✅")
                    success_count += 1
                else:
                    print(f"❌ {result.get('description', 'Unknown error')}")
        except Exception as e:
            print(f"❌ {e}")
    
    try:
        os.unlink(image_file)
    except:
        pass
    
    return success_count > 0


# ============================================================
# VOICE SUMMARY & OUTPUT - نسخه کامل با اخبار و سیگنال‌ها
# ============================================================

def generate_voice_summary(results, news=None, btc_regime=None):
    """تولید خلاصه صوتی کامل از نتایج با اخبار و سیگنال‌ها"""
    if not results:
        return "هیچ داده‌ای برای گزارش صوتی موجود نیست."
    
    print(f"📝 generate_voice_summary: processing {len(results)} items")
    
    session, session_label, session_multiplier = get_current_session()
    
    up_count = 0
    down_count = 0
    stable_count = 0
    changes = []
    buy_signals = []
    sell_signals = []
    watch_signals = []
    
    for r in results:
        price = f(r.get("price"))
        change = f(r.get("change")) or f(r.get("change24"))
        symbol = r.get("coin", "")
        action = str(r.get("action") or "").upper()
        confidence = r.get("confidence", 0)
        
        if price:
            if change is not None:
                changes.append((symbol, change))
                if change > 0.5:
                    up_count += 1
                elif change < -0.5:
                    down_count += 1
                else:
                    stable_count += 1
        
        if action in ("BUY CONFIRMATION", "BUY"):
            buy_signals.append((symbol, confidence, r.get("rr", 0)))
        elif action in ("SELL CONFIRMATION", "SELL"):
            sell_signals.append((symbol, confidence, r.get("rr", 0)))
        elif action in ("BULLISH WATCH", "BEARISH WATCH"):
            watch_signals.append((symbol, action, confidence))
    
    print(f"📊 Voice stats: up={up_count}, down={down_count}, stable={stable_count}")
    print(f"📊 Signals: BUY={len(buy_signals)}, SELL={len(sell_signals)}, WATCH={len(watch_signals)}")
    
    lines = [
        "به گزارش صوتی اطلس خوش آمدید.",
        f"زمان: {now_tehran().strftime('%H:%M')} - سشن {session_label}.",
    ]
    
    if btc_regime:
        regime = btc_regime.get("regime", "UNKNOWN")
        if regime == "RISK_ON":
            lines.append("بازار در حالت ریسک‌پذیر قرار دارد و تمایل به صعود دارد.")
        elif regime == "RISK_OFF":
            lines.append("بازار در حالت ریسک‌گریز قرار دارد و احتیاط بیشتری نیاز است.")
        else:
            lines.append("بازار در حالت خنثی قرار دارد.")
    
    if up_count > 0:
        lines.append(f"{up_count} ارز صعودی هستند.")
    if down_count > 0:
        lines.append(f"{down_count} ارز نزولی هستند.")
    if stable_count > 0:
        lines.append(f"{stable_count} ارز بدون تغییر قابل توجه هستند.")
    
    if changes:
        best = max(changes, key=lambda x: x[1])
        worst = min(changes, key=lambda x: x[1])
        if best[1] > 0:
            lines.append(f"بهترین عملکرد: {best[0]} با رشد {best[1]:.2f} درصد.")
        if worst[1] < 0:
            lines.append(f"ضعیف‌ترین عملکرد: {worst[0]} با کاهش {abs(worst[1]):.2f} درصد.")
    
    if buy_signals:
        buy_text = "سیگنال خرید برای: " + "، ".join([f"{s[0]} با اطمینان {s[1]:.0f} درصد" for s in buy_signals[:3]])
        lines.append(buy_text)
    
    if sell_signals:
        sell_text = "سیگنال فروش برای: " + "، ".join([f"{s[0]} با اطمینان {s[1]:.0f} درصد" for s in sell_signals[:3]])
        lines.append(sell_text)
    
    if watch_signals:
        watch_text = "در انتظار تأیید برای: " + "، ".join([f"{s[0]}" for s in watch_signals[:3]])
        lines.append(watch_text)
    
    if news:
        bias = news.get("bias", "")
        impact = news.get("impact", "")
        if bias == "POSITIVE":
            lines.append("اخبار بازار عمدتاً مثبت است.")
        elif bias == "NEGATIVE":
            lines.append("اخبار بازار عمدتاً منفی است.")
        elif bias == "MIXED/LIMITED":
            lines.append("اخبار بازار مختلط است.")
        
        if impact == "HIGH":
            lines.append("اخبار با تأثیر بالا - احتیاط بیشتری نیاز است.")
        
        items = news.get("items", [])[:3]
        if items:
            headlines = [item.get("title", "")[:50] for item in items if item.get("title")]
            if headlines:
                lines.append("خبرهای مهم: " + "، ".join(headlines))
    
    usdt = fetch_usdt_toman_public()
    if usdt:
        lines.append(f"نرخ تتر: {usdt:,.0f} تومان.")
    
    if buy_signals:
        lines.append("توصیه: با توجه به سیگنال‌های خرید، می‌توانید ورودهای کنترل‌شده داشته باشید.")
    elif watch_signals:
        lines.append("توصیه: در حال حاضر در جایگاه ناظر باشید و منتظر تأیید سیگنال‌ها بمانید.")
    else:
        lines.append("توصیه: فعلاً در جایگاه ناظر باشید و منتظر شکل‌گیری سیگنال معتبر بمانید.")
    
    lines.append("این پیام به صورت خودکار هر ۴ ساعت بروزرسانی می‌شود.")
    
    result = " ".join(lines)
    print(f"📝 Voice text length: {len(result)} characters")
    return result


def generate_voice_summary_from_snapshot(results):
    """تولید خلاصه صوتی از داده‌های اسنپ‌شات"""
    if not results:
        return "هیچ داده‌ای برای گزارش صوتی موجود نیست."
    
    session, session_label, session_multiplier = get_current_session()
    
    up_count = 0
    down_count = 0
    stable_count = 0
    changes = []
    prices = []
    
    for r in results:
        price = f(r.get("price"))
        change = f(r.get("change")) or f(r.get("change24"))
        symbol = r.get("coin", "")
        if price:
            prices.append(price)
            if change is not None:
                changes.append((symbol, change))
                if change > 0.5:
                    up_count += 1
                elif change < -0.5:
                    down_count += 1
                else:
                    stable_count += 1
    
    lines = [
        "به گزارش صوتی اطلس خوش آمدید.",
        f"گزارش لحظه‌ای بازار ارزهای دیجیتال در سشن {session_label}.",
    ]
    
    if up_count > 0:
        lines.append(f"{up_count} ارز صعودی هستند.")
    if down_count > 0:
        lines.append(f"{down_count} ارز نزولی هستند.")
    if stable_count > 0:
        lines.append(f"{stable_count} ارز بدون تغییر قابل توجه هستند.")
    
    if changes:
        best = max(changes, key=lambda x: x[1])
        worst = min(changes, key=lambda x: x[1])
        if best[1] > 0:
            lines.append(f"بهترین عملکرد: {best[0]} با رشد {best[1]:.2f} درصد.")
        if worst[1] < 0:
            lines.append(f"ضعیف‌ترین عملکرد: {worst[0]} با کاهش {abs(worst[1]):.2f} درصد.")
    
    usdt = fetch_usdt_toman_public()
    if usdt:
        lines.append(f"نرخ تتر: {usdt:,.0f} تومان.")
    
    lines.append("این پیام به صورت خودکار هر ۳ ساعت بروزرسانی می‌شود.")
    
    return " ".join(lines)


def text_to_speech_persian(text, voice="female"):
    """تبدیل متن فارسی به صدا - اولویت: Edge TTS → gTTS → Google Translate"""
    
    try:
        import edge_tts
        import asyncio
        voice_map = {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"}
        selected_voice = voice_map.get(voice, "fa-IR-DilaraNeural")
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        output_path = temp_file.name
        temp_file.close()
        async def generate():
            communicate = edge_tts.Communicate(text, selected_voice)
            await communicate.save(output_path)
        asyncio.run(generate())
        return output_path
    except:
        pass
    
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="fa", slow=False)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        tts.save(temp_file.name)
        return temp_file.name
    except:
        pass
    
    try:
        text_encoded = urllib.parse.quote(text)
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={text_encoded}&tl=fa&client=tw-ob"
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            audio_data = response.read()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_file.write(audio_data)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        print(f"⚠️ TTS error: {e}")
        return None


def generate_audio_report(results, news=None, btc_regime=None, filename="audio_report.mp3"):
    """تولید فایل صوتی کامل از گزارش با اخبار و سیگنال‌ها"""
    if not results:
        return None
    
    audio_text = generate_voice_summary(results, news, btc_regime)
    
    if len(audio_text) < 50:
        audio_text = generate_voice_summary_from_snapshot(results)
    
    print(f"🎤 Generating audio with text: {audio_text[:100]}...")
    audio_file = text_to_speech_persian(audio_text, VOICE_TYPE)
    if audio_file:
        import shutil
        final_path = filename
        shutil.move(audio_file, final_path)
        return final_path
    return None


def send_audio_report(audio_file, caption=None):
    """ارسال گزارش صوتی به تمام مقاصد تلگرام (چت خصوصی + سوپرگروه)"""
    if not os.path.exists(audio_file):
        print(f"❌ Audio file not found: {audio_file}")
        return False
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set")
        return False
    if not AUTO_SEND_VOICE:
        print("ℹ️ AUTO_SEND_VOICE is disabled")
        return False
    
    with open(audio_file, 'rb') as f:
        audio_data = f.read()
    
    destinations = []
    if TELEGRAM_CHAT_ID and str(TELEGRAM_CHAT_ID).strip():
        destinations.append({
            "id": str(TELEGRAM_CHAT_ID).strip(),
            "name": "PRIVATE_CHAT"
        })
        print(f"✅ Audio destination: PRIVATE_CHAT ({TELEGRAM_CHAT_ID})")
    
    if TELEGRAM_GROUP_CHAT_ID and str(TELEGRAM_GROUP_CHAT_ID).strip():
        group_id = str(TELEGRAM_GROUP_CHAT_ID).strip()
        if group_id not in [d["id"] for d in destinations]:
            destinations.append({
                "id": group_id,
                "name": "SUPERGROUP"
            })
            print(f"✅ Audio destination: SUPERGROUP ({group_id})")
    
    if not destinations:
        print("❌ No Telegram destinations configured for audio")
        return False
    
    print(f"🎤 Sending audio to {len(destinations)} destination(s)")
    success_count = 0
    
    for dest in destinations:
        chat_id = dest["id"]
        dest_name = dest["name"]
        
        print(f"  Sending audio to {dest_name}...", end=" ", flush=True)
        
        boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
        body = bytearray()
        
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body.extend(str(chat_id).encode())
        body.extend(b'\r\n')
        
        if caption:
            body.extend(f'--{boundary}\r\n'.encode())
            body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
            body.extend(caption.encode('utf-8'))
            body.extend(b'\r\n')
        
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(f'Content-Disposition: form-data; name="audio"; filename="{os.path.basename(audio_file)}"\r\n'.encode())
        body.extend(b'Content-Type: audio/mpeg\r\n\r\n')
        body.extend(audio_data)
        body.extend(b'\r\n')
        body.extend(f'--{boundary}--\r\n'.encode())
        
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(len(body))
        }
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
        req = urllib.request.Request(url, data=bytes(body), headers=headers, method='POST')
        
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result.get('ok', False):
                    print("✅")
                    success_count += 1
                else:
                    error_msg = result.get('description', 'Unknown error')
                    print(f"❌ {error_msg}")
        except urllib.error.HTTPError as e:
            print(f"❌ HTTP {e.code}: {e.reason}")
        except Exception as e:
            print(f"❌ {e}")
    
    if success_count > 0:
        print(f"✅ Audio sent to {success_count}/{len(destinations)} destinations")
    else:
        print(f"❌ Audio failed to all {len(destinations)} destinations")
    
    return success_count > 0


# ============================================================
# گزارش‌های جدولی مجزا - TABLES (با خطوط جدول)
# ============================================================

def _fmt_price(value):
    """فرمت کردن قیمت"""
    if value is None:
        return "N/A"
    if abs(value) >= 1000:
        return f"${value:,.2f}"
    if abs(value) >= 1:
        return f"${value:,.4f}"
    if abs(value) >= 0.01:
        return f"${value:,.6f}"
    return f"${value:.8f}"

def _fmt_change(value):
    """فرمت کردن تغییرات"""
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"

def _get_status_emoji(r):
    """دریافت وضعیت با ایموجی"""
    action = str(r.get("action") or "").upper()
    if "BUY" in action or "BULLISH" in action:
        return "🟢 BULL"
    elif "SELL" in action or "BEARISH" in action:
        return "🔴 BEAR"
    else:
        return "⚪ WAIT"


def build_table_top10(results):
    """ساخت جدول TOP 10 بازار"""
    lines = []
    lines.append("🏆 MARKET TOP 10")
    lines.append("───────────────────")
    lines.append("┌──────┬──────────┬──────────┬──────────┬──────────┬────────────┐")
    lines.append("│ ASSET│ STATUS   │ PRICE    │ 24H %    │ SUPPORT  │ RESIST     │")
    lines.append("├──────┼──────────┼──────────┼──────────┼──────────┼────────────┤")
    
    sorted_results = sorted(
        [r for r in results if r.get("price") is not None],
        key=lambda x: x.get("price", 0) or 0,
        reverse=True
    )[:10]
    
    for r in sorted_results:
        coin = r.get("coin", "UNKNOWN")[:6]
        price = r.get("price")
        change = r.get("change")
        support = r.get("support")
        resistance = r.get("resistance")
        
        status = _get_status_emoji(r)
        
        lines.append(f"│ {coin:<4} │ {status:<8} │ {_fmt_price(price):>8} │ {_fmt_change(change):>8} │ {_fmt_price(support):>8} │ {_fmt_price(resistance):>10} │")
    
    lines.append("└──────┴──────────┴──────────┴──────────┴──────────┴────────────┘")
    
    bullish = sum(1 for r in sorted_results if "BULL" in str(r.get("action")).upper())
    bearish = sum(1 for r in sorted_results if "BEAR" in str(r.get("action")).upper())
    if bullish > bearish * 1.5:
        lines.append("📌 پیش‌بینی: روند صعودی غالب")
    elif bearish > bullish * 1.5:
        lines.append("📌 پیش‌بینی: روند نزولی غالب")
    else:
        lines.append("📌 پیش‌بینی: بازار متعادل")
    
    return lines


def build_table_personal(results):
    """ساخت جدول PERSONAL PORTFOLIO با جزئیات کامل"""
    lines = []
    lines.append("💼 PERSONAL PORTFOLIO")
    lines.append("───────────────────")
    lines.append("┌──────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐")
    lines.append("│ ASSET│ STATUS   │ PRICE    │ 24H %    │ SUPPORT  │ RESIST   │ TP1      │ SL       │")
    lines.append("├──────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤")
    
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    personal_rows = []
    for r in results:
        coin = str(r.get("coin") or "").upper()
        if coin in personal_symbols and r.get("price") is not None:
            personal_rows.append(r)
    
    personal_rows.sort(key=lambda x: x.get("coin", ""))
    
    for r in personal_rows:
        coin = r.get("coin", "UNKNOWN")[:6]
        price = r.get("price")
        change = r.get("change")
        support = r.get("support")
        resistance = r.get("resistance")
        tp1 = r.get("tp1")
        sl = r.get("sl")
        
        status = _get_status_emoji(r)
        
        lines.append(f"│ {coin:<4} │ {status:<8} │ {_fmt_price(price):>8} │ {_fmt_change(change):>8} │ {_fmt_price(support):>8} │ {_fmt_price(resistance):>8} │ {_fmt_price(tp1):>8} │ {_fmt_price(sl):>8} │")
    
    lines.append("└──────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘")
    
    bullish = sum(1 for r in personal_rows if "BULL" in str(r.get("action")).upper())
    bearish = sum(1 for r in personal_rows if "BEAR" in str(r.get("action")).upper())
    lines.append(f"📌 آمار: {bullish} ارز صعودی، {bearish} ارز نزولی، {len(personal_rows) - bullish - bearish} ارز در انتظار")
    
    return lines


def build_table_dynamic(results, dynamic30_symbols):
    """ساخت جدول DYNAMIC TOP 30"""
    lines = []
    lines.append("📡 DYNAMIC TOP 30")
    lines.append("───────────────────")
    lines.append("┌──────┬──────────┬──────────┬──────────┬──────────┬────────────┐")
    lines.append("│ ASSET│ STATUS   │ PRICE    │ 24H %    │ SUPPORT  │ RESIST     │")
    lines.append("├──────┼──────────┼──────────┼──────────┼──────────┼────────────┤")
    
    top10_set = {str(x).upper() for x in ATLAS_PRIORITY_TOP10}
    personal_set = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    dynamic_set = {str(x).upper() for x in (dynamic30_symbols or [])}
    
    dynamic_rows = []
    for r in results:
        coin = str(r.get("coin") or "").upper()
        if coin in dynamic_set and coin not in top10_set and coin not in personal_set:
            if r.get("price") is not None:
                dynamic_rows.append(r)
    
    dynamic_rows.sort(key=lambda x: x.get("price", 0) or 0, reverse=True)
    dynamic_rows = dynamic_rows[:8]
    
    for r in dynamic_rows:
        coin = r.get("coin", "UNKNOWN")[:6]
        price = r.get("price")
        change = r.get("change")
        support = r.get("support")
        resistance = r.get("resistance")
        
        status = _get_status_emoji(r)
        
        lines.append(f"│ {coin:<4} │ {status:<8} │ {_fmt_price(price):>8} │ {_fmt_change(change):>8} │ {_fmt_price(support):>8} │ {_fmt_price(resistance):>10} │")
    
    lines.append("└──────┴──────────┴──────────┴──────────┴──────────┴────────────┘")
    
    return lines


def build_table_metals():
    """ساخت جدول METALS"""
    lines = []
    lines.append("🪙 ATLAS METALS")
    lines.append("───────────────────")
    lines.append("┌──────┬──────────┬──────────┬──────────┬──────────┬────────────┐")
    lines.append("│ ASSET│ STATUS   │ PRICE    │ CHANGE   │ SUPPORT  │ RESIST     │")
    lines.append("├──────┼──────────┼──────────┼──────────┼──────────┼────────────┤")
    
    metals = [_metal_analysis(x) for x in ATLAS_METALS]
    for r in metals:
        coin = r.get("coin", "UNKNOWN")[:6]
        price = r.get("price")
        support = r.get("support")
        resistance = r.get("resistance")
        
        action = str(r.get("action") or "").upper()
        if "BUY" in action or "BULLISH" in action:
            status = "🟢 BULL"
        elif "SELL" in action or "BEARISH" in action:
            status = "🔴 BEAR"
        else:
            status = "⚪ WAIT"
        
        lines.append(f"│ {coin:<4} │ {status:<8} │ {_fmt_price(price):>8} │ {_fmt_change(None):>8} │ {_fmt_price(support):>8} │ {_fmt_price(resistance):>10} │")
    
    lines.append("└──────┴──────────┴──────────┴──────────┴──────────┴────────────┘")
    
    return lines


def build_best_setup_section(results):
    """ساخت بخش BEST SETUP"""
    lines = []
    lines.append("🔥 BEST SETUP")
    lines.append("───────────────────")
    
    best = None
    best_score = -1
    
    for r in results:
        if r.get("action") in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            score = (r.get("confidence", 0) * 0.5) + (min(r.get("rr", 0) or 0, 5) * 10)
            if score > best_score:
                best_score = score
                best = r
    
    if best:
        direction = "LONG" if best.get("direction") == "LONG" else "SHORT"
        emoji = "🟢" if direction == "LONG" else "🔴"
        lines.append(f"{emoji} {best.get('coin')} — {direction}")
        lines.append(f"   Entry: {_fmt_price(best.get('entry'))} | SL: {_fmt_price(best.get('sl'))}")
        lines.append(f"   TP1: {_fmt_price(best.get('tp1'))} | TP2: {_fmt_price(best.get('tp2'))}")
        lines.append(f"   Confidence: {best.get('confidence', 0)}% | R/R: {best.get('rr', 0):.2f}")
    else:
        lines.append("⚪ هیچ ستاپ اجرایی با R/R و هندسه معتبر در این اجرا تأیید نشد.")
    
    return lines


def build_market_summary(results):
    """ساخت بخش جمع‌بندی بازار"""
    lines = []
    lines.append("📊 MARKET SUMMARY")
    lines.append("───────────────────")
    
    total = len(results)
    bullish = sum(1 for r in results if "BULL" in str(r.get("action")).upper())
    bearish = sum(1 for r in results if "BEAR" in str(r.get("action")).upper())
    waiting = total - bullish - bearish
    
    lines.append(f"📈 کل ارزها: {total}")
    lines.append(f"🟢 صعودی: {bullish} ({bullish/total*100:.1f}%)" if total > 0 else "🟢 صعودی: 0")
    lines.append(f"🔴 نزولی: {bearish} ({bearish/total*100:.1f}%)" if total > 0 else "🔴 نزولی: 0")
    lines.append(f"⚪ در انتظار: {waiting} ({waiting/total*100:.1f}%)" if total > 0 else "⚪ در انتظار: 0")
    
    changes = [(r.get("coin"), r.get("change")) for r in results if r.get("change") is not None]
    if changes:
        best = max(changes, key=lambda x: x[1] or -999)
        worst = min(changes, key=lambda x: x[1] or 999)
        lines.append(f"🏆 بهترین: {best[0]} {best[1]:+.2f}%")
        lines.append(f"📉 بدترین: {worst[0]} {worst[1]:+.2f}%")
    
    btc_regime = btc_market_regime()
    lines.append(f"🎯 BTC Regime: {btc_regime.get('regime', 'UNKNOWN')}")
    
    return lines


def build_full_table_report(results, top10_symbols=None, dynamic30_symbols=None):
    """
    ساخت گزارش کامل جدولی با تمام بخش‌ها
    """
    lines = []
    dt = now_tehran()
    session, session_label, session_multiplier = get_current_session()
    
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"🤖 ATLAS AI — {VERSION}")
    lines.append(f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران")
    lines.append(f"🕐 سشن: {session_label} | ضریب: {session_multiplier:.1f}x")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("")
    
    lines.extend(build_best_setup_section(results))
    lines.append("")
    
    lines.extend(build_table_top10(results))
    lines.append("")
    
    lines.extend(build_table_personal(results))
    lines.append("")
    
    lines.extend(build_table_dynamic(results, dynamic30_symbols))
    lines.append("")
    
    lines.extend(build_table_metals())
    lines.append("")
    
    lines.extend(build_market_summary(results))
    
    return "\n".join(lines)


def build_v11_intelligence_report(results, portfolio):
    """ساخت گزارش هوشمندی ATLAS v11.1"""
    ranked = sorted(results, key=lambda r: float(r.get("v11_opportunity_score", 0)), reverse=True)
    lines = []
    lines.append("🧠 ATLAS v11.1 — INTELLIGENCE")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    
    for r in ranked[:10]:
        coin = str(r.get("coin", "")).upper()
        decision = r.get("v11_decision", "WAIT")
        prob = r.get("v11_estimated_probability", 0)
        quality = r.get("v11_data_quality", 0)
        score = r.get("v11_opportunity_score", 0)
        
        if decision in {"BUY", "STRONG BUY", "LONG"}:
            icon = "🟢"
        elif decision in {"SELL", "STRONG SELL", "SHORT"}:
            icon = "🔴"
        else:
            icon = "🟡"
        
        lines.append(f"{icon} {coin} | {decision} | P~{prob:.0f}% | Q:{quality:.0f} | O:{score:.0f} | V:{r.get('v11_volatility_regime', '?')}")
    
    if portfolio.get("warning"):
        lines.append(f"\n⚠️ Portfolio: {portfolio['warning']}")
    
    lines.append("\nℹ️ P~ = heuristic estimate; not calibrated win probability.")
    return "\n".join(lines)


def build_signal_ranking_table(results, top10_symbols=None, dynamic30_symbols=None):
    """ساخت جدول رتبه‌بندی سیگنال‌ها"""
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("📊 ATLAS SIGNAL RANKING")
    lines.append("━━━━━━━━━━━━━━━━━━")
    
    lines.append("")
    lines.append("🏆 TOP 10 MARKET")
    lines.append("───────────────────")
    
    sorted_by_price = sorted(
        [r for r in results if r.get("price") is not None],
        key=lambda x: x.get("price", 0) or 0,
        reverse=True
    )[:10]
    
    if sorted_by_price:
        for i, r in enumerate(sorted_by_price, 1):
            coin = r.get("coin", "UNKNOWN")
            price = r.get("price")
            change = r.get("change")
            action = str(r.get("action") or "WAIT").upper()
            
            if "BUY" in action:
                status = "🟢 BUY"
            elif "SELL" in action:
                status = "🔴 SELL"
            elif "WATCH" in action:
                status = "🟡 WATCH"
            else:
                status = "⚪ HOLD"
            
            price_str = f"${price:,.2f}" if price else "N/A"
            change_str = f"{change:+.2f}%" if change is not None else "N/A"
            lines.append(f"{i:2}. {coin:<6} {price_str:>12} | {change_str:>8} | {status}")
    else:
        lines.append("⚪ داده‌ای برای نمایش وجود ندارد")
    
    lines.append("")
    lines.append("💼 PERSONAL PORTFOLIO")
    lines.append("───────────────────")
    
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    personal_rows = []
    for r in results:
        coin = str(r.get("coin") or "").upper()
        if coin in personal_symbols and r.get("price") is not None:
            personal_rows.append(r)
    
    if personal_rows:
        personal_rows.sort(key=lambda x: x.get("coin", ""))
        for i, r in enumerate(personal_rows, 1):
            coin = r.get("coin", "UNKNOWN")
            price = r.get("price")
            change = r.get("change")
            action = str(r.get("action") or "WAIT").upper()
            
            if "BUY" in action:
                status = "🟢 BUY"
            elif "SELL" in action:
                status = "🔴 SELL"
            elif "WATCH" in action:
                status = "🟡 WATCH"
            else:
                status = "⚪ HOLD"
            
            price_str = f"${price:,.2f}" if price else "N/A"
            change_str = f"{change:+.2f}%" if change is not None else "N/A"
            lines.append(f"{i:2}. {coin:<6} {price_str:>12} | {change_str:>8} | {status}")
    else:
        lines.append("⚪ داده‌ای برای پورتفولیو موجود نیست")
    
    lines.append("")
    lines.append("📈 TOP 5 BUY/SELL SIGNALS")
    lines.append("───────────────────")
    
    signals = []
    for r in results:
        action = str(r.get("action") or "").upper()
        if action in ("BUY CONFIRMATION", "SELL CONFIRMATION", "BUY", "SELL"):
            signals.append({
                "coin": r.get("coin", "UNKNOWN"),
                "action": action,
                "confidence": r.get("confidence", 0),
                "rr": r.get("rr", 0),
                "price": r.get("price"),
                "entry": r.get("entry"),
                "sl": r.get("sl"),
                "tp1": r.get("tp1"),
                "tp2": r.get("tp2")
            })
    
    if not signals:
        for r in results:
            action = str(r.get("action") or "").upper()
            if action in ("BULLISH WATCH", "BEARISH WATCH"):
                signals.append({
                    "coin": r.get("coin", "UNKNOWN"),
                    "action": action,
                    "confidence": r.get("confidence", 0),
                    "rr": r.get("rr", 0),
                    "price": r.get("price"),
                    "entry": None,
                    "sl": None,
                    "tp1": None,
                    "tp2": None
                })
    
    signals.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    top5_signals = signals[:5]
    
    if top5_signals:
        for i, r in enumerate(top5_signals, 1):
            coin = r.get("coin", "UNKNOWN")
            action = r.get("action", "WAIT")
            
            if "BUY" in action:
                action_str = "🟢 BUY"
            elif "SELL" in action:
                action_str = "🔴 SELL"
            elif "WATCH" in action:
                action_str = "🟡 WATCH"
            else:
                action_str = "⚪ WAIT"
            
            conf = r.get("confidence", 0)
            rr = r.get("rr", 0)
            entry = r.get("entry")
            entry_str = f"${entry:,.4f}" if entry else "N/A"
            lines.append(f"{i:2}. {coin:<6} {action_str} | {conf}% | R/R {rr:.2f} | Entry {entry_str}")
    else:
        lines.append("⚪ هیچ سیگنال خرید/فروشی یافت نشد")
        lines.append("   (این بخش بر اساس داده‌های واقعی صرافی‌هاست)")
    
    lines.append("")
    session, session_label, session_multiplier = get_current_session()
    lines.append(f"🕐 سشن: {session_label} | ضریب: {session_multiplier:.1f}x")
    lines.append("━━━━━━━━━━━━━━━━━━")
    
    return "\n".join(lines)


def send_image_table(results, top10_symbols=None, dynamic30_symbols=None):
    """ارسال جدول تصویری به تمام مقاصد تلگرام"""
    if not ENABLE_IMAGE_TABLE:
        print("ℹ️ Image table disabled by ATLAS_ENABLE_IMAGE_TABLE")
        return False
    
    try:
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        
        try:
            font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
            if os.path.exists(font_path):
                fm.fontManager.addfont(font_path)
                plt.rcParams['font.family'] = 'DejaVu Sans'
            else:
                plt.rcParams['font.family'] = 'sans-serif'
        except:
            plt.rcParams['font.family'] = 'sans-serif'
        
        signals = []
        for r in results:
            action = str(r.get("action") or "").upper()
            if action in ("BUY CONFIRMATION", "SELL CONFIRMATION", "BUY", "SELL"):
                quality_score = 0
                quality_score += r.get("confidence", 0) * 0.4
                quality_score += min(r.get("rr", 0) or 0, 5) * 15
                quality_score += min(r.get("liquidity_score", 0) / 100, 1) * 15
                quality_score += 10 if r.get("sr_confidence") == "HIGH" else 5 if r.get("sr_confidence") == "MEDIUM" else 0
                quality_score += 10 if r.get("volume_ratio", 0) >= 1.5 else 5 if r.get("volume_ratio", 0) >= 1.2 else 0
                r["quality_score"] = min(100, quality_score)
                signals.append(r)
        
        if not signals:
            signals = sorted(
                [r for r in results if r.get("price") is not None],
                key=lambda x: x.get("price", 0) or 0,
                reverse=True
            )[:10]
            for r in signals:
                r["quality_score"] = 50
        
        signals.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
        top_signals = signals[:10]
        
        fig, ax = plt.subplots(figsize=(14, 10))
        ax.axis('off')
        
        cell_text = []
        headers = ['#', 'Asset', 'Direction', 'Confidence', 'R/R', 'Quality']
        cell_text.append(headers)
        
        for i, r in enumerate(top_signals, 1):
            action = str(r.get("action") or "WAIT").upper()
            if "BUY" in action:
                direction = '🟢 BUY'
            elif "SELL" in action:
                direction = '🔴 SELL'
            else:
                direction = '🟡 WATCH'
            
            row = [
                str(i),
                r.get('coin', 'UNKNOWN'),
                direction,
                f"{r.get('confidence', 0)}%",
                f"{r.get('rr', 0):.2f}" if r.get('rr') else "N/A",
                f"{r.get('quality_score', 0):.0f}%"
            ]
            cell_text.append(row)
        
        while len(cell_text) < 11:
            cell_text.append(['', '', '', '', '', ''])
        
        table = ax.table(cellText=cell_text, loc='center', cellLoc='center')
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1, 2.5)
        
        for i, row in enumerate(cell_text):
            for j, cell in enumerate(row):
                if i == 0:
                    table[(i, j)].set_facecolor('#2c3e50')
                    table[(i, j)].set_text_props(color='white', weight='bold')
                elif i % 2 == 0:
                    table[(i, j)].set_facecolor('#ecf0f1')
                else:
                    table[(i, j)].set_facecolor('#ffffff')
                
                if i > 0 and j == 5 and cell:
                    try:
                        val = int(cell.replace('%', ''))
                        if val >= 80:
                            table[(i, j)].set_facecolor('#27ae60')
                            table[(i, j)].set_text_props(color='white')
                        elif val >= 60:
                            table[(i, j)].set_facecolor('#f1c40f')
                        else:
                            table[(i, j)].set_facecolor('#e74c3c')
                            table[(i, j)].set_text_props(color='white')
                    except:
                        pass
                
                if i > 0 and j == 2:
                    if 'BUY' in cell:
                        table[(i, j)].set_facecolor('#27ae60')
                        table[(i, j)].set_text_props(color='white')
                    elif 'SELL' in cell:
                        table[(i, j)].set_facecolor('#e74c3c')
                        table[(i, j)].set_text_props(color='white')
        
        ax.set_title('📊 ATLAS SIGNAL RANKING', fontsize=16, weight='bold', pad=20)
        
        plt.tight_layout()
        plt.savefig("signal_table.png", dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        # ارسال تصویر به همه مقاصد
        with open("signal_table.png", 'rb') as f:
            image_data = f.read()
        
        destinations = []
        if TELEGRAM_CHAT_ID and str(TELEGRAM_CHAT_ID).strip():
            destinations.append({
                "id": str(TELEGRAM_CHAT_ID).strip(),
                "name": "PRIVATE_CHAT"
            })
        if TELEGRAM_GROUP_CHAT_ID and str(TELEGRAM_GROUP_CHAT_ID).strip():
            group_id = str(TELEGRAM_GROUP_CHAT_ID).strip()
            if group_id not in [d["id"] for d in destinations]:
                destinations.append({
                    "id": group_id,
                    "name": "SUPERGROUP"
                })
        
        if not destinations:
            return False
        
        success_count = 0
        
        for dest in destinations:
            chat_id = dest["id"]
            dest_name = dest["name"]
            
            print(f"  Sending image to {dest_name}...", end=" ", flush=True)
            
            boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
            body = bytearray()
            
            body.extend(f'--{boundary}\r\n'.encode())
            body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
            body.extend(str(chat_id).encode())
            body.extend(b'\r\n')
            
            body.extend(f'--{boundary}\r\n'.encode())
            body.extend(b'Content-Disposition: form-data; name="photo"; filename="signal_table.png"\r\n'.encode())
            body.extend(b'Content-Type: image/png\r\n\r\n')
            body.extend(image_data)
            body.extend(b'\r\n')
            body.extend(f'--{boundary}--\r\n'.encode())
            
            headers = {
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Content-Length': str(len(body))
            }
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            req = urllib.request.Request(url, data=bytes(body), headers=headers, method='POST')
            
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    result = json.loads(response.read().decode())
                    if result.get('ok', False):
                        print("✅")
                        success_count += 1
                    else:
                        print(f"❌ {result.get('description', 'Unknown error')}")
            except Exception as e:
                print(f"❌ {e}")
        
        try:
            os.unlink("signal_table.png")
        except:
            pass
        
        return success_count > 0
    except ImportError as e:
        print(f"⚠️ Matplotlib not installed: {e}")
        return False
    except Exception as e:
        print(f"⚠️ Image generation error: {e}")
        return False


def send_csv_report(results, top10, dynamic30):
    """ارسال CSV به تمام مقاصد"""
    # کد موجود در فایل اصلی
    import csv, io
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    
    content = generate_csv_report(results, top10, dynamic30)
    if not content.strip():
        return 0, ["CSV is empty"]
    
    dt = now_tehran()
    filename = f"atlas_report_{shamsi(dt).replace('/','')}_{dt.strftime('%H%M%S')}.csv"
    caption = f"📎 ATLAS AI — CSV کامل | {VERSION} | {shamsi(dt)} {dt.strftime('%H:%M:%S')} تهران"
    
    destinations = []
    for chat_id in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if chat_id and chat_id not in destinations:
            destinations.append(chat_id)
    
    sent = 0
    errors = []
    for chat_id in destinations:
        try:
            boundary = "----ATLAS" + uuid.uuid4().hex
            body = bytearray()
            def field(name, value):
                body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode())
            field("chat_id", str(chat_id))
            if caption:
                field("caption", caption)
            body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: text/csv; charset=utf-8\r\n\r\n").encode())
            body.extend(content.encode("utf-8-sig"))
            body.extend(f"\r\n--{boundary}--\r\n".encode())
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if data.get("ok"):
                    sent += 1
                else:
                    errors.append(f"CSV {chat_id}: {data}")
        except Exception as e:
            errors.append(f"CSV {chat_id}: {e}")
    
    return sent, errors


def generate_csv_report(results, top10, dynamic30):
    """تولید گزارش CSV کامل"""
    import csv, io
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    top10_set = {str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)}
    dynamic_set = {str(x).upper() for x in (dynamic30 or [])}
    result_map = {str(r.get("coin") or "").upper(): dict(r) for r in (results or []) if r.get("coin")}
    
    ordered = []
    for sym in list(top10 or ATLAS_PRIORITY_TOP10) + list(dynamic30 or []) + list(ATLAS_PERSONAL_ASSETS):
        s = str(sym).upper()
        if s and s not in ordered:
            ordered.append(s)
    for metal in ATLAS_METALS:
        if metal not in ordered:
            ordered.append(metal)
    
    rows = []
    for sym in ordered:
        r = result_map.get(sym)
        if r is None and sym in ATLAS_METALS:
            r = _metal_analysis(sym)
        if not r:
            continue
        
        rows.append([
            "PERSONAL_PORTFOLIO" if sym in personal_symbols else "MARKET_TOP10" if sym in top10_set else "DYNAMIC_TOP30" if sym in dynamic_set else "ATLAS_RADAR",
            sym,
            "BUY" if "BUY" in str(r.get("action")).upper() else "SELL" if "SELL" in str(r.get("action")).upper() else "WATCH" if "WATCH" in str(r.get("action")).upper() else "HOLD",
            r.get("decision_state", "WAIT"),
            r.get("price"),
            r.get("change"),
            r.get("support"),
            r.get("resistance"),
            r.get("entry"),
            r.get("sl"),
            r.get("tp1"),
            r.get("tp2"),
            r.get("tp3"),
            r.get("tp4"),
            r.get("rr"),
            r.get("confidence"),
            r.get("h4_trend"),
            r.get("d1_trend"),
            r.get("w1_trend"),
            r.get("rsi"),
            r.get("macd"),
            r.get("volume"),
            r.get("volume_ratio"),
            r.get("atr_pct"),
            r.get("liquidity"),
            r.get("gate"),
            r.get("gate_reason"),
            r.get("direction"),
            r.get("repeat_signal"),
            r.get("reason"),
            VERSION
        ])
    
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([
        "Group", "Symbol", "Status", "DecisionState", "Price", "Change24H",
        "Support", "Resistance", "Entry", "SL", "TP1", "TP2", "TP3", "TP4",
        "R/R", "Confidence", "H4Trend", "D1Trend", "W1Trend", "RSI", "MACD",
        "Volume", "VolumeRatio", "ATR_pct", "Liquidity", "Gate", "GateReason",
        "Direction", "RepeatSignal", "Reason", "ModelVersion"
    ])
    writer.writerows(rows)
    return out.getvalue()


# ============================================================
# بقیه کدهای اصلی (CCXT، EXCHANGE، PRICE، SIGNAL SCORING، ANALYZE COIN، DECISION ENGINE، و ...)
# ============================================================
# (همه کدهای قبلی بدون تغییر باقی می‌مانند)
# ============================================================


# ============================================================
# MAIN - نسخه اصلاح‌شده با ارسال تصویر به جای متن
# ============================================================

_LAST_TOP10 = []
_LAST_DYNAMIC30 = []


def report():
    init_sqlite()
    evaluate_open_outcomes()
    universe, top10, dynamic30 = build_universe()
    global _LAST_TOP10, _LAST_DYNAMIC30
    _LAST_TOP10, _LAST_DYNAMIC30 = list(top10), list(dynamic30)

    backtest_ok, bt = mandatory_backtest_gate(universe)
    if backtest_ok:
        self_diagnostic()
    else:
        append_changelog("SELF_HEALING", None, None,
                         "Model adaptation frozen because mandatory backtest gate failed", bt)

    weights = get_weights()
    news = news_feed()
    macro = macro_snapshot()
    market_info = global_market_intelligence()
    results = []
    unavailable = 0
    for coin in universe:
        try:
            if is_stable(coin):
                continue
            r = analyze_coin(coin, news, weights)
            if r and not is_stable(str(r.get("coin") or "")):
                results.append(r)
        except Exception as e:
            unavailable += 1
            append_changelog("ASSET_ERROR", None, None, f"{coin}: {e}", {"traceback": traceback.format_exc()})
        time.sleep(REQUEST_SLEEP_SECONDS)

    btc_regime = btc_market_regime()
    breadth = market_breadth(results)
    results = apply_decision_engine(results, btc_regime, breadth)

    for r in results:
        r["action"] = r.get("decision_state", r.get("action"))
        store_signal(r)
    text = build_report(results, top10, dynamic30, macro, news, market_info, unavailable, btc_regime, breadth)
    return text, results, macro, news, market_info, unavailable


def main():
    try:
        telegram_preflight()
        run_mode = get_run_mode()
        
        if run_mode == "AUTO":
            plan = _automatic_run_plan()
            do_analysis, do_snapshot = plan["analysis"], plan["snapshot"]
        elif run_mode == "SNAPSHOT":
            do_analysis, do_snapshot = False, True
        elif run_mode == "ANALYSIS":
            do_analysis, do_snapshot = True, False
        else:
            do_analysis, do_snapshot = True, True

        total_sent = 0
        all_errors = []
        analysis_results = []

        if do_analysis:
            text, results, macro, news, market_info, unavailable = report()
            
            # اعمال لایه هوشمندی
            for r in results:
                r = v11_apply_intelligence(r)
            
            v11_portfolio = v11_portfolio_diagnostics(results)
            top10, dynamic30 = list(_LAST_TOP10), list(_LAST_DYNAMIC30)
            btc_regime = btc_market_regime()
            breadth = market_breadth(results)
            
            # ============================================================
            # 📊 ساخت گزارش کامل جدولی
            # ============================================================
            full_table_report = build_full_table_report(results, top10, dynamic30)
            
            # ============================================================
            # 🧠 گزارش هوشمندی
            # ============================================================
            intelligence_report = build_v11_intelligence_report(results, v11_portfolio)
            
            # ============================================================
            # 📈 جدول رتبه‌بندی سیگنال‌ها
            # ============================================================
            signal_ranking = build_signal_ranking_table(results, top10, dynamic30)
            
            # ============================================================
            # ✅ ارسال همه گزارش‌ها به صورت تصویر PNG
            # ============================================================
            caption = f"📊 ATLAS REPORT | {shamsi(now_tehran())} | {get_current_session()[1]}"
            
            # 1. گزارش کامل جدولی
            image_sent = send_report_as_image(full_table_report, caption)
            if image_sent:
                print("✅ Report image sent successfully to all destinations")
            else:
                print("❌ Report image failed to send")
            
            # 2. گزارش هوشمندی
            intelligence_sent = send_report_as_image(intelligence_report, "🧠 ATLAS INTELLIGENCE")
            if intelligence_sent:
                print("✅ Intelligence report sent successfully")
            else:
                print("❌ Intelligence report failed to send")
            
            # 3. جدول رتبه‌بندی سیگنال‌ها (با matplotlib)
            signal_image_sent = send_image_table(results, top10, dynamic30)
            if signal_image_sent:
                print("✅ Signal ranking image sent successfully")
            else:
                print("ℹ️ Signal ranking image not sent")
            
            # ============================================================
            # 📎 ارسال CSV
            # ============================================================
            csv_sent, csv_errors = send_csv_report(results, top10, dynamic30)
            total_sent += csv_sent
            all_errors.extend(csv_errors)
            print(f"CSV export: {csv_sent} destination(s), {len(csv_errors)} error(s)")
            
            analysis_results = results
            save_context(macro, news, market_liquidity_index(results), market_info)
            save_run(results, 0, macro, news, unavailable)

        if do_snapshot:
            snapshot_results = analysis_results if analysis_results else fetch_snapshot_results()
            snapshot_sent, snapshot_errors = send_price_snapshot(snapshot_results)
            total_sent += snapshot_sent
            all_errors.extend(snapshot_errors)

        # ============================================================
        # 🎤 Voice Output
        # ============================================================
        if ENABLE_VOICE_REPORT and AUTO_SEND_VOICE:
            try:
                print("\n🎤 Generating audio report...")
                voice_data = analysis_results if analysis_results else snapshot_results
                if voice_data:
                    news_data = news if 'news' in locals() else None
                    btc_data = btc_regime if 'btc_regime' in locals() else None
                    audio_file = generate_audio_report(voice_data, news_data, btc_data)
                    if audio_file:
                        result = send_audio_report(audio_file, "🎤 گزارش صوتی کامل اطلس")
                        if result:
                            print("✅ Audio report sent successfully to all destinations")
                        try:
                            os.unlink(audio_file)
                        except:
                            pass
                else:
                    print("⚠️ No voice data available")
            except Exception as e:
                print(f"⚠️ Audio error: {e}")
                traceback.print_exc()
        else:
            if not ENABLE_VOICE_REPORT:
                print(f"ℹ️ Voice disabled: ENABLE_VOICE_REPORT={ENABLE_VOICE_REPORT}")
            elif not AUTO_SEND_VOICE:
                print(f"ℹ️ Voice disabled: AUTO_SEND_VOICE={AUTO_SEND_VOICE}")

        if not do_analysis and not do_snapshot:
            print(f"{VERSION}: AUTO schedule has no task at this hour.")
            return 0

        if all_errors or total_sent == 0:
            raise RuntimeError("Telegram delivery failed: " + "; ".join(all_errors or ["0 messages sent"]))
        return 0
    except Exception as e:
        tb = traceback.format_exc()
        append_changelog("FATAL", None, None, str(e), {"traceback": tb})
        print(f"{VERSION} ERROR: {e}")
        try:
            if TELEGRAM_TOKEN and (TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID):
                alert = f"🚨 {VERSION} FAILED\nReason: {str(e)[:900]}\n\nCheck GitHub Actions log and changelog.txt."
                for destination in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
                    if destination:
                        try:
                            telegram_send_one(destination, alert)
                        except Exception as te:
                            print(f"Telegram error alert failed: {te}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
