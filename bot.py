import os
import json
import urllib.request
import urllib.parse
from datetime import datetime

TOKEN = os.environ.get("TELEGRAM_TOKEN")

WATCHLIST = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "XRPUSDT": "XRP",
    "SOLUSDT": "SOL",
    "TONUSDT": "TON",
    "UNIUSDT": "UNI",
    "ETHFIUSDT": "ETHFI"
}

def get_price(symbol):
    url = "https://api.binance.com/api/v3/ticker/24hr?symbol=" + symbol
    with urllib.request.urlopen(url, timeout=10) as response:
        data = json.loads(response.read().decode())
    return float(data["lastPrice"]), float(data["priceChangePercent"])

def atlas_report():
    lines = []
    lines.append("🤖 ATLAS AI — LIVE")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    lines.append("")

    for symbol, name in WATCHLIST.items():
        try:
            price, change = get_price(symbol)

            if change >= 5:
                signal = "🔥 STRONG MOMENTUM"
            elif change >= 2:
                signal = "🟢 BULLISH"
            elif change <= -5:
                signal = "🔴 HIGH RISK"
            elif change <= -2:
                signal = "🟠 WEAK"
            else:
                signal = "⚪ NEUTRAL"

            lines.append(
                f"{name}: ${price:,.4f} | 24H {change:+.2f}%\n"
                f"   {signal}"
            )

        except Exception as e:
            lines.append(f"{name}: ⚠️ DATA ERROR")

        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("ATLAS SNIPER MODE: ACTIVE")
    lines.append("⚠️ سیگنال‌ها تصمیم نهایی خرید/فروش نیستند.")

    return "\n".join(lines)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text
    }).encode()

    with urllib.request.urlopen(url, data=data, timeout=15) as response:
        return response.read()

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?timeout=30"

    if offset:
        url += f"&offset={offset}"

    with urllib.request.urlopen(url, timeout=40) as response:
        return json.loads(response.read().decode())

def main():
    print("🤖 ATLAS AI is online.")

    offset = None

    while True:
        try:
            updates = get_updates(offset)

            for update in updates.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message", {})
                chat = message.get("chat", {})
                chat_id = chat.get("id")
                text = message.get("text", "").strip().lower()

                if not chat_id:
                    continue

                if text in ["/start", "/help"]:
                    send_message(
                        chat_id,
                        "🤖 ATLAS AI\n\n"
                        "/report — گزارش کامل ATLAS\n"
                        "/sniper — ATLAS SNIPER\n"
                        "/portfolio — وضعیت سبد\n"
                        "/goal — فاصله تا هدف\n"
                        "/metals — ATLAS Metals\n"
                        "/help — راهنما"
                    )

                elif text in ["/report", "/sniper"]:
                    send_message(chat_id, atlas_report())

                elif text == "/portfolio":
                    send_message(
                        chat_id,
                        "📊 ATLAS PORTFOLIO\n\n"
                        "ماژول مدیریت سبد در مرحله بعد فعال می‌شود."
                    )

                elif text == "/goal":
                    send_message(
                        chat_id,
                        "🎯 ATLAS GOAL\n\n"
                        "ماژول محاسبه فاصله تا هدف در مرحله بعد فعال می‌شود."
                    )

                elif text == "/metals":
                    send_message(
                        chat_id,
                        "🥇 ATLAS METALS\n\n"
                        "ماژول طلا و نقره در مرحله بعد فعال می‌شود."
                    )

        except Exception as e:
            print("ERROR:", e)

if __name__ == "__main__":
    main()
