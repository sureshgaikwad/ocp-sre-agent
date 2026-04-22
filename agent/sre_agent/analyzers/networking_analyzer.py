"""
Networking analyzer for diagnosing OpenShift networking issues.

Analyzes networking problems including:
- SDN/OVN pod failures
- DNS resolution issues
- NetworkPolicy blocking
"""

import json
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.analyzers.base import BaseAnalyzer
from sre_agent.analyzers.evidence_builder import build_evidence
from sre_agent.models.observation import Observation, ObservationType
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.secret_scrubber import SecretScrubber

logger = get_logger(__name__)


class NetworkingAnalyzer(BaseAnalyzer):
    """
    Analyzer for OpenShift networking issues.

    Diagnoses networking problems by analyzing:
    1. SDN/OVN pod status and logs
    2. DNS pod status and logs
    3. NetworkPolicy events
    """

    # Regex patterns for categorizing networking failures
    DNS_PATTERNS = [
        r"dial.*no such host",
        r"lookup.*on.*no such host",
        r"name resolution failed",
        r"could not resolve host",
        r"DNS.*failed",
        r"nxdomain",
    ]

    NETWORK_POLICY_PATTERNS = [
        r"network.*policy.*denied",
        r"connection.*refused",
        r"policy.*blocked",
        r"ingress.*denied",
        r"egress.*denied",
    ]

    SDN_OVN_PATTERNS = [
        r"ovs.*failed",
        r"openflow.*error",
        r"tunnel.*down",
        r"vxlan.*error",
        r"CNI.*failed",
    ]

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize NetworkingAnalyzer.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "networking_analyzer")

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        Args:
            observation: Observation to check

        Returns:
            True if observation is a networking issue
        """
        return observation.type in [
            ObservationType.DNS_FAILURE,
            ObservationType.SDN_DEGRADED,
            ObservationType.NETWORK_POLICY_VIOLATION,
            ObservationType.SERVICE_NO_ENDPOINTS
        ]

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze a networking observation.

        Args:
            observation: Networking observation to analyze

        Returns:
            Diagnosis with root cause analysis
        """
        request_id = logger.set_request_id()

        logger.info(
            f"Analyzing networking observation: {observation.resource_name}",
            request_id=request_id,
            observation_id=observation.id,
            resource=observation.resource_name,
            namespace=observation.namespace,
            type=observation.type.value
        )

        try:
            # Route to specific analyzer based on observation type
            if observation.type == ObservationType.DNS_FAILURE:
                return await self._analyze_dns_failure(observation, request_id)
            elif observation.type == ObservationType.SDN_DEGRADED:
                return await self._analyze_sdn_failure(observation, request_id)
            elif observation.type == ObservationType.NETWORK_POLICY_VIOLATION:
                return await self._analyze_network_policy(observation, request_id)
            elif observation.type == ObservationType.SERVICE_NO_ENDPOINTS:
                return await self._analyze_service_endpoints(observation, request_id)
            else:
                return None

        except Exception as e:
            logger.error(
                f"Failed to analyze networking observation: {e}",
                request_id=request_id,
                observation_id=observation.id,
                exc_info=True
            )
            return None

    async def _analyze_dns_failure(
        self,
        observation: Observation,
        request_id: str
    ) -> Diagnosis:
        """
        Analyze DNS pod failure.

        Args:
            observation: DNS failure observation
            request_id: Request ID for logging

        Returns:
            Diagnosis for DNS issue
        """
        # Try to get pod logs for more details
        logs = await self._get_pod_logs(observation, request_id)

        # Scrub secrets
        if logs:
            logs = SecretScrubber.scrub(logs)

        # Check if it's a pod failure or actual DNS resolution issue
        raw_data = observation.raw_data
        status = raw_data.get("status", {})
        phase = status.get("phase", "Unknown")

        if phase in ["Pending", "Failed", "Unknown"]:
            # DNS pod itself is unhealthy
            return self._create_diagnosis(
                observation=observation,
                category=DiagnosisCategory.DNS_RESOLUTION_FAILURE,
                root_cause=f"DNS pod {observation.resource_name} is in {phase} state",
                confidence=Confidence.HIGH,
                tier=3,
                recommended_actions=[
                    "Check DNS operator status: oc get clusteroperator dns",
                    "Review DNS pod logs for errors",
                    "Verify DNS operator configuration",
                    "Check node resources where DNS pods are scheduled"
                ],
                evidence=build_evidence(
                    observation,
                    "pod_phase": phase,
                    "pod_status": status,
                    "logs_snippet": logs[:500] if logs else None
                )
            )
        else:
            # DNS pod running but might have issues
            return self._create_diagnosis(
                observation=observation,
                category=DiagnosisCategory.DNS_RESOLUTION_FAILURE,
                root_cause=f"DNS service degraded: {observation.message}",
                confidence=Confidence.MEDIUM,
                tier=3,
                recommended_actions=[
                    "Check DNS pod logs for resolution errors",
                    "Verify upstream DNS servers",
                    "Check CoreDNS configuration"
                ],
                evidence=build_evidence(
                    observation,
                    "logs_snippet": logs[:500] if logs else None
                )
            )

    async def _analyze_sdn_failure(
        self,
        observation: Observation,
        request_id: str
    ) -> Diagnosis:
        """
        Analyze SDN/OVN pod failure.

        Args:
            observation: SDN failure observation
            request_id: Request ID for logging

        Returns:
            Diagnosis for SDN issue
        """
        # Try to get pod logs for more details
        logs = await self._get_pod_logs(observation, request_id)

        # Scrub secrets
        if logs:
            logs = SecretScrubber.scrub(logs)

        # Check pod status
        raw_data = observation.raw_data
        status = raw_data.get("status", {})
        phase = status.get("phase", "Unknown")

        # Determine network plugin (SDN vs OVN)
        namespace = observation.namespace
        network_plugin = "OVN-Kubernetes" if "ovn" in namespace else "OpenShift SDN"

        return self._create_diagnosis(
            observation=observation,
            category=DiagnosisCategory.SDN_POD_FAILURE,
            root_cause=f"{network_plugin} pod {observation.resource_name} is unhealthy (phase: {phase})",
            confidence=Confidence.HIGH,
            tier=3,
            recommended_actions=[
                f"Check {network_plugin} operator status",
                "Review network pod logs for errors",
                "Verify node network connectivity",
                "Check for OVS/kernel module issues on affected nodes",
                "Restart network pods if safe to do so"
            ],
            evidence=build_evidence(
                    observation,
                    "pod_phase": phase,
                    "pod_status": status,
                    "network_plugin": network_plugin,
                    "logs_snippet": logs[:500] if logs else None
                )
        )

    async def _analyze_network_policy(
        self,
        observation: Observation,
        request_id: str
    ) -> Diagnosis:
        """
        Analyze NetworkPolicy violation.

        Args:
            observation: NetworkPolicy observation
            request_id: Request ID for logging

        Returns:
            Diagnosis for NetworkPolicy issue
        """
        return self._create_diagnosis(
            observation=observation,
            category=DiagnosisCategory.NETWORK_POLICY_BLOCKING,
            root_cause=f"NetworkPolicy blocking traffic: {observation.message}",
            confidence=Confidence.MEDIUM,
            tier=3,
            recommended_actions=[
                "Review NetworkPolicies in affected namespace",
                "Check ingress/egress rules",
                "Verify pod labels match policy selectors",
                "Test connectivity with a temporary allow-all policy (for debugging only)"
            ],
            evidence=build_evidence(
                    observation,
                    "observation_message": observation.message,
                    "namespace": observation.namespace
                )
        )

    async def _analyze_service_endpoints(
        self,
        observation: Observation,
        request_id: str
    ) -> Diagnosis:
        """
        Analyze service with no endpoints.

        Args:
            observation: Service endpoints observation
            request_id: Request ID for logging

        Returns:
            Diagnosis for service endpoints issue
        """
        return self._create_diagnosis(
            observation=observation,
            category=DiagnosisCategory.ROUTE_SERVICE_NO_ENDPOINTS,
            root_cause=f"Service has no ready endpoints: {observation.message}",
            confidence=Confidence.HIGH,
            tier=2,
            recommended_actions=[
                "Check pod status for the service",
                "Verify pod readiness probes",
                "Scale deployment if needed",
                "Check for NetworkPolicy blocking health checks"
            ],
            evidence=build_evidence(
                    observation,
                    "observation_message": observation.message,
                    "namespace": observation.namespace
                )
        )

    async def _get_pod_logs(
        self,
        observation: Observation,
        request_id: str
    ) -> Optional[str]:
        """
        Get logs for a pod.

        Args:
            observation: Observation with pod info
            request_id: Request ID for logging

        Returns:
            Logs as string, or None if unable to fetch
        """
        try:
            logs = await self._get_pod_logs_via_mcp(
                observation.namespace,
                observation.resource_name
            )

            logger.info(
                f"Retrieved logs for pod {observation.resource_name}",
                request_id=request_id,
                pod=observation.resource_name,
                log_length=len(logs) if logs else 0
            )

            return logs

        except NotImplementedError as e:
            logger.warning(
                f"Pod logs retrieval not implemented: {e}",
                request_id=request_id
            )
            return None
        except Exception as e:
            logger.error(
                f"Failed to get pod logs: {e}",
                request_id=request_id,
                exc_info=True
            )
            return None

    async def _get_pod_logs_via_mcp(self, namespace: str, pod_name: str) -> str:
        """
        Get pod logs via MCP.

        Args:
            namespace: Namespace
            pod_name: Pod name

        Returns:
            Logs as string

        Raises:
            NotImplementedError: Until MCP tool name is configured
        """
        # TODO: Configure actual MCP tool name
        raise NotImplementedError(
            f"NetworkingAnalyzer._get_pod_logs_via_mcp(): Configure MCP tool name for "
            f"'oc logs {pod_name} -n {namespace}'"
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
