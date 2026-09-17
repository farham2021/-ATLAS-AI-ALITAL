#!/usr/bin/env python3
"""ATLAS Iran Data Plane collector — resilient production edition.

Architecture boundary: collection + Supabase persistence only. No Telegram and no
ATLAS analysis logic lives here.

Key properties:
- Navasan is quota-aware (free plan friendly): refreshes only when cached FX is old.
- Uses Navasan's officially documented HTTP endpoint; provider currently documents HTTP.
- Silver spot: Alpha Vantage GOLD_SILVER_SPOT first, Yahoo SI=F futures proxy fallback.
- SILVER999_FAIR is derived and explicitly NOT a retail Iran quote.
- TSETMC is retried and remains non-fatal if temporarily unavailable.
- BrsApi is the primary Iran market provider using documented AllSymbols, Nav, Commodity and Gold_Currency endpoints.
- Provider failures are isolated; existing good Supabase data is never overwritten by fake data.
"""
import json, os, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

SB=os.getenv("SUPABASE_URL","").rstrip("/")
KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
NAV=os.getenv("NAVASAN_API_KEY","").strip()
ALPHA=os.getenv("ALPHAVANTAGE_API_KEY","").strip()
BRS=os.getenv("BRSAPI_API_KEY","").strip()
TIMEOUT=int(os.getenv("ATLAS_IRAN_HTTP_TIMEOUT","18"))
NAV_MIN_AGE_H=float(os.getenv("ATLAS_NAVASAN_MIN_REFRESH_HOURS","7.5"))  # ~3 calls/day
TROY_OZ_GRAMS=31.1034768
UA={"User-Agent":"Mozilla/5.0 (compatible; ATLAS-Iran-DataPlane/4.0)","Accept":"application/json"}

def now(): return datetime.now(timezone.utc).isoformat()
def num(x):
    try:return float(str(x).replace(",",""))
    except Exception:return None

def http_json(url, timeout=None, retries=1):
    last=None
    for i in range(max(1,retries)):
        try:
            req=urllib.request.Request(url,headers=UA)
            with urllib.request.urlopen(req,timeout=timeout or TIMEOUT) as r:
                raw=r.read().decode("utf-8","replace")
                return json.loads(raw)
        except Exception as e:
            last=e
            if i+1<retries: time.sleep(1.5*(i+1))
    raise last

def supabase_headers(content_type=False):
    h={"apikey":KEY}
    if KEY.startswith("eyJ"):
        h["Authorization"]=f"Bearer {KEY}"
    if content_type:
        h["Content-Type"]="application/json"
        h["Prefer"]="return=minimal"
    return h

def post(table, rows):
    if not rows:return 0
    req=urllib.request.Request(
        f"{SB}/rest/v1/{table}",
        data=json.dumps(rows,ensure_ascii=False,allow_nan=False).encode(),
        method="POST", headers=supabase_headers(content_type=True))
    try:
        with urllib.request.urlopen(req,timeout=TIMEOUT):pass
    except urllib.error.HTTPError as e:
        try:
            body=e.read().decode("utf-8","replace")[:1200]
        except Exception:
            body=""
        raise RuntimeError(f"Supabase {table} HTTP {e.code}: {body}") from None
    return len(rows)

def latest_rows(table, symbols, limit=50):
    if not symbols:return []
    q=urllib.parse.urlencode({"select":"captured_at,symbol,price,payload","order":"captured_at.desc","limit":str(limit)})
    req=urllib.request.Request(f"{SB}/rest/v1/{table}?{q}",headers=supabase_headers())
    with urllib.request.urlopen(req,timeout=TIMEOUT) as r: rows=json.loads(r.read())
    out=[]; seen=set(); wanted={str(s) for s in symbols}
    for row in rows if isinstance(rows,list) else []:
        s=str(row.get("symbol") or "")
        if s in wanted and s not in seen: out.append(row);seen.add(s)
    return out

def age_hours(ts):
    try:return (datetime.now(timezone.utc)-datetime.fromisoformat(str(ts).replace("Z","+00:00"))).total_seconds()/3600
    except Exception:return 1e9


BRS_BASE="https://Api.BrsApi.ir"

def brs_get(path, params=None, retries=2):
    if not BRS:
        return None
    q={"key":BRS}
    if params:q.update(params)
    return http_json(BRS_BASE+path+"?"+urllib.parse.urlencode(q),retries=retries)

def walk_records(obj, path=""):
    """Recursively yield BrsApi records while preserving JSON path metadata."""
    if isinstance(obj,list):
        for i,x in enumerate(obj):
            p=f"{path}[{i}]" if path else f"[{i}]"
            if isinstance(x,(dict,list)):
                yield from walk_records(x,p)
        return
    if not isinstance(obj,dict):
        return
    scalar_count=sum(not isinstance(v,(dict,list)) for v in obj.values())
    if scalar_count:
        rec=dict(obj)
        rec["__path"]=path
        rec["__key"]=path.rsplit(".",1)[-1] if path else ""
        yield rec
    for k,v in obj.items():
        if isinstance(v,(dict,list)):
            p=f"{path}.{k}" if path else str(k)
            yield from walk_records(v,p)

def clean_raw(x):
    return {k:v for k,v in x.items() if not str(k).startswith("__")}

def record_name(x):
    vals=[
        first(x,"symbol","name","title","key","slug","l18","lVal18AFC",
              "nameFa","nameEn","persianName","englishName","label"),
        x.get("__key"),x.get("__path")
    ]
    return " ".join(str(v) for v in vals if v not in (None,"")).strip()

def first(d, *keys):
    for k in keys:
        if isinstance(d,dict) and d.get(k) not in (None,""):
            return d.get(k)
    return None

def brs_gold_currency_rows():
    d=brs_get("/Market/Gold_Currency.php")
    if d is None:return []
    out=[];ts=now()
    aliases={
      "usd":"USD_IRR","dollar":"USD_IRR","دلار":"USD_IRR",
      "usdt":"USDT_IRR","tether":"USDT_IRR","تتر":"USDT_IRR",
      "18ayar":"GOLD18","gold18":"GOLD18","طلای 18 عیار":"GOLD18","طلای ۱۸ عیار":"GOLD18",
      "sekkeh":"COIN_EMAMI","emami":"COIN_EMAMI","سکه امامی":"COIN_EMAMI"}
    for x in walk_records(d):
        name=record_name(x)
        norm=name.lower().replace("_","").replace("-","").replace(" ","")
        sym=None
        for a,target in aliases.items():
            if a.lower().replace(" ","") in norm: sym=target;break
        p=num(first(x,"price","value","last","close","pClosing","pDrCotVal","lastPrice","finalPrice","current","rate"))
        if sym and p and p>0:
            out.append({"captured_at":ts,"symbol":sym,"price":p,"payload":{"provider":"brsapi_gold_currency","source_name":name,"price":p,"raw":clean_raw(x)}})
    return out

def brs_commodity_rows():
    d=brs_get("/Market/Commodity.php")
    if d is None:return []
    out=[];ts=now()
    for x in walk_records(d):
        name=record_name(x)
        n=name.lower().replace("_","").replace("-","").replace(" ","")
        sym=None; asset=None; unit=None
        if any(a in n for a in ("xagusd","silver","نقره")):
            sym="XAGUSD";asset="SILVER";unit="USD_PER_TROY_OZ"
        elif any(a in n for a in ("xauusd","goldspot","طلایجهانی","انسجهانیطلا")):
            sym="XAUUSD";asset="GOLD";unit="USD_PER_TROY_OZ"
        elif any(a in n for a in ("copper","مس")):
            sym="COPPER";asset="COPPER";unit=None
        p=num(first(x,"price","value","last","close","lastPrice","finalPrice","current","rate"))
        if sym and p and p>0:
            out.append({"captured_at":ts,"symbol":sym,"asset":asset,"price":p,"payload":{"provider":"brsapi_commodity","source_name":name,"price":p,"unit":unit,"raw":clean_raw(x)}})
    return out

def brs_tse_rows(status=None):
    """Read BrsApi AllSymbols using tolerant field mapping.

    If the provider schema changes, return [] but emit safe diagnostics rather
    than inventing mappings.  Direct TSETMC remains a fallback in main().
    """
    d=brs_get("/Tsetmc/AllSymbols.php")
    if d is None:return []
    records=list(walk_records(d))
    if status is not None:
        status["brsapi_tse_response_type"]=type(d).__name__
        if isinstance(d,dict):
            status["brsapi_tse_top_keys"]=list(d.keys())[:20]
        status["brsapi_tse_records_seen"]=len(records)
        if records:
            status["brsapi_tse_sample_keys"]=[
                k for k in records[0].keys() if not k.startswith("__")
            ][:40]

    ts=now(); rows=[]; adv=dec=unch=0; tv=vol=0.; leaders=[]
    for x in records:
        sym=str(first(
            x,"l18","symbol","Symbol","ticker","lVal18AFC","insCode",
            "instrumentSymbol","instrument_symbol","نماد"
        ) or "").strip()
        name=str(first(
            x,"l30","name","Name","lVal30","companyName","company_name",
            "instrumentName","instrument_name","نام"
        ) or "").strip()
        # BrsApi AllSymbols schema observed in production:
        # pl = last traded price, pc = closing price, py = yesterday price.
        # Prefer pl for live snapshot; fall back to pc.
        p=num(first(x,"pl","pc"))
        if not sym or not p or p<=0:continue

        y=num(first(x,"py"))
        # plp is the provider's last-price percent change; pcp is closing-price
        # percent change. Since snapshot price prefers pl, prefer plp too.
        pct=num(first(x,"plp","pcp"))
        if pct is None and y and y>0:pct=(p/y-1)*100

        # Verified from the production BrsApi AllSymbols schema.
        trades=num(first(x,"tno")) or 0
        volume=num(first(x,"tvol")) or 0
        value=num(first(x,"tval")) or 0

        if pct is not None:
            if pct>0:adv+=1
            elif pct<0:dec+=1
            else:unch+=1
        tv+=value;vol+=volume;leaders.append((value,sym,p,pct))
        raw_text=str(clean_raw(x)).lower()
        is_fund_hint=any(k in raw_text for k in (
            "صندوق","etf","fund","سرمایه گذاری قابل معامله",
            "سرمایه‌گذاری قابل معامله"
        ))
        rows.append({
            "captured_at":ts,"symbol":sym,"price":p,"value":value,
            "payload":{
                "provider":"brsapi_allsymbols","name":name,"price":p,
                "close":num(first(x,"pc")),"yesterday":y,"pct":pct,
                "trades":trades,"volume":volume,"trade_value":value,
                "isin":first(x,"isin"),"industry_code":first(x,"cs"),
                "market_value":num(first(x,"mv")),
                "is_fund_hint":is_fund_hint
            }
        })

    if status is not None:
        status["brsapi_tse_rows_mapped"]=len(rows)
        status["brsapi_tse_price_mapping"]="pl->pc; py; plp->pcp"
    if not rows:return []

    breadth=adv/(adv+dec)*100 if adv+dec else None
    summary={
        "captured_at":ts,"symbol":"TSE_MARKET","price":None,"value":tv,
        "payload":{
            "provider":"brsapi_allsymbols","trade_value":tv,"volume":vol,
            "advance":adv,"decline":dec,"unchanged":unch,"breadth":breadth,
            "leaders":[
                {"symbol":s,"price":p,"pct":pc,"value":v}
                for v,s,p,pc in sorted(leaders,reverse=True)[:15]
            ]
        }
    }
    return [summary]+sorted(
        rows,key=lambda r:r.get("value") or 0,reverse=True
    )[:250]

def brs_fund_rows(tse_rows, status=None):
    """Persist ETF market-price snapshots from AllSymbols.

    NAV is optional enrichment. A BrsApi HTTP 402 means the current plan does
    not expose NAV; after the first 402 we open a circuit breaker for this run.
    We never fabricate NAV.
    """
    if not BRS:return []

    candidates=[]
    for r in tse_rows:
        if r.get("symbol")=="TSE_MARKET":continue
        payload=r.get("payload") or {}
        hay=(" ".join(str(payload.get(k) or "") for k in
             ("name","isin","industry_code"))).lower()
        if payload.get("is_fund_hint") or any(k in hay for k in (
            "صندوق","etf","fund","سرمایه گذاری قابل معامله",
            "سرمایه‌گذاری قابل معامله"
        )):
            candidates.append(r)

    if status is not None:
        status["brsapi_fund_candidates"]=len(candidates)

    # Store actual ETF market data even when paid NAV is unavailable.
    ts=now()
    out=[]
    for r in candidates:
        p=r.get("payload") or {}
        out.append({
            "captured_at":ts,
            "symbol":str(r.get("symbol") or ""),
            "name":p.get("name"),
            "fund_type":"ETF",
            "price":num(r.get("price")),
            "nav":None,
            "payload":{
                "provider":"brsapi_allsymbols",
                "price":num(r.get("price")),
                "nav":None,
                "nav_status":"UNAVAILABLE_NOT_QUERIED",
                "pct":p.get("pct"),
                "volume":p.get("volume"),
                "trade_value":p.get("trade_value"),
                "isin":p.get("isin")
            }
        })

    max_nav=int(os.getenv("ATLAS_BRSAPI_NAV_MAX_SYMBOLS","20"))
    nav_requests=0; nav_errors=0; nav_402=False; nav_error_sample=None
    nav_rows=0

    # Optional NAV enrichment. Stop immediately on plan-level HTTP 402.
    for idx,r in enumerate(out[:max_nav]):
        sym=r["symbol"]
        try:
            d=brs_get("/Tsetmc/Nav.php",{"l18":sym},retries=1)
            nav_requests+=1
        except urllib.error.HTTPError as e:
            nav_errors+=1
            if e.code==402:
                nav_402=True
                nav_error_sample={"symbol":sym,"http_status":402,
                                  "reason":"PAYMENT_REQUIRED"}
                break
            if nav_error_sample is None:
                nav_error_sample={"symbol":sym,"http_status":e.code,
                                  "reason":"HTTP_ERROR"}
            continue
        except Exception as e:
            nav_errors+=1
            if nav_error_sample is None:
                nav_error_sample={"symbol":sym,"reason":str(e)[:200]}
            continue

        recs=list(walk_records(d))
        selected=None; nav=issue=generic=None
        for rec in recs:
            nav=num(first(
                rec,"nav","NAV","navRedemption","redemptionNav",
                "nav_redemption","redemption_nav","cancelNav","cancel_nav",
                "ابطال","nav_ebtal"
            ))
            issue=num(first(
                rec,"navIssuance","issuanceNav","nav_issuance",
                "issuance_nav","issueNav","issue_nav","صدور","nav_sodoor"
            ))
            generic=num(first(rec,"navValue","nav_value"))
            if any(v is not None and v>0 for v in (nav,issue,generic)):
                selected=rec
                break
        if not selected:
            continue

        chosen=next((v for v in (nav,issue,generic)
                     if v is not None and v>0),None)
        if not chosen:
            continue
        price=num(r.get("price"))
        prem=(price/chosen-1)*100 if price else None
        r["nav"]=chosen
        r["payload"].update({
            "provider":"brsapi_nav",
            "nav":chosen,
            "nav_status":"AVAILABLE",
            "nav_redemption":nav,
            "nav_issuance":issue,
            "premium_pct":prem
        })
        nav_rows+=1

    if nav_402:
        for r in out:
            if r.get("nav") is None:
                r["payload"]["nav_status"]="UNAVAILABLE_PLAN_REQUIRED"

    if status is not None:
        status["fund_provider"]="brsapi_allsymbols"
        status["brsapi_nav_requests"]=nav_requests
        status["brsapi_nav_errors"]=nav_errors
        status["brsapi_nav_circuit_breaker"]="PAYMENT_REQUIRED" if nav_402 else "CLOSED"
        status["brsapi_nav_rows_mapped"]=nav_rows
        if nav_error_sample:
            status["brsapi_nav_error_sample"]=nav_error_sample
        status["fund_market_rows"]=len(out)

    return out

def navasan_rows():
    if not NAV:return []
    # Navasan's current official guide documents http://api.navasan.tech/latest/.
    url="http://api.navasan.tech/latest/?"+urllib.parse.urlencode({"api_key":NAV})
    d=http_json(url,retries=2)
    mp={"usd_sell":"USD_IRR","usdt":"USDT_IRR","18ayar":"GOLD18","sekkeh":"COIN_EMAMI"};out=[];ts=now()
    for k,s in mp.items():
        x=d.get(k) if isinstance(d,dict) else None;p=num(x.get("value")) if isinstance(x,dict) else None
        if p and p>0:out.append({"captured_at":ts,"symbol":s,"price":p,"payload":{"provider":"navasan","source_symbol":k,"price":p,"unit":"TOMAN_PROVIDER_QUOTE","raw":x}})
    return out

def get_fx_quota_aware(status):
    cached=[]
    try:cached=latest_rows("atlas_iran_fx_snapshots",{"USD_IRR","USDT_IRR","GOLD18","COIN_EMAMI"})
    except Exception as e:status["fx_cache_error"]=str(e)
    usd=next((r for r in cached if r.get("symbol")=="USD_IRR"),None)
    due=(usd is None or age_hours(usd.get("captured_at"))>=NAV_MIN_AGE_H)
    if not due:
        status["navasan"]="CACHE_OK";status["navasan_cache_age_h"]=round(age_hours(usd.get("captured_at")),2)
        return cached
    if not NAV:
        status["navasan"]="NO_KEY_USING_CACHE"
        return cached
    try:
        fresh=navasan_rows();status["navasan_written"]=post("atlas_iran_fx_snapshots",fresh)
        return fresh or cached
    except Exception as e:
        status["navasan_error"]=str(e);status["navasan"]="DEGRADED_USING_CACHE"
        return cached

def alpha_silver():
    if not ALPHA:return []
    q=urllib.parse.urlencode({"function":"GOLD_SILVER_SPOT","symbol":"SILVER","apikey":ALPHA})
    d=http_json("https://www.alphavantage.co/query?"+q,retries=2)
    if not isinstance(d,dict):return []
    # API response field names can vary; accept only a positive explicit price.
    candidates=[d.get("price"),d.get("Price"),d.get("spot_price"),d.get("Spot Price"),d.get("ask"),d.get("Ask Price")]
    p=next((num(v) for v in candidates if num(v) and num(v)>0),None)
    if not p:return []
    return [{"captured_at":now(),"symbol":"XAGUSD","asset":"SILVER","price":p,
             "payload":{"provider":"alphavantage","source_symbol":"SILVER","price":p,"unit":"USD_PER_TROY_OZ","proxy":False,"spot":True}}]

def yahoo_silver():
    urls=[
      "https://query1.finance.yahoo.com/v8/finance/chart/SI%3DF?"+urllib.parse.urlencode({"interval":"1h","range":"5d","events":"history"}),
      "https://query2.finance.yahoo.com/v8/finance/chart/SI%3DF?"+urllib.parse.urlencode({"interval":"1h","range":"5d","events":"history"})]
    last=None
    for url in urls:
        try:
            d=http_json(url,retries=1);result=((d.get("chart") or {}).get("result") or [])
            if not result:continue
            r=result[0];meta=r.get("meta") or {};p=num(meta.get("regularMarketPrice"))
            if not p:
                closes=(((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
                p=next((num(v) for v in reversed(closes) if num(v) and num(v)>0),None)
            if p and p>0:return [{"captured_at":now(),"symbol":"XAGUSD","asset":"SILVER","price":p,
              "payload":{"provider":"yahoo","source_symbol":"SI=F","price":p,"unit":"USD_PER_TROY_OZ","proxy":True,"proxy_kind":"COMEX_SILVER_FUTURES"}}]
        except Exception as e:last=e
    if last:raise last
    return []

def silver_rows(status):
    if BRS:
        try:
            rows=[r for r in brs_commodity_rows() if r.get("symbol")=="XAGUSD"]
            if rows:status["silver_provider"]="brsapi";return rows
        except Exception as e:status["silver_brsapi_error"]=str(e)
    for fn,name in ((alpha_silver,"alphavantage"),(yahoo_silver,"yahoo")):
        try:
            rows=fn()
            if rows:status["silver_provider"]=name;return rows
        except Exception as e:status[f"silver_{name}_error"]=str(e)
    try:
        cached=latest_rows("atlas_market_snapshots",{"XAGUSD"})
        if cached:status["silver_provider"]="CACHE";return cached
    except Exception as e:status["silver_cache_error"]=str(e)
    return []

def silver_fair(fx,xag):
    usd=next((num(r.get("price")) for r in fx if r.get("symbol")=="USD_IRR"),None)
    xp=next((num(r.get("price")) for r in xag if r.get("symbol")=="XAGUSD"),None)
    if not usd or not xp:return []
    fair=(xp*usd)/TROY_OZ_GRAMS
    return [{"captured_at":now(),"symbol":"SILVER999_FAIR","asset":"SILVER","price":fair,
      "payload":{"provider":"atlas_derived","price":fair,"unit":"TOMAN_PER_GRAM","derived":True,"not_retail_quote":True,
      "formula":"XAG_USD_per_oz * Navasan_USD_Toman / 31.1034768","xag_usd_oz":xp,"usd_toman":usd}}]

def tsetmc():
    qs=[("market","0"),("withBestLimits","false"),("hEven","0"),("RefID","0")]+[(f"paperTypes[{i}]",str(i+1)) for i in range(9)]
    w=http_json("https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?"+urllib.parse.urlencode(qs),timeout=14,retries=3)
    w=w.get("marketwatch",[]) if isinstance(w,dict) else []
    try:c=http_json("https://cdn.tsetmc.com/api/ClientType/GetClientTypeAll",timeout=14,retries=2);c=c.get("clientTypeAllDto",[]) if isinstance(c,dict) else []
    except Exception:c=[]
    cm={str(x.get("insCode") or ""):x for x in c if isinstance(x,dict)};ts=now();rows=[];adv=dec=unch=0;tv=vol=rf=0.;leaders=[]
    for x in w:
        if not isinstance(x,dict):continue
        code=str(x.get("insCode") or "");sym=str(x.get("lVal18AFC") or "").strip();close=num(x.get("pClosing"));y=num(x.get("priceYesterday") or x.get("pYesterday"));vv=num(x.get("qTotTran5J")) or 0;val=num(x.get("qTotCap")) or 0
        if not sym or close is None:continue
        pct=(close/y-1)*100 if y else num(x.get("priceChangePercent") or x.get("percent"))
        if pct is not None:adv+=pct>0;dec+=pct<0;unch+=pct==0
        cc=cm.get(code,{});bi=num(cc.get("buy_I_Volume") or cc.get("buyIVolume"));si=num(cc.get("sell_I_Volume") or cc.get("sellIVolume"));flow=(bi-si)*close if bi is not None and si is not None else None
        if flow is not None:rf+=flow
        tv+=val;vol+=vv;leaders.append((val,sym,close,pct));rows.append({"captured_at":ts,"symbol":sym,"price":close,"value":val,"payload":{"provider":"tsetmc","ins_code":code,"price":close,"pct":pct,"volume":vv,"trade_value":val,"real_money_flow":flow,"sector":x.get("lSecVal"),"name":x.get("lVal30")}})
    if not rows:return []
    breadth=adv/(adv+dec)*100 if adv+dec else None
    summary={"captured_at":ts,"symbol":"TSE_MARKET","value":tv,"payload":{"provider":"tsetmc","trade_value":tv,"volume":vol,"real_money_flow":rf,"advance":adv,"decline":dec,"unchanged":unch,"breadth":breadth,"leaders":[{"symbol":s,"price":p,"pct":pc,"value":v} for v,s,p,pc in sorted(leaders,reverse=True)[:15]]}}
    return [summary]+sorted(rows,key=lambda r:r.get("value") or 0,reverse=True)[:250]

def main():
    if not SB or not KEY:raise SystemExit("Supabase credentials missing")
    st={"brsapi_key_configured":bool(BRS),"supabase_key_type":"new_secret" if KEY.startswith("sb_secret_") else ("legacy_jwt" if KEY.startswith("eyJ") else "unknown")}
    fx=get_fx_quota_aware(st)
    # BrsApi Gold/Currency can fill gaps without consuming Navasan quota.
    if BRS:
        try:
            diag=brs_get("/Market/Gold_Currency.php",retries=1)
            st["brsapi_gold_currency_response_type"]=type(diag).__name__
            if isinstance(diag,dict):
                st["brsapi_gold_currency_top_keys"]=list(diag.keys())[:20]
                for section in ("gold","currency","cryptocurrency"):
                    if section in diag:
                        section_records=list(walk_records(diag.get(section)))
                        st[f"brsapi_{section}_records_seen"]=len(section_records)
                        if section_records:
                            st[f"brsapi_{section}_sample_keys"]=[
                                k for k in section_records[0].keys()
                                if not k.startswith("__")
                            ][:30]
            brsfx=brs_gold_currency_rows(); st["brsapi_gold_currency_rows"]=len(brsfx)

            # BrsApi is authoritative for USDT_IRR.  Do not let an older Navasan/cache
            # quote win merely because that symbol already exists in this run.
            brs_usdt=[r for r in brsfx if r.get("symbol")=="USDT_IRR"]
            if brs_usdt:
                st["brsapi_usdt_written"]=post("atlas_iran_fx_snapshots",brs_usdt[-1:])
                fx=[r for r in fx if r.get("symbol")!="USDT_IRR"] + brs_usdt[-1:]
                st["usdt_provider"]="brsapi"

            # BrsApi still fills any other symbols missing from the quota-aware FX set.
            existing={r.get("symbol") for r in fx}
            additions=[r for r in brsfx if r.get("symbol") not in existing]
            if additions:
                st["brsapi_fx_written"]=post("atlas_iran_fx_snapshots",additions)
                fx=fx+additions
        except Exception as e:st["brsapi_gold_currency_error"]=str(e)
    xag=silver_rows(st);fresh_xag=[] if st.get("silver_provider")=="CACHE" else xag;fair=silver_fair(fx,xag)
    try:
        extra=[]
        if BRS:
            try:extra=[r for r in brs_commodity_rows() if r.get("symbol") in {"XAUUSD","COPPER"}]
            except Exception as e:st["brsapi_commodity_error"]=str(e)
        st["market_written"]=post("atlas_market_snapshots",fresh_xag+extra+fair);st["silver_fair"]=len(fair)
    except Exception as e:st["market_store_error"]=str(e)
    tse=[]
    if BRS:
        try:tse=brs_tse_rows(st);st["tse_provider"]="brsapi" if tse else "brsapi_empty"
        except Exception as e:st["brsapi_tse_error"]=str(e)
    if not tse:
        try:tse=tsetmc();st["tse_provider"]="tsetmc"
        except Exception as e:st["tsetmc_error"]=str(e);st["tse_provider"]="CACHE"
    try:st["tse_written"]=post("atlas_tse_snapshots",tse)
    except Exception as e:st["tse_store_error"]=str(e)
    fundrows=[]
    if BRS and tse:
        try:fundrows=brs_fund_rows(tse,st)
        except Exception as e:st["brsapi_fund_error"]=str(e)
    try:st["funds_written"]=post("atlas_fund_snapshots",fundrows)
    except Exception as e:st["fund_store_error"]=str(e)
    st["collector_status"]="OK_OR_DEGRADED"
    print(json.dumps(st,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
