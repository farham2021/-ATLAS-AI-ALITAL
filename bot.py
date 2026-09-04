#============================================================
# ATLAS AI v11.5 — ARCHITECTURE REDESIGN PASS
# ============================================================
# Stage 1: Data Quality + Signal Lifecycle + No-Trade
# Stage 2: Regime Matrix (single RegimeEngine) + Volatility + Liquidation Cascade
# Stage 3: Intelligence Scoring (Signal Score / Model Strength / Win Probability)
# Stage 4: Decision Engine + Backtest Gate (real gate, not advisory)
# Stage 5: Reporting (Telegram / PNG / split CSV / voice) + Decision Supportit CSV / Voice)
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
#   - Model weights are changed only after a mandatory backtest gate AND a
#     minimum-sample-size gate (no auto-learning under 100 closed trades).
#   - Exactly one component may set decision_state/confidence/regime — no
#     two engines silently overwrite each other's output.
#   - Every self-modification is written to the changelog.
#
# IMPORTANT:
#   This is an analytical engine. It does not place orders.
#   No model can guarantee low-error signals or profits.
#
# ------------------------------------------------------------
# v11.3.1 CHANGELOG (decision-engine bugfix pass)
# ------------------------------------------------------------
# 1. Removed dead, silently-shadowed duplicate function definitions that never
#    executed (Python only keeps the last def of a repeated name): the old
#    generate_voice_summary, generate_csv_report, build_two_engine_reports,
#    build_image_table, and the v11.1 apply_intelligence/build_v11_intelligence_report
#    block. No behavior change — these bodies were already unreachable — but they
#    were a correctness/maintenance hazard, since editing the "obvious" earlier
#    copy of any of these functions previously had no effect at all.
# 2. Fixed v11_portfolio_diagnostics(): it read a field (v11_opportunity_score)
#    that no live code populated, so the portfolio-concentration warning was a
#    permanent no-op. It now reads the fields the live intel engine sets
#    (opportunity_score, executable).
# 3. The mandatory backtest gate previously only froze self-learning (weight
#    updates) on failure — it never restricted live BUY/SELL signals. A new
#    _LAST_BACKTEST_OK flag is now read inside apply_decision_engine(): when the
#    gate fails, no signal is allowed past WATCH state until it passes again.
# 4. v11_apply_intelligence() used to silently overwrite r["confidence"],
#    r["regime_trend"], r["regime_volatility"] — fields already set, with a
#    different meaning, by the engine that actually gated BUY/SELL. The original
#    values are now preserved as decision_confidence / decision_regime_trend /
#    decision_regime_volatility (also exported to CSV) so the number that drove
#    the trade decision remains visible after the intel-scoring pass runs.
# 5. self_diagnostic() (automatic weight tuning) was one-directional (only ever
#    decayed weights, never reinforced a feature behind a winning streak), used
#    a 3-trade batch (not statistically meaningful — one loss looked like a
#    "5%+ error rate"), and matched feature names against free-text notes with a
#    short token list that missed several real candle-pattern names. Batch size
#    is now configurable (ATLAS_SELF_HEAL_BATCH, default 15), the logic now
#    rewards a dominant winning feature as well as punishing a dominant losing
#    one, and the token list covers every pattern name candle_pattern() emits.
#
# ------------------------------------------------------------
# v11.5 CHANGELOG (architecture redesign, per user's review doc)
# ------------------------------------------------------------
# 6. Snapshot arrow bug: build_price_snapshot() read r["change24"], a key
#    analyze_coin() never set (the real key is r["change"]) — every row's
#    arrow silently fell back to a comparison against a previous-price table
#    that was usually empty, so every coin showed ➡️ regardless of the real
#    move. Fixed to read the correct key, AND a proper append-only
#    snapshot_price_history table was added (with Supabase migration) so the
#    arrow can be based on a real "price 4 hours ago" lookup instead of
#    whatever the last run happened to record.
# 7. Unified the two colliding regime engines (Stage 2's calculate_regime_score
#    path and the intel engine's _i_regime()) into one RegimeEngine() call.
#    Both used to write regime_trend/regime_volatility with different values;
#    now there is exactly one computation, done once, read everywhere else.
# 8. Score separation (was: a single overloaded "confidence"): every result
#    now carries three distinct numbers — signal_score (raw technical
#    evidence), model_strength (how decisive the read is), and
#    win_probability (a calibrated historical win rate, or None below the
#    minimum sample size).
# 9. win_probability is produced by a pure-Python isotonic regression
#    (Pool-Adjacent-Violators) over closed signal_outcomes, gated by sample
#    size (<100: NOT_CALIBRATED / 100-300: CAUTIOUS / 300-1000: ADAPTIVE /
#    1000+: ROBUST). The same tiers now also scale how aggressively
#    self_diagnostic() is allowed to move a feature weight.
# 10. Added why_not_trade(): every non-executable asset gets concrete,
#     itemized rejection reasons (gate block, R/R below minimum, weak volume,
#     H4/D1 conflict, resistance/support too close, low data quality, etc.)
#     surfaced in a new "چرا معامله نشد؟" report section, instead of the
#     report going quiet on the majority of scanned assets.
# 11. CSV export split into three files (personal / metals / dynamic_top30)
#     instead of one combined file, sent as three separate Telegram documents.
# 12. Fixed a second, pre-existing VERSION reassignment later in the file
#     that silently overrode the VERSION declared here — the same
#     "two definitions, last one wins" pattern this whole pass targets.
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
from statistics import mean, median, pstdev

import ccxt


# ============================================================
# CONFIG
# ============================================================

# ------------------------------------------------------------
# v11.6 CHANGELOG (backtest engine redesign)
# ------------------------------------------------------------
# 13. backtest_coin() used to book a hardcoded -1.5% / +3.0% equity change
#     on every SL/TP hit, regardless of the actual ATR-to-price ratio,
#     position sizing, fees, or slippage — i.e. it silently assumed a fixed
#     1.5%-of-equity risk with zero trading costs. The new engine
#     (_run_backtest_window) derives the real R-multiple per trade, applies
#     RISK_PER_TRADE_PCT for position sizing, and subtracts round-trip fees
#     (ATLAS_BACKTEST_FEE_PCT) and entry/exit slippage
#     (ATLAS_BACKTEST_SLIPPAGE_PCT).
# 14. Each trade now records MAE, MFE, holding time (bars), and exit reason
#     (TP/SL/TIMEOUT) instead of only a win/loss flag — previously a trade
#     that hit neither SL nor TP within the horizon was silently dropped
#     from the sample entirely.
# 15. Added Expectancy (R), Net Return, Sharpe, and Sortino to the
#     performance stats alongside the existing Win Rate / Profit Factor /
#     Max Drawdown — so a misleadingly high win rate on a net-losing
#     strategy is now visible.
# 16. Added walk_forward_backtest(): splits history into sequential
#     Train/Validate/Test windows (120/30/30 days by default) and runs the
#     same fixed rule on each independently, flagging when the out-of-sample
#     test period diverges sharply from train (possible overfit to one
#     window). This runs as a diagnostic on one representative coin per
#     gate check and is logged to the changelog — it does not (yet) change
#     the pass/fail decision on its own; see the note in mandatory_backtest_gate.
# ============================================================

VERSION = "ATLAS v11.5 WORKFLOW + SUPABASE REDESIGN"
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
# MARKET INTELLIGENCE BRIEFING (macro / whales / influential figures)
# ============================================================
# همه‌ی این‌ها اختیاری‌اند: اگر کلید مربوطه ست نشود، همان بخش بی‌صدا خالی
# می‌ماند و بقیه‌ی ربات مثل قبل کار می‌کند — هیچ‌کدام نباید کل اجرا را بشکنند.
#
# عمداً از اسکرپ غیررسمی توییتر/X یا Truth Social استفاده نشده: توییتر/X
# API رسمی برای خواندن توییت‌های یک اکانت خاص، پولی (طرح‌های Basic/Pro) است؛
# Truth Social اصلاً API عمومی ندارد و اسکرپ آن هم ناقض ToS است و هم چیزی است
# که با هر تغییر ظاهری سایت می‌شکند. به‌جای آن، اظهارات مهم افراد تأثیرگذار
# (ترامپ/پاول/بزوس) را از طریق خبرگزاری‌های معتبری که همان حرف‌ها را در عرض
# چند دقیقه پوشش می‌دهند (NewsAPI/CryptoPanic که همین حالا استفاده می‌شوند)
# دنبال می‌کنیم — پوشش قابل‌اتکاتر، بدون هزینه/ریسک اضافه.
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
WHALE_ALERT_API_KEY = os.environ.get("WHALE_ALERT_API_KEY", "").strip()
WHALE_ALERT_MIN_USD = float(os.environ.get("ATLAS_WHALE_MIN_USD", "3000000"))
ENABLE_INTEL_BRIEFING = os.environ.get("ATLAS_ENABLE_INTEL_BRIEFING", "1").strip() != "0"

INFLUENTIAL_FIGURES = {
    "ترامپ": ("trump", "truth social", "white house crypto", "trump tariff", "trump executive order"),
    "پاول (فدرال رزرو)": ("powell", "fomc", "federal reserve chair", "fed chair"),
    "بزوس": ("bezos", "jeff bezos"),
}

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
# MULTI-SOURCE VALIDATION LAYER
# ============================================================
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
# RISK & TRADE SETTINGS
# ============================================================
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE_PCT", "1.5"))
MAX_PORTFOLIO_RISK = float(os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT", "6.0"))
MIN_CONFIDENCE = float(os.environ.get("ATLAS_MIN_CONFIDENCE", "55"))
MAX_LEVERAGE = float(os.environ.get("ATLAS_MAX_LEVERAGE", "10"))

# ============================================================
# BACKTEST SETTINGS
# ============================================================
BACKTEST_DAYS = int(os.environ.get("ATLAS_BACKTEST_DAYS", "180"))
SIGNAL_HORIZON_BARS = int(os.environ.get("ATLAS_SIGNAL_HORIZON_BARS", "36"))
MIN_BACKTEST_IMPROVEMENT = float(os.environ.get("ATLAS_BACKTEST_IMPROVEMENT", "10"))
BACKTEST_REFRESH_HOURS = float(os.environ.get("ATLAS_BACKTEST_REFRESH_HOURS", "24"))
# Round-trip taker fee and one-way slippage, both in percent of price.
# Defaults are a reasonable major-exchange taker fee (0.08% round trip) and a
# conservative slippage estimate for liquid pairs.
BACKTEST_FEE_PCT = float(os.environ.get("ATLAS_BACKTEST_FEE_PCT", "0.08"))
BACKTEST_SLIPPAGE_PCT = float(os.environ.get("ATLAS_BACKTEST_SLIPPAGE_PCT", "0.05"))
# Walk-forward window sizes (days). Train isn't used to fit any parameter here
# (the signal rule is fixed, not optimized) — walk-forward instead checks
# whether the same fixed rule holds up out-of-sample instead of only having
# looked good over one lucky historical window.
WALK_FORWARD_TRAIN_DAYS = int(os.environ.get("ATLAS_WF_TRAIN_DAYS", "120"))
WALK_FORWARD_VALIDATE_DAYS = int(os.environ.get("ATLAS_WF_VALIDATE_DAYS", "30"))
WALK_FORWARD_TEST_DAYS = int(os.environ.get("ATLAS_WF_TEST_DAYS", "30"))

# ============================================================
# TECHNICAL SETTINGS
# ============================================================
MIN_VOLUME_RATIO = float(os.environ.get("ATLAS_MIN_VOLUME_RATIO", "0.60"))
H4_FALLBACK_MIN_SCORE = float(os.environ.get("ATLAS_H4_FALLBACK_MIN_SCORE", "70"))
REQUEST_SLEEP_SECONDS = float(os.environ.get("ATLAS_REQUEST_SLEEP_SECONDS", "0.50"))

# ============================================================
# TRADE GEOMETRY SETTINGS
# ============================================================
MIN_EXECUTABLE_RR = float(os.environ.get("ATLAS_MIN_EXECUTABLE_RR", "2.0"))
MIN_WATCH_CONFIDENCE = float(os.environ.get("ATLAS_MIN_WATCH_CONFIDENCE", "55"))
TRADE_GEOMETRY_EPSILON = float(os.environ.get("ATLAS_TRADE_GEOMETRY_EPSILON", "1e-12"))
SNAPSHOT_FLAT_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_FLAT_THRESHOLD_PCT", "0.05"))
SNAPSHOT_24H_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_24H_THRESHOLD", "0.5"))

# ============================================================
# CACHE & MEMORY SETTINGS
# ============================================================
BTC_REGIME_CACHE_MINUTES = int(os.environ.get("ATLAS_BTC_REGIME_CACHE_MINUTES", "30"))
SIGNAL_MEMORY_HOURS = int(os.environ.get("ATLAS_SIGNAL_MEMORY_HOURS", "12"))
MARKET_BREADTH_MIN_SAMPLES = int(os.environ.get("ATLAS_MARKET_BREADTH_MIN_SAMPLES", "8"))

# ============================================================
# DATABASE & LOGGING
# ============================================================
DB_FILE = os.environ.get("ATLAS_SQLITE_FILE", "atlas_v11.sqlite3")
CHANGELOG_FILE = os.environ.get("ATLAS_CHANGELOG", "changelog.txt")

# ============================================================
# REGIME & VOLATILITY SETTINGS (Stage 2)
# ============================================================
VOLATILITY_THRESHOLDS = {
    "LOW": float(os.environ.get("ATLAS_VOLATILITY_LOW", "2.0")),
    "NORMAL": float(os.environ.get("ATLAS_VOLATILITY_NORMAL", "5.0")),
    "HIGH": float(os.environ.get("ATLAS_VOLATILITY_HIGH", "8.0")),
}
REGIME_WEIGHTS = {
    "trend": float(os.environ.get("ATLAS_REGIME_WEIGHT_TREND", "0.4")),
    "volatility": float(os.environ.get("ATLAS_REGIME_WEIGHT_VOL", "0.2")),
    "derivatives": float(os.environ.get("ATLAS_REGIME_WEIGHT_DERIV", "0.2")),
    "breadth": float(os.environ.get("ATLAS_REGIME_WEIGHT_BREADTH", "0.2")),
}

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
    
    # اولویت با OVERLAP (همپوشانی) - ابتدا بررسی شود
    for name, session in MARKET_SESSIONS.items():
        if name == "OVERLAP" and session["open"] <= hour < session["close"]:
            return name, session["label"], session["multiplier"]
    
    # سپس سایر سشن‌ها
    for name, session in MARKET_SESSIONS.items():
        if name != "OVERLAP" and session["open"] <= hour < session["close"]:
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
# COINGECKO IDS MAPPING
# ============================================================
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "SOL": "solana",
    "TRX": "tron",
    "HYPE": "hype",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "XLM": "stellar",
    "SUI": "sui",
    "AVAX": "avalanche-2",
    "LTC": "litecoin",
    "SHIB": "shiba-inu",
    "HBAR": "hedera-hashgraph",
    "DOT": "polkadot",
    "BCH": "bitcoin-cash",
    "XMR": "monero",
    "NEAR": "near",
    "QNT": "quant-network",
    "GRT": "the-graph",
    "TAO": "tao",
    "ONDO": "ondo",
    "UNI": "uniswap",
    "ETHFI": "ethfi",
    "ATOM": "cosmos",
    "FIL": "filecoin",
    "AAVE": "aave",
    "MKR": "maker",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "INJ": "injective-protocol",
    "TIA": "celestia",
    "SEI": "sei-network",
    "PEPE": "pepe",
    "FET": "fet",
    "ICP": "internet-computer",
    "ETC": "ethereum-classic",
}

# ============================================================
# VOICE SUMMARY & OUTPUT
# ============================================================
# NOTE: an earlier generate_voice_summary (the "خلاصه صوتی کامل" version working
# off raw action/confidence fields) used to live here. It was silently shadowed by
# the later, intel-engine-aware generate_voice_summary defined further below and
# never ran. Removed to avoid confusion.

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
# ATLAS RADAR
# ============================================================

ATLAS_PRIORITY_TOP10 = [
    "BTC", "ETH", "BNB", "XRP", "SOL",
    "TRX", "HYPE", "DOGE", "ADA", "MATIC",
]

ATLAS_PERSONAL_ASSETS = [
    "BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "DOGE", "ADA", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR",
    "NEAR", "ONDO", "TAO",
]

ATLAS_STATIC = [
    "BTC", "ETH", "XRP", "SOL", "BNB", "TON", "ADA", "DOGE", "TRX", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR", "NEAR",
    "QNT", "GRT", "TAO", "ONDO", "UNI", "ETHFI", "ATOM", "FIL", "AAVE", "MKR",
    "APT", "ARB", "OP", "INJ", "TIA", "SEI", "PEPE", "FET", "ICP", "ETC",
    "HYPE", "MATIC",
]

