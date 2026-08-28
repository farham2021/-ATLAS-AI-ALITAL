from pathlib import Path
import csv, io, sys, types

# The CI workflow installs ccxt. This test can also run without network/package access.
ccxt_stub = types.ModuleType('ccxt')
sys.modules.setdefault('ccxt', ccxt_stub)
sys.path.insert(0, str(Path(__file__).parent))
import bot

bot._metal_analysis = lambda x: {
    'coin': x, 'price': 1.0, 'support': 0.9, 'resistance': 1.1,
    'action': 'BULLISH WATCH', 'decision_state': 'BULLISH WATCH',
    'h4_trend': 'BULLISH', 'd1_trend': 'BULLISH', 'confidence': 60,
}

valid = {
    'coin': 'BTC', 'price': 100.0, 'support': 90.0, 'resistance': 110.0,
    'entry': 101.0, 'sl': 95.0, 'tp1': 105.0, 'tp2': 113.0,
    'h4_trend': 'BULLISH', 'd1_trend': 'BULLISH',
    'action': 'BUY CONFIRMATION', 'decision_state': 'BUY CONFIRMATION',
    'direction': 'LONG', 'confidence': 80,
    # Invalidation fields
    'signal_id': 'BTC-LON-1234567890',
    'contradiction_status': 'NO_CONTRADICTION',
    'contradictions': [],
    'no_trade_reasons': [],
    'should_trade': True,
}
invalid = dict(valid)
invalid.update({'coin': 'ETH', 'tp2': 99.0, 'confidence': 95, 'signal_id': 'ETH-LON-0987654321'})

# Test CSV export
text = bot.generate_csv_report([valid, invalid], ['BTC', 'ETH'], [])
rows = list(csv.DictReader(io.StringIO(text)))
assert any(r['Symbol'] == 'BTC' and r['Group'] == 'PERSONAL_PORTFOLIO' for r in rows)
eth = next(r for r in rows if r['Symbol'] == 'ETH')
assert eth['Entry'] == '' and eth['SL'] == '' and eth['TP2'] == '' and eth['R/R'] == ''
assert {r['Symbol'] for r in rows} >= {'BTC', 'ETH', 'GOLD', 'SILVER', 'COPPER'}
print(f'PASS: v11.1 CSV export test ({len(rows)} rows)')

# Test Invalidation & No-Trade fields
from core.invalidation import SignalLifecycle, InvalidationEngine, NoTradeEngine, ContradictionDetector

signal_lifecycle = SignalLifecycle()
signal_id = signal_lifecycle.create_signal(
    coin='BTC',
    direction='LONG',
    entry=101.0,
    sl=95.0,
    tp1=105.0,
    tp2=113.0,
    confidence=80,
    candle_ts=1234567890,
    reason='Test signal'
)
assert signal_id.startswith('BTC-LON-')
assert len(signal_id) > 10

# Test contradiction detector
contradiction_detector = ContradictionDetector()
status, contradictions = contradiction_detector.detect({
    'direction': 'LONG',
    'rsi': 80,  # Overbought
    'macd': 'BULLISH',
    'h4_trend': 'BULLISH',
    'd1_trend': 'BULLISH',
    'btc_regime': {'regime': 'RISK_ON'},
})
assert status == 'LOW_CONTRADICTION' or status == 'HIGH_CONTRADICTION'
print(f'PASS: Contradiction detector test ({status})')

print('PASS: v11.1 invalidation test suite')
