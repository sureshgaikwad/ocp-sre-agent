"""
Proactive analyzer for trend and anomaly observations.

Analyzes proactive observations to recommend preventive actions.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.analyzers.base import BaseAnalyzer
from sre_agent.analyzers.evidence_builder import build_evidence
from sre_agent.models.observation import Observation, ObservationType
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class ProactiveAnalyzer(BaseAnalyzer):
    """
    Analyzer for proactive observations (trends and anomalies).

    Recommends preventive actions BEFORE failures occur.
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize ProactiveAnalyzer.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "proactive_analyzer")

    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the observation.

        Args:
            observation: Observation to check

        Returns:
            True if observation is proactive (trend or anomaly)
        """
        return observation.type in [
            ObservationType.TREND_MEMORY_INCREASING,
            ObservationType.TREND_CPU_INCREASING,
            ObservationType.TREND_ERROR_RATE_RISING,
            ObservationType.TREND_RESTART_COUNT_RISING,
            ObservationType.ANOMALY_CPU_SPIKE,
            ObservationType.ANOMALY_MEMORY_SPIKE,
            ObservationType.ANOMALY_DISK_GROWTH,
        ]

    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze a proactive observation.

        Args:
            observation: Proactive observation

        Returns:
            Diagnosis with preventive recommendations
        """
        request_id = logger.set_request_id()

        logger.info(
            f"Analyzing proactive observation: {observation.resource_name}",
            request_id=request_id,
            observation_id=observation.id,
            type=observation.type.value
        )

        try:
            # Route to specific analyzer based on type
            if observation.type == ObservationType.TREND_MEMORY_INCREASING:
                return self._analyze_memory_trend(observation)
            elif observation.type == ObservationType.TREND_CPU_INCREASING:
                return self._analyze_cpu_trend(observation)
            elif observation.type == ObservationType.TREND_ERROR_RATE_RISING:
                return self._analyze_error_trend(observation)
            elif observation.type in [ObservationType.ANOMALY_CPU_SPIKE, ObservationType.ANOMALY_MEMORY_SPIKE]:
                return self._analyze_anomaly(observation)
            else:
                return None

        except Exception as e:
            logger.error(
                f"Failed to analyze proactive observation: {e}",
                request_id=request_id,
                observation_id=observation.id,
                exc_info=True
            )
            return None

    def _analyze_memory_trend(self, observation: Observation) -> Diagnosis:
        """
        Analyze memory trend to recommend proactive memory increase.

        Args:
            observation: Memory trend observation

        Returns:
            Diagnosis with proactive memory increase recommendation
        """
        raw_data = observation.raw_data
        current_percent = raw_data.get("current_percent", 0)
        time_to_limit_seconds = raw_data.get("time_to_limit_seconds")
        container = raw_data.get("container", "unknown")

        # Determine urgency based on time to limit
        if time_to_limit_seconds and time_to_limit_seconds < 3600:  # Less than 1 hour
            confidence = Confidence.HIGH
            urgency = "URGENT"
        elif time_to_limit_seconds and time_to_limit_seconds < 86400:  # Less than 24 hours
            confidence = Confidence.HIGH
            urgency = "HIGH"
        else:
            confidence = Confidence.MEDIUM
            urgency = "MEDIUM"

        # Calculate recommended memory increase
        # Increase by 50% to provide headroom
        recommended_increase_factor = 1.5

        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.PROACTIVE_MEMORY_INCREASE,
            root_cause=(
                f"Memory usage trending upward ({current_percent:.1f}% of limit). "
                f"Predicted OOM in {time_to_limit_seconds / 3600:.1f} hours. "
                f"Proactive increase recommended to prevent failure."
            ),
            confidence=confidence,
            recommended_tier=2,  # Tier 2: GitOps config change
            recommended_actions=[
                f"Increase memory limit by {(recommended_increase_factor - 1) * 100:.0f}%",
                "Add memory request to ensure scheduling",
                "Monitor after increase to verify trend stabilizes",
                "Consider application-level optimization if trend continues"
            ],
            evidence=build_evidence(
                observation,
                current_percent=current_percent,
                time_to_limit_hours=time_to_limit_seconds / 3600 if time_to_limit_seconds else None,
                trend_slope=raw_data.get("trend_slope"),
                container=container,
                urgency=urgency,
                recommended_increase_factor=recommended_increase_factor
            ),
            analyzer_name=self.analyzer_name
        )

    def _analyze_cpu_trend(self, observation: Observation) -> Diagnosis:
        """
        Analyze CPU trend to recommend proactive CPU increase.

        Args:
            observation: CPU trend observation

        Returns:
            Diagnosis with proactive CPU increase recommendation
        """
        raw_data = observation.raw_data
        current_percent = raw_data.get("current_percent", 0)
        container = raw_data.get("container", "unknown")

        # High CPU usage leads to throttling
        if current_percent > 90:
            confidence = Confidence.HIGH
            urgency = "HIGH"
        elif current_percent > 80:
            confidence = Confidence.HIGH
            urgency = "MEDIUM"
        else:
            confidence = Confidence.MEDIUM
            urgency = "LOW"

        recommended_increase_factor = 1.3  # 30% increase

        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.PROACTIVE_CPU_INCREASE,
            root_cause=(
                f"CPU usage trending upward ({current_percent:.1f}% of limit). "
                f"Application may experience throttling. "
                f"Proactive increase recommended to prevent performance degradation."
            ),
            confidence=confidence,
            recommended_tier=2,
            recommended_actions=[
                f"Increase CPU limit by {(recommended_increase_factor - 1) * 100:.0f}%",
                "Add CPU request to prevent throttling",
                "Monitor CPU throttling metrics",
                "Consider horizontal scaling (HPA) if trend continues"
            ],
            evidence=build_evidence(
                observation,
                current_percent=current_percent,
                trend_slope=raw_data.get("trend_slope"),
                container=container,
                urgency=urgency,
                recommended_increase_factor=recommended_increase_factor
            ),
            analyzer_name=self.analyzer_name
        )

    def _analyze_error_trend(self, observation: Observation) -> Diagnosis:
        """
        Analyze error rate trend.

        Args:
            observation: Error trend observation

        Returns:
            Diagnosis with recommendations
        """
        raw_data = observation.raw_data
        current_error_rate = raw_data.get("current_error_rate", 0)

        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.PROACTIVE_SCALE_UP,
            root_cause=(
                f"Error rate increasing ({current_error_rate:.0f} errors/hour). "
                f"May indicate approaching capacity limits or degrading service. "
                f"Proactive scaling recommended."
            ),
            confidence=Confidence.MEDIUM,
            recommended_tier=2,
            recommended_actions=[
                "Scale up application replicas",
                "Review application logs for error patterns",
                "Check downstream service health",
                "Verify rate limiting and circuit breaker configurations"
            ],
            evidence=build_evidence(
                observation,
                current_error_rate=current_error_rate,
                trend_slope=raw_data.get("trend_slope")
            ),
            analyzer_name=self.analyzer_name
        )

    def _analyze_anomaly(self, observation: Observation) -> Diagnosis:
        """
        Analyze anomaly observation.

        Args:
            observation: Anomaly observation

        Returns:
            Diagnosis with investigation recommendations
        """
        raw_data = observation.raw_data
        z_score = raw_data.get("z_score", 0)

        # Anomalies are Tier 3 (notify for investigation)
        # Unlike trends, anomalies are sudden and need human analysis

        return Diagnosis(
            observation_id=observation.id,
            category=DiagnosisCategory.UNKNOWN,  # Use generic category for anomalies
            root_cause=(
                f"Statistical anomaly detected ({observation.type.value}). "
                f"Z-score: {z_score:.2f}. "
                f"Investigate for potential issues or attacks."
            ),
            confidence=Confidence.MEDIUM,
            recommended_tier=3,  # Tier 3: Notify for investigation
            recommended_actions=[
                "Investigate sudden change in behavior",
                "Review application logs for errors",
                "Check for external factors (traffic spikes, deployments)",
                "Monitor for recurrence or escalation"
            ],
            evidence=build_evidence(
                observation,
                z_score=z_score,
                current_value=raw_data.get("current_value"),
                threshold_std=raw_data.get("threshold_std")
            ),
            analyzer_name=self.analyzer_name
        )
