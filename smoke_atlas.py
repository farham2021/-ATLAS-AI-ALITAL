#!/usr/bin/env python3
# ============================================================
# SMOKE TEST FOR ATLAS v11.2
# ============================================================

import os
import sys
import time
import json
import traceback
from datetime import datetime

# تنظیم مسیر
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ایمپورت از bot
from bot import (
    now_tehran,
    shamsi,
    fmt,
    f,
    ATLAS_PRIORITY_TOP10,
    ATLAS_PERSONAL_ASSETS,
    ATLAS_METALS,
    analyze_coin,
    build_report,
    build_personal_report,
    send_report,
    telegram_preflight,
    init_sqlite,
    VERSION,
    tf_snapshot,
    price_consensus,
    calculate_levels
)


def print_section(title):
    """چاپ بخش"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def smoke_test_basic():
    """تست اولیه - بررسی توابع پایه"""
    print_section("BASIC FUNCTIONS TEST")
    try:
        dt = now_tehran()
        print(f"✅ now_tehran: {dt}")
        print(f"✅ shamsi: {shamsi(dt)}")
        print(f"✅ fmt(1234.56): {fmt(1234.56)}")
        print(f"✅ VERSION: {VERSION}")
        print(f"✅ ATLAS_METALS: {ATLAS_METALS}")
        return True
    except Exception as e:
        print(f"❌ Basic test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_telegram():
    """تست اتصال تلگرام"""
    print_section("TELEGRAM CONNECTION TEST")
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        print("⚠️ TELEGRAM_TOKEN not set, skipping test")
        return True

    try:
        result = telegram_preflight()
        username = result.get('result', {}).get('username', 'unknown')
        print(f"✅ Telegram connected: @{username}")
        return True
    except Exception as e:
        print(f"❌ Telegram test failed: {e}")
        return False


def smoke_test_database():
    """تست دیتابیس"""
    print_section("DATABASE TEST")
    try:
        init_sqlite()
        print("✅ Database initialized successfully")
        return True
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_tf_snapshot():
    """تست snapshot تایم‌فریم"""
    print_section("TIMEFRAME SNAPSHOT TEST")
    try:
        coin = "BTC"
        result = tf_snapshot(coin)
        print(f"✅ tf_snapshot({coin}) returned {len(result)} timeframes")
        for tf, data in result.items():
            rows = data.get("rows", [])
            trend = data.get("trend", "UNKNOWN")
            print(f"   - {tf}: {len(rows)} candles, trend: {trend}")
        return True
    except Exception as e:
        print(f"❌ tf_snapshot test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_price_consensus():
    """تست اجماع قیمت"""
    print_section("PRICE CONSENSUS TEST")
    try:
        coin = "BTC"
        price, sources, quality, spread, errors = price_consensus(coin)
        print(f"✅ price_consensus({coin}):")
        print(f"   - Price: {fmt(price)}")
        print(f"   - Quality: {quality}")
        print(f"   - Sources: {len(sources)}")
        for src in sources[:3]:
            print(f"     • {src.get('source')}: {fmt(src.get('price'))}")
        if errors:
            print(f"   - Errors: {len(errors)}")
        return True
    except Exception as e:
        print(f"❌ price_consensus test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_calculate_levels():
    """تست محاسبه سطوح"""
    print_section("LEVELS CALCULATION TEST")
    try:
        coin = "BTC"
        snapshots = tf_snapshot(coin)
        tf4 = snapshots.get("4h", {})
        rows = tf4.get("rows", [])

        if not rows:
            print("⚠️ No 4H data available, skipping")
            return True

        levels = calculate_levels(rows, "LONG")
        if levels:
            print(f"✅ calculate_levels:")
            print(f"   - Entry: {fmt(levels.get('entry'))}")
            print(f"   - SL: {fmt(levels.get('sl'))}")
            print(f"   - TP1: {fmt(levels.get('tp1'))}")
            print(f"   - TP2: {fmt(levels.get('tp2'))}")
            return True
        else:
            print("⚠️ Could not calculate levels")
            return True
    except Exception as e:
        print(f"❌ calculate_levels test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_analyze():
    """تست تحلیل یک کوین"""
    print_section("COIN ANALYSIS TEST")
    try:
        coin = "BTC"
        weights = {
            "candle_pattern": 15,
            "rsi": 15,
            "macd": 15,
            "volume": 15,
            "higher_trend": 20,
            "news_clear": 15
        }
        market_news = {"impact": "NORMAL", "bias": "NEUTRAL"}

        result = analyze_coin(coin, market_news, weights)

        if result:
            print(f"✅ Analysis for {coin}:")
            print(f"   - Price: {fmt(result.get('price'))}")
            print(f"   - Action: {result.get('action')}")
            print(f"   - Confidence: {result.get('confidence')}%")
            print(f"   - Direction: {result.get('direction')}")
            print(f"   - Gate: {result.get('gate')}")
            print(f"   - Reason: {result.get('reason')}")
            return True
        else:
            print(f"❌ Analysis returned None for {coin}")
            return False
    except Exception as e:
        print(f"❌ Analysis test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_report():
    """تست تولید گزارش"""
    print_section("REPORT GENERATION TEST")
    try:
        results = []
        coins = ["BTC", "ETH", "BNB"]
        weights = {
            "candle_pattern": 15,
            "rsi": 15,
            "macd": 15,
            "volume": 15,
            "higher_trend": 20,
            "news_clear": 15
        }
        market_news = {"impact": "NORMAL", "bias": "NEUTRAL"}

        print("Analyzing coins...")
        for coin in coins:
            try:
                r = analyze_coin(coin, market_news, weights)
                if r:
                    results.append(r)
                    status = "✅" if r.get('gate') == "PASS" else "⚠️"
                    print(f"   {status} {coin}: {r['action']} ({r['confidence']}%)")
            except Exception as e:
                print(f"   ❌ {coin}: {e}")

        if not results:
            print("⚠️ No results to build report")
            return True

        report = build_report(
            results=results,
            top10=ATLAS_PRIORITY_TOP10,
            dynamic30=[],
            macro={},
            news={"impact": "NORMAL"},
            market_info={},
            unavailable=0
        )

        print(f"✅ Report generated ({len(report)} chars)")
        print("\n--- Report preview ---")
        lines = report.split('\n')
        for line in lines[:15]:
            print(line)
        if len(lines) > 15:
            print(f"... and {len(lines) - 15} more lines")
        return True
    except Exception as e:
        print(f"❌ Report test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_personal_report():
    """تست گزارش شخصی"""
    print_section("PERSONAL REPORT TEST")
    try:
        results = []
        weights = {
            "candle_pattern": 15,
            "rsi": 15,
            "macd": 15,
            "volume": 15,
            "higher_trend": 20,
            "news_clear": 15
        }
        market_news = {"impact": "NORMAL", "bias": "NEUTRAL"}

        print("Analyzing personal assets...")
        for coin in ATLAS_PERSONAL_ASSETS[:5]:
            try:
                r = analyze_coin(coin, market_news, weights)
                if r:
                    results.append(r)
                    status = "✅" if r.get('gate') == "PASS" else "⚠️"
                    print(f"   {status} {coin}: {r['action']}")
            except Exception as e:
                print(f"   ❌ {coin}: {e}")

        if not results:
            print("⚠️ No results for personal report")
            return True

        report = build_personal_report(
            results=results,
            macro={},
            news={"impact": "NORMAL"},
            market_info={}
        )

        print(f"✅ Personal report generated ({len(report)} chars)")
        return True
    except Exception as e:
        print(f"❌ Personal report test failed: {e}")
        traceback.print_exc()
        return False


def smoke_test_send_report():
    """تست ارسال گزارش (اختیاری - فقط در صورت وجود توکن)"""
    print_section("REPORT SEND TEST")

    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("⚠️ Telegram token or chat_id not set, skipping send test")
        return True

    try:
        test_message = f"🧪 Smoke test from ATLAS {VERSION} at {now_tehran()}"
        parts, sent, errors = send_report(test_message)

        if sent > 0:
            print(f"✅ Report sent: {sent} messages delivered")
            return True
        else:
            print(f"❌ Report send failed: {errors}")
            return False
    except Exception as e:
        print(f"❌ Send test failed: {e}")
        traceback.print_exc()
        return False


def main():
    """اجرای تمام تست‌ها"""
    print("=" * 60)
    print(f"  🚀 ATLAS {VERSION} SMOKE TEST")
    print(f"  📅 {shamsi(now_tehran())} {now_tehran().strftime('%H:%M:%S')}")
    print("=" * 60)

    tests = [
        ("Basic Functions", smoke_test_basic),
        ("Database", smoke_test_database),
        ("Telegram Connection", smoke_test_telegram),
        ("TF Snapshot", smoke_test_tf_snapshot),
        ("Price Consensus", smoke_test_price_consensus),
        ("Levels Calculation", smoke_test_calculate_levels),
        ("Coin Analysis", smoke_test_analyze),
        ("Report Generation", smoke_test_report),
        ("Personal Report", smoke_test_personal_report),
    ]

    # تست ارسال فقط در صورت فعال بودن
    if os.environ.get("SMOKE_TEST_SEND", "").lower() == "true":
        tests.append(("Send Report", smoke_test_send_report))

    passed = 0
    failed = 0
    results = []

    for name, test_func in tests:
        print(f"\n{'─' * 60}")
        try:
            if test_func():
                passed += 1
                results.append(f"✅ {name}: PASSED")
            else:
                failed += 1
                results.append(f"❌ {name}: FAILED")
        except Exception as e:
            failed += 1
            results.append(f"❌ {name}: ERROR - {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("  📊 SMOKE TEST RESULTS")
    print("=" * 60)

    for result in results:
        print(result)

    print(f"\n✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Total: {passed + failed}")

    if failed > 0:
        print("\n⚠️ Some tests failed!")
        sys.exit(1)
    else:
        print("\n🎉 All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
