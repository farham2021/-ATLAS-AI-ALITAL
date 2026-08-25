#!/usr/bin/env python3
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parent
for n in ("bot12.py","atlas_v12_upgrade.py","telegram_delivery_v12.py","test_v12.py"):
    p=ROOT/n; assert p.exists(), f"Missing {n}"
    ast.parse(p.read_text(encoding="utf-8"), filename=n)
print("ATLAS v12 smoke: PASS")
