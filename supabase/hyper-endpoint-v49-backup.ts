// ATLAS Desk webhook — Multi-Asset Chat Plane
// Live slug: hyper-endpoint
// Reads stored Supabase state only. No fresh market analysis is run here.
// Backward-compatible: atlas_desk_holdings remains (user_id, coin, qty).
// Portfolio registration is independent from market-state availability for known assets.

const PERSONAL = [
  "BTC","ETH","BNB","XRP","SOL","TRX","HYPE","DOGE","ADA","MATIC",
  "LINK","XLM","SUI","AVAX","LTC","SHIB","HBAR","DOT","BCH","XMR",
  "NEAR","ONDO","TAO","ZEC",
];

// Assets users may keep in a private portfolio even when the Analysis Plane
// does not currently publish a snapshot for them. Missing state never fabricates a price.
// Private portfolio registry: current CoinGecko Top-100 market-cap symbols
// (snapshot: 2026-09-18) + ATLAS compatibility symbols/aliases.
// Registration does NOT require an Analysis Plane snapshot; missing state never
// fabricates a price. PERSONAL remains the analysis universe, not the hold limit.
const HOLDABLE_CRYPTO = new Set([
  ...PERSONAL,
  "BTC","ETH","BNB","XRP","USDC","SOL","TRX","ZEC","FIGR_HELOC","HYPE",
  "DOGE","XMR","WBT","USDS","RAIN","LINK","ADA","LEO","XLM","UNI",
  "BCH","USDE","NEAR","DAI","USD1","LTC","CC","GRAM","AVAX","HBAR",
  "SUI","USDG","SHIB","M","CRO","TAO","PYUSD","XAUT","USYC","OKB",
  "BUIDL","RLUSD","USDY","AAVE","ASTER","PUMP","MNT","DOT","ONDO","PAXG",
  "WLFI","BTW","MORPHO","ENA","SKY","PEPE","ICP","WLD","HTX","USDD",
  "ARB","BGB","U","EURSAFO","USDGO","USDF","BFUSD","ETC","VVV","LIT",
  "POL","GT","KAS","KCS","BCAP","JST","PI","QNT","ATOM","JUP",
  "ALGO","CAKE","NEXO","RENDER","EUTBL","JAAA","DASH","FIL","USTB","ETHFI",
  "GHO","VET","STABLE","INJ","AERO","BDX","AKE","APT","TRUMP","TON",
  "RNDR",
]);

const ALIASES: Record<string,string> = {
  BITCOIN:"BTC",
  ETHEREUM:"ETH",
  POL:"MATIC",
  POLYGON:"MATIC",
  TRON:"TRX",
  RNDR:"RNDR",
  RENDER:"RNDR",
  TON:"TON",
  TONCOIN:"TON",
  POLKADOT:"DOT",
  CARDANO:"ADA",
  SOLANA:"SOL",
  DOGECOIN:"DOGE",
  LITECOIN:"LTC",
  AVALANCHE:"AVAX",
  CHAINLINK:"LINK",

  EUR:"EUR",
  EURO:"EUR",
  "یورو":"EUR",

  THB:"THB",
  BAHT:"THB",
  "بات":"THB",
  "بات_تایلند":"THB",

  IRR:"IRR",
  RIAL:"IRR",
  "ریال":"IRR",

  USD:"USD_IRR",
  DOLLAR:"USD_IRR",
  "دلار":"USD_IRR",

  USDT:"USDT_IRR",
  TETHER:"USDT_IRR",
  "تتر":"USDT_IRR",

  GOLD:"GOLD18",
  GOLD18:"GOLD18",
  "طلا":"GOLD18",
  "طلای18":"GOLD18",
  "طلای۱۸":"GOLD18",

  COIN:"COIN_EMAMI",
  EMAMI:"COIN_EMAMI",
  "سکه":"COIN_EMAMI",
  "امامی":"COIN_EMAMI",

  SILVER:"SILVER999",
  SILVER999:"SILVER999",
  "نقره":"SILVER999",

  SILVERFAIR:"SILVER999_FAIR",
  SILVER999_FAIR:"SILVER999_FAIR",
  "نقره_منصفانه":"SILVER999_FAIR",

  XAU:"XAUUSD",
  XAUUSD:"XAUUSD",

  XAG:"XAGUSD",
  XAGUSD:"XAGUSD",

  COPPER:"COPPER",
  "مس":"COPPER",
};

const FIXED_CLASS: Record<string,string> = {
  // Fiat holdings. EUR/THB/IRR are real portfolio assets; USD_IRR/USDT_IRR
  // remain market-rate symbols for backward compatibility with the live Desk.
  EUR:"FX",
  THB:"FX",
  IRR:"FX",
  USD_IRR:"FX",
  USDT_IRR:"FX",

  GOLD18:"METAL_IRAN",
  COIN_EMAMI:"METAL_IRAN",
  SILVER999:"METAL_IRAN",
  SILVER999_FAIR:"METAL_IRAN",

  XAUUSD:"METAL_GLOBAL",
  XAGUSD:"METAL_GLOBAL",
  COPPER:"METAL_GLOBAL",
};

// Registration and valuation are intentionally separate. Known ATLAS assets
// may be held even when no current market snapshot exists. In that case the
// holding is stored and portfolio valuation simply remains unavailable.
function isKnownHoldAsset(symbol:string) {
  return HOLDABLE_CRYPTO.has(symbol) || Boolean(FIXED_CLASS[symbol]);
}

function riskPct() {
  return 1.5;
}

function nowIso() {
  return new Date().toISOString();
}

function normFa(s:string) {
  return String(s || "")
    .trim()
    .replace(/ي/g,"ی")
    .replace(/ك/g,"ک")
    .replace(/\u200c/g,"")
    .replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d).toString())
    .replace(/[٠-٩]/g, d => "٠١٢٣٤٥٦٧٨٩".indexOf(d).toString());
}

function canon(raw:string) {
  const x = normFa(raw);
  const up = x.toUpperCase();

  return (
    ALIASES[up] ||
    ALIASES[x] ||
    (HOLDABLE_CRYPTO.has(up) ? up : x)
  );
}

function fmtQty(x:any) {
  const n = Number(x);

  if (!Number.isFinite(n)) return "-";

  if (n >= 100) {
    return n.toLocaleString(
      "en-US",
      { maximumFractionDigits: 2 }
    );
  }

  if (n >= 1) {
    return n.toLocaleString(
      "en-US",
      { maximumFractionDigits: 4 }
    );
  }

  return String(n);
}

function fmtPx(x:any) {
  const n = Number(x);

  if (!Number.isFinite(n)) return "-";

  if (Math.abs(n) >= 1000) {
    return n.toLocaleString(
      "en-US",
      { maximumFractionDigits: 2 }
    );
  }

  if (Math.abs(n) >= 1) {
    return n.toLocaleString(
      "en-US",
      { maximumFractionDigits: 4 }
    );
  }

  return n.toFixed(6);
}

function payloadOf(r:any) {
  return (
    r?.payload &&
    typeof r.payload === "object"
  )
    ? r.payload
    : {};
}

function unitOf(r:any) {
  const p = payloadOf(r);

  return String(
    p.unit_canonical ||
    p.unit ||
    r?.unit ||
    ""
  ).toUpperCase();
}

function rawPrice(r:any) {
  for (
    const v of [
      r?.price,
      r?.last_price,
      r?.close,
      r?.pl,
      r?.pc,
    ]
  ) {
    const n = Number(v);

    if (Number.isFinite(n)) {
      return n;
    }
  }

  return null;
}

