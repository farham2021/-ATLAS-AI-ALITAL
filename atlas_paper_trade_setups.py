"""ATLAS actionable PAPER research: closed candles, explicit BUY/SELL/WATCH/WAIT, TP/SL.
No live execution. Uses cached exchange candles; does not guarantee performance.
"""
import os,json,urllib.request,urllib.parse,datetime,statistics,math,csv,io
def request(url,headers=None,data=None):
 with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {},data=data),timeout=30) as r:return json.load(r)
def main():
 base=os.environ["SUPABASE_URL"].rstrip("/");key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 q=urllib.parse.urlencode({"select":"symbol,timeframe,provider,rows_json,last_closed_ts,updated_at","limit":150})
 rows=request(base+"/rest/v1/atlas_ohlcv_closed_cache?"+q,{"apikey":key,"Authorization":"Bearer "+key})
 now=datetime.datetime.now(datetime.timezone.utc)
 outputs=[]
 for rec in rows:
  try:
   tf=str(rec["timeframe"]).lower()
   if tf not in ("4h","1h"):continue
   updated=datetime.datetime.fromisoformat(rec["updated_at"].replace("Z","+00:00"))
   if now-updated>datetime.timedelta(hours=8):continue
   bars=json.loads(rec["rows_json"])
   if isinstance(bars,dict):bars=bars.get("rows",[])
   if len(bars)<65:continue
   bars=sorted(bars,key=lambda x:x[0])
   # Exclude potentially still-open last candle based on candle timestamp.
   width=4*3600000 if tf=="4h" else 3600000
   bars=[x for x in bars if int(x[0])+width<=int(now.timestamp()*1000)]
   if len(bars)<65:continue
   closes=[float(x[4]) for x in bars];highs=[float(x[2]) for x in bars];lows=[float(x[3]) for x in bars]
   p=closes[-1];prev=closes[-2]
   if not (p>0 and prev>0):continue
   trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(len(bars)-14,len(bars))]
   atr=statistics.mean(trs)
   if not 0<atr/p<0.10:continue
   sma20=statistics.mean(closes[-20:]);sma50=statistics.mean(closes[-50:])
   hi=max(highs[-21:-1]);lo=min(lows[-21:-1])
   vol=[float(x[5]) for x in bars];vbase=statistics.mean(vol[-21:-1]);vr=vol[-1]/vbase if vbase>0 else 0
   direction=1 if p>hi and sma20>sma50 and vr>=1.2 else -1 if p<lo and sma20<sma50 and vr>=1.2 else 0
   near=1 if p>hi*0.985 and sma20>sma50 else -1 if p<lo*1.015 and sma20<sma50 else 0
   status="BUY" if direction==1 else "SELL" if direction==-1 else "WATCH" if near else "WAIT"
   result={"symbol":rec["symbol"],"tf":tf,"status":status,"price":p,"volume_ratio":round(vr,2),"source":rec["provider"]}
   if direction:
    entry=p;stop=p-direction*1.5*atr;tp1=p+direction*3*atr;tp2=p+direction*4.5*atr
    if stop<=0 or tp1<=0 or tp2<=0:continue
    result.update(entry=round(entry,8),sl=round(stop,8),tp1=round(tp1,8),tp2=round(tp2,8),rr=2.0,
                  side="LONG" if direction==1 else "SHORT (derivatives only)")
   elif near:result["watch_trigger"]=round(hi if near==1 else lo,8)
   outputs.append(result)
  except (ValueError,KeyError,TypeError,IndexError,ZeroDivisionError):continue
 # Deduplicate by symbol, prefer 4h for slower false-positive control.
 best={}
 for x in sorted(outputs,key=lambda x:0 if x["tf"]=="4h" else 1):best.setdefault(x["symbol"],x)
 outputs=list(best.values());rank={"BUY":0,"SELL":0,"WATCH":1,"WAIT":2}
 outputs.sort(key=lambda x:(rank[x["status"]],x["symbol"]))
 lines=["ATLAS | PAPER TRADE SETUPS","UTC "+now.strftime("%Y-%m-%d %H:%M"),
        "Closed OHLCV / breakout + trend + volume / R:R 2+",
        "Unvalidated strategy; NOT an execution instruction.",""]
 for x in outputs[:30]:
  s=f'{x["symbol"]} {x["tf"]}: {x["status"]} | {x["price"]:.7g}'
  if x["status"] in ("BUY","SELL"):
   s+=f' | Entry {x["entry"]} SL {x["sl"]} TP1 {x["tp1"]} TP2 {x["tp2"]} | {x["side"]}'
  elif x["status"]=="WATCH":s+=f' | trigger {x["watch_trigger"]}'
  lines.append(s)
 if not outputs:lines.append("NO TRADE: no sufficiently fresh valid closed candles.")
 msg="\n".join(lines)
 print(json.dumps({"assets":len(outputs),"statuses":{s:sum(x["status"]==s for x in outputs) for s in ("BUY","SELL","WATCH","WAIT")}},ensure_ascii=False))
 # CSV export of the exact same signals; image generation is best-effort.
 csvbuf=io.StringIO();cols=["symbol","tf","status","price","volume_ratio","entry","sl","tp1","tp2","rr","watch_trigger","side","source"]
 writer=csv.DictWriter(csvbuf,fieldnames=cols,extrasaction="ignore");writer.writeheader();writer.writerows(outputs)
 def multipart(method,filename,blob,mime,caption):
  boundary="ATLASBoundary123456789"
  parts=[]
  for name,value in (("chat_id",chat),("caption",caption)):
   parts.append(("--"+boundary+"\\r\\nContent-Disposition: form-data; name=\\\""+name+"\\\"\\r\\n\\r\\n"+str(value)+"\\r\\n").encode())
  field="photo" if method=="sendPhoto" else "document"
  parts.append(("--"+boundary+"\\r\\nContent-Disposition: form-data; name=\\\""+field+"\\\"; filename=\\\""+filename+"\\\"\\r\\nContent-Type: "+mime+"\\r\\n\\r\\n").encode()+blob+b"\\r\\n")
  parts.append(("--"+boundary+"--\\r\\n").encode())
  return request("https://api.telegram.org/bot"+token+"/"+method,headers={"Content-Type":"multipart/form-data; boundary="+boundary},data=b"".join(parts))
 def render_png():
  import matplotlib
  matplotlib.use("Agg")
  import matplotlib.pyplot as plt
  from matplotlib.backends.backend_agg import FigureCanvasAgg
  fig,ax=plt.subplots(figsize=(14,max(4,2+0.35*min(len(outputs),30))),dpi=140)
  ax.axis("off")
  headers=["Asset","TF","Signal","Price","Entry","SL","TP1","TP2"]
  def fmt(v):return "" if v is None else f"{v:.7g}" if isinstance(v,(float,int)) else str(v)
  cells=[[fmt(x.get(k)) for k in ("symbol","tf","status","price","entry","sl","tp1","tp2")] for x in outputs[:30]]
  if not cells:cells=[["NO DATA"]+[""]*7]
  table=ax.table(cellText=cells,colLabels=headers,loc="center",cellLoc="center")
  table.auto_set_font_size(False);table.set_fontsize(9);table.scale(1,1.4)
  fig.suptitle("ATLAS | PAPER SETUPS | "+now.strftime("%Y-%m-%d %H:%M UTC"),fontsize=14)
  buf=io.BytesIO();fig.savefig(buf,format="png",bbox_inches="tight");plt.close(fig)
  return buf.getvalue()
 if os.getenv("ATLAS_PAPER_TELEGRAM","0")=="1":
  token=os.environ["TELEGRAM_TOKEN"];chat=os.environ["TELEGRAM_CHAT_ID"]
  try:
   response=multipart("sendDocument","atlas_paper_setups.csv",csvbuf.getvalue().encode("utf-8-sig"),"text/csv","ATLAS PAPER | CSV")
   print("CSV sent",response.get("ok",False))
  except Exception as exc:print("CSV delivery failed",type(exc).__name__)
  try:
   response=multipart("sendPhoto","atlas_paper_setups.png",render_png(),"image/png","ATLAS PAPER | PNG")
   print("PNG sent",response.get("ok",False))
  except Exception as exc:print("PNG delivery failed",type(exc).__name__)
  for part in [msg[i:i+3500] for i in range(0,len(msg),3500)]:
   result=request("https://api.telegram.org/bot"+token+"/sendMessage",data=urllib.parse.urlencode({"chat_id":chat,"text":part}).encode())
   if not result.get("ok"):raise RuntimeError("Telegram send rejected")
   print("Telegram message_id",result["result"]["message_id"])
 else:print(msg)
if __name__=="__main__":main()
