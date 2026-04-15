"""
Event watcher for detecting Warning events in real-time.
"""

import asyncio
import logging
from typing import Callable, Set
from kubernetes import client, watch
from datetime import datetime, timedelta
from .base import BaseWatcher

logger = logging.getLogger(__name__)


class EventWatcher(BaseWatcher):
    """
    Watches Kubernetes events cluster-wide for Warning type.

    Triggers on Warning events from various resources.
    Implements deduplication to avoid processing the same event multiple times.
    """

    def __init__(self, event_callback: Callable):
        super().__init__(event_callback)
        self.core_api = client.CoreV1Api()

        # Deduplication: track processed events by UID
        self._processed_events: Set[str] = set()
        self._cleanup_interval = 300  # Clean up old UIDs every 5 minutes

    @property
    def resource_type(self) -> str:
        return "event"

    def _should_process_event(self, event: dict) -> bool:
        """
        Check if event is a Warning and hasn't been processed.

        Args:
            event: Kubernetes watch event

        Returns:
            True if event should be processed
        """
        event_type = event.get('type')
        event_obj = event.get('object')

        if not event_obj or event_type == 'DELETED':
            return False

        # Only process Warning events
        if event_obj.type != 'Warning':
            return False

        # Skip if already processed
        event_uid = event_obj.metadata.uid
        if event_uid in self._processed_events:
            return False

        # Add to processed set
        self._processed_events.add(event_uid)

        # Cleanup old entries periodically
        if len(self._processed_events) > 10000:
            self._processed_events.clear()

        return True

    async def _watch_loop(self):
        """
        Main watch loop for events.

        Watches Warning events cluster-wide and triggers workflow.
        """
        w = watch.Watch()

        while self._running:
            try:
                logger.info("Starting event watch stream")

                # Watch Warning events across all namespaces
                stream = w.stream(
                    self.core_api.list_event_for_all_namespaces,
                    field_selector="type=Warning",
                    timeout_seconds=300,
                    _request_timeout=310
                )

                async for event in self._async_watch_stream(stream):
                    if not self._running:
                        break

                    if self._should_process_event(event):
                        event_obj = event['object']
                        event_data = {
                            'type': event['type'],
                            'name': event_obj.metadata.name,
                            'namespace': event_obj.metadata.namespace,
                            'event_type': event_obj.type,
                            'reason': event_obj.reason,
                            'message': event_obj.message,
                            'involved_object': {
                                'kind': event_obj.involved_object.kind,
                                'name': event_obj.involved_object.name,
                                'namespace': event_obj.involved_object.namespace
                            } if event_obj.involved_object else None,
                            'count': event_obj.count,
                            'first_timestamp': event_obj.first_timestamp.isoformat() if event_obj.first_timestamp else None,
                            'last_timestamp': event_obj.last_timestamp.isoformat() if event_obj.last_timestamp else None,
                            'uid': event_obj.metadata.uid
                        }

                        # Trigger workflow
                        await self._trigger_workflow(event_data)

                logger.info("Event watch stream ended, reconnecting...")

            except asyncio.CancelledError:
                logger.info("Event watch cancelled")
                break
            except Exception as e:
                await self._handle_watch_error(e)

    async def _async_watch_stream(self, stream):
        """
        Convert synchronous watch stream to async.

        Args:
            stream: Kubernetes watch stream

        Yields:
            Watch events
        """
        loop = asyncio.get_event_loop()
        for event in stream:
            yield event
            await asyncio.sleep(0)
