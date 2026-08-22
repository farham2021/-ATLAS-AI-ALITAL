#!/usr/bin/env python3
"""Offline smoke test for ATLAS AI v10.2 COMPACT."""

import importlib.util
import inspect
from pathlib import Path

BOT = Path("bot.py")
if not BOT.exists():
    raise SystemExit("FAIL: bot.py not found")

spec = importlib.util.spec_from_file_location("atlas_bot", BOT)
if spec is None or spec.loader is None:
    raise SystemExit("FAIL: cannot load bot.py")

mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

assert getattr(mod, "VERSION", None) == "ATLAS v10.2 COMPACT", (
    f"FAIL: VERSION={getattr(mod, 'VERSION', None)!r}"
)

required = [
    "SIGNAL_TIMEFRAME",
    "compact_table_1",
    "compact_table_2",
    "compact_summary",
    "build_report",
]
missing = [name for name in required if not hasattr(mod, name)]
assert not missing, f"FAIL: missing required items: {missing}"

assert mod.SIGNAL_TIMEFRAME == "4h"

result = mod.compact_table_1([], 10)
assert isinstance(result, tuple) and len(result) == 2
assert isinstance(mod.compact_table_2([]), str)

source = BOT.read_text(encoding="utf-8", errors="ignore").upper()
for token in ("TP1", "TP2", "TP3", "TP4", "SL", "R/R", "BUY", "SELL", "WAIT"):
    assert token in source, f"FAIL: expected token {token} not found"

assert callable(getattr(mod, "main", None))
assert inspect.isfunction(mod.main)

print("PASS: ATLAS v10.2 COMPACT smoke test")
print("PASS: bot.py syntax/import")
print("PASS: 4H signal timeframe")
print("PASS: compact tables")
print("PASS: TP1/TP2/TP3/TP4 + SL + R/R + BUY/SELL/WAIT")
print("PASS: main() present; network execution skipped")
