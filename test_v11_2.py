#!/usr/bin/env python3

from pathlib import Path
import ast
import csv
import io
import sys
import types


# ============================================================
# CCXT STUB
# ============================================================

ccxt_stub = types.ModuleType("ccxt")
sys.modules.setdefault("ccxt", ccxt_stub)

sys.path.insert(0, str(Path(__file__).parent))

import bot


# ============================================================
# VERSION
# ============================================================

assert bot.VERSION.startswith(
    "ATLAS v11.2"
), bot.VERSION


# ============================================================
# FUNCTION CONTRACT
# ============================================================

required = [
    "build_report",
    "build_personal_report",
    "build_two_engine_reports",
    "atlas_engine_mode",
    "analyze_coin",
    "main",
    "build_price_snapshot",
    "fetch_snapshot_results",
    "send_price_snapshot",
    "generate_csv_report",
    "send_csv_report",
    "fetch_usdt_toman_public",
    "_automatic_run_plan",
]


missing = [
    name
    for name in required
    if not hasattr(bot, name)
]


assert not missing, (
    "Missing functions: "
    + ", ".join(missing)
)


# ============================================================
# GEOMETRY / CSV TEST
# ============================================================

rows = [
    {
        "coin": "BTC",
        "price": 100.0,
        "support": 90.0,
        "resistance": 120.0,
        "entry": 101.0,
        "sl": 95.0,
        "tp1": 110.0,
        "tp2": 120.0,
        "h4_trend": "BULLISH",
        "d1_trend": "BULLISH",
        "w1_trend": "BULLISH",
        "action": "BUY CONFIRMATION",
        "decision_state": "BUY CONFIRMATION",
        "direction": "LONG",
        "confidence": 82,
        "volume_ratio": 1.20,
        "rsi": 61,
        "volume": 10000,
        "market_cap": 1000000,
    },
    {
        "coin": "ETH",
        "price": 100.0,
        "support": 90.0,
        "resistance": 110.0,
        "entry": 101.0,
        "sl": 95.0,
        "tp1": 105.0,
        "tp2": 99.0,
        "h4_trend": "BULLISH",
        "d1_trend": "BULLISH",
        "action": "BUY CONFIRMATION",
        "decision_state": "BUY CONFIRMATION",
        "direction": "LONG",
        "confidence": 95,
    },
]


# ============================================================
# CSV
# ============================================================

csv_text = bot.generate_csv_report(
    rows,
    ["BTC"],
    [],
)


assert isinstance(csv_text, str)
assert len(csv_text) > 0


parsed = list(
    csv.DictReader(
        io.StringIO(csv_text)
    )
)


assert parsed, "CSV is empty"


btc = next(
    row
    for row in parsed
    if row.get("Symbol") == "BTC"
)


eth = next(
    row
    for row in parsed
    if row.get("Symbol") == "ETH"
)


# Invalid TP2 geometry must not be exported as
# an executable trade plan.

if "Entry" in eth:
    assert eth["Entry"] in ("", None)


# ============================================================
# CLOSED CANDLE CONTRACT
# ============================================================

assert hasattr(
    bot,
    "candle_is_closed"
)

assert hasattr(
    bot,
    "strip_incomplete"
)


# ============================================================
# TELEGRAM CONTRACT
# ============================================================

assert hasattr(
    bot,
    "telegram_preflight"
)

assert hasattr(
    bot,
    "telegram_send_one"
)

assert hasattr(
    bot,
    "send_report"
)


# ============================================================
# SCHEDULER
# ============================================================

plan = bot._automatic_run_plan


assert callable(plan)


# ============================================================
# REAL AST IMPORT CHECK
# ============================================================

source = Path(
    "bot.py"
).read_text(
    encoding="utf-8"
)

tree = ast.parse(
    source,
    filename="bot.py"
)


for node in ast.walk(tree):

    if isinstance(node, ast.Import):

        for alias in node.names:
            assert alias.name != "bot", (
                "Legacy import detected: import bot"
            )

    elif isinstance(node, ast.ImportFrom):

        assert node.module != "bot", (
            "Legacy import detected: from bot import ..."
        )


print(
    "ATLAS AI v11.2 UNIT TEST: PASS"
)
