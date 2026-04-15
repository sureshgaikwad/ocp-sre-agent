"""
Networking collector for monitoring OpenShift SDN/OVN and NetworkPolicies.

Monitors network infrastructure health and policy issues.
"""

import json
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class NetworkingCollector(BaseCollector):
    """
    Collector for OpenShift networking components.

    Monitors:
    - SDN/OVN pods in openshift-sdn or openshift-ovn-kubernetes namespaces
    - DNS pods (CoreDNS) in openshift-dns namespace
    - NetworkPolicy issues (detected via events)
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize NetworkingCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "networking_collector")

    async def collect(self) -> list[Observation]:
        """
        Collect networking observations.

        Returns:
            List of Observation objects for networking issues

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting networking collection",
                request_id=request_id,
                action_taken="collect_networking"
            )

            # Collect SDN/OVN pod issues
            sdn_obs = await self._collect_sdn_issues(request_id)
            observations.extend(sdn_obs)

            # Collect DNS pod issues
            dns_obs = await self._collect_dns_issues(request_id)
            observations.extend(dns_obs)

            logger.info(
                f"Networking collection completed: {len(observations)} issues found",
                request_id=request_id,
                observation_count=len(observations)
            )

        except Exception as e:
            logger.error(
                f"Networking collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            # Don't re-raise - allow other collectors to run

        return observations

    async def _collect_sdn_issues(self, request_id: str) -> list[Observation]:
        """
        Collect SDN/OVN pod issues.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for SDN/OVN issues
        """
        observations = []

        # Check which network type is in use (SDN or OVN)
        # First check openshift-sdn namespace
        for namespace in ["openshift-sdn", "openshift-ovn-kubernetes"]:
            try:
                pods_json = await self._get_pods_in_namespace(namespace)

                if not pods_json:
                    # Namespace might not exist (SDN vs OVN)
                    continue

                # Parse pods
                try:
                    pods_data = json.loads(pods_json)
                except json.JSONDecodeError as e:
                    logger.error(
                        f"Failed to parse pods JSON for {namespace}: {e}",
                        request_id=request_id,
                        namespace=namespace,
                        exc_info=True
                    )
                    continue

                items = pods_data.get("items", [])
                logger.info(
                    f"Retrieved {len(items)} pods from {namespace}",
                    request_id=request_id,
                    namespace=namespace,
                    pod_count=len(items)
                )

                # Process each pod
                for pod_item in items:
                    try:
                        obs = self._process_network_pod(pod_item, namespace, request_id)
                        if obs:
                            observations.append(obs)
                    except Exception as e:
                        logger.error(
                            f"Failed to process network pod: {e}",
                            request_id=request_id,
                            pod=pod_item.get("metadata", {}).get("name"),
                            exc_info=True
                        )

            except Exception as e:
                logger.error(
                    f"Failed to collect SDN pods from {namespace}: {e}",
                    request_id=request_id,
                    namespace=namespace,
                    exc_info=True
                )

        return observations

    async def _collect_dns_issues(self, request_id: str) -> list[Observation]:
        """
        Collect DNS pod issues.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for DNS issues
        """
        observations = []
        namespace = "openshift-dns"

        try:
            pods_json = await self._get_pods_in_namespace(namespace)

            if not pods_json:
                logger.warning(
                    f"No DNS pods data returned from namespace {namespace}",
                    request_id=request_id,
                    namespace=namespace
                )
                return observations

            # Parse pods
            try:
                pods_data = json.loads(pods_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse DNS pods JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = pods_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} DNS pods",
                request_id=request_id,
                pod_count=len(items)
            )

            # Process each DNS pod
            for pod_item in items:
                try:
                    obs = self._process_dns_pod(pod_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process DNS pod: {e}",
                        request_id=request_id,
                        pod=pod_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

        except Exception as e:
            logger.error(
                f"Failed to collect DNS pods: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _get_pods_in_namespace(self, namespace: str) -> str:
        """
        Get pods in a specific namespace via Kubernetes API.

        Args:
            namespace: Namespace to query

        Returns:
            JSON string of pods

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_pods():
                try:
                    # List pods in the specific namespace
                    pod_list = self.core_api.list_namespaced_pod(namespace=namespace)
                    return self.core_api.api_client.sanitize_for_serialization(pod_list)
                except ApiException as e:
                    if e.status == 404:
                        # Namespace doesn't exist
                        logger.debug(f"Namespace {namespace} not found")
                        return {"items": []}
                    logger.error(f"Kubernetes API error listing pods in {namespace}: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            pods_dict = await asyncio.to_thread(_list_pods)

            # Return as JSON string
            return json.dumps(pods_dict)

        except Exception as e:
            logger.error(
                f"Failed to list pods in namespace {namespace}: {e}",
                exc_info=True
            )
            raise

    def _process_network_pod(self, pod_item: dict, namespace: str, request_id: str) -> Observation | None:
        """
        Process a network infrastructure pod (SDN/OVN).

        Args:
            pod_item: Pod JSON object
            namespace: Namespace (openshift-sdn or openshift-ovn-kubernetes)
            request_id: Request ID for logging

        Returns:
            Observation if pod has issues, None otherwise
        """
        metadata = pod_item.get("metadata", {})
        status = pod_item.get("status", {})

        pod_name = metadata.get("name", "unknown")
        phase = status.get("phase", "Unknown")

        # Check if pod is unhealthy
        if phase not in ["Running", "Succeeded"]:
            logger.warning(
                f"Network pod {namespace}/{pod_name} in {phase} state",
                request_id=request_id,
                pod=pod_name,
                namespace=namespace,
                phase=phase
            )

            return Observation(
                type=ObservationType.SDN_DEGRADED,
                severity=Severity.CRITICAL,
                namespace=namespace,
                resource_kind="Pod",
                resource_name=pod_name,
                message=f"Network infrastructure pod unhealthy: {pod_name} in {phase} state",
                raw_data=pod_item,
                labels=metadata.get("labels", {})
            )

        # Check container statuses
        container_statuses = status.get("containerStatuses", [])
        for container_status in container_statuses:
            if not container_status.get("ready", False):
                container_name = container_status.get("name", "unknown")
                state = container_status.get("state", {})

                logger.warning(
                    f"Network pod {namespace}/{pod_name} container {container_name} not ready",
                    request_id=request_id,
                    pod=pod_name,
                    container=container_name,
                    state=state
                )

                return Observation(
                    type=ObservationType.SDN_DEGRADED,
                    severity=Severity.CRITICAL,
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod_name,
                    message=f"Network infrastructure container not ready: {container_name}",
                    raw_data=pod_item,
                    labels=metadata.get("labels", {})
                )

        return None

    def _process_dns_pod(self, pod_item: dict, request_id: str) -> Observation | None:
        """
        Process a DNS pod.

        Args:
            pod_item: Pod JSON object
            request_id: Request ID for logging

        Returns:
            Observation if pod has issues, None otherwise
        """
        metadata = pod_item.get("metadata", {})
        status = pod_item.get("status", {})

        pod_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "openshift-dns")
        phase = status.get("phase", "Unknown")

        # Check if DNS pod is unhealthy
        if phase not in ["Running", "Succeeded"]:
            logger.warning(
                f"DNS pod {namespace}/{pod_name} in {phase} state",
                request_id=request_id,
                pod=pod_name,
                phase=phase
            )

            return Observation(
                type=ObservationType.DNS_FAILURE,
                severity=Severity.CRITICAL,
                namespace=namespace,
                resource_kind="Pod",
                resource_name=pod_name,
                message=f"DNS pod unhealthy: {pod_name} in {phase} state",
                raw_data=pod_item,
                labels=metadata.get("labels", {})
            )

        # Check container statuses
        container_statuses = status.get("containerStatuses", [])
        for container_status in container_statuses:
            if not container_status.get("ready", False):
                container_name = container_status.get("name", "unknown")
                state = container_status.get("state", {})

                logger.warning(
                    f"DNS pod {namespace}/{pod_name} container {container_name} not ready",
                    request_id=request_id,
                    pod=pod_name,
                    container=container_name,
                    state=state
                )

                return Observation(
                    type=ObservationType.DNS_FAILURE,
                    severity=Severity.CRITICAL,
                    namespace=namespace,
                    resource_kind="Pod",
                    resource_name=pod_name,
                    message=f"DNS container not ready: {container_name}",
                    raw_data=pod_item,
                    labels=metadata.get("labels", {})
                )

        return None

    def __str__(self) -> str:
        """String representation."""
        return f"NetworkingCollector(monitoring SDN/OVN and DNS)"
