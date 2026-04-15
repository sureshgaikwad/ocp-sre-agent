"""
Event collector for monitoring Kubernetes/OpenShift events.

Monitors Warning events across all namespaces and creates Observations.
"""

import json
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class EventCollector(BaseCollector):
    """
    Collector for Kubernetes/OpenShift Warning events.

    Monitors events across all namespaces using field selector for type=Warning.
    Deduplicates by event UID to avoid processing the same event multiple times.
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize EventCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "event_collector")
        self._seen_events: set[str] = set()  # Track UIDs to deduplicate

    async def collect(self) -> list[Observation]:
        """
        Collect Warning events from all namespaces.

        Returns:
            List of Observation objects for Warning events

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting event collection",
                request_id=request_id,
                action_taken="collect_events"
            )

            # Call oc get events via MCP
            # Assuming MCP OpenShift server has a tool for executing oc commands
            # We'll use a generic approach that can be adapted
            events_json = await self._get_warning_events()

            if not events_json:
                logger.warning(
                    "No events data returned from MCP",
                    request_id=request_id
                )
                return observations

            # Parse events
            try:
                events_data = json.loads(events_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse events JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = events_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} Warning events",
                request_id=request_id,
                event_count=len(items)
            )

            # Process each event
            for event_item in items:
                try:
                    obs = self._process_event(event_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process event: {e}",
                        request_id=request_id,
                        event_uid=event_item.get("metadata", {}).get("uid"),
                        exc_info=True
                    )

            logger.info(
                f"Event collection complete: {len(observations)} new observations",
                request_id=request_id,
                observation_count=len(observations)
            )

        except Exception as e:
            logger.error(
                f"Event collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            raise

        return observations

    async def _get_warning_events(self) -> str:
        """
        Get Warning events from cluster via Kubernetes API.

        Returns:
            JSON string of events

        Raises:
            Exception: If API call fails
        """
        try:
            # List events across all namespaces with field selector for type=Warning
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_events():
                try:
                    # Kubernetes API: list events with field selector
                    event_list = self.core_api.list_event_for_all_namespaces(
                        field_selector="type=Warning"
                    )
                    # Convert to dict for JSON serialization
                    return self.core_api.api_client.sanitize_for_serialization(event_list)
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing events: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            events_dict = await asyncio.to_thread(_list_events)

            # Return as JSON string
            return json.dumps(events_dict)

        except Exception as e:
            logger.error(
                f"Failed to list Warning events: {e}",
                exc_info=True
            )
            raise

    def _process_event(self, event_item: dict, request_id: str) -> Observation | None:
        """
        Process a single event and create an Observation.

        Args:
            event_item: Event data from Kubernetes API
            request_id: Request ID for logging

        Returns:
            Observation if event is new and relevant, None otherwise
        """
        metadata = event_item.get("metadata", {})
        event_uid = metadata.get("uid")

        # Deduplicate by UID
        if event_uid in self._seen_events:
            logger.debug(
                f"Skipping duplicate event {event_uid}",
                request_id=request_id,
                event_uid=event_uid
            )
            return None

        self._seen_events.add(event_uid)

        # Extract event details
        namespace = metadata.get("namespace")
        event_name = metadata.get("name")
        involved_object = event_item.get("involvedObject", {})
        resource_kind = involved_object.get("kind")
        resource_name = involved_object.get("name")
        reason = event_item.get("reason", "Unknown")
        message = event_item.get("message", "No message")
        event_type = event_item.get("type", "Warning")
        count = event_item.get("count", 1)
        first_timestamp = event_item.get("firstTimestamp")
        last_timestamp = event_item.get("lastTimestamp")

        # Determine severity based on reason
        severity = self._determine_severity(reason, count)

        # Build human-readable message
        full_message = f"{reason}: {message}"
        if count > 1:
            full_message += f" (occurred {count} times)"

        # Create observation
        observation = Observation(
            type=ObservationType.EVENT_WARNING,
            severity=severity,
            namespace=namespace,
            resource_kind=resource_kind,
            resource_name=resource_name,
            message=full_message,
            raw_data={
                "event_uid": event_uid,
                "event_name": event_name,
                "reason": reason,
                "count": count,
                "first_timestamp": first_timestamp,
                "last_timestamp": last_timestamp,
                "involved_object": involved_object,
                "source": event_item.get("source", {}),
            },
            labels={
                "event_type": event_type,
                "reason": reason,
            }
        )

        logger.debug(
            f"Created observation for event: {reason} in {namespace}/{resource_name}",
            request_id=request_id,
            event_uid=event_uid,
            namespace=namespace,
            resource_kind=resource_kind,
            resource_name=resource_name
        )

        return observation

    def _determine_severity(self, reason: str, count: int) -> Severity:
        """
        Determine severity based on event reason and count.

        Args:
            reason: Event reason (e.g., "FailedScheduling", "BackOff")
            count: Number of times event occurred

        Returns:
            Severity level
        """
        # High-priority reasons
        critical_reasons = {
            "OOMKilled",
            "NodeNotReady",
            "FailedMount",
            "FailedAttachVolume",
            "FailedScheduling",
        }

        if reason in critical_reasons or count > 10:
            return Severity.CRITICAL

        if count > 3:
            return Severity.WARNING

        return Severity.INFO

    def clear_cache(self) -> None:
        """
        Clear the seen events cache.

        Useful for testing or periodic cleanup to avoid unbounded memory growth.
        """
        logger.info(f"Clearing event cache ({len(self._seen_events)} events)")
        self._seen_events.clear()

    def get_cache_size(self) -> int:
        """
        Get number of events in cache.

        Returns:
            Number of cached event UIDs
        """
        return len(self._seen_events)
