#============================================================
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
    
    # مسیر اول: Edge TTS
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
    
    # مسیر دوم: gTTS
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="fa", slow=False)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        tts.save(temp_file.name)
        return temp_file.name
    except:
        pass
    
    # مسیر سوم: Google Translate
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


def generate_audio_report(results, filename="audio_report.mp3"):
    """تولید فایل صوتی از گزارش"""
    if not results:
        return None
    
    audio_text = generate_voice_summary(results)
    
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
    """ارسال گزارش صوتی به تلگرام - Binary-safe Multipart"""
    if not os.path.exists(audio_file):
        return False
    if not TELEGRAM_TOKEN:
        return False
    if not AUTO_SEND_VOICE:
        return False
    
    with open(audio_file, 'rb') as f:
        audio_data = f.read()
    
    boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
    body = bytearray()
    
    # chat_id
    body.extend(f'--{boundary}\r\n'.encode())
    body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    chat_id = TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID
    if chat_id:
        body.extend(str(chat_id).encode())
    body.extend(b'\r\n')
    
    # caption
    if caption:
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
        body.extend(caption.encode('utf-8'))
        body.extend(b'\r\n')
    
    # audio (بایت‌های خام)
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
            return result.get('ok', False)
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
    if not ENABLE_IMAGE_TABLE:
        print("ℹ️ Image table disabled by ATLAS_ENABLE_IMAGE_TABLE")
        return None
    
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
        print("ℹ️ Image table disabled by ATLAS_ENABLE_IMAGE_TABLE")
        return False
    
    filename = build_image_table(results, top10_symbols, dynamic30_symbols)
    if not filename or not os.path.exists(filename):
        return False
    
    if not TELEGRAM_TOKEN:
        return False
    
    try:
        with open(filename, 'rb') as f:
            image_data = f.read()
        
        boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
        body = bytearray()
        
        # chat_id
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        chat_id = TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID
        if chat_id:
            body.extend(str(chat_id).encode())
        body.extend(b'\r\n')
        
        # photo
        body.extend(f'--{boundary}\r\n'.encode())
        body.extend(f'Content-Disposition: form-data; name="photo"; filename="signal_table.png"\r\n'.encode())
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
            return result.get('ok', False)
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
# ANALYZE COIN
# ============================================================

def analyze_coin(coin, market_news, weights):
    if is_stable(coin):
        return None
    snapshots = tf_snapshot(coin)
    tf4 = snapshots.get("4h", {})
    if "rows" not in tf4:
        raise RuntimeError("4H unavailable")
    tf1 = snapshots.get("1h", {})
    tfd = snapshots.get("1d", {})
    tfw = snapshots.get("1w", {})
    tfm = snapshots.get("1M", {})
    price, sources, quality, spread_pct, errors = price_consensus(coin)
    h1 = tf1.get("trend", "UNKNOWN")
    h4 = tf4.get("trend", "UNKNOWN")
    d1 = tfd.get("trend", "UNKNOWN")
    w1 = tfw.get("trend", "UNKNOWN")
    m1 = tfm.get("trend", "UNKNOWN")
    pattern, pattern_dir = candle_pattern(tf4["rows"])
    ind_dir, bull_n, bear_n, indicator_reasons, overbought, oversold = indicator_alignment(tf4)
    divergence = strong_divergence(tf4["rows"])
    vol_state, vol_ratio = volume_state(tf4["rows"])
    atrp = atr_pct(tf4["rows"])
    liq_score, liq_label = asset_liquidity(coin, sources)
    daily_levels = daily_key_levels(tfd.get("rows", []), price)
    h4_levels = h4_fallback_levels(tf4.get("rows", []), price)
    sr_fallback = False
    effective_levels = daily_levels
    if (not effective_levels or effective_levels.get("confidence") == "LOW") and h4_levels and h4_levels.get("confidence") != "LOW":
        effective_levels = h4_levels
        sr_fallback = True
    mom30, _ = momentum_30m(coin)

    rsi_value = f(tf4.get("rsi"))
    ml, ms, _hist = macd(closes(tf4["rows"]))

    candle_points = 0.0
    candle_valid = False
    if pattern != "NONE" and pattern_dir in ("BULLISH", "BEARISH"):
        aligned = sum([pattern_dir == ind_dir, pattern_dir == h4, pattern_dir == d1])
        if aligned >= 2:
            candle_points = weights["candle_pattern"]
            candle_valid = True
        elif aligned == 1:
            candle_points = weights["candle_pattern"] * 0.35

    rsi_points = 0.0
    if rsi_value is not None:
        if ind_dir == "BULLISH":
            if 52 <= rsi_value <= 68:
                rsi_points = weights["rsi"]
            elif 68 < rsi_value <= 75:
                rsi_points = weights["rsi"] * 0.70
            elif 75 < rsi_value <= 80:
                rsi_points = weights["rsi"] * 0.25
            elif rsi_value > 80:
                rsi_points = weights["rsi"] * 0.10
        elif ind_dir == "BEARISH":
            if 32 <= rsi_value < 45:
                rsi_points = weights["rsi"]
            elif 25 <= rsi_value < 32:
                rsi_points = weights["rsi"] * 0.70
            elif 20 <= rsi_value < 25:
                rsi_points = weights["rsi"] * 0.25
            elif rsi_value < 20:
                rsi_points = weights["rsi"] * 0.10

    macd_points = 0.0
    if ml is not None and ms is not None:
        if ind_dir == "BULLISH" and ml > ms:
            macd_points = weights["macd"]
        elif ind_dir == "BEARISH" and ml < ms:
            macd_points = weights["macd"]

    if vol_ratio is None:
        volume_points = 0.0
    elif vol_ratio >= 1.50:
        volume_points = weights["volume"]
    elif vol_ratio >= 1.00:
        volume_points = weights["volume"] * 0.70
    elif vol_ratio >= MIN_VOLUME_RATIO:
        volume_points = weights["volume"] * 0.35
    else:
        volume_points = 0.0

    higher_points = weights["higher_trend"] if h4 in ("BULLISH", "BEARISH") and d1 == h4 else 0.0

    if market_news["impact"] == "NORMAL":
        news_points = weights["news_clear"]
    elif market_news["impact"] == "HIGH":
        news_points = 0.0
    else:
        news_points = weights["news_clear"] * 0.50

    indicator_points = rsi_points + macd_points
    confidence = candle_points + indicator_points + volume_points + higher_points + news_points
    score_components = {
        "candle_pattern": round(candle_points, 2),
        "rsi": round(rsi_points, 2),
        "macd": round(macd_points, 2),
        "indicators": round(indicator_points, 2),
        "volume": round(volume_points, 2),
        "higher_trend": round(higher_points, 2),
        "news_clear": round(news_points, 2),
        "weights_used": dict(weights),
    }

    direction = "NONE"
    if ind_dir == "BULLISH" and h4 == "BULLISH" and d1 == "BULLISH":
        direction = "LONG"
    elif ind_dir == "BEARISH" and h4 == "BEARISH" and d1 == "BEARISH":
        direction = "SHORT"

    if divergence == "BULLISH_3_LEVEL" and h4 != "BULLISH":
        direction = "LONG"
    elif divergence == "BEARISH_3_LEVEL" and h4 != "BEARISH":
        direction = "SHORT"

    if direction in ("LONG", "SHORT"):
        rsi_points = 0.0
        if rsi_value is not None:
            if direction == "LONG":
                if 52 <= rsi_value <= 68: rsi_points = weights["rsi"]
                elif 68 < rsi_value <= 75: rsi_points = weights["rsi"] * 0.70
                elif 75 < rsi_value <= 80: rsi_points = weights["rsi"] * 0.25
                elif rsi_value > 80: rsi_points = weights["rsi"] * 0.10
            else:
                if 32 <= rsi_value < 45: rsi_points = weights["rsi"]
                elif 25 <= rsi_value < 32: rsi_points = weights["rsi"] * 0.70
                elif 20 <= rsi_value < 25: rsi_points = weights["rsi"] * 0.25
                elif rsi_value < 20: rsi_points = weights["rsi"] * 0.10
        macd_points = 0.0
        if ml is not None and ms is not None:
            if direction == "LONG" and ml > ms: macd_points = weights["macd"]
            elif direction == "SHORT" and ml < ms: macd_points = weights["macd"]
        old_indicator_points = score_components["indicators"]
        new_indicator_points = rsi_points + macd_points
        confidence += new_indicator_points - old_indicator_points
        score_components["rsi"] = round(rsi_points, 2)
        score_components["macd"] = round(macd_points, 2)
        score_components["indicators"] = round(new_indicator_points, 2)

    regime_conflict = False
    trigger = candle_trigger_state(
        tf4.get("rows", []),
        direction,
        effective_levels.get("support") if effective_levels else None,
        effective_levels.get("resistance") if effective_levels else None,
    )
    if direction == "LONG" and m1 == "BEARISH":
        regime_conflict = True
    elif direction == "SHORT" and m1 == "BULLISH":
        regime_conflict = True

    gate = "PASS"
    gate_reasons = []
    gate_reason = "All mandatory gates passed"
    warning = None

    if regime_conflict:
        gate_reasons.append("Monthly regime contradicts signal")
    if quality == "LOW" or spread_pct > 3:
        gate_reasons.append("Data quality/conflict")
    if vol_ratio is None or vol_ratio <= MIN_VOLUME_RATIO:
        gate_reasons.append("Volume confirmation missing")
    if confidence < MIN_CONFIDENCE:
        gate_reasons.append("Confidence below threshold")
    if direction == "NONE":
        gate_reasons.append("Higher-timeframe alignment missing")
    if ((direction == "LONG" and w1 == "BEARISH") or (direction == "SHORT" and w1 == "BULLISH")) and confidence < max(MIN_CONFIDENCE + 15, 75):
        gate_reasons.append("Weekly regime conflict; stronger confirmation required")
    if market_news["impact"] == "HIGH":
        warning = "نوسان بالا"
        if (market_news["bias"] == "NEGATIVE" and direction == "LONG") or (market_news["bias"] == "POSITIVE" and direction == "SHORT"):
            gate_reasons.append("High-impact news contradicts signal")
    if direction == "LONG" and mom30 == "BEARISH":
        warning = "شتاب مخالف"
        gate_reasons.append("30m momentum strongly opposes long")
    if direction == "SHORT" and mom30 == "BULLISH":
        warning = "شتاب مخالف"
        gate_reasons.append("30m momentum strongly opposes short")

    if gate_reasons:
        gate = "BLOCK"
        gate_reason = " | ".join(dict.fromkeys(gate_reasons))

    levels = None
    leverage = 1.0
    action = "NO TRADE"

    # Always calculate a valid candidate plan for the complete personal report.
    # A candidate plan is NOT a trade approval; the decision gate still controls action.
    candidate_levels = calculate_levels(tf4["rows"], direction, effective_levels)

    if gate == "PASS":
        if not effective_levels or effective_levels.get("confidence") == "LOW":
            gate = "BLOCK"
            gate_reason = (gate_reason + " | " if gate_reason and gate_reason != "All mandatory gates passed" else "") + "Reliable Daily/H4 S/R not confirmed"
        elif sr_fallback and confidence < max(MIN_CONFIDENCE + 10, H4_FALLBACK_MIN_SCORE):
            gate = "BLOCK"
            gate_reason = (gate_reason + " | " if gate_reason and gate_reason != "All mandatory gates passed" else "") + "H4 S/R fallback requires elevated confidence"
        else:
            levels = candidate_levels
            if levels is None:
                gate = "BLOCK"
                gate_reason = (gate_reason + " | " if gate_reason and gate_reason != "All mandatory gates passed" else "") + "Invalid price geometry"
            else:
                leverage = suggested_leverage(atrp)
                four_h_event = snapshots.get("4h", {}).get("event", {})
                trigger_ok_long = trigger["state"] in ("BREAKOUT_CLOSED", "SUPPORT_RECLAIM", "BULLISH_CLOSE") and direction == "LONG"
                trigger_ok_short = trigger["state"] in ("BREAKDOWN_CLOSED", "RESISTANCE_REJECT", "BEARISH_CLOSE") and direction == "SHORT"
                if trigger_ok_long:
                    action = "BUY CONFIRMATION"
                elif trigger_ok_short:
                    action = "SELL CONFIRMATION"
                else:
                    action = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                    warning = warning or "منتظر بسته‌شدن/تأیید ساختار 4H"
                if sr_fallback:
                    warning = warning or "Daily S/R unavailable؛ H4 fallback used"

    reason_parts = []
    if pattern_valid := candle_valid:
        reason_parts.append(pattern)
    reason_parts.extend(indicator_reasons[:3])
    if vol_ratio is not None and vol_ratio > MIN_VOLUME_RATIO:
        reason_parts.append(f"حجم {vol_ratio:.2f}x میانگین 20")
    if h4 == d1 and h4 in ("BULLISH", "BEARISH"):
        reason_parts.append(f"هم‌جهت H4/D1 {h4}")
    if divergence:
        reason_parts.append("واگرایی 3 سطحی")
    if warning:
        reason_parts.append(warning)

    change_24h = next(
        (f(x.get("change")) for x in sources if f(x.get("change")) is not None),
        None,
    )
    if change_24h is None:
        h1_rows = tf1.get("rows", [])
        if len(h1_rows) >= 25 and price is not None:
            base_24h = f(h1_rows[-25][4])
            if base_24h and base_24h > 0:
                change_24h = (price / base_24h - 1.0) * 100.0

    change_7d = None
    d1_rows = tfd.get("rows", [])
    if len(d1_rows) >= 8 and price is not None:
        base_7d = f(d1_rows[-8][4])
        if base_7d and base_7d > 0:
            change_7d = (price / base_7d - 1.0) * 100.0

    if levels is None and candidate_levels is not None:
        levels = candidate_levels

    source_validation = multi_source_validation(coin, exchange_price=price)
    tvv = source_validation.get("tradingview", {})
    if tvv.get("status") == "OK":
        tvr = str(tvv.get("rating") or "").upper()
        if tvr in ("BUY", "STRONG_BUY") and direction == "LONG":
            confidence += 5
        elif tvr in ("SELL", "STRONG_SELL") and direction == "SHORT":
            confidence += 5
        elif tvr in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
            confidence -= 8

    # ============================================================
    # اعمال ضریب سشن بازار روی کانفیدنس
    # ============================================================
    session, session_label, session_multiplier = get_current_session()
    
    # ذخیره کانفیدنس اصلی برای گزارش
    confidence_raw = confidence
    
    # اعمال ضریب سشن
    confidence = confidence * session_multiplier
    
    # اگر در سشن کم‌نقدینگی هستیم، هشدار اضافه کن
    if session in ("ASIA", "CLOSED"):
        warning = warning or f"سشن {session_label} — نقدینگی کمتر، احتیاط بیشتر"
    
    # اگر در همپوشانی هستیم، یک امتیاز مثبت به دلیل نقدینگی بالا
    if session == "OVERLAP":
        if "همپوشانی سشن — نقدینگی بالا" not in str(reason_parts):
            reason_parts.append("همپوشانی سشن — نقدینگی بالا")

    return {
        "coin": coin,
        "price": price,
        "change": change_24h,
        "change_7d": change_7d,
        "change_source": "ticker" if any(f(x.get("change")) is not None for x in sources) else "H1_24H_FALLBACK",
        "trend": h4,
        "h1_trend": h1,
        "h4_trend": h4,
        "d1_trend": d1,
        "w1_trend": w1,
        "m1_trend": m1,
        "pattern": pattern,
        "pattern_valid": pattern_valid,
        "rsi": tf4.get("rsi"),
        "macd": tf4.get("macd"),
        "volume": vol_state,
        "volume_ratio": vol_ratio,
        "atr_pct": atrp,
        "support": effective_levels.get("support") if effective_levels else None,
        "resistance": effective_levels.get("resistance") if effective_levels else None,
        "support_score": effective_levels.get("support_score", 0) if effective_levels else 0,
        "resistance_score": effective_levels.get("resistance_score", 0) if effective_levels else 0,
        "support_touches": effective_levels.get("support_touches", 0) if effective_levels else 0,
        "resistance_touches": effective_levels.get("resistance_touches", 0) if effective_levels else 0,
        "sr_confidence": effective_levels.get("confidence", "LOW") if effective_levels else "LOW",
        "sr_method": ("H4_FALLBACK_" + effective_levels.get("method", "UNKNOWN")) if sr_fallback and effective_levels else (effective_levels.get("method", "UNKNOWN") if effective_levels else "NONE"),
        "sr_fallback": sr_fallback,
        "pivot": levels["pivot"] if levels else weekly_pivot(tf4["rows"]),
        "entry": levels["entry"] if levels else None,
        "sl": levels["sl"] if levels else None,
        "tp1": levels["tp1"] if levels else None,
        "tp2": levels["tp2"] if levels else None,
        "tp3": levels["tp3"] if levels else None,
        "tp4": levels["tp4"] if levels else None,
        "leverage": leverage,
        "direction": direction,
        "action": action,
        "confidence": int(clamp(confidence, 0, 100)),
        "score_components": score_components,
        "confidence_raw": round(confidence_raw, 2),
        "overbought": overbought,
        "oversold": oversold,
        "quality": quality,
        "spread": spread_pct,
        "liquidity_score": liq_score,
        "liquidity": liq_label,
        "momentum_30m": mom30,
        "candle_trigger": trigger,
        "signal_candle_ts": snapshots.get("4h", {}).get("event", {}).get("closed_ts"),
        "candle_events": {tf: snapshots.get(tf, {}).get("event", {}) for tf in EVENT_TIMEFRAMES},
        "news_impact": market_news["impact"],
        "warning": warning,
        "gate": gate,
        "gate_reason": gate_reason,
        "reason": " + ".join(reason_parts) or "تایید چندعاملی کافی نیست",
        "sources": [x["source"] for x in sources],
        "source_validation": source_validation,
        "tradingview_status": tvv.get("status"),
        "tradingview_rating": tvv.get("rating"),
        "coinglass_status": source_validation.get("coinglass", {}).get("status"),
        "coinglass_open_interest": source_validation.get("coinglass", {}).get("open_interest"),
        "coinglass_funding_rate": source_validation.get("coinglass", {}).get("funding_rate"),
        "engine": tf4.get("engine"),
        "snapshots": snapshots,
        # سشن‌های بازار
        "session": session,
        "session_label": session_label,
        "session_multiplier": session_multiplier,
    }


