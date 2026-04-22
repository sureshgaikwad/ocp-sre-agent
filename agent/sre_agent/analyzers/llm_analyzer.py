"""
LLM analyzer (generic fallback).

Uses LiteLLM to analyze complex failures that don't match specific patterns.
This is the fallback analyzer when specialized analyzers don't match.
"""

import json
import asyncio
import os
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


class LLMAnalyzer(BaseAnalyzer):
    """
    Generic LLM-based analyzer.

    Uses LiteLLM to analyze observations that don't match specific patterns.
    This analyzer can handle any observation type but with lower confidence.
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize LLM analyzer.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "llm_analyzer")

        self.litellm_url = os.environ.get("LITELLM_URL", "")
        self.litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
        self.litellm_model = os.environ.get("LITELLM_MODEL", "openai/Llama-4-Scout-17B-16E-W4A16")

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        LLM analyzer can analyze any observation as a fallback.

        Args:
            observation: Observation to check

        Returns:
            Always True (fallback analyzer)
        """
        # LLM analyzer can handle any observation type
        # It should be registered LAST so specific analyzers run first
        return True

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze observation using LLM.

        Args:
            observation: Observation to analyze

        Returns:
            Diagnosis from LLM analysis
        """
        logger.info(
            f"LLM analyzing {observation.type.value} for {observation.namespace}/{observation.resource_name}",
            namespace=observation.namespace,
            resource_name=observation.resource_name,
            observation_type=observation.type.value,
            action_taken="analyze_with_llm"
        )

        try:
            # Fetch additional context if needed
            context = await self._gather_context(observation)

            # Analyze with LLM
            diagnosis = await self._llm_analysis(observation, context)

            return diagnosis

        except Exception as e:
            logger.error(
                f"LLM analysis failed: {e}",
                namespace=observation.namespace,
                resource_name=observation.resource_name,
                exc_info=True
            )
            # Return None to allow other analyzers to try
            return None

    async def _gather_context(self, observation: Observation) -> dict:
        """
        Gather additional context for analysis.

        Args:
            observation: Observation

        Returns:
            Dict with context data (logs, events, etc.)
        """
        context = {
            "logs": "",
            "events": "",
            "describe": "",
        }

        # For pod failures, get logs and events
        if observation.type == ObservationType.POD_FAILURE:
            try:
                # Get pod logs
                logs = await self._get_pod_logs(
                    observation.namespace,
                    observation.resource_name,
                    observation.raw_data.get("container_name")
                )
                context["logs"] = logs[:2000]  # Limit to 2000 chars

                # Get pod events
                events = await self._get_pod_events(
                    observation.namespace,
                    observation.resource_name
                )
                context["events"] = events[:1000]  # Limit to 1000 chars

            except Exception as e:
                logger.warning(f"Failed to gather context: {e}")

        return context

    async def _get_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        container_name: Optional[str]
    ) -> str:
        """Get pod logs via MCP."""
        try:
            arguments = {
                "namespace": namespace,
                "name": pod_name,
                "tailLines": 50,
            }
            if container_name:
                arguments["container"] = container_name

            logs = await self.mcp_registry.call_tool("pods_log", arguments)
            return SecretScrubber.scrub(logs)
        except Exception as e:
            logger.debug(f"Failed to fetch logs: {e}")
            return ""

    async def _get_pod_events(self, namespace: str, pod_name: str) -> str:
        """Get pod events via MCP."""
        try:
            command = f"oc get events -n {namespace} --field-selector involvedObject.name={pod_name} --sort-by='.lastTimestamp' -o json"
            result = await self.mcp_registry.call_tool("exec", {
                "command": command
            })

            events_data = json.loads(result)
            items = events_data.get("items", [])

            event_messages = []
            for event in items[-5:]:  # Last 5 events
                reason = event.get("reason", "")
                message = event.get("message", "")
                event_messages.append(f"{reason}: {message}")

            return SecretScrubber.scrub("\n".join(event_messages))
        except Exception as e:
            logger.debug(f"Failed to fetch events: {e}")
            return ""

    async def _llm_analysis(
        self,
        observation: Observation,
        context: dict
    ) -> Optional[Diagnosis]:
        """
        Analyze observation with LLM.

        Args:
            observation: Observation
            context: Additional context (logs, events)

        Returns:
            Diagnosis or None
        """
        # Build prompt
        prompt = self._build_prompt(observation, context)

        try:
            completion_kwargs = {
                "model": self.litellm_model,
                "messages": [{"role": "user", "content": prompt}],
                "api_key": self.litellm_api_key,
            }
            if self.litellm_url:
                completion_kwargs["api_base"] = self.litellm_url

            response = await asyncio.to_thread(
                litellm.completion,
                **completion_kwargs
            )

            content = response.choices[0].message.content

            # Parse response
            diagnosis = self._parse_llm_response(content, observation)

            return diagnosis

        except Exception as e:
            logger.error(f"LLM call failed: {e}", exc_info=True)
            return None

    def _build_prompt(self, observation: Observation, context: dict) -> str:
        """Build analysis prompt for LLM."""
        prompt = f"""You are an expert OpenShift/Kubernetes SRE. Analyze this issue and provide a diagnosis.

