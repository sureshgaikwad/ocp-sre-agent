"""
CrashLoop analyzer.

Analyzes CrashLoopBackOff failures and categorizes them into:
- OOMKilled (exit code 137)
- Liveness probe failure
- SCC (Security Context Constraints) issues
- Application errors
"""

import json
import asyncio
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.analyzers.base import BaseAnalyzer
from sre_agent.analyzers.evidence_builder import build_evidence
from sre_agent.models.observation import Observation, ObservationType
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.secret_scrubber import SecretScrubber
import litellm

logger = get_logger(__name__)


class CrashLoopAnalyzer(BaseAnalyzer):
    """
    Analyzer for CrashLoopBackOff failures.

    Categorizes crashes by analyzing:
    - Exit codes (137 = OOMKilled, 143 = SIGTERM, etc.)
    - Container state reasons
    - Pod events
    - Container logs
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize CrashLoop analyzer.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "crashloop_analyzer")

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        Args:
            observation: Observation to check

        Returns:
            True if observation is a pod failure with crash-related reason
        """
        if observation.type != ObservationType.POD_FAILURE:
            logger.debug(
                f"CrashLoopAnalyzer: Skipping - not POD_FAILURE type",
                observation_id=observation.id,
                observation_type=observation.type.value if hasattr(observation.type, 'value') else str(observation.type)
            )
            return False

        # Check if reason indicates crash
        reason = observation.labels.get("reason", "")
        crash_reasons = [
            "CrashLoopBackOff",
            "Error",
            "OOMKilled",
        ]

        can_handle = any(crash_reason in reason for crash_reason in crash_reasons)

        logger.info(
            f"CrashLoopAnalyzer: can_analyze={can_handle}",
            observation_id=observation.id,
            namespace=observation.namespace,
            resource_name=observation.resource_name,
            reason=reason,
            labels=observation.labels
        )

        return can_handle

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze CrashLoopBackOff and determine root cause.

        Args:
            observation: Pod failure observation

        Returns:
            Diagnosis with categorized root cause
        """
        if not self.can_analyze(observation):
            return None

        logger.info(
            f"Analyzing CrashLoopBackOff for {observation.namespace}/{observation.resource_name}",
            namespace=observation.namespace,
            resource_name=observation.resource_name,
            action_taken="analyze_crashloop"
        )

        # Extract data from observation
        exit_code = observation.raw_data.get("exit_code")
        reason = observation.raw_data.get("reason", "")
        restart_count = observation.raw_data.get("restart_count", 0)
        container_name = observation.raw_data.get("container_name")

        # Quick pattern matching first
        quick_diagnosis = self._quick_pattern_match(exit_code, reason, observation)
        if quick_diagnosis:
            return quick_diagnosis

        # Need deeper analysis - fetch logs and events
        try:
            # Get previous container logs (crashed container)
            logs = await self._get_previous_logs(
                observation.namespace,
                observation.resource_name,
                container_name
            )

            # Get pod events
            events = await self._get_pod_events(
                observation.namespace,
                observation.resource_name
            )

            # Analyze with LLM for complex cases
            diagnosis = await self._llm_analysis(
                observation, logs, events, exit_code, restart_count
            )

            return diagnosis

        except Exception as e:
            logger.error(
                f"CrashLoop analysis failed: {e}",
                namespace=observation.namespace,
                resource_name=observation.resource_name,
                exc_info=True
            )
            # Return generic diagnosis on error
            return self._create_generic_diagnosis(observation, exit_code, restart_count)

    def _quick_pattern_match(
        self,
        exit_code: Optional[int],
        reason: str,
        observation: Observation
    ) -> Optional[Diagnosis]:
        """
        Quick pattern matching without LLM.

        Args:
            exit_code: Container exit code
            reason: Failure reason
            observation: Observation

        Returns:
            Diagnosis if pattern matched, None otherwise
        """
        # OOMKilled - exit code 137 or "OOMKilled" in reason string
        if exit_code == 137 or "OOMKilled" in reason:
            memory_limit = observation.raw_data.get("container_status", {}).get(
                "resources", {}
            ).get("limits", {}).get("memory", "unknown")

            return Diagnosis(
                observation_id=observation.id,
                category=DiagnosisCategory.OOM_KILLED,
                root_cause=f"Container exceeded memory limit and was killed by OOM killer (exit code {exit_code})",
                confidence=Confidence.HIGH,
                recommended_actions=[
                    f"Increase memory limit (current: {memory_limit})",
                    "Analyze application for memory leaks",
                    "Add memory request for better scheduling",
                ],
                recommended_tier=1,  # Direct fix: increase memory limit
                evidence=build_evidence(
                    observation,
                    exit_code=exit_code,
                    reason=reason,
                    memory_limit=memory_limit,
                    pod_name=observation.resource_name,
                    container_name=observation.raw_data.get("container_name"),
                ),
                exit_code=exit_code,
                error_patterns=["OOMKilled", f"exit code {exit_code}"],
                analyzer_name=self.analyzer_name,
            )

        # Liveness probe failure
        if "Liveness probe failed" in reason or "liveness" in reason.lower():
            return Diagnosis(
                observation_id=observation.id,
                category=DiagnosisCategory.LIVENESS_PROBE_FAILURE,
                root_cause="Container failed liveness probe check",
                confidence=Confidence.HIGH,
                recommended_actions=[
                    "Increase liveness probe initialDelaySeconds",
                    "Increase liveness probe timeout",
                    "Check application health endpoint",
                ],
                recommended_tier=2,  # GitOps PR to adjust probe
                evidence=build_evidence(
                    observation,
                    exit_code=exit_code,
                    reason=reason,
                ),
                exit_code=exit_code,
                error_patterns=["Liveness probe failed"],
                analyzer_name=self.analyzer_name,
            )

        return None

    async def _get_previous_logs(
        self,
        namespace: str,
        pod_name: str,
        container_name: Optional[str]
    ) -> str:
        """
        Get logs from previous (crashed) container.

        Args:
            namespace: Namespace
            pod_name: Pod name
            container_name: Container name

        Returns:
            Log content (scrubbed)
        """
        try:
            # Use MCP pods_log tool
            arguments = {
                "namespace": namespace,
                "name": pod_name,
                "previous": True,
                "tailLines": 100,
            }
            if container_name:
                arguments["container"] = container_name

            logs = await self.mcp_registry.call_tool("pods_log", arguments)

            # CRITICAL: Scrub secrets before using logs
            scrubbed_logs = SecretScrubber.scrub(logs)

            return scrubbed_logs

        except Exception as e:
            logger.warning(
                f"Failed to fetch previous logs: {e}",
                namespace=namespace,
                pod_name=pod_name
            )
            return f"Error fetching logs: {str(e)}"

    async def _get_pod_events(
        self,
        namespace: str,
        pod_name: str
    ) -> str:
        """
        Get events related to pod.

        Args:
            namespace: Namespace
            pod_name: Pod name

        Returns:
            Events as string
        """
        try:
            command = f"oc get events -n {namespace} --field-selector involvedObject.name={pod_name} -o json"
            result = await self.mcp_registry.call_tool("exec", {
                "command": command
            })

            events_data = json.loads(result)
            items = events_data.get("items", [])

            # Format events
            event_messages = []
            for event in items[-10:]:  # Last 10 events
                reason = event.get("reason", "")
                message = event.get("message", "")
                event_messages.append(f"{reason}: {message}")

            scrubbed = SecretScrubber.scrub("\n".join(event_messages))
            return scrubbed

        except Exception as e:
            logger.warning(
                f"Failed to fetch pod events: {e}",
                namespace=namespace,
                pod_name=pod_name
            )
            return ""

    async def _llm_analysis(
        self,
        observation: Observation,
        logs: str,
        events: str,
        exit_code: Optional[int],
        restart_count: int
    ) -> Diagnosis:
        """
        Use LLM to analyze crash for complex cases.

        Args:
            observation: Observation
            logs: Container logs (scrubbed)
            events: Pod events (scrubbed)
            exit_code: Exit code
            restart_count: Restart count

        Returns:
            Diagnosis from LLM analysis
        """
        import os

        litellm_url = os.environ.get("LITELLM_URL", "")
        litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
        litellm_model = os.environ.get("LITELLM_MODEL", "openai/Llama-4-Scout-17B-16E-W4A16")

        prompt = f"""Analyze this CrashLoopBackOff failure and categorize the root cause.

