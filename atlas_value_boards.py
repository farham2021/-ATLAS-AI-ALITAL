"""ATLAS comparative value boards. Shadow-first: no fabricated returns or forecasts."""
import os,json,urllib.request,urllib.parse,datetime,statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from pathlib import Path

IRAN={"XAUUSD":"Gold (global USD)","XAGUSD":"Silver (global USD)","COPPER":"Copper (global USD)","SILVER999_FAIR":"Silver 999 fair (IRR)","USD_IRR":"USD/IRR"}
CRYPTO=("bitcoin","ethereum","solana","binancecoin","ripple","chainlink","avalanche-2","sui","dogecoin","cardano")
def get(url,headers=None):
 req=urllib.request.Request(url,headers=headers or {"User-Agent":"ATLAS-value-board/1"})
 with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def supa(table,symbol):
 base=os.environ["SUPABASE_URL"].rstrip("/")+"/rest/v1/"+table
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 q=urllib.parse.urlencode({"symbol":"eq."+symbol,"select":"captured_at,price","order":"captured_at.desc","limit":"600"})
 rows=get(base+"?"+q,{"apikey":key,"Authorization":"Bearer "+key})
 out=[]
 for row in reversed(rows):
  try:
   t=datetime.datetime.fromisoformat(row["captured_at"].replace("Z","+00:00"))
   v=float(row["price"])
   if v>0:out.append((t,v))
  except (ValueError,TypeError,KeyError):pass
 return out
def change(series,days):
 if len(series)<2:return None
 end,latest=series[-1]
 if (datetime.datetime.now(datetime.timezone.utc)-end).total_seconds()>72*3600:return None
 candidates=[(abs((end-t).total_seconds()-days*86400),v) for t,v in series[:-1] if (end-t).total_seconds()>=days*86400*.85]
 if not candidates:return None
 _,baseline=min(candidates)
 return (latest/baseline-1)*100
def crypto_series(coin):
 key=os.getenv("COINGECKO_API_KEY","")
 headers={"User-Agent":"ATLAS-value-board/1"}
 if key:headers["x-cg-demo-api-key"]=key
 url="https://api.coingecko.com/api/v3/coins/"+urllib.parse.quote(coin)+"/market_chart?vs_currency=usd&days=90"
 raw=get(url,headers)
 return [(datetime.datetime.fromtimestamp(t/1000,datetime.timezone.utc),float(p)) for t,p in raw.get("prices",[]) if p>0]
def render(title,items,path):
 fig,ax=plt.subplots(figsize=(13,7.5))
 fig.patch.set_facecolor("#101827");ax.set_facecolor("#101827")
 labels=[x[0] for x in items];values=[x[1] for x in items]
 colors=["#34d399" if v is not None and v>=0 else "#fb7185" if v is not None else "#94a3b8" for v in values]
 plotted=[v if v is not None else 0 for v in values]
 ax.barh(labels,plotted,color=colors,height=.62)
 ax.invert_yaxis();ax.axvline(0,color="#cbd5e1",lw=.8)
 for i,v in enumerate(values):
  ax.text((plotted[i]+(1 if plotted[i]>=0 else -1)),i,"N/A" if v is None else f"{v:+.1f}%",color="white",va="center",ha="left" if plotted[i]>=0 else "right",fontsize=10)
 ax.tick_params(colors="white",labelsize=10);[s.set_visible(False) for s in ax.spines.values()]
 ax.set_title(title,color="white",fontsize=17,pad=22)
 ax.set_xlabel("Approximate trailing 30-day return (%) — not a future forecast",color="#cbd5e1")
 fig.text(.02,.02,"Missing/stale history = N/A. Different currencies are NOT directly comparable. No guaranteed future returns.",color="#cbd5e1",fontsize=9)
 fig.tight_layout(rect=[0,.045,1,1]);fig.savefig(path,dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
def main():
 output=Path(os.getenv("ATLAS_VALUE_OUTPUT","value_boards"));output.mkdir(parents=True,exist_ok=True)
 iran=[]
 for sym,label in IRAN.items():
  try:
   table="atlas_iran_fx_snapshots" if sym=="USD_IRR" else "atlas_market_snapshots"
   iran.append((label,change(supa(table,sym),30)))
  except Exception as e:
   print("::warning::",sym,type(e).__name__,str(e)[:120]);iran.append((label,None))
 for label in ("Housing (no verified series)","Cars (no verified series)","TSE index (no verified index series)"):
  iran.append((label,None))
 crypto=[]
 for coin in CRYPTO:
  try:crypto.append((coin,change(crypto_series(coin),30)))
  except Exception as e:
   print("::warning::",coin,type(e).__name__,str(e)[:120]);crypto.append((coin,None))
 render("ATLAS | Iran assets — observed 30-day returns",iran,output/"atlas_iran_value.png")
 render("ATLAS | Crypto — observed 30-day returns",crypto,output/"atlas_crypto_value.png")
 print(json.dumps({"iran":iran,"crypto":crypto,"files":["atlas_iran_value.png","atlas_crypto_value.png"]},ensure_ascii=False))
 if os.getenv("ATLAS_VALUE_SEND_TELEGRAM")=="1":
  if not any(v is not None for _,v in iran+crypto):raise RuntimeError("no validated returns: refuse to deliver")
  token=os.environ["TELEGRAM_TOKEN"];chat=os.environ["TELEGRAM_GROUP_CHAT_ID"]
  for name,caption in (("atlas_iran_value.png","ATLAS Iran | Historical returns only; future valuation needs fundamentals and comparable prices."),("atlas_crypto_value.png","ATLAS Crypto | Historical returns only; not a buy recommendation.")):
   boundary="ATLASBOUNDARY"
   data=(output/name).read_bytes()
   body=(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n"+str(chat)+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n"+caption+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"photo\"; filename=\""+name+"\"\r\nContent-Type: image/png\r\n\r\n").encode()+data+("\r\n--"+boundary+"--\r\n").encode())
   req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendPhoto",data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary})
   with urllib.request.urlopen(req,timeout=35) as response:
    result=json.load(response)
    if not result.get("ok"):raise RuntimeError("Telegram photo delivery failed")
    print("Telegram photo delivered",name,result.get("result",{}).get("message_id"))
if __name__=="__main__":main()
