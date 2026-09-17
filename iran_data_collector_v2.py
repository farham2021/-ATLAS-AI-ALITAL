#!/usr/bin/env python3
"""ATLAS Iran Data Plane collector.

Silver additions are isolated to the Data Plane:
- XAGUSD: global silver proxy from Yahoo SI=F, explicitly tagged as futures proxy.
- SILVER999_FAIR: theoretical 999-silver value in TOMAN/gram derived from
  SI=F and Navasan USD/Toman.  It is NOT presented as an observed Iranian
  retail quote.  SILVER999 remains reserved for a future real Iran-market feed.
"""
import os,json,urllib.parse,urllib.request
from datetime import datetime,timezone
SB=os.getenv("SUPABASE_URL","").rstrip("/"); KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY","")
NAV=os.getenv("NAVASAN_API_KEY",""); FUNDS=os.getenv("ATLAS_FUNDS_JSON_URL",""); TIMEOUT=25
UA={"User-Agent":"Mozilla/5.0 ATLAS/3.0","Accept":"application/json"}
TROY_OZ_GRAMS=31.1034768

def now(): return datetime.now(timezone.utc).isoformat()
def n(x):
    try:return float(str(x).replace(",",""))
    except:return None
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=TIMEOUT) as r:return json.loads(r.read())
def post(table,rows):
    if not rows:return 0
    req=urllib.request.Request(f"{SB}/rest/v1/{table}",data=json.dumps(rows,ensure_ascii=False).encode(),method="POST",
      headers={"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json","Prefer":"return=minimal"})
    with urllib.request.urlopen(req,timeout=TIMEOUT): pass
    return len(rows)

def navasan():
    if not NAV:return []
    d=get("https://api.navasan.tech/latest/?"+urllib.parse.urlencode({"api_key":NAV}))
    mp={"usd_sell":"USD_IRR","usdt":"USDT_IRR","18ayar":"GOLD18","sekkeh":"COIN_EMAMI"};o=[]
    for k,s in mp.items():
        x=d.get(k); p=n(x.get("value")) if isinstance(x,dict) else None
        if p and p>0:o.append({"captured_at":now(),"symbol":s,"price":p,"payload":{"provider":"navasan","source_symbol":k,"price":p,"unit":"TOMAN_PROVIDER_QUOTE","raw":x}})
    return o

