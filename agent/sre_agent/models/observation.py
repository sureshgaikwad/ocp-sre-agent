"""
Observation data model.

Observations are the output of collectors - structured data about cluster state.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ObservationType(str, Enum):
    """Types of observations the agent can make."""
    POD_FAILURE = "pod_failure"
    EVENT_WARNING = "event_warning"
    CLUSTER_OPERATOR_DEGRADED = "cluster_operator_degraded"
    MACHINE_CONFIG_POOL_DEGRADED = "machine_config_pool_degraded"
    ROUTE_ERROR = "route_error"
    NODE_ISSUE = "node_issue"
    PIPELINE_FAILURE = "pipeline_failure"
    RESOURCE_QUOTA_EXCEEDED = "resource_quota_exceeded"
    # Build-related observations
    BUILD_FAILURE = "build_failure"
    TASK_RUN_FAILURE = "task_run_failure"
    # Networking-related observations
    NETWORK_POLICY_VIOLATION = "network_policy_violation"
    DNS_FAILURE = "dns_failure"
    SDN_DEGRADED = "sdn_degraded"
    SERVICE_NO_ENDPOINTS = "service_no_endpoints"
    # Autoscaling-related observations
    HPA_DEGRADED = "hpa_degraded"
    HPA_UNABLE_TO_SCALE = "hpa_unable_to_scale"
    CLUSTER_AUTOSCALER_DEGRADED = "cluster_autoscaler_degraded"
    NODE_SCALE_FAILURE = "node_scale_failure"
    # Proactive observations (trends and anomalies)
    TREND_MEMORY_INCREASING = "trend_memory_increasing"
    TREND_CPU_INCREASING = "trend_cpu_increasing"
    TREND_ERROR_RATE_RISING = "trend_error_rate_rising"
    TREND_RESTART_COUNT_RISING = "trend_restart_count_rising"
    ANOMALY_CPU_SPIKE = "anomaly_cpu_spike"
    ANOMALY_MEMORY_SPIKE = "anomaly_memory_spike"
    ANOMALY_DISK_GROWTH = "anomaly_disk_growth"
    ANOMALY_NETWORK_LATENCY = "anomaly_network_latency"
    # Alert correlation
    ALERT_STORM = "alert_storm"


class Severity(str, Enum):
    """Severity levels for observations."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Observation(BaseModel):
    """
    An observation about cluster state.

    Observations are created by collectors and consumed by analyzers.
    """

    # Unique identifier
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # What was observed
    type: ObservationType
    severity: Severity

    # When it was observed
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Resource information
    namespace: Optional[str] = None
    resource_kind: Optional[str] = None  # Pod, Event, ClusterOperator, etc.
    resource_name: Optional[str] = None

    # Details
    message: str  # Human-readable description
    raw_data: dict = Field(default_factory=dict)  # Original data from oc command

    # Metadata
    cluster_name: Optional[str] = None
    labels: dict[str, str] = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "id": "obs-123e4567-e89b-12d3-a456-426614174000",
                "type": "pod_failure",
                "severity": "critical",
                "timestamp": "2026-04-14T10:30:00Z",
                "namespace": "openshift-pipelines",
                "resource_kind": "Pod",
                "resource_name": "build-pipeline-run-abc-pod",
                "message": "Pod is in CrashLoopBackOff state",
                "raw_data": {
                    "status": "CrashLoopBackOff",
                    "restartCount": 5
                },
                "labels": {
                    "app": "pipeline",
                    "pipeline-run": "build-pipeline-run-abc"
                }
            }
        }

    def __str__(self) -> str:
        """Human-readable string representation."""
        resource = f"{self.namespace}/{self.resource_name}" if self.namespace else self.resource_name
        return f"[{self.severity.value.upper()}] {self.type.value}: {resource} - {self.message}"

    def to_summary(self) -> str:
        """Short summary for logging."""
        return f"{self.type.value}:{self.namespace}/{self.resource_name}"
