import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# =========================================================
# ATLAS AI v2.1
# MULTI-SOURCE DATA ENGINE
# =========================================================
#
# Primary:
#   Binance public market data
#
# Backup:
#   Kraken public OHLC
#
# Validation:
#   CoinMarketCap Keyless Public API
#   CoinPaprika
#   Optional CoinGecko Demo API
#
# IMPORTANT:
#   No trade signal is produced when required market data
#   is unavailable or unreliable.
# =========================================================


TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()


# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = {
    "BTCUSDT": {
        "name": "BTC",
        "kraken": "XBTUSD",
        "gecko": "bitcoin",
        "paprika": "btc-bitcoin",
        "cmc": "BTC",
    },

    "ETHUSDT": {
        "name": "ETH",
        "kraken": "ETHUSD",
        "gecko": "ethereum",
        "paprika": "eth-ethereum",
        "cmc": "ETH",
    },

    "XRPUSDT": {
        "name": "XRP",
        "kraken": "XRPUSD",
        "gecko": "ripple",
        "paprika": "xrp-xrp",
        "cmc": "XRP",
    },

    "SOLUSDT": {
        "name": "SOL",
        "kraken": "SOLUSD",
        "gecko": "solana",
        "paprika": "sol-solana",
        "cmc": "SOL",
    },

    "TONUSDT": {
        "name": "TON",
        "kraken": "TONUSD",
        "gecko": "the-open-network",
        "paprika": "ton-toncoin",
        "cmc": "TON",
    },

    "UNIUSDT": {
        "name": "UNI",
        "kraken": "UNIUSD",
        "gecko": "uniswap",
        "paprika": "uni-uniswap",
        "cmc": "UNI",
    },

    "ETHFIUSDT": {
        "name": "ETHFI",
        "kraken": "ETHFIUSD",
        "gecko": "ether-fi",
        "paprika": "ethfi-ether-fi",
        "cmc": "ETHFI",
    },
}


# =========================================================
# BINANCE ENDPOINTS
# =========================================================

BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]


# =========================================================
# HTTP ENGINE
# =========================================================

def http_get(url, timeout=15, headers=None):

    request_headers = {
        "User-Agent": "ATLAS-AI/2.1",
        "Accept": "application/json",
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        headers=request_headers
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:

        status = response.getcode()
        raw = response.read().decode("utf-8")

        if status < 200 or status >= 300:
            raise RuntimeError(
                f"HTTP {status}"
            )

        return json.loads(raw)


# =========================================================
# HELPERS
# =========================================================

def safe_float(value):

    try:
        return float(value)
    except Exception:
        return None


def percent_difference(a, b):

    if a is None or b is None:
        return None

    if a == 0 or b == 0:
        return None

    return abs(a - b) / ((a + b) / 2) * 100


def format_price(price):

    if price is None:
        return "N/A"

    if price >= 1000:
        return f"${price:,.2f}"

    if price >= 1:
        return f"${price:,.4f}"

    return f"${price:,.6f}"


# =========================================================
# BINANCE 24H
# =========================================================

def get_binance_24h(symbol):

    errors = []

    for host in BINANCE_HOSTS:

        try:

            url = (
                f"{host}/api/v3/ticker/24hr"
                f"?symbol={urllib.parse.quote(symbol)}"
            )

            data = http_get(url, timeout=12)

            price = safe_float(data.get("lastPrice"))

            if price is None:
                raise RuntimeError(
                    "Invalid Binance lastPrice"
                )

            return {
                "price": price,
                "change": safe_float(
                    data.get("priceChangePercent")
                ),
                "high": safe_float(
                    data.get("highPrice")
                ),
                "low": safe_float(
                    data.get("lowPrice")
                ),
                "volume": safe_float(
                    data.get("quoteVolume")
                ),
                "source": "Binance",
                "endpoint": host,
            }

        except Exception as e:

            errors.append(
                f"{host}: {str(e)}"
            )

    raise RuntimeError(
        " | ".join(errors[-3:])
    )


# =========================================================
# BINANCE 4H CANDLES
# =========================================================

def get_binance_klines(
    symbol,
    interval="4h",
    limit=80
):

    errors = []

    for host in BINANCE_HOSTS:

        try:

            url = (
                f"{host}/api/v3/klines"
                f"?symbol={urllib.parse.quote(symbol)}"
                f"&interval={interval}"
                f"&limit={limit}"
            )

            data = http_get(url, timeout=15)

            if not isinstance(data, list):
                raise RuntimeError(
                    "Invalid Binance kline response"
                )

            if len(data) < 55:
                raise RuntimeError(
                    f"Insufficient candles: {len(data)}"
                )

            return {
                "candles": data,
                "source": "Binance",
                "endpoint": host,
            }

        except Exception as e:

            errors.append(
                f"{host}: {str(e)}"
            )

    raise RuntimeError(
        " | ".join(errors[-4:])
    )


# =========================================================
# KRAKEN 4H BACKUP
# =========================================================

def get_kraken_ohlc(pair):

    url = (
        "https://api.kraken.com/0/public/OHLC"
        f"?pair={urllib.parse.quote(pair)}"
        "&interval=240"
    )

    data = http_get(
        url,
        timeout=15
    )

    if data.get("error"):
        raise RuntimeError(
            "Kraken: "
            + str(data["error"])
        )

    result = data.get("result", {})

    pair_key = None

    for key in result:

        if key != "last":
            pair_key = key
            break

    if not pair_key:
        raise RuntimeError(
            "Kraken OHLC pair not found"
        )

    raw_candles = result[pair_key]

    if len(raw_candles) < 55:
        raise RuntimeError(
            f"Kraken insufficient candles: "
            f"{len(raw_candles)}"
        )

    candles = []

    for row in raw_candles:

        # Kraken:
        # [time, open, high, low, close,
        #  vwap, volume, count]

        candles.append([
            int(row[0]) * 1000,
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
        ])

    return {
        "candles": candles,
        "source": "Kraken",
        "endpoint": "api.kraken.com",
    }


# =========================================================
# COINPAPRIKA PRICE
# =========================================================

def get_coinpaprika_price(coin_id):

    url = (
        "https://api.coinpaprika.com/v1/tickers/"
        + urllib.parse.quote(coin_id)
    )

    data = http_get(
        url,
        timeout=12
    )

    usd = (
        data
        .get("quotes", {})
        .get("USD", {})
    )

    price = safe_float(
        usd.get("price")
    )

    change = safe_float(
        usd.get("percent_change_24h")
    )

    if price is None:
        raise RuntimeError(
            "CoinPaprika price unavailable"
        )

    return {
        "price": price,
        "change": change,
        "source": "CoinPaprika",
    }


# =========================================================
# COINMARKETCAP KEYLESS PRICE
# =========================================================

def get_cmc_price(symbol):

    url = (
        "https://pro-api.coinmarketcap.com"
        "/public-api/v3/cryptocurrency/quotes/latest"
        "?symbol="
        + urllib.parse.quote(symbol)
        + "&convert=USD"
    )

    data = http_get(
        url,
        timeout=15
    )

    records = data.get("data", [])

    if isinstance(records, dict):

        # Some response formats return:
        # {"BTC": [...]}

        if symbol in records:
            item = records[symbol]

            if isinstance(item, list):
                item = item[0]

        else:
            item = None

            for value in records.values():

                if isinstance(value, list) and value:
                    item = value[0]
                    break

                if isinstance(value, dict):
                    item = value
                    break

    elif isinstance(records, list):

        item = records[0] if records else None

    else:

        item = None

    if not item:
        raise RuntimeError(
            "CoinMarketCap data unavailable"
        )

    quote = (
        item
        .get("quote", {})
        .get("USD", {})
    )

    price = safe_float(
        quote.get("price")
    )

    change = safe_float(
        quote.get("percent_change_24h")
    )

    if price is None:
        raise RuntimeError(
            "CoinMarketCap price unavailable"
        )

    return {
        "price": price,
        "change": change,
        "source": "CoinMarketCap",
    }


# =========================================================
# COINGECKO OPTIONAL
# =========================================================

def get_coingecko_price(coin_id):

    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={urllib.parse.quote(coin_id)}"
        "&vs_currencies=usd"
        "&include_24hr_change=true"
    )

    headers = {}

    if COINGECKO_API_KEY:

        headers[
            "x-cg-demo-api-key"
        ] = COINGECKO_API_KEY

    data = http_get(
        url,
        timeout=15,
        headers=headers
    )

    coin = data.get(coin_id)

    if not coin:
        raise RuntimeError(
            "CoinGecko coin unavailable"
        )

    price = safe_float(
        coin.get("usd")
    )

    change = safe_float(
        coin.get("usd_24h_change")
    )

    if price is None:
        raise RuntimeError(
            "CoinGecko price unavailable"
        )

    return {
        "price": price,
        "change": change,
        "source": "CoinGecko",
    }


# =========================================================
# PRICE CONSENSUS
# =========================================================

def get_price_consensus(symbol, info):

    sources = []
    errors = []

    # -----------------------------------------------------
    # Binance
    # -----------------------------------------------------

    try:

        result = get_binance_24h(symbol)
        sources.append(result)

    except Exception as e:

        errors.append(
            "Binance: " + str(e)
        )

    # -----------------------------------------------------
    # CoinPaprika
    # -----------------------------------------------------

    try:

        result = get_coinpaprika_price(
            info["paprika"]
        )

        sources.append(result)

    except Exception as e:

        errors.append(
            "CoinPaprika: " + str(e)
        )

    # -----------------------------------------------------
    # CoinMarketCap
    # -----------------------------------------------------

    try:

        result = get_cmc_price(
            info["cmc"]
        )

        sources.append(result)

    except Exception as e:

        errors.append(
            "CMC: " + str(e)
        )

    # -----------------------------------------------------
    # CoinGecko
    # -----------------------------------------------------

    try:

        result = get_coingecko_price(
            info["gecko"]
        )

        sources.append(result)

    except Exception as e:

        errors.append(
            "CoinGecko: " + str(e)
        )

    if not sources:

        raise RuntimeError(
            "No price source available | "
            + " | ".join(errors)
        )

    prices = [
        x["price"]
        for x in sources
        if x.get("price") is not None
    ]

    median_price = sorted(prices)[
        len(prices) // 2
    ]

    max_difference = 0

    for price in prices:

        diff = percent_difference(
            price,
            median_price
        )

        if diff is not None:
            max_difference = max(
                max_difference,
                diff
            )

    if max_difference <= 0.50:

        confidence = "HIGH"

    elif max_difference <= 1.50:

        confidence = "MEDIUM"

    else:

        confidence = "LOW"

    return {
        "price": median_price,
        "sources": sources,
        "errors": errors,
        "confidence": confidence,
        "max_difference": max_difference,
    }


# =========================================================
# REMOVE INCOMPLETE CANDLE
# =========================================================

def remove_incomplete_last_candle(candles):

    if len(candles) < 2:
        return candles

    try:

        last_open_time = int(
            candles[-1][0]
        )

        now_ms = int(
            datetime.now(
                timezone.utc
            ).timestamp() * 1000
        )

        # 4H = 14,400,000 ms
        candle_length = 4 * 60 * 60 * 1000

        candle_close_time = (
            last_open_time
            + candle_length
        )

        if candle_close_time > now_ms:

            return candles[:-1]

    except Exception:

        pass

    return candles


# =========================================================
# SELECT 4H DATA SOURCE
# =========================================================

def get_4h_candles(symbol, info):

    errors = []

    # -----------------------------------------------------
    # Binance
    # -----------------------------------------------------

    try:

        result = get_binance_klines(
            symbol,
            interval="4h",
            limit=80
        )

        candles = (
            remove_incomplete_last_candle(
                result["candles"]
            )
        )

        if len(candles) >= 55:

            return {
                "candles": candles,
                "source": "Binance",
                "endpoint": result["endpoint"],
            }

    except Exception as e:

        errors.append(
            "Binance 4H: " + str(e)
        )

    # -----------------------------------------------------
    # Kraken
    # -----------------------------------------------------

    try:

        result = get_kraken_ohlc(
            info["kraken"]
        )

        candles = (
            remove_incomplete_last_candle(
                result["candles"]
            )
        )

        if len(candles) >= 55:

            return {
                "candles": candles,
                "source": "Kraken",
                "endpoint": result["endpoint"],
            }

    except Exception as e:

        errors.append(
            "Kraken 4H: " + str(e)
        )

    raise RuntimeError(
        "4H DATA UNAVAILABLE | "
        + " | ".join(errors)
    )


# =========================================================
# EXTRACT CLOSES
# =========================================================

def extract_closes(candles):

    closes = []

    for candle in candles:

        try:
            closes.append(
                float(candle[4])
            )

        except Exception:
            continue

    return closes


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    result = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
            + result
        )

    return result


# =========================================================
# RSI
# =========================================================

def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# =========================================================
# TECHNICAL ANALYSIS
# =========================================================

def technical_analysis(
    symbol,
    info
):

    market = get_price_consensus(
        symbol,
        info
    )

    candles_info = get_4h_candles(
        symbol,
        info
    )

    candles = candles_info[
        "candles"
    ]

    closes = extract_closes(
        candles
    )

    if len(closes) < 55:

        raise RuntimeError(
            "Insufficient 4H closes"
        )

    current = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi14 = rsi(
        closes,
        14
    )

    score = 0

    # -----------------------------------------------------
    # Price vs EMA20
    # -----------------------------------------------------

    if ema20 is not None:

        if current > ema20:
            score += 1
        else:
            score -= 1

    # -----------------------------------------------------
    # Price vs EMA50
    # -----------------------------------------------------

    if ema50 is not None:

        if current > ema50:
            score += 1
        else:
            score -= 1

    # -----------------------------------------------------
    # EMA20 vs EMA50
    # -----------------------------------------------------

    if (
        ema20 is not None
        and ema50 is not None
    ):

        if ema20 > ema50:
            score += 2
        else:
            score -= 2

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if rsi14 is not None:

        if 50 <= rsi14 < 70:

            score += 1

        elif rsi14 >= 70:

            score -= 1

        elif 30 < rsi14 < 50:

            score -= 1

        elif rsi14 <= 30:

            score += 1

    # -----------------------------------------------------
    # Signal
    # -----------------------------------------------------

    if score >= 4:

        signal = "🟢 BUY BIAS"

    elif score >= 2:

        signal = "🟢 BULLISH"

    elif score <= -4:

        signal = "🔴 SELL BIAS"

    elif score <= -2:

        signal = "🟠 BEARISH"

    else:

        signal = "⚪ NEUTRAL"

    return {
        "market": market,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "score": score,
        "signal": signal,
        "technical_source":
            candles_info["source"],
        "technical_endpoint":
            candles_info["endpoint"],
    }


# =========================================================
# DATA QUALITY LABEL
# =========================================================

def data_quality_label(analysis):

    market = analysis["market"]

    confidence = market[
        "confidence"
    ]

    technical_source = analysis[
        "technical_source"
    ]

    if (
        confidence == "HIGH"
        and technical_source == "Binance"
    ):

        return "🟢 HIGH"

    if confidence in [
        "HIGH",
        "MEDIUM"
    ]:

        return "🟡 MEDIUM"

    return "🟠 LOW"


# =========================================================
# ATLAS REPORT
# =========================================================

def atlas_report():

    lines = []

    tehran = ZoneInfo(
        "Asia/Tehran"
    )

    now = datetime.now(
        tehran
    )

    lines.append(
        "🤖 ATLAS AI — SNIPER"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        now.strftime(
            "%Y/%m/%d  %H:%M"
        )
        + " 🇮🇷"
    )

    lines.append(
        "Timeframe: 4H"
    )

    lines.append("")

    bullish = 0
    bearish = 0
    unavailable = 0

    for symbol, info in WATCHLIST.items():

        name = info["name"]

        try:

            analysis = technical_analysis(
                symbol,
                info
            )

            market = analysis[
                "market"
            ]

            price = market[
                "price"
            ]

            change = None

            # Prefer Binance 24H change
            # when available.
            for source in market[
                "sources"
            ]:

                if (
                    source["source"]
                    == "Binance"
                ):

                    change = source[
                        "change"
                    ]

                    break

            if change is None:

                for source in market[
                    "sources"
                ]:

                    if source.get(
                        "change"
                    ) is not None:

                        change = source[
                            "change"
                        ]

                        break

            rsi14 = analysis[
                "rsi"
            ]

            score = analysis[
                "score"
            ]

            signal = analysis[
                "signal"
            ]

            if score >= 2:
                bullish += 1

            elif score <= -2:
                bearish += 1

            quality = data_quality_label(
                analysis
            )

            source_names = [
                x["source"]
                for x in market[
                    "sources"
                ]
            ]

            source_text = (
                ", ".join(
                    source_names
                )
                if source_names
                else "None"
            )

            lines.append(
                f"🔹 {name}"
            )

            lines.append(
                "Price: "
                + format_price(price)
            )

            if change is not None:

                lines.append(
                    f"24H: "
                    f"{change:+.2f}%"
                )

            if rsi14 is not None:

                lines.append(
                    f"RSI14: "
                    f"{rsi14:.1f}"
                )

            lines.append(
                f"4H Score: "
                f"{score:+d}"
            )

            lines.append(
                f"Signal: "
                f"{signal}"
            )

            lines.append(
                f"Data: "
                f"{quality}"
            )

            lines.append(
                f"Sources: "
                f"{source_text}"
            )

            lines.append(
                f"4H Engine: "
                f"{analysis['technical_source']}"
            )

            if (
                market[
                    "max_difference"
                ] > 1.5
            ):

                lines.append(
                    "⚠️ DATA CONFLICT: "
                    f"{market['max_difference']:.2f}%"
                )

            lines.append("")

        except Exception as e:

            unavailable += 1

            lines.append(
                f"🔹 {name}"
            )

            lines.append(
                "⚫ DATA UNAVAILABLE"
            )

            lines.append(
                "Action: NO TRADE"
            )

            # Keep the real reason visible
            # but short enough for Telegram.
            reason = str(e)

            if len(reason) > 240:

                reason = (
                    reason[:240]
                    + "..."
                )

            lines.append(
                f"Reason: {reason}"
            )

            lines.append("")

    # =====================================================
    # MARKET SUMMARY
    # =====================================================

    if unavailable == len(
        WATCHLIST
    ):

        market_state = (
            "⚫ MARKET STATUS: "
            "DATA UNAVAILABLE"
        )

    elif bullish >= 5:

        market_state = (
            "🟢 MARKET BIAS: BULLISH"
        )

    elif bearish >= 5:

        market_state = (
            "🔴 MARKET BIAS: BEARISH"
        )

    elif bullish > bearish:

        market_state = (
            "🟢 MARKET BIAS: "
            "SLIGHTLY BULLISH"
        )

    elif bearish > bullish:

        market_state = (
            "🟠 MARKET BIAS: "
            "SLIGHTLY BEARISH"
        )

    else:

        market_state = (
            "⚪ MARKET BIAS: NEUTRAL"
        )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        market_state
    )

    lines.append(
        f"Bullish: {bullish} | "
        f"Bearish: {bearish}"
    )

    lines.append(
        f"Data unavailable: "
        f"{unavailable}/{len(WATCHLIST)}"
    )

    lines.append("")

    if unavailable > 0:

        lines.append(
            "⚠️ DATA ENGINE: "
            "PARTIAL / DEGRADED"
        )

        lines.append(
            "⚫ No-trade protection "
            "active for unavailable assets."
        )

        lines.append("")

    else:

        lines.append(
            "🟢 DATA ENGINE: "
            "ALL ASSETS AVAILABLE"
        )

        lines.append("")

    lines.append(
        "🎯 ATLAS SNIPER MODE: ACTIVE"
    )

    lines.append("")

    lines.append(
        "⚠️ این گزارش تحلیلی است؛ "
        "تصمیم نهایی خرید/فروش باید "
        "با مدیریت ریسک انجام شود."
    )

    return "\n".join(lines)


# =========================================================
# TELEGRAM
# =========================================================

def send_message(
    chat_id,
    text
):

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_TOKEN is not configured."
        )

    if not chat_id:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    # Telegram message limit protection
    if len(text) > 4000:

        text = text[:3950] + (
            "\n\n"
            "⚠️ Report truncated."
        )

    url = (
        f"https://api.telegram.org/bot"
        f"{TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": str(chat_id),
        "text": text
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type":
            "application/x-www-form-urlencoded"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        return response.read()


# =========================================================
# CHAT ID
# =========================================================

def find_chat_id():

    if CHAT_ID:

        return CHAT_ID

    if not TOKEN:

        return None

    # Fallback only.
    # Normally GitHub Secret is used.

    try:

        url = (
            f"https://api.telegram.org/bot"
            f"{TOKEN}/getUpdates"
            "?timeout=5"
        )

        data = http_get(
            url,
            timeout=10
        )

        updates = data.get(
            "result",
            []
        )

        if not updates:

            return None

        for update in reversed(
            updates
        ):

            message = update.get(
                "message"
            )

            if not message:
                continue

            chat = message.get(
                "chat"
            )

            if (
                chat
                and chat.get("id")
            ):

                return chat["id"]

    except Exception as e:

        print(
            "Telegram update error:",
            str(e)
        )

    return None


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "================================"
    )

    print(
        "🤖 ATLAS AI v2.1"
    )

    print(
        "MULTI-SOURCE DATA ENGINE"
    )

    print(
        "================================"
    )

    if not TOKEN:

        print(
            "ERROR: "
            "TELEGRAM_TOKEN is missing."
        )

        return 1

    try:

        report = atlas_report()

        print("")
        print(report)
        print("")

        chat_id = find_chat_id()

        if not chat_id:

            print(
                "ERROR: "
                "TELEGRAM_CHAT_ID is missing."
            )

            return 1

        send_message(
            chat_id,
            report
        )

        print(
            "✅ ATLAS report "
            "sent successfully."
        )

        print(
            "ATLAS execution completed."
        )

        return 0

    except Exception as e:

        print("")
        print(
            "❌ ATLAS ERROR:"
        )

        print(
            str(e)
        )

        return 1


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )
