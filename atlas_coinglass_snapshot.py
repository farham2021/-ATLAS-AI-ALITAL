#!/usr/bin/env python3
"""Fail-closed public-safe CoinGlass derivatives snapshot for ATLAS Pages."""
from __future__ import annotations
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "https://open-api-v4.coinglass.com/api/futures"
SYMBOLS = ("BTC", "ETH", "SOL")
EXCHANGES = ("OKX", "Binance", "Bybit")

def _fetch(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    key = os.environ.get("COINGLASS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("COINGLASS_API_KEY_NOT_CONFIGURED")
    query = "?" + urllib.parse.urlencode(params) if params else ""
    req = urllib.request.Request(BASE + path + query, headers={
        "CG-API-KEY": key, "Accept": "application/json",
        "User-Agent": "ATLAS-Derivatives-Snapshot/1.0"})
    error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status != 200: raise RuntimeError(f"HTTP_{response.status}")
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or str(payload.get("code")) != "0":
                raise RuntimeError("COINGLASS_API_ERROR")
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            error = exc
            if attempt < 2: time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(type(error).__name__ if error else "FETCH_FAILED")

def _num(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError): return None

def collect() -> dict[str, Any]:
    result = {"schema_version":"atlas_coinglass_derivatives_v1","source":"CoinGlass",
              "scope":"MARKET_CONTEXT_ONLY",
              "fetched_at_utc":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "status":"UNAVAILABLE","symbols":{},"error":None}
    try:
        payload = _fetch("/funding-rate/exchange-list")
        funding = {str(x.get("symbol","")).upper():x for x in payload.get("data",[])
                   if isinstance(x,dict) and x.get("symbol")}
        good = 0
        for symbol in SYMBOLS:
            row = {"status":"UNAVAILABLE","open_interest_usd":None,
                   "open_interest_change_1h_pct":None,"open_interest_change_24h_pct":None,
                   "funding_by_exchange":{}}
            try:
                oi = _fetch("/open-interest/exchange-list",{"symbol":symbol}).get("data") or []
                if isinstance(oi,dict): oi=[oi]
                total = next((x for x in oi if isinstance(x,dict) and str(x.get("exchange","")).lower()=="all"),None)
                if total:
                    row["open_interest_usd"]=_num(total.get("open_interest_usd"))
                    row["open_interest_change_1h_pct"]=_num(total.get("open_interest_change_percent_1h"))
                    row["open_interest_change_24h_pct"]=_num(total.get("open_interest_change_percent_24h"))
                for x in (funding.get(symbol,{}).get("stablecoin_margin_list") or []):
                    if not isinstance(x,dict) or x.get("exchange") not in EXCHANGES: continue
                    rate=_num(x.get("funding_rate"))
                    if rate is None: continue
                    row["funding_by_exchange"][x["exchange"]]={"rate_pct":rate,
                      "settlement_interval_hours":_num(x.get("funding_rate_interval")),
                      "next_funding_time_ms":_num(x.get("next_funding_time"))}
                row["status"]="OK" if row["open_interest_usd"] is not None or row["funding_by_exchange"] else "UNAVAILABLE"
                good += row["status"]=="OK"
            except Exception as exc: row["error"]=type(exc).__name__
            result["symbols"][symbol]=row
        result["status"]="OK" if good==len(SYMBOLS) else ("PARTIAL" if good else "UNAVAILABLE")
        if not good: result["error"]="NO_VERIFIED_SYMBOL_DATA"
    except Exception as exc: result["error"]=type(exc).__name__
    return result

def main() -> int:
    path=Path(sys.argv[1] if len(sys.argv)>1 else "coinglass_snapshot.json")
    payload=collect()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"symbols":len(payload["symbols"]),"error":payload["error"]}))
    return 0
if __name__=="__main__": raise SystemExit(main())
