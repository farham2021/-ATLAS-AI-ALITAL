#!/usr/bin/env python3
"""
ATLAS v10.0 — Smoke Test
------------------------
Static validation only.

این تست:
- هیچ API خارجی را صدا نمی‌زند.
- هیچ پیام Telegram ارسال نمی‌کند.
- فقط ساختار و سلامت اولیه ATLAS v10 را بررسی می‌کند.
"""

from pathlib import Path
import ast
import re
import sys


ROOT = Path(__file__).resolve().parent
BOT_FILE = ROOT / "bot.py"


EXPECTED_TOP10 = [
    "BTC",
    "ETH",
    "BNB",
    "XRP",
    "SOL",
    "TRX",
    "HYPE",
    "DOGE",
    "ADA",
    "MATIC",
]


def fail(message: str):
    print(f"ATLAS v10 SMOKE TEST: FAIL — {message}")
    sys.exit(1)


def main():

    print("=" * 60)
    print("ATLAS v10.0 — SMOKE TEST")
    print("=" * 60)

    # ---------------------------------------------------------
    # 1. bot.py must exist
    # ---------------------------------------------------------

    if not BOT_FILE.exists():
        fail("bot.py not found")

    print("✓ bot.py exists")

    # ---------------------------------------------------------
    # 2. Syntax validation
    # ---------------------------------------------------------

    try:
        source = BOT_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        fail(f"cannot read bot.py: {exc}")

    try:
        tree = ast.parse(source, filename=str(BOT_FILE))
    except SyntaxError as exc:
        fail(
            f"Python syntax error at line "
            f"{exc.lineno}: {exc.msg}"
        )

    print("✓ bot.py syntax valid")

    # ---------------------------------------------------------
    # 3. Version validation
    # ---------------------------------------------------------

    versions = re.findall(
        r"ATLAS(?: AI)? v(\d+\.\d+(?:\.\d+)?)",
        source,
        flags=re.IGNORECASE,
    )

    if not versions:
        fail("ATLAS version label not found")

    if not any(v.startswith("10.") for v in versions):
        fail(
            "ATLAS v10.x label not found. "
            f"Detected versions: {sorted(set(versions))}"
        )

    # Legacy v9 labels should not remain in executable/source
    # comments that identify the current architecture.
    legacy_versions = re.findall(
        r"ATLAS(?: AI)? v9(?:\.\d+){0,2}",
        source,
        flags=re.IGNORECASE,
    )

    if legacy_versions:
        fail(
            "legacy ATLAS v9 reference detected: "
            + ", ".join(sorted(set(legacy_versions)))
        )

    print("✓ ATLAS v10 version validated")
    print("✓ no legacy v9 architecture label detected")

    # ---------------------------------------------------------
    # 4. Required functions
    # ---------------------------------------------------------

    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef)
        )
    }

    required_functions = {
        "build_report",
        "send_report",
        "telegram_send_one",
    }

    missing = sorted(required_functions - functions)

    if missing:
        fail(
            "required functions missing: "
            + ", ".join(missing)
        )

    print("✓ core functions present")

    # ---------------------------------------------------------
    # 5. Top 10 priority radar
    # ---------------------------------------------------------

    expected_text = (
        "BTC → ETH → BNB → XRP → SOL → "
        "TRX → HYPE → DOGE → ADA → MATIC"
    )

    if expected_text not in source:

        # Fallback: verify individual symbols are present.
        missing_top10 = [
            symbol
            for symbol in EXPECTED_TOP10
            if symbol not in source
        ]

        if missing_top10:
            fail(
                "Top-10 priority radar incomplete: "
                + ", ".join(missing_top10)
            )

        fail(
            "Top-10 symbols exist but their required "
            "priority order was not found"
        )

    print(
        "✓ Top-10 priority order preserved:"
    )
    print(
        "  BTC → ETH → BNB → XRP → SOL → "
        "TRX → HYPE → DOGE → ADA → MATIC"
    )

    # ---------------------------------------------------------
    # 6. Dynamic Top 30
    # ---------------------------------------------------------

    dynamic_markers = [
        "Dynamic Top 30",
        "DYNAMIC TOP 30",
        "dynamic_top_30",
        "top30",
    ]

    if not any(marker in source for marker in dynamic_markers):
        fail(
            "Dynamic Top 30 logic/marker not found"
        )

    print("✓ Dynamic Top 30 supported")

    # ---------------------------------------------------------
    # 7. Top 300 gainers / losers
    # ---------------------------------------------------------

    if "TOP GAINERS" not in source:
        fail("TOP GAINERS section missing")

    if "TOP LOSERS" not in source:
        fail("TOP LOSERS section missing")

    if "Top 300" not in source:
        fail("Top 300 market-mover logic missing")

    print("✓ Top-300 gainers/losers preserved")

    # ---------------------------------------------------------
    # 8. Market intelligence modules
    # ---------------------------------------------------------

    required_markers = {
        "DXY": "DXY",
        "Fear & Greed": "Fear & Greed",
        "Liquidation Heatmap": "Liquidation Heatmap",
    }

    for marker, label in required_markers.items():

        if marker not in source:
            fail(
                f"required market module missing: {label}"
            )

    print("✓ DXY module present")
    print("✓ Fear & Greed module present")
    print("✓ Liquidation Heatmap module present")

    # ---------------------------------------------------------
    # 9. Closed-candle architecture
    # ---------------------------------------------------------

    closed_candle_markers = [
        "closed",
        "CLOSED",
        "closed-candle",
        "Closed-candle",
    ]

    if not any(
        marker in source
        for marker in closed_candle_markers
    ):
        fail(
            "closed-candle architecture marker not found"
        )

    print("✓ closed-candle architecture detected")

    # ---------------------------------------------------------
    # 10. Multi-timeframe architecture
    # ---------------------------------------------------------

    timeframe_markers = [
        "30M",
        "1H",
        "4H",
        "1D",
        "1W",
        "1M",
    ]

    missing_tf = [
        tf
        for tf in timeframe_markers
        if tf not in source
    ]

    if missing_tf:
        fail(
            "missing timeframe markers: "
            + ", ".join(missing_tf)
        )

    print(
        "✓ multi-timeframe architecture detected"
    )

    # ---------------------------------------------------------
    # 11. Decision engine
    # ---------------------------------------------------------

    decision_markers = [
        "BUY",
        "SELL",
        "WATCH",
        "NO TRADE",
        "Decision Board",
        "DECISION BOARD",
    ]

    missing_decision = [
        marker
        for marker in decision_markers
        if marker not in source
    ]

    if missing_decision:
        fail(
            "decision engine markers missing: "
            + ", ".join(missing_decision)
        )

    print("✓ decision engine detected")

    # ---------------------------------------------------------
    # 12. Risk controls
    # ---------------------------------------------------------

    risk_markers = [
        "RISK_PER_TRADE",
        "MAX_PORTFOLIO_OPEN_RISK",
        "RISK",
        "R/R",
    ]

    if not any(
        marker in source
        for marker in risk_markers
    ):
        fail("risk-management logic not detected")

    print("✓ risk-management layer detected")

    # ---------------------------------------------------------
    # 13. Report ordering
    # ---------------------------------------------------------

    ordering_markers = [
        "ATLAS TOP 10 PRIORITY",
        "DYNAMIC TOP 30",
        "ATLAS Static Radar",
    ]

    ordering_hits = sum(
        1
        for marker in ordering_markers
        if marker in source
    )

    if ordering_hits < 2:
        fail(
            "report ordering structure is incomplete"
        )

    print("✓ radar/report ordering structure detected")

    # ---------------------------------------------------------
    # 14. Final result
    # ---------------------------------------------------------

    print("=" * 60)
    print("ATLAS v10 SMOKE TEST: PASS")
    print("=" * 60)

    print("✓ bot.py exists")
    print("✓ Python syntax valid")
    print("✓ ATLAS v10 architecture detected")
    print("✓ no legacy v9 architecture label")
    print("✓ Top-10 priority order preserved")
    print("✓ Dynamic Top 30 preserved")
    print("✓ Top-300 gainers/losers preserved")
    print("✓ DXY preserved")
    print("✓ Fear & Greed preserved")
    print("✓ Liquidation Heatmap preserved")
    print("✓ closed-candle engine detected")
    print("✓ multi-timeframe engine detected")
    print("✓ decision engine detected")
    print("✓ risk controls detected")
    print("✓ report ordering detected")
    print("=" * 60)


if __name__ == "__main__":
    main()
