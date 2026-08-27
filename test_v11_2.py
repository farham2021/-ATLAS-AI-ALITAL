#!/usr/bin/env python3
"""
ATLAS v11.2 Test Suite
تست تمام توابع جدید
"""

import sys
import types
from pathlib import Path

ccxt_stub = types.ModuleType('ccxt')
sys.modules.setdefault('ccxt', ccxt_stub)
sys.path.insert(0, str(Path(__file__).parent))

import bot

def test_all():
    print("🧪 ATLAS v11.2 TEST SUITE")
    print("━━━━━━━━━━━━━━━━━━")
    
    tests_passed = 0
    tests_failed = 0
    
    # 1. Test Voice Summary
    try:
        result = bot.generate_voice_summary([], {}, {})
        assert isinstance(result, str)
        tests_passed += 1
        print("✅ Voice Summary")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Voice Summary: {e}")
    
    # 2. Test Market Quality
    try:
        result = bot.get_market_quality({}, {}, "NORMAL")
        assert "score" in result
        assert "level" in result
        assert "emoji" in result
        tests_passed += 1
        print("✅ Market Quality")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Market Quality: {e}")
    
    # 3. Test Signal Ranking
    try:
        result = bot.rank_signals([], 5)
        assert isinstance(result, list)
        tests_passed += 1
        print("✅ Signal Ranking")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Signal Ranking: {e}")
    
    # 4. Test Graphical Price Display
    try:
        result = bot.graphical_price_display(100, 99)
        assert isinstance(result, str)
        tests_passed += 1
        print("✅ Graphical Price Display")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Graphical Price Display: {e}")
    
    # 5. Test Risk Report - اصلاح شده
    try:
        market_quality = {"level": "HIGH", "score": 80, "emoji": "🟢"}
        result = bot.generate_risk_report({}, {}, market_quality)
        assert isinstance(result, str)
        assert "ریسک" in result or "Risk" in result
        tests_passed += 1
        print("✅ Risk Report")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Risk Report: {e}")
    
    # 6. Test Level Break Alerts
    try:
        result = bot.detect_level_breaks(100, 90, 110, 95)
        assert isinstance(result, list)
        tests_passed += 1
        print("✅ Level Break Alerts")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Level Break Alerts: {e}")
    
    # 7. Test Multi-Timeframe Confirmation
    try:
        result = bot.multi_timeframe_confirmation("BTC", {})
        assert isinstance(result, dict)
        tests_passed += 1
        print("✅ Multi-Timeframe Confirmation")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Multi-Timeframe Confirmation: {e}")
    
    # 8. Test Entry Quality Score
    try:
        result = bot.entry_quality_score(100, 95, 1.5, 55, "BULLISH", "HIGH")
        assert isinstance(result, (int, float))
        tests_passed += 1
        print("✅ Entry Quality Score")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Entry Quality Score: {e}")
    
    # 9. Test Exit Signals
    try:
        result = bot.generate_exit_signal(100, 105, "LONG", 102, 108, 95)
        assert result is None or isinstance(result, dict)
        tests_passed += 1
        print("✅ Exit Signals")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Exit Signals: {e}")
    
    # 10. Test Sentiment Analysis
    try:
        result = bot.analyze_sentiment([])
        assert "score" in result
        tests_passed += 1
        print("✅ Sentiment Analysis")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Sentiment Analysis: {e}")
    
    # 11. Test Correlation Analysis
    try:
        result = bot.analyze_correlations([])
        assert isinstance(result, list)
        tests_passed += 1
        print("✅ Correlation Analysis")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Correlation Analysis: {e}")
    
    # 12. Test Smart Volume Analysis
    try:
        result = bot.smart_volume_analysis(2.0, 1000, 2000)
        assert isinstance(result, dict)
        tests_passed += 1
        print("✅ Smart Volume Analysis")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Smart Volume Analysis: {e}")
    
    # 13. Test Pattern Recognition
    try:
        rows = [[0, 1, 2, 0.5, 1.5, 1000] for _ in range(30)]
        result = bot.detect_patterns(rows)
        assert isinstance(result, list)
        tests_passed += 1
        print("✅ Pattern Recognition")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Pattern Recognition: {e}")
    
    # 14. Test Weekly Analysis
    try:
        result = bot.generate_weekly_analysis([])
        assert isinstance(result, str)
        tests_passed += 1
        print("✅ Weekly Analysis")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Weekly Analysis: {e}")
    
    # 15. Test Position Sizing
    try:
        result = bot.get_position_suggestion({"entry": 100, "sl": 95})
        if result:
            assert "units" in result
        tests_passed += 1
        print("✅ Position Sizing")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Position Sizing: {e}")
    
    # 16. Test Stop Loss Alert
    try:
        result = bot.check_stop_loss_alert(100, 98)
        assert result is None or isinstance(result, dict)
        tests_passed += 1
        print("✅ Stop Loss Alert")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Stop Loss Alert: {e}")
    
    # 17. Test CSV Export
    try:
        result = bot.generate_csv_report([], [], [])
        assert isinstance(result, str)
        tests_passed += 1
        print("✅ CSV Export")
    except Exception as e:
        tests_failed += 1
        print(f"❌ CSV Export: {e}")
    
    # 18. Test Market Session
    try:
        result = bot.get_current_session()
        assert isinstance(result, tuple)
        tests_passed += 1
        print("✅ Market Session")
    except Exception as e:
        tests_failed += 1
        print(f"❌ Market Session: {e}")
    
    # Summary
    print("━━━━━━━━━━━━━━━━━━")
    print(f"📊 Results: {tests_passed} passed, {tests_failed} failed")
    
    if tests_failed > 0:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("✅ ALL TESTS PASSED")
        sys.exit(0)

if __name__ == "__main__":
    test_all()
