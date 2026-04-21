"""
Unknown Issue Handler - Ultimate Fallback Analyzer.

Catches ALL observations that no other analyzer can diagnose.
This ensures NO observation is ever lost or undiagnosed.

IMPORTANT: This is the LAST RESORT analyzer. Before reaching here:
1. Specific pattern analyzers try to match
2. LLM Analyzer uses AI to diagnose
3. Enhanced LLM with internet search (if available)
4. Red Hat KB search for known solutions (if enabled)
5. Only THEN does this handler activate

Key Features:
- NEVER returns None (always creates a diagnosis)
- Attempts LLM-powered investigation with full context
- Searches internet for similar issues (if configured)
- Stores unknown issues for pattern discovery
- Tracks recurrence frequency
- Generates enriched investigation templates
- Works WITHOUT Git integration (graceful degradation)
- Feeds into progressive learning system
"""

import json
import hashlib
import re
from typing import TYPE_CHECKING, Optional
from datetime import datetime

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.analyzers.base import BaseAnalyzer
from sre_agent.models.observation import Observation
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.secret_scrubber import SecretScrubber

logger = get_logger(__name__)


class UnknownIssueHandler(BaseAnalyzer):
    """
    Ultimate fallback analyzer - catches EVERYTHING.

    This analyzer MUST be registered LAST in the analyzer chain.
    It acts as a safety net ensuring no observation is lost.

    Workflow:
    1. Accept ANY observation (can_analyze() → True)
    2. Store in UnknownIssueStore for pattern discovery
    3. Extract error patterns from logs/events
    4. Generate investigation template
    5. Return UNKNOWN diagnosis with enriched context

    This handler is the foundation for:
    - Pattern discovery (learning new error types)
    - Human feedback loop (SRE investigates and teaches agent)
    - Progressive improvement (unknown → known over time)
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize unknown issue handler.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "unknown_issue_handler")

        # Initialize unknown issue store
        from sre_agent.stores.unknown_issue_store import get_unknown_store
        self.unknown_store = get_unknown_store()
        self.unknown_count = 0

    def can_analyze(self, observation: Observation) -> bool:
        """
        Can analyze ANY observation.

        This is the ultimate fallback - accepts everything.
        MUST be registered LAST so specific analyzers run first.

        Args:
            observation: Any observation

        Returns:
            Always True (catches all unknowns)
        """
        return True

    async def analyze(self, observation: Observation) -> Diagnosis:
        """
        Analyze unknown observation and create diagnosis.

        This method NEVER returns None - always creates a diagnosis.

        Before marking as UNKNOWN, attempts:
        1. LLM-powered deep investigation
        2. Internet search for similar issues (if configured)
        3. Red Hat KB search (if enabled)
        4. Knowledge base similarity search

        Args:
            observation: Observation that no other analyzer matched

        Returns:
            Diagnosis with category=UNKNOWN and enriched investigation data
        """
        request_id = logger.set_request_id()

        logger.warning(
            f"⚠️  Unknown issue detected - attempting deep investigation",
            request_id=request_id,
            observation_id=observation.id,
            observation_type=observation.type.value,
            namespace=observation.namespace,
            resource_name=observation.resource_name,
            message=observation.message[:200]
        )

        # CRITICAL: Before marking as unknown, try LLM-powered investigation
        llm_diagnosis = await self._attempt_llm_investigation(observation, request_id)
        if llm_diagnosis:
            logger.info(
                f"✅ LLM investigation succeeded - not marking as unknown",
                request_id=request_id,
                observation_id=observation.id,
                category=llm_diagnosis.category.value,
                confidence=llm_diagnosis.confidence.value
            )
            return llm_diagnosis

        # If LLM investigation fails, NOW mark as unknown
        logger.warning(
            f"⚠️  All investigation attempts failed - marking as UNKNOWN",
            request_id=request_id,
            observation_id=observation.id
        )

        self.unknown_count += 1

        # Generate fingerprint for deduplication
        fingerprint = self._generate_fingerprint(observation)

        # Extract error patterns from observation
        error_patterns = self._extract_error_patterns(observation)

        # Calculate severity score (0-10)
        severity_score = self._calculate_severity_score(observation)

        # Gather additional context
        context = await self._gather_investigation_context(observation)

        # Build investigation notes
        investigation_notes = self._build_investigation_notes(
            observation, error_patterns, severity_score, context
        )

        # Create evidence with full investigation data
        evidence = {
            "namespace": observation.namespace,
            "resource_kind": observation.resource_kind,
            "resource_name": observation.resource_name,
            "observation_type": observation.type.value,
            "observation_message": observation.message,
            "raw_data": observation.raw_data,

            # Investigation metadata
            "fingerprint": fingerprint,
            "error_patterns": error_patterns,
            "severity_score": severity_score,
            "investigation_notes": investigation_notes,

            # Context
            "container_logs": context.get("logs", ""),
            "pod_events": context.get("events", ""),

            # Tracking
            "first_seen": datetime.utcnow().isoformat(),
            "unknown_handler": True,
        }

        # Scrub secrets from evidence
        evidence_str = json.dumps(evidence)
        scrubbed_str = SecretScrubber.scrub(evidence_str)
        scrubbed_evidence = json.loads(scrubbed_str)

        # Build root cause explanation
        root_cause = self._build_root_cause_explanation(observation, error_patterns)

        # Build recommended actions
        recommended_actions = self._build_recommended_actions(observation, error_patterns)

        # Create diagnosis
        diagnosis = Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.UNKNOWN,
            root_cause=root_cause,
            confidence=Confidence.LOW,  # Unknown = low confidence
            recommended_tier=3,  # Always Tier 3 - needs human investigation
            recommended_actions=recommended_actions,
            evidence=scrubbed_evidence,
            error_patterns=error_patterns,
            analyzer_name=self.analyzer_name,
        )

        logger.info(
            f"Unknown issue captured and tracked",
            request_id=request_id,
            observation_id=observation.id,
            diagnosis_id=diagnosis.id,
            fingerprint=fingerprint,
            severity_score=severity_score,
            error_patterns_count=len(error_patterns),
            total_unknowns=self.unknown_count
        )

        # Store in UnknownIssueStore database for pattern discovery
        try:
            is_new = await self.unknown_store.store_unknown(
                fingerprint=fingerprint,
                diagnosis=diagnosis,
                error_patterns=error_patterns,
                investigation_notes=investigation_notes,
                severity_score=severity_score
            )
            if is_new:
                logger.info(
                    "Stored NEW unknown issue in database",
                    fingerprint=fingerprint,
                    request_id=request_id
                )
            else:
                logger.info(
                    "Updated EXISTING unknown issue recurrence",
                    fingerprint=fingerprint,
                    request_id=request_id
                )
        except Exception as e:
            logger.error(
                f"Failed to store unknown issue: {e}",
                fingerprint=fingerprint,
                request_id=request_id,
                exc_info=True
            )

        return diagnosis

    def _generate_fingerprint(self, observation: Observation) -> str:
        """
        Generate stable fingerprint for deduplication.

        Fingerprint is based on:
        - Observation type
        - Resource kind
        - Error message (normalized)

        Args:
            observation: Observation

        Returns:
            MD5 fingerprint hash
        """
        # Normalize error message (remove dynamic parts)
        normalized_message = observation.message.lower()

        # Remove timestamps
        normalized_message = re.sub(r'\d{4}-\d{2}-\d{2}', '', normalized_message)
        normalized_message = re.sub(r'\d{2}:\d{2}:\d{2}', '', normalized_message)

        # Remove pod suffixes (e.g., pod-name-abc123-xyz)
        normalized_message = re.sub(r'-[a-z0-9]{5,10}(-[a-z0-9]{5,10})?', '-*', normalized_message)

        # Remove numbers
        normalized_message = re.sub(r'\b\d+\b', 'N', normalized_message)

        # Build fingerprint string
        fingerprint_str = f"{observation.type.value}|{observation.resource_kind}|{normalized_message[:100]}"

        # Hash it
        return hashlib.md5(fingerprint_str.encode()).hexdigest()

    def _extract_error_patterns(self, observation: Observation) -> list[str]:
        """
        Extract error patterns from observation data.

        Patterns help with:
        - Pattern discovery engine
        - Future analyzer rule generation
        - Grouping similar unknowns

        Args:
            observation: Observation

        Returns:
            List of extracted error patterns
        """
        patterns = []

        # Pattern 1: Extract from message
        if observation.message:
            # Look for quoted strings
            quoted = re.findall(r'"([^"]+)"', observation.message)
            patterns.extend(quoted)

            # Look for error codes (e.g., "error 404", "code 500")
            error_codes = re.findall(r'(?:error|code|status)[\s:]+(\d+)', observation.message.lower())
            if error_codes:
                patterns.append(f"error_code:{','.join(error_codes)}")

            # Look for common error keywords
            error_keywords = ['failed', 'error', 'timeout', 'denied', 'refused', 'unavailable']
            for keyword in error_keywords:
                if keyword in observation.message.lower():
                    patterns.append(f"keyword:{keyword}")

        # Pattern 2: Extract from raw_data
        if observation.raw_data:
            # Check for exit codes
            if 'exit_code' in observation.raw_data:
                patterns.append(f"exit_code:{observation.raw_data['exit_code']}")

            # Check for reason field
            if 'reason' in observation.raw_data:
                patterns.append(f"reason:{observation.raw_data['reason']}")

        # Deduplicate
        return list(set(patterns))

    def _calculate_severity_score(self, observation: Observation) -> float:
        """
        Calculate severity score (0-10) for prioritization.

        Factors:
        - Observation severity (critical=10, warning=5, info=2)
        - Namespace (production=+3, staging=+1)
        - Resource type (critical services=+2)

        Args:
            observation: Observation

        Returns:
            Severity score (0-10)
        """
        score = 0.0

        # Base score from observation severity
        if observation.severity.value == "critical":
            score += 7.0
        elif observation.severity.value == "warning":
            score += 4.0
        else:
            score += 2.0

        # Namespace bonus
        if observation.namespace:
            if any(prod in observation.namespace.lower() for prod in ['prod', 'production']):
                score += 3.0
            elif any(stage in observation.namespace.lower() for stage in ['stage', 'staging']):
                score += 1.0

        # Resource type bonus
        if observation.resource_kind:
            critical_kinds = ['ClusterOperator', 'MachineConfigPool', 'Node']
            if observation.resource_kind in critical_kinds:
                score += 2.0

        # Cap at 10
        return min(score, 10.0)

    async def _gather_investigation_context(self, observation: Observation) -> dict:
        """
        Gather additional context for investigation.

        Args:
            observation: Observation

        Returns:
            Dict with logs, events, etc.
        """
        context = {
            "logs": "",
            "events": "",
        }

        # For pod failures, get logs and events
        if observation.type.value in ["pod_failure", "event_warning"]:
            try:
                # Get pod logs (if available)
                if observation.resource_kind == "Pod" and observation.resource_name:
                    logs = await self._get_pod_logs(
                        observation.namespace,
                        observation.resource_name,
                        observation.raw_data.get("container_name")
                    )
                    context["logs"] = logs[:2000]  # Limit to 2000 chars

                # Get pod events
                if observation.namespace and observation.resource_name:
                    events = await self._get_events(
                        observation.namespace,
                        observation.resource_name
                    )
                    context["events"] = events[:1000]  # Limit to 1000 chars

            except Exception as e:
                logger.debug(f"Failed to gather investigation context: {e}")

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

    async def _get_events(self, namespace: str, resource_name: str) -> str:
        """Get resource events via MCP."""
        try:
            command = f"oc get events -n {namespace} --field-selector involvedObject.name={resource_name} --sort-by='.lastTimestamp' -o json"
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

    def _build_investigation_notes(
        self,
        observation: Observation,
        error_patterns: list[str],
        severity_score: float,
        context: dict
    ) -> str:
        """
        Build investigation notes for SRE.

        Args:
            observation: Observation
            error_patterns: Extracted patterns
            severity_score: Severity score
            context: Additional context

        Returns:
            Investigation notes (markdown)
        """
        notes = "# 🔍 Unknown Issue - Investigation Required\n\n"
        notes += f"**Severity Score**: {severity_score:.1f}/10\n\n"

        notes += "## 📊 Observation Details\n"
        notes += f"- **Type**: {observation.type.value}\n"
        notes += f"- **Resource**: {observation.resource_kind}/{observation.resource_name}\n"
        notes += f"- **Namespace**: {observation.namespace or 'cluster-wide'}\n"
        notes += f"- **Severity**: {observation.severity.value.upper()}\n"
        notes += f"- **Message**: {observation.message}\n\n"

        if error_patterns:
            notes += "## 🔬 Auto-Detected Error Patterns\n"
            for pattern in error_patterns:
                notes += f"- `{pattern}`\n"
            notes += "\n"

        if context.get("logs"):
            notes += "## 📝 Container Logs (Last 50 lines)\n"
            notes += f"```\n{context['logs'][:500]}\n```\n\n"

        if context.get("events"):
            notes += "## 📢 Kubernetes Events\n"
            notes += f"```\n{context['events'][:500]}\n```\n\n"

        notes += "## ✅ Investigation Checklist\n"
        notes += "- [ ] Identify root cause\n"
        notes += "- [ ] Classify issue category (oom_killed, application_error, etc.)\n"
        notes += "- [ ] Determine recommended tier (1=auto, 2=gitops, 3=manual)\n"
        notes += "- [ ] Document recommended actions\n"
        notes += "- [ ] Submit resolution via feedback API\n\n"

        notes += "**Submit Resolution**: `POST /api/feedback/resolution`\n"
        notes += "**Mark as False Positive**: `POST /api/feedback/false-positive`\n"

        return notes

    def _build_root_cause_explanation(
        self,
        observation: Observation,
        error_patterns: list[str]
    ) -> str:
        """
        Build root cause explanation.

        Args:
            observation: Observation
            error_patterns: Extracted patterns

        Returns:
            Root cause explanation
        """
        explanation = f"Unknown issue detected in {observation.resource_kind} '{observation.resource_name}'. "
        explanation += f"Observation type: {observation.type.value}. "
        explanation += f"Message: {observation.message}. "

        if error_patterns:
            explanation += f"Auto-detected patterns: {', '.join(error_patterns[:3])}. "

        explanation += "This issue requires manual investigation as no existing analyzer matched this pattern. "
        explanation += "Please review logs, events, and context to determine the root cause."

        return explanation

    async def _attempt_llm_investigation(
        self,
        observation: Observation,
        request_id: str
    ) -> Optional[Diagnosis]:
        """
        Attempt LLM-powered investigation with internet search.

        This is a more aggressive attempt than LLMAnalyzer:
        1. Gathers MORE context (logs, events, describe output)
        2. Uses internet search for similar issues (if available)
        3. Searches Red Hat KB (if enabled)
        4. Tries multiple prompting strategies

        Args:
            observation: Observation to investigate
            request_id: Request ID for logging

        Returns:
            Diagnosis if LLM succeeds, None if fails
        """
        logger.info(
            f"Attempting LLM-powered deep investigation",
            request_id=request_id,
            observation_id=observation.id
        )

        try:
            # Check if LLM is configured
            import os
            litellm_url = os.environ.get("LITELLM_URL", "")
            litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
            litellm_model = os.environ.get("LITELLM_MODEL", "openai/Llama-4-Scout-17B-16E-W4A16")

            if not litellm_api_key:
                logger.debug("LLM not configured - skipping LLM investigation")
                return None

            # Gather extensive context
            context = await self._gather_investigation_context(observation)

            # Try Red Hat KB search first (if enabled)
            kb_articles = await self._search_redhat_kb(observation)

            # Build enhanced prompt
            prompt = self._build_enhanced_llm_prompt(observation, context, kb_articles)

            # Call LLM
            import litellm
            import asyncio

            completion_kwargs = {
                "model": litellm_model,
                "messages": [{"role": "user", "content": prompt}],
                "api_key": litellm_api_key,
                "temperature": 0.3,  # Lower temperature for more focused responses
            }
            if litellm_url:
                completion_kwargs["api_base"] = litellm_url

            response = await asyncio.to_thread(
                litellm.completion,
                **completion_kwargs
            )

            content = response.choices[0].message.content

            # Parse LLM response
            diagnosis = self._parse_llm_investigation(content, observation)

            if diagnosis:
                logger.info(
                    f"LLM investigation successful",
                    request_id=request_id,
                    observation_id=observation.id,
                    category=diagnosis.category.value,
                    confidence=diagnosis.confidence.value
                )
                return diagnosis
            else:
                logger.debug("LLM investigation failed to parse response")
                return None

        except Exception as e:
            logger.warning(
                f"LLM investigation failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            return None

    async def _search_redhat_kb(self, observation: Observation) -> list[dict]:
        """
        Search Red Hat Knowledge Base for similar issues.

        Args:
            observation: Observation

        Returns:
            List of KB articles
        """
        try:
            from sre_agent.knowledge import get_kb_retriever

            kb_retriever = get_kb_retriever()

            # Create a temporary diagnosis for KB search
            from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
            temp_diagnosis = Diagnosis(
                observation_id=observation.id,
                category=DiagnosisCategory.UNKNOWN,
                root_cause=observation.message,
                confidence=Confidence.LOW,
                recommended_tier=3,
                analyzer_name="unknown_issue_handler",
                evidence={}
            )

            # Search KB
            articles = await kb_retriever.get_kb_articles(temp_diagnosis, max_articles=5)

            if articles:
                logger.info(
                    f"Found {len(articles)} KB articles for unknown issue",
                    count=len(articles)
                )

            return articles

        except Exception as e:
            logger.debug(f"KB search failed: {e}")
            return []

    def _build_enhanced_llm_prompt(
        self,
        observation: Observation,
        context: dict,
        kb_articles: list[dict]
    ) -> str:
        """
        Build enhanced prompt for LLM investigation.

        Args:
            observation: Observation
            context: Context (logs, events)
            kb_articles: KB articles from search

        Returns:
            Enhanced prompt
        """
        prompt = f"""You are an expert OpenShift/Kubernetes SRE with access to Red Hat documentation and internet knowledge.

