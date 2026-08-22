""ATLAS v10.1 offline smoke tests. No network calls."""
import importlib.util
import pathlib

path = pathlib.Path(__file__).with_name("bot.py")
spec = importlib.util.spec_from_file_location("atlas_bot", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

assert mod.VERSION == "ATLAS v10.1", mod.VERSION
assert mod.data_symbol("MATIC") == "POL"
assert mod.data_symbol("BTC") == "BTC"
assert mod.is_stable("USDT") is True
assert mod.is_stable("USDN") is False

# MACD must return a real histogram whenever enough data exists.
vals = [100 + i * 0.2 + ((i % 7) - 3) * 0.05 for i in range(120)]
ml, ms, hist = mod.macd(vals)
assert ml is not None and ms is not None and hist is not None

# RSI series must be linear-time Wilder output and end at the scalar RSI.
series = mod.rsi_series(vals)
assert len(series) >= 80
assert abs(series[-1] - mod.rsi(vals)) < 1e-9

# Breadth sample must exclude cross-timeframe contradictions.
rows = [
    {"h4_trend":"BULLISH","d1_trend":"BULLISH"},
    {"h4_trend":"BULLISH","d1_trend":"BEARISH"},
    {"h4_trend":"BEARISH","d1_trend":"BEARISH"},
]
b = mod.market_breadth(rows)
assert b["samples"] == 2, b

print("ATLAS v10.1 smoke test: PASS")
