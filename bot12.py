#!/usr/bin/env python3
"""
ATLAS AI v12 - Reliable Analytical Engine

- 4H analytical engine
- No forced signals
- Standardized status levels
- Explicit R/R calculation for TP1 and TP2
- Confidence / RSI / volume filters
- TGJU is the primary source for USD and USDT
- Telegram delivery through telegram_delivery_v12.py
"""

from __future__ import annotations

import csv
import json
import re
import traceback

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests

from telegram_delivery_v12 import (
    send_report,
    send_csv as send_csv_report,
)


# ============================================================
# CONFIGURATION
# ============================================================

TGJU_USD_URL = (
    "https://www.tgju.org/profile/price_dollar_rl"
)

TGJU_USDT_URL = (
    "https://www.tgju.org/profile/price_dollar_usdt"
)

STATUS_LEVELS = (
    "STRONG BULL",
    "BULL",
    "NEUTRAL",
    "BEAR",
    "STRONG BEAR",
)

SETUP_LEVELS = (
    "EXECUTABLE",
    "BEST WATCH",
    "NO VALID SETUP",
)

REQUEST_TIMEOUT = 15


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class SetupResult:

    symbol: str
    status: str
    level: str

    entry: Optional[float] = None
    stop_loss: Optional[float] = None

    tp1: Optional[float] = None
    tp2: Optional[float] = None

    rr_tp1: Optional[float] = None
    rr_tp2: Optional[float] = None

    confidence: float = 0.0

    rsi: Optional[float] = None

    volume_trend: str = "UNKNOWN"
    volume_ratio: Optional[float] = None

    distance_to_resistance_pct: Optional[float] = None

    required_conditions: Optional[List[str]] = None
    missing_conditions: Optional[List[str]] = None
    invalid_reasons: Optional[List[str]] = None

    downside_target: Optional[float] = None
    dynamic_stop: Optional[float] = None

    def __post_init__(self):

        self.required_conditions = (
            self.required_conditions or []
        )

        self.missing_conditions = (
            self.missing_conditions or []
        )

        self.invalid_reasons = (
            self.invalid_reasons or []
        )


# ============================================================
# NUMBER PARSER
# ============================================================

def _number(value):

    if value is None:
        return None

    text = str(value)

    match = re.search(
        r"-?[0-9][0-9,٬]*(?:\.[0-9]+)?",
        text,
    )

    if not match:
        return None

    try:
        return float(
            match.group()
            .replace(",", "")
            .replace("٬", "")
        )
    except ValueError:
        return None


# ============================================================
# TGJU FETCHER
# ============================================================

def _tgju(url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers=headers,
    )

    response.raise_for_status()

    text = response.text

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    candidates = []

    patterns = (
        r"(?:قیمت|ارزش|آخرین)"
        r"[^0-9]{0,80}"
        r"([0-9,٬]{4,})",

        r"(?:USD|USDT)"
        r"[^0-9]{0,80}"
        r"([0-9,٬]{4,})",
    )

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE,
        ):

            number = _number(
                match.group(1)
            )

            if number is not None and number > 1000:
                candidates.append(number)

    if not candidates:
        raise RuntimeError(
            f"TGJU rate unavailable: {url}"
        )

    return candidates[0]


# ============================================================
# TGJU RATES
# ============================================================

def fetch_tgju_rates():

    usd = _tgju(
        TGJU_USD_URL
    )

    usdt = _tgju(
        TGJU_USDT_URL
    )

    return {
        "usd_toman": usd,
        "usdt_toman": usdt,
        "source": "tgju.org",
        "timestamp": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "quality": 1.0,
    }


# ============================================================
# R/R
# ============================================================

