"""
ATLAS AI v11.1 — Smoke Tests
====================================
Quick smoke tests to verify the bot can start and perform basic operations.
These tests run faster than full unit tests and are used for CI/CD pipelines.
"""

import os
import sys
import json
import time
import unittest
import tempfile
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import (
    VERSION,
    f,
    fmt,
    pct,
    clamp,
    now_utc,
    now_tehran,
    shamsi,
    is_stable,
    _parse_bool,
    get_current_session,
    get_run_mode,
    get_engine_mode,
    _rr_from_values,
    _validate_trade_geometry,
    safe_float,
    safe_mean,
    safe_median,
    DEFAULT_WEIGHTS,
    ATLAS_PRIORITY_TOP10,
    ATLAS_PERSONAL_ASSETS,
    ATLAS_STATIC,
    ATLAS_METALS,
    SNAPSHOT_SYMBOLS,
    MARKET_SESSIONS,
    TIMEFRAMES,
)


class SmokeTests(unittest.TestCase):
    """Smoke tests for critical functionality"""

    def test_version(self):
        """Test version string exists"""
        self.assertIsInstance(VERSION, str)
        self.assertNotEqual(VERSION, "")
        self.assertIn("ATLAS", VERSION)

    def test_imports(self):
        """Test all imports work"""
        self.assertIsNotNone(f)
        self.assertIsNotNone(fmt)
        self.assertIsNotNone(pct)
        self.assertIsNotNone(clamp)

    def test_basic_math(self):
        """Test basic math operations"""
        self.assertEqual(f(10.5), 10.5)
        self.assertEqual(f("10.5"), 10.5)
        self.assertEqual(f(None), None)
        self.assertEqual(fmt(1000), "$1,000.00")
        self.assertEqual(pct(10), "+10.00%")
        self.assertEqual(clamp(5, 0, 10), 5)

    def test_time_functions(self):
        """Test time functions"""
        now = now_utc()
        self.assertIsInstance(now, datetime)
        self.assertEqual(now.tzinfo, timezone.utc)

        tehran = now_tehran()
        self.assertIsInstance(tehran, datetime)

        shamsi_str = shamsi(now)
        self.assertIsInstance(shamsi_str, str)
        self.assertTrue(len(shamsi_str) >= 8)

    def test_session_detection(self):
        """Test session detection works"""
        name, label, multiplier = get_current_session()
        self.assertIsInstance(name, str)
        self.assertIsInstance(label, str)
        self.assertIsInstance(multiplier, float)
        self.assertGreater(multiplier, 0)
        self.assertLessEqual(multiplier, 1.5)

    def test_stablecoin_detection(self):
        """Test stablecoin detection"""
        self.assertTrue(is_stable("USDT"))
        self.assertTrue(is_stable("USDC"))
        self.assertFalse(is_stable("BTC"))
        self.assertFalse(is_stable("ETH"))

    def test_parse_bool(self):
        """Test boolean parser"""
        self.assertTrue(_parse_bool("true"))
        self.assertTrue(_parse_bool("1"))
        self.assertTrue(_parse_bool(True))
        self.assertFalse(_parse_bool("false"))
        self.assertFalse(_parse_bool("0"))
        self.assertFalse(_parse_bool(False))

    def test_constants_exist(self):
        """Test required constants exist"""
        self.assertIsInstance(ATLAS_PRIORITY_TOP10, list)
        self.assertGreater(len(ATLAS_PRIORITY_TOP10), 0)

        self.assertIsInstance(ATLAS_PERSONAL_ASSETS, list)
        self.assertGreater(len(ATLAS_PERSONAL_ASSETS), 0)

        self.assertIsInstance(ATLAS_STATIC, list)
        self.assertGreater(len(ATLAS_STATIC), 0)

        self.assertIsInstance(ATLAS_METALS, tuple)
        self.assertGreater(len(ATLAS_METALS), 0)

        self.assertIsInstance(SNAPSHOT_SYMBOLS, tuple)
        self.assertGreater(len(SNAPSHOT_SYMBOLS), 0)

        self.assertIsInstance(MARKET_SESSIONS, dict)
        self.assertGreater(len(MARKET_SESSIONS), 0)

        self.assertIsInstance(TIMEFRAMES, tuple)
        self.assertGreater(len(TIMEFRAMES), 0)

    def test_default_weights(self):
        """Test default weights exist"""
        self.assertIsInstance(DEFAULT_WEIGHTS, dict)
        self.assertGreater(len(DEFAULT_WEIGHTS), 0)
        self.assertIn("rsi", DEFAULT_WEIGHTS)
        self.assertIn("macd", DEFAULT_WEIGHTS)
        self.assertIn("volume", DEFAULT_WEIGHTS)

    def test_rr_calculation(self):
        """Test R/R calculation"""
        # Long position
        rr = _rr_from_values(100, 95, 110)
        self.assertEqual(rr, 2.0)

        # Short position
        rr = _rr_from_values(100, 105, 90)
        self.assertEqual(rr, 2.0)

        # Invalid cases
        self.assertIsNone(_rr_from_values(None, 95, 110))
        self.assertIsNone(_rr_from_values(100, 100, 110))

    def test_trade_geometry(self):
        """Test trade geometry validation"""
        # Valid LONG
        valid, reason = _validate_trade_geometry("LONG", 100, 95, 102, 110)
        self.assertTrue(valid)

        # Valid SHORT
        valid, reason = _validate_trade_geometry("SHORT", 100, 105, 98, 90)
        self.assertTrue(valid)

        # Invalid geometries
        valid, reason = _validate_trade_geometry("LONG", 100, 105, 102, 110)
        self.assertFalse(valid)

        valid, reason = _validate_trade_geometry("SHORT", 100, 95, 98, 90)
        self.assertFalse(valid)

    def test_safe_helpers(self):
        """Test safe helpers"""
        self.assertEqual(safe_float(10.5), 10.5)
        self.assertEqual(safe_float(None), None)
        self.assertEqual(safe_mean([1, 2, 3]), 2.0)
        self.assertEqual(safe_mean([]), None)
        self.assertEqual(safe_median([1, 2, 3]), 2)

    def test_run_mode(self):
        """Test run mode detection"""
        mode = get_run_mode()
        self.assertIn(mode, ["AUTO", "SNAPSHOT", "ANALYSIS", "BOTH"])

    def test_engine_mode(self):
        """Test engine mode detection"""
        mode = get_engine_mode()
        self.assertIn(mode, ["MARKET", "PERSONAL", "BOTH"])


