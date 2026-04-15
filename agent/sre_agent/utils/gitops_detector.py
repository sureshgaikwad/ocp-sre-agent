"""
GitOps detector utility.

Detects if resources are managed by ArgoCD or other GitOps tools.
"""

import json
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


@dataclass
class GitOpsInfo:
    """
    Information about GitOps-managed resource.
    """
    is_managed: bool
    tool: Optional[str] = None  # "argocd", "flux", etc.
    application: Optional[str] = None  # ArgoCD Application name
    repo_url: Optional[str] = None
    path: Optional[str] = None  # Path in repo
    branch: Optional[str] = None
    sync_status: Optional[str] = None  # "Synced", "OutOfSync", etc.


class GitOpsDetector:
    """
    Detector for GitOps-managed resources.

    Checks for ArgoCD, Flux, and other GitOps tool annotations/labels.
    """

    # ArgoCD annotations
    ARGOCD_INSTANCE_ANNOTATION = "argocd.argoproj.io/instance"
    ARGOCD_TRACKING_ANNOTATION = "argocd.argoproj.io/tracking-id"
    ARGOCD_SYNC_STATUS_ANNOTATION = "argocd.argoproj.io/sync-status"

    # Flux annotations
    FLUX_RECONCILE_ANNOTATION = "fluxcd.io/reconcile"
    FLUX_RECONCILE_REQUEST_ANNOTATION = "reconcile.fluxcd.io/requestedAt"

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize GitOps detector.

        Args:
            mcp_registry: MCP tool registry for fetching resource metadata
        """
        self.mcp_registry = mcp_registry

    async def detect(
        self,
        resource_kind: str,
        resource_name: str,
        namespace: Optional[str] = None
    ) -> GitOpsInfo:
        """
        Detect if resource is GitOps-managed.

        Args:
            resource_kind: Resource kind (Deployment, ConfigMap, etc.)
            resource_name: Resource name
            namespace: Namespace (required for namespaced resources)

        Returns:
            GitOpsInfo with detection results

        Example:
            >>> info = await detector.detect("Deployment", "my-app", "default")
            >>> if info.is_managed:
            ...     print(f"Managed by {info.tool}: {info.repo_url}")
        """
        try:
            # Fetch resource metadata
            resource_data = await self._get_resource_metadata(
                resource_kind, resource_name, namespace
            )

            if not resource_data:
                logger.warning(
                    f"Could not fetch metadata for {resource_kind}/{resource_name}",
                    resource_kind=resource_kind,
                    resource_name=resource_name,
                    namespace=namespace
                )
                return GitOpsInfo(is_managed=False)

            # Check for ArgoCD
            argocd_info = self._check_argocd(resource_data)
            if argocd_info.is_managed:
                logger.info(
                    f"Resource {resource_kind}/{resource_name} is ArgoCD-managed",
                    resource_kind=resource_kind,
                    resource_name=resource_name,
                    namespace=namespace,
                    application=argocd_info.application
                )
                return argocd_info

            # Check for Flux
            flux_info = self._check_flux(resource_data)
            if flux_info.is_managed:
                logger.info(
                    f"Resource {resource_kind}/{resource_name} is Flux-managed",
                    resource_kind=resource_kind,
                    resource_name=resource_name,
                    namespace=namespace
                )
                return flux_info

            # Not managed by known GitOps tools
            logger.debug(
                f"Resource {resource_kind}/{resource_name} is not GitOps-managed",
                resource_kind=resource_kind,
                resource_name=resource_name,
                namespace=namespace
            )
            return GitOpsInfo(is_managed=False)

        except Exception as e:
            logger.error(
                f"GitOps detection failed for {resource_kind}/{resource_name}: {e}",
                resource_kind=resource_kind,
                resource_name=resource_name,
                namespace=namespace,
                exc_info=True
            )
            # Fail safe - assume not managed on error
            return GitOpsInfo(is_managed=False)

    async def _get_resource_metadata(
        self,
        resource_kind: str,
        resource_name: str,
        namespace: Optional[str]
    ) -> Optional[dict]:
        """
        Fetch resource metadata (annotations, labels) via MCP.

        Args:
            resource_kind: Resource kind
            resource_name: Resource name
            namespace: Namespace

        Returns:
            Resource data dict or None if fetch fails
        """
        # Build oc get command
        resource_type = resource_kind.lower()
        cmd_parts = ["oc", "get", resource_type, resource_name]

        if namespace:
            cmd_parts.extend(["-n", namespace])

        cmd_parts.extend(["-o", "json"])
        command = " ".join(cmd_parts)

        # Execute via MCP
        try:
            result = await self.mcp_registry.call_tool("exec", {
                "command": command
            })
            return json.loads(result)
        except Exception as e:
            logger.error(
                f"Failed to fetch resource metadata: {e}",
                command=command,
                exc_info=True
            )
            raise NotImplementedError(
                f"GitOpsDetector requires MCP OpenShift server with command execution. "
                f"Expected tool: 'exec'. Command would be: {command}"
            )

    def _check_argocd(self, resource_data: dict) -> GitOpsInfo:
        """
        Check if resource is managed by ArgoCD.

        Args:
            resource_data: Resource JSON data

        Returns:
            GitOpsInfo with ArgoCD details
        """
        metadata = resource_data.get("metadata", {})
        annotations = metadata.get("annotations", {})
        labels = metadata.get("labels", {})

        # Check for ArgoCD instance annotation
        if self.ARGOCD_INSTANCE_ANNOTATION not in annotations:
            return GitOpsInfo(is_managed=False)

        # Resource is ArgoCD-managed
        application = annotations.get(self.ARGOCD_INSTANCE_ANNOTATION)
        sync_status = annotations.get(self.ARGOCD_SYNC_STATUS_ANNOTATION)

        # Try to extract repo info from tracking annotation
        tracking_id = annotations.get(self.ARGOCD_TRACKING_ANNOTATION, "")
        repo_url = None
        path = None

        # Tracking ID format: <app-name>:<namespace>/<kind>/<name>
        # But doesn't contain repo URL, would need to query ArgoCD Application

        return GitOpsInfo(
            is_managed=True,
            tool="argocd",
            application=application,
            sync_status=sync_status,
            # Note: repo_url and path would require fetching the Application resource
            # For now, we just return the application name
        )

    def _check_flux(self, resource_data: dict) -> GitOpsInfo:
        """
        Check if resource is managed by Flux.

        Args:
            resource_data: Resource JSON data

        Returns:
            GitOpsInfo with Flux details
        """
        metadata = resource_data.get("metadata", {})
        annotations = metadata.get("annotations", {})
        labels = metadata.get("labels", {})

        # Check for Flux annotations
        has_flux_reconcile = self.FLUX_RECONCILE_ANNOTATION in annotations
        has_flux_request = self.FLUX_RECONCILE_REQUEST_ANNOTATION in annotations

        if not (has_flux_reconcile or has_flux_request):
            return GitOpsInfo(is_managed=False)

        # Resource is Flux-managed
        # Flux doesn't store repo URL in resource annotations
        # Would need to query Flux Kustomization or HelmRelease resources

        return GitOpsInfo(
            is_managed=True,
            tool="flux",
        )

    async def get_argocd_application_details(
        self,
        application_name: str,
        namespace: str = "argocd"
    ) -> Optional[dict]:
        """
        Fetch ArgoCD Application details to get repo URL and path.

        Args:
            application_name: ArgoCD Application name
            namespace: ArgoCD namespace (default: argocd)

        Returns:
            Application details dict or None

        Example:
            >>> details = await detector.get_argocd_application_details("my-app")
            >>> print(details["spec"]["source"]["repoURL"])
            https://github.com/org/repo
        """
        try:
            command = f"oc get application {application_name} -n {namespace} -o json"
            result = await self.mcp_registry.call_tool("exec", {
                "command": command
            })
            app_data = json.loads(result)

            # Extract source info
            spec = app_data.get("spec", {})
            source = spec.get("source", {})

            return {
                "repo_url": source.get("repoURL"),
                "path": source.get("path"),
                "target_revision": source.get("targetRevision"),
                "sync_status": app_data.get("status", {}).get("sync", {}).get("status"),
            }
        except Exception as e:
            logger.error(
                f"Failed to fetch ArgoCD Application {application_name}: {e}",
                application_name=application_name,
                namespace=namespace,
                exc_info=True
            )
            return None

    def detect_from_annotations(self, annotations: dict) -> GitOpsInfo:
        """
        Detect GitOps management from annotations dict.

        Useful when you already have resource metadata.

        Args:
            annotations: Resource annotations dict

        Returns:
            GitOpsInfo
        """
        # Check ArgoCD
        if self.ARGOCD_INSTANCE_ANNOTATION in annotations:
            return GitOpsInfo(
                is_managed=True,
                tool="argocd",
                application=annotations.get(self.ARGOCD_INSTANCE_ANNOTATION),
                sync_status=annotations.get(self.ARGOCD_SYNC_STATUS_ANNOTATION),
            )

        # Check Flux
        if self.FLUX_RECONCILE_ANNOTATION in annotations:
            return GitOpsInfo(
                is_managed=True,
                tool="flux",
            )

        return GitOpsInfo(is_managed=False)


# Singleton instance
_gitops_detector_instance: Optional[GitOpsDetector] = None


def get_gitops_detector(mcp_registry: Optional["MCPToolRegistry"] = None) -> GitOpsDetector:
    """
    Get GitOpsDetector singleton instance.

    Args:
        mcp_registry: MCP tool registry (required on first call)

    Returns:
        GitOpsDetector instance

    Raises:
        ValueError: If mcp_registry not provided on first call
    """
    global _gitops_detector_instance

    if _gitops_detector_instance is None:
        if mcp_registry is None:
            raise ValueError("mcp_registry required on first call to get_gitops_detector()")
        _gitops_detector_instance = GitOpsDetector(mcp_registry)

    return _gitops_detector_instance


if __name__ == "__main__":
    # Demo
    import asyncio

    async def demo():
        from mcp_client import MCPToolRegistry

        mcp_registry = MCPToolRegistry()
        detector = get_gitops_detector(mcp_registry)

        # Example: Check if deployment is ArgoCD-managed
        print("Demo GitOps detection:")
        print("Would check: oc get deployment my-app -n default -o json")
        print("Looking for ArgoCD annotations...")

        # Quick check from annotations
        test_annotations = {
            "argocd.argoproj.io/instance": "my-app",
            "argocd.argoproj.io/sync-status": "Synced"
        }
        info = detector.detect_from_annotations(test_annotations)
        print(f"Is managed: {info.is_managed}")
        print(f"Tool: {info.tool}")
        print(f"Application: {info.application}")

    asyncio.run(demo())
