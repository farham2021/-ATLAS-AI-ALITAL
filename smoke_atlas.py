#!/usr/bin/env python3
from pathlib import Path
import ast

FILES = ["bot.py", "atlas_v12_upgrade.py", "bot_v12.py"]
for f in FILES:
    p = Path(f)
    if not p.exists():
        raise SystemExit(f"Missing required file: {f}")
    ast.parse(p.read_text(encoding="utf-8"))

s = Path("atlas_v12_upgrade.py").read_text(encoding="utf-8")

required = [
    "fetch_tgju_fx",
    "fetch_tgju_rate",
    "health_check",
    "volume_spike_warning",
    "rsi_divergence",
    "setup_assessment",
    "best_setup_block",
    "generate_csv1_analysis_snapshot",
    "generate_csv2_institutional_data",
    "send_dual_csv",
    "augment_report_text",
]
for name in required:
    if f"def {name}(" not in s:
        raise SystemExit(f"Missing v12 function: {name}")

checks = {
    "v12": 'VERSION = "ATLAS v12.0"' in s,
    "TGJU USD only": "TGJU_USD_URL" in s and "price_dollar_rl" in s,
    "TGJU USDT only": "TGJU_USDT_URL" in s and "price_usdt" in s,
    "no Wallex fallback": "wallex.ir" not in s.lower(),
    "no Excoino fallback": "excoino" not in s.lower(),
    "no Nobitex fallback": "nobitex" not in s.lower(),
    "three-level setup": all(x in s for x in ("EXECUTABLE", "BEST_WATCH", "NO_VALID_SETUP")),
    "computed RR": "reward1" in s and "risk" in s and "rr =" in s,
    "health": "success_rate" in s,
    "volume spike": "VOLUME_SPIKE_MULTIPLIER" in s,
    "RSI divergence": "REGULAR_BEARISH" in s and "REGULAR_BULLISH" in s,
    "market cap CSV": '"market_cap"' in s,
    "dual CSV": "generate_csv1_analysis_snapshot" in s and "generate_csv2_institutional_data" in s,
    "timestamp filenames": "atlas_v12_analysis_snapshot_" in s and "atlas_v12_institutional_" in s,
    "UTF8 BOM": "utf-8-sig" in s,
    "telegram documents": "sendDocument" in s,
}
failed = [k for k,v in checks.items() if not v]
if failed:
    raise SystemExit("v12 smoke checks failed: " + ", ".join(failed))

print("PASS: ATLAS AI v12 upgrade smoke test")
for k in checks:
    print("  OK:", k)
