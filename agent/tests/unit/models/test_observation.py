"""Unit tests for Observation model."""

import pytest
from datetime import datetime
from sre_agent.models.observation import Observation, ObservationType, Severity


class TestObservationModel:
    """Test Observation data model."""

    def test_create_observation_minimal(self):
        """Test creating observation with minimal fields."""
        obs = Observation(
            type=ObservationType.POD_FAILURE,
            severity=Severity.CRITICAL,
            message="Pod is failing"
        )
        assert obs.type == ObservationType.POD_FAILURE
        assert obs.severity == Severity.CRITICAL
        assert obs.message == "Pod is failing"
        assert obs.id is not None  # UUID generated
        assert isinstance(obs.timestamp, datetime)

    def test_create_observation_full(self):
        """Test creating observation with all fields."""
        obs = Observation(
            type=ObservationType.POD_FAILURE,
            severity=Severity.CRITICAL,
            namespace="openshift-pipelines",
            resource_kind="Pod",
            resource_name="build-pod-123",
            message="Pod is in CrashLoopBackOff",
            raw_data={"status": "CrashLoopBackOff", "restartCount": 5},
            cluster_name="prod-cluster",
            labels={"app": "pipeline"}
        )
        assert obs.namespace == "openshift-pipelines"
        assert obs.resource_kind == "Pod"
        assert obs.resource_name == "build-pod-123"
        assert obs.raw_data["restartCount"] == 5
        assert obs.labels["app"] == "pipeline"

    def test_observation_str(self):
        """Test string representation."""
        obs = Observation(
            type=ObservationType.POD_FAILURE,
            severity=Severity.WARNING,
            namespace="default",
            resource_name="my-pod",
            message="Pod restarting frequently"
        )
        str_repr = str(obs)
        assert "WARNING" in str_repr
        assert "pod_failure" in str_repr
        assert "default/my-pod" in str_repr

    def test_observation_to_summary(self):
        """Test summary generation."""
        obs = Observation(
            type=ObservationType.EVENT_WARNING,
            severity=Severity.INFO,
            namespace="kube-system",
            resource_name="event-123",
            message="Some event"
        )
        summary = obs.to_summary()
        assert "event_warning" in summary
        assert "kube-system" in summary
        assert "event-123" in summary

    def test_observation_serialization(self):
        """Test Pydantic serialization."""
        obs = Observation(
            type=ObservationType.CLUSTER_OPERATOR_DEGRADED,
            severity=Severity.CRITICAL,
            resource_name="authentication",
            message="Cluster operator degraded"
        )
        # Test model_dump
        data = obs.model_dump()
        assert data["type"] == "cluster_operator_degraded"
        assert data["severity"] == "critical"

        # Test JSON serialization
        json_str = obs.model_dump_json()
        assert "cluster_operator_degraded" in json_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
