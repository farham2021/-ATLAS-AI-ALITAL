# ============================================================
# ATLAS AI v11.1 — UNIFIED TWO-ENGINE DECISION ENGINE
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
import csv
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from statistics import mean, median

import ccxt


# ============================================================
# CONFIG
# ============================================================

VERSION = "ATLAS v11.1 UNIFIED TWO-ENGINE"
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

# Voice Output Settings
def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)

ENABLE_VOICE_REPORT = _parse_bool(os.environ.get("ATLAS_ENABLE_VOICE", "1"))
AUTO_SEND_VOICE = _parse_bool(os.environ.get("ATLAS_AUTO_SEND_VOICE", "1"))
VOICE_TYPE = os.environ.get("ATLAS_VOICE_TYPE", "female")
VOICE_LANGUAGE = os.environ.get("ATLAS_VOICE_LANGUAGE", "fa")

# Image Table Settings
ENABLE_IMAGE_TABLE = _parse_bool(os.environ.get("ATLAS_ENABLE_IMAGE_TABLE", "1"))

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
# MARKET SESSIONS
# ============================================================

MARKET_SESSIONS = {
    "ASIA": {"open": 0, "close": 8, "label": "🇯🇵 آسیا", "multiplier": 0.8},
    "EUROPE": {"open": 7, "close": 15, "label": "🇬🇧 اروپا", "multiplier": 1.0},
    "AMERICA": {"open": 12, "close": 20, "label": "🇺🇸 آمریکا", "multiplier": 0.9},
    "OVERLAP": {"open": 12, "close": 15, "label": "🔀 همپوشانی اروپا-آمریکا", "multiplier": 1.2},
}

def get_current_session(dt=None):
    """تشخیص سشن فعلی بازار و ضریب کیفیت آن"""
    dt = dt or now_utc()
    hour = dt.hour
    for name, session in MARKET_SESSIONS.items():
        if session["open"] <= hour < session["close"]:
            return name, session["label"], session["multiplier"]
    return "CLOSED", "🔒 خارج از سشن", 0.7


# ============================================================
# VOICE SUMMARY & OUTPUT
# ============================================================

def generate_voice_summary(results):
    """تولید خلاصه صوتی از نتایج"""
    if not results:
        print("⚠️ generate_voice_summary: results is empty")
        return "هیچ داده‌ای برای گزارش صوتی موجود نیست."
    
    print(f"📝 generate_voice_summary: processing {len(results)} items")
    
    # دریافت سشن فعلی
    session, session_label, session_multiplier = get_current_session()
    
    # تحلیل قیمت‌ها
    prices = []
    up_count = 0
    down_count = 0
    stable_count = 0
    changes = []
    
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
    
    print(f"📊 Voice stats: up={up_count}, down={down_count}, stable={stable_count}, changes={len(changes)}")
    
    # تولید متن صوتی
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
    
    # بهترین و بدترین عملکرد
    if changes:
        best = max(changes, key=lambda x: x[1])
        worst = min(changes, key=lambda x: x[1])
        if best[1] > 0:
            lines.append(f"بهترین عملکرد: {best[0]} با رشد {best[1]:.2f} درصد.")
        if worst[1] < 0:
            lines.append(f"ضعیف‌ترین عملکرد: {worst[0]} با کاهش {abs(worst[1]):.2f} درصد.")
    
    # قیمت تتر
    usdt = fetch_usdt_toman_public()
    if usdt:
        lines.append(f"نرخ تتر: {usdt:,.0f} تومان.")
    
    lines.append("این پیام به صورت خودکار هر ۳ ساعت بروزرسانی می‌شود.")
    
    result = " ".join(lines)
    print(f"📝 Voice text length: {len(result)} characters")
    return result


def generate_voice_summary_from_snapshot(results):
    """تولید خلاصه صوتی از داده‌های اسنپ‌شات"""
    if not results:
        return "هیچ داده‌ای برای گزارش صوتی موجود نیست."
    
    # دریافت سشن فعلی
    session, session_label, session_multiplier = get_current_session()
    
    # تحلیل قیمت‌ها
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
    
    # تولید متن صوتی
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
    
    # بهترین و بدترین عملکرد
    if changes:
        best = max(changes, key=lambda x: x[1])
        worst = min(changes, key=lambda x: x[1])
        if best[1] > 0:
            lines.append(f"بهترین عملکرد: {best[0]} با رشد {best[1]:.2f} درصد.")
        if worst[1] < 0:
            lines.append(f"ضعیف‌ترین عملکرد: {worst[0]} با کاهش {abs(worst[1]):.2f} درصد.")
    
    # قیمت تتر
    usdt = fetch_usdt_toman_public()
    if usdt:
        lines.append(f"نرخ تتر: {usdt:,.0f} تومان.")
    
    lines.append("این پیام به صورت خودکار هر ۳ ساعت بروزرسانی می‌شود.")
    
    return " ".join(lines)


def text_to_speech_persian(text, voice="female"):
    """تبدیل متن فارسی به صدا - اولویت: Edge TTS → gTTS → Google Translate"""
    
    # ============================================================
    # مسیر اول: Edge TTS (کیفیت بالا، بدون نیاز به اینترنت آزاد)
    # ============================================================
    try:
        import edge_tts
        import asyncio
        voice_map = {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"}
        selected_voice = voice_map.get(voice, "fa-IR-DilaraNeural")
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        output_path = temp_file.name
        temp_file.close()
        
        print(f"🎤 Using Edge TTS with voice: {selected_voice}")
        
        async def generate():
            communicate = edge_tts.Communicate(text, selected_voice)
            await communicate.save(output_path)
        
        asyncio.run(generate())
        print(f"✅ Edge TTS generated: {output_path}")
        return output_path
    except ImportError as e:
        print(f"⚠️ edge-tts not installed: {e}")
    except Exception as e:
        print(f"⚠️ Edge TTS error: {e}")
    
    # ============================================================
    # مسیر دوم: gTTS (Google Text-to-Speech)
    # ============================================================
    try:
        from gtts import gTTS
        print("🎤 Using gTTS (Google TTS)")
        tts = gTTS(text=text, lang="fa", slow=False)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        tts.save(temp_file.name)
        print(f"✅ gTTS generated: {temp_file.name}")
        return temp_file.name
    except ImportError as e:
        print(f"⚠️ gTTS not installed: {e}")
    except Exception as e:
        print(f"⚠️ gTTS error: {e}")
    
    # ============================================================
    # مسیر سوم: Google Translate TTS (بدون کتابخانه، مستقیم)
    # ============================================================
    try:
        print("🎤 Using Google Translate TTS (fallback)")
        text_encoded = urllib.parse.quote(text)
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={text_encoded}&tl=fa&client=tw-ob"
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            audio_data = response.read()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_file.write(audio_data)
        temp_file.close()
        print(f"✅ Google Translate TTS generated: {temp_file.name}")
        return temp_file.name
    except Exception as e:
        print(f"⚠️ Google Translate TTS error: {e}")
        return None


def generate_audio_report(results, filename="audio_report.mp3"):
    """تولید فایل صوتی از گزارش - FIXED: accepts list of dicts"""
    if not results:
        print("⚠️ generate_audio_report: results is empty")
        return None
    
    print(f"🎤 generate_audio_report: processing {len(results)} items")
    
    # Generate voice text from results
    audio_text = generate_voice_summary(results)
    
    # Fallback: if text is too short, try snapshot format
    if len(audio_text) < 50:
        audio_text = generate_voice_summary_from_snapshot(results)
    
    print(f"🎤 Generating audio with text: {audio_text[:100]}...")
    audio_file = text_to_speech_persian(audio_text, VOICE_TYPE)
    
    if audio_file:
        import shutil
        final_path = filename
        shutil.move(audio_file, final_path)
        print(f"✅ Audio file saved: {final_path}")
        return final_path
    
    return None


def send_audio_report(audio_file, caption=None):
    """
    ارسال گزارش صوتی به تلگرام - با Multipart فرمت صحیح و Binary-safe
    """
    if not os.path.exists(audio_file):
        print(f"❌ Audio file not found: {audio_file}")
        return False
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set")
        return False
    if not AUTO_SEND_VOICE:
        print("ℹ️ AUTO_SEND_VOICE is disabled, skipping audio send")
        return False
    
    print(f"📤 Sending audio file: {audio_file} ({os.path.getsize(audio_file)} bytes)")
    
    # ============================================================
    # خواندن فایل به صورت باینری
    # ============================================================
    with open(audio_file, 'rb') as f:
        audio_data = f.read()
    
    # ============================================================
    # ساخت Multipart فرمت صحیح - Binary-safe
    # ============================================================
    boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
    
    # ساخت Body به صورت bytearray برای جلوگیری از تغییر بایت‌ها
    body = bytearray()
    
    # فیلد chat_id
    body.extend(f'--{boundary}\r\n'.encode())
    body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    chat_id = TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID
    if chat_id:
        body.extend(str(chat_id).encode())
    body.extend(b'\r\n')
    
    # فیلد caption (اختیاری)
    if caption:
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
        body.extend(caption.encode('utf-8'))
        body.extend(b'\r\n')
    
    # ============================================================
    # فیلد audio - با بایت‌های خام MP3 (بدون تبدیل)
    # ============================================================
    body.extend(f'--{boundary}\r\n'.encode())
    body.extend(f'Content-Disposition: form-data; name="audio"; filename="{os.path.basename(audio_file)}"\r\n'.encode())
    body.extend(b'Content-Type: audio/mpeg\r\n\r\n')
    body.extend(audio_data)  # <--- بایت‌های خام MP3 بدون تغییر
    body.extend(b'\r\n')
    
    # پایان Multipart
    body.extend(f'--{boundary}--\r\n'.encode())
    
    # ============================================================
    # ارسال به تلگرام
    # ============================================================
    headers = {
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Content-Length': str(len(body))
    }
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
    req = urllib.request.Request(url, data=bytes(body), headers=headers, method='POST')
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            print(f"📤 Telegram audio response: {result.get('ok', False)}")
            if result.get('ok'):
                print("✅ Audio sent successfully")
                return True
            else:
                print(f"❌ Telegram error: {result.get('description', 'Unknown error')}")
                return False
    except Exception as e:
        print(f"❌ Audio send error: {e}")
        return False


# ============================================================
# SIGNAL RANKING TABLE
# ============================================================

def build_signal_ranking_table(results, top10_symbols=None, dynamic30_symbols=None):
    """
    ساخت جدول رتبه‌بندی سیگنال‌ها با فرمت Telegram
    شامل: TOP 10 اجرایی + TOP 5 فرصت‌های پتانسیل‌دار
    """
    # فیلتر کردن سیگنال‌های اجرایی
    executable = []
    for r in results:
        action = str(r.get("action") or "").upper()
        if action in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            # محاسبه امتیاز کیفیت
            quality_score = 0
            quality_score += r.get("confidence", 0) * 0.4
            quality_score += min(r.get("rr", 0) or 0, 5) * 15
            quality_score += min(r.get("liquidity_score", 0) / 100, 1) * 15
            quality_score += 10 if r.get("sr_confidence") == "HIGH" else 5 if r.get("sr_confidence") == "MEDIUM" else 0
            quality_score += 10 if r.get("volume_ratio", 0) >= 1.5 else 5 if r.get("volume_ratio", 0) >= 1.2 else 0
            r["quality_score"] = min(100, quality_score)
            executable.append(r)
    
    # مرتب‌سازی بر اساس کیفیت
    executable.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    
    # TOP 10 اجرایی
    top10_exec = executable[:10]
    
    # TOP 5 فرصت‌های پتانسیل‌دار (از Dynamic 30)
    opportunities = []
    dynamic_set = {str(x).upper() for x in (dynamic30_symbols or [])}
    for r in results:
        coin = str(r.get("coin") or "").upper()
        if coin in dynamic_set:
            if r.get("action") in ("BULLISH WATCH", "BEARISH WATCH"):
                # امتیاز فرصت
                opp_score = r.get("confidence", 0) * 0.5
                opp_score += min(r.get("rr", 0) or 0, 3) * 10
                opp_score += r.get("liquidity_score", 0) * 0.1
                r["opp_score"] = opp_score
                opportunities.append(r)
    
    opportunities.sort(key=lambda x: x.get("opp_score", 0), reverse=True)
    top5_opp = opportunities[:5]
    
    # ساخت جدول
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("📊 ATLAS SIGNAL RANKING")
    lines.append("━━━━━━━━━━━━━━━━━━")
    
    # TOP 10 اجرایی
    lines.append("")
    lines.append("🎯 TOP 10 EXECUTABLE SIGNALS")
    lines.append("───────────────────")
    if top10_exec:
        for i, r in enumerate(top10_exec, 1):
            coin = r.get("coin", "UNKNOWN")
            direction = "🟢 BUY" if r.get("direction") == "LONG" else "🔴 SELL"
            conf = r.get("confidence", 0)
            rr = r.get("rr", 0)
            quality = r.get("quality_score", 0)
            lines.append(f"{i:2}. {coin:<6} {direction} | {conf}% | R/R {rr:.2f} | Q:{quality:.0f}%")
    else:
        lines.append("⚪ هیچ سیگنال اجرایی یافت نشد")
    
    # TOP 5 فرصت‌ها
    lines.append("")
    lines.append("🚀 TOP 5 OPPORTUNITIES (Dynamic 30)")
    lines.append("───────────────────")
    if top5_opp:
        for i, r in enumerate(top5_opp, 1):
            coin = r.get("coin", "UNKNOWN")
            action = "📈 WATCH" if r.get("action") == "BULLISH WATCH" else "📉 WATCH"
            conf = r.get("confidence", 0)
            opp = r.get("opp_score", 0)
            lines.append(f"{i:2}. {coin:<6} {action} | {conf}% | Score:{opp:.0f}")
    else:
        lines.append("⚪ هیچ فرصت پتانسیل‌داری یافت نشد")
    
    # اطلاعات تکمیلی
    lines.append("")
    session, session_label, session_multiplier = get_current_session()
    lines.append(f"🕐 سشن: {session_label} | ضریب: {session_multiplier:.1f}x")
    lines.append("━━━━━━━━━━━━━━━━━━")
    
    return "\n".join(lines)


def build_image_table(results, top10_symbols=None, dynamic30_symbols=None, filename="signal_table.png"):
    """ساخت جدول تصویری از سیگنال‌ها"""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        
        # تنظیم فونت
        try:
            font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
            if os.path.exists(font_path):
                fm.fontManager.addfont(font_path)
                plt.rcParams['font.family'] = 'DejaVu Sans'
            else:
                plt.rcParams['font.family'] = 'sans-serif'
        except:
            plt.rcParams['font.family'] = 'sans-serif'
        
        # آماده‌سازی داده‌ها
        executable = []
        for r in results:
            action = str(r.get("action") or "").upper()
            if action in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
                quality_score = 0
                quality_score += r.get("confidence", 0) * 0.4
                quality_score += min(r.get("rr", 0) or 0, 5) * 15
                quality_score += min(r.get("liquidity_score", 0) / 100, 1) * 15
                quality_score += 10 if r.get("sr_confidence") == "HIGH" else 5 if r.get("sr_confidence") == "MEDIUM" else 0
                quality_score += 10 if r.get("volume_ratio", 0) >= 1.5 else 5 if r.get("volume_ratio", 0) >= 1.2 else 0
                r["quality_score"] = min(100, quality_score)
                executable.append(r)
        
        executable.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
        top10_exec = executable[:10]
        
        # ساخت جدول
        fig, ax = plt.subplots(figsize=(14, 10))
        ax.axis('off')
        
        # ایجاد سلول‌های جدول
        cell_text = []
        headers = ['#', 'Asset', 'Direction', 'Confidence', 'R/R', 'Quality']
        cell_text.append(headers)
        
        for i, r in enumerate(top10_exec, 1):
            direction = '🟢 BUY' if r.get('direction') == 'LONG' else '🔴 SELL'
            row = [
                str(i),
                r.get('coin', 'UNKNOWN'),
                direction,
                f"{r.get('confidence', 0)}%",
                f"{r.get('rr', 0):.2f}",
                f"{r.get('quality_score', 0):.0f}%"
            ]
            cell_text.append(row)
        
        # اگر کمتر از 10 تا بود، با ردیف‌های خالی پر کن
        while len(cell_text) < 11:
            cell_text.append(['', '', '', '', '', ''])
        
        # رسم جدول
        table = ax.table(cellText=cell_text, loc='center', cellLoc='center')
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1, 2.5)
        
        # تنظیم رنگ‌ها
        for i, row in enumerate(cell_text):
            for j, cell in enumerate(row):
                if i == 0:  # هدر
                    table[(i, j)].set_facecolor('#2c3e50')
                    table[(i, j)].set_text_props(color='white', weight='bold')
                elif i % 2 == 0:
                    table[(i, j)].set_facecolor('#ecf0f1')
                else:
                    table[(i, j)].set_facecolor('#ffffff')
                
                # رنگ‌بندی بر اساس کیفیت
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
                
                # رنگ‌بندی جهت خرید/فروش
                if i > 0 and j == 2:
                    if 'BUY' in cell:
                        table[(i, j)].set_facecolor('#27ae60')
                        table[(i, j)].set_text_props(color='white')
                    elif 'SELL' in cell:
                        table[(i, j)].set_facecolor('#e74c3c')
                        table[(i, j)].set_text_props(color='white')
        
        # عنوان
        ax.set_title('📊 ATLAS SIGNAL RANKING', fontsize=16, weight='bold', pad=20)
        
        # ذخیره تصویر
        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"✅ Image table saved: {filename}")
        return filename
    except ImportError as e:
        print(f"⚠️ Matplotlib not installed: {e}")
        return None
    except Exception as e:
        print(f"⚠️ Image generation error: {e}")
        return None


def send_image_table(results, top10_symbols=None, dynamic30_symbols=None):
    """ارسال جدول تصویری به تلگرام"""
    if not ENABLE_IMAGE_TABLE:
        print("ℹ️ Image table disabled")
        return False
    
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set")
        return False
    
    filename = build_image_table(results, top10_symbols, dynamic30_symbols)
    if not filename or not os.path.exists(filename):
        print("❌ Image generation failed")
        return False
    
    try:
        with open(filename, 'rb') as f:
            image_data = f.read()
        
        boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
        body = bytearray()
        
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        chat_id = TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID
        if chat_id:
            body.extend(str(chat_id).encode())
        body.extend(b'\r\n')
        
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(b'Content-Disposition: form-data; name="photo"; filename="signal_table.png"\r\n')
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
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode())
            os.unlink(filename)
            if result.get('ok'):
                print("✅ Image sent successfully")
                return True
            else:
                print(f"❌ Telegram error: {result.get('description', 'Unknown error')}")
                return False
    except Exception as e:
        print(f"❌ Image send error: {e}")
        try:
            os.unlink(filename)
        except:
            pass
        return False


# ============================================================
# MULTI-SOURCE VALIDATION LAYER
# ============================================================
# Exchange OHLCV/tickers are the execution-grade market layer.
# CoinGecko/CMC are independent aggregation cross-checks.
# CoinGlass is derivatives context.
# TradingView is confirmation-only and only consumes a real authorized
# endpoint if supplied; ATLAS never fabricates TradingView values.
# CryptoBubbles/EasyTrader/OMPFinex/Bitunix/TabTrader/KCEX are optional
# adapters. They are ignored unless a real endpoint is configured.
TRADINGVIEW_CONFIRMATION_URL = os.environ.get("TRADINGVIEW_CONFIRMATION_URL", "").strip()
TRADINGVIEW_CHART_EXCHANGE = os.environ.get("ATLAS_TRADINGVIEW_EXCHANGE", "BYBIT").strip().upper() or "BYBIT"
TRADINGVIEW_INTERVAL = os.environ.get("ATLAS_TRADINGVIEW_INTERVAL", "240").strip() or "240"
CRYPTOBUBBLES_API_URL = os.environ.get("CRYPTOBUBBLES_API_URL", "").strip()
EASYTRADER_API_URL = os.environ.get("EASYTRADER_API_URL", "").strip()
OMPFINEX_API_URL = os.environ.get("OMPFINEX_API_URL", "").strip()
BITUNIX_API_URL = os.environ.get("BITUNIX_API_URL", "").strip()
TABTRADER_API_URL = os.environ.get("TABTRADER_API_URL", "").strip()
KCEX_API_URL = os.environ.get("KCEX_API_URL", "").strip()

SECONDARY_ENDPOINTS = {
    "CryptoBubbles": CRYPTOBUBBLES_API_URL,
    "EasyTrader": EASYTRADER_API_URL,
    "OMPFinex": OMPFINEX_API_URL,
    "Bitunix": BITUNIX_API_URL,
    "TabTrader": TABTRADER_API_URL,
    "KCEX": KCEX_API_URL,
}

# ============================================================
# تنظیمات پیشنهادی برای سیگنال‌های بیشتر
# ============================================================
# برای دریافت سیگنال‌های بیشتر می‌توانید مقادیر زیر را کاهش دهید:
# 1. MIN_CONFIDENCE را از ۶۰ به ۵۵ کاهش دهید
# 2. MIN_VOLUME_RATIO را از ۰.۸۰ به ۰.۶۰ کاهش دهید
# 3. در سشن همپوشانی اروپا-آمریکا (ساعت ۱۵:۳۰ تا ۱۸:۳۰ تهران) اجرا کنید
# ============================================================

RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE_PCT", "1.5"))
MAX_PORTFOLIO_RISK = float(os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT", "6.0"))
MIN_CONFIDENCE = float(os.environ.get("ATLAS_MIN_CONFIDENCE", "55"))
MAX_LEVERAGE = float(os.environ.get("ATLAS_MAX_LEVERAGE", "10"))
BACKTEST_DAYS = int(os.environ.get("ATLAS_BACKTEST_DAYS", "180"))
SIGNAL_HORIZON_BARS = int(os.environ.get("ATLAS_SIGNAL_HORIZON_BARS", "36"))
MIN_BACKTEST_IMPROVEMENT = float(os.environ.get("ATLAS_BACKTEST_IMPROVEMENT", "10"))
BACKTEST_REFRESH_HOURS = float(os.environ.get("ATLAS_BACKTEST_REFRESH_HOURS", "24"))
MIN_VOLUME_RATIO = float(os.environ.get("ATLAS_MIN_VOLUME_RATIO", "0.60"))
H4_FALLBACK_MIN_SCORE = float(os.environ.get("ATLAS_H4_FALLBACK_MIN_SCORE", "70"))
REQUEST_SLEEP_SECONDS = float(os.environ.get("ATLAS_REQUEST_SLEEP_SECONDS", "0.50"))

MIN_EXECUTABLE_RR = float(os.environ.get("ATLAS_MIN_EXECUTABLE_RR", "2.0"))
MIN_WATCH_CONFIDENCE = float(os.environ.get("ATLAS_MIN_WATCH_CONFIDENCE", "55"))
TRADE_GEOMETRY_EPSILON = float(os.environ.get("ATLAS_TRADE_GEOMETRY_EPSILON", "1e-12"))
SNAPSHOT_FLAT_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_FLAT_THRESHOLD_PCT", "0.05"))
BTC_REGIME_CACHE_MINUTES = int(os.environ.get("ATLAS_BTC_REGIME_CACHE_MINUTES", "30"))
SIGNAL_MEMORY_HOURS = int(os.environ.get("ATLAS_SIGNAL_MEMORY_HOURS", "12"))
MARKET_BREADTH_MIN_SAMPLES = int(os.environ.get("ATLAS_MARKET_BREADTH_MIN_SAMPLES", "8"))

DB_FILE = os.environ.get("ATLAS_SQLITE_FILE", "atlas_v11.sqlite3")
CHANGELOG_FILE = os.environ.get("ATLAS_CHANGELOG", "changelog.txt")


# ============================================================
# ATLAS RADAR
# ============================================================

ATLAS_PRIORITY_TOP10 = [
    "BTC", "ETH", "BNB", "XRP", "SOL",
    "TRX", "HYPE", "DOGE", "ADA", "MATIC",
]

ATLAS_STATIC = [
    "BTC", "ETH", "XRP", "SOL", "BNB", "TON", "ADA", "DOGE", "TRX", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR", "NEAR",
    "QNT", "GRT", "TAO", "ONDO", "UNI", "ETHFI", "ATOM", "FIL", "AAVE", "MKR",
    "APT", "ARB", "OP", "INJ", "TIA", "SEI", "PEPE", "FET", "ICP", "ETC",
    "HYPE", "MATIC",
]

DATA_SYMBOL_ALIASES = {
    "MATIC": "POL",
}

def data_symbol(symbol):
    return DATA_SYMBOL_ALIASES.get((symbol or "").upper(), (symbol or "").upper())

STABLE_SYMBOLS = {
    "USDT", "USDC", "USDE", "USDS", "DAI", "FDUSD", "TUSD", "USDP",
    "PYUSD", "USDD", "FRAX", "LUSD", "GUSD", "USDG", "USDB", "EURC",
    "USDC.E", "USD0", "USD1",
}

MACRO_SYMBOLS = {
    "DXY": ("DX-Y.NYB", "DX=F", "^DXY"),
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "COPPER": "HG=F",
    "WTI": "CL=F",
    "BRENT": "BZ=F",
}

NEWS_NEGATIVE = (
    "hack", "exploit", "lawsuit", "ban", "delist", "liquidation", "fraud",
    "sec", "investigation", "outflow", "stolen", "sanction", "default",
    "bankruptcy", "attack", "breach", "collapse", "tariff", "war",
)
NEWS_POSITIVE = (
    "approval", "approved", "etf", "inflow", "partnership", "launch",
    "adoption", "upgrade", "listing", "integration", "record", "acquisition",
)
HIGH_IMPACT_WORDS = (
    "federal reserve", "fed", "fomc", "interest rate", "rate decision",
    "cpi", "inflation", "jobs report", "nonfarm", "nfp", "powell",
    "hack", "exploit", "sec", "lawsuit", "ban", "regulation", "sanction",
    "war", "tariff", "bank failure", "liquidation cascade",
)


# ============================================================
# GENERIC HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)

def now_tehran():
    return datetime.now(TEHRAN)

def shamsi(dt):
    gy, gm, gd = dt.year, dt.month, dt.day
    gdm = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
        + (gy2 + 399) // 400 + gd
    )
    for i in range(1, gm):
        days += gdm[i]
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        days += 1
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return f"{jy:04d}/{jm:02d}/{jd:02d}"

def safe_float(x, default=None):
    try:
        if x is None or isinstance(x, bool):
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError, OverflowError):
        return default

def f(x, default=None):
    return safe_float(x, default)

def safe_mean(values, default=None):
    vals = [safe_float(v) for v in (values or [])]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else default

def safe_median(values, default=None):
    vals = [safe_float(v) for v in (values or [])]
    vals = [v for v in vals if v is not None]
    if not vals:
        return default
    vals.sort()
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2

def fmt(x):
    x = f(x)
    if x is None:
        return "N/A"
    if abs(x) >= 1000:
        return f"${x:,.2f}"
    if abs(x) >= 1:
        return f"${x:,.4f}"
    return f"${x:,.6f}"

def pct(x):
    x = f(x)
    return "N/A" if x is None else f"{x:+.2f}%"

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

AMBIGUOUS_DYNAMIC_SYMBOLS = {"M", "CC"}

def is_ambiguous_symbol(symbol):
    return str(symbol or "").upper() in AMBIGUOUS_DYNAMIC_SYMBOLS

def is_stable(symbol):
    s = (symbol or "").upper().replace("-", "")
    return s in STABLE_SYMBOLS

def safe_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"

def http_get(url, timeout=15, headers=None):
    h = {
        "User-Agent": "ATLAS-AI/11.0",
        "Accept": "application/json,application/xml,text/xml,*/*",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        ctype = (r.headers.get("Content-Type") or "").lower()
        if raw.lstrip().startswith("<") or "xml" in ctype:
            return ET.fromstring(raw)
        return json.loads(raw)

def safe_http_get(url, timeout=15, headers=None, default=None):
    try:
        return http_get(url, timeout, headers)
    except ET.ParseError as e:
        append_changelog("HTTP_XML", None, None, f"XML parse failed: {url}: {e}")
        return default
    except Exception as e:
        append_changelog("HTTP", None, None, f"request failed: {url}: {e}")
        return default


# ============================================================
# SQLITE FALLBACK / LOCAL AUDIT
# ============================================================

def sqlite_conn():
    c = sqlite3.connect(DB_FILE, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init_sqlite():
    with sqlite_conn() as c:
        c.executescript("""
        create table if not exists signal_outcomes(
            id integer primary key autoincrement,
            coin text not null,
            direction text not null,
            entry real, sl real, tp1 real, tp2 real,
            issued_at text not null,
            status text default 'OPEN',
            outcome text,
            exit_price real,
            exit_at text,
            pnl_pct real,
            bars_to_exit integer,
            notes text
        );
        create table if not exists model_weights(
            feature text primary key,
            weight real not null,
            baseline_weight real not null,
            samples integer default 0,
            wins integer default 0,
            losses integer default 0,
            updated_at text,
            reason text
        );
        create table if not exists self_healing_cursor(
            id integer primary key check(id=1),
            processed_closed integer not null default 0,
            updated_at text
        );
        create table if not exists self_healing_processed(
            signal_id integer primary key,
            processed_at text not null
        );
        create table if not exists telegram_sent_reports(
            report_hash text not null,
            destination text not null,
            sent_at text not null,
            primary key(report_hash, destination)
        );
        create table if not exists snapshot_prices(
            symbol text primary key,
            price real not null,
            captured_at text not null
        );
        create table if not exists backtest_gate_cache(
            id integer primary key check(id=1),
            timestamp text not null,
            passed integer not null,
            details text
        );
        create table if not exists candle_events(
            coin text not null,
            timeframe text not null,
            last_closed_ts integer,
            last_status text,
            observed_at text not null,
            primary key(coin, timeframe)
        );
        create table if not exists signal_memory(
            coin text primary key,
            direction text,
            action text,
            confidence real,
            signal_candle_ts integer,
            entry real,
            sl real,
            tp1 real,
            tp2 real,
            last_seen_at text not null,
            decision_state text
        );
        create table if not exists decision_events(
            id integer primary key autoincrement,
            timestamp text not null,
            coin text not null,
            state text not null,
            confidence real,
            rr real,
            btc_regime text,
            breadth real,
            reason text
        );
        create table if not exists backtests(
            id integer primary key autoincrement,
            timestamp text,
            model_version text,
            coin text,
            timeframe text,
            period_days integer,
            trades integer,
            wins integer,
            losses integer,
            win_rate real,
            avg_profit real,
            avg_loss real,
            max_drawdown real,
            profit_factor real,
            baseline_profit_factor real,
            baseline_win_rate real,
            improvement_pct real,
            passed integer,
            details text
        );
        """)


# ============================================================
# SUPABASE STORAGE
# ============================================================

class SupabaseStore:
    def __init__(self):
        self.enabled = bool(SUPABASE_URL and SUPABASE_KEY)
        self.headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def insert(self, table, row):
        if not self.enabled:
            return False
        try:
            url = f"{SUPABASE_URL}/rest/v1/{table}"
            req = urllib.request.Request(
                url,
                data=safe_json(row).encode(),
                headers=self.headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            if table != "atlas_changelog":
                try:
                    with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write(f"{now_utc().isoformat()} | SUPABASE | insert failed: {table}: {e}\n")
                except Exception:
                    pass
            return False

    def update(self, table, match, row):
        if not self.enabled:
            return False
        try:
            q = urllib.parse.urlencode(match)
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            req = urllib.request.Request(
                url,
                data=safe_json(row).encode(),
                headers=self.headers,
                method="PATCH",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            if table != "atlas_changelog":
                try:
                    with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write(f"{now_utc().isoformat()} | SUPABASE | update failed: {table}: {e}\n")
                except Exception:
                    pass
            return False

    def select(self, table, params=None):
        if not self.enabled:
            return []
        try:
            q = urllib.parse.urlencode(params or {})
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            return []


STORE = SupabaseStore()


def append_changelog(component, old, new, reason, evidence=None):
    ts = now_utc().isoformat()
    line = (
        f"{ts} | {VERSION} | {component} | "
        f"{old!r} -> {new!r} | {reason}"
    )
    if evidence:
        line += f" | {safe_json(evidence)}"
    try:
        with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    STORE.insert(
        "atlas_changelog",
        {
            "timestamp": ts,
            "model_version": VERSION,
            "component": component,
            "old_value": old if isinstance(old, (int, float)) else None,
            "new_value": new if isinstance(new, (int, float)) else None,
            "reason": reason,
            "evidence": evidence or {},
        },
    )


# ============================================================
# MULTI-SOURCE HELPERS
# ============================================================

def _http_json(url, headers=None, timeout=12):
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "ATLAS-AI/11.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None

def _source_query(base, symbol):
    if not base:
        return None
    sep = "&" if "?" in base else "?"
    return base + sep + urllib.parse.urlencode({"symbol": symbol.upper()})

def coinmarketcap_quote(symbol):
    if not CMC_API_KEY:
        return {"status": "UNAVAILABLE", "reason": "CMC_API_KEY not configured"}
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?" + urllib.parse.urlencode({
        "symbol": symbol.upper(), "convert": "USD"
    })
    d = _http_json(url, {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"})
    try:
        row = d["data"][symbol.upper()][0]
        q = row["quote"]["USD"]
        return {"status":"OK","price":f(q.get("price")),
                "change_24h":f(q.get("percent_change_24h")),
                "change_7d":f(q.get("percent_change_7d")),
                "volume_24h":f(q.get("volume_24h")),
                "timestamp":q.get("last_updated")}
    except Exception:
        return {"status":"UNAVAILABLE","reason":"CMC response unavailable"}

def coingecko_quote(symbol):
    # Uses the existing ID map when available; no guessed market data.
    try:
        cgid = COINGECKO_IDS.get(symbol.upper())
    except Exception:
        cgid = None
    if not cgid:
        return {"status":"UNAVAILABLE","reason":"CoinGecko id not mapped"}
    url = "https://api.coingecko.com/api/v3/simple/price?" + urllib.parse.urlencode({
        "ids": cgid, "vs_currencies":"usd", "include_24hr_change":"true"
    })
    d = _http_json(url, coingecko_headers())
    try:
        q=d[cgid]
        return {"status":"OK","price":f(q.get("usd")),
                "change_24h":f(q.get("usd_24h_change"))}
    except Exception:
        return {"status":"UNAVAILABLE","reason":"CoinGecko response unavailable"}

def coinglass_context(symbol):
    if not COINGLASS_API_KEY:
        return {"status":"UNAVAILABLE","reason":"COINGLASS_API_KEY not configured"}
    headers={"CG-API-KEY":COINGLASS_API_KEY,"Accept":"application/json"}
    out={"status":"UNAVAILABLE","open_interest":None,"funding_rate":None,"liquidations":None}
    urls=[
        ("open_interest","https://open-api-v4.coinglass.com/api/futures/open-interest/exchange-list"),
        ("funding_rate","https://open-api-v4.coinglass.com/api/futures/funding-rate/exchange-list"),
    ]
    for key,url in urls:
        d=_http_json(url+"?"+urllib.parse.urlencode({"symbol":symbol.upper()}),headers)
        if isinstance(d,dict):
            rows=d.get("data") or []
            if isinstance(rows,dict): rows=[rows]
            row=next((x for x in rows if isinstance(x,dict) and str(x.get("exchange","")).lower()=="all"), None)
            row=row or (rows[0] if rows and isinstance(rows[0],dict) else None)
            if row:
                val=row.get(key)
                if val is None:
                    for k in ("open_interest_usd","funding_rate","avg_funding_rate"):
                        if k in row: val=row[k]; break
                out[key]=f(val)
                out["status"]="OK"
    return out

def tradingview_confirmation(symbol, timeframe=SIGNAL_TIMEFRAME):
    if not TRADINGVIEW_CONFIRMATION_URL:
        return {"status":"UNAVAILABLE","rating":None,
                "reason":"No authorized TradingView confirmation endpoint configured"}
    d=_http_json(_source_query(TRADINGVIEW_CONFIRMATION_URL,symbol))
    if not isinstance(d,dict):
        return {"status":"ERROR","rating":None,"reason":"Invalid TradingView payload"}
    return {"status":"OK","rating":d.get("rating"),
            "rsi":f(d.get("rsi")),"macd":d.get("macd"),
            "moving_averages":d.get("moving_averages"),
            "timestamp":d.get("timestamp")}

def secondary_sources(symbol):
    out={}
    for name,base in SECONDARY_ENDPOINTS.items():
        if not base:
            out[name]={"status":"UNAVAILABLE","reason":"endpoint not configured"}
            continue
        d=_http_json(_source_query(base,symbol))
        out[name]={"status":"OK","data":d} if d is not None else {"status":"ERROR"}
    return out

def multi_source_validation(symbol, exchange_price=None):
    cg=coingecko_quote(symbol)
    cmc=coinmarketcap_quote(symbol)
    cgl=coinglass_context(symbol)
    tv=tradingview_confirmation(symbol)
    sec=secondary_sources(symbol)
    prices=[f(x.get("price")) for x in (cg,cmc) if isinstance(x,dict)]
    if f(exchange_price) is not None: prices.append(f(exchange_price))
    prices=[x for x in prices if x is not None and x>0]
    spread=None
    if len(prices)>=2:
        spread=(max(prices)/min(prices)-1)*100
    return {
        "coingecko":cg,"coinmarketcap":cmc,"coinglass":cgl,
        "tradingview":tv,"secondary":sec,
        "price_sources":len(prices),"price_spread_pct":spread
    }

# ============================================================
# CCXT
# ============================================================

def make_exchange(exchange_id):
    cls = getattr(ccxt, exchange_id)
    return cls({
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {"defaultType": "spot"},
    })

def init_exchanges():
    global EX, MARKETS
    EX = {}
    MARKETS = {}
    for eid in ("kcex", "lbank", "xt", "okx", "bybit", "kucoin", "gateio", "bitget", "mexc", "kraken"):
        try:
            ex = make_exchange(eid)
            markets = ex.load_markets()
            if not markets:
                raise RuntimeError(f"{eid}: empty market catalog")
            EX[eid] = ex
            MARKETS[eid] = markets
            print(f"✅ {eid} initialized with {len(markets)} markets")
        except Exception as e:
            EX.pop(eid, None)
            MARKETS.pop(eid, None)
            append_changelog("EXCHANGE_INIT", None, None, f"{eid}: {e}")
            print(f"❌ {eid} failed: {e}")

EX = {}
MARKETS = {}

def ensure_exchanges(force=False):
    if EX and MARKETS and not force:
        return True
    init_exchanges()
    return bool(EX)

def coingecko_headers():
    if COINGECKO_API_KEY:
        return {"x-cg-demo-api-key": COINGECKO_API_KEY}
    return {}

def symbol_for(eid, coin):
    markets = MARKETS.get(eid, {})
    dc = data_symbol(coin)
    for s in (f"{dc}/USDT", f"{dc}/USDT:USDT", f"{coin}/USDT", f"{coin}/USDT:USDT"):
        if s in markets:
            return s
    return None

def exchange_ticker(eid, coin):
    ex = EX.get(eid)
    if ex is None:
        raise RuntimeError(f"{eid}: exchange unavailable")
    sym = symbol_for(eid, coin)
    if not sym:
        raise RuntimeError(f"{eid}: pair unavailable")
    t = ex.fetch_ticker(sym)
    return {
        "source": eid.upper(),
        "price": f(t.get("last")),
        "change": f(t.get("percentage")),
        "quoteVolume": f(t.get("quoteVolume")),
    }

def exchange_ohlcv(eid, coin, timeframe="4h", limit=250):
    ex = EX.get(eid)
    if ex is None:
        raise RuntimeError(f"{eid}: exchange unavailable")
    sym = symbol_for(eid, coin)
    if not sym:
        raise RuntimeError(f"{eid}: pair unavailable")
    supported = getattr(ex, "timeframes", None) or {}
    if supported and timeframe not in supported:
        raise RuntimeError(f"{eid}: timeframe {timeframe} unsupported")
    rows = ex.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
    if len(rows) < 60:
        raise RuntimeError(f"{eid}: insufficient candles")
    return strip_incomplete(rows, timeframe)

def _next_candle_boundary_ms(start_ms, timeframe):
    dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    if timeframe == "1M":
        if dt.month == 12:
            nxt = dt.replace(year=dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            nxt = dt.replace(month=dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return int(nxt.timestamp() * 1000)
    if timeframe == "1w":
        nxt = dt + timedelta(days=7)
        return int(nxt.timestamp() * 1000)
    fixed = {
        "15m": 15 * 60 * 1000,
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }.get(timeframe)
    if fixed is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return start_ms + fixed

def candle_is_closed(start_ms, timeframe, now_ms=None):
    if start_ms is None:
        return False
    now_ms = now_ms or int(time.time() * 1000)
    try:
        return _next_candle_boundary_ms(int(start_ms), timeframe) <= now_ms
    except Exception:
        return False

def strip_incomplete(rows, timeframe):
    clean = []
    now_ms = int(time.time() * 1000)
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        ts = safe_float(row[0])
        if ts is None:
            continue
        if candle_is_closed(int(ts), timeframe, now_ms):
            clean.append(list(row))
    return clean

def candle_event(coin, timeframe, rows):
    latest = int(rows[-1][0]) if rows else None
    if latest is None:
        return {"status": "NO_DATA", "closed_ts": None, "timeframe": timeframe}
    status = "NEW_CLOSED"
    if EVENT_DEDUP_ENABLED:
        with sqlite_conn() as c:
            prev = c.execute(
                "select last_closed_ts from candle_events where coin=? and timeframe=?",
                (coin, timeframe),
            ).fetchone()
            if prev and prev[0] == latest:
                status = "UNCHANGED"
            c.execute(
                "insert into candle_events(coin,timeframe,last_closed_ts,last_status,observed_at) values(?,?,?,?,?) "
                "on conflict(coin,timeframe) do update set last_closed_ts=excluded.last_closed_ts,last_status=excluded.last_status,observed_at=excluded.observed_at",
                (coin, timeframe, latest, status, now_utc().isoformat()),
            )
    return {"status": status, "closed_ts": latest, "timeframe": timeframe}

def best_ohlcv(coin, timeframe, limit=250):
    ensure_exchanges()
    for eid in ("kcex", "lbank", "xt", "okx", "bybit", "kucoin", "gateio", "bitget", "mexc", "kraken"):
        try:
            return exchange_ohlcv(eid, coin, timeframe, limit), eid.upper()
        except Exception:
            continue
    raise RuntimeError(f"{timeframe} DATA UNAVAILABLE: {coin}")


# ============================================================
# DYNAMIC MARKET UNIVERSE
# ============================================================

def gecko_top(limit=40):
    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    url = "https://api.coingecko.com/api/v3/coins/markets?" + urllib.parse.urlencode({
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": str(limit),
        "page": "1",
        "sparkline": "false",
    })
    rows = safe_http_get(url, headers=headers, default=[])
    result = []
    for x in rows or []:
        s = (x.get("symbol") or "").upper()
        if s and not is_stable(s):
            result.append({
                "id": (x.get("id") or "").strip(),
                "symbol": s,
                "name": x.get("name"),
                "rank": x.get("market_cap_rank"),
                "market_cap": f(x.get("market_cap")),
            })
    return result

def binance_top(limit=40):
    ensure_exchanges()
    try:
        ex = EX.get("binance")
        if ex is None:
            return []
        rows = ex.fetch_tickers()
    except Exception:
        return []
    result = []
    for sym, x in rows.items():
        if not sym.endswith("/USDT") or ":USDT" in sym:
            continue
        coin = sym.split("/")[0].upper()
        if is_stable(coin):
            continue
        qv = f(x.get("quoteVolume"))
        if qv is None:
            continue
        result.append({"symbol": coin, "quote_volume": qv})
    result.sort(key=lambda x: x["quote_volume"], reverse=True)
    return result[:limit]

def build_universe():
    cg = gecko_top(60)
    cg_symbols = []
    for x in cg:
        s = (x.get("symbol") or "").upper()
        if s and not is_stable(s) and s not in cg_symbols:
            cg_symbols.append(s)
    top10 = list(ATLAS_PRIORITY_TOP10)
    dynamic30 = [s for s in cg_symbols if s not in top10][:30]
    if len(dynamic30) < 30:
        for x in binance_top(80):
            s = (x.get("symbol") or "").upper()
            if s and not is_stable(s) and s not in top10 and s not in dynamic30:
                dynamic30.append(s)
            if len(dynamic30) >= 30:
                break
    dynamic30 = dynamic30[:30]
    static = [
        x for x in ATLAS_STATIC
        if not is_stable(x) and x not in top10 and x not in dynamic30
    ]
    universe = list(dict.fromkeys(top10 + dynamic30 + static))
    universe = [x for x in universe if not is_stable(x)]
    for symbol in universe:
        source = (
            "TOP10_PRIORITY" if symbol in top10
            else "DYNAMIC30" if symbol in dynamic30
            else "ATLAS_STATIC"
        )
        STORE.insert(
            "atlas_assets",
            {
                "symbol": symbol,
                "rank": next(
                    (x["rank"] for x in cg if x["symbol"] == symbol), None
                ),
                "source": source,
                "is_stablecoin": False,
                "active": True,
                "last_seen_at": now_utc().isoformat(),
            },
        )
    return universe, top10, dynamic30


# ============================================================
# PORTFOLIO SYMBOLS — FIXED (USER-DEFINED, NEVER CHANGES)
# ============================================================

def _portfolio_symbols():
    """User portfolio surveillance universe, kept independent of market ranking."""
    return list(dict.fromkeys([
        "BTC", "ETH", "XRP", "SOL", "BNB", "DOGE", "ADA", "TRX", "LINK",
        "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR",
        "NEAR", "TAO", "ONDO"
    ]))

def _portfolio_rows(results):
    """Return portfolio rows in the exact configured order."""
    by = {r.get("coin"): r for r in results}
    portfolio_symbols = _portfolio_symbols()
    rows = []
    for s in portfolio_symbols:
        if s in by:
            rows.append(by[s])
        else:
            # Asset not in results, create a NO DATA row
            rows.append({
                "coin": s,
                "price": None,
                "change": None,
                "change_7d": None,
                "h4_trend": "N/A",
                "d1_trend": "N/A",
                "w1_trend": "N/A",
                "rsi": None,
                "macd": "N/A",
                "pattern": "N/A",
                "pattern_valid": False,
                "volume": "N/A",
                "volume_ratio": None,
                "atr_pct": None,
                "liquidity": "N/A",
                "liquidity_score": 0,
                "action": "NO DATA",
                "confidence": 0,
                "entry": None,
                "sl": None,
                "tp1": None,
                "tp2": None,
                "tp3": None,
                "tp4": None,
                "rr": None,
                "reason": "داده در دسترس نیست",
                "warning": "داده دریافت نشد",
                "gate": "BLOCK",
                "gate_reason": "No data available",
                "quality": "N/A",
                "spread": 0,
                "overbought": False,
                "oversold": False,
                "candle_trigger": {"state": "N/A"},
                "sr_confidence": "N/A",
                "support": None,
                "resistance": None,
                "pivot": None,
                "leverage": 1.0,
                "direction": "NONE",
                "sources": [],
                "price_source_errors": ["Data not available"],
                "snapshots": {},
                "candle_events": {},
                "news_impact": "N/A",
                "setup_score": 0,
                "entry_quality": 0,
                "risk_quality": 0,
                "decision_state": "NO DATA",
                "decision_reasons": ["Data not available"],
                "repeat_signal": False,
                "original_action": "NO DATA",
            })
    return rows


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def closes(rows):
    return [f(x[4]) for x in rows if f(x[4]) is not None]

def ema(values, n):
    if len(values) < n:
        return None
    a = 2 / (n + 1)
    e = sum(values[:n]) / n
    for x in values[n:]:
        e = (x - e) * a + e
    return e

def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n

def rsi(values, n=14):
    if len(values) <= n:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = ((n - 1) * ag + gains[i]) / n
        al = ((n - 1) * al + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)

def ema_series(values, n):
    if len(values) < n:
        return []
    a = 2 / (n + 1)
    e = sum(values[:n]) / n
    out = [e]
    for x in values[n:]:
        e = (x - e) * a + e
        out.append(e)
    return out

def macd(values):
    if len(values) < 35:
        return None, None, None
    fast = ema_series(values, 12)
    slow = ema_series(values, 26)
    offset = len(fast) - len(slow)
    if offset < 0:
        return None, None, None
    line = [fast[i + offset] - slow[i] for i in range(len(slow))]
    if len(line) < 9:
        return None, None, None
    sig_series = ema_series(line, 9)
    if not sig_series:
        return None, None, None
    signal = sig_series[-1]
    hist = line[-1] - signal
    return line[-1], signal, hist

def atr(rows, n=14):
    if len(rows) < n + 1:
        return None
    tr = []
    for i in range(1, len(rows)):
        h, l, pc = f(rows[i][2]), f(rows[i][3]), f(rows[i - 1][4])
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr[-n:]) / n

def atr_pct(rows, n=14):
    a = atr(rows, n)
    c = f(rows[-1][4]) if rows else None
    return a / c * 100 if a and c else None

def volume_ratio(rows, n=20):
    if len(rows) < n + 1:
        return None
    vols = [f(x[5]) for x in rows if f(x[5]) is not None]
    if len(vols) < n + 1:
        return None
    avg = sum(vols[-n - 1:-1]) / n
    return vols[-1] / avg if avg else None

def volume_state(rows):
    vr = volume_ratio(rows)
    if vr is None:
        return "UNKNOWN", None
    if vr > 1.35:
        return "STRONG", vr
    if vr < 0.75:
        return "WEAK", vr
    return "NORMAL", vr

def support_resistance(rows):
    lows = [f(x[3]) for x in rows[-30:] if f(x[3]) is not None]
    highs = [f(x[2]) for x in rows[-30:] if f(x[2]) is not None]
    if not lows or not highs:
        return None, None
    return min(lows), max(highs)

def _cluster_levels(values, tolerance=0.012):
    vals = sorted(v for v in values if v is not None and v > 0)
    if not vals:
        return []
    clusters = [[vals[0]]]
    for v in vals[1:]:
        center = sum(clusters[-1]) / len(clusters[-1])
        if abs(v - center) / center <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [
        {
            "level": sum(c) / len(c),
            "touches": len(c),
            "spread": (max(c) - min(c)) / max(sum(c) / len(c), 1e-12) * 100,
        }
        for c in clusters
    ]

def daily_key_levels(daily_rows, current_price=None):
    valid = []
    for r in (daily_rows or []):
        if not isinstance(r, (list, tuple)) or len(r) < 6:
            continue
        vals = [f(r[i]) for i in (0,1,2,3,4,5)]
        if all(v is not None for v in vals[:5]):
            valid.append([int(vals[0]), vals[1], vals[2], vals[3], vals[4], vals[5] or 0.0])
    if len(valid) < 60:
        return {"support":None,"resistance":None,"support_score":0,"resistance_score":0,
                "support_touches":0,"resistance_touches":0,"confidence":"LOW","method":"INSUFFICIENT_DAILY_DATA"}
    rows = valid[-180:]
    price = f(current_price) or f(rows[-1][4])
    if price is None or price <= 0:
        return {"support":None,"resistance":None,"support_score":0,"resistance_score":0,
                "support_touches":0,"resistance_touches":0,"confidence":"LOW","method":"INVALID_DAILY_PRICE"}
    highs=[r[2] for r in rows]; lows=[r[3] for r in rows]; vols=[r[5] for r in rows]
    atr_d=atr(rows,14)
    if atr_d is None or atr_d <= 0:
        return {"support":None,"resistance":None,"support_score":0,"resistance_score":0,
                "support_touches":0,"resistance_touches":0,"confidence":"LOW","method":"INVALID_DAILY_ATR"}
    swing_highs=[]; swing_lows=[]
    for i in range(2,len(rows)-2):
        h,l=highs[i],lows[i]
        if h is not None and h >= max(highs[i-2:i]) and h >= max(highs[i+1:i+3]): swing_highs.append(h)
        if l is not None and l <= min(lows[i-2:i]) and l <= min(lows[i+1:i+3]): swing_lows.append(l)
    for n in (20,60,120):
        chunk=rows[-n:]
        swing_highs.append(max(r[2] for r in chunk))
        swing_lows.append(min(r[3] for r in chunk))
    sup_clusters=_cluster_levels([x for x in swing_lows if x < price],0.015)
    res_clusters=_cluster_levels([x for x in swing_highs if x > price],0.015)
    valid_vols=[v for v in vols[-21:-1] if v is not None and v>0]
    avg_vol=safe_mean(valid_vols) if len(valid_vols)>=10 else None

    def score_zone(zone,side):
        level=zone["level"]; touches=zone["touches"]; score=35+min(25,(touches-1)*8)
        distances=[]; rejection=0; vol_hits=0
        for i,r in enumerate(rows):
            o,h,l,c,v=r[1],r[2],r[3],r[4],r[5]
            if None in (h,l,c): continue
            if h >= level >= l: distances.append(len(rows)-1-i)
            body=max(abs(c-o),1e-12) if o is not None else 1e-12
            rng=max(h-l,1e-12)
            if side=="support" and l<=level*1.006 and c>level and (c-l)/rng>0.55: rejection+=1
            if side=="resistance" and h>=level*0.994 and c<level and (h-c)/rng>0.55: rejection+=1
            if avg_vol and v is not None and v>=avg_vol*1.2:
                if side=="support" and l<=level*1.006 and c>level: vol_hits+=1
                if side=="resistance" and h>=level*0.994 and c<level: vol_hits+=1
        if distances:
            score += max(0,15-min(distances)*0.35)
        dist_pct=abs(level-price)/price*100; atrp=atr_d/price*100
        if dist_pct<=max(atrp*4,8): score+=10
        elif dist_pct<=max(atrp*8,15): score+=5
        score += min(15,rejection*3)+min(10,vol_hits*2)
        return int(clamp(round(score),0,100))

    def best(clusters,side):
        ranked=[(score_zone(z,side),z) for z in clusters]
        if not ranked:return None
        ranked.sort(key=lambda q:(q[0],-abs(q[1]["level"]-price)/price),reverse=True)
        score,z=ranked[0]
        return {"level":z["level"],"score":score,"touches":z["touches"]}

    sup=best(sup_clusters,"support"); res=best(res_clusters,"resistance")
    if sup and sup["score"]<55:sup=None
    if res and res["score"]<55:res=None
    min_score=min(sup["score"] if sup else 0,res["score"] if res else 0)
    confidence="HIGH" if min_score>=80 else "MEDIUM" if min_score>=65 else "LOW"
    return {"support":sup["level"] if sup else None,"resistance":res["level"] if res else None,
            "support_score":sup["score"] if sup else 0,"resistance_score":res["score"] if res else 0,
            "support_touches":sup["touches"] if sup else 0,"resistance_touches":res["touches"] if res else 0,
            "confidence":confidence,"method":"DAILY_SWING_CLUSTER_REJECTION_VOLUME"}


# ============================================================
# CANDLE PATTERNS
# ============================================================

def candle_pattern(rows):
    if len(rows) < 3:
        return "NONE", "NONE"
    a, b = rows[-2], rows[-1]
    ao, ac = f(a[1]), f(a[4])
    bo, bh, bl, bc = f(b[1]), f(b[2]), f(b[3]), f(b[4])
    ar = abs(ac - ao)
    br = abs(bc - bo)
    upper = bh - max(bo, bc)
    lower = min(bo, bc) - bl
    total = max(bh - bl, 1e-12)
    if br / total <= 0.10:
        return "DOJI", "NEUTRAL"
    if bc > bo and ac < ao and bo <= ac and bc >= ao and br > ar:
        return "BULLISH ENGULFING", "BULLISH"
    if bc < bo and ac > ao and bo >= ac and bc <= ao and br > ar:
        return "BEARISH ENGULFING", "BEARISH"
    if lower >= 2.2 * max(br, total * 0.02) and upper <= br:
        return "HAMMER", "BULLISH"
    if upper >= 2.2 * max(br, total * 0.02) and lower <= br:
        return "SHOOTING STAR", "BEARISH"
    if lower / total >= 0.60 and bc >= bo:
        return "BULLISH PIN BAR", "BULLISH"
    if upper / total >= 0.60 and bc <= bo:
        return "BEARISH PIN BAR", "BEARISH"
    return "NONE", "NEUTRAL"


# ============================================================
# DIVERGENCE
# ============================================================

def local_extrema(values, window=3):
    vals=[safe_float(v) for v in (values or [])]
    lows,highs=[],[]
    for i in range(window,len(vals)-window):
        if vals[i] is None: continue
        chunk=[v for v in vals[i-window:i+window+1] if v is not None]
        if len(chunk)<window+1: continue
        if vals[i]==min(chunk): lows.append(i)
        if vals[i]==max(chunk): highs.append(i)
    return lows,highs

def divergence_3_level(values, indicator):
    if len(values) != len(indicator) or len(values) < 40:
        return None
    lows, highs = local_extrema(values, 2)
    if len(lows) >= 3:
        idx = lows[-3:]
        p = [values[i] for i in idx]
        r = [indicator[i] for i in idx]
        if p[0] > p[1] > p[2] and r[0] < r[1] < r[2]:
            return "BULLISH_3_LEVEL"
    if len(highs) >= 3:
        idx = highs[-3:]
        p = [values[i] for i in idx]
        r = [indicator[i] for i in idx]
        if p[0] < p[1] < p[2] and r[0] > r[1] > r[2]:
            return "BEARISH_3_LEVEL"
    return None


# ============================================================
# MULTI-TIMEFRAME ANALYSIS
# ============================================================

def trend_from_rows(rows):
    c = closes(rows)
    s20, s50 = sma(c, 20), sma(c, 50)
    if not s20 or not s50:
        return "UNKNOWN"
    price = c[-1]
    if price > s20 > s50:
        return "BULLISH"
    if price < s20 < s50:
        return "BEARISH"
    return "MIXED"

def tf_snapshot(coin):
    out = {}
    for tf in TIMEFRAMES:
        try:
            limit = 250 if tf in ("1h", "4h", "1d") else 120 if tf == "1w" else 60
            rows, engine = best_ohlcv(coin, tf, limit)
            c = closes(rows)
            if len(c) < 20:
                raise RuntimeError(f"{tf}: insufficient closed candles")
            r = rsi(c)
            ml, ms, hist = macd(c)
            s20, s50 = sma(c, 20), sma(c, 50)
            out[tf] = {
                "rows": rows,
                "engine": engine,
                "trend": trend_from_rows(rows),
                "rsi": r,
                "macd": "BULLISH" if ml is not None and ms is not None and ml > ms
                else "BEARISH" if ml is not None and ms is not None else "UNKNOWN",
                "sma20": s20,
                "sma50": s50,
                "price": c[-1],
                "event": candle_event(coin, tf, rows),
            }
        except Exception as e:
            out[tf] = {"error": str(e), "trend": "UNKNOWN", "event": {"status":"ERROR","closed_ts":None,"timeframe":tf}}
    try:
        rows, engine = best_ohlcv(coin, "30m", EVENT_LOOKBACK_LIMITS["30m"])
        out["30m"] = {"rows": rows, "engine": engine, "event": candle_event(coin, "30m", rows)}
    except Exception as e:
        out["30m"] = {"error": str(e), "event": {"status":"ERROR","closed_ts":None,"timeframe":"30m"}}
    return out


# ============================================================
# 30-MINUTE MOMENTUM
# ============================================================

def momentum_30m(coin):
    try:
        rows,_=best_ohlcv(coin,"30m",60)
        rows=strip_incomplete(rows,"30m")
        c=[x for x in closes(rows) if x is not None]
        if len(c)<6:return "UNKNOWN",False
        base = c[-4]
        if base is None or base == 0:
            return "UNKNOWN", False
        short=(c[-1]/base-1)*100
        if short>0.20:return "BULLISH",False
        if short<-0.20:return "BEARISH",False
        return "NEUTRAL",False
    except Exception as e:
        append_changelog("MOMENTUM_30M",None,None,f"{coin}: {e}")
        return "UNKNOWN",False


# ============================================================
# NEWS
# ============================================================

RSS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://www.theblock.co/rss.xml",
]

def news_feed():
    items = []
    for url in RSS:
        root = safe_http_get(url, timeout=10, default=None)
        if root is None or not hasattr(root, "findall"):
            continue
        for x in root.findall(".//item")[:8]:
            title = (x.findtext("title") or "").strip()
            link = (x.findtext("link") or "").strip()
            if title:
                items.append({"title": title, "url": link, "source": url})
    if CRYPTOPANIC_TOKEN:
        url = "https://cryptopanic.com/api/developer/v2/posts/?" + urllib.parse.urlencode({
            "auth_token": CRYPTOPANIC_TOKEN,
            "public": "true",
            "kind": "news",
            "regions": "en",
            "limit": "15",
        })
        d = safe_http_get(url, default={})
        for x in d.get("results", []) if isinstance(d, dict) else []:
            items.append({
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "source": "CryptoPanic",
            })
    if NEWSAPI_KEY:
        url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode({
            "q": "crypto bitcoin ethereum regulation Federal Reserve",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": NEWSAPI_KEY,
        })
        d = safe_http_get(url, default={})
        for x in d.get("articles", []) if isinstance(d, dict) else []:
            items.append({
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "source": x.get("source", {}).get("name", "NewsAPI"),
            })
    score = 0
    high = False
    for item in items:
        t = item["title"].lower()
        score += sum(1 for w in NEWS_POSITIVE if w in t)
        score -= sum(1 for w in NEWS_NEGATIVE if w in t)
        if any(w in t for w in HIGH_IMPACT_WORDS):
            high = True
    bias = (
        "NEGATIVE" if score <= -3
        else "POSITIVE" if score >= 3
        else "MIXED/LIMITED"
    )
    impact = "HIGH" if high else "NORMAL"
    return {
        "bias": bias,
        "impact": impact,
        "items": items[:12],
    }


# ============================================================
# MACRO: DXY / METALS / OIL
# ============================================================

def yahoo_chart(symbol, interval="1h", range_="5d"):
    url=("https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?"+urllib.parse.urlencode({"interval":interval,"range":range_,"events":"history"}))
    d=safe_http_get(url,timeout=15,default={})
    if not isinstance(d,dict): return []
    chart=d.get("chart")
    if not isinstance(chart,dict): return []
    results=chart.get("result")
    if not isinstance(results,list) or not results: return []
    result=results[0] or {}
    indicators=result.get("indicators") or {}
    quotes=indicators.get("quote") or []
    if not quotes or not isinstance(quotes[0],dict): return []
    quote=quotes[0]; timestamps=result.get("timestamp") or []
    rows=[]
    for i,ts in enumerate(timestamps):
        try:
            o=f((quote.get("open") or [None]*len(timestamps))[i]); h=f((quote.get("high") or [None]*len(timestamps))[i])
            l=f((quote.get("low") or [None]*len(timestamps))[i]); c=f((quote.get("close") or [None]*len(timestamps))[i])
            v=f((quote.get("volume") or [None]*len(timestamps))[i])
            if None not in (o,h,l,c): rows.append([int(ts)*1000,o,h,l,c,v or 0.0])
        except (IndexError,TypeError,ValueError): continue
    return strip_incomplete(rows,interval)

def macro_snapshot():
    out = {}
    for name, symbols in MACRO_SYMBOLS.items():
        candidates = symbols if isinstance(symbols, (tuple, list)) else (symbols,)
        value = None
        for symbol in candidates:
            try:
                rows = yahoo_chart(symbol, "1h", "5d")
                c = closes(rows)
                if c:
                    value = c[-1]
                    break
            except Exception as e:
                append_changelog("MACRO", None, None, f"{name}/{symbol}: {e}")
        out[name] = value
    return out


# ============================================================
# LIQUIDITY
# ============================================================

def asset_liquidity(coin, ticker_sources):
    volumes = []
    for x in ticker_sources:
        qv = f(x.get("quoteVolume"))
        if qv and qv > 0:
            volumes.append(qv)
    if not volumes:
        return 0.0, "LOW"
    v = sum(volumes)
    score = clamp((math.log10(v + 1) / 10) * 100, 0, 100)
    label = "HIGH" if score >= 70 else "MEDIUM" if score >= 45 else "LOW"
    return score, label

def market_liquidity_index(results):
    scores = [f(x.get("liquidity_score")) for x in results]
    scores = [x for x in scores if x is not None]
    return round(safe_mean(scores, 0.0), 1)


# ============================================================
# PRICE CONSENSUS
# ============================================================

def price_consensus(coin):
    vals = []
    sources = []
    errors = []
    for eid in EX:
        try:
            x = exchange_ticker(eid, coin)
            if x["price"] is not None:
                vals.append(x["price"])
                sources.append(x)
        except Exception as e:
            errors.append(str(e))
    try:
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
        rows = gecko_top(50)
        lookup_symbol = data_symbol(coin)
        x = next(
            (z for z in rows if (z.get("symbol") or "").upper() == lookup_symbol),
            None,
        )
        gecko_id = (x or {}).get("id")
        if gecko_id:
            url = "https://api.coingecko.com/api/v3/simple/price?" + urllib.parse.urlencode({
                "ids": gecko_id,
                "vs_currencies": "usd",
            })
            d = safe_http_get(url, headers=headers, default={})
            p = f((d.get(gecko_id) or {}).get("usd")) if isinstance(d, dict) else None
            if p is not None:
                vals.append(p)
                sources.append({"source": "CoinGecko", "price": p, "id": gecko_id})
    except Exception:
        pass
    if errors:
        append_changelog(
            "PRICE_CONSENSUS", coin, None,
            f"source errors: {len(errors)}",
            {"errors": errors[:8]},
        )
    if not vals:
        raise RuntimeError("NO PRICE DATA")
    med = safe_median(vals)
    spreads = [abs(x - med) / med * 100 for x in vals if med]
    sp = max(spreads) if spreads else 0
    quality = (
        "HIGH" if len(vals) >= 4 and sp <= 1.5
        else "MEDIUM" if len(vals) >= 3 and sp <= 3
        else "LOW"
    )
    return med, sources, quality, sp, errors


# ============================================================
# SIGNAL SCORING
# ============================================================

def indicator_alignment(tf4):
    c = tf4["rows"]
    vals = closes(c)
    rr = tf4["rsi"]
    ml, ms, hist = macd(vals)
    bullish = 0
    bearish = 0
    reasons = []
    overbought = False
    oversold = False
    if rr is not None:
        if 52 <= rr <= 68:
            bullish += 1
            reasons.append("RSI صعودی/متعادل")
        elif rr < 45:
            bearish += 1
            oversold = True
            reasons.append("RSI ضعیف / اشباع فروش")
        elif rr > 75:
            overbought = True
            reasons.append("RSI بالای 75؛ اشباع خرید — بدون امتیاز صعودی")
    if ml is not None and ms is not None:
        if ml > ms:
            bullish += 1
            reasons.append("MACD صعودی")
        elif ml < ms:
            bearish += 1
            reasons.append("MACD نزولی")
    if tf4["sma20"] and tf4["sma50"]:
        if vals[-1] > tf4["sma20"] > tf4["sma50"]:
            bullish += 1
            reasons.append("SMA20/50 صعودی")
        elif vals[-1] < tf4["sma20"] < tf4["sma50"]:
            bearish += 1
            reasons.append("SMA20/50 نزولی")
    direction = (
        "BULLISH" if bullish >= 2 and bullish > bearish
        else "BEARISH" if bearish >= 2 and bearish > bullish
        else "MIXED"
    )
    return direction, bullish, bearish, reasons, overbought, oversold

def rsi_series(values, n=14):
    if len(values) <= n:
        return []
    gains = []
    losses = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    out = [100.0 if al == 0 else 100 - 100 / (1 + ag / al)]
    for i in range(n, len(gains)):
        ag = ((n - 1) * ag + gains[i]) / n
        al = ((n - 1) * al + losses[i]) / n
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out

def strong_divergence(rows):
    vals = closes(rows)
    rsis = rsi_series(vals, 14)
    if len(rsis) < 40:
        return None
    p = vals[-len(rsis):]
    return divergence_3_level(p, rsis)

def weekly_pivot(rows):
    if not rows or len(rows) < 42:
        return None
    recent = rows[-42:]
    highs = [f(x[2]) for x in recent if len(x) >= 5 and f(x[2]) is not None]
    lows = [f(x[3]) for x in recent if len(x) >= 5 and f(x[3]) is not None]
    closes_ = [f(x[4]) for x in recent if len(x) >= 5 and f(x[4]) is not None]
    if not highs or not lows or not closes_:
        return None
    return (max(highs) + min(lows) + closes_[-1]) / 3.0


def _validate_trade_geometry(direction, entry, sl, tp1, tp2, min_rr=None):
    """Deterministic safety gate: reject impossible/contradictory trade geometry."""
    direction = str(direction or "").upper()
    entry, sl, tp1, tp2 = map(f, (entry, sl, tp1, tp2))
    if direction not in ("LONG", "SHORT") or None in (entry, sl, tp1, tp2):
        return False, "missing trade levels"
    if min(x <= 0 for x in (entry, sl, tp1, tp2)):
        return False, "non-positive trade level"
    if direction == "LONG":
        if not (sl < entry < tp1 < tp2):
            return False, "invalid LONG geometry"
    else:
        if not (sl > entry > tp1 > tp2):
            return False, "invalid SHORT geometry"
    rr = _rr_from_values(entry, sl, tp2)
    if rr is None or rr <= 0:
        return False, "invalid R/R"
    required_rr = MIN_EXECUTABLE_RR if min_rr is None else float(min_rr)
    if rr < required_rr:
        return False, f"R/R below {required_rr:.2f}"
    return True, None

def calculate_levels(rows, direction, daily_levels=None):
    """
    Build structural levels from CLOSED candles.
    Important: TP levels are NOT generated as fixed multiples of risk.
    They are taken from actual market structure first, with ATR-based
    fallback only when a structural level is unavailable.
    """
    price = f(rows[-1][4]) if rows else None
    if price is None or price <= 0 or direction not in ("LONG", "SHORT"):
        return None

    daily_levels = daily_levels or {}
    sup = f(daily_levels.get("support"))
    res = f(daily_levels.get("resistance"))

    recent = rows[-60:] if len(rows) >= 30 else rows
    highs = sorted({round(f(x[2]), 10) for x in recent if len(x) >= 5 and f(x[2]) is not None and f(x[2]) > 0})
    lows = sorted({round(f(x[3]), 10) for x in recent if len(x) >= 5 and f(x[3]) is not None and f(x[3]) > 0})
    atr_v = f(atr(rows))
    if atr_v is None or atr_v <= 0:
        return None

    below = [x for x in lows if x < price]
    above = [x for x in highs if x > price]
    if sup is None:
        sup = max(below) if below else None
    if res is None:
        res = min(above) if above else None
    if sup is None or res is None:
        return None

    if direction == "LONG":
        # Entry is either current price after a confirmed close, or a breakout trigger.
        entry = price if price >= res else res * 1.002
        sl = min(sup * 0.995, entry - 1.5 * atr_v)
        risk = entry - sl
        if risk <= 0:
            return None

        # Real structural targets. Never manufacture four targets.
        higher = [x for x in above if x > entry * 1.003]
        tp1 = higher[0] if higher else entry + 1.25 * risk
        tp2 = higher[1] if len(higher) > 1 else max(entry + 2.0 * risk, tp1 + 0.5 * risk)
        tp3 = higher[2] if len(higher) > 2 else None
        tp4 = higher[3] if len(higher) > 3 else None

        if tp1 <= entry:
            return None
        if tp2 <= tp1:
            tp2 = tp1 + max(0.5 * risk, 0.25 * atr_v)
        if tp3 is not None and tp3 <= tp2:
            tp3 = None
        if tp4 is not None and (tp3 is None or tp4 <= tp3):
            tp4 = None

    else:
        entry = price if price <= sup else sup * 0.998
        sl = max(res * 1.005, entry + 1.5 * atr_v)
        risk = sl - entry
        if risk <= 0:
            return None

        lower = [x for x in lows if x < entry * 0.997]
        tp1 = lower[-1] if lower else entry - 1.25 * risk
        tp2 = lower[-2] if len(lower) > 1 else min(entry - 2.0 * risk, tp1 - 0.5 * risk)
        tp3 = lower[-3] if len(lower) > 2 else None
        tp4 = lower[-4] if len(lower) > 3 else None

        if tp1 >= entry:
            return None
        if tp2 >= tp1:
            tp2 = tp1 - max(0.5 * risk, 0.25 * atr_v)
        if tp3 is not None and tp3 >= tp2:
            tp3 = None
        if tp4 is not None and (tp3 is None or tp4 >= tp3):
            tp4 = None

    # Structural sanity + deterministic trade geometry gate.
    valid, _reason = _validate_trade_geometry(direction, entry, sl, tp1, tp2, min_rr=None)
    if not valid:
        return None

    return {
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
        "tp3": tp3, "tp4": tp4, "atr": atr_v,
        "support": sup, "resistance": res,
        "pivot": weekly_pivot(rows),
    }

def suggested_leverage(atr_percent):
    if not atr_percent or atr_percent <= 0:
        return 1.0
    lev = (1 / (atr_percent / 100)) * 0.5
    return round(clamp(lev, 1, MAX_LEVERAGE), 1)

def candle_trigger_state(rows, direction, support=None, resistance=None):
    if not rows or len(rows) < 3:
        return {"state":"UNKNOWN","close_location":None,"range_pct":None,"near_extreme":False}
    r=rows[-1]
    o,h,l,c=map(f,r[1:5])
    if None in (h,l,c) or h <= l or c <= 0:
        return {"state":"UNKNOWN","close_location":None,"range_pct":None,"near_extreme":False}
    loc=(c-l)/(h-l)
    range_pct=(h-l)/c*100
    prev=rows[-2]
    ph,pl,pc=f(prev[2]),f(prev[3]),f(prev[4])
    state="NEUTRAL_CLOSE"
    if direction=="LONG":
        if resistance is not None and c>resistance and pc is not None and pc<=resistance:
            state="BREAKOUT_CLOSED"
        elif loc>=0.80:
            state="BULLISH_CLOSE"
        elif l < (support or -math.inf) and c > (support or math.inf):
            state="SUPPORT_RECLAIM"
    elif direction=="SHORT":
        if support is not None and c<support and pc is not None and pc>=support:
            state="BREAKDOWN_CLOSED"
        elif loc<=0.20:
            state="BEARISH_CLOSE"
        elif h > (resistance or math.inf) and c < (resistance or -math.inf):
            state="RESISTANCE_REJECT"
    return {"state":state,"close_location":round(loc,3),"range_pct":round(range_pct,3),"near_extreme":loc>=0.85 or loc<=0.15}


# ============================================================
# MAIN - FIXED WITH VOICE AND IMAGE
# ============================================================

def main():
    try:
        telegram_preflight()
        run_mode = (os.environ.get("ATLAS_RUN_MODE") or "BOTH").strip().upper()
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
            print("📊 Running analysis...")
            results = []
            coins = ["BTC", "ETH", "BNB", "XRP", "SOL"]
            for coin in coins:
                try:
                    r = analyze_coin(coin, {"impact": "NORMAL", "bias": "NEUTRAL"}, {"candle_pattern": 15, "rsi": 15, "macd": 15, "volume": 15, "higher_trend": 20, "news_clear": 15})
                    if r:
                        results.append(r)
                        print(f"✅ {coin}: {r['action']}")
                except Exception as e:
                    print(f"❌ {coin}: {e}")
            
            analysis_results = results
            
            # Build report
            text = build_report(results, ["BTC", "ETH"], [], {}, {"impact": "NORMAL"}, {}, 0)
            parts, sent, errors = send_report(text)
            total_sent += sent
            all_errors.extend(errors)
            
            # ============================================================
            # IMAGE TABLE (NEW)
            # ============================================================
            if ENABLE_IMAGE_TABLE:
                try:
                    print("📸 Generating image table...")
                    image_sent = send_image_table(results, ["BTC", "ETH"], [])
                    if image_sent:
                        print("✅ Image table sent successfully")
                    else:
                        print("⚠️ Image table not sent")
                except Exception as e:
                    print(f"⚠️ Image error: {e}")
            
            # ============================================================
            # VOICE OUTPUT - FIXED: Pass results list directly
            # ============================================================
            if ENABLE_VOICE_REPORT and AUTO_SEND_VOICE:
                try:
                    print("\n🎤 Generating audio report...")
                    audio_file = generate_audio_report(results)
                    if audio_file:
                        result = send_audio_report(audio_file, "🎤 گزارش صوتی اطلس")
                        if result:
                            print("✅ Audio report sent successfully")
                        else:
                            print("❌ Failed to send audio report")
                        try:
                            os.unlink(audio_file)
                        except:
                            pass
                except Exception as e:
                    print(f"⚠️ Audio error: {e}")
            
            # CSV Export
            csv_sent, csv_errors = send_csv_report(results, ["BTC", "ETH"], [])
            if csv_sent > 0:
                print(f"📊 CSV sent: {csv_sent} destinations")
            if csv_errors:
                print(f"⚠️ CSV errors: {csv_errors}")

        if do_snapshot:
            print("📸 Running snapshot...")
            snapshot_results = analysis_results if analysis_results else fetch_snapshot_results()
            snapshot_sent, snapshot_errors = send_price_snapshot(snapshot_results)
            total_sent += snapshot_sent
            all_errors.extend(snapshot_errors)

        if not do_analysis and not do_snapshot:
            print(f"{VERSION}: AUTO schedule has no task at this hour.")
            return 0

        if all_errors or total_sent == 0:
            raise RuntimeError("Telegram delivery failed: " + "; ".join(all_errors or ["0 messages sent"]))
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        return 1


# ============================================================
# TELEGRAM HELPERS (MINIMAL)
# ============================================================

def telegram_preflight():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not set")
    if not TELEGRAM_CHAT_ID and not TELEGRAM_GROUP_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID required")

def send_report(text):
    parts = split_message(text)
    sent = 0
    errors = []
    for part in parts:
        try:
            if not send_telegram_message(part, TELEGRAM_CHAT_ID):
                errors.append("Private failed")
                continue
            sent += 1
            time.sleep(TELEGRAM_PRIVATE_DELAY)
            if TELEGRAM_GROUP_CHAT_ID:
                if not send_telegram_message(part, TELEGRAM_GROUP_CHAT_ID):
                    errors.append("Group failed")
                    continue
                sent += 1
                time.sleep(TELEGRAM_GROUP_DELAY)
        except Exception as e:
            errors.append(str(e))
    return parts, sent, errors

def split_message(text, max_len=4000):
    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        split_at = text.rfind('\n', 0, max_len)
        if split_at == -1:
            split_at = text.rfind(' ', 0, max_len)
        if split_at == -1:
            split_at = max_len
        parts.append(text[:split_at])
        text = text[split_at:].lstrip()
    return parts

def send_telegram_message(text, chat_id):
    if not TELEGRAM_TOKEN or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False


# ============================================================
# PRICE SNAPSHOT
# ============================================================

def fetch_usdt_toman_public():
    """دریافت نرخ تتر از منابع عمومی بدون نیاز به API"""
    try:
        # منبع اول: TGJU
        url = "https://api.tgju.org/v1/market/price/3"
        d = safe_http_get(url, timeout=10, default={})
        if isinstance(d, dict) and d.get("price"):
            return f(d["price"])
    except:
        pass
    
    try:
        # منبع دوم: ارزدیجیتال
        url = "https://api.arzdigital.net/api/v1/price/USDT"
        d = safe_http_get(url, timeout=10, default={})
        if isinstance(d, dict) and d.get("price"):
            return f(d["price"])
    except:
        pass
    
    return None

def fetch_snapshot_results():
    """دریافت داده‌های اسنپ‌شات برای قیمت‌ها"""
    results = []
    coins = ["BTC", "ETH", "BNB", "XRP", "SOL"]
    for coin in coins:
        try:
            price, sources, quality, spread, errors = price_consensus(coin)
            results.append({
                "coin": coin,
                "price": price,
                "change": 0,
                "sources": sources,
                "quality": quality,
                "spread": spread,
            })
        except Exception as e:
            results.append({
                "coin": coin,
                "price": None,
                "change": None,
                "error": str(e),
            })
    return results

def send_price_snapshot(results):
    """ارسال اسنپ‌شات قیمت به تلگرام"""
    lines = ["📸 ATLAS PRICE SNAPSHOT", "━━━━━━━━━━━━━━━━━━"]
    
    for r in results:
        coin = r.get("coin", "UNKNOWN")
        price = r.get("price")
        change = r.get("change")
        
        if price:
            price_str = fmt(price)
            change_str = pct(change) if change is not None else "N/A"
            lines.append(f"{coin}: {price_str} | {change_str}")
        else:
            lines.append(f"{coin}: ❌ No data")
    
    # USDT
    usdt = fetch_usdt_toman_public()
    if usdt:
        lines.append("")
        lines.append(f"🇮🇷 USDT: {usdt:,.0f} Toman")
    
    lines.append("")
    lines.append(f"🕐 {now_tehran().strftime('%Y-%m-%d %H:%M:%S')} Tehran")
    
    text = "\n".join(lines)
    return send_report(text)


# ============================================================
# CSV EXPORT
# ============================================================

def send_csv_report(results, top10_symbols=None, dynamic30_symbols=None):
    """ارسال گزارش CSV به تلگرام"""
    if not results:
        return 0, ["No results"]
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    headers = ["Coin", "Price", "Change%", "Action", "Confidence%", "R/R", "Quality%"]
    writer.writerow(headers)
    
    for r in results:
        row = [
            r.get("coin", "UNKNOWN"),
            r.get("price") or "N/A",
            r.get("change") or "N/A",
            r.get("action", "NO DATA"),
            r.get("confidence", 0),
            r.get("rr", 0),
            r.get("quality_score", 0),
        ]
        writer.writerow(row)
    
    csv_data = output.getvalue()
    output.close()
    
    # Send as file
    sent = 0
    errors = []
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
            body = bytearray()
            
            body.extend(f'--{boundary}\r\n'.encode())
            body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
            body.extend(str(TELEGRAM_CHAT_ID).encode())
            body.extend(b'\r\n')
            
            body.extend(f'--{boundary}\r\n'.encode())
            body.extend(b'Content-Disposition: form-data; name="document"; filename="atlas_report.csv"\r\n')
            body.extend(b'Content-Type: text/csv\r\n\r\n')
            body.extend(csv_data.encode('utf-8'))
            body.extend(b'\r\n')
            
            body.extend(f'--{boundary}--\r\n'.encode())
            
            headers = {
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Content-Length': str(len(body))
            }
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
            req = urllib.request.Request(url, data=bytes(body), headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode())
                if result.get('ok'):
                    sent += 1
                else:
                    errors.append(result.get('description', 'Unknown error'))
        except Exception as e:
            errors.append(str(e))
    
    return sent, errors


# ============================================================
# ANALYSIS FUNCTIONS (PLACEHOLDERS)
# ============================================================

def analyze_coin(coin, news, weights):
    """تحلیل یک ارز و تولید سیگنال"""
    try:
        # Get 4H data
        rows, engine = best_ohlcv(coin, "4h", 120)
        if len(rows) < 60:
            raise RuntimeError("Insufficient data")
        
        price = rows[-1][4]
        change = (price / rows[-20][4] - 1) * 100 if len(rows) >= 20 else 0
        
        # Simple analysis
        c = closes(rows)
        rsi_val = rsi(c, 14)
        vol_ratio = volume_ratio(rows, 20)
        
        # Determine action
        action = "NO SIGNAL"
        confidence = 0
        direction = "NONE"
        
        if rsi_val and vol_ratio:
            if rsi_val < 30 and vol_ratio > 1.2:
                action = "BULLISH WATCH"
                confidence = 60
                direction = "LONG"
            elif rsi_val > 70 and vol_ratio > 1.2:
                action = "BEARISH WATCH"
                confidence = 60
                direction = "SHORT"
        
        return {
            "coin": coin,
            "price": price,
            "change": change,
            "action": action,
            "confidence": confidence,
            "direction": direction,
            "rsi": rsi_val,
            "volume_ratio": vol_ratio,
            "liquidity_score": 50,
            "rr": 2.0,
            "quality_score": confidence,
            "entry": price,
            "sl": price * 0.95 if direction == "LONG" else price * 1.05,
            "tp1": price * 1.05 if direction == "LONG" else price * 0.95,
            "tp2": price * 1.10 if direction == "LONG" else price * 0.90,
            "h4_trend": "BULLISH" if rsi_val > 50 else "BEARISH",
        }
    except Exception as e:
        print(f"❌ analyze_coin {coin}: {e}")
        return None


def build_report(results, top10, dynamic30, levels, news, macro, liquidity):
    """ساخت گزارش متنی"""
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 {VERSION}")
    lines.append("━━━━━━━━━━━━━━━━━━")
    
    for r in results[:10]:
        coin = r.get("coin", "UNKNOWN")
        price = r.get("price")
        action = r.get("action", "NO SIGNAL")
        conf = r.get("confidence", 0)
        
        price_str = fmt(price) if price else "N/A"
        lines.append(f"{coin}: {price_str} | {action} | {conf}%")
    
    session, label, mult = get_current_session()
    lines.append("")
    lines.append(f"🕐 {label} | {mult:.1f}x")
    lines.append(f"📅 {now_tehran().strftime('%Y-%m-%d %H:%M:%S')} Tehran")
    
    return "\n".join(lines)


def _automatic_run_plan():
    """برنامه اجرای خودکار (هر 30 دقیقه)"""
    now = now_tehran()
    minute = now.minute
    
    # تحلیل کامل در دقایق 0 و 30
    do_analysis = minute in (0, 30)
    
    # اسنپ‌شات در دقایق 15 و 45
    do_snapshot = minute in (15, 45)
    
    return {"analysis": do_analysis, "snapshot": do_snapshot}


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    raise SystemExit(main())
