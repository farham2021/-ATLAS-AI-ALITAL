export const TROY_OZ_GRAMS = 31.1034768;
export const COIN_SPECS = Object.freeze([
  {symbol:"EMAMI", name_fa:"سکه امامی", weight_g:8.133, purity:0.9, source_symbol:"COIN_EMAMI"},
  {symbol:"AZADI", name_fa:"سکه بهار آزادی", weight_g:8.133, purity:0.9, source_symbol:"COIN_AZADI"},
  {symbol:"HALF", name_fa:"نیم سکه", weight_g:4.0665, purity:0.9, source_symbol:"COIN_HALF"},
  {symbol:"QUARTER", name_fa:"ربع سکه", weight_g:2.03325, purity:0.9, source_symbol:"COIN_QUARTER"},
  {symbol:"GERAMI", name_fa:"سکه گرمی", weight_g:1.01, purity:0.9, source_symbol:"COIN_GERAMI"}
]);

const finitePositive = value => Number.isFinite(Number(value)) && Number(value) > 0;
export function normalizeUsdIrr(row) {
  if (!row || !finitePositive(row.price)) return null;
  const payload = row.payload && typeof row.payload === "object" ? row.payload : {};
  const unit = String(payload.unit_canonical || "").toUpperCase();
  if (unit !== "IRR_PER_USD" && !(unit === "IRR" && row.symbol === "USD_IRR")) return null;
  return Number(row.price);
}
export function normalizeTomanMarket(row) {
  if (!row || !finitePositive(row.price)) return null;
  const payload = row.payload && typeof row.payload === "object" ? row.payload : {};
  const unit = String(payload.unit_canonical || "").toUpperCase();
  if (unit !== "TOMAN") return null;
  return Number(row.price);
}
export function normalizeUsdMetal(row, expectedUnit) {
  if (!row || !finitePositive(row.price)) return null;
  const payload = row.payload && typeof row.payload === "object" ? row.payload : {};
  const unit = String(payload.unit_canonical || payload.unit || "").toUpperCase();
  return unit === expectedUnit ? Number(row.price) : null;
}
export function fairValueToman({weightG, purity, xauUsd, usdIrr}) {
  for (const [key, value] of Object.entries({weightG,purity,xauUsd,usdIrr})) {
    if (!Number.isFinite(Number(value)) || Number(value) <= 0) throw new TypeError("invalid_" + key);
  }
  if (Number(purity) > 1) throw new RangeError("purity_must_be_fraction");
  return Number(weightG) * Number(purity) * Number(xauUsd) * Number(usdIrr) / TROY_OZ_GRAMS / 10;
}
export function bubbleToman(marketToman, fairToman) {
  if (!Number.isFinite(Number(marketToman)) || Number(marketToman) <= 0 ||
      !Number.isFinite(Number(fairToman)) || Number(fairToman) <= 0) return null;
  const diff = Number(marketToman) - Number(fairToman);
  return {bubble_toman:Math.round(diff), bubble_pct:Number((diff / Number(fairToman) * 100).toFixed(2))};
}
export function quoteFreshness(rows, nowMs=Date.now(), maxAgeMs=6*60*60*1000) {
  const times = rows.map(row => Date.parse(row?.captured_at));
  if (times.some(time => !Number.isFinite(time))) return {ok:false, reason:"missing_timestamp"};
  const oldest=Math.min(...times), newest=Math.max(...times);
  if (nowMs-oldest > maxAgeMs || oldest-nowMs > 60_000) return {ok:false, reason:"stale_or_future"};
  if (newest-oldest > 30*60*1000) return {ok:false, reason:"source_time_skew"};
  return {ok:true, oldest_at:new Date(oldest).toISOString(), newest_at:new Date(newest).toISOString()};
}