def yahoo_silver():
    # SI=F is a liquid COMEX silver-futures proxy (USD/troy oz), not spot XAG.
    url="https://query1.finance.yahoo.com/v8/finance/chart/SI%3DF?"+urllib.parse.urlencode({"interval":"1h","range":"5d","events":"history"})
    d=get(url); result=((d.get("chart") or {}).get("result") or [])
    if not result:return []
    r=result[0]; meta=r.get("meta") or {}; price=n(meta.get("regularMarketPrice"))
    if not price:
        q=(((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
        price=next((n(v) for v in reversed(q) if n(v) is not None),None)
    if not price or price<=0:return []
    return [{"captured_at":now(),"symbol":"XAGUSD","asset":"SILVER","price":price,
             "payload":{"provider":"yahoo","source_symbol":"SI=F","price":price,"unit":"USD_PER_TROY_OZ","proxy":True,"proxy_kind":"COMEX_SILVER_FUTURES"}}]

def silver_fair(navasan_rows,xag_rows):
    # Navasan's public quote is Toman; preserve that unit explicitly.
    usd=next((n(r.get("price")) for r in navasan_rows if r.get("symbol")=="USD_IRR"),None)
    xag=next((n(r.get("price")) for r in xag_rows if r.get("symbol")=="XAGUSD"),None)
    if not usd or not xag:return []
    fair=(xag*usd)/TROY_OZ_GRAMS
    return [{"captured_at":now(),"symbol":"SILVER999_FAIR","asset":"SILVER","price":fair,
             "payload":{"provider":"atlas_derived","price":fair,"unit":"TOMAN_PER_GRAM","derived":True,
                        "not_retail_quote":True,"formula":"SI=F_USD_per_oz * Navasan_USD_Toman / 31.1034768",
                        "xag_proxy_usd_oz":xag,"usd_toman":usd}}]

def tsetmc():
    qs=[("market","0"),("withBestLimits","false"),("hEven","0"),("RefID","0")]+[(f"paperTypes[{i}]",str(i+1)) for i in range(9)]
    w=get("https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?"+urllib.parse.urlencode(qs)); w=w.get("marketwatch",[]) if isinstance(w,dict) else []
    c=get("https://cdn.tsetmc.com/api/ClientType/GetClientTypeAll"); c=c.get("clientTypeAllDto",[]) if isinstance(c,dict) else []
    cm={str(x.get("insCode") or ""):x for x in c if isinstance(x,dict)}; ts=now(); rows=[]; adv=dec=unch=0; tv=vol=rf=0.; leaders=[]
    for x in w:
        if not isinstance(x,dict):continue
        code=str(x.get("insCode") or ""); sym=str(x.get("lVal18AFC") or "").strip(); close=n(x.get("pClosing")); y=n(x.get("priceYesterday") or x.get("pYesterday")); vv=n(x.get("qTotTran5J")) or 0; val=n(x.get("qTotCap")) or 0
        if not sym or close is None:continue
        pct=(close/y-1)*100 if y else n(x.get("priceChangePercent") or x.get("percent"))
        if pct is not None: adv+=pct>0; dec+=pct<0; unch+=pct==0
        cc=cm.get(code,{}); bi=n(cc.get("buy_I_Volume") or cc.get("buyIVolume")); si=n(cc.get("sell_I_Volume") or cc.get("sellIVolume")); flow=(bi-si)*close if bi is not None and si is not None else None
        if flow is not None:rf+=flow
        tv+=val;vol+=vv;leaders.append((val,sym,close,pct)); rows.append({"captured_at":ts,"symbol":sym,"price":close,"value":val,"payload":{"provider":"tsetmc","ins_code":code,"price":close,"pct":pct,"volume":vv,"trade_value":val,"real_money_flow":flow,"sector":x.get("lSecVal"),"name":x.get("lVal30")}})
    breadth=adv/(adv+dec)*100 if adv+dec else None
    summary={"captured_at":ts,"symbol":"TSE_MARKET","value":tv,"payload":{"provider":"tsetmc","trade_value":tv,"volume":vol,"real_money_flow":rf,"advance":adv,"decline":dec,"unchanged":unch,"breadth":breadth,"leaders":[{"symbol":s,"price":p,"pct":pc,"value":v} for v,s,p,pc in sorted(leaders,reverse=True)[:15]]}}
    return [summary]+sorted(rows,key=lambda r:r.get("value") or 0,reverse=True)[:250]

def funds():
    if not FUNDS:return []
    d=get(FUNDS); items=d.get("data",[]) if isinstance(d,dict) else d
    if not isinstance(items,list):return []
    o=[];ts=now()
    for x in items:
        if not isinstance(x,dict):continue
        s=str(x.get("symbol") or "");p=n(x.get("price"));nav=n(x.get("nav"))
        if not s or not p:continue
        prem=(p/nav-1)*100 if nav else None; payload={**x,"provider":"configured_fund_feed","price":p,"nav":nav,"premium_pct":prem}
        o.append({"captured_at":ts,"symbol":s,"name":x.get("name"),"fund_type":x.get("fund_type"),"price":p,"nav":nav,"payload":payload})
    return o

def main():
    if not SB or not KEY:raise SystemExit("Supabase credentials missing")
    st={}; nav_rows=[]; xag_rows=[]
    try: nav_rows=navasan(); st["navasan"]=post("atlas_iran_fx_snapshots",nav_rows)
    except Exception as e: st["navasan_error"]=str(e)
    try: xag_rows=yahoo_silver(); fair_rows=silver_fair(nav_rows,xag_rows); st["silver_global"]=post("atlas_market_snapshots",xag_rows+fair_rows); st["silver_fair"]=len(fair_rows)
    except Exception as e: st["silver_error"]=str(e)
    for table,fn,name in [("atlas_tse_snapshots",tsetmc,"tsetmc"),("atlas_fund_snapshots",funds,"funds")]:
        try:st[name]=post(table,fn())
        except Exception as e:st[name+"_error"]=str(e)
    print(json.dumps(st,ensure_ascii=False))
    if not any(isinstance(v,int) and v>0 for v in st.values()):raise SystemExit("No observations collected")
if __name__=="__main__":main()
