"""ATLAS Telegram CSV risk digest: one document per destination, no individual alerts."""
import csv,io,json,urllib.parse,urllib.request,datetime,os

FIELDS=("time_utc","symbol","direction","severity","price_usd","change_24h_pct","volume_ratio","signals","tradingview_url")
def chart_url(symbol):
    asset=symbol.upper().removesuffix("USDT")
    if not asset.isalnum():raise ValueError("invalid symbol")
    return "https://www.tradingview.com/chart/?symbol="+urllib.parse.quote("COINBASE:"+asset+"USD",safe="")
def csv_bytes(items,at=None):
    at=at or datetime.datetime.now(datetime.timezone.utc)
    out=io.StringIO(newline="")
    w=csv.DictWriter(out,fieldnames=FIELDS,lineterminator="\r\n");w.writeheader()
    for symbol,result in items:
        level=result["level"]
        if level=="NONE":continue
        def safe(v):
            s=str(v)
            return "'"+s if s.lstrip().startswith(("=","+","-","@","\t","\r")) else s
        w.writerow(dict(time_utc=at.isoformat(),symbol=symbol,direction="GROWTH" if level.startswith("GROWTH") else "DROP",severity=level,price_usd=result["price"],change_24h_pct=result["decline24"],volume_ratio=result["volume_ratio"],signals=safe("; ".join(result["flags"])),tradingview_url=chart_url(symbol) if result.get("market","CRYPTO")=="CRYPTO" else ""))
    return out.getvalue().encode("utf-8-sig")
def send_document(token,chat_id,data,filename,caption):
    boundary="----ATLASCSVBOUNDARY"
    fields={"chat_id":str(chat_id),"caption":caption}
    body=bytearray()
    for key,value in fields.items():
        body+=("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+key+"\"\r\n\r\n"+value+"\r\n").encode()
    body+=("--"+boundary+"\r\nContent-Disposition: form-data; name=\"document\"; filename=\""+filename+"\"\r\nContent-Type: text/csv\r\n\r\n").encode()
    body+=data+b"\r\n"+("--"+boundary+"--\r\n").encode()
    req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendDocument",data=bytes(body),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    with urllib.request.urlopen(req,timeout=35) as response:
        payload=json.load(response)
    if payload.get("ok") is not True or not payload.get("result",{}).get("message_id"):
        raise RuntimeError("Telegram document delivery unconfirmed")
    return payload["result"]["message_id"]
def send_digest(items):
    if not items:return []
    token=os.environ["TELEGRAM_TOKEN"]
    chats=list(dict.fromkeys(filter(None,(os.environ.get("TELEGRAM_GROUP_CHAT_ID"),os.environ.get("ATLAS_PRIVATE_CHAT_ID")))))
    if not chats:raise ValueError("no destination chats")
    data=csv_bytes(items)
    drops=sum(not x["level"].startswith("GROWTH") for _,x in items)
    caption=f"ATLAS risk digest | {drops} drop warnings, {len(items)-drops} growth warnings. Open CSV for TradingView links."
    filename="atlas_risk_"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M")+".csv"
    return [send_document(token,chat,data,filename,caption) for chat in chats]
