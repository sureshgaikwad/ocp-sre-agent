"""
Autoscaling analyzer for diagnosing HPA and ClusterAutoscaler issues.

Analyzes autoscaling problems including:
- HPA unable to fetch metrics
- HPA target reference missing
- ClusterAutoscaler node provisioning failures
- Insufficient cluster capacity
"""

import json
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.analyzers.base import BaseAnalyzer
from sre_agent.models.observation import Observation, ObservationType
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class AutoscalingAnalyzer(BaseAnalyzer):
    """
    Analyzer for autoscaling issues.

    Diagnoses autoscaling problems by analyzing:
    1. HPA conditions and metrics availability
    2. HPA scaleTargetRef validity
    3. ClusterAutoscaler status and events
    4. Node scaling capacity constraints
    """

    # Regex patterns for categorizing autoscaling failures
    METRICS_UNAVAILABLE_PATTERNS = [
        r"unable to get metrics",
        r"unable to fetch metrics",
        r"failed to get.*metric",
        r"metrics server.*unavailable",
        r"no metrics returned",
    ]

    SCALEREF_MISSING_PATTERNS = [
        r"scale target.*not found",
        r"deployment.*not found",
        r"statefulset.*not found",
        r"missing scale target",
    ]

    NODE_CAPACITY_PATTERNS = [
        r"insufficient.*capacity",
        r"no available nodes",
        r"cannot provision.*nodes",
        r"resource exhausted",
        r"quota exceeded",
    ]

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize AutoscalingAnalyzer.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "autoscaling_analyzer")

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        Args:
            observation: Observation to check

        Returns:
            True if observation is an autoscaling issue
        """
        return observation.type in [
            ObservationType.HPA_DEGRADED,
            ObservationType.HPA_UNABLE_TO_SCALE,
            ObservationType.CLUSTER_AUTOSCALER_DEGRADED,
            ObservationType.NODE_SCALE_FAILURE
        ]

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze an autoscaling observation.

        Args:
            observation: Autoscaling observation to analyze

        Returns:
            Diagnosis with root cause analysis
        """
        request_id = logger.set_request_id()

        logger.info(
            f"Analyzing autoscaling observation: {observation.resource_name}",
            request_id=request_id,
            observation_id=observation.id,
            resource=observation.resource_name,
            namespace=observation.namespace,
            type=observation.type.value
        )

        try:
            # Route to specific analyzer based on observation type
            if observation.type in [ObservationType.HPA_DEGRADED, ObservationType.HPA_UNABLE_TO_SCALE]:
                return await self._analyze_hpa_issue(observation, request_id)
            elif observation.type in [ObservationType.CLUSTER_AUTOSCALER_DEGRADED, ObservationType.NODE_SCALE_FAILURE]:
                return await self._analyze_cluster_autoscaler_issue(observation, request_id)
            else:
                return None

        except Exception as e:
            logger.error(
                f"Failed to analyze autoscaling observation: {e}",
                request_id=request_id,
                observation_id=observation.id,
                exc_info=True
            )
            return None

    async def _analyze_hpa_issue(
        self,
        observation: Observation,
        request_id: str
    ) -> Diagnosis:
        """
        Analyze HPA issue.

        Args:
            observation: HPA observation
            request_id: Request ID for logging

        Returns:
            Diagnosis for HPA issue
        """
        raw_data = observation.raw_data
        status = raw_data.get("status", {})
        spec = raw_data.get("spec", {})

        # Get condition details
        conditions = status.get("conditions", [])
        message_combined = observation.message.lower()

        for condition in conditions:
            reason = condition.get("reason", "")
            message = condition.get("message", "")
            message_combined += f" {reason} {message}".lower()

        # Check for metrics unavailability
        for pattern in self.METRICS_UNAVAILABLE_PATTERNS:
            if re.search(pattern, message_combined, re.IGNORECASE):
                logger.info(
                    f"HPA issue categorized as metrics unavailable",
                    request_id=request_id,
                    pattern=pattern
                )

                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.HPA_UNABLE_TO_GET_METRICS,
                    root_cause=f"HPA unable to fetch metrics: {observation.message}",
                    confidence=Confidence.HIGH,
                    tier=3,
                    recommended_actions=[
                        "Check metrics-server deployment: oc get deployment metrics-server -n kube-system",
                        "Verify metrics-server is running: oc get pods -n kube-system -l k8s-app=metrics-server",
                        "Check HPA metrics configuration in spec.metrics",
                        "Verify pod has resource requests defined (required for CPU/memory metrics)",
                        "Test metrics API: kubectl top pods -n " + observation.namespace
                    ],
                    evidence={
                        "hpa_status": status,
                        "hpa_spec": spec,
                        "message": observation.message
                    }
                )

        # Check for missing scale target
        for pattern in self.SCALEREF_MISSING_PATTERNS:
            if re.search(pattern, message_combined, re.IGNORECASE):
                logger.info(
                    f"HPA issue categorized as missing scale target",
                    request_id=request_id,
                    pattern=pattern
                )

                scale_target_ref = spec.get("scaleTargetRef", {})
                target_kind = scale_target_ref.get("kind", "unknown")
                target_name = scale_target_ref.get("name", "unknown")

                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.HPA_MISSING_SCALEREF,
                    root_cause=f"HPA scale target not found: {target_kind}/{target_name}",
                    confidence=Confidence.HIGH,
                    tier=3,
                    recommended_actions=[
                        f"Verify {target_kind} '{target_name}' exists: oc get {target_kind} {target_name} -n {observation.namespace}",
                        "Check if deployment/statefulset was deleted",
                        "Update HPA scaleTargetRef or delete HPA if no longer needed"
                    ],
                    evidence={
                        "scale_target_ref": scale_target_ref,
                        "target_kind": target_kind,
                        "target_name": target_name
                    }
                )

        # Check if HPA is at max replicas
        current_replicas = status.get("currentReplicas", 0)
        max_replicas = spec.get("maxReplicas", 0)

        if current_replicas >= max_replicas:
            logger.info(
                f"HPA at maximum replicas",
                request_id=request_id,
                current=current_replicas,
                max=max_replicas
            )

            # This is Tier 2 - we can propose config change
            return self._create_diagnosis(
                observation=observation,
                category=DiagnosisCategory.RESOURCE_QUOTA_EXCEEDED,  # Reusing existing category
                root_cause=f"HPA reached maximum replicas ({max_replicas}), consider increasing maxReplicas",
                confidence=Confidence.HIGH,
                tier=2,
                recommended_actions=[
                    f"Increase HPA maxReplicas from {max_replicas} to {max_replicas * 2}",
                    "Verify cluster has capacity for additional pods",
                    "Consider vertical scaling (increase pod resources) instead"
                ],
                evidence={
                    "current_replicas": current_replicas,
                    "max_replicas": max_replicas,
                    "current_metrics": status.get("currentMetrics", [])
                }
            )

        # Generic HPA issue (Tier 3)
        return self._create_diagnosis(
            observation=observation,
            category=DiagnosisCategory.UNKNOWN,
            root_cause=f"HPA issue: {observation.message}",
            confidence=Confidence.MEDIUM,
            tier=3,
            recommended_actions=[
                "Check HPA status: oc describe hpa " + observation.resource_name + " -n " + observation.namespace,
                "Review HPA events for errors",
                "Verify target deployment/statefulset exists and is healthy"
            ],
            evidence={
                "hpa_status": status,
                "observation_message": observation.message
            }
        )

    async def _analyze_cluster_autoscaler_issue(
        self,
        observation: Observation,
        request_id: str
    ) -> Diagnosis:
        """
        Analyze ClusterAutoscaler issue.

        Args:
            observation: ClusterAutoscaler observation
            request_id: Request ID for logging

        Returns:
            Diagnosis for ClusterAutoscaler issue
        """
        raw_data = observation.raw_data
        status = raw_data.get("status", {})

        # Get condition details
        conditions = status.get("conditions", [])
        message_combined = observation.message.lower()

        for condition in conditions:
            reason = condition.get("reason", "")
            message = condition.get("message", "")
            message_combined += f" {reason} {message}".lower()

        # Check for node capacity issues
        for pattern in self.NODE_CAPACITY_PATTERNS:
            if re.search(pattern, message_combined, re.IGNORECASE):
                logger.info(
                    f"ClusterAutoscaler issue categorized as insufficient capacity",
                    request_id=request_id,
                    pattern=pattern
                )

                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.NODE_SCALE_INSUFFICIENT_RESOURCES,
                    root_cause=f"ClusterAutoscaler cannot provision nodes: {observation.message}",
                    confidence=Confidence.HIGH,
                    tier=3,
                    recommended_actions=[
                        "Check cloud provider quotas (EC2 instance limits, vCPU limits)",
                        "Verify MachineAutoscaler configuration: oc get machineautoscaler -n openshift-machine-api",
                        "Check MachineSet limits: oc get machinesets -n openshift-machine-api",
                        "Review ClusterAutoscaler logs: oc logs -n openshift-machine-api -l cluster-autoscaler=default",
                        "Verify cloud provider credentials and permissions"
                    ],
                    evidence={
                        "autoscaler_status": status,
                        "message": observation.message
                    }
                )

        # Generic ClusterAutoscaler issue (Tier 3)
        return self._create_diagnosis(
            observation=observation,
            category=DiagnosisCategory.CLUSTER_AUTOSCALER_FAILED,
            root_cause=f"ClusterAutoscaler failed: {observation.message}",
            confidence=Confidence.MEDIUM,
            tier=3,
            recommended_actions=[
                "Check ClusterAutoscaler status: oc get clusterautoscaler default -o yaml",
                "Review ClusterAutoscaler operator: oc get clusteroperator cluster-autoscaler",
                "Check MachineAutoscaler configurations",
                "Review autoscaler logs for detailed errors"
            ],
            evidence={
                "autoscaler_status": status,
                "observation_message": observation.message
            }
        )

    def _create_diagnosis(
        self,
        observation: Observation,
        category: DiagnosisCategory,
        root_cause: str,
        confidence: Confidence,
        tier: int,
        recommended_actions: list[str] = None,
        evidence: dict = None
    ) -> Diagnosis:
        """
        Create a Diagnosis object.

        Args:
            observation: Source observation
            category: Diagnosis category
            root_cause: Root cause description
            confidence: Confidence level
            tier: Recommended tier
            recommended_actions: List of recommended actions
            evidence: Supporting evidence

        Returns:
            Diagnosis object
        """
        return Diagnosis(
            observation_id=observation.id,
            category=category,
            root_cause=root_cause,
            confidence=confidence,
            recommended_tier=tier,
            recommended_actions=recommended_actions or [],
            evidence=evidence or {},
            analyzer_name=self.analyzer_name
        )