function displayPrice(
  symbol:string,
  row:any
) {
  let p = rawPrice(row);

  if (p == null) return null;

  const u = unitOf(row);

  // Canonical ATLAS FX is IRR.
  // Historical rows may already be Toman.
  if (
    symbol === "USD_IRR" ||
    symbol === "USDT_IRR"
  ) {
    if (
      u.includes("TOMAN") ||
      u.includes("تومان")
    ) {
      return {
        value:p,
        unit:"تومان"
      };
    }

    if (
      u.includes("IRR") ||
      p >= 1_000_000
    ) {
      return {
        value:p / 10,
        unit:"تومان"
      };
    }

    return {
      value:p,
      unit:"تومان"
    };
  }

  // SILVER999_FAIR is kept separate from
  // domestic retail SILVER999.
  if (symbol === "SILVER999_FAIR") {
    if (u.includes("IRR")) {
      return {
        value:p / 10,
        unit:"تومان/گرم"
      };
    }

    return {
      value:p,
      unit:"تومان/گرم"
    };
  }

  if (
    [
      "GOLD18",
      "COIN_EMAMI",
      "SILVER999"
    ].includes(symbol)
  ) {
    return {
      value:p,
      unit:"تومان"
    };
  }

  // Global metals.
  // COPPER currently comes from Yahoo HG=F when BrsApi has no copper row.
  // HG=F is a COMEX copper-futures proxy quoted in USD per pound.
  if (symbol === "COPPER") {
    const pay = payloadOf(row);
    const sourceSymbol =
      String(pay?.source_symbol || "")
        .toUpperCase();

    if (
      u.includes("USD_PER_LB") ||
      u.includes("USD/LB") ||
      sourceSymbol === "HG=F"
    ) {
      return {
        value:p,
        unit:"USD/lb"
      };
    }

    // Fail-safe: if a future provider changes the copper unit,
    // do not invent USD/lb without explicit metadata.
    return {
      value:p,
      unit:"USD"
    };
  }

  if (
    [
      "XAUUSD",
      "XAGUSD"
    ].includes(symbol)
  ) {
    return {
      value:p,
      unit:"USD"
    };
  }

  // TSE/Fund: don't invent a currency unit.
  return {
    value:p,
    unit:""
  };
}

function parseCapital(text:string) {
  const m = String(text || "")
    .trim()
    .match(
      /^(?:\/)?(?:capital|equity|cap|deskcapital|سرمایه|موجودی)\s+([0-9]+(?:[.,][0-9]+)?)\s*(k|usdt|usd|tether|dollar|دلار|تتر)?$/i
    );

  if (!m) return null;

  let amount = parseFloat(
    m[1].replace(",",".")
  );

  if (!Number.isFinite(amount)) {
    return null;
  }

  if (
    (m[2] || "").toLowerCase() === "k"
  ) {
    amount *= 1000;
  }

  return amount;
}

function parseHold(text:string) {
  const m = normFa(text).match(
    /^(?:\/)?(?:hold|دارایی)(?:@\w+)?\s+([^\s]+)\s+([0-9]+(?:[.,][0-9]+)?)$/i
  );

  if (!m) return null;

  return {
    coin:canon(m[1]),
    qty:parseFloat(
      m[2].replace(",",".")
    )
  };
}

function parseUnhold(text:string) {
  const m = normFa(text).match(
    /^(?:\/)?(?:unhold|حذف)(?:@\w+)?\s+([^\s]+)(?:\s+[0-9]+(?:[.,][0-9]+)?)?$/i
  );

  return m
    ? canon(m[1])
    : null;
}

function isStatus(t:string) {
  return /^(?:\/)?(?:desk|status|میز|وضعیت)$/i
    .test(normFa(t));
}

function isHelp(t:string) {
  return /^(?:\/)?(?:start|help|راهنما)(?:@\w+)?(?:\s+desk)?$/i
    .test(normFa(t));
}

function isPortfolio(t:string) {
  return /^(?:\/)?(?:portfolio|holds|bag|سبد|داراییها|دارایی‌ها)$/i
    .test(normFa(t));
}


function parseRiskProfile(t:string) {
  const m=normFa(t).match(/^(?:\/)?(?:risk|ریسک)(?:@\w+)?\s+(conservative|moderate|aggressive|محافظه.?کار|متعادل|تهاجمی)$/i);
  if (!m) return null;
  const x=m[1].toLowerCase();
  if (x.startsWith("محافظه") || x==="conservative") return "CONSERVATIVE";
  if (x==="متعادل" || x==="moderate") return "MODERATE";
  return "AGGRESSIVE";
}


