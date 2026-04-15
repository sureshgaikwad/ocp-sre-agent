"""
Pod watcher for detecting pod failures in real-time.
"""

import asyncio
import logging
from typing import Callable
from kubernetes import client, watch
from .base import BaseWatcher

logger = logging.getLogger(__name__)


class PodWatcher(BaseWatcher):
    """
    Watches pods cluster-wide for failure conditions.

    Triggers on:
    - CrashLoopBackOff
    - OOMKilled
    - ImagePullBackOff
    - Error state
    - Failed phase
    """

    def __init__(self, event_callback: Callable):
        super().__init__(event_callback)
        self.core_api = client.CoreV1Api()

    @property
    def resource_type(self) -> str:
        return "pod"

    def _should_process_event(self, event: dict) -> bool:
        """
        Check if pod event indicates a problem.

        Args:
            event: Kubernetes watch event

        Returns:
            True if pod has failure condition
        """
        event_type = event.get('type')  # ADDED, MODIFIED, DELETED
        pod = event.get('object')

        if not pod or event_type == 'DELETED':
            return False

        # Skip system namespaces
        namespace = pod.metadata.namespace
        if namespace in ['kube-system', 'kube-public', 'kube-node-lease', 'openshift-*']:
            return False

        # Check pod status for failure conditions
        status = pod.status

        # Check container statuses
        if status.container_statuses:
            for container_status in status.container_statuses:
                # Waiting state with failure reasons
                if container_status.state and container_status.state.waiting:
                    reason = container_status.state.waiting.reason
                    if reason in [
                        'CrashLoopBackOff',
                        'ImagePullBackOff',
                        'ErrImagePull',
                        'CreateContainerConfigError',
                        'InvalidImageName'
                    ]:
                        return True

                # Terminated state with failure
                if container_status.state and container_status.state.terminated:
                    exit_code = container_status.state.terminated.exit_code
                    reason = container_status.state.terminated.reason

                    # OOMKilled or non-zero exit code
                    if reason == 'OOMKilled' or (exit_code and exit_code != 0):
                        return True

                # High restart count
                if container_status.restart_count and container_status.restart_count >= 3:
                    return True

        # Check pod phase
        if status.phase in ['Failed', 'Unknown']:
            return True

        return False

    async def _watch_loop(self):
        """
        Main watch loop for pods.

        Watches all pods cluster-wide and triggers workflow on failures.
        """
        w = watch.Watch()

        while self._running:
            try:
                logger.info("Starting pod watch stream")

                # Watch all pods across all namespaces
                stream = w.stream(
                    self.core_api.list_pod_for_all_namespaces,
                    timeout_seconds=300,  # Reconnect every 5 minutes
                    _request_timeout=310
                )

                async for event in self._async_watch_stream(stream):
                    if not self._running:
                        break

                    if self._should_process_event(event):
                        # Extract pod info
                        pod = event['object']
                        event_data = {
                            'type': event['type'],
                            'name': pod.metadata.name,
                            'namespace': pod.metadata.namespace,
                            'phase': pod.status.phase,
                            'conditions': self._extract_conditions(pod),
                            'container_statuses': self._extract_container_statuses(pod),
                            'uid': pod.metadata.uid,
                            'resource_version': pod.metadata.resource_version
                        }

                        # Trigger workflow asynchronously
                        await self._trigger_workflow(event_data)

                logger.info("Pod watch stream ended, reconnecting...")

            except asyncio.CancelledError:
                logger.info("Pod watch cancelled")
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
            # Yield control to allow cancellation
            await asyncio.sleep(0)

    def _extract_conditions(self, pod) -> list:
        """Extract pod conditions."""
        if not pod.status.conditions:
            return []

        return [
            {
                'type': cond.type,
                'status': cond.status,
                'reason': cond.reason,
                'message': cond.message
            }
            for cond in pod.status.conditions
        ]

    def _extract_container_statuses(self, pod) -> list:
        """Extract container status details."""
        if not pod.status.container_statuses:
            return []

        statuses = []
        for cs in pod.status.container_statuses:
            status = {
                'name': cs.name,
                'ready': cs.ready,
                'restart_count': cs.restart_count
            }

            # Current state
            if cs.state:
                if cs.state.waiting:
                    status['state'] = 'waiting'
                    status['reason'] = cs.state.waiting.reason
                    status['message'] = cs.state.waiting.message
                elif cs.state.running:
                    status['state'] = 'running'
                elif cs.state.terminated:
                    status['state'] = 'terminated'
                    status['exit_code'] = cs.state.terminated.exit_code
                    status['reason'] = cs.state.terminated.reason
                    status['message'] = cs.state.terminated.message

            statuses.append(status)

        return statuses