class QuickIntegrationTests(unittest.TestCase):
    """Quick integration tests that don't require external APIs"""

    def test_symbol_data_structures(self):
        """Test symbol data structures"""
        # All symbols should be uppercase
        for s in ATLAS_PRIORITY_TOP10:
            self.assertEqual(s, s.upper())

        for s in ATLAS_PERSONAL_ASSETS:
            self.assertEqual(s, s.upper())

        for s in ATLAS_STATIC:
            self.assertEqual(s, s.upper())

        # No duplicates within priority list
        self.assertEqual(len(ATLAS_PRIORITY_TOP10), len(set(ATLAS_PRIORITY_TOP10)))

    def test_market_sessions(self):
        """Test market session structure"""
        for name, session in MARKET_SESSIONS.items():
            self.assertIn("open", session)
            self.assertIn("close", session)
            self.assertIn("label", session)
            self.assertIn("multiplier", session)
            self.assertIsInstance(session["open"], int)
            self.assertIsInstance(session["close"], int)
            self.assertIsInstance(session["multiplier"], float)
            self.assertGreater(session["multiplier"], 0)

    def test_timeframes(self):
        """Test timeframe constants"""
        expected = ("1h", "4h", "1d", "1w", "1M")
        self.assertEqual(TIMEFRAMES, expected)

    def test_snapshot_symbols(self):
        """Test snapshot symbols"""
        for s in SNAPSHOT_SYMBOLS:
            self.assertEqual(s, s.upper())

        # BTC should be first
        self.assertEqual(SNAPSHOT_SYMBOLS[0], "BTC")

    def test_metals(self):
        """Test metals configuration"""
        expected = ("GOLD", "SILVER", "COPPER")
        self.assertEqual(ATLAS_METALS, expected)


def run_smoke_tests():
    """Run all smoke tests"""
    print(f"\n🔥 Running Smoke Tests for {VERSION}")
    print("=" * 50)
    unittest.main(verbosity=2, exit=False)


if __name__ == "__main__":
    run_smoke_tests()
