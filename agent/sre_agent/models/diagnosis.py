"""
Diagnosis data model.

Diagnoses are the output of analyzers - identified root causes and recommendations.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class DiagnosisCategory(str, Enum):
    """
    Categories of diagnosed issues.

    These categories determine which remediation tier is used.
    """
    # Tier 1: Automated remediation
    IMAGE_PULL_BACKOFF_TRANSIENT = "image_pull_backoff_transient"  # Retry-wait
    REGISTRY_TIMEOUT = "registry_timeout"  # Temporary registry issue
    ROUTE_BACKEND_TEMPORARILY_UNAVAILABLE = "route_backend_temporarily_unavailable"  # Service recovering

    # Tier 2: GitOps PR
    OOM_KILLED = "oom_killed"  # Increase memory limit
    LIVENESS_PROBE_FAILURE = "liveness_probe_failure"  # Adjust probe settings
    RESOURCE_QUOTA_EXCEEDED = "resource_quota_exceeded"  # Increase quota
    SCC_PERMISSION_DENIED = "scc_permission_denied"  # Add SCC binding
    ROUTE_SERVICE_NO_ENDPOINTS = "route_service_no_endpoints"  # Scale deployment
    BUILD_RESOURCE_LIMIT = "build_resource_limit"  # Increase build resources
    BUILD_TIMEOUT = "build_timeout"  # Increase timeout
    PROACTIVE_MEMORY_INCREASE = "proactive_memory_increase"  # Prevent OOM
    PROACTIVE_CPU_INCREASE = "proactive_cpu_increase"  # Prevent throttling
    PROACTIVE_SCALE_UP = "proactive_scale_up"  # Prevent overload
    POD_OVERPROVISIONED = "pod_overprovisioned"  # Cost optimization
    STORAGE_ORPHANED = "storage_orphaned"  # Cost optimization

    # Tier 3: Notification only
    IMAGE_PULL_BACKOFF_AUTH = "image_pull_backoff_auth"  # Auth issue, needs manual fix
    IMAGE_PULL_BACKOFF_NOT_FOUND = "image_pull_backoff_not_found"  # Image doesn't exist
    NODE_DISK_PRESSURE = "node_disk_pressure"  # Node issue, notify ops
    CLUSTER_OPERATOR_DEGRADED = "cluster_operator_degraded"  # Platform issue
    MACHINE_CONFIG_POOL_DEGRADED = "machine_config_pool_degraded"  # MCP degraded, platform issue
    APPLICATION_ERROR = "application_error"  # Application code issue
    ROUTE_TLS_CERT_ERROR = "route_tls_cert_error"  # TLS/SSL issue
    BUILD_TEST_FAILURE = "build_test_failure"  # Test failures in build
    BUILD_COMPILATION_ERROR = "build_compilation_error"  # Code compilation error
    NETWORK_POLICY_BLOCKING = "network_policy_blocking"  # NetworkPolicy denying traffic
    DNS_RESOLUTION_FAILURE = "dns_resolution_failure"  # DNS not resolving
    SDN_POD_FAILURE = "sdn_pod_failure"  # SDN/OVN pods unhealthy
    HPA_UNABLE_TO_GET_METRICS = "hpa_unable_to_get_metrics"  # HPA can't fetch metrics
    HPA_MISSING_SCALEREF = "hpa_missing_scaleref"  # HPA target doesn't exist
    CLUSTER_AUTOSCALER_FAILED = "cluster_autoscaler_failed"  # Node autoscaling failed
    NODE_SCALE_INSUFFICIENT_RESOURCES = "node_scale_insufficient_resources"  # Can't provision nodes

    # Uncategorized
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    """Confidence level in the diagnosis."""
    HIGH = "high"  # Pattern-matched or LLM high confidence
    MEDIUM = "medium"  # LLM medium confidence
    LOW = "low"  # Fallback or uncertain


class Diagnosis(BaseModel):
    """
    A diagnosis of an observed issue.

    Diagnoses are created by analyzers and consumed by handlers.
    """

    # Unique identifier
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Link to observation
    observation_id: str

    # What's the problem
    category: DiagnosisCategory
    root_cause: str  # Human-readable explanation
    confidence: Confidence

    # Recommendations
    recommended_actions: list[str] = Field(default_factory=list)
    recommended_tier: int = Field(ge=1, le=3)  # 1=auto, 2=PR, 3=notify

    # Technical details
    evidence: dict = Field(default_factory=dict)  # Supporting data (logs, metrics)
    exit_code: Optional[int] = None  # For pod failures
    error_patterns: list[str] = Field(default_factory=list)  # Matched patterns

    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    analyzer_name: str  # Which analyzer produced this

    class Config:
        json_schema_extra = {
            "example": {
                "id": "diag-123e4567-e89b-12d3-a456-426614174000",
                "observation_id": "obs-123e4567-e89b-12d3-a456-426614174000",
                "category": "oom_killed",
                "root_cause": "Container exceeded memory limit (256Mi) and was killed by OOM killer",
                "confidence": "high",
                "recommended_actions": [
                    "Increase memory limit to 512Mi",
                    "Add memory request of 384Mi for better scheduling"
                ],
                "recommended_tier": 2,
                "evidence": {
                    "exit_code": 137,
                    "last_state": "OOMKilled",
                    "memory_limit": "256Mi",
                    "restart_count": 5
                },
                "exit_code": 137,
                "error_patterns": ["OOMKilled", "exit code 137"],
                "analyzer_name": "oom_analyzer"
            }
        }

    def __str__(self) -> str:
        """Human-readable string representation."""
        return (
            f"[{self.confidence.value.upper()}] {self.category.value}: {self.root_cause} "
            f"(Tier {self.recommended_tier})"
        )

    def to_summary(self) -> str:
        """Short summary for logging."""
        return f"{self.category.value}:tier{self.recommended_tier}:confidence={self.confidence.value}"
