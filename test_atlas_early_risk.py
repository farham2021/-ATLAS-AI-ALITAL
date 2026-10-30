import datetime as dt
import unittest
from unittest.mock import patch

import atlas_crossmarket_risk as cross
import atlas_early_risk as risk


UTC = dt.timezone.utc


def candles(timeframe, closes, volume=100.0, now_ms=None):
    interval = risk.timeframe_ms(timeframe)
    now_ms = int(now_ms if now_ms is not None else dt.datetime(2026, 10, 30, 20, tzinfo=UTC).timestamp() * 1000)
    last = risk.expected_closed_open_ms(timeframe, now_ms)
    start = last - (len(closes) - 1) * interval
    rows = []
    for i, close in enumerate(closes):
        stamp = start + i * interval
        prev = closes[i - 1] if i else close
        op = prev
        hi = max(op, close) * 1.002
        lo = min(op, close) * 0.998
        vol = volume * (3 if i == len(closes) - 1 else 1)
        rows.append([stamp, op, hi, lo, close, vol])
    return rows


class EarlyRiskSignalTests(unittest.TestCase):
    def setUp(self):
        self.now_ms = int(dt.datetime(2026, 10, 30, 20, tzinfo=UTC).timestamp() * 1000)

    def test_closed_candle_boundaries_and_open_bar_rejected(self):
        rows = candles("4h", [100.0] * 60, now_ms=self.now_ms)
        current_open = (self.now_ms // risk.timeframe_ms("4h")) * risk.timeframe_ms("4h")
        rows.append([current_open, 100, 101, 99, 100, 10])
        normalized = risk.normalize_ohlcv(rows, "4h", self.now_ms)
        self.assertEqual(normalized[-1][0], risk.expected_closed_open_ms("4h", self.now_ms))
        self.assertEqual(len(normalized), 60)

    def test_only_explicit_live_value_enables_delivery_mode(self):
        self.assertEqual(risk.normalize_risk_mode("LIVE"), "LIVE")
        self.assertEqual(risk.normalize_risk_mode("SHADOW"), "SHADOW")
        self.assertEqual(risk.normalize_risk_mode("typo"), "SHADOW")

    def test_stale_daily_series_fails_closed(self):
        rows4 = candles("4h", [100.0] * 60, now_ms=self.now_ms)
        rowsd = candles("1d", [100.0] * 60, now_ms=self.now_ms - 8 * 24 * 3600 * 1000)
        with self.assertRaisesRegex(ValueError, "stale closed-candle boundary"):
            risk.score(rows4, rowsd, self.now_ms)

    def test_historical_downside_replay_requires_multiple_closed_candle_factors(self):
        closes4 = [100.0 + i * 0.1 for i in range(60)]
        closes4[-6:] = [102, 100, 98, 96, 94, 88]
        closesd = [100.0 + i * 0.1 for i in range(60)]
        closesd[-1] = 90
        result = risk.score(
            candles("4h", closes4, now_ms=self.now_ms),
            candles("1d", closesd, now_ms=self.now_ms),
            now_ms=self.now_ms, providers={"4h": "LBANK", "1d": "XT"}, rank=3,
        )
        self.assertEqual(result["decision"], "SELL")
        self.assertGreaterEqual(result["confidence"], 80)
        self.assertFalse(result["evidence_is_probability"])
        self.assertTrue(result["technical_flags"])

    def test_partial_downside_is_watch_and_not_sell(self):
        closes4 = [100.0] * 54 + [99.9, 99.8, 99.7, 99.6, 99.5, 99.2]
        closesd = [100.0] * 60
        rows4 = candles("4h", closes4, now_ms=self.now_ms)
        rows4[-1][5] = 100.0
        result = risk.score(
            rows4,
            candles("1d", closesd, now_ms=self.now_ms), now_ms=self.now_ms,
        )
        self.assertEqual(result["decision"], "WATCH")

    def test_stablecoin_depeg_monitor(self):
        now = dt.datetime(2026, 10, 30, 20, tzinfo=UTC)
        quote = {"symbol": "USDC", "current_price": 0.975, "provider": "CoinGecko",
                 "updated_at": now.isoformat()}
        self.assertIsNone(risk.stablecoin_risk({**quote, "current_price": 1.001}, now=now))
        alert = risk.stablecoin_risk(quote, now=now)
        self.assertEqual(alert["decision"], "SELL")
        self.assertIn("انحراف قیمت", alert["flags"][0])
        stale = {**quote, "updated_at": (now - dt.timedelta(hours=1)).isoformat()}
        self.assertIsNone(risk.stablecoin_risk(stale, now=now))

    def test_current_top100_and_personal_union(self):
        market_rows = [
            {"symbol": f"C{i}", "market_cap_rank": i + 1, "current_price": 1.0,
             "price_change_percentage_24h": 0.0, "last_updated": "2026-10-30T20:00:00Z"}
            for i in range(100)
        ]
        with patch.object(risk, "request_json", return_value=market_rows):
            universe, provider = risk.fetch_universe()
        symbols = {x["symbol"] for x in universe}
        self.assertEqual(provider, "CoinGecko")
        self.assertEqual(len(universe), 100 + len(set(risk.PERSONAL_ASSETS) - {f"C{i}" for i in range(100)}))
        self.assertTrue(set(risk.PERSONAL_ASSETS).issubset(symbols))


class CrossMarketEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 30, 20, tzinfo=UTC)

    def test_brsapi_tse_percent_and_flow_schema(self):
        rows = [{
            "symbol": "TSE_MARKET", "captured_at": self.now.isoformat(),
            "payload": {"breadth": 30.0, "market_real_net_volume": -100,
                        "market_real_flow_direction": "OUTFLOW", "provider": "brsapi_allsymbols"},
        }]
        out = cross.market_risks("atlas_tse_snapshots", rows=rows, now=self.now)
        self.assertEqual(out[0]["decision"], "WATCH")
        self.assertIn("خروج پول حقیقی", " ".join(out[0]["flags"]))

    def test_tse_breadth_is_percent_not_fraction(self):
        rows = [{
            "symbol": "TSE_MARKET", "captured_at": self.now.isoformat(),
            "payload": {"breadth": 64.5, "market_real_net_volume": 500,
                        "market_real_flow_direction": "INFLOW", "provider": "brsapi_allsymbols"},
        }]
        self.assertEqual(cross.market_risks("atlas_tse_snapshots", rows=rows, now=self.now), [])

    def test_very_weak_breadth_without_outflow_stays_watch(self):
        rows = [{
            "symbol": "TSE_MARKET", "captured_at": self.now.isoformat(),
            "payload": {"breadth": 15.0, "market_real_net_volume": 500,
                        "market_real_flow_direction": "INFLOW", "provider": "brsapi_allsymbols"},
        }]
        out = cross.market_risks("atlas_tse_snapshots", rows=rows, now=self.now)
        self.assertEqual(out[0]["decision"], "WATCH")

    def test_fund_warning_requires_decline_and_real_outflow(self):
        rows = [{
            "symbol": "عیار", "fund_type": "ETF", "price": 100,
            "captured_at": self.now.isoformat(),
            "payload": {"pct": -4.5, "real_flow_direction": "OUTFLOW", "real_buyer_power": 0.49},
        }]
        out = cross.market_risks("atlas_fund_snapshots", rows=rows, now=self.now)
        self.assertEqual(out[0]["decision"], "REDUCE")
        self.assertEqual(out[0]["asset_group"], "صندوق")

    def test_global_silver_drawdown_is_not_double_counted_as_derived_fair_price(self):
        rows = [
            {"symbol": "SILVER999_FAIR", "captured_at": self.now.isoformat(), "price": 430000,
             "payload": {"provider": "atlas_derived", "derived": True}},
            {"symbol": "XAGUSD", "captured_at": self.now.isoformat(), "price": 48.95,
             "payload": {"provider": "brsapi_commodity", "raw": {"change_percent": -6.79}}},
        ]
        out = cross.market_risks("atlas_market_snapshots", rows=rows, now=self.now)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol"], "XAGUSD")
        self.assertEqual(out[0]["decision"], "REDUCE")

    def test_stale_iran_snapshot_never_creates_alert(self):
        rows = [{"symbol": "TSE_MARKET", "captured_at": (self.now - dt.timedelta(days=3)).isoformat(),
                 "payload": {"breadth": 10, "market_real_flow_direction": "OUTFLOW"}}]
        self.assertEqual(cross.market_risks("atlas_tse_snapshots", max_age=36, rows=rows, now=self.now), [])


