"""
Alert Correlator for reducing noise and identifying root causes.

Correlates related observations to find root cause and deduplicate symptoms.
"""

from typing import List, Dict, Set, Optional
from datetime import datetime, timedelta

from sre_agent.models.observation import Observation, ObservationType
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class DependencyGraph:
    """
    Dependency graph for resources.

    Represents: Node → Pod → Service → Route hierarchy
    """

    def __init__(self):
        self.graph: Dict[str, Set[str]] = {}  # parent_id -> set of child_ids

    def add_dependency(self, parent_id: str, child_id: str):
        """Add parent -> child dependency."""
        if parent_id not in self.graph:
            self.graph[parent_id] = set()
        self.graph[parent_id].add(child_id)

    def get_children(self, parent_id: str) -> Set[str]:
        """Get all children of a parent."""
        return self.graph.get(parent_id, set())

    def get_all_descendants(self, parent_id: str) -> Set[str]:
        """Get all descendants (children, grandchildren, etc.) of a parent."""
        descendants = set()
        to_visit = [parent_id]

        while to_visit:
            current = to_visit.pop()
            children = self.graph.get(current, set())
            for child in children:
                if child not in descendants:
                    descendants.add(child)
                    to_visit.append(child)

        return descendants


class CorrelatedObservationGroup:
    """Group of correlated observations with identified root cause."""

    def __init__(
        self,
        root_cause_observation: Observation,
        symptom_observations: List[Observation],
        correlation_reason: str
    ):
        self.root_cause = root_cause_observation
        self.symptoms = symptom_observations
        self.correlation_reason = correlation_reason
        self.timestamp = datetime.utcnow()

    def __str__(self) -> str:
        return (
            f"CorrelatedGroup(root={self.root_cause.resource_name}, "
            f"symptoms={len(self.symptoms)}, reason={self.correlation_reason})"
        )


