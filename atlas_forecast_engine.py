"""ATLAS research-only forecast engine: walk-forward benchmark, no fake fallback."""
import datetime as dt,math,statistics
def forecast(series,horizon_days=90):
 daily={}
 for t,p in sorted(series,key=lambda z:z[0]):
  if t.tzinfo is None:raise ValueError("timezone-aware timestamps required")
  p=float(p)
  if math.isfinite(p) and p>0:daily[t.astimezone(dt.timezone.utc).date()]=p
 d=sorted(daily.items())
 if not d:return {"status":"UNAVAILABLE","reason":"no_valid_prices"}
 age=(dt.datetime.now(dt.timezone.utc).date()-d[-1][0]).days
 if age<0 or age>3:return {"status":"UNAVAILABLE","reason":"stale_or_future_data","age_days":age}
 if horizon_days not in (30,90,180,365):return {"status":"UNAVAILABLE","reason":"unsupported_horizon"}
 if len(d)<120 or (d[-1][0]-d[0][0]).days<119:return {"status":"UNAVAILABLE","reason":"insufficient_history"}
 folds=[]
 for i in range(90,len(d)-30,30):
  elapsed=(d[i+30][0]-d[i][0]).days;lookback=(d[i][0]-d[i-30][0]).days
  if not 24<=elapsed<=45 or not 24<=lookback<=45:continue
  origin=d[i][1];actual=d[i+30][1]
  drift=max(-.01,min(.01,.25*math.log(origin/d[i-30][1])/lookback))
  folds.append((origin,actual,origin,origin*math.exp(drift*elapsed)))
 if len(folds)<3:return {"status":"UNAVAILABLE","reason":"insufficient_walk_forward_folds","folds":len(folds)}
 errors=[statistics.mean(abs(math.log(f[1]/f[k])) for f in folds) for k in (2,3)]
 model="shrinkage_momentum" if errors[1]<errors[0]*.95 else "random_walk"
 drift=0.0
 if model=="shrinkage_momentum":
  lookback=(d[-1][0]-d[-31][0]).days
  drift=max(-.01,min(.01,.25*math.log(d[-1][1]/d[-31][1])/max(lookback,1)))
 ret=(math.exp(drift*horizon_days)-1)*100
 result={"status":"RESEARCH_ONLY","model":model,"horizon_days":horizon_days,"as_of":d[-1][0].isoformat(),"last_price":d[-1][1],"forecast_ret":round(ret,2),"walk_forward_folds":len(folds),"benchmark_mae_log":round(errors[0],5),"model_mae_log":round(errors[1] if model=="shrinkage_momentum" else errors[0],5),"fc_low":None,"fc_high":None,"interval_status":"NOT_CALIBRATED"}
 if len(folds)>=8:
  k=3 if model=="shrinkage_momentum" else 2
  residuals=sorted(math.log(f[1]/f[k]) for f in folds)
  factor=math.sqrt(horizon_days/30)
  lo=residuals[max(0,math.floor(.1*(len(residuals)-1)))]*factor
  hi=residuals[min(len(residuals)-1,math.ceil(.9*(len(residuals)-1)))]*factor
  result.update(fc_low=round((math.exp(drift*horizon_days+lo)-1)*100,2),fc_high=round((math.exp(drift*horizon_days+hi)-1)*100,2),interval_status="HEURISTIC_UNCALIBRATED")
 return result