ATLAS_METALS = ("GOLD", "SILVER", "COPPER")
METAL_YAHOO = {"GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F"}
METAL_TV = {"GOLD": "OANDA:XAUUSD", "SILVER": "OANDA:XAGUSD", "COPPER": "COMEX:HG1!"}

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
            notes text,
            signal_score real
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
        create table if not exists snapshot_price_history(
            id integer primary key autoincrement,
            symbol text not null,
            price real not null,
            captured_at text not null
        );
        create index if not exists idx_snapshot_history_symbol_time
            on snapshot_price_history(symbol, captured_at);
        create table if not exists backtest_gate_cache(
            id integer primary key check(id=1),
            timestamp text not null,
            passed integer not null,
            details text
        );
        create table if not exists ohlcv_cache(
            coin text not null,
            timeframe text not null,
            provider text not null,
            limit_n integer not null,
            last_closed_ts integer not null,
            cached_at text not null,
            rows_json text not null,
            primary key(coin, timeframe)
        );
        create index if not exists idx_ohlcv_cache_tf_ts
            on ohlcv_cache(timeframe, last_closed_ts);
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
        # Migration for DBs created before signal_score was added to
        # signal_outcomes (needed for calibration — see _win_probability_for_score).
        try:
            c.execute("alter table signal_outcomes add column signal_score real")
        except sqlite3.OperationalError:
            pass  # column already exists


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

    def insert_many(self, table, rows):
        """Batch insert using one Supabase REST request; preserves Supabase as primary."""
        rows = list(rows or [])
        if not rows or not self.enabled:
            return False
        try:
            url = f"{SUPABASE_URL}/rest/v1/{table}"
            req = urllib.request.Request(
                url,
                data=safe_json(rows).encode(),
                headers=self.headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            if table != "atlas_changelog":
                try:
                    with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write(
                            f"{now_utc().isoformat()} | SUPABASE | batch insert failed: "
                            f"{table}: {e}\n"
                        )
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

    def upsert(self, table, row, on_conflict):
        """درج یا به‌روزرسانی واقعی (نه فقط insert). بدون این، جدولی مثل
        snapshot_prices که قرار است فقط «آخرین قیمت» را نگه دارد، هر بار یک
        ردیف تازه اضافه می‌کند و در طول زمان به‌جای یک upsert تمیز، انبوهی از
        ردیف‌های تکراری تولید می‌شود که خواندن «قیمت قبلی» را غیرقابل‌اعتماد
        می‌کند. نیازمند یک UNIQUE constraint روی ستون(های) on_conflict در خودِ
        جدول Supabase (مثلاً: alter table snapshot_prices add constraint
        snapshot_prices_symbol_key unique (symbol);)."""
        if not self.enabled:
            return False
        try:
            q = urllib.parse.urlencode({"on_conflict": on_conflict})
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            headers = dict(self.headers)
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
            req = urllib.request.Request(
                url,
                data=safe_json(row).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            try:
                with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                    fh.write(f"{now_utc().isoformat()} | SUPABASE | upsert failed: {table}: {e}\n")
            except Exception:
                pass
            return False


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
# CCXT — FAULT-TOLERANT EXCHANGE LAYER
# ============================================================
# Provider failures are isolated. A missing CCXT adapter, unsupported venue,
# geo-block (403), empty market catalogue, or transient network error must
# never terminate the ATLAS analysis pipeline.
#
# Canonical CCXT IDs are used here. In particular, Gate.io is `gate`, not
# `gateio`. KCEX is optional because the installed CCXT build may not expose
# a KCEX adapter. Bybit may be unavailable from a GitHub runner because of
# regional/CloudFront restrictions; ATLAS records that state and continues.
# ============================================================

EXCHANGE_SPECS = (
    ("kcex", "kcex"),
    ("lbank", "lbank"),
    ("xt", "xt"),
    ("okx", "okx"),
    ("bybit", "bybit"),
    ("kucoin", "kucoin"),
    ("gateio", "gate"),
    ("bitget", "bitget"),
    ("mexc", "mexc"),
    ("kraken", "kraken"),
)

# Public-facing names retained for reports/backward compatibility.
EXCHANGE_IDS = tuple(name for name, _ccxt_id in EXCHANGE_SPECS)
EXCHANGE_CCXT_IDS = {name: ccxt_id for name, ccxt_id in EXCHANGE_SPECS}
EXCHANGE_STATUS = {}

def _classify_exchange_error(exc):
    msg = str(exc or "").lower()
    if "no attribute" in msg or "not supported" in msg or "unsupported" in msg:
        return "UNSUPPORTED"
    if "403" in msg or "forbidden" in msg or "cloudfront" in msg or "configured to block access" in msg:
        return "GEO_BLOCKED"
    if "429" in msg or "rate limit" in msg:
        return "RATE_LIMITED"
    if "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    return "ERROR"

def _record_exchange_status(name, status, error=None, ccxt_id=None, markets=0):
    EXCHANGE_STATUS[name] = {
        "name": name.upper(),
        "ccxt_id": ccxt_id or EXCHANGE_CCXT_IDS.get(name, name),
        "status": status,
        "markets": int(markets or 0),
        "error": str(error)[:500] if error else None,
        "updated_at": now_utc().isoformat(),
    }

def make_exchange(exchange_id):
    # Accept either our public alias (gateio) or a native CCXT id (gate).
    native_id = EXCHANGE_CCXT_IDS.get(exchange_id, exchange_id)
    cls = getattr(ccxt, native_id, None)
    if cls is None:
        raise RuntimeError(f"{exchange_id}: CCXT adapter '{native_id}' is not supported by installed ccxt")
    return cls({
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {"defaultType": "spot"},
    })

def init_exchanges():
    global EX, MARKETS
    EX = {}
    MARKETS = {}
    EXCHANGE_STATUS.clear()

    for public_id, native_id in EXCHANGE_SPECS:
        try:
            ex = make_exchange(public_id)
            markets = ex.load_markets()
            if not markets:
                raise RuntimeError(f"{public_id}: empty market catalog")

            EX[public_id] = ex
            MARKETS[public_id] = markets
            _record_exchange_status(public_id, "OK", ccxt_id=native_id, markets=len(markets))
            print(f"✅ {public_id} initialized with {len(markets)} markets [ccxt={native_id}]")

        except Exception as e:
            EX.pop(public_id, None)
            MARKETS.pop(public_id, None)
            kind = _classify_exchange_error(e)
            _record_exchange_status(public_id, kind, e, native_id)

            # These are expected provider-level failures and must be non-fatal.
            if kind == "UNSUPPORTED":
                print(f"⚠️ {public_id} skipped: CCXT adapter '{native_id}' unavailable")
            elif kind == "GEO_BLOCKED":
                print(f"⚠️ {public_id} unavailable: provider/geographic access restriction; continuing with other sources")
            else:
                print(f"⚠️ {public_id} unavailable ({kind}): {e}")

            try:
                append_changelog(
                    "EXCHANGE_INIT", None, None,
                    f"{public_id}: {kind}: {e}",
                    {"ccxt_id": native_id, "status": kind},
                )
            except Exception:
                pass

EX = {}
MARKETS = {}


# ============================================================
# ATLAS DATA EFFICIENCY LAYER
# In-run reuse only. It does not alter trading thresholds/decisions.
# ============================================================
ATLAS_TICKER_CACHE_TTL = float(os.environ.get("ATLAS_TICKER_CACHE_TTL", "45"))
ATLAS_PRICE_CONSENSUS_CACHE_TTL = float(os.environ.get("ATLAS_PRICE_CONSENSUS_CACHE_TTL", "45"))
ATLAS_GECKO_CACHE_TTL = float(os.environ.get("ATLAS_GECKO_CACHE_TTL", "300"))
ATLAS_USDT_TOMAN_CACHE_TTL = float(os.environ.get("ATLAS_USDT_TOMAN_CACHE_TTL", "300"))
ATLAS_BATCH_TICKERS_ENABLED = os.environ.get("ATLAS_BATCH_TICKERS_ENABLED", "1").strip() != "0"
ATLAS_BATCH_TICKERS_CHUNK = max(10, int(os.environ.get("ATLAS_BATCH_TICKERS_CHUNK", "30")))
ATLAS_PERSISTENT_BACKTEST_CACHE = os.environ.get("ATLAS_PERSISTENT_BACKTEST_CACHE", "1").strip() != "0"
ATLAS_ANALYSIS_WORKERS = max(1, min(4, int(os.environ.get("ATLAS_ANALYSIS_WORKERS", "2"))))
ATLAS_EXCHANGE_MAX_CONCURRENCY = max(1, min(3, int(os.environ.get("ATLAS_EXCHANGE_MAX_CONCURRENCY", "2"))))

_ATLAS_DATA_CACHE = {
    "ticker": {},
    "ohlcv": {},
    "price_consensus": {},
    "gecko_top": {},
    "usdt_toman": {},
}
_ATLAS_CACHE_STATS = {}
_ATLAS_OHLCV_PROVIDER_AFFINITY = {}
_ATLAS_OHLCV_PROVIDER_FAILURES = set()
_ATLAS_BATCH_TICKER_STATS = {"requests": 0, "symbols": 0, "failures": 0, "jit_batches": 0}
_ATLAS_BT_CACHE_STATS = {
    "sqlite_hit": 0,
    "supabase_hit": 0,
    "miss": 0,
    "fingerprint_mismatch": 0,
    "supabase_rows_seen": 0,
}
_ATLAS_EXCHANGE_SEMAPHORES = {}

def _atlas_cache_reset():
    for bucket in _ATLAS_DATA_CACHE.values():
        bucket.clear()
    _ATLAS_CACHE_STATS.clear()
    _ATLAS_OHLCV_PROVIDER_AFFINITY.clear()
    _ATLAS_OHLCV_PROVIDER_FAILURES.clear()
    _ATLAS_BATCH_TICKER_STATS.update({"requests": 0, "symbols": 0, "failures": 0, "jit_batches": 0})
    _ATLAS_BT_CACHE_STATS.update({
        "sqlite_hit": 0,
        "supabase_hit": 0,
        "miss": 0,
        "fingerprint_mismatch": 0,
        "supabase_rows_seen": 0,
    })
    _ATLAS_EXCHANGE_SEMAPHORES.clear()

def _atlas_cache_stat(name, hit):
    row = _ATLAS_CACHE_STATS.setdefault(name, {"hit": 0, "miss": 0})
    row["hit" if hit else "miss"] += 1

def _atlas_ttl_get(bucket, key, ttl):
    item = _ATLAS_DATA_CACHE[bucket].get(key)
    if not item:
        _atlas_cache_stat(bucket, False)
        return None
    ts, value = item
    if time.monotonic() - ts > ttl:
        _ATLAS_DATA_CACHE[bucket].pop(key, None)
        _atlas_cache_stat(bucket, False)
        return None
    _atlas_cache_stat(bucket, True)
    return value

def _atlas_ttl_set(bucket, key, value):
    _ATLAS_DATA_CACHE[bucket][key] = (time.monotonic(), value)

def _atlas_copy_rows(rows):
    # Prevent downstream accidental mutation of the shared OHLCV cache.
    return [list(x) if isinstance(x, (list, tuple)) else x for x in (rows or [])]

def ensure_exchanges(force=False):
    if EX and MARKETS and not force:
        return True
    init_exchanges()
    return bool(EX)

def exchange_health_report():
    """Return a serializable health snapshot for diagnostics/Telegram/CSV."""
    ok = [x for x in EXCHANGE_STATUS.values() if x.get("status") == "OK"]
    unavailable = [x for x in EXCHANGE_STATUS.values() if x.get("status") != "OK"]
    return {
        "total": len(EXCHANGE_STATUS),
        "healthy": len(ok),
        "unavailable": len(unavailable),
        "healthy_exchanges": [x["name"] for x in ok],
        "unavailable_exchanges": [
            {"name": x["name"], "status": x["status"], "error": x.get("error")}
            for x in unavailable
        ],
    }

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



def _atlas_exchange_guard(eid):
    key = str(eid).lower()
    sem = _ATLAS_EXCHANGE_SEMAPHORES.get(key)
    if sem is None:
        sem = _atlas_threading.BoundedSemaphore(ATLAS_EXCHANGE_MAX_CONCURRENCY)
        _ATLAS_EXCHANGE_SEMAPHORES[key] = sem
    return sem

def _atlas_store_prefetched_ticker(eid, coin, ticker):
    if not isinstance(ticker, dict):
        return False
    result = {
        "source": str(eid).upper(),
        "price": f(ticker.get("last") if ticker.get("last") is not None else ticker.get("close")),
        "change": f(ticker.get("percentage")),
        "quoteVolume": f(ticker.get("quoteVolume")),
    }
    if result["price"] is None:
        return False
    _atlas_ttl_set("ticker", (str(eid).lower(), str(coin).upper()), dict(result))
    return True

def _atlas_prefetch_tickers(universe):
    """Prefetch all available ticker data per exchange using CCXT fetch_tickers.

    Falls back safely to the existing per-symbol exchange_ticker path whenever
    an exchange does not support batch ticker retrieval.
    """
    if not ATLAS_BATCH_TICKERS_ENABLED:
        return {"requests": 0, "symbols": 0, "failures": 0}

    ensure_exchanges()
    universe = [str(x).upper() for x in (universe or []) if x]
    if not universe:
        return dict(_ATLAS_BATCH_TICKER_STATS)

    for eid, ex in list(EX.items()):
        has_map = getattr(ex, "has", None) or {}
        if isinstance(has_map, dict) and has_map.get("fetchTickers") is False:
            continue
        fn = getattr(ex, "fetch_tickers", None)
        if not callable(fn):
            continue

        pairs = []
        pair_to_coin = {}
        for coin in universe:
            sym = symbol_for(eid, coin)
            if not sym:
                continue
            pairs.append(sym)
            pair_to_coin[sym] = coin

        if not pairs:
            continue

        for start in range(0, len(pairs), ATLAS_BATCH_TICKERS_CHUNK):
            chunk = pairs[start:start + ATLAS_BATCH_TICKERS_CHUNK]
            try:
                _ATLAS_BATCH_TICKER_STATS["requests"] += 1
                try:
                    with _atlas_exchange_guard(eid):
                        payload = fn(chunk)
                except TypeError:
                    # Some CCXT adapters only accept fetch_tickers() without symbols.
                    with _atlas_exchange_guard(eid):
                        payload = fn()
                if not isinstance(payload, dict):
                    continue

                for pair, ticker in payload.items():
                    coin = pair_to_coin.get(pair)
                    if coin is None:
                        # Normalize common "BTC/USDT:USDT" style contracts.
                        base = str(pair).split("/")[0].upper()
                        if base in universe:
                            coin = base
                    if coin and _atlas_store_prefetched_ticker(eid, coin, ticker):
                        _ATLAS_BATCH_TICKER_STATS["symbols"] += 1
            except Exception as e:
                _ATLAS_BATCH_TICKER_STATS["failures"] += 1
                append_changelog(
                    "BATCH_TICKERS", None, None,
                    f"{eid}: batch prefetch failed; fallback to per-symbol ticker",
                    {"error": str(e)[:500], "symbols": len(chunk)},
                )
                break

    return dict(_ATLAS_BATCH_TICKER_STATS)

def exchange_ticker(eid, coin):
    key = (str(eid).lower(), str(coin).upper())
    cached = _atlas_ttl_get("ticker", key, ATLAS_TICKER_CACHE_TTL)
    if cached is not None:
        return dict(cached)

    ex = EX.get(eid)
    if ex is None:
        raise RuntimeError(f"{eid}: exchange unavailable")
    sym = symbol_for(eid, coin)
    if not sym:
        raise RuntimeError(f"{eid}: pair unavailable")
    with _atlas_exchange_guard(eid):
        t = ex.fetch_ticker(sym)
    result = {
        "source": eid.upper(),
        "price": f(t.get("last")),
        "change": f(t.get("percentage")),
        "quoteVolume": f(t.get("quoteVolume")),
    }
    _atlas_ttl_set("ticker", key, dict(result))
    return result

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
    with _atlas_exchange_guard(eid):
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


def _atlas_fixed_tf_ms(timeframe):
    return {
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }.get(str(timeframe))

def _atlas_expected_last_closed_open_ts(timeframe, now_ms=None):
    tf_ms = _atlas_fixed_tf_ms(timeframe)
    if not tf_ms:
        return None
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    current_open = (now_ms // tf_ms) * tf_ms
    return current_open - tf_ms

def _atlas_sqlite_ohlcv_get(coin, timeframe, limit):
    # Only fixed UTC-aligned timeframes use exact freshness validation.
    expected = _atlas_expected_last_closed_open_ts(timeframe)
    if expected is None:
        return None
    try:
        init_sqlite()
        with sqlite_conn() as c:
            row = c.execute(
                "select provider,limit_n,last_closed_ts,rows_json "
                "from ohlcv_cache where coin=? and timeframe=?",
                (str(coin).upper(), str(timeframe)),
            ).fetchone()
        if not row:
            return None
        provider, limit_n, last_closed_ts, rows_json = row
        if int(last_closed_ts) != int(expected) or int(limit_n) < int(limit):
            return None
        rows = json.loads(rows_json)
        if not isinstance(rows, list) or len(rows) < min(60, int(limit)):
            return None
        _atlas_cache_stat("ohlcv_sqlite", True)
        return _atlas_copy_rows(rows[-int(limit):]), str(provider)
    except Exception:
        return None

def _atlas_sqlite_ohlcv_set(coin, timeframe, limit, rows, provider):
    expected = _atlas_expected_last_closed_open_ts(timeframe)
    if expected is None or not rows:
        return
    try:
        last_ts = int(rows[-1][0])
        if last_ts != int(expected):
            return
        init_sqlite()
        with sqlite_conn() as c:
            c.execute(
                "insert or replace into ohlcv_cache"
                "(coin,timeframe,provider,limit_n,last_closed_ts,cached_at,rows_json)"
                " values(?,?,?,?,?,?,?)",
                (
                    str(coin).upper(), str(timeframe), str(provider),
                    int(limit), last_ts, now_utc().isoformat(),
                    json.dumps(rows, separators=(",", ":")),
                ),
            )
    except Exception:
        pass

def best_ohlcv(coin, timeframe, limit=250):
    ensure_exchanges()
    coin_key = str(coin).upper()
    tf_key = str(timeframe)
    cache_key = (coin_key, tf_key)

    cached = _ATLAS_DATA_CACHE["ohlcv"].get(cache_key)
    if cached is not None:
        cached_limit = int(cached["limit"])
        rows = cached["rows"]
        if cached_limit >= int(limit) and len(rows) >= min(60, int(limit)):
            _atlas_cache_stat("ohlcv", True)
            return _atlas_copy_rows(rows[-int(limit):]), cached["engine"]

    disk_cached = _atlas_sqlite_ohlcv_get(coin_key, tf_key, limit)
    if disk_cached is not None:
        rows, engine = disk_cached
        _ATLAS_DATA_CACHE["ohlcv"][cache_key] = {
            "limit": int(limit),
            "rows": _atlas_copy_rows(rows),
            "engine": engine,
        }
        return _atlas_copy_rows(rows), engine

    _atlas_cache_stat("ohlcv", False)
    _atlas_cache_stat("ohlcv_sqlite", False)
    errors = []

    # Prefer the provider that already succeeded for this exact timeframe,
    # then the provider that succeeded for this coin on another timeframe.
    preferred = []
    exact = _ATLAS_OHLCV_PROVIDER_AFFINITY.get((coin_key, tf_key))
    general = _ATLAS_OHLCV_PROVIDER_AFFINITY.get((coin_key, "*"))
    for eid in (exact, general):
        if eid and eid in EX and eid not in preferred:
            preferred.append(eid)
    ordered_ids = preferred + [eid for eid in EXCHANGE_IDS if eid not in preferred]

    for eid in ordered_ids:
        if eid not in EX:
            continue
        failure_key = (eid, coin_key, tf_key)
        if failure_key in _ATLAS_OHLCV_PROVIDER_FAILURES:
            continue
        try:
            rows = exchange_ohlcv(eid, coin, timeframe, limit)
            if rows:
                _ATLAS_OHLCV_PROVIDER_AFFINITY[(coin_key, tf_key)] = eid
                _ATLAS_OHLCV_PROVIDER_AFFINITY[(coin_key, "*")] = eid
                stored_rows = _atlas_copy_rows(rows)
                previous = _ATLAS_DATA_CACHE["ohlcv"].get(cache_key)
                if previous is None or int(limit) >= int(previous["limit"]):
                    _ATLAS_DATA_CACHE["ohlcv"][cache_key] = {
                        "limit": int(limit),
                        "rows": stored_rows,
                        "engine": eid.upper(),
                    }
                _atlas_sqlite_ohlcv_set(
                    coin_key, tf_key, int(limit), stored_rows, eid.upper()
                )
                return _atlas_copy_rows(stored_rows), eid.upper()
        except Exception as e:
            kind = _classify_exchange_error(e)
            errors.append(f"{eid}:{kind}")
            # Skip this exact failing provider/coin/timeframe for the remainder
            # of the run. No cross-timeframe blacklisting is done.
            _ATLAS_OHLCV_PROVIDER_FAILURES.add(failure_key)
            _record_exchange_status(
                eid, kind, e, EXCHANGE_CCXT_IDS.get(eid), len(MARKETS.get(eid, {}))
            )
            continue

    detail = ", ".join(errors[-8:])
    raise RuntimeError(
        f"{timeframe} DATA UNAVAILABLE: {coin} | providers tried={detail or 'none'}"
    )


# ============================================================
# DYNAMIC MARKET UNIVERSE
# ============================================================

def gecko_top(limit=40):
    cache_key = int(limit)
    cached = _atlas_ttl_get("gecko_top", cache_key, ATLAS_GECKO_CACHE_TTL)
    if cached is not None:
        return [dict(x) for x in cached]

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
                "price": f(x.get("current_price")),
            })
    _atlas_ttl_set("gecko_top", cache_key, [dict(x) for x in result])
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
    elif not NEWSAPI_KEY:
        # نه CryptoPanic نه NewsAPI تنظیم شده (چون هر دو الان پولی/نیازمند
        # ثبت‌نام هستند و بودجه‌ای برایش نیست) — از دو API کاملاً رایگان و
        # بدون کلید استفاده می‌کنیم تا این بخش گزارش کاملاً خالی نماند. این‌ها
        # سرویس‌های کوچک‌تر شخص‌ثالث‌اند، پس مثل بقیه‌ی منابع، شکستشان کاملاً
        # بی‌صدا مدیریت می‌شود و به بقیه‌ی گزارش آسیبی نمی‌رساند.

        # منبع رایگان ۱ (اولویت با این — ۷ منبع معتبر: CoinDesk/CoinTelegraph/Decrypt/...)
        d1 = safe_http_get("https://free-crypto-news.vercel.app/api/breaking", default={})
        for x in d1.get("articles", []) if isinstance(d1, dict) else []:
            items.append({
                "title": x.get("title", ""),
                "url": x.get("link", "") or x.get("url", ""),
                "source": x.get("source", "free-crypto-news"),
            })

        # منبع رایگان ۲ (تکمیلی/پشتیبان، منابع متفاوت)
        d2 = safe_http_get("https://cryptocurrency.cv/api/news?limit=20", default={})
        for x in d2.get("articles", []) if isinstance(d2, dict) else []:
            items.append({
                "title": x.get("title", ""),
                "url": x.get("link", ""),
                "source": x.get("source", "cryptocurrency.cv"),
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
# INTELLIGENCE BRIEFING: FED RATE / UNEMPLOYMENT / WHALES / FIGURES
# ============================================================

def fetch_fed_macro():
    """نرخ بهره فدرال رزرو (Fed Funds Rate) و نرخ بیکاری آمریکا، از FRED —
    منبع رسمی و رایگان بانک فدرال رزرو سنت‌لوئیس. نیازمند FRED_API_KEY
    (ثبت‌نام رایگان در fred.stlouisfed.org). این دو سری داده ماهانه به‌روز
    می‌شوند نه لحظه‌ای — این طبیعتِ خودِ داده است، نه نقص در کد."""
    out = {
        "fed_funds_rate": None, "fed_funds_date": None,
        "unemployment_rate": None, "unemployment_date": None,
    }
    if not FRED_API_KEY:
        return out
    series_map = {
        "fed_funds_rate": ("FEDFUNDS", "fed_funds_date"),
        "unemployment_rate": ("UNRATE", "unemployment_date"),
    }
    for value_key, (series_id, date_key) in series_map.items():
        try:
            url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode({
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "1",
            })
            d = safe_http_get(url, default={})
            obs = (d or {}).get("observations") or []
            if obs:
                val = f(obs[0].get("value"))
                if val is not None:
                    out[value_key] = val
                    out[date_key] = obs[0].get("date")
        except Exception as e:
            append_changelog("FRED", None, None, f"{series_id}: {e}")
    return out


def fetch_whale_activity():
    """تراکنش‌های بزرگ (نهنگ) اخیر. اگر WHALE_ALERT_API_KEY تنظیم شده باشد از
    Whale Alert رسمی استفاده می‌شود (دقیق‌تر و کامل‌تر)؛ در غیر این صورت
    به‌طور پیش‌فرض از یک API رایگان و بدون کلید (cryptocurrency.cv) استفاده
    می‌کند تا این بخش گزارش، صرفاً به‌خاطر نداشتن بودجه، کاملاً خالی نماند."""
    if WHALE_ALERT_API_KEY:
        return _fetch_whale_activity_paid()
    return _fetch_whale_activity_free()


def _fetch_whale_activity_paid():
    """منبع پولی/دقیق: whale-alert.io"""
    lookback_seconds = int(os.environ.get("ATLAS_WHALE_LOOKBACK_SECONDS", str(4 * 3600 + 1800)))
    start_ts = int(time.time()) - lookback_seconds
    try:
        url = "https://api.whale-alert.io/v1/transactions?" + urllib.parse.urlencode({
            "api_key": WHALE_ALERT_API_KEY,
            "min_value": str(int(WHALE_ALERT_MIN_USD)),
            "start": str(start_ts),
            "limit": "20",
        })
        d = safe_http_get(url, default={})
        txs = (d or {}).get("transactions") or []
        items = []
        for tx in txs:
            frm = tx.get("from") or {}
            to = tx.get("to") or {}
            items.append({
                "symbol": str(tx.get("symbol", "")).upper(),
                "amount_usd": f(tx.get("amount_usd")) or 0.0,
                "from_type": frm.get("owner_type", "unknown"),
                "to_type": to.get("owner_type", "unknown"),
                "from_owner": frm.get("owner") or "",
                "to_owner": to.get("owner") or "",
            })
        items.sort(key=lambda x: x["amount_usd"], reverse=True)
        return items[:10]
    except Exception as e:
        append_changelog("WHALE_ALERT", None, None, str(e))
        return []


def _fetch_whale_activity_free():
    """منبع رایگان و بدون کلید: cryptocurrency.cv/api/whale-alerts.
    شخص‌ثالث کوچک‌تر است؛ اگر در دسترس نبود، فقط لیست خالی برمی‌گردد و بقیه
    گزارش بدون مشکل ادامه پیدا می‌کند."""
    try:
        d = safe_http_get(
            f"https://cryptocurrency.cv/api/whale-alerts?min_value={int(WHALE_ALERT_MIN_USD)}&limit=15",
            default={},
        )
        raw = (d or {}).get("alerts") or (d or {}).get("transactions") or (d or {}).get("data") or []
        items = []
        for tx in raw if isinstance(raw, list) else []:
            amount_usd = f(tx.get("amount_usd") or tx.get("value_usd") or tx.get("usd_value"))
            items.append({
                "symbol": str(tx.get("symbol") or tx.get("asset") or tx.get("coin") or "").upper(),
                "amount_usd": amount_usd or 0.0,
                "from_type": tx.get("from_type") or (tx.get("from") or {}).get("owner_type", "unknown"),
                "to_type": tx.get("to_type") or (tx.get("to") or {}).get("owner_type", "unknown"),
                "from_owner": tx.get("from_owner") or "",
                "to_owner": tx.get("to_owner") or "",
            })
        items.sort(key=lambda x: x["amount_usd"], reverse=True)
        return items[:10]
    except Exception as e:
        append_changelog("WHALE_FREE", None, None, str(e))
        return []


def translate_to_fa(text, timeout=8):
    """ترجمه سریع انگلیسی→فارسی برای عنوان اخبار، با استفاده از همان Endpoint
    غیررسمی و رایگان Google Translate که gTTS (طبق کامنت خودِ requirements.txt،
    به‌عنوان fallback صدا) از قبل به آن متکی است. اگر ترجمه به هر دلیلی شکست
    بخورد، متن اصلی انگلیسی برگردانده می‌شود — گزارش هرگز به‌خاطر شکست ترجمه
    از کار نمی‌افتد."""
    if not text:
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode({
            "client": "gtx", "sl": "en", "tl": "fa", "dt": "t", "q": text,
        })
        d = safe_http_get(url, timeout=timeout, default=None)
        if d and isinstance(d, list) and d[0]:
            translated = "".join(seg[0] for seg in d[0] if seg and seg[0])
            if translated:
                return translated
    except Exception as e:
        append_changelog("TRANSLATE", None, None, str(e))
    return text


def fetch_influential_figures_news(existing_items=None):
    """اظهارات چهره‌های تأثیرگذار (ترامپ / رئیس فدرال رزرو / بزوس) که می‌تواند
    بازار کریپتو را حرکت دهد — از خبرگزاری‌های معتبر، نه اسکرپ مستقیم
    توییتر/X یا Truth Social (دلیل در کامنت بالای تعریف INFLUENTIAL_FIGURES).
    عنوان هر خبر به فارسی هم ترجمه می‌شود (کلید 'title_fa')."""

    def keyword_hit(title):
        t = (title or "").lower()
        for person, kws in INFLUENTIAL_FIGURES.items():
            if any(kw in t for kw in kws):
                return person
        return None

    seen_urls = set()
    matched = []

    for item in (existing_items or []):
        person = keyword_hit(item.get("title", ""))
        url = item.get("url")
        if person and url and url not in seen_urls:
            seen_urls.add(url)
            matched.append({**item, "figure": person})

    if NEWSAPI_KEY:
        try:
            url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode({
                "q": '(Trump OR Powell OR "Jeff Bezos") AND (crypto OR bitcoin OR tariff OR "interest rate" OR Fed)',
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
                "apiKey": NEWSAPI_KEY,
            })
            d = safe_http_get(url, default={})
            for x in d.get("articles", []) if isinstance(d, dict) else []:
                title = x.get("title", "")
                desc = x.get("description", "") or ""
                link = x.get("url", "")
                # NewsAPI's q= matches anywhere in title/description/content, نه فقط
                # عنوان — پس عنوان به‌تنهایی ممکن است ترامپ/پاول/بزوس را نداشته باشد
                # ولی مقاله واقعاً درباره‌شان نباشد (مثلاً فقط یک اشاره‌ی جانبی در بدنه).
                # قبلاً چنین مواردی با برچسب مبهم «سایر چهره‌های تأثیرگذار» درج می‌شدند
                # که باعث می‌شد اخبار کاملاً بی‌ربط (بدهی آمریکا، حمله ایران، و…) در این
                # بخش ظاهر شوند. حالا اگر عنوان+توضیح هیچ‌کدام از سه چهره را نام نبرند،
                # مقاله کاملاً کنار گذاشته می‌شود، نه این‌که با برچسب مبهم درج شود.
                person = keyword_hit(title) or keyword_hit(desc)
                if person and link and link not in seen_urls:
                    seen_urls.add(link)
                    matched.append({
                        "title": title,
                        "url": link,
                        "source": x.get("source", {}).get("name", "NewsAPI"),
                        "figure": person,
                    })
        except Exception as e:
            append_changelog("INFLUENTIAL_NEWS", None, None, str(e))
    elif not matched:
        # نه NEWSAPI_KEY تنظیم شده نه چیزی در آیتم‌های موجود پیدا شد — دو
        # جست‌وجوی رایگان و بدون کلید هم امتحان می‌کنیم تا این بخش کاملاً
        # خالی نماند.
        for search_url, source_label in (
            ("https://free-crypto-news.vercel.app/api/search?q=trump", "free-crypto-news"),
            ("https://free-crypto-news.vercel.app/api/search?q=powell", "free-crypto-news"),
            ("https://free-crypto-news.vercel.app/api/search?q=bezos", "free-crypto-news"),
            ("https://cryptocurrency.cv/api/search?q=trump%20OR%20powell%20OR%20bezos&limit=15", "cryptocurrency.cv"),
        ):
            try:
                d = safe_http_get(search_url, default={})
                for x in d.get("articles", []) if isinstance(d, dict) else []:
                    title = x.get("title", "")
                    link = x.get("link", "") or x.get("url", "")
                    person = keyword_hit(title)
                    if person and link and link not in seen_urls:
                        seen_urls.add(link)
                        matched.append({
                            "title": title,
                            "url": link,
                            "source": x.get("source", source_label),
                            "figure": person,
                        })
            except Exception as e:
                append_changelog("INFLUENTIAL_NEWS_FREE", None, None, f"{search_url}: {e}")

    matched = matched[:8]
    # ترجمه‌ی عنوان‌ها به فارسی (فقط همینجا، تعداد کم، تا هزینه/تأخیر شبکه کنترل‌شده بماند)
    for it in matched:
        it["title_fa"] = translate_to_fa(it.get("title", ""))

    return matched


def build_intelligence_briefing(macro, fed_macro, whale_items, figure_items):
    """بلوک فشرده‌ی فارسی از زمینه‌ی کلان/نهنگ/چهره‌های تأثیرگذار برای درج در
    هم گزارش متنی و هم خلاصه‌ی صوتی. اگر هیچ کلید API تنظیم نشده باشد، خروجی
    کاملاً خالی است (نه خطا، نه placeholder گمراه‌کننده)."""
    text_lines = []
    voice_bits = []

    fed_rate = (fed_macro or {}).get("fed_funds_rate")
    unemployment = (fed_macro or {}).get("unemployment_rate")
    if fed_rate is not None or unemployment is not None:
        text_lines.append("💵 کلان آمریکا:")
        if fed_rate is not None:
            text_lines.append(f"   نرخ بهره فدرال رزرو: {fed_rate:.2f}% (تاریخ: {fed_macro.get('fed_funds_date','?')})")
            voice_bits.append(f"نرخ بهره فدرال رزرو {fed_rate:.2f} درصد است.")
        if unemployment is not None:
            text_lines.append(f"   نرخ بیکاری آمریکا: {unemployment:.1f}% (تاریخ: {fed_macro.get('unemployment_date','?')})")
            voice_bits.append(f"نرخ بیکاری آمریکا {unemployment:.1f} درصد است.")

    if whale_items:
        text_lines.append("")
        text_lines.append(f"🐋 تحرکات نهنگ ({len(whale_items)} تراکنش بزرگ اخیر، آستانه ${WHALE_ALERT_MIN_USD:,.0f}):")
        for w in whale_items[:5]:
            text_lines.append(
                f"   {w.get('symbol','?')}: ${w.get('amount_usd',0):,.0f} — از {w.get('from_type','?')} به {w.get('to_type','?')}"
            )
        top = whale_items[0]
        voice_bits.append(
            f"بزرگترین تراکنش نهنگ اخیر، جابجایی {top.get('symbol','?')} به ارزش تقریبی "
            f"{top.get('amount_usd',0):,.0f} دلار بوده است."
        )

    if figure_items:
        text_lines.append("")
        text_lines.append("🗣️ اظهارات مؤثر بر بازار:")
        for it in figure_items[:5]:
            title_fa = it.get("title_fa") or it.get("title")
            text_lines.append(f"   [{it.get('figure')}] {title_fa} ({it.get('source')})")
        voice_bits.append(
            f"همچنین {figure_items[0].get('figure')} اظهاراتی مطرح کرده که ممکن است روی بازار اثر بگذارد: "
            f"{figure_items[0].get('title_fa') or figure_items[0].get('title')}."
        )

    if not text_lines:
        return {"text": "", "voice_text": "", "has_content": False}

    header = ["", "━━━━━━━━━━━━━━━━━━", "🌍 زمینه کلان و اخبار مؤثر (فراتر از تحلیل تکنیکال)"]
    return {
        "text": "\n".join(header + text_lines),
        "voice_text": " ".join(voice_bits),
        "has_content": True,
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
    cache_key = str(coin).upper()
    cached = _atlas_ttl_get(
        "price_consensus", cache_key, ATLAS_PRICE_CONSENSUS_CACHE_TTL
    )
    if cached is not None:
        med, sources, quality, sp, errors = cached
        return med, [dict(x) for x in sources], quality, sp, list(errors)

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
        rows = gecko_top(50)
        lookup_symbol = data_symbol(coin)
        x = next(
            (z for z in rows if (z.get("symbol") or "").upper() == lookup_symbol),
            None,
        )
        if x:
            p = f(x.get("price"))
            if p is not None:
                vals.append(p)
                sources.append({
                    "source": "CoinGecko",
                    "price": p,
                    "id": x.get("id"),
                })
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
    result = (med, [dict(x) for x in sources], quality, sp, list(errors))
    _atlas_ttl_set("price_consensus", cache_key, result)
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
        entry = price if price >= res else res * 1.002
        sl = min(sup * 0.995, entry - 1.5 * atr_v)
        risk = entry - sl
        if risk <= 0:
            return None

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
# ===== DATA QUALITY, SIGNAL LIFECYCLE, NO-TRADE ENGINES (Stage 1) =====
# ============================================================

def calculate_data_quality(result):
    """
    Data Quality Engine - امتیاز کیفیت داده‌ها (0-100)
    معیارها: تعداد منابع، spread، در دسترس بودن داده‌ها، تازگی، کیفیت S/R
    """
    score = 0
    
    # 1. تعداد منابع قیمت (30 امتیاز)
    sources = len(result.get("sources", []))
    if sources >= 5:
        score += 30
    elif sources >= 3:
        score += 20
    elif sources >= 1:
        score += 10
    
    # 2. Spread قیمت (20 امتیاز)
    spread = result.get("spread", 100)
    if spread is not None:
        if spread <= 0.5:
            score += 20
        elif spread <= 1.5:
            score += 15
        elif spread <= 3.0:
            score += 10
        else:
            score += 5
    
    # 3. در دسترس بودن داده‌های کلیدی (30 امتیاز)
    key_fields = ["price", "rsi", "macd", "volume_ratio", "atr_pct", "support", "resistance"]
    available = sum(1 for f in key_fields if result.get(f) is not None)
    score += (available / len(key_fields)) * 30
    
    # 4. تازگی داده (10 امتیاز)
    errors = result.get("price_source_errors", [])
    if len(errors) == 0:
        score += 10
    elif len(errors) <= 2:
        score += 5
    
    # 5. کیفیت S/R (10 امتیاز)
    sr_conf = result.get("sr_confidence", "LOW")
    if sr_conf == "HIGH":
        score += 10
    elif sr_conf == "MEDIUM":
        score += 5
    
    return min(100, int(score))


def generate_signal_id(coin, timeframe="4H"):
    """تولید شناسه یکتا برای هر سیگنال"""
    timestamp = now_tehran().strftime("%Y%m%d-%H%M")
    random_part = hashlib.md5(f"{coin}{timeframe}{time.time()}{random.random()}".encode()).hexdigest()[:4].upper()
    return f"{coin}-{timeframe}-{timestamp}-{random_part}"


def build_no_trade_reasons(result):
    """
    No-Trade Engine - لیست دقیق دلایل عدم ورود به معامله
    """
    reasons = []
    
    # RR پایین
    rr = result.get("rr")
    if rr is not None and rr < MIN_EXECUTABLE_RR:
        reasons.append(f"R/R too low ({rr:.2f} < {MIN_EXECUTABLE_RR:.1f})")
    
    # BTC regime مخالف
    regime = result.get("btc_regime", {}).get("regime")
    direction = result.get("direction")
    if direction == "LONG" and regime == "RISK_OFF":
        reasons.append("BTC regime is RISK_OFF (bearish)")
    elif direction == "SHORT" and regime == "RISK_ON":
        reasons.append("BTC regime is RISK_ON (bullish)")
    
    # نقدینگی کم
    liquidity = result.get("liquidity_score", 0)
    if liquidity < 45:
        reasons.append(f"Low liquidity ({liquidity:.0f})")
    
    # کیفیت داده پایین
    dq = result.get("data_quality", 100)
    if dq < 60:
        reasons.append(f"Poor data quality ({dq:.0f})")
    
    # مقاومت/حمایت نزدیک
    entry = result.get("entry")
    if direction == "LONG":
        resistance = result.get("resistance")
        if resistance and entry and (resistance - entry) / entry < 0.015:
            reasons.append(f"Resistance too close ({fmt(resistance)})")
    elif direction == "SHORT":
        support = result.get("support")
        if support and entry and (entry - support) / entry < 0.015:
            reasons.append(f"Support too close ({fmt(support)})")
    
    # اشباع RSI
    rsi = result.get("rsi")
    if direction == "LONG" and rsi and rsi > 70:
        reasons.append(f"RSI overbought ({rsi:.1f})")
    elif direction == "SHORT" and rsi and rsi < 30:
        reasons.append(f"RSI oversold ({rsi:.1f})")
    
    # نوسان بالا
    atr = result.get("atr_pct")
    if atr and atr > 8:
        reasons.append(f"Extreme volatility ({atr:.1f}%)")
    
    # تکرار سیگنال
    if result.get("repeat_signal"):
        reasons.append("Signal already active")
    
    # تضاد در سیگنال
    contradictions = result.get("contradictions", [])
    if contradictions:
        reasons.append(f"Contradictions: {', '.join(contradictions[:2])}")
    
    # عدم تأیید کندل
    trigger_state = (result.get("candle_trigger") or {}).get("state")
    if direction in ("LONG", "SHORT") and trigger_state not in ("BREAKOUT_CLOSED", "BREAKDOWN_CLOSED", "SUPPORT_RECLAIM", "RESISTANCE_REJECT"):
        reasons.append("Candle confirmation missing")
    
    # گیت بلاک
    if result.get("gate") == "BLOCK":
        reasons.append(f"Gate blocked: {result.get('gate_reason', 'Unknown reason')}")
    
    return reasons


# ============================================================
# ===== REGIME MATRIX & VOLATILITY ENGINE (Stage 2) =====
# ============================================================

def detect_trend_state(btc_h4, btc_d1, breadth_score, h4_trend, d1_trend):
    """تشخیص وضعیت روند با جزئیات بیشتر (6 حالت)"""
    if btc_h4 == "BULLISH" and btc_d1 == "BULLISH" and breadth_score > 65:
        return "TRENDING_BULL"
    if btc_h4 == "BEARISH" and btc_d1 == "BEARISH" and breadth_score < 35:
        return "TRENDING_BEAR"
    if btc_h4 == "MIXED" or breadth_score < 45:
        return "RANGE"
    if btc_h4 == "BULLISH" and breadth_score < 45:
        return "ACCUMULATION"
    if btc_h4 == "BEARISH" and breadth_score > 55:
        return "DISTRIBUTION"
    return "NEUTRAL"

def detect_volatility_state(atr_pct):
    """تشخیص سطح نوسان بر اساس ATR"""
    if atr_pct is None:
        return "UNKNOWN"
    if atr_pct < VOLATILITY_THRESHOLDS["LOW"]:
        return "LOW"
    if atr_pct < VOLATILITY_THRESHOLDS["NORMAL"]:
        return "NORMAL"
    if atr_pct < VOLATILITY_THRESHOLDS["HIGH"]:
        return "HIGH"
    return "EXTREME"

def detect_derivatives_state(funding_rate, open_interest_change=None):
    """تشخیص وضعیت مشتقات (شلوغی/خنثی)"""
    if funding_rate is None:
        return "UNAVAILABLE"
    if funding_rate > 0.01:
        return "LONG_CROWDED"
    if funding_rate < -0.01:
        return "SHORT_CROWDED"
    return "NEUTRAL"

def detect_liquidation_cascade(price_change, volume_ratio, oi_change, liquidation_volume):
    """تشخیص آبشار لیکوئید بر اساس داده‌های CoinGlass"""
    if None in (price_change, volume_ratio, oi_change, liquidation_volume):
        return False, "NO_DATA"
    
    # نشانه‌های آبشار لیکوئید:
    # - قیمت افت شدید (بیش از ۳٪)
    # - حجم معاملات جهش (بیش از ۲ برابر میانگین)
    # - Open Interest کاهش (بیش از ۵٪)
    # - حجم لیکوئید بالا (بیش از ۱۰۰ میلیون دلار)
    is_cascade = (
        price_change < -3.0 and
        volume_ratio > 2.0 and
        oi_change < -5.0 and
        liquidation_volume > 100_000_000
    )
    if is_cascade:
        return True, "LONG_CASCADE"
    return False, "NONE"

def calculate_regime_score(trend_state, volatility_state, derivatives_state):
    """محاسبه امتیاز کلی رژیم (۰-۱۰۰)"""
    trend_scores = {
        "TRENDING_BULL": 90, "ACCUMULATION": 70, "NEUTRAL": 50,
        "RANGE": 50, "DISTRIBUTION": 30, "TRENDING_BEAR": 10
    }
    vol_scores = {"LOW": 80, "NORMAL": 60, "HIGH": 40, "EXTREME": 20, "UNKNOWN": 50}
    deriv_scores = {"NEUTRAL": 70, "LONG_CROWDED": 40, "SHORT_CROWDED": 40, "UNAVAILABLE": 50}
    
    score = 0
    score += trend_scores.get(trend_state, 50) * REGIME_WEIGHTS["trend"]
    score += vol_scores.get(volatility_state, 50) * REGIME_WEIGHTS["volatility"]
    score += deriv_scores.get(derivatives_state, 50) * REGIME_WEIGHTS["derivatives"]
    
    return int(round(score))


def RegimeEngine(h4_trend, d1_trend, w1_trend, atr_pct, volume_ratio,
                  btc_h4="UNKNOWN", btc_d1="UNKNOWN", breadth_score=50, funding_rate=None):
    """
    Single canonical regime computation, replacing the two separate, colliding
    implementations that used to exist (Stage-2's calculate_regime_score() path
    and the intel engine's _i_regime()). Both wrote to the same result fields
    (regime_trend / regime_volatility) with different values computed from
    different inputs — whichever ran last silently won, so the regime shown in
    a report was not reliably the one that drove the decision.

    This does not throw away either engine's logic — it keeps both signals,
    under distinct keys, in one dict:
      - macro/derivatives context (BTC regime + market breadth + funding) →
        the questions "what kind of market is this, generally" and "is this
        specific asset's own MTF trend confirmed" are different questions and
        both stay, just no longer under the same field name.

    Returns a dict matching the schema proposed for ATLAS's next version:
        {
          "regime": "TRENDING_BULL",      # macro market regime (6-state)
          "score": 78,                     # 0-100 confidence in that regime read
          "trend": "BULLISH",              # this asset's own MTF trend alignment
          "volatility": "NORMAL",          # shared volatility bucket (ATR-based)
          "participation": "HIGH",         # volume-ratio based
          "derivatives": "NEUTRAL",        # funding-rate based crowding state
          "market_bias": "LONG",           # simplified directional lean
        }
    """
    trend_state = detect_trend_state(btc_h4, btc_d1, breadth_score, h4_trend, d1_trend)
    volatility_state = detect_volatility_state(atr_pct)
    derivatives_state = detect_derivatives_state(funding_rate)
    score = calculate_regime_score(trend_state, volatility_state, derivatives_state)

    h4d = _i_dir(h4_trend); d1d = _i_dir(d1_trend); w1d = _i_dir(w1_trend)
    if h4d == d1d == "LONG" and w1d in ("LONG", "NEUTRAL"):
        asset_trend = "BULLISH"
    elif h4d == d1d == "SHORT" and w1d in ("SHORT", "NEUTRAL"):
        asset_trend = "BEARISH"
    else:
        asset_trend = "NEUTRAL"

    vr = _i_num(volume_ratio, 0)
    if vr >= 1.5:
        participation = "HIGH"
    elif vr >= 1.0:
        participation = "NORMAL"
    else:
        participation = "LOW"

    if trend_state in ("TRENDING_BULL", "ACCUMULATION") and asset_trend != "BEARISH":
        market_bias = "LONG"
    elif trend_state in ("TRENDING_BEAR", "DISTRIBUTION") and asset_trend != "BULLISH":
        market_bias = "SHORT"
    else:
        market_bias = "NEUTRAL"

    return {
        "regime": trend_state, "score": score, "trend": asset_trend,
        "volatility": volatility_state, "participation": participation,
        "derivatives": derivatives_state, "market_bias": market_bias,
    }


# ============================================================
# ===== SIGNAL SUMMARY ENGINE (Stage 3) =====
# ============================================================

def generate_signal_summary(results):
    """تولید خلاصه هوشمند از سیگنال‌ها برای انتهای گزارش"""
    if not results:
        return "⚠️ داده‌ای برای تحلیل سیگنال وجود ندارد."
    
    lines = []
    
    # 1. آمار کلی
    total = len(results)
    actionable = [r for r in results if r.get("decision_state") in ("BUY CONFIRMATION", "SELL CONFIRMATION") and not r.get("repeat_signal")]
    watch = [r for r in results if r.get("decision_state") in ("BULLISH WATCH", "BEARISH WATCH")]
    no_trade = [r for r in results if r.get("decision_state") == "NO TRADE" or r.get("gate") == "BLOCK"]
    
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("📊 خلاصه سیگنال‌های هوشمند")
    lines.append("───────────────────")
    lines.append(f"🔍 کل دارایی‌های تحلیل‌شده: {total}")
    lines.append(f"🟢 سیگنال اجرایی: {len(actionable)}")
    lines.append(f"🟡 در انتظار تأیید: {len(watch)}")
    lines.append(f"⚪ بدون سیگنال: {len(no_trade)}")
    
    # 2. بهترین فرصت‌ها (حداکثر ۳ مورد)
    if actionable:
        lines.append("")
        lines.append("🏆 بهترین فرصت‌های معاملاتی:")
        top = sorted(actionable, key=lambda r: (r.get("confidence", 0), r.get("rr") or 0), reverse=True)[:3]
        for i, r in enumerate(top, 1):
            direction = "LONG" if r.get("direction") == "LONG" else "SHORT"
            emoji = "🟢" if direction == "LONG" else "🔴"
            rr = r.get("rr", 0)
            conf = r.get("confidence", 0)
            lines.append(f"  {i}. {emoji} {r['coin']} — {direction} — اطمینان {conf}% — R/R {rr:.2f}")
    
    # 3. هشدارهای مهم
    warnings = []
    for r in results:
        if r.get("warning"):
            warnings.append(f"⚠️ {r['coin']}: {r['warning']}")
        if r.get("regime", {}).get("cascade_detected"):
            warnings.append(f"🔥 {r['coin']}: آبشار لیکوئید شناسایی شد!")
        if r.get("regime_volatility") == "EXTREME":
            warnings.append(f"📈 {r['coin']}: نوسان فوق‌العاده بالا")
        if r.get("data_quality", 100) < 50:
            warnings.append(f"🔴 {r['coin']}: کیفیت داده پایین ({r.get('data_quality')}%)")
    
    if warnings:
        lines.append("")
        lines.append("⚠️ هشدارهای مهم:")
        for w in warnings[:5]:
            lines.append(f"  {w}")
        if len(warnings) > 5:
            lines.append(f"  ... و {len(warnings)-5} هشدار دیگر")
    
    # 4. وضعیت کلی بازار (بر اساس رژیم)
    regime_scores = [r.get("regime_score", 50) for r in results if r.get("regime_score") is not None]
    if regime_scores:
        avg_regime = sum(regime_scores) / len(regime_scores)
        if avg_regime >= 70:
            market_state = "🟢 بازار صعودی"
        elif avg_regime >= 45:
            market_state = "🟡 بازار خنثی"
        else:
            market_state = "🔴 بازار نزولی"
        lines.append("")
        lines.append(f"📈 وضعیت کلی بازار: {market_state} (میانگین امتیاز رژیم: {avg_regime:.0f}/100)")
    
    # 5. پیشنهاد نهایی بر اساس تحلیل
    if actionable:
        best = actionable[0]
        lines.append("")
        if best.get("direction") == "LONG":
            lines.append(f"💡 پیشنهاد: تمرکز روی خرید {best['coin']} با حد ضرر {fmt(best.get('sl'))} و هدف {fmt(best.get('tp2'))}")
        else:
            lines.append(f"💡 پیشنهاد: تمرکز روی فروش {best['coin']} با حد ضرر {fmt(best.get('sl'))} و هدف {fmt(best.get('tp2'))}")
    else:
        lines.append("")
        lines.append("💡 پیشنهاد: فعلاً در جایگاه ناظر باشید. هیچ سیگنال اجرایی با کیفیت کافی یافت نشد.")
    
    lines.append("━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def generate_top_opportunities(results, limit=5):
    """استخراج بهترین فرصت‌های معاملاتی با اولویت‌بندی"""
    candidates = []
    for r in results:
        if r.get("decision_state") in ("BUY CONFIRMATION", "SELL CONFIRMATION") and not r.get("repeat_signal"):
            # امتیاز ترکیبی: اطمینان + R/R + کیفیت داده + امتیاز رژیم
            score = (
                (r.get("confidence", 0) * 0.4) +
                (min(r.get("rr", 0), 5.0) * 15) +
                (r.get("data_quality", 0) * 0.1) +
                (r.get("regime_score", 50) * 0.05)
            )
            candidates.append((score, r))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in candidates[:limit]]


def generate_alert_summary(results):
    """جمع‌آوری هشدارهای مهم از نتایج"""
    alerts = []
    for r in results:
        if r.get("warning"):
            alerts.append({"type": "warning", "coin": r["coin"], "message": r["warning"]})
        if r.get("regime", {}).get("cascade_detected"):
            alerts.append({"type": "cascade", "coin": r["coin"], "message": "آبشار لیکوئید"})
        if r.get("regime_volatility") == "EXTREME":
            alerts.append({"type": "volatility", "coin": r["coin"], "message": "نوسان فوق‌العاده بالا"})
        if r.get("data_quality", 100) < 50:
            alerts.append({"type": "data", "coin": r["coin"], "message": f"کیفیت داده پایین ({r.get('data_quality')}%)"})
    return alerts


# ============================================================
# ANALYZE COIN (modified with Stage 1 + Stage 2)
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

    session, session_label, session_multiplier = get_current_session()
    
    confidence_raw = confidence
    confidence = confidence * session_multiplier
    
    if session in ("ASIA", "CLOSED"):
        warning = warning or f"سشن {session_label} — نقدینگی کمتر، احتیاط بیشتر"
    
    if session == "OVERLAP":
        if "همپوشانی سشن — نقدینگی بالا" not in str(reason_parts):
            reason_parts.append("همپوشانی سشن — نقدینگی بالا")

    # ===== STAGE 1: Data Quality =====
    data_quality = calculate_data_quality({
        "sources": sources,
        "spread": spread_pct,
        "price": price,
        "rsi": tf4.get("rsi"),
        "macd": tf4.get("macd"),
        "volume_ratio": vol_ratio,
        "atr_pct": atrp,
        "support": effective_levels.get("support") if effective_levels else None,
        "resistance": effective_levels.get("resistance") if effective_levels else None,
        "sr_confidence": effective_levels.get("confidence", "LOW") if effective_levels else "LOW",
        "price_source_errors": errors,
    })
    
    # ===== STAGE 1: Signal ID =====
    signal_id = generate_signal_id(coin, "4H")
    
    # ===== STAGE 1: Apply Data Quality cap =====
    if data_quality < 70:
        confidence = min(confidence, 65)
        if data_quality < 50:
            confidence = min(confidence, 40)
            gate = "BLOCK"
            gate_reason = "Data quality too low: " + gate_reason

    # ===== STAGE 2: Regime Matrix (single canonical RegimeEngine) =====
    btc_regime = btc_market_regime()
    breadth_score = market_breadth([]).get("score", 50)  # Will be updated later
    
    # دریافت داده‌های مشتقات
    funding_rate = source_validation.get("coinglass", {}).get("funding_rate")
    oi = source_validation.get("coinglass", {}).get("open_interest")

    regime_engine_out = RegimeEngine(
        h4, d1, w1, atrp, vol_ratio,
        btc_h4=btc_regime.get("h4", "UNKNOWN"), btc_d1=btc_regime.get("d1", "UNKNOWN"),
        breadth_score=breadth_score, funding_rate=funding_rate,
    )
    trend_state = regime_engine_out["regime"]
    volatility_state = regime_engine_out["volatility"]
    derivatives_state = regime_engine_out["derivatives"]
    regime_score = regime_engine_out["score"]

    # تشخیص آبشار لیکوئید (ساده‌شده)
    cascade_detected, cascade_type = detect_liquidation_cascade(
        change_24h,
        vol_ratio,
        None,  # oi_change - فعلاً در دسترس نیست
        source_validation.get("coinglass", {}).get("liquidations")
    )

    regime = {
        "trend": trend_state,
        "volatility": volatility_state,
        "derivatives": derivatives_state,
        "cascade_detected": cascade_detected,
        "cascade_type": cascade_type,
        "regime_score": regime_score,
        # Full canonical dict (asset-trend/participation/market_bias included)
        # kept here too so downstream code (v11 intel pass) can consume it
        # directly instead of recomputing a second, colliding regime read.
        "engine": regime_engine_out,
    }
    

    # ===== STAGE 2: Regime-based adjustments =====
    if volatility_state == "EXTREME":
        warning = warning or "EXTREME VOLATILITY - Reduce position size"
        if levels and "sl" in levels:
            entry_price = levels["entry"]
            sl_price = levels["sl"]
            if direction == "LONG":
                levels["sl"] = entry_price - abs(entry_price - sl_price) * 1.5
            else:
                levels["sl"] = entry_price + abs(entry_price - sl_price) * 1.5
        leverage = max(1.0, leverage * 0.5)
    
    if derivatives_state == "LONG_CROWDED" and direction == "LONG":
        gate = "BLOCK"
        gate_reason = "Long crowded (high funding rate) - " + gate_reason
    elif derivatives_state == "SHORT_CROWDED" and direction == "SHORT":
        gate = "BLOCK"
        gate_reason = "Short crowded (negative funding rate) - " + gate_reason

    temp_result = {
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
        "session": session,
        "session_label": session_label,
        "session_multiplier": session_multiplier,
        "btc_regime": btc_regime,
        # Stage 1 fields
        "data_quality": data_quality,
        "data_quality_label": "HIGH" if data_quality >= 80 else "MEDIUM" if data_quality >= 60 else "LOW",
        "signal_id": signal_id,
        "no_trade_reasons": [],
        "no_trade_summary": "",
        # Stage 2 fields
        "regime": regime,
        "regime_trend": trend_state,
        "regime_volatility": volatility_state,
        "regime_derivatives": derivatives_state,
        "regime_score": regime_score,
    }

    # Simple invalidation logic inline
    signal_id = hashlib.md5(f"{coin}|{direction}|{temp_result.get('signal_candle_ts', 0)}".encode()).hexdigest()[:10]
    
    contradictions = []
    contradiction_status = "LOW"
    if direction == "LONG" and overbought:
        contradictions.append("overbought RSI contradicts long")
        contradiction_status = "MEDIUM"
    if direction == "SHORT" and oversold:
        contradictions.append("oversold RSI contradicts short")
        contradiction_status = "MEDIUM"
    if direction == "LONG" and d1 == "BEARISH":
        contradictions.append("D1 bearish contradicts long")
        contradiction_status = "HIGH"
    if direction == "SHORT" and d1 == "BULLISH":
        contradictions.append("D1 bullish contradicts short")
        contradiction_status = "HIGH"
    
    if contradiction_status == "HIGH_CONTRADICTION" or contradiction_status == "HIGH":
        warning = warning or f"High contradiction: {', '.join(contradictions[:3])}"
        action = "NO TRADE"
        gate = "BLOCK"
        gate_reason = f"High contradiction: {', '.join(contradictions[:3])}"

    no_trade_reasons = []
    should_trade = True
    
    if gate == "BLOCK":
        should_trade = False
        no_trade_reasons.append(f"Gate blocked: {gate_reason}")
    
    if liq_label == "LOW" and liq_score < 30:
        should_trade = False
        no_trade_reasons.append("Low liquidity")
    
    if quality == "LOW":
        should_trade = False
        no_trade_reasons.append("Low data quality")
    
    if spread_pct is not None and spread_pct > 3:
        should_trade = False
        no_trade_reasons.append(f"High spread: {spread_pct:.2f}%")
    
    repeat_signal = False
    if action in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
        with sqlite_conn() as c:
            prev = c.execute(
                "select 1 from signal_memory where coin=? and direction=? and signal_candle_ts=?",
                (coin, direction, temp_result.get("signal_candle_ts", 0))
            ).fetchone()
            if prev:
                repeat_signal = True
                should_trade = False
                no_trade_reasons.append("Repeated signal on same candle")
        
        if should_trade:
            with sqlite_conn() as c:
                c.execute(
                    "insert into signal_memory(coin,direction,action,confidence,signal_candle_ts,entry,sl,tp1,tp2,last_seen_at,decision_state) values(?,?,?,?,?,?,?,?,?,?,?)",
                    (coin, direction, action, confidence, temp_result.get("signal_candle_ts", 0),
                     levels["entry"] if levels else None, levels["sl"] if levels else None,
                     levels["tp1"] if levels else None, levels["tp2"] if levels else None,
                     now_utc().isoformat(), action)
                )

    if not should_trade and action != "NO TRADE":
        action = "NO TRADE"
        gate = "BLOCK"
        gate_reason = " | ".join(no_trade_reasons[:5])

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
        "session": session,
        "session_label": session_label,
        "session_multiplier": session_multiplier,
        "signal_id": signal_id,
        "contradiction_status": contradiction_status,
        "contradictions": contradictions,
        "no_trade_reasons": no_trade_reasons,
        "should_trade": should_trade,
        "repeat_signal": repeat_signal,
        # Stage 1 fields
        "data_quality": data_quality,
        "data_quality_label": "HIGH" if data_quality >= 80 else "MEDIUM" if data_quality >= 60 else "LOW",
        # Stage 2 fields
        "regime": regime,
        "regime_trend": trend_state,
        "regime_volatility": volatility_state,
        "regime_derivatives": derivatives_state,
        "regime_score": regime_score,
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
            
            # ===== STAGE 2: Regime-based decision adjustment =====
            if r.get("regime_volatility") == "EXTREME" and state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("Extreme volatility - entry postponed")
            
            if r.get("regime_derivatives") == "LONG_CROWDED" and direction == "LONG":
                if state == "BUY CONFIRMATION":
                    state = "BULLISH WATCH"
                    reasons.append("Long crowded (funding rate too high)")
            
            if r.get("regime_derivatives") == "SHORT_CROWDED" and direction == "SHORT":
                if state == "SELL CONFIRMATION":
                    state = "BEARISH WATCH"
                    reasons.append("Short crowded (negative funding rate)")

            # FIX: wire the mandatory backtest gate into live decisions, not just
            # into whether weights are allowed to self-adjust. If the model most
            # recently failed its backtest, no signal may reach an executable
            # CONFIRMATION state — cap it at WATCH until backtest passes again.
            if not _LAST_BACKTEST_OK and state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("Backtest gate failed — execution frozen, watch-only")
            
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
    """Self-healing weight adjustment based on closed signal outcomes.

    FIXES applied here vs. the previous version:
    1. Batch size of 3 was not statistically meaningful (a single bad trade
       flips the batch's error rate). Raised to a configurable, larger batch
       (ATLAS_SELF_HEAL_BATCH, default 15) so a genuine pattern is required
       before any weight moves.
    2. The old logic was one-directional: it only ever punished a feature after
       losses, and never rewarded a feature that kept showing up in winning
       trades. Left running long enough, every weight decays toward the floor.
       This version also nudges a feature's weight up when it shows up
       disproportionately in wins.
    3. Feature attribution used to grep for raw indicator tokens inside the
       Persian-mixed free-text 'notes' field, which is fragile (breaks
       silently if wording changes, misses some candle-pattern names like
       "SHOOTING STAR" / "PIN BAR"). The token list now matches every pattern
       name candle_pattern() can actually produce, plus the indicator/volume
       tokens, so attribution degrades to "no clear feature" instead of
       silently picking the wrong one.
    4. Added a total-sample-size gate using the same tiers as calibration
       (_calibration_tier): under 100 total closed outcomes, no automatic
       weight change happens at all — with fewer than 100 trades the model
       has no business claiming it has learned which feature is unreliable.
       Between 100-1000 the nudge is small (cautious/adaptive); only past
       1000 closed trades does the adjustment reach its full size.
    """
    init_sqlite()
    with sqlite_conn() as c:
        total_closed = c.execute(
            "select count(*) as n from signal_outcomes where status='CLOSED'"
        ).fetchone()["n"]
    tier = _calibration_tier(total_closed)
    if tier == "NOT_CALIBRATED":
        print(f"🧪 self_diagnostic: only {total_closed} closed outcomes (<100) — auto-learning frozen")
        return
    # How aggressively a batch is allowed to move a weight, scaled by how much
    # historical evidence backs the model overall (not just this one batch).
    nudge_by_tier = {"CAUTIOUS": 0.05, "ADAPTIVE": 0.12, "ROBUST": 0.20}
    nudge = nudge_by_tier[tier]

    with sqlite_conn() as c:
        rows=c.execute("""
            select s.id,s.coin,s.direction,s.outcome,s.notes
            from signal_outcomes s
            left join self_healing_processed p on p.signal_id=s.id
            where s.status='CLOSED' and p.signal_id is null
            order by s.id asc
        """).fetchall()
    batch_size = max(10, int(os.environ.get("ATLAS_SELF_HEAL_BATCH", "15")))
    if len(rows) < batch_size:
        return
    batch = rows[:(len(rows)//batch_size)*batch_size]

    token_map = {
        "rsi": "rsi", "macd": "macd", "sma": "higher_trend",
        "hammer": "candle_pattern", "shooting star": "candle_pattern",
        "engulfing": "candle_pattern", "pin bar": "candle_pattern",
        "doji": "candle_pattern", "حجم": "volume", "واگرایی": "rsi",
    }

    def attribute_feature(note_text):
        text = (note_text or "").lower()
        for token, feature in token_map.items():
            if token in text:
                return feature
        return None

    for start_i in range(0, len(batch), batch_size):
        chunk = batch[start_i:start_i + batch_size]
        n = len(chunk)
        losses = sum(1 for r in chunk if r["outcome"] == "SL")
        wins = sum(1 for r in chunk if r["outcome"] == "TP")
        error_pct = losses / n * 100
        win_pct = wins / n * 100

        loss_feature_counts, win_feature_counts = {}, {}
        for r in chunk:
            feature = attribute_feature(r["notes"])
            if not feature:
                continue
            bucket = loss_feature_counts if r["outcome"] == "SL" else (
                win_feature_counts if r["outcome"] == "TP" else None)
            if bucket is not None:
                bucket[feature] = bucket.get(feature, 0) + 1

        # Punish a feature that dominates losses when the batch's error rate
        # is meaningfully above the losing side of a coin flip.
        if error_pct > 55 and loss_feature_counts:
            feature = max(loss_feature_counts, key=loss_feature_counts.get)
            update_weight(
                feature, 1.0 - nudge,
                f"خطای پیش‌بینی {error_pct:.0f}% در batch {n} تایی (tier={tier}, کل={total_closed})؛ "
                f"وزن {nudge*100:.0f}% کاهش یافت",
                {"samples": n, "wins": wins, "losses": losses, "error_pct": error_pct,
                 "tier": tier, "total_closed": total_closed, "signal_ids": [r["id"] for r in chunk]},
            )
        # Reward a feature that dominates wins when the batch is clearly
        # profitable — without this, weights only ever decay over time.
        elif win_pct > 60 and win_feature_counts:
            feature = max(win_feature_counts, key=win_feature_counts.get)
            update_weight(
                feature, 1.0 + nudge,
                f"نرخ برد {win_pct:.0f}% در batch {n} تایی (tier={tier}, کل={total_closed})؛ "
                f"وزن {nudge*100:.0f}% افزایش یافت",
                {"samples": n, "wins": wins, "losses": losses, "win_pct": win_pct,
                 "tier": tier, "total_closed": total_closed, "signal_ids": [r["id"] for r in chunk]},
            )

        with sqlite_conn() as c:
            c.executemany(
                "insert or ignore into self_healing_processed(signal_id,processed_at) values(?,?)",
                [(r["id"], now_utc().isoformat()) for r in chunk],
            )


# ============================================================
# BACKTEST ENGINE
# ============================================================

def _backtest_trade_stats(trades, days_covered=None):
    """
    Aggregate a list of trade dicts (as produced by _run_backtest_window) into
    the fuller performance picture requested in the architecture review — a
    strategy can have a 58% win rate and still lose money overall, so win
    rate alone was never enough.
    """
    if not trades:
        return None
    r_multiples = [t["r_multiple"] for t in trades]
    pnl_pcts = [t["pnl_pct"] for t in trades]
    wins = [t for t in trades if t["r_multiple"] > 0]
    losses = [t for t in trades if t["r_multiple"] <= 0]

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in trades:
        equity *= (1 + t["pnl_pct"] / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    net_return_pct = (equity - 1.0) * 100.0

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else (99.0 if gross_profit > 0 else 0.0)

    win_rate = len(wins) / len(trades) * 100.0
    expectancy_r = mean(r_multiples)
    avg_r = expectancy_r
    med_r = median(r_multiples)
    avg_win_pct = mean([t["pnl_pct"] for t in wins]) if wins else 0.0
    avg_loss_pct = mean([t["pnl_pct"] for t in losses]) if losses else 0.0
    avg_mae_r = mean([t["mae_r"] for t in trades])
    avg_mfe_r = mean([t["mfe_r"] for t in trades])
    avg_holding_bars = mean([t["holding_bars"] for t in trades])

    # Sharpe/Sortino on the per-trade return series (not annualized to a fixed
    # trading-day calendar, since trade frequency varies by asset/regime —
    # reported as a per-trade ratio, which is still meaningful for comparing
    # one coin/strategy variant against another under the same rule).
    if len(pnl_pcts) > 1 and pstdev(pnl_pcts) > 0:
        sharpe = mean(pnl_pcts) / pstdev(pnl_pcts)
    else:
        sharpe = 0.0
    downside = [min(0.0, p) for p in pnl_pcts]
    downside_dev = pstdev(downside) if len(downside) > 1 else 0.0
    sortino = (mean(pnl_pcts) / downside_dev) if downside_dev > 0 else (sharpe if sharpe > 0 else 0.0)

    exit_reasons = {}
    for t in trades:
        exit_reasons[t["exit_reason"]] = exit_reasons.get(t["exit_reason"], 0) + 1

    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "profit_factor": profit_factor,
        "expectancy_r": expectancy_r, "avg_r": avg_r, "median_r": med_r,
        "net_return_pct": net_return_pct, "max_drawdown_pct": max_dd,
        "sharpe": sharpe, "sortino": sortino,
        "avg_win_pct": avg_win_pct, "avg_loss_pct": avg_loss_pct,
        "avg_mae_r": avg_mae_r, "avg_mfe_r": avg_mfe_r,
        "avg_holding_bars": avg_holding_bars, "exit_reasons": exit_reasons,
        "days_covered": days_covered,
        # Backward-compatible aliases for older callers/columns.
        "avg_profit": avg_win_pct, "avg_loss": abs(avg_loss_pct),
        "max_drawdown": max_dd,
    }


def _run_backtest_window(rows, risk_pct=None, fee_pct=None, slippage_pct=None):
    """
    Runs the fixed technical rule (same signal logic as before: SMA20/50 +
    MACD + RSI + volume filter, SL=1.5*ATR / TP=3*ATR) over one contiguous
    slice of OHLCV rows and returns a list of trade dicts.

    FIXES vs. the previous backtest_coin():
    - Every trade used to book a hardcoded -1.5% / +3.0% equity change
      regardless of the actual ATR-to-price ratio or any position sizing —
      i.e. it silently assumed every trade risks exactly 1.5% of equity with
      zero fees/slippage. Now: position size is derived from risk_pct (same
      RISK_PER_TRADE_PCT the live engine uses) so a trade's % equity impact
      reflects its real R-multiple, and fees + slippage are subtracted from
      both entry and exit.
    - MAE (max adverse excursion) and MFE (max favorable excursion), holding
      time in bars, and exit reason (TP/SL/TIMEOUT) are now tracked per trade
      instead of being discarded.
    """
    risk_pct = RISK_PER_TRADE if risk_pct is None else risk_pct
    fee_pct = BACKTEST_FEE_PCT if fee_pct is None else fee_pct
    slippage_pct = BACKTEST_SLIPPAGE_PCT if slippage_pct is None else slippage_pct
    trades = []
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
        raw_entry = c[-1]
        # Slippage: fills are always slightly worse than the signal price.
        entry = raw_entry * (1 + slippage_pct / 100.0) if direction == "LONG" else raw_entry * (1 - slippage_pct / 100.0)
        sl = entry - 1.5 * a if direction == "LONG" else entry + 1.5 * a
        tp = entry + 3.0 * a if direction == "LONG" else entry - 3.0 * a
        risk_per_unit = abs(entry - sl)
        if risk_per_unit <= 0:
            continue

        outcome, exit_price, holding_bars = None, None, 0
        mae_r, mfe_r = 0.0, 0.0
        future_slice = rows[i:i + SIGNAL_HORIZON_BARS]
        for bar_idx, future in enumerate(future_slice, start=1):
            hi, lo = f(future[2]), f(future[3])
            if hi is None or lo is None:
                continue
            if direction == "LONG":
                adverse_r = (entry - lo) / risk_per_unit
                favorable_r = (hi - entry) / risk_per_unit
            else:
                adverse_r = (hi - entry) / risk_per_unit
                favorable_r = (entry - lo) / risk_per_unit
            mae_r = max(mae_r, adverse_r)
            mfe_r = max(mfe_r, favorable_r)
            if direction == "LONG":
                if lo <= sl:
                    outcome, exit_price, holding_bars = "SL", sl, bar_idx
                    break
                if hi >= tp:
                    outcome, exit_price, holding_bars = "TP", tp, bar_idx
                    break
            else:
                if hi >= sl:
                    outcome, exit_price, holding_bars = "SL", sl, bar_idx
                    break
                if lo <= tp:
                    outcome, exit_price, holding_bars = "TP", tp, bar_idx
                    break
        if outcome is None:
            # Neither SL nor TP hit within the horizon — close at last known
            # price instead of silently dropping the trade (dropping it
            # would bias results toward only the trades that resolved fast).
            last_close = f(future_slice[-1][4]) if future_slice else raw_entry
            if last_close is None:
                continue
            outcome, exit_price, holding_bars = "TIMEOUT", last_close, len(future_slice)

        # Exit slippage in the adverse direction too.
        exit_fill = exit_price * (1 - slippage_pct / 100.0) if direction == "LONG" else exit_price * (1 + slippage_pct / 100.0)
        raw_move_pct = ((exit_fill - entry) / entry * 100.0) if direction == "LONG" else ((entry - exit_fill) / entry * 100.0)
        fee_drag_pct = fee_pct  # round-trip fee, already expressed as % of notional
        # Position size: risking exactly risk_pct of equity if SL is hit,
        # i.e. position notional = (risk_pct / 100) * equity / (risk_per_unit/entry).
        # Expressed directly as a scaling factor on the raw price-return so
        # the % impact on equity matches "risk_pct at 1R, more at >1R".
        r_multiple = (exit_fill - entry) / risk_per_unit if direction == "LONG" else (entry - exit_fill) / risk_per_unit
        pnl_pct = r_multiple * risk_pct - fee_drag_pct

        trades.append({
            "direction": direction, "entry": entry, "sl": sl, "tp": tp,
            "exit_price": exit_fill, "exit_reason": outcome,
            "r_multiple": r_multiple, "pnl_pct": pnl_pct,
            "holding_bars": holding_bars, "mae_r": mae_r, "mfe_r": mfe_r,
            "position_risk_pct": risk_pct, "fee_pct": fee_pct, "slippage_pct": slippage_pct,
        })
    return trades


def backtest_coin(coin, days=180):
    """Single-window backtest (kept name/shape for existing callers like
    mandatory_backtest_gate). Internally now uses the fee/slippage/position-
    sizing-aware engine and the fuller stat set from _backtest_trade_stats,
    merged so old field names (win_rate, profit_factor, max_drawdown,
    avg_profit, avg_loss) keep working alongside the new ones."""
    try:
        rows, engine = best_ohlcv(coin, "4h", 1200)
    except Exception:
        return None
    cutoff = int((time.time() - days * 86400) * 1000)
    rows = [x for x in rows if x[0] >= cutoff]
    if len(rows) < 150:
        return None
    trades = _run_backtest_window(rows)
    if not trades:
        return None
    stats = _backtest_trade_stats(trades, days_covered=days)
    stats["coin"] = coin
    stats["engine"] = engine
    stats["trades_raw"] = [t["r_multiple"] * RISK_PER_TRADE for t in trades]  # back-compat shape
    return stats


def walk_forward_backtest(coin, train_days=None, validate_days=None, test_days=None):
    """
    Splits history into sequential Train / Validate / Test windows and runs
    the SAME fixed rule independently on each (architecture review, point 7).
    There's no parameter fitting happening on "train" here — the signal rule
    itself is fixed, not optimized — so this is a robustness check ("does
    this rule's edge hold up on data it wasn't eyeballed against") rather
    than a classic ML train/val/test split. Returns None if there isn't
    enough history for all three windows.
    """
    train_days = train_days or WALK_FORWARD_TRAIN_DAYS
    validate_days = validate_days or WALK_FORWARD_VALIDATE_DAYS
    test_days = test_days or WALK_FORWARD_TEST_DAYS
    total_days = train_days + validate_days + test_days

    try:
        rows, engine = best_ohlcv(coin, "4h", 2000)
    except Exception:
        return None
    cutoff = int((time.time() - total_days * 86400) * 1000)
    rows = [x for x in rows if x[0] >= cutoff]
    if len(rows) < 300:
        return None

    bars_per_day = 6  # 4H candles
    train_end = train_days * bars_per_day
    validate_end = train_end + validate_days * bars_per_day
    test_end = validate_end + test_days * bars_per_day

    segments = {
        "train": rows[:train_end],
        "validate": rows[train_end:validate_end],
        "test": rows[validate_end:test_end],
    }
    results = {}
    for name, seg_rows in segments.items():
        if len(seg_rows) < 150:
            results[name] = None
            continue
        seg_trades = _run_backtest_window(seg_rows)
        results[name] = _backtest_trade_stats(seg_trades) if seg_trades else None

    train_stats, test_stats = results.get("train"), results.get("test")
    consistent = None
    if train_stats and test_stats:
        # "Consistent" = the out-of-sample test period didn't collapse
        # relative to train — test PF at least half of train PF, and test
        # expectancy still non-negative. This is intentionally a loose bar;
        # it flags clear overfit-to-one-window cases, not marginal drift.
        consistent = (
            test_stats["profit_factor"] >= max(1.0, train_stats["profit_factor"] * 0.5)
            and test_stats["expectancy_r"] >= 0
        )

    return {"coin": coin, "engine": engine, "segments": results, "consistent": consistent}



def _backtest_gate_fingerprint(universe):
    """Fingerprint the gate against model/config/universe/latest closed 4H bar."""
    anchor_coin = str((universe or ["BTC"])[0]).upper()
    closed_ts = None
    try:
        rows, _ = best_ohlcv(anchor_coin, "4h", 60)
        if rows:
            closed_ts = int(rows[-1][0])
    except Exception:
        pass

    payload = {
        "version": VERSION,
        "timeframe": SIGNAL_TIMEFRAME,
        "days": BACKTEST_DAYS,
        "fee": BACKTEST_FEE_PCT,
        "slippage": BACKTEST_SLIPPAGE_PCT,
        "min_improvement": MIN_BACKTEST_IMPROVEMENT,
        "universe20": [str(x).upper() for x in (universe or [])[:20]],
        "latest_closed_4h": closed_ts,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), payload

def _cached_backtest_gate(fingerprint=None):
    cutoff = now_utc() - timedelta(hours=BACKTEST_REFRESH_HOURS)

    # 1) Fast local SQLite cache.
    try:
        with sqlite_conn() as c:
            row = c.execute(
                "select timestamp, passed, details from backtest_gate_cache where id=1"
            ).fetchone()
        if row and row[0]:
            ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            details = row[2]
            try:
                details = json.loads(details) if isinstance(details, str) else (details or {})
            except Exception:
                details = {}
            fp_ok = fingerprint is None or details.get("fingerprint") == fingerprint
            if ts >= cutoff and fp_ok:
                _ATLAS_BT_CACHE_STATS["sqlite_hit"] += 1
                return bool(row[1]), {"cached": True, "cache_source": "sqlite", **details}
            if ts >= cutoff and not fp_ok:
                _ATLAS_BT_CACHE_STATS["fingerprint_mismatch"] += 1
    except Exception as e:
        append_changelog(
            "BACKTEST_CACHE", None, None, str(e),
            {"traceback": traceback.format_exc()},
        )

    # 2) Persistent Supabase cache using the already-existing atlas_changelog.
    if ATLAS_PERSISTENT_BACKTEST_CACHE and getattr(STORE, "enabled", False):
        try:
            rows = STORE.select(
                "atlas_changelog",
                {
                    "select": "timestamp,evidence",
                    "model_version": f"eq.{VERSION}",
                    "component": "eq.BACKTEST_GATE_CACHE",
                    "order": "timestamp.desc",
                    # Search several recent runs because a newer cache row from
                    # a different 4H fingerprint must not hide a still-valid
                    # exact match inside the refresh window.
                    "limit": "12",
                },
            )
            _ATLAS_BT_CACHE_STATS["supabase_rows_seen"] += len(rows or [])
            for row in rows or []:
                try:
                    ts = datetime.fromisoformat(
                        str(row.get("timestamp") or "").replace("Z", "+00:00")
                    )
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                evidence = row.get("evidence") or {}
                if isinstance(evidence, str):
                    try:
                        evidence = json.loads(evidence)
                    except Exception:
                        evidence = {}
                fp_ok = fingerprint is None or evidence.get("fingerprint") == fingerprint
                if not fp_ok:
                    _ATLAS_BT_CACHE_STATS["fingerprint_mismatch"] += 1
                    continue
                if "passed" not in evidence:
                    continue
                result = evidence.get("result") or {}
                try:
                    with sqlite_conn() as c:
                        local_details = {
                            **result,
                            "fingerprint": evidence.get("fingerprint"),
                            "fingerprint_payload": evidence.get("fingerprint_payload"),
                        }
                        c.execute(
                            "insert or replace into backtest_gate_cache"
                            "(id,timestamp,passed,details) values(1,?,?,?)",
                            (
                                ts.isoformat(),
                                int(bool(evidence.get("passed"))),
                                safe_json(local_details),
                            ),
                        )
                except Exception:
                    pass
                _ATLAS_BT_CACHE_STATS["supabase_hit"] += 1
                return bool(evidence.get("passed")), {
                    "cached": True,
                    "cache_source": "supabase",
                    "fingerprint": evidence.get("fingerprint"),
                    **result,
                }
        except Exception as e:
            append_changelog(
                "BACKTEST_CACHE_SUPABASE", None, None, str(e),
                {"traceback": traceback.format_exc()},
            )

    _ATLAS_BT_CACHE_STATS["miss"] += 1
    return None

def _save_backtest_gate(passed, details, fingerprint=None, fingerprint_payload=None):
    enriched = {
        **(details or {}),
        "fingerprint": fingerprint,
        "fingerprint_payload": fingerprint_payload or {},
    }

    # SQLite fallback/audit.
    try:
        with sqlite_conn() as c:
            c.execute(
                "insert or replace into backtest_gate_cache(id,timestamp,passed,details) values(1,?,?,?)",
                (now_utc().isoformat(), int(bool(passed)), safe_json(enriched)),
            )
    except Exception as e:
        append_changelog(
            "BACKTEST_CACHE", None, None,
            f"cache write failed: {e}",
            {"traceback": traceback.format_exc()},
        )

    # Persistent cache in existing Supabase atlas_changelog.
    if ATLAS_PERSISTENT_BACKTEST_CACHE:
        append_changelog(
            "BACKTEST_GATE_CACHE",
            None,
            int(bool(passed)),
            "Persistent mandatory backtest gate cache",
            {
                "fingerprint": fingerprint,
                "fingerprint_payload": fingerprint_payload or {},
                "passed": bool(passed),
                "result": details or {},
            },
        )


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
    fingerprint, fingerprint_payload = _backtest_gate_fingerprint(universe)
    cached = _cached_backtest_gate(fingerprint)
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
        _save_backtest_gate(False, result, fingerprint, fingerprint_payload)
        return False, result
    win_rate = safe_mean([x.get("win_rate") for x in samples], 0.0)
    pf = safe_mean([x.get("profit_factor") for x in samples], 0.0)
    dd = max((safe_float(x.get("max_drawdown"), 0.0) or 0.0) for x in samples)
    net_return = safe_mean([x.get("net_return_pct") for x in samples], 0.0)
    expectancy_r = safe_mean([x.get("expectancy_r") for x in samples], 0.0)
    sharpe = safe_mean([x.get("sharpe") for x in samples], 0.0)
    sortino = safe_mean([x.get("sortino") for x in samples], 0.0)

    # Walk-forward diagnostic (architecture review, point 7): run on one
    # representative coin only — walk-forward fetches up to 2000 candles per
    # coin, so running it across the full universe every gate check would be
    # expensive for a diagnostic that doesn't (yet) change the pass/fail
    # decision below. It's logged so drift/overfit becomes visible over time.
    wf = walk_forward_backtest(universe[0]) if universe else None
    wf_summary = None
    if wf:
        wf_summary = {
            "coin": wf["coin"], "consistent": wf["consistent"],
            "train_pf": (wf["segments"].get("train") or {}).get("profit_factor"),
            "test_pf": (wf["segments"].get("test") or {}).get("profit_factor"),
            "train_expectancy_r": (wf["segments"].get("train") or {}).get("expectancy_r"),
            "test_expectancy_r": (wf["segments"].get("test") or {}).get("expectancy_r"),
        }
        if wf["consistent"] is False:
            append_changelog(
                "WALK_FORWARD", None, None,
                f"{wf['coin']}: out-of-sample test period diverged from train — possible overfit to one window",
                wf_summary,
            )

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
                    "net_return_pct": r.get("net_return_pct"),
                    "expectancy_r": r.get("expectancy_r"),
                    "sharpe": r.get("sharpe"),
                    "sortino": r.get("sortino"),
                    "passed": True,
                    "details": {"baseline": True, "fee_pct": BACKTEST_FEE_PCT,
                                "slippage_pct": BACKTEST_SLIPPAGE_PCT},
                },
            )
        append_changelog(
            "BACKTEST",
            None,
            pf,
            "Baseline established; no automatic model change allowed yet",
            {"win_rate": win_rate, "profit_factor": pf, "max_drawdown": dd,
             "net_return_pct": net_return, "expectancy_r": expectancy_r,
             "sharpe": sharpe, "sortino": sortino, "walk_forward": wf_summary},
        )
        result = {
            "win_rate": win_rate,
            "profit_factor": pf,
            "max_drawdown": dd,
            "net_return_pct": net_return,
            "expectancy_r": expectancy_r,
            "sharpe": sharpe,
            "sortino": sortino,
            "walk_forward": wf_summary,
            "improvement": 0,
        }
        _save_backtest_gate(True, result, fingerprint, fingerprint_payload)
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
                "net_return_pct": r.get("net_return_pct"),
                "expectancy_r": r.get("expectancy_r"),
                "sharpe": r.get("sharpe"),
                "sortino": r.get("sortino"),
                "baseline_profit_factor": baseline_pf,
                "baseline_win_rate": baseline_wr,
                "improvement_pct": max(improvement_pf, improvement_wr),
                "passed": passed,
                "details": {"self_healing_gate": True, "fee_pct": BACKTEST_FEE_PCT,
                            "slippage_pct": BACKTEST_SLIPPAGE_PCT, "walk_forward": wf_summary},
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
            "net_return_pct": net_return,
            "expectancy_r": expectancy_r,
            "sharpe": sharpe,
            "sortino": sortino,
            "walk_forward": wf_summary,
            "passed": passed,
        },
    )
    result = {
        "win_rate": win_rate,
        "profit_factor": pf,
        "max_drawdown": dd,
        "net_return_pct": net_return,
        "expectancy_r": expectancy_r,
        "sharpe": sharpe,
        "sortino": sortino,
        "walk_forward": wf_summary,
        "improvement": max(improvement_pf, improvement_wr),
    }
    _save_backtest_gate(passed, result, fingerprint, fingerprint_payload)
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
            (coin,direction,entry,sl,tp1,tp2,issued_at,notes,signal_score)
            values(?,?,?,?,?,?,?,?,?)
            """,
            (
                result["coin"], result["direction"], result["entry"],
                result["sl"], result["tp1"], result["tp2"],
                now_utc().isoformat(), result["reason"], result["confidence"],
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
    
    print(f"🔍 TELEGRAM_CHAT_ID: '{TELEGRAM_CHAT_ID}'")
    print(f"🔍 TELEGRAM_GROUP_CHAT_ID: '{TELEGRAM_GROUP_CHAT_ID}'")
    
    if TELEGRAM_CHAT_ID and str(TELEGRAM_CHAT_ID).strip():
        chat_id_str = str(TELEGRAM_CHAT_ID).strip()
        destinations.append({
            "id": chat_id_str,
            "name": "PRIVATE_CHAT",
            "delay": TELEGRAM_PRIVATE_DELAY
        })
        print(f"✅ Added PRIVATE_CHAT: {chat_id_str}")
    else:
        print("⚠️ TELEGRAM_CHAT_ID is empty")
    
    if TELEGRAM_GROUP_CHAT_ID and str(TELEGRAM_GROUP_CHAT_ID).strip():
        group_id_str = str(TELEGRAM_GROUP_CHAT_ID).strip()
        existing_ids = [d["id"] for d in destinations]
        if group_id_str not in existing_ids:
            destinations.append({
                "id": group_id_str,
                "name": "SUPERGROUP",
                "delay": TELEGRAM_GROUP_DELAY
            })
            print(f"✅ Added SUPERGROUP: {group_id_str}")
        else:
            print(f"⚠️ SUPERGROUP already in destinations: {group_id_str}")
    else:
        print(f"⚠️ TELEGRAM_GROUP_CHAT_ID is empty or invalid: '{TELEGRAM_GROUP_CHAT_ID}'")
    
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
    "DataQuality", "SignalID", "RegimeTrend", "RegimeVolatility",
    "RegimeDerivatives", "RegimeScore",
    "سناریوی_معاملاتی",
    "تحلیل_عمیق_بازار",
    "سطوح_کلیدی",
    "نقاط_ورود_و_خروج",
    "توصیه_نهایی"
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

def _resolve_csv_universe(results, top10, dynamic30):
    """Returns ordered symbols for CSV export."""
    ordered = []
    for sym in list(top10 or ATLAS_PRIORITY_TOP10) + list(dynamic30 or []) + list(ATLAS_PERSONAL_ASSETS) + list(ATLAS_METALS):
        s = str(sym).upper()
        if s and s not in ordered:
            ordered.append(s)
    return ordered

def _csv_text_for_symbols(symbols, results, top10, dynamic30):
    import csv, io
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    result_map = {str(r.get("coin") or "").upper(): dict(r) for r in (results or []) if r.get("coin")}
    rows = []
    for sym in symbols:
        r = result_map.get(sym)
        if r is None and sym in ATLAS_METALS:
            r = _metal_analysis(sym)
            if r:
                r = v11_apply_intelligence(r)
        if not r:
            continue
        
        # ===== تولید تحلیل انسانی برای ستون‌های جدید =====
        direction_text = "صعودی" if r.get("direction") == "LONG" else "نزولی" if r.get("direction") == "SHORT" else "خنثی"
        setup_type = r.get("setup_type", "NO SETUP")
        setup_map = {
            "BREAKOUT": "شکست مقاومت با تأیید حجم",
            "BREAKDOWN": "شکست حمایت با تأیید حجم",
            "PULLBACK": "بازگشت به حمایت و ادامه روند",
            "REVERSAL": "برگشت از سطح کلیدی",
            "RANGE": "بازار در محدوده - منتظر شکست",
            "TREND CONTINUATION": "ادامه روند",
            "NO SETUP": "ستاپ مشخص نیست"
        }
        setup_desc = setup_map.get(setup_type, setup_type.replace("_", " ").lower())
        
        plan = _csv_safe_plan(r)
        entry = sl = tp1 = tp2 = ""
        if plan:
            entry, sl, tp1, tp2 = plan
        
        scenario = f"{direction_text} - {setup_desc}"
        if entry and sl and tp1:
            scenario += f" | ورود: {fmt(entry)} | حدضرر: {fmt(sl)} | هدف: {fmt(tp1)}"
        
        deep_analysis = f"رژیم: {r.get('regime_trend', 'نامشخص')} | نوسان: {r.get('regime_volatility', 'نامشخص')}"
        if r.get("rsi") is not None:
            deep_analysis += f" | RSI: {r.get('rsi'):.1f}"
        if r.get("volume_ratio") is not None:
            deep_analysis += f" | حجم: {r.get('volume_ratio'):.2f}x"
        
        key_levels = f"حمایت: {fmt(r.get('support'))} | مقاومت: {fmt(r.get('resistance'))}"
        
        entry_exit = f"ورود: {fmt(entry)} | حدضرر: {fmt(sl)} | TP1: {fmt(tp1)} | TP2: {fmt(tp2)}" if entry and sl else "نامشخص"
        
        if r.get("decision_state") in ("BUY CONFIRMATION", "SELL CONFIRMATION") and r.get("gate") == "PASS":
            recommendation = "قابل اجرا - با احتیاط وارد شوید"
        elif "WATCH" in str(r.get("decision_state", "")):
            recommendation = "در انتظار تأیید - صبر کنید"
        else:
            recommendation = "بدون سیگنال - در جایگاه ناظر باشید"
        
        rows.append([
            sym,
            _csv_status(r),
            r.get("decision_state") or r.get("action") or "WAIT",
            _csv_number(r.get("price")),
            _csv_number(r.get("change"), 4),
            _csv_number(r.get("support")),
            _csv_number(r.get("resistance")),
            _csv_number(entry),
            _csv_number(sl),
            _csv_number(tp1),
            _csv_number(tp2),
            _csv_number(r.get("confidence"), 2),
            r.get("h4_trend", "UNKNOWN"),
            r.get("d1_trend", "UNKNOWN"),
            r.get("w1_trend", "UNKNOWN"),
            _csv_number(r.get("rsi"), 2),
            r.get("macd", ""),
            r.get("volume", ""),
            _csv_number(r.get("volume_ratio"), 3),
            _csv_number(r.get("atr_pct"), 3),
            r.get("liquidity", ""),
            r.get("gate", ""),
            r.get("gate_reason", ""),
            r.get("direction", ""),
            bool(r.get("repeat_signal")),
            r.get("intel_reason") or r.get("reason", ""),
            VERSION,
            _csv_number(r.get("data_quality"), 2),
            r.get("signal_id", ""),
            r.get("regime_trend", ""),
            r.get("regime_volatility", ""),
            r.get("regime_derivatives", ""),
            _csv_number(r.get("regime_score"), 2),
            r.get("intel_bias", "NEUTRAL"),
            r.get("setup_type", "NO SETUP"),
            _csv_number(r.get("opportunity_score"), 2),
            _csv_number(r.get("structure_score"), 2),
            _csv_number(r.get("momentum_score"), 2),
            _csv_number(r.get("volume_score"), 2),
            _csv_number(r.get("sr_score"), 2),
            len(r.get("contradictions") or []),
            " | ".join(r.get("contradictions") or []),
            bool(r.get("executable")),
            r.get("intel_decision", "WAIT"),
            r.get("intel_signal_id", ""),
            _csv_number(r.get("decision_confidence"), 2),
            r.get("decision_regime_trend", ""),
            r.get("decision_regime_volatility", ""),
            bool(_LAST_BACKTEST_OK),
            _csv_number(r.get("signal_score"), 2),
            _csv_number(r.get("model_strength"), 2),
            _csv_number(r.get("win_probability"), 1) if r.get("win_probability") is not None else "NOT_CALIBRATED",
            r.get("win_probability_tier", ""),
            r.get("win_probability_samples", 0),
            # ===== ستون‌های جدید =====
            scenario,
            deep_analysis,
            key_levels,
            entry_exit,
            recommendation
        ])
    
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    w.writerows(rows)
    return out.getvalue()

def generate_split_csv_reports(results, top10, dynamic30):
    """Three separate CSV exports instead of one combined file."""
    metals_set = {str(x).upper() for x in ATLAS_METALS}
    personal_set = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS} - metals_set
    top_dynamic_set = ({str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)}
                        | {str(x).upper() for x in (dynamic30 or [])}) - metals_set - personal_set

    ordered = _resolve_csv_universe(results, top10, dynamic30)
    personal_syms = [s for s in ordered if s in personal_set]
    metals_syms = [s for s in ordered if s in metals_set]
    dynamic_syms = [s for s in ordered if s in top_dynamic_set]

    return {
        "personal": _csv_text_for_symbols(personal_syms, results, top10, dynamic30),
        "metals": _csv_text_for_symbols(metals_syms, results, top10, dynamic30),
        "dynamic_top30": _csv_text_for_symbols(dynamic_syms, results, top10, dynamic30),
    }

# NOTE: an earlier generate_csv_report (built around the older CSV_COLUMNS schema)
# used to live here. It was silently shadowed by the later, more complete
# generate_csv_report defined further below (which includes the intel-engine
# columns: OpportunityScore, StructureScore, SetupType, etc.) and never ran.
# Removed to avoid confusion — see the live version further down for the real
# implementation and _new_csv_columns() for the actual exported schema.

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
    """Send three separate CSVs (personal / metals / dynamic_top30)."""
    dt = now_tehran()
    date_tag = shamsi(dt).replace('/', '')
    time_tag = dt.strftime('%H%M%S')
    caption_base = f"📎 ATLAS AI | {VERSION} | {shamsi(dt)} {dt.strftime('%H:%M:%S')} تهران"

    csvs = generate_split_csv_reports(results, top10, dynamic30)
    files = [
        ("personal", "پرتفوی شخصی", csvs["personal"]),
        ("metals", "فلزات گران‌بها", csvs["metals"]),
        ("dynamic_top30", "Top10 + Dynamic Top30", csvs["dynamic_top30"]),
    ]

    destinations = []
    for chat_id in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if chat_id and chat_id not in destinations:
            destinations.append(chat_id)

    sent = 0
    errors = []
    for key, label, content in files:
        if not content.strip():
            continue
        filename = f"atlas_{key}_{date_tag}_{time_tag}.csv"
        caption = f"{caption_base} | {label}"
        for chat_id in destinations:
            try:
                _telegram_send_document(chat_id, content, filename, caption)
                sent += 1
            except Exception as e:
                errors.append(f"CSV[{key}] {chat_id}: {e}")
                append_changelog("CSV_EXPORT", None, None, str(e), {"file": key, "traceback": traceback.format_exc()})
    return sent, errors
# ============================================================
# REPORT FORMAT — DECISION-FIRST / COMPACT / PERSIAN
# ============================================================

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

    session, session_label, session_multiplier = get_current_session()

    lines = [
        f"🔹 {symbol} | {action} | اطمینان: {int(conf) if isinstance(conf,(int,float)) else 0}%",
        f"Price: {fmt(price)} | 24H: {pct(r.get('change'))}" if not metal else f"Price: {fmt(price)}",
        f"🕐 سشن: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x",
        f"Trend: H4 {r.get('h4_trend','UNKNOWN')} / D1 {r.get('d1_trend','UNKNOWN')} / W1 {r.get('w1_trend','UNKNOWN')}",
        f"RSI: {rsi_text} | MACD: {r.get('macd','N/A')} | ATR: {atr_text}",
        f"S/R: {fmt(r.get('support'))} ↔ {fmt(r.get('resistance'))}",
    ]

    # ===== Stage 1: Data Quality =====
    if r.get("data_quality") is not None:
        dq = r["data_quality"]
        label = r.get("data_quality_label", "UNKNOWN")
        lines.append(f"Data Quality: {dq:.0f}% — {label}")

    # ===== Stage 2: Regime Display =====
    if r.get("regime"):
        reg = r["regime"]
        lines.append(
            f"📊 Regime: {reg.get('trend', 'N/A')} | "
            f"Vol: {reg.get('volatility', 'N/A')} | "
            f"Deriv: {reg.get('derivatives', 'N/A')} | "
            f"Score: {reg.get('regime_score', 0)}/100"
        )
        if reg.get("cascade_detected"):
            lines.append(f"⚠️ LIQUIDATION CASCADE: {reg.get('cascade_type', 'UNKNOWN')}")

    # ===== Stage 1: Signal ID =====
    if r.get("signal_id"):
        lines.append(f"🆔 Signal ID: {r['signal_id']}")

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
        if atr_v is None or atr_v < float(os.environ.get("ATLAS_HIGH_ATR_PCT", "4.0")):
            warning = None
    if warning:
        lines.append(f"⚠️ {warning}")
    if tv:
        lines.append(f"📊 Chart: {tv}")
    
    if r.get("signal_id"):
        lines.append(f"🆔 Signal: {r.get('signal_id')}")
    if r.get("contradiction_status") == "HIGH_CONTRADICTION":
        lines.append(f"⚠️ Contradictions: {', '.join(r.get('contradictions', [])[:3])}")
    if r.get("no_trade_reasons"):
        lines.append(f"🚫 No-Trade: {', '.join(r.get('no_trade_reasons', [])[:3])}")
    
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
        # _best_setup_block removed to avoid text report duplication (CSV only)
        _compact_section("📡 ATLAS TOP 10", top10_rows),
        _compact_section("📡 DYNAMIC TOP 30 — خارج از Top 10 و Personal", dyn30_rows),
        _compact_section("🪙 ATLAS METALS — GOLD / SILVER / COPPER", metal_rows, metal=True),
        _final_market_recommendation(results, top10_rows, dyn30_rows, macro, btc_regime),
        # ===== Stage 3: Signal Summary =====
        generate_signal_summary(results),
    ]
    return "\n\n".join(lines)


def build_personal_report(results, macro=None, news=None, market_info=None, btc_regime=None, breadth=None):
    """PERSONAL engine: all portfolio assets, same compact table format."""
    rows = _portfolio_rows(results)
    dt = now_tehran()
    session, session_label, session_multiplier = get_current_session()
    report_lines = [
        "🤖 ATLAS AI — PERSONAL PORTFOLIO 4H",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران",
        f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x",
        # _best_setup_block removed to avoid text report duplication (CSV only)
        _compact_section("💼 PERSONAL PORTFOLIO — همه دارایی‌ها", rows),
        _final_market_recommendation(rows, [], [], macro, btc_regime),
        # ===== Stage 3: Signal Summary =====
        generate_signal_summary(results),
    ]
    return "\n\n".join(report_lines)


def personal_report(*args, **kwargs):
    return build_personal_report(*args, **kwargs)


def atlas_engine_mode():
    return get_engine_mode()


# NOTE: an earlier build_two_engine_reports (the one that called build_report /
# build_personal_report directly) used to live here. It was silently shadowed by
# the later v11.3 intel-style build_two_engine_reports defined further below, so it
# never ran — Python keeps only the last definition of a name. It has been removed
# to avoid confusion. build_report/build_personal_report are still computed inside
# report() (see the 'text' variable) but that text is not currently sent anywhere;
# see the changelog note near main() for details.


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
        lines.append("🔥 Liquidation Heatmap: N/A (COINGLASS_API_KEY not configured or endpoint unavailable")
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
# FIX: previously the mandatory backtest gate only froze self-learning (weight
# updates) when it failed — it never actually restricted which signals could be
# sent as live BUY/SELL. A gate that doesn't gate the thing users act on isn't
# doing its job. _LAST_BACKTEST_OK is read by apply_decision_engine(): when the
# gate fails, no signal is allowed to reach BUY/SELL CONFIRMATION that run; the
# best it can do is a WATCH state, until the model passes backtest again.
_LAST_BACKTEST_OK = True
_LAST_BACKTEST_DETAILS = {}


def report():
    init_sqlite()
    evaluate_open_outcomes()
    universe, top10, dynamic30 = build_universe()
    global _LAST_TOP10, _LAST_DYNAMIC30, _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS
    _LAST_TOP10, _LAST_DYNAMIC30 = list(top10), list(dynamic30)

    backtest_ok, bt = mandatory_backtest_gate(universe)
    _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS = bool(backtest_ok), (bt or {})
    if backtest_ok:
        self_diagnostic()
    else:
        append_changelog("SELF_HEALING", None, None,
                         "Model adaptation frozen because mandatory backtest gate failed", bt)

    weights = get_weights()
    news = news_feed()
    macro = macro_snapshot()

    if ENABLE_INTEL_BRIEFING:
        try:
            fed_macro = fetch_fed_macro()
            whale_items = fetch_whale_activity()
            figure_items = fetch_influential_figures_news(news.get("items"))
            news["intel_briefing"] = build_intelligence_briefing(macro, fed_macro, whale_items, figure_items)
            news["whale_items"] = whale_items
            news["figure_items"] = figure_items
            news["fed_macro"] = fed_macro
            macro["fed_funds_rate"] = fed_macro.get("fed_funds_rate")
            macro["unemployment_rate"] = fed_macro.get("unemployment_rate")
        except Exception as e:
            # این بخش کاملاً مکمل است؛ خرابی آن نباید تحلیل اصلی را متوقف کند.
            append_changelog("INTEL_BRIEFING", None, None, str(e), {"traceback": traceback.format_exc()})
            news["intel_briefing"] = {"text": "", "voice_text": "", "has_content": False}

    market_info = global_market_intelligence()
    results = []
    unavailable = 0

    # JIT ticker strategy:
    # - prefetch only the symbols about to be analyzed;
    # - refresh again for each ~30-coin block, preventing the 45s cache from
    #   expiring before late-universe symbols are used;
    # - keep per-symbol fallback for unsupported batch exchanges.
    active_universe = [c for c in universe if not is_stable(c)]
    chunk_size = max(10, ATLAS_BATCH_TICKERS_CHUNK)

    def _analyze_one(index_coin):
        idx, coin = index_coin
        try:
            r = analyze_coin(coin, news, weights)
            return idx, coin, r, None
        except Exception as e:
            return idx, coin, None, (e, traceback.format_exc())

    indexed_results = []
    for chunk_start in range(0, len(active_universe), chunk_size):
        chunk = active_universe[chunk_start:chunk_start + chunk_size]
        _ATLAS_BATCH_TICKER_STATS["jit_batches"] += 1
        _atlas_prefetch_tickers(chunk)

        if ATLAS_ANALYSIS_WORKERS <= 1 or len(chunk) <= 1:
            chunk_outputs = [
                _analyze_one((chunk_start + offset, coin))
                for offset, coin in enumerate(chunk)
            ]
        else:
            chunk_outputs = []
            with _AtlasThreadPoolExecutor(
                max_workers=min(ATLAS_ANALYSIS_WORKERS, len(chunk)),
                thread_name_prefix="atlas-analysis",
            ) as pool:
                futures = [
                    pool.submit(_analyze_one, (chunk_start + offset, coin))
                    for offset, coin in enumerate(chunk)
                ]
                for fut in _atlas_as_completed(futures):
                    chunk_outputs.append(fut.result())

        # Preserve original universe ordering in output/reporting.
        chunk_outputs.sort(key=lambda x: x[0])
        for idx, coin, r, err in chunk_outputs:
            if err is not None:
                unavailable += 1
                exc, tb = err
                append_changelog(
                    "ASSET_ERROR", None, None,
                    f"{coin}: {exc}",
                    {"traceback": tb},
                )
            elif r and not is_stable(str(r.get("coin") or "")):
                indexed_results.append((idx, r))
            time.sleep(REQUEST_SLEEP_SECONDS)

    indexed_results.sort(key=lambda x: x[0])
    results = [r for _, r in indexed_results]

    btc_regime = btc_market_regime()
    breadth = market_breadth(results)
    results = apply_decision_engine(results, btc_regime, breadth)

    for r in results:
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
    compact = re.sub(r"\s+", " ", html or "")
    values = []

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

    for m in re.finditer(r"USDT.{0,900}?([0-9][0-9,]{5,})\s*ریال.{0,120}?([0-9][0-9,]{5,})\s*ریال", compact, re.I):
        try:
            a = float(m.group(1).replace(",", "")) / 10.0
            b = float(m.group(2).replace(",", "")) / 10.0
        except ValueError:
            continue
        vals = [x for x in (a, b) if 50000 <= x <= 1000000]
        if vals:
            return median(vals)

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
    """Read USDT/Toman once per short TTL and reuse it across the same run."""
    cached = _atlas_ttl_get(
        "usdt_toman", "public", ATLAS_USDT_TOMAN_CACHE_TTL
    )
    if cached is not None:
        return cached
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
    result = round(median([x[0] for x in candidates]), 0)
    _atlas_ttl_set("usdt_toman", "public", result)
    return result

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
    """دریافت قیمت‌های قبلی از Supabase (با Fallback به SQLite)"""
    # اولویت ۱: خواندن از Supabase. مرتب‌سازی بر اساس captured_at (نزولی) به‌عنوان
    # محافظ در برابر ردیف‌های تکراری قدیمی که پیش از اعمال upsert/UNIQUE constraint
    # ممکن است در جدول مانده باشند — با این ترتیب همیشه جدیدترین ردیف هر نماد
    # برنده می‌شود، نه یک ردیف تصادفی بسته به ترتیب پاسخ API.
    rows = STORE.select("snapshot_prices", {"select": "symbol,price,captured_at", "order": "captured_at.desc"})
    if rows and isinstance(rows, list) and len(rows) > 0:
        result = {}
        for r in rows:
            sym = str(r.get("symbol", "")).upper()
            price = f(r.get("price"))
            if sym and price is not None and sym not in result:
                result[sym] = price
        print(f"📊 Loaded {len(result)} previous prices from Supabase")
        return result
    
    # Fallback به SQLite (برای اجرای محلی)
    try:
        con = sqlite3.connect(DB_FILE, timeout=10)
        try:
            rows = con.execute("select symbol, price from snapshot_prices").fetchall()
            result = {str(sym).upper(): float(price) for sym, price in rows if price is not None}
            print(f"📊 Loaded {len(result)} previous prices from SQLite (fallback)")
            return result
        finally:
            con.close()
    except Exception as e:
        print(f"⚠️ Snapshot previous prices error (SQLite): {e}")
        return {}


def _snapshot_direction(current, previous):
    """تشخیص جهت تغییر قیمت نسبت به قیمت قبلی (فال‌بک)"""
    current = f(current)
    previous = f(previous)
    if current is None or previous is None or previous <= 0:
        return "➡️"
    delta_pct = (current - previous) / previous * 100.0
    if abs(delta_pct) < SNAPSHOT_FLAT_THRESHOLD_PCT:
        return "➡️"
    return "⬆️" if delta_pct > 0 else "⬇️"


def _get_snapshot_arrow(price, previous_price, change24=None):
    """
    تعیین فلش جهت تغییر قیمت با اولویت تغییرات ۲۴ ساعته.
    اگر change24 موجود باشد، بر اساس آن و آستانه‌ی SNAPSHOT_24H_THRESHOLD_PCT تصمیم‌گیری می‌شود.
    در غیر این صورت به _snapshot_direction فال‌بک می‌شود.
    """
    if change24 is not None:
        if abs(change24) < SNAPSHOT_24H_THRESHOLD_PCT:
            return "➡️"
        return "⬆️" if change24 > 0 else "⬇️"
    return _snapshot_direction(price, previous_price)


def _save_snapshot_prices(results, captured_at):
    """ذخیره آخرین قیمت‌ها در Supabase (با Fallback به SQLite) — فقط جدیدترین مقدار.

    از upsert واقعی استفاده می‌کند (نه insert ساده) تا هر نماد دقیقاً یک ردیف
    داشته باشد. نیازمند این migration یک‌باره روی جدول snapshot_prices در
    Supabase (اگر قبلاً این constraint وجود ندارد):

        alter table snapshot_prices
            add constraint snapshot_prices_symbol_key unique (symbol);
    """
    saved_count = 0
    for r in results or []:
        sym = str(r.get("coin") or "").upper()
        price = f(r.get("price"))
        if sym and price is not None and price > 0:
            # تلاش برای upsert در Supabase (یک ردیف به‌ازای هر نماد)
            success = STORE.upsert(
                "snapshot_prices",
                {
                    "symbol": sym,
                    "price": price,
                    "captured_at": captured_at,
                },
                on_conflict="symbol",
            )
            if success:
                saved_count += 1
            else:
                # Fallback به SQLite
                try:
                    con = sqlite3.connect(DB_FILE, timeout=10)
                    try:
                        con.execute(
                            "insert into snapshot_prices(symbol,price,captured_at) values(?,?,?) "
                            "on conflict(symbol) do update set price=excluded.price,captured_at=excluded.captured_at",
                            (sym, price, captured_at),
                        )
                        con.commit()
                        saved_count += 1
                    finally:
                        con.close()
                except Exception as e:
                    print(f"⚠️ Snapshot save error (SQLite): {e}")
    
    print(f"📊 Saved {saved_count} prices to Supabase (and fallback)")


def _save_snapshot_history(results, captured_at):
    """Append-only snapshot history with batched Supabase + SQLite writes."""
    rows_to_save = []
    sqlite_rows = []
    for r in results or []:
        sym = str(r.get("coin") or "").upper()
        price = f(r.get("price"))
        if not sym or price is None or price <= 0:
            continue
        rows_to_save.append({
            "symbol": sym,
            "price": price,
            "captured_at": captured_at,
        })
        sqlite_rows.append((sym, price, captured_at))

    saved_count = 0
    if rows_to_save:
        if hasattr(STORE, "insert_many") and STORE.insert_many(
            "snapshot_price_history", rows_to_save
        ):
            saved_count = len(rows_to_save)
        else:
            # Compatibility fallback if batch API is unavailable.
            for row in rows_to_save:
                if STORE.insert("snapshot_price_history", row):
                    saved_count += 1

    if sqlite_rows:
        try:
            con = sqlite3.connect(DB_FILE, timeout=10)
            try:
                con.executemany(
                    "insert into snapshot_price_history(symbol,price,captured_at) values(?,?,?)",
                    sqlite_rows,
                )
                con.commit()
            finally:
                con.close()
        except Exception as e:
            print(f"⚠️ Snapshot history save error (SQLite batch): {e}")

    print(
        f"📊 Saved {saved_count} rows to snapshot_price_history (Supabase); "
        f"SQLite mirror batch attempted for {len(sqlite_rows)} rows"
    )


def _lookup_history_price(symbol, target_dt):
    """نزدیک‌ترین قیمتِ ثبت‌شده در یا پیش از target_dt را برمی‌گرداند (یا None)."""
    sym = str(symbol).upper()
    target_iso = target_dt.isoformat()
    rows = STORE.select(
        "snapshot_price_history",
        {
            "select": "price,captured_at",
            "symbol": f"eq.{sym}",
            "captured_at": f"lte.{target_iso}",
            "order": "captured_at.desc",
            "limit": "1",
        },
    )
    if rows:
        p = f(rows[0].get("price"))
        if p is not None:
            return p
    try:
        con = sqlite3.connect(DB_FILE, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute(
                "select price from snapshot_price_history where symbol=? and captured_at<=? "
                "order by captured_at desc limit 1",
                (sym, target_iso),
            ).fetchone()
            return f(row["price"]) if row else None
        finally:
            con.close()
    except Exception:
        return None


def build_price_snapshot(results, updated_at=None, previous_prices=None):
    """
    FIX (reported bug): every row showed ➡️ regardless of the real price move.
    Root cause: this function read r.get("change24"), but analyze_coin()/_metal_analysis()
    never set that key — the 24H change is stored under r.get("change"). So change24 was
    always None, _get_snapshot_arrow() always fell through to the SQLite/Supabase
    "previous run" comparison, and — since that comparison table was either empty
    (first run / ephemeral CI filesystem) or a plain-insert into a primary-keyed
    Supabase table silently failing — previous_price was usually also None, so the
    arrow defaulted to ➡️ every time.

    Now: arrow direction prefers a real 4H-ago price from the new
    snapshot_price_history table (see _lookup_history_price), falls back to the
    ticker's own 24H change (r.get("change"), the correct key) if no 4H history
    exists yet, and only falls back to the old "previous run" comparison as a last
    resort. The 24H change percentage is also shown next to price.
    """
    by_coin = {str(r.get("coin") or "").upper(): r for r in (results or [])}
    dt = updated_at or now_tehran()

    if previous_prices is None:
        previous_prices = _snapshot_previous_prices()

    four_hours_ago = dt.astimezone(timezone.utc) - timedelta(hours=4)

    weekdays = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")
    lines = [
        f"📅 {weekdays[dt.weekday()]} | {shamsi(dt)}",
        "",
        f"⏰ آخرین بروزرسانی : {dt.strftime('%H:%M:%S')}",
        "",
        "📊 وضعیت بازار ارزهای دیجیتال:",
        "───────────────────",
    ]

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

        change24 = f(r.get("change"))  # FIX: was r.get("change24"), a key nothing ever set

        price_4h_ago = _lookup_history_price(sym, four_hours_ago)
        if price_4h_ago is not None:
            arrow = _snapshot_direction(price, price_4h_ago)
        else:
            arrow = _get_snapshot_arrow(price, previous_prices.get(sym), change24)
        arrow_stats[arrow] = arrow_stats.get(arrow, 0) + 1

        change_text = f"  ({change24:+.2f}%)" if change24 is not None else ""
        lines.append(f"🔹 {arrow}{sym:<6}:   {_snapshot_price_text(price)}{change_text}")

    print(f"📊 Arrow stats: ⬆️={arrow_stats.get('⬆️', 0)}, ⬇️={arrow_stats.get('⬇️', 0)}, ➡️={arrow_stats.get('➡️', 0)}")

    lines.append("───────────────────")
    usdt = fetch_usdt_toman_public()
    if usdt is None:
        lines.append("💵 🟡نرخ تتر  :   در دسترس نیست")
    else:
        lines.append(f"💵 🟢نرخ تتر  :   {usdt:,.0f} تومان")
    lines.append("🔄 این پیام هر ۳ ساعت بروزرسانی می‌شود")

    session, session_label, session_multiplier = get_current_session()
    lines.append(f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")
    return "\n".join(lines)


def send_price_snapshot(results):
    """Send snapshot separately; persist comparison state only after successful delivery."""
    captured_at = now_tehran().isoformat()
    # History is saved unconditionally (not gated on Telegram delivery) since it's
    # just data collection for future 4H/24H lookups — a failed Telegram send
    # shouldn't cost us a data point.
    _save_snapshot_history(results, captured_at)
    previous = _snapshot_previous_prices()
    payload = build_price_snapshot(results, previous_prices=previous)
    parts, sent, errors = send_report(payload)
    if sent == parts and sent > 0:
        _save_snapshot_prices(results, captured_at)
    return sent, errors

def _automatic_run_plan(now=None):
    """Unified ATLAS scheduler.

    Production scheduling is owned by GitHub Actions.  A real GitHub
    ``schedule`` event always executes the complete ATLAS cycle
    (ANALYSIS + SNAPSHOT), regardless of runner start delay.

    ``workflow_dispatch`` continues to honor the selected ATLAS_RUN_MODE.
    Legacy local AUTO scheduling remains available when GitHub does not
    own the cadence.
    """
    cadence = os.environ.get("ATLAS_SCHEDULED_CADENCE", "").strip().lower()
    mode = os.environ.get("ATLAS_RUN_MODE", "AUTO").strip().upper()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip().lower()

    if cadence == "workflow":
        # ---------------------------------------------------------
        # GitHub scheduled event: ALWAYS run the complete cycle.
        # Do not inspect the local clock and do not depend on the
        # exact cron minute. GitHub has already triggered the job.
        # ---------------------------------------------------------
        if event_name == "schedule":
            return {"analysis": True, "snapshot": True}

        # ---------------------------------------------------------
        # Manual workflow_dispatch: honor the user's selection.
        # ---------------------------------------------------------
        if mode == "ANALYSIS":
            return {"analysis": True, "snapshot": False}
        if mode == "SNAPSHOT":
            return {"analysis": False, "snapshot": True}
        if mode == "BOTH":
            return {"analysis": True, "snapshot": True}

        # If the workflow is configured for workflow cadence but the
        # event metadata is unavailable, BOTH is the safest production
        # fallback because the workflow itself is the scheduler.
        return {"analysis": True, "snapshot": True}

    # Legacy/manual AUTO scheduling remains available.
    dt = now or now_tehran()
    return {
        "analysis": dt.hour % 4 == 0,
        "snapshot": dt.hour % 3 == 0,
    }



TA_QUALITY = float(os.environ.get("ATLAS_V11_MIN_DATA_QUALITY", "70"))
ATLAS_V11_MIN_RR = float(os.environ.get("ATLAS_V11_MIN_RR", "2.0"))
ATLAS_V11_MAX_CORR = float(os.environ.get("ATLAS_V11_MAX_CORR", "0.85"))
ATLAS_V11_MAX_CONCENTRATION = float(os.environ.get("ATLAS_V11_MAX_CONCENTRATION", "0.65"))

def _v11_num(v, default=None):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default

def _v11_clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))

def v11_portfolio_diagnostics(results):
    """Concentration check across executable opportunities.
    FIX: previously read 'v11_opportunity_score', a field no live code populated
    (it was written only by an earlier v11.1 apply_intelligence implementation that
    had been silently shadowed by a later redefinition of the same function name).
    That made this diagnostic a permanent no-op. It now reads the fields the live
    v11.3 intelligence engine (v11_apply_intelligence) actually sets: 'opportunity_score'
    and 'executable'.
    """
    active = [r for r in results if r.get("executable")]
    weights = {str(r.get("coin", "")).upper(): max(0, _v11_num(r.get("opportunity_score"), 0)) for r in active}
    total = sum(weights.values())
    concentration = {k: round(v / total, 3) for k, v in weights.items()} if total else {}
    warning = "HIGH_CONCENTRATION" if any(v >= ATLAS_V11_MAX_CONCENTRATION for v in concentration.values()) else None
    return {"concentration": concentration, "warning": warning, "high_correlation_pairs": []}


# ============================================================
# BUILD FULL TABLE REPORT
# ============================================================

def build_full_table_report(results, top10_symbols=None, dynamic30_symbols=None):
    """
    ساخت گزارش کامل جدولی با تمام بخش‌ها - اما این تابع دیگر در خروجی نهایی ارسال نمی‌شود
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


def build_signal_ranking_table(results, top10_symbols=None, dynamic30_symbols=None):
    """ساخت جدول رتبه‌بندی کامل سیگنال‌ها - این تابع دیگر در خروجی نهایی ارسال نمی‌شود"""
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("📊 ATLAS SIGNAL RANKING")
    lines.append("━━━━━━━━━━━━━━━━━━")
    
    signal_rows = []
    for r in results:
        action = str(r.get("action") or "").upper()
        if action in ("BUY CONFIRMATION", "SELL CONFIRMATION", "BUY", "SELL"):
            quality = (r.get("confidence", 0) * 0.5) + (min(r.get("rr", 0) or 0, 5) * 15)
            signal_rows.append((quality, r))
    
    signal_rows.sort(key=lambda x: x[0], reverse=True)
    top10_signals = signal_rows[:10]
    
    if top10_signals:
        lines.append("┌──────┬──────────┬──────────┬──────────┬──────────┬──────────┐")
        lines.append("│ #    │ ASSET    │ DIRECTION│ CONFID   │ R/R      │ QUALITY  │")
        lines.append("├──────┼──────────┼──────────┼──────────┼──────────┼──────────┤")
        
        for i, (quality, r) in enumerate(top10_signals, 1):
            coin = r.get("coin", "UNKNOWN")[:8]
            action = str(r.get("action") or "").upper()
            direction = "🟢 BUY" if "BUY" in action else "🔴 SELL"
            conf = r.get("confidence", 0)
            rr = r.get("rr", 0)
            
            lines.append(f"│ {i:>2}   │ {coin:<8} │ {direction:<8} │ {conf:>6}%   │ {rr:>6.2f}  │ {quality:>6.0f}%  │")
        
        lines.append("└──────┴──────────┴──────────┴──────────┴──────────┴──────────┘")
    else:
        lines.append("⚪ هیچ سیگنال تأییدشده‌ای وجود ندارد")
    
    return "\n".join(lines)



def send_image_table(results, top10_symbols=None, dynamic30_symbols=None):
    """ارسال جدول تصویری به تمام مقاصد تلگرام"""
    if not ENABLE_IMAGE_TABLE:
        print("ℹ️ Image table disabled by ATLAS_ENABLE_IMAGE_TABLE")
        return False
    
    filename = build_image_table(results, top10_symbols, dynamic30_symbols)
    if not filename or not os.path.exists(filename):
        return False
    
    if not TELEGRAM_TOKEN:
        return False
    
    with open(filename, 'rb') as f:
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
        os.unlink(filename)
    except:
        pass
    
    return success_count > 0


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



# ============================================================
# ATLAS v11.4 — INTELLIGENCE / DECISION REDESIGN
# ============================================================
# This layer intentionally sits above the legacy collectors and execution
# plumbing. It reuses the existing OHLCV, multi-timeframe, S/R, volume,
# liquidity, news, derivatives, Telegram, CSV, PNG and voice infrastructure,
# but replaces the old "mostly hard-gates" presentation with:
#   1) evidence-based scoring,
#   2) explicit market regime,
#   3) setup classification,
#   4) conditional triggers,
#   5) contradiction analysis,
#   6) scenario map,
#   7) opportunity ranking,
#   8) portfolio-aware actions.
#
# IMPORTANT: "confidence" is a model score, NOT a calibrated win probability.
# No order is placed by ATLAS.
# ============================================================

# FIX: this used to reassign VERSION = "ATLAS v11.4 INTELLIGENCE ENGINE" here,
# silently overriding the VERSION set at the top of the file for the rest of
# the module (the exact same "two definitions, last one wins silently" bug
# this whole pass has been fixing elsewhere). There is now exactly one
# VERSION, declared once at the top of the file.
ATLAS_INTELLIGENCE_VERSION = VERSION
ATLAS_MIN_INTEL_SCORE = float(os.environ.get("ATLAS_MIN_INTEL_SCORE", "58"))
ATLAS_EXECUTABLE_SCORE = float(os.environ.get("ATLAS_EXECUTABLE_SCORE", "72"))
ATLAS_BREAKOUT_VOLUME = float(os.environ.get("ATLAS_BREAKOUT_VOLUME", "1.15"))
ATLAS_NEAR_LEVEL_ATR = float(os.environ.get("ATLAS_NEAR_LEVEL_ATR", "0.60"))
ATLAS_IMAGE_ROWS = int(os.environ.get("ATLAS_IMAGE_ROWS", "10"))

def _i_num(x, default=0.0):
    v = f(x)
    return default if v is None or not math.isfinite(v) else float(v)

def _i_dir(x):
    s = str(x or "").upper()
    if any(k in s for k in ("BULL", "UP", "LONG", "BUY")):
        return "LONG"
    if any(k in s for k in ("BEAR", "DOWN", "SHORT", "SELL")):
        return "SHORT"
    return "NEUTRAL"

def _i_sign(x):
    return 1 if x == "LONG" else -1 if x == "SHORT" else 0

def _i_level_distance(price, level):
    p, l = _i_num(price, None), _i_num(level, None)
    if p is None or l is None or p <= 0:
        return None
    return abs(p-l)/p*100.0

def _i_setup(r):
    """Classify the market structure rather than reducing it to BUY/SELL."""
    direction = _i_dir(r.get("direction"))
    trigger = r.get("candle_trigger") or {}
    state = str(trigger.get("state") or "").upper()
    price = _i_num(r.get("price"), None)
    support = _i_num(r.get("support"), None)
    resistance = _i_num(r.get("resistance"), None)
    vr = _i_num(r.get("volume_ratio"), 0)
    pattern = str(r.get("pattern") or "").upper()
    atrp = _i_num(r.get("atr_pct"), 0)

    if state in ("BREAKOUT_CLOSED", "BREAKDOWN_CLOSED"):
        return "BREAKOUT" if state == "BREAKOUT_CLOSED" else "BREAKDOWN"
    if state in ("SUPPORT_RECLAIM", "RESISTANCE_REJECT"):
        return "PULLBACK" if state == "SUPPORT_RECLAIM" else "REVERSAL"
    if direction in ("LONG", "SHORT") and vr >= ATLAS_BREAKOUT_VOLUME:
        if direction == "LONG" and resistance and price and price >= resistance*0.995:
            return "BREAKOUT WATCH"
        if direction == "SHORT" and support and price and price <= support*1.005:
            return "BREAKDOWN WATCH"
    if pattern and pattern not in ("NONE", "UNKNOWN"):
        if direction == "LONG" and "BULL" in pattern:
            return "TREND CONTINUATION"
        if direction == "SHORT" and "BEAR" in pattern:
            return "TREND CONTINUATION"
    if price and support and resistance and support < price < resistance:
        width = (resistance-support)/price*100.0
        if width > max(2.0, atrp*2.0):
            return "RANGE"
    if direction in ("LONG", "SHORT"):
        return "TREND CONTINUATION"
    return "NO SETUP"

def _i_structure_score(r):
    h1, h4, d1, w1 = map(_i_dir, (r.get("h1_trend"), r.get("h4_trend"), r.get("d1_trend"), r.get("w1_trend")))
    votes = [_i_sign(x) for x in (h1,h4,d1,w1)]
    weighted = votes[0]*0.10 + votes[1]*0.30 + votes[2]*0.35 + votes[3]*0.25
    return 50 + 50*weighted

def _i_momentum_score(r):
    score = 50.0
    ind = _i_dir(r.get("trend"))
    h4 = _i_dir(r.get("h4_trend"))
    macd_s = str(r.get("macd") or "").upper()
    rsi = _i_num(r.get("rsi"), None)
    mom30 = _i_dir(r.get("momentum_30m"))
    if ind == h4 and ind != "NEUTRAL": score += 15*_i_sign(ind)
    if "BULL" in macd_s: score += 12
    elif "BEAR" in macd_s: score -= 12
    if mom30 == "LONG": score += 6
    elif mom30 == "SHORT": score -= 6
    if rsi is not None:
        if 52 <= rsi <= 68: score += 8
        elif 45 <= rsi < 52: score += 2
        elif 68 < rsi <= 75: score += 4
        elif rsi > 75: score -= 8
        elif 32 <= rsi < 45: score -= 4
        elif rsi < 25: score += 6
    return max(0, min(100, score))

def _i_volume_score(r):
    vr = _i_num(r.get("volume_ratio"), 0)
    if vr >= 1.50: return 95
    if vr >= 1.20: return 82
    if vr >= 1.00: return 68
    if vr >= 0.60: return 52
    if vr > 0: return 35
    return 45

def _i_sr_score(r):
    price = _i_num(r.get("price"), None)
    support = _i_num(r.get("support"), None)
    resistance = _i_num(r.get("resistance"), None)
    if price is None or support is None or resistance is None or resistance <= support:
        return 45
    span = resistance-support
    if span <= 0: return 45
    pos = (price-support)/span
    # Better location: longs near support / shorts near resistance.
    d = _i_dir(r.get("direction"))
    if d == "LONG":
        return max(20, min(95, 95 - pos*65))
    if d == "SHORT":
        return max(20, min(95, 30 + pos*65))
    return 55

def _i_liquidity_score(r):
    return max(0, min(100, _i_num(r.get("liquidity_score"), 50)))

def _i_contradictions(r, bias):
    out = []
    h4, d1, w1 = map(_i_dir, (r.get("h4_trend"), r.get("d1_trend"), r.get("w1_trend")))
    rsi = _i_num(r.get("rsi"), None)
    vr = _i_num(r.get("volume_ratio"), None)
    macd = str(r.get("macd") or "").upper()
    if bias == "LONG":
        if d1 == "SHORT": out.append("D1 opposes long")
        if w1 == "SHORT": out.append("W1 opposes long")
        if "BEAR" in macd: out.append("MACD bearish")
        if rsi is not None and rsi > 75: out.append("RSI overbought")
    elif bias == "SHORT":
        if d1 == "LONG": out.append("D1 opposes short")
        if w1 == "LONG": out.append("W1 opposes short")
        if "BULL" in macd: out.append("MACD bullish")
        if rsi is not None and rsi < 25: out.append("RSI oversold")
    if vr is not None and vr < 0.60: out.append("weak volume")
    return out

def _i_bias(r):
    structure = _i_structure_score(r)
    momentum = _i_momentum_score(r)
    h4 = _i_dir(r.get("h4_trend"))
    d1 = _i_dir(r.get("d1_trend"))
    long_votes = sum(1 for x in (h4,d1,_i_dir(r.get("w1_trend"))) if x == "LONG")
    short_votes = sum(1 for x in (h4,d1,_i_dir(r.get("w1_trend"))) if x == "SHORT")
    if structure >= 58 and momentum >= 55 and long_votes >= 2: return "LONG"
    if structure <= 42 and momentum <= 45 and short_votes >= 2: return "SHORT"
    if structure >= 62: return "LONG"
    if structure <= 38: return "SHORT"
    return "NEUTRAL"


_REASON_FA_STATIC = {
    "Monthly regime contradicts signal": "روند ماهانه با سیگنال در تضاد است",
    "Data quality/conflict": "کیفیت داده یا تضاد داده",
    "Volume confirmation missing": "تأیید حجم معاملات وجود ندارد",
    "Confidence below threshold": "اطمینان سیگنال زیر آستانه لازم است",
    "Higher-timeframe alignment missing": "همسویی با تایم‌فریم‌های بالاتر وجود ندارد",
    "Weekly regime conflict; stronger confirmation required": "تضاد در روند هفتگی؛ نیاز به تأیید قوی‌تر",
    "High-impact news contradicts signal": "خبر مهم بازار با سیگنال در تضاد است",
    "30m momentum strongly opposes long": "مومنتوم ۳۰ دقیقه‌ای به‌شدت مخالف خرید است",
    "30m momentum strongly opposes short": "مومنتوم ۳۰ دقیقه‌ای به‌شدت مخالف فروش است",
    "Reliable Daily/H4 S/R not confirmed": "حمایت/مقاومت معتبر روزانه یا ۴ساعته تأیید نشده",
    "H4 S/R fallback requires elevated confidence": "سطح جایگزین ۴ساعته نیاز به اطمینان بالاتر دارد",
    "Invalid price geometry": "ساختار قیمتی (حد ضرر/سود) نامعتبر است",
    "Backtest gate failed — execution frozen (watch-only)": "گیت بک‌تست رد شد — اجرا متوقف است (فقط دیده‌بانی)",
    "H4/D1 trend conflict": "تضاد روند بین ۴ساعته و روزانه",
    "Breakout/pullback structure not confirmed": "ساختار شکست/بازگشت تأیید نشده",
    "No multi-factor confirmation yet": "هنوز تأیید چندعاملی کافی نیست",
    "D1 opposes long": "روند روزانه مخالف خرید است",
    "W1 opposes long": "روند هفتگی مخالف خرید است",
    "MACD bearish": "مکدی نزولی است",
    "RSI overbought": "RSI در اشباع خرید است",
    "D1 opposes short": "روند روزانه مخالف فروش است",
    "W1 opposes short": "روند هفتگی مخالف فروش است",
    "MACD bullish": "مکدی صعودی است",
    "RSI oversold": "RSI در اشباع فروش است",
    "weak volume": "حجم معاملات ضعیف",
}

_REASON_FA_PATTERNS = (
    (re.compile(r"^R/R ([\d.]+) below minimum ([\d.]+)$"),
     lambda m: f"نسبت ریسک‌به‌ریوارد {m.group(1)} کمتر از حداقل {m.group(2)} است"),
    (re.compile(r"^Volume ratio ([\d.]+)x below 1\.0x average$"),
     lambda m: f"نسبت حجم {m.group(1)}x کمتر از میانگین (۱x) است"),
    (re.compile(r"^Resistance too close \(([\d.]+)% away\)$"),
     lambda m: f"مقاومت خیلی نزدیک است ({m.group(1)}٪ فاصله)"),
    (re.compile(r"^Support too close \(([\d.]+)% away\)$"),
     lambda m: f"حمایت خیلی نزدیک است ({m.group(1)}٪ فاصله)"),
    (re.compile(r"^Data quality (\d+)/100 below threshold$"),
     lambda m: f"کیفیت داده {m.group(1)} از ۱۰۰، زیر آستانه است"),
    (re.compile(r"^Data quality too low: (.+)$"),
     lambda m: f"کیفیت داده بسیار پایین: {m.group(1)}"),
    (re.compile(r"^Long crowded \(high funding rate\) - (.+)$"),
     lambda m: f"ازدحام معامله‌گران خرید (نرخ فاندینگ بالا) - {m.group(1)}"),
    (re.compile(r"^Short crowded \(negative funding rate\) - (.+)$"),
     lambda m: f"ازدحام معامله‌گران فروش (نرخ فاندینگ منفی) - {m.group(1)}"),
    (re.compile(r"^High contradiction: (.+)$"),
     lambda m: f"تضاد بالا: {m.group(1)}"),
)


def translate_reason_fa(text):
    """ترجمه‌ی دلایل «چرا معامله نشد؟» به فارسی.

    این متن‌ها برخلاف عناوین اخبار، از یک واژگان بسته و از‌پیش‌شناخته‌شده
    تولید می‌شوند (نه متن آزاد) — پس یک دیکشنری/الگوی ثابت اینجا قابل‌اتکاتر،
    آنی و بدون هیچ وابستگی شبکه‌ای از فراخوانی یک API ترجمه برای هر خط
    گزارش است. هر عبارت ناشناخته بدون تغییر (انگلیسی) برمی‌گردد — fail-safe،
    نه خطا."""
    if not text:
        return text
    if " | " in text:
        return " | ".join(translate_reason_fa(p.strip()) for p in text.split(" | "))
    if text.startswith("Gate blocked: "):
        return "گیت مسدود شد: " + translate_reason_fa(text[len("Gate blocked: "):])
    if text in _REASON_FA_STATIC:
        return _REASON_FA_STATIC[text]
    for pattern, fn in _REASON_FA_PATTERNS:
        m = pattern.match(text)
        if m:
            return fn(m)
    return text


def why_not_trade(r):
    """
    Architecture review, feature request: 'WHY NOT TRADE?'. For any asset that
    isn't executable, this returns the concrete reasons — instead of the report
    just going quiet on 52 of 54 assets and leaving the user to guess whether
    ATLAS actually analyzed them or just defaulted everything to HOLD.
    """
    if r.get("executable"):
        return []
    reasons = []
    if r.get("gate") == "BLOCK" and r.get("gate_reason"):
        reasons.append(f"Gate blocked: {r['gate_reason']}")
    if not _LAST_BACKTEST_OK:
        reasons.append("Backtest gate failed — execution frozen (watch-only)")

    rr = _i_num(r.get("rr"), None)
    if rr is not None and rr < ATLAS_V11_MIN_RR:
        reasons.append(f"R/R {rr:.2f} below minimum {ATLAS_V11_MIN_RR:.1f}")

    vr = _i_num(r.get("volume_ratio"), None)
    if vr is not None and vr < 1.0:
        reasons.append(f"Volume ratio {vr:.2f}x below 1.0x average")

    h4 = _i_dir(r.get("h4_trend")); d1 = _i_dir(r.get("d1_trend"))
    if h4 != "NEUTRAL" and d1 != "NEUTRAL" and h4 != d1:
        reasons.append("H4/D1 trend conflict")

    for c in (r.get("contradictions") or []):
        if c not in reasons:
            reasons.append(c)

    price = _i_num(r.get("price"), None)
    res = _i_num(r.get("resistance"), None)
    sup = _i_num(r.get("support"), None)
    if price and res and res > price:
        dist = (res - price) / price * 100
        if dist < 0.5:
            reasons.append(f"Resistance too close ({dist:.2f}% away)")
    if price and sup and price > sup:
        dist = (price - sup) / price * 100
        if dist < 0.5:
            reasons.append(f"Support too close ({dist:.2f}% away)")

    setup = str(r.get("setup_type") or "")
    if setup in ("", "NO SETUP"):
        reasons.append("Breakout/pullback structure not confirmed")

    dq = _i_num(r.get("data_quality"), None)
    if dq is not None and dq < 70:
        reasons.append(f"Data quality {dq:.0f}/100 below threshold")

    if not reasons:
        reasons.append("No multi-factor confirmation yet")
    return reasons

# NOTE: _i_regime() used to live here — a second, independent regime computation
# that collided with RegimeEngine() (see Stage 2 in analyze_coin). Removed; the
# canonical regime dict is now read from r["regime"]["engine"] instead. See
# v11_apply_intelligence() for where it's consumed.

def _i_trigger(r):
    p = _i_num(r.get("price"), None)
    s = _i_num(r.get("support"), None)
    res = _i_num(r.get("resistance"), None)
    atrp = _i_num(r.get("atr_pct"), 0)
    pad = max(0.10, atrp*0.15)
    if p is None: return {}
    return {
        "long": round(res*(1+pad/100), 8) if res else None,
        "short": round(s*(1-pad/100), 8) if s else None,
        "support": s, "resistance": res,
    }

def _i_scenario(r):
    p = _i_num(r.get("price"), None)
    s = _i_num(r.get("support"), None)
    res = _i_num(r.get("resistance"), None)
    bias = r.get("intel_bias","NEUTRAL")
    trig = r.get("intel_trigger") or {}
    scenarios = []
    if p is not None and res is not None:
        scenarios.append(("BULL", "LONG", trig.get("long"), f"4H close above {fmt(trig.get('long')) if trig.get('long') else fmt(res)}"))
    if p is not None and s is not None:
        scenarios.append(("BEAR", "SHORT", trig.get("short"), f"4H close below {fmt(trig.get('short')) if trig.get('short') else fmt(s)}"))
    if bias == "LONG":
        base = "Bull case has the stronger structural edge."
    elif bias == "SHORT":
        base = "Bear case has the stronger structural edge."
    else:
        base = "No directional edge; wait for a range break."
    return scenarios, base

def _i_reason(r):
    parts = []
    bias = r.get("intel_bias","NEUTRAL")
    if r.get("structure_score",50) >= 65: parts.append("HTF structure bullish")
    elif r.get("structure_score",50) <= 35: parts.append("HTF structure bearish")
    if r.get("momentum_score",50) >= 65: parts.append("momentum supportive")
    elif r.get("momentum_score",50) <= 35: parts.append("momentum weak")
    if r.get("volume_score",50) >= 75: parts.append("volume expansion")
    elif r.get("volume_score",50) < 50: parts.append("volume thin")
    setup = r.get("setup_type","NO SETUP")
    if setup != "NO SETUP": parts.append(setup.replace("_"," ").lower())
    c = r.get("contradictions") or []
    if c: parts.append("conflict: " + ", ".join(c[:2]))
    return "؛ ".join(parts) or ("neutral structure" if bias == "NEUTRAL" else "mixed evidence")

def _i_quality(r):
    return _i_num(r.get("data_quality"), 50)

def _i_score(r):
    structure = _i_num(r.get("structure_score"),50)
    momentum = _i_num(r.get("momentum_score"),50)
    volume = _i_num(r.get("volume_score"),50)
    sr = _i_num(r.get("sr_score"),50)
    liq = _i_num(r.get("liquidity_score"),50)
    dataq = _i_quality(r)
    regime = _i_num(r.get("regime_score"),50)
    contradiction = len(r.get("contradictions") or [])
    # Evidence score is deliberately independent from hard trade gates.
    score = (
        structure*0.28 + momentum*0.22 + volume*0.12 + sr*0.12 +
        liq*0.08 + dataq*0.10 + regime*0.08
    )
    score -= min(18, contradiction*5)
    return max(0, min(100, score))

def _i_opportunity(r):
    score = _i_num(r.get("intel_score"),50)
    rr = _i_num(r.get("rr"), 0)
    setup = str(r.get("setup_type") or "")
    setup_bonus = 10 if setup in ("BREAKOUT","BREAKDOWN","PULLBACK","REVERSAL","BREAKOUT WATCH","BREAKDOWN WATCH") else 3
    rr_bonus = min(12, max(0, rr-1.0)*5)
    if str(r.get("regime_volatility")) == "EXTREME": setup_bonus -= 8
    return round(max(0,min(100,score*0.72 + setup_bonus + rr_bonus)),1)

# ============================================================
# CALIBRATION ENGINE — isotonic win-probability calibration
# ============================================================
# Pure-Python implementation (no numpy/sklearn dependency) of the
# Pool-Adjacent-Violators Algorithm for isotonic regression, mapping
# signal_score -> historically observed win rate.
#
# Sample-size tiers (per architecture review — same tiers gate
# self_diagnostic()'s automatic weight adjustment):
#   < 100 closed outcomes  -> NOT_CALIBRATED, no probability shown
#   100-300                -> CAUTIOUS
#   300-1000               -> ADAPTIVE
#   1000+                  -> ROBUST
# NOTE: this draws from the same signal_outcomes table self_diagnostic()
# uses. That is a real limitation flagged in the architecture review (a
# fully separate calibration/training split would need a second, held-out
# outcome stream) — the tiers here reduce but don't eliminate that risk.

def _calibration_tier(n):
    if n < 100: return "NOT_CALIBRATED"
    if n < 300: return "CAUTIOUS"
    if n < 1000: return "ADAPTIVE"
    return "ROBUST"


def _pava_isotonic(pairs):
    """pairs: [(x, y in {0,1}), ...] sorted ascending by x.
    Returns [(x_min, x_max, fitted_y), ...] blocks, non-decreasing in y."""
    if not pairs:
        return []
    blocks = [[y, 1, x, x] for x, y in pairs]
    i = 0
    while i < len(blocks) - 1:
        avg_i = blocks[i][0] / blocks[i][1]
        avg_next = blocks[i + 1][0] / blocks[i + 1][1]
        if avg_i > avg_next:
            merged = [blocks[i][0] + blocks[i + 1][0], blocks[i][1] + blocks[i + 1][1],
                      blocks[i][2], blocks[i + 1][3]]
            blocks[i:i + 2] = [merged]
            i = max(0, i - 1)
        else:
            i += 1
    return [(b[2], b[3], b[0] / b[1]) for b in blocks]


def _apply_isotonic(curve, x):
    if not curve:
        return None
    if x <= curve[0][0]:
        return curve[0][2]
    if x >= curve[-1][1]:
        return curve[-1][2]
    for lo, hi, y in curve:
        if lo <= x <= hi:
            return y
    for k in range(len(curve) - 1):
        if curve[k][1] < x < curve[k + 1][0]:
            y0, y1 = curve[k][2], curve[k + 1][2]
            x0, x1 = curve[k][1], curve[k + 1][0]
            frac = (x - x0) / (x1 - x0) if x1 > x0 else 0
            return y0 + frac * (y1 - y0)
    return curve[-1][2]


_CALIBRATION_CACHE = {"curve": None, "n": 0, "tier": "NOT_CALIBRATED", "built": False}


def _build_calibration_curve():
    """Builds (once per process run) the isotonic score->win-rate curve from
    CLOSED signal_outcomes that have a recorded signal_score."""
    if _CALIBRATION_CACHE["built"]:
        return _CALIBRATION_CACHE
    init_sqlite()
    with sqlite_conn() as c:
        rows = c.execute(
            "select signal_score, outcome from signal_outcomes "
            "where status='CLOSED' and signal_score is not null and outcome in ('TP','SL')"
        ).fetchall()
    pairs = sorted(
        ((float(row["signal_score"]), 1.0 if row["outcome"] == "TP" else 0.0) for row in rows),
        key=lambda p: p[0],
    )
    n = len(pairs)
    tier = _calibration_tier(n)
    curve = _pava_isotonic(pairs) if tier != "NOT_CALIBRATED" else None
    _CALIBRATION_CACHE.update({"curve": curve, "n": n, "tier": tier, "built": True})
    return _CALIBRATION_CACHE


def win_probability_for_score(score):
    """Returns (probability_pct_or_None, tier, sample_size)."""
    cal = _build_calibration_curve()
    if cal["tier"] == "NOT_CALIBRATED" or not cal["curve"]:
        return None, cal["tier"], cal["n"]
    p = _apply_isotonic(cal["curve"], float(score))
    return (round(p * 100, 1) if p is not None else None), cal["tier"], cal["n"]



# ============================================================
# FINAL DECISION-SUPPORT LAYER
# ============================================================
# This layer is deliberately advisory: it ranks the quality and
# actionability of a setup without changing the existing BUY/SELL
# gate semantics. The price-arrow/snapshot architecture is untouched.
# ============================================================

def _ds_clamp(value, low=0.0, high=100.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _ds_direction_alignment(r):
    """Measure agreement between asset direction and market/regime evidence."""
    direction = str(r.get("direction") or "").upper()
    regime_bias = str(r.get("regime_bias") or "").upper()
    regime_trend = str(r.get("regime_trend") or "").upper()
    score = 50.0

    if direction == "LONG":
        if regime_bias in ("BULLISH", "LONG", "RISK_ON"):
            score += 25
        elif regime_bias in ("BEARISH", "SHORT", "RISK_OFF"):
            score -= 25
        if regime_trend in ("UP", "BULLISH", "TRENDING_UP"):
            score += 15
        elif regime_trend in ("DOWN", "BEARISH", "TRENDING_DOWN"):
            score -= 15
    elif direction == "SHORT":
        if regime_bias in ("BEARISH", "SHORT", "RISK_OFF"):
            score += 25
        elif regime_bias in ("BULLISH", "LONG", "RISK_ON"):
            score -= 25
        if regime_trend in ("DOWN", "BEARISH", "TRENDING_DOWN"):
            score += 15
        elif regime_trend in ("UP", "BULLISH", "TRENDING_UP"):
            score -= 15

    return _ds_clamp(score)


def _ds_trigger_quality(r):
    """Score the quality of the actual market trigger, not just oscillator state."""
    trigger = str(r.get("intel_trigger") or (r.get("candle_trigger") or {}).get("state") or "").upper()
    strong = {
        "BREAKOUT_CLOSED", "BREAKDOWN_CLOSED",
        "SUPPORT_RECLAIM", "RESISTANCE_REJECT",
        "BREAKOUT", "BREAKDOWN",
    }
    weak = {"NONE", "NO_TRIGGER", "RANGE", "UNKNOWN", ""}
    if trigger in strong:
        return 90.0
    if trigger in weak:
        return 40.0
    return 65.0


def _ds_data_quality(r):
    """Aggregate evidence completeness into a single auditable score."""
    q = _ds_clamp(_i_quality(r))
    required = ("price", "atr", "rsi", "macd", "volume_ratio")
    present = sum(r.get(k) is not None for k in required)
    completeness = present / len(required) * 100.0
    return round(q * 0.65 + completeness * 0.35, 1)


def decision_support_score(r):
    """
    Final ranking score for the decision-support layer.

    It is NOT a probability and does not replace apply_decision_engine().
    It answers: 'How actionable is this setup right now, given evidence,
    risk geometry, trigger quality, regime alignment and data quality?'
    """
    signal = _ds_clamp(r.get("signal_score", r.get("intel_score", 50)))
    opportunity = _ds_clamp(r.get("opportunity_score", 50))
    alignment = _ds_direction_alignment(r)
    trigger = _ds_trigger_quality(r)
    dataq = _ds_data_quality(r)

    rr = _i_num(r.get("rr"), 0.0) or 0.0
    rr_quality = _ds_clamp(rr / 3.0 * 100.0)

    contradictions = len(r.get("contradictions") or [])
    contradiction_penalty = min(25.0, contradictions * 6.0)

    # Evidence and actionability are intentionally separate from win probability.
    score = (
        signal * 0.28
        + opportunity * 0.22
        + alignment * 0.15
        + trigger * 0.12
        + rr_quality * 0.13
        + dataq * 0.10
        - contradiction_penalty
    )
    return round(_ds_clamp(score), 1)


def build_decision_support(r):
    """Attach an auditable decision-support packet to an asset result."""
    score = decision_support_score(r)
    direction = str(r.get("direction") or "").upper()
    action = str(r.get("action") or r.get("decision_state") or "NO TRADE").upper()
    win_prob = r.get("win_probability")

    if action in ("BUY CONFIRMATION", "SELL CONFIRMATION", "BUY", "SELL") and score >= 75:
        verdict = "EXECUTABLE_CANDIDATE"
    elif score >= 68 and direction in ("LONG", "SHORT"):
        verdict = "WATCH_HIGH_PRIORITY"
    elif score >= 55:
        verdict = "WATCH"
    else:
        verdict = "WAIT"

    r["decision_support_score"] = score
    r["decision_support"] = {
        "verdict": verdict,
        "signal_evidence": round(_ds_clamp(r.get("signal_score", r.get("intel_score", 50))), 1),
        "opportunity": round(_ds_clamp(r.get("opportunity_score", 50)), 1),
        "regime_alignment": round(_ds_direction_alignment(r), 1),
        "trigger_quality": round(_ds_trigger_quality(r), 1),
        "risk_geometry": round(_ds_clamp((_i_num(r.get("rr"), 0.0) or 0.0) / 3.0 * 100.0), 1),
        "data_quality": _ds_data_quality(r),
        "contradictions": len(r.get("contradictions") or []),
        "calibrated_win_probability": win_prob,
    }
    return r


def v11_apply_intelligence(r):
    """New evidence engine. It never claims its score is a win probability.

    FIX: this function used to overwrite r["confidence"], r["regime_trend"],
    r["regime_volatility"] in place. Those same field names were already set
    earlier by analyze_coin()/apply_decision_engine() with a different meaning
    (the weighted candle/RSI/MACD/volume score that actually gated BUY/SELL
    CONFIRMATION vs WATCH). Overwriting them meant the confidence number shown
    in the final report was never the number that produced the decision —
    and the original value was gone, so it couldn't even be audited afterward.
    The original values are now preserved under decision_* keys before being
    replaced, so both are visible: decision_confidence/decision_regime_* is
    "why the trade engine acted", confidence/regime_* (below) is "how strong
    the evidence looks under the intel model".
    """
    r["decision_confidence"] = r.get("confidence")
    r["decision_regime_trend"] = r.get("regime_trend")
    r["decision_regime_volatility"] = r.get("regime_volatility")

    q = _i_quality(r)
    structure = _i_structure_score(r)
    momentum = _i_momentum_score(r)
    volume = _i_volume_score(r)
    sr = _i_sr_score(r)
    liq = _i_liquidity_score(r)
    bias = _i_bias(r)
    # FIX: this used to call _i_regime(r, ...) here, a second, independent regime
    # computation that then overwrote regime_trend/regime_volatility — the exact
    # collision described in the architecture review. There is now exactly one
    # regime computation (RegimeEngine, called once inside analyze_coin's Stage 2)
    # and its output is stored on r["regime"]["engine"]. This just reads it.
    regime = (r.get("regime") or {}).get("engine") or {
        "regime": r.get("regime_trend", "RANGE"), "score": _i_num(r.get("regime_score"), 50),
        "trend": "NEUTRAL", "volatility": r.get("regime_volatility", "NORMAL"),
        "participation": "NORMAL", "derivatives": r.get("regime_derivatives", "UNAVAILABLE"),
        "market_bias": "NEUTRAL",
    }
    r["intel_bias"] = bias
    r["structure_score"] = round(structure,1)
    r["momentum_score"] = round(momentum,1)
    r["volume_score"] = round(volume,1)
    r["sr_score"] = round(sr,1)
    r["liquidity_score_canonical"] = round(liq,1)
    r["intel_regime"] = regime
    # NOTE: regime_trend / regime_volatility are intentionally left untouched here —
    # they were already set once, correctly, by analyze_coin(). No second write.
    r["regime_participation"] = regime["participation"]
    r["regime_bias"] = regime["market_bias"]
    r["intel_trigger"] = _i_trigger(r)
    r["setup_type"] = _i_setup(r)
    r["contradictions"] = _i_contradictions(r, bias)
    r["intel_score"] = round(_i_score(r),1)
    # Preserve the confidence that actually produced the decision.  Intelligence
    # strength is a separate field and must never overwrite decision confidence.
    decision_conf = r.get("decision_confidence")
    if decision_conf is not None:
        try:
            r["confidence"] = int(round(float(decision_conf)))
        except (TypeError, ValueError):
            pass
    r["confidence_label"] = "DECISION CONFIDENCE"
    # ------------------------------------------------------------------
    # Three-way score separation (architecture review, point 1):
    #   signal_score    = raw technical evidence strength (0-100)
    #   model_strength  = how strong/decisive the read is (0-100, not a
    #                      probability — high near either extreme, low
    #                      near 50)
    #   win_probability = calibrated historical win rate for this score,
    #                      or None if too few closed trades exist yet
    # These used to be conflated under a single "confidence" number.
    # ------------------------------------------------------------------
    r["signal_score"] = r["intel_score"]
    r["model_strength"] = r["confidence"]
    win_prob, cal_tier, cal_n = win_probability_for_score(r["signal_score"])
    r["win_probability"] = win_prob
    r["win_probability_tier"] = cal_tier
    r["win_probability_samples"] = cal_n
    r["opportunity_score"] = _i_opportunity(r)
    # Preserve executable status from the validated legacy trade engine.
    legacy_action = str(r.get("action") or r.get("decision_state") or "NO TRADE").upper()
    executable = legacy_action in ("BUY CONFIRMATION","SELL CONFIRMATION","BUY","SELL") and r.get("gate") == "PASS"
    r["executable"] = bool(executable)
    if executable:
        r["intel_decision"] = "BUY" if "BUY" in legacy_action else "SELL"
    elif r["opportunity_score"] >= ATLAS_MIN_INTEL_SCORE and bias != "NEUTRAL":
        r["intel_decision"] = "WATCH LONG" if bias == "LONG" else "WATCH SHORT"
    else:
        r["intel_decision"] = "WAIT"
    rr = _i_num(r.get("rr"),0)
    if not rr:
        e, sl, tp2 = map(lambda k:_i_num(r.get(k),None), ("entry","sl","tp2"))
        if None not in (e,sl,tp2) and abs(e-sl)>0:
            rr=abs(tp2-e)/abs(e-sl)
    r["rr_intel"] = round(rr,2) if rr else None
    scenarios, base = _i_scenario(r)
    r["scenarios"] = scenarios
    r["scenario_base_case"] = base
    r["intel_reason"] = _i_reason(r)
    r["intel_signal_id"] = hashlib.sha1(
        f"{r.get('coin')}|{r.get('signal_candle_ts')}|{bias}|{r.get('setup_type')}".encode()
    ).hexdigest()[:12]
    r["v11_estimated_probability"] = None
    r["v11_probability_status"] = "NOT_CALIBRATED"
    build_decision_support(r)
    return r

def _intel_rank(results, personal=False):
    rows = []
    pset = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    for r in results:
        if not r.get("price"): continue
        if personal and str(r.get("coin","")).upper() not in pset: continue
        if not personal and str(r.get("coin","")).upper() in pset: continue
        rows.append(r)
    return sorted(rows, key=lambda x: (
        _i_num(x.get("opportunity_score"),0),
        _i_num(x.get("intel_score"),0),
        _i_num(x.get("data_quality"),0)
    ), reverse=True)

def _intel_line(r, detailed=True):
    coin=str(r.get("coin","")).upper()
    decision=r.get("intel_decision","WAIT")
    icon="🟢" if decision=="BUY" or decision=="WATCH LONG" else "🔴" if decision=="SELL" or decision=="WATCH SHORT" else "🟡"
    price=fmt(r.get("price"))
    setup=r.get("setup_type","NO SETUP")
    bias=r.get("intel_bias","NEUTRAL")
    score=r.get("opportunity_score",0)
    conf=r.get("confidence",0)
    rr=r.get("rr_intel")
    trig=r.get("intel_trigger") or {}
    if bias=="LONG": trigger=f"LONG>{fmt(trig.get('long'))}" if trig.get("long") else "LONG trigger N/A"
    elif bias=="SHORT": trigger=f"SHORT<{fmt(trig.get('short'))}" if trig.get("short") else "SHORT trigger N/A"
    else: trigger="breakout required"
    line=f"{icon} {coin} | {decision} | {setup} | O:{score:.0f} | S:{conf:.0f}"
    win_prob = r.get("win_probability")
    if win_prob is not None:
        line += f" | W:{win_prob:.0f}%"
    line += f" | {price}"
    if rr: line += f" | RR:{rr:.2f}"
    if detailed:
        line += f"\n   Trigger: {trigger}"
        price_v, long_v, short_v = _i_num(r.get("price"),None), trig.get("long"), trig.get("short")
        if price_v and long_v:
            line += f"\n   Distance to LONG trigger: {((long_v-price_v)/price_v*100):+.2f}%"
        if price_v and short_v:
            line += f"\n   Distance to SHORT trigger: {((short_v-price_v)/price_v*100):+.2f}%"
        line += f"\n   {r.get('intel_reason','')}"
    return line

def _intel_market_header(macro=None, news=None, breadth=None):
    dt=now_tehran()
    session, label, mult=get_current_session()
    market_score = _i_num((breadth or {}).get("score"),50)
    lines=[
        "🤖 ATLAS AI — MARKET INTELLIGENCE 4H",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران",
        f"🕐 {label} | ضریب کیفیت سشن: {mult:.1f}x",
        f"🌐 Market breadth: {market_score:.0f}/100",
    ]
    if news:
        lines.append(f"📰 News: {news.get('bias','MIXED/LIMITED')} | Impact: {news.get('impact','NORMAL')}")
    briefing = (news or {}).get("intel_briefing") or {}
    if briefing.get("has_content"):
        lines.append(briefing["text"])
    return lines

def _intel_summary(results, personal=False):
    rows=_intel_rank(results,personal)
    executable=[r for r in rows if r.get("executable")]
    watches=[r for r in rows if str(r.get("intel_decision","")).startswith("WATCH")]
    waits=[r for r in rows if r.get("intel_decision")=="WAIT"]
    return rows, executable, watches, waits

def _build_intel_report(results, macro, news, breadth, personal=False):
    rows, executable, watches, waits = _intel_summary(results,personal)
    lines=_intel_market_header(macro,news,breadth)
    title="💼 PERSONAL PORTFOLIO" if personal else "📡 OPPORTUNITY RANKING"
    lines += ["", title, "───────────────────"]
    for r in rows[:8]:
        lines.append(_intel_line(r))
    lines += ["", "🧠 DECISION BOARD", "───────────────────"]
    if executable:
        best=executable[0]
        lines.append(f"🟢 EXECUTABLE: {best.get('coin')} — {best.get('intel_decision')} | O:{best.get('opportunity_score',0):.0f} | RR:{best.get('rr_intel') or 'N/A'}")
    elif watches:
        best=watches[0]
        lines.append(f"🟡 BEST WATCH: {best.get('coin')} — {best.get('intel_decision')} | O:{best.get('opportunity_score',0):.0f}")
        lines.append(f"   Trigger: {('above '+fmt((best.get('intel_trigger') or {}).get('long'))) if best.get('intel_bias')=='LONG' else ('below '+fmt((best.get('intel_trigger') or {}).get('short')) if best.get('intel_bias')=='SHORT' else 'range break')}")
    else:
        lines.append("⚪ NO ACTIONABLE SETUP: market structure is not sufficiently asymmetric.")
    lines.append(f"📊 Universe: {len(rows)} | Executable: {len(executable)} | Watch: {len(watches)} | Wait: {len(waits)}")
    if rows:
        best=rows[0]
        lines.append(f"🎯 Best opportunity: {best.get('coin')} | {best.get('setup_type')} | O:{best.get('opportunity_score',0):.0f}")
    lines += ["", "📌 Scenario map", "───────────────────"]
    for r in rows[:3]:
        scenarios=r.get("scenarios") or []
        lines.append(f"🔹 {r.get('coin')}: {r.get('scenario_base_case','')}")
        for side, direction, trigger, txt in scenarios:
            lines.append(f"   {'🟢' if direction=='LONG' else '🔴'} {side}: {txt}")

    # "WHY NOT TRADE?" (architecture review): explain concretely why the
    # majority of scanned assets did not reach an executable state, instead
    # of the report silently defaulting everything to HOLD/WAIT.
    lines += ["", "❓ چرا معامله نشد؟ (WHY NOT TRADE)", "───────────────────"]
    if waits:
        for r in waits[:5]:
            lines.append(f"🔸 {r.get('coin')}")
            for reason in why_not_trade(r)[:4]:
                lines.append(f"   ❌ {translate_reason_fa(reason)}")
    else:
        lines.append("همه دارایی‌های بررسی‌شده یا اجرایی‌اند یا در حال دیده‌بانی.")

    cal = _build_calibration_curve()
    if cal["tier"] == "NOT_CALIBRATED":
        lines += ["", f"⚠️ نکته مدل: Signal Score / Model Strength معیارهای شاهد هستند، نه احتمال برد "
                       f"کالیبره‌شده ({cal['n']}/100 معامله بسته لازم است)."]
    else:
        lines += ["", f"ℹ️ Win Probability is calibrated from {cal['n']} closed trades "
                       f"(tier: {cal['tier']}) — treat CAUTIOUS-tier numbers as provisional."]
    return "\n".join(lines)

def build_two_engine_reports(results, top10, dynamic30, macro, news, market_info, unavailable=0, btc_regime=None, breadth=None):
    mode=get_engine_mode()
    if mode=="MARKET":
        return [_build_intel_report(results,macro,news,breadth,False)]
    if mode=="PERSONAL":
        return [_build_intel_report(results,macro,news,breadth,True)]
    return [
        _build_intel_report(results,macro,news,breadth,False),
        _build_intel_report(results,macro,news,breadth,True),
    ]

def _new_csv_columns():
    return (
        "Group","Symbol","Status","DecisionState","Price","Change24H",
        "Support","Resistance","Entry","SL","TP1","TP2","TP3","TP4","R/R",
        "Confidence","H4Trend","D1Trend","W1Trend","RSI","MACD","Volume",
        "VolumeRatio","ATR_pct","Liquidity","Gate","GateReason","Direction",
        "RepeatSignal","Reason","ModelVersion","DataQuality","SignalID",
        "RegimeTrend","RegimeVolatility","RegimeDerivatives","RegimeScore",
        "IntelBias","SetupType","OpportunityScore","StructureScore",
        "MomentumScore","VolumeScore","SRScore","ContradictionCount",
        "Contradictions","LongTrigger","ShortTrigger","Executable",
        "IntelDecision","IntelSignalID","ConfidenceLabel",
        "DecisionConfidence","DecisionRegimeTrend","DecisionRegimeVolatility","BacktestGateOK",
        "SignalScore","ModelStrength","WinProbability","WinProbabilityTier","WinProbabilitySamples"
    )

def _csv_row_for(sym, r, top10, dynamic30, personal_symbols):
    """Builds one CSV row for a symbol. Shared by the combined and the
    split (personal/metals/dynamic_top30) exporters so column logic lives
    in exactly one place."""
    plan=_csv_safe_plan(r)
    entry=sl=tp1=tp2=tp3=tp4=rr=""
    if plan:
        entry,sl,tp1,tp2=plan
        tp3=f(r.get("tp3")); tp4=f(r.get("tp4"))
        rr=_rr_from_values(entry,sl,tp2)
    trig=r.get("intel_trigger") or {}
    state=str(r.get("intel_decision") or r.get("decision_state") or r.get("action") or "WAIT")
    if state in ("BUY","BUY CONFIRMATION"): status="BUY"
    elif state in ("SELL","SELL CONFIRMATION"): status="SELL"
    elif state.startswith("WATCH"): status="WATCH"
    elif state=="WAIT": status="WAIT"
    else: status="HOLD"
    return [
        _csv_group(sym,top10,dynamic30,personal_symbols),sym,status,state,
        _csv_number(r.get("price")),_csv_number(r.get("change"),4),
        _csv_number(r.get("support")),_csv_number(r.get("resistance")),
        _csv_number(entry),_csv_number(sl),_csv_number(tp1),_csv_number(tp2),
        _csv_number(tp3),_csv_number(tp4),_csv_number(rr,3),
        _csv_number(r.get("confidence"),2),r.get("h4_trend","UNKNOWN"),
        r.get("d1_trend","UNKNOWN"),r.get("w1_trend","UNKNOWN"),
        _csv_number(r.get("rsi"),2),r.get("macd",""),r.get("volume",""),
        _csv_number(r.get("volume_ratio"),3),_csv_number(r.get("atr_pct"),3),
        r.get("liquidity",""),r.get("gate",""),r.get("gate_reason",""),
        r.get("direction",""),bool(r.get("repeat_signal")),r.get("intel_reason") or r.get("reason",""),
        VERSION,_csv_number(r.get("data_quality"),2),r.get("signal_id",""),
        r.get("regime_trend",""),r.get("regime_volatility",""),r.get("regime_derivatives",""),
        _csv_number(r.get("regime_score"),2),r.get("intel_bias","NEUTRAL"),r.get("setup_type","NO SETUP"),
        _csv_number(r.get("opportunity_score"),2),_csv_number(r.get("structure_score"),2),
        _csv_number(r.get("momentum_score"),2),_csv_number(r.get("volume_score"),2),
        _csv_number(r.get("sr_score"),2),len(r.get("contradictions") or []),
        " | ".join(r.get("contradictions") or []),_csv_number(trig.get("long")),
        _csv_number(trig.get("short")),bool(r.get("executable")),r.get("intel_decision","WAIT"),
        r.get("intel_signal_id",""),r.get("confidence_label","MODEL STRENGTH"),
        _csv_number(r.get("decision_confidence"),2),r.get("decision_regime_trend",""),
        r.get("decision_regime_volatility",""),bool(_LAST_BACKTEST_OK),
        _csv_number(r.get("signal_score"),2),_csv_number(r.get("model_strength"),2),
        _csv_number(r.get("win_probability"),1) if r.get("win_probability") is not None else "NOT_CALIBRATED",
        r.get("win_probability_tier",""),r.get("win_probability_samples",0)
    ]


def generate_csv_report(results, top10, dynamic30):
    """Combined single-file export (kept for backward compatibility).
    For the split personal/metals/dynamic_top30 files, use
    generate_split_csv_reports() instead."""
    ordered = _resolve_csv_universe(results, top10, dynamic30)
    return _csv_text_for_symbols(ordered, results, top10, dynamic30)


def build_image_table(results, top10_symbols=None, dynamic30_symbols=None, filename="signal_table.png"):
    """PNG ranking redesigned around opportunity/setup rather than raw price."""
    if not ENABLE_IMAGE_TABLE: return None
    try:
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            fm.fontManager.addfont("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
            plt.rcParams["font.family"]="DejaVu Sans"
        rows=_intel_rank(results,False)[:ATLAS_IMAGE_ROWS]
        if not rows:
            return None
        fig,ax=plt.subplots(figsize=(17,8.5))
        ax.axis("off")
        headers=["#","Asset","Decision","Setup","Bias","Opp.","Strength","R/R","Trigger"]
        cell=[headers]
        for i,r in enumerate(rows,1):
            trig=r.get("intel_trigger") or {}
            if r.get("intel_bias")=="LONG": t=fmt(trig.get("long")) if trig.get("long") else "N/A"
            elif r.get("intel_bias")=="SHORT": t=fmt(trig.get("short")) if trig.get("short") else "N/A"
            else: t="Range break"
            cell.append([
                str(i),str(r.get("coin",""))[:8],str(r.get("intel_decision","WAIT")),
                str(r.get("setup_type","NO SETUP"))[:16],str(r.get("intel_bias","NEUTRAL")),
                f"{_i_num(r.get('opportunity_score'),0):.0f}",
                f"{_i_num(r.get('confidence'),0):.0f}",f"{_i_num(r.get('rr_intel'),0):.2f}" if r.get("rr_intel") else "—",
                t[:22]
            ])
        table=ax.table(cellText=cell,loc="center",cellLoc="center",colWidths=[.04,.09,.12,.15,.09,.08,.09,.08,.20])
        table.auto_set_font_size(False); table.set_fontsize(10); table.scale(1,2.0)
        for (ri,cj),cellobj in table.get_celld().items():
            if ri==0:
                cellobj.set_facecolor("#26384A"); cellobj.set_text_props(color="white",weight="bold")
            elif ri%2==0:
                cellobj.set_facecolor("#EEF2F5")
            if ri>0 and cj in (2,4):
                val=str(cell[ri][cj])
                if "LONG" in val or val=="BUY": cellobj.set_facecolor("#2E8B57"); cellobj.set_text_props(color="white")
                elif "SHORT" in val or val=="SELL": cellobj.set_facecolor("#C0392B"); cellobj.set_text_props(color="white")
            if ri>0 and cj==5:
                v=_i_num(cell[ri][cj],0)
                cellobj.set_facecolor("#2E8B57" if v>=75 else "#D4AC0D" if v>=60 else "#C0392B")
                cellobj.set_text_props(color="white")
        ax.set_title("ATLAS v11.4 — OPPORTUNITY RANKING",fontsize=17,weight="bold",pad=18)
        ax.text(0.5,0.03,"Opportunity ≠ probability | Conditional triggers only | No order execution",ha="center",fontsize=9)
        plt.tight_layout()
        plt.savefig(filename,dpi=160,bbox_inches="tight",facecolor="white")
        plt.close()
        return filename
    except Exception as e:
        print(f"⚠️ Image generation error: {e}")
        return None

def generate_voice_summary(results, news=None, btc_regime=None):
    rows=_intel_rank(results,False)
    dt=now_tehran()
    session,label,mult=get_current_session()
    lines=[
        "گزارش هوشمند اطلس.",
        f"زمان گزارش {dt.strftime('%H:%M')} به وقت تهران. {label}.",
    ]
    if btc_regime:
        regime=btc_regime.get("regime") or btc_regime.get("trend") or "نامشخص"
        lines.append(f"رژیم کلی بیت کوین {regime}.")
    executable=[r for r in rows if r.get("executable")]
    watches=[r for r in rows if str(r.get("intel_decision","")).startswith("WATCH")]
    if executable:
        lines.append("سیگنال اجرایی معتبر وجود دارد.")
        for r in executable[:3]:
            lines.append(f"{r.get('coin')}، {r.get('intel_decision')}، امتیاز فرصت {r.get('opportunity_score',0):.0f}، نسبت ریسک به بازده {r.get('rr_intel') or 0:.1f}.")
    elif watches:
        lines.append("در حال حاضر سیگنال اجرایی قطعی نداریم، اما چند فرصت در مرحله انتظار تأیید هستند.")
        for r in watches[:3]:
            trig=r.get("intel_trigger") or {}
            if r.get("intel_bias")=="LONG":
                lines.append(f"{r.get('coin')} صعودی؛ تریگر عبور و تثبیت بالای {fmt(trig.get('long')) if trig.get('long') else 'سطح مقاومت'} است.")
            else:
                lines.append(f"{r.get('coin')} نزولی؛ تریگر شکست و تثبیت زیر {fmt(trig.get('short')) if trig.get('short') else 'سطح حمایت'} است.")
    else:
        lines.append("در حال حاضر فرصت معاملاتی با عدم تقارن کافی دیده نمی‌شود.")
    if rows:
        best=rows[0]
        lines.append(f"بهترین فرصت فعلی {best.get('coin')} با نوع ستاپ {best.get('setup_type')} و امتیاز فرصت {best.get('opportunity_score',0):.0f} است.")
        if best.get("contradictions"):
            lines.append("هشدارهای اصلی این فرصت: " + "، ".join(best["contradictions"][:3]) + ".")
    if news:
        lines.append(f"وضعیت اخبار {news.get('bias','مختلط')} و شدت اثر {news.get('impact','عادی')} است.")
    briefing = (news or {}).get("intel_briefing") or {}
    if briefing.get("voice_text"):
        lines.append(briefing["voice_text"])
    usdt=fetch_usdt_toman_public()
    if usdt: lines.append(f"نرخ تتر حدود {usdt:,.0f} تومان است.")
    lines.append("امتیاز فرصت و اطمینان اطلس احتمال برد آماری نیست و هنوز کالیبره نشده است.")
    lines.append("این گزارش توصیه سرمایه گذاری قطعی نیست و اتلس سفارش خرید یا فروش ثبت نمی‌کند.")
    return " ".join(lines)



# ============================================================
# FINAL ANALYSIS DELIVERY — 3 SEPARATE DOCUMENTS
# ============================================================
# Delivery-only layer. Existing engines, snapshot/arrow logic,
# PNG, voice, Supabase and risk logic are intentionally untouched.
# Telegram receives exactly three comprehensive CSV documents:
#   1) MARKET 4H
#   2) PERSONAL PORTFOLIO 4H
#   3) MARKET INTELLIGENCE 4H
# ============================================================

def _analysis_detail_row(r, report_type):
    """Export the existing analysis fields without changing their values."""
    trig = r.get("intel_trigger") or {}
    scenarios = r.get("scenarios") or []
    contradictions = r.get("contradictions") or []

    scenario_text = []
    for item in scenarios:
        try:
            side, direction, trigger, explanation = item
            scenario_text.append(
                f"{side} | {direction} | trigger={trigger} | {explanation}"
            )
        except Exception:
            scenario_text.append(str(item))

    return [
        report_type, r.get("coin", ""), r.get("price", ""), r.get("change", ""),
        r.get("h4_trend", ""), r.get("d1_trend", ""), r.get("w1_trend", ""),
        r.get("rsi", ""), r.get("macd", ""), r.get("volume", ""),
        r.get("volume_ratio", ""), r.get("atr_pct", ""),
        r.get("support", ""), r.get("resistance", ""), r.get("entry", ""),
        r.get("sl", ""), r.get("tp1", ""), r.get("tp2", ""), r.get("tp3", ""),
        r.get("tp4", ""), r.get("rr_intel", r.get("rr", "")),
        r.get("direction", ""), r.get("decision_state", ""),
        r.get("decision_confidence", r.get("confidence", "")),
        r.get("confidence_label", ""), r.get("intel_bias", ""),
        r.get("setup_type", ""), r.get("opportunity_score", ""),
        r.get("structure_score", ""), r.get("momentum_score", ""),
        r.get("volume_score", ""), r.get("sr_score", ""), len(contradictions),
        " | ".join(map(str, contradictions)), trig.get("long", ""),
        trig.get("short", ""), r.get("intel_decision", ""),
        r.get("executable", ""), r.get("signal_score", ""),
        r.get("model_strength", ""), r.get("win_probability", ""),
        r.get("win_probability_tier", ""), r.get("win_probability_samples", ""),
        r.get("regime_trend", ""), r.get("regime_volatility", ""),
        r.get("regime_derivatives", ""), r.get("regime_score", ""),
        r.get("gate", ""), r.get("gate_reason", ""), r.get("data_quality", ""),
        r.get("liquidity", ""), r.get("repeat_signal", ""), r.get("signal_id", ""),
        r.get("intel_signal_id", ""), r.get("intel_reason", r.get("reason", "")),
        " || ".join(scenario_text), " || ".join(map(str, why_not_trade(r))),
    ]


_ANALYSIS_EXPORT_COLUMNS = [
    "ReportType","Symbol","Price","Change24H","H4Trend","D1Trend","W1Trend",
    "RSI","MACD","Volume","VolumeRatio","ATR_pct","Support","Resistance",
    "Entry","SL","TP1","TP2","TP3","TP4","RR","Direction","DecisionState",
    "DecisionConfidence","ConfidenceLabel","IntelBias","SetupType",
    "OpportunityScore","StructureScore","MomentumScore","VolumeScore","SRScore",
    "ContradictionCount","Contradictions","LongTrigger","ShortTrigger",
    "IntelDecision","Executable","SignalScore","ModelStrength","WinProbability",
    "WinProbabilityTier","WinProbabilitySamples","RegimeTrend",
    "RegimeVolatility","RegimeDerivatives","RegimeScore","Gate","GateReason",
    "DataQuality","Liquidity","RepeatSignal","SignalID","IntelSignalID",
    "AnalyticalReason","ScenarioMap","WhyNotTrade"
]


def _write_analysis_csv(rows):
    import csv, io
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(_ANALYSIS_EXPORT_COLUMNS)
    writer.writerows(rows)
    return out.getvalue()


def generate_analysis_documents(results, top10, dynamic30):
    """
    Deep CSV analysis is intentionally restricted to:
      1) Top10 market
      2) Personal portfolio

    The former third aggregate CSV was removed because it only duplicated
    the union of these two datasets and added no unique reporting value.
    """
    personal_order = [str(x).upper() for x in ATLAS_PERSONAL_ASSETS]
    top_order = [str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)]
    by_symbol = {
        str(r.get("coin") or r.get("symbol") or "").upper(): r
        for r in (results or []) if (r.get("coin") or r.get("symbol"))
    }

    top_symbols = [x for x in top_order if x in by_symbol]
    personal_symbols = [x for x in personal_order if x in by_symbol]

    def rows(symbols, title):
        return [_analysis_detail_row(by_symbol[x], title) for x in symbols if x in by_symbol]

    return {
        "market_4h": _write_analysis_csv(
            rows(top_symbols, "ATLAS AI TOP 10 MARKET 4H")
        ),
        "personal_4h": _write_analysis_csv(
            rows(personal_symbols, "ATLAS AI PERSONAL PORTFOLIO 4H")
        ),
    }


def send_analysis_documents(results, top10, dynamic30):
    """Send exactly two comprehensive CSV analysis documents to Telegram."""
    dt = now_tehran()
    date_tag = shamsi(dt).replace("/", "")
    time_tag = dt.strftime("%H%M%S")

    docs = generate_analysis_documents(results, top10, dynamic30)
    labels = {
        "market_4h": "MARKET 4H",
        "personal_4h": "PERSONAL PORTFOLIO 4H",
    }

    destinations = []
    for chat_id in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if chat_id and chat_id not in destinations:
            destinations.append(chat_id)

    sent = 0
    errors = []

    for key, content in docs.items():
        if not content.strip():
            continue

        filename = f"atlas_{key}_{date_tag}_{time_tag}.csv"
        caption = (
            f"📊 ATLAS AI | {labels[key]}\n"
            f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران\n"
            f"📎 گزارش جامع — CSV"
        )

        for chat_id in destinations:
            try:
                _telegram_send_document(chat_id, content, filename, caption)
                sent += 1
                print(f"✅ Sent {filename} to Telegram")
            except Exception as e:
                errors.append(f"ANALYSIS_DOC[{key}] {chat_id}: {e}")

    return sent, errors


def _aio_num(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default

def _aio_symbol(r):
    return str(r.get("coin") or r.get("symbol") or "").upper()

def _aio_selected_results(results, top10):
    wanted = []
    for x in list(top10 or ATLAS_PRIORITY_TOP10) + list(ATLAS_PERSONAL_ASSETS):
        x = str(x).upper()
        if x and x not in wanted: wanted.append(x)
    by = {_aio_symbol(r): r for r in (results or []) if _aio_symbol(r)}
    return [by[x] for x in wanted if x in by]

def _aio_whale_bias(items):
    score, rows = 0, []
    for w in items or []:
        sym = str(w.get("symbol") or "").upper()
        if sym not in ("BTC","ETH"): continue
        rows.append(w)
        frm, to = str(w.get("from_type") or "").lower(), str(w.get("to_type") or "").lower()
        if "exchange" in to and "exchange" not in frm: score -= 1
        elif "exchange" in frm and "exchange" not in to: score += 1
    return ("ACCUMULATION_LEAN" if score >= 2 else
            "DISTRIBUTION_RISK" if score <= -2 else "NEUTRAL"), score, rows

def build_market_context_txt(macro, news, results, btc_regime=None):
    """
    گزارش Market Context به زبان فارسی.
    منطق داده و منابع قبلی حفظ شده و فقط لایه ارائه/متن فارسی شده است.
    """
    economic_events = fetch_economic_calendar()
    multi_exchange = compare_multi_exchange_prices()

    lines = [
        "ATLAS AI — زمینه و وضعیت بازار 4H",
        "=" * 64,
        "",
        "۱) وضعیت کلی بازار",
        f"- رژیم بازار BTC: {btc_regime if btc_regime is not None else 'نامشخص'}",
    ]

    # Breadth / macro summary if available
    if isinstance(macro, dict):
        fed = macro.get("fed_funds") or macro.get("fed_rate") or macro.get("federal_funds")
        unemp = macro.get("unemployment") or macro.get("us_unemployment")
        if fed is not None:
            lines.append(f"- نرخ بهره فدرال رزرو: {fed}")
        if unemp is not None:
            lines.append(f"- نرخ بیکاری آمریکا: {unemp}")

    lines += ["", "۲) خبرها و فضای کلان"]

    if isinstance(news, dict):
        bias = news.get("bias") or news.get("news_bias") or news.get("sentiment")
        impact = news.get("impact") or news.get("news_impact")
        if bias is not None:
            lines.append(f"- جهت کلی اخبار: {bias}")
        if impact is not None:
            lines.append(f"- شدت اثر خبری: {impact}")

        items = news.get("items") or news.get("news_items") or []
        if isinstance(items, list) and items:
            lines.append("- خبرهای مؤثر:")
            for item in items[:8]:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("headline") or item.get("name")
                    if title:
                        lines.append(f"  • {title}")

    lines += ["", "۳) نهنگ‌ها و جریان‌های بزرگ"]

    whale_items = news.get("whale_items") if isinstance(news, dict) else None
    if isinstance(whale_items, list) and whale_items:
        for w in whale_items[:8]:
            if isinstance(w, dict):
                sym = w.get("symbol") or w.get("coin") or "?"
                amount = w.get("amount_usd") or w.get("usd_value") or w.get("amount")
                direction = w.get("direction") or w.get("type") or w.get("flow")
                src = w.get("from") or w.get("source")
                dst = w.get("to") or w.get("destination")
                parts = [str(sym)]
                if amount is not None:
                    parts.append(f"ارزش: {amount}")
                if direction:
                    parts.append(str(direction))
                if src or dst:
                    parts.append(f"{src or '?'} → {dst or '?'}")
                lines.append("- " + " | ".join(parts))
    else:
        lines.append("- رویداد مهم و قابل‌اتکای نهنگ‌ها در این چرخه ثبت نشد.")

    lines += ["", "۴) مشتقات و فشار بازار"]

    # Keep this conservative and schema tolerant
    shown_deriv = False
    for r in results or []:
        sym = str(r.get("coin") or r.get("symbol") or "").upper()
        if sym not in ("BTC", "ETH"):
            continue
        cg = r.get("coinglass") or r.get("derivatives") or r.get("derivatives_context")
        if cg:
            lines.append(f"- {sym}: {cg}")
            shown_deriv = True
    if not shown_deriv:
        lines.append("- داده مشتقات قابل‌اتکای جداگانه‌ای برای BTC/ETH در این چرخه موجود نبود.")

    lines += ["", "۵) جمع‌بندی تفسیری"]

    # Infer a conservative market interpretation from available values.
    bullish_votes = 0
    bearish_votes = 0

    if isinstance(news, dict):
        nb = str(news.get("bias") or news.get("news_bias") or "").upper()
        if any(x in nb for x in ("BULL", "POSITIVE", "BUY")):
            bullish_votes += 1
        if any(x in nb for x in ("BEAR", "NEGATIVE", "SELL")):
            bearish_votes += 1

    br = str(btc_regime or "").upper()
    if any(x in br for x in ("BULL", "UP", "TRENDING_UP")):
        bullish_votes += 1
    if any(x in br for x in ("BEAR", "DOWN", "TRENDING_DOWN")):
        bearish_votes += 1

    if bullish_votes >= bearish_votes + 2:
        interpretation = "صعودی"
    elif bullish_votes > bearish_votes:
        interpretation = "محتاطانه صعودی"
    elif bearish_votes >= bullish_votes + 2:
        interpretation = "نزولی"
    elif bearish_votes > bullish_votes:
        interpretation = "محتاطانه نزولی"
    else:
        interpretation = "خنثی / بدون برتری روشن"

    lines.append(f"- برداشت کلی ATLAS از شرایط فعلی: {interpretation}")
    lines.append("- این بخش نقش زمینه تحلیلی دارد و به‌تنهایی فرمان خرید یا فروش محسوب نمی‌شود.")

    lines += ["", "۶) تقویم اقتصادی"]
    econ_lines = build_economic_calendar_context(economic_events)
    for x in econ_lines:
        s = str(x)
        s = s.replace("Economic Calendar / Event Risk:", "تقویم اقتصادی / ریسک رویداد:")
        s = s.replace("Economic Calendar: no tracked high-impact event in the configured lookahead window.",
                      "در بازه زمانی تنظیم‌شده، رویداد اقتصادی پراثرِ ثبت‌شده‌ای مشاهده نشد.")
        s = s.replace("[HIGH]", "[ریسک بالا]")
        s = s.replace("[UPCOMING]", "[در پیش‌رو]")
        s = s.replace("Forecast=", "پیش‌بینی=")
        s = s.replace("Previous=", "قبلی=")
        s = s.replace(" | in ", " | تا رویداد: ")
        s = s.replace("h", " ساعت")
        lines.append(s)

    lines += ["", "۷) مقایسه قیمت بین صرافی‌ها"]
    mx_lines = build_multi_exchange_context(multi_exchange)
    for x in mx_lines:
        s = str(x)
        s = s.replace("Multi-Exchange Comparison:", "مقایسه چندصرافی:")
        s = s.replace("Multi-Exchange: insufficient comparable prices or feature disabled.",
                      "داده کافی برای مقایسه چندصرافی وجود ندارد یا این قابلیت غیرفعال است.")
        s = s.replace("spread=", "اختلاف قیمت=")
        s = s.replace("[⚠️ MEANINGFUL]", "[⚠️ معنادار]")
        s = s.replace("[normal]", "[عادی]")
        lines.append(s)

    briefing = (news.get("intel_briefing") or {}).get("text") if isinstance(news, dict) else None
    if briefing:
        lines += ["", "۸) خلاصه هوشمندی فعلی ATLAS", briefing]

    return "\n".join(lines)


def _aio_trigger(r):
    t = r.get("intel_trigger") or {}
    d = str(r.get("direction") or "").upper()
    if d=="LONG" and t.get("long") is not None:
        return f"Confirm above {fmt(t.get('long'))} with volume/structure confirmation"
    if d=="SHORT" and t.get("short") is not None:
        return f"Confirm below {fmt(t.get('short'))} with volume/structure confirmation"
    return "Confirmed trigger + acceptable RR + evidence alignment"

def _aio_fuse(r, news=None):
    d = str(r.get("direction") or "").upper()
    tech = _aio_num(r.get("signal_score"),50) >= 60
    opp = _aio_num(r.get("opportunity_score"),50) >= 60
    reg = str(r.get("regime_trend") or "").upper()
    der = str(r.get("regime_derivatives") or "").upper()
    nb = str((news or {}).get("bias") or "MIXED/LIMITED").upper()
    if d=="LONG":
        votes=[("Technical",tech),("Opportunity",opp),("Regime",reg in ("UPTREND","BULLISH","UP")),
               ("Derivatives",der not in ("LONG_CROWDED","BEARISH")),("News",nb!="NEGATIVE")]
    elif d=="SHORT":
        votes=[("Technical",tech),("Opportunity",opp),("Regime",reg in ("DOWNTREND","BEARISH","DOWN")),
               ("Derivatives",der not in ("SHORT_CROWDED","BULLISH")),("News",nb!="POSITIVE")]
    else:
        votes=[("Technical",False),("Opportunity",opp),("Regime",False),("Derivatives",True),("News",True)]
    votes += [("RiskGeometry",_aio_num(r.get("rr"),0)>=1.5),
              ("DataQuality",_aio_num(r.get("data_quality"),0)>=60),
              ("BacktestGate",bool(_LAST_BACKTEST_OK))]
    agree=sum(1 for _,ok in votes if ok)
    r["evidence_agreement_count"]=agree
    r["evidence_total_count"]=len(votes)
    r["evidence_agreement"]=f"{agree}/{len(votes)}"
    r["evidence_details"]={k:bool(v) for k,v in votes}
    r["conviction_score"]=round(agree/len(votes)*100,1)
    return r

def apply_evidence_fusion(results, news=None):
    return [_aio_fuse(r, news) for r in (results or [])]

def build_deep_analysis_txt(results, top10):
    """
    Retained intentionally after duplication review: unlike the two CSV
    tables, this report adds qualitative Interpretation and Decision-change
    conditions per symbol, so it still provides unique explanatory value.
    """
    lines=["ATLAS AI — TOP10 + PERSONAL DEEP ANALYSIS 4H","="*64,
           "Scope: Top10 + Personal Portfolio only",""]
    for r in _aio_selected_results(results, top10):
        lines += [
            f"[{_aio_symbol(r)}]",
            f"Price: {fmt(r.get('price'))}",
            f"Decision: {r.get('intel_decision') or r.get('decision_state') or r.get('action') or 'WAIT'}",
            f"Direction: {r.get('direction','NEUTRAL')} | Setup: {r.get('setup_type','NO SETUP')}",
            f"4H/1D/1W: {r.get('h4_trend',r.get('trend_4h','?'))} / {r.get('d1_trend',r.get('trend_1d','?'))} / {r.get('w1_trend',r.get('trend_1w','?'))}",
            f"Signal: {_aio_num(r.get('signal_score')):.0f}/100 | Opportunity: {_aio_num(r.get('opportunity_score')):.0f}/100 | Conviction: {_aio_num(r.get('conviction_score')):.0f}/100 | Evidence: {r.get('evidence_agreement','N/A')}",
            f"RSI: {r.get('rsi','N/A')} | MACD: {r.get('macd','N/A')} | VolumeRatio: {r.get('volume_ratio','N/A')}",
            f"Regime: {r.get('regime_trend','N/A')} | Volatility: {r.get('regime_volatility','N/A')} | Derivatives: {r.get('regime_derivatives','N/A')}",
            f"Entry: {fmt(r.get('entry'))} | SL: {fmt(r.get('sl'))} | TP1: {fmt(r.get('tp1'))} | TP2: {fmt(r.get('tp2'))} | TP3: {fmt(r.get('tp3'))} | TP4: {fmt(r.get('tp4'))} | RR: {r.get('rr','N/A')}",
            f"Interpretation: {r.get('intel_reason') or r.get('analytical_reason') or r.get('reason') or 'N/A'}",
            f"Decision-change condition: {_aio_trigger(r)}",""
        ]
    return "\n".join(lines)

def _aio_csv(rows, cols):
    import csv, io
    out=io.StringIO(newline="")
    w=csv.DictWriter(out,fieldnames=cols,lineterminator="\n",extrasaction="ignore")
    w.writeheader()
    for x in rows: w.writerow(x)
    return out.getvalue()

def generate_best_watch_csv(results, top10):
    rows=[]
    for r in _aio_selected_results(results, top10):
        if r.get("executable"): continue
        score=max(_aio_num(r.get("decision_support_score")),_aio_num(r.get("opportunity_score")))
        if score<55: continue
        rows.append({"Rank":0,"Symbol":_aio_symbol(r),"Direction":r.get("direction","NEUTRAL"),
            "Decision":r.get("intel_decision") or r.get("decision_state") or "WATCH",
            "Opportunity":r.get("opportunity_score"),"DecisionSupport":r.get("decision_support_score"),
            "Conviction":r.get("conviction_score"),"EvidenceAgreement":r.get("evidence_agreement"),
            "Trigger":_aio_trigger(r),"RR":r.get("rr"),"Regime":r.get("regime_trend"),
            "DataQuality":r.get("data_quality"),"WhyWatch":r.get("intel_reason") or r.get("gate_reason") or ""})
    rows.sort(key=lambda x:(_aio_num(x["DecisionSupport"]),_aio_num(x["Opportunity"])),reverse=True)
    for i,x in enumerate(rows,1): x["Rank"]=i
    cols=["Rank","Symbol","Direction","Decision","Opportunity","DecisionSupport","Conviction",
          "EvidenceAgreement","Trigger","RR","Regime","DataQuality","WhyWatch"]
    return _aio_csv(rows,cols)

def generate_opportunity_ranking_csv(results):
    rows=[]
    for r in results or []:
        rows.append({"Rank":0,"Symbol":_aio_symbol(r),"Direction":r.get("direction","NEUTRAL"),
            "Decision":r.get("intel_decision") or r.get("decision_state") or "WAIT",
            "Opportunity":r.get("opportunity_score"),"SignalScore":r.get("signal_score"),
            "DecisionSupport":r.get("decision_support_score"),"Conviction":r.get("conviction_score"),
            "EvidenceAgreement":r.get("evidence_agreement"),"RR":r.get("rr"),
            "Regime":r.get("regime_trend"),"Derivatives":r.get("regime_derivatives"),
            "DataQuality":r.get("data_quality"),"Executable":bool(r.get("executable"))})
    rows.sort(key=lambda x:(_aio_num(x["DecisionSupport"]),_aio_num(x["Opportunity"]),_aio_num(x["SignalScore"])),reverse=True)
    for i,x in enumerate(rows,1): x["Rank"]=i
    cols=["Rank","Symbol","Direction","Decision","Opportunity","SignalScore","DecisionSupport",
          "Conviction","EvidenceAgreement","RR","Regime","Derivatives","DataQuality","Executable"]
    return _aio_csv(rows,cols)

def send_all_in_one_documents(results, top10, macro, news, btc_regime):
    dt=now_tehran(); tag=shamsi(dt).replace("/","")+"_"+dt.strftime("%H%M%S")
    docs=[
      (f"01_ATLAS_MARKET_CONTEXT_{tag}.txt",build_market_context_txt(macro,news,results,btc_regime),"🌍 ATLAS | Market Context"),
      (f"02_ATLAS_TOP10_PERSONAL_DEEP_ANALYSIS_{tag}.txt",build_deep_analysis_txt(results,top10),"🧠 ATLAS | Top10 + Personal Deep Analysis"),
      (f"04_ATLAS_BEST_WATCH_{tag}.csv",generate_best_watch_csv(results,top10),"👀 ATLAS | Best Watch"),
      (f"05_ATLAS_OPPORTUNITY_RANKING_{tag}.csv",generate_opportunity_ranking_csv(results),"🏆 ATLAS | Opportunity Ranking")]
    destinations=[]
    for c in (TELEGRAM_CHAT_ID,TELEGRAM_GROUP_CHAT_ID):
        if c and c not in destinations: destinations.append(c)
    sent=0; errors=[]
    for fn,content,cap in docs:
        if not content.strip(): continue
        for c in destinations:
            try: _telegram_send_document(c,content,fn,cap); sent+=1
            except Exception as e:
                errors.append(f"AIO_DOC[{fn}] {c}: {e}")
                append_changelog("AIO_DOCUMENT",None,None,str(e))
    return sent,errors

def _aio_notification_db():
    conn=sqlite3.connect(DB_FILE)
    conn.execute("""create table if not exists signal_notifications(
        symbol text primary key,state text not null,direction text,trend text,notified_at text not null)""")
    conn.commit(); return conn

def send_signal_change_notifications(results, top10):
    """Notify meaningful state/trend changes; first observation only seeds state."""
    conn=_aio_notification_db(); sent=0; errors=[]; now=now_tehran()
    try:
        for r in _aio_selected_results(results,top10):
            sym=_aio_symbol(r)
            decision=str(r.get("intel_decision") or r.get("decision_state") or r.get("action") or "WAIT").upper()
            direction=str(r.get("direction") or "NEUTRAL").upper()
            trend=str(r.get("regime_trend") or "UNKNOWN").upper()
            old=conn.execute("select state,direction,trend from signal_notifications where symbol=?",(sym,)).fetchone()
            if not old:
                conn.execute("insert or replace into signal_notifications values(?,?,?,?,?)",
                             (sym,decision,direction,trend,now.isoformat())); continue
            pd,pdir,ptrend=old
            if (pd,pdir,ptrend)==(decision,direction,trend): continue
            important={"BUY","SELL","EXIT","BUY CONFIRMATION","SELL CONFIRMATION","WATCH LONG","WATCH SHORT"}
            meaningful=(decision in important or pd in important or
                        (ptrend!=trend and trend not in ("UNKNOWN","RANGE","NEUTRAL")))
            score=max(_aio_num(r.get("decision_support_score")),_aio_num(r.get("opportunity_score")))
            if meaningful and score>=ATLAS_NOTIFICATION_MIN_SCORE:
                msg=format_signal_notification(r,pd,pdir,ptrend)
                if ATLAS_SIGNAL_MENTIONS: msg += "\\n\\n"+ATLAS_SIGNAL_MENTIONS
                for c in dict.fromkeys([x for x in (TELEGRAM_CHAT_ID,TELEGRAM_GROUP_CHAT_ID) if x]):
                    try: telegram_send_one(c,msg); sent+=1
                    except Exception as e: errors.append(f"SIGNAL_NOTIFY[{sym}] {c}: {e}")
            conn.execute("update signal_notifications set state=?,direction=?,trend=?,notified_at=? where symbol=?",
                         (decision,direction,trend,now.isoformat(),sym))
        conn.commit()
    finally: conn.close()
    return sent,errors



# ============================================================
# ATLAS v11.5 — PHASE 1 INTELLIGENCE UPGRADE
# MTF + Signal Lifecycle + Why-Not-Trade v2 + Portfolio Risk
# Additive by design; existing signal engine remains canonical.
# ============================================================

ATLAS_MTF_MIN_ALIGNMENT = int(os.environ.get("ATLAS_MTF_MIN_ALIGNMENT", "3"))
ATLAS_PORTFOLIO_MAX_OPEN_RISK_PCT = float(
    os.environ.get("ATLAS_PORTFOLIO_MAX_OPEN_RISK_PCT", os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT", "6.0"))
)
ATLAS_PORTFOLIO_MAX_DIRECTIONAL_EXPOSURE_PCT = float(
    os.environ.get("ATLAS_PORTFOLIO_MAX_DIRECTIONAL_EXPOSURE_PCT", "75")
)
ATLAS_LIFECYCLE_NOTIFY_ON_TP = os.environ.get("ATLAS_LIFECYCLE_NOTIFY_ON_TP", "1").strip().lower() not in ("0","false","no","off")

def _p1_norm_trend(v):
    s = str(v or "").strip().upper()
    bullish = {"UP","UPTREND","BULLISH","LONG","TREND_UP","RISING","STRONG_UP"}
    bearish = {"DOWN","DOWNTREND","BEARISH","SHORT","TREND_DOWN","FALLING","STRONG_DOWN"}
    neutral = {"RANGE","SIDEWAYS","NEUTRAL","FLAT","MIXED","UNKNOWN","NONE",""}
    if s in bullish or "BULL" in s or "UPTREND" in s:
        return "BULLISH"
    if s in bearish or "BEAR" in s or "DOWNTREND" in s:
        return "BEARISH"
    if s in neutral:
        return "NEUTRAL"
    return "NEUTRAL"

def _p1_extract_mtf(r):
    """Returns normalized H1/H4/D1/W1 trend states without changing arrow/snapshot logic."""
    h1 = (
        r.get("h1_trend") or r.get("trend_1h") or r.get("trend_h1")
        or r.get("h1_structure") or r.get("one_hour_trend")
    )
    h4 = r.get("h4_trend") or r.get("trend_4h") or r.get("trend_h4") or r.get("regime_trend")
    d1 = r.get("d1_trend") or r.get("trend_1d") or r.get("trend_d1")
    w1 = r.get("w1_trend") or r.get("trend_1w") or r.get("trend_w1")
    return {
        "H1": _p1_norm_trend(h1),
        "H4": _p1_norm_trend(h4),
        "D1": _p1_norm_trend(d1),
        "W1": _p1_norm_trend(w1),
    }

def apply_mtf_confirmation(results):
    """
    Weighted MTF agreement for the current canonical direction.
    H1=20%, H4=35%, D1=30%, W1=15%.
    This layer scores confirmation and does not veto a trade by itself.
    """
    weights = {"H1": 0.20, "H4": 0.35, "D1": 0.30, "W1": 0.15}
    for r in results or []:
        mtf = _p1_extract_mtf(r)
        direction = str(r.get("direction") or r.get("intel_bias") or "").upper()
        target = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else None

        aligned = 0
        weighted = 0.0
        available = 0
        available_weight = 0.0
        conflicts = 0
        detail = {}

        for tf, state in mtf.items():
            if state == "NEUTRAL":
                detail[tf] = "NEUTRAL"
                continue
            available += 1
            available_weight += weights[tf]
            if target and state == target:
                aligned += 1
                weighted += weights[tf]
                detail[tf] = "ALIGNED"
            elif target:
                conflicts += 1
                detail[tf] = "CONFLICT"
            else:
                detail[tf] = state

        agreement_pct = round((weighted / available_weight * 100.0) if available_weight > 0 else 0.0, 1)
        r["mtf_states"] = mtf
        r["mtf_detail"] = detail
        r["mtf_aligned_count"] = aligned
        r["mtf_available_count"] = available
        r["mtf_conflicts"] = conflicts
        r["mtf_agreement_pct"] = agreement_pct
        r["mtf_agreement"] = f"{aligned}/{available}" if available else "0/0"
        r["mtf_confirmation"] = (
            "STRONG" if agreement_pct >= 75 and aligned >= min(ATLAS_MTF_MIN_ALIGNMENT, max(1, available))
            else "MODERATE" if agreement_pct >= 50
            else "WEAK"
        )
    return results

def _p1_risk_per_trade_pct(r):
    """Estimate risk % using existing fields first; otherwise derive from entry/SL distance."""
    for key in ("risk_pct", "position_risk_pct", "risk_per_trade_pct", "open_risk_pct"):
        if r.get(key) is not None:
            try:
                return max(0.0, float(r.get(key)))
            except Exception:
                pass
    try:
        entry = float(r.get("entry"))
        sl = float(r.get("sl"))
        if entry > 0:
            return abs(entry - sl) / entry * 100.0
    except Exception:
        pass
    return 0.0

def build_portfolio_risk_intelligence(results, top10=None):
    """
    Aggregate only live/active-looking trade ideas.
    Does not alter portfolio accounting or execution; provides decision context.
    """
    active_states = {
        "BUY","SELL","ACTIVE","CONFIRMED","BUY CONFIRMATION","SELL CONFIRMATION",
        "WATCH LONG","WATCH SHORT"
    }
    rows = []
    long_risk = 0.0
    short_risk = 0.0
    total_risk = 0.0

    for r in (results or []):
        decision = str(r.get("intel_decision") or r.get("decision_state") or r.get("action") or "").upper()
        if decision not in active_states and not bool(r.get("executable")):
            continue
        rpct = _p1_risk_per_trade_pct(r)
        if rpct <= 0:
            continue
        direction = str(r.get("direction") or "").upper()
        if direction == "LONG":
            long_risk += rpct
        elif direction == "SHORT":
            short_risk += rpct
        total_risk += rpct
        rows.append({
            "symbol": _aio_symbol(r),
            "direction": direction or "NEUTRAL",
            "risk_pct": round(rpct, 3),
            "decision": decision or "WATCH",
            "rr": r.get("rr"),
        })

    directional_den = max(total_risk, 1e-9)
    long_share = round(long_risk / directional_den * 100.0, 1)
    short_share = round(short_risk / directional_den * 100.0, 1)
    risk_status = (
        "BLOCK_NEW_RISK" if total_risk >= ATLAS_PORTFOLIO_MAX_OPEN_RISK_PCT
        else "CAUTION" if total_risk >= 0.75 * ATLAS_PORTFOLIO_MAX_OPEN_RISK_PCT
        else "NORMAL"
    )

    concentration = "BALANCED"
    if long_share >= ATLAS_PORTFOLIO_MAX_DIRECTIONAL_EXPOSURE_PCT:
        concentration = "LONG_CONCENTRATED"
    elif short_share >= ATLAS_PORTFOLIO_MAX_DIRECTIONAL_EXPOSURE_PCT:
        concentration = "SHORT_CONCENTRATED"

    return {
        "open_risk_pct": round(total_risk, 3),
        "long_risk_pct": round(long_risk, 3),
        "short_risk_pct": round(short_risk, 3),
        "long_share_pct": long_share,
        "short_share_pct": short_share,
        "max_open_risk_pct": ATLAS_PORTFOLIO_MAX_OPEN_RISK_PCT,
        "risk_status": risk_status,
        "directional_concentration": concentration,
        "positions_count": len(rows),
        "positions": rows,
    }

def apply_portfolio_risk_context(results, risk_summary):
    """
    Adds portfolio-risk context to each candidate.
    Existing canonical decisions are preserved; this creates a risk recommendation.
    """
    risk_summary = risk_summary or {}
    status = risk_summary.get("risk_status", "NORMAL")
    concentration = risk_summary.get("directional_concentration", "BALANCED")

    for r in results or []:
        d = str(r.get("direction") or "").upper()
        allowed = True
        reason = "Portfolio risk within configured limits."

        if status == "BLOCK_NEW_RISK":
            allowed = False
            reason = (
                f"Open portfolio risk {risk_summary.get('open_risk_pct',0):.2f}% "
                f">= limit {risk_summary.get('max_open_risk_pct',0):.2f}%."
            )
        elif concentration == "LONG_CONCENTRATED" and d == "LONG":
            allowed = False
            reason = (
                f"Long-side concentration {risk_summary.get('long_share_pct',0):.1f}% "
                "is above configured directional threshold."
            )
        elif concentration == "SHORT_CONCENTRATED" and d == "SHORT":
            allowed = False
            reason = (
                f"Short-side concentration {risk_summary.get('short_share_pct',0):.1f}% "
                "is above configured directional threshold."
            )

        r["portfolio_risk_allowed"] = allowed
        r["portfolio_risk_reason"] = reason
        r["portfolio_open_risk_pct"] = risk_summary.get("open_risk_pct", 0.0)
        r["portfolio_directional_concentration"] = concentration
    return results

def _p1_structured_blockers(r):
    blockers = []
    # RR
    rr = _aio_num(r.get("rr"), 0)
    if rr and rr < 1.5:
        blockers.append({
            "code": "RR_LOW",
            "severity": "HIGH",
            "message": f"RR={rr:.2f} is below the preferred 1.50 threshold."
        })

    # MTF
    if r.get("mtf_conflicts", 0) > 0 and _aio_num(r.get("mtf_agreement_pct"), 0) < 60:
        blockers.append({
            "code": "MTF_CONFLICT",
            "severity": "HIGH",
            "message": (
                f"MTF agreement is only {r.get('mtf_agreement','0/0')} "
                f"({_aio_num(r.get('mtf_agreement_pct')):.0f}%)."
            )
        })
    elif str(r.get("mtf_confirmation") or "").upper() == "WEAK":
        blockers.append({
            "code": "MTF_WEAK",
            "severity": "MEDIUM",
            "message": "Multi-timeframe confirmation is weak."
        })

    # Data quality
    dq = _aio_num(r.get("data_quality"), 0)
    if dq and dq < 60:
        blockers.append({
            "code": "DATA_QUALITY",
            "severity": "HIGH",
            "message": f"Data quality is {dq:.0f}/100."
        })

    # Portfolio risk
    if not bool(r.get("portfolio_risk_allowed", True)):
        blockers.append({
            "code": "PORTFOLIO_RISK",
            "severity": "HIGH",
            "message": r.get("portfolio_risk_reason") or "Portfolio risk blocks a new position."
        })

    # Existing gate / why-not-trade
    try:
        raw = why_not_trade(r)
        if isinstance(raw, str):
            raw = [raw] if raw else []
        for x in list(raw or [])[:5]:
            msg = translate_reason_fa(str(x))
            if msg and not any(b["message"] == msg for b in blockers):
                blockers.append({"code": "EXISTING_GATE", "severity": "MEDIUM", "message": msg})
    except Exception:
        pass

    return blockers

def _p1_activation_conditions(r):
    conditions = []
    t = r.get("intel_trigger") or {}
    direction = str(r.get("direction") or "").upper()

    if direction == "LONG" and t.get("long") is not None:
        conditions.append(f"4H close/hold above {fmt(t.get('long'))} with volume confirmation.")
    elif direction == "SHORT" and t.get("short") is not None:
        conditions.append(f"4H close/hold below {fmt(t.get('short'))} with volume confirmation.")

    if _aio_num(r.get("mtf_agreement_pct"), 0) < 60:
        conditions.append("MTF agreement improves to at least 60% without major 1D conflict.")

    rr = _aio_num(r.get("rr"), 0)
    if rr and rr < 1.5:
        conditions.append("Entry/SL geometry improves so RR reaches at least 1.50.")

    if not bool(r.get("portfolio_risk_allowed", True)):
        conditions.append("Portfolio open-risk/directional concentration returns below configured limit.")

    if not conditions:
        conditions.append("Canonical ATLAS trigger remains valid and Evidence/MTF/RR stay aligned.")
    return conditions

def build_why_not_trade_txt(results, top10):
    lines = [
        "ATLAS AI — WHY NOT TRADE?",
        "=" * 64,
        "Scope: Top10 + Personal Portfolio only",
        "Structured blockers + measurable decision-change conditions",
        "",
    ]

    for r in _aio_selected_results(results, top10):
        blockers = _p1_structured_blockers(r)
        lines += [
            f"[{_aio_symbol(r)}]",
            f"Decision: {r.get('intel_decision') or r.get('decision_state') or r.get('action') or 'WAIT'}",
            f"Direction: {r.get('direction','NEUTRAL')}",
            f"MTF: {r.get('mtf_agreement','0/0')} | {r.get('mtf_agreement_pct',0)}% | {r.get('mtf_confirmation','N/A')}",
            f"Evidence: {r.get('evidence_agreement','N/A')} | Conviction: {r.get('conviction_score','N/A')}",
            f"Portfolio Risk Allowed: {'YES' if r.get('portfolio_risk_allowed', True) else 'NO'}",
            "Blocking Factors:",
        ]
        if blockers:
            for i, b in enumerate(blockers, 1):
                lines.append(f"{i}. [{b['severity']}] {b['message']}")
        else:
            lines.append("1. No hard blocker detected.")

        lines += ["Decision Changes If:"]
        for i, c in enumerate(_p1_activation_conditions(r), 1):
            lines.append(f"{i}. {c}")
        lines += [""]

    return "\n".join(lines)

def build_portfolio_risk_txt(risk_summary):
    r = risk_summary or {}
    lines = [
        "ATLAS AI — PORTFOLIO RISK INTELLIGENCE",
        "=" * 64,
        f"Open Risk: {r.get('open_risk_pct',0):.2f}%",
        f"Configured Max Open Risk: {r.get('max_open_risk_pct',0):.2f}%",
        f"Long Risk: {r.get('long_risk_pct',0):.2f}% | Share: {r.get('long_share_pct',0):.1f}%",
        f"Short Risk: {r.get('short_risk_pct',0):.2f}% | Share: {r.get('short_share_pct',0):.1f}%",
        f"Risk Status: {r.get('risk_status','NORMAL')}",
        f"Directional Concentration: {r.get('directional_concentration','BALANCED')}",
        f"Tracked Trade Ideas: {r.get('positions_count',0)}",
        "",
        "Positions:",
    ]
    if r.get("positions"):
        for x in r["positions"]:
            lines.append(
                f"- {x.get('symbol')} | {x.get('direction')} | "
                f"Risk={x.get('risk_pct')}% | RR={x.get('rr')} | {x.get('decision')}"
            )
    else:
        lines.append("- No active trade-risk rows found.")
    return "\n".join(lines)

def _p1_lifecycle_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        create table if not exists signal_lifecycle(
            symbol text primary key,
            signal_id text,
            lifecycle_state text not null,
            direction text,
            entry real,
            sl real,
            tp1 real,
            tp2 real,
            tp3 real,
            tp4 real,
            last_price real,
            first_seen_at text not null,
            updated_at text not null,
            last_event text
        )
    """)
    conn.execute("""
        create table if not exists signal_lifecycle_events(
            id integer primary key autoincrement,
            symbol text not null,
            signal_id text,
            from_state text,
            to_state text,
            event text,
            price real,
            created_at text not null
        )
    """)
    conn.commit()
    return conn

def _p1_initial_lifecycle_state(r):
    decision = str(r.get("intel_decision") or r.get("decision_state") or r.get("action") or "WAIT").upper()
    if decision in ("BUY","SELL","BUY CONFIRMATION","SELL CONFIRMATION") or bool(r.get("executable")):
        return "CONFIRMED"
    if decision in ("WATCH LONG","WATCH SHORT","WATCH"):
        return "WATCH"
    if str(r.get("direction") or "").upper() in ("LONG","SHORT"):
        return "CANDIDATE"
    return "CANDIDATE"

def _p1_price_hit(price, level, direction, kind):
    try:
        p, lv = float(price), float(level)
    except Exception:
        return False
    if direction == "LONG":
        return p >= lv if kind == "TP" else p <= lv
    if direction == "SHORT":
        return p <= lv if kind == "TP" else p >= lv
    return False

def update_signal_lifecycle(results, top10=None):
    """
    Stateful lifecycle tracker:
    CANDIDATE -> WATCH -> CONFIRMED -> ACTIVE -> TP1/TP2/TP3/TP4/SL/INVALIDATED.
    It tracks; it does not place orders.
    """
    now = now_tehran().isoformat()
    conn = _p1_lifecycle_db()
    events = []
    selected = _aio_selected_results(results, top10) if top10 is not None else (results or [])

    try:
        for r in selected:
            sym = _aio_symbol(r)
            if not sym:
                continue

            direction = str(r.get("direction") or "").upper()
            signal_id = str(r.get("intel_signal_id") or r.get("signal_id") or "")
            price = r.get("price")
            desired = _p1_initial_lifecycle_state(r)

            row = conn.execute(
                """select lifecycle_state,direction,entry,sl,tp1,tp2,tp3,tp4,first_seen_at
                   from signal_lifecycle where symbol=?""",
                (sym,)
            ).fetchone()

            entry, sl = r.get("entry"), r.get("sl")
            tp1, tp2, tp3, tp4 = r.get("tp1"), r.get("tp2"), r.get("tp3"), r.get("tp4")

            if not row:
                conn.execute(
                    """insert into signal_lifecycle(
                       symbol,signal_id,lifecycle_state,direction,entry,sl,tp1,tp2,tp3,tp4,
                       last_price,first_seen_at,updated_at,last_event
                       ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sym,signal_id,desired,direction,entry,sl,tp1,tp2,tp3,tp4,price,now,now,"INIT")
                )
                events.append({"symbol":sym,"from":None,"to":desired,"event":"INIT","price":price})
                continue

            prev_state, prev_dir, pentry, psl, ptp1, ptp2, ptp3, ptp4, first_seen = row
            new_state = prev_state
            event = None

            # Direction flip invalidates previous setup first.
            if prev_dir and direction and prev_dir != direction and prev_state not in ("TP4","SL","INVALIDATED","EXITED"):
                new_state = "INVALIDATED"
                event = "DIRECTION_FLIP"
            else:
                # Price milestone tracking for confirmed/active setups.
                levels = [
                    ("TP4", tp4 if tp4 is not None else ptp4),
                    ("TP3", tp3 if tp3 is not None else ptp3),
                    ("TP2", tp2 if tp2 is not None else ptp2),
                    ("TP1", tp1 if tp1 is not None else ptp1),
                ]
                effective_sl = sl if sl is not None else psl
                if _p1_price_hit(price, effective_sl, direction or prev_dir, "SL"):
                    new_state, event = "SL", "SL_HIT"
                else:
                    for state_name, lv in levels:
                        if _p1_price_hit(price, lv, direction or prev_dir, "TP"):
                            new_state, event = state_name, f"{state_name}_HIT"
                            break

                if event is None:
                    if desired == "CONFIRMED" and prev_state in ("CANDIDATE","WATCH"):
                        new_state, event = "CONFIRMED", "SETUP_CONFIRMED"
                    elif desired == "WATCH" and prev_state == "CANDIDATE":
                        new_state, event = "WATCH", "WATCH_STARTED"
                    elif prev_state == "CONFIRMED":
                        # First subsequent observation of a still-valid confirmed setup becomes ACTIVE.
                        new_state, event = "ACTIVE", "ACTIVE_TRACKING"

            if new_state != prev_state or event:
                conn.execute(
                    """insert into signal_lifecycle_events(
                       symbol,signal_id,from_state,to_state,event,price,created_at
                       ) values(?,?,?,?,?,?,?)""",
                    (sym,signal_id,prev_state,new_state,event or "STATE_UPDATE",price,now)
                )
                events.append({"symbol":sym,"from":prev_state,"to":new_state,"event":event,"price":price})

            conn.execute(
                """update signal_lifecycle set
                   signal_id=?,lifecycle_state=?,direction=?,entry=?,sl=?,tp1=?,tp2=?,tp3=?,tp4=?,
                   last_price=?,updated_at=?,last_event=?
                   where symbol=?""",
                (signal_id,new_state,direction,entry,sl,tp1,tp2,tp3,tp4,price,now,event,sym)
            )
            r["lifecycle_state"] = new_state
            r["lifecycle_event"] = event

        conn.commit()
    finally:
        conn.close()
    return events

def generate_lifecycle_csv():
    import csv, io
    conn = _p1_lifecycle_db()
    try:
        rows = conn.execute(
            """select symbol,signal_id,lifecycle_state,direction,entry,sl,tp1,tp2,tp3,tp4,
                      last_price,first_seen_at,updated_at,last_event
               from signal_lifecycle
               order by updated_at desc"""
        ).fetchall()
    finally:
        conn.close()

    out = io.StringIO(newline="")
    cols = ["Symbol","SignalID","Lifecycle","Direction","Entry","SL","TP1","TP2","TP3","TP4",
            "LastPrice","FirstSeen","UpdatedAt","LastEvent"]
    w = csv.writer(out, lineterminator="\n")
    w.writerow(cols)
    for row in rows:
        w.writerow(row)
    return out.getvalue()

def send_phase1_documents(results, top10, risk_summary):
    dt = now_tehran()
    tag = shamsi(dt).replace("/","") + "_" + dt.strftime("%H%M%S")
    docs = [
        (f"03_ATLAS_WHY_NOT_TRADE_{tag}.txt",
         build_why_not_trade_txt(results, top10),
         "🧩 ATLAS | Why Not Trade — Structured Blockers"),
        (f"06_ATLAS_PORTFOLIO_RISK_{tag}.txt",
         build_portfolio_risk_txt(risk_summary),
         "🛡️ ATLAS | Portfolio Risk Intelligence"),
        (f"07_ATLAS_SIGNAL_LIFECYCLE_{tag}.csv",
         generate_lifecycle_csv(),
         "🔄 ATLAS | Signal Lifecycle"),
    ]
    destinations = []
    for c in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if c and c not in destinations:
            destinations.append(c)

    sent, errors = 0, []
    for fn, content, cap in docs:
        if not content or not str(content).strip():
            continue
        for c in destinations:
            try:
                _telegram_send_document(c, content, fn, cap)
                sent += 1
            except Exception as e:
                errors.append(f"PHASE1_DOC[{fn}] {c}: {e}")
    return sent, errors



# ============================================================
# ATLAS v11.5 — CLEAN+ OPTIMIZATION PACK
# Lifecycle Alerts + Backtest Dashboard + Economic Calendar
# Rich Signal Notifications + Multi-Exchange Comparison
# ============================================================

ATLAS_LIFECYCLE_ALERTS = os.environ.get("ATLAS_LIFECYCLE_ALERTS", "1").strip().lower() not in ("0","false","no","off")
ATLAS_LIFECYCLE_ALERT_LEVELS = tuple(
    x.strip().upper() for x in os.environ.get("ATLAS_LIFECYCLE_ALERT_LEVELS", "TP1,TP2,TP3,TP4,SL").split(",")
    if x.strip()
)
ATLAS_LIFECYCLE_ALERT_COOLDOWN_MIN = int(os.environ.get("ATLAS_LIFECYCLE_ALERT_COOLDOWN_MIN", "10"))
ATLAS_MULTI_EXCHANGE_ENABLED = os.environ.get("ATLAS_MULTI_EXCHANGE_ENABLED", "1").strip().lower() not in ("0","false","no","off")
ATLAS_MULTI_EXCHANGE_THRESHOLD_PCT = float(os.environ.get("ATLAS_MULTI_EXCHANGE_THRESHOLD_PCT", "0.35"))
ATLAS_MULTI_EXCHANGE_SYMBOLS = tuple(
    x.strip().upper() for x in os.environ.get("ATLAS_MULTI_EXCHANGE_SYMBOLS", "BTC,ETH").split(",")
    if x.strip()
)
ATLAS_ECON_CALENDAR_ENABLED = os.environ.get("ATLAS_ECON_CALENDAR_ENABLED", "1").strip().lower() not in ("0","false","no","off")
ATLAS_ECON_EVENT_LOOKAHEAD_HOURS = int(os.environ.get("ATLAS_ECON_EVENT_LOOKAHEAD_HOURS", "168"))
ATLAS_ECON_HIGH_IMPACT_HOURS = int(os.environ.get("ATLAS_ECON_HIGH_IMPACT_HOURS", "12"))

def _opt_telegram_destinations():
    out=[]
    for c in (TELEGRAM_CHAT_ID,TELEGRAM_GROUP_CHAT_ID):
        if c and c not in out:
            out.append(c)
    return out

def _opt_alert_db():
    conn=sqlite3.connect(DB_FILE)
    conn.execute("""
        create table if not exists lifecycle_alert_dedupe(
            alert_key text primary key,
            sent_at text not null
        )
    """)
    conn.commit()
    return conn

def _opt_should_send_alert(key, cooldown_min=None):
    cooldown_min=ATLAS_LIFECYCLE_ALERT_COOLDOWN_MIN if cooldown_min is None else cooldown_min
    now=now_tehran()
    conn=_opt_alert_db()
    try:
        row=conn.execute("select sent_at from lifecycle_alert_dedupe where alert_key=?",(key,)).fetchone()
        if not row:
            return True
        try:
            prev=datetime.fromisoformat(row[0])
            if prev.tzinfo is None:
                prev=prev.replace(tzinfo=now.tzinfo)
            return (now-prev).total_seconds()/60.0 >= cooldown_min
        except Exception:
            return True
    finally:
        conn.close()

def _opt_mark_alert_sent(key):
    conn=_opt_alert_db()
    try:
        conn.execute(
            """insert into lifecycle_alert_dedupe(alert_key,sent_at)
               values(?,?)
               on conflict(alert_key) do update set sent_at=excluded.sent_at""",
            (key,now_tehran().isoformat())
        )
        conn.commit()
    finally:
        conn.close()

def format_lifecycle_notification(event):
    to_state=str(event.get("to") or "").upper()
    icon="🎯" if to_state.startswith("TP") else "🛑" if to_state=="SL" else "🚨"
    return (
        f"{icon} ATLAS LIFECYCLE ALERT\n\n"
        f"{event.get('symbol','?')} reached {to_state}\n"
        f"Price: {fmt(event.get('price'))}\n"
        f"Previous: {event.get('from') or 'N/A'}\n"
        f"Event: {event.get('event') or to_state}\n"
        f"Time: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')} Tehran"
    )

def notify_lifecycle_changes(events):
    if not ATLAS_LIFECYCLE_ALERTS:
        return 0,[]
    sent,errors=0,[]
    for event in events or []:
        to_state=str(event.get("to") or "").upper()
        if to_state not in ATLAS_LIFECYCLE_ALERT_LEVELS:
            continue
        key=f"{event.get('symbol')}|{to_state}|{event.get('price')}"
        if not _opt_should_send_alert(key):
            continue
        msg=format_lifecycle_notification(event)
        ok=False
        for c in _opt_telegram_destinations():
            try:
                telegram_send_one(c,msg)
                sent+=1
                ok=True
            except Exception as e:
                errors.append(f"LIFECYCLE_ALERT[{event.get('symbol')}:{to_state}] {c}: {e}")
        if ok:
            _opt_mark_alert_sent(key)
    return sent,errors

def format_signal_notification(r, old_state, old_direction=None, old_trend=None):
    coin=_aio_symbol(r)
    new_state=r.get("intel_decision") or r.get("decision_state") or r.get("action") or "N/A"
    confidence=r.get("confidence")
    if confidence is None:
        confidence=r.get("decision_support_score")
    if confidence is None:
        confidence=r.get("signal_score")
    reason=r.get("intel_reason") or r.get("reason") or "No explicit reason available."
    return (
        f"🚨 ATLAS SIGNAL CHANGE\n\n"
        f"{coin}\n"
        f"Previous: {old_state}\n"
        f"New: {new_state}\n"
        f"Direction: {old_direction or 'N/A'} → {r.get('direction','N/A')}\n"
        f"Trend: {old_trend or 'N/A'} → {r.get('regime_trend','N/A')}\n"
        f"Confidence: {confidence if confidence is not None else 'N/A'}\n"
        f"R/R: {r.get('rr','N/A')}\n"
        f"Entry: {fmt(r.get('entry'))}\n"
        f"SL: {fmt(r.get('sl'))}\n"
        f"TP1: {fmt(r.get('tp1'))}\n"
        f"TP2: {fmt(r.get('tp2'))}\n"
        f"MTF: {r.get('mtf_agreement','N/A')}\n"
        f"Evidence: {r.get('evidence_agreement','N/A')}\n"
        f"Portfolio Risk Allowed: {'YES' if r.get('portfolio_risk_allowed', True) else 'NO'}\n\n"
        f"Reason: {reason}"
    )

def _opt_num(v, default=None):
    try:
        if v is None or v=="":
            return default
        return float(v)
    except Exception:
        return default

def _opt_backtest_db_rows(limit=500):
    conn=sqlite3.connect(DB_FILE)
    conn.row_factory=sqlite3.Row
    try:
        tables={r[0] for r in conn.execute("select name from sqlite_master where type='table'").fetchall()}
        rows=[]
        for name in ("backtests","signal_outcomes"):
            if name in tables:
                try:
                    q=conn.execute(f"select * from {name} order by rowid desc limit ?",(limit,)).fetchall()
                    rows.extend(dict(r) for r in q)
                except Exception:
                    pass
        return rows
    finally:
        conn.close()

def _opt_backtest_metrics(rows):
    import statistics
    returns=[]; wins=0; losses=0; drawdowns=[]
    explicit={"win_rate":[],"profit_factor":[],"sharpe":[],"max_drawdown":[]}
    for r in rows or []:
        for k in ("pnl_pct","return_pct","net_return_pct","profit_pct","pnl"):
            v=_opt_num(r.get(k))
            if v is not None:
                returns.append(v); break
        outcome=str(r.get("outcome") or r.get("result") or r.get("status") or "").upper()
        if any(x in outcome for x in ("WIN","TP","PROFIT")): wins+=1
        elif any(x in outcome for x in ("LOSS","SL","STOP")): losses+=1
        for src,dst in (
            ("win_rate","win_rate"),("profit_factor","profit_factor"),
            ("sharpe","sharpe"),("sharpe_ratio","sharpe"),
            ("max_drawdown","max_drawdown"),("max_drawdown_pct","max_drawdown")
        ):
            v=_opt_num(r.get(src))
            if v is not None: explicit[dst].append(v)
        dd=_opt_num(r.get("drawdown_pct"))
        if dd is not None: drawdowns.append(abs(dd))
    win_rate=(wins/(wins+losses)*100.0) if wins+losses else (statistics.mean(explicit["win_rate"]) if explicit["win_rate"] else None)
    pf=statistics.mean(explicit["profit_factor"]) if explicit["profit_factor"] else None
    if pf is None and returns:
        gp=sum(x for x in returns if x>0); gl=abs(sum(x for x in returns if x<0))
        if gl>0: pf=gp/gl
    sharpe=statistics.mean(explicit["sharpe"]) if explicit["sharpe"] else None
    if sharpe is None and len(returns)>=2:
        sd=statistics.pstdev(returns)
        if sd>0: sharpe=statistics.mean(returns)/sd
    maxdd=max(drawdowns) if drawdowns else (max(explicit["max_drawdown"]) if explicit["max_drawdown"] else None)
    expectancy=statistics.mean(returns) if returns else None
    return {"samples":len(rows or []),"wins":wins,"losses":losses,"win_rate":win_rate,"profit_factor":pf,
            "sharpe_like":sharpe,"max_drawdown_pct":maxdd,"expectancy_pct":expectancy}

def build_backtest_report():
    rows=_opt_backtest_db_rows()
    m=_opt_backtest_metrics(rows)
    cut=max(1,len(rows)//2) if rows else 0
    cur=_opt_backtest_metrics(rows[:cut]) if cut else {}
    base=_opt_backtest_metrics(rows[cut:]) if len(rows)>=20 else {}
    def f(v,d=2,s=""):
        return "N/A" if v is None else f"{v:.{d}f}{s}"
    return "\n".join([
        "ATLAS AI — BACKTEST DASHBOARD","="*64,
        f"Stored Samples: {m.get('samples',0)}",
        f"Wins / Losses: {m.get('wins',0)} / {m.get('losses',0)}",
        f"Win Rate: {f(m.get('win_rate'),1,'%')}",
        f"Profit Factor: {f(m.get('profit_factor'))}",
        f"Sharpe-like: {f(m.get('sharpe_like'))}",
        f"Max Drawdown: {f(m.get('max_drawdown_pct'),2,'%')}",
        f"Expectancy: {f(m.get('expectancy_pct'),3,'%')}",
        "",
        "Recent vs Baseline:",
        f"Recent Win Rate: {f(cur.get('win_rate'),1,'%')}",
        f"Baseline Win Rate: {f(base.get('win_rate'),1,'%')}",
        f"Recent PF: {f(cur.get('profit_factor'))}",
        f"Baseline PF: {f(base.get('profit_factor'))}",
        "",
        "N/A means the current persisted schema does not support a safe calculation."
    ])

_ATLAS_2026_FOMC=[
    ("2026-09-15T00:00:00","FOMC Meeting — Day 1"),
    ("2026-09-16T00:00:00","FOMC Meeting — Decision / Press Conference"),
    ("2026-10-27T00:00:00","FOMC Meeting — Day 1"),
    ("2026-10-28T00:00:00","FOMC Meeting — Decision / Press Conference"),
    ("2026-12-08T00:00:00","FOMC Meeting — Day 1"),
    ("2026-12-09T00:00:00","FOMC Meeting — Decision / Press Conference"),
]

def fetch_economic_calendar():
    if not ATLAS_ECON_CALENDAR_ENABLED:
        return []
    now=now_tehran()
    out=[]
    for ds,name in _ATLAS_2026_FOMC:
        try:
            dt=datetime.fromisoformat(ds)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=now.tzinfo)
            hours=(dt-now).total_seconds()/3600.0
            if 0<=hours<=ATLAS_ECON_EVENT_LOOKAHEAD_HOURS:
                out.append({"event":name,"date":dt.isoformat(),"importance":3,"source":"Federal Reserve","hours_until":round(hours,1)})
        except Exception:
            pass
    te_key=os.environ.get("TRADINGECONOMICS_API_KEY","").strip()
    if te_key:
        try:
            start=now.date().isoformat()
            end=(now+timedelta(hours=ATLAS_ECON_EVENT_LOOKAHEAD_HOURS)).date().isoformat()
            url=("https://api.tradingeconomics.com/calendar/country/United%20States/"
                 f"{start}/{end}?c={te_key}&importance=3&f=json")
            raw=safe_http_get(url, timeout=12)
            if isinstance(raw,str): raw=json.loads(raw)
            if isinstance(raw,dict): raw=raw.get("data") or raw.get("results") or []
            for x in raw or []:
                name=str(x.get("Event") or x.get("Category") or "")
                if not any(k in name.upper() for k in ("CPI","CONSUMER PRICE","NON FARM","NFP","FOMC","FEDERAL FUNDS","PAYROLL")):
                    continue
                ds=x.get("Date")
                dt=datetime.fromisoformat(str(ds).replace("Z","+00:00")) if ds else None
                if dt is not None and dt.tzinfo is None: dt=dt.replace(tzinfo=now.tzinfo)
                hours=((dt-now).total_seconds()/3600.0) if dt else None
                out.append({
                    "event":name,"date":dt.isoformat() if dt else str(ds),"importance":x.get("Importance",3),
                    "actual":x.get("Actual"),"forecast":x.get("Forecast"),"previous":x.get("Previous"),
                    "source":x.get("Source") or "Trading Economics",
                    "hours_until":round(hours,1) if hours is not None else None
                })
        except Exception as e:
            print(f"⚠️ Economic calendar augmentation unavailable: {e}")
    seen=set(); events=[]
    for e in sorted(out,key=lambda z:(z.get("hours_until") is None,z.get("hours_until") or 1e9)):
        k=(e.get("event"),str(e.get("date"))[:16])
        if k in seen: continue
        seen.add(k); events.append(e)
    return events

def build_economic_calendar_context(events):
    if not events:
        return ["Economic Calendar: no tracked high-impact event in the configured lookahead window."]
    lines=["Economic Calendar / Event Risk:"]
    for e in events[:8]:
        h=e.get("hours_until")
        risk="HIGH" if h is not None and h<=ATLAS_ECON_HIGH_IMPACT_HOURS else "UPCOMING"
        extra=[]
        if e.get("forecast") not in (None,""): extra.append(f"Forecast={e.get('forecast')}")
        if e.get("previous") not in (None,""): extra.append(f"Previous={e.get('previous')}")
        lines.append(f"- [{risk}] {e.get('event')} | in {h if h is not None else '?'}h" + (f" | {' | '.join(extra)}" if extra else ""))
    return lines

def _opt_exchange_last_price(exchange_id, symbol):
    try:
        # Resolve native CCXT id (e.g. gate) to ATLAS alias (e.g. gateio).
        alias = None
        for atlas_name, native_id in EXCHANGE_CCXT_IDS.items():
            if exchange_id == atlas_name or exchange_id == native_id:
                if atlas_name in EX:
                    alias = atlas_name
                    break
        if alias is None and exchange_id in EX:
            alias = exchange_id
        if alias is None:
            return None
        t = exchange_ticker(alias, symbol)
        return f(t.get("price"))
    except Exception:
        return None

def compare_multi_exchange_prices(symbols=None):
    import statistics
    if not ATLAS_MULTI_EXCHANGE_ENABLED:
        return []
    ensure_exchanges()
    symbols = list(symbols or ATLAS_MULTI_EXCHANGE_SYMBOLS)

    preferred_native = ("binance", "okx", "kucoin", "gate")
    exchanges = []
    for native in preferred_native:
        for atlas_name, ccxt_id in EXCHANGE_CCXT_IDS.items():
            if (native == atlas_name or native == ccxt_id) and atlas_name in EX:
                if atlas_name not in exchanges:
                    exchanges.append(atlas_name)
                break

    rows = []
    for sym in symbols:
        px = {}
        for atlas_eid in exchanges:
            v = _opt_exchange_last_price(atlas_eid, sym)
            if v is not None:
                px[atlas_eid] = v
        if len(px) < 2:
            continue
        vals = list(px.values())
        lo, hi = min(vals), max(vals)
        mid = statistics.mean(vals)
        spread = ((hi - lo) / mid * 100.0) if mid else 0.0
        rows.append({
            "symbol": sym,
            "prices": px,
            "spread_pct": round(spread, 4),
            "meaningful": spread >= ATLAS_MULTI_EXCHANGE_THRESHOLD_PCT,
        })
    return rows


def build_multi_exchange_context(rows):
    if not rows:
        return ["Multi-Exchange: insufficient comparable prices or feature disabled."]
    lines=["Multi-Exchange Comparison:"]
    for r in rows:
        label="⚠️ MEANINGFUL" if r.get("meaningful") else "normal"
        px=", ".join(f"{k}={fmt(v)}" for k,v in r.get("prices",{}).items())
        lines.append(f"- {r.get('symbol')}: spread={r.get('spread_pct')}% [{label}] | {px}")
    return lines

def send_optimization_documents(backtest_text):
    dt=now_tehran(); tag=shamsi(dt).replace("/","")+"_"+dt.strftime("%H%M%S")
    fn=f"08_ATLAS_BACKTEST_DASHBOARD_{tag}.txt"
    sent,errors=0,[]
    for c in _opt_telegram_destinations():
        try:
            _telegram_send_document(c,backtest_text,fn,"📈 ATLAS | Backtest Dashboard")
            sent+=1
        except Exception as e:
            errors.append(f"OPT_DOC[{fn}] {c}: {e}")
    return sent,errors



# ============================================================
# ATLAS PERFORMANCE TELEMETRY — FULL PROFILING
# Function-level + subsystem-level timing/call/error statistics.
# Observability only: no decision logic is changed.
# ============================================================
import time as _atlas_time
import functools as _atlas_functools
import threading as _atlas_threading
from concurrent.futures import ThreadPoolExecutor as _AtlasThreadPoolExecutor, as_completed as _atlas_as_completed

_ATLAS_PERF = {}
_ATLAS_FUNC_PERF = {}
_ATLAS_PROFILE_INSTALLED = False

class _AtlasTimer:
    def __init__(self, name):
        self.name = name
        self.started = None
    def __enter__(self):
        self.started = _atlas_time.perf_counter()
        return self
    def __exit__(self, exc_type, exc, tb):
        elapsed = _atlas_time.perf_counter() - self.started
        _ATLAS_PERF[self.name] = _ATLAS_PERF.get(self.name, 0.0) + elapsed
        return False

def _atlas_perf_reset():
    _ATLAS_PERF.clear()
    _ATLAS_FUNC_PERF.clear()
    _ATLAS_PERF["_TOTAL_STARTED"] = _atlas_time.perf_counter()

def _atlas_record_function(name, elapsed, failed=False):
    row = _ATLAS_FUNC_PERF.setdefault(
        name, {"calls": 0, "total": 0.0, "max": 0.0, "errors": 0}
    )
    row["calls"] += 1
    row["total"] += float(elapsed)
    row["max"] = max(float(row["max"]), float(elapsed))
    if failed:
        row["errors"] += 1

def _atlas_profile_wrapper(name, fn):
    if getattr(fn, "_atlas_profiled", False):
        return fn
    @_atlas_functools.wraps(fn)
    def wrapped(*args, **kwargs):
        started = _atlas_time.perf_counter()
        failed = False
        try:
            return fn(*args, **kwargs)
        except Exception:
            failed = True
            raise
        finally:
            _atlas_record_function(
                name,
                _atlas_time.perf_counter() - started,
                failed=failed,
            )
    wrapped._atlas_profiled = True
    return wrapped

# Functions grouped by subsystem. Missing names are skipped safely.
_ATLAS_PROFILE_GROUPS = {
    "Preflight / Scheduler": [
        "telegram_preflight", "get_run_mode", "_automatic_run_plan",
    ],
    "Database / Persistence": [
        "init_sqlite", "evaluate_open_outcomes", "store_signal",
        "save_context", "save_run", "_save_snapshot_history",
        "_snapshot_previous_prices", "_p1_lifecycle_db",
        "_aio_notification_db", "_opt_alert_db",
    ],
    "Universe / Market Discovery": [
        "build_universe", "global_market_intelligence",
        "market_breadth", "btc_market_regime",
    ],
    "Backtest / Self-Healing": [
        "mandatory_backtest_gate", "backtest_coin",
        "self_diagnostic", "_cached_backtest_gate",
        "_backtest_gate_fingerprint", "_store_backtest_gate_cache",
    ],
    "News / Macro / Whale": [
        "news_feed", "macro_snapshot", "fetch_fed_macro",
        "fetch_whale_activity", "_fetch_whale_activity_paid",
        "_fetch_whale_activity_free", "fetch_influential_figures_news",
        "build_intelligence_briefing", "fetch_economic_calendar",
    ],
    "Market Data / Exchange I/O": [
        "ensure_exchanges", "_atlas_prefetch_tickers", "exchange_ticker", "best_ohlcv",
        "_atlas_sqlite_ohlcv_get", "_atlas_sqlite_ohlcv_set",
        "tf_snapshot", "price_consensus", "safe_http_get", "http_get",
        "_opt_exchange_last_price", "compare_multi_exchange_prices",
    ],
    "Per-Asset Technical Analysis": [
        "analyze_coin", "technical_score", "indicator_snapshot",
        "support_resistance", "build_trade_plan",
    ],
    "Decision / Intelligence": [
        "apply_decision_engine", "v11_apply_intelligence",
        "v11_portfolio_diagnostics", "apply_evidence_fusion",
        "apply_mtf_confirmation", "build_portfolio_risk_intelligence",
        "apply_portfolio_risk_context", "update_signal_lifecycle",
        "decision_support_score", "build_decision_support",
    ],
    "Lifecycle / Signal Alerts": [
        "notify_lifecycle_changes", "send_signal_change_notifications",
        "format_lifecycle_notification", "format_signal_notification",
    ],
    "Report Generation": [
        "generate_analysis_documents", "build_market_context_txt",
        "build_deep_analysis_txt", "build_why_not_trade_txt",
        "build_portfolio_risk_txt", "generate_best_watch_csv",
        "generate_opportunity_ranking_csv", "generate_lifecycle_csv",
        "build_backtest_report", "build_image_table",
        "generate_split_csv_reports",
    ],
    "Telegram Documents / Reports": [
        "send_analysis_documents", "send_all_in_one_documents",
        "send_phase1_documents", "send_optimization_documents",
        "send_image_table", "send_csv_report",
    ],
    "Telegram Low-Level I/O": [
        "_telegram_send_document", "telegram_send_one",
        "send_with_retry", "telegram_api_get_me",
    ],
    "Snapshot": [
        "fetch_snapshot_results", "build_price_snapshot",
        "send_price_snapshot", "fetch_usdt_toman_public",
    ],
    "Voice": [
        "generate_voice_summary", "generate_audio_report",
        "text_to_speech_persian", "send_audio_report",
    ],
}

_ATLAS_FUNC_TO_GROUP = {
    fn: group
    for group, names in _ATLAS_PROFILE_GROUPS.items()
    for fn in names
}

def _atlas_install_full_profiler():
    global _ATLAS_PROFILE_INSTALLED
    if _ATLAS_PROFILE_INSTALLED:
        return
    installed = 0
    for fn_name in _ATLAS_FUNC_TO_GROUP:
        fn = globals().get(fn_name)
        if callable(fn):
            globals()[fn_name] = _atlas_profile_wrapper(fn_name, fn)
            installed += 1
    _ATLAS_PROFILE_INSTALLED = True
    print(f"⏱ Full profiler installed on {installed} ATLAS functions")

def _atlas_perf_mark_total():
    started = _ATLAS_PERF.get("_TOTAL_STARTED")
    if started is not None:
        _ATLAS_PERF["TOTAL_BEFORE_TELEMETRY_SEND"] = (
            _atlas_time.perf_counter() - started
        )

def _atlas_group_stats():
    grouped = {}
    for fn_name, row in _ATLAS_FUNC_PERF.items():
        group = _ATLAS_FUNC_TO_GROUP.get(fn_name, "Other")
        g = grouped.setdefault(
            group, {"calls": 0, "total": 0.0, "errors": 0, "functions": 0}
        )
        g["calls"] += int(row.get("calls", 0))
        g["total"] += float(row.get("total", 0.0))
        g["errors"] += int(row.get("errors", 0))
        g["functions"] += 1
    return grouped

def build_performance_telemetry_report():
    _atlas_perf_mark_total()
    grouped = _atlas_group_stats()

    lines = [
        "ATLAS AI — FULL PERFORMANCE PROFILING",
        "=" * 78,
        f"زمان گزارش: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')} تهران",
        "",
        "نکته: زمان گروه‌ها cumulative است؛ چون برخی توابع داخل توابع دیگر اجرا",
        "می‌شوند، جمع گروه‌ها الزاماً برابر TOTAL نیست. TOTAL زمان واقعی چرخه است.",
        "",
        "1) SUBSYSTEM PROFILE",
        "-" * 78,
        f"{'Subsystem':34} {'Calls':>8} {'Errors':>8} {'Cum.Time(s)':>14}",
    ]

    for group, row in sorted(
        grouped.items(), key=lambda kv: kv[1]["total"], reverse=True
    ):
        lines.append(
            f"{group[:34]:34} "
            f"{row['calls']:>8d} {row['errors']:>8d} "
            f"{row['total']:>14.2f}"
        )

    lines += [
        "",
        "2) SLOWEST FUNCTIONS — TOP 25",
        "-" * 78,
        f"{'Function':38} {'Calls':>7} {'Err':>5} {'Total(s)':>10} {'Max(s)':>10} {'Avg(s)':>10}",
    ]

    ranked = sorted(
        _ATLAS_FUNC_PERF.items(),
        key=lambda kv: kv[1]["total"],
        reverse=True,
    )
    for name, row in ranked[:25]:
        calls = max(1, int(row["calls"]))
        avg = float(row["total"]) / calls
        lines.append(
            f"{name[:38]:38} "
            f"{int(row['calls']):>7d} {int(row['errors']):>5d} "
            f"{float(row['total']):>10.2f} {float(row['max']):>10.2f} {avg:>10.3f}"
        )

    # High-call diagnostics can expose chatty APIs / repeated work.
    lines += [
        "",
        "3) HIGHEST CALL COUNTS — TOP 15",
        "-" * 78,
        f"{'Function':42} {'Calls':>10} {'Total(s)':>12}",
    ]
    by_calls = sorted(
        _ATLAS_FUNC_PERF.items(),
        key=lambda kv: kv[1]["calls"],
        reverse=True,
    )
    for name, row in by_calls[:15]:
        lines.append(
            f"{name[:42]:42} {int(row['calls']):>10d} {float(row['total']):>12.2f}"
        )

    if _ATLAS_PERF:
        lines += ["", "4) EXPLICIT MAIN-STAGE TIMERS", "-" * 78]
        for key, sec in sorted(
            ((k, v) for k, v in _ATLAS_PERF.items()
             if k not in ("_TOTAL_STARTED", "TOTAL_BEFORE_TELEMETRY_SEND")),
            key=lambda kv: kv[1],
            reverse=True,
        ):
            lines.append(f"- {key}: {float(sec):.2f}s")

    total = _ATLAS_PERF.get("TOTAL_BEFORE_TELEMETRY_SEND")
    lines += [
        "",
        "5) DATA CACHE EFFICIENCY",
        "-" * 78,
        f"{'Cache':26} {'Hits':>10} {'Misses':>10} {'Hit Rate':>12}",
    ]
    for cache_name, row in sorted(_ATLAS_CACHE_STATS.items()):
        hits = int(row.get("hit", 0))
        misses = int(row.get("miss", 0))
        total_cache = hits + misses
        rate = (hits / total_cache * 100.0) if total_cache else 0.0
        lines.append(
            f"{cache_name[:26]:26} {hits:>10d} {misses:>10d} {rate:>11.1f}%"
        )
    lines += [
        "",
        "Batch ticker prefetch:",
        f"- requests: {_ATLAS_BATCH_TICKER_STATS.get('requests', 0)}",
        f"- symbols cached: {_ATLAS_BATCH_TICKER_STATS.get('symbols', 0)}",
        f"- batch failures: {_ATLAS_BATCH_TICKER_STATS.get('failures', 0)}",
        f"- JIT ticker batches: {_ATLAS_BATCH_TICKER_STATS.get('jit_batches', 0)}",
        f"- analysis workers: {ATLAS_ANALYSIS_WORKERS}",
        f"- exchange max concurrency: {ATLAS_EXCHANGE_MAX_CONCURRENCY}",
        f"- OHLCV provider affinities learned: {len(_ATLAS_OHLCV_PROVIDER_AFFINITY)}",
        f"- OHLCV failed provider/timeframe routes skipped: {len(_ATLAS_OHLCV_PROVIDER_FAILURES)}",
        "",
        "Persistent Backtest Cache:",
        f"- SQLite hits: {_ATLAS_BT_CACHE_STATS.get('sqlite_hit', 0)}",
        f"- Supabase hits: {_ATLAS_BT_CACHE_STATS.get('supabase_hit', 0)}",
        f"- misses: {_ATLAS_BT_CACHE_STATS.get('miss', 0)}",
        f"- fingerprint mismatches: {_ATLAS_BT_CACHE_STATS.get('fingerprint_mismatch', 0)}",
        f"- Supabase cache rows examined: {_ATLAS_BT_CACHE_STATS.get('supabase_rows_seen', 0)}",
    ]

    lines += [
        "",
        "6) TOTAL RUNTIME",
        "-" * 78,
        f"TOTAL BEFORE TELEMETRY SEND: {float(total or 0.0):.2f}s",
    ]

    if ranked:
        slow_name, slow_row = ranked[0]
        lines += [
            "",
            "7) AUTOMATIC BOTTLENECK HINT",
            "-" * 78,
            f"کندترین تابع تجمعی: {slow_name} ({slow_row['total']:.2f}s / {slow_row['calls']} calls)",
        ]
        if slow_name in ("safe_http_get", "http_get", "exchange_ticker", "best_ohlcv"):
            lines.append("پیشنهاد: TTL cache، کاهش retry غیرضروری و reuse اتصال/metadata را بررسی کنید.")
        elif slow_name in ("mandatory_backtest_gate", "backtest_coin"):
            lines.append("پیشنهاد: cache بک‌تست، کاهش universe بک‌تست یا اجرای incremental را بررسی کنید.")
        elif slow_name.startswith("send_") or slow_name in ("_telegram_send_document", "send_with_retry"):
            lines.append("پیشنهاد: تعداد فایل‌ها، حجم payload، retry و latency تلگرام را بررسی کنید.")
        elif slow_name in ("analyze_coin", "tf_snapshot", "price_consensus"):
            lines.append("پیشنهاد: cache کندل بر اساس timeframe و اشتراک داده بین asset-analysisها را بررسی کنید.")

    lines += [
        "",
        "این profiling فقط observability است و سیگنال، Entry/SL/TP، Evidence،",
        "Backtest Gate، Legacy CSV یا Snapshot Arrow را تغییر نمی‌دهد.",
    ]
    return "\n".join(lines)

def send_performance_telemetry_report():
    content = build_performance_telemetry_report()
    dt = now_tehran()
    tag = shamsi(dt).replace("/", "") + "_" + dt.strftime("%H%M%S")
    filename = f"09_ATLAS_FULL_PERFORMANCE_PROFILING_{tag}.txt"
    sent, errors = 0, []
    destinations = []
    for c in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if c and c not in destinations:
            destinations.append(c)
    for c in destinations:
        try:
            _telegram_send_document(
                c, content, filename,
                "⏱ ATLAS | Full Performance Profiling"
            )
            sent += 1
        except Exception as e:
            errors.append(f"FULL_PROFILE[{c}]: {e}")
    return sent, errors

# Install wrappers after all profiler-target functions above have been defined
# and before main() starts using them.
_atlas_install_full_profiler()

# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    _atlas_perf_reset()
    _atlas_cache_reset()
    try:
        print(f"\n{'='*50}")
        print(f"🚀 {VERSION}")
        print(f"📅 {now_tehran().strftime('%Y-%m-%d %H:%M:%S')} Tehran")
        print(f"{'='*50}\n")
        
        try:
            telegram_preflight()
        except Exception as e:
            # یک preflight ناموفق (مثلاً یک هیک‌آپ گذرای شبکه در فراخوانی
            # getMe) نباید کل چرخه‌ی ۴ ساعته را فدا کند. تلاش واقعی برای
            # ارسال گزارش در send_report()/send_with_retry() منطق retry و
            # گزارش‌دهی خطای خودش را دارد و در پایین همچنان اجرا می‌شود؛
            # اگر ارسال واقعی هم شکست بخورد آن وقت اجرا با خطا پایان می‌یابد.
            print(f"⚠️ Telegram preflight failed (continuing anyway): {e}")
            append_changelog("TELEGRAM_PREFLIGHT", None, None, f"Preflight failed, continuing: {e}")
        run_mode = get_run_mode()
        print(f"📌 Run Mode: {run_mode}")
        print(f"📌 Scheduler: {os.environ.get('ATLAS_SCHEDULED_CADENCE', 'internal')}")
        print(f"📌 Engine Mode: {get_engine_mode()}")
        print(f"📌 Voice Enabled: {ENABLE_VOICE_REPORT}")
        print(f"📌 Auto Voice: {AUTO_SEND_VOICE}")
        print(f"📌 Image Table: {ENABLE_IMAGE_TABLE}")
        print()
        
        # GitHub Actions is the production scheduler.  A real scheduled
        # event is authoritative: once GitHub has started this job, ATLAS
        # must execute the full ANALYSIS + SNAPSHOT cycle and must not apply
        # local hour-modulo scheduling rules.
        scheduled_workflow = (
            os.environ.get("ATLAS_SCHEDULED_CADENCE", "").strip().lower() == "workflow"
            and os.environ.get("GITHUB_EVENT_NAME", "").strip().lower() == "schedule"
        )

        if scheduled_workflow:
            plan = _automatic_run_plan()
            do_analysis, do_snapshot = plan["analysis"], plan["snapshot"]
            print("⏰ GitHub scheduled event detected → forcing ANALYSIS + SNAPSHOT")
        elif run_mode == "AUTO":
            plan = _automatic_run_plan()
            do_analysis, do_snapshot = plan["analysis"], plan["snapshot"]
        elif run_mode == "SNAPSHOT":
            do_analysis, do_snapshot = False, True
        elif run_mode == "ANALYSIS":
            do_analysis, do_snapshot = True, False
        else:
            do_analysis, do_snapshot = True, True
        
        print(f"📋 Plan: Analysis={do_analysis}, Snapshot={do_snapshot}")
        print()

        total_sent = 0
        all_errors = []
        analysis_results = []
        
        # متغیرهای پیش‌فرض برای همه حالت‌ها
        news = None
        btc_regime = None
        macro = None
        market_info = None
        top10 = []
        dynamic30 = []

        if do_analysis:
            print("🔍 Starting ANALYSIS...")
            with _AtlasTimer("FULL CORE REPORT()"):
                text, results, macro, news, market_info, unavailable = report()
            print(f"✅ Analysis complete: {len(results)} results, {unavailable} unavailable")
            
            with _AtlasTimer("POST-REPORT INTELLIGENCE"):
                results = [v11_apply_intelligence(r) for r in results]
                v11_portfolio = v11_portfolio_diagnostics(results)
                top10, dynamic30 = list(_LAST_TOP10), list(_LAST_DYNAMIC30)
                btc_regime = btc_market_regime()
                breadth = market_breadth(results)
            
            with _AtlasTimer("Evidence + MTF + Risk + Lifecycle"):
                results = apply_evidence_fusion(results, news)
                results = apply_mtf_confirmation(results)
                portfolio_risk = build_portfolio_risk_intelligence(results, top10)
                results = apply_portfolio_risk_context(results, portfolio_risk)
                lifecycle_events = update_signal_lifecycle(results, top10)
            with _AtlasTimer("LIFECYCLE ALERT DELIVERY"):
                lifecycle_alert_sent, lifecycle_alert_errors = notify_lifecycle_changes(lifecycle_events)
            total_sent += lifecycle_alert_sent
            all_errors.extend(lifecycle_alert_errors)
            print(f"🎯 Lifecycle alerts sent: {lifecycle_alert_sent}, errors={len(lifecycle_alert_errors)}")
            print(f"📊 Building reports...")
            
            # ========================================================
            # FINAL TELEGRAM DELIVERY — TWO ANALYSIS DOCUMENTS
            # ========================================================
            # Do not send the old long text reports. The analysis engines
            # above remain unchanged; only the Telegram presentation layer
            # is changed to two comprehensive CSV documents.
            # ========================================================

            print("📊 Generating 2 separate analysis documents...")

            with _AtlasTimer("Analysis CSV Reports"):
                analysis_doc_sent, analysis_doc_errors = send_analysis_documents(
                    results, top10, dynamic30
                )

            total_sent += analysis_doc_sent
            all_errors.extend(analysis_doc_errors)

            print(
                f"📎 Analysis documents sent: {analysis_doc_sent}, "
                f"errors={len(analysis_doc_errors)}"
            )

            with _AtlasTimer("ALL-IN-ONE REPORT DELIVERY"):
                aio_sent, aio_errors = send_all_in_one_documents(
                    results, top10, macro, news, btc_regime
                )
            total_sent += aio_sent
            all_errors.extend(aio_errors)
            print(f"🧠 All-in-One documents sent: {aio_sent}, errors={len(aio_errors)}")

            with _AtlasTimer("Signal Notifications"):
                notify_sent, notify_errors = send_signal_change_notifications(results, top10)
            total_sent += notify_sent
            all_errors.extend(notify_errors)
            print(f"🚨 Signal-change notifications sent: {notify_sent}, errors={len(notify_errors)}")

            with _AtlasTimer("PHASE-1 REPORT DELIVERY"):
                phase1_sent, phase1_errors = send_phase1_documents(
                    results, top10, portfolio_risk
                )
            total_sent += phase1_sent
            all_errors.extend(phase1_errors)
            print(
                f"🧩 Phase-1 documents sent: {phase1_sent}, "
                f"lifecycle_events={len(lifecycle_events)}, errors={len(phase1_errors)}"
            )
            with _AtlasTimer("Backtest Dashboard"):
                backtest_dashboard = build_backtest_report()
                opt_sent, opt_errors = send_optimization_documents(backtest_dashboard)
            total_sent += opt_sent
            all_errors.extend(opt_errors)
            print(f"📈 Backtest dashboard sent: {opt_sent}, errors={len(opt_errors)}")

            # Keep a small compatibility marker for existing run metadata.
            outputs = []

            # ارسال جدول تصویری - با بررسی ENABLE_IMAGE_TABLE
            if ENABLE_IMAGE_TABLE:
                print("📸 Generating image table...")
                with _AtlasTimer("PNG / IMAGE"):
                    image_sent = send_image_table(results, top10, dynamic30)
                if image_sent:
                    print("✅ Image table sent successfully")
                else:
                    print("ℹ️ Image table not sent (matplotlib may not be installed)")
            else:
                print("ℹ️ Image table disabled by ATLAS_ENABLE_IMAGE_TABLE")
            
            analysis_results = results
            # Also log to the price history table on analysis runs (every 4H),
            # not just snapshot runs (every 3H) — denser history improves the
            # accuracy of the 4H/24H direction lookups in build_price_snapshot.
            with _AtlasTimer("ANALYSIS SNAPSHOT HISTORY"):
                _save_snapshot_history(results, now_tehran().isoformat())
            
            # Keep the existing legacy CSV delivery active exactly as before.
            # The three requested analysis documents are additional outputs;
            # personal / metals / dynamic_top30 remain enabled.
            print("📊 Generating legacy split CSV reports...")
            with _AtlasTimer("LEGACY CSV DELIVERY"):
                csv_sent, csv_errors = send_csv_report(results, top10, dynamic30)
            total_sent += csv_sent
            all_errors.extend(csv_errors)
            print(f"CSV export: {csv_sent} destination(s), {len(csv_errors)} error(s)")

            perf_sent, perf_errors = send_performance_telemetry_report()
            total_sent += perf_sent
            all_errors.extend(perf_errors)
            print(f"⏱ Performance telemetry sent: {perf_sent}, errors={len(perf_errors)}")
            
            with _AtlasTimer("FINAL PERSISTENCE"):
                save_context(macro, news, market_liquidity_index(results), market_info)
                save_run(results, sum(len(split_telegram(x)) for x in outputs), macro, news, unavailable)

        if do_snapshot:
            print("📸 Starting SNAPSHOT...")
            with _AtlasTimer("SNAPSHOT FETCH"):
                snapshot_results = analysis_results if analysis_results else fetch_snapshot_results()
            print(f"✅ Snapshot results: {len(snapshot_results)}")
            with _AtlasTimer("SNAPSHOT DELIVERY"):
                snapshot_sent, snapshot_errors = send_price_snapshot(snapshot_results)
            total_sent += snapshot_sent
            all_errors.extend(snapshot_errors)
            print(f"✅ Snapshot sent: {snapshot_sent}")

        # ============================================================
        # VOICE REPORT - با بررسی وجود داده
        # ============================================================
        if ENABLE_VOICE_REPORT and AUTO_SEND_VOICE:
            try:
                print("\n🎤 Generating audio report...")
                
                snapshot_results = []
                if not analysis_results:
                    try:
                        snapshot_results = fetch_snapshot_results()
                        print(f"📊 Fetched {len(snapshot_results)} snapshot items for voice")
                    except Exception as e:
                        print(f"⚠️ Could not fetch snapshot: {e}")
                        snapshot_results = []
                
                voice_data = analysis_results if analysis_results else snapshot_results
                
                if voice_data:
                    # استفاده از متغیرهای تعریف شده با مقدار پیش‌فرض
                    news_data = news if news is not None else None
                    btc_data = btc_regime if btc_regime is not None else None
                    with _AtlasTimer("VOICE GENERATION"):
                        audio_file = generate_audio_report(voice_data, news_data, btc_data)
                    if audio_file:
                        with _AtlasTimer("VOICE DELIVERY"):
                            result = send_audio_report(audio_file, "🎤 گزارش صوتی کامل اطلس")
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

        # Full profiling is deliberately sent after analysis, persistence,
        # snapshot and voice so it measures the complete production cycle.
        try:
            perf_sent, perf_errors = send_performance_telemetry_report()
            total_sent += perf_sent
            all_errors.extend(perf_errors)
            print(f"⏱ Full performance profiling sent: {perf_sent}, errors={len(perf_errors)}")
        except Exception as perf_e:
            all_errors.append(f"FULL_PROFILE: {perf_e}")
            print(f"⚠️ Full performance profiling failed: {perf_e}")

        print(f"\n{'='*50}")
        print(f"📊 SUMMARY:")
        print(f"  Total sent: {total_sent}")
        print(f"  Errors: {len(all_errors)}")
        if all_errors:
            print(f"  Errors: {all_errors[:5]}")
        print(f"{'='*50}\n")

        if not do_analysis and not do_snapshot:
            print(f"{VERSION}: AUTO schedule has no task at this hour.")
            return 0

        if total_sent == 0:
            # هیچ پیامی به هیچ مقصدی نرسید — این واقعاً شکست کامل است.
            raise RuntimeError("Telegram delivery failed: " + "; ".join(all_errors or ["0 messages sent"]))

        if all_errors:
            # بخشی از خروجی‌ها (مثلاً CSV به یکی از دو مقصد، یا جدول تصویری)
            # ناموفق بود ولی گزارش اصلی رسید. قبلاً هر خطای جزئی کل جاب
            # گیت‌هاب اکشن را «Failed» می‌کرد؛ این باعث می‌شد به اشتباه به نظر
            # برسد که هیچ گزارشی ارسال نشده، در حالی که فقط بخشی از ارسال‌ها
            # ناقص بوده. حالا این حالت به‌عنوان هشدار ثبت می‌شود، نه شکست کامل.
            print(f"⚠️ Partial delivery failure ({len(all_errors)} error(s)) but {total_sent} message(s)/file(s) were delivered.")
            append_changelog("PARTIAL_DELIVERY", None, None, "; ".join(all_errors))

        return 0
    except Exception as e:
        tb = traceback.format_exc()
        append_changelog("FATAL", None, None, str(e), {"traceback": tb})
        print(f"{VERSION} ERROR: {e}")
        print(tb)
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
# ============================================================
# v11.5 - HUMAN-READABLE REPORT ENGINE
# ============================================================

def generate_human_readable_report(results, top10, dynamic30, macro, news, btc_regime):
    original_report = build_report(results, top10, dynamic30, macro, news, None, 0, btc_regime, None)
    human_sections = []
    human_sections.append("")
    human_sections.append("━━━━━━━━━━━━━━━━━━")
    human_sections.append("📝 تفسیر تحلیلی هوشمند (برای هر دارایی)")
    human_sections.append("━━━━━━━━━━━━━━━━━━")
    
    top_opportunities = top5_opportunities(results) or results[:5]
    for r in top_opportunities[:5]:
        coin = r.get("coin", "UNKNOWN")
        direction = r.get("direction", "NEUTRAL")
        setup_type = r.get("setup_type", "NO SETUP")
        entry = r.get("entry")
        sl = r.get("sl")
        tp1 = r.get("tp1")
        tp2 = r.get("tp2")
        rr = r.get("rr")
        confidence = r.get("confidence", 0)
        signal_score = r.get("signal_score", 0)
        win_prob = r.get("win_probability")
        regime = r.get("regime_trend", "نامشخص")
        volatility = r.get("regime_volatility", "نامشخص")
        reasons = r.get("no_trade_reasons", [])
        contradictions = r.get("contradictions", [])
        session, session_label, session_multiplier = get_current_session()
        
        setup_map = {
            "BREAKOUT": "شکست مقاومت (Breakout) با تأیید حجم",
            "BREAKOUT WATCH": "شکست مقاومت در انتظار تأیید",
            "BREAKDOWN": "شکست حمایت (Breakdown) با تأیید حجم",
            "BREAKDOWN WATCH": "شکست حمایت در انتظار تأیید",
            "PULLBACK": "بازگشت به حمایت (Pullback) و ادامه روند",
            "REVERSAL": "برگشت قیمت از سطح کلیدی (Reversal)",
            "RANGE": "بازار در محدوده (Range) - منتظر شکست",
            "TREND CONTINUATION": "ادامه روند",
            "NO SETUP": "ستاپ مشخص نیست"
        }
        setup_desc = setup_map.get(setup_type, setup_type.replace("_", " ").lower())
        
        section = []
        section.append("")
        section.append(f"🔹 تحلیل {coin}")
        section.append("───────────────────")
        
        if direction == "LONG":
            section.append(f"📈 جهت‌گیری: **صعودی (LONG)** — {setup_desc}")
        elif direction == "SHORT":
            section.append(f"📉 جهت‌گیری: **نزولی (SHORT)** — {setup_desc}")
        else:
            section.append(f"⚪ جهت‌گیری: خنثی — {setup_desc}")
        
        if entry and sl and tp1:
            section.append("")
            section.append("🎯 سناریوی معاملاتی:")
            if direction == "LONG":
                section.append(f"   • ورود: تایید شکست بالای {fmt(entry)} با افزایش حجم")
            else:
                section.append(f"   • ورود: تایید شکست زیر {fmt(entry)} با افزایش حجم")
            section.append(f"   • حد ضرر: زیر {fmt(sl)} برای محافظت در برابر شکست کاذب")
            section.append(f"   • هدف اول: {fmt(tp1)}")
            if tp2:
                section.append(f"   • هدف دوم: {fmt(tp2)} در صورت تداوم مومنتوم")
            if rr:
                section.append(f"   • نسبت ریسک به ریوارد: حدود ۱ به {rr:.1f}")
        else:
            section.append("")
            section.append("⏳ سناریوی معاملاتی: هنوز ورود معتبر تأیید نشده است.")
            if reasons:
                section.append("   دلایل: " + "، ".join([translate_reason_fa(r) for r in reasons[:3]]))
        
        section.append("")
        section.append("📊 تحلیل عمیق بازار:")
        section.append(f"   • رژیم کلی بازار: {regime}")
        section.append(f"   • سطح نوسان: {volatility}")
        section.append(f"   • امتیاز سیگنال: {signal_score:.0f}/۱۰۰")
        section.append(f"   • اطمینان مدل: {confidence:.0f}%")
        if win_prob is not None:
            section.append(f"   • احتمال برد (کالیبره): {win_prob:.0f}%")
        else:
            section.append("   • احتمال برد: هنوز کالیبره نشده (نیاز به معامله بسته بیشتر)")
        
        if contradictions:
            section.append("")
            section.append("⚠️ تضادهای شناسایی‌شده:")
            for c in contradictions[:3]:
                section.append(f"   • {translate_reason_fa(c)}")
        
        if sl:
            section.append("")
            if direction == "LONG":
                section.append(f"🔴 سطح ابطال: زیر {fmt(sl)}، که تز صعودی را باطل می‌کند.")
            else:
                section.append(f"🔴 سطح ابطال: بالای {fmt(sl)}، که تز نزولی را باطل می‌کند.")
        
        section.append("")
        section.append(f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")
        human_sections.append("\n".join(section))
    
    return original_report + "\n\n" + "\n".join(human_sections)


def generate_unified_report(results, top10, dynamic30, macro, news, btc_regime, breadth, market_info=None):
    original_report = build_report(results, top10, dynamic30, macro, news, market_info, 0, btc_regime, breadth)
    
    personal_report_text = ""
    if get_engine_mode() in ("PERSONAL", "BOTH"):
        personal_report_text = build_personal_report(results, macro, news, market_info, btc_regime, breadth)
    
    human_sections = []
    human_sections.append("")
    human_sections.append("━━━━━━━━━━━━━━━━━━")
    human_sections.append("📝 تفسیر تحلیلی جامع (همه ارزها)")
    human_sections.append("━━━━━━━━━━━━━━━━━━")
    
    ranked_results = sorted(
        [r for r in results if r.get("price") is not None],
        key=lambda x: (x.get("opportunity_score", 0), x.get("confidence", 0)),
        reverse=True
    )
    top_assets = ranked_results[:10]
    
    for idx, r in enumerate(top_assets, 1):
        coin = r.get("coin", "UNKNOWN")
        direction = r.get("direction", "NEUTRAL")
        setup_type = r.get("setup_type", "NO SETUP")
        decision_state = r.get("decision_state", "NO TRADE")
        price = r.get("price")
        change = r.get("change")
        support = r.get("support")
        resistance = r.get("resistance")
        entry = r.get("entry")
        sl = r.get("sl")
        tp1 = r.get("tp1")
        tp2 = r.get("tp2")
        tp3 = r.get("tp3")
        tp4 = r.get("tp4")
        rr = r.get("rr")
        confidence = r.get("confidence", 0)
        signal_score = r.get("signal_score", 0)
        model_strength = r.get("model_strength", 0)
        win_prob = r.get("win_probability")
        win_prob_tier = r.get("win_probability_tier", "NOT_CALIBRATED")
        regime_trend = r.get("regime_trend", "نامشخص")
        regime_volatility = r.get("regime_volatility", "نامشخص")
        regime_derivatives = r.get("regime_derivatives", "نامشخص")
        regime_score = r.get("regime_score", 0)
        data_quality = r.get("data_quality", 0)
        liquidity = r.get("liquidity", "UNKNOWN")
        volume_ratio = r.get("volume_ratio")
        rsi = r.get("rsi")
        macd = r.get("macd", "N/A")
        h4_trend = r.get("h4_trend", "UNKNOWN")
        d1_trend = r.get("d1_trend", "UNKNOWN")
        w1_trend = r.get("w1_trend", "UNKNOWN")
        reasons = r.get("no_trade_reasons", [])
        contradictions = r.get("contradictions", [])
        gate = r.get("gate", "BLOCK")
        gate_reason = r.get("gate_reason", "")
        session, session_label, session_multiplier = get_current_session()
        
        section = []
        section.append("")
        section.append(f"🔹 {idx}. تحلیل {coin}")
        section.append("───────────────────")
        
        if decision_state in ("BUY CONFIRMATION", "SELL CONFIRMATION") and gate == "PASS":
            status_emoji = "🟢" if "BUY" in decision_state else "🔴"
            status_text = "قابل اجرا (EXECUTABLE)" if "BUY" in decision_state else "قابل اجرا (EXECUTABLE)"
        elif "WATCH" in decision_state:
            status_emoji = "🟡"
            status_text = "در انتظار تأیید (WATCH)"
        else:
            status_emoji = "⚪"
            status_text = "بدون سیگنال (NO TRADE)"
        
        direction_text = {
            "LONG": "صعودی 📈",
            "SHORT": "نزولی 📉",
            "NEUTRAL": "خنثی ➡️",
            "NONE": "نامشخص ❓"
        }.get(direction, "نامشخص ❓")
        
        setup_map = {
            "BREAKOUT": "شکست مقاومت (Breakout)",
            "BREAKOUT WATCH": "شکست مقاومت در انتظار تأیید",
            "BREAKDOWN": "شکست حمایت (Breakdown)",
            "BREAKDOWN WATCH": "شکست حمایت در انتظار تأیید",
            "PULLBACK": "بازگشت به حمایت (Pullback)",
            "REVERSAL": "برگشت از سطح کلیدی (Reversal)",
            "RANGE": "بازار در محدوده (Range)",
            "TREND CONTINUATION": "ادامه روند",
            "NO SETUP": "ستاپ مشخص نیست"
        }
        setup_desc = setup_map.get(setup_type, setup_type.replace("_", " ").lower())
        
        section.append(f"📊 وضعیت: {status_emoji} {status_text}")
        section.append(f"🎯 جهت‌گیری: {direction_text}")
        section.append(f"📐 نوع ستاپ: {setup_desc}")
        section.append(f"💰 قیمت فعلی: {fmt(price)}")
        if change is not None:
            change_emoji = "🟢" if change > 0 else "🔴" if change < 0 else "➡️"
            section.append(f"📈 تغییر ۲۴ساعته: {change_emoji} {change:+.2f}%")
        
        section.append("")
        section.append("🎯 سناریوی معاملاتی:")
        if entry and sl and tp1 and gate == "PASS" and decision_state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            if direction == "LONG":
                section.append(f"   • ورود: تایید شکست و تثبیت بالای {fmt(entry)} با افزایش حجم")
                section.append(f"   • حد ضرر: زیر {fmt(sl)} (محافظت در برابر شکست کاذب)")
            else:
                section.append(f"   • ورود: تایید شکست و تثبیت زیر {fmt(entry)} با افزایش حجم")
                section.append(f"   • حد ضرر: بالای {fmt(sl)} (محافظت در برابر شکست کاذب)")
            section.append(f"   • هدف اول (TP1): {fmt(tp1)}")
            if tp2:
                section.append(f"   • هدف دوم (TP2): {fmt(tp2)} (در صورت تداوم مومنتوم)")
            if tp3:
                section.append(f"   • هدف سوم (TP3): {fmt(tp3)}")
            if tp4:
                section.append(f"   • هدف چهارم (TP4): {fmt(tp4)}")
            if rr:
                rr_text = "عالی" if rr >= 3 else "خوب" if rr >= 2 else "متوسط" if rr >= 1.5 else "پایین"
                section.append(f"   • نسبت ریسک به ریوارد: ۱ به {rr:.2f} ({rr_text})")
        else:
            section.append("   ⏳ ورود معتبر تأیید نشده است.")
            if reasons:
                section.append(f"   🔸 دلایل: " + "؛ ".join([translate_reason_fa(r) for r in reasons[:3]]))
            elif gate == "BLOCK" and gate_reason:
                section.append(f"   🔸 گیت مسدود: {translate_reason_fa(gate_reason)}")
            else:
                section.append("   🔸 منتظر تأیید ساختار و افزایش حجم باشید.")
        
        section.append("")
        section.append("📊 تحلیل عمیق بازار:")
        
        regime_map = {
            "RISK_ON": "🟢 ریسک‌پذیر (Risk-On) - تمایل صعودی",
            "RISK_OFF": "🔴 ریسک‌گریز (Risk-Off) - تمایل نزولی",
            "NEUTRAL": "🟡 خنثی",
            "TRENDING_BULL": "🟢 روند صعودی قوی",
            "TRENDING_BEAR": "🔴 روند نزولی قوی",
            "ACCUMULATION": "🟡 انباشت (خریداران قوی‌تر)",
            "DISTRIBUTION": "🟠 توزیع (فروشندگان قوی‌تر)",
            "RANGE": "🟡 محدوده (خنثی)"
        }
        regime_text = regime_map.get(regime_trend, regime_trend)
        section.append(f"   • رژیم بازار: {regime_text} (امتیاز: {regime_score}/۱۰۰)")
        
        vol_map = {
            "LOW": "🟢 پایین - مناسب برای ورود",
            "NORMAL": "🟡 عادی - قابل قبول",
            "HIGH": "🟠 بالا - احتیاط بیشتر",
            "EXTREME": "🔴 فوق‌العاده بالا - ریسک زیاد"
        }
        vol_text = vol_map.get(regime_volatility, regime_volatility)
        section.append(f"   • سطح نوسان: {vol_text}")
        
        deriv_map = {
            "NEUTRAL": "🟢 خنثی - بدون فشار اضافی",
            "LONG_CROWDED": "🟠 ازدحام خریداران - خطر ریزش",
            "SHORT_CROWDED": "🟠 ازدحام فروشندگان - خطر رشد",
            "UNAVAILABLE": "⚪ در دسترس نیست"
        }
        deriv_text = deriv_map.get(regime_derivatives, regime_derivatives)
        section.append(f"   • وضعیت مشتقات: {deriv_text}")
        
        dq_label = "عالی" if data_quality >= 80 else "خوب" if data_quality >= 60 else "متوسط" if data_quality >= 40 else "ضعیف"
        section.append(f"   • کیفیت داده: {data_quality:.0f}% ({dq_label})")
        liq_map = {"HIGH": "🟢 بالا", "MEDIUM": "🟡 متوسط", "LOW": "🔴 پایین"}
        section.append(f"   • نقدینگی: {liq_map.get(liquidity, liquidity)}")
        
        if volume_ratio is not None:
            vol_desc = "بسیار بالا (تأیید قوی)" if volume_ratio >= 1.5 else "بالاتر از میانگین" if volume_ratio >= 1.2 else "نزدیک به میانگین" if volume_ratio >= 0.8 else "پایین‌تر از میانگین (نیاز به احتیاط)"
            section.append(f"   • نسبت حجم: {volume_ratio:.2f}x ({vol_desc})")
        
        if rsi is not None:
            rsi_state = "اشباع خرید" if rsi > 70 else "اشباع فروش" if rsi < 30 else "منطقه تعادل" if 45 <= rsi <= 55 else "متمایل به صعود" if rsi > 55 else "متمایل به نزول"
            section.append(f"   • RSI: {rsi:.1f} ({rsi_state})")
        section.append(f"   • MACD: {macd}")
        section.append(f"   • روندها: H4={h4_trend} | D1={d1_trend} | W1={w1_trend}")
        if support or resistance:
            section.append(f"   • سطوح کلیدی: حمایت {fmt(support)} ↔ مقاومت {fmt(resistance)}")
        
        section.append("")
        section.append("📈 امتیازات و احتمال:")
        section.append(f"   • امتیاز سیگنال (Signal Score): {signal_score:.0f}/۱۰۰")
        section.append(f"   • قدرت مدل (Model Strength): {model_strength:.0f}%")
        if win_prob is not None:
            prob_text = "بالا" if win_prob >= 65 else "متوسط" if win_prob >= 50 else "پایین"
            section.append(f"   • احتمال برد (کالیبره): {win_prob:.0f}% ({prob_text}) — سطح: {win_prob_tier}")
        else:
            section.append(f"   • احتمال برد: هنوز کالیبره نشده (نیاز به معامله بسته بیشتر)")
        
        if contradictions:
            section.append("")
            section.append("⚠️ تضادهای شناسایی‌شده:")
            for c in contradictions[:4]:
                section.append(f"   • {translate_reason_fa(c)}")
        
        if r.get("warning"):
            section.append("")
            section.append(f"⚠️ هشدار: {r.get('warning')}")
        
        if sl and direction != "NEUTRAL":
            section.append("")
            if direction == "LONG":
                section.append(f"🔴 سطح ابطال (Invalidation): زیر {fmt(sl)}")
                section.append(f"   در صورت بسته‌شدن کندل زیر {fmt(sl)}، تز صعودی باطل شده و احتمال ریزش تا حمایت بعدی وجود دارد.")
            else:
                section.append(f"🔴 سطح ابطال (Invalidation): بالای {fmt(sl)}")
                section.append(f"   در صورت بسته‌شدن کندل بالای {fmt(sl)}، تز نزولی باطل شده و احتمال رشد تا مقاومت بعدی وجود دارد.")
        
        section.append("")
        section.append("🔄 سناریوی جایگزین:")
        if direction == "LONG" and support:
            section.append(f"   • در صورت شکست حمایت {fmt(support)}، سناریوی نزولی فعال می‌شود.")
            section.append(f"   • هدف نزولی احتمالی: {fmt(support * 0.97)}")
        elif direction == "SHORT" and resistance:
            section.append(f"   • در صورت شکست مقاومت {fmt(resistance)}، سناریوی صعودی فعال می‌شود.")
            section.append(f"   • هدف صعودی احتمالی: {fmt(resistance * 1.03)}")
        else:
            section.append("   • در صورت تغییر ساختار، سناریو بازبینی خواهد شد.")
            if support and resistance:
                section.append(f"   • محدوده فعلی: {fmt(support)} تا {fmt(resistance)}")
        
        section.append("")
        section.append(f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")
        if session == "OVERLAP":
            section.append("   ✅ همپوشانی سشن‌ها - نقدینگی بالا، اسپرد کمتر")
        elif session == "CLOSED":
            section.append("   ⚠️ خارج از سشن - نقدینگی پایین، اسپرد بیشتر")
        
        human_sections.append("\n".join(section))
    
    summary_section = []
    summary_section.append("")
    summary_section.append("━━━━━━━━━━━━━━━━━━")
    summary_section.append("🧠 خلاصه‌ی هوشمند و توصیه‌ی نهایی")
    summary_section.append("━━━━━━━━━━━━━━━━━━")
    
    total = len(results)
    executable = sum(1 for r in results if r.get("decision_state") in ("BUY CONFIRMATION", "SELL CONFIRMATION") and r.get("gate") == "PASS")
    bullish = sum(1 for r in results if r.get("direction") == "LONG")
    bearish = sum(1 for r in results if r.get("direction") == "SHORT")
    watch = sum(1 for r in results if "WATCH" in str(r.get("decision_state", "")))
    
    summary_section.append(f"📊 آمار کلی: {total} ارز بررسی شد | {executable} سیگنال اجرایی | {watch} در انتظار تأیید")
    summary_section.append(f"📈 جهت‌گیری بازار: {bullish} صعودی | {bearish} نزولی")
    
    if btc_regime:
        btc_state = btc_regime.get("regime", "UNKNOWN")
        if btc_state == "RISK_ON":
            summary_section.append("🟢 رژیم کلی بیت‌کوین: ریسک‌پذیر (Risk-On) — تمایل کلی بازار به سمت صعود است.")
        elif btc_state == "RISK_OFF":
            summary_section.append("🔴 رژیم کلی بیت‌کوین: ریسک‌گریز (Risk-Off) — تمایل کلی بازار به سمت نزول است.")
        else:
            summary_section.append("🟡 رژیم کلی بیت‌کوین: خنثی — بازار جهت مشخصی ندارد.")
    
    best = None
    best_score = -1
    for r in results:
        if r.get("decision_state") in ("BUY CONFIRMATION", "SELL CONFIRMATION") and r.get("gate") == "PASS":
            score = (r.get("opportunity_score", 0) * 0.5) + (r.get("confidence", 0) * 0.3) + (min(r.get("rr", 0) or 0, 5) * 4)
            if score > best_score:
                best_score = score
                best = r
    
    if best:
        direction_emoji = "🟢" if best.get("direction") == "LONG" else "🔴"
        summary_section.append("")
        summary_section.append(f"🏆 بهترین فرصت: {direction_emoji} {best.get('coin')}")
        summary_section.append(f"   • جهت‌گیری: {'خرید' if best.get('direction') == 'LONG' else 'فروش'}")
        summary_section.append(f"   • نقطه ورود: {fmt(best.get('entry'))}")
        summary_section.append(f"   • حد ضرر: {fmt(best.get('sl'))}")
        summary_section.append(f"   • هدف اول: {fmt(best.get('tp1'))}")
        if best.get('tp2'):
            summary_section.append(f"   • هدف دوم: {fmt(best.get('tp2'))}")
        summary_section.append(f"   • نسبت R/R: {best.get('rr', 0):.2f}")
        summary_section.append(f"   • اطمینان: {best.get('confidence', 0)}%")
        
        if best.get('win_probability') and best.get('win_probability') >= 60:
            summary_section.append("")
            summary_section.append("✅ توصیه: با توجه به امتیاز بالا و احتمال برد مناسب، این فرصت قابل بررسی است.")
            summary_section.append("   🔹 حجم معامله را بر اساس ریسک‌پذیری خود تنظیم کنید.")
            summary_section.append("   🔹 حد ضرر را حتماً رعایت کنید.")
        else:
            summary_section.append("")
            summary_section.append("⚠️ توصیه: با احتیاط رفتار کنید. احتمال برد هنوز در سطح اطمینان‌بخشی نیست.")
            summary_section.append("   🔹 منتظر تأیید بیشتر یا بهبود شرایط بازار باشید.")
    else:
        summary_section.append("")
        summary_section.append("⚪ هیچ فرصت اجرایی با کیفیت کافی پیدا نشد.")
        summary_section.append("   🔹 توصیه: در جایگاه ناظر (HOLD) باشید و منتظر شکل‌گیری ستاپ جدید بمانید.")
    
    if news and news.get("impact") == "HIGH":
        summary_section.append("")
        summary_section.append(f"📰 اخبار مهم: {news.get('bias', '')} | شدت تأثیر: بالا")
        summary_section.append("   ⚠️ در معاملات خود احتیاط بیشتری به خرج دهید.")
    
    summary_section.append("")
    summary_section.append("━━━━━━━━━━━━━━━━━━")
    summary_section.append("🔔 این گزارش یک توصیه‌ی سرمایه‌گذاری قطعی نیست.")
    summary_section.append("   همیشه قبل از هر معامله، تحلیل خود را انجام دهید.")
    summary_section.append(f"🕐 آخرین بروزرسانی: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')} تهران")
    
    final_report = original_report
    if personal_report_text:
        final_report += "\n\n" + personal_report_text
    final_report += "\n\n" + "\n".join(human_sections)
    final_report += "\n\n" + "\n".join(summary_section)
    
    return final_report
    
if __name__ == "__main__":
    raise SystemExit(main())
