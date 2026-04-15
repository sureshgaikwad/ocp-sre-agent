"""
Unit tests for AlertCorrelator.

Tests alert correlation, dependency graphs, and root cause detection.
"""

import pytest
from datetime import datetime, timedelta

from sre_agent.orchestrator.alert_correlator import (
    AlertCorrelator,
    DependencyGraph,
    CorrelatedObservationGroup
)
from sre_agent.models.observation import Observation, ObservationType, Severity


@pytest.fixture
def alert_correlator():
    """Create AlertCorrelator instance."""
    return AlertCorrelator()


@pytest.fixture
def dependency_graph():
    """Create DependencyGraph instance."""
    return DependencyGraph()


# DependencyGraph Tests

def test_add_dependency(dependency_graph):
    """Test adding dependency to graph."""
    dependency_graph.add_dependency("Node/worker-1", "Pod/ns1/app-1")

    assert "Node/worker-1" in dependency_graph.graph
    assert "Pod/ns1/app-1" in dependency_graph.graph["Node/worker-1"]


def test_get_descendants_single_level(dependency_graph):
    """Test getting immediate descendants."""
    dependency_graph.add_dependency("Node/worker-1", "Pod/ns1/app-1")
    dependency_graph.add_dependency("Node/worker-1", "Pod/ns1/app-2")

    descendants = dependency_graph.get_descendants("Node/worker-1")

    assert len(descendants) == 2
    assert "Pod/ns1/app-1" in descendants
    assert "Pod/ns1/app-2" in descendants


def test_get_descendants_multi_level(dependency_graph):
    """Test getting descendants across multiple levels."""
    # Build hierarchy: Node → Pod → Service → Route
    dependency_graph.add_dependency("Node/worker-1", "Pod/ns1/app-1")
    dependency_graph.add_dependency("Pod/ns1/app-1", "Service/ns1/app-svc")
    dependency_graph.add_dependency("Service/ns1/app-svc", "Route/ns1/api")

    descendants = dependency_graph.get_descendants("Node/worker-1")

    # Should get all descendants (transitive closure)
    assert len(descendants) == 3
    assert "Pod/ns1/app-1" in descendants
    assert "Service/ns1/app-svc" in descendants
    assert "Route/ns1/api" in descendants


def test_get_descendants_no_children(dependency_graph):
    """Test getting descendants when resource has no children."""
    descendants = dependency_graph.get_descendants("Route/ns1/api")

    assert len(descendants) == 0


def test_is_descendant_of_true(dependency_graph):
    """Test checking if resource is descendant of another."""
    dependency_graph.add_dependency("Node/worker-1", "Pod/ns1/app-1")
    dependency_graph.add_dependency("Pod/ns1/app-1", "Service/ns1/app-svc")

    assert dependency_graph.is_descendant_of("Service/ns1/app-svc", "Node/worker-1") is True
    assert dependency_graph.is_descendant_of("Pod/ns1/app-1", "Node/worker-1") is True


def test_is_descendant_of_false(dependency_graph):
    """Test checking if resource is NOT descendant of another."""
    dependency_graph.add_dependency("Node/worker-1", "Pod/ns1/app-1")
    dependency_graph.add_dependency("Node/worker-2", "Pod/ns2/db-1")

    # Different branches
    assert dependency_graph.is_descendant_of("Pod/ns2/db-1", "Node/worker-1") is False


# AlertCorrelator Tests

@pytest.mark.asyncio
async def test_correlate_observations_empty_list(alert_correlator):
    """Test correlation with empty observations list."""
    groups = await alert_correlator.correlate_observations([])

    assert len(groups) == 0


@pytest.mark.asyncio
async def test_correlate_observations_single_observation(alert_correlator):
    """Test correlation with single observation."""
    obs = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",
        message="Pod failed"
    )

    groups = await alert_correlator.correlate_observations([obs])

    # Single observation, no correlation needed
    assert len(groups) == 0


@pytest.mark.asyncio
async def test_alert_storm_detection(alert_correlator):
    """Test alert storm detection (>10 alerts in 5 minutes)."""
    base_time = datetime.utcnow()

    # Create 15 observations within 3 minutes
    observations = []
    for i in range(15):
        obs = Observation(
            type=ObservationType.POD_FAILURE,
            severity=Severity.ERROR,
            namespace="production",
            resource_kind="Pod",
            resource_name=f"app-{i}",
            message=f"Pod {i} failed",
            timestamp=base_time + timedelta(seconds=i * 10)  # Spread over 150 seconds
        )
        observations.append(obs)

    groups = await alert_correlator.correlate_observations(observations)

    # Should detect alert storm
    assert len(groups) == 1
    assert groups[0].correlation_reason.startswith("Alert storm:")
    assert groups[0].root_cause is not None
    assert len(groups[0].symptoms) == 14  # All except root cause