// ============================================================
// MULTI-ASSET INVESTOR PROFILE — private Chat Plane preferences
// Stores user intent only. Analysis remains in the Analysis Plane.
// ============================================================
const MA_HORIZON: Record<string,string> = {
  short:"SHORT_TERM", short_term:"SHORT_TERM", "کوتاه":"SHORT_TERM", "کوتاه‌مدت":"SHORT_TERM", "کوتاهمدت":"SHORT_TERM",
  mid:"MID_TERM", medium:"MID_TERM", mid_term:"MID_TERM", "میان":"MID_TERM", "میان‌مدت":"MID_TERM", "میانمدت":"MID_TERM",
  long:"LONG_TERM", long_term:"LONG_TERM", "بلند":"LONG_TERM", "بلندمدت":"LONG_TERM", "بلند‌مدت":"LONG_TERM"
};
const MA_GOAL: Record<string,string> = {
  fast_profit:"FAST_PROFIT", fast:"FAST_PROFIT", "سودسریع":"FAST_PROFIT", "سود_سریع":"FAST_PROFIT",
  growth:"GROWTH", "رشد":"GROWTH", "رشدبلندمدت":"GROWTH", "رشد_بلندمدت":"GROWTH",
  capital_preservation:"CAPITAL_PRESERVATION", preservation:"CAPITAL_PRESERVATION", "حفظارزش":"CAPITAL_PRESERVATION", "حفظ_ارزش":"CAPITAL_PRESERVATION",
  inflation_hedge:"INFLATION_HEDGE", hedge:"INFLATION_HEDGE", "پوششتورمی":"INFLATION_HEDGE", "پوشش_تورمی":"INFLATION_HEDGE",
  diversification:"DIVERSIFICATION", diversify:"DIVERSIFICATION", "تنوع":"DIVERSIFICATION", "تنوعبخشی":"DIVERSIFICATION", "تنوع_بخشی":"DIVERSIFICATION"
};
function isProfile(t:string) { return /^(?:\/)?(?:profile|پروفایل)(?:@\w+)?$/i.test(normFa(t)); }
function parseHorizon(t:string) {
  const m=normFa(t).match(/^(?:\/)?(?:horizon|افق)(?:@\w+)?\s+(.+)$/i); if(!m) return null;
  const k=m[1].trim().toLowerCase().replace(/\s+/g,"_"); return MA_HORIZON[k]||null;
}
function parseGoal(t:string) {
  const m=normFa(t).match(/^(?:\/)?(?:goal|هدف)(?:@\w+)?\s+(.+)$/i); if(!m) return null;
  const k=m[1].trim().toLowerCase().replace(/\s+/g,"_"); return MA_GOAL[k]||null;
}
function parseProfileCapital(t:string) {
  const m=normFa(t).match(/^(?:\/)?(?:capital|سرمایه)(?:@\w+)?\s+([0-9]+(?:[.,][0-9]+)?)\s*(USD|USDT|IRR|دلار|تتر|ریال)$/i);
  if(!m) return null; const amount=Number(m[1].replace(",",".")); if(!Number.isFinite(amount)||amount<=0) return {error:"amount"};
  const u=m[2].toUpperCase(); return {amount, currency:(u==="IRR"||m[2]==="ریال")?"IRR":"USD"};
}
function parseSplit(t:string) {
  const x=normFa(t); if(!/^(?:\/)?(?:split|تقسیم)(?:@\w+)?\s+/i.test(x)) return null;
  const body=x.replace(/^(?:\/)?(?:split|تقسیم)(?:@\w+)?\s+/i,"");
  const get=(names:string[])=>{ for(const n of names){ const m=body.match(new RegExp("(?:^|\\s)"+n+"\\s+([0-9]+(?:[.,][0-9]+)?)","i")); if(m) return Number(m[1].replace(",",".")); } return null; };
  const crypto=get(["crypto","کریپتو"]), stocks=get(["tse","stocks","stock","بورس"]), metals=get(["metals","metal","فلزات","فلز"]);
  if([crypto,stocks,metals].some(v=>v===null||!Number.isFinite(Number(v))||Number(v)<0||Number(v)>100)) return {error:"format"};
  if(Math.abs(Number(crypto)+Number(stocks)+Number(metals)-100)>0.001) return {error:"sum",sum:Number(crypto)+Number(stocks)+Number(metals)};
  return {crypto_pct:crypto,stocks_pct:stocks,metals_pct:metals};
}
function parseListPref(t:string, cmd:string, fa:string) {
  const re=new RegExp("^(?:\\/)?(?:"+cmd+"|"+fa+")(?:@\\w+)?\\s+(.+)$","i"); const m=normFa(t).match(re); if(!m) return null;
  const raw=m[1].trim(); if(!raw) return [];
  return raw.split(/[،,]+|\s+/).map(x=>x.trim()).filter(Boolean).slice(0,30);
}
async function multiProfile(env:any,userId:string) {
  const rows=await sb(env,"GET","/rest/v1/atlas_desk_multiasset_preferences?user_id=eq."+encodeURIComponent(userId)+"&select=*&limit=1");
  return Array.isArray(rows)&&rows.length?rows[0]:null;
}
async function patchMultiProfile(env:any,userId:string, patch:any) {
  return await sb(env,"POST","/rest/v1/atlas_desk_multiasset_preferences?on_conflict=user_id",{user_id:userId,...patch,updated_at:nowIso()});
}
async function multiRisk(env:any,userId:string) {
  const rows=await sb(env,"GET","/rest/v1/atlas_desk_allocation_preferences?user_id=eq."+encodeURIComponent(userId)+"&select=risk_profile&limit=1");
  return Array.isArray(rows)&&rows.length?String(rows[0].risk_profile||"MODERATE"):"MODERATE";
}
async function formattedMultiProfile(env:any,userId:string) {
  return fmtMultiProfile(await multiProfile(env,userId),await multiRisk(env,userId));
}
function fmtMultiProfile(p:any, riskFallback?:string) {
  p=p||{}; const risk=String(riskFallback||p.risk_profile||"MODERATE");
  const missing:string[]=[]; if(!p.horizon) missing.push("horizon"); if(!p.goal) missing.push("goal");
  const splitOk=[p.crypto_pct,p.stocks_pct,p.metals_pct].every((v:any)=>Number.isFinite(Number(v))) && Math.abs(Number(p.crypto_pct)+Number(p.stocks_pct)+Number(p.metals_pct)-100)<0.01;
  if(!splitOk) missing.push("split"); if(!(Number(p.capital_usd)>0||Number(p.capital_irr)>0)) missing.push("capital");
  const lines=["👤 ATLAS | INVESTOR PROFILE","","Risk: "+risk,"Horizon: "+(p.horizon||"—"),"Goal: "+(p.goal||"—")];
  if(Number(p.capital_usd)>0) lines.push("Capital USD: "+Number(p.capital_usd).toLocaleString("en-US"));
  if(Number(p.capital_irr)>0) lines.push("Capital IRR: "+Number(p.capital_irr).toLocaleString("en-US"));
  lines.push("Split: "+(splitOk?`Crypto ${Number(p.crypto_pct)}% | TSE ${Number(p.stocks_pct)}% | Metals ${Number(p.metals_pct)}%`:"—"));
  lines.push("Excluded: "+(Array.isArray(p.excluded_markets)&&p.excluded_markets.length?p.excluded_markets.join(", "):"هیچ"));
  lines.push("Platforms: "+(Array.isArray(p.platforms)&&p.platforms.length?p.platforms.join(", "):"—"));
  lines.push("","Profile: "+(missing.length?"INCOMPLETE ⚠️":"COMPLETE ✅")); if(missing.length) lines.push("Missing: "+missing.join(", "));
  lines.push("","/horizon mid","/goal growth","/capital <amount> USD|IRR","/split crypto 50 tse 30 metals 20","/exclude meme leverage","/platform Binance TSE");
  return lines.join("\n");
}


// ============================================================
// MULTI-ASSET INTELLIGENCE — private read-only Chat Plane
// Reads the latest Analysis Plane snapshot only; never creates signals here.
// ============================================================
function isMultiAsset(t:string) {
  return /^(?:\/)?(?:multiasset|multi-asset|چنددارایی)(?:@\w+)?$/i.test(normFa(t));
}
function isResearch(t:string) {
  return /^(?:\/)?(?:research|پژوهش|تحقیق)(?:@\w+)?$/i.test(normFa(t));
}
async function latestMultiAsset(env:any,userId:string) {
  const rows=await sb(
    env,
    "GET",
    "/rest/v1/atlas_multiasset_intelligence_latest?user_id=eq."+
      encodeURIComponent(userId)+
      "&select=user_id,chat_id,payload,generated_at&limit=1"
  );
  return Array.isArray(rows)&&rows.length ? rows[0] : null;
}
function asObj(v:any) {
  return v && typeof v === "object" && !Array.isArray(v) ? v : {};
}
function firstText(...vals:any[]) {
  for (const v of vals) if (typeof v === "string" && v.trim()) return v.trim();
  return "";
}
function compactJson(v:any, max=900) {
  try {
    const x=JSON.stringify(v,null,2);
    return x.length>max ? x.slice(0,max)+"…" : x;
  } catch (_e) { return String(v??""); }
}
function assetRows(v:any) {
  if (Array.isArray(v)) return v;
  const o=asObj(v);
  for (const k of ["top","assets","rows","items","candidates","picks","opportunities"]) {
    if (Array.isArray(o[k])) return o[k];
  }
  return [];
}
function fmtAssetRow(x:any) {
  if (typeof x === "string") return "• "+x;
  const o=asObj(x);
  const sym=firstText(o.symbol,o.asset,o.coin,o.ticker,o.name)||"ASSET";
  const sig=firstText(o.signal,o.action,o.state,o.status,o.decision);
  const score=Number(o.score??o.confidence??o.rank_score);
  const bits=[sym];
  if(sig) bits.push(sig);
  if(Number.isFinite(score)) bits.push("score "+score.toFixed(score%1?1:0));
  const reason=firstText(o.reason,o.thesis,o.summary,o.note);
  return "• "+bits.join(" | ")+(reason?" — "+reason:"");
}
function fmtMultiAssetSnapshot(row:any) {
  if (!row) return "هنوز Multi-Asset snapshot برای تو ساخته نشده است. بعد از چرخه DEEP4H دوباره /multiasset را بزن.";
  const p=asObj(row.payload);
  const lines=["🧭 ATLAS | MULTI-ASSET INTELLIGENCE"];
  const ver=firstText(p.engine_version,p.engine);
  const status=firstText(p.status);
  const risk=firstText(p.risk_profile);
  if(ver) lines.push("Engine: "+ver);
  if(status) lines.push("Status: "+status);
  if(risk) lines.push("Risk: "+risk);
  lines.push("Generated: "+String(row.generated_at||p.generated_at||"—"));

  const exec=firstText(p.executive_summary,p.summary,p.executive);
  if(exec) lines.push("","📌 Executive Summary",exec);
  else if(Array.isArray(p.executive_summary)) lines.push("","📌 Executive Summary",...p.executive_summary.slice(0,7).map((x:any)=>"• "+String(x)));

  const sections:[string,any][]=[
    ["🪙 Crypto",p.crypto||p.cryptocurrency||p.crypto_market],
    ["📈 TSE / Stocks",p.tse||p.stocks||p.equities],
    ["🥇 Metals",p.metals||p.commodities],
  ];
  for(const [title,data] of sections){
    const rows=assetRows(data).slice(0,5);
    if(rows.length) lines.push("",title,...rows.map(fmtAssetRow));
  }
  const gaps=p.data_gaps||p.missing_data;
  if(Array.isArray(gaps)&&gaps.length) lines.push("","⚠️ Data Gaps",...gaps.slice(0,10).map((x:any)=>"• "+String(x)));
  else if(typeof gaps==="string"&&gaps.trim()) lines.push("","⚠️ Data Gaps",gaps.trim());

  if(lines.length<=5) lines.push("","Snapshot payload:",compactJson(p,1800));
  return lines.join("\n");
}
function researchText(row:any) {
  if (!row) return "هنوز گزارش Research برای تو ساخته نشده است. بعد از چرخه DEEP4H دوباره /research را بزن.";
  const p=asObj(row.payload);
  const direct=firstText(p.rendered_text,p.research_text,p.report_text,p.full_report,p.report);
  if(direct) return direct;
  const parts:any[]=[];
  for(const k of ["executive_summary","summary","crypto","stocks","tse","metals","allocation","avoid","data_coverage","data_gaps"]){
    if(p[k]!==undefined&&p[k]!==null) parts.push("## "+k.replace(/_/g," ")+"\n"+(typeof p[k]==="string"?p[k]:compactJson(p[k],5000)));
  }
  return parts.length ? "📚 ATLAS | RESEARCH\n\n"+parts.join("\n\n") : "📚 ATLAS | RESEARCH\n\n"+compactJson(p,12000);
}
function splitTelegramText(text:string, maxLen=3600) {
  const src=String(text||"").trim();
  if(!src) return ["گزارش خالی است."];
  const out:string[]=[]; let rest=src;
  while(rest.length>maxLen){
    let cut=rest.lastIndexOf("\n",maxLen);
    if(cut<maxLen*0.55) cut=rest.lastIndexOf(" ",maxLen);
    if(cut<maxLen*0.55) cut=maxLen;
    out.push(rest.slice(0,cut).trim());
    rest=rest.slice(cut).trim();
  }
  if(rest) out.push(rest);
  return out;
}

