(() => {
  "use strict";

  const panel = document.getElementById("news-panel");
  if (!panel) return;

  const heading = panel.querySelector("h2");
  if (!heading) return;

  let container = document.getElementById("atlas-macro-event-risk");
  if (!container) {
    container = document.createElement("section");
    container.id = "atlas-macro-event-risk";
    container.setAttribute("aria-live", "polite");
    container.style.cssText =
      "display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:12px 0 16px";
    heading.insertAdjacentElement("afterend", container);
  }

  const langSelect = document.getElementById("atlas-lang");
  const scriptUrl = document.currentScript && document.currentScript.src;
  const dataUrl = scriptUrl
    ? new URL("../macro_events.json", scriptUrl).toString()
    : "./macro_events.json";

  const text = (fa, en) => (langSelect && langSelect.value === "en" ? en : fa);
  let lastPayload = null;

  function message(fa, en, color = "#a9bdd5") {
    container.replaceChildren();
    const box = document.createElement("div");
    box.style.cssText =
      "grid-column:1/-1;padding:11px 13px;border-radius:10px;background:#101c33;border:1px solid #344867;font-size:12px";
    box.style.color = color;
    box.textContent = text(fa, en);
    container.appendChild(box);
  }

  function pct(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "") : "—";
  }

  function render(payload) {
    lastPayload = payload;
    const fetchedMs = Date.parse(payload && payload.fetched_at_utc);
    const ageMs = Date.now() - fetchedMs;
    if (!Number.isFinite(fetchedMs) || ageMs < -5 * 60 * 1000 || ageMs > 3 * 60 * 60 * 1000) {
      message("دادهٔ بازار پیش‌بینی تازه نیست؛ احتمال‌ها نمایش داده نمی‌شوند.",
              "Prediction-market data is stale; probabilities are hidden.", "#fbbf24");
      return;
    }

    if (!payload || !Array.isArray(payload.events) || payload.events.length === 0 ||
        !["OK", "PARTIAL"].includes(payload.status)) {
      message("دادهٔ معتبر بازارهای پیش‌بینی در این نوبت در دسترس نیست.",
              "Verified prediction-market data is unavailable for this update.");
      return;
    }

    container.replaceChildren();
    const header = document.createElement("div");
    header.style.cssText =
      "grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;color:#a9bdd5;font-size:12px";
    const note = document.createElement("span");
    note.textContent = text(
      "ریسک رویداد و احتمال ضمنی بازار (میانهٔ قیمت خرید/فروش YES) · منبع: Kalshi",
      "Event risk and market-implied probability (YES bid/ask midpoint) · Source: Kalshi"
    );
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.textContent = text("تازه‌سازی", "Refresh");
    refresh.style.cssText = "padding:5px 9px;font-size:11px";
    refresh.addEventListener("click", load);
    header.append(note, refresh);
    container.appendChild(header);

    for (const event of payload.events) {
      if (!event || typeof event.title !== "string" ||
          !Number.isFinite(Number(event.implied_probability_pct))) continue;

      const card = document.createElement("article");
      const highRisk = event.risk_flag === "HIGH_EVENT_RISK";
      card.style.cssText =
        "padding:11px 12px;border-radius:10px;background:#0f1b31;border:1px solid " +
        (highRisk ? "rgba(245,158,11,.55)" : "rgba(148,163,184,.23)");

      const series = document.createElement("div");
      series.style.cssText = "font-size:11px;color:#38bdf8;font-weight:700;margin-bottom:5px";
      series.textContent = String(event.series_label || event.series || "");

      const title = document.createElement("div");
      title.style.cssText = "font-size:12px;color:#e2e8f0;line-height:1.5;margin-bottom:8px";
      title.textContent = event.title;

      const probability = document.createElement("div");
      probability.style.cssText = "display:flex;justify-content:space-between;gap:8px;align-items:center";
      const probabilityLabel = document.createElement("span");
      probabilityLabel.style.cssText = "font-size:11px;color:#a9bdd5";
      probabilityLabel.textContent = text("احتمال ضمنی YES:", "YES market-implied:");
      const probabilityValue = document.createElement("strong");
      probabilityValue.style.cssText = "font-size:15px;color:#22c55e";
      probabilityValue.textContent = pct(event.implied_probability_pct) + "%";
      probability.append(probabilityLabel, probabilityValue);

      const quotes = document.createElement("div");
      quotes.style.cssText = "font-size:11px;color:#a9bdd5;margin-top:5px";
      const bid = Number(event.yes_bid_dollars) * 100;
      const ask = Number(event.yes_ask_dollars) * 100;
      quotes.textContent = text("بازهٔ قیمت YES: ", "YES quote: ") +
        (Number.isFinite(bid) && Number.isFinite(ask)
          ? bid.toFixed(0) + "¢ – " + ask.toFixed(0) + "¢"
          : "—");

      const details = document.createElement("div");
      details.style.cssText = "display:flex;justify-content:space-between;gap:8px;margin-top:8px;font-size:10px;color:#94a3b8";
      const close = document.createElement("span");
      close.textContent = text("بسته‌شدن تا ", "Closes in ") +
        Number(event.hours_to_close).toFixed(1) + text(" ساعت", "h");
      const risk = document.createElement("span");
      risk.style.color = highRisk ? "#fbbf24" : "#94a3b8";
      risk.textContent = highRisk
        ? text("ریسک رویداد بالا", "HIGH EVENT RISK")
        : text("عادی", "NORMAL");
      details.append(close, risk);

      card.append(series, title, probability, quotes, details);
      container.appendChild(card);
    }
  }

  async function load() {
    try {
      const url = new URL(dataUrl);
      url.searchParams.set("_", String(Date.now()));
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP_" + response.status);
      const payload = await response.json();
      render(payload);
    } catch (_) {
      message("دریافت دادهٔ رویدادهای کلان ناموفق است؛ عددی نمایش داده نمی‌شود.",
              "Macro-event data could not be loaded; no probability is shown.", "#fca5a5");
    }
  }

  if (langSelect) {
    langSelect.addEventListener("change", () => {
      if (lastPayload) render(lastPayload);
      else load();
    });
  }

  load();
  window.setInterval(load, 30 * 60 * 1000);
})();