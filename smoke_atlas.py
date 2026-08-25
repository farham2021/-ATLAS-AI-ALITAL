#!/usr/bin/env python3
"""ATLAS AI v12 smoke test."""
import ast,importlib,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parent
MODULES=["atlas_v12_upgrade","bot12"]
def main():
    failures=[]
    for m in MODULES:
        p=ROOT/(m+".py")
        try:
            src=p.read_text(encoding="utf-8"); ast.parse(src,filename=str(p)); compile(src,str(p),"exec"); importlib.import_module(m); print(f"✅ {m}: compile/import OK")
        except Exception as e: failures.append((m,e)); print(f"❌ {m}: {type(e).__name__}: {e}")
    first=pathlib.Path(__file__).read_text(encoding="utf-8").splitlines()[0]
    if first=="#!/usr/bin/env python3":print("✅ smoke_atlas.py: shebang OK")
    else: failures.append(("shebang",first)); print("❌ smoke_atlas.py: invalid shebang")
    print("\n❌ SMOKE TEST FAILED" if failures else "\n✅ SMOKE TEST PASSED")
    return 1 if failures else 0
if __name__=="__main__":raise SystemExit(main())
