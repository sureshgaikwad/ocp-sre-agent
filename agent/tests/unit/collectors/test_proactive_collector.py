"""
Unit tests for ProactiveCollector.

Tests trend detection, anomaly detection, and time-to-failure prediction.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from sre_agent.collectors.proactive_collector import ProactiveCollector
from sre_agent.models.observation import ObservationType, Severity
from sre_agent.config.settings import get_settings


@pytest.fixture
def mock_mcp_registry():
    """Create mock MCP registry."""
    registry = AsyncMock()
    return registry


@pytest.fixture
def proactive_collector(mock_mcp_registry):
    """Create ProactiveCollector instance."""
    return ProactiveCollector(mock_mcp_registry)


@pytest.mark.asyncio
async def test_collect_prometheus_disabled(proactive_collector):
    """Test that collect returns empty list when Prometheus is disabled."""
    with patch('sre_agent.collectors.proactive_collector.get_settings') as mock_settings:
        settings = MagicMock()
        settings.prometheus_enabled = False
        settings.prometheus_url = None
        mock_settings.return_value = settings

        # Re-initialize collector with patched settings
        collector = ProactiveCollector(proactive_collector.mcp_registry)
        observations = await collector.collect()

        assert observations == []


@pytest.mark.asyncio
async def test_collect_memory_trends_not_implemented(proactive_collector):
    """Test that NotImplementedError is caught gracefully."""
    with patch('sre_agent.collectors.proactive_collector.get_settings') as mock_settings:
        settings = MagicMock()
        settings.prometheus_enabled = True
        settings.prometheus_url = "http://prometheus:9090"
        settings.trend_lookback_hours = 24
        settings.proactive_memory_threshold_percent = 80.0
        settings.proactive_cpu_threshold_percent = 80.0
        settings.anomaly_threshold_std = 3.0
        mock_settings.return_value = settings

        collector = ProactiveCollector(proactive_collector.mcp_registry)
        observations = await collector.collect()

        # Should return empty list, not raise exception
        assert observations == []


def test_calculate_trend_increasing(proactive_collector):
    """Test trend calculation for increasing values."""
    # Values trending upward
    values = [
        (1000, 70.0),
        (1060, 75.0),
        (1120, 80.0),
        (1180, 85.0),
        (1240, 90.0)
    ]

    is_increasing, slope = proactive_collector._calculate_trend(values)

    assert is_increasing is True
    assert slope > 0


def test_calculate_trend_decreasing(proactive_collector):
    """Test trend calculation for decreasing values."""
    # Values trending downward
    values = [
        (1000, 90.0),
        (1060, 85.0),
        (1120, 80.0),
        (1180, 75.0),
        (1240, 70.0)
    ]

    is_increasing, slope = proactive_collector._calculate_trend(values)

    assert is_increasing is False
    assert slope < 0


def test_calculate_trend_flat(proactive_collector):
    """Test trend calculation for flat values."""
    # Values staying flat
    values = [
        (1000, 80.0),
        (1060, 80.0),
        (1120, 80.0),
        (1180, 80.0),
        (1240, 80.0)
    ]

    is_increasing, slope = proactive_collector._calculate_trend(values)

    # Slope should be very close to 0
    assert abs(slope) < 0.01


def test_calculate_trend_insufficient_data(proactive_collector):
    """Test trend calculation with insufficient data points."""
    values = [(1000, 70.0)]

    is_increasing, slope = proactive_collector._calculate_trend(values)

    assert is_increasing is False
    assert slope == 0.0


def test_predict_time_to_limit(proactive_collector):
    """Test time-to-limit prediction."""
    # Memory at 85%, increasing by 5% per hour, limit is 100%
    # Time to OOM should be 3 hours
    values = [
        (0, 70.0),      # 0 hours ago
        (3600, 75.0),   # 1 hour ago
        (7200, 80.0),   # 2 hours ago
        (10800, 85.0)   # now
    ]

    time_to_limit = proactive_collector._predict_time_to_limit(
        values, limit=100.0, current=85.0
    )

    # Should predict ~3 hours (10800 seconds)
    assert time_to_limit is not None
    assert 9000 < time_to_limit < 12000  # Allow some variance


def test_predict_time_to_limit_decreasing(proactive_collector):
    """Test time-to-limit prediction for decreasing trend."""
    # Memory decreasing - should return None
    values = [
        (0, 90.0),
        (3600, 85.0),
        (7200, 80.0),
        (10800, 75.0)
    ]

    time_to_limit = proactive_collector._predict_time_to_limit(
        values, limit=100.0, current=75.0
    )

    # Decreasing trend, won't reach limit
    assert time_to_limit is None


def test_detect_anomaly_spike(proactive_collector):
    """Test anomaly detection for CPU spike."""
    with patch('sre_agent.collectors.proactive_collector.get_settings') as mock_settings:
        settings = MagicMock()
        settings.anomaly_threshold_std = 3.0
        mock_settings.return_value = settings

        collector = ProactiveCollector(proactive_collector.mcp_registry)

        # Normal values with sudden spike
        values = [
            (0, 0.1),
            (60, 0.11),
            (120, 0.09),
            (180, 0.10),
            (240, 0.12),
            (300, 0.11),
            (360, 0.10),
            (420, 0.09),
            (480, 0.11),
            (540, 2.5)  # Spike! (z-score > 3)
        ]

        is_anomaly, z_score = collector._detect_anomaly(values)

        assert is_anomaly is True
        assert z_score > 3.0


def test_detect_anomaly_normal(proactive_collector):
    """Test anomaly detection for normal values."""
    with patch('sre_agent.collectors.proactive_collector.get_settings') as mock_settings:
        settings = MagicMock()
        settings.anomaly_threshold_std = 3.0
        mock_settings.return_value = settings

        collector = ProactiveCollector(proactive_collector.mcp_registry)

        # Normal values with typical variance
        values = [
            (0, 0.1),
            (60, 0.11),
            (120, 0.09),
            (180, 0.10),
            (240, 0.12),
            (300, 0.11),
            (360, 0.10),
            (420, 0.09),
            (480, 0.11),
            (540, 0.10)
        ]

        is_anomaly, z_score = collector._detect_anomaly(values)

        assert is_anomaly is False
        assert z_score < 3.0


def test_detect_anomaly_insufficient_data(proactive_collector):
    """Test anomaly detection with insufficient data."""
    values = [(0, 0.1), (60, 0.2)]

    is_anomaly, z_score = proactive_collector._detect_anomaly(values)

    assert is_anomaly is False
    assert z_score == 0.0


def test_detect_anomaly_zero_stdev(proactive_collector):
    """Test anomaly detection when all values are identical."""
    values = [
        (0, 0.1),
        (60, 0.1),
        (120, 0.1),
        (180, 0.1)
    ]

    is_anomaly, z_score = proactive_collector._detect_anomaly(values)

    # No variance, can't detect anomaly
    assert is_anomaly is False
    assert z_score == 0.0


@pytest.mark.asyncio
async def test_query_prometheus_range_not_implemented(proactive_collector):
    """Test that Prometheus query raises NotImplementedError."""
    with pytest.raises(NotImplementedError) as exc_info:
        await proactive_collector._query_prometheus_range(
            query="test_query",
            lookback_hours=24
        )

    assert "ProactiveCollector._query_prometheus_range()" in str(exc_info.value)
    assert "Configure Prometheus integration" in str(exc_info.value)


def test_str_representation(proactive_collector):
    """Test string representation of collector."""
    assert str(proactive_collector) == "ProactiveCollector(monitoring trends and anomalies)"
