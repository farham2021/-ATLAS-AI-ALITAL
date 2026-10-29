"""ATLAS private market status report, read-only; no trade recommendation."""
import os,json,urllib.parse,urllib.request,urllib.error,datetime,time
def api(url,headers=None,data=None):
 req=urllib.request.Request(url,headers=headers or {},data=data)
 for attempt in range(3):
  try:
   with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
  except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as e:
   if attempt==2 or (isinstance(e,urllib.error.HTTPError) and e.code not in (429,500,502,503,504)):raise
   time.sleep(2*(attempt+1))
def main():
 base=os.environ["SUPABASE_URL"].rstrip("/")
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 token=os.environ["TELEGRAM_TOKEN"];chat=os.environ["TELEGRAM_CHAT_ID"]
 params=urllib.parse.urlencode({"select":"symbol,asset_group,captured_at,price,decision_state,public_signal,confidence,opportunity_score","order":"captured_at.desc","limit":150})
 rows=api(base+"/rest/v1/atlas_hourly_signal_snapshots?"+params,{"apikey":key,"Authorization":"Bearer "+key})
 latest={}
 for r in rows:
  if r["symbol"] not in latest:latest[r["symbol"]]=r
 if not latest:raise RuntimeError("No snapshot data; not sending stale report")
 now=datetime.datetime.now(datetime.timezone.utc)
 fresh=[]
 for r in latest.values():
  dt=datetime.datetime.fromisoformat(r["captured_at"].replace("Z","+00:00"))
  if datetime.timedelta(0)<=now-dt<=datetime.timedelta(hours=8):fresh.append(r)
 if not fresh:raise RuntimeError("All data older than 8 hours; no report sent")
 fresh.sort(key=lambda r:(r.get("asset_group") or "",r["symbol"]))
 watch=[r for r in fresh if r.get("decision_state") in ("BULLISH WATCH","BEARISH WATCH")]
 internal=[r for r in fresh if r.get("decision_state") in ("BUY CONFIRMATION","SELL CONFIRMATION")]
 tradable=[r for r in fresh if r.get("public_signal") in ("BUY","SELL")]
 lines=["ATLAS | گزارش تحلیلی بازار","UTC: "+now.strftime("%Y-%m-%d %H:%M"),
        "داده تازه: "+str(len(fresh))+" از "+str(len(latest))+" نماد",
        "سیگنال عمومی قابل معامله: "+str(len(tradable)),
        "هشدار اولیه: "+str(len(watch))+" | تأیید داخلی مسدود: "+str(len(internal)),""]
 if tradable:
  lines.append("سیگنال عمومی (طبق موتور فعلی):")
  for r in tradable[:8]:lines.append(f'{r["symbol"]}: {r["public_signal"]}')
 else:lines.append("هیچ سیگنال عمومی BUY/SELL تأییدشده‌ای موجود نیست.")
 if watch:
  lines.extend(["","هشدارهای اولیه (غیرقابل معامله):"])
  for r in watch[:10]:
   lines.append(f'{r["symbol"]}: {r["decision_state"]} | confidence {r.get("confidence") or "?"} | score {r.get("opportunity_score") or "?"}')
 if internal:
  lines.extend(["","تأییدهای داخلی که هنوز WAIT هستند:"])
  for r in internal[:10]:
   p={}
   if isinstance(p,str):
    try:p=json.loads(p)
    except ValueError:p={}
   missing=[x for x in ("entry","sl","tp1") if not p.get(x)]
   flags=[]
   # Payload intentionally excluded from bulk query to prevent oversized responses.
   flags.append("risk gate details not loaded")
   if (r.get("opportunity_score") or 0)<55:flags.append("low opportunity score")
   if not flags:flags.append("public risk gate not passed")
   lines.append(f'{r["symbol"]}: {r["decision_state"]} | confidence {r.get("confidence") or "?"} | '+", ".join(flags))
 lines.extend(["","قیمت‌های پایش‌شده:"])
 for r in fresh[:30]:
  try:p=f'{float(r["price"]):.6g}'
  except (TypeError,ValueError):p="N/A"
  lines.append(f'{r["symbol"]}: {p} | {r.get("public_signal") or "WAIT"}')
 lines.append("WATCH/CONFIRMATION داخلی توصیه معامله نیست. PAPER فقط.")
 msg="\n".join(lines)
 result=api("https://api.telegram.org/bot"+token+"/sendMessage",data=urllib.parse.urlencode({"chat_id":chat,"text":msg}).encode())
 if not result.get("ok"):raise RuntimeError("Telegram rejected report")
 print("ATLAS report sent; message_id:",result["result"]["message_id"],"fresh_assets:",len(fresh))
if __name__=="__main__":main()