function isAllocate(t:string) {
  return /^(?:\/)?(?:allocate|allocation|سبدچینی|تخصیص)(?:@\w+)?$/i.test(normFa(t));
}
function isRebalance(t:string) {
  return /^(?:\/)?(?:rebalance|بازتعادل|متعادل.?سازی)(?:@\w+)?$/i.test(normFa(t));
}

async function latestAllocation(env:any,userId:string) {
  const rows=await sb(env,"GET","/rest/v1/atlas_desk_allocation_snapshots?user_id=eq."+encodeURIComponent(userId)+"&select=*&limit=1");
  return Array.isArray(rows)&&rows.length ? rows[0] : null;
}
function fmtAllocation(row:any) {
  if (!row) return "هنوز سبد پیشنهادی برای تو محاسبه نشده است. بعد از چرخه تحلیل بعدی دوباره /allocate را بزن.";
  const p=(row.payload&&typeof row.payload==="object")?row.payload:{};
  const targets=Array.isArray(p.targets)?p.targets:[];
  const profile=String(row.risk_profile||p.risk_profile||"MODERATE");
  const faProfile:Record<string,string>={CONSERVATIVE:"محافظه‌کار",MODERATE:"متعادل",AGGRESSIVE:"تهاجمی"};
  const irr=(v:any)=>Number.isFinite(Number(v)) ? Number(v).toLocaleString("en-US",{maximumFractionDigits:0})+" IRR" : "—";
  const lines=["🧠 ATLAS | PERSONAL ALLOCATION","Engine: Allocation V5","پروفایل ریسک: "+(faProfile[profile]||profile)];

  const d=(p.diagnostics&&typeof p.diagnostics==="object")?p.diagnostics:{};
  if (Number.isFinite(Number(d.data_coverage_pct))) lines.push("پوشش داده بازار: "+Number(d.data_coverage_pct).toFixed(0)+"%");
  if (Number.isFinite(Number(d.actionable_quality_pct))) lines.push("کیفیت فرصت‌های قابل تخصیص: "+Number(d.actionable_quality_pct).toFixed(0)+"%");
  if (Number.isFinite(Number(p.deployable_cash_irr))) lines.push("سرمایه نقدی قابل ارزش‌گذاری: "+irr(p.deployable_cash_irr));

  lines.push("","🎯 درصد پیشنهادی سبد:");
  if (!targets.length) lines.push("- فرصت واجد کیفیت کافی پیدا نشد؛ بودجه در نقد می‌ماند.");
  for (const x of targets) {
    let line="- "+String(x.symbol||"-")+": "+Number(x.target_pct||0).toFixed(1)+"% | "+String(x.group||"")+" | score "+Number(x.score||0).toFixed(0)+(x.signal?" | "+String(x.signal):"");
    if (Number.isFinite(Number(x.target_irr))) line += " | "+irr(x.target_irr);
    lines.push(line);
  }
  let cashLine="- CASH / نقد: "+Number(row.cash_target_pct??p.cash_target_pct??0).toFixed(1)+"%";
  if (Number.isFinite(Number(p.cash_target_irr))) cashLine += " | "+irr(p.cash_target_irr);
  lines.push(cashLine);

  const cash=p.registered_cash&&typeof p.registered_cash==="object"?p.registered_cash:{};
  const val=p.registered_cash_valuation&&typeof p.registered_cash_valuation==="object"?p.registered_cash_valuation:{};
  const ck=Object.keys(cash);
  if (ck.length) {
    lines.push("","💵 نقد ثبت‌شده:");
    for (const k of ck) {
      const v=val[k]&&typeof val[k]==="object"?val[k]:{};
      let line="- "+k+": "+fmtQty(cash[k]);
      if (v.value_irr !== null && v.value_irr !== undefined && Number.isFinite(Number(v.value_irr))) {
        line += " | ≈ "+irr(v.value_irr);
        if (k!=="IRR" && Number.isFinite(Number(v.rate_irr))) line += " | نرخ "+Number(v.rate_irr).toLocaleString("en-US",{maximumFractionDigits:0})+" IRR";
        if (v.source) line += " | "+String(v.source);
      } else if (k!=="IRR") line += " | نرخ تازه/معتبر در state موجود نیست";
      lines.push(line);
    }
  }
  lines.push("","کیفیت سیگنال قبل از پُرکردن سهم بازار بررسی می‌شود؛ بودجه استفاده‌نشده نقد می‌ماند.","این سبد پیشنهادی است و معامله خودکار انجام نمی‌شود.","تغییر ریسک: /risk conservative | moderate | aggressive");
  return lines.join("\n");
}

function isHourlyOn(t:string) {
  return /^(?:\/)?(?:hourlyon|ساعتی_روشن)$/i
    .test(normFa(t));
}

function isHourlyOff(t:string) {
  return /^(?:\/)?(?:hourlyoff|ساعتی_خاموش)$/i
    .test(normFa(t));
}

function extractAsset(text:string) {
  const raw = normFa(text)
    .replace(/[؟?،,:]/g," ");

  for (
    const token of raw
      .split(/\s+/)
      .filter(Boolean)
  ) {
    const c = canon(token);

    if (
      PERSONAL.includes(c) ||
      FIXED_CLASS[c]
    ) {
      return c;
    }
  }

  const stop = new Set([
    "بخرم",
    "بفروشم",
    "چطوره",
    "وضعیت",
    "تحلیل",
    "بررسی",
    "الان",
    "نظرت",
    "سیگنال",
    "نگه",
    "دارم",
    "چیکار",
    "کنم",
    "خوبه",
    "مناسبه",
    "است",
    "چطور",
  ]);

  for (
    const token of raw
      .split(/\s+/)
      .filter(Boolean)
  ) {
    if (
      /[\u0600-\u06FF]/.test(token) &&
      !stop.has(token)
    ) {
      return canon(token);
    }
  }

  return null;
}

function isSignalQuestion(text:string) {
  const t = normFa(text);

  if (
    !t ||
    t.startsWith("/")
  ) {
    return false;
  }

  return /[؟?]|چطوره|چطور است|وضعیت|نظرت|خوبه|مناسبه|الان|تحلیل|بررسی|بخرم|بفروشم|نگه دارم|نگهدارم|سیگنال|چیکار کنم|entry/i
    .test(t);
}

