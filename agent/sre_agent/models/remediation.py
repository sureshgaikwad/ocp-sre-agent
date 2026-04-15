"""
Remediation data model.

RemediationResults are the output of handlers - what was done to fix the issue.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class RemediationStatus(str, Enum):
    """Status of remediation attempt."""
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"  # RBAC denied, cooldown, etc.
    PENDING = "pending"  # PR created, awaiting approval
    SKIPPED = "skipped"  # Human-in-the-loop required


class RemediationAction(BaseModel):
    """A single action taken during remediation."""
    action_type: str  # "kubectl_patch", "create_pr", "create_issue", "retry_wait"
    description: str  # Human-readable
    command: Optional[str] = None  # Actual command executed
    result: Optional[str] = None  # Output or error
    success: bool = True


class RemediationResult(BaseModel):
    """
    Result of a remediation attempt.

    RemediationResults are created by handlers and logged for audit.
    """

    # Unique identifier
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Link to diagnosis
    diagnosis_id: str

    # What was done
    tier: int = Field(ge=1, le=3)  # 1=auto, 2=PR, 3=notify
    status: RemediationStatus
    actions: list[RemediationAction] = Field(default_factory=list)

    # Results
    message: str  # Summary of what happened
    pr_url: Optional[str] = None  # For Tier 2
    issue_url: Optional[str] = None  # For Tier 3 or fallback
    error: Optional[str] = None  # If failed

    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    handler_name: str  # Which handler executed this
    execution_time_seconds: float = 0.0

    # Verification
    verified: bool = False  # Did we verify the fix worked?
    verification_result: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "id": "rem-123e4567-e89b-12d3-a456-426614174000",
                "diagnosis_id": "diag-123e4567-e89b-12d3-a456-426614174000",
                "tier": 2,
                "status": "pending",
                "actions": [
                    {
                        "action_type": "create_pr",
                        "description": "Created PR to increase memory limit from 256Mi to 512Mi",
                        "command": None,
                        "result": "PR #42 created",
                        "success": True
                    }
                ],
                "message": "Created GitOps PR to increase memory limit",
                "pr_url": "https://gitea.example.com/user1/mcp/pull/42",
                "issue_url": None,
                "error": None,
                "handler_name": "tier2_gitops",
                "execution_time_seconds": 2.5,
                "verified": False
            }
        }

    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"[Tier {self.tier}] {self.status.value}: {self.message}"

    def to_summary(self) -> str:
        """Short summary for logging."""
        return f"tier{self.tier}:{self.status.value}:{len(self.actions)} actions"

    def add_action(
        self,
        action_type: str,
        description: str,
        command: Optional[str] = None,
        result: Optional[str] = None,
        success: bool = True
    ) -> None:
        """Helper to add an action to the remediation result."""
        self.actions.append(
            RemediationAction(
                action_type=action_type,
                description=description,
                command=command,
                result=result,
                success=success
            )
        )
