#!/usr/bin/env python3
# ============================================================
# UNIT TESTS FOR ATLAS v11.2
# ============================================================

import unittest
import sys
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import (
    now_utc,
    now_tehran,
    shamsi,
    safe_float,
    f,
    clamp,
    fmt,
    pct,
    is_stable,
    is_ambiguous_symbol,
    closes,
    ema,
    sma,
    rsi,
    macd,
    atr,
    atr_pct,
    volume_ratio,
    volume_state,
    support_resistance,
    get_market_quality,
    graphical_price_display,
    generate_risk_report,
    detect_level_breaks,
    entry_quality_score,
    analyze_sentiment,
    calculate_correlation,
    smart_volume_analysis,
    detect_patterns,
    calculate_position_size,
    check_stop_loss_alert,
    trend_from_rows,
    _plan_is_allowed,
    _clear_trade_plan,
    _rr_from_values,
    tf_snapshot,
    price_consensus,
    candle_pattern,
    indicator_alignment,
    strong_divergence,
    momentum_30m,
    asset_liquidity,
    daily_key_levels,
    h4_fallback_levels,
    candle_trigger_state,
    calculate_levels,
    suggested_leverage,
    weekly_pivot,
    multi_source_validation,
    _cluster_levels,
    ATLAS_PRIORITY_TOP10,
    ATLAS_PERSONAL_ASSETS,
    ATLAS_METALS,
    VERSION,
    TEHRAN
)


