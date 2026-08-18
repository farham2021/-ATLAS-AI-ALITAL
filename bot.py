import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# =========================================================
# ATLAS AI — SNIPER v4
# =========================================================
#
# 4H Multi-Factor Decision Engine
#
# Data:
#   Binance
#   Kraken backup
#   CoinPaprika
#   CoinGecko optional
#
# Engine:
#   EMA20 / EMA50
#   RSI14
#   MACD
#   Volume
#   Support / Resistance
#   Breakout / Pullback
#   BTC Market Regime
#   Risk / Reward
#
# IMPORTANT:
# Bullish != BUY
# BUY requires confirmation + acceptable risk.
# =========================================================


TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

COINGECKO_API_KEY = os.environ.get(
    "COINGECKO_API_KEY", ""
).strip()


# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = {
    "BTCUSDT": {
        "name": "BTC",
        "kraken": "XBTUSD",
        "gecko": "bitcoin",
        "paprika": "btc-bitcoin",
    },
    "ETHUSDT": {
        "name": "ETH",
        "kraken": "ETHUSD",
        "gecko": "ethereum",
        "paprika": "eth-ethereum",
    },
    "XRPUSDT": {
        "name": "XRP",
        "kraken": "XRPUSD",
        "gecko": "ripple",
        "paprika": "xrp-xrp",
    },
    "SOLUSDT": {
        "name": "SOL",
        "kraken": "SOLUSD",
        "gecko": "solana",
        "paprika": "sol-solana",
    },
    "TONUSDT": {
        "name": "TON",
        "kraken": "TONUSD",
        "gecko": "the-open-network",
        "paprika": "ton-toncoin",
    },
    "UNIUSDT": {
        "name": "UNI",
        "kraken": "UNIUSD",
        "gecko": "uniswap",
        "paprika": "uni-uniswap",
    },
    "ETHFIUSDT": {
        "name": "ETHFI",
        "kraken": "ETHFIUSD",
        "gecko": "ether-fi",
        "paprika": "ethfi-ether-fi",
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
]


# =========================================================
# HTTP
# =========================================================

def http_get(url, timeout=15, headers=None):

    request_headers = {
        "User-Agent": "ATLAS-AI/4.0",
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

        if status < 200 or status >= 300:
            raise RuntimeError(
                f"HTTP {status}"
            )

        raw = response.read().decode("utf-8")

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

    return (
        abs(a - b)
        / ((a + b) / 2)
        * 100
    )


def format_price(price):

    if price is None:
        return "N/A"

    if price >= 1000:
        return f"${price:,.2f}"

    if price >= 1:
        return f"${price:,.4f}"

    return f"${price:,.6f}"


def clamp(value, minimum, maximum):

    return max(
        minimum,
        min(maximum, value)
    )


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

            data = http_get(
                url,
                timeout=12
            )

            price = safe_float(
                data.get("lastPrice")
            )

            if price is None:
                raise RuntimeError(
                    "Invalid price"
                )

            return {
                "price": price,
                "change": safe_float(
                    data.get(
                        "priceChangePercent"
                    )
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
            }

        except Exception as e:

            errors.append(
                str(e)
            )

    raise RuntimeError(
        "Binance 24H unavailable: "
        + " | ".join(errors[-2:])
    )


# =========================================================
# BINANCE 4H
# =========================================================

def get_binance_klines(
    symbol,
    interval="4h",
    limit=100
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
                timeout=15
            )

            if not isinstance(
                data,
                list
            ):
                raise RuntimeError(
                    "Invalid kline response"
                )

            if len(data) < 60:
                raise RuntimeError(
                    f"Only {len(data)} candles"
                )

            return {
                "candles": data,
                "source": "Binance",
            }

        except Exception as e:

            errors.append(
                str(e)
            )

    raise RuntimeError(
        "Binance 4H unavailable: "
        + " | ".join(errors[-2:])
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
        timeout=15
    )

    if data.get("error"):
        raise RuntimeError(
            "Kraken: "
            + str(data["error"])
        )

    result = data.get(
        "result",
        {}
    )

    pair_key = None

    for key in result:

        if key != "last":
            pair_key = key
            break

    if not pair_key:
        raise RuntimeError(
            "Kraken pair unavailable"
        )

    raw = result[pair_key]

    if len(raw) < 60:
        raise RuntimeError(
            "Kraken insufficient candles"
        )

    candles = []

    for row in raw:

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
    }


# =========================================================
# COINPAPRIKA
# =========================================================

def get_coinpaprika_price(
    coin_id
):

    url = (
        "https://api.coinpaprika.com/v1/tickers/"
        + urllib.parse.quote(
            coin_id
        )
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
# COINGECKO OPTIONAL
# =========================================================

def get_coingecko_price(
    coin_id
):

    url = (
        "https://api.coingecko.com/api/v3/"
        "simple/price"
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

    coin = data.get(
        coin_id
    )

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
# PRICE CONSENSUS
# =========================================================

def get_price_consensus(
    symbol,
    info
):

    sources = []
    errors = []

    try:

        sources.append(
            get_binance_24h(
                symbol
            )
        )

    except Exception as e:

        errors.append(
            "Binance"
        )

    try:

        sources.append(
            get_coinpaprika_price(
                info["paprika"]
            )
        )

    except Exception:

        errors.append(
            "CoinPaprika"
        )

    try:

        sources.append(
            get_coingecko_price(
                info["gecko"]
            )
        )

    except Exception:

        errors.append(
            "CoinGecko"
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

    prices.sort()

    median = prices[
        len(prices) // 2
    ]

    max_difference = 0

    for price in prices:

        diff = percent_difference(
            price,
            median
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
        "price": median,
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

        open_time = int(
            candles[-1][0]
        )

        now_ms = int(
            datetime.now(
                timezone.utc
            ).timestamp()
            * 1000
        )

        candle_length = (
            4 * 60 * 60 * 1000
        )

        if (
            open_time
            + candle_length
            > now_ms
        ):

            return candles[:-1]

    except Exception:
        pass

    return candles


# =========================================================
# 4H DATA ENGINE
# =========================================================

def get_4h_candles(
    symbol,
    info
):

    try:

        result = get_binance_klines(
            symbol
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
            }

    except Exception:

        pass

    result = get_kraken_ohlc(
        info["kraken"]
    )

    candles = (
        remove_incomplete_last_candle(
            result["candles"]
        )
    )

    if len(candles) < 60:

        raise RuntimeError(
            "4H DATA UNAVAILABLE"
        )

    return {
        "candles": candles,
        "source": "Kraken",
    }


# =========================================================
# CANDLE DATA
# =========================================================

def extract_ohlcv(
    candles
):

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
        volumes
    )


# =========================================================
# EMA
# =========================================================

def ema(
    values,
    period
):

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
# RSI
# =========================================================

def rsi(
    values,
    period=14
):

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
# MACD
# =========================================================

def macd(
    closes
):

    if len(closes) < 35:
        return None, None, None

    ema12 = ema_series(
        closes,
        12
    )

    ema26 = ema_series(
        closes,
        26
    )

    macd_line = []

    start = max(
        len(ema12),
        len(ema26)
    )

    for i in range(
        start
    ):

        if (
            ema12[i] is not None
            and ema26[i] is not None
        ):

            macd_line.append(
                ema12[i]
                - ema26[i]
            )

    if len(macd_line) < 9:

        return (
            None,
            None,
            None
        )

    signal_line = ema(
        macd_line,
        9
    )

    if signal_line is None:
        return (
            None,
            None,
            None
        )

    current_macd = (
        macd_line[-1]
    )

    previous_macd = (
        macd_line[-2]
    )

    histogram = (
        current_macd
        - signal_line
    )

    return (
        current_macd,
        signal_line,
        histogram
    )


def ema_series(
    values,
    period
):

    if len(values) < period:
        return []

    result = [
        None
    ] * (
        period - 1
    )

    current = (
        sum(values[:period])
        / period
    )

    result.append(
        current
    )

    multiplier = (
        2 / (period + 1)
    )

    for value in values[period:]:

        current = (
            (value - current)
            * multiplier
            + current
        )

        result.append(
            current
        )

    return result


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def support_resistance(
    highs,
    lows,
    current
):

    lookback = min(
        30,
        len(highs)
    )

    recent_highs = highs[
        -lookback:
    ]

    recent_lows = lows[
        -lookback:
    ]

    resistance = max(
        recent_highs
    )

    support = min(
        recent_lows
    )

    # Avoid nonsensical levels
    if support >= current:
        support = current * 0.97

    if resistance <= current:
        resistance = current * 1.03

    return support, resistance


# =========================================================
# VOLUME
# =========================================================

def volume_status(
    volumes
):

    if len(volumes) < 21:
        return "UNKNOWN", 0

    current = volumes[-1]

    avg20 = (
        sum(volumes[-21:-1])
        / 20
    )

    if avg20 <= 0:
        return "UNKNOWN", 0

    ratio = (
        current
        / avg20
    )

    if ratio >= 1.50:

        return "STRONG", 2

    if ratio >= 0.90:

        return "NORMAL", 1

    return "WEAK", -1


# =========================================================
# TECHNICAL ENGINE
# =========================================================

def analyze_asset(
    symbol,
    info
):

    market = get_price_consensus(
        symbol,
        info
    )

    candles_info = (
        get_4h_candles(
            symbol,
            info
        )
    )

    (
        opens,
        highs,
        lows,
        closes,
        volumes
    ) = extract_ohlcv(
        candles_info["candles"]
    )

    if len(closes) < 60:

        raise RuntimeError(
            "Insufficient 4H candles"
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

    (
        macd_line,
        macd_signal,
        macd_hist
    ) = macd(
        closes
    )

    support, resistance = (
        support_resistance(
            highs,
            lows,
            current
        )
    )

    vol_state, vol_score = (
        volume_status(
            volumes
        )
    )

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    trend_score = 0

    if (
        ema20 is not None
        and current > ema20
    ):
        trend_score += 2

    else:
        trend_score -= 2

    if (
        ema50 is not None
        and current > ema50
    ):
        trend_score += 2

    else:
        trend_score -= 2

    if (
        ema20 is not None
        and ema50 is not None
        and ema20 > ema50
    ):
        trend_score += 2

    else:
        trend_score -= 2

    if trend_score >= 4:

        trend = "🟢 BULLISH"

    elif trend_score <= -4:

        trend = "🔴 BEARISH"

    else:

        trend = "🟡 MIXED"

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    rsi_score = 0

    if rsi14 is not None:

        if 50 <= rsi14 < 68:
            rsi_score = 2

        elif 68 <= rsi14 < 72:
            rsi_score = 1

        elif rsi14 >= 72:
            rsi_score = -1

        elif 40 <= rsi14 < 50:
            rsi_score = -1

        elif rsi14 < 40:
            rsi_score = -2

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    macd_score = 0

    if (
        macd_line is not None
        and macd_signal is not None
    ):

        if macd_line > macd_signal:

            macd_score = 2

            macd_state = (
                "🟢 BULLISH"
            )

        else:

            macd_score = -2

            macd_state = (
                "🔴 BEARISH"
            )

    else:

        macd_state = "⚪ UNKNOWN"

    # -----------------------------------------------------
    # PRICE LOCATION
    # -----------------------------------------------------

    range_size = (
        resistance - support
    )

    if range_size > 0:

        position = (
            current - support
        ) / range_size

    else:

        position = 0.5

    position = clamp(
        position,
        0,
        1
    )

    # -----------------------------------------------------
    # BREAKOUT
    # -----------------------------------------------------

    breakout = False

    if (
        current > resistance
        and vol_state == "STRONG"
    ):
        breakout = True

    # -----------------------------------------------------
    # DISTANCE TO RESISTANCE
    # -----------------------------------------------------

    if resistance > current:

        resistance_distance = (
            resistance - current
        ) / current * 100

    else:

        resistance_distance = 0

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

    score = (
        trend_score
        + rsi_score
        + macd_score
        + vol_score
    )

    # -----------------------------------------------------
    # BASE CONFIDENCE
    # -----------------------------------------------------

    confidence = 50

    if trend_score >= 4:
        confidence += 10

    elif trend_score <= -4:
        confidence += 10

    if macd_score != 0:
        confidence += 10

    if vol_score >= 1:
        confidence += 5

    if market[
        "confidence"
    ] == "HIGH":

        confidence += 10

    elif market[
        "confidence"
    ] == "MEDIUM":

        confidence += 5

    if breakout:
        confidence += 10

    if (
        market[
            "confidence"
        ] == "LOW"
    ):

        confidence -= 25

    confidence = int(
        clamp(
            confidence,
            20,
            95
        )
    )

    # -----------------------------------------------------
    # DATA PROTECTION
    # -----------------------------------------------------

    data_conflict = (
        market[
            "max_difference"
        ]
    )

    data_reliable = (
        data_conflict <= 1.50
    )

    # -----------------------------------------------------
    # ACTION ENGINE
    # -----------------------------------------------------

    action = "⚪ NO TRADE"

    # Hard protection:
    # bad data = no trade

    if not data_reliable:

        action = (
            "⚪ NO TRADE"
        )

    elif score >= 7:

        # Strong trend but too close
        # to resistance => confirmation.

        if (
            resistance_distance <= 2
            and not breakout
        ):

            action = (
                "🟡 BUY ON CONFIRMATION"
            )

        elif (
            vol_state == "WEAK"
            and not breakout
        ):

            action = (
                "🟡 WATCH"
            )

        elif (
            rsi14 is not None
            and rsi14 >= 72
        ):

            action = (
                "🟡 WATCH"
            )

        else:

            action = "🟢 BUY"

    elif score >= 4:

        action = "🟡 WATCH"

    elif score <= -7:

        action = "🔴 SELL / SHORT"

    elif score <= -4:

        action = "🔴 SELL WATCH"

    else:

        action = "⚪ NO TRADE"

    # -----------------------------------------------------
    # ENTRY / STOP / TARGETS
    # -----------------------------------------------------

    entry = current

    stop = None
    tp1 = None
    tp2 = None
    rr = None

    if action in (
        "🟢 BUY",
        "🟡 BUY ON CONFIRMATION",
        "🟡 WATCH"
    ):

        # Conservative stop:
        # below support with 0.5% buffer

        stop = (
            support * 0.995
        )

        risk = (
            entry - stop
        )

        if risk > 0:

            tp1 = entry + (
                risk * 1.5
            )

            tp2 = entry + (
                risk * 2.5
            )

            rr = (
                (tp2 - entry)
                / risk
            )

    return {
        "market": market,
        "technical_source":
            candles_info["source"],
        "current": current,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "macd_state": macd_state,
        "trend": trend,
        "volume": vol_state,
        "score": score,
        "confidence": confidence,
        "support": support,
        "resistance": resistance,
        "breakout": breakout,
        "resistance_distance":
            resistance_distance,
        "action": action,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rr": rr,
    }


# =========================================================
# DATA QUALITY
# =========================================================

def data_quality(
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
        ] == "Binance"
    ):

        return "🟢 HIGH"

    if market[
        "confidence"
    ] == "MEDIUM":

        return "🟡 MEDIUM"

    return "🟠 LOW"


# =========================================================
# BTC MARKET REGIME
# =========================================================

def get_btc_regime():

    try:

        btc = analyze_asset(
            "BTCUSDT",
            WATCHLIST[
                "BTCUSDT"
            ]
        )

        score = btc[
            "score"
        ]

        if score >= 4:

            return (
                "🟢 BULLISH",
                score
            )

        if score <= -4:

            return (
                "🔴 BEARISH",
                score
            )

        return (
            "🟡 NEUTRAL",
            score
        )

    except Exception:

        return (
            "⚪ UNKNOWN",
            0
        )


# =========================================================
# TELEGRAM REPORT
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
        "🤖 ATLAS AI — SNIPER v4"
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

    # -----------------------------------------------------
    # BTC REGIME
    # -----------------------------------------------------

    btc_regime, btc_score = (
        get_btc_regime()
    )

    lines.append(
        f"🌎 BTC REGIME: "
        f"{btc_regime}"
    )

    lines.append("")

    # -----------------------------------------------------
    # COUNTERS
    # -----------------------------------------------------

    buy = 0
    confirmation = 0
    watch = 0
    no_trade = 0
    sell = 0
    unavailable = 0

    results = {}

    # -----------------------------------------------------
    # ASSETS
    # -----------------------------------------------------

    for symbol, info in (
        WATCHLIST.items()
    ):

        name = info[
            "name"
        ]

        try:

            analysis = analyze_asset(
                symbol,
                info
            )

            results[symbol] = analysis

            market = analysis[
                "market"
            ]

            action = analysis[
                "action"
            ]

            if action == "🟢 BUY":
                buy += 1

            elif action == (
                "🟡 BUY ON CONFIRMATION"
            ):
                confirmation += 1

            elif action == "🟡 WATCH":
                watch += 1

            elif action == (
                "🔴 SELL / SHORT"
            ):
                sell += 1

            else:
                no_trade += 1

            source_names = [
                x["source"]
                for x in market[
                    "sources"
                ]
            ]

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

            if change is not None:

                lines.append(
                    f"24H: "
                    f"{change:+.2f}%"
                )

            lines.append(
                f"Trend: "
                f"{analysis['trend']}"
            )

            if analysis[
                "rsi"
            ] is not None:

                lines.append(
                    f"RSI14: "
                    f"{analysis['rsi']:.1f}"
                )

            lines.append(
                f"MACD: "
                f"{analysis['macd_state']}"
            )

            lines.append(
                f"Volume: "
                f"{analysis['volume']}"
            )

            lines.append(
                f"4H Score: "
                f"{analysis['score']:+d}"
            )

            lines.append(
                f"Confidence: "
                f"{analysis['confidence']}%"
            )

            lines.append(
                "Support: "
                + format_price(
                    analysis[
                        "support"
                    ]
                )
            )

            lines.append(
                "Resistance: "
                + format_price(
                    analysis[
                        "resistance"
                    ]
                )
            )

            if analysis[
                "breakout"
            ]:

                lines.append(
                    "🚀 BREAKOUT: CONFIRMED"
                )

            if action in (
                "🟢 BUY",
                "🟡 BUY ON CONFIRMATION",
                "🟡 WATCH"
            ):

                lines.append(
                    "Entry: "
                    + format_price(
                        analysis[
                            "entry"
                        ]
                    )
                )

                if analysis[
                    "stop"
                ] is not None:

                    lines.append(
                        "SL: "
                        + format_price(
                            analysis[
                                "stop"
                            ]
                        )
                    )

                if analysis[
                    "tp1"
                ] is not None:

                    lines.append(
                        "TP1: "
                        + format_price(
                            analysis[
                                "tp1"
                            ]
                        )
                    )

                if analysis[
                    "tp2"
                ] is not None:

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
                        f"R:R: "
                        f"1:{analysis['rr']:.1f}"
                    )

            lines.append(
                f"🎯 ACTION: {action}"
            )

            lines.append(
                f"Data: "
                f"{data_quality(analysis)}"
            )

            lines.append(
                "Sources: "
                + (
                    ", ".join(
                        source_names
                    )
                    if source_names
                    else "None"
                )
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

            if len(reason) > 180:

                reason = (
                    reason[:180]
                    + "..."
                )

            lines.append(
                f"Reason: {reason}"
            )

            lines.append("")

    # -----------------------------------------------------
    # MARKET SUMMARY
    # -----------------------------------------------------

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    if buy > 0:

        market_bias = (
            "🟢 ACTIVE BUY SETUPS"
        )

    elif confirmation > 0:

        market_bias = (
            "🟡 BUY CONFIRMATION ZONE"
        )

    elif (
        watch > 0
        and sell == 0
    ):

        market_bias = (
            "🟡 WATCHLIST MODE"
        )

    elif sell > 0:

        market_bias = (
            "🔴 RISK-OFF / BEARISH"
        )

    else:

        market_bias = (
            "⚪ NO TRADE ENVIRONMENT"
        )

    lines.append(
        f"MARKET STATUS: "
        f"{market_bias}"
    )

    lines.append(
        f"🟢 BUY: {buy}"
    )

    lines.append(
        f"🟡 BUY CONFIRMATION: "
        f"{confirmation}"
    )

    lines.append(
        f"🟡 WATCH: {watch}"
    )

    lines.append(
        f"⚪ NO TRADE: {no_trade}"
    )

    lines.append(
        f"🔴 SELL/SHORT: {sell}"
    )

    lines.append(
        f"⚫ DATA UNAVAILABLE: "
        f"{unavailable}/{len(WATCHLIST)}"
    )

    lines.append("")

    if unavailable > 0:

        lines.append(
            "⚠️ DATA ENGINE: "
            "PARTIAL / DEGRADED"
        )

        lines.append(
            "No-trade protection is ACTIVE."
        )

    else:

        lines.append(
            "🟢 DATA ENGINE: "
            "ALL ASSETS AVAILABLE"
        )

    lines.append("")

    lines.append(
        "🎯 ATLAS SNIPER v4: ACTIVE"
    )

    lines.append("")

    lines.append(
        "⚠️ v4 separates trend from "
        "actual entry. BUY requires "
        "technical confirmation and "
        "acceptable risk."
    )

    return "\n".join(
        lines
    )


# =========================================================
# TELEGRAM
# =========================================================

def send_message(
    chat_id,
    text
):

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_TOKEN missing"
        )

    if not chat_id:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID missing"
        )

    # Telegram limit
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
        "🤖 ATLAS AI — SNIPER v4"
    )

    print(
        "================================"
    )

    if not TOKEN:

        print(
            "ERROR: "
            "TELEGRAM_TOKEN missing."
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
                "TELEGRAM_CHAT_ID missing."
            )

            return 1

        send_message(
            chat_id,
            report
        )

        print(
            "✅ ATLAS v4 report sent."
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
