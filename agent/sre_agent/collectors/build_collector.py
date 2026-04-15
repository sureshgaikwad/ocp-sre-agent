"""
Build collector for monitoring Tekton Pipelines and OpenShift Builds.

Monitors PipelineRuns, TaskRuns, and BuildConfigs for failures.
"""

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class BuildCollector(BaseCollector):
    """
    Collector for Tekton Pipelines and OpenShift Builds.

    Monitors:
    - PipelineRuns in Failed state
    - TaskRuns in Failed state
    - Build/BuildConfigs that failed
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize BuildCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "build_collector")
        self._seen_pipelineruns: set[str] = set()  # Track UIDs to deduplicate

    async def collect(self) -> list[Observation]:
        """
        Collect build/pipeline observations from all namespaces.

        Returns:
            List of Observation objects for failed builds/pipelines

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting build collection",
                request_id=request_id,
                action_taken="collect_builds"
            )

            # Collect failed PipelineRuns
            pipeline_obs = await self._collect_failed_pipelineruns(request_id)
            observations.extend(pipeline_obs)

            # Collect failed TaskRuns
            taskrun_obs = await self._collect_failed_taskruns(request_id)
            observations.extend(taskrun_obs)

            logger.info(
                f"Build collection completed: {len(observations)} issues found",
                request_id=request_id,
                observation_count=len(observations)
            )

        except Exception as e:
            logger.error(
                f"Build collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            # Don't re-raise - allow other collectors to run

        return observations

    async def _collect_failed_pipelineruns(self, request_id: str) -> list[Observation]:
        """
        Collect failed PipelineRuns.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for failed PipelineRuns
        """
        observations = []

        try:
            # Get all PipelineRuns
            pipelineruns_json = await self._get_pipelineruns()

            if not pipelineruns_json:
                logger.debug(
                    "No PipelineRuns data returned",
                    request_id=request_id
                )
                return observations

            # Parse PipelineRuns
            try:
                pipelineruns_data = json.loads(pipelineruns_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse PipelineRuns JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = pipelineruns_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} PipelineRuns",
                request_id=request_id,
                pipelinerun_count=len(items)
            )

            # Process each PipelineRun
            for pr_item in items:
                try:
                    obs = self._process_pipelinerun(pr_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process PipelineRun: {e}",
                        request_id=request_id,
                        pipelinerun=pr_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

        except Exception as e:
            logger.error(
                f"Failed to collect PipelineRuns: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _collect_failed_taskruns(self, request_id: str) -> list[Observation]:
        """
        Collect failed TaskRuns.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for failed TaskRuns
        """
        observations = []

        try:
            # Get all TaskRuns
            taskruns_json = await self._get_taskruns()

            if not taskruns_json:
                logger.debug(
                    "No TaskRuns data returned",
                    request_id=request_id
                )
                return observations

            # Parse TaskRuns
            try:
                taskruns_data = json.loads(taskruns_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse TaskRuns JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = taskruns_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} TaskRuns",
                request_id=request_id,
                taskrun_count=len(items)
            )

            # Process each TaskRun
            for tr_item in items:
                try:
                    obs = self._process_taskrun(tr_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process TaskRun: {e}",
                        request_id=request_id,
                        taskrun=tr_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

        except Exception as e:
            logger.error(
                f"Failed to collect TaskRuns: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _get_pipelineruns(self) -> str:
        """
        Get all PipelineRuns via Kubernetes API.

        Returns:
            JSON string of PipelineRuns

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_pipelineruns():
                try:
                    # PipelineRuns are Tekton custom resources
                    result = self.custom_api.list_cluster_custom_object(
                        group="tekton.dev",
                        version="v1",
                        plural="pipelineruns"
                    )
                    return result
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing PipelineRuns: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            pr_dict = await asyncio.to_thread(_list_pipelineruns)

            # Return as JSON string
            return json.dumps(pr_dict)

        except Exception as e:
            logger.error(
                f"Failed to list PipelineRuns: {e}",
                exc_info=True
            )
            raise

    async def _get_taskruns(self) -> str:
        """
        Get all TaskRuns via Kubernetes API.

        Returns:
            JSON string of TaskRuns

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_taskruns():
                try:
                    # TaskRuns are Tekton custom resources
                    result = self.custom_api.list_cluster_custom_object(
                        group="tekton.dev",
                        version="v1",
                        plural="taskruns"
                    )
                    return result
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing TaskRuns: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            tr_dict = await asyncio.to_thread(_list_taskruns)

            # Return as JSON string
            return json.dumps(tr_dict)

        except Exception as e:
            logger.error(
                f"Failed to list TaskRuns: {e}",
                exc_info=True
            )
            raise

    def _process_pipelinerun(self, pr_item: dict, request_id: str) -> Observation | None:
        """
        Process a single PipelineRun.

        Args:
            pr_item: PipelineRun JSON object
            request_id: Request ID for logging

        Returns:
            Observation if PipelineRun failed, None otherwise
        """
        metadata = pr_item.get("metadata", {})
        status = pr_item.get("status", {})

        pr_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "default")
        uid = metadata.get("uid", "")

        # Check if already seen
        if uid in self._seen_pipelineruns:
            return None

        # Check status
        conditions = status.get("conditions", [])
        for condition in conditions:
            if condition.get("type") == "Succeeded":
                if condition.get("status") == "False":
                    # PipelineRun failed
                    reason = condition.get("reason", "Unknown")
                    message = condition.get("message", "")

                    self._seen_pipelineruns.add(uid)

                    logger.warning(
                        f"PipelineRun {namespace}/{pr_name} failed: {reason}",
                        request_id=request_id,
                        pipelinerun=pr_name,
                        namespace=namespace,
                        reason=reason
                    )

                    return Observation(
                        type=ObservationType.PIPELINE_FAILURE,
                        severity=Severity.CRITICAL,
                        namespace=namespace,
                        resource_kind="PipelineRun",
                        resource_name=pr_name,
                        message=f"PipelineRun failed: {reason} - {message}",
                        raw_data=pr_item,
                        labels=metadata.get("labels", {})
                    )

        return None

    def _process_taskrun(self, tr_item: dict, request_id: str) -> Observation | None:
        """
        Process a single TaskRun.

        Args:
            tr_item: TaskRun JSON object
            request_id: Request ID for logging

        Returns:
            Observation if TaskRun failed independently (not part of PipelineRun), None otherwise
        """
        metadata = tr_item.get("metadata", {})
        status = tr_item.get("status", {})

        tr_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "default")
        labels = metadata.get("labels", {})

        # Skip TaskRuns that are part of a PipelineRun (we'll handle at pipeline level)
        if "tekton.dev/pipelineRun" in labels:
            return None

        # Check status
        conditions = status.get("conditions", [])
        for condition in conditions:
            if condition.get("type") == "Succeeded":
                if condition.get("status") == "False":
                    # TaskRun failed
                    reason = condition.get("reason", "Unknown")
                    message = condition.get("message", "")

                    logger.warning(
                        f"TaskRun {namespace}/{tr_name} failed: {reason}",
                        request_id=request_id,
                        taskrun=tr_name,
                        namespace=namespace,
                        reason=reason
                    )

                    return Observation(
                        type=ObservationType.TASK_RUN_FAILURE,
                        severity=Severity.WARNING,
                        namespace=namespace,
                        resource_kind="TaskRun",
                        resource_name=tr_name,
                        message=f"TaskRun failed: {reason} - {message}",
                        raw_data=tr_item,
                        labels=labels
                    )

        return None

    def __str__(self) -> str:
        """String representation."""
        return f"BuildCollector(monitoring PipelineRuns and TaskRuns)"
