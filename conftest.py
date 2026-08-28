"""
ATLAS AI v11.1 — Pytest Configuration
====================================
Global fixtures and configuration for pytest.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def setup_test_env():
    """Setup test environment variables"""
    os.environ.setdefault("ATLAS_RUN_MODE", "TEST")
    os.environ.setdefault("ATLAS_ENGINE", "BOTH")
    os.environ.setdefault("ATLAS_ENABLE_VOICE", "0")
    os.environ.setdefault("ATLAS_AUTO_SEND_VOICE", "0")
    os.environ.setdefault("ATLAS_ENABLE_IMAGE_TABLE", "0")
    os.environ.setdefault("TELEGRAM_TOKEN", "test_token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
    os.environ.setdefault("TELEGRAM_GROUP_CHAT_ID", "67890")
    yield


@pytest.fixture
def mock_results():
    """Mock analysis results"""
    return [
        {
            "coin": "BTC",
            "price": 45000.0,
            "change": 2.5,
            "h4_trend": "BULLISH",
            "d1_trend": "BULLISH",
            "action": "BUY CONFIRMATION",
            "confidence": 85,
            "entry": 45000.0,
            "sl": 44000.0,
            "tp1": 46000.0,
            "tp2": 47000.0,
            "rr": 2.0,
            "support": 44000.0,
            "resistance": 46000.0,
            "rsi": 65.0,
            "macd": "BULLISH",
            "volume_ratio": 1.5,
            "liquidity_score": 80,
            "quality": "HIGH",
            "sr_confidence": "HIGH",
            "candle_trigger": {"state": "BREAKOUT_CLOSED"},
            "source_validation": {
                "price_sources": 3,
                "price_spread_pct": 0.5
            }
        },
        {
            "coin": "ETH",
            "price": 3000.0,
            "change": -1.2,
            "h4_trend": "BEARISH",
            "d1_trend": "BEARISH",
            "action": "SELL CONFIRMATION",
            "confidence": 75,
            "entry": 3000.0,
            "sl": 3100.0,
            "tp1": 2900.0,
            "tp2": 2800.0,
            "rr": 2.0,
            "support": 2800.0,
            "resistance": 3100.0,
            "rsi": 35.0,
            "macd": "BEARISH",
            "volume_ratio": 1.2,
            "liquidity_score": 75,
            "quality": "MEDIUM",
            "sr_confidence": "MEDIUM",
            "candle_trigger": {"state": "BREAKDOWN_CLOSED"},
            "source_validation": {
                "price_sources": 2,
                "price_spread_pct": 1.2
            }
        }
    ]


@pytest.fixture
def mock_btc_regime():
    """Mock BTC regime"""
    return {
        "regime": "RISK_ON",
        "h4": "BULLISH",
        "d1": "BULLISH",
        "rsi4": 65.0,
        "rsi1": 60.0,
        "volume_ratio": 1.2,
        "reason": "BTC 4H + 1D bullish"
    }


@pytest.fixture
def mock_news():
    """Mock news data"""
    return {
        "bias": "POSITIVE",
        "impact": "NORMAL",
        "items": [
            {"title": "Bitcoin ETF approved", "url": "https://example.com", "source": "NewsAPI"},
            {"title": "Market shows strength", "url": "https://example.com", "source": "CryptoPanic"}
        ]
    }


@pytest.fixture
def mock_macro():
    """Mock macro data"""
    return {
        "DXY": 102.5,
        "GOLD": 2050.0,
        "SILVER": 25.5,
        "COPPER": 4.20,
        "WTI": 75.0,
        "BRENT": 80.0
    }


def pytest_configure(config):
    """Pytest configuration hook"""
    config.addinivalue_line(
        "markers", "slow: mark test as slow to run"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "api: mark test that requires API access"
    )
