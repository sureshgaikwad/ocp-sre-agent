"""
Pod collector for monitoring failing pods.

Monitors pods in problematic states like CrashLoopBackOff, ImagePullBackOff, etc.
"""

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class PodCollector(BaseCollector):
    """
    Collector for failing Kubernetes/OpenShift pods.

    Monitors pods across all namespaces and flags:
    - CrashLoopBackOff
    - ImagePullBackOff / ErrImagePull
    - Pending (with certain reasons)
    - Error / Failed
    - OOMKilled (via containerStatuses)
    """

    # States we care about
    PROBLEMATIC_STATES = {
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "Error",
        "Failed",
        "CreateContainerConfigError",
        "InvalidImageName",
    }

    def __init__(self, mcp_registry: "MCPToolRegistry", namespaces: list[str] = None):
        """
        Initialize PodCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
            namespaces: List of namespaces to monitor (None = all namespaces)
        """
        super().__init__(mcp_registry, "pod_collector")
        self.namespaces = namespaces  # None means all namespaces

    async def collect(self) -> list[Observation]:
        """
        Collect failing pods.

        Returns:
            List of Observation objects for failing pods

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting pod collection",
                request_id=request_id,
                action_taken="collect_pods",
                namespaces=self.namespaces or "all"
            )

            # Get pods via MCP
            pods_json = await self._get_pods()

            if not pods_json:
                logger.warning(
                    "No pod data returned from MCP",
                    request_id=request_id
                )
                return observations

            # Parse JSON
            try:
                pods_data = json.loads(pods_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse pods JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = pods_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} pods",
                request_id=request_id,
                pod_count=len(items)
            )

            # Process each pod
            for pod_item in items:
                try:
                    obs = self._process_pod(pod_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process pod: {e}",
                        request_id=request_id,
                        pod_name=pod_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

            healthy_count = len(items) - len(observations)
            logger.info(
                f"Pod collection complete: {len(observations)} failing, {healthy_count} healthy",
                request_id=request_id,
                failing_count=len(observations),
                healthy_count=healthy_count
            )

        except Exception as e:
            logger.error(
                f"Pod collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            raise

        return observations

    async def _get_pods(self) -> str:
        """
        Get pods from cluster via Kubernetes API.

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
                    if self.namespaces:
                        # List pods in specific namespaces
                        all_pods = []
                        for ns in self.namespaces:
                            pod_list = self.core_api.list_namespaced_pod(namespace=ns)
                            all_pods.extend(pod_list.items)
                        # Create a list object compatible with K8s response
                        result = {"items": all_pods}
                    else:
                        # List all pods across all namespaces
                        pod_list = self.core_api.list_pod_for_all_namespaces()
                        result = self.core_api.api_client.sanitize_for_serialization(pod_list)
                    return result
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing pods: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            pods_dict = await asyncio.to_thread(_list_pods)

            # Return as JSON string
            return json.dumps(pods_dict)

        except Exception as e:
            logger.error(
                f"Failed to list pods: {e}",
                exc_info=True
            )
            raise

    def _process_pod(self, pod_item: dict, request_id: str) -> Observation | None:
        """
        Process a pod and create Observation if failing.

        Args:
            pod_item: Pod data from API
            request_id: Request ID for logging

        Returns:
            Observation if pod is failing, None otherwise
        """
        metadata = pod_item.get("metadata", {})
        pod_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "unknown")
        status = pod_item.get("status", {})
        spec = pod_item.get("spec", {})

        phase = status.get("phase")
        container_statuses = status.get("containerStatuses", [])
        conditions = status.get("conditions", [])

        # Check for problematic container states
        for container_status in container_statuses:
            container_name = container_status.get("name")
            waiting = container_status.get("state", {}).get("waiting")
            terminated = container_status.get("state", {}).get("terminated")
            last_state = container_status.get("lastState", {})
            restart_count = container_status.get("restartCount", 0)

            # Check waiting state
            if waiting:
                reason = waiting.get("reason", "Unknown")
                message = waiting.get("message", "")

                # For CrashLoopBackOff, check if lastState has more specific info (e.g., OOMKilled)
                if reason == "CrashLoopBackOff" and restart_count > 3:
                    last_terminated = last_state.get("terminated")
                    if last_terminated:
                        last_reason = last_terminated.get("reason", "Unknown")
                        last_exit_code = last_terminated.get("exitCode", 0)
                        if last_reason in ["OOMKilled", "Error"]:
                            # Use lastState information for more specific diagnosis
                            return self._create_pod_observation(
                                pod_name=pod_name,
                                namespace=namespace,
                                container_name=container_name,
                                reason=f"CrashLoopBackOff ({last_reason})",
                                message=f"Container restarted {restart_count} times, last: {last_reason} (exit {last_exit_code})",
                                restart_count=restart_count,
                                phase=phase,
                                raw_status=container_status,
                                spec=spec,
                                request_id=request_id,
                                exit_code=last_exit_code
                            )

                # Generic waiting state handling
                if reason in self.PROBLEMATIC_STATES:
                    return self._create_pod_observation(
                        pod_name=pod_name,
                        namespace=namespace,
                        container_name=container_name,
                        reason=reason,
                        message=message,
                        restart_count=restart_count,
                        phase=phase,
                        raw_status=container_status,
                        spec=spec,
                        request_id=request_id
                    )

            # Check terminated state (especially OOMKilled)
            if terminated:
                reason = terminated.get("reason", "Unknown")
                exit_code = terminated.get("exitCode", 0)

                # OOMKilled or error exits
                if reason == "OOMKilled" or (reason == "Error" and exit_code != 0):
                    return self._create_pod_observation(
                        pod_name=pod_name,
                        namespace=namespace,
                        container_name=container_name,
                        reason=reason,
                        message=f"Container terminated: {reason} (exit code {exit_code})",
                        restart_count=restart_count,
                        phase=phase,
                        raw_status=container_status,
                        spec=spec,
                        request_id=request_id,
                        exit_code=exit_code
                    )

            # Check last state for recent crashes
            last_terminated = last_state.get("terminated")
            if last_terminated and restart_count > 3:
                last_reason = last_terminated.get("reason", "Unknown")
                last_exit_code = last_terminated.get("exitCode", 0)
                if last_reason in ["OOMKilled", "Error"]:
                    return self._create_pod_observation(
                        pod_name=pod_name,
                        namespace=namespace,
                        container_name=container_name,
                        reason=f"CrashLoopBackOff ({last_reason})",
                        message=f"Container restarted {restart_count} times, last: {last_reason} (exit {last_exit_code})",
                        restart_count=restart_count,
                        phase=phase,
                        raw_status=container_status,
                        spec=spec,
                        request_id=request_id,
                        exit_code=last_exit_code
                    )

        # Check pod phase for Failed/Error
        if phase in ["Failed", "Unknown"]:
            reason = status.get("reason", phase)
            message = status.get("message", f"Pod in {phase} state")
            return self._create_pod_observation(
                pod_name=pod_name,
                namespace=namespace,
                container_name=None,
                reason=reason,
                message=message,
                restart_count=0,
                phase=phase,
                raw_status=status,
                spec=spec,
                request_id=request_id
            )

        # Pod is healthy
        return None

    def _create_pod_observation(
        self,
        pod_name: str,
        namespace: str,
        container_name: str | None,
        reason: str,
        message: str,
        restart_count: int,
        phase: str,
        raw_status: dict,
        spec: dict,
        request_id: str,
        exit_code: int | None = None
    ) -> Observation:
        """
        Create an Observation for a failing pod.

        Args:
            pod_name: Pod name
            namespace: Namespace
            container_name: Container name (if specific container failed)
            reason: Failure reason
            message: Detailed message
            restart_count: Number of restarts
            phase: Pod phase
            raw_status: Raw container/pod status
            spec: Pod spec
            request_id: Request ID
            exit_code: Exit code if terminated

        Returns:
            Observation object
        """
        # Determine severity
        severity = self._determine_severity(reason, restart_count)

        # Build full message
        full_message = f"Pod {pod_name}"
        if container_name:
            full_message += f" (container: {container_name})"
        full_message += f" - {reason}: {message}"
        if restart_count > 0:
            full_message += f" (restarted {restart_count} times)"

        # Create observation
        observation = Observation(
            type=ObservationType.POD_FAILURE,
            severity=severity,
            namespace=namespace,
            resource_kind="Pod",
            resource_name=pod_name,
            message=full_message,
            raw_data={
                "pod_name": pod_name,
                "container_name": container_name,
                "reason": reason,
                "phase": phase,
                "restart_count": restart_count,
                "exit_code": exit_code,
                "container_status": raw_status,
                "node_name": spec.get("nodeName"),
                "service_account": spec.get("serviceAccountName"),
                "priority_class": spec.get("priorityClassName"),
            },
            labels={
                "reason": reason,
                "phase": phase,
                "container": container_name or "pod-level",
            }
        )

        logger.info(
            f"Created observation for failing pod: {namespace}/{pod_name}",
            request_id=request_id,
            namespace=namespace,
            resource_kind="Pod",
            resource_name=pod_name,
            reason=reason,
            severity=severity.value
        )

        return observation

    def _determine_severity(self, reason: str, restart_count: int) -> Severity:
        """
        Determine severity based on failure reason and restart count.

        Args:
            reason: Failure reason
            restart_count: Number of restarts

        Returns:
            Severity level
        """
        # Critical reasons
        if reason in ["OOMKilled", "Error"] or restart_count > 10:
            return Severity.CRITICAL

        # Warning for common transient issues
        if reason in ["ImagePullBackOff", "ErrImagePull"] and restart_count < 3:
            return Severity.WARNING

        # Critical for persistent issues
        if restart_count > 5:
            return Severity.CRITICAL

        return Severity.WARNING
