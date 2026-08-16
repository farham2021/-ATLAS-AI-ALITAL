import os
import json
import urllib.request
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo


# =========================================================
# ATLAS AI v2
# GitHub Actions compatible
# No infinite loop
# =========================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BINANCE_HOSTS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

WATCHLIST = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "XRPUSDT": "XRP",
    "SOLUSDT": "SOL",
    "TONUSDT": "TON",
    "UNIUSDT": "UNI",
    "ETHFIUSDT": "ETHFI",
}


# =========================================================
# HTTP
# =========================================================

def http_get(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ATLAS-AI/2.0"
        }
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


# =========================================================
# BINANCE
# =========================================================

def get_24h(symbol):
    last_error = None

    for host in BINANCE_HOSTS:
        try:
            url = (
                f"{host}/api/v3/ticker/24hr"
                f"?symbol={urllib.parse.quote(symbol)}"
            )

            data = http_get(url)

            return {
                "price": float(data["lastPrice"]),
                "change": float(data["priceChangePercent"]),
                "high": float(data["highPrice"]),
                "low": float(data["lowPrice"]),
                "volume": float(data["quoteVolume"]),
            }

        except Exception as e:
            last_error = e

    raise last_error


def get_klines(symbol, interval="4h", limit=60):
    last_error = None

    for host in BINANCE_HOSTS:
        try:
            url = (
                f"{host}/api/v3/klines"
                f"?symbol={urllib.parse.quote(symbol)}"
                f"&interval={interval}"
                f"&limit={limit}"
            )

            return http_get(url)

        except Exception as e:
            last_error = e

    raise last_error


# =========================================================
# TECHNICAL INDICATORS
# =========================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def technical_analysis(symbol):
    candles = get_klines(symbol, "4h", 60)

    closes = [float(candle[4]) for candle in candles]

    current = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi14 = rsi(closes, 14)

    score = 0

    if ema20 and current > ema20:
        score += 1
    else:
        score -= 1

    if ema50 and current > ema50:
        score += 1
    else:
        score -= 1

    if ema20 and ema50:
        if ema20 > ema50:
            score += 2
        else:
            score -= 2

    if rsi14 is not None:
        if 50 <= rsi14 < 70:
            score += 1
        elif rsi14 >= 70:
            score -= 1
        elif 30 < rsi14 < 50:
            score -= 1
        elif rsi14 <= 30:
            score += 1

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
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "score": score,
        "signal": signal,
    }


# =========================================================
# ATLAS REPORT
# =========================================================

def atlas_report():
    lines = []

    tehran = ZoneInfo("Asia/Tehran")
    now = datetime.now(tehran)

    lines.append("🤖 ATLAS AI — SNIPER")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(
        now.strftime("%Y/%m/%d  %H:%M")
        + " 🇮🇷"
    )
    lines.append("Timeframe: 4H")
    lines.append("")

    bullish = 0
    bearish = 0

    for symbol, name in WATCHLIST.items():

        try:
            market = get_24h(symbol)
            tech = technical_analysis(symbol)

            price = market["price"]
            change = market["change"]
            rsi14 = tech["rsi"]
            score = tech["score"]

            if score >= 2:
                bullish += 1

            if score <= -2:
                bearish += 1

            lines.append(f"🔹 {name}")
            lines.append(
                f"Price: ${price:,.4f}"
            )
            lines.append(
                f"24H: {change:+.2f}%"
            )

            if rsi14 is not None:
                lines.append(
                    f"RSI14: {rsi14:.1f}"
                )

            lines.append(
                f"4H Score: {score:+d}"
            )

            lines.append(
                f"Signal: {tech['signal']}"
            )

            lines.append("")

        except Exception as e:
            lines.append(
                f"🔹 {name}: ⚠️ DATA ERROR"
            )
            lines.append("")

    # =====================================================
    # MARKET SUMMARY
    # =====================================================

    if bullish >= 5:
        market_state = "🟢 MARKET BIAS: BULLISH"
    elif bearish >= 5:
        market_state = "🔴 MARKET BIAS: BEARISH"
    elif bullish > bearish:
        market_state = "🟢 MARKET BIAS: SLIGHTLY BULLISH"
    elif bearish > bullish:
        market_state = "🟠 MARKET BIAS: SLIGHTLY BEARISH"
    else:
        market_state = "⚪ MARKET BIAS: NEUTRAL"

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(market_state)
    lines.append(
        f"Bullish: {bullish} | Bearish: {bearish}"
    )
    lines.append("")
    lines.append("🎯 ATLAS SNIPER MODE: ACTIVE")
    lines.append("")
    lines.append(
        "⚠️ این گزارش سیگنال تحلیلی است؛ "
        "تصمیم نهایی خرید/فروش باید با مدیریت ریسک انجام شود."
    )

    return "\n".join(lines)


# =========================================================
# TELEGRAM
# =========================================================

def send_message(chat_id, text):

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN is not configured."
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
# FIND CHAT ID
# =========================================================

def find_chat_id():

    # Preferred method:
    # TELEGRAM_CHAT_ID stored as GitHub Secret

    if CHAT_ID:
        return CHAT_ID

    # Backup method:
    # Find latest Telegram conversation

    if not TOKEN:
        return None

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TOKEN}/getUpdates?timeout=5"
        )

        data = http_get(url, timeout=10)

        updates = data.get("result", [])

        if not updates:
            return None

        for update in reversed(updates):

            message = update.get("message")

            if message:
                chat = message.get("chat")

                if chat and chat.get("id"):
                    return chat["id"]

    except Exception as e:
        print("Telegram update error:", e)

    return None


# =========================================================
# MAIN
# =========================================================

def main():

    print("================================")
    print("🤖 ATLAS AI v2")
    print("================================")

    if not TOKEN:
        print("ERROR: TELEGRAM_TOKEN is missing.")
        return 1

    try:

        report = atlas_report()

        print(report)

        chat_id = find_chat_id()

        if not chat_id:
            print(
                "ERROR: TELEGRAM_CHAT_ID is missing "
                "and no Telegram chat was found."
            )
            return 1

        send_message(
            chat_id,
            report
        )

        print("")
        print("✅ ATLAS report sent successfully.")
        print("ATLAS execution completed.")

        return 0

    except Exception as e:

        print("")
        print("❌ ATLAS ERROR:")
        print(str(e))

        return 1


if __name__ == "__main__":
    raise SystemExit(main())