class FakeStore:
    def __init__(self):
        self.states = {}
        self.events = {}

    def state(self, symbol):
        return self.states.get(symbol)

    def event(self, event_key):
        return self.events.get(event_key)

    def upsert_event(self, row):
        self.events[row["event_key"]] = row

    def update_event(self, event_key, telegram_sent, details):
        self.events[event_key]["telegram_sent"] = telegram_sent
        self.events[event_key]["details"] = details

    def update_state(self, symbol, level, notified_at):
        self.states[symbol] = {"symbol": symbol, "level": level, "notified_at": notified_at}


class DeliveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 30, 20, tzinfo=UTC)
        self.store = FakeStore()
        self.candidate = {
            "symbol": "BTC", "asset_group": "کریپتو", "decision": "REDUCE", "confidence": 78,
            "evidence_is_probability": False, "price": 100.0, "price_unit": "USDT", "change_pct": -6.2,
            "volume_ratio": 2.0, "flags": ["شکست حمایت"], "technical_flags": ["شکست حمایت"],
            "providers": {"4h": "LBANK", "1d": "XT"}, "timestamp": self.now.isoformat(),
            "last_closed_4h_ms": 1793380800000, "support": 103.0,
        }

    @patch("atlas_early_risk.telegram_preflight", return_value={"username": "atlas_test"})
    def test_audit_is_persisted_before_send_and_delivery_state_is_recorded(self, _preflight):
        def send(message, chat):
            self.assertIn("USDT", message)
            event = next(iter(self.store.events.values()))
            self.assertEqual(event["details"]["delivery"]["status"], "ATTEMPTING")
            self.assertEqual(chat, "-100123")
            return {"message_id": 55}

        result = risk.deliver_candidates([self.candidate], self.store, send,
                                         token="token", group="-100123", now=self.now)
        self.assertEqual(result["sent"], 1)
        event = next(iter(self.store.events.values()))
        self.assertTrue(event["telegram_sent"])
        self.assertEqual(event["details"]["delivery"]["status"], "SENT")
        self.assertEqual(self.store.states["BTC"]["level"], "REDUCE")

    @patch("atlas_early_risk.telegram_preflight", return_value={"username": "atlas_test"})
    def test_repeat_is_suppressed_by_event_key_and_six_hour_state(self, _preflight):
        calls = []
        result = risk.deliver_candidates([self.candidate], self.store,
                                         lambda message, chat: calls.append(message) or {"message_id": 1},
                                         token="token", group="-100123", now=self.now)
        self.assertEqual(result["sent"], 1)
        again = risk.deliver_candidates([self.candidate], self.store,
                                        lambda message, chat: calls.append(message) or {"message_id": 2},
                                        token="token", group="-100123", now=self.now + dt.timedelta(minutes=30))
        self.assertEqual(again["sent"], 0)
        self.assertEqual(len(calls), 1)

    @patch("atlas_early_risk.telegram_preflight", return_value={"username": "atlas_test"})
    def test_ambiguous_telegram_timeout_is_not_automatically_resent(self, _preflight):
        def fail(_message, _chat):
            raise TimeoutError("test timeout")
        result = risk.deliver_candidates([self.candidate], self.store, fail,
                                         token="token", group="-100123", now=self.now)
        self.assertIn("UNKNOWN", result["errors"][0])
        again = risk.deliver_candidates([self.candidate], self.store,
                                        lambda message, chat: {"message_id": 2},
                                        token="token", group="-100123", now=self.now + dt.timedelta(minutes=30))
        self.assertEqual(again["sent"], 0)

    def test_missing_group_configuration_fails_closed(self):
        result = risk.deliver_candidates([self.candidate], self.store, lambda *_: self.fail("must not send"),
                                         token="", group="", now=self.now)
        self.assertEqual(result["sent"], 0)
        event = next(iter(self.store.events.values()))
        self.assertEqual(event["details"]["delivery"]["status"], "BLOCKED")

    @patch("atlas_early_risk._telegram_call", side_effect=[
        {"id": 7, "username": "atlas_test"}, {"id": -100123}, {"status": "administrator"},
    ])
    def test_telegram_preflight_checks_bot_group_membership_without_sending(self, api_call):
        result = risk.telegram_preflight("token", "-100123")
        self.assertEqual(result["membership_status"], "administrator")
        self.assertTrue(result["send_permission_checked"])
        self.assertEqual(api_call.call_count, 3)
        self.assertEqual(api_call.call_args_list[-1].args[0], "getChatMember")

    @patch("atlas_early_risk._telegram_call", side_effect=[
        {"id": 7, "username": "atlas_test"}, {"id": -100123}, {"status": "left"},
    ])
    def test_telegram_preflight_rejects_bot_outside_group(self, _api_call):
        with self.assertRaisesRegex(RuntimeError, "not a member"):
            risk.telegram_preflight("token", "-100123")

    @patch("atlas_early_risk.urllib.request.urlopen", side_effect=TimeoutError("late response"))
    def test_telegram_send_timeout_is_not_retried_inside_client(self, urlopen):
        with self.assertRaisesRegex(TimeoutError, "outcome is unknown"):
            risk._telegram_call("sendMessage", {"chat_id": "-100123", "text": "test"}, token="token")
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