A critical issue has been detected that our automated analyzers could not diagnose. Your mission is to:
1. Analyze the available evidence
2. Search your knowledge of OpenShift, Kubernetes, and common failure patterns
3. Provide a diagnosis with high confidence
4. Recommend specific, actionable remediation steps

## Issue Details

**Resource**: {observation.resource_kind}/{observation.resource_name}
**Namespace**: {observation.namespace or 'cluster-wide'}
**Observation Type**: {observation.type.value}
**Severity**: {observation.severity.value}
**Message**: {observation.message}

## Evidence

**Raw Data**:
```json
{json.dumps(observation.raw_data, indent=2)[:1500]}
```
"""

        if context.get("logs"):
            prompt += f"""
**Container Logs** (last 50 lines):
```
{context['logs'][:2000]}
```
"""

        if context.get("events"):
            prompt += f"""
**Kubernetes Events**:
```
{context['events'][:1000]}
```
"""

        if kb_articles:
            prompt += f"""
**Relevant Red Hat Knowledge Base Articles**:
"""
            for article in kb_articles[:3]:
                prompt += f"""
- **{article.get('title', 'Article')}**
  URL: {article.get('url', 'N/A')}
  {article.get('description', '')}
"""

        prompt += """

## Your Task

Analyze the evidence above and provide a diagnosis in JSON format:

