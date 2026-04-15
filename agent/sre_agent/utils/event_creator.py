"""
Kubernetes Event Creator for OpenShift Console Alerts.

Creates Kubernetes Events that show up in OpenShift Console and `oc get events`.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from kubernetes import client
from kubernetes.client.rest import ApiException

from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class EventCreator:
    """Creates Kubernetes Events for observations and remediations."""

    def __init__(self):
        """Initialize Event Creator with Kubernetes API client."""
        try:
            self.core_api = client.CoreV1Api()
            logger.info("EventCreator initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize EventCreator: {e}", exc_info=True)
            self.core_api = None

    async def create_observation_event(
        self,
        namespace: str,
        resource_name: str,
        resource_kind: str,
        reason: str,
        message: str,
        severity: str = "Warning"
    ) -> bool:
        """
        Create Event when an issue is detected.

        Args:
            namespace: Namespace of the resource
            resource_name: Name of the resource
            resource_kind: Kind of resource (Pod, Deployment, etc.)
            reason: Short reason code (e.g., "OOMKilled", "CrashLoopBackOff")
            message: Detailed message
            severity: Event type (Normal or Warning)

        Returns:
            True if event created successfully
        """
        if not self.core_api:
            return False

        try:
            # Create event name (must be unique)
            now = datetime.now(timezone.utc)
            event_name = f"sre-agent-{resource_name}-{now.strftime('%s')}"

            event = client.CoreV1Event(
                metadata=client.V1ObjectMeta(
                    name=event_name,
                    namespace=namespace
                ),
                involved_object=client.V1ObjectReference(
                    kind=resource_kind,
                    name=resource_name,
                    namespace=namespace,
                    api_version="v1"
                ),
                reason=f"SREAgent{reason}",
                message=f"🔍 SRE Agent detected: {message}",
                type=severity,
                source=client.V1EventSource(component="sre-agent"),
                first_timestamp=now,
                last_timestamp=now,
                count=1
            )

            def _create_event():
                return self.core_api.create_namespaced_event(
                    namespace=namespace,
                    body=event
                )

            await asyncio.to_thread(_create_event)

            logger.info(
                f"Created observation event in OpenShift Console",
                namespace=namespace,
                resource=f"{resource_kind}/{resource_name}",
                reason=reason,
                event_name=event_name
            )
            return True

        except ApiException as e:
            # Events are best-effort - don't fail if we can't create them
            logger.warning(
                f"Failed to create observation event: {e.reason}",
                namespace=namespace,
                resource_name=resource_name,
                status_code=e.status,
                error_body=str(e.body) if hasattr(e, 'body') else None
            )
            return False
        except Exception as e:
            logger.warning(
                f"Unexpected error creating observation event: {e}",
                namespace=namespace,
                resource_name=resource_name
            )
            return False

    async def create_remediation_event(
        self,
        namespace: str,
        resource_name: str,
        resource_kind: str,
        action: str,
        result: str,
        success: bool = True
    ) -> bool:
        """
        Create Event when remediation is performed.

        Args:
            namespace: Namespace of the resource
            resource_name: Name of the resource
            resource_kind: Kind of resource
            action: Action taken (e.g., "MemoryIncreased", "IssueCreated")
            result: Result description
            success: Whether remediation succeeded

        Returns:
            True if event created successfully
        """
        if not self.core_api:
            return False

        try:
            now = datetime.now(timezone.utc)
            event_name = f"sre-agent-fix-{resource_name}-{now.strftime('%s')}"

            severity = "Normal" if success else "Warning"
            emoji = "✅" if success else "❌"

            event = client.CoreV1Event(
                metadata=client.V1ObjectMeta(
                    name=event_name,
                    namespace=namespace
                ),
                involved_object=client.V1ObjectReference(
                    kind=resource_kind,
                    name=resource_name,
                    namespace=namespace,
                    api_version="v1"
                ),
                reason=f"SREAgent{action}",
                message=f"{emoji} SRE Agent remediation: {result}",
                type=severity,
                source=client.V1EventSource(component="sre-agent"),
                first_timestamp=now,
                last_timestamp=now,
                count=1
            )

            def _create_event():
                return self.core_api.create_namespaced_event(
                    namespace=namespace,
                    body=event
                )

            await asyncio.to_thread(_create_event)

            logger.info(
                f"Created remediation event in OpenShift Console",
                namespace=namespace,
                resource=f"{resource_kind}/{resource_name}",
                action=action,
                success=success,
                event_name=event_name
            )
            return True

        except ApiException as e:
            logger.warning(
                f"Failed to create remediation event: {e.reason}",
                namespace=namespace,
                resource_name=resource_name,
                status_code=e.status,
                error_body=str(e.body) if hasattr(e, 'body') else None
            )
            return False
        except Exception as e:
            logger.warning(
                f"Unexpected error creating remediation event: {e}",
                namespace=namespace,
                resource_name=resource_name
            )
            return False


# Global singleton
_event_creator: Optional[EventCreator] = None


def get_event_creator() -> EventCreator:
    """Get or create global EventCreator instance."""
    global _event_creator
    if _event_creator is None:
        _event_creator = EventCreator()
    return _event_creator