function helpText() {
  return [
    "ATLAS Desk • Multi-Asset",
    "این چت خصوصی میز سرمایه توست.",
    "",
    "ثبت سرمایه: /capital 4000",
    "وضعیت: /desk",
    "سبد فعلی: /portfolio",
    "سبد پیشنهادی: /allocate",
    "بازتعادل: /rebalance",
    "ریسک: /risk moderate",
    "پروفایل سرمایه‌گذار: /profile",
    "افق: /horizon mid",
    "هدف: /goal growth",
    "تقسیم بازار: /split crypto 50 tse 30 metals 20",
    "محدودیت‌ها: /exclude meme leverage",
    "پلتفرم‌ها: /platform Binance TSE",
    "",
    "کریپتو: /hold BTC 0.05",
    "دلار: /hold USD 1000",
    "تتر: /hold USDT 500",
    "طلا: /hold GOLD18 20",
    "نقره: /hold SILVER999 100",
    "یورو: /hold EUR 300",
    "بات تایلند: /hold THB 3400",
    "ریال ایران: /hold IRR 500000000",
    "مس: /hold COPPER 10",
    "بورس: /hold فولاد 5000",
    "",
    "حذف: /unhold فولاد",
    "",
    "سؤال:",
    "BTC بخرم؟",
    "دلار چطوره؟",
    "نقره چطوره؟",
    "فولاد چطوره؟",
    "",
    "Chat Plane فقط state ذخیره‌شده ATLAS را می‌خواند."
  ].join("\n");
}

function welcomeText(
  name:string,
  botUser:string
) {
  const link = botUser
    ? (
        "https://t.me/" +
        botUser +
        "?start=desk"
      )
    : "چت خصوصی همین ربات";

  return [
    "سلام " + (name || "دوست"),
    "به Atlas Desk خوش آمدی.",
    "",
    "سیگنال در گروه نمی آید. در خصوصی:",
    "1) " + link,
    "2) /start",
    "3) /capital 4000",
    "4) /portfolio"
  ].join("\n");
}

function envOf() {
  return {
    TELEGRAM_TOKEN:
      Deno.env.get(
        "TELEGRAM_TOKEN"
      ) || "",

    TELEGRAM_GROUP_CHAT_ID:
      Deno.env.get(
        "TELEGRAM_GROUP_CHAT_ID"
      ) || "",

    WEBHOOK_SECRET:
      Deno.env.get(
        "WEBHOOK_SECRET"
      ) || "",

    SUPABASE_URL:
      Deno.env.get(
        "SUPABASE_URL"
      ) || "",

    SUPABASE_SERVICE_ROLE_KEY:
      Deno.env.get(
        "SUPABASE_SERVICE_ROLE_KEY"
      ) || "",
  };
}

async function sb(
  env:any,
  method:string,
  path:string,
  body?:any
) {
  if (
    !env.SUPABASE_URL ||
    !env.SUPABASE_SERVICE_ROLE_KEY
  ) {
    throw new Error(
      "SUPABASE_SERVICE_ROLE_KEY missing; webhook fail-closed"
    );
  }

  const res = await fetch(
    env.SUPABASE_URL.replace(/\/$/,"") +
      path,
    {
      method,

      headers:{
        apikey:
          env.SUPABASE_SERVICE_ROLE_KEY,

        Authorization:
          "Bearer " +
          env.SUPABASE_SERVICE_ROLE_KEY,

        "Content-Type":
          "application/json",

        Prefer:
          method === "GET"
            ? "return=representation"
            : "resolution=merge-duplicates,return=representation",
      },

      body:
        body
          ? JSON.stringify(body)
          : undefined
    }
  );

  const text = await res.text();

  if (!res.ok) {
    throw new Error(
      "Supabase " +
      res.status +
      ": " +
      text.slice(0,300)
    );
  }

  return text
    ? JSON.parse(text)
    : [];
}

async function tg(
  env:any,
  method:string,
  payload:any
) {
  if (!env.TELEGRAM_TOKEN) {
    throw new Error(
      "TELEGRAM_TOKEN missing"
    );
  }

  const res = await fetch(
    "https://api.telegram.org/bot" +
      env.TELEGRAM_TOKEN +
      "/" +
      method,
    {
      method:"POST",

      headers:{
        "Content-Type":
          "application/json"
      },

      body:
        JSON.stringify(payload)
    }
  );

  const data =
    await res.json();

  if (
    !res.ok ||
    data.ok === false
  ) {
    throw new Error(
      "Telegram " +
      method +
      " " +
      res.status +
      ": " +
      JSON.stringify(data)
        .slice(0,300)
    );
  }

  return data;
}

async function getUser(
  env:any,
  userId:string
) {
  const rows = await sb(
    env,
    "GET",

    "/rest/v1/atlas_desk_users?user_id=eq." +
      encodeURIComponent(userId) +
      "&select=*"
  );

  return (
    Array.isArray(rows) &&
    rows[0]
  )
    ? rows[0]
    : null;
}

async function upsertUser(
  env:any,
  row:any
) {
  row.updated_at = nowIso();

  await sb(
    env,
    "POST",

    "/rest/v1/atlas_desk_users?on_conflict=user_id",

    row
  );
}

async function getHoldings(
  env:any,
  userId:string
) {
  const rows = await sb(
    env,
    "GET",

    "/rest/v1/atlas_desk_holdings?user_id=eq." +
      encodeURIComponent(userId) +
      "&select=coin,qty"
  );

  const bag:Record<string,number> = {};

  for (
    const r of rows || []
  ) {
    if (
      r.coin &&
      Number(r.qty) > 0
    ) {
      bag[String(r.coin)] =
        Number(r.qty);
    }
  }

  return bag;
}

async function deleteHolding(
  env:any,
  userId:string,
  symbol:string
) {
  await sb(
    env,
    "DELETE",

    "/rest/v1/atlas_desk_holdings?user_id=eq." +
      encodeURIComponent(userId) +
      "&coin=eq." +
      encodeURIComponent(symbol)
  );
}

async function latestRows(
  env:any,
  table:string,
  symbol:string
) {
  // Current ATLAS snapshot tables use captured_at.
  // created_at is tolerated as fallback.

  for (
    const orderCol of [
      "captured_at",
      "created_at"
    ]
  ) {
    try {
      const path =
        "/rest/v1/" +
        table +
        "?symbol=eq." +
        encodeURIComponent(symbol) +
        "&select=*" +
        "&order=" +
        orderCol +
        ".desc&limit=1";

      const r =
        await sb(
          env,
          "GET",
          path
        );

      if (
        Array.isArray(r) &&
        r[0]
      ) {
        return r[0];
      }

    } catch (_e) {}
  }

  return null;
}

async function latestAsset(
  env:any,
  symbol:string
) {
  // Crypto
  if (
    HOLDABLE_CRYPTO.has(symbol)
  ) {
    let row =
      await latestRows(
        env,
        "atlas_hourly_signal_snapshots",
        symbol
      );

    // RNDR was renamed to RENDER. Read either stored symbol, while keeping
    // the user's holding key backward-compatible as RNDR.
    if (!row && symbol === "RNDR") {
      row = await latestRows(
        env,
        "atlas_hourly_signal_snapshots",
        "RENDER"
      );
    }

    return row
      ? {
          symbol,
          kind:"CRYPTO",
          table:
            "atlas_hourly_signal_snapshots",
          row
        }
      : null;
  }

  let tables:string[] = [];

  // FX
  if (
    FIXED_CLASS[symbol] === "FX"
  ) {
    tables = [
      "atlas_iran_fx_snapshots"
    ];
  }

  // Metals
  else if (
    FIXED_CLASS[symbol]
      ?.startsWith("METAL")
  ) {
    tables = [
      "atlas_market_snapshots",
      "atlas_iran_fx_snapshots"
    ];
  }

  // TSE / Funds
  else {
    tables = [
      "atlas_tse_snapshots",
      "atlas_fund_snapshots"
    ];
  }

  for (
    const table of tables
  ) {
    const row =
      await latestRows(
        env,
        table,
        symbol
      );

    if (row) {
      return {
        symbol,

        kind:
          FIXED_CLASS[symbol] ||
          (
            table.includes("fund")
              ? "FUND"
              : "TSE"
          ),

        table,
        row
      };
    }
  }

  // Unknown Persian token:
  // resolve only if it really exists
  // in TSE/Fund stored state.
  if (!FIXED_CLASS[symbol]) {
    for (
      const table of [
        "atlas_tse_snapshots",
        "atlas_fund_snapshots"
      ]
    ) {
      const row =
        await latestRows(
          env,
          table,
          symbol
        );

      if (row) {
        return {
          symbol,

          kind:
            table.includes("fund")
              ? "FUND"
              : "TSE",

          table,
          row
        };
      }
    }
  }

  return null;
}

