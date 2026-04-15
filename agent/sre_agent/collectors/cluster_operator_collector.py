"""
ClusterOperator collector for monitoring OpenShift platform health.

Monitors ClusterOperator resources to detect degraded or unavailable operators.
"""

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class ClusterOperatorCollector(BaseCollector):
    """
    Collector for OpenShift ClusterOperators.

    Monitors platform operators and flags if:
    - Available != True
    - Degraded != False
    - Progressing takes too long (optional)
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize ClusterOperatorCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "cluster_operator_collector")

    async def collect(self) -> list[Observation]:
        """
        Collect ClusterOperator status.

        Returns:
            List of Observation objects for unhealthy operators

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting ClusterOperator collection",
                request_id=request_id,
                action_taken="collect_cluster_operators"
            )

            # Get ClusterOperators via MCP
            operators_json = await self._get_cluster_operators()

            if not operators_json:
                logger.warning(
                    "No ClusterOperator data returned from MCP",
                    request_id=request_id
                )
                return observations

            # Parse JSON
            try:
                operators_data = json.loads(operators_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse ClusterOperators JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = operators_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} ClusterOperators",
                request_id=request_id,
                operator_count=len(items)
            )

            # Process each operator
            for operator_item in items:
                try:
                    obs = self._process_operator(operator_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process ClusterOperator: {e}",
                        request_id=request_id,
                        operator_name=operator_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

            healthy_count = len(items) - len(observations)
            logger.info(
                f"ClusterOperator collection complete: {len(observations)} unhealthy, {healthy_count} healthy",
                request_id=request_id,
                unhealthy_count=len(observations),
                healthy_count=healthy_count
            )

        except Exception as e:
            logger.error(
                f"ClusterOperator collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            raise

        return observations

    async def _get_cluster_operators(self) -> str:
        """
        Get ClusterOperators from cluster via Kubernetes API.

        Returns:
            JSON string of ClusterOperators

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_cluster_operators():
                try:
                    # ClusterOperators are OpenShift custom resources
                    # API: config.openshift.io/v1, Kind: ClusterOperator
                    result = self.custom_api.list_cluster_custom_object(
                        group="config.openshift.io",
                        version="v1",
                        plural="clusteroperators"
                    )
                    return result
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing ClusterOperators: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            operators_dict = await asyncio.to_thread(_list_cluster_operators)

            # Return as JSON string
            return json.dumps(operators_dict)

        except Exception as e:
            logger.error(
                f"Failed to list ClusterOperators: {e}",
                exc_info=True
            )
            raise

    def _process_operator(self, operator_item: dict, request_id: str) -> Observation | None:
        """
        Process a ClusterOperator and create Observation if unhealthy.

        Args:
            operator_item: ClusterOperator data from API
            request_id: Request ID for logging

        Returns:
            Observation if operator is unhealthy, None otherwise
        """
        metadata = operator_item.get("metadata", {})
        operator_name = metadata.get("name", "unknown")
        status = operator_item.get("status", {})
        conditions = status.get("conditions", [])

        # Convert conditions list to dict for easier lookup
        condition_map = {
            cond.get("type"): cond
            for cond in conditions
        }

        # Check health status
        available = condition_map.get("Available", {})
        degraded = condition_map.get("Degraded", {})
        progressing = condition_map.get("Progressing", {})

        is_available = available.get("status") == "True"
        is_degraded = degraded.get("status") == "True"
        is_progressing = progressing.get("status") == "True"

        # Operator is healthy if Available=True and Degraded=False
        if is_available and not is_degraded:
            logger.debug(
                f"ClusterOperator {operator_name} is healthy",
                request_id=request_id,
                resource_name=operator_name
            )
            return None

        # Operator is unhealthy - determine severity and message
        issues = []
        severity = Severity.WARNING

        if not is_available:
            issues.append("Not Available")
            severity = Severity.CRITICAL
            available_reason = available.get("reason", "Unknown")
            available_message = available.get("message", "")
            if available_reason:
                issues.append(f"Reason: {available_reason}")

        if is_degraded:
            issues.append("Degraded")
            severity = Severity.CRITICAL
            degraded_reason = degraded.get("reason", "Unknown")
            degraded_message = degraded.get("message", "")
            if degraded_reason:
                issues.append(f"Reason: {degraded_reason}")

        if is_progressing:
            progressing_reason = progressing.get("reason", "Unknown")
            if progressing_reason not in ["AsExpected", "Reconciling"]:
                issues.append(f"Progressing: {progressing_reason}")

        message = f"ClusterOperator {operator_name} is unhealthy: {', '.join(issues)}"

        # Create observation
        observation = Observation(
            type=ObservationType.CLUSTER_OPERATOR_DEGRADED,
            severity=severity,
            resource_kind="ClusterOperator",
            resource_name=operator_name,
            message=message,
            raw_data={
                "operator_name": operator_name,
                "available": {
                    "status": available.get("status"),
                    "reason": available.get("reason"),
                    "message": available.get("message"),
                    "lastTransitionTime": available.get("lastTransitionTime"),
                },
                "degraded": {
                    "status": degraded.get("status"),
                    "reason": degraded.get("reason"),
                    "message": degraded.get("message"),
                    "lastTransitionTime": degraded.get("lastTransitionTime"),
                },
                "progressing": {
                    "status": progressing.get("status"),
                    "reason": progressing.get("reason"),
                    "message": progressing.get("message"),
                    "lastTransitionTime": progressing.get("lastTransitionTime"),
                },
                "versions": status.get("versions", []),
            },
            labels={
                "operator": operator_name,
                "available": str(is_available),
                "degraded": str(is_degraded),
            }
        )

        logger.info(
            f"Created observation for unhealthy ClusterOperator: {operator_name}",
            request_id=request_id,
            resource_kind="ClusterOperator",
            resource_name=operator_name,
            severity=severity.value
        )

        return observation