def calculate_rr(
    entry,
    stop_loss,
    tp1,
    tp2,
):

    risk = abs(
        entry - stop_loss
    )

    if risk <= 0:
        raise ValueError(
            "Invalid R/R geometry"
        )

    rr_tp1 = (
        (tp1 - entry)
        / risk
    )

    rr_tp2 = (
        (tp2 - entry)
        / risk
    )

    return (
        rr_tp1,
        rr_tp2,
    )


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def _level(
    data,
    key,
    price,
    direction,
):

    values = [
        data.get(key)
    ]

    values += list(
        data.get(
            key + "s",
            []
        )
        or []
    )

    parsed = []

    for value in values:

        try:
            parsed.append(
                float(value)
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

    if direction == "below":

        parsed = [
            value
            for value in parsed
            if value < price
        ]

        if parsed:
            return max(parsed)

    else:

        parsed = [
            value
            for value in parsed
            if value > price
        ]

        if parsed:
            return min(parsed)

    return None


# ============================================================
# STATUS
# ============================================================

def classify_status(data):

    trend = str(
        data.get(
            "trend",
            "neutral",
        )
    ).lower()

    if trend in (
        "strong_bullish",
        "strong bull",
    ):
        return "STRONG BULL"

    if trend in (
        "bullish",
        "bull",
    ):
        return "BULL"

    if trend in (
        "strong_bearish",
        "strong bear",
    ):
        return "STRONG BEAR"

    if trend in (
        "bearish",
        "bear",
    ):
        return "BEAR"

    return "NEUTRAL"


# ============================================================
# CONFIDENCE
# ============================================================

def confidence_score(data):

    score = 50

    status = classify_status(
        data
    )

    score += {
        "STRONG BULL": 20,
        "BULL": 10,
        "NEUTRAL": 0,
        "BEAR": -10,
        "STRONG BEAR": -20,
    }.get(
        status,
        0,
    )

    rsi = data.get("rsi")
    volume_ratio = data.get(
        "volume_ratio"
    )

    if rsi is not None:

        try:
            rsi = float(rsi)

            if 45 <= rsi < 68:
                score += 10

            elif rsi >= 70:
                score -= 15

            else:
                score -= 5

        except (
            TypeError,
            ValueError,
        ):
            pass

    if volume_ratio is not None:

        try:
            volume_ratio = float(
                volume_ratio
            )

            if volume_ratio >= 1.2:
                score += 10

            elif volume_ratio < 1:
                score -= 5

        except (
            TypeError,
            ValueError,
        ):
            pass

    if data.get(
        "ma_alignment"
    ) is True:

        score += 10

    quality = data.get(
        "data_quality"
    )

    if quality is not None:

        try:
            score += (
                float(quality)
                - 0.5
            ) * 20

        except (
            TypeError,
            ValueError,
        ):
            pass

    return max(
        0,
        min(
            100,
            round(
                score,
                1,
            ),
        ),
    )


# ============================================================
# ANALYTICAL ENGINE
# ============================================================

class ReliableAnalyticalEngine:

    def analyze_coin(
        self,
        symbol,
        data,
    ):

        try:

            price = float(
                data.get(
                    "current_price"
                )
                or 0
            )

        except (
            TypeError,
            ValueError,
        ):

            price = 0

        status = classify_status(
            data
        )

        confidence = confidence_score(
            data
        )

        support = _level(
            data,
            "support",
            price,
            "below",
        )

        resistance = _level(
            data,
            "resistance",
            price,
            "above",
        )

        if (
            not price
            or support is None
            or resistance is None
        ):

            return SetupResult(
                symbol=symbol,
                status=status,
                level="NO VALID SETUP",
                confidence=confidence,
                invalid_reasons=[
                    (
                        "incomplete "
                        "price/support/"
                        "resistance data"
                    )
                ],
            )

        try:

            stop_loss = float(
                data.get(
                    "stop_loss"
                )
                or support
            )

        except (
            TypeError,
            ValueError,
        ):

            stop_loss = support

        try:

            tp1 = float(
                data.get(
                    "tp1"
                )
                or resistance
            )

        except (
            TypeError,
            ValueError,
        ):

            tp1 = resistance

        try:

            tp2 = float(
                data.get(
                    "tp2"
                )
                or (
                    resistance
                    + 0.30
                    * (
                        resistance
                        - price
                    )
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            tp2 = (
                resistance
                + 0.30
                * (
                    resistance
                    - price
                )
            )

        try:

            rr_tp1, rr_tp2 = calculate_rr(
                price,
                stop_loss,
                tp1,
                tp2,
            )

        except ValueError:

            return SetupResult(
                symbol=symbol,
                status=status,
                level="NO VALID SETUP",
                entry=price,
                stop_loss=stop_loss,
                tp1=tp1,
                tp2=tp2,
                confidence=confidence,
                invalid_reasons=[
                    "invalid R/R geometry"
                ],
            )

        rsi = data.get(
            "rsi"
        )

        volume_ratio = data.get(
            "volume_ratio"
        )

        try:

            if rsi is not None:
                rsi = float(rsi)

        except (
            TypeError,
            ValueError,
        ):

            rsi = None

        try:

            if volume_ratio is not None:
                volume_ratio = float(
                    volume_ratio
                )

        except (
            TypeError,
            ValueError,
        ):

            volume_ratio = None

        conditions = {

            "rr": (
                rr_tp1 >= 1
                or rr_tp2 >= 1.5
            ),

            "trend": (
                status
                in (
                    "STRONG BULL",
                    "BULL",
                )
            ),

            "rsi": (
                rsi is None
                or rsi < 70
            ),

            "volume": (
                volume_ratio is None
                or volume_ratio >= 1.2
            ),

            "support_confirmation": (
                int(
                    data.get(
                        "support_confirmations",
                        0,
                    )
                    or 0
                )
                >= 2
            ),

            "breakout_confirmation": bool(
                data.get(
                    "confirmed_breakout",
                    False,
                )
            ),
        }

        labels = {

            "rr":
                "R/R threshold",

            "trend":
                "bullish trend",

            "rsi":
                "RSI below 70",

            "volume":
                (
                    "volume >= 120% "
                    "of 20-period average"
                ),

            "support_confirmation":
                (
                    "at least 2 "
                    "support confirmations"
                ),

            "breakout_confirmation":
                (
                    "2 consecutive H4 "
                    "closes above resistance"
                ),
        }

        missing_conditions = [
            labels[key]
            for key, valid
            in conditions.items()
            if not valid
        ]

        if all(
            conditions.values()
        ):

            level = "EXECUTABLE"

        elif (
            conditions["rr"]
            and status in (
                "STRONG BULL",
                "BULL",
                "NEUTRAL",
            )
        ):

            level = "BEST WATCH"

        else:

            level = "NO VALID SETUP"

        downside_target = data.get(
            "downside_target"
        )

        if downside_target is None:

            downside_target = (
                support
                - 0.5
                * (
                    price
                    - support
                )
            )

        dynamic_stop = data.get(
            "dynamic_stop"
        )

        if dynamic_stop is None:

            dynamic_stop = (
                support
                * 0.995
            )

        return SetupResult(

            symbol=symbol,

            status=status,

            level=level,

            entry=price,

            stop_loss=stop_loss,

            tp1=tp1,

            tp2=tp2,

            rr_tp1=rr_tp1,

            rr_tp2=rr_tp2,

            confidence=confidence,

            rsi=rsi,

            volume_trend=str(
                data.get(
                    "volume_trend",
                    "UNKNOWN",
                )
            ),

            volume_ratio=volume_ratio,

            distance_to_resistance_pct=(
                (
                    resistance
                    - price
                )
                / price
                * 100
            ),

            required_conditions=(
                [
                    (
                        "2 consecutive H4 "
                        "closes above resistance"
                    ),
                    (
                        "volume >= 120% "
                        "of 20-period average"
                    ),
                ]
                if level == "BEST WATCH"
                else []
            ),

            missing_conditions=(
                missing_conditions
            ),

            invalid_reasons=[],

            downside_target=(
                float(
                    downside_target
                )
            ),

            dynamic_stop=(
                float(
                    dynamic_stop
                )
            ),
        )


# ============================================================
# ASSET BLOCK
# ============================================================

def asset_block(
    symbol,
    data,
):

    result = (
        ReliableAnalyticalEngine()
        .analyze_coin(
            symbol,
            data,
        )
    )

    if result.entry is None:

        return (
            f"🔹 {symbol} | "
            f"{result.status} | "
            f"NO VALID SETUP"
        )

    rsi_text = (
        f"{result.rsi:.2f}"
        if result.rsi is not None
        else "N/A"
    )

    distance_text = (
        f"{result.distance_to_resistance_pct:.2f}%"
        if result.distance_to_resistance_pct is not None
        else "N/A"
    )

    rr_tp1_text = (
        f"1:{result.rr_tp1:.2f}"
        if result.rr_tp1 is not None
        else "N/A"
    )

    rr_tp2_text = (
        f"1:{result.rr_tp2:.2f}"
        if result.rr_tp2 is not None
        else "N/A"
    )

    support = data.get(
        "support",
        0,
    )

    resistance = data.get(
        "resistance",
        0,
    )

    try:
        support = float(support)
    except (
        TypeError,
        ValueError,
    ):
        support = 0

    try:
        resistance = float(
            resistance
        )
    except (
        TypeError,
        ValueError,
    ):
        resistance = 0

    return (
        f"🔹 {symbol} | "
        f"{result.status} | "
        f"{result.level} | "
        f"Confidence "
        f"{result.confidence:.0f}%\n"

        f"   Price "
        f"${result.entry:,.6f} | "

        f"Support "
        f"${support:,.6f} | "

        f"Resistance "
        f"${resistance:,.6f}\n"

        f"   RSI {rsi_text} | "
        f"Volume "
        f"{result.volume_trend} | "
        f"Distance "
        f"{distance_text}\n"

        f"   R/R TP1 "
        f"{rr_tp1_text} | "
        f"TP2 "
        f"{rr_tp2_text}"
    )


# ============================================================
# PERSONAL REPORT
# ============================================================

def personal_report(
    portfolio,
    rates=None,
):

    engine = (
        ReliableAnalyticalEngine()
    )

    results = [
        engine.analyze_coin(
            symbol,
            data,
        )
        for symbol, data
        in portfolio.items()
    ]

    executable = [
        result
        for result in results
        if result.level
        == "EXECUTABLE"
    ]

    best = None

    if executable:

        best = max(
            executable,
            key=lambda x: (
                x.confidence,
                x.rr_tp2 or 0,
            ),
        )

    if best:

        best_text = (
            f"{best.symbol} — "
            f"EXECUTABLE — "
            f"R/R TP1 "
            f"1:{best.rr_tp1:.2f} | "
            f"TP2 "
            f"1:{best.rr_tp2:.2f}"
        )

    else:

        best_text = (
            "هیچ ستاپ اجرایی "
            "معتبر تأیید نشد."
        )

    lines = [

        "🤖 ATLAS AI — "
        "PERSONAL PORTFOLIO 4H",

        "━━━━━━━━━━━━━━━━━━",

        "🔥 BEST PERSONAL SETUP: "
        + best_text,

        "",

        "💼 PERSONAL PORTFOLIO",

        "───────────────────",
    ]

    lines.extend(
        asset_block(
            result.symbol,
            portfolio[
                result.symbol
            ],
        )
        for result in results
    )

    return "\n".join(
        lines
    )


# ============================================================
# CSV
# ============================================================

def generate_csv_report(
    results,
    filename,
):

    fieldnames = (
        list(
            asdict(
                results[0]
            ).keys()
        )
        if results
        else [
            "symbol",
            "level",
        ]
    )

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for result in results:

            row = asdict(
                result
            )

            for key in (
                "required_conditions",
                "missing_conditions",
                "invalid_reasons",
            ):

                row[key] = json.dumps(
                    row[key],
                    ensure_ascii=False,
                )

            writer.writerow(
                row
            )

    return filename


# ============================================================
# FULL REPORT
# ============================================================

def build_report(
    market,
    portfolio,
    metals=None,
):

    rates = fetch_tgju_rates()

    engine = (
        ReliableAnalyticalEngine()
    )

    market_results = [
        engine.analyze_coin(
            symbol,
            data,
        )
        for symbol, data
        in market.items()
    ]

    executable = [
        result
        for result in market_results
        if result.level
        == "EXECUTABLE"
    ]

    best = None

    if executable:

        best = max(
            executable,
            key=lambda x: (
                x.confidence,
                x.rr_tp2 or 0,
            ),
        )

    if best:

        best_text = (
            f"{best.symbol} — "
            f"EXECUTABLE — "
            f"R/R TP1 "
            f"1:{best.rr_tp1:.2f} | "
            f"TP2 "
            f"1:{best.rr_tp2:.2f} | "
            f"Confidence "
            f"{best.confidence:.0f}%"
        )

    else:

        best_text = (
            "هیچ ستاپ اجرایی "
            "معتبر تأیید نشد."
        )

    lines = [

        "🤖 ATLAS AI — MARKET 4H",

        "━━━━━━━━━━━━━━━━━━",

        (
            f"💵 دلار: "
            f"{rates['usd_toman']:,.0f} تومان"
            f" | "
            f"تتر: "
            f"{rates['usdt_toman']:,.0f} تومان"
        ),

        (
            f"📡 Source: "
            f"{rates['source']} | "
            f"Updated: "
            f"{rates['timestamp']}"
        ),

        "",

        "🔥 BEST SETUP: "
        + best_text,

        "",

        "📡 MARKET",

        "───────────────────",
    ]

    lines.extend(
        asset_block(
            result.symbol,
            market[
                result.symbol
            ],
        )
        for result in market_results
    )

    if metals:

        lines.extend(
            [
                "",
                "🪙 ATLAS METALS",
                "───────────────────",
            ]
        )

        lines.extend(
            asset_block(
                symbol,
                data,
            )
            for symbol, data
            in metals.items()
        )

    lines.extend(
        [
            "",
            personal_report(
                portfolio,
                rates,
            ),

            "",

            "📐 V12 RULES",

            "───────────────────",

            (
                "• وضعیت‌ها: "
                "STRONG BULL / BULL / "
                "NEUTRAL / BEAR / "
                "STRONG BEAR"
            ),

            (
                "• تثبیت شکست = "
                "حداقل ۲ کلوز متوالی "
                "H4 بالای مقاومت"
            ),

            (
                "• تأیید حجم = "
                "حداقل ۲۰٪ بالاتر "
                "از میانگین ۲۰ دوره"
            ),

            (
                "• RSI >= 70 برای "
                "لانگ EXECUTABLE مانع است"
            ),

            (
                "• R/R برای TP1 و TP2 "
                "جداگانه محاسبه می‌شود"
            ),

            (
                "• Confidence هرگز "
                "جای R/R را نمی‌گیرد"
            ),

            (
                "• BEST WATCH معامله نیست؛ "
                "فقط وضعیت تحت نظر است"
            ),

            (
                "• داده ناکافی = "
                "NO VALID SETUP"
            ),

            (
                "• هیچ سیگنال اجباری وجود ندارد"
            ),

            (
                "• دلار و تتر فقط "
                "از TGJU دریافت می‌شوند"
            ),
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================
# ACTION EMOJI
# ============================================================

def action_emoji(
    status,
):

    return {
        "STRONG BULL": "🟢",
        "BULL": "🟢",
        "NEUTRAL": "🟡",
        "BEAR": "🔴",
        "STRONG BEAR": "🔴",
    }.get(
        status,
        "⚪",
    )


# ============================================================
# TELEGRAM SPLITTER
# ============================================================

def split_telegram(
    text,
    limit=4000,
):

    if not text:
        return []

    return [
        text[index:index + limit]
        for index in range(
            0,
            len(text),
            limit,
        )
    ]


# ============================================================
# SAMPLE / RUNTIME DATA
# ============================================================

def get_runtime_market():

    return {

        "BTC": {

            "current_price": 65000,
            "support": 64000,
            "resistance": 66000,

            "trend": "bullish",

            "rsi": 55,

            "volume_ratio": 1.3,

            "support_confirmations": 2,

            "confirmed_breakout": True,

            "volume_trend": "HIGH",

            "data_quality": 0.9,
        },

        "ETH": {

            "current_price": 3200,
            "support": 3100,
            "resistance": 3300,

            "trend": "neutral",

            "rsi": 60,

            "volume_ratio": 0.9,

            "support_confirmations": 1,

            "confirmed_breakout": False,

            "volume_trend": "LOW",

            "data_quality": 0.8,
        },
    }


def get_runtime_portfolio():

    return {

        "BTC": {

            "current_price": 65000,
            "support": 64000,
            "resistance": 66000,

            "trend": "bullish",

            "rsi": 55,

            "volume_ratio": 1.3,

            "support_confirmations": 2,

            "confirmed_breakout": True,

            "volume_trend": "HIGH",

            "data_quality": 0.9,
        },

        "ETH": {

            "current_price": 3200,
            "support": 3100,
            "resistance": 3300,

            "trend": "neutral",

            "rsi": 60,

            "volume_ratio": 0.9,

            "support_confirmations": 1,

            "confirmed_breakout": False,

            "volume_trend": "LOW",

            "data_quality": 0.8,
        },
    }


# ============================================================
# TELEGRAM DELIVERY
# ============================================================

def deliver_report(
    report_text,
):

    if not report_text:
        raise RuntimeError(
            "Generated report is empty."
        )

    print(
        "Sending ATLAS v12 report "
        "to Telegram..."
    )

    result = send_report(
        report_text
    )

    if not isinstance(
        result,
        tuple,
    ):

        raise RuntimeError(
            "telegram_delivery_v12.send_report "
            "returned an invalid result."
        )

    if len(result) != 3:

        raise RuntimeError(
            "Unexpected Telegram delivery "
            "result format."
        )

    parts_count, sent_count, errors = result

    errors = errors or []

    print(
        f"Telegram parts: "
        f"{parts_count}"
    )

    print(
        f"Telegram sent: "
        f"{sent_count}"
    )

    if errors:

        print(
            "Telegram delivery errors:"
        )

        for error in errors:

            print(
                f"  - {error}"
            )

    if sent_count == 0:

        raise RuntimeError(
            "Telegram delivery failed: "
            "zero messages were sent."
        )

    return (
        parts_count,
        sent_count,
        errors,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=================================================="
    )

    print(
        "ATLAS AI v12 starting..."
    )

    print(
        "=================================================="
    )

    market = (
        get_runtime_market()
    )

    portfolio = (
        get_runtime_portfolio()
    )

    try:

        print(
            "Fetching TGJU USD/USDT..."
        )

        rates = (
            fetch_tgju_rates()
        )

        print(
            "TGJU USD:",
            rates[
                "usd_toman"
            ],
        )

        print(
            "TGJU USDT:",
            rates[
                "usdt_toman"
            ],
        )

        print(
            "Building report..."
        )

        report_text = build_report(
            market=market,
            portfolio=portfolio,
            metals=None,
        )

        if not report_text:

            raise RuntimeError(
                "Report generation "
                "returned empty text."
            )

        print(
            "Report built successfully."
        )

        print(
            "Report length:",
            len(report_text),
        )

        parts_count, sent_count, errors = (
            deliver_report(
                report_text
            )
        )

        print(
            "=================================================="
        )

        print(
            "ATLAS AI v12 completed."
        )

        print(
            f"Telegram delivery: "
            f"{sent_count} messages "
            f"in {parts_count} parts."
        )

        if errors:

            print(
                "Completed with Telegram "
                "warnings."
            )

        print(
            "=================================================="
        )

        return 0

    except Exception as error:

        print(
            "=================================================="
        )

        print(
            "ATLAS AI v12 ERROR"
        )

        print(
            str(error)
        )

        print(
            "=================================================="
        )

        traceback.print_exc()

        return 1


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )
