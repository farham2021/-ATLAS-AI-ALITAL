import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# =========================================================
# ATLAS AI v3 — SNIPER CORE
# Multi-source data + 4H technical engine
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
# BINANCE
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
# HTTP
# =========================================================

def http_get(url, timeout=15, headers=None):

    request_headers = {
        "User-Agent": "ATLAS-AI/3.0",
        "Accept": "application/json",
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        headers=request_headers,
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:

        status = response.getcode()

        raw = response.read().decode("utf-8")

        if status < 200 or status >= 300:
            raise RuntimeError(f"HTTP {status}")

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
                    "Invalid Binance price"
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
        "Binance 24H unavailable | "
        + " | ".join(errors[-3:])
    )


# =========================================================
# BINANCE 4H
# =========================================================

def get_binance_klines(
    symbol,
    interval="4h",
    limit=100,
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

            data = http_get(
                url,
                timeout=15,
            )

            if not isinstance(data, list):
                raise RuntimeError(
                    "Invalid kline response"
                )

            if len(data) < 60:
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
        "Binance 4H unavailable | "
        + " | ".join(errors[-4:])
    )


# =========================================================
# KRAKEN BACKUP
# =========================================================

def get_kraken_ohlc(pair):

    url = (
        "https://api.kraken.com/0/public/OHLC"
        f"?pair={urllib.parse.quote(pair)}"
        "&interval=240"
    )

    data = http_get(
        url,
        timeout=15,
    )

    if data.get("error"):
        raise RuntimeError(
            "Kraken: "
            + str(data["error"])
        )

    result = data.get(
        "result",
        {},
    )

    pair_key = None

    for key in result:

        if key != "last":
            pair_key = key
            break

    if not pair_key:
        raise RuntimeError(
            "Kraken pair not found"
        )

    raw_candles = result[pair_key]

    if len(raw_candles) < 60:
        raise RuntimeError(
            "Kraken insufficient candles"
        )

    candles = []

    for row in raw_candles:

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
# COINPAPRIKA
# =========================================================

def get_coinpaprika_price(coin_id):

    url = (
        "https://api.coinpaprika.com/v1/tickers/"
        + urllib.parse.quote(coin_id)
    )

    data = http_get(
        url,
        timeout=12,
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
            "CoinPaprika unavailable"
        )

    return {
        "price": price,
        "change": change,
        "source": "CoinPaprika",
    }


# =========================================================
# COINGECKO
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

        headers["x-cg-demo-api-key"] = (
            COINGECKO_API_KEY
        )

    data = http_get(
        url,
        timeout=15,
        headers=headers,
    )

    coin = data.get(coin_id)

    if not coin:
        raise RuntimeError(
            "CoinGecko unavailable"
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
# CMC OPTIONAL
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
        timeout=15,
    )

    records = data.get(
        "data",
        {}
    )

    item = None

    if isinstance(records, dict):

        if symbol in records:

            item = records[symbol]

            if isinstance(item, list) and item:
                item = item[0]

        else:

            for value in records.values():

                if isinstance(value, list) and value:
                    item = value[0]
                    break

                if isinstance(value, dict):
                    item = value
                    break

    elif isinstance(records, list):

        if records:
            item = records[0]

    if not item:
        raise RuntimeError(
            "CoinMarketCap unavailable"
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
            "CMC price unavailable"
        )

    return {
        "price": price,
        "change": change,
        "source": "CoinMarketCap",
    }


# =========================================================
# PRICE CONSENSUS
# =========================================================

def get_price_consensus(
    symbol,
    info,
):

    sources = []
    errors = []

    try:
        sources.append(
            get_binance_24h(symbol)
        )
    except Exception as e:
        errors.append(
            "Binance: " + str(e)
        )

    try:
        sources.append(
            get_coinpaprika_price(
                info["paprika"]
            )
        )
    except Exception as e:
        errors.append(
            "CoinPaprika: " + str(e)
        )

    try:
        sources.append(
            get_coingecko_price(
                info["gecko"]
            )
        )
    except Exception as e:
        errors.append(
            "CoinGecko: " + str(e)
        )

    # CMC is optional.
    try:
        sources.append(
            get_cmc_price(
                info["cmc"]
            )
        )
    except Exception as e:
        errors.append(
            "CMC: " + str(e)
        )

    if not sources:
        raise RuntimeError(
            "No price source available"
        )

    prices = [
        x["price"]
        for x in sources
        if x.get("price") is not None
    ]

    if not prices:
        raise RuntimeError(
            "No valid prices"
        )

    ordered = sorted(prices)

    median_price = ordered[
        len(ordered) // 2
    ]

    max_difference = 0

    for price in prices:

        diff = percent_difference(
            price,
            median_price,
        )

        if diff is not None:
            max_difference = max(
                max_difference,
                diff,
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

def remove_incomplete_last_candle(
    candles
):

    if len(candles) < 2:
        return candles

    try:

        last_open = int(
            candles[-1][0]
        )

        now_ms = int(
            datetime.now(
                timezone.utc
            ).timestamp() * 1000
        )

        candle_length = (
            4 * 60 * 60 * 1000
        )

        if (
            last_open
            + candle_length
            > now_ms
        ):

            return candles[:-1]

    except Exception:
        pass

    return candles


# =========================================================
# SELECT 4H ENGINE
# =========================================================

def get_4h_candles(
    symbol,
    info,
):

    errors = []

    try:

        result = get_binance_klines(
            symbol,
            "4h",
            100,
        )

        candles = (
            remove_incomplete_last_candle(
                result["candles"]
            )
        )

        if len(candles) >= 60:

            return {
                "candles": candles,
                "source": "Binance",
                "endpoint": result["endpoint"],
            }

    except Exception as e:

        errors.append(
            "Binance: " + str(e)
        )

    try:

        result = get_kraken_ohlc(
            info["kraken"]
        )

        candles = (
            remove_incomplete_last_candle(
                result["candles"]
            )
        )

        if len(candles) >= 60:

            return {
                "candles": candles,
                "source": "Kraken",
                "endpoint": result["endpoint"],
            }

    except Exception as e:

        errors.append(
            "Kraken: " + str(e)
        )

    raise RuntimeError(
        "4H DATA UNAVAILABLE | "
        + " | ".join(errors)
    )


# =========================================================
# CANDLE EXTRACTION
# =========================================================

def extract_ohlcv(candles):

    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    for candle in candles:

        try:

            opens.append(
                float(candle[1])
            )

            highs.append(
                float(candle[2])
            )

            lows.append(
                float(candle[3])
            )

            closes.append(
                float(candle[4])
            )

            volumes.append(
                float(candle[5])
            )

        except Exception:
            continue

    return (
        opens,
        highs,
        lows,
        closes,
        volumes,
    )


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = (
        2 / (period + 1)
    )

    result = (
        sum(values[:period])
        / period
    )

    for value in values[period:]:

        result = (
            (value - result)
            * multiplier
            + result
        )

    return result


# =========================================================
# EMA SERIES
# =========================================================

def ema_series(values, period):

    if len(values) < period:
        return []

    multiplier = (
        2 / (period + 1)
    )

    result = (
        sum(values[:period])
        / period
    )

    series = [result]

    for value in values[period:]:

        result = (
            (value - result)
            * multiplier
            + result
        )

        series.append(result)

    return series


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
        len(values),
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
        len(gains),
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
# MACD
# =========================================================

def macd(values):

    fast = ema_series(
        values,
        12,
    )

    slow = ema_series(
        values,
        26,
    )

    if not fast or not slow:
        return None

    # Align series from the latest values.
    length = min(
        len(fast),
        len(slow),
    )

    fast = fast[-length:]
    slow = slow[-length:]

    macd_line = []

    for i in range(length):

        macd_line.append(
            fast[i] - slow[i]
        )

    signal_series = ema_series(
        macd_line,
        9,
    )

    if not signal_series:
        return None

    macd_value = macd_line[-1]
    signal_value = signal_series[-1]

    histogram = (
        macd_value
        - signal_value
    )

    return {
        "macd": macd_value,
        "signal": signal_value,
        "histogram": histogram,
    }


# =========================================================
# ATR
# =========================================================

def atr(
    highs,
    lows,
    closes,
    period=14,
):

    if len(closes) < period + 1:
        return None

    true_ranges = []

    for i in range(
        1,
        len(closes),
    ):

        high = highs[i]
        low = lows[i]
        previous_close = closes[i - 1]

        tr = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            ),
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    value = (
        sum(
            true_ranges[:period]
        )
        / period
    )

    for tr in true_ranges[period:]:

        value = (
            (
                value
                * (period - 1)
            )
            + tr
        ) / period

    return value


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def support_resistance(
    highs,
    lows,
    closes,
    lookback=30,
):

    if len(closes) < lookback:
        lookback = len(closes)

    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]

    resistance = max(
        recent_highs
    )

    support = min(
        recent_lows
    )

    return support, resistance


# =========================================================
# VOLUME ANALYSIS
# =========================================================

def volume_analysis(
    volumes,
    period=20,
):

    if len(volumes) < period + 1:
        return None

    average = (
        sum(
            volumes[-period - 1:-1]
        )
        / period
    )

    current = volumes[-1]

    if average <= 0:
        return None

    ratio = (
        current / average
    )

    if ratio >= 1.30:
        state = "CONFIRMED"

    elif ratio >= 0.90:
        state = "NORMAL"

    else:
        state = "WEAK"

    return {
        "current": current,
        "average": average,
        "ratio": ratio,
        "state": state,
    }


# =========================================================
# TECHNICAL ENGINE
# =========================================================

def technical_analysis(
    symbol,
    info,
):

    market = get_price_consensus(
        symbol,
        info,
    )

    candles_info = get_4h_candles(
        symbol,
        info,
    )

    candles = candles_info[
        "candles"
    ]

    (
        opens,
        highs,
        lows,
        closes,
        volumes,
    ) = extract_ohlcv(
        candles
    )

    if len(closes) < 60:
        raise RuntimeError(
            "Insufficient 4H data"
        )

    current = closes[-1]

    ema20 = ema(
        closes,
        20,
    )

    ema50 = ema(
        closes,
        50,
    )

    rsi14 = rsi(
        closes,
        14,
    )

    macd_data = macd(
        closes
    )

    atr14 = atr(
        highs,
        lows,
        closes,
        14,
    )

    support, resistance = (
        support_resistance(
            highs,
            lows,
            closes,
            30,
        )
    )

    volume_data = (
        volume_analysis(
            volumes,
            20,
        )
    )

    score = 0

    # -----------------------------------------------------
    # Trend
    # -----------------------------------------------------

    if ema20 is not None:

        if current > ema20:
            score += 1
        else:
            score -= 1

    if ema50 is not None:

        if current > ema50:
            score += 1
        else:
            score -= 1

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
    # MACD
    # -----------------------------------------------------

    macd_state = "N/A"

    if macd_data:

        if (
            macd_data["macd"]
            > macd_data["signal"]
        ):

            score += 2
            macd_state = "BULLISH"

        else:

            score -= 2
            macd_state = "BEARISH"

    # -----------------------------------------------------
    # Volume
    # -----------------------------------------------------

    volume_state = "N/A"

    if volume_data:

        volume_state = (
            volume_data["state"]
        )

        if (
            volume_data["ratio"]
            >= 1.30
        ):

            if score > 0:
                score += 1
            elif score < 0:
                score -= 1

    # -----------------------------------------------------
    # Trend label
    # -----------------------------------------------------

    if (
        ema20 is not None
        and ema50 is not None
        and current > ema20
        and ema20 > ema50
    ):

        trend = "BULLISH"

    elif (
        ema20 is not None
        and ema50 is not None
        and current < ema20
        and ema20 < ema50
    ):

        trend = "BEARISH"

    else:

        trend = "MIXED"

    # -----------------------------------------------------
    # ATR risk levels
    # -----------------------------------------------------

    entry = market["price"]

    if atr14:

        if score >= 2:

            stop = entry - (
                atr14 * 1.5
            )

            tp1 = entry + (
                atr14 * 2.5
            )

            tp2 = entry + (
                atr14 * 4.0
            )

        elif score <= -2:

            stop = entry + (
                atr14 * 1.5
            )

            tp1 = entry - (
                atr14 * 2.5
            )

            tp2 = entry - (
                atr14 * 4.0
            )

        else:

            stop = None
            tp1 = None
            tp2 = None

    else:

        stop = None
        tp1 = None
        tp2 = None

    # -----------------------------------------------------
    # Resistance / support filter
    # -----------------------------------------------------

    near_resistance = False
    near_support = False

    if resistance and entry > 0:

        distance = (
            resistance - entry
        ) / entry * 100

        if (
            0 <= distance <= 1.5
        ):
            near_resistance = True

    if support and entry > 0:

        distance = (
            entry - support
        ) / entry * 100

        if (
            0 <= distance <= 1.5
        ):
            near_support = True

    # -----------------------------------------------------
    # Action
    # -----------------------------------------------------

    action = "NO TRADE"

    if (
        market["confidence"]
        == "LOW"
        or market["max_difference"]
        > 5.0
    ):

        action = "NO TRADE"

    elif (
        score >= 7
        and not near_resistance
        and volume_state != "WEAK"
    ):

        action = "BUY"

    elif (
        score <= -7
        and not near_support
        and volume_state != "WEAK"
    ):

        action = "SELL"

    elif score >= 4:

        action = "BULLISH WATCH"

    elif score <= -4:

        action = "BEARISH WATCH"

    else:

        action = "NO TRADE"

    # -----------------------------------------------------
    # Confidence
    # -----------------------------------------------------

    confidence = 50

    confidence += min(
        abs(score) * 5,
        30,
    )

    if trend in [
        "BULLISH",
        "BEARISH",
    ]:
        confidence += 5

    if volume_state == "CONFIRMED":
        confidence += 5

    elif volume_state == "WEAK":
        confidence -= 10

    if macd_state != "N/A":
        confidence += 5

    if (
        market["confidence"]
        == "MEDIUM"
    ):
        confidence -= 8

    elif (
        market["confidence"]
        == "LOW"
    ):
        confidence -= 20

    if near_resistance and score > 0:
        confidence -= 10

    if near_support and score < 0:
        confidence -= 10

    confidence = max(
        0,
        min(
            100,
            int(confidence),
        ),
    )

    # -----------------------------------------------------
    # Risk / Reward
    # -----------------------------------------------------

    rr = None

    if (
        action == "BUY"
        and stop is not None
        and tp1 is not None
    ):

        risk = (
            entry - stop
        )

        reward = (
            tp1 - entry
        )

        if risk > 0:
            rr = reward / risk

    elif (
        action == "SELL"
        and stop is not None
        and tp1 is not None
    ):

        risk = (
            stop - entry
        )

        reward = (
            entry - tp1
        )

        if risk > 0:
            rr = reward / risk

    return {
        "market": market,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "macd": macd_data,
        "macd_state": macd_state,
        "atr": atr14,
        "volume": volume_data,
        "volume_state": volume_state,
        "support": support,
        "resistance": resistance,
        "trend": trend,
        "score": score,
        "action": action,
        "confidence": confidence,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rr": rr,
        "technical_source": candles_info[
            "source"
        ],
        "technical_endpoint": candles_info[
            "endpoint"
        ],
    }


# =========================================================
# DATA QUALITY
# =========================================================

def data_quality_label(
    analysis
):

    market = analysis[
        "market"
    ]

    if (
        market["confidence"]
        == "HIGH"
        and analysis[
            "technical_source"
        ]
        == "Binance"
    ):

        return "🟢 HIGH"

    if market["confidence"] in [
        "HIGH",
        "MEDIUM",
    ]:

        return "🟡 MEDIUM"

    return "🟠 LOW"


# =========================================================
# TELEGRAM FORMAT
# =========================================================

def format_number(
    value,
    decimals=2,
):

    if value is None:
        return "N/A"

    return f"{value:,.{decimals}f}"


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
        "🤖 ATLAS AI — SNIPER v3"
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
    no_trade = 0
    unavailable = 0

    for symbol, info in WATCHLIST.items():

        name = info["name"]

        try:

            analysis = (
                technical_analysis(
                    symbol,
                    info,
                )
            )

            market = analysis[
                "market"
            ]

            score = analysis[
                "score"
            ]

            action = analysis[
                "action"
            ]

            confidence = analysis[
                "confidence"
            ]

            quality = (
                data_quality_label(
                    analysis
                )
            )

            if score >= 2:
                bullish += 1

            elif score <= -2:
                bearish += 1

            if action in [
                "NO TRADE",
                "BULLISH WATCH",
                "BEARISH WATCH",
            ]:
                no_trade += 1

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
                + format_price(
                    market["price"]
                )
            )

            change = None

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

            if change is not None:

                lines.append(
                    f"24H: "
                    f"{change:+.2f}%"
                )

            lines.append(
                "Trend: "
                + (
                    "🟢 "
                    if analysis[
                        "trend"
                    ] == "BULLISH"
                    else
                    "🔴 "
                    if analysis[
                        "trend"
                    ] == "BEARISH"
                    else
                    "🟡 "
                )
                + analysis[
                    "trend"
                ]
            )

            if analysis["rsi"] is not None:

                lines.append(
                    f"RSI14: "
                    f"{analysis['rsi']:.1f}"
                )

            lines.append(
                "MACD: "
                + (
                    "🟢 "
                    if analysis[
                        "macd_state"
                    ] == "BULLISH"
                    else
                    "🔴 "
                    if analysis[
                        "macd_state"
                    ] == "BEARISH"
                    else
                    "⚪ "
                )
                + analysis[
                    "macd_state"
                ]
            )

            lines.append(
                "Volume: "
                + (
                    "🟢 "
                    if analysis[
                        "volume_state"
                    ] == "CONFIRMED"
                    else
                    "🟡 "
                    if analysis[
                        "volume_state"
                    ] == "NORMAL"
                    else
                    "🔴 "
                )
                + analysis[
                    "volume_state"
                ]
            )

            lines.append(
                f"4H Score: "
                f"{score:+d}"
            )

            lines.append(
                f"Confidence: "
                f"{confidence}%"
            )

            if analysis[
                "support"
            ] is not None:

                lines.append(
                    "Support: "
                    + format_price(
                        analysis[
                            "support"
                        ]
                    )
                )

            if analysis[
                "resistance"
            ] is not None:

                lines.append(
                    "Resistance: "
                    + format_price(
                        analysis[
                            "resistance"
                        ]
                    )
                )

            lines.append(
                "🎯 ACTION: "
                + action
            )

            if action in [
                "BUY",
                "SELL",
            ]:

                lines.append(
                    "Entry: "
                    + format_price(
                        analysis[
                            "entry"
                        ]
                    )
                )

                lines.append(
                    "Stop: "
                    + format_price(
                        analysis[
                            "stop"
                        ]
                    )
                )

                lines.append(
                    "TP1: "
                    + format_price(
                        analysis[
                            "tp1"
                        ]
                    )
                )

                lines.append(
                    "TP2: "
                    + format_price(
                        analysis[
                            "tp2"
                        ]
                    )
                )

                if analysis[
                    "rr"
                ] is not None:

                    lines.append(
                        "R/R: "
                        f"1:{analysis['rr']:.2f}"
                    )

            lines.append(
                "Data: "
                + quality
            )

            lines.append(
                "Sources: "
                + source_text
            )

            lines.append(
                "4H Engine: "
                + analysis[
                    "technical_source"
                ]
            )

            if market[
                "max_difference"
            ] > 1.5:

                lines.append(
                    "⚠️ DATA CONFLICT: "
                    f"{market['max_difference']:.2f}%"
                )

            lines.append("")

        except Exception as e:

            unavailable += 1
            no_trade += 1

            lines.append(
                f"🔹 {name}"
            )

            lines.append(
                "⚫ DATA UNAVAILABLE"
            )

            lines.append(
                "🎯 ACTION: NO TRADE"
            )

            reason = str(e)

            if len(reason) > 220:

                reason = (
                    reason[:220]
                    + "..."
                )

            lines.append(
                "Reason: "
                + reason
            )

            lines.append("")

    # =====================================================
    # MARKET BIAS
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
        f"No-trade/watch: "
        f"{no_trade}"
    )

    lines.append(
        f"Data unavailable: "
        f"{unavailable}/"
        f"{len(WATCHLIST)}"
    )

    lines.append("")

    if unavailable > 0:

        lines.append(
            "⚠️ DATA ENGINE: "
            "PARTIAL / DEGRADED"
        )

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
        "⚠️ این گزارش نسخه آزمایشی "
        "SNIPER v3 است؛ "
        "سیگنال‌ها قبل از استفاده واقعی "
        "باید با مدیریت ریسک تأیید شوند."
    )

    return "\n".join(lines)


# =========================================================
# TELEGRAM
# =========================================================

def send_message(
    chat_id,
    text,
):

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_TOKEN is not configured."
        )

    if not chat_id:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    if len(text) > 4000:

        text = (
            text[:3950]
            + "\n\n⚠️ Report truncated."
        )

    url = (
        f"https://api.telegram.org/bot"
        f"{TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": str(chat_id),
        "text": text,
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type":
            "application/x-www-form-urlencoded"
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=20,
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

    try:

        url = (
            f"https://api.telegram.org/bot"
            f"{TOKEN}/getUpdates"
            "?timeout=5"
        )

        data = http_get(
            url,
            timeout=10,
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
            str(e),
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
        "🤖 ATLAS AI v3"
    )

    print(
        "SNIPER CORE"
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
            report,
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
