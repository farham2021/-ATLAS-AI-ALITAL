"""Private holdings to owner only; group receives public market-only analysis."""
import os,json,datetime,urllib.request,urllib.parse,io,math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from atlas_value_boards import get
IDS={"BTC":"bitcoin","ETH":"ethereum","BNB":"binancecoin","XRP":"ripple","SOL":"solana","TRX":"tron","ZEC":"zcash","HYPE":"hyperliquid","DOGE":"dogecoin","LINK":"chainlink","ADA":"cardano","SUI":"sui","HBAR":"hedera-hashgraph","AAVE":"aave","DOT":"polkadot","RNDR":"render-token","MATIC":"polygon-ecosystem-token","USDC":"usd-coin"}
def holdings(user):
 base=os.environ["SUPABASE_URL"].rstrip("/")+"/rest/v1/atlas_desk_holdings"
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 q=urllib.parse.urlencode({"user_id":"eq."+user,"select":"coin,qty,updated_at"})
 return get(base+"?"+q,{"apikey":key,"Authorization":"Bearer "+key})
def prices():
 ids=",".join(sorted(set(IDS.values())))
 key=os.getenv("COINGECKO_API_KEY","")
 headers={"User-Agent":"ATLAS-portfolio/1"}
 if key:headers["x-cg-demo-api-key"]=key
 data=get("https://api.coingecko.com/api/v3/simple/price?"+urllib.parse.urlencode({"ids":ids,"vs_currencies":"usd"}),headers)
 return {s:float(data[i]["usd"]) for s,i in IDS.items() if i in data and data[i].get("usd") is not None}
def portfolio(rows,quotes):
 out=[];missing=[]
 for row in rows:
  s=row["coin"];q=float(row["qty"])
  if s in quotes and math.isfinite(q) and q>=0:out.append((s,q*quotes[s]))
  elif s not in ("IRR","EUR","THB","GOLD18","SILVER999_FAIR","USD_IRR","USDT_IRR","عیار","وبملت","وتجارت"):missing.append(s)
 return sorted(out,key=lambda x:x[1],reverse=True),sorted(missing)
def chart(items,kind):
 fig,ax=plt.subplots(figsize=(11,7))
 fig.patch.set_facecolor("#101827");ax.set_facecolor("#101827")
 if kind=="weights":
  top=items[:10];others=sum(v for _,v in items[10:])
  if others>0:top=top+[("OTHER",others)]
  ax.pie([v for _,v in top],labels=[s for s,_ in top],autopct="%1.1f%%",textprops={"color":"white","fontsize":10})
  ax.set_title("ATLAS | Portfolio weights (priced crypto only)",color="white",pad=18)
 else:
  top=items[:15]
  ax.barh([s for s,_ in reversed(top)],[v for _,v in reversed(top)],color="#34d399")
  ax.tick_params(colors="white");ax.set_xlabel("Estimated USD value",color="white")
  ax.set_title("ATLAS | Holdings by USD value",color="white",pad=18)
  for spine in ax.spines.values():spine.set_visible(False)
 fig.text(.03,.025,"Not a verified wallet balance. Stale quantities; missing assets excluded.",color="#cbd5e1",fontsize=9)
 fig.tight_layout(rect=[0,.05,1,1])
 b=io.BytesIO();fig.savefig(b,format="png",dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
 return b.getvalue()
def public_market_chart(quotes):
 """Price-relative comparison uses public market data only, never holdings."""
 symbols=[s for s in ("BTC","ETH","SOL","BNB","XRP","ADA","DOGE","LINK","SUI","ZEC") if s in quotes]
 if len(symbols)<5:raise RuntimeError("insufficient public market prices")
 fig,ax=plt.subplots(figsize=(11,7))
 fig.patch.set_facecolor("#101827");ax.set_facecolor("#101827")
 vals=[quotes[s] for s in symbols]
 ax.barh(list(reversed(symbols)),list(reversed(vals)),color="#38bdf8")
 ax.set_xscale("log");ax.tick_params(colors="white")
 ax.set_xlabel("USD market price (log scale; NOT comparable returns)",color="white")
 ax.set_title("ATLAS | Public crypto market reference prices",color="white",pad=18)
 for spine in ax.spines.values():spine.set_visible(False)
 fig.text(.03,.025,"Public market data only. No holdings, quantities, weights or portfolio values.",color="#cbd5e1",fontsize=9)
 fig.tight_layout(rect=[0,.05,1,1])
 b=io.BytesIO();fig.savefig(b,format="png",dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
 return b.getvalue()
def send(token,chat,filename,data,caption):
 boundary="ATLASPORTFOLIOBOUNDARY"
 fields=(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n"+chat+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n"+caption+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"photo\"; filename=\""+filename+"\"\r\nContent-Type: image/png\r\n\r\n").encode())
 req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendPhoto",data=fields+data+("\r\n--"+boundary+"--\r\n").encode(),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
 with urllib.request.urlopen(req,timeout=30) as response:
  result=json.load(response)
 if not result.get("ok"):raise RuntimeError("Telegram did not accept private photo")
 print("private Telegram photo accepted",filename,"message_id",result.get("result",{}).get("message_id"))
def main():
 user=os.environ["ATLAS_PORTFOLIO_USER_ID"];chat=os.environ["ATLAS_PORTFOLIO_CHAT_ID"]
 if user!=chat:raise RuntimeError("private chat ID must equal owner user ID")
 rows=holdings(user)
 if not rows:raise RuntimeError("no holdings for configured user")
 quotes=prices()
 items,missing=portfolio(rows,quotes)
 if len(items)<5:raise RuntimeError("insufficient priced holdings; refuse delivery")
 total=sum(v for _,v in items)
 latest=max(str(x.get("updated_at","")) for x in rows)[:10]
 top=sum(v for _,v in items[:3])/total*100 if total else 0
 caption=("ATLAS | Portfolio snapshot\\nEstimated priced crypto: $"+f"{total:,.2f}"+
          "\\nTop 3 concentration: "+f"{top:.1f}%"+
          "\\nHoldings last updated: "+latest+
          "\\nUnpriced tokens: "+(", ".join(missing) if missing else "none")+
          "\\nNo live wallet sync; not a sell signal.")
 token=os.environ["TELEGRAM_TOKEN"]
 group=os.environ["TELEGRAM_GROUP_CHAT_ID"]
 if not group or group==chat:raise RuntimeError("distinct group destination required")
 for kind in ("weights","values"):
  send(token,chat,"atlas_portfolio_"+kind+".png",chart(items,kind),caption)
 send(token,group,"atlas_public_market_prices.png",public_market_chart(quotes),"ATLAS | Public crypto reference prices. No personal portfolio information. Price levels are not return comparisons or trading signals.")
 print("Owner-only portfolio charts and public group chart accepted; priced_assets",len(items),"unpriced_assets",len(missing))
if __name__=="__main__":main()