Pod: {observation.namespace}/{observation.resource_name}
Exit Code: {exit_code}
Restart Count: {restart_count}

Container Logs (last 100 lines):
{logs[:2000]}

Pod Events:
{events[:1000]}

Categorize the root cause as ONE of:
1. OOMKilled - Out of memory (exit code 137)
2. Liveness probe failure - Probe check failed
3. SCC permission denied - Security Context Constraints issue
4. Application error - Application-level crash

Respond with JSON:
{{
  "category": "oom_killed|liveness_probe_failure|scc_permission_denied|application_error",
  "root_cause": "brief explanation",
  "confidence": "high|medium|low",
  "evidence": ["key evidence 1", "key evidence 2"],
  "recommended_actions": ["action 1", "action 2"]
}}
"""

        try:
            completion_kwargs = {
                "model": litellm_model,
                "messages": [{"role": "user", "content": prompt}],
                "api_key": litellm_api_key,
            }
            if litellm_url:
                completion_kwargs["api_base"] = litellm_url

            response = await asyncio.to_thread(
                litellm.completion,
                **completion_kwargs
            )

            content = response.choices[0].message.content
            analysis = json.loads(content)

            # Map category string to enum
            category_map = {
                "oom_killed": DiagnosisCategory.OOM_KILLED,
                "liveness_probe_failure": DiagnosisCategory.LIVENESS_PROBE_FAILURE,
                "scc_permission_denied": DiagnosisCategory.SCC_PERMISSION_DENIED,
                "application_error": DiagnosisCategory.APPLICATION_ERROR,
            }

            category = category_map.get(
                analysis.get("category", "application_error"),
                DiagnosisCategory.APPLICATION_ERROR
            )

            confidence_map = {
                "high": Confidence.HIGH,
                "medium": Confidence.MEDIUM,
                "low": Confidence.LOW,
            }
            confidence = confidence_map.get(
                analysis.get("confidence", "medium"),
                Confidence.MEDIUM
            )

            # Determine tier based on category
            tier = 3  # Default: notification
            if category == DiagnosisCategory.OOM_KILLED:
                tier = 2  # GitOps PR
            elif category == DiagnosisCategory.LIVENESS_PROBE_FAILURE:
                tier = 2  # GitOps PR
            elif category == DiagnosisCategory.SCC_PERMISSION_DENIED:
                tier = 2  # GitOps PR

            return Diagnosis(
                observation_id=observation.id,
                category=category,
                root_cause=analysis.get("root_cause", "Unknown crash"),
                confidence=confidence,
                recommended_actions=analysis.get("recommended_actions", []),
                recommended_tier=tier,
                evidence=build_evidence(
                    observation,
                    exit_code=exit_code,
                    restart_count=restart_count,
                    llm_evidence=analysis.get("evidence", []),
                    logs_analyzed=True,
                ),
                exit_code=exit_code,
                error_patterns=analysis.get("evidence", []),
                analyzer_name=self.analyzer_name,
            )

        except Exception as e:
            logger.error(
                f"LLM analysis failed: {e}",
                exc_info=True
            )
            return self._create_generic_diagnosis(observation, exit_code, restart_count)

    def _create_generic_diagnosis(
        self,
        observation: Observation,
        exit_code: Optional[int],
        restart_count: int
    ) -> Diagnosis:
        """
        Create generic diagnosis when pattern matching and LLM fail.

        Args:
            observation: Observation
            exit_code: Exit code
            restart_count: Restart count

        Returns:
            Generic diagnosis
        """
        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.APPLICATION_ERROR,
            root_cause=f"Container crashed with exit code {exit_code}. Requires manual investigation.",
            confidence=Confidence.LOW,
            recommended_actions=[
                "Check container logs for error details",
                "Verify container image and startup command",
                "Check resource limits and requests",
            ],
            recommended_tier=3,  # Notification
            evidence=build_evidence(
                observation,
                exit_code=exit_code,
                restart_count=restart_count,
            ),
            exit_code=exit_code,
            analyzer_name=self.analyzer_name,
        )
