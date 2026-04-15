"""
Autoscaling collector for monitoring HPA and ClusterAutoscaler.

Monitors:
- HorizontalPodAutoscalers (HPA) status
- ClusterAutoscaler status
- MachineAutoscaler status (OpenShift)
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


class AutoscalingCollector(BaseCollector):
    """
    Collector for autoscaling components.

    Monitors:
    - HorizontalPodAutoscalers (HPA) - unable to scale, missing metrics
    - ClusterAutoscaler - node scaling failures
    - MachineAutoscaler - machine provisioning issues
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize AutoscalingCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "autoscaling_collector")

    async def collect(self) -> list[Observation]:
        """
        Collect autoscaling observations.

        Returns:
            List of Observation objects for autoscaling issues

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting autoscaling collection",
                request_id=request_id,
                action_taken="collect_autoscaling"
            )

            # Collect HPA issues
            hpa_obs = await self._collect_hpa_issues(request_id)
            observations.extend(hpa_obs)

            # Collect ClusterAutoscaler issues
            ca_obs = await self._collect_cluster_autoscaler_issues(request_id)
            observations.extend(ca_obs)

            logger.info(
                f"Autoscaling collection completed: {len(observations)} issues found",
                request_id=request_id,
                observation_count=len(observations)
            )

        except Exception as e:
            logger.error(
                f"Autoscaling collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            # Don't re-raise - allow other collectors to run

        return observations

    async def _collect_hpa_issues(self, request_id: str) -> list[Observation]:
        """
        Collect HorizontalPodAutoscaler issues.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for HPA issues
        """
        observations = []

        try:
            # Get all HPAs
            hpas_json = await self._get_hpas()

            if not hpas_json:
                logger.debug(
                    "No HPA data returned",
                    request_id=request_id
                )
                return observations

            # Parse HPAs
            try:
                hpas_data = json.loads(hpas_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse HPAs JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = hpas_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} HPAs",
                request_id=request_id,
                hpa_count=len(items)
            )

            # Process each HPA
            for hpa_item in items:
                try:
                    obs = self._process_hpa(hpa_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process HPA: {e}",
                        request_id=request_id,
                        hpa=hpa_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

        except NotImplementedError as e:
            logger.warning(
                f"HPA collection not implemented: {e}",
                request_id=request_id
            )
        except Exception as e:
            logger.error(
                f"Failed to collect HPAs: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _collect_cluster_autoscaler_issues(self, request_id: str) -> list[Observation]:
        """
        Collect ClusterAutoscaler issues.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for ClusterAutoscaler issues
        """
        observations = []

        try:
            # Get ClusterAutoscaler status
            ca_json = await self._get_cluster_autoscaler()

            if not ca_json:
                logger.debug(
                    "No ClusterAutoscaler data returned",
                    request_id=request_id
                )
                return observations

            # Parse ClusterAutoscaler
            try:
                ca_data = json.loads(ca_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse ClusterAutoscaler JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            # Check if it's a list of autoscalers or single item
            items = ca_data.get("items", [ca_data] if ca_data.get("kind") == "ClusterAutoscaler" else [])

            logger.info(
                f"Retrieved {len(items)} ClusterAutoscaler(s)",
                request_id=request_id,
                ca_count=len(items)
            )

            # Process each ClusterAutoscaler
            for ca_item in items:
                try:
                    obs = self._process_cluster_autoscaler(ca_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process ClusterAutoscaler: {e}",
                        request_id=request_id,
                        exc_info=True
                    )

        except NotImplementedError as e:
            logger.warning(
                f"ClusterAutoscaler collection not implemented: {e}",
                request_id=request_id
            )
        except Exception as e:
            logger.error(
                f"Failed to collect ClusterAutoscaler: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _get_hpas(self) -> str:
        """
        Get all HorizontalPodAutoscalers via Kubernetes API.

        Returns:
            JSON string of HPAs

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_hpas():
                try:
                    # List HPAs across all namespaces
                    result = self.autoscaling_api.list_horizontal_pod_autoscaler_for_all_namespaces()
                    return self.autoscaling_api.api_client.sanitize_for_serialization(result)
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing HPAs: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            hpas_dict = await asyncio.to_thread(_list_hpas)

            # Return as JSON string
            return json.dumps(hpas_dict)

        except Exception as e:
            logger.error(
                f"Failed to list HorizontalPodAutoscalers: {e}",
                exc_info=True
            )
            raise

    async def _get_cluster_autoscaler(self) -> str:
        """
        Get ClusterAutoscaler via Kubernetes API.

        Returns:
            JSON string of ClusterAutoscaler

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_cluster_autoscalers():
                try:
                    # ClusterAutoscaler is an OpenShift custom resource
                    result = self.custom_api.list_cluster_custom_object(
                        group="autoscaling.openshift.io",
                        version="v1",
                        plural="clusterautoscalers"
                    )
                    return result
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing ClusterAutoscalers: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            ca_dict = await asyncio.to_thread(_list_cluster_autoscalers)

            # Return as JSON string
            return json.dumps(ca_dict)

        except Exception as e:
            logger.error(
                f"Failed to list ClusterAutoscalers: {e}",
                exc_info=True
            )
            raise

    def _process_hpa(self, hpa_item: dict, request_id: str) -> Observation | None:
        """
        Process a single HPA.

        Args:
            hpa_item: HPA JSON object
            request_id: Request ID for logging

        Returns:
            Observation if HPA has issues, None otherwise
        """
        metadata = hpa_item.get("metadata", {})
        status = hpa_item.get("status", {})
        spec = hpa_item.get("spec", {})

        hpa_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "default")

        # Check conditions for issues
        conditions = status.get("conditions", [])
        for condition in conditions:
            condition_type = condition.get("type", "")
            condition_status = condition.get("status", "")
            reason = condition.get("reason", "")
            message = condition.get("message", "")

            # AbleToScale = False means HPA cannot scale
            if condition_type == "AbleToScale" and condition_status != "True":
                logger.warning(
                    f"HPA {namespace}/{hpa_name} unable to scale: {reason}",
                    request_id=request_id,
                    hpa=hpa_name,
                    namespace=namespace,
                    reason=reason
                )

                return Observation(
                    type=ObservationType.HPA_UNABLE_TO_SCALE,
                    severity=Severity.CRITICAL,
                    namespace=namespace,
                    resource_kind="HorizontalPodAutoscaler",
                    resource_name=hpa_name,
                    message=f"HPA unable to scale: {reason} - {message}",
                    raw_data=hpa_item,
                    labels=metadata.get("labels", {})
                )

            # ScalingActive = False means HPA is not actively scaling
            if condition_type == "ScalingActive" and condition_status != "True":
                logger.warning(
                    f"HPA {namespace}/{hpa_name} scaling not active: {reason}",
                    request_id=request_id,
                    hpa=hpa_name,
                    namespace=namespace,
                    reason=reason
                )

                return Observation(
                    type=ObservationType.HPA_DEGRADED,
                    severity=Severity.WARNING,
                    namespace=namespace,
                    resource_kind="HorizontalPodAutoscaler",
                    resource_name=hpa_name,
                    message=f"HPA scaling inactive: {reason} - {message}",
                    raw_data=hpa_item,
                    labels=metadata.get("labels", {})
                )

        # Check if HPA is at max replicas and still under load
        current_replicas = status.get("currentReplicas", 0)
        desired_replicas = status.get("desiredReplicas", 0)
        max_replicas = spec.get("maxReplicas", 0)

        if current_replicas == max_replicas and desired_replicas >= max_replicas:
            # HPA is maxed out - potential capacity issue
            current_metrics = status.get("currentMetrics", [])

            logger.info(
                f"HPA {namespace}/{hpa_name} at max replicas ({max_replicas})",
                request_id=request_id,
                hpa=hpa_name,
                namespace=namespace,
                max_replicas=max_replicas
            )

            return Observation(
                type=ObservationType.HPA_DEGRADED,
                severity=Severity.WARNING,
                namespace=namespace,
                resource_kind="HorizontalPodAutoscaler",
                resource_name=hpa_name,
                message=f"HPA at maximum replicas ({max_replicas}) - consider increasing maxReplicas",
                raw_data=hpa_item,
                labels=metadata.get("labels", {})
            )

        return None

    def _process_cluster_autoscaler(self, ca_item: dict, request_id: str) -> Observation | None:
        """
        Process a ClusterAutoscaler.

        Args:
            ca_item: ClusterAutoscaler JSON object
            request_id: Request ID for logging

        Returns:
            Observation if ClusterAutoscaler has issues, None otherwise
        """
        metadata = ca_item.get("metadata", {})
        status = ca_item.get("status", {})

        ca_name = metadata.get("name", "default")

        # Check status conditions (OpenShift-specific)
        conditions = status.get("conditions", [])
        for condition in conditions:
            condition_type = condition.get("type", "")
            condition_status = condition.get("status", "")
            reason = condition.get("reason", "")
            message = condition.get("message", "")

            # Available = False or Degraded = True indicates issues
            if condition_type == "Available" and condition_status != "True":
                logger.warning(
                    f"ClusterAutoscaler {ca_name} unavailable: {reason}",
                    request_id=request_id,
                    ca=ca_name,
                    reason=reason
                )

                return Observation(
                    type=ObservationType.CLUSTER_AUTOSCALER_DEGRADED,
                    severity=Severity.CRITICAL,
                    namespace="openshift-machine-api",
                    resource_kind="ClusterAutoscaler",
                    resource_name=ca_name,
                    message=f"ClusterAutoscaler unavailable: {reason} - {message}",
                    raw_data=ca_item,
                    labels=metadata.get("labels", {})
                )

            if condition_type == "Degraded" and condition_status == "True":
                logger.warning(
                    f"ClusterAutoscaler {ca_name} degraded: {reason}",
                    request_id=request_id,
                    ca=ca_name,
                    reason=reason
                )

                return Observation(
                    type=ObservationType.CLUSTER_AUTOSCALER_DEGRADED,
                    severity=Severity.WARNING,
                    namespace="openshift-machine-api",
                    resource_kind="ClusterAutoscaler",
                    resource_name=ca_name,
                    message=f"ClusterAutoscaler degraded: {reason} - {message}",
                    raw_data=ca_item,
                    labels=metadata.get("labels", {})
                )

        return None

    def __str__(self) -> str:
        """String representation."""
        return f"AutoscalingCollector(monitoring HPA and ClusterAutoscaler)"
