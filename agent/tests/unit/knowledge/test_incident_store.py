"""
Unit tests for IncidentKnowledgeStore.

Tests incident storage, retrieval, and similarity matching.
"""

import pytest
import tempfile
import os
from datetime import datetime
from unittest.mock import AsyncMock

from sre_agent.knowledge.incident_store import (
    IncidentKnowledgeStore,
    IncidentRecord,
    get_knowledge_store
)
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.models.remediation import RemediationResult, RemediationStatus


@pytest.fixture
def temp_db_path():
    """Create temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
async def knowledge_store(temp_db_path):
    """Create IncidentKnowledgeStore instance."""
    store = IncidentKnowledgeStore(temp_db_path)
    await store.initialize()
    yield store
    # Close connection
    if store._conn:
        await store._conn.close()


@pytest.fixture
def sample_observation():
    """Create sample observation."""
    return Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="api-server-1",
        message="Pod failing: ImagePullBackOff",
        raw_data={"reason": "ImagePullBackOff", "exitCode": None}
    )


@pytest.fixture
def sample_diagnosis():
    """Create sample diagnosis."""
    return Diagnosis(
        category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
        root_cause="Registry temporarily unavailable (HTTP 503)",
        confidence=Confidence.HIGH,
        recommended_tier=1,
        recommended_actions=[
            "Wait 1 minute and retry image pull",
            "If persists after 3 retries, escalate"
        ],
        observation_id="obs-123",
        evidence={"status_code": 503}
    )


@pytest.fixture
def sample_remediation():
    """Create sample remediation result."""
    return RemediationResult(
        status=RemediationStatus.SUCCESS,
        tier=1,
        message="Image pull successful after retry",
        diagnosis_id="diag-456",
        actions_taken=["Waited 60 seconds", "Retried image pull"],
        duration_seconds=65
    )


@pytest.mark.asyncio
async def test_initialize_creates_table(temp_db_path):
    """Test that initialize creates incidents table."""
    store = IncidentKnowledgeStore(temp_db_path)
    await store.initialize()

    # Verify table exists by trying to query it
    async with store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='incidents'") as cursor:
        result = await cursor.fetchone()
        assert result is not None
        assert result[0] == "incidents"

    await store._conn.close()


@pytest.mark.asyncio
async def test_store_incident(knowledge_store, sample_observation, sample_diagnosis, sample_remediation):
    """Test storing an incident."""
    incident_id = await knowledge_store.store_incident(
        sample_observation,
        sample_diagnosis,
        sample_remediation
    )

    assert incident_id is not None
    assert incident_id.startswith("incident-")


@pytest.mark.asyncio
async def test_find_similar_incidents_exact_match(knowledge_store, sample_observation, sample_diagnosis, sample_remediation):
    """Test finding similar incidents with exact fingerprint match."""
    # Store first incident
    await knowledge_store.store_incident(
        sample_observation,
        sample_diagnosis,
        sample_remediation
    )

    # Create similar observation (same type + kind + category)
    similar_obs = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="staging",  # Different namespace
        resource_kind="Pod",
        resource_name="api-server-2",  # Different pod
        message="Pod failing: ImagePullBackOff",
        raw_data={"reason": "ImagePullBackOff"}
    )

    # Find similar incidents
    similar_incidents = await knowledge_store.find_similar_incidents(
        similar_obs,
        diagnosis=sample_diagnosis,  # Same diagnosis category
        limit=5
    )

    assert len(similar_incidents) == 1
    assert similar_incidents[0].observation.type == sample_observation.type
    assert similar_incidents[0].diagnosis.category == sample_diagnosis.category


@pytest.mark.asyncio
async def test_find_similar_incidents_no_match(knowledge_store, sample_observation, sample_diagnosis, sample_remediation):
    """Test that different incident types don't match."""
    # Store incident
    await knowledge_store.store_incident(
        sample_observation,
        sample_diagnosis,
        sample_remediation
    )

    # Create completely different observation
    different_obs = Observation(
        type=ObservationType.CLUSTER_OPERATOR_DEGRADED,
        severity=Severity.ERROR,
        namespace=None,
        resource_kind="ClusterOperator",
        resource_name="authentication",
        message="Operator degraded"
    )

    # Find similar incidents
    similar_incidents = await knowledge_store.find_similar_incidents(
        different_obs,
        limit=5
    )

    # Should not find any matches (different type and kind)
    assert len(similar_incidents) == 0


@pytest.mark.asyncio
async def test_find_similar_incidents_partial_match(knowledge_store):
    """Test finding incidents with same type but different category."""
    # Store first incident - ImagePullBackOff transient
    obs1 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",
        message="ImagePullBackOff"
    )
    diag1 = Diagnosis(
        category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
        root_cause="Transient registry error",
        confidence=Confidence.HIGH,
        recommended_tier=1,
        recommended_actions=["Retry"],
        observation_id=obs1.id
    )
    rem1 = RemediationResult(
        status=RemediationStatus.SUCCESS,
        tier=1,
        message="Retry successful",
        diagnosis_id=diag1.id,
        actions_taken=["Waited", "Retried"]
    )
    await knowledge_store.store_incident(obs1, diag1, rem1)

    # Search for similar pod failure (same type+kind, no diagnosis)
    obs2 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="staging",
        resource_kind="Pod",
        resource_name="app-2",
        message="Different issue"
    )

    similar_incidents = await knowledge_store.find_similar_incidents(obs2, limit=5)

    # Should find partial match (same type + kind)
    assert len(similar_incidents) >= 1