# ============================================================
# DECISION ENGINE — REGIME / BREADTH / RISK / MEMORY
# ============================================================

def _trend_bias_from_rows(rows):
    try:
        c = closes(rows)
        if len(c) < 60:
            return "UNKNOWN", None, None, None
        rr = rsi(c)
        ml, ms, _ = macd(c)
        s20, s50 = sma(c, 20), sma(c, 50)
        if None in (rr, ml, ms, s20, s50):
            return "UNKNOWN", rr, ml, ms
        bull = c[-1] > s20 > s50 and ml > ms
        bear = c[-1] < s20 < s50 and ml < ms
        if bull and rr >= 52:
            return "BULLISH", rr, ml, ms
        if bear and rr <= 48:
            return "BEARISH", rr, ml, ms
        return "MIXED", rr, ml, ms
    except Exception:
        return "UNKNOWN", None, None, None

def btc_market_regime(force=False):
    global _BTC_REGIME_CACHE
    now = time.time()
    if not force and _BTC_REGIME_CACHE:
        if now - _BTC_REGIME_CACHE.get("ts", 0) < BTC_REGIME_CACHE_MINUTES * 60:
            return dict(_BTC_REGIME_CACHE)
    out = {
        "regime": "UNKNOWN", "h4": "UNKNOWN", "d1": "UNKNOWN",
        "rsi4": None, "rsi1": None, "volume_ratio": None,
        "reason": "BTC data unavailable", "ts": now,
    }
    try:
        r4, _ = best_ohlcv("BTC", "4h", 180)
        r1, _ = best_ohlcv("BTC", "1d", 180)
        h4, rsi4, _, _ = _trend_bias_from_rows(r4)
        d1, rsi1, _, _ = _trend_bias_from_rows(r1)
        _, vr = volume_state(r4)
        out.update({"h4": h4, "d1": d1, "rsi4": rsi4, "rsi1": rsi1, "volume_ratio": vr})
        if h4 == "BULLISH" and d1 == "BULLISH":
            out["regime"] = "RISK_ON"
            out["reason"] = "BTC 4H + 1D bullish"
        elif h4 == "BEARISH" and d1 == "BEARISH":
            out["regime"] = "RISK_OFF"
            out["reason"] = "BTC 4H + 1D bearish"
        else:
            out["regime"] = "NEUTRAL"
            out["reason"] = "BTC higher timeframes mixed"
    except Exception as e:
        append_changelog("BTC_REGIME", None, None, str(e), {"traceback": traceback.format_exc()})
    _BTC_REGIME_CACHE = dict(out)
    return out

_BTC_REGIME_CACHE = {}

def market_breadth(results):
    bullish_set = [r for r in results if r.get("h4_trend") == "BULLISH" and r.get("d1_trend") == "BULLISH"]
    bearish_set = [r for r in results if r.get("h4_trend") == "BEARISH" and r.get("d1_trend") == "BEARISH"]
    samples = len(bullish_set) + len(bearish_set)
    if samples == 0:
        return {"score": 50.0, "bullish": 0, "bearish": 0, "samples": 0, "state": "UNKNOWN"}
    bullish = len(bullish_set)
    bearish = len(bearish_set)
    score = bullish / samples * 100
    if samples < MARKET_BREADTH_MIN_SAMPLES:
        state = "LOW_SAMPLE"
    elif score >= 65:
        state = "BULLISH"
    elif score <= 35:
        state = "BEARISH"
    else:
        state = "MIXED"
    return {"score": round(score, 1), "bullish": bullish, "bearish": bearish, "samples": samples, "state": state}

def decision_rr(result):
    entry, sl, tp2 = f(result.get("entry")), f(result.get("sl")), f(result.get("tp2"))
    if None in (entry, sl, tp2) or entry <= 0:
        return None
    risk = abs(entry - sl)
    reward = abs(tp2 - entry)
    if risk <= 0:
        return None
    return reward / risk

def _near_opposing_level(result):
    entry = f(result.get("entry"))
    if entry is None or entry <= 0:
        return False
    direction = result.get("direction")
    if direction == "LONG":
        res = f(result.get("resistance"))
        if res is not None and res > entry:
            return (res - entry) / entry < 0.015
    if direction == "SHORT":
        sup = f(result.get("support"))
        if sup is not None and sup < entry:
            return (entry - sup) / entry < 0.015
    return False

def _load_signal_memory(coin):
    init_sqlite()
    with sqlite_conn() as c:
        row = c.execute("select * from signal_memory where coin=?", (coin,)).fetchone()
    return dict(row) if row else None

def _save_signal_memory(result, state):
    init_sqlite()
    with sqlite_conn() as c:
        c.execute("""insert into signal_memory
            (coin,direction,action,confidence,signal_candle_ts,entry,sl,tp1,tp2,last_seen_at,decision_state)
            values(?,?,?,?,?,?,?,?,?,?,?)
            on conflict(coin) do update set
            direction=excluded.direction, action=excluded.action,
            confidence=excluded.confidence, signal_candle_ts=excluded.signal_candle_ts,
            entry=excluded.entry, sl=excluded.sl, tp1=excluded.tp1, tp2=excluded.tp2,
            last_seen_at=excluded.last_seen_at, decision_state=excluded.decision_state""",
            (result["coin"], result.get("direction"), result.get("action"), result.get("confidence"),
             result.get("signal_candle_ts"), result.get("entry"), result.get("sl"), result.get("tp1"),
             result.get("tp2"), now_utc().isoformat(), state))

def setup_quality_score(r):
    score = 50.0
    trigger = (r.get("candle_trigger") or {}).get("state")
    if trigger in ("BREAKOUT_CLOSED", "SUPPORT_RECLAIM", "BREAKDOWN_CLOSED", "RESISTANCE_REJECT"):
        score += 15
    elif trigger == "BULLISH_CLOSE" or trigger == "BEARISH_CLOSE":
        score += 8
    if r.get("h4_trend") == r.get("d1_trend") and r.get("h4_trend") in ("BULLISH", "BEARISH"):
        score += 10
    if r.get("overbought") or r.get("oversold"):
        score -= 15
    vr = f(r.get("volume_ratio"))
    if vr is not None:
        score += 10 if vr >= 1.35 else 5 if vr >= 1.0 else -5 if vr < 0.8 else 0
    sr = r.get("sr_confidence")
    score += 10 if sr == "HIGH" else 5 if sr == "MEDIUM" else 0
    direction = r.get("direction")
    w1 = r.get("w1_trend")
    if direction == "LONG" and w1 == "BEARISH":
        score -= 10
    elif direction == "SHORT" and w1 == "BULLISH":
        score -= 10
    return int(clamp(round(score), 0, 100))

def risk_quality_score(r, rr=None):
    score = 40.0
    rr = f(rr)
    if rr is not None:
        score += 25 if rr >= 3 else 20 if rr >= 2.5 else 15 if rr >= 2 else 0 if rr >= 1.5 else -20
    liq = f(r.get("liquidity_score")) or 0
    score += 15 if liq >= 70 else 8 if liq >= 45 else -8
    q = r.get("quality")
    score += 15 if q == "HIGH" else 8 if q == "MEDIUM" else -10
    spread = f(r.get("spread"))
    score += 10 if spread is not None and spread <= 1 else 5 if spread is not None and spread <= 3 else -20
    if _near_opposing_level(r):
        score -= 20
    return int(clamp(round(score), 0, 100))

def apply_decision_engine(results, btc_regime, breadth):
    for r in results:
        raw = r.get("action", "NO TRADE")
        rr = decision_rr(r)
        r["rr"] = round(rr, 2) if rr is not None else None
        r["setup_score"] = int(r.get("confidence", 0))
        r["entry_quality"] = setup_quality_score(r)
        r["risk_quality"] = risk_quality_score(r, rr)
        state = "NO TRADE"
        reasons = []
        direction = r.get("direction")
        regime = btc_regime.get("regime", "UNKNOWN")

        if raw in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            state = raw
            if r.get("entry_quality", 0) < 70:
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append(f"Entry quality {r.get('entry_quality', 0)}/100 < 70")
            if r.get("risk_quality", 0) < 70:
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append(f"Risk quality {r.get('risk_quality', 0)}/100 < 70")
            trigger_state = (r.get("candle_trigger") or {}).get("state")
            if direction == "LONG" and r.get("overbought"):
                if not (trigger_state in ("BREAKOUT_CLOSED", "SUPPORT_RECLAIM") and r.get("confidence", 0) >= 75 and (r.get("volume_ratio") or 0) >= 1.35):
                    state = "BULLISH WATCH"
                    reasons.append("RSI اشباع خرید؛ ورود تعقیبی ممنوع، منتظر Pullback/Retest")
            elif direction == "SHORT" and r.get("oversold"):
                if not (trigger_state in ("BREAKDOWN_CLOSED", "RESISTANCE_REJECT") and r.get("confidence", 0) >= 75 and (r.get("volume_ratio") or 0) >= 1.35):
                    state = "BEARISH WATCH"
                    reasons.append("RSI اشباع فروش؛ ورود تعقیبی ممنوع، منتظر Pullback/Retest")
            if rr is None or rr < MIN_EXECUTABLE_RR:
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append(f"R/R زیر {MIN_EXECUTABLE_RR:.1f}")
            if _near_opposing_level(r):
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("مقاومت/حمایت مقابل بسیار نزدیک")
            if regime == "RISK_OFF" and direction == "LONG":
                state = "BULLISH WATCH"
                reasons.append("BTC regime ریسک‌گریز")
            elif regime == "RISK_ON" and direction == "SHORT":
                state = "BEARISH WATCH"
                reasons.append("BTC regime ریسک‌پذیر")
            if breadth["state"] == "BEARISH" and direction == "LONG":
                state = "BULLISH WATCH"
                reasons.append("Market breadth مخالف LONG")
            elif breadth["state"] == "BULLISH" and direction == "SHORT":
                state = "BEARISH WATCH"
                reasons.append("Market breadth مخالف SHORT")
            mem = _load_signal_memory(r["coin"])
            same_candle = bool(mem and mem.get("signal_candle_ts") == r.get("signal_candle_ts") and mem.get("direction") == direction)
            recent_same = False
            if mem and mem.get("last_seen_at"):
                try:
                    age = (now_utc() - datetime.fromisoformat(mem["last_seen_at"].replace("Z", "+00:00"))).total_seconds() / 3600
                    recent_same = age < SIGNAL_MEMORY_HOURS and mem.get("direction") == direction
                except Exception:
                    pass
            if same_candle or recent_same:
                r["repeat_signal"] = True
                if state == raw:
                    state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("سیگنال تکراری؛ تغییر معنادار مشاهده نشد")
            else:
                r["repeat_signal"] = False
        elif raw in ("BULLISH WATCH", "BEARISH WATCH"):
            state = raw
        else:
            state = "NO TRADE"
        r["decision_state"] = state
        r["decision_reasons"] = reasons
        if state != raw:
            r["original_action"] = raw
        if state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            _save_signal_memory(r, state)
        elif raw in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            _save_signal_memory(r, state)
        STORE.insert("atlas_decision_events", {
            "timestamp": now_utc().isoformat(), "coin": r["coin"], "state": state,
            "confidence": r.get("confidence"), "rr": r.get("rr"),
            "btc_regime": regime, "breadth": breadth.get("score"),
            "reason": " | ".join(reasons) or "decision passed",
        })
    return results

def atlas_decision_board(results, btc_regime, breadth):
    buys = [r for r in results if r.get("decision_state") == "BUY CONFIRMATION" and not r.get("repeat_signal")]
    sells = [r for r in results if r.get("decision_state") == "SELL CONFIRMATION" and not r.get("repeat_signal")]
    bw = [r for r in results if r.get("decision_state") == "BULLISH WATCH"]
    sw = [r for r in results if r.get("decision_state") == "BEARISH WATCH"]
    buys.sort(key=lambda r: (r.get("confidence", 0), r.get("rr") or 0), reverse=True)
    sells.sort(key=lambda r: (r.get("confidence", 0), r.get("rr") or 0), reverse=True)
    bw.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    sw.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    best = buys[0] if buys else (sells[0] if sells else None)
    lines = [
        "━━━━━━━━━━━━━━━━━━",
        "🎯 ATLAS v11 DECISION BOARD",
        f"BTC REGIME: {btc_regime.get('regime','UNKNOWN')} | {btc_regime.get('reason','')}",
        f"MARKET BREADTH: {breadth.get('state')} | {breadth.get('score'):.1f}% bullish | N={breadth.get('samples',0)}",
    ]
    def compact(title, rows, icon):
        lines.append(f"{icon} {title}")
        if not rows:
            lines.append("— ندارد")
            return
        for r in rows[:5]:
            rr = f" | R/R {r['rr']:.2f}" if r.get("rr") else ""
            lines.append(f"{r['coin']} — {r['confidence']}%{rr}")
    compact("EXECUTABLE BUY", buys, "🟢")
    compact("EXECUTABLE SELL / REDUCE", sells, "🔴")
    compact("WATCH — صعود", bw, "📈")
    compact("WATCH — ریزش", sw, "📉")
    if best:
        lines.extend([
            "🔥 BEST SETUP",
            f"{best['coin']} | {best['decision_state']} | Confidence {best['confidence']}% | R/R {best.get('rr') or 0:.2f}",
            f"Entry {fmt(best.get('entry'))} | SL {fmt(best.get('sl'))} | TP1 {fmt(best.get('tp1'))} | TP2 {fmt(best.get('tp2'))}",
            f"Trend H4/D1: {best.get('h4_trend')} / {best.get('d1_trend')} | S/R: {best.get('sr_confidence')}",
        ])
    else:
        lines.append("⚪ BEST SETUP: هیچ معامله‌ای با کیفیت کافی پیدا نشد")
    lines.append("Rule: تحلیل خوب ≠ معامله خوب؛ R/R، regime، ساختار و تکراری‌بودن سیگنال همزمان بررسی شده‌اند.")
    return "\n".join(lines)


# ============================================================
# SELF-HEALING WEIGHTS
# ============================================================

DEFAULT_WEIGHTS = {
    "candle_pattern": 20.0,
    "rsi": 15.0,
    "macd": 15.0,
    "volume": 15.0,
    "higher_trend": 20.0,
    "news_clear": 15.0,
}

def get_weights():
    weights = DEFAULT_WEIGHTS.copy()
    rows = STORE.select(
        "atlas_model_weights",
        {"select": "feature,weight,model_version,updated_at", "order": "updated_at.desc", "limit": "200"},
    )
    seen=set()
    for r in rows:
        feature=r.get("feature")
        w=f(r.get("weight"))
        if feature in weights and feature not in seen and w is not None:
            weights[feature]=clamp(w,5,30); seen.add(feature)
    init_sqlite()
    with sqlite_conn() as c:
        local=c.execute("select feature,weight from model_weights").fetchall()
        for r in local:
            if r["feature"] in weights and r["feature"] not in seen and f(r["weight"]) is not None:
                weights[r["feature"]]=clamp(f(r["weight"]),5,30)
        for feature,weight in weights.items():
            c.execute("insert or ignore into model_weights(feature,weight,baseline_weight,updated_at) values(?,?,?,?)",
                      (feature,weight,DEFAULT_WEIGHTS[feature],now_utc().isoformat()))
    return weights

def update_weight(feature, factor, reason, evidence):
    if feature not in DEFAULT_WEIGHTS:
        return
    evidence=evidence or {}
    old=DEFAULT_WEIGHTS.get(feature,15.0)
    rows=STORE.select("atlas_model_weights", {"select":"feature,weight,updated_at","feature":f"eq.{feature}","order":"updated_at.desc","limit":"1"})
    if rows:
        old=f(rows[0].get("weight")) or old
    else:
        init_sqlite()
        with sqlite_conn() as c:
            r=c.execute("select weight from model_weights where feature=?",(feature,)).fetchone()
            if r and f(r[0]) is not None: old=f(r[0])
    new=clamp(old*factor,5,30)
    payload={"model_version":VERSION,"feature":feature,"weight":new,"baseline_weight":DEFAULT_WEIGHTS[feature],"samples":evidence.get("samples",0),"wins":evidence.get("wins",0),"losses":evidence.get("losses",0),"reason":reason,"updated_at":now_utc().isoformat()}
    STORE.insert("atlas_model_weights",payload)
    init_sqlite()
    with sqlite_conn() as c:
        c.execute("insert into model_weights(feature,weight,baseline_weight,samples,wins,losses,updated_at,reason) values(?,?,?,?,?,?,?,?) on conflict(feature) do update set weight=excluded.weight,samples=excluded.samples,wins=excluded.wins,losses=excluded.losses,updated_at=excluded.updated_at,reason=excluded.reason",
                  (feature,new,DEFAULT_WEIGHTS[feature],evidence.get("samples",0),evidence.get("wins",0),evidence.get("losses",0),payload["updated_at"],reason))
    append_changelog(feature,old,new,reason,evidence)

