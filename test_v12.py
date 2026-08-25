#!/usr/bin/env python3

from pathlib import Path
import csv
import io
import sys
import types

# ------------------------------------------------------------
# ATLAS v12 — Unit Test
# Canonical engine: ATLAS_v12_bot.py
# ------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Allow the test to run even when ccxt is not installed locally.
try:
    import ccxt  # noqa: F401
except ImportError:
    ccxt = types.ModuleType("ccxt")
    sys.modules["ccxt"] = ccxt

# Canonical v12 engine import.
import ATLAS_v12_bot as bot


# ------------------------------------------------------------
# Test data
# ------------------------------------------------------------

rows = [
    {
        "coin": "BTC",
        "price": 100,
        "support": 90,
        "resistance": 120,
        "entry": 101,
        "sl": 95,
        "tp1": 110,
        "tp2": 120,
        "h4_trend": "BULLISH",
        "d1_trend": "BULLISH",
        "w1_trend": "BULLISH",
        "action": "BUY CONFIRMATION",
        "decision_state": "BUY CONFIRMATION",
        "direction": "LONG",
        "confidence": 82,
        "volume_ratio": 1.1,
        "market_cap": 1_000_000,
        "rsi": 61,
        "volume": 10_000,
    },
    {
        "coin": "ETH",
        "price": 100,
        "support": 90,
        "resistance": 110,
        "entry": 101,
        "sl": 95,
        "tp1": 105,
        "tp2": 99,
        "h4_trend": "BULLISH",
        "d1_trend": "BULLISH",
        "action": "BUY CONFIRMATION",
        "decision_state": "BUY CONFIRMATION",
        "direction": "LONG",
        "confidence": 95,
    },
]


# ------------------------------------------------------------
# Controlled test configuration
# ------------------------------------------------------------

bot.ATLAS_PERSONAL_ASSETS = ["BTC", "ETH"]
bot.ATLAS_METALS = ()
bot.ATLAS_PRIORITY_TOP10 = ["BTC"]


# ------------------------------------------------------------
# CSV 1 — Analysis Snapshot
# ------------------------------------------------------------

csv1 = bot.generate_csv_report(
    rows,
    ["BTC"],
    [],
)

assert csv1, "CSV1 is empty."

assert "MarketCap" in csv1, (
    "CSV1 does not contain MarketCap column."
)

parsed = list(
    csv.DictReader(
        io.StringIO(csv1)
    )
)

btc = next(
    row for row in parsed
    if row["Symbol"] == "BTC"
)

eth = next(
    row for row in parsed
    if row["Symbol"] == "ETH"
)

assert btc["Entry"] == "101.0", (
    f"Unexpected BTC Entry: {btc['Entry']!r}"
)

assert eth["Entry"] == "", (
    f"ETH should not have executable entry: {eth['Entry']!r}"
)


# ------------------------------------------------------------
# CSV 2 — Institutional Dataset
# ------------------------------------------------------------

fx = {
    "usd": {
        "value": 190_000,
    },
    "usdt": {
        "value": 191_000,
    },
}

csv2 = bot.generate_institutional_csv(
    rows,
    ["BTC"],
    [],
    fx,
)

assert csv2, "CSV2 is empty."

assert "fx_usd_toman" in csv2, (
    "CSV2 missing fx_usd_toman."
)

assert "fx_usdt_toman" in csv2, (
    "CSV2 missing fx_usdt_toman."
)

assert "TGJU" in csv2, (
    "CSV2 does not identify TGJU as FX source."
)


# ------------------------------------------------------------
# Health Check
# ------------------------------------------------------------

health = bot.health_check(rows)

assert health["successful"] == 2, (
    f"Expected 2 successful analyses, got "
    f"{health.get('successful')}"
)


# ------------------------------------------------------------
# Final result
# ------------------------------------------------------------

print("==========================================")
print(" ATLAS AI v12 UNIT TEST")
print("==========================================")
print("PASS: CSV1 Analysis Snapshot")
print("PASS: MarketCap export")
print("PASS: CSV2 Institutional Dataset")
print("PASS: TGJU USD/USDT fields")
print("PASS: Health Check")
print("==========================================")
print("PASS: ATLAS AI v12 unit test")
