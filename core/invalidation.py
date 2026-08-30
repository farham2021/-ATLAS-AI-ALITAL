# ============================================================
# ATLAS v11.1 — INVALIDATION ENGINE
# ============================================================
# Signal Lifecycle Management + Invalidation Logic
# ============================================================

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple

# ============================================================
# SIGNAL LIFECYCLE STATES
# ============================================================

SIGNAL_STATES = {
    "CREATED": "Signal generated, not yet confirmed",
    "CONFIRMED": "Signal confirmed by candle close",
    "ACTIVE": "Signal is active and valid",
    "TP1": "Take Profit 1 hit",
    "TP2": "Take Profit 2 hit",
    "TP3": "Take Profit 3 hit",
    "SL": "Stop Loss hit",
    "EXPIRED": "Signal expired (TTL reached)",
    "INVALIDATED": "Signal invalidated by regime/structural change",
    "CANCELLED": "Signal manually cancelled",
}

class SignalLifecycle:
    """مدیریت چرخه حیات سیگنال"""
    
    def __init__(self):
        self.active_signals = {}
        self.history = []
    
    def create_signal(self, coin: str, direction: str, entry: float, sl: float, 
                      tp1: float, tp2: float, confidence: float, 
                      candle_ts: int, reason: str) -> str:
        signal_id = self._generate_id(coin, direction, candle_ts)
        signal = {
            "id": signal_id,
            "coin": coin,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "confidence": confidence,
            "state": "CREATED",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "confirmed_at": None,
            "activated_at": None,
            "closed_at": None,
            "candle_ts": candle_ts,
            "reason": reason,
            "invalidation_reasons": [],
            "ttl_hours": 24,
        }
        self.active_signals[signal_id] = signal
        self.history.append(signal)
        return signal_id
    
    def _generate_id(self, coin: str, direction: str, candle_ts: int) -> str:
        raw = f"{coin}-{direction}-{candle_ts}-{datetime.now().timestamp()}"
        return f"{coin}-{direction[:3]}-{hashlib.md5(raw.encode()).hexdigest()[:10]}"
    
    def confirm_signal(self, signal_id: str) -> bool:
        if signal_id not in self.active_signals:
            return False
        self.active_signals[signal_id]["state"] = "CONFIRMED"
        self.active_signals[signal_id]["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        return True
    
    def activate_signal(self, signal_id: str) -> bool:
        if signal_id not in self.active_signals:
            return False
        self.active_signals[signal_id]["state"] = "ACTIVE"
        self.active_signals[signal_id]["activated_at"] = datetime.now(timezone.utc).isoformat()
        return True
    
    def close_signal(self, signal_id: str, outcome: str, exit_price: float) -> bool:
        if signal_id not in self.active_signals:
            return False
        self.active_signals[signal_id]["state"] = outcome
        self.active_signals[signal_id]["closed_at"] = datetime.now(timezone.utc).isoformat()
        self.active_signals[signal_id]["exit_price"] = exit_price
        return True
    
    def invalidate_signal(self, signal_id: str, reason: str) -> bool:
        if signal_id not in self.active_signals:
            return False
        self.active_signals[signal_id]["state"] = "INVALIDATED"
        self.active_signals[signal_id]["invalidation_reasons"].append(reason)
        self.active_signals[signal_id]["closed_at"] = datetime.now(timezone.utc).isoformat()
        return True
    
    def get_signal(self, signal_id: str) -> Optional[Dict]:
        return self.active_signals.get(signal_id)
    
    def get_all_active(self) -> List[Dict]:
        return [s for s in self.active_signals.values() 
                if s["state"] in ("CREATED", "CONFIRMED", "ACTIVE")]
    
    def expire_expired(self) -> List[str]:
        expired = []
        now = datetime.now(timezone.utc)
        for sid, signal in self.active_signals.items():
            if signal["state"] not in ("CREATED", "CONFIRMED", "ACTIVE"):
                continue
            created = datetime.fromisoformat(signal["created_at"])
            age_hours = (now - created).total_seconds() / 3600
            if age_hours > signal["ttl_hours"]:
                signal["state"] = "EXPIRED"
                signal["closed_at"] = now.isoformat()
                expired.append(sid)
        return expired


# ============================================================
# INVALIDATION ENGINE
# ============================================================

class InvalidationEngine:
    """تشخیص دلایل باطل‌سازی سیگنال"""
    
    def __init__(self):
        self.contradictions = []
    
    def check_invalidation(self, signal: Dict, current_data: Dict) -> Tuple[bool, List[str]]:
        reasons = []
        reasons.extend(self._check_technical_invalidation(signal, current_data))
        reasons.extend(self._check_regime_invalidation(signal, current_data))
        reasons.extend(self._check_volume_invalidation(signal, current_data))
        reasons.extend(self._check_time_invalidation(signal))
        reasons.extend(self._check_contradiction(signal, current_data))
        return len(reasons) > 0, reasons
    
    def _check_technical_invalidation(self, signal: Dict, data: Dict) -> List[str]:
        reasons = []
        price = data.get("price")
        support = data.get("support")
        resistance = data.get("resistance")
        direction = signal.get("direction", "").upper()
        if price is None:
            return reasons
        if direction == "LONG":
            if support is not None and price < support * 0.995:
                reasons.append("Price closed below support")
            if resistance is not None and price < resistance * 0.995:
                reasons.append("Failed to break resistance")
        elif direction == "SHORT":
            if resistance is not None and price > resistance * 1.005:
                reasons.append("Price closed above resistance")
            if support is not None and price > support * 1.005:
                reasons.append("Failed to break support")
        return reasons
    
    def _check_regime_invalidation(self, signal: Dict, data: Dict) -> List[str]:
        reasons = []
        btc_regime = data.get("btc_regime", {}).get("regime", "UNKNOWN")
        direction = signal.get("direction", "").upper()
        if direction == "LONG" and btc_regime == "RISK_OFF":
            reasons.append("BTC regime turned risk-off")
        elif direction == "SHORT" and btc_regime == "RISK_ON":
            reasons.append("BTC regime turned risk-on")
        h4_trend = data.get("h4_trend", "UNKNOWN")
        d1_trend = data.get("d1_trend", "UNKNOWN")
        if direction == "LONG" and h4_trend in ("BEARISH", "MIXED"):
            reasons.append("H4 trend no longer bullish")
        elif direction == "SHORT" and h4_trend in ("BULLISH", "MIXED"):
            reasons.append("H4 trend no longer bearish")
        return reasons
    
    def _check_volume_invalidation(self, signal: Dict, data: Dict) -> List[str]:
        reasons = []
        volume_ratio = data.get("volume_ratio")
        if volume_ratio is not None and volume_ratio < 0.6:
            reasons.append("Volume collapsed below threshold")
        return reasons
    
    def _check_time_invalidation(self, signal: Dict) -> List[str]:
        reasons = []
        created = datetime.fromisoformat(signal["created_at"])
        age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        if age_hours > signal.get("ttl_hours", 24):
            reasons.append("Signal TTL expired")
        return reasons
    
    def _check_contradiction(self, signal: Dict, data: Dict) -> List[str]:
        reasons = []
        direction = signal.get("direction", "").upper()
        rsi = data.get("rsi")
        macd = data.get("macd", "UNKNOWN")
        if direction == "LONG" and rsi is not None and rsi >= 75:
            reasons.append("RSI overbought (contradiction)")
        elif direction == "SHORT" and rsi is not None and rsi <= 25:
            reasons.append("RSI oversold (contradiction)")
        if direction == "LONG" and macd == "BEARISH":
            reasons.append("MACD bearish (contradiction)")
        elif direction == "SHORT" and macd == "BULLISH":
            reasons.append("MACD bullish (contradiction)")
        return reasons


# ============================================================
# NO-TRADE ENGINE
# ============================================================

class NoTradeEngine:
    """تشخیص دلایل عدم ورود به معامله"""
    
    def __init__(self):
        self.reasons = []
    
    def should_trade(self, result: Dict, btc_regime: Dict, breadth: Dict) -> Tuple[bool, List[str]]:
        reasons = []
        reasons.extend(self._check_basic_conditions(result))
        reasons.extend(self._check_rr(result))
        reasons.extend(self._check_regime(result, btc_regime, breadth))
        reasons.extend(self._check_liquidity(result))
        reasons.extend(self._check_data_quality(result))
        reasons.extend(self._check_near_levels(result))
        reasons.extend(self._check_repeat_signal(result))
        return len(reasons) == 0, reasons
    
    def _check_basic_conditions(self, result: Dict) -> List[str]:
        reasons = []
        if result.get("direction") == "NONE":
            reasons.append("No valid direction detected")
        if result.get("confidence", 0) < 55:
            reasons.append(f"Confidence {result.get('confidence', 0)}% < 55%")
        if result.get("gate") == "BLOCK":
            reasons.append(f"Gate blocked: {result.get('gate_reason', 'Unknown')}")
        return reasons
    
    def _check_rr(self, result: Dict) -> List[str]:
        reasons = []
        rr = result.get("rr")
        min_rr = 2.0
        if rr is None:
            reasons.append("R/R not calculated")
        elif rr < min_rr:
            reasons.append(f"R/R {rr:.2f} < {min_rr:.1f}")
        return reasons
    
    def _check_regime(self, result: Dict, btc_regime: Dict, breadth: Dict) -> List[str]:
        reasons = []
        direction = result.get("direction", "").upper()
        regime = btc_regime.get("regime", "UNKNOWN")
        breadth_state = breadth.get("state", "UNKNOWN")
        if direction == "LONG" and regime == "RISK_OFF":
            reasons.append("BTC regime risk-off")
        elif direction == "SHORT" and regime == "RISK_ON":
            reasons.append("BTC regime risk-on")
        if direction == "LONG" and breadth_state == "BEARISH":
            reasons.append("Market breadth bearish")
        elif direction == "SHORT" and breadth_state == "BULLISH":
            reasons.append("Market breadth bullish")
        return reasons
    
    def _check_liquidity(self, result: Dict) -> List[str]:
        reasons = []
        liquidity = result.get("liquidity", "LOW")
        liquidity_score = result.get("liquidity_score", 0)
        if liquidity == "LOW" or liquidity_score < 45:
            reasons.append(f"Low liquidity: {liquidity}")
        return reasons
    
    def _check_data_quality(self, result: Dict) -> List[str]:
        reasons = []
        quality = result.get("quality", "LOW")
        spread = result.get("spread", 100)
        if quality == "LOW":
            reasons.append("Data quality low")
        if spread > 3:
            reasons.append(f"Spread too high: {spread:.2f}%")
        return reasons
    
    def _check_near_levels(self, result: Dict) -> List[str]:
        reasons = []
        entry = result.get("entry")
        direction = result.get("direction", "").upper()
        resistance = result.get("resistance")
        support = result.get("support")
        if entry is None or entry <= 0:
            return reasons
        if direction == "LONG" and resistance is not None:
            distance = (resistance - entry) / entry * 100
            if distance < 1.5:
                reasons.append(f"Resistance too close ({distance:.1f}%)")
        if direction == "SHORT" and support is not None:
            distance = (entry - support) / entry * 100
            if distance < 1.5:
                reasons.append(f"Support too close ({distance:.1f}%)")
        return reasons
    
    def _check_repeat_signal(self, result: Dict) -> List[str]:
        reasons = []
        if result.get("repeat_signal", False):
            reasons.append("Repeat signal detected")
        return reasons


# ============================================================
# CONTRADICTION DETECTOR
# ============================================================

class ContradictionDetector:
    """تشخیص تضاد در سیگنال‌ها"""
    
    def detect(self, result: Dict) -> Tuple[str, List[str]]:
        contradictions = []
        direction = result.get("direction", "").upper()
        if direction == "NONE":
            return "NO_DIRECTION", []
        indicators = {
            "rsi": result.get("rsi"),
            "macd": result.get("macd", "UNKNOWN"),
            "h4_trend": result.get("h4_trend", "UNKNOWN"),
            "d1_trend": result.get("d1_trend", "UNKNOWN"),
            "btc_regime": result.get("btc_regime", {}).get("regime", "UNKNOWN"),
        }
        if direction == "LONG":
            if indicators["rsi"] is not None and indicators["rsi"] >= 75:
                contradictions.append("RSI overbought vs LONG")
            if indicators["macd"] == "BEARISH":
                contradictions.append("MACD bearish vs LONG")
            if indicators["h4_trend"] in ("BEARISH", "MIXED"):
                contradictions.append("H4 trend not bullish vs LONG")
            if indicators["btc_regime"] == "RISK_OFF":
                contradictions.append("BTC risk-off vs LONG")
        elif direction == "SHORT":
            if indicators["rsi"] is not None and indicators["rsi"] <= 25:
                contradictions.append("RSI oversold vs SHORT")
            if indicators["macd"] == "BULLISH":
                contradictions.append("MACD bullish vs SHORT")
            if indicators["h4_trend"] in ("BULLISH", "MIXED"):
                contradictions.append("H4 trend not bearish vs SHORT")
            if indicators["btc_regime"] == "RISK_ON":
                contradictions.append("BTC risk-on vs SHORT")
        if len(contradictions) >= 2:
            return "HIGH_CONTRADICTION", contradictions
        elif len(contradictions) >= 1:
            return "LOW_CONTRADICTION", contradictions
        else:
            return "NO_CONTRADICTION", contradictions