Observation Type: {observation.type.value}
Severity: {observation.severity.value}
Resource: {observation.resource_kind}/{observation.resource_name}
Namespace: {observation.namespace}
Message: {observation.message}

Raw Data:
{json.dumps(observation.raw_data, indent=2)[:1000]}
"""

        if context.get("logs"):
            prompt += f"\n\nContainer Logs (last 50 lines):\n{context['logs']}"

        if context.get("events"):
            prompt += f"\n\nPod Events:\n{context['events']}"

        prompt += """

Provide a diagnosis in JSON format:
{
  "category": "one of: unknown, oom_killed, liveness_probe_failure, image_pull_backoff_transient, image_pull_backoff_auth, image_pull_backoff_not_found, scc_permission_denied, application_error, cluster_operator_degraded, machine_config_pool_degraded",
  "root_cause": "brief explanation of the root cause",
  "confidence": "high|medium|low",
  "recommended_actions": ["action 1", "action 2", "action 3"],
  "recommended_tier": 1|2|3,
  "evidence": ["key evidence 1", "key evidence 2"]
}

Tier guide:
- Tier 1: Automated fixes (transient issues, retries)
- Tier 2: GitOps PR (config changes like memory limits)
- Tier 3: Notification only (needs human intervention)
"""

        return prompt

    def _parse_llm_response(
        self,
        content: str,
        observation: Observation
    ) -> Optional[Diagnosis]:
        """Parse LLM response into Diagnosis."""
        try:
            # Extract JSON from response
            # LLM might wrap in markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            analysis = json.loads(content.strip())

            # Map category string to enum
            category_map = {
                "unknown": DiagnosisCategory.UNKNOWN,
                "oom_killed": DiagnosisCategory.OOM_KILLED,
                "liveness_probe_failure": DiagnosisCategory.LIVENESS_PROBE_FAILURE,
                "image_pull_backoff_transient": DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
                "image_pull_backoff_auth": DiagnosisCategory.IMAGE_PULL_BACKOFF_AUTH,
                "image_pull_backoff_not_found": DiagnosisCategory.IMAGE_PULL_BACKOFF_NOT_FOUND,
                "scc_permission_denied": DiagnosisCategory.SCC_PERMISSION_DENIED,
                "application_error": DiagnosisCategory.APPLICATION_ERROR,
                "cluster_operator_degraded": DiagnosisCategory.CLUSTER_OPERATOR_DEGRADED,
                "machine_config_pool_degraded": DiagnosisCategory.MACHINE_CONFIG_POOL_DEGRADED,
                "registry_timeout": DiagnosisCategory.REGISTRY_TIMEOUT,
            }

            category = category_map.get(
                analysis.get("category", "unknown"),
                DiagnosisCategory.UNKNOWN
            )

            confidence_map = {
                "high": Confidence.HIGH,
                "medium": Confidence.MEDIUM,
                "low": Confidence.LOW,
            }
            confidence = confidence_map.get(
                analysis.get("confidence", "low"),
                Confidence.LOW  # LLM fallback has lower confidence by default
            )

            tier = analysis.get("recommended_tier", 3)

            return Diagnosis(
                observation_id=observation.id,
                category=category,
                root_cause=analysis.get("root_cause", "Unknown issue"),
                confidence=confidence,
                recommended_actions=analysis.get("recommended_actions", []),
                recommended_tier=tier,
                evidence=build_evidence(
                    observation,
                    llm_analysis=True,
                    llm_evidence=analysis.get("evidence", [])
                ),
                error_patterns=analysis.get("evidence", []),
                analyzer_name=self.analyzer_name,
            )

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}", exc_info=True)
            logger.debug(f"Raw LLM response: {content[:500]}")
            return None
