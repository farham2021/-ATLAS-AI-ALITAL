"""ATLAS private market status report, read-only; no trade recommendation."""
import os,json,urllib.parse,urllib.request,datetime
def api(url,headers=None,data=None):
 req=urllib.request.Request(url,headers=headers or {},data=data)
 with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def main():
 base=os.environ["SUPABASE_URL"].rstrip("/")
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 token=os.environ["TELEGRAM_TOKEN"];chat=os.environ["TELEGRAM_CHAT_ID"]
 params=urllib.parse.urlencode({"select":"symbol,asset_group,captured_at,price,decision_state,public_signal","order":"captured_at.desc","limit":1000})
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
 lines=["ATLAS | گزارش واقعی وضعیت بازار","زمان UTC: "+now.strftime("%Y-%m-%d %H:%M"),
        "داده تازه: "+str(len(fresh))+" از "+str(len(latest))+" نماد",
        "صرفاً پایش بازار؛ توصیه خرید/فروش نیست.",""]
 for r in fresh[:30]:
  try:p=f'{float(r["price"]):.6g}'
  except (TypeError,ValueError):p="N/A"
  lines.append(f'{r["symbol"]}: {p} | {r.get("public_signal") or "WAIT"}')
 lines.append("سیگنال‌های تأییدنشده عمداً منتشر نمی‌شوند.")
 msg="\n".join(lines)
 result=api("https://api.telegram.org/bot"+token+"/sendMessage",data=urllib.parse.urlencode({"chat_id":chat,"text":msg}).encode())
 if not result.get("ok"):raise RuntimeError("Telegram rejected report")
 print("ATLAS report sent; message_id:",result["result"]["message_id"],"fresh_assets:",len(fresh))
if __name__=="__main__":main()
