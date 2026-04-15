"""
MachineConfigPool collector for monitoring node configuration updates.

Monitors MachineConfigPool resources to detect update issues or degradation.
"""

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class MachineConfigPoolCollector(BaseCollector):
    """
    Collector for OpenShift MachineConfigPools.

    Monitors node configuration pools and flags if:
    - Updated != True (pool has pending updates)
    - Degraded == True (pool is degraded)
    - UpdatedMachineCount < MachineCount (some nodes not updated)
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize MachineConfigPoolCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "machine_config_pool_collector")

    async def collect(self) -> list[Observation]:
        """
        Collect MachineConfigPool status.

        Returns:
            List of Observation objects for unhealthy pools

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting MachineConfigPool collection",
                request_id=request_id,
                action_taken="collect_machine_config_pools"
            )

            # Get MachineConfigPools via MCP
            pools_json = await self._get_machine_config_pools()

            if not pools_json:
                logger.warning(
                    "No MachineConfigPool data returned from MCP",
                    request_id=request_id
                )
                return observations

            # Parse JSON
            try:
                pools_data = json.loads(pools_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse MachineConfigPools JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = pools_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} MachineConfigPools",
                request_id=request_id,
                pool_count=len(items)
            )

            # Process each pool
            for pool_item in items:
                try:
                    obs = self._process_pool(pool_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process MachineConfigPool: {e}",
                        request_id=request_id,
                        pool_name=pool_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

            healthy_count = len(items) - len(observations)
            logger.info(
                f"MachineConfigPool collection complete: {len(observations)} unhealthy, {healthy_count} healthy",
                request_id=request_id,
                unhealthy_count=len(observations),
                healthy_count=healthy_count
            )

        except Exception as e:
            logger.error(
                f"MachineConfigPool collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            raise

        return observations

    async def _get_machine_config_pools(self) -> str:
        """
        Get MachineConfigPools from cluster via Kubernetes API.

        Returns:
            JSON string of MachineConfigPools

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_machine_config_pools():
                try:
                    # MachineConfigPools are OpenShift custom resources
                    result = self.custom_api.list_cluster_custom_object(
                        group="machineconfiguration.openshift.io",
                        version="v1",
                        plural="machineconfigpools"
                    )
                    return result
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing MachineConfigPools: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            mcp_dict = await asyncio.to_thread(_list_machine_config_pools)

            # Return as JSON string
            return json.dumps(mcp_dict)

        except Exception as e:
            logger.error(
                f"Failed to list MachineConfigPools: {e}",
                exc_info=True
            )
            raise

    def _process_pool(self, pool_item: dict, request_id: str) -> Observation | None:
        """
        Process a MachineConfigPool and create Observation if unhealthy.

        Args:
            pool_item: MachineConfigPool data from API
            request_id: Request ID for logging

        Returns:
            Observation if pool is unhealthy, None otherwise
        """
        metadata = pool_item.get("metadata", {})
        pool_name = metadata.get("name", "unknown")
        status = pool_item.get("status", {})

        # Get machine counts
        machine_count = status.get("machineCount", 0)
        ready_machine_count = status.get("readyMachineCount", 0)
        updated_machine_count = status.get("updatedMachineCount", 0)
        degraded_machine_count = status.get("degradedMachineCount", 0)
        unavailable_machine_count = status.get("unavailableMachineCount", 0)

        # Get conditions
        conditions = status.get("conditions", [])
        condition_map = {
            cond.get("type"): cond
            for cond in conditions
        }

        updated_cond = condition_map.get("Updated", {})
        updating_cond = condition_map.get("Updating", {})
        degraded_cond = condition_map.get("Degraded", {})

        is_updated = updated_cond.get("status") == "True"
        is_updating = updating_cond.get("status") == "True"
        is_degraded = degraded_cond.get("status") == "True"

        # Pool is healthy if Updated=True and Degraded=False
        if is_updated and not is_degraded and degraded_machine_count == 0:
            logger.debug(
                f"MachineConfigPool {pool_name} is healthy",
                request_id=request_id,
                resource_name=pool_name
            )
            return None

        # Pool is unhealthy - determine severity and message
        issues = []
        severity = Severity.WARNING

        if is_degraded or degraded_machine_count > 0:
            issues.append(f"Degraded ({degraded_machine_count} machines)")
            severity = Severity.CRITICAL
            degraded_reason = degraded_cond.get("reason", "Unknown")
            degraded_message = degraded_cond.get("message", "")
            if degraded_reason:
                issues.append(f"Reason: {degraded_reason}")

        if not is_updated:
            issues.append("Not fully updated")
            if updated_machine_count < machine_count:
                pending_count = machine_count - updated_machine_count
                issues.append(f"{pending_count}/{machine_count} machines pending update")

        if unavailable_machine_count > 0:
            issues.append(f"{unavailable_machine_count} machines unavailable")
            if unavailable_machine_count > machine_count * 0.3:  # >30% unavailable
                severity = Severity.CRITICAL

        if is_updating and not is_degraded:
            # Updating is normal, only flag if taking too long or degraded
            updating_reason = updating_cond.get("reason", "Unknown")
            if updating_reason not in ["AsExpected"]:
                issues.append(f"Update in progress: {updating_reason}")

        message = f"MachineConfigPool {pool_name} is unhealthy: {', '.join(issues)}"

        # Create observation
        observation = Observation(
            type=ObservationType.MACHINE_CONFIG_POOL_DEGRADED,
            severity=severity,
            resource_kind="MachineConfigPool",
            resource_name=pool_name,
            message=message,
            raw_data={
                "pool_name": pool_name,
                "machine_count": machine_count,
                "ready_machine_count": ready_machine_count,
                "updated_machine_count": updated_machine_count,
                "degraded_machine_count": degraded_machine_count,
                "unavailable_machine_count": unavailable_machine_count,
                "updated": {
                    "status": updated_cond.get("status"),
                    "reason": updated_cond.get("reason"),
                    "message": updated_cond.get("message"),
                    "lastTransitionTime": updated_cond.get("lastTransitionTime"),
                },
                "updating": {
                    "status": updating_cond.get("status"),
                    "reason": updating_cond.get("reason"),
                    "message": updating_cond.get("message"),
                    "lastTransitionTime": updating_cond.get("lastTransitionTime"),
                },
                "degraded": {
                    "status": degraded_cond.get("status"),
                    "reason": degraded_cond.get("reason"),
                    "message": degraded_cond.get("message"),
                    "lastTransitionTime": degraded_cond.get("lastTransitionTime"),
                },
                "configuration": status.get("configuration", {}),
            },
            labels={
                "pool": pool_name,
                "updated": str(is_updated),
                "degraded": str(is_degraded),
            }
        )

        logger.info(
            f"Created observation for unhealthy MachineConfigPool: {pool_name}",
            request_id=request_id,
            resource_kind="MachineConfigPool",
            resource_name=pool_name,
            severity=severity.value
        )

        return observation