class TestAtlasCore(unittest.TestCase):

    def test_now_utc(self):
        result = now_utc()
        self.assertIsNotNone(result)
        self.assertEqual(result.tzname(), 'UTC')

    def test_now_tehran(self):
        result = now_tehran()
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.tzinfo)

    def test_shamsi(self):
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = shamsi(dt)
        self.assertIsInstance(result, str)
        self.assertRegex(result, r'\d{4}/\d{2}/\d{2}')

    def test_safe_float(self):
        self.assertEqual(safe_float("123.45"), 123.45)
        self.assertEqual(safe_float("invalid"), None)
        self.assertEqual(safe_float(None), None)
        self.assertEqual(safe_float("123.45", 0), 123.45)
        self.assertEqual(safe_float("invalid", 0), 0)

    def test_f(self):
        self.assertEqual(f("123.45"), 123.45)
        self.assertEqual(f(None), None)

    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-5, 0, 10), 0)
        self.assertEqual(clamp(15, 0, 10), 10)

    def test_fmt(self):
        self.assertEqual(fmt(1000), "$1,000.00")
        self.assertEqual(fmt(123.456), "$123.4560")
        self.assertEqual(fmt(0.001234), "$0.001234")
        self.assertEqual(fmt(None), "N/A")

    def test_pct(self):
        self.assertEqual(pct(0.1234), "+12.34%")
        self.assertEqual(pct(-0.1234), "-12.34%")
        self.assertEqual(pct(None), "N/A")

    def test_is_stable(self):
        self.assertTrue(is_stable("USDT"))
        self.assertTrue(is_stable("usdc"))
        self.assertFalse(is_stable("BTC"))

    def test_is_ambiguous_symbol(self):
        self.assertTrue(is_ambiguous_symbol("M"))
        self.assertTrue(is_ambiguous_symbol("CC"))
        self.assertFalse(is_ambiguous_symbol("BTC"))

    def test_ema(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = ema(values, 3)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)

    def test_sma(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = sma(values, 3)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 9.0)

    def test_rsi(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
        result = rsi(values)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, 0)
        self.assertLessEqual(result, 100)

    def test_macd(self):
        values = list(range(1, 50))
        line, signal, hist = macd(values)
        self.assertIsNotNone(line)
        self.assertIsNotNone(signal)
        self.assertIsNotNone(hist)

    def test_atr(self):
        rows = [
            [0, 100, 110, 90, 100, 1000],
            [1, 100, 105, 95, 102, 1000],
            [2, 102, 108, 98, 105, 1000],
            [3, 105, 112, 100, 108, 1000],
            [4, 108, 115, 105, 110, 1000],
        ]
        result = atr(rows, 3)
        self.assertIsNotNone(result)

    def test_atr_pct(self):
        rows = [
            [0, 100, 110, 90, 100, 1000],
            [1, 100, 105, 95, 102, 1000],
            [2, 102, 108, 98, 105, 1000],
            [3, 105, 112, 100, 108, 1000],
            [4, 108, 115, 105, 110, 1000],
        ]
        result = atr_pct(rows, 3)
        self.assertIsNotNone(result)

    def test_volume_ratio(self):
        rows = [
            [0, 100, 110, 90, 100, 1000],
            [1, 100, 105, 95, 102, 2000],
            [2, 102, 108, 98, 105, 3000],
            [3, 105, 112, 100, 108, 4000],
            [4, 108, 115, 105, 110, 5000],
        ]
        result = volume_ratio(rows, 3)
        self.assertIsNotNone(result)

    def test_volume_state(self):
        rows = [
            [0, 100, 110, 90, 100, 1000],
            [1, 100, 105, 95, 102, 2000],
            [2, 102, 108, 98, 105, 3000],
            [3, 105, 112, 100, 108, 4000],
            [4, 108, 115, 105, 110, 5000],
        ]
        state, ratio = volume_state(rows)
        self.assertIn(state, ["STRONG", "WEAK", "NORMAL", "UNKNOWN"])

    def test_support_resistance(self):
        rows = [
            [0, 100, 110, 90, 100, 1000],
            [1, 100, 105, 95, 102, 1000],
            [2, 102, 108, 98, 105, 1000],
            [3, 105, 112, 100, 108, 1000],
            [4, 108, 115, 105, 110, 1000],
        ]
        support, resistance = support_resistance(rows)
        self.assertIsNotNone(support)
        self.assertIsNotNone(resistance)

    def test_get_market_quality(self):
        result = get_market_quality(
            {"regime": "RISK_ON"},
            {"score": 70},
            "NORMAL"
        )
        self.assertIsInstance(result, dict)
        self.assertIn("score", result)
        self.assertIn("level", result)
        self.assertIn("emoji", result)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_graphical_price_display(self):
        result = graphical_price_display(105, 100)
        self.assertIsInstance(result, str)
        self.assertIn("⬆️", result)

        result = graphical_price_display(95, 100)
        self.assertIsInstance(result, str)
        self.assertIn("⬇️", result)

        result = graphical_price_display(100, 100)
        self.assertIsInstance(result, str)
        self.assertIn("➡️", result)

    def test_generate_risk_report(self):
        result = generate_risk_report(
            {"regime": "RISK_ON"},
            {"score": 70},
            {"level": "HIGH", "score": 80}
        )
        self.assertIsInstance(result, str)
        self.assertIn("ریسک بازار", result)

    def test_detect_level_breaks(self):
        alerts = detect_level_breaks(90, 100, 110, 95)
        if len(alerts) == 0:
            alerts = detect_level_breaks(120, 100, 110, 115)
        self.assertGreater(len(alerts), 0)

    def test_entry_quality_score(self):
        score = entry_quality_score(100, 97, 1.5, 55, "BULLISH", "HIGH")
        self.assertIsInstance(score, (int, float))
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_analyze_sentiment(self):
        news = [
            {"title": "Bitcoin ETF approved"},
            {"title": "Massive hack on exchange"}
        ]
        result = analyze_sentiment(news)
        self.assertIsInstance(result, dict)
        self.assertIn("score", result)
        self.assertIn("level", result)

    def test_calculate_correlation(self):
        prices1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        prices2 = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
        result = calculate_correlation(prices1, prices2)
        self.assertIsInstance(result, (int, float))
        self.assertAlmostEqual(abs(result), 1.0, places=2)

    def test_smart_volume_analysis(self):
        result = smart_volume_analysis(2.5, 100, 250)
        self.assertIsInstance(result, dict)
        self.assertIn("alert", result)
        self.assertTrue(result["alert"])

        result = smart_volume_analysis(1.0, 100, 100)
        self.assertIsInstance(result, dict)
        self.assertIn("alert", result)
        self.assertFalse(result["alert"])

    def test_detect_patterns(self):
        rows = [
            [0, 100, 105, 95, 102, 1000] for _ in range(20)
        ]
        rows[-1][4] = 103
        patterns = detect_patterns(rows)
        self.assertIsInstance(patterns, list)

    def test_calculate_position_size(self):
        result = calculate_position_size(10000, 1.5, 100, 97)
        self.assertIsInstance(result, (int, float))
        self.assertGreater(result, 0)

        result = calculate_position_size(10000, 1.5, 100, 100)
        self.assertEqual(result, 0)

    def test_check_stop_loss_alert(self):
        result = check_stop_loss_alert(100, 98)
        self.assertIsInstance(result, dict)
        self.assertIn("alert", result)
        self.assertTrue(result["alert"])

        result = check_stop_loss_alert(100, 90)
        self.assertIsNone(result)

    def test_trend_from_rows(self):
        rows = [
            [0, 100, 105, 95, 102, 1000] for _ in range(20)
        ]
        rows[-1][4] = 110
        result = trend_from_rows(rows)
        self.assertIn(result, ["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"])

    def test_plan_is_allowed(self):
        self.assertTrue(_plan_is_allowed({"action": "BUY CONFIRMATION"}))
        self.assertTrue(_plan_is_allowed({"action": "SELL CONFIRMATION"}))
        self.assertTrue(_plan_is_allowed({"action": "BULLISH WATCH"}))
        self.assertFalse(_plan_is_allowed({"action": "NO TRADE"}))

    def test_clear_trade_plan(self):
        r = {"entry": 100, "sl": 95, "tp1": 110, "tp2": 120, "rr": 2.0}
        result = _clear_trade_plan(r)
        self.assertIsNone(result["entry"])
        self.assertIsNone(result["sl"])
        self.assertIsNone(result["tp1"])
        self.assertIsNone(result["tp2"])
        self.assertIsNone(result["rr"])

    def test_rr_from_values(self):
        result = _rr_from_values(100, 97, 110)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 3.333, places=2)

        result = _rr_from_values(100, 103, 90)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 3.333, places=2)

    def test_cluster_levels(self):
        values = [100, 101, 102, 110, 111, 112]
        result = _cluster_levels(values, 0.05)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_suggested_leverage(self):
        result = suggested_leverage(0.5)
        self.assertIsInstance(result, (int, float))
        self.assertGreaterEqual(result, 1.0)

        result = suggested_leverage(5.0)
        self.assertEqual(result, 1.0)

    def test_weekly_pivot(self):
        rows = [
            [0, 100, 110, 90, 105, 1000] for _ in range(7)
        ]
        result = weekly_pivot(rows)
        self.assertIsNotNone(result)

    def test_multi_source_validation(self):
        result = multi_source_validation("BTC", 100)
        self.assertIsInstance(result, dict)
        self.assertIn("tradingview", result)
        self.assertIn("coinglass", result)
        self.assertIn("exchange", result)


class TestAtlasIntegration(unittest.TestCase):

    def test_constants(self):
        self.assertIsInstance(ATLAS_PRIORITY_TOP10, list)
        self.assertGreater(len(ATLAS_PRIORITY_TOP10), 0)
        self.assertIsInstance(ATLAS_PERSONAL_ASSETS, list)
        self.assertGreater(len(ATLAS_PERSONAL_ASSETS), 0)
        self.assertIsInstance(ATLAS_METALS, tuple)
        self.assertGreater(len(ATLAS_METALS), 0)

    def test_version(self):
        self.assertIsInstance(VERSION, str)
        self.assertIn("ATLAS", VERSION)
        self.assertIn("11.2", VERSION)


if __name__ == "__main__":
    unittest.main()
