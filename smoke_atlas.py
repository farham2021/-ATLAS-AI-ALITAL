#!/usr/bin/env python3
import ast,importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    for n in ("bot12.py","atlas_v12_upgrade.py","smoke_atlas.py","test_v12.py"):
        p=ROOT/n; assert p.exists(),f"Missing {n}"; ast.parse(p.read_text(encoding="utf-8")); print("PASS",n)
    b=importlib.import_module("bot12"); u=importlib.import_module("atlas_v12_upgrade")
    for x in ("personal_report","build_report"): assert callable(getattr(b,x))
    for x in ("health_check","build_personal_report","build_market_report"): assert callable(getattr(u,x))
    assert u.health_check()["forced_signals"] is False
    print("ATLAS AI v12 SMOKE TEST: PASS")
if __name__=="__main__": main()
