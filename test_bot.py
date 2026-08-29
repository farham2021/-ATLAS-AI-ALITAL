# test_bot.py
# ============================================================
# ATLAS AI v11.1 — TEST SUITE
# ============================================================

import pytest
import os
import sys
import json
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

# تنظیم متغیرهای محیطی برای تست
os.environ["TELEGRAM_TOKEN"] = "test_token"
os.environ["TELEGRAM_CHAT_ID"] = "test_chat"
os.environ["TELEGRAM_GROUP_CHAT_ID"] = "test_group"
os.environ["ATLAS_RUN_MODE"] = "ANALYSIS"
os.environ["ATLAS_ENGINE"] = "BOTH"
os.environ["ATLAS_ENABLE_VOICE"] = "0"
os.environ["ATLAS_AUTO_SEND_VOICE"] = "0"
os.environ["ATLAS_ENABLE_IMAGE_TABLE"] = "0"
os.environ["ATLAS_CANDLE_EVENT_DEDUP"] = "0"

# وارد کردن ماژول bot
from bot import (
    VERSION,
    TIMEFRAMES,
    SIGNAL_TIMEFRAME,
    now_utc,
    now_tehran,
    shamsi,
    safe_float,
    f,
    safe_mean,
    safe_median,
    fmt,
    pct,
    clamp,
    is_stable,
    is_ambiguous_symbol,
    get_run_mode,
    get_engine_mode,
    get_current_session,
    get_next_session_time,
    _parse_bool,
    _fmt_price,
    _fmt_change,
    _get_status_emoji,
)


# ============================================================
# TEST CLASSES
# ============================================================

class TestBasicFunctions:
    """تست توابع پایه"""

    def test_version(self):
        """تست وجود نسخه"""
        assert VERSION is not None
        assert "ATLAS" in VERSION

    def test_timeframes(self):
        """تست تایم‌فریم‌ها"""
        assert "4h" in TIMEFRAMES
        assert "1d" in TIMEFRAMES
        assert "1w" in TIMEFRAMES
        assert "1M" in TIMEFRAMES

    def test_signal_timeframe(self):
        """تست تایم‌فریم سیگنال"""
        assert SIGNAL_TIMEFRAME == "4h"

    def test_now_utc(self):
        """تست زمان UTC"""
        dt = now_utc()
        assert dt.tzinfo == timezone.utc

    def test_now_tehran(self):
        """تست زمان تهران"""
        dt = now_tehran()
        assert dt.tzinfo is not None
        assert str(dt.tzinfo) == "Asia/Tehran"

    def test_shamsi(self):
        """تست تبدیل تاریخ شمسی"""
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = shamsi(dt)
        assert isinstance(result, str)
        assert len(result.split("/")) == 3

    def test_safe_float(self):
        """تست تبدیل به float"""
        assert safe_float("123") == 123.0
        assert safe_float("abc") is None
        assert safe_float(None) is None
        assert safe_float(456) == 456.0

    def test_f(self):
        """تست تابع f"""
        assert f("123") == 123.0
        assert f(None) is None

    def test_safe_mean(self):
        """تست میانگین"""
        assert safe_mean([1, 2, 3]) == 2.0
        assert safe_mean([]) is None
        assert safe_mean([1, None, 3]) == 2.0

    def test_safe_median(self):
        """تست میانه"""
        assert safe_median([1, 2, 3]) == 2.0
        assert safe_median([1, 2, 3, 4]) == 2.5
        assert safe_median([]) is None

    def test_fmt(self):
        """تست فرمت قیمت"""
        assert fmt(1000) == "$1,000.00"
        assert fmt(1.2345) == "$1.2345"
        assert fmt(None) == "N/A"

    def test_pct(self):
        """تست فرمت درصد"""
        assert pct(10.5) == "+10.50%"
        assert pct(-5.2) == "-5.20%"
        assert pct(None) == "N/A"

    def test_clamp(self):
        """تست محدودسازی"""
        assert clamp(5, 0, 10) == 5
        assert clamp(-1, 0, 10) == 0
        assert clamp(15, 0, 10) == 10

    def test_is_stable(self):
        """تست تشخیص استیبل‌کوین"""
        assert is_stable("USDT") is True
        assert is_stable("BTC") is False
        assert is_stable("USDC") is True

    def test_is_ambiguous_symbol(self):
        """تست تشخیص سمبل مبهم"""
        assert is_ambiguous_symbol("M") is True
        assert is_ambiguous_symbol("CC") is True
        assert is_ambiguous_symbol("BTC") is False

    def test_parse_bool(self):
        """تست تبدیل boolean"""
        assert _parse_bool("true") is True
        assert _parse_bool("1") is True
        assert _parse_bool("yes") is True
        assert _parse_bool("false") is False
        assert _parse_bool("0") is False
        assert _parse_bool("no") is False
        assert _parse_bool(True) is True
        assert _parse_bool(False) is False

    def test_get_run_mode(self):
        """تست حالت اجرا"""
        mode = get_run_mode()
        assert mode in ("AUTO", "SNAPSHOT", "ANALYSIS", "BOTH")

    def test_get_engine_mode(self):
        """تست حالت موتور"""
        mode = get_engine_mode()
        assert mode in ("MARKET", "PERSONAL", "BOTH")

    def test_fmt_price(self):
        """تست فرمت قیمت با _fmt_price"""
        assert _fmt_price(1000) == "$1,000.00"
        assert _fmt_price(1.2345) == "$1.2345"
        assert _fmt_price(None) == "N/A"

    def test_fmt_change(self):
        """تست فرمت تغییرات"""
        assert _fmt_change(10.5) == "+10.50%"
        assert _fmt_change(-5.2) == "-5.20%"
        assert _fmt_change(None) == "N/A"

    def test_get_status_emoji(self):
        """تست دریافت ایموجی وضعیت"""
        mock_r = {"action": "BUY CONFIRMATION"}
        assert _get_status_emoji(mock_r) == "🟢 BULL"
        
        mock_r = {"action": "SELL CONFIRMATION"}
        assert _get_status_emoji(mock_r) == "🔴 BEAR"
        
        mock_r = {"action": "WAIT"}
        assert _get_status_emoji(mock_r) == "⚪ WAIT"


class TestSessionFunctions:
    """تست توابع سشن"""

    def test_get_current_session(self):
        """تست تشخیص سشن فعلی"""
        name, label, multiplier = get_current_session()
        assert name in ("ASIA", "EUROPE", "AMERICA", "OVERLAP", "CLOSED")
        assert isinstance(multiplier, float)
        assert 0.7 <= multiplier <= 1.2

    def test_get_next_session_time(self):
        """تست زمان سشن بعدی"""
        name, dt = get_next_session_time()
        assert name in ("ASIA", "EUROPE", "AMERICA", "OVERLAP")
        assert isinstance(dt, datetime)


# ============================================================
# RUN TESTS
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
