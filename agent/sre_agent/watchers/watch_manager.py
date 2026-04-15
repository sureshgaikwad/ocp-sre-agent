"""
Watch manager for coordinating multiple Kubernetes watchers.
"""

import asyncio
import logging
from typing import List, Callable, Optional
from .pod_watcher import PodWatcher
from .event_watcher import EventWatcher

logger = logging.getLogger(__name__)


class WatchManager:
    """
    Manages multiple Kubernetes resource watchers.

    Coordinates starting, stopping, and health monitoring of watchers.
    """

    def __init__(self, event_callback: Callable):
        """
        Initialize watch manager.

        Args:
            event_callback: Async function called when any watcher detects an event.
                           Signature: async def callback(resource_type: str, event_data: dict)
        """
        self.event_callback = event_callback
        self.watchers: List = []
        self._running = False

        # Initialize watchers
        self.watchers.append(PodWatcher(event_callback))
        self.watchers.append(EventWatcher(event_callback))

        logger.info(f"Watch manager initialized with {len(self.watchers)} watchers")

    async def start_all(self):
        """Start all watchers."""
        if self._running:
            logger.warning("Watch manager already running")
            return

        self._running = True

        logger.info(f"Starting {len(self.watchers)} watchers...")

        # Start all watchers concurrently
        start_tasks = [watcher.start() for watcher in self.watchers]
        await asyncio.gather(*start_tasks)

        logger.info(
            "All watchers started",
            watcher_count=len(self.watchers),
            watcher_types=[w.resource_type for w in self.watchers]
        )

    async def stop_all(self):
        """Stop all watchers gracefully."""
        if not self._running:
            logger.warning("Watch manager not running")
            return

        self._running = False

        logger.info(f"Stopping {len(self.watchers)} watchers...")

        # Stop all watchers concurrently
        stop_tasks = [watcher.stop() for watcher in self.watchers]
        await asyncio.gather(*stop_tasks, return_exceptions=True)

        logger.info("All watchers stopped")

    def is_running(self) -> bool:
        """Check if watch manager is running."""
        return self._running

    def get_stats(self) -> dict:
        """
        Get statistics for all watchers.

        Returns:
            Dictionary with watcher statistics
        """
        return {
            'running': self._running,
            'watcher_count': len(self.watchers),
            'watchers': [
                {
                    'type': watcher.resource_type,
                    'running': watcher.is_running()
                }
                for watcher in self.watchers
            ]
        }