@pytest.mark.asyncio
async def test_dependency_based_correlation_node_failure(alert_correlator):
    """Test dependency-based correlation for node failure."""
    base_time = datetime.utcnow()

    # Node fails
    node_obs = Observation(
        type=ObservationType.NODE_UNHEALTHY,
        severity=Severity.CRITICAL,
        namespace=None,
        resource_kind="Node",
        resource_name="worker-3",
        message="Node DiskPressure",
        timestamp=base_time
    )

    # Pods on that node evicted
    pod_obs1 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="db-primary",
        message="Pod evicted",
        labels={"node": "worker-3"},
        timestamp=base_time + timedelta(seconds=10)
    )

    pod_obs2 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="db-replica-1",
        message="Pod evicted",
        labels={"node": "worker-3"},
        timestamp=base_time + timedelta(seconds=15)
    )

    # Service loses endpoints
    svc_obs = Observation(
        type=ObservationType.SERVICE_NO_ENDPOINTS,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Service",
        resource_name="database",
        message="No endpoints available",
        timestamp=base_time + timedelta(seconds=20)
    )

    observations = [node_obs, pod_obs1, pod_obs2, svc_obs]
    groups = await alert_correlator.correlate_observations(observations)

    # Should correlate into single group with node as root cause
    assert len(groups) >= 1

    # Find the group with node observation
    node_group = None
    for group in groups:
        if group.root_cause.resource_kind == "Node":
            node_group = group
            break

    if node_group:
        assert node_group.root_cause.resource_name == "worker-3"
        assert len(node_group.symptoms) > 0
        assert "dependency" in node_group.correlation_reason.lower()


@pytest.mark.asyncio
async def test_time_based_correlation(alert_correlator):
    """Test time-based correlation (alerts within 5-minute window)."""
    base_time = datetime.utcnow()

    # Create 3 similar observations within 2 minutes
    obs1 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",
        message="CrashLoopBackOff",
        timestamp=base_time
    )

    obs2 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-2",
        message="CrashLoopBackOff",
        timestamp=base_time + timedelta(seconds=60)
    )

    obs3 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-3",
        message="CrashLoopBackOff",
        timestamp=base_time + timedelta(seconds=120)
    )

    # Create one observation outside the window (7 minutes later)
    obs4 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-4",
        message="CrashLoopBackOff",
        timestamp=base_time + timedelta(minutes=7)
    )

    observations = [obs1, obs2, obs3, obs4]
    groups = await alert_correlator.correlate_observations(observations)

    # Should have at least one group (possibly two if obs4 is separate)
    assert len(groups) >= 1


@pytest.mark.asyncio
async def test_deduplication_by_fingerprint(alert_correlator):
    """Test that duplicate observations are deduplicated."""
    base_time = datetime.utcnow()

    # Same observation twice (same resource, same type)
    obs1 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",
        message="CrashLoopBackOff",
        timestamp=base_time
    )

    obs2 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",  # Same pod
        message="CrashLoopBackOff",
        timestamp=base_time + timedelta(seconds=30)
    )

    observations = [obs1, obs2]
    groups = await alert_correlator.correlate_observations(observations)

    # Should deduplicate and not create a group (only 1 unique observation)
    assert len(groups) == 0


@pytest.mark.asyncio
async def test_build_dependency_graph_from_observations(alert_correlator):
    """Test building dependency graph from observations."""
    # Node observation
    node_obs = Observation(
        type=ObservationType.NODE_UNHEALTHY,
        severity=Severity.CRITICAL,
        namespace=None,
        resource_kind="Node",
        resource_name="worker-1",
        message="DiskPressure"
    )

    # Pod observation with node label
    pod_obs = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="ns1",
        resource_kind="Pod",
        resource_name="app-1",
        message="Evicted",
        labels={"node": "worker-1"}
    )

    # Service observation
    svc_obs = Observation(
        type=ObservationType.SERVICE_NO_ENDPOINTS,
        severity=Severity.ERROR,
        namespace="ns1",
        resource_kind="Service",
        resource_name="app-svc",
        message="No endpoints"
    )

    observations = [node_obs, pod_obs, svc_obs]

    # Build graph
    graph = alert_correlator._build_dependency_graph(observations)

    # Verify dependencies
    assert "Node/worker-1" in graph.graph
    assert "Pod/ns1/app-1" in graph.graph["Node/worker-1"]


@pytest.mark.asyncio
async def test_generate_fingerprint(alert_correlator):
    """Test fingerprint generation for deduplication."""
    obs1 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",
        message="Test"
    )

    obs2 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",  # Same
        message="Different message"  # Message doesn't matter
    )

    fp1 = alert_correlator._generate_fingerprint(obs1)
    fp2 = alert_correlator._generate_fingerprint(obs2)

    # Same resource + type = same fingerprint
    assert fp1 == fp2


@pytest.mark.asyncio
async def test_generate_fingerprint_different(alert_correlator):
    """Test that different resources generate different fingerprints."""
    obs1 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",
        message="Test"
    )

    obs2 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-2",  # Different pod
        message="Test"
    )

    fp1 = alert_correlator._generate_fingerprint(obs1)
    fp2 = alert_correlator._generate_fingerprint(obs2)

    # Different resources = different fingerprints
    assert fp1 != fp2


def test_correlated_observation_group_dataclass():
    """Test CorrelatedObservationGroup dataclass."""
    root = Observation(
        type=ObservationType.NODE_UNHEALTHY,
        severity=Severity.CRITICAL,
        namespace=None,
        resource_kind="Node",
        resource_name="worker-1",
        message="DiskPressure"
    )

    symptom = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="ns1",
        resource_kind="Pod",
        resource_name="app-1",
        message="Evicted"
    )

    group = CorrelatedObservationGroup(
        root_cause=root,
        symptoms=[symptom],
        correlation_reason="Node failure causing pod eviction"
    )

    assert group.root_cause.resource_name == "worker-1"
    assert len(group.symptoms) == 1
    assert group.symptoms[0].resource_name == "app-1"
    assert "Node failure" in group.correlation_reason
