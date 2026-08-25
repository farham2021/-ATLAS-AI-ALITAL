#!/usr/bin/env python3
"""ATLAS AI v12 - Reliable Analytical Engine. No forced signals."""
from __future__ import annotations

import csv
import json
import re
import time

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests

# ============================================================
# TELEGRAM DELIVERY
# ============================================================

from telegram_delivery_v12 import (
    send_report,
    send_csv as send_csv_report,
)

# ============================================================
# FX SOURCES
#
# PRIMARY:
#   TGJU
#
# IMPORTANT:
#   USD / USDT are NEVER silently relabeled as TGJU when
#   a fallback source is used.
#
#   If TGJU is unavailable and no verified fallback exists,
#   the value becomes N/A instead of inventing a price.
# ============================================================

TGJU_USD_URLS = [
    "https://www.tgju.org/profile/price_dollar_rl",
    "https://www.tgju.org/profile/price_dollar_rl?output=1",
]

TGJU_USDT_URLS = [
    "https://www.tgju.org/profile/price_usdt",
    "https://www.tgju.org/profile/price_dollar_usdt",
]

# Optional public fallback.
#
# This source is used ONLY after TGJU fails.
# USD from this endpoint is converted from IRR to Toman.
#
# USDT deliberately has no unverified fallback.
# Therefore USDT becomes N/A if TGJU is unavailable.
FALLBACK_USD_URLS = [
    "https://open.er-api.com/v6/latest/USD",
]

FALLBACK_USDT_URLS = []


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

    required_conditions: List[str] = None
    missing_conditions: List[str] = None
    invalid_reasons: List[str] = None

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

def _number(x):
    if x is None:
        return None

    text = str(x)

    m = re.search(
        r"-?[0-9][0-9,٬]*(?:\.[0-9]+)?",
        text,
    )

    if not m:
        return None

    try:
        return float(
            m.group()
            .replace(",", "")
            .replace("٬", "")
        )
    except (TypeError, ValueError):
        return None


# ============================================================
# HTTP GET
# ============================================================