async function latestBookScan(
  env:any,
  coin:string
) {
  return await latestRows(
    env,
    "atlas_book_scan_snapshots",
    coin
  );
}

function bookScanLines(
  scan:any
) {
  if (!scan) return [];

  const when =
    String(
      scan.captured_at ||
      scan.created_at ||
      ""
    )
      .replace("T"," ")
      .slice(0,16);

  return [
    "Book Scan ذخیره شده",

    scan.quality
      ? (
          "کیفیت: " +
          scan.quality
        )
      : "",

    scan.kind
      ? (
          "نوع: " +
          scan.kind
        )
      : "",

    scan.level != null
      ? (
          "سطح: " +
          fmtPx(scan.level)
        )
      : "",

    scan.reason
      ? (
          "دلیل: " +
          scan.reason
        )
      : "",

    when
      ? (
          "زمان اسکن: " +
          when +
          " UTC"
        )
      : ""

  ].filter(Boolean);
}

function storedAdvice(
  asset:any,
  scan:any = null
) {
  if (!asset) {
    return (
      "برای این نماد state ذخیره‌شده پیدا نشد."
    );
  }

  const {
    symbol,
    kind,
    row
  } = asset;

  const p =
    payloadOf(row);

  const price =
    displayPrice(
      symbol,
      row
    );

  const when =
    String(
      row.captured_at ||
      row.created_at ||
      ""
    )
      .replace("T"," ")
      .slice(0,16);

  // Crypto keeps existing
  // Analysis Plane signal semantics.
  if (kind === "CRYPTO") {
    const signal =
      String(
        row.public_signal ||
        p.public_signal ||
        "WAIT"
      ).toUpperCase();

    const state =
      String(
        row.decision_state ||
        p.decision_state ||
        ""
      );

    const direction =
      String(
        row.direction ||
        p.direction ||
        ""
      );

    const conf =
      row.confidence ??
      p.confidence;

    return [
      symbol +
        " • آخرین تحلیل ذخیره‌شده",

      "سیگنال عمومی: " +
        signal,

      state
        ? (
            "وضعیت تصمیم: " +
            state
          )
        : "",

      direction
        ? (
            "جهت: " +
            direction
          )
        : "",

      (
        conf != null &&
        Number.isFinite(
          Number(conf)
        )
      )
        ? (
            "اعتماد: " +
            Number(conf)
              .toFixed(0)
          )
        : "",

      price
        ? (
            "قیمت: " +
            fmtPx(price.value) +
            " " +
            price.unit
          )
        : "",

      p.entry != null
        ? (
            "ورود: " +
            fmtPx(p.entry)
          )
        : "",

      p.sl != null
        ? (
            "SL: " +
            fmtPx(p.sl)
          )
        : "",

      p.tp1 != null
        ? (
            "TP1: " +
            fmtPx(p.tp1)
          )
        : "",

      when
        ? (
            "زمان: " +
            when +
            " UTC"
          )
        : "",

      (
        signal === "WAIT" ||
        signal === "WATCH"
      )
        ? "الان ورود نکن."
        : "",

      ...bookScanLines(scan),

      "این خواندن state است، نه تحلیل تازه."

    ].filter(Boolean)
      .join("\n");
  }

  // Iran / TSE / Funds:
  // advisory/state only.
  const pct =
    Number(
      row.pct_change ??
      row.change_pct ??
      row.percent ??
      p.pct_change ??
      p.change_pct
    );

  const sig =
    String(
      row.public_signal ||
      row.signal ||
      p.public_signal ||
      p.signal ||
      ""
    ).toUpperCase();

  return [
    symbol +
      " • " +
      kind,

    price
      ? (
          "آخرین قیمت: " +
          fmtPx(price.value) +
          (
            price.unit
              ? " " + price.unit
              : ""
          )
        )
      : "قیمت: -",

    Number.isFinite(pct)
      ? (
          "تغییر: " +
          (
            pct >= 0
              ? "+"
              : ""
          ) +
          pct.toFixed(2) +
          "%"
        )
      : "",

    sig
      ? (
          "وضعیت ATLAS: " +
          sig
        )
      : "",

    p.real_flow_direction
      ? (
          "جریان حقیقی: " +
          p.real_flow_direction
        )
      : "",

    when
      ? (
          "زمان داده: " +
          when +
          " UTC"
        )
      : "",

    "این پاسخ از آخرین state ذخیره‌شده است؛ تحلیل تازه اجرا نشده."

  ].filter(Boolean)
    .join("\n");
}

async function formatPortfolio(
  env:any,
  bag:Record<string,number>
) {
  const keys = Object.keys(bag);

  if (!keys.length) {
    return (
      "سبد خالی است.\n" +
      "ثبت کن: /hold BTC 0.05"
    );
  }

  type PortfolioItem = {
    symbol:string;
    qty:number;
    suffix:string;
    group:"CRYPTO" | "FX" | "METALS" | "TSE" | "OTHER";
  };

  const items:PortfolioItem[] = [];

  for (const s of keys.sort()) {
    let suffix = "";
    let group:PortfolioItem["group"] =
      HOLDABLE_CRYPTO.has(s)
        ? "CRYPTO"
        : FIXED_CLASS[s] === "FX"
          ? "FX"
          : (
              FIXED_CLASS[s] === "METAL_IRAN" ||
              FIXED_CLASS[s] === "METAL_GLOBAL"
            )
            ? "METALS"
            : "OTHER";

    try {
      const a = await latestAsset(env, s);

      if (a) {
        const kind =
          String(a.kind || "")
            .toUpperCase();

        if (kind === "TSE" || kind === "FUND") {
          group = "TSE";
        } else if (kind === "FX") {
          group = "FX";
        } else if (
          kind === "METAL_IRAN" ||
          kind === "METAL_GLOBAL"
        ) {
          group = "METALS";
        } else if (kind === "CRYPTO") {
          group = "CRYPTO";
        }

        const px = displayPrice(s, a.row);

        if (px) {
          suffix =
            " | قیمت " +
            fmtPx(px.value) +
            (px.unit ? " " + px.unit : "");
        }
      }
    } catch (_e) {}

    items.push({
      symbol:s,
      qty:bag[s],
      suffix,
      group
    });
  }

  const sections:{
    key:PortfolioItem["group"];
    title:string;
  }[] = [
    { key:"CRYPTO", title:"🪙 کریپتو" },
    { key:"FX", title:"💵 ارز" },
    { key:"METALS", title:"🥇 طلا و فلزات" },
    { key:"TSE", title:"📈 بورس و صندوق‌ها" },
    { key:"OTHER", title:"📦 سایر دارایی‌ها" }
  ];

  const lines = [
    "سبد دارایی تو • Multi-Asset"
  ];

  for (const section of sections) {
    const rows =
      items.filter(
        x => x.group === section.key
      );

    if (!rows.length) continue;

    lines.push("", section.title);

    for (const x of rows) {
      lines.push(
        "- " +
        x.symbol +
        ": " +
        fmtQty(x.qty) +
        x.suffix
      );
    }
  }

  lines.push(
    "\nتغییر: /hold ETH 1.2\n" +
    "حذف: /unhold ETH"
  );

  return lines.join("\n");
}

