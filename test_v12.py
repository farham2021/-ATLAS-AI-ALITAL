from pathlib import Path
import csv,io,sys,types
# Import without installing ccxt.
ccxt=types.ModuleType("ccxt"); sys.modules.setdefault("ccxt",ccxt)
sys.path.insert(0,str(Path(__file__).parent))
import bot

# Geometry / CSV test data.
rows=[
{"coin":"BTC","price":100,"support":90,"resistance":120,"entry":101,"sl":95,"tp1":110,"tp2":120,
 "h4_trend":"BULLISH","d1_trend":"BULLISH","w1_trend":"BULLISH","action":"BUY CONFIRMATION",
 "decision_state":"BUY CONFIRMATION","direction":"LONG","confidence":82,"volume_ratio":1.1,
 "market_cap":1000000,"rsi":61,"volume":10000},
{"coin":"ETH","price":100,"support":90,"resistance":110,"entry":101,"sl":95,"tp1":105,"tp2":99,
 "h4_trend":"BULLISH","d1_trend":"BULLISH","action":"BUY CONFIRMATION",
 "decision_state":"BUY CONFIRMATION","direction":"LONG","confidence":95},
]
bot.ATLAS_PERSONAL_ASSETS=["BTC","ETH"]
bot.ATLAS_METALS=()
bot.ATLAS_PRIORITY_TOP10=["BTC"]
c1=bot.generate_csv_report(rows,["BTC"],[])
assert "MarketCap" in c1
parsed=list(csv.DictReader(io.StringIO(c1)))
btc=next(x for x in parsed if x["Symbol"]=="BTC")
eth=next(x for x in parsed if x["Symbol"]=="ETH")
assert btc["Entry"]=="101.0"
assert eth["Entry"]==""
c2=bot.generate_institutional_csv(rows,["BTC"],[],{"usd":{"value":190000},"usdt":{"value":191000}})
assert "fx_usd_toman" in c2 and "fx_usdt_toman" in c2
assert "TGJU" in c2
assert bot.health_check(rows)["successful"]==2
print("PASS: v12 CSV/geometry/health unit test")
