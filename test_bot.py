"""
ATLAS AI v11.1 — Unit Tests
====================================
Tests for core functionality of the ATLAS AI trading bot.
"""

import os
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import from bot module
from bot import (
    VERSION,
    f,
    fmt,
    pct,
    clamp,
    now_utc,
    now_tehran,
    shamsi,
    safe_float,
    safe_mean,
    safe_median,
    is_stable,
    is_ambiguous_symbol,
    _parse_bool,
    get_current_session,
    get_next_session_time,
    get_run_mode,
    get_engine_mode,
    _fmt_price,
    _fmt_change,
    _get_status_emoji,
    action_emoji,
    _rr_from_values,
    _validate_trade_geometry,
    _snapshot_direction,
    _snapshot_price_text,
    TEHRAN,
)


class TestHelpers(unittest.TestCase):
    """Test helper functions"""

    def test_f(self):
        """Test safe_float wrapper"""
        self.assertEqual(f(10.5), 10.5)
        self.assertEqual(f("10.5"), 10.5)
        self.assertEqual(f(None), None)
        self.assertEqual(f("invalid"), None)
        self.assertEqual(f("invalid", 0), 0)
        self.assertEqual(f(True), None)

    def test_fmt(self):
        """Test price formatting"""
        self.assertEqual(fmt(1234.56), "$1,234.56")
        self.assertEqual(fmt(12.34), "$12.3400")
        self.assertEqual(fmt(0.1234), "$0.123400")
        self.assertEqual(fmt(0.00012345), "$0.000123")
        self.assertEqual(fmt(None), "N/A")

    def test_pct(self):
        """Test percentage formatting"""
        self.assertEqual(pct(10.5), "+10.50%")
        self.assertEqual(pct(-5.2), "-5.20%")
        self.assertEqual(pct(None), "N/A")

    def test_clamp(self):
        """Test clamp function"""
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-5, 0, 10), 0)
        self.assertEqual(clamp(15, 0, 10), 10)

    def test_safe_float(self):
        """Test safe_float"""
        self.assertEqual(safe_float(10.5), 10.5)
        self.assertEqual(safe_float("10.5"), 10.5)
        self.assertEqual(safe_float(None), None)
        self.assertEqual(safe_float("invalid"), None)

    def test_safe_mean(self):
        """Test safe_mean"""
        self.assertEqual(safe_mean([1, 2, 3]), 2.0)
        self.assertEqual(safe_mean([None, 2, 3]), 2.5)
        self.assertEqual(safe_mean([]), None)
        self.assertEqual(safe_mean([None]), None)

    def test_safe_median(self):
        """Test safe_median"""
        self.assertEqual(safe_median([1, 2, 3]), 2)
        self.assertEqual(safe_median([1, 2, 3, 4]), 2.5)
        self.assertEqual(safe_median([]), None)

    def test_is_stable(self):
        """Test stablecoin detection"""
        self.assertTrue(is_stable("USDT"))
        self.assertTrue(is_stable("USDC"))
        self.assertTrue(is_stable("DAI"))
        self.assertFalse(is_stable("BTC"))
        self.assertFalse(is_stable("ETH"))
        self.assertFalse(is_stable(""))

    def test_is_ambiguous_symbol(self):
        """Test ambiguous symbol detection"""
        self.assertTrue(is_ambiguous_symbol("M"))
        self.assertTrue(is_ambiguous_symbol("CC"))
        self.assertFalse(is_ambiguous_symbol("BTC"))
        self.assertFalse(is_ambiguous_symbol(""))

    def test_parse_bool(self):
        """Test boolean parser"""
        self.assertTrue(_parse_bool("true"))
        self.assertTrue(_parse_bool("1"))
        self.assertTrue(_parse_bool("yes"))
        self.assertTrue(_parse_bool("on"))
        self.assertTrue(_parse_bool(True))
        self.assertFalse(_parse_bool("false"))
        self.assertFalse(_parse_bool("0"))
        self.assertFalse(_parse_bool("no"))
        self.assertFalse(_parse_bool("off"))
        self.assertFalse(_parse_bool(False))
        self.assertFalse(_parse_bool("random"))

    def test_now_utc(self):
        """Test UTC time"""
        now = now_utc()
        self.assertIsInstance(now, datetime)
        self.assertEqual(now.tzinfo, timezone.utc)

    def test_now_tehran(self):
        """Test Tehran time"""
        now = now_tehran()
        self.assertIsInstance(now, datetime)
        self.assertEqual(now.tzinfo, TEHRAN)

    def test_shamsi(self):
        """Test Persian date conversion"""
        dt = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
        result = shamsi(dt)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) == 10)


