"""Compatibility alias: legacy patches and canonical calls share one module object."""
import sys
from atlas.delivery import risk_csv_digest as _canonical
sys.modules[__name__] = _canonical
