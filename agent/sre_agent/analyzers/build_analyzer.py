"""
Build analyzer for diagnosing Tekton Pipeline and Build failures.

Analyzes build failures including:
- Test failures
- Compilation errors
- Resource limits
- Timeouts
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
from sre_agent.utils.secret_scrubber import SecretScrubber

logger = get_logger(__name__)


class BuildAnalyzer(BaseAnalyzer):
    """
    Analyzer for Tekton Pipeline and Build failures.

    Diagnoses build issues by analyzing:
    1. PipelineRun/TaskRun logs
    2. Failure reasons and messages
    3. Exit codes and container status
    4. Resource limits and timeouts
    """

    # Regex patterns for categorizing build failures
    TEST_FAILURE_PATTERNS = [
        r"test.*failed",
        r"assertion.*failed",
        r"\d+ failing",
        r"FAIL:",
        r"Error: Test",
        r"jest.*failed",
        r"pytest.*failed",
        r"go test.*FAIL",
    ]

    COMPILATION_ERROR_PATTERNS = [
        r"compilation.*error",
        r"syntax error",
        r"cannot find symbol",
        r"undefined reference",
        r"error: expected",
        r"fatal error",
        r"build.*failed",
        r"npm ERR!",
        r"maven.*BUILD FAILURE",
    ]

    RESOURCE_LIMIT_PATTERNS = [
        r"OOMKilled",
        r"exit code 137",
        r"memory.*limit",
        r"disk.*full",
        r"no space left",
    ]

    TIMEOUT_PATTERNS = [
        r"timeout",
        r"timed out",
        r"exceeded.*deadline",
        r"context deadline exceeded",
    ]

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize BuildAnalyzer.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "build_analyzer")

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        Args:
            observation: Observation to check

        Returns:
            True if observation is a pipeline/build failure
        """
        return observation.type in [
            ObservationType.PIPELINE_FAILURE,
            ObservationType.TASK_RUN_FAILURE,
            ObservationType.BUILD_FAILURE
        ]

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze a build/pipeline failure observation.

        Args:
            observation: Build failure observation to analyze

        Returns:
            Diagnosis with root cause analysis
        """
        request_id = logger.set_request_id()

        logger.info(
            f"Analyzing build observation: {observation.resource_name}",
            request_id=request_id,
            observation_id=observation.id,
            resource=observation.resource_name,
            namespace=observation.namespace,
            type=observation.type.value
        )

        try:
            # Extract failure details from observation
            raw_data = observation.raw_data
            status = raw_data.get("status", {})
            conditions = status.get("conditions", [])

            # Get failure reason and message
            failure_reason = ""
            failure_message = ""

            for condition in conditions:
                if condition.get("type") == "Succeeded" and condition.get("status") == "False":
                    failure_reason = condition.get("reason", "Unknown")
                    failure_message = condition.get("message", "")
                    break

            # Try to get logs for deeper analysis
            logs = await self._get_build_logs(observation, request_id)

            # Scrub secrets from logs
            if logs:
                logs = SecretScrubber.scrub(logs)

            # Analyze failure based on reason, message, and logs
            diagnosis = await self._categorize_failure(
                observation=observation,
                failure_reason=failure_reason,
                failure_message=failure_message,
                logs=logs,
                request_id=request_id
            )

            return diagnosis

        except Exception as e:
            logger.error(
                f"Failed to analyze build observation: {e}",
                request_id=request_id,
                observation_id=observation.id,
                exc_info=True
            )
            return None

    async def _get_build_logs(self, observation: Observation, request_id: str) -> Optional[str]:
        """
        Get logs for PipelineRun/TaskRun.

        Args:
            observation: Build observation
            request_id: Request ID for logging

        Returns:
            Logs as string, or None if unable to fetch
        """
        try:
            resource_type = observation.resource_kind
            resource_name = observation.resource_name
            namespace = observation.namespace

            if resource_type == "PipelineRun":
                logs = await self._get_pipelinerun_logs(namespace, resource_name)
            elif resource_type == "TaskRun":
                logs = await self._get_taskrun_logs(namespace, resource_name)
            else:
                logger.warning(
                    f"Unknown build resource type: {resource_type}",
                    request_id=request_id,
                    resource_type=resource_type
                )
                return None

            logger.info(
                f"Retrieved logs for {resource_type} {resource_name}",
                request_id=request_id,
                resource_type=resource_type,
                resource_name=resource_name,
                log_length=len(logs) if logs else 0
            )

            return logs

        except NotImplementedError as e:
            logger.warning(
                f"Build logs retrieval not implemented: {e}",
                request_id=request_id
            )
            return None
        except Exception as e:
            logger.error(
                f"Failed to get build logs: {e}",
                request_id=request_id,
                exc_info=True
            )
            return None

    async def _categorize_failure(
        self,
        observation: Observation,
        failure_reason: str,
        failure_message: str,
        logs: Optional[str],
        request_id: str
    ) -> Diagnosis:
        """
        Categorize build failure based on reason, message, and logs.

        Args:
            observation: Build observation
            failure_reason: Failure reason from status
            failure_message: Failure message from status
            logs: Build logs (optional)
            request_id: Request ID for logging

        Returns:
            Diagnosis with categorized failure
        """
        combined_text = f"{failure_reason} {failure_message} {logs or ''}"
        combined_text_lower = combined_text.lower()

        # Check for resource limits (Tier 2 - can fix with config)
        for pattern in self.RESOURCE_LIMIT_PATTERNS:
            if re.search(pattern, combined_text_lower, re.IGNORECASE):
                logger.info(
                    f"Build failure categorized as resource limit",
                    request_id=request_id,
                    pattern=pattern
                )
                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.BUILD_RESOURCE_LIMIT,
                    root_cause=f"Build failed due to resource limits: {failure_reason}",
                    confidence=Confidence.HIGH,
                    tier=2,
                    recommended_actions=[
                        "Increase memory limits for build containers",
                        "Increase CPU requests/limits",
                        "Add more disk space for build workspace"
                    ],
                    evidence={
                        "failure_reason": failure_reason,
                        "failure_message": failure_message,
                        "logs_snippet": logs[:500] if logs else None
                    }
                )

        # Check for timeouts (Tier 2 - can fix with config)
        for pattern in self.TIMEOUT_PATTERNS:
            if re.search(pattern, combined_text_lower, re.IGNORECASE):
                logger.info(
                    f"Build failure categorized as timeout",
                    request_id=request_id,
                    pattern=pattern
                )
                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.BUILD_TIMEOUT,
                    root_cause=f"Build timed out: {failure_reason}",
                    confidence=Confidence.HIGH,
                    tier=2,
                    recommended_actions=[
                        "Increase pipeline timeout value",
                        "Optimize build steps to reduce execution time",
                        "Check for hanging processes in build"
                    ],
                    evidence={
                        "failure_reason": failure_reason,
                        "failure_message": failure_message
                    }
                )

        # Check for test failures (Tier 3 - code issue)
        for pattern in self.TEST_FAILURE_PATTERNS:
            if re.search(pattern, combined_text_lower, re.IGNORECASE):
                logger.info(
                    f"Build failure categorized as test failure",
                    request_id=request_id,
                    pattern=pattern
                )
                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.BUILD_TEST_FAILURE,
                    root_cause=f"Build failed due to test failures",
                    confidence=Confidence.HIGH,
                    tier=3,
                    recommended_actions=[
                        "Review test failure logs",
                        "Fix failing test cases",
                        "Check for environment-specific test issues"
                    ],
                    evidence={
                        "failure_reason": failure_reason,
                        "failure_message": failure_message,
                        "logs_snippet": logs[:1000] if logs else None
                    }
                )

        # Check for compilation errors (Tier 3 - code issue)
        for pattern in self.COMPILATION_ERROR_PATTERNS:
            if re.search(pattern, combined_text_lower, re.IGNORECASE):
                logger.info(
                    f"Build failure categorized as compilation error",
                    request_id=request_id,
                    pattern=pattern
                )
                return self._create_diagnosis(
                    observation=observation,
                    category=DiagnosisCategory.BUILD_COMPILATION_ERROR,
                    root_cause=f"Build failed due to compilation errors",
                    confidence=Confidence.HIGH,
                    tier=3,
                    recommended_actions=[
                        "Review compilation error logs",
                        "Fix syntax or dependency errors",
                        "Check for missing dependencies"
                    ],
                    evidence={
                        "failure_reason": failure_reason,
                        "failure_message": failure_message,
                        "logs_snippet": logs[:1000] if logs else None
                    }
                )

        # Unknown build failure (Tier 3 - needs manual review)
        logger.info(
            f"Build failure could not be categorized",
            request_id=request_id,
            failure_reason=failure_reason
        )
        return self._create_diagnosis(
            observation=observation,
            category=DiagnosisCategory.UNKNOWN,
            root_cause=f"Build failed: {failure_reason} - {failure_message}",
            confidence=Confidence.LOW,
            tier=3,
            recommended_actions=[
                "Review build logs for errors",
                "Check build configuration",
                "Verify dependencies and build environment"
            ],
            evidence={
                "failure_reason": failure_reason,
                "failure_message": failure_message,
                "logs_snippet": logs[:1000] if logs else None
            }
        )

    async def _get_pipelinerun_logs(self, namespace: str, pipelinerun_name: str) -> str:
        """
        Get logs for a PipelineRun.

        Args:
            namespace: Namespace
            pipelinerun_name: PipelineRun name

        Returns:
            Logs as string

        Raises:
            NotImplementedError: Until MCP tool name is configured
        """
        # TODO: Configure actual MCP tool name
        # Options:
        # 1. Use tkn CLI: tkn pipelinerun logs <name> -n <namespace>
        # 2. Use oc logs on the pod created by the PipelineRun

        raise NotImplementedError(
            f"BuildAnalyzer._get_pipelinerun_logs(): Configure MCP tool name for "
            f"'tkn pipelinerun logs {pipelinerun_name} -n {namespace}'"
        )

    async def _get_taskrun_logs(self, namespace: str, taskrun_name: str) -> str:
        """
        Get logs for a TaskRun.

        Args:
            namespace: Namespace
            taskrun_name: TaskRun name

        Returns:
            Logs as string

        Raises:
            NotImplementedError: Until MCP tool name is configured
        """
        # TODO: Configure actual MCP tool name
        raise NotImplementedError(
            f"BuildAnalyzer._get_taskrun_logs(): Configure MCP tool name for "
            f"'tkn taskrun logs {taskrun_name} -n {namespace}'"
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