@pytest.mark.asyncio
async def test_get_mttr_statistics_single_category(knowledge_store, sample_observation, sample_remediation):
    """Test MTTR statistics for single category."""
    # Store multiple incidents with varying durations
    for i, duration in enumerate([60, 120, 180]):
        obs = Observation(
            type=ObservationType.POD_FAILURE,
            severity=Severity.ERROR,
            namespace="production",
            resource_kind="Pod",
            resource_name=f"pod-{i}",
            message="ImagePullBackOff"
        )
        diag = Diagnosis(
            category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
            root_cause="Transient error",
            confidence=Confidence.HIGH,
            recommended_tier=1,
            recommended_actions=["Retry"],
            observation_id=obs.id
        )
        rem = RemediationResult(
            status=RemediationStatus.SUCCESS,
            tier=1,
            message="Success",
            diagnosis_id=diag.id,
            actions_taken=["Retry"],
            duration_seconds=duration
        )
        await knowledge_store.store_incident(obs, diag, rem)

    # Get MTTR statistics
    stats = await knowledge_store.get_mttr_statistics(
        DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT
    )

    assert stats is not None
    assert stats["incident_count"] == 3
    assert stats["mean_mttr_seconds"] == 120.0  # (60 + 120 + 180) / 3
    assert stats["min_mttr_seconds"] == 60.0
    assert stats["max_mttr_seconds"] == 180.0


@pytest.mark.asyncio
async def test_get_mttr_statistics_no_incidents(knowledge_store):
    """Test MTTR statistics when no incidents exist."""
    stats = await knowledge_store.get_mttr_statistics(
        DiagnosisCategory.IMAGE_PULL_BACKOFF_AUTH
    )

    assert stats is None


@pytest.mark.asyncio
async def test_fingerprint_generation(knowledge_store, sample_observation, sample_diagnosis):
    """Test fingerprint generation for similarity matching."""
    fingerprint = knowledge_store._generate_fingerprint(
        sample_observation,
        sample_diagnosis
    )

    # Should be 16-char hex string
    assert len(fingerprint) == 16
    assert all(c in "0123456789abcdef" for c in fingerprint)

    # Same inputs should generate same fingerprint
    fingerprint2 = knowledge_store._generate_fingerprint(
        sample_observation,
        sample_diagnosis
    )
    assert fingerprint == fingerprint2


@pytest.mark.asyncio
async def test_fingerprint_different_for_different_inputs(knowledge_store):
    """Test that different observations generate different fingerprints."""
    obs1 = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="production",
        resource_kind="Pod",
        resource_name="app-1",
        message="Test"
    )

    obs2 = Observation(
        type=ObservationType.NODE_UNHEALTHY,
        severity=Severity.ERROR,
        namespace=None,
        resource_kind="Node",
        resource_name="worker-1",
        message="Test"
    )

    diag = Diagnosis(
        category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
        root_cause="Test",
        confidence=Confidence.HIGH,
        recommended_tier=1,
        recommended_actions=[],
        observation_id="test"
    )

    fp1 = knowledge_store._generate_fingerprint(obs1, diag)
    fp2 = knowledge_store._generate_fingerprint(obs2, diag)

    # Different observation types should generate different fingerprints
    assert fp1 != fp2


@pytest.mark.asyncio
async def test_get_knowledge_store_singleton():
    """Test that get_knowledge_store returns singleton."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store1 = get_knowledge_store(db_path)
        store2 = get_knowledge_store(db_path)

        # Should return same instance
        assert store1 is store2

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.mark.asyncio
async def test_incident_record_dataclass():
    """Test IncidentRecord dataclass."""
    obs = Observation(
        type=ObservationType.POD_FAILURE,
        severity=Severity.ERROR,
        namespace="test",
        resource_kind="Pod",
        resource_name="test-pod",
        message="Test"
    )

    diag = Diagnosis(
        category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
        root_cause="Test",
        confidence=Confidence.HIGH,
        recommended_tier=1,
        recommended_actions=[],
        observation_id=obs.id
    )

    rem = RemediationResult(
        status=RemediationStatus.SUCCESS,
        tier=1,
        message="Test",
        diagnosis_id=diag.id,
        actions_taken=[],
        duration_seconds=60
    )

    record = IncidentRecord(
        incident_id="test-incident-123",
        timestamp=datetime.utcnow(),
        observation=obs,
        diagnosis=diag,
        remediation=rem,
        fingerprint="abcdef1234567890",
        mttr_seconds=60,
        outcome="success"
    )

    assert record.incident_id == "test-incident-123"
    assert record.mttr_seconds == 60
    assert record.outcome == "success"
    assert record.observation.resource_name == "test-pod"