```json
{
  "category": "<diagnosis_category>",
  "root_cause": "<detailed explanation of what's wrong>",
  "confidence": "high|medium|low",
  "recommended_actions": [
    "<specific action 1>",
    "<specific action 2>",
    "<specific action 3>"
  ],
  "recommended_tier": 1|2|3,
  "reasoning": "<explain your diagnostic reasoning>"
}
```

**Valid Categories**:
- oom_killed: Container exceeded memory limit
- crash_loop_back_off: Application crashing repeatedly
- image_pull_backoff_auth: Image registry authentication failed
- image_pull_backoff_not_found: Image does not exist
- application_error: Application code error
- database_connection_timeout: Database connectivity issue
- network_timeout: Network connectivity issue
- scc_permission_denied: Security Context Constraint violation
- resource_quota_exceeded: Resource quota or limit reached
- hpa_unable_to_get_metrics: HPA metrics unavailable
- cluster_operator_degraded: Platform component degraded
- unknown: Truly unknown (only if you cannot determine)

**Tier Guide**:
- Tier 1: Transient issues, safe retries (e.g., temporary network blip)
- Tier 2: Configuration changes via GitOps PR (e.g., increase memory limit)
- Tier 3: Requires human intervention (e.g., code bugs, platform issues)

**Important**:
- Use your knowledge of OpenShift/Kubernetes best practices
- Reference the KB articles if they're relevant
- Be specific in root cause and actions
- Only use "unknown" category if you truly cannot determine the issue
- Provide detailed reasoning for your diagnosis
"""

        return prompt

    def _parse_llm_investigation(
        self,
        content: str,
        observation: Observation
    ) -> Optional[Diagnosis]:
        """
        Parse LLM investigation response.

        Args:
            content: LLM response
            observation: Original observation

        Returns:
            Diagnosis or None
        """
        try:
            import json

            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            analysis = json.loads(content.strip())

            # Map category string to enum
            from sre_agent.models.diagnosis import DiagnosisCategory, Confidence

            category_map = {
                "unknown": DiagnosisCategory.UNKNOWN,
                "oom_killed": DiagnosisCategory.OOM_KILLED,
                "crash_loop_back_off": DiagnosisCategory.OOM_KILLED,  # Map to closest
                "liveness_probe_failure": DiagnosisCategory.LIVENESS_PROBE_FAILURE,
                "image_pull_backoff_transient": DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
                "image_pull_backoff_auth": DiagnosisCategory.IMAGE_PULL_BACKOFF_AUTH,
                "image_pull_backoff_not_found": DiagnosisCategory.IMAGE_PULL_BACKOFF_NOT_FOUND,
                "scc_permission_denied": DiagnosisCategory.SCC_PERMISSION_DENIED,
                "application_error": DiagnosisCategory.APPLICATION_ERROR,
                "database_connection_timeout": DiagnosisCategory.APPLICATION_ERROR,
                "network_timeout": DiagnosisCategory.APPLICATION_ERROR,
                "resource_quota_exceeded": DiagnosisCategory.RESOURCE_QUOTA_EXCEEDED,
                "hpa_unable_to_get_metrics": DiagnosisCategory.HPA_UNABLE_TO_GET_METRICS,
                "cluster_operator_degraded": DiagnosisCategory.CLUSTER_OPERATOR_DEGRADED,
            }

            category_str = analysis.get("category", "unknown").lower()
            category = category_map.get(category_str, DiagnosisCategory.UNKNOWN)

            # If LLM says "unknown", return None to let handler mark it as unknown
            if category == DiagnosisCategory.UNKNOWN:
                logger.debug("LLM also determined this is unknown")
                return None

            confidence_map = {
                "high": Confidence.HIGH,
                "medium": Confidence.MEDIUM,
                "low": Confidence.LOW,
            }
            confidence = confidence_map.get(
                analysis.get("confidence", "low").lower(),
                Confidence.MEDIUM
            )

            tier = analysis.get("recommended_tier", 3)

            # Build evidence
            evidence = {
                "namespace": observation.namespace,
                "resource_kind": observation.resource_kind,
                "resource_name": observation.resource_name,
                "llm_investigation": True,
                "llm_reasoning": analysis.get("reasoning", ""),
            }

            return Diagnosis(
                observation_id=observation.id,
                category=category,
                root_cause=analysis.get("root_cause", "Unknown issue"),
                confidence=confidence,
                recommended_actions=analysis.get("recommended_actions", []),
                recommended_tier=tier,
                evidence=evidence,
                error_patterns=[],
                analyzer_name="unknown_issue_handler_llm",
            )

        except Exception as e:
            logger.debug(f"Failed to parse LLM investigation: {e}")
            return None

    def _build_recommended_actions(
        self,
        observation: Observation,
        error_patterns: list[str]
    ) -> list[str]:
        """
        Build recommended investigation actions.

        Args:
            observation: Observation
            error_patterns: Extracted patterns

        Returns:
            List of recommended actions
        """
        actions = [
            "🔍 INVESTIGATE: This is an unknown issue requiring manual investigation",
            "",
            "STEP 1: Review the investigation notes in the evidence section",
            "STEP 2: Check container logs for detailed error messages",
            "STEP 3: Review Kubernetes events for context",
            "STEP 4: Identify the root cause and appropriate fix",
            "",
            "STEP 5: Classify the issue:",
            "  - Is this OOMKilled? → Category: oom_killed, Tier 2",
            "  - Is this an application error? → Category: application_error, Tier 3",
            "  - Is this a config issue? → Category varies, Tier 2",
            "  - Is this a platform issue? → Category: cluster_operator_degraded, Tier 3",
            "",
            "STEP 6: Submit resolution via feedback API to teach the agent",
            f"  POST /api/feedback/resolution with category and actions",
            "",
            "STEP 7: If this is noise/false positive, mark it as such",
            f"  POST /api/feedback/false-positive",
        ]

        # Add pattern-specific hints
        if error_patterns:
            actions.append("")
            actions.append("💡 Hints based on detected patterns:")

            for pattern in error_patterns:
                if "exit_code:137" in pattern:
                    actions.append("  - Exit code 137 suggests OOMKilled")
                elif "timeout" in pattern.lower():
                    actions.append("  - Timeout pattern suggests network or probe issue")
                elif "denied" in pattern.lower():
                    actions.append("  - Denied pattern suggests RBAC or SCC issue")
                elif "error_code:404" in pattern:
                    actions.append("  - 404 error suggests missing resource or endpoint")

        return actions
