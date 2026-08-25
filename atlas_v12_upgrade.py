#!/usr/bin/env python3
"""ATLAS v12 compatibility/API layer."""
from bot12 import *
V12_VERSION="12.0.0"
CONFIRMATION_RULE="2 consecutive H4 closes above resistance"
VOLUME_RULE="volume >= 120% of 20-period average"
def health_check():
    return {"version":V12_VERSION,"forced_signals":False,"fx_source":"tgju.org only",
            "confirmation_rule":CONFIRMATION_RULE,"volume_rule":VOLUME_RULE}
def build_personal_report(portfolio,rates=None): return personal_report(portfolio,rates)
def build_market_report(market,portfolio,metals=None): return build_report(market,portfolio,metals)
def volume_spike_warning(volume_ratio):
    return "CONFIRMED" if volume_ratio is not None and volume_ratio>=1.2 else "NOT CONFIRMED" if volume_ratio is not None else "DATA UNAVAILABLE"
def rsi_divergence(*a,**k): return "UNKNOWN — validated divergence data not supplied"
