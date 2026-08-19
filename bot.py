import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# ============================================================
# ATLAS AI v6
# SNIPER + CORE RADAR + TOP 30 MARKET RADAR
# ============================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

COINGECKO_API_KEY = os.environ.get(
    "COINGECKO_API_KEY", ""
).strip()

COINMARKETCAP_API_KEY = os.environ.get(
    "COINMARKETCAP_API_KEY", ""
).strip()


# ============================================================
# ATLAS CORE
# These assets NEVER disappear from the ATLAS radar
# ============================================================

CORE_ASSETS = [
    "BTC",
    "ETH",
    "XRP",
    "SOL",
    "BNB",
    "DOGE",
    "ADA",
    "TRX",
    "LINK",
    "XLM",
    "SUI",
    "AVAX",
    "LTC",
    "SHIB",
    "HBAR",
    "DOT",
    "BCH",
    "XMR",
    "NEAR",
    "ONDO",
    "TAO",
    "QNT",
    "GRT",
    "TON",
    "UNI",
    "ETHFI",
]


# ============================================================
# Stablecoins / unsuitable assets excluded from dynamic Top 30
# ============================================================

EXCLUDED_SYMBOLS = {
    "USDT",
    "USDC",
    "DAI",
    "USDE",
    "FDUSD",
    "USDS",
    "TUSD",
    "USDD",
    "PYUSD",
    "BUSD",
    "FRAX",
    "LUSD",
    "GUSD",
    "USD0",
    "EURC",
    "WBTC",
    "WETH",
}


# ============================================================
# Binance endpoints
# ============================================================

BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]


# ============================================================
# Known CoinGecko IDs
# Dynamic Top 30 assets without an ID use other sources.
# ============================================================

GECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "SOL": "solana",
    "BNB": "binancecoin",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "TRX": "tron",
    "LINK": "chainlink",
    "XLM": "stellar",
    "SUI": "sui",
    "AVAX": "avalanche-2",
    "LTC": "litecoin",
    "SHIB": "shiba-inu",
    "HBAR": "hedera-hashgraph",
    "DOT": "polkadot",
    "BCH": "bitcoin-cash",
    "XMR": "monero",
    "NEAR": "near",
    "ONDO": "ondo-finance",
    "TAO": "bittensor",
    "QNT": "quant",
    "GRT": "the-graph",
    "TON": "the-open-network",
    "UNI": "uniswap",
    "ETHFI": "ether-fi",
}


# ============================================================
# HTTP
# ============================================================

