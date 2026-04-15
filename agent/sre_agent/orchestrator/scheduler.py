"""
Scheduler for background periodic collection.

Runs workflow engine on configured intervals for continuous monitoring.
"""

import asyncio
from datetime import datetime
from typing import Optional

from sre_agent.orchestrator.workflow_engine import WorkflowEngine
from sre_agent.utils.json_logger import get_logger
from sre_agent.config.settings import get_settings

logger = get_logger(__name__)


class Scheduler:
    """
    Background scheduler for continuous monitoring.

    Runs the workflow engine periodically based on configured intervals.
    Supports graceful shutdown and health checks.
    """

    def __init__(self, workflow_engine: WorkflowEngine):
        """
        Initialize scheduler.

        Args:
            workflow_engine: Workflow engine to execute periodically
        """
        self.workflow_engine = workflow_engine
        self.settings = get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run: Optional[datetime] = None
        self._total_runs = 0
        self._failed_runs = 0

    async def start(self) -> None:
        """
        Start the scheduler.

        Begins background task that runs workflow engine periodically.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())

        logger.info(
            "Scheduler started",
            mode=self.settings.mode,
            event_interval=self.settings.event_collection_interval,
            cluster_operator_interval=self.settings.cluster_operator_interval,
            mcp_interval=self.settings.machine_config_pool_interval
        )

    async def stop(self) -> None:
        """
        Stop the scheduler gracefully.

        Waits for current workflow execution to complete.
        """
        if not self._running:
            logger.warning("Scheduler not running")
            return

        logger.info("Stopping scheduler...")
        self._running = False

        if self._task:
            # Wait for current execution to complete (with timeout)
            try:
                await asyncio.wait_for(self._task, timeout=60.0)
            except asyncio.TimeoutError:
                logger.warning("Scheduler stop timeout, cancelling task")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        logger.info(
            "Scheduler stopped",
            total_runs=self._total_runs,
            failed_runs=self._failed_runs
        )

    async def _run_loop(self) -> None:
        """
        Main scheduler loop.

        Runs workflow engine periodically until stopped.
        """
        # Use the shortest interval as the tick rate
        # This ensures we don't miss any scheduled runs
        tick_interval = min(
            self.settings.event_collection_interval,
            self.settings.cluster_operator_interval,
            self.settings.machine_config_pool_interval,
            self.settings.pod_collection_interval,
            self.settings.route_collection_interval,
            self.settings.build_collection_interval,
            self.settings.networking_collection_interval,
            self.settings.autoscaling_collection_interval,
            self.settings.proactive_collection_interval,
        )

        logger.info(
            f"Scheduler loop starting with {tick_interval}s tick interval",
            tick_interval=tick_interval
        )

        # Track last run time for each interval type
        last_runs = {
            "event": None,
            "cluster_operator": None,
            "machine_config_pool": None,
            "pod": None,
            "route": None,
            "build": None,
            "networking": None,
            "autoscaling": None,
            "proactive": None,
        }

        while self._running:
            try:
                current_time = datetime.utcnow()

                # Check if it's time to run a workflow
                # In Phase 2, we run all collectors together
                # In future phases, we could run them on different schedules
                should_run = self._should_run_workflow(current_time, last_runs)

                if should_run:
                    logger.info("Running scheduled workflow execution")
                    try:
                        stats = await self.workflow_engine.run_workflow()
                        self._last_run = current_time
                        self._total_runs += 1

                        # Update last run times
                        for interval_type in last_runs.keys():
                            last_runs[interval_type] = current_time

                        logger.info(
                            "Scheduled workflow execution complete",
                            **stats
                        )
                    except Exception as e:
                        self._failed_runs += 1
                        logger.error(
                            f"Scheduled workflow execution failed: {e}",
                            exc_info=True,
                            total_runs=self._total_runs,
                            failed_runs=self._failed_runs
                        )

                # Sleep until next tick
                await asyncio.sleep(tick_interval)

            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(
                    f"Scheduler loop error: {e}",
                    exc_info=True
                )
                # Continue running despite errors
                await asyncio.sleep(tick_interval)

    def _should_run_workflow(self, current_time: datetime, last_runs: dict) -> bool:
        """
        Determine if workflow should run based on intervals.

        Args:
            current_time: Current time
            last_runs: Dict of last run times for each interval type

        Returns:
            True if workflow should run, False otherwise
        """
        # For Phase 2, we run all collectors together on the shortest interval
        # In the future, this could be more sophisticated

        # If this is the first run, run immediately
        if all(t is None for t in last_runs.values()):
            return True

        # Check if any interval has elapsed
        intervals = {
            "event": self.settings.event_collection_interval,
            "cluster_operator": self.settings.cluster_operator_interval,
            "machine_config_pool": self.settings.machine_config_pool_interval,
            "pod": self.settings.pod_collection_interval,
            "route": self.settings.route_collection_interval,
            "build": self.settings.build_collection_interval,
            "networking": self.settings.networking_collection_interval,
            "autoscaling": self.settings.autoscaling_collection_interval,
            "proactive": self.settings.proactive_collection_interval,
        }

        for interval_type, interval_seconds in intervals.items():
            last_run = last_runs.get(interval_type)
            if last_run is None:
                return True

            elapsed = (current_time - last_run).total_seconds()
            if elapsed >= interval_seconds:
                logger.debug(
                    f"Interval {interval_type} elapsed ({elapsed:.0f}s >= {interval_seconds}s)",
                    interval_type=interval_type,
                    elapsed=elapsed,
                    interval=interval_seconds
                )
                return True

        return False

    def is_running(self) -> bool:
        """
        Check if scheduler is running.

        Returns:
            True if running, False otherwise
        """
        return self._running

    def get_stats(self) -> dict:
        """
        Get scheduler statistics.

        Returns:
            Dict with run counts, last run time, etc.
        """
        return {
            "running": self._running,
            "total_runs": self._total_runs,
            "failed_runs": self._failed_runs,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "uptime_seconds": (
                (datetime.utcnow() - self._last_run).total_seconds()
                if self._last_run
                else None
            ),
        }

    async def trigger_immediate_run(self) -> dict:
        """
        Trigger an immediate workflow run (outside of schedule).

        Useful for manual triggers or on-demand execution.

        Returns:
            Workflow execution statistics
        """
        logger.info("Triggering immediate workflow run")

        try:
            stats = await self.workflow_engine.run_workflow()
            self._last_run = datetime.utcnow()
            self._total_runs += 1

            logger.info("Immediate workflow run complete", **stats)
            return stats

        except Exception as e:
            self._failed_runs += 1
            logger.error(
                f"Immediate workflow run failed: {e}",
                exc_info=True
            )
            raise
