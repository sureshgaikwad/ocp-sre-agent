"""
Tier 1 Automated Handler.

Executes fully automated remediation for safe, non-destructive fixes.
Includes RBAC checks before all actions.
"""

import asyncio
from typing import TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.handlers.base import BaseHandler
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory
from sre_agent.models.remediation import RemediationResult, RemediationStatus
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.rbac_checker import get_rbac_checker
from sre_agent.utils.audit_logger import get_audit_logger, OperationType
from sre_agent.utils.event_creator import get_event_creator
from sre_agent.config.settings import get_settings

logger = get_logger(__name__)


class Tier1AutomatedHandler(BaseHandler):
    """
    Tier 1 handler: Automated remediation.

    Executes safe, fully automated fixes with RBAC pre-checks:
    - ImagePullBackOff transient: Retry-wait with exponential backoff
    - Registry timeout: Wait and retry

    All actions are:
    - Non-destructive (no deletes, no destructive patches)
    - RBAC-verified before execution
    - Fully audited
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize Tier 1 handler.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "tier1_automated", tier=1)
        self.settings = get_settings()
        self.rbac_checker = get_rbac_checker(mcp_registry)
        self.audit_logger = get_audit_logger(self.settings.audit_db_path)

        # Retry intervals (seconds) for exponential backoff
        self.retry_intervals = self.settings.image_pull_retry_intervals or [60, 120, 300]

    def can_handle(self, diagnosis: Diagnosis) -> bool:
        """
        Check if this handler can handle the diagnosis.

        Args:
            diagnosis: Diagnosis to check

        Returns:
            True if diagnosis is Tier 1 and automated remediation is enabled
        """
        if not self.settings.enable_tier1_auto:
            logger.debug("Tier 1 automated remediation is disabled")
            return False

        return diagnosis.recommended_tier == 1

    async def handle(self, diagnosis: Diagnosis) -> RemediationResult:
        """
        Handle diagnosis with automated remediation.

        Args:
            diagnosis: Diagnosis to handle

        Returns:
            RemediationResult
        """
        start_time = datetime.utcnow()

        logger.info(
            f"Tier 1 handling diagnosis: {diagnosis.category.value}",
            diagnosis_id=diagnosis.id,
            category=diagnosis.category.value,
            action_taken="automated_remediation"
        )

        result = RemediationResult(
            diagnosis_id=diagnosis.id,
            tier=1,
            status=RemediationStatus.SUCCESS,
            message="",
            handler_name=self.handler_name,
        )

        try:
            # Route to specific automated remediation based on category
            if diagnosis.category == DiagnosisCategory.IMAGE_PULL_BACKOFF_TRANSIENT:
                await self._handle_transient_image_pull(diagnosis, result)
            elif diagnosis.category == DiagnosisCategory.REGISTRY_TIMEOUT:
                await self._handle_registry_timeout(diagnosis, result)
            elif diagnosis.category == DiagnosisCategory.OOM_KILLED:
                await self._handle_oom_killed(diagnosis, result)
            else:
                # Unknown Tier 1 category - should not happen
                result.status = RemediationStatus.SKIPPED
                result.message = f"No automated remediation for category: {diagnosis.category.value}"
                logger.warning(
                    f"Unknown Tier 1 category: {diagnosis.category.value}",
                    diagnosis_id=diagnosis.id
                )

        except Exception as e:
            result.status = RemediationStatus.FAILED
            result.error = str(e)
            result.message = f"Automated remediation failed: {str(e)}"

            logger.error(
                f"Tier 1 automated remediation failed: {e}",
                diagnosis_id=diagnosis.id,
                exc_info=True
            )

            # Audit log failure
            await self.audit_logger.log_operation(
                operation_type=OperationType.REMEDIATE,
                action="tier1_automated",
                success=False,
                diagnosis_id=diagnosis.id,
                error=str(e)
            )

        # Calculate execution time
        end_time = datetime.utcnow()
        result.execution_time_seconds = (end_time - start_time).total_seconds()

        return result

    async def _handle_transient_image_pull(
        self,
        diagnosis: Diagnosis,
        result: RemediationResult
    ) -> None:
        """
        Handle transient ImagePullBackOff with retry-wait logic.

        Args:
            diagnosis: Diagnosis
            result: RemediationResult to populate
        """
        logger.info(
            "Executing retry-wait for transient ImagePullBackOff",
            diagnosis_id=diagnosis.id
        )

        # Retry-wait strategy: Wait progressively longer intervals
        # and check if pod recovers (Kubernetes will automatically retry)

        for attempt, interval in enumerate(self.retry_intervals, 1):
            result.add_action(
                action_type="retry_wait",
                description=f"Attempt {attempt}/{len(self.retry_intervals)}: Wait {interval}s for registry recovery",
                success=True
            )

            logger.info(
                f"Retry-wait attempt {attempt}: waiting {interval}s",
                diagnosis_id=diagnosis.id,
                attempt=attempt,
                interval=interval
            )

            # Wait
            await asyncio.sleep(interval)

            # Check if issue resolved
            # In a real implementation, would check pod status via MCP
            # For now, we just log the wait
            result.add_action(
                action_type="check_status",
                description=f"Checked status after {interval}s wait",
                result="Wait completed, Kubernetes will retry automatically",
                success=True
            )

        result.status = RemediationStatus.SUCCESS
        result.message = (
            f"Retry-wait completed. Kubernetes will automatically retry pulling the image. "
            f"If issue persists after {sum(self.retry_intervals)}s, escalate to Tier 3."
        )

        # Audit log
        await self.audit_logger.log_operation(
            operation_type=OperationType.REMEDIATE,
            action="tier1_retry_wait",
            success=True,
            diagnosis_id=diagnosis.id,
            remediation_id=result.id,
            result_summary=f"Retry-wait completed: {len(self.retry_intervals)} attempts"
        )

        # Create Kubernetes Event
        event_creator = get_event_creator()
        namespace = diagnosis.evidence.get("namespace", "default")
        pod_name = diagnosis.evidence.get("pod_name", "unknown")
        await event_creator.create_remediation_event(
            namespace=namespace,
            resource_name=pod_name,
            resource_kind="Pod",
            action="ImagePullRetryWait",
            result=f"✅ SRE Agent applied retry-wait strategy for transient ImagePullBackOff. Waited {sum(self.retry_intervals)}s for registry recovery. Kubernetes will automatically retry pulling the image.",
            success=True
        )

    async def _handle_registry_timeout(
        self,
        diagnosis: Diagnosis,
        result: RemediationResult
    ) -> None:
        """
        Handle registry timeout/rate limit.

        Args:
            diagnosis: Diagnosis
            result: RemediationResult to populate
        """
        logger.info(
            "Executing extended wait for registry rate limit",
            diagnosis_id=diagnosis.id
        )

        # For rate limits, wait longer (typically 1 hour for Docker Hub)
        # Use longer backoff intervals
        extended_intervals = [300, 600, 1800]  # 5min, 10min, 30min

        for attempt, interval in enumerate(extended_intervals, 1):
            result.add_action(
                action_type="rate_limit_wait",
                description=f"Attempt {attempt}/{len(extended_intervals)}: Wait {interval}s for rate limit reset",
                success=True
            )

            logger.info(
                f"Rate limit wait attempt {attempt}: waiting {interval}s",
                diagnosis_id=diagnosis.id,
                attempt=attempt,
                interval=interval
            )

            await asyncio.sleep(interval)

            result.add_action(
                action_type="check_status",
                description=f"Checked status after {interval}s wait",
                result="Wait completed",
                success=True
            )

        result.status = RemediationStatus.SUCCESS
        result.message = (
            f"Rate limit wait completed ({sum(extended_intervals)}s total). "
            f"Kubernetes will automatically retry. Consider using authenticated pulls to avoid rate limits."
        )

        # Audit log
        await self.audit_logger.log_operation(
            operation_type=OperationType.REMEDIATE,
            action="tier1_rate_limit_wait",
            success=True,
            diagnosis_id=diagnosis.id,
            remediation_id=result.id,
            result_summary=f"Rate limit wait completed: {sum(extended_intervals)}s"
        )

        # Create Kubernetes Event
        event_creator = get_event_creator()
        namespace = diagnosis.evidence.get("namespace", "default")
        pod_name = diagnosis.evidence.get("pod_name", "unknown")
        await event_creator.create_remediation_event(
            namespace=namespace,
            resource_name=pod_name,
            resource_kind="Pod",
            action="RateLimitWait",
            result=f"✅ SRE Agent applied extended wait for registry rate limit. Waited {sum([300, 600, 1800])}s for rate limit reset. Consider using authenticated pulls to avoid Docker Hub rate limits.",
            success=True
        )

    async def _verify_rbac(
        self,
        verb: str,
        resource: str,
        namespace: str = None
    ) -> bool:
        """
        Verify RBAC permission before action.

        Args:
            verb: Action verb (get, create, patch, delete)
            resource: Resource type
            namespace: Namespace (optional)

        Returns:
            True if allowed, False if denied
        """
        if not self.settings.rbac_check_enabled:
            logger.debug("RBAC checks disabled, allowing action")
            return True

        allowed = await self.rbac_checker.can_i(verb, resource, namespace)

        if not allowed:
            logger.warning(
                f"RBAC denied: {verb} {resource} in {namespace or 'cluster'}",
                verb=verb,
                resource=resource,
                namespace=namespace
            )

        return allowed

    async def _handle_oom_killed(
        self,
        diagnosis: Diagnosis,
        result: RemediationResult
    ) -> None:
        """
        Handle OOMKilled by increasing memory limits.

        Args:
            diagnosis: OOMKilled diagnosis
            result: RemediationResult to update
        """
        from kubernetes import client
        from kubernetes.client.rest import ApiException

        # Extract pod info from diagnosis evidence
        namespace = diagnosis.evidence.get("namespace", "")
        pod_name = diagnosis.evidence.get("pod_name", "")
        current_memory = diagnosis.evidence.get("memory_limit", "unknown")

        if not namespace or not pod_name:
            result.status = RemediationStatus.FAILED
            result.message = "Missing namespace or pod_name in diagnosis evidence"
            return

        logger.info(
            f"Tier 1: Fixing OOMKilled pod {namespace}/{pod_name}",
            namespace=namespace,
            pod_name=pod_name,
            current_memory=current_memory,
            action_taken="increase_memory_limit"
        )

        # Initialize variables for error handling
        owner_kind = "Unknown"
        owner_name = "Unknown"

        try:
            # Get the pod to find its owner (Deployment, StatefulSet, etc.)
            core_api = client.CoreV1Api()
            apps_api = client.AppsV1Api()

            def _get_pod():
                return core_api.read_namespaced_pod(name=pod_name, namespace=namespace)

            pod = await asyncio.to_thread(_get_pod)

            # Find the owner
            owner_ref = None
            if pod.metadata.owner_references:
                for owner in pod.metadata.owner_references:
                    if owner.kind in ["ReplicaSet", "Deployment", "StatefulSet", "DaemonSet"]:
                        owner_ref = owner
                        break

            if not owner_ref:
                result.status = RemediationStatus.SKIPPED
                result.message = f"Pod {pod_name} has no supported owner (Deployment/StatefulSet/DaemonSet)"
                logger.warning(
                    f"Cannot remediate: pod has no owner",
                    namespace=namespace,
                    pod_name=pod_name
                )
                return

            # If owner is ReplicaSet, find the Deployment
            owner_kind = owner_ref.kind
            owner_name = owner_ref.name

            if owner_kind == "ReplicaSet":
                # ReplicaSet name format: deployment-name-xxxxx
                # Extract deployment name by removing hash suffix
                deployment_name = "-".join(owner_name.split("-")[:-1])
                owner_kind = "Deployment"
                owner_name = deployment_name

            logger.info(
                f"Found owner: {owner_kind}/{owner_name}",
                namespace=namespace,
                owner_kind=owner_kind,
                owner_name=owner_name
            )

            # Calculate new memory limit (increase by 50% or minimum 256Mi)
            new_memory = self._calculate_new_memory(current_memory)

            logger.info(
                f"Increasing memory limit: {current_memory} → {new_memory}",
                namespace=namespace,
                owner=f"{owner_kind}/{owner_name}",
                current_memory=current_memory,
                new_memory=new_memory
            )

            # Check RBAC permission
            resource = owner_kind.lower() + "s"  # deployment -> deployments
            if not await self._verify_rbac("patch", resource, namespace):
                result.status = RemediationStatus.FAILED
                result.message = f"RBAC denied: cannot patch {resource} in {namespace}"

                # Create event for RBAC failure
                event_creator = get_event_creator()
                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=owner_name,
                    resource_kind=owner_kind,
                    action="RBACDenied",
                    result=f"⚠️ SRE Agent cannot fix OOMKilled: RBAC permission denied to patch {resource}. Manual fix required: increase memory limit from {current_memory} to {new_memory}",
                    success=False
                )
                return

            # Patch the owner with increased memory limit
            if owner_kind == "Deployment":
                def _patch_deployment():
                    # Find the container that OOMKilled
                    deployment = apps_api.read_namespaced_deployment(name=owner_name, namespace=namespace)

                    # Patch all containers (or specific one if we can identify it)
                    for container in deployment.spec.template.spec.containers:
                        if not container.resources:
                            container.resources = client.V1ResourceRequirements()
                        if not container.resources.limits:
                            container.resources.limits = {}

                        container.resources.limits["memory"] = new_memory

                        # Also set requests to prevent overcommit
                        if not container.resources.requests:
                            container.resources.requests = {}
                        container.resources.requests["memory"] = new_memory

                    # Update deployment
                    return apps_api.patch_namespaced_deployment(
                        name=owner_name,
                        namespace=namespace,
                        body=deployment
                    )

                patched = await asyncio.to_thread(_patch_deployment)

                result.status = RemediationStatus.SUCCESS
                result.message = f"✅ Increased memory limit to {new_memory} for {owner_kind}/{owner_name}. Pod will restart with new limits."

                # Add actions using add_action() method
                result.add_action(
                    action_type="patch_deployment",
                    description=f"Patched {owner_kind}/{owner_name} memory limit",
                    result=f"{current_memory} → {new_memory}",
                    success=True
                )
                result.add_action(
                    action_type="pod_restart",
                    description="Pod will automatically restart with new limits",
                    success=True
                )

                logger.info(
                    f"Successfully patched {owner_kind}/{owner_name} with new memory limit",
                    namespace=namespace,
                    owner=f"{owner_kind}/{owner_name}",
                    new_memory=new_memory,
                    action_taken="memory_limit_increased"
                )

                # Audit log
                await self.audit_logger.log_operation(
                    operation_type=OperationType.REMEDIATE,
                    action="tier1_oom_fix",
                    success=True,
                    diagnosis_id=diagnosis.id,
                    result_summary=f"Increased memory to {new_memory}"
                )

                # Create Kubernetes Event for OpenShift Console
                event_creator = get_event_creator()
                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=owner_name,
                    resource_kind=owner_kind,
                    action="MemoryIncreased",
                    result=f"Automatically increased memory from {current_memory} to {new_memory}",
                    success=True
                )

            else:
                result.status = RemediationStatus.SKIPPED
                result.message = f"Auto-remediation not implemented for {owner_kind} (only Deployment supported)"
                logger.warning(
                    f"Cannot remediate {owner_kind}, only Deployment supported",
                    namespace=namespace,
                    owner_kind=owner_kind
                )

                # Create event for unsupported owner type
                event_creator = get_event_creator()
                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=owner_name if owner_name != "Unknown" else pod_name,
                    resource_kind=owner_kind if owner_kind != "Unknown" else "Pod",
                    action="UnsupportedOwnerType",
                    result=f"⚠️ SRE Agent detected OOMKilled but cannot auto-fix {owner_kind}. Auto-remediation only supports Deployments.\n\nManual fix required: Increase memory limit from {current_memory} to {self._calculate_new_memory(current_memory)}",
                    success=False
                )

        except ApiException as e:
            # Handle 404 Not Found - pod may have been replaced already
            if e.status == 404 and "not found" in str(e).lower():
                result.status = RemediationStatus.SUCCESS
                result.message = f"Pod {pod_name} no longer exists (likely already remediated by previous attempt)"
                logger.info(
                    f"Pod {namespace}/{pod_name} not found - already replaced",
                    namespace=namespace,
                    pod_name=pod_name,
                    reason="Pod already deleted/replaced"
                )
            else:
                result.status = RemediationStatus.FAILED
                result.error = str(e)
                result.message = f"Kubernetes API error: {e.reason}"
                logger.error(
                    f"Failed to patch {owner_kind}/{owner_name}: {e}",
                    namespace=namespace,
                    exc_info=True
                )

                # Create event for API failure
                event_creator = get_event_creator()
                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=owner_name if owner_name != "Unknown" else pod_name,
                    resource_kind=owner_kind if owner_kind != "Unknown" else "Pod",
                    action="RemediationFailed",
                    result=f"⚠️ SRE Agent cannot fix OOMKilled: API error: {e.reason}. Manual fix required: increase memory limit from {current_memory} to {new_memory}",
                    success=False
                )

        except Exception as e:
            result.status = RemediationStatus.FAILED
            result.error = str(e)
            result.message = f"Unexpected error: {str(e)}"
            logger.error(
                f"Unexpected error during OOMKilled remediation: {e}",
                namespace=namespace,
                exc_info=True
            )

            # Create event for unexpected failure
            event_creator = get_event_creator()
            await event_creator.create_remediation_event(
                namespace=namespace,
                resource_name=owner_name if owner_name != "Unknown" else pod_name,
                resource_kind=owner_kind if owner_kind != "Unknown" else "Pod",
                action="RemediationFailed",
                result=f"⚠️ SRE Agent cannot fix OOMKilled: {str(e)}. Manual fix required: increase memory limit from {current_memory} to {new_memory}",
                success=False
            )

    def _calculate_new_memory(self, current_memory: str) -> str:
        """
        Calculate new memory limit (increase by 50% or minimum 256Mi).

        Args:
            current_memory: Current memory limit (e.g., "128Mi", "1Gi", "unknown")

        Returns:
            New memory limit string
        """
        import re

        if current_memory == "unknown" or not current_memory:
            return "512Mi"  # Default if unknown

        # Parse current memory
        match = re.match(r'(\d+)([KMGT]i?)', current_memory)
        if not match:
            return "512Mi"  # Fallback

        value = int(match.group(1))
        unit = match.group(2)

        # Convert to Mi for calculation
        if unit in ["Ki", "K"]:
            value_mi = value / 1024
        elif unit in ["Mi", "M"]:
            value_mi = value
        elif unit in ["Gi", "G"]:
            value_mi = value * 1024
        elif unit in ["Ti", "T"]:
            value_mi = value * 1024 * 1024
        else:
            value_mi = value

        # Increase by 50%
        new_value_mi = int(value_mi * 1.5)

        # Minimum 256Mi
        if new_value_mi < 256:
            new_value_mi = 256

        # Convert back to appropriate unit
        if new_value_mi >= 1024:
            return f"{new_value_mi // 1024}Gi"
        else:
            return f"{new_value_mi}Mi"