def http_get(url, timeout=15, headers=None):

    request_headers = {
        "User-Agent": "ATLAS-AI/6.0",
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

        raw = response.read().decode(
            "utf-8"
        )

        if status < 200 or status >= 300:
            raise RuntimeError(
                f"HTTP {status}"
            )

        return json.loads(raw)


# ============================================================
# HELPERS
# ============================================================

def safe_float(value):

    try:
        return float(value)

    except Exception:
        return None


def clamp(value, low, high):

    return max(
        low,
        min(high, value)
    )


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


def symbol_to_binance(symbol):

    return symbol.upper() + "USDT"


# ============================================================
# COINPAPRIKA TOP MARKET
# ============================================================

def get_coinpaprika_top_market():

    url = (
        "https://api.coinpaprika.com/v1/tickers"
        "?quotes=USD"
        "&limit=50"
    )

    data = http_get(
        url,
        timeout=20
    )

    if not isinstance(data, list):
        raise RuntimeError(
            "Invalid CoinPaprika ticker response"
        )

    result = []

    for item in data:

        symbol = str(
            item.get("symbol", "")
        ).upper()

        if not symbol:
            continue

        if symbol in EXCLUDED_SYMBOLS:
            continue

        quotes = item.get(
            "quotes",
            {}
        )

        usd = quotes.get(
            "USD",
            {}
        )

        price = safe_float(
            usd.get("price")
        )

        change = safe_float(
            usd.get("percent_change_24h")
        )

        market_cap = safe_float(
            usd.get("market_cap")
        )

        rank = item.get(
            "rank"
        )

        if price is None:
            continue

        result.append({
            "symbol": symbol,
            "name": item.get(
                "name",
                symbol
            ),
            "rank": rank,
            "price": price,
            "change": change,
            "market_cap": market_cap,
            "source": "CoinPaprika",
        })

        if len(result) >= 30:
            break

    return result


# ============================================================
# BINANCE 24H
# ============================================================

def get_binance_24h(symbol):

    errors = []

    for host in BINANCE_HOSTS:

        try:

            url = (
                f"{host}/api/v3/ticker/24hr"
                f"?symbol="
                f"{urllib.parse.quote(symbol)}"
            )

            data = http_get(
                url,
                timeout=12
            )

            price = safe_float(
                data.get(
                    "lastPrice"
                )
            )

            if price is None:
                raise RuntimeError(
                    "Invalid Binance price"
                )

            return {
                "price": price,
                "change": safe_float(
                    data.get(
                        "priceChangePercent"
                    )
                ),
                "high": safe_float(
                    data.get(
                        "highPrice"
                    )
                ),
                "low": safe_float(
                    data.get(
                        "lowPrice"
                    )
                ),
                "volume": safe_float(
                    data.get(
                        "quoteVolume"
                    )
                ),
                "source": "Binance",
                "endpoint": host,
            }

        except Exception as e:

            errors.append(
                f"{host}: {str(e)}"
            )

    raise RuntimeError(
        "Binance unavailable | "
        + " | ".join(
            errors[-3:]
        )
    )


# ============================================================
# BINANCE 4H
# ============================================================

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
                f"?symbol="
                f"{urllib.parse.quote(symbol)}"
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
                "endpoint": host,
            }

        except Exception as e:

            errors.append(
                f"{host}: {str(e)}"
            )

    raise RuntimeError(
        "Binance 4H unavailable | "
        + " | ".join(
            errors[-4:]
        )
    )


# ============================================================
# REMOVE INCOMPLETE CANDLE
# ============================================================

def remove_incomplete_candle(
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
            ).timestamp()
            * 1000
        )

        candle_length = (
            4
            * 60
            * 60
            * 1000
        )

        close_time = (
            last_open
            + candle_length
        )

        if close_time > now_ms:
            return candles[:-1]

    except Exception:
        pass

    return candles


# ============================================================
# COINGECKO
# ============================================================

def get_coingecko_price(
    symbol
):

    coin_id = GECKO_IDS.get(
        symbol
    )

    if not coin_id:
        raise RuntimeError(
            "CoinGecko ID unavailable"
        )

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
        coin.get(
            "usd_24h_change"
        )
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


# ============================================================
# COINMARKETCAP
# Optional
# ============================================================

