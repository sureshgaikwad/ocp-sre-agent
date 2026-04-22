"""
Route analyzer for diagnosing OpenShift Route issues.

Analyzes Route problems including:
- Service endpoint availability
- TLS/certificate issues
- Backend unavailability
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

logger = get_logger(__name__)


class RouteAnalyzer(BaseAnalyzer):
    """
    Analyzer for OpenShift Route issues.

    Diagnoses route problems by checking:
    1. Service existence and endpoints
    2. Pod readiness behind the service
    3. TLS/certificate configuration
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize RouteAnalyzer.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "route_analyzer")

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        Args:
            observation: Observation to check

        Returns:
            True if observation is a Route error
        """
        return observation.type == ObservationType.ROUTE_ERROR

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze a Route observation.

        Args:
            observation: Route observation to analyze

        Returns:
            Diagnosis with root cause analysis
        """
        request_id = logger.set_request_id()

        logger.info(
            f"Analyzing Route observation: {observation.resource_name}",
            request_id=request_id,
            observation_id=observation.id,
            route=observation.resource_name,
            namespace=observation.namespace
        )

        try:
            # Extract route details
            route_data = observation.raw_data
            spec = route_data.get("spec", {})
            status = route_data.get("status", {})

            # Get service name
            service_name = spec.get("to", {}).get("name")
            if not service_name:
                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.UNKNOWN,
                    root_cause="Route has no backend service configured",
                    confidence=Confidence.HIGH,
                    tier=3,
                    evidence=build_evidence(
                    observation,
                    "route_spec": spec
                )
                )

            # Check if route is admitted
            ingress = status.get("ingress", [])
            if not ingress:
                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.UNKNOWN,
                    root_cause="Route not admitted by any router",
                    confidence=Confidence.HIGH,
                    tier=3,
                    recommended_actions=[
                        "Check router pods in openshift-ingress namespace",
                        "Verify route configuration",
                        "Check for router selectors matching route labels"
                    ],
                    evidence=build_evidence(
                    observation,
                    "route_status": status
                )
                )

            # Check for TLS issues
            tls_config = spec.get("tls", {})
            if tls_config:
                tls_diagnosis = await self._check_tls_issues(observation, tls_config, request_id)
                if tls_diagnosis:
                    return tls_diagnosis

            # Check service endpoints
            endpoints_diagnosis = await self._check_service_endpoints(
                observation, service_name, request_id
            )
            if endpoints_diagnosis:
                return endpoints_diagnosis

            # If we get here, issue might be transient
            return self._create_diagnosis(
                observation=observation,
                category=DiagnosisCategory.ROUTE_BACKEND_TEMPORARILY_UNAVAILABLE,
                root_cause=f"Route backend service '{service_name}' temporarily unavailable",
                confidence=Confidence.MEDIUM,
                tier=1,
                recommended_actions=[
                    "Wait for backend pods to become ready",
                    "Check service endpoint status"
                ],
                evidence=build_evidence(
                    observation,
                    "service": service_name, "route_spec": spec
                )
            )

        except Exception as e:
            logger.error(
                f"Failed to analyze Route observation: {e}",
                request_id=request_id,
                observation_id=observation.id,
                exc_info=True
            )
            return None

    async def _check_service_endpoints(
        self,
        observation: Observation,
        service_name: str,
        request_id: str
    ) -> Optional[Diagnosis]:
        """
        Check if the backing service has endpoints.

        Args:
            observation: Route observation
            service_name: Name of backend service
            request_id: Request ID for logging

        Returns:
            Diagnosis if service has no endpoints, None otherwise
        """
        try:
            # Get endpoints for the service
            endpoints_json = await self._get_endpoints(observation.namespace, service_name)

            if not endpoints_json:
                logger.warning(
                    f"Could not retrieve endpoints for service {service_name}",
                    request_id=request_id,
                    service=service_name,
                    namespace=observation.namespace
                )
                return None

            # Parse endpoints
            try:
                endpoints_data = json.loads(endpoints_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse endpoints JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return None

            # Check if endpoints exist
            subsets = endpoints_data.get("subsets", [])
            has_ready_endpoints = False

            for subset in subsets:
                addresses = subset.get("addresses", [])
                if addresses:
                    has_ready_endpoints = True
                    break

            if not has_ready_endpoints:
                # Service has no ready endpoints
                logger.warning(
                    f"Service {service_name} has no ready endpoints",
                    request_id=request_id,
                    service=service_name,
                    namespace=observation.namespace
                )

                # Get service to find pod selector
                service_json = await self._get_service(observation.namespace, service_name)
                selector = {}
                if service_json:
                    try:
                        service_data = json.loads(service_json)
                        selector = service_data.get("spec", {}).get("selector", {})
                    except json.JSONDecodeError:
                        pass

                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.ROUTE_SERVICE_NO_ENDPOINTS,
                    root_cause=f"Service '{service_name}' has no ready endpoints",
                    confidence=Confidence.HIGH,
                    tier=2,
                    recommended_actions=[
                        f"Scale up deployment for service '{service_name}'",
                        "Check pod status for selector: " + str(selector),
                        "Verify pod readiness probes"
                    ],
                    evidence=build_evidence(
                    observation,
                    "service": service_name,
                    "endpoints": endpoints_data,
                    "selector": selector
                )
                )

        except NotImplementedError as e:
            logger.warning(
                f"Endpoints check not implemented: {e}",
                request_id=request_id
            )
            return None
        except Exception as e:
            logger.error(
                f"Failed to check service endpoints: {e}",
                request_id=request_id,
                exc_info=True
            )
            return None

        return None

    async def _check_tls_issues(
        self,
        observation: Observation,
        tls_config: dict,
        request_id: str
    ) -> Optional[Diagnosis]:
        """
        Check for TLS/certificate issues.

        Args:
            observation: Route observation
            tls_config: TLS configuration from route spec
            request_id: Request ID for logging

        Returns:
            Diagnosis if TLS issues detected, None otherwise
        """
        # Check termination type
        termination = tls_config.get("termination", "")

        # Check if certificate is provided for edge/reencrypt
        if termination in ["edge", "reencrypt"]:
            certificate = tls_config.get("certificate", "")
            key = tls_config.get("key", "")

            if not certificate or not key:
                logger.warning(
                    f"Route {observation.resource_name} has TLS but missing cert/key",
                    request_id=request_id,
                    route=observation.resource_name,
                    termination=termination
                )

                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.ROUTE_TLS_CERT_ERROR,
                    root_cause=f"TLS configured with {termination} termination but certificate or key missing",
                    confidence=Confidence.HIGH,
                    tier=3,
                    recommended_actions=[
                        "Provide TLS certificate and key in route configuration",
                        "Or configure route to use default ingress certificate"
                    ],
                    evidence=build_evidence(
                    observation,
                    "tls_config": tls_config
                )
                )

        # Note: Actual certificate expiry checking would require parsing the cert
        # This could be added as an enhancement

        return None

    async def _get_endpoints(self, namespace: str, service_name: str) -> str:
        """
        Get endpoints for a service.

        Args:
            namespace: Namespace
            service_name: Service name

        Returns:
            JSON string of endpoints

        Raises:
            NotImplementedError: Until MCP tool name is configured
        """
        # TODO: Configure actual MCP tool name
        raise NotImplementedError(
            f"RouteAnalyzer._get_endpoints(): Configure MCP tool name for "
            f"'oc get endpoints {service_name} -n {namespace} -o json'"
        )

    async def _get_service(self, namespace: str, service_name: str) -> str:
        """
        Get service details.

        Args:
            namespace: Namespace
            service_name: Service name

        Returns:
            JSON string of service

        Raises:
            NotImplementedError: Until MCP tool name is configured
        """
        # TODO: Configure actual MCP tool name
        raise NotImplementedError(
            f"RouteAnalyzer._get_service(): Configure MCP tool name for "
            f"'oc get service {service_name} -n {namespace} -o json'"
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