def _http_get(url, attempts=3):
    """
    Robust HTTP request.

    Handles:
        403
        429
        5xx
        timeout
        connection errors

    Returns:
        requests.Response

    Raises:
        RuntimeError
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/json;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    last_error = None

    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                timeout=20,
                headers=headers,
                allow_redirects=True,
            )

            status = response.status_code

            if status == 403:
                last_error = RuntimeError(
                    f"HTTP 403 Forbidden: {url}"
                )

            elif status == 429:
                last_error = RuntimeError(
                    f"HTTP 429 Too Many Requests: {url}"
                )

            elif 500 <= status < 600:
                last_error = RuntimeError(
                    f"HTTP {status} Server Error: {url}"
                )

            else:
                response.raise_for_status()
                return response

        except requests.RequestException as exc:
            last_error = exc

        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))

    raise last_error or RuntimeError(
        f"HTTP request failed: {url}"
    )


# ============================================================
# TGJU HTML PARSER
# ============================================================

def _parse_tgju_rate(text, kind):
    """
    Extract a rate from TGJU page content.

    TGJU profile values are normally Rial.
    Returned value is converted to Toman.
    """

    clean = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    clean = re.sub(
        r"\s+",
        " ",
        clean,
    )

    if kind == "usd":
        patterns = [
            r"(?:قیمت|ارزش|آخرین)[^0-9]{0,100}"
            r"([0-9,٬]{4,})",

            r"(?:دلار|USD)[^0-9]{0,100}"
            r"([0-9,٬]{4,})",
        ]

    else:
        patterns = [
            r"(?:قیمت|ارزش|آخرین)[^0-9]{0,100}"
            r"([0-9,٬]{4,})",

            r"(?:تتر|USDT)[^0-9]{0,100}"
            r"([0-9,٬]{4,})",
        ]

    candidates = []

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            clean,
            re.IGNORECASE,
        ):

            value = _number(
                match.group(1)
            )

            if value is not None and value > 1000:
                candidates.append(value)

    if not candidates:
        raise RuntimeError(
            f"TGJU {kind} rate could not be parsed."
        )

    # TGJU price is normally Rial.
    # ATLAS reports Toman.
    return candidates[0] / 10.0


# ============================================================
# TGJU FETCH
# ============================================================

def _fetch_tgju(url, kind):
    response = _http_get(url)

    return _parse_tgju_rate(
        response.text,
        kind,
    )


# ============================================================
# FALLBACK USD
# ============================================================

def _fetch_fallback_usd(url):
    """
    Public fallback for USD.

    open.er-api.com:
        USD -> IRR

    IRR is converted to Toman.
    """

    response = _http_get(url)

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Fallback USD source returned invalid JSON."
        ) from exc

    if payload.get("result") != "success":
        raise RuntimeError(
            "Fallback USD source did not return success."
        )

    rates = payload.get("rates") or {}

    irr_rate = rates.get("IRR")

    if irr_rate is None:
        raise RuntimeError(
            "Fallback USD source has no IRR rate."
        )

    irr_rate = float(irr_rate)

    if irr_rate <= 0:
        raise RuntimeError(
            "Invalid fallback USD rate."
        )

    return irr_rate / 10.0


# ============================================================
# GENERIC SOURCE TRY
# ============================================================

def _try_sources(
    urls,
    parser,
    source_name,
):
    errors = []

    for url in urls:

        try:
            value = parser(url)

            if value is not None and value > 0:

                return (
                    value,
                    source_name,
                    errors,
                )

        except Exception as exc:

            errors.append(
                f"{source_name}: {exc}"
            )

    return (
        None,
        None,
        errors,
    )


# ============================================================
# FX ENGINE
# ============================================================

def fetch_tgju_rates():
    """
    Obtain USD and USDT rates.

    Priority:

        TGJU USD
        ↓
        fallback USD

        TGJU USDT
        ↓
        N/A

    No fabricated substitution is allowed.
    """

    errors = []

    # --------------------------------------------------------
    # USD — TGJU FIRST
    # --------------------------------------------------------

    usd, usd_source, usd_errors = _try_sources(
        TGJU_USD_URLS,
        lambda url: _fetch_tgju_rate(
            url,
            "usd",
        ),
        "TGJU",
    )

    errors.extend(usd_errors)

    # --------------------------------------------------------
    # USD — FALLBACK
    # --------------------------------------------------------

    if usd is None:

        usd, usd_source, fallback_errors = _try_sources(
            FALLBACK_USD_URLS,
            _fetch_fallback_usd,
            "FALLBACK",
        )

        errors.extend(
            fallback_errors
        )

    # --------------------------------------------------------
    # USDT — TGJU ONLY
    # --------------------------------------------------------

    usdt, usdt_source, usdt_errors = _try_sources(
        TGJU_USDT_URLS,
        lambda url: _fetch_tgju_rate(
            url,
            "usdt",
        ),
        "TGJU",
    )

    errors.extend(usdt_errors)

    # --------------------------------------------------------
    # USDT FALLBACK
    # --------------------------------------------------------

    if usdt is None and FALLBACK_USDT_URLS:

        usdt, usdt_source, fallback_errors = _try_sources(
            FALLBACK_USDT_URLS,
            _fetch_fallback_usd,
            "FALLBACK",
        )

        errors.extend(
            fallback_errors
        )

    # --------------------------------------------------------
    # SOURCE LABEL
    # --------------------------------------------------------

    source_parts = []

    if usd_source:
        source_parts.append(
            f"USD={usd_source}"
        )
    else:
        source_parts.append(
            "USD=UNAVAILABLE"
        )

    if usdt_source:
        source_parts.append(
            f"USDT={usdt_source}"
        )
    else:
        source_parts.append(
            "USDT=UNAVAILABLE"
        )

    quality = 1.0

    if usd is None:
        quality -= 0.25

    if usdt is None:
        quality -= 0.25

    return {
        "usd_toman": usd,
        "usdt_toman": usdt,
        "source": " | ".join(source_parts),
        "timestamp": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "quality": max(
            0.0,
            quality,
        ),
        "errors": errors,
    }


# ============================================================
# INTERNAL ALIAS
# ============================================================

def _fetch_tgju_rate(url, kind):
    return _fetch_tgju(
        url,
        kind,
    )


# ============================================================
# R/R
# ============================================================

def calculate_rr(
    entry,
    sl,
    tp1,
    tp2,
):
    risk = abs(
        entry - sl
    )

    if risk <= 0:
        raise ValueError(
            "Invalid R/R geometry"
        )

    rr_tp1 = (
        tp1 - entry
    ) / risk

    rr_tp2 = (
        tp2 - entry
    ) / risk

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
    vals = [
        data.get(key)
    ]

    vals += list(
        data.get(
            key + "s",
            [],
        )
        or []
    )

    vals = [
        float(v)
        for v in vals
        if v is not None
    ]

    if direction == "below":
        vals = [
            v for v in vals
            if v < price
        ]
    else:
        vals = [
            v for v in vals
            if v > price
        ]

    if direction == "below":
        return (
            max(vals)
            if vals
            else None
        )

    return (
        min(vals)
        if vals
        else None
    )


# ============================================================
# STATUS
# ============================================================

def classify_status(d):

    trend = str(
        d.get(
            "trend",
            "neutral",
        )
    ).lower()

    if trend in (
        "strong_bullish",
        "strong bull",
        "strong bullish",
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
        "strong bearish",
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

def confidence_score(d):

    score = 50

    status = classify_status(d)

    score += {
        "STRONG BULL": 20,
        "BULL": 10,
        "NEUTRAL": 0,
        "BEAR": -10,
        "STRONG BEAR": -20,
    }[status]

    rsi = d.get("rsi")
    volume_ratio = d.get(
        "volume_ratio"
    )

    if rsi is not None:

        score += (
            10
            if 45 <= rsi < 68
            else -15
            if rsi >= 70
            else -5
        )

    if volume_ratio is not None:

        score += (
            10
            if volume_ratio >= 1.2
            else -5
            if volume_ratio < 1
            else 0
        )

    if d.get(
        "ma_alignment"
    ) is True:
        score += 10

    if d.get(
        "data_quality"
    ) is not None:

        score += (
            float(
                d["data_quality"]
            )
            - 0.5
        ) * 20

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
        d,
    ):

        price = float(
            d.get(
                "current_price"
            )
            or 0
        )

        status = classify_status(d)

        confidence = confidence_score(d)

        support = _level(
            d,
            "support",
            price,
            "below",
        )

        resistance = _level(
            d,
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
                symbol,
                status,
                "NO VALID SETUP",
                confidence=confidence,
                invalid_reasons=[
                    "incomplete price/support/resistance data"
                ],
            )

        stop_loss = float(
            d.get(
                "stop_loss"
            )
            or support
        )

        tp1 = float(
            d.get(
                "tp1"
            )
            or resistance
        )

        tp2 = float(
            d.get(
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

        rr_tp1, rr_tp2 = calculate_rr(
            price,
            stop_loss,
            tp1,
            tp2,
        )

        rsi = d.get("rsi")
        volume_ratio = d.get(
            "volume_ratio"
        )

        conditions = {

            "rr": (
                rr_tp1 >= 1
                or rr_tp2 >= 1.5
            ),

            "trend": status in (
                "STRONG BULL",
                "BULL",
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
                    d.get(
                        "support_confirmations",
                        0,
                    )
                )
                >= 2
            ),

            "breakout_confirmation": bool(
                d.get(
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
                "volume >= 120% of 20-period average",

            "support_confirmation":
                "at least 2 support confirmations",

            "breakout_confirmation":
                "2 consecutive H4 closes above resistance",
        }

        missing = [
            labels[key]
            for key, value
            in conditions.items()
            if not value
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

        return SetupResult(

            symbol,
            status,
            level,

            price,
            stop_loss,
            tp1,
            tp2,

            rr_tp1,
            rr_tp2,

            confidence,

            rsi,

            str(
                d.get(
                    "volume_trend",
                    "UNKNOWN",
                )
            ),

            volume_ratio,

            (
                resistance - price
            )
            / price
            * 100,

            (
                [
                    "2 consecutive H4 closes above resistance",
                    "volume >= 120% of 20-period average",
                ]
                if level == "BEST WATCH"
                else []
            ),

            missing,

            [],

            float(
                d.get(
                    "downside_target"
                )
                or (
                    support
                    - 0.5
                    * (
                        price
                        - support
                    )
                )
            ),

            float(
                d.get(
                    "dynamic_stop"
                )
                or support * 0.995
            ),
        )


# ============================================================
# ASSET BLOCK
# ============================================================

def asset_block(
    symbol,
    d,
):

    result = ReliableAnalyticalEngine().analyze_coin(
        symbol,
        d,
    )

    if result.entry is None:

        return (
            f"🔹 {symbol} | "
            f"{result.status} | "
            f"NO VALID SETUP"
        )

    return (
        f"🔹 {symbol} | "
        f"{result.status} | "
        f"{result.level} | "
        f"Confidence "
        f"{result.confidence:.0f}%\n"

        f"   Price "
        f"${result.entry:,.6f} | "
        f"Support "
        f"${d.get('support', 0):,.6f} | "
        f"Resistance "
        f"${d.get('resistance', 0):,.6f}\n"

        f"   RSI "
        f"{result.rsi "
        f"if result.rsi is not None else 'N/A'} | "

        f"Volume "
        f"{result.volume_trend} | "

        f"Distance "
        f"{result.distance_to_resistance_pct:.2f}%\n"

        f"   R/R TP1 "
        f"1:{result.rr_tp1:.2f} | "

        f"TP2 "
        f"1:{result.rr_tp2:.2f}"
    )


# ============================================================
# PERSONAL REPORT
# ============================================================

def personal_report(
    portfolio,
    rates=None,
):

    engine = ReliableAnalyticalEngine()

    results = [
        engine.analyze_coin(
            symbol,
            data,
        )
        for symbol, data
        in portfolio.items()
    ]

    best = next(
        (
            result
            for result in results
            if result.level == "EXECUTABLE"
        ),
        None,
    )

    out = [

        "🤖 ATLAS AI — PERSONAL PORTFOLIO 4H",

        "━━━━━━━━━━━━━━━━━━",

        (
            "🔥 BEST PERSONAL SETUP: "
            f"{best.symbol} — EXECUTABLE — "
            f"R/R TP1 1:{best.rr_tp1:.2f} | "
            f"TP2 1:{best.rr_tp2:.2f}"
            if best
            else
            "🔥 BEST PERSONAL SETUP: "
            "هیچ ستاپ اجرایی معتبر تأیید نشد."
        ),

        "",

        "💼 PERSONAL PORTFOLIO",

        "───────────────────",
    ]

    out += [
        asset_block(
            result.symbol,
            portfolio[result.symbol],
        )
        for result in results
    ]

    return "\n".join(out)


# ============================================================
# CSV
# ============================================================

def generate_csv_report(
    results,
    filename,
):

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        fields = (
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

        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )

        writer.writeheader()

        for result in results:

            row = asdict(result)

            for key in (
                "required_conditions",
                "missing_conditions",
                "invalid_reasons",
            ):

                row[key] = json.dumps(
                    row[key],
                    ensure_ascii=False,
                )

            writer.writerow(row)

    return filename


# ============================================================
# REPORT BUILDER
# ============================================================

def build_report(
    market,
    portfolio,
    metals=None,
):

    rates = fetch_tgju_rates()

    engine = ReliableAnalyticalEngine()

    market_results = [
        engine.analyze_coin(
            symbol,
            data,
        )
        for symbol, data
        in market.items()
    ]

    best = next(
        (
            result
            for result in market_results
            if result.level == "EXECUTABLE"
        ),
        None,
    )

    lines = [

        "🤖 ATLAS AI — MARKET 4H",

        "━━━━━━━━━━━━━━━━━━",

        (
            f"💵 دلار: "
            f"{rates['usd_toman']:,.0f} تومان"
            if rates["usd_toman"] is not None
            else
            "💵 دلار: N/A"
        ),

        (
            f"💵 تتر: "
            f"{rates['usdt_toman']:,.0f} تومان"
            if rates["usdt_toman"] is not None
            else
            "💵 تتر: N/A"
        ),

        (
            f"📡 FX Source: "
            f"{rates['source']}"
        ),

        (
            f"⏰ Updated: "
            f"{rates['timestamp']}"
        ),
    ]

    # Report source errors without stopping the report.
    if rates.get("errors"):

        lines.append(
            "⚠️ FX source notes: "
            + "; ".join(
                rates["errors"][-3:]
            )
        )

    lines += [

        "",

        (
            "🔥 BEST SETUP: "
            f"{best.symbol} — EXECUTABLE — "
            f"R/R TP1 1:{best.rr_tp1:.2f} | "
            f"TP2 1:{best.rr_tp2:.2f}"
            if best
            else
            "🔥 BEST SETUP: "
            "هیچ ستاپ اجرایی معتبر تأیید نشد."
        ),

        "",

        "📡 MARKET",

        "───────────────────",
    ]

    lines += [
        asset_block(
            result.symbol,
            market[result.symbol],
        )
        for result in market_results
    ]

    if metals:

        lines += [

            "",

            "🪙 ATLAS METALS",

            "───────────────────",
        ]

        lines += [
            asset_block(
                symbol,
                data,
            )
            for symbol, data
            in metals.items()
        ]

    lines += [

        "",

        personal_report(
            portfolio,
            rates,
        ),

        "",

        "📐 V12 RULES",

        "───────────────────",

        "• وضعیت‌ها: STRONG BULL / BULL / NEUTRAL / BEAR / STRONG BEAR",

        "• تثبیت شکست = حداقل ۲ کلوز متوالی H4 بالای مقاومت",

        "• تأیید حجم = حداقل ۲۰٪ بالاتر از میانگین ۲۰ دوره",

        "• RSI >= 70 برای لانگ EXECUTABLE مانع است",

        "• R/R برای TP1 و TP2 جداگانه محاسبه می‌شود",

        "• Confidence هرگز جای R/R را نمی‌گیرد",

        "• BEST WATCH معامله نیست؛ فقط وضعیت تحت نظر است",

        "• داده ناکافی = NO VALID SETUP",

        "• هیچ سیگنال اجباری تولید نمی‌شود",

        "• نرخ اصلی USD و USDT فقط از TGJU",

        "• در خطای TGJU، فقط USD مجاز به استفاده از fallback معتبر است",

        "• اگر نرخ معتبر در دسترس نباشد، مقدار N/A نمایش داده می‌شود",

        "• منبع fallback هرگز به‌عنوان TGJU گزارش نمی‌شود",
    ]

    return "\n".join(lines)


# ============================================================
# HELPERS
# ============================================================

def action_emoji(status):

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


def split_telegram(
    text,
    limit=4000,
):

    return [
        text[i:i + limit]
        for i in range(
            0,
            len(text),
            limit,
        )
    ]


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    # ========================================================
    # SAMPLE DATA
    # Replace this section with your actual market engine
    # data provider when integrated.
    # ========================================================

    market = {

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

    portfolio = {

        "SOL": {

            "current_price": 150,

            "support": 140,

            "resistance": 160,

            "trend": "bullish",

            "rsi": 45,

            "volume_ratio": 1.5,

            "support_confirmations": 3,

            "confirmed_breakout": True,

            "volume_trend": "HIGH",

            "data_quality": 0.95,
        },
    }

    print(
        "ATLAS AI v12 starting..."
    )

    try:

        # ----------------------------------------------------
        # BUILD REPORT
        # ----------------------------------------------------

        report_text = build_report(
            market,
            portfolio,
        )

        print(
            "Report built successfully."
        )

        print(
            "Report length:",
            len(report_text),
        )

        # ----------------------------------------------------
        # TELEGRAM DELIVERY
        # ----------------------------------------------------

        print(
            "Sending report to Telegram..."
        )

        result = send_report(
            report_text
        )

        # ----------------------------------------------------
        # DELIVERY RESULT
        # ----------------------------------------------------

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
                "send_report() must return "
                "(parts_count, sent_count, errors)."
            )

        parts_count, sent_count, errors = result

        errors = errors or []

        print(
            "Telegram parts:",
            parts_count,
        )

        print(
            "Telegram successful destinations:",
            sent_count,
        )

        # ----------------------------------------------------
        # REAL DELIVERY VALIDATION
        # ----------------------------------------------------

        if errors:

            print(
                "Telegram delivery errors:"
            )

            for error in errors:

                print(
                    " -",
                    error,
                )

        if sent_count == 0:

            raise RuntimeError(
                "Telegram delivery failed: "
                "0 destinations received the report."
            )

        print(
            "SUCCESS: ATLAS v12 report "
            "delivered to Telegram."
        )

    except Exception as exc:

        print(
            "ERROR:",
            str(exc),
        )

        import traceback

        traceback.print_exc()

        raise
