# ============================================================
# ATLAS AI — SMOKE TEST
# ============================================================
import bot
def main():
    for name in ("asset_block","action_emoji","build_report","build_market_report","build_personal_report","_levels"):
        assert hasattr(bot,name), f"missing: {name}"
    a={"symbol":"BTC","price":100,"change24":"+1%","rsi":60,"macd":"BULLISH","h4":"BULLISH","d1":"BULLISH","w1":"MIXED","support":95,"resistance":110,"confidence":50,"signal":"WAIT"}
    text=bot.asset_block(a)
    for k in ("Entry:","SL:","TP1:","TP2:","TP3:","TP4:","R/R(TP2):"): assert k in text,k
    p=bot._levels(100,95,110,"LONG"); assert abs(p["rr"]-abs(100-p["tp2"])/abs(100-p["sl"]))<1e-12
    assert "ATLAS AI" in bot.build_report("PERSONAL",[a])
    assert "ATLAS AI" in bot.build_report("MARKET",[a])
    assert "ATLAS AI" in bot.build_report("BOTH",[a])
    print("PASS: ATLAS two-engine smoke test")
if __name__=="__main__":main()
