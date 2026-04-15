"""
ImagePull analyzer.

Analyzes ImagePullBackOff failures and categorizes them into:
- Transient (5xx registry errors, timeouts)
- Authentication failure (401, 403)
- Image not found (404)
- Rate limit (429)
"""

import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.analyzers.base import BaseAnalyzer
from sre_agent.models.observation import Observation, ObservationType
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class ImagePullAnalyzer(BaseAnalyzer):
    """
    Analyzer for ImagePullBackOff failures.

    Categorizes image pull failures by analyzing error messages:
    - Transient: 5xx errors, timeouts, temporary registry issues
    - Auth: 401, 403, authentication failures
    - Not Found: 404, image doesn't exist
    - Rate Limit: 429, too many requests
    """

    # Error pattern regexes
    PATTERNS = {
        # Transient errors (Tier 1: auto-retry)
        "transient": [
            r"503\s+Service\s+Unavailable",
            r"502\s+Bad\s+Gateway",
            r"500\s+Internal\s+Server\s+Error",
            r"504\s+Gateway\s+Timeout",
            r"timeout",
            r"connection\s+refused",
            r"temporary\s+failure",
            r"TLS\s+handshake\s+timeout",
        ],
        # Authentication errors (Tier 3: notify)
        "auth": [
            r"401\s+Unauthorized",
            r"403\s+Forbidden",
            r"authentication\s+required",
            r"unauthorized",
            r"no\s+basic\s+auth\s+credentials",
            r"pull\s+access\s+denied",
        ],
        # Not found errors (Tier 3: notify)
        "not_found": [
            r"404\s+Not\s+Found",
            r"manifest\s+unknown",
            r"not\s+found",
            r"repository\s+does\s+not\s+exist",
        ],
        # Rate limit errors (Tier 1: retry with backoff)
        "rate_limit": [
            r"429\s+Too\s+Many\s+Requests",
            r"rate\s+limit\s+exceeded",
            r"toomanyrequests",
        ],
    }

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize ImagePull analyzer.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "image_pull_analyzer")

        # Compile regex patterns
        self.compiled_patterns = {
            category: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for category, patterns in self.PATTERNS.items()
        }

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        Args:
            observation: Observation to check

        Returns:
            True if observation is ImagePullBackOff
        """
        if observation.type != ObservationType.POD_FAILURE:
            return False

        reason = observation.labels.get("reason", "")
        return "ImagePullBackOff" in reason or "ErrImagePull" in reason

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze ImagePullBackOff and determine root cause.

        Args:
            observation: Pod failure observation

        Returns:
            Diagnosis with categorized root cause
        """
        if not self.can_analyze(observation):
            return None

        logger.info(
            f"Analyzing ImagePullBackOff for {observation.namespace}/{observation.resource_name}",
            namespace=observation.namespace,
            resource_name=observation.resource_name,
            action_taken="analyze_image_pull"
        )

        # Extract error message from observation
        message = observation.message
        raw_data = observation.raw_data
        container_status = raw_data.get("container_status", {})
        waiting = container_status.get("state", {}).get("waiting", {})
        error_message = waiting.get("message", message)

        # Extract image name
        image_name = self._extract_image_name(container_status, raw_data)

        # Categorize based on error message
        category, confidence, evidence = self._categorize_error(error_message)

        # Build diagnosis based on category
        if category == "transient":
            return self._create_transient_diagnosis(
                observation, image_name, error_message, evidence
            )
        elif category == "auth":
            return self._create_auth_diagnosis(
                observation, image_name, error_message, evidence
            )
        elif category == "not_found":
            return self._create_not_found_diagnosis(
                observation, image_name, error_message, evidence
            )
        elif category == "rate_limit":
            return self._create_rate_limit_diagnosis(
                observation, image_name, error_message, evidence
            )
        else:
            # Unknown category - generic diagnosis
            return self._create_generic_diagnosis(
                observation, image_name, error_message
            )

    def _extract_image_name(self, container_status: dict, raw_data: dict) -> str:
        """
        Extract image name from container status.

        Args:
            container_status: Container status dict
            raw_data: Raw observation data

        Returns:
            Image name
        """
        # Try to get from container status
        image = container_status.get("image", "")
        if image:
            return image

        # Try from raw_data
        image = raw_data.get("image", "unknown")
        return image

    def _categorize_error(self, error_message: str) -> tuple[str, Confidence, list[str]]:
        """
        Categorize error message using regex patterns.

        Args:
            error_message: Error message to categorize

        Returns:
            Tuple of (category, confidence, evidence_patterns_matched)
        """
        # Check each category
        for category, patterns in self.compiled_patterns.items():
            matched_patterns = []
            for pattern in patterns:
                if pattern.search(error_message):
                    matched_patterns.append(pattern.pattern)

            if matched_patterns:
                # Category matched
                confidence = Confidence.HIGH if len(matched_patterns) > 1 else Confidence.MEDIUM
                return category, confidence, matched_patterns

        # No category matched
        return "unknown", Confidence.LOW, []

    def _create_transient_diagnosis(
        self,
        observation: Observation,
        image_name: str,
        error_message: str,
        evidence: list[str]
    ) -> Diagnosis:
        """Create diagnosis for transient registry errors."""
        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
            root_cause=f"Transient registry error pulling image '{image_name}'. Registry may be temporarily unavailable or experiencing high load.",
            confidence=Confidence.HIGH,
            recommended_actions=[
                "Wait 1-5 minutes for registry to recover",
                "Retry image pull automatically",
                "Check registry status page",
            ],
            recommended_tier=1,  # Automated retry-wait
            evidence={
                "image": image_name,
                "error_message": error_message[:500],
                "matched_patterns": evidence,
            },
            error_patterns=evidence,
            analyzer_name=self.analyzer_name,
        )

    def _create_auth_diagnosis(
        self,
        observation: Observation,
        image_name: str,
        error_message: str,
        evidence: list[str]
    ) -> Diagnosis:
        """Create diagnosis for authentication errors."""
        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.IMAGE_PULL_BACKOFF_AUTH,
            root_cause=f"Authentication failure pulling image '{image_name}'. Invalid or missing image pull secret.",
            confidence=Confidence.HIGH,
            recommended_actions=[
                "Verify image pull secret exists and is valid",
                "Check image registry credentials",
                "Ensure secret is linked to ServiceAccount",
                "Verify image repository permissions",
            ],
            recommended_tier=3,  # Notification - manual fix required
            evidence={
                "image": image_name,
                "error_message": error_message[:500],
                "matched_patterns": evidence,
            },
            error_patterns=evidence,
            analyzer_name=self.analyzer_name,
        )

    def _create_not_found_diagnosis(
        self,
        observation: Observation,
        image_name: str,
        error_message: str,
        evidence: list[str]
    ) -> Diagnosis:
        """Create diagnosis for image not found errors."""
        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.IMAGE_PULL_BACKOFF_NOT_FOUND,
            root_cause=f"Image '{image_name}' not found in registry. Image may not exist or tag is incorrect.",
            confidence=Confidence.HIGH,
            recommended_actions=[
                "Verify image name and tag are correct",
                "Check if image exists in registry",
                "Ensure image repository name is correct",
                "Verify registry URL is correct",
            ],
            recommended_tier=3,  # Notification - manual fix required
            evidence={
                "image": image_name,
                "error_message": error_message[:500],
                "matched_patterns": evidence,
            },
            error_patterns=evidence,
            analyzer_name=self.analyzer_name,
        )

    def _create_rate_limit_diagnosis(
        self,
        observation: Observation,
        image_name: str,
        error_message: str,
        evidence: list[str]
    ) -> Diagnosis:
        """Create diagnosis for rate limit errors."""
        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.REGISTRY_TIMEOUT,
            root_cause=f"Rate limit exceeded pulling image '{image_name}'. Too many requests to registry.",
            confidence=Confidence.HIGH,
            recommended_actions=[
                "Wait for rate limit window to reset (typically 1 hour)",
                "Use authenticated pulls to increase rate limit",
                "Consider using image pull secret for higher limits",
                "Mirror frequently-used images to internal registry",
            ],
            recommended_tier=1,  # Automated retry with longer backoff
            evidence={
                "image": image_name,
                "error_message": error_message[:500],
                "matched_patterns": evidence,
            },
            error_patterns=evidence,
            analyzer_name=self.analyzer_name,
        )

    def _create_generic_diagnosis(
        self,
        observation: Observation,
        image_name: str,
        error_message: str
    ) -> Diagnosis:
        """Create generic diagnosis for unknown errors."""
        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT,
            root_cause=f"Unknown image pull error for '{image_name}'. Requires investigation.",
            confidence=Confidence.LOW,
            recommended_actions=[
                "Check container registry logs",
                "Verify network connectivity to registry",
                "Check pod events for more details",
                "Verify image name and tag",
            ],
            recommended_tier=3,  # Notification
            evidence={
                "image": image_name,
                "error_message": error_message[:500],
            },
            error_patterns=[],
            analyzer_name=self.analyzer_name,
        )
