"""
Audit entry data model.

Audit entries log all operations for security and compliance.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class OperationType(str, Enum):
    """Types of operations that are audited."""
    READ = "read"  # oc get, oc describe
    WRITE = "write"  # oc patch, oc delete, oc create
    ANALYZE = "analyze"  # LLM analysis
    REMEDIATE = "remediate"  # Remediation action
    CREATE_ISSUE = "create_issue"  # External issue creation
    CREATE_PR = "create_pr"  # External PR creation


class AuditEntry(BaseModel):
    """
    An audit log entry for compliance and security.

    All operations (read/write) are logged with full context.
    """

    # Unique identifier
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # When and who
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    operation_type: OperationType

    # What was done
    resource_kind: Optional[str] = None  # Pod, ClusterOperator, etc.
    resource_name: Optional[str] = None
    namespace: Optional[str] = None
    action: str  # "get", "patch", "delete", "analyze", etc.

    # How it went
    success: bool
    error: Optional[str] = None

    # Context
    diagnosis_id: Optional[str] = None  # Link to diagnosis if applicable
    remediation_id: Optional[str] = None  # Link to remediation if applicable
    observation_id: Optional[str] = None  # Link to observation if applicable

    # Details (MUST be scrubbed before storage)
    command: Optional[str] = None  # Command executed
    result_summary: Optional[str] = None  # Brief result (not full output)

    # RBAC
    service_account: Optional[str] = None  # Which SA was used
    rbac_check_passed: bool = True  # Did RBAC check pass before action

    class Config:
        json_schema_extra = {
            "example": {
                "id": "audit-123e4567-e89b-12d3-a456-426614174000",
                "timestamp": "2026-04-14T10:35:00Z",
                "operation_type": "write",
                "resource_kind": "Pod",
                "resource_name": "build-pipeline-run-abc-pod",
                "namespace": "openshift-pipelines",
                "action": "delete",
                "success": True,
                "error": None,
                "diagnosis_id": "diag-123e4567-e89b-12d3-a456-426614174000",
                "remediation_id": "rem-123e4567-e89b-12d3-a456-426614174000",
                "command": "oc delete pod build-pipeline-run-abc-pod -n openshift-pipelines",
                "result_summary": "Pod deleted successfully",
                "service_account": "sre-agent",
                "rbac_check_passed": True
            }
        }

    def __str__(self) -> str:
        """Human-readable string representation."""
        resource = f"{self.namespace}/{self.resource_name}" if self.namespace else self.resource_name
        status = "SUCCESS" if self.success else "FAILED"
        return f"[{status}] {self.operation_type.value}:{self.action} {resource}"

    def to_summary(self) -> str:
        """Short summary for logging."""
        status = "OK" if self.success else "FAIL"
        return f"{self.operation_type.value}:{self.action}:{status}"