async function handlePrivate(
  env:any,
  msg:any
) {
  const chatId =
    msg.chat &&
    msg.chat.id;

  const from =
    msg.from || {};

  const userId =
    String(
      from.id || ""
    );

  const text =
    String(
      msg.text || ""
    ).trim();

  if (
    !chatId ||
    !userId ||
    !text
  ) {
    return;
  }

  const existing =
    (
      await getUser(
        env,
        userId
      )
    ) || {};

  await upsertUser(
    env,
    {
      user_id:userId,

      chat_id:
        String(chatId),

      username:
        from.username ||
        existing.username ||
        "",

      first_name:
        from.first_name ||
        existing.first_name ||
        "",

      equity_usdt:
        existing.equity_usdt ??
        null,

      seen_in_group:
        !!existing.seen_in_group,

      dm_started:true,

      hourly_on:
        existing.hourly_on !== false,

      welcomed_at:
        existing.welcomed_at ||
        null
    }
  );

  const reply =
    async (body:string) =>
      await tg(
        env,
        "sendMessage",
        {
          chat_id:chatId,
          text:body
        }
      );

  // MULTI-ASSET INTELLIGENCE — private, read-only latest snapshot.
  if (isMultiAsset(text)) {
    return reply(fmtMultiAssetSnapshot(await latestMultiAsset(env,userId)));
  }
  if (isResearch(text)) {
    const row=await latestMultiAsset(env,userId);
    const chunks=splitTelegramText(researchText(row));
    for(let i=0;i<chunks.length;i++) {
      const prefix=chunks.length>1 ? `📚 ATLAS RESEARCH ${i+1}/${chunks.length}\n\n` : "";
      await reply(prefix+chunks[i]);
    }
    return;
  }

  // MULTI-ASSET INVESTOR PROFILE — private chat only (handlePrivate).
  if (isProfile(text)) {
    return reply(await formattedMultiProfile(env,userId));
  }
  const hz=parseHorizon(text);
  if (hz) { await patchMultiProfile(env,userId,{horizon:hz}); return reply("افق سرمایه‌گذاری ثبت شد: "+hz+"\n\n"+await formattedMultiProfile(env,userId)); }
  if (/^(?:\/)?(?:horizon|افق)(?:@\w+)?\s+/i.test(normFa(text))) return reply("افق نامعتبر است.\n/horizon short | mid | long");
  const goal=parseGoal(text);
  if (goal) { await patchMultiProfile(env,userId,{goal}); return reply("هدف سرمایه‌گذاری ثبت شد: "+goal+"\n\n"+await formattedMultiProfile(env,userId)); }
  if (/^(?:\/)?(?:goal|هدف)(?:@\w+)?\s+/i.test(normFa(text))) return reply("هدف نامعتبر است.\n/goal fast_profit | growth | capital_preservation | inflation_hedge | diversification");
  const pc=parseProfileCapital(text);
  if (pc) {
    if ((pc as any).error) return reply("مبلغ سرمایه باید عددی بزرگ‌تر از صفر باشد.");
    const patch=(pc as any).currency==="IRR"
      ? {capital_irr:(pc as any).amount,capital_usd:null}
      : {capital_usd:(pc as any).amount,capital_irr:null};
    await patchMultiProfile(env,userId,patch);
    // Preserve legacy Desk semantics: explicit USD/USDT capital also updates equity_usdt.
    if ((pc as any).currency==="USD") await upsertUser(env,{user_id:userId,chat_id:String(chatId),username:from.username||"",first_name:from.first_name||"",equity_usdt:(pc as any).amount,seen_in_group:!!existing.seen_in_group,dm_started:true,hourly_on:existing.hourly_on!==false,welcomed_at:existing.welcomed_at||null});
    return reply("سرمایه پروفایل ثبت شد: "+Number((pc as any).amount).toLocaleString("en-US")+" "+(pc as any).currency+"\n\n"+await formattedMultiProfile(env,userId));
  }
  const sp=parseSplit(text);
  if (sp) {
    if ((sp as any).error==="sum") return reply("جمع درصدها باید دقیقاً 100% باشد. جمع فعلی: "+Number((sp as any).sum).toFixed(1)+"%");
    if ((sp as any).error) return reply("فرمت صحیح:\n/split crypto 50 tse 30 metals 20");
    await patchMultiProfile(env,userId,sp); return reply("تقسیم بازار ثبت شد.\n\n"+await formattedMultiProfile(env,userId));
  }
  const ex=parseListPref(text,"exclude","حذفبازار");
  if (ex) { await patchMultiProfile(env,userId,{excluded_markets:ex}); return reply("محدودیت‌ها ثبت شد: "+(ex.join(", ")||"هیچ")+"\n\n"+await formattedMultiProfile(env,userId)); }
  const pl=parseListPref(text,"platform","پلتفرم");
  if (pl) { await patchMultiProfile(env,userId,{platforms:pl}); return reply("پلتفرم‌ها ثبت شد: "+(pl.join(", ")||"—")+"\n\n"+await formattedMultiProfile(env,userId)); }

  // CAPITAL
  const cap =
    parseCapital(text);

  if (cap != null) {
    if (cap < 50) {
      return reply(
        "حداقل سرمایه 50 USDT است."
      );
    }

    if (
      cap > 10000000
    ) {
      return reply(
        "عدد سرمایه غیرمنطقی است."
      );
    }

    await upsertUser(
      env,
      {
        user_id:userId,

        chat_id:
          String(chatId),

        username:
          from.username ||
          "",

        first_name:
          from.first_name ||
          "",

        equity_usdt:cap,

        seen_in_group:
          !!existing.seen_in_group,

        dm_started:true,

        hourly_on:
          existing.hourly_on !== false,

        welcomed_at:
          existing.welcomed_at ||
          null
      }
    );

    const risk =
      (
        cap *
        riskPct()
      ) / 100;

    return reply(
      "سرمایه تو ثبت شد: " +
      cap.toFixed(2) +
      " USDT\n" +

      "ریسک هر معامله: " +
      riskPct().toFixed(2) +
      "% = " +
      risk.toFixed(2) +
      " USDT\n" +

      "سبد: /portfolio"
    );
  }

  // HOLD
  const hold =
    parseHold(text);

  if (hold) {
    if (
      !Number.isFinite(
        hold.qty
      ) ||
      hold.qty <= 0
    ) {
      await deleteHolding(
        env,
        userId,
        hold.coin
      );

      return reply(
        await formatPortfolio(
          env,
          await getHoldings(
            env,
            userId
          )
        )
      );
    }

    // Known portfolio assets are registrable independently of market state.
    // This covers Top-100 crypto plus canonical FX/metals such as EUR, THB,
    // IRR and SILVER999. Missing state must never fabricate a price.
    // Unknown symbols (e.g. a Persian TSE token) still require real stored state.
    if (!isKnownHoldAsset(hold.coin)) {
      const asset = await latestAsset(env, hold.coin);

      if (!asset) {
        return reply(
          hold.coin +
          " در state فعلی ATLAS پیدا نشد؛ چیزی ثبت نشد."
        );
      }
    }

    await sb(
      env,
      "POST",

      "/rest/v1/atlas_desk_holdings?on_conflict=user_id,coin",

      {
        user_id:userId,
        coin:hold.coin,
        qty:hold.qty,
        updated_at:nowIso()
      }
    );

    return reply(
      hold.coin +
      " ثبت شد: " +
      fmtQty(hold.qty) +
      "\n\n" +

      await formatPortfolio(
        env,
        await getHoldings(
          env,
          userId
        )
      )
    );
  }

  // UNHOLD
  const un =
    parseUnhold(text);

  if (un) {
    await deleteHolding(
      env,
      userId,
      un
    );

    return reply(
      un +
      " از سبد حذف شد.\n" +

      await formatPortfolio(
        env,
        await getHoldings(
          env,
          userId
        )
      )
    );
  }

  // RISK PROFILE — preference only; Analysis Plane recomputes allocation.
  const rp=parseRiskProfile(text);
  if (rp) {
    await sb(env,"POST","/rest/v1/atlas_desk_allocation_preferences?on_conflict=user_id",{
      user_id:userId,risk_profile:rp,updated_at:nowIso()
    });
    return reply("پروفایل ریسک ثبت شد: "+rp+"\nسبد پیشنهادی در چرخه تحلیل بعدی با این پروفایل بازمحاسبه می‌شود.\n/allocate");
  }

  // ALLOCATE — Chat Plane reads latest stored Analysis Plane snapshot only.
  if (isAllocate(text)) {
    return reply(fmtAllocation(await latestAllocation(env,userId)));
  }

  // REBALANCE — expose target allocation; no trade execution from webhook.
  if (isRebalance(text)) {
    const a=await latestAllocation(env,userId);
    if (!a) return reply(fmtAllocation(null));
    return reply("🔄 ATLAS | REBALANCE TARGET\n\n"+fmtAllocation(a)+"\n\nبرای اجرای تغییرات، تصمیم و معامله با خود کاربر است.");
  }

  // PORTFOLIO
  if (
    isPortfolio(text)
  ) {
    return reply(
      await formatPortfolio(
        env,
        await getHoldings(
          env,
          userId
        )
      )
    );
  }

  // DESK STATUS
  if (
    isStatus(text)
  ) {
    const me =
      (
        await getUser(
          env,
          userId
        )
      ) || {};

    const eq =
      Number(
        me.equity_usdt
      );

    if (!eq) {
      return reply(
        "هنوز سرمایه نداری.\n" +
        "بفرست: /capital 4000"
      );
    }

    const bag =
      await getHoldings(
        env,
        userId
      );

    return reply(
      [
        "ATLAS Desk",

        "سرمایه تو: " +
        eq.toFixed(2) +
        " USDT",

        "ریسک هر معامله: " +
        riskPct().toFixed(2) +
        "% = " +
        (
          (
            eq *
            riskPct()
          ) / 100
        ).toFixed(2) +
        " USDT",

        "تعداد دارایی ثبت شده: " +
        Object.keys(bag).length,

        "سیگنال ساعتی: " +
        (
          me.hourly_on === false
            ? "خاموش"
            : "روشن"
        ),

        "",

        await formatPortfolio(
          env,
          bag
        )

      ].join("\n")
    );
  }

  // HOURLY ON
  if (
    isHourlyOn(text)
  ) {
    await upsertUser(
      env,
      Object.assign(
        {},
        existing,
        {
          user_id:userId,
          chat_id:String(chatId),
          dm_started:true,
          hourly_on:true
        }
      )
    );

    return reply(
      "سیگنال ساعتی روشن شد."
    );
  }

  // HOURLY OFF
  if (
    isHourlyOff(text)
  ) {
    await upsertUser(
      env,
      Object.assign(
        {},
        existing,
        {
          user_id:userId,
          chat_id:String(chatId),
          dm_started:true,
          hourly_on:false
        }
      )
    );

    return reply(
      "سیگنال ساعتی خاموش شد."
    );
  }

  // HELP
  if (
    isHelp(text) ||
    text.startsWith(
      "/start"
    )
  ) {
    return reply(
      helpText()
    );
  }

  // QUICK QUESTION
  if (
    isSignalQuestion(text)
  ) {
    const symbol =
      extractAsset(text);

    if (!symbol) {
      return reply(
        "نماد را مشخص کن؛ مثلا BTC بخرم؟ یا فولاد چطوره؟"
      );
    }

    const asset =
      await latestAsset(
        env,
        symbol
      );

    if (!asset) {
      return reply(
        symbol +
        " در state ذخیره‌شده ATLAS پیدا نشد."
      );
    }

    let scan = null;

    // Book Scan remains crypto-only.
    if (
      asset.kind === "CRYPTO"
    ) {
      try {
        scan =
          await latestBookScan(
            env,
            symbol
          );

      } catch (e) {
        console.error(
          "Book Scan read failed: " +
          String(e)
        );
      }
    }

    return reply(
      storedAdvice(
        asset,
        scan
      )
    );
  }
}

async function handleGroup(
  env:any,
  update:any
) {
  const groupId =
    String(
      env.TELEGRAM_GROUP_CHAT_ID ||
      ""
    );

  const msg =
    update.message || {};

  const chat =
    msg.chat ||
    (
      update.chat_member &&
      update.chat_member.chat
    ) ||
    {};

  if (
    !groupId ||
    String(chat.id) !== groupId
  ) {
    return;
  }

  const members = [
    ...(
      msg.new_chat_members ||
      []
    )
  ];

  if (
    update.chat_member &&
    update.chat_member
      .new_chat_member
  ) {
    const st =
      update.chat_member
        .new_chat_member
        .status;

    if (
      [
        "member",
        "administrator",
        "restricted"
      ].includes(st)
    ) {
      const u =
        update.chat_member
          .new_chat_member
          .user;

      if (
        u &&
        !u.is_bot
      ) {
        members.push(u);
      }
    }
  }

  // No new member:
  // no Telegram getMe call.
  if (
    !members.length
  ) {
    return;
  }

  const me =
    await tg(
      env,
      "getMe",
      {}
    );

  const botUser =
    (
      me.result &&
      me.result.username
    ) || "";

  for (
    const member of members
  ) {
    if (
      !member ||
      member.is_bot
    ) {
      continue;
    }

    const uid =
      String(
        member.id
      );

    const existing =
      (
        await getUser(
          env,
          uid
        )
      ) || {};

    if (
      existing.welcomed_at &&
      existing.seen_in_group
    ) {
      continue;
    }

    await upsertUser(
      env,
      {
        user_id:uid,

        chat_id:
          existing.chat_id ||
          uid,

        username:
          member.username ||
          "",

        first_name:
          member.first_name ||
          "",

        equity_usdt:
          existing.equity_usdt ??
          null,

        seen_in_group:true,

        dm_started:
          !!existing.dm_started,

        hourly_on:
          existing.hourly_on !== false,

        welcomed_at:
          nowIso()
      }
    );

    await tg(
      env,
      "sendMessage",
      {
        chat_id:groupId,

        text:
          welcomeText(
            member.first_name,
            botUser
          )
      }
    );
  }
}

Deno.serve(
  async (request) => {
    const env =
      envOf();

    if (
      request.method !== "POST"
    ) {
      return new Response(
        "ATLAS Desk webhook hyper-endpoint • Multi-Asset",
        {
          status:200
        }
      );
    }

    // Telegram webhook secret
    // authentication remains fail-closed.
    if (
      !env.WEBHOOK_SECRET
    ) {
      console.error(
        "WEBHOOK_SECRET missing; fail-closed"
      );

      return new Response(
        "webhook secret required",
        {
          status:503
        }
      );
    }

    if (
      request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
      ) !== env.WEBHOOK_SECRET
    ) {
      return new Response(
        "forbidden",
        {
          status:403
        }
      );
    }

    if (
      !env.SUPABASE_SERVICE_ROLE_KEY ||
      !env.TELEGRAM_TOKEN
    ) {
      console.error(
        "required runtime secrets missing"
      );

      return new Response(
        "misconfigured",
        {
          status:503
        }
      );
    }

    let update:any;

    try {
      update =
        await request.json();

    } catch (_e) {
      return new Response(
        "bad json",
        {
          status:400
        }
      );
    }

    try {
      await handleGroup(
        env,
        update
      );

      const msg =
        update.message ||
        update.edited_message;

      if (
        msg &&
        msg.chat &&
        msg.chat.type ===
          "private"
      ) {
        await handlePrivate(
          env,
          msg
        );
      }

      return new Response(
        "ok",
        {
          status:200
        }
      );

    } catch (err) {
      console.error(
        String(err)
      );

      return new Response(
        String(err)
          .slice(0,200),
        {
          status:500
        }
      );
    }
  }
);