class TestMarketSessions(unittest.TestCase):
    """Test market session functions"""

    def test_get_current_session(self):
        """Test session detection"""
        dt = datetime(2026, 8, 28, 5, 0, 0, tzinfo=timezone.utc)
        name, label, multiplier = get_current_session(dt)
        self.assertEqual(name, "ASIA")
        self.assertIsInstance(multiplier, float)

        dt = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
        name, label, multiplier = get_current_session(dt)
        self.assertEqual(name, "EUROPE")

        dt = datetime(2026, 8, 28, 14, 0, 0, tzinfo=timezone.utc)
        name, label, multiplier = get_current_session(dt)
        self.assertEqual(name, "OVERLAP")

        dt = datetime(2026, 8, 28, 22, 0, 0, tzinfo=timezone.utc)
        name, label, multiplier = get_current_session(dt)
        self.assertEqual(name, "CLOSED")

    def test_get_next_session_time(self):
        """Test next session time"""
        dt = datetime(2026, 8, 28, 5, 0, 0, tzinfo=timezone.utc)
        name, next_dt = get_next_session_time(dt)
        self.assertEqual(name, "EUROPE")
        self.assertEqual(next_dt.hour, 7)

        dt = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
        name, next_dt = get_next_session_time(dt)
        self.assertEqual(name, "OVERLAP")
        self.assertEqual(next_dt.hour, 12)


class TestFormatting(unittest.TestCase):
    """Test formatting functions"""

    def test_fmt_price(self):
        """Test price formatting"""
        self.assertEqual(_fmt_price(123456.78), "$123,456.78")
        self.assertEqual(_fmt_price(123.45), "$123.4500")
        self.assertEqual(_fmt_price(0.1234), "$0.123400")
        self.assertEqual(_fmt_price(0.00012345), "$0.000123")
        self.assertEqual(_fmt_price(None), "N/A")

    def test_fmt_change(self):
        """Test change formatting"""
        self.assertEqual(_fmt_change(10.5), "+10.50%")
        self.assertEqual(_fmt_change(-5.2), "-5.20%")
        self.assertEqual(_fmt_change(None), "N/A")

    def test_get_status_emoji(self):
        """Test status emoji"""
        r_buy = {"action": "BUY CONFIRMATION"}
        r_sell = {"action": "SELL CONFIRMATION"}
        r_watch = {"action": "BULLISH WATCH"}
        r_wait = {"action": "NO TRADE"}

        self.assertEqual(_get_status_emoji(r_buy), "🟢 BULL")
        self.assertEqual(_get_status_emoji(r_sell), "🔴 BEAR")
        self.assertEqual(_get_status_emoji(r_watch), "⚪ WAIT")
        self.assertEqual(_get_status_emoji(r_wait), "⚪ WAIT")

    def test_action_emoji(self):
        """Test action emoji"""
        self.assertEqual(action_emoji("BUY CONFIRMATION"), "🟢 BUY")
        self.assertEqual(action_emoji("SELL CONFIRMATION"), "🔴 SELL")
        self.assertEqual(action_emoji("BULLISH WATCH"), "🟡 WATCH")
        self.assertEqual(action_emoji("BEARISH WATCH"), "🟠 WATCH-SELL")
        self.assertEqual(action_emoji("NO DATA"), "⚪ NO DATA")
        self.assertEqual(action_emoji("NO TRADE"), "⚪ WAIT")


class TestTradeGeometry(unittest.TestCase):
    """Test trade geometry validation"""

    def test_rr_from_values(self):
        """Test R/R calculation"""
        rr = _rr_from_values(100, 95, 110)
        self.assertEqual(rr, 2.0)

        rr = _rr_from_values(100, 105, 90)
        self.assertEqual(rr, 2.0)

        self.assertIsNone(_rr_from_values(None, 95, 110))
        self.assertIsNone(_rr_from_values(100, 100, 110))

    def test_validate_trade_geometry_long(self):
        """Test LONG geometry validation"""
        valid, reason = _validate_trade_geometry("LONG", 100, 95, 102, 110)
        self.assertTrue(valid)

        valid, reason = _validate_trade_geometry("LONG", 100, 95, 98, 110)
        self.assertFalse(valid)
        self.assertIn("invalid LONG geometry", reason)

        valid, reason = _validate_trade_geometry("LONG", 100, 105, 102, 110)
        self.assertFalse(valid)

    def test_validate_trade_geometry_short(self):
        """Test SHORT geometry validation"""
        valid, reason = _validate_trade_geometry("SHORT", 100, 105, 98, 90)
        self.assertTrue(valid)

        valid, reason = _validate_trade_geometry("SHORT", 100, 105, 102, 110)
        self.assertFalse(valid)

        valid, reason = _validate_trade_geometry("SHORT", 100, 95, 98, 90)
        self.assertFalse(valid)

    def test_validate_trade_geometry_min_rr(self):
        """Test minimum R/R requirement"""
        valid, reason = _validate_trade_geometry("LONG", 100, 98, 101, 103, min_rr=3.0)
        self.assertFalse(valid)
        self.assertIn("R/R below", reason)