class AlertCorrelator:
    """
    Correlates related observations to reduce noise and identify root causes.

    Features:
    - Dependency-based correlation (Node → Pod → Service → Route)
    - Time-based correlation (alerts within 5 minutes)
    - Alert storm detection (>10 alerts in 5 minutes)
    - Deduplication by fingerprint
    """

    def __init__(self):
        self.dependency_graph = DependencyGraph()
        self.alert_storm_threshold = 10  # alerts
        self.alert_storm_window_seconds = 300  # 5 minutes
        self.correlation_window_seconds = 300  # 5 minutes

    async def correlate_observations(
        self,
        observations: List[Observation]
    ) -> List[CorrelatedObservationGroup]:
        """
        Correlate observations to identify root causes and symptoms.

        Args:
            observations: List of observations to correlate

        Returns:
            List of correlated groups (root cause + symptoms)
        """
        if not observations:
            return []

        request_id = logger.set_request_id()

        logger.info(
            f"Correlating {len(observations)} observations",
            request_id=request_id,
            observation_count=len(observations)
        )

        # Check for alert storm
        if self._is_alert_storm(observations):
            logger.warning(
                f"Alert storm detected: {len(observations)} observations in short time",
                request_id=request_id
            )
            # Group into single alert storm
            return [self._create_alert_storm_group(observations)]

        # Build dependency graph
        self._build_dependency_graph(observations)

        # Correlate by dependencies
        correlated_groups = self._correlate_by_dependencies(observations)

        # Correlate remaining by time proximity
        uncorrelated = self._get_uncorrelated_observations(observations, correlated_groups)
        time_groups = self._correlate_by_time(uncorrelated)
        correlated_groups.extend(time_groups)

        logger.info(
            f"Correlation complete: {len(correlated_groups)} groups",
            request_id=request_id,
            group_count=len(correlated_groups),
            original_count=len(observations)
        )

        return correlated_groups

    def _is_alert_storm(self, observations: List[Observation]) -> bool:
        """
        Check if observations constitute an alert storm.

        Args:
            observations: List of observations

        Returns:
            True if alert storm detected
        """
        if len(observations) < self.alert_storm_threshold:
            return False

        # Check if all within time window
        timestamps = [obs.timestamp for obs in observations]
        earliest = min(timestamps)
        latest = max(timestamps)

        time_span = (latest - earliest).total_seconds()

        return time_span <= self.alert_storm_window_seconds

    def _create_alert_storm_group(
        self,
        observations: List[Observation]
    ) -> CorrelatedObservationGroup:
        """
        Create a single correlated group for alert storm.

        Args:
            observations: All observations in the storm

        Returns:
            CorrelatedObservationGroup with first observation as root cause
        """
        # Use first (earliest) observation as representative root cause
        root_cause = observations[0]
        symptoms = observations[1:]

        return CorrelatedObservationGroup(
            root_cause_observation=root_cause,
            symptom_observations=symptoms,
            correlation_reason=f"Alert storm: {len(observations)} observations in {self.alert_storm_window_seconds}s"
        )

    def _build_dependency_graph(self, observations: List[Observation]):
        """
        Build dependency graph from observations.

        Hierarchy: Node → Pod → Service → Route

        Args:
            observations: List of observations
        """
        self.dependency_graph = DependencyGraph()

        for obs in observations:
            resource_id = self._get_resource_id(obs)

            # Add dependencies based on resource metadata
            if obs.resource_kind == "Pod":
                # Pod depends on Node
                node_name = obs.raw_data.get("spec", {}).get("nodeName")
                if node_name:
                    node_id = f"Node/{node_name}"
                    self.dependency_graph.add_dependency(node_id, resource_id)

                # Service depends on Pods (via labels)
                # This would require fetching service selectors - simplified for now

            elif obs.resource_kind == "Route":
                # Route depends on Service
                service_name = obs.raw_data.get("spec", {}).get("to", {}).get("name")
                if service_name:
                    service_id = f"Service/{obs.namespace}/{service_name}"
                    self.dependency_graph.add_dependency(service_id, resource_id)

    def _correlate_by_dependencies(
        self,
        observations: List[Observation]
    ) -> List[CorrelatedObservationGroup]:
        """
        Correlate observations based on dependency graph.

        If a Node fails, all Pods on that Node are symptoms, not root causes.

        Args:
            observations: List of observations

        Returns:
            List of correlated groups
        """
        groups = []
        processed_ids = set()

        # Sort by hierarchy (Node first, then Pod, then Service, then Route)
        hierarchy_order = {"Node": 0, "Pod": 1, "Service": 2, "Route": 3}
        sorted_obs = sorted(
            observations,
            key=lambda o: hierarchy_order.get(o.resource_kind, 99)
        )

        for obs in sorted_obs:
            resource_id = self._get_resource_id(obs)

            if resource_id in processed_ids:
                continue  # Already processed as a symptom

            # Find all descendants of this resource
            descendants = self.dependency_graph.get_all_descendants(resource_id)

            # Find observations that are descendants (symptoms)
            symptom_observations = [
                o for o in observations
                if self._get_resource_id(o) in descendants and o != obs
            ]

            if symptom_observations:
                # This observation is a root cause
                groups.append(CorrelatedObservationGroup(
                    root_cause_observation=obs,
                    symptom_observations=symptom_observations,
                    correlation_reason=f"Dependency: {obs.resource_kind} affects {len(symptom_observations)} downstream resources"
                ))

                # Mark all as processed
                processed_ids.add(resource_id)
                for symptom_obs in symptom_observations:
                    processed_ids.add(self._get_resource_id(symptom_obs))

        return groups

    def _correlate_by_time(
        self,
        observations: List[Observation]
    ) -> List[CorrelatedObservationGroup]:
        """
        Correlate observations for the SAME resource that occurred close in time.

        Only correlates observations that:
        1. Are for the SAME resource (same kind, namespace, name)
        2. Occur within time window

        This prevents grouping unrelated failures (e.g., POD_FAILURE + HPA_DEGRADED)
        and only groups repeated failures of the same resource.

        Args:
            observations: List of observations

        Returns:
            List of correlated groups
        """
        groups = []

        if not observations:
            return groups

        # Group by resource ID first
        resource_groups = {}
        for obs in observations:
            resource_id = self._get_resource_id(obs)
            if resource_id not in resource_groups:
                resource_groups[resource_id] = []
            resource_groups[resource_id].append(obs)

        # Correlate within each resource group
        for resource_id, resource_obs in resource_groups.items():
            if len(resource_obs) <= 1:
                continue  # Single observation, no correlation needed

            # Sort by timestamp
            sorted_obs = sorted(resource_obs, key=lambda o: o.timestamp)

            current_group = [sorted_obs[0]]

            for obs in sorted_obs[1:]:
                time_diff = (obs.timestamp - current_group[0].timestamp).total_seconds()

                if time_diff <= self.correlation_window_seconds:
                    # Within time window - add to current group
                    current_group.append(obs)
                else:
                    # Outside window - finalize current group and start new one
                    if len(current_group) > 1:
                        # Create correlated group (first as root cause, others as symptoms)
                        groups.append(CorrelatedObservationGroup(
                            root_cause_observation=current_group[0],
                            symptom_observations=current_group[1:],
                            correlation_reason=f"Time proximity for {resource_id}: {len(current_group)} occurrences within {self.correlation_window_seconds}s"
                        ))

                    current_group = [obs]

            # Finalize last group for this resource
            if len(current_group) > 1:
                groups.append(CorrelatedObservationGroup(
                    root_cause_observation=current_group[0],
                    symptom_observations=current_group[1:],
                    correlation_reason=f"Time proximity for {resource_id}: {len(current_group)} occurrences within {self.correlation_window_seconds}s"
                ))

        return groups

    def _get_uncorrelated_observations(
        self,
        all_observations: List[Observation],
        correlated_groups: List[CorrelatedObservationGroup]
    ) -> List[Observation]:
        """
        Get observations that haven't been correlated yet.

        Args:
            all_observations: All observations
            correlated_groups: Already correlated groups

        Returns:
            List of uncorrelated observations
        """
        correlated_ids = set()

        for group in correlated_groups:
            correlated_ids.add(group.root_cause.id)
            for symptom in group.symptoms:
                correlated_ids.add(symptom.id)

        return [obs for obs in all_observations if obs.id not in correlated_ids]

    def _get_resource_id(self, observation: Observation) -> str:
        """
        Get unique resource identifier.

        Args:
            observation: Observation

        Returns:
            Resource ID (e.g., "Pod/namespace/name")
        """
        if observation.namespace:
            return f"{observation.resource_kind}/{observation.namespace}/{observation.resource_name}"
        else:
            return f"{observation.resource_kind}/{observation.resource_name}"

