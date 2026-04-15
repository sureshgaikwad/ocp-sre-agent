"""
Base watcher class for Kubernetes resource watching.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Callable, Any
from kubernetes import client, watch
from datetime import datetime

logger = logging.getLogger(__name__)


class BaseWatcher(ABC):
    """
    Base class for Kubernetes resource watchers.

    Watchers use the Kubernetes watch API to receive real-time notifications
    when resources change, enabling immediate detection and response.
    """

    def __init__(self, event_callback: Callable):
        """
        Initialize the watcher.

        Args:
            event_callback: Async function to call when a relevant event occurs.
                           Signature: async def callback(resource_type: str, event: dict)
        """
        self.event_callback = event_callback
        self._running = False
        self._watch_task: Optional[asyncio.Task] = None
        self._last_resource_version: Optional[str] = None

        # Initialize Kubernetes API clients (shared across watchers)
        try:
            from kubernetes import config
            config.load_incluster_config()
        except Exception:
            logger.warning("Not running in cluster, watch functionality disabled")

    @property
    @abstractmethod
    def resource_type(self) -> str:
        """Human-readable resource type (e.g., 'pod', 'event')."""
        pass

    @abstractmethod
    async def _watch_loop(self):
        """
        Main watch loop implementation.

        Subclasses must implement this to watch specific resources.
        """
        pass

    @abstractmethod
    def _should_process_event(self, event: dict) -> bool:
        """
        Determine if an event should trigger processing.

        Args:
            event: Kubernetes watch event dict with 'type' and 'object'

        Returns:
            True if event should be processed, False otherwise
        """
        pass

    async def start(self):
        """Start the watch loop."""
        if self._running:
            logger.warning(f"{self.resource_type} watcher already running")
            return

        self._running = True
        self._watch_task = asyncio.create_task(self._watch_loop())
        logger.info(
            f"{self.resource_type} watcher started",
            resource_type=self.resource_type
        )

    async def stop(self):
        """Stop the watch loop gracefully."""
        if not self._running:
            logger.warning(f"{self.resource_type} watcher not running")
            return

        self._running = False

        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

        logger.info(
            f"{self.resource_type} watcher stopped",
            resource_type=self.resource_type
        )

    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running

    async def _handle_watch_error(self, error: Exception):
        """
        Handle watch errors with exponential backoff.

        Args:
            error: The exception that occurred
        """
        logger.error(
            f"{self.resource_type} watch error: {error}",
            exc_info=True,
            resource_type=self.resource_type
        )

        # Exponential backoff before reconnecting
        await asyncio.sleep(5)

    async def _trigger_workflow(self, event_data: dict):
        """
        Trigger workflow engine for detected event.

        Args:
            event_data: Event data to pass to callback
        """
        try:
            logger.info(
                f"Triggering workflow for {self.resource_type} event",
                resource_type=self.resource_type,
                event_type=event_data.get('type'),
                resource_name=event_data.get('name')
            )

            await self.event_callback(self.resource_type, event_data)

        except Exception as e:
            logger.error(
                f"Failed to trigger workflow for {self.resource_type}: {e}",
                exc_info=True,
                resource_type=self.resource_type
            )