class TestSnapshotHelpers(unittest.TestCase):
    """Test snapshot helper functions"""

    def test_snapshot_price_text(self):
        """Test price text formatting for snapshots"""
        self.assertEqual(_snapshot_price_text(123456.78), "$123,457")
        self.assertEqual(_snapshot_price_text(1234.56), "$1,234.56")
        self.assertEqual(_snapshot_price_text(12.34), "$12.34")
        self.assertEqual(_snapshot_price_text(0.1234), "$0.12")
        self.assertEqual(_snapshot_price_text(0.00012345), "$0.000123")
        self.assertEqual(_snapshot_price_text(None), None)

    def test_snapshot_direction(self):
        """Test direction arrow detection"""
        self.assertEqual(_snapshot_direction(110, 100), "⬆️")
        self.assertEqual(_snapshot_direction(90, 100), "⬇️")
        self.assertEqual(_snapshot_direction(100.02, 100), "➡️")
        self.assertEqual(_snapshot_direction(None, 100), "➡️")
        self.assertEqual(_snapshot_direction(110, None), "➡️")
        self.assertEqual(_snapshot_direction(110, 0), "➡️")


class TestRunMode(unittest.TestCase):
    """Test run mode detection"""

    @patch.dict(os.environ, {"ATLAS_RUN_MODE": "AUTO"})
    def test_get_run_mode_auto(self):
        self.assertEqual(get_run_mode(), "AUTO")

    @patch.dict(os.environ, {"ATLAS_RUN_MODE": "SNAPSHOT"})
    def test_get_run_mode_snapshot(self):
        self.assertEqual(get_run_mode(), "SNAPSHOT")

    @patch.dict(os.environ, {"ATLAS_RUN_MODE": "ANALYSIS"})
    def test_get_run_mode_analysis(self):
        self.assertEqual(get_run_mode(), "ANALYSIS")

    @patch.dict(os.environ, {"ATLAS_RUN_MODE": "BOTH"})
    def test_get_run_mode_both(self):
        self.assertEqual(get_run_mode(), "BOTH")

    @patch.dict(os.environ, {"ATLAS_RUN_MODE": "INVALID"})
    def test_get_run_mode_default(self):
        self.assertEqual(get_run_mode(), "AUTO")

    @patch.dict(os.environ, {})
    def test_get_run_mode_empty(self):
        self.assertEqual(get_run_mode(), "AUTO")


class TestEngineMode(unittest.TestCase):
    """Test engine mode detection"""

    @patch.dict(os.environ, {"ATLAS_ENGINE": "MARKET"})
    def test_get_engine_mode_market(self):
        self.assertEqual(get_engine_mode(), "MARKET")

    @patch.dict(os.environ, {"ATLAS_ENGINE": "PERSONAL"})
    def test_get_engine_mode_personal(self):
        self.assertEqual(get_engine_mode(), "PERSONAL")

    @patch.dict(os.environ, {"ATLAS_ENGINE": "BOTH"})
    def test_get_engine_mode_both(self):
        self.assertEqual(get_engine_mode(), "BOTH")

    @patch.dict(os.environ, {"ATLAS_ENGINE": "INVALID"})
    def test_get_engine_mode_default(self):
        self.assertEqual(get_engine_mode(), "BOTH")

    @patch.dict(os.environ, {})
    def test_get_engine_mode_empty(self):
        self.assertEqual(get_engine_mode(), "BOTH")


class TestVersion(unittest.TestCase):
    """Test version string"""

    def test_version(self):
        self.assertIn("ATLAS", VERSION)
        self.assertIn("v11", VERSION)


def run_tests():
    """Run all tests"""
    unittest.main(verbosity=2)


if __name__ == "__main__":
    run_tests()
