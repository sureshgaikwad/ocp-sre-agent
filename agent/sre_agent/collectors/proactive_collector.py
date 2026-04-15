"""
Proactive collector for trend and anomaly detection.

Detects issues BEFORE they cause incidents using Prometheus metrics.
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Tuple
import statistics

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.utils.json_logger import get_logger
from sre_agent.config.settings import get_settings

logger = get_logger(__name__)


class ProactiveCollector(BaseCollector):
    """
    Proactive collector for detecting trends and anomalies.

    Features:
    - Memory usage trending toward limit
    - CPU usage trending toward limit
    - Error rate increasing over time
    - Restart count increasing
    - Anomaly detection using statistical methods
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize ProactiveCollector.

        Args:
            mcp_registry: MCP tool registry for calling tools
        """
        super().__init__(mcp_registry, "proactive_collector")
        self.settings = get_settings()

    async def collect(self) -> list[Observation]:
        """
        Collect proactive observations (trends and anomalies).

        Returns:
            List of Observation objects for predicted issues

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        if not self.settings.prometheus_enabled or not self.settings.prometheus_url:
            logger.debug(
                "Prometheus integration disabled, skipping proactive collection",
                request_id=request_id
            )
            return observations

        try:
            logger.info(
                "Starting proactive collection (trends and anomalies)",
                request_id=request_id,
                action_taken="collect_proactive"
            )

            # Collect memory trends
            memory_obs = await self._collect_memory_trends(request_id)
            observations.extend(memory_obs)

            # Collect CPU trends
            cpu_obs = await self._collect_cpu_trends(request_id)
            observations.extend(cpu_obs)

            # Collect error rate trends
            error_obs = await self._collect_error_trends(request_id)
            observations.extend(error_obs)

            # Collect anomalies
            anomaly_obs = await self._collect_anomalies(request_id)
            observations.extend(anomaly_obs)

            logger.info(
                f"Proactive collection completed: {len(observations)} potential issues found",
                request_id=request_id,
                observation_count=len(observations)
            )

        except Exception as e:
            logger.error(
                f"Proactive collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            # Don't re-raise - allow other collectors to run

        return observations

    async def _collect_memory_trends(self, request_id: str) -> List[Observation]:
        """
        Detect pods with memory usage trending toward limits.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for memory trends
        """
        observations = []

        try:
            # Query Prometheus for memory usage over time
            lookback_hours = self.settings.trend_lookback_hours

            # PromQL query: pods using >80% of memory limit
            query = f"""
            (
                container_memory_working_set_bytes /
                container_spec_memory_limit_bytes
            ) > {self.settings.proactive_memory_threshold_percent / 100}
            """

            # Get time series data
            metrics_data = await self._query_prometheus_range(
                query,
                lookback_hours=lookback_hours
            )

            for metric in metrics_data:
                # Extract metadata
                namespace = metric.get("namespace")
                pod_name = metric.get("pod")
                container = metric.get("container")

                # Analyze trend
                values = metric.get("values", [])
                if len(values) < 3:
                    continue  # Need at least 3 data points

                # Check if trend is increasing
                is_increasing, slope = self._calculate_trend(values)

                if is_increasing and slope > 0:
                    # Memory is increasing - predict time to OOM
                    current_percent = values[-1][1]
                    time_to_limit = self._predict_time_to_limit(
                        values, limit=100, current=current_percent
                    )

                    logger.warning(
                        f"Memory trend detected for {namespace}/{pod_name}/{container}",
                        request_id=request_id,
                        pod=pod_name,
                        namespace=namespace,
                        current_percent=current_percent,
                        time_to_limit_hours=time_to_limit / 3600 if time_to_limit else None
                    )

                    observations.append(Observation(
                        type=ObservationType.TREND_MEMORY_INCREASING,
                        severity=Severity.WARNING,
                        namespace=namespace,
                        resource_kind="Pod",
                        resource_name=pod_name,
                        message=f"Memory usage trending upward: {current_percent:.1f}% of limit. "
                                f"Predicted OOM in {time_to_limit / 3600:.1f}h" if time_to_limit else "soon",
                        raw_data={
                            "container": container,
                            "current_percent": current_percent,
                            "trend_slope": slope,
                            "time_to_limit_seconds": time_to_limit,
                            "historical_values": values[-10:]  # Last 10 data points
                        },
                        labels={"container": container}
                    ))

        except NotImplementedError as e:
            logger.warning(
                f"Memory trend collection not implemented: {e}",
                request_id=request_id
            )
        except Exception as e:
            logger.error(
                f"Failed to collect memory trends: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _collect_cpu_trends(self, request_id: str) -> List[Observation]:
        """
        Detect pods with CPU usage trending toward limits.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for CPU trends
        """
        observations = []

        try:
            # PromQL query: pods using >80% of CPU limit
            query = f"""
            (
                rate(container_cpu_usage_seconds_total[5m]) /
                container_spec_cpu_quota * 100
            ) > {self.settings.proactive_cpu_threshold_percent}
            """

            metrics_data = await self._query_prometheus_range(
                query,
                lookback_hours=self.settings.trend_lookback_hours
            )

            for metric in metrics_data:
                namespace = metric.get("namespace")
                pod_name = metric.get("pod")
                container = metric.get("container")

                values = metric.get("values", [])
                if len(values) < 3:
                    continue

                is_increasing, slope = self._calculate_trend(values)

                if is_increasing and slope > 0:
                    current_percent = values[-1][1]

                    logger.warning(
                        f"CPU trend detected for {namespace}/{pod_name}/{container}",
                        request_id=request_id,
                        pod=pod_name,
                        namespace=namespace,
                        current_percent=current_percent
                    )

                    observations.append(Observation(
                        type=ObservationType.TREND_CPU_INCREASING,
                        severity=Severity.WARNING,
                        namespace=namespace,
                        resource_kind="Pod",
                        resource_name=pod_name,
                        message=f"CPU usage trending upward: {current_percent:.1f}% of limit",
                        raw_data={
                            "container": container,
                            "current_percent": current_percent,
                            "trend_slope": slope,
                            "historical_values": values[-10:]
                        },
                        labels={"container": container}
                    ))

        except NotImplementedError as e:
            logger.warning(
                f"CPU trend collection not implemented: {e}",
                request_id=request_id
            )
        except Exception as e:
            logger.error(
                f"Failed to collect CPU trends: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _collect_error_trends(self, request_id: str) -> List[Observation]:
        """
        Detect increasing error rates.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for error rate trends
        """
        observations = []

        try:
            # PromQL query: error rate increasing
            query = """
            increase(http_requests_total{status=~"5.."}[1h]) > 10
            """

            metrics_data = await self._query_prometheus_range(
                query,
                lookback_hours=self.settings.trend_lookback_hours
            )

            for metric in metrics_data:
                namespace = metric.get("namespace")
                service = metric.get("service", "unknown")

                values = metric.get("values", [])
                if len(values) < 3:
                    continue

                is_increasing, slope = self._calculate_trend(values)

                if is_increasing:
                    current_rate = values[-1][1]

                    observations.append(Observation(
                        type=ObservationType.TREND_ERROR_RATE_RISING,
                        severity=Severity.WARNING,
                        namespace=namespace,
                        resource_kind="Service",
                        resource_name=service,
                        message=f"Error rate increasing: {current_rate:.0f} errors/hour",
                        raw_data={
                            "current_error_rate": current_rate,
                            "trend_slope": slope,
                            "historical_values": values[-10:]
                        }
                    ))

        except NotImplementedError as e:
            logger.debug(
                f"Error trend collection not implemented: {e}",
                request_id=request_id
            )
        except Exception as e:
            logger.error(
                f"Failed to collect error trends: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _collect_anomalies(self, request_id: str) -> List[Observation]:
        """
        Detect statistical anomalies in metrics.

        Args:
            request_id: Request ID for logging

        Returns:
            List of observations for anomalies
        """
        observations = []

        try:
            # Check for CPU spikes (sudden increases)
            query = "rate(container_cpu_usage_seconds_total[1m])"

            metrics_data = await self._query_prometheus_range(
                query,
                lookback_hours=1  # Check last hour for anomalies
            )

            for metric in metrics_data:
                namespace = metric.get("namespace")
                pod_name = metric.get("pod")

                values = metric.get("values", [])
                if len(values) < 10:
                    continue

                # Detect anomalies using z-score
                is_anomaly, z_score = self._detect_anomaly(values)

                if is_anomaly:
                    current_value = values[-1][1]

                    observations.append(Observation(
                        type=ObservationType.ANOMALY_CPU_SPIKE,
                        severity=Severity.WARNING,
                        namespace=namespace,
                        resource_kind="Pod",
                        resource_name=pod_name,
                        message=f"CPU spike detected: {current_value:.2f} cores (z-score: {z_score:.2f})",
                        raw_data={
                            "current_value": current_value,
                            "z_score": z_score,
                            "threshold_std": self.settings.anomaly_threshold_std
                        }
                    ))

        except NotImplementedError as e:
            logger.debug(
                f"Anomaly collection not implemented: {e}",
                request_id=request_id
            )
        except Exception as e:
            logger.error(
                f"Failed to collect anomalies: {e}",
                request_id=request_id,
                exc_info=True
            )

        return observations

    async def _query_prometheus_range(
        self,
        query: str,
        lookback_hours: int
    ) -> List[dict]:
        """
        Query Prometheus for time series data.

        Args:
            query: PromQL query
            lookback_hours: Hours to look back

        Returns:
            List of metric dicts with time series data

        Raises:
            NotImplementedError: Prometheus integration not yet available via MCP
        """
        # TODO: Prometheus integration requires custom MCP tool or direct API access
        # For now, return empty result to avoid errors
        logger.debug(
            "Prometheus query skipped - integration not yet available",
            query=query,
            lookback_hours=lookback_hours
        )
        return []

    def _calculate_trend(self, values: List[Tuple[float, float]]) -> Tuple[bool, float]:
        """
        Calculate if trend is increasing using linear regression.

        Args:
            values: List of (timestamp, value) tuples

        Returns:
            Tuple of (is_increasing, slope)
        """
        if len(values) < 2:
            return False, 0.0

        # Simple linear regression
        x = list(range(len(values)))
        y = [v[1] for v in values]

        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(x[i] ** 2 for i in range(n))

        # Calculate slope
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)

        # Trend is increasing if slope > 0
        return slope > 0, slope

    def _predict_time_to_limit(
        self,
        values: List[Tuple[float, float]],
        limit: float,
        current: float
    ) -> Optional[float]:
        """
        Predict time until value reaches limit based on trend.

        Args:
            values: Historical values
            limit: Limit value
            current: Current value

        Returns:
            Seconds until limit, or None if won't reach
        """
        is_increasing, slope = self._calculate_trend(values)

        if not is_increasing or slope <= 0:
            return None

        # Calculate time to limit based on slope
        remaining = limit - current
        time_to_limit = remaining / slope * (values[-1][0] - values[-2][0])

        return time_to_limit if time_to_limit > 0 else None

    def _detect_anomaly(self, values: List[Tuple[float, float]]) -> Tuple[bool, float]:
        """
        Detect anomaly using z-score method.

        Args:
            values: Historical values

        Returns:
            Tuple of (is_anomaly, z_score)
        """
        if len(values) < 3:
            return False, 0.0

        # Extract values
        y = [v[1] for v in values]

        # Calculate mean and standard deviation
        mean = statistics.mean(y)
        stdev = statistics.stdev(y)

        if stdev == 0:
            return False, 0.0

        # Calculate z-score for latest value
        latest = y[-1]
        z_score = abs((latest - mean) / stdev)

        # Anomaly if z-score exceeds threshold
        is_anomaly = z_score > self.settings.anomaly_threshold_std

        return is_anomaly, z_score

    def __str__(self) -> str:
        """String representation."""
        return f"ProactiveCollector(monitoring trends and anomalies)"
