"""
Unit tests for ProactiveAnalyzer.

Tests preventive diagnosis and urgency calculation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from sre_agent.analyzers.proactive_analyzer import ProactiveAnalyzer
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.models.diagnosis import DiagnosisCategory, Confidence


@pytest.fixture
def mock_mcp_registry():
    """Create mock MCP registry."""
    return AsyncMock()


@pytest.fixture
def proactive_analyzer(mock_mcp_registry):
    """Create ProactiveAnalyzer instance."""
    return ProactiveAnalyzer(mock_mcp_registry)


def test_can_analyze_memory_trend(proactive_analyzer):
    """Test that analyzer can handle memory trend observations."""
    observation = Observation(
        type=ObservationType.TREND_MEMORY_INCREASING,
        severity=Severity.WARNING,
        namespace="test-ns",
        resource_kind="Pod",
        resource_name="test-pod",
        message="Memory trending upward"
    )

    assert proactive_analyzer.can_analyze(observation) is True


def test_can_analyze_cpu_trend(proactive_analyzer):
    """Test that analyzer can handle CPU trend observations."""
    observation = Observation(
        type=ObservationType.TREND_CPU_INCREASING,
        severity=Severity.WARNING,
        namespace="test-ns",
        resource_kind="Pod",
        resource_name="test-pod",
        message="CPU trending upward"
    )

    assert proactive_analyzer.can_analyze(observation) is True


def test_can_analyze_error_trend(proactive_analyzer):
    """Test that analyzer can handle error rate trends."""
    observation = Observation(
        type=ObservationType.TREND_ERROR_RATE_RISING,
        severity=Severity.WARNING,
        namespace="test-ns",
        resource_kind="Service",
        resource_name="test-svc",
        message="Error rate increasing"
    )

    assert proactive_analyzer.can_analyze(observation) is True


def test_can_analyze_anomaly(proactive_analyzer):
    """Test that analyzer can handle anomaly observations."""
    observation = Observation(
        type=ObservationType.ANOMALY_CPU_SPIKE,
        severity=Severity.WARNING,
        namespace="test-ns",
        resource_kind="Pod",
        resource_name="test-pod",
        message="CPU spike detected"
    )

    assert proactive_analyzer.can_analyze(observation) is True


def test_cannot_analyze_other_types(proactive_analyzer):
    """Test that analyzer rejects non-proactive observations."""
    observation = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="test-ns",
        resource_kind="Pod",
        resource_name="test-pod",
        message="Pod failed"
    )

    assert proactive_analyzer.can_analyze(observation) is False


@pytest.mark.asyncio
async def test_analyze_memory_trend_urgent(proactive_analyzer):
    """Test memory trend analysis with URGENT urgency (< 1 hour)."""
    observation = Observation(
        type=ObservationType.TREND_MEMORY_INCREASING,
        severity=Severity.WARNING,
        namespace="ecommerce",
        resource_kind="Pod",
        resource_name="checkout-api",
        message="Memory trending upward: 92% of limit. Predicted OOM in 0.5h",
        raw_data={
            "container": "app",
            "current_percent": 92.0,
            "trend_slope": 0.1,
            "time_to_limit_seconds": 1800,  # 30 minutes
            "historical_values": []
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.PROACTIVE_MEMORY_INCREASE
    assert diagnosis.confidence == Confidence.HIGH
    assert diagnosis.recommended_tier == 2
    assert "URGENT" in diagnosis.evidence.get("urgency", "")
    assert "Increase memory limit by 50%" in diagnosis.recommended_actions


@pytest.mark.asyncio
async def test_analyze_memory_trend_high(proactive_analyzer):
    """Test memory trend analysis with HIGH urgency (1-24 hours)."""
    observation = Observation(
        type=ObservationType.TREND_MEMORY_INCREASING,
        severity=Severity.WARNING,
        namespace="ecommerce",
        resource_kind="Pod",
        resource_name="checkout-api",
        message="Memory trending upward: 85% of limit. Predicted OOM in 5h",
        raw_data={
            "container": "app",
            "current_percent": 85.0,
            "trend_slope": 0.05,
            "time_to_limit_seconds": 18000,  # 5 hours
            "historical_values": []
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.PROACTIVE_MEMORY_INCREASE
    assert "HIGH" in diagnosis.evidence.get("urgency", "")


@pytest.mark.asyncio
async def test_analyze_memory_trend_medium(proactive_analyzer):
    """Test memory trend analysis with MEDIUM urgency (> 24 hours)."""
    observation = Observation(
        type=ObservationType.TREND_MEMORY_INCREASING,
        severity=Severity.WARNING,
        namespace="ecommerce",
        resource_kind="Pod",
        resource_name="checkout-api",
        message="Memory trending upward: 82% of limit. Predicted OOM in 48h",
        raw_data={
            "container": "app",
            "current_percent": 82.0,
            "trend_slope": 0.02,
            "time_to_limit_seconds": 172800,  # 48 hours
            "historical_values": []
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.PROACTIVE_MEMORY_INCREASE
    assert "MEDIUM" in diagnosis.evidence.get("urgency", "")


@pytest.mark.asyncio
async def test_analyze_cpu_trend(proactive_analyzer):
    """Test CPU trend analysis."""
    observation = Observation(
        type=ObservationType.TREND_CPU_INCREASING,
        severity=Severity.WARNING,
        namespace="production",
        resource_kind="Pod",
        resource_name="api-server",
        message="CPU trending upward: 88% of limit",
        raw_data={
            "container": "app",
            "current_percent": 88.0,
            "trend_slope": 0.03,
            "historical_values": []
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.PROACTIVE_CPU_INCREASE
    assert diagnosis.confidence == Confidence.HIGH
    assert diagnosis.recommended_tier == 2
    assert "Increase CPU limit by 30%" in diagnosis.recommended_actions
    assert "current_percent" in diagnosis.evidence


@pytest.mark.asyncio
async def test_analyze_error_rate_trend(proactive_analyzer):
    """Test error rate trend analysis."""
    observation = Observation(
        type=ObservationType.TREND_ERROR_RATE_RISING,
        severity=Severity.WARNING,
        namespace="production",
        resource_kind="Service",
        resource_name="payment-api",
        message="Error rate increasing: 150 errors/hour",
        raw_data={
            "current_error_rate": 150,
            "trend_slope": 0.05,
            "historical_values": []
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.PROACTIVE_SCALE_UP
    assert diagnosis.confidence == Confidence.MEDIUM
    assert diagnosis.recommended_tier == 2
    assert "Scale deployment to 3 replicas" in diagnosis.recommended_actions


@pytest.mark.asyncio
async def test_analyze_cpu_anomaly(proactive_analyzer):
    """Test CPU anomaly analysis."""
    observation = Observation(
        type=ObservationType.ANOMALY_CPU_SPIKE,
        severity=Severity.WARNING,
        namespace="production",
        resource_kind="Pod",
        resource_name="worker-1",
        message="CPU spike detected: 2.5 cores (z-score: 4.2)",
        raw_data={
            "current_value": 2.5,
            "z_score": 4.2,
            "threshold_std": 3.0
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.POD_PERFORMANCE_DEGRADED
    assert diagnosis.confidence == Confidence.MEDIUM
    assert diagnosis.recommended_tier == 3
    assert "investigation" in diagnosis.root_cause.lower()


@pytest.mark.asyncio
async def test_analyze_memory_anomaly(proactive_analyzer):
    """Test memory anomaly analysis."""
    observation = Observation(
        type=ObservationType.ANOMALY_MEMORY_SPIKE,
        severity=Severity.WARNING,
        namespace="production",
        resource_kind="Pod",
        resource_name="cache-1",
        message="Memory spike detected",
        raw_data={
            "current_value": 4.5,
            "z_score": 3.8
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.POD_PERFORMANCE_DEGRADED
    assert diagnosis.recommended_tier == 3


@pytest.mark.asyncio
async def test_analyze_restart_count_trend(proactive_analyzer):
    """Test restart count trend analysis."""
    observation = Observation(
        type=ObservationType.TREND_RESTART_COUNT_RISING,
        severity=Severity.WARNING,
        namespace="production",
        resource_kind="Pod",
        resource_name="unstable-app",
        message="Restart count increasing",
        raw_data={
            "current_count": 15,
            "trend_slope": 0.5
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.POD_PERFORMANCE_DEGRADED
    assert diagnosis.recommended_tier == 3


@pytest.mark.asyncio
async def test_analyze_alert_storm(proactive_analyzer):
    """Test alert storm analysis."""
    observation = Observation(
        type=ObservationType.ALERT_STORM,
        severity=Severity.CRITICAL,
        namespace="production",
        resource_kind="Cluster",
        resource_name="ocp-prod",
        message="Alert storm: 25 alerts in 3 minutes",
        raw_data={
            "alert_count": 25,
            "time_window_seconds": 180
        }
    )

    diagnosis = await proactive_analyzer.analyze(observation)

    assert diagnosis is not None
    assert diagnosis.category == DiagnosisCategory.CLUSTER_WIDE_DEGRADATION
    assert diagnosis.confidence == Confidence.HIGH
    assert diagnosis.recommended_tier == 3
    assert "alert storm" in diagnosis.root_cause.lower()


def test_str_representation(proactive_analyzer):
    """Test string representation of analyzer."""
    assert str(proactive_analyzer) == "ProactiveAnalyzer(preventive recommendations)"
