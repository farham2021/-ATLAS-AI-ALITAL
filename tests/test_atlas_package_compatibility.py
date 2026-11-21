"""Check relocated ATLAS library modules retain their public compatibility API."""
import importlib
import unittest

MODULES = {
    "atlas_forecast_engine": "atlas.intelligence.forecast_engine",
    "atlas_futures_costs": "atlas.trading.futures_costs",
    "atlas_portfolio_risk_shield": "atlas.trading.portfolio_risk_shield",
    "atlas_external_evidence_gate": "atlas.research.external_evidence_gate",
    "atlas_quant_risk_v2": "atlas.intelligence.quant_risk_v2",
    "atlas_top100_universe": "atlas.markets.top100_universe",
    "atlas_risk_csv_digest": "atlas.delivery.risk_csv_digest",
    "atlas_telegram_receipts": "atlas.delivery.telegram_receipts",
    "atlas_risk_top20_selection": "atlas.risk_top20_selection",
    "atlas_delivery_policy_shadow": "atlas.delivery_policy_shadow",
}

class TestAtlasPackageCompatibility(unittest.TestCase):
    def test_public_exports(self):
        for legacy, canonical in MODULES.items():
            with self.subTest(module=legacy):
                old = importlib.import_module(legacy)
                new = importlib.import_module(canonical)
                for name, obj in vars(new).items():
                    if name.startswith("_"):
                        continue
                    self.assertTrue(hasattr(old, name), name)
                    self.assertIs(getattr(old, name), obj)

if __name__ == "__main__":
    unittest.main()
