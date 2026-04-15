"""Unit tests for RemediationResult model."""

import pytest
from sre_agent.models.remediation import RemediationResult, RemediationStatus, RemediationAction


class TestRemediationModel:
    """Test RemediationResult data model."""

    def test_create_remediation_minimal(self):
        """Test creating remediation with minimal fields."""
        rem = RemediationResult(
            diagnosis_id="diag-123",
            tier=2,
            status=RemediationStatus.SUCCESS,
            message="PR created successfully",
            handler_name="tier2_gitops"
        )
        assert rem.diagnosis_id == "diag-123"
        assert rem.tier == 2
        assert rem.status == RemediationStatus.SUCCESS
        assert rem.id is not None

    def test_create_remediation_with_actions(self):
        """Test creating remediation with actions."""
        action1 = RemediationAction(
            action_type="create_pr",
            description="Created PR to increase memory",
            result="PR #42 created",
            success=True
        )
        action2 = RemediationAction(
            action_type="update_yaml",
            description="Updated deployment.yaml",
            command="yq eval '.spec.template.spec.containers[0].resources.limits.memory = \"512Mi\"' deployment.yaml",
            success=True
        )

        rem = RemediationResult(
            diagnosis_id="diag-456",
            tier=2,
            status=RemediationStatus.PENDING,
            message="PR awaiting review",
            actions=[action1, action2],
            pr_url="https://gitea.example.com/user/repo/pull/42",
            handler_name="tier2_gitops"
        )
        assert len(rem.actions) == 2
        assert rem.actions[0].action_type == "create_pr"
        assert rem.pr_url is not None

    def test_add_action_helper(self):
        """Test add_action helper method."""
        rem = RemediationResult(
            diagnosis_id="diag-789",
            tier=1,
            status=RemediationStatus.SUCCESS,
            message="Automated fix applied",
            handler_name="tier1_automated"
        )

        rem.add_action(
            action_type="retry_wait",
            description="Waited 60 seconds for registry",
            success=True
        )
        rem.add_action(
            action_type="verify_pod",
            description="Verified pod is running",
            command="oc get pod my-pod -n default",
            result="Running",
            success=True
        )

        assert len(rem.actions) == 2
        assert rem.actions[0].action_type == "retry_wait"
        assert rem.actions[1].command == "oc get pod my-pod -n default"

    def test_remediation_str(self):
        """Test string representation."""
        rem = RemediationResult(
            diagnosis_id="diag-123",
            tier=3,
            status=RemediationStatus.SUCCESS,
            message="Issue created for manual review",
            handler_name="tier3_notification"
        )
        str_repr = str(rem)
        assert "Tier 3" in str_repr
        assert "success" in str_repr

    def test_remediation_to_summary(self):
        """Test summary generation."""
        rem = RemediationResult(
            diagnosis_id="diag-123",
            tier=1,
            status=RemediationStatus.FAILED,
            message="Automated fix failed",
            handler_name="tier1_automated"
        )
        rem.add_action("patch_pod", "Attempted to patch pod", success=False)

        summary = rem.to_summary()
        assert "tier1" in summary
        assert "failed" in summary
        assert "1 actions" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