def get_cmc_price(
    symbol
):

    if not COINMARKETCAP_API_KEY:
        raise RuntimeError(
            "CMC API key not configured"
        )

    url = (
        "https://pro-api.coinmarketcap.com/"
        "v2/cryptocurrency/quotes/latest"
        f"?symbol={urllib.parse.quote(symbol)}"
        "&convert=USD"
    )

    headers = {
        "X-CMC_PRO_API_KEY":
            COINMARKETCAP_API_KEY
    }

    data = http_get(
        url,
        timeout=15,
        headers=headers
    )

    records = data.get(
        "data",
        {}
    )

    item = None

    if isinstance(
        records,
        dict
    ):

        value = records.get(
            symbol
        )

        if isinstance(
            value,
            list
        ) and value:

            item = value[0]

        elif isinstance(
            value,
            dict
        ):

            item = value

    if not item:

        raise RuntimeError(
            "CMC asset unavailable"
        )

    quote = (
        item
        .get(
            "quote",
            {}
        )
        .get(
            "USD",
            {}
        )
    )

    price = safe_float(
        quote.get(
            "price"
        )
    )

    change = safe_float(
        quote.get(
            "percent_change_24h"
        )
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


# ============================================================
# PRICE CONSENSUS
# ============================================================

def get_price_consensus(
    symbol,
    paprika_item=None
):

    sources = []
    errors = []

    # Binance
    try:

        sources.append(
            get_binance_24h(
                symbol_to_binance(
                    symbol
                )
            )
        )

    except Exception as e:

        errors.append(
            "Binance: "
            + str(e)
        )

    # CoinPaprika
    if paprika_item:

        sources.append({
            "price":
                paprika_item["price"],
            "change":
                paprika_item["change"],
            "source":
                "CoinPaprika",
        })

    # CoinGecko
    try:

        sources.append(
            get_coingecko_price(
                symbol
            )
        )

    except Exception as e:

        errors.append(
            "CoinGecko: "
            + str(e)
        )

    # CoinMarketCap
    if COINMARKETCAP_API_KEY:

        try:

            sources.append(
                get_cmc_price(
                    symbol
                )
            )

        except Exception as e:

            errors.append(
                "CMC: "
                + str(e)
            )

    prices = [
        x["price"]
        for x in sources
        if x.get("price") is not None
    ]

    if not prices:

        raise RuntimeError(
            "NO VALID PRICE SOURCE"
        )

    sorted_prices = sorted(
        prices
    )

    middle = len(
        sorted_prices
    ) // 2

    if len(sorted_prices) % 2:

        median = sorted_prices[
            middle
        ]

    else:

        median = (
            sorted_prices[
                middle - 1
            ]
            + sorted_prices[
                middle
            ]
        ) / 2

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

    # Hard data gates
    if max_difference <= 0.75:

        confidence = "HIGH"

    elif max_difference <= 1.50:

        confidence = "MEDIUM"

    elif max_difference <= 3.00:

        confidence = "LOW"

    else:

        confidence = "INVALID"

    return {
        "price": median,
        "sources": sources,
        "errors": errors,
        "confidence":
            confidence,
        "max_difference":
            max_difference,
    }


# ============================================================
# TECHNICAL HELPERS
# ============================================================

def closes_from_candles(
    candles
):

    return [
        float(c[4])
        for c in candles
    ]


def volumes_from_candles(
    candles
):

    return [
        float(c[5])
        for c in candles
    ]


def ema(
    values,
    period
):

    if len(values) < period:
        return None

    multiplier = (
        2
        / (period + 1)
    )

    result = (
        sum(
            values[:period]
        )
        / period
    )

    for value in values[period:]:

        result = (
            (
                value
                - result
            )
            * multiplier
            + result
        )

    return result


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

            gains.append(
                change
            )

            losses.append(0)

        else:

            gains.append(0)

            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(
            gains[:period]
        )
        / period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
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


# ============================================================
# MACD
# ============================================================

def macd(
    values
):

    if len(values) < 35:
        return None

    ema12_series = []
    ema26_series = []

    def ema_series(
        data,
        period
    ):

        if len(data) < period:
            return []

        multiplier = (
            2
            / (period + 1)
        )

        result = (
            sum(
                data[:period]
            )
            / period
        )

        output = [
            result
        ]

        for value in data[period:]:

            result = (
                (
                    value
                    - result
                )
                * multiplier
                + result
            )

            output.append(
                result
            )

        return output

    e12 = ema_series(
        values,
        12
    )

    e26 = ema_series(
        values,
        26
    )

    if not e12 or not e26:
        return None

    # Align final EMA values
    offset = (
        len(e12)
        - len(e26)
    )

    e12_aligned = e12[
        offset:
    ]

    macd_line = [
        a - b
        for a, b
        in zip(
            e12_aligned,
            e26
        )
    ]

    if len(macd_line) < 9:
        return None

    signal_line = ema(
        macd_line,
        9
    )

    if signal_line is None:
        return None

    histogram = (
        macd_line[-1]
        - signal_line
    )

    return {
        "line":
            macd_line[-1],
        "signal":
            signal_line,
        "histogram":
            histogram,
        "bullish":
            macd_line[-1]
            > signal_line,
    }


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def support_resistance(
    candles,
    lookback=30
):

    recent = candles[
        -lookback:
    ]

    highs = [
        float(c[2])
        for c in recent
    ]

    lows = [
        float(c[3])
        for c in recent
    ]

    if not highs or not lows:

        return None, None

    resistance = max(
        highs
    )

    support = min(
        lows
    )

    return support, resistance


# ============================================================
# VOLUME ANALYSIS
# ============================================================

def volume_state(
    candles
):

    volumes = volumes_from_candles(
        candles
    )

    if len(volumes) < 21:
        return "UNKNOWN", 0

    current = volumes[-1]

    average = (
        sum(
            volumes[-21:-1]
        )
        / 20
    )

    if average <= 0:
        return "UNKNOWN", 0

    ratio = (
        current
        / average
    )

    if ratio >= 1.50:

        return "🟢 STRONG", ratio

    if ratio >= 1.05:

        return "🟡 NORMAL", ratio

    return "🔴 WEAK", ratio


# ============================================================
# TREND
# ============================================================

def trend_state(
    current,
    ema20_value,
    ema50_value
):

    if (
        ema20_value is None
        or ema50_value is None
    ):

        return "🟡 MIXED"

    if (
        current > ema20_value
        and ema20_value > ema50_value
    ):

        return "🟢 BULLISH"

    if (
        current < ema20_value
        and ema20_value < ema50_value
    ):

        return "🔴 BEARISH"

    return "🟡 MIXED"


# ============================================================
# TECHNICAL ANALYSIS
# ============================================================

def analyze_asset(
    symbol,
    paprika_item=None
):

    market = get_price_consensus(
        symbol,
        paprika_item
    )

    kline = get_binance_klines(
        symbol_to_binance(
            symbol
        ),
        "4h",
        100
    )

    candles = remove_incomplete_candle(
        kline["candles"]
    )

    if len(candles) < 60:

        raise RuntimeError(
            "INSUFFICIENT 4H DATA"
        )

    closes = closes_from_candles(
        candles
    )

    current = closes[-1]

    ema20_value = ema(
        closes,
        20
    )

    ema50_value = ema(
        closes,
        50
    )

    rsi_value = rsi(
        closes,
        14
    )

    macd_value = macd(
        closes
    )

    volume_label, volume_ratio = (
        volume_state(
            candles
        )
    )

    trend = trend_state(
        current,
        ema20_value,
        ema50_value
    )

    support, resistance = (
        support_resistance(
            candles,
            30
        )
    )

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    # Trend
    if trend == "🟢 BULLISH":
        score += 3

    elif trend == "🔴 BEARISH":
        score -= 3

    # Price / EMA20
    if (
        ema20_value
        and current > ema20_value
    ):

        score += 1

    elif ema20_value:

        score -= 1

    # EMA20 / EMA50
    if (
        ema20_value
        and ema50_value
    ):

        if ema20_value > ema50_value:

            score += 2

        else:

            score -= 2

    # RSI
    if rsi_value is not None:

        if 52 <= rsi_value < 68:

            score += 1

        elif 68 <= rsi_value < 75:

            score += 0

        elif rsi_value >= 75:

            score -= 1

        elif 45 <= rsi_value < 52:

            score += 0

        elif 30 < rsi_value < 45:

            score -= 1

        elif rsi_value <= 30:

            score += 1

    # MACD
    if macd_value:

        if macd_value["bullish"]:

            score += 2

        else:

            score -= 2

    # Volume
    if volume_label == "🟢 STRONG":

        score += 2

    elif volume_label == "🟡 NORMAL":

        score += 1

    elif volume_label == "🔴 WEAK":

        score -= 1

    # ========================================================
    # STRUCTURE
    # ========================================================

    breakout = False
    pullback = False

    if resistance:

        breakout = (
            current > resistance
        )

    if support:

        distance_to_support = (
            abs(current - support)
            / current
            * 100
        )

        pullback = (
            distance_to_support <= 2.0
            and trend
            == "🟢 BULLISH"
        )

    # ========================================================
    # DATA QUALITY
    # ========================================================

    conflict = market[
        "max_difference"
    ]

    confidence = 100

    if market[
        "confidence"
    ] == "HIGH":

        confidence -= 0

    elif market[
        "confidence"
    ] == "MEDIUM":

        confidence -= 15

    elif market[
        "confidence"
    ] == "LOW":

        confidence -= 30

    else:

        confidence -= 50

    if volume_label == "🔴 WEAK":

        confidence -= 10

    if trend == "🟡 MIXED":

        confidence -= 10

    if not macd_value:

        confidence -= 15

    if conflict > 1.5:

        confidence -= 10

    if conflict > 3:

        confidence -= 20

    confidence = int(
        clamp(
            confidence,
            0,
            100
        )
    )

    # ========================================================
    # HARD DATA GATE
    # ========================================================

    data_trade_allowed = True

    if market[
        "confidence"
    ] in [
        "LOW",
        "INVALID"
    ]:

        data_trade_allowed = False

    if conflict > 3:

        data_trade_allowed = False

    # ========================================================
    # ENTRY ENGINE
    # ========================================================

    entry = None
    sl = None
    tp1 = None
    tp2 = None
    rr = None

    action = "⚪ NO TRADE"

    confirmation_reason = []

    # Bullish setup
    bullish_setup = (
        trend == "🟢 BULLISH"
        and macd_value
        and macd_value["bullish"]
        and rsi_value is not None
        and 50 <= rsi_value < 70
        and score >= 6
    )

    # Strong confirmation
    confirmed_breakout = (
        bullish_setup
        and breakout
        and volume_label
        in [
            "🟢 STRONG",
            "🟡 NORMAL"
        ]
        and data_trade_allowed
    )

    if confirmed_breakout:

        entry = current

        if support:

            sl = support * 0.995

        else:

            sl = current * 0.95

        risk = (
            entry - sl
        )

        if risk > 0:

            tp1 = (
                entry
                + risk * 2
            )

            tp2 = (
                entry
                + risk * 3
            )

            rr = 3.0

        if rr and rr >= 2:

            action = "🟢 BUY"

    # Potential breakout
    elif bullish_setup:

        if not data_trade_allowed:

            action = (
                "⚫ NO TRADE — DATA"
            )

        elif not breakout:

            action = (
                "🟡 BUY ON CONFIRMATION"
            )

            if resistance:

                confirmation_reason.append(
                    "4H close above resistance"
                )

            if volume_label == "🔴 WEAK":

                confirmation_reason.append(
                    "volume confirmation"
                )

        else:

            action = (
                "🟡 WAIT — VOLUME"
            )

            confirmation_reason.append(
                "volume confirmation"
            )

    # Bearish setup
    bearish_setup = (
        trend == "🔴 BEARISH"
        and score <= -5
    )

    if bearish_setup:

        if data_trade_allowed:

            action = "🔴 SELL WATCH"

        else:

            action = (
                "⚫ NO TRADE — DATA"
            )

    # ========================================================
    # Pullback watch
    # ========================================================

    if (
        action == "🟡 BUY ON CONFIRMATION"
        and pullback
        and not breakout
    ):

        action = "🟡 PULLBACK WATCH"

    return {
        "symbol": symbol,
        "market": market,
        "candles": candles,
        "current": current,
        "ema20": ema20_value,
        "ema50": ema50_value,
        "rsi": rsi_value,
        "macd": macd_value,
        "volume": volume_label,
        "volume_ratio": volume_ratio,
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "score": score,
        "confidence": confidence,
        "breakout": breakout,
        "pullback": pullback,
        "action": action,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr": rr,
        "confirmation_reason":
            confirmation_reason,
        "technical_source":
            kline["source"],
    }


# ============================================================
# BTC MARKET REGIME
# ============================================================

def get_btc_regime(
    paprika_map
):

    try:

        analysis = analyze_asset(
            "BTC",
            paprika_map.get(
                "BTC"
            )
        )

        score = analysis[
            "score"
        ]

        trend = analysis[
            "trend"
        ]

        if (
            trend == "🟢 BULLISH"
            and score >= 5
        ):

            return "🟢 BULLISH"

        if (
            trend == "🔴 BEARISH"
            and score <= -5
        ):

            return "🔴 BEARISH"

        return "🟡 MIXED"

    except Exception:

        return "⚪ UNKNOWN"


# ============================================================
# ACTION PRIORITY
# ============================================================

def action_priority(
    action
):

    priorities = {
        "🟢 BUY": 100,
        "🟡 BUY ON CONFIRMATION": 80,
        "🟡 PULLBACK WATCH": 75,
        "🟡 WAIT — VOLUME": 70,
        "🟡 WATCH": 60,
        "🔴 SELL WATCH": 50,
        "⚪ NO TRADE": 10,
        "⚫ NO TRADE — DATA": 0,
    }

    return priorities.get(
        action,
        0
    )


# ============================================================
# REPORT
# ============================================================

def atlas_report():

    tehran = ZoneInfo(
        "Asia/Tehran"
    )

    now = datetime.now(
        tehran
    )

    # ========================================================
    # TOP 30
    # ========================================================

    top30 = []

    try:

        top30 = (
            get_coinpaprika_top_market()
        )

    except Exception as e:

        print(
            "Top30 error:",
            str(e)
        )

    top30_symbols = [
        x["symbol"]
        for x in top30
    ]

    paprika_map = {
        x["symbol"]: x
        for x in top30
    }

    # ========================================================
    # UNIVERSE
    # ========================================================

    universe = []

    for symbol in CORE_ASSETS:

        if symbol not in universe:

            universe.append(
                symbol
            )

    for symbol in top30_symbols:

        if symbol not in universe:

            universe.append(
                symbol
            )

    # ========================================================
    # HEADER
    # ========================================================

    lines = []

    lines.append(
        "🤖 ATLAS AI — SNIPER v6"
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

    btc_regime = get_btc_regime(
        paprika_map
    )

    lines.append(
        "🌎 BTC REGIME: "
        + btc_regime
    )

    lines.append("")

    lines.append(
        f"📡 UNIVERSE: "
        f"{len(universe)} assets"
    )

    lines.append(
        f"⭐ CORE: "
        f"{len(CORE_ASSETS)}"
    )

    lines.append(
        f"🏆 TOP 30: "
        f"{len(top30)}"
    )

    lines.append("")

    # ========================================================
    # ANALYSIS
    # ========================================================

    analyses = []
    unavailable = []

    for symbol in universe:

        try:

            result = analyze_asset(
                symbol,
                paprika_map.get(
                    symbol
                )
            )

            analyses.append(
                result
            )

        except Exception as e:

            unavailable.append({
                "symbol": symbol,
                "reason": str(e)
            })

    # ========================================================
    # TOP OPPORTUNITIES
    # ========================================================

    opportunities = [
        x
        for x in analyses
        if x["action"]
        in [
            "🟢 BUY",
            "🟡 BUY ON CONFIRMATION",
            "🟡 PULLBACK WATCH",
            "🟡 WAIT — VOLUME",
            "🔴 SELL WATCH",
        ]
    ]

    opportunities.sort(
        key=lambda x: (
            action_priority(
                x["action"]
            ),
            x["confidence"],
            abs(x["score"])
        ),
        reverse=True
    )

    lines.append(
        "🔥 TOP ATLAS OPPORTUNITIES"
    )

    if not opportunities:

        lines.append(
            "No high-quality setup."
        )

    else:

        for item in opportunities[:8]:

            lines.append(
                f"{item['symbol']} "
                f"{item['action']} "
                f"| Score "
                f"{item['score']:+d} "
                f"| Conf "
                f"{item['confidence']}%"
            )

    lines.append("")

    # ========================================================
    # MARKET STATISTICS
    # ========================================================

    bullish = sum(
        1
        for x in analyses
        if x["score"] >= 5
    )

    bearish = sum(
        1
        for x in analyses
        if x["score"] <= -5
    )

    buy_count = sum(
        1
        for x in analyses
        if x["action"]
        == "🟢 BUY"
    )

    confirmation_count = sum(
        1
        for x in analyses
        if x["action"]
        in [
            "🟡 BUY ON CONFIRMATION",
            "🟡 PULLBACK WATCH",
            "🟡 WAIT — VOLUME",
        ]
    )

    sell_count = sum(
        1
        for x in analyses
        if x["action"]
        == "🔴 SELL WATCH"
    )

    no_trade = sum(
        1
        for x in analyses
        if x["action"]
        in [
            "⚪ NO TRADE",
            "⚫ NO TRADE — DATA",
        ]
    )

    if (
        btc_regime
        == "🔴 BEARISH"
    ):

        market_status = (
            "🔴 MARKET DEFENSIVE"
        )

    elif buy_count >= 3:

        market_status = (
            "🟢 MARKET ACTIVE"
        )

    elif confirmation_count >= 3:

        market_status = (
            "🟡 BUY CONFIRMATION ZONE"
        )

    elif bearish > bullish:

        market_status = (
            "🔴 MARKET WEAK"
        )

    else:

        market_status = (
            "🟡 MARKET MIXED"
        )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "MARKET STATUS: "
        + market_status
    )

    lines.append(
        f"🟢 BUY: {buy_count}"
    )

    lines.append(
        f"🟡 CONFIRMATION/WATCH: "
        f"{confirmation_count}"
    )

    lines.append(
        f"⚪ NO TRADE: {no_trade}"
    )

    lines.append(
        f"🔴 SELL WATCH: {sell_count}"
    )

    lines.append(
        f"⚫ DATA UNAVAILABLE: "
        f"{len(unavailable)}/"
        f"{len(universe)}"
    )

    lines.append("")

    # ========================================================
    # DETAILED CORE
    # ========================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "⭐ ATLAS CORE RADAR"
    )

    for symbol in CORE_ASSETS:

        matches = [
            x
            for x in analyses
            if x["symbol"]
            == symbol
        ]

        if not matches:

            lines.append(
                f"{symbol}: ⚫ DATA UNAVAILABLE"
            )

            continue

        x = matches[0]

        lines.append(
            f"{symbol} | "
            f"{x['action']} | "
            f"S{x['score']:+d} | "
            f"RSI "
            f"{x['rsi']:.1f} | "
            f"{x['trend']}"
        )

    lines.append("")

    # ========================================================
    # TOP 30 RADAR
    # ========================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "🏆 TOP 30 MARKET RADAR"
    )

    top_results = []

    for item in top30:

        symbol = item[
            "symbol"
        ]

        matches = [
            x
            for x in analyses
            if x["symbol"]
            == symbol
        ]

        if matches:

            x = matches[0]

            top_results.append(
                (
                    item.get(
                        "rank"
                    ),
                    x
                )
            )

    top_results.sort(
        key=lambda z:
            z[0]
            if z[0]
            else 999
    )

    for rank, x in top_results:

        lines.append(
            f"#{rank} "
            f"{x['symbol']} | "
            f"{x['action']} | "
            f"S{x['score']:+d} | "
            f"RSI "
            f"{x['rsi']:.1f}"
        )

    lines.append("")

    # ========================================================
    # SNIPER DETAILS
    # ========================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "🎯 SNIPER DETAILS"
    )

    sniper_items = [
        x
        for x in analyses
        if x["action"]
        in [
            "🟢 BUY",
            "🟡 BUY ON CONFIRMATION",
            "🟡 PULLBACK WATCH",
            "🔴 SELL WATCH",
        ]
    ]

    sniper_items.sort(
        key=lambda x: (
            action_priority(
                x["action"]
            ),
            x["confidence"],
            abs(x["score"])
        ),
        reverse=True
    )

    for x in sniper_items[:10]:

        lines.append("")

        lines.append(
            f"🔹 {x['symbol']}"
        )

        lines.append(
            "Price: "
            + format_price(
                x["current"]
            )
        )

        lines.append(
            f"Trend: {x['trend']}"
        )

        if x["rsi"] is not None:

            lines.append(
                f"RSI14: "
                f"{x['rsi']:.1f}"
            )

        if x["macd"]:

            macd_state = (
                "🟢 BULLISH"
                if x["macd"]["bullish"]
                else "🔴 BEARISH"
            )

            lines.append(
                f"MACD: "
                f"{macd_state}"
            )

        lines.append(
            f"Volume: "
            f"{x['volume']}"
        )

        lines.append(
            f"4H Score: "
            f"{x['score']:+d}"
        )

        lines.append(
            f"Confidence: "
            f"{x['confidence']}%"
        )

        if x["support"]:

            lines.append(
                "Support: "
                + format_price(
                    x["support"]
                )
            )

        if x["resistance"]:

            lines.append(
                "Resistance: "
                + format_price(
                    x["resistance"]
                )
            )

        if x["breakout"]:

            lines.append(
                "🚀 BREAKOUT: CONFIRMED"
            )

        if x["pullback"]:

            lines.append(
                "↩️ PULLBACK: ACTIVE"
            )

        if x["entry"]:

            lines.append(
                "Entry: "
                + format_price(
                    x["entry"]
                )
            )

        if x["sl"]:

            lines.append(
                "SL: "
                + format_price(
                    x["sl"]
                )
            )

        if x["tp1"]:

            lines.append(
                "TP1: "
                + format_price(
                    x["tp1"]
                )
            )

        if x["tp2"]:

            lines.append(
                "TP2: "
                + format_price(
                    x["tp2"]
                )
            )

        if x["rr"]:

            lines.append(
                f"R:R: 1:{x['rr']:.1f}"
            )

        lines.append(
            "🎯 ACTION: "
            + x["action"]
        )

        if x[
            "confirmation_reason"
        ]:

            lines.append(
                "Trigger: "
                + ", ".join(
                    x[
                        "confirmation_reason"
                    ]
                )
            )

        lines.append(
            "Data: "
            + x["market"][
                "confidence"
            ]
        )

        if x[
            "market"
        ][
            "max_difference"
        ] > 1.5:

            lines.append(
                "⚠️ DATA CONFLICT: "
                f"{x['market']['max_difference']:.2f}%"
            )

    # ========================================================
    # DATA ENGINE
    # ========================================================

    lines.append("")

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "🛡️ ATLAS DATA ENGINE"
    )

    lines.append(
        f"Assets scanned: "
        f"{len(universe)}"
    )

    lines.append(
        f"Successful: "
        f"{len(analyses)}"
    )

    lines.append(
        f"Unavailable: "
        f"{len(unavailable)}"
    )

    lines.append(
        "Data conflict >3% = NO TRADE"
    )

    lines.append(
        "Incomplete 4H candles excluded"
    )

    lines.append("")

    lines.append(
        "🎯 ATLAS SNIPER v6: ACTIVE"
    )

    lines.append("")

    lines.append(
        "⚠️ این گزارش تحلیلی است؛ "
        "سیگنال قطعی نیست و قبل از "
        "معامله باید ریسک کل سبد، "
        "نقدشوندگی و شرایط بازار بررسی شود."
    )

    return "\n".join(
        lines
    )


