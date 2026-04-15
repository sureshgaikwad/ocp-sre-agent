"""Unit tests for Diagnosis model."""

import pytest
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence


class TestDiagnosisModel:
    """Test Diagnosis data model."""

    def test_create_diagnosis_minimal(self):
        """Test creating diagnosis with minimal fields."""
        diag = Diagnosis(
            observation_id="obs-123",
            category=DiagnosisCategory.OOM_KILLED,
            root_cause="Container exceeded memory limit",
            confidence=Confidence.HIGH,
            recommended_tier=2,
            analyzer_name="oom_analyzer"
        )
        assert diag.observation_id == "obs-123"
        assert diag.category == DiagnosisCategory.OOM_KILLED
        assert diag.confidence == Confidence.HIGH
        assert diag.recommended_tier == 2
        assert diag.id is not None

    def test_create_diagnosis_full(self):
        """Test creating diagnosis with all fields."""
        diag = Diagnosis(
            observation_id="obs-456",
            category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
            root_cause="Registry timeout, likely temporary",
            confidence=Confidence.MEDIUM,
            recommended_actions=["Wait 1 minute and retry", "Check registry status"],
            recommended_tier=1,
            evidence={"http_status": 503, "error": "Service Unavailable"},
            error_patterns=["503", "timeout"],
            analyzer_name="image_pull_analyzer"
        )
        assert len(diag.recommended_actions) == 2
        assert diag.evidence["http_status"] == 503
        assert "503" in diag.error_patterns

    def test_diagnosis_tier_validation(self):
        """Test tier must be 1-3."""
        with pytest.raises(Exception):  # Pydantic validation error
            Diagnosis(
                observation_id="obs-789",
                category=DiagnosisCategory.UNKNOWN,
                root_cause="Unknown issue",
                confidence=Confidence.LOW,
                recommended_tier=4,  # Invalid tier
                analyzer_name="test"
            )

    def test_diagnosis_str(self):
        """Test string representation."""
        diag = Diagnosis(
            observation_id="obs-123",
            category=DiagnosisCategory.SCC_PERMISSION_DENIED,
            root_cause="Pod requires privileged SCC",
            confidence=Confidence.HIGH,
            recommended_tier=2,
            analyzer_name="scc_analyzer"
        )
        str_repr = str(diag)
        assert "HIGH" in str_repr
        assert "scc_permission_denied" in str_repr
        assert "Tier 2" in str_repr

    def test_diagnosis_to_summary(self):
        """Test summary generation."""
        diag = Diagnosis(
            observation_id="obs-123",
            category=DiagnosisCategory.LIVENESS_PROBE_FAILURE,
            root_cause="Liveness probe timing out",
            confidence=Confidence.MEDIUM,
            recommended_tier=2,
            analyzer_name="liveness_analyzer"
        )
        summary = diag.to_summary()
        assert "liveness_probe_failure" in summary
        assert "tier2" in summary
        assert "medium" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