def self_diagnostic():
    init_sqlite()
    with sqlite_conn() as c:
        rows=c.execute("""
            select s.id,s.coin,s.direction,s.outcome,s.notes
            from signal_outcomes s
            left join self_healing_processed p on p.signal_id=s.id
            where s.status='CLOSED' and p.signal_id is null
            order by s.id asc
        """).fetchall()
    if len(rows)<3:return
    batch=rows[:(len(rows)//3)*3]
    for start_i in range(0,len(batch),3):
        recent=batch[start_i:start_i+3]
        losses=sum(1 for r in recent if r["outcome"]=="SL")
        error_pct=losses/3*100
        if error_pct>5:
            counts={}
            for r in recent:
                text=(r["notes"] or "").lower()
                for token in ("rsi","macd","volume","sma","hammer","engulfing"):
                    if token in text: counts[token]=counts.get(token,0)+1
            feature=max(counts,key=counts.get) if counts else "rsi"
            mapped={"rsi":"rsi","macd":"macd","volume":"volume","sma":"higher_trend","hammer":"candle_pattern","engulfing":"candle_pattern"}
            feature=mapped.get(feature,"rsi")
            update_weight(feature,0.80,"خطای پیش‌بینی > 5% پس از batch جدید؛ وزن 20% کاهش یافت",
                          {"samples":3,"wins":3-losses,"losses":losses,"error_pct":error_pct,"signal_ids":[r["id"] for r in recent]})
        with sqlite_conn() as c:
            c.executemany("insert or ignore into self_healing_processed(signal_id,processed_at) values(?,?)",[(r["id"],now_utc().isoformat()) for r in recent])


# ============================================================
# BACKTEST ENGINE
# ============================================================

def backtest_coin(coin, days=180):
    try:
        rows, engine = best_ohlcv(coin, "4h", 1200)
    except Exception:
        return None
    cutoff = int((time.time() - days * 86400) * 1000)
    rows = [x for x in rows if x[0] >= cutoff]
    if len(rows) < 150:
        return None
    trades = []
    equity = 1.0
    peak = equity
    max_dd = 0.0
    for i in range(80, len(rows) - SIGNAL_HORIZON_BARS, 4):
        window = rows[:i]
        c = closes(window)
        rr = rsi(c)
        ml, ms, _ = macd(c)
        s20, s50 = sma(c, 20), sma(c, 50)
        if None in (rr, ml, ms, s20, s50):
            continue
        bullish = c[-1] > s20 > s50 and ml > ms and rr > 50
        bearish = c[-1] < s20 < s50 and ml < ms and rr < 50
        vol, vr = volume_state(window)
        if vr is None or vr <= MIN_VOLUME_RATIO:
            continue
        direction = "LONG" if bullish else "SHORT" if bearish else None
        if not direction:
            continue
        a = atr(window)
        if not a:
            continue
        entry = c[-1]
        sl = entry - 1.5 * a if direction == "LONG" else entry + 1.5 * a
        tp = entry + 3 * a if direction == "LONG" else entry - 3 * a
        outcome = None
        pnl = None
        for future in rows[i:i + SIGNAL_HORIZON_BARS]:
            hi, lo = f(future[2]), f(future[3])
            if direction == "LONG":
                if lo <= sl:
                    outcome, pnl = "SL", -1.5
                    break
                if hi >= tp:
                    outcome, pnl = "TP", 3.0
                    break
            else:
                if hi >= sl:
                    outcome, pnl = "SL", -1.5
                    break
                if lo <= tp:
                    outcome, pnl = "TP", 3.0
                    break
        if outcome:
            trades.append(pnl)
            equity *= 1 + pnl / 100
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    if not trades:
        return None
    wins = sum(1 for x in trades if x > 0)
    losses = len(trades) - wins
    avg_profit = safe_mean([x for x in trades if x > 0], 0.0)
    avg_loss = abs(safe_mean([x for x in trades if x < 0], 0.0)) if losses else 0
    gross_profit = sum(x for x in trades if x > 0)
    gross_loss = abs(sum(x for x in trades if x < 0))
    return {
        "coin": coin,
        "engine": engine,
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades) * 100,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "max_drawdown": max_dd,
        "profit_factor": gross_profit / gross_loss if gross_loss else 99,
        "trades_raw": trades,
    }

def _cached_backtest_gate():
    try:
        cutoff = now_utc() - timedelta(hours=BACKTEST_REFRESH_HOURS)
        with sqlite_conn() as c:
            row = c.execute(
                "select timestamp, passed, details from backtest_gate_cache where id=1"
            ).fetchone()
        if not row or not row[0]:
            return None
        ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if ts < cutoff:
            return None
        details = row[2]
        try:
            details = json.loads(details) if isinstance(details, str) else (details or {})
        except Exception:
            details = {}
        return bool(row[1]), {"cached": True, **details}
    except Exception as e:
        append_changelog("BACKTEST_CACHE", None, None, str(e), {"traceback": traceback.format_exc()})
        return None

def _save_backtest_gate(passed, details):
    try:
        with sqlite_conn() as c:
            c.execute(
                "insert or replace into backtest_gate_cache(id,timestamp,passed,details) values(1,?,?,?)",
                (now_utc().isoformat(), int(bool(passed)), safe_json(details)),
            )
    except Exception as e:
        append_changelog("BACKTEST_CACHE", None, None, f"cache write failed: {e}", {"traceback": traceback.format_exc()})

def h4_fallback_levels(rows, current_price=None):
    if not rows or len(rows) < 80:
        return None
    price = f(current_price) or f(rows[-1][4])
    if price is None or price <= 0:
        return None
    window = rows[-80:]
    lows = [f(x[3]) for x in window if f(x[3]) is not None and f(x[3]) < price]
    highs = [f(x[2]) for x in window if f(x[2]) is not None and f(x[2]) > price]
    if not lows or not highs:
        return None
    sup = max(lows)
    res = min(highs)
    a = atr(window)
    if not a or a <= 0:
        return None
    sup_dist = abs(price - sup) / a
    res_dist = abs(res - price) / a
    score_s = 80 if sup_dist <= 3 else 72 if sup_dist <= 6 else 60
    score_r = 80 if res_dist <= 3 else 72 if res_dist <= 6 else 60
    conf = "HIGH" if min(score_s, score_r) >= 80 else "MEDIUM" if min(score_s, score_r) >= 65 else "LOW"
    return {
        "support": sup, "resistance": res,
        "support_score": score_s, "resistance_score": score_r,
        "support_touches": 0, "resistance_touches": 0,
        "confidence": conf, "method": "H4_RANGE_FALLBACK"
    }

def mandatory_backtest_gate(universe):
    cached = _cached_backtest_gate()
    if cached is not None:
        return cached
    samples = []
    for coin in universe[:20]:
        r = backtest_coin(coin, BACKTEST_DAYS)
        if r:
            samples.append(r)
    if not samples:
        append_changelog(
            "BACKTEST",
            None,
            None,
            "Backtest unavailable; self-modification frozen",
        )
        result = {"reason": "no backtest data"}
        _save_backtest_gate(False, result)
        return False, result
    win_rate = safe_mean([x.get("win_rate") for x in samples], 0.0)
    pf = safe_mean([x.get("profit_factor") for x in samples], 0.0)
    dd = max((safe_float(x.get("max_drawdown"), 0.0) or 0.0) for x in samples)
    old = STORE.select(
        "atlas_backtests",
        {
            "select": "profit_factor,win_rate",
            "model_version": f"eq.{VERSION}",
            "limit": "1",
            "order": "timestamp.desc",
        },
    )
    if not old:
        for r in samples:
            STORE.insert(
                "atlas_backtests",
                {
                    "model_version": VERSION,
                    "coin": r["coin"],
                    "timeframe": "4h",
                    "period_days": BACKTEST_DAYS,
                    "trades": r["trades"],
                    "wins": r["wins"],
                    "losses": r["losses"],
                    "win_rate": r["win_rate"],
                    "avg_profit": r["avg_profit"],
                    "avg_loss": r["avg_loss"],
                    "max_drawdown": r["max_drawdown"],
                    "profit_factor": r["profit_factor"],
                    "passed": True,
                    "details": {"baseline": True},
                },
            )
        append_changelog(
            "BACKTEST",
            None,
            pf,
            "Baseline established; no automatic model change allowed yet",
            {"win_rate": win_rate, "profit_factor": pf, "max_drawdown": dd},
        )
        result = {
            "win_rate": win_rate,
            "profit_factor": pf,
            "max_drawdown": dd,
            "improvement": 0,
        }
        _save_backtest_gate(True, result)
        return True, result
    baseline_pf = f(old[0].get("profit_factor")) or 0
    baseline_wr = f(old[0].get("win_rate")) or 0
    improvement_pf = (
        (pf - baseline_pf) / baseline_pf * 100 if baseline_pf else 0
    )
    improvement_wr = (
        (win_rate - baseline_wr) / baseline_wr * 100 if baseline_wr else 0
    )
    passed = (
        improvement_pf >= MIN_BACKTEST_IMPROVEMENT
        or improvement_wr >= MIN_BACKTEST_IMPROVEMENT
    )
    for r in samples:
        STORE.insert(
            "atlas_backtests",
            {
                "model_version": VERSION,
                "coin": r["coin"],
                "timeframe": "4h",
                "period_days": BACKTEST_DAYS,
                "trades": r["trades"],
                "wins": r["wins"],
                "losses": r["losses"],
                "win_rate": r["win_rate"],
                "avg_profit": r["avg_profit"],
                "avg_loss": r["avg_loss"],
                "max_drawdown": r["max_drawdown"],
                "profit_factor": r["profit_factor"],
                "baseline_profit_factor": baseline_pf,
                "baseline_win_rate": baseline_wr,
                "improvement_pct": max(improvement_pf, improvement_wr),
                "passed": passed,
                "details": {"self_healing_gate": True},
            },
        )
    append_changelog(
        "BACKTEST_GATE",
        baseline_pf,
        pf,
        "Mandatory pre-change backtest",
        {
            "baseline_win_rate": baseline_wr,
            "new_win_rate": win_rate,
            "improvement_pf_pct": improvement_pf,
            "improvement_wr_pct": improvement_wr,
            "passed": passed,
        },
    )
    result = {
        "win_rate": win_rate,
        "profit_factor": pf,
        "max_drawdown": dd,
        "improvement": max(improvement_pf, improvement_wr),
    }
    _save_backtest_gate(passed, result)
    return passed, result


# ============================================================
# SIGNAL OUTCOME TRACKING
# ============================================================

def store_signal(result):
    if result["action"] not in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
        return None
    row = {
        "timestamp": now_utc().isoformat(),
        "run_type": "SNIPER",
        "coin": result["coin"],
        "timeframe": "4h",
        "action": result["action"],
        "direction": result["direction"],
        "score": int(result["confidence"]),
        "confidence": result["confidence"],
        "price": result["price"],
        "change_24h": result["change"],
        "trend": result["trend"],
        "rsi": result["rsi"],
        "macd": result["macd"],
        "volume": result["volume"],
        "support": result["support"],
        "resistance": result["resistance"],
        "entry": result["entry"],
        "sl": result["sl"],
        "tp1": result["tp1"],
        "tp2": result["tp2"],
        "data_quality": result["quality"],
        "spread_pct": result["spread"],
        "exchanges": ",".join(result["sources"]),
        "alignment": result["h4_trend"] + "/" + result["d1_trend"],
        "gate": result["gate"],
        "gate_reason": result["gate_reason"],
        "raw_action": result["action"],
        "notes": result["reason"],
        "candle_pattern": result["pattern"],
        "h1_trend": result["h1_trend"],
        "h4_trend": result["h4_trend"],
        "d1_trend": result["d1_trend"],
        "w1_trend": result.get("w1_trend"),
        "m1_trend": result.get("m1_trend"),
        "candle_trigger": result.get("candle_trigger", {}),
        "candle_events": result.get("candle_events", {}),
        "liquidity_score": result["liquidity_score"],
        "volume_ratio": result["volume_ratio"],
        "atr_pct": result["atr_pct"],
        "pivot_weekly": result["pivot"],
        "momentum_30m": result["momentum_30m"],
        "news_impact": result["news_impact"],
        "volatility_warning": bool(result["warning"]),
        "reason": result["reason"],
        "leverage": result["leverage"],
        "confidence_breakdown": result.get("score_components", {}),
        "model_version": VERSION,
    }
    STORE.insert("atlas_signals", row)
    init_sqlite()
    with sqlite_conn() as c:
        c.execute(
            """
            insert into signal_outcomes
            (coin,direction,entry,sl,tp1,tp2,issued_at,notes)
            values(?,?,?,?,?,?,?,?)
            """,
            (
                result["coin"], result["direction"], result["entry"],
                result["sl"], result["tp1"], result["tp2"],
                now_utc().isoformat(), result["reason"],
            ),
        )

def evaluate_open_outcomes():
    init_sqlite()
    with sqlite_conn() as c:
        open_rows=c.execute("select * from signal_outcomes where status='OPEN' order by id asc limit 100").fetchall()
    for row in open_rows:
        try:
            candles,_=best_ohlcv(row["coin"],"4h",100)
            issued=datetime.fromisoformat(row["issued_at"].replace("Z","+00:00"))
            after=[x for x in candles if x[0]/1000>issued.timestamp()]
            outcome=None; exit_price=None; bars=0
            entry=f(row["entry"]); sl=f(row["sl"]); tp1=f(row["tp1"]); tp2=f(row["tp2"])
            if None in (entry,sl,tp1): continue
            for bars,x in enumerate(after[:SIGNAL_HORIZON_BARS],1):
                hi,lo=f(x[2]),f(x[3])
                if hi is None or lo is None: continue
                if row["direction"]=="LONG":
                    if lo<=sl:
                        outcome,exit_price="SL",sl; break
                    if tp2 is not None and hi>=tp2:
                        outcome,exit_price="TP2",tp2; break
                    if hi>=tp1:
                        outcome,exit_price="TP1",tp1; break
                else:
                    if hi>=sl:
                        outcome,exit_price="SL",sl; break
                    if tp2 is not None and lo<=tp2:
                        outcome,exit_price="TP2",tp2; break
                    if lo<=tp1:
                        outcome,exit_price="TP1",tp1; break
            if outcome is None and after and len(after)>=SIGNAL_HORIZON_BARS:
                last=after[SIGNAL_HORIZON_BARS-1]; exit_price=f(last[4])
                if exit_price is not None:
                    outcome="TIMEOUT"; bars=SIGNAL_HORIZON_BARS
            if not outcome or exit_price is None: continue
            pnl=((exit_price-entry)/entry*100) if row["direction"]=="LONG" else ((entry-exit_price)/entry*100)
            with sqlite_conn() as c:
                c.execute("update signal_outcomes set status='CLOSED',outcome=?,exit_price=?,exit_at=?,pnl_pct=?,bars_to_exit=? where id=?",(outcome,exit_price,now_utc().isoformat(),pnl,bars,row["id"]))
            STORE.insert("atlas_signal_outcomes",{"coin":row["coin"],"direction":row["direction"],"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"issued_at":row["issued_at"],"status":"CLOSED","outcome":outcome,"exit_price":exit_price,"exit_at":now_utc().isoformat(),"pnl_pct":pnl,"bars_to_exit":bars,"notes":row["notes"]})
        except Exception as e:
            append_changelog("OUTCOME_EVAL",None,None,f"{row['coin']}: {e}",{"traceback":traceback.format_exc()})


# ============================================================
# TELEGRAM — WITH RATE LIMIT HANDLING
# ============================================================

def _telegram_send_chunk(chat_id, text):
    data = urllib.parse.urlencode({
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if not data.get("ok"):
            error_desc = data.get("description", "Unknown error")
            raise RuntimeError(f"Telegram sendMessage failed: {error_desc}")
        return data

def send_with_retry(chat_id, text, max_retries=None, base_delay=None):
    if max_retries is None:
        max_retries = TELEGRAM_MAX_RETRIES
    if base_delay is None:
        base_delay = TELEGRAM_BASE_RETRY_DELAY
    for attempt in range(max_retries):
        try:
            _telegram_send_chunk(chat_id, text)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get('Retry-After', base_delay))
                wait_time = min(retry_after * (2 ** attempt) + random.uniform(0, 1), TELEGRAM_MAX_WAIT)
                print(f"⚠️ Telegram rate limit (429). Waiting {wait_time:.1f}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                append_changelog("TELEGRAM_SEND", None, None, f"HTTP {e.code}: {e.reason}")
                return False
        except Exception as e:
            append_changelog("TELEGRAM_SEND", None, None, f"Unexpected error: {e}")
            wait_time = min(base_delay * (2 ** attempt), TELEGRAM_MAX_WAIT)
            time.sleep(wait_time)
    print(f"❌ Failed to send message to {chat_id} after {max_retries} attempts")
    return False

def telegram_send_one(chat_id, text):
    if not TELEGRAM_TOKEN or not chat_id:
        raise RuntimeError("Telegram secrets missing")
    if len(text) > 4096:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            success = send_with_retry(chat_id, chunk)
            if not success:
                return False
            time.sleep(0.5)
        return True
    else:
        return send_with_retry(chat_id, text)

def telegram_api_get_me():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN missing")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
        headers={"User-Agent": "ATLAS-AI/11.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getMe failed: {data}")
    return data.get("result") or {}

def telegram_preflight():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing from GitHub Secrets")
    if not TELEGRAM_CHAT_ID and not TELEGRAM_GROUP_CHAT_ID:
        raise RuntimeError("No Telegram destination configured: TELEGRAM_CHAT_ID / TELEGRAM_GROUP_CHAT_ID")
    me = telegram_api_get_me()
    append_changelog(
        "TELEGRAM_PREFLIGHT", None, None,
        f"Telegram API reachable as @{me.get('username') or me.get('first_name') or 'bot'}"
    )
    print(f"✅ Telegram bot connected: @{me.get('username') or 'unknown'}")
    return me

def split_telegram(text, max_chars=3900):
    if len(text) <= max_chars:
        return [text]
    parts = []
    current = ""
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                parts.append(current)
            if len(block) <= max_chars:
                current = block
            else:
                for i in range(0, len(block), max_chars):
                    parts.append(block[i:i + max_chars])
                current = ""
    if current:
        parts.append(current)
    return parts

def send_report(text):
    parts = split_telegram(text)
    report_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    init_sqlite()
    destinations = []
    if TELEGRAM_CHAT_ID:
        destinations.append({
            "id": TELEGRAM_CHAT_ID,
            "name": "PRIVATE_CHAT",
            "delay": TELEGRAM_PRIVATE_DELAY
        })
    if TELEGRAM_GROUP_CHAT_ID and TELEGRAM_GROUP_CHAT_ID not in [d["id"] for d in destinations]:
        destinations.append({
            "id": TELEGRAM_GROUP_CHAT_ID,
            "name": "SUPERGROUP",
            "delay": TELEGRAM_GROUP_DELAY
        })
    if not destinations:
        msg = "No Telegram destination configured"
        append_changelog("TELEGRAM", None, None, msg)
        return len(parts), 0, [msg]
    sent = 0
    errors = []
    print(f"\n📤 Sending report to {len(destinations)} destination(s)")
    for dest in destinations:
        chat_id = dest["id"]
        dest_name = dest["name"]
        delay = dest["delay"]
        with sqlite_conn() as c:
            already = c.execute(
                "select 1 from telegram_sent_reports where report_hash=? and destination=?",
                (report_hash, chat_id),
            ).fetchone()
        if already:
            print(f"⏭️ Skipping {dest_name}: duplicate report detected")
            continue
        print(f"📤 Sending {len(parts)} parts to {dest_name}...")
        dest_success = True
        for i, part in enumerate(parts, 1):
            print(f"  Part {i}/{len(parts)}...", end=" ", flush=True)
            success = send_with_retry(chat_id, part)
            if success:
                sent += 1
                print("✅")
            else:
                dest_success = False
                errors.append(f"Telegram {dest_name}, part {i}: failed after retries")
                print("❌")
                break
            if i < len(parts):
                actual_delay = delay + random.uniform(0, 0.5)
                time.sleep(actual_delay)
        if dest_success:
            with sqlite_conn() as c:
                c.execute(
                    "insert or ignore into telegram_sent_reports(report_hash,destination,sent_at) values(?,?,?)",
                    (report_hash, chat_id, now_utc().isoformat()),
                )
            print(f"✅ All {len(parts)} parts sent to {dest_name}")
        else:
            print(f"❌ Failed to send all parts to {dest_name}")
    return len(parts), sent, errors



# ============================================================
# DATA EXPORT — DYNAMIC CSV FROM THE SAME RESULTS OBJECT
# ============================================================

CSV_COLUMNS = (
    "Group", "Symbol", "Status", "DecisionState", "Price", "Change24H",
    "Support", "Resistance", "Entry", "SL", "TP1", "TP2", "TP3", "TP4",
    "R/R", "Confidence", "H4Trend", "D1Trend", "W1Trend", "RSI", "MACD",
    "Volume", "VolumeRatio", "ATR_pct", "Liquidity", "Gate", "GateReason",
    "Direction", "RepeatSignal", "Reason", "ModelVersion",
)

def _csv_group(symbol, top10, dynamic30, personal_symbols):
    s = str(symbol or "").upper()
    if s in personal_symbols:
        return "PERSONAL_PORTFOLIO"
    if s in {str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)}:
        return "MARKET_TOP10"
    if s in {str(x).upper() for x in (dynamic30 or [])}:
        return "DYNAMIC_TOP30"
    return "ATLAS_RADAR"

def _csv_status(r):
    state = str(r.get("decision_state") or r.get("action") or "WAIT").upper()
    if state in ("BUY", "BUY CONFIRMATION"):
        return "BUY"
    if state in ("SELL", "SELL CONFIRMATION", "SELL / REDUCE"):
        return "SELL"
    if state in ("BULLISH WATCH", "BEARISH WATCH", "WATCH"):
        return "WATCH"
    if state == "NO DATA":
        return "NO DATA"
    return "HOLD"

def _csv_number(value, digits=8):
    v = f(value)
    if v is None:
        return ""
    return round(v, digits)

def _csv_safe_plan(r):
    """Return only geometrically valid executable/conditional levels."""
    direction = r.get("direction")
    entry, sl, tp1, tp2 = (f(r.get(k)) for k in ("entry", "sl", "tp1", "tp2"))
    if None in (entry, sl, tp1, tp2):
        return None
    valid, _ = _validate_trade_geometry(direction, entry, sl, tp1, tp2, min_rr=None)
    if not valid:
        return None
    return entry, sl, tp1, tp2

def generate_csv_report(results, top10, dynamic30):
    """Generate a complete, dynamic export from current engine results.

    No values are hard-coded. The CSV contains every current Dynamic Top-30
    candidate, every personal asset, every priority Top-10 asset and all three
    metals, with invalid trade geometry suppressed rather than exported.
    """
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
        plan = _csv_safe_plan(r)
        entry = sl = tp1 = tp2 = tp3 = tp4 = rr = ""
        if plan:
            entry, sl, tp1, tp2 = plan
            tp3, tp4 = f(r.get("tp3")), f(r.get("tp4"))
            rr = _rr_from_values(entry, sl, tp2)
        rows.append([
            _csv_group(sym, top10, dynamic30, personal_symbols),
            sym,
            _csv_status(r),
            str(r.get("decision_state") or r.get("action") or "WAIT"),
            _csv_number(r.get("price")), _csv_number(r.get("change"), 4),
            _csv_number(r.get("support")), _csv_number(r.get("resistance")),
            _csv_number(entry), _csv_number(sl), _csv_number(tp1), _csv_number(tp2),
            _csv_number(tp3), _csv_number(tp4),
            _csv_number(rr, 3), _csv_number(r.get("confidence"), 2),
            r.get("h4_trend", "UNKNOWN"), r.get("d1_trend", "UNKNOWN"),
            r.get("w1_trend", "UNKNOWN"), _csv_number(r.get("rsi"), 2),
            r.get("macd", ""), r.get("volume", ""), _csv_number(r.get("volume_ratio"), 3),
            _csv_number(r.get("atr_pct"), 3), r.get("liquidity", ""),
            r.get("gate", ""), r.get("gate_reason", ""), r.get("direction", ""),
            bool(r.get("repeat_signal")), r.get("reason", ""), VERSION,
        ])

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    writer.writerows(rows)
    return out.getvalue()

def _telegram_send_document(chat_id, content, filename, caption=None):
    """Send a UTF-8 CSV as a real Telegram document using stdlib only."""
    import uuid
    if not TELEGRAM_TOKEN or not chat_id:
        raise RuntimeError("Telegram secrets missing")
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
        data=json.loads(resp.read().decode("utf-8", errors="replace"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendDocument failed: {data}")
    return data

def send_csv_report(results, top10, dynamic30):
    """Send one dynamically generated CSV to every configured destination."""
    content = generate_csv_report(results, top10, dynamic30)
    if not content.strip():
        return 0, ["CSV is empty"]
    dt = now_tehran()
    filename = f"atlas_report_{shamsi(dt).replace('/','')}_{dt.strftime('%H%M%S')}.csv"
    caption = f"📎 ATLAS AI — CSV کامل | {VERSION} | {shamsi(dt)} {dt.strftime('%H:%M:%S')} تهران"
    destinations=[]
    for chat_id in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if chat_id and chat_id not in destinations:
            destinations.append(chat_id)
    sent=0; errors=[]
    for chat_id in destinations:
        try:
            _telegram_send_document(chat_id, content, filename, caption)
            sent += 1
        except Exception as e:
            errors.append(f"CSV {chat_id}: {e}")
            append_changelog("CSV_EXPORT", None, None, str(e), {"traceback": traceback.format_exc()})
    return sent, errors

# ============================================================
# REPORT FORMAT — DECISION-FIRST / COMPACT / PERSIAN
# ============================================================

ATLAS_PERSONAL_ASSETS = [
    "BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "DOGE", "ADA", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR",
    "NEAR", "ONDO", "TAO",
]
ATLAS_METALS = ("GOLD", "SILVER", "COPPER")
METAL_YAHOO = {"GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F"}
METAL_TV = {"GOLD": "OANDA:XAUUSD", "SILVER": "OANDA:XAGUSD", "COPPER": "COMEX:HG1!"}


def action_emoji(action):
    a = str(action or "NO TRADE").upper()
    if a in ("BUY CONFIRMATION", "BUY"):
        return "🟢 BUY"
    if a in ("SELL CONFIRMATION", "SELL", "SELL / REDUCE"):
        return "🔴 SELL"
    if a in ("BULLISH WATCH", "WATCH"):
        return "🟡 WATCH"
    if a == "BEARISH WATCH":
        return "🟠 WATCH-SELL"
    if a == "NO DATA":
        return "⚪ NO DATA"
    return "⚪ WAIT"


def tradingview_chart_url(symbol, metal=False):
    if metal:
        tv_symbol = METAL_TV.get(str(symbol).upper())
    else:
        tv_symbol = f"{TRADINGVIEW_CHART_EXCHANGE}:{str(symbol).upper()}USDT"
    if not tv_symbol:
        return None
    return f"https://www.tradingview.com/chart/?symbol={urllib.parse.quote(tv_symbol, safe=':!')}&interval={urllib.parse.quote(TRADINGVIEW_INTERVAL)}"


def _rr_from_values(entry, sl, tp):
    entry, sl, tp = f(entry), f(sl), f(tp)
    if None in (entry, sl, tp) or entry == sl:
        return None
    return abs(entry - tp) / abs(entry - sl)


def _plan_is_allowed(r):
    """Expose levels only for executable or explicitly conditional closed-candle setups."""
    action = str(r.get("action") or r.get("decision_state") or "").upper()
    if action in ("BUY CONFIRMATION", "SELL CONFIRMATION", "BUY", "SELL"):
        return True
    trigger = str((r.get("candle_trigger") or {}).get("state") or "").upper()
    return trigger in {
        "BREAKOUT_CLOSED", "BREAKDOWN_CLOSED",
        "SUPPORT_RECLAIM", "RESISTANCE_REJECT",
    }

def _conditional_trigger_text(r):
    direction = str(r.get("direction") or "").upper()
    trigger = str((r.get("candle_trigger") or {}).get("state") or "").upper()
    support = f(r.get("support")); resistance = f(r.get("resistance"))
    if direction == "LONG":
        if resistance is not None and trigger in {"BREAKOUT_CLOSED", "BULLISH_CLOSE"}:
            return f"H4 close بالای {fmt(resistance)}"
        if support is not None and trigger == "SUPPORT_RECLAIM":
            return f"H4 reclaim بالای {fmt(support)}"
    if direction == "SHORT":
        if support is not None and trigger in {"BREAKDOWN_CLOSED", "BEARISH_CLOSE"}:
            return f"H4 close زیر {fmt(support)}"
        if resistance is not None and trigger == "RESISTANCE_REJECT":
            return f"H4 rejection زیر {fmt(resistance)}"
    return "تأیید کندل بسته‌شده 4H لازم است"

def _clear_trade_plan(r):
    for k in ("entry", "sl", "tp1", "tp2", "tp3", "tp4", "rr"):
        r[k] = None
    return r

def _ensure_candidate_plan(r):
    """Do not invent trade levels for ordinary WAIT/WATCH rows."""
    if not isinstance(r, dict):
        return r
    if not _plan_is_allowed(r):
        return _clear_trade_plan(r)

    direction = r.get("direction")
    rows = (r.get("snapshots") or {}).get("4h", {}).get("rows") or []
    if direction not in ("LONG", "SHORT") or not rows:
        return _clear_trade_plan(r)

    try:
        levels = calculate_levels(rows, direction, {
            "support": f(r.get("support")),
            "resistance": f(r.get("resistance")),
        })
    except Exception:
        levels = None

    if not levels:
        return _clear_trade_plan(r)

    for k in ("entry", "sl", "tp1", "tp2", "tp3", "tp4"):
        r[k] = levels.get(k)
    r["rr"] = _rr_from_values(r.get("entry"), r.get("sl"), r.get("tp2"))
    valid, reason = _validate_trade_geometry(r.get("direction"), r.get("entry"), r.get("sl"), r.get("tp1"), r.get("tp2"), min_rr=None)
    if not valid:
        r["gate_reason"] = f"Trade geometry blocked: {reason}"
        return _clear_trade_plan(r)
    return r

def _compact_reason(r):
    reason = str(r.get("reason") or r.get("gate_reason") or "تأیید کافی نیست")
    parts = [x.strip() for x in reason.replace("+", "|").split("|") if x.strip()]
    seen=[]
    for p in parts:
        if p not in seen:
            seen.append(p)
    return "؛ ".join(seen[:2])


def asset_block(r, metal=False, detail=False):
    """Compact decision block; trade levels appear only for a valid/conditional setup."""
    r = _ensure_candidate_plan(dict(r or {}))
    symbol = str(r.get("coin") or r.get("symbol") or "UNKNOWN").upper()
    price = f(r.get("price"))
    action = action_emoji(r.get("action") or r.get("decision_state"))
    conf = r.get("confidence")
    tv = tradingview_chart_url(symbol, metal=metal)

    rsi_v = f(r.get("rsi"))
    atr_v = f(r.get("atr_pct"))
    rsi_text = f"{rsi_v:.1f}" if rsi_v is not None else "N/A"
    atr_text = f"{atr_v:.2f}%" if atr_v is not None else "N/A"

    # دریافت سشن فعلی
    session, session_label, session_multiplier = get_current_session()

    lines = [
        f"🔹 {symbol} | {action} | اطمینان: {int(conf) if isinstance(conf,(int,float)) else 0}%",
        f"Price: {fmt(price)} | 24H: {pct(r.get('change'))}" if not metal else f"Price: {fmt(price)}",
        f"🕐 سشن: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x",
        f"Trend: H4 {r.get('h4_trend','UNKNOWN')} / D1 {r.get('d1_trend','UNKNOWN')} / W1 {r.get('w1_trend','UNKNOWN')}",
        f"RSI: {rsi_text} | MACD: {r.get('macd','N/A')} | ATR: {atr_text}",
        f"S/R: {fmt(r.get('support'))} ↔ {fmt(r.get('resistance'))}",
    ]

    if _plan_is_allowed(r) and f(r.get("entry")) is not None and f(r.get("sl")) is not None and f(r.get("tp2")) is not None:
        rr = _rr_from_values(r.get("entry"), r.get("sl"), r.get("tp2"))
        direction = "LONG" if r.get("direction") == "LONG" else "SHORT"
        action_u = str(r.get("action") or r.get("decision_state") or "").upper()
        executable = action_u in ("BUY CONFIRMATION", "SELL CONFIRMATION", "BUY", "SELL")
        label = ("🎯 BUY PLAN" if direction == "LONG" else "🎯 SELL PLAN") if executable else ("🟠 CONDITIONAL BUY" if direction == "LONG" else "🟠 CONDITIONAL SELL")
        lines.append(label)
        if not executable:
            lines.append(f"Trigger: {_conditional_trigger_text(r)}")
        lines.append(
            f"Entry: {fmt(r.get('entry'))} | SL: {fmt(r.get('sl'))} | "
            f"TP1: {fmt(r.get('tp1'))} | TP2: {fmt(r.get('tp2'))}"
            + (f" | R/R: {rr:.2f}" if rr is not None else "")
        )
        extras = [x for x in (r.get("tp3"), r.get("tp4")) if f(x) is not None]
        if extras:
            lines.append(" | ".join(
                f"TP{i}: {fmt(x)}" for i, x in enumerate((r.get("tp3"), r.get("tp4")), 3) if f(x) is not None
            ))
    else:
        lines.append("🎯 Setup: هنوز ورود معتبر تأیید نشده است.")

    lines.append(f"Reason: {_compact_reason(r)}")
    warning = r.get("warning")
    if warning and "نوسان بالا" in str(warning):
        # Only show this warning when ATR actually crosses the configured high-volatility threshold.
        if atr_v is None or atr_v < float(os.environ.get("ATLAS_HIGH_ATR_PCT", "4.0")):
            warning = None
    if warning:
        lines.append(f"⚠️ {warning}")
    if tv:
        lines.append(f"📊 Chart: {tv}")
    return "\n".join(lines)



def _opportunity_score(r):
    conf = float(r.get("confidence") or 0)
    rr = float(r.get("rr") or 0)
    setup = float(r.get("setup_score") or 0)
    entry = float(r.get("entry_quality") or 0)
    risk = float(r.get("risk_quality") or 0)
    tv = (r.get("tradingview_rating") or "").upper()
    tv_bonus = 8 if tv in ("BUY","STRONG_BUY") and r.get("direction") == "LONG" else 8 if tv in ("SELL","STRONG_SELL") and r.get("direction") == "SHORT" else 0
    executable = 30 if r.get("action") in ("BUY CONFIRMATION","SELL CONFIRMATION") else 0
    rr_score = min(rr, 4.0) * 10
    return conf * .45 + rr_score + setup*.08 + entry*.05 + risk*.04 + tv_bonus + executable


def top5_opportunities(results, exclude_symbols=None):
    """Five best EXECUTABLE crypto opportunities; excluded portfolio symbols never leak into MARKET."""
    excluded = {str(x).upper() for x in (exclude_symbols or ())}
    candidates = []
    for r in results or []:
        if str(r.get("coin") or "").upper() in excluded:
            continue
        r = _ensure_candidate_plan(dict(r))
        action = str(r.get("action") or "").upper()
        if action not in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            continue
        rr = f(r.get("rr"))
        conf = float(r.get("confidence") or 0)
        if rr is None or rr < MIN_EXECUTABLE_RR or conf < MIN_CONFIDENCE:
            continue
        r["opportunity_score"] = _opportunity_score(r)
        candidates.append(r)
    candidates.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
    return candidates[:5]

def dynamic_top8(results, dynamic30, exclude_symbols=None):
    top10 = {str(x).upper() for x in ATLAS_PRIORITY_TOP10}
    excluded = {str(x).upper() for x in (exclude_symbols or ())}
    allowed = {
        str(x).upper() for x in (dynamic30 or [])
        if str(x).upper() not in top10
        and str(x).upper() not in excluded
        and not is_stable(str(x).upper())
        and not is_ambiguous_symbol(str(x).upper())
    }
    rows = []
    for r in results or []:
        coin = str(r.get("coin") or "").upper()
        if coin not in allowed or is_stable(coin) or is_ambiguous_symbol(coin):
            continue
        # Dynamic section is for meaningful market candidates, not stablecoins/data junk.
        if not r.get("price") or r.get("action") == "NO DATA":
            continue
        r = _ensure_candidate_plan(dict(r))
        r["opportunity_score"] = _opportunity_score(r)
        rows.append(r)
    rows.sort(key=lambda r: (r.get("opportunity_score", 0), abs(float(r.get("change") or 0))), reverse=True)
    return rows[:8]

def _metal_analysis(name):
    symbol = METAL_YAHOO[name]
    try:
        rows = yahoo_chart(symbol, "4h", "120d")
        rows = strip_incomplete(rows, "4h")
        if len(rows) < 60:
            raise RuntimeError("insufficient closed candles")
        c=closes(rows)
        price=c[-1]
        trend=trend_from_rows(rows)
        rsi_v=rsi(c)
        ml,ms,_=macd(c)
        macd_state="BULLISH" if ml is not None and ms is not None and ml>ms else "BEARISH" if ml is not None and ms is not None else "UNKNOWN"
        atrp=atr_pct(rows)
        lows=[f(x[3]) for x in rows[-30:] if f(x[3]) is not None and f(x[3])<price]
        highs=[f(x[2]) for x in rows[-30:] if f(x[2]) is not None and f(x[2])>price]
        support=max(lows) if lows else None
        resistance=min(highs) if highs else None
        if support is None or resistance is None:
            raise RuntimeError("support/resistance unavailable")
        direction="LONG" if trend=="BULLISH" and macd_state=="BULLISH" else "SHORT" if trend=="BEARISH" and macd_state=="BEARISH" else "NONE"
        levels=calculate_levels(rows,direction,{"support":support,"resistance":resistance}) if direction!="NONE" else None
        action="BUY CONFIRMATION" if direction=="LONG" and rsi_v is not None and rsi_v<72 else "SELL CONFIRMATION" if direction=="SHORT" and rsi_v is not None and rsi_v>28 else "BULLISH WATCH" if direction=="LONG" else "BEARISH WATCH" if direction=="SHORT" else "NO TRADE"
        conf=55
        if direction!="NONE": conf += 15
        if (direction=="LONG" and rsi_v is not None and 50<=rsi_v<=68) or (direction=="SHORT" and rsi_v is not None and 32<=rsi_v<=50): conf += 10
        if levels: conf += 10
        rr=_rr_from_values((levels or {}).get("entry"),(levels or {}).get("sl"),(levels or {}).get("tp2")) if levels else None
        # دریافت سشن برای فلزات
        session, session_label, session_multiplier = get_current_session()
        return {"coin":name,"price":price,"change":None,"h4_trend":trend,"d1_trend":trend,"w1_trend":"UNKNOWN","rsi":rsi_v,"macd":macd_state,"atr_pct":atrp,"support":support,"resistance":resistance,"direction":direction,"action":action,"confidence":min(int(conf),100),"entry":(levels or {}).get("entry"),"sl":(levels or {}).get("sl"),"tp1":(levels or {}).get("tp1"),"tp2":(levels or {}).get("tp2"),"tp3":(levels or {}).get("tp3"),"tp4":(levels or {}).get("tp4"),"rr":rr,"reason":"روند 4H + MACD + ساختار قیمت","snapshots":{"4h":{"rows":rows}},"session":session,"session_label":session_label,"session_multiplier":session_multiplier}
    except Exception as e:
        return {"coin":name,"price":None,"change":None,"h4_trend":"N/A","d1_trend":"N/A","w1_trend":"N/A","rsi":None,"macd":"N/A","atr_pct":None,"support":None,"resistance":None,"direction":"NONE","action":"NO DATA","confidence":0,"reason":"داده در دسترس نیست","error":str(e)}


def metals_report():
    rows=[_metal_analysis(x) for x in ATLAS_METALS]
    lines=["━━━━━━━━━━━━━━━━━━","🪙 ATLAS METALS","طلا / نقره / مس — مستقل از Top 5 کریپتو"]
    for r in rows:
        lines.append(asset_block(r, metal=True, detail=True))
    return "\n\n".join(lines)


def _compact_scenario_row(r, metal=False):
    """Compact dashboard row matching the user's uploaded CSV format.

    Engine calculations remain internal. Telegram exposes only:
    asset, overall status, key level, bullish scenario, bearish/correction scenario.
    """
    r = dict(r or {})
    symbol = str(r.get("coin") or r.get("symbol") or "UNKNOWN").upper()
    price = f(r.get("price"))
    change = f(r.get("change"))
    action = str(r.get("action") or r.get("decision_state") or "WAIT").upper()
    h4 = str(r.get("h4_trend") or "UNKNOWN").upper()
    d1 = str(r.get("d1_trend") or "UNKNOWN").upper()
    support = f(r.get("support"))
    resistance = f(r.get("resistance"))
    entry = f(r.get("entry"))
    sl = f(r.get("sl"))
    tp1 = f(r.get("tp1"))
    tp2 = f(r.get("tp2"))

    # دریافت سشن فعلی
    session, session_label, session_multiplier = get_current_session()

    if action in ("BUY", "BUY CONFIRMATION"):
        status = "BUY"
    elif action in ("SELL", "SELL CONFIRMATION", "SELL / REDUCE"):
        status = "SELL"
    elif action in ("BULLISH WATCH", "WATCH"):
        status = "WATCH"
    elif action == "NO DATA":
        status = "NO DATA"
    else:
        status = "WAIT"

    # Keep the uploaded table's wording style: short, decision-oriented,
    # and without RSI/MACD/ATR/confidence/news details.
    if h4 == "BULLISH" and d1 == "BULLISH":
        if symbol == "BTC":
            overall = "صعودی اما در حال تثبیت"
        else:
            overall = "صعودی"
    elif h4 == "BEARISH" and d1 == "BEARISH":
        overall = "نزولی"
    elif h4 == "BULLISH":
        overall = "صعودی اما در حال تثبیت"
    elif h4 == "BEARISH":
        overall = "نزولی اما در حال نوسان"
    else:
        overall = "خنثی / نامشخص"

    if price is None:
        overall = "داده کافی نیست"

    if support is not None and resistance is not None:
        if abs(resistance - support) / max(abs(price or resistance), 1e-12) < 0.02:
            key = f"{fmt(support)} - {fmt(resistance)}"
        else:
            key = f"حمایت {fmt(support)} | مقاومت {fmt(resistance)}"
    elif support is not None:
        key = f"حمایت {fmt(support)}"
    elif resistance is not None:
        key = f"مقاومت {fmt(resistance)}"
    else:
        key = "سطح کلیدی در دسترس نیست"

    if resistance is not None:
        bull = f"حفظ و تثبیت بالای {fmt(resistance)}"
    elif entry is not None:
        bull = f"تثبیت بالای {fmt(entry)}"
    else:
        bull = "تأیید ادامه روند صعودی"

    if tp1 is not None:
        bull += f"، هدف اول {fmt(tp1)}"
    if tp2 is not None:
        bull += f" و هدف دوم {fmt(tp2)}"

    if support is not None:
        bear = f"شکست زیر {fmt(support)}"
    elif sl is not None:
        bear = f"شکست سطح دفاعی {fmt(sl)}"
    else:
        bear = "از دست رفتن حمایت کلیدی"

    if sl is not None:
        bear += f"، حد ریسک {fmt(sl)}"

    # For metals the same table structure is used; no separate verbose block.
    return {
        "ارز": symbol,
        "وضعیت کلی": overall,
        "نقطه‌ی کلیدی": key,
        "سناریوی صعودی": bull,
        "سناریوی نزولی (اصلاح)": bear,
        "status": status,
        "price": price,
        "change": change,
        "session": session_label,
        "session_multiplier": session_multiplier,
    }


def _compact_section(title, rows, metal=False):
    lines = [title, "───────────────────"]
    if not rows:
        lines.append("⚪ داده‌ای برای نمایش وجود ندارد.")
        return "\n".join(lines)

    for r in rows:
        x = _compact_scenario_row(r, metal=metal)
        lines.append(
            f"🔹 {x['ارز']} | {x['وضعیت کلی']}\n"
            f"   نقطه‌ی کلیدی: {x['نقطه‌ی کلیدی']}\n"
            f"   🟢 صعودی: {x['سناریوی صعودی']}\n"
            f"   🔴 نزولی: {x['سناریوی نزولی (اصلاح)']}"
        )
    # اضافه کردن سشن به انتهای بخش
    session, session_label, session_multiplier = get_current_session()
    lines.append(f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")
    return "\n".join(lines)



def _table_status(r):
    h4 = str(r.get("h4_trend") or "").upper()
    d1 = str(r.get("d1_trend") or "").upper()
    if h4 == "BULLISH" and d1 == "BULLISH":
        return "BULL"
    if h4 == "BEARISH" and d1 == "BEARISH":
        return "BEAR"
    if h4 == "BULLISH":
        return "BULL?"
    if h4 == "BEARISH":
        return "BEAR?"
    return "WAIT"

def _compact_dashboard_table(title, rows):
    """Telegram-safe monospace table; no HTML/Markdown dependency."""
    cols = ("ASSET", "STATUS", "PRICE", "SUPPORT", "RESIST")
    data=[]
    for r in rows or []:
        sym=str(r.get("coin") or r.get("symbol") or "?").upper()
        data.append((sym, _table_status(r), fmt(r.get("price")), fmt(r.get("support")), fmt(r.get("resistance"))))
    if not data:
        return f"{title}\n───────────────────\nداده‌ای برای جدول موجود نیست."
    widths=[len(x) for x in cols]
    for row in data:
        widths=[max(w,len(str(v))) for w,v in zip(widths,row)]
    header="  ".join(str(v).ljust(widths[i]) for i,v in enumerate(cols))
    sep="  ".join("-"*w for w in widths)
    lines=[title,"───────────────────",header,sep]
    for row in data:
        lines.append("  ".join(str(v).ljust(widths[i]) for i,v in enumerate(row)))
    # اضافه کردن سشن به انتهای جدول
    session, session_label, session_multiplier = get_current_session()
    lines.append(f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")
    return "\n".join(lines)

def build_dashboard_table(results, top10, dynamic30):
    """Separate table message covering all requested universes + metals."""
    personal_symbols={str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    by={str(r.get("coin") or "").upper():r for r in (results or []) if r.get("coin")}
    top10_rows=[by[s] for s in (top10 or ATLAS_PRIORITY_TOP10) if str(s).upper() not in personal_symbols and str(s).upper() in by]
    dynamic_rows=[by[str(s).upper()] for s in (dynamic30 or []) if str(s).upper() in by and str(s).upper() not in personal_symbols and str(s).upper() not in {str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)}]
    personal_rows=_portfolio_rows(results)
    metals=[_metal_analysis(x) for x in ATLAS_METALS]
    blocks=[
        "📊 ATLAS AI — DASHBOARD TABLE",
        "━━━━━━━━━━━━━━━━━━",
        _compact_dashboard_table("📡 MARKET TOP 10 (EX-PERSONAL)", top10_rows),
        _compact_dashboard_table("📡 DYNAMIC TOP 30 (ALL CANDIDATES)", dynamic_rows),
        _compact_dashboard_table("💼 PERSONAL PORTFOLIO", personal_rows),
        _compact_dashboard_table("🪙 ATLAS METALS", metals),
    ]
    return "\n\n".join(blocks)

def _final_market_recommendation(results, top10, dynamic30, macro=None, btc_regime=None):
    """Short final recommendation, derived from current engine state."""
    rows = [r for r in (results or []) if isinstance(r, dict)]
    rsi_vals = [f(r.get("rsi")) for r in rows if f(r.get("rsi")) is not None]
    overbought = sum(1 for x in rsi_vals if x >= 70)
    bullish = sum(1 for r in rows if str(r.get("h4_trend") or "").upper() == "BULLISH")
    bearish = sum(1 for r in rows if str(r.get("h4_trend") or "").upper() == "BEARISH")
    regime = str(btc_regime or "").upper()
    session, session_label, session_multiplier = get_current_session()
    
    if not rows:
        return f"توصیه نهایی: فعلاً در جایگاه ناظر (HOLD) باشید و منتظر تأیید جهت بازار و شکل‌گیری سطوح حمایتی معتبر بمانید. (سشن: {session_label})"

    if overbought >= max(3, len(rsi_vals) // 4) and bearish >= bullish * 0.35:
        return (
            f"توصیه نهایی: فعلاً در جایگاه ناظر (HOLD) باشید و منتظر یک اصلاح قیمت "
            f"(pullback) به سطوح حمایتی کلیدی باشید. با توجه به اینکه بخشی از شاخص‌ها "
            f"نشان از اشباع خرید و کاهش قدرت دارند، هرگونه ورود جدید در قیمت‌های فعلی "
            f"ریسک بالایی دارد. منتظر شفاف‌تر شدن جهت بازار باشید. (سشن: {session_label} | ضریب: {session_multiplier:.1f}x)"
        )
    if regime == "BEARISH" or bearish > bullish:
        return (
            f"توصیه نهایی: فعلاً HOLD باشید و از ورود عجولانه خودداری کنید. "
            f"ابتدا تثبیت قیمت روی حمایت‌های کلیدی و تغییر تأییدشده ساختار روند را انتظار بکشید. (سشن: {session_label} | ضریب: {session_multiplier:.1f}x)"
        )
    if bullish > bearish * 1.5 and overbought < max(3, len(rsi_vals) // 3):
        return (
            f"توصیه نهایی: روند فعلاً متمایل به صعود است؛ ورود فقط روی شکست و تثبیت "
            f"مقاومت‌های کلیدی یا pullback کنترل‌شده به حمایت‌ها منطقی است. از تعقیب قیمت "
            f"پس از جهش‌های تند خودداری کنید. (سشن: {session_label} | ضریب: {session_multiplier:.1f}x)"
        )
    return (
        f"توصیه نهایی: فعلاً در جایگاه ناظر (HOLD) باشید و منتظر تأیید شفاف‌تر جهت بازار "
        f"یا یک pullback به سطوح حمایتی کلیدی بمانید. ورود در شرایط نامطمئن ریسک بهینه‌ای ندارد. (سشن: {session_label} | ضریب: {session_multiplier:.1f}x)"
    )



def _best_setup_block(results, universe_filter=None, title="🔥 BEST SETUP"):
    """Choose only a real, geometrically valid setup; overbought is a risk modifier, not a buy signal."""
    allowed={str(x).upper() for x in universe_filter} if universe_filter is not None else None
    candidates=[]
    for raw in results or []:
        r=_ensure_candidate_plan(dict(raw or {}))
        sym=str(r.get("coin") or "").upper()
        if allowed is not None and sym not in allowed: continue
        state=str(r.get("decision_state") or r.get("action") or "").upper()
        if state not in ("BUY CONFIRMATION","SELL CONFIRMATION","BUY","SELL"): continue
        if r.get("repeat_signal"): continue
        plan=_csv_safe_plan(r)
        if not plan: continue
        rr=_rr_from_values(*plan[:2], plan[3])
        if rr is None or rr < MIN_EXECUTABLE_RR: continue
        conf=float(r.get("confidence") or 0)
        rsi_v=f(r.get("rsi"))
        penalty=12 if rsi_v is not None and rsi_v>=80 else 7 if rsi_v is not None and rsi_v>=75 else 0
        score=conf + min(rr,5)*5 + float(r.get("liquidity_score") or 0)*0.05 - penalty
        candidates.append((score,r,rr,rsi_v))
    if not candidates:
        return title + ": هیچ ستاپ اجرایی با R/R و هندسه معتبر در این اجرا تأیید نشد."
    _,r,rr,rsi_v=max(candidates,key=lambda x:x[0])
    direction="BUY" if str(r.get("direction"))=="LONG" else "SELL"
    entry,sl,tp1,tp2=_csv_safe_plan(r)
    risk_note=" | RSI اشباع خرید" if rsi_v is not None and rsi_v>=75 else ""
    session, session_label, session_multiplier = get_current_session()
    return (f"{title}: {r.get('coin')} — {direction} — R/R 1:{rr:.2f}\n"
            f"   Entry: {fmt(entry)} | SL: {fmt(sl)} | TP1: {fmt(tp1)} | TP2: {fmt(tp2)}\n"
            f"   Confidence: {float(r.get('confidence') or 0):.0f}% | H4/D1: {r.get('h4_trend','UNKNOWN')}/{r.get('d1_trend','UNKNOWN')}{risk_note}\n"
            f"   🕐 سشن: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")

def build_report(results, top10, dynamic30, macro, news, market_info, unavailable=0, btc_regime=None, breadth=None):
    """MARKET engine: only the compact table-style dashboard is exposed."""
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    market_results = [
        r for r in (results or [])
        if str(r.get("coin") or "").upper() not in personal_symbols
    ]
    top10_order = [
        str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)
        if str(x).upper() not in personal_symbols
    ]
    result_map = {str(r.get("coin") or "").upper(): r for r in market_results if r.get("coin")}
    top10_rows = [result_map[s] for s in top10_order if s in result_map]
    top10_names = set(top10_order)
    dyn30_all_rows = [
        result_map[str(x).upper()]
        for x in (dynamic30 or [])
        if str(x).upper() in result_map
        and str(x).upper() not in top10_names
        and str(x).upper() not in personal_symbols
    ]
    dyn30_rows = dynamic_top8(market_results, [r.get("coin") for r in dyn30_all_rows], exclude_symbols=personal_symbols)

    metal_rows = [_metal_analysis(x) for x in ATLAS_METALS]
    dt = now_tehran()
    session, session_label, session_multiplier = get_current_session()
    lines = [
        "🤖 ATLAS AI — MARKET 4H",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران",
        f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x",
        _best_setup_block(market_results),
        _compact_section("📡 ATLAS TOP 10", top10_rows),
        _compact_section("📡 DYNAMIC TOP 30 — خارج از Top 10 و Personal", dyn30_rows),
        _compact_section("🪙 ATLAS METALS — GOLD / SILVER / COPPER", metal_rows, metal=True),
        _final_market_recommendation(results, top10_rows, dyn30_rows, macro, btc_regime),
    ]
    return "\n\n".join(lines)


def build_personal_report(results, macro=None, news=None, market_info=None, btc_regime=None, breadth=None):
    """PERSONAL engine: all portfolio assets, same compact table format."""
    rows = _portfolio_rows(results)
    dt = now_tehran()
    session, session_label, session_multiplier = get_current_session()
    return "\n\n".join([
        "🤖 ATLAS AI — PERSONAL PORTFOLIO 4H",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران",
        f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x",
        _best_setup_block(rows, title="🔥 BEST PERSONAL SETUP"),
        _compact_section("💼 PERSONAL PORTFOLIO — همه دارایی‌ها", rows),
        _final_market_recommendation(rows, [], [], macro, btc_regime),
    ])


def personal_report(*args, **kwargs):
    return build_personal_report(*args, **kwargs)


def atlas_engine_mode():
    return get_engine_mode()


def build_two_engine_reports(results, top10, dynamic30, macro, news, market_info, unavailable=0, btc_regime=None, breadth=None):
    market=build_report(results,top10,dynamic30,macro,news,market_info,unavailable,btc_regime,breadth)
    mode=get_engine_mode()
    if mode=="MARKET": return [market]
    personal=build_personal_report(results,macro,news,market_info,btc_regime,breadth)
    if mode=="PERSONAL": return [personal]
    return [market,personal]


# MARKET INTELLIGENCE — GLOBAL / SENTIMENT / DOMINANCE / MOVERS
# ============================================================

def global_market_intelligence():
    out = {
        "market_cap": None, "volume_24h": None, "market_change_24h": None,
        "volume_change_24h": None, "btc_dominance": None,
        "eth_dominance": None, "stablecoin_dominance": None,
        "altcoin_dominance": None, "fear_greed": None,
        "fear_greed_label": None, "fear_greed_ts": None,
        "top_gainers": [], "top_losers": [], "heatmap": [],
        "source": "CoinGecko + Alternative.me + optional CoinGlass",
    }
    global_data = safe_http_get(
        "https://api.coingecko.com/api/v3/global",
        headers=coingecko_headers(), default={}
    )
    if isinstance(global_data, dict):
        d = global_data.get("data") or {}
        cap = d.get("total_market_cap") or {}
        vol = d.get("total_volume") or {}
        dom = d.get("market_cap_percentage") or {}
        out["market_cap"] = f(cap.get("usd"))
        out["volume_24h"] = f(vol.get("usd"))
        out["market_change_24h"] = f(d.get("market_cap_change_percentage_24h_usd"))
        out["volume_change_24h"] = f(d.get("volume_change_percentage_24h_usd"))
        out["btc_dominance"] = f(dom.get("btc"))
        out["eth_dominance"] = f(dom.get("eth"))
        stable_ids = ("usdt", "usdc", "usde", "dai", "fdusd", "usds", "usdd")
        stable_dom = sum(f(dom.get(k), 0) or 0 for k in stable_ids)
        out["stablecoin_dominance"] = stable_dom if stable_dom > 0 else None
        btc = out["btc_dominance"] or 0
        stable = out["stablecoin_dominance"] or 0
        out["altcoin_dominance"] = max(0.0, 100.0 - btc - stable)

    markets = []
    for page, per_page in ((1, 250), (2, 50)):
        url = "https://api.coingecko.com/api/v3/coins/markets?" + urllib.parse.urlencode({
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": str(per_page), "page": str(page), "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        })
        rows = safe_http_get(url, headers=coingecko_headers(), default=[])
        if isinstance(rows, list):
            markets.extend(rows)
        if len(markets) >= 300:
            break
        time.sleep(0.15)

    clean = []
    for x in markets[:300]:
        if not isinstance(x, dict):
            continue
        sym = (x.get("symbol") or "").upper()
        if not sym or is_stable(sym):
            continue
        ch = f(x.get("price_change_percentage_24h"))
        price = f(x.get("current_price"))
        vol = f(x.get("total_volume"))
        rank = x.get("market_cap_rank")
        if ch is None or price is None:
            continue
        clean.append({
            "symbol": sym, "name": x.get("name") or sym,
            "rank": rank, "price": price, "volume": vol,
            "change_24h": ch, "high_24h": f(x.get("high_24h")),
            "low_24h": f(x.get("low_24h")),
            "change_1h": f(x.get("price_change_percentage_1h_in_currency")),
            "change_7d": f(x.get("price_change_percentage_7d_in_currency")),
        })
    unique = {}
    for item in sorted(clean, key=lambda x: (x.get("rank") or 999999)):
        unique.setdefault(item["symbol"], item)
    clean = list(unique.values())
    clean.sort(key=lambda x: x["change_24h"], reverse=True)
    out["top_gainers"] = clean[:7]
    out["top_losers"] = list(reversed(clean[-7:])) if clean else []

    fg = safe_http_get("https://api.alternative.me/fng/?limit=1", default={})
    if isinstance(fg, dict):
        try:
            item = (fg.get("data") or [])[0]
            out["fear_greed"] = int(item.get("value"))
            out["fear_greed_label"] = item.get("value_classification")
            out["fear_greed_ts"] = item.get("timestamp")
        except (IndexError, TypeError, ValueError):
            pass

    out["heatmap"] = liquidation_heatmap_summary(("BTC", "ETH"))
    return out

def liquidation_heatmap_summary(symbols=("BTC", "ETH")):
    if not COINGLASS_API_KEY:
        return []
    headers = {"CG-API-KEY": COINGLASS_API_KEY, "accept": "application/json"}
    result = []
    for symbol in symbols:
        url = "https://open-api-v4.coinglass.com/api/futures/liquidation/aggregated-heatmap/model1?" + urllib.parse.urlencode({
            "symbol": symbol, "range": "24h"
        })
        d = safe_http_get(url, timeout=15, headers=headers, default={})
        if not isinstance(d, dict) or d.get("code") not in (None, "0", 0):
            continue
        data = d.get("data") or {}
        y_axis = data.get("y_axis") or []
        cells = data.get("liquidation_leverage_data") or []
        price = None
        candles = data.get("price_candlesticks") or []
        if candles and isinstance(candles[-1], (list, tuple)) and len(candles[-1]) >= 5:
            price = f(candles[-1][4])
        levels = []
        for cell in cells:
            if not isinstance(cell, (list, tuple)) or len(cell) < 3:
                continue
            yi, intensity = safe_float(cell[1]), safe_float(cell[2])
            if yi is None or intensity is None:
                continue
            yi = int(yi)
            if 0 <= yi < len(y_axis):
                lvl = f(y_axis[yi])
                if lvl and lvl > 0:
                    levels.append((lvl, intensity))
        above = sorted([x for x in levels if price is not None and x[0] > price], key=lambda z: z[1], reverse=True)
        below = sorted([x for x in levels if price is not None and x[0] < price], key=lambda z: z[1], reverse=True)
        result.append({
            "symbol": symbol, "price": price,
            "above": above[:3], "below": below[:3],
        })
    return result

def market_intelligence_block(mi):
    lines = ["━━━━━━━━━━━━━━━━━━", "🌐 GLOBAL MARKET PULSE"]
    if mi.get("market_cap") is not None:
        lines.append(f"Total Market Cap: ${mi['market_cap']/1e12:.2f}T")
    if mi.get("volume_24h") is not None:
        lines.append(f"24H Market Volume: ${mi['volume_24h']/1e9:.2f}B")
    if mi.get("market_change_24h") is not None:
        lines.append(f"Market Cap 24H: {pct(mi['market_change_24h'])}")
    if mi.get("volume_change_24h") is not None:
        lines.append(f"Volume 24H Change: {pct(mi['volume_change_24h'])}")
    if mi.get("fear_greed") is not None:
        lines.append(f"😨 Fear & Greed: {mi['fear_greed']} — {mi.get('fear_greed_label','N/A')} (Alternative.me)")
    dom = []
    if mi.get("btc_dominance") is not None: dom.append(f"BTC {mi['btc_dominance']:.2f}%")
    if mi.get("eth_dominance") is not None: dom.append(f"ETH {mi['eth_dominance']:.2f}%")
    if mi.get("altcoin_dominance") is not None: dom.append(f"ALT* {mi['altcoin_dominance']:.2f}%")
    if dom: lines.append("Dominance: " + " | ".join(dom))
    if mi.get("stablecoin_dominance") is not None:
        lines.append(f"Stablecoin dominance: {mi['stablecoin_dominance']:.2f}%")

    gainers = mi.get("top_gainers") or []
    losers = mi.get("top_losers") or []
    if gainers:
        lines.append("🚀 TOP GAINERS — Top 300: " + " | ".join(f"{x['symbol']} {pct(x['change_24h'])}" for x in gainers[:5]))
    if losers:
        lines.append("🔻 TOP LOSERS — Top 300: " + " | ".join(f"{x['symbol']} {pct(x['change_24h'])}" for x in losers[:5]))

    hm = mi.get("heatmap") or []
    if hm:
        lines.append("🔥 LIQUIDATION HEATMAP — CoinGlass")
        for x in hm:
            above = x.get("above") or []
            below = x.get("below") or []
            a = fmt(above[0][0]) if above else "N/A"
            b = fmt(below[0][0]) if below else "N/A"
            lines.append(f"{x['symbol']}: price {fmt(x.get('price'))} | strongest above {a} | strongest below {b}")
    else:
        lines.append("🔥 Liquidation Heatmap: N/A (COINGLASS_API_KEY not configured or endpoint unavailable)")
    lines.append("* ALT* = total crypto dominance excluding BTC and principal stablecoins; ETH is included in ALT*, so dominance lines are not additive.")
    return "\n".join(lines)

def market_summary(results, macro, news):
    tradable = [
        x for x in results
        if x["action"] in ("BUY CONFIRMATION", "SELL CONFIRMATION")
    ]
    bullish = sum(1 for x in results if x["h4_trend"] == "BULLISH")
    bearish = sum(1 for x in results if x["h4_trend"] == "BEARISH")

    if bullish > bearish * 1.25:
        regime = "تمایل غالب صعودی"
    elif bearish > bullish * 1.25:
        regime = "تمایل غالب نزولی"
    else:
        regime = "بازار دوطرفه / خنثی"

    dxy = macro.get("DXY")
    fg = safe_http_get(
        "https://api.alternative.me/fng/?limit=1",
        default={},
    )
    fg_value = None
    fg_label = ""
    try:
        fg_value = int(fg["data"][0]["value"])
        fg_label = fg["data"][0]["value_classification"]
    except Exception:
        pass

    lines = [
        "━━━━━━━━━━━━━━━━━━",
        "🧠 ATLAS MARKET INTELLIGENCE",
        f"Bias: {regime}",
        f"4H Bullish: {bullish} | 4H Bearish: {bearish}",
        f"Actionable setups: {len(tradable)}",
        f"DXY: {fmt(dxy)} | USD liquidity proxy" if dxy is not None else "DXY: N/A | USD liquidity proxy unavailable",
        f"Fear & Greed: {fg_value} — {fg_label}" if fg_value is not None else "Fear & Greed: N/A",
        f"News: {news['bias']} / Impact: {news['impact']}",
    ]

    if macro.get("GOLD"):
        lines.append(f"Gold: {fmt(macro['GOLD'])}")
    if macro.get("SILVER"):
        lines.append(f"Silver: {fmt(macro['SILVER'])}")
    if macro.get("COPPER"):
        lines.append(f"Copper: {fmt(macro['COPPER'])}")
    if macro.get("WTI"):
        lines.append(f"WTI: {fmt(macro['WTI'])}")
    if macro.get("BRENT"):
        lines.append(f"Brent: {fmt(macro['BRENT'])}")

    if tradable:
        lines.append("")
        lines.append("🏆 BEST SETUPS")
        for i, x in enumerate(
            sorted(
                tradable,
                key=lambda z: (z["confidence"], z["liquidity_score"]),
                reverse=True,
            )[:8],
            1,
        ):
            lines.append(
                f"{i}. {x['coin']} — {x['direction']} — "
                f"{x['confidence']}% — {x['liquidity']}"
            )
    else:
        lines += [
            "",
            "⛔ هیچ ستاپی با تمام شروط ATLAS تأیید نشد.",
            "عدم قطعیت بالا - سیگنال صادر نشد",
        ]

    lines += [
        "",
        "📌 جمع‌بندی:",
        "ATLAS فقط زمانی سیگنال معاملاتی می‌دهد که روند H4 و D1، "
        "اندیکاتورها، حجم و ساختار قیمت هم‌جهت باشند.",
        "سیگنال خلاف روند تایم‌فریم بالاتر بدون واگرایی 3 سطحی حذف می‌شود.",
        "خبر پرریسک یا داده متناقض می‌تواند سیگنال را متوقف کند.",
        "استیبل‌کوین‌ها از چرخه سیگنال‌دهی حذف شده‌اند.",
        "",
        "تنظیمات بر اساس داده‌ی محدود اخیر انجام شده و ممکن است در آینده عملکرد متفاوتی داشته باشد.",
    ]
    return "\n".join(lines)

def atlas_conclusion(results):
    threshold = MIN_CONFIDENCE
    actionable = [x for x in results if x.get("action") in ("BUY CONFIRMATION", "SELL CONFIRMATION") and x.get("confidence", 0) >= threshold]
    buys = sorted([x for x in actionable if x.get("action") == "BUY CONFIRMATION"], key=lambda z: (z.get("confidence", 0), z.get("rr") or 0, z.get("liquidity_score", 0)), reverse=True)
    sells = sorted([x for x in actionable if x.get("action") == "SELL CONFIRMATION"], key=lambda z: (z.get("confidence", 0), z.get("rr") or 0, z.get("liquidity_score", 0)), reverse=True)
    rise = sorted([x for x in results if x.get("action") == "BULLISH WATCH" and x.get("confidence", 0) >= MIN_WATCH_CONFIDENCE], key=lambda z: (z.get("confidence", 0), z.get("liquidity_score", 0)), reverse=True)
    fall = sorted([x for x in results if x.get("action") == "BEARISH WATCH" and x.get("confidence", 0) >= MIN_WATCH_CONFIDENCE], key=lambda z: (z.get("confidence", 0), z.get("liquidity_score", 0)), reverse=True)

    lines = ["━━━━━━━━━━━━━━━━━━", f"🎯 {VERSION} FINAL CONCLUSION"]
    lines.append("🟢 BUY / ACCUMULATE: " + (", ".join(f"{x['coin']} ({x['confidence']}%)" for x in buys[:5]) if buys else "هیچ خریدی با تأیید کامل صادر نشد."))
    lines.append("🔴 SELL / REDUCE: " + (", ".join(f"{x['coin']} ({x['confidence']}%)" for x in sells[:5]) if sells else "هیچ فروش تأییدشده‌ای صادر نشد."))
    lines.append("📈 RISE WATCH: " + (", ".join(f"{x['coin']} ({x['confidence']}%)" for x in rise[:5]) if rise else "ندارد"))
    lines.append("📉 FALL WATCH: " + (", ".join(f"{x['coin']} ({x['confidence']}%)" for x in fall[:5]) if fall else "ندارد"))

    best = buys[0] if buys else (sells[0] if sells else None)
    best_side = "BUY" if buys else "SELL"
    if buys and sells and sells[0].get("confidence", 0) > buys[0].get("confidence", 0):
        best, best_side = sells[0], "SELL"
    if best:
        lines += [
            f"⭐ BEST SETUP: {best['coin']} — {best_side} — {best['confidence']}%",
            f"   H4/D1: {best.get('h4_trend')} / {best.get('d1_trend')} | S/R: {best.get('sr_confidence','LOW')} | Volume: {best.get('volume_ratio'):.2f}x" if best.get('volume_ratio') is not None else f"   H4/D1: {best.get('h4_trend')} / {best.get('d1_trend')} | S/R: {best.get('sr_confidence','LOW')} | Volume: N/A",
            f"   Entry: {fmt(best.get('entry'))} | SL: {fmt(best.get('sl'))} | TP1: {fmt(best.get('tp1'))} | TP2: {fmt(best.get('tp2'))}",
        ]
    elif rise or fall:
        watch = rise[0] if rise else fall[0]
        side = "BULLISH WATCH" if rise else "BEARISH WATCH"
        lines += [
            f"⭐ BEST WATCH: {watch['coin']} — {side} — {watch['confidence']}%",
            f"   Trigger: {(watch.get('candle_trigger') or {}).get('state','UNKNOWN')} | RSI: {watch.get('rsi'):.1f}" if watch.get('rsi') is not None else f"   Trigger: {(watch.get('candle_trigger') or {}).get('state','UNKNOWN')} | RSI: N/A",
            f"   S/R: {watch.get('sr_confidence','LOW')} | Volume: {watch.get('volume_ratio'):.2f}x" if watch.get('volume_ratio') is not None else f"   S/R: {watch.get('sr_confidence','LOW')} | Volume: N/A",
            "   تصمیم: هنوز ورود اجرایی نیست؛ منتظر تأیید ساختار/پولبک هستیم.",
        ]
    else:
        lines.append("⭐ BEST SETUP: NONE — بازار در این اجرا ستاپ کم‌ریسک و تأییدشده نداد.")

    new_events = 0
    for r in results:
        ev = r.get("candle_events", {})
        new_events += sum(1 for x in ev.values() if isinstance(x, dict) and x.get("status") == "NEW_CLOSED")
    lines.append(f"Threshold: {threshold:.0f}% | Watch threshold: {MIN_WATCH_CONFIDENCE:.0f}% | Closed-candle events observed: {new_events}")
    lines.append("🛡️ تصمیم ATLAS: BUY/SELL فقط پس از Gate + R/R + regime + ساختار؛ WATCH یعنی جهت جالب است اما ورود هنوز تأیید نشده.")
    return "\n".join(lines)


# ============================================================
# CONTEXT PERSISTENCE
# ============================================================

def save_context(macro, news, liquidity, market_info=None):
    STORE.insert(
        "atlas_market_context",
        {
            "timestamp": now_utc().isoformat(),
            "timeframe": "4h",
            "fear_greed": (market_info or {}).get("fear_greed"),
            "fear_greed_label": (market_info or {}).get("fear_greed_label"),
            "btc_dominance": (market_info or {}).get("btc_dominance"),
            "btc_funding": None,
            "btc_open_interest": None,
            "news_bias": news["bias"],
            "news_items": news["items"],
            "dxy": macro.get("DXY"),
            "liquidity_score": liquidity,
            "gold": macro.get("GOLD"),
            "silver": macro.get("SILVER"),
            "copper": macro.get("COPPER"),
            "wti": macro.get("WTI"),
            "brent": macro.get("BRENT"),
            "market_summary": news["bias"],
            "eth_dominance": (market_info or {}).get("eth_dominance"),
            "altcoin_dominance": (market_info or {}).get("altcoin_dominance"),
            "stablecoin_dominance": (market_info or {}).get("stablecoin_dominance"),
            "global_market_cap": (market_info or {}).get("market_cap"),
            "global_volume_24h": (market_info or {}).get("volume_24h"),
            "global_market_change_24h": (market_info or {}).get("market_change_24h"),
            "global_volume_change_24h": (market_info or {}).get("volume_change_24h"),
        },
    )

def save_run(results, parts, macro, news, unavailable=0):
    STORE.insert(
        "atlas_runs",
        {
            "timestamp": now_utc().isoformat(),
            "model_version": VERSION,
            "assets_scanned": len(results) + unavailable,
            "successful": len(results),
            "unavailable": unavailable,
            "signals_sent": sum(
                1 for x in results
                if x["action"] in ("BUY CONFIRMATION", "SELL CONFIRMATION")
            ),
            "telegram_parts": parts,
            "market_liquidity": market_liquidity_index(results),
            "dxy": macro.get("DXY"),
            "news_bias": news["bias"],
            "notes": "v11.0 complete: unified market + personal + metals + snapshot + self-healing",
        },
    )


# ============================================================
# MAIN
# ============================================================

_LAST_TOP10 = []
_LAST_DYNAMIC30 = []


def report():
    init_sqlite()
    evaluate_open_outcomes()
    universe, top10, dynamic30 = build_universe()
    global _LAST_TOP10, _LAST_DYNAMIC30
    _LAST_TOP10, _LAST_DYNAMIC30 = list(top10), list(dynamic30)

    # Governance: backtest MUST pass before self-healing can change weights.
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

    # v9: market regime and breadth are calculated after the raw radar scan,
    # then the decision engine converts technical confirmations into actual
    # trade candidates. The existing 4-hour cadence is intentionally unchanged.
    btc_regime = btc_market_regime()
    breadth = market_breadth(results)
    results = apply_decision_engine(results, btc_regime, breadth)

    for r in results:
        # Only genuinely executable decisions become open trade signals.
        r["action"] = r.get("decision_state", r.get("action"))
        store_signal(r)
    text = build_report(results, top10, dynamic30, macro, news, market_info, unavailable, btc_regime, breadth)
    return text, results, macro, news, market_info, unavailable

def checkpoint_sqlite(*args, **kwargs):
    """Compatibility checkpoint hook; SQLite persistence is handled by STORE/init_sqlite."""
    try:
        return True
    except Exception:
        return False

def _conditional_trade_plan(result):
    """Return the already validated candidate trade plan without approving a trade."""
    if not isinstance(result, dict):
        return None
    return {k: result.get(k) for k in ("entry","sl","tp1","tp2","tp3","tp4","direction")
            if result.get(k) is not None}

# ============================================================
# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT
# ============================================================

SNAPSHOT_SYMBOLS = ("BTC","ETH","XRP","SOL","BNB","DOGE","ADA","TRX","LINK","XLM","SUI","AVAX","LTC","SHIB","HBAR","DOT","BCH","XMR","NEAR")
PUBLIC_USDT_PAGES = (
    "https://wallex.ir/price/usdt",
    "https://www.excoino.com/coins",
    "https://nobitex.ir/usdt/",
)


def _snapshot_price_text(value):
    v = f(value)
    if v is None:
        return None
    if v >= 1:
        return f"${v:,.2f}" if v < 10000 else f"${v:,.0f}"
    if v >= 0.1:
        return f"${v:.2f}"
    if v >= 0.01:
        return f"${v:.4f}"
    if v >= 0.0001:
        return f"${v:.6f}"
    return f"${v:.8f}"


def _public_page_text(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 ATLAS-AI/11.0", "Accept": "text/html,application/xhtml+xml"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="ignore")


def _parse_usdt_toman_page(url, html):
    """Parse public exchange HTML only; no exchange API/key is used."""
    compact = re.sub(r"\\s+", " ", html or "")
    values = []

    # Wallex publishes the current USDT/Toman quote directly in تومان.
    wallex_patterns = (
        r"قیمت تتر به تومان برابر است با:\s*</?[^>]*>\s*([0-9۰-۹][0-9۰-۹,٬]*)",
        r"آخرین قیمت تتر.*?([0-9۰-۹][0-9۰-۹,٬]{4,})\s*تومان",
        r"USDT.*?([0-9۰-۹][0-9۰-۹,٬]{4,})\s*تومان",
    )
    for pat in wallex_patterns:
        for m in re.finditer(pat, compact, re.I):
            raw = m.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).replace(",", "").replace("٬", "")
            try:
                v = float(raw)
            except ValueError:
                continue
            if 50000 <= v <= 1000000:
                values.append(v)
        if values:
            return median(values)

    # Excoino exposes its local quote in ریال; convert to تومان exactly once.
    for m in re.finditer(r"USDT.{0,900}?([0-9][0-9,]{5,})\s*ریال.{0,120}?([0-9][0-9,]{5,})\s*ریال", compact, re.I):
        try:
            a = float(m.group(1).replace(",", "")) / 10.0
            b = float(m.group(2).replace(",", "")) / 10.0
        except ValueError:
            continue
        vals = [x for x in (a, b) if 50000 <= x <= 1000000]
        if vals:
            return median(vals)

    # Generic تومان/IRT/IRR patterns for public exchange pages.
    generic = (
        r"(?:USDT|Tether|تتر).{0,250}?([0-9][0-9,]{4,})\s*(?:تومان|IRT)",
        r"(?:USDT|Tether|تتر).{0,250}?([0-9][0-9,]{5,})\s*IRR",
    )
    for pat in generic:
        for m in re.finditer(pat, compact, re.I):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if 50000 <= v <= 1000000:
                values.append(v)
        if values:
            return median(values)
    return None


def fetch_usdt_toman_public():
    """Read USDT/Toman from reputable Iranian exchange web pages, without API keys."""
    candidates = []
    for url in PUBLIC_USDT_PAGES:
        try:
            html = _public_page_text(url)
            value = _parse_usdt_toman_page(url, html)
            if value is not None:
                candidates.append((float(value), url))
        except Exception as e:
            append_changelog("USDT_PUBLIC_SOURCE", None, None, f"{url}: {e}")
    if not candidates:
        return None
    # Median protects the snapshot from one stale/abnormal public page.
    return round(median([x[0] for x in candidates]), 0)

def fetch_snapshot_results():
    """Lightweight 3H snapshot path: tickers only, no 4H technical analysis."""
    ensure_exchanges()
    rows = []
    for sym in SNAPSHOT_SYMBOLS:
        best = None
        for eid in ("kcex", "lbank", "bybit", "okx", "kucoin", "gateio", "bitget", "mexc", "kraken"):
            try:
                t = exchange_ticker(eid, sym)
                if f(t.get("price")) is not None:
                    best = {"coin": sym, "price": t.get("price"), "change24": t.get("change")}
                    break
            except Exception:
                continue
        if best:
            rows.append(best)
    return rows


def _snapshot_previous_prices():
    """دریافت قیمت‌های قبلی از دیتابیس"""
    try:
        con = sqlite3.connect(DB_FILE, timeout=10)
        try:
            rows = con.execute("select symbol, price from snapshot_prices").fetchall()
            result = {str(sym).upper(): float(price) for sym, price in rows if price is not None}
            print(f"📊 Loaded {len(result)} previous prices from database")
            return result
        finally:
            con.close()
    except Exception as e:
        print(f"⚠️ Snapshot previous prices error: {e}")
        return {}


def _snapshot_direction(current, previous):
    """تشخیص جهت تغییر قیمت و نمایش فلش مناسب"""
    current = f(current)
    previous = f(previous)
    if current is None or previous is None or previous <= 0:
        return "➡️"
    delta_pct = (current - previous) / previous * 100.0
    if abs(delta_pct) < SNAPSHOT_FLAT_THRESHOLD_PCT:
        return "➡️"
    return "⬆️" if delta_pct > 0 else "⬇️"


def _save_snapshot_prices(results, captured_at):
    try:
        con = sqlite3.connect(DB_FILE, timeout=10)
        try:
            con.execute("create table if not exists snapshot_prices(symbol text primary key, price real not null, captured_at text not null)")
            for r in results or []:
                sym = str(r.get("coin") or "").upper()
                price = f(r.get("price"))
                if sym and price is not None and price > 0:
                    con.execute(
                        "insert into snapshot_prices(symbol,price,captured_at) values(?,?,?) "
                        "on conflict(symbol) do update set price=excluded.price,captured_at=excluded.captured_at",
                        (sym, price, captured_at),
                    )
            con.commit()
        finally:
            con.close()
    except Exception as e:
        print(f"⚠️ Snapshot save error: {e}")


def build_price_snapshot(results, updated_at=None, previous_prices=None):
    by_coin = {str(r.get("coin") or "").upper(): r for r in (results or [])}
    dt = updated_at or now_tehran()
    
    # اگر previous_prices ارسال نشده، از دیتابیس بخوان
    if previous_prices is None:
        previous_prices = _snapshot_previous_prices()
    
    weekdays = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")
    lines = [
        f"📅 {weekdays[dt.weekday()]} | {shamsi(dt)}",
        "",
        f"⏰ آخرین بروزرسانی : {dt.strftime('%H:%M:%S')}",
        "",
        "📊 وضعیت بازار ارزهای دیجیتال:",
        "───────────────────",
    ]
    
    # شمارش فلش‌ها برای دیباگ
    arrow_stats = {"⬆️": 0, "⬇️": 0, "➡️": 0}
    
    for sym in SNAPSHOT_SYMBOLS:
        r = by_coin.get(sym)
        if not r:
            lines.append(f"🔹 ➖{sym:<6}:   N/A")
            continue
        price = f(r.get("price"))
        if price is None:
            lines.append(f"🔹 ➖{sym:<6}:   N/A")
            continue
        arrow = _snapshot_direction(price, previous_prices.get(sym))
        arrow_stats[arrow] = arrow_stats.get(arrow, 0) + 1
        lines.append(f"🔹 {arrow}{sym:<6}:   {_snapshot_price_text(price)}")
    
    # اضافه کردن آمار فلش‌ها برای دیباگ
    print(f"📊 Arrow stats: ⬆️={arrow_stats.get('⬆️', 0)}, ⬇️={arrow_stats.get('⬇️', 0)}, ➡️={arrow_stats.get('➡️', 0)}")
    
    lines.append("───────────────────")
    usdt = fetch_usdt_toman_public()
    if usdt is None:
        lines.append("💵 🟡 نرخ تتر  :   در دسترس نیست")
    else:
        lines.append(f"💵 🟢نرخ تتر  :   {usdt:,.0f} تومان")
    lines.append("🔄 این پیام هر ۳ ساعت بروزرسانی می‌شود")
    
    session, session_label, session_multiplier = get_current_session()
    lines.append(f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")
    return "\n".join(lines)


def send_price_snapshot(results):
    """Send snapshot separately; persist comparison state only after successful delivery."""
    captured_at = now_tehran().isoformat()
    previous = _snapshot_previous_prices()
    payload = build_price_snapshot(results, previous_prices=previous)
    parts, sent, errors = send_report(payload)
    if sent == parts and sent > 0:
        _save_snapshot_prices(results, captured_at)
    return sent, errors

def _automatic_run_plan(now=None):
    """Unified scheduler: analysis every 4H, snapshot every 3H, both at overlaps."""
    dt = now or now_tehran()
    return {
        "analysis": dt.hour % 4 == 0,
        "snapshot": dt.hour % 3 == 0,
    }


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
            top10, dynamic30 = list(_LAST_TOP10), list(_LAST_DYNAMIC30)
            btc_regime = btc_market_regime()
            breadth = market_breadth(results)
            outputs = build_two_engine_reports(
                results, top10, dynamic30, macro, news, market_info,
                unavailable, btc_regime, breadth
            )
            outputs.append(build_dashboard_table(results, top10, dynamic30))
            
            # اضافه کردن جدول رتبه‌بندی سیگنال‌ها
            signal_ranking = build_signal_ranking_table(results, top10, dynamic30)
            outputs.append(signal_ranking)
            
            for payload in outputs:
                parts, sent, errors = send_report(payload)
                total_sent += sent
                all_errors.extend(errors)
                print(payload)
            
            # ارسال جدول تصویری (در صورت وجود matplotlib)
            image_sent = send_image_table(results, top10, dynamic30)
            if image_sent:
                print("✅ Image table sent successfully")
            else:
                print("ℹ️ Image table not sent (matplotlib may not be installed)")
            
            analysis_results = results
            csv_sent, csv_errors = send_csv_report(results, top10, dynamic30)
            total_sent += csv_sent
            all_errors.extend(csv_errors)
            print(f"CSV export: {csv_sent} destination(s), {len(csv_errors)} error(s)")
            save_context(macro, news, market_liquidity_index(results), market_info)
            save_run(results, sum(len(split_telegram(x)) for x in outputs), macro, news, unavailable)

        if do_snapshot:
            snapshot_results = analysis_results if analysis_results else fetch_snapshot_results()
            snapshot_sent, snapshot_errors = send_price_snapshot(snapshot_results)
            total_sent += snapshot_sent
            all_errors.extend(snapshot_errors)

        # ============================================================
        # Voice Output - ارسال گزارش صوتی
        # ============================================================
        if ENABLE_VOICE_REPORT and AUTO_SEND_VOICE:
            try:
                print("\n🎤 Generating audio report...")
                voice_data = analysis_results if analysis_results else snapshot_results
                if voice_data:
                    audio_file = generate_audio_report(voice_data)
                    if audio_file:
                        result = send_audio_report(audio_file, "🎤 گزارش صوتی اطلس")
                        if result:
                            print("✅ Audio report sent successfully")
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