# ============================================================
# TELEGRAM
# ============================================================

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

    # Telegram safe chunk size
    max_length = 3900

    chunks = []

    while len(text) > max_length:

        cut = text.rfind(
            "\n",
            0,
            max_length
        )

        if cut <= 0:
            cut = max_length

        chunks.append(
            text[:cut]
        )

        text = text[
            cut:
        ].lstrip()

    if text:
        chunks.append(
            text
        )

    for chunk in chunks:

        url = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendMessage"
        )

        data = urllib.parse.urlencode({
            "chat_id":
                str(chat_id),
            "text":
                chunk
        }).encode()

        request = (
            urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type":
                    "application/"
                    "x-www-form-urlencoded"
                }
            )
        )

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            response.read()


# ============================================================
# CHAT ID
# ============================================================

def find_chat_id():

    if CHAT_ID:
        return CHAT_ID

    if not TOKEN:
        return None

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TOKEN}/getUpdates"
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
            "Telegram error:",
            str(e)
        )

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=========================================="
    )

    print(
        "🤖 ATLAS AI v6"
    )

    print(
        "CORE + TOP 30 + SNIPER ENGINE"
    )

    print(
        "=========================================="
    )

    if not TOKEN:

        print(
            "ERROR: TELEGRAM_TOKEN missing"
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
                "ERROR: TELEGRAM_CHAT_ID missing"
            )

            return 1

        send_message(
            chat_id,
            report
        )

        print(
            "✅ ATLAS v6 report sent"
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


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )
