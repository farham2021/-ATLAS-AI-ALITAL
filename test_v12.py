#!/usr/bin/env python3
from pathlib import Path
import ast, importlib.util

ROOT=Path(__file__).resolve().parent
for name in ("bot12.py","atlas_v12_upgrade.py","telegram_delivery_v12.py","smoke_atlas.py"):
    p=ROOT/name
    assert p.exists(), f"Missing {name}"
    ast.parse(p.read_text(encoding="utf-8"), filename=name)

bot=(ROOT/"bot12.py").read_text(encoding="utf-8")
assert "ATLAS_v12_bot" not in bot
assert "from bot import" not in bot
assert "import bot as engine" in bot
assert "telegram_delivery_v12" in bot

delivery=(ROOT/"telegram_delivery_v12.py").read_text(encoding="utf-8")
for x in ("TELEGRAM_CHAT_ID","TELEGRAM_GROUP_CHAT_ID","getMe","sendMessage","MAX_RETRIES"):
    assert x in delivery, f"Missing {x}"

print("ATLAS v12 tests: PASS")
