#!/usr/bin/env python3
import ast,importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    for n in ("bot12.py","atlas_v12_upgrade.py","smoke_atlas.py","test_v12.py"):
        p=ROOT/n; assert p.exists(); ast.parse(p.read_text(encoding="utf-8"))
    b=importlib.import_module("bot12"); u=importlib.import_module("atlas_v12_upgrade")
    assert callable(b.personal_report) and callable(b.build_report)
    assert callable(u.health_check) and callable(u.build_personal_report) and callable(u.build_market_report)
    s=Path(__file__).read_text(encoding="utf-8")
    assert "ATLAS_v12_bot" not in s and "from bot import" not in s
    print("ATLAS AI v12 TEST STATUS: PASS")
if __name__=="__main__": main()
