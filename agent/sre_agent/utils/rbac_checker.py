"""
RBAC checker utility.

Verifies permissions before executing privileged operations using 'oc auth can-i'.
"""

import asyncio
from typing import Optional, TYPE_CHECKING
from datetime import datetime, timedelta

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class RBACChecker:
    """
    RBAC permission checker.

    Verifies permissions before privileged operations using 'oc auth can-i'.
    Caches results to avoid excessive API calls.
    """

    def __init__(self, mcp_registry: "MCPToolRegistry", cache_ttl_seconds: int = 300):
        """
        Initialize RBAC checker.

        Args:
            mcp_registry: MCP tool registry for calling oc commands
            cache_ttl_seconds: Cache TTL in seconds (default: 5 minutes)
        """
        self.mcp_registry = mcp_registry
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[bool, datetime]] = {}  # key -> (result, timestamp)

    async def can_i(
        self,
        verb: str,
        resource: str,
        namespace: Optional[str] = None,
        resource_name: Optional[str] = None,
        use_cache: bool = True
    ) -> bool:
        """
        Check if current service account can perform action.

        Args:
            verb: Action to check (get, list, create, update, patch, delete)
            resource: Resource type (pod, deployment, configmap, etc.)
            namespace: Namespace (None for cluster-scoped)
            resource_name: Specific resource name (optional)
            use_cache: Whether to use cached results

        Returns:
            True if allowed, False if denied

        Example:
            >>> await checker.can_i("delete", "pod", namespace="default")
            True
            >>> await checker.can_i("delete", "clusterrole")
            False
        """
        # Build cache key
        cache_key = self._build_cache_key(verb, resource, namespace, resource_name)

        # Check cache
        if use_cache and cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            age = (datetime.utcnow() - timestamp).total_seconds()
            if age < self.cache_ttl_seconds:
                logger.debug(
                    f"RBAC cache hit: {cache_key} = {result} (age: {age:.0f}s)",
                    verb=verb,
                    resource=resource,
                    namespace=namespace,
                    cached=True
                )
                return result

        # Execute oc auth can-i
        try:
            result = await self._execute_can_i(verb, resource, namespace, resource_name)

            # Cache result
            self._cache[cache_key] = (result, datetime.utcnow())

            logger.info(
                f"RBAC check: {verb} {resource} = {result}",
                verb=verb,
                resource=resource,
                namespace=namespace,
                resource_name=resource_name,
                allowed=result,
                cached=False
            )

            return result

        except Exception as e:
            logger.error(
                f"RBAC check failed: {e}",
                verb=verb,
                resource=resource,
                namespace=namespace,
                exc_info=True
            )
            # Fail closed - deny on error
            return False

    async def _execute_can_i(
        self,
        verb: str,
        resource: str,
        namespace: Optional[str],
        resource_name: Optional[str]
    ) -> bool:
        """
        Execute RBAC check using Kubernetes SelfSubjectAccessReview API.

        Args:
            verb: Action verb
            resource: Resource type
            namespace: Namespace (optional)
            resource_name: Resource name (optional)

        Returns:
            True if allowed, False if denied

        Raises:
            Exception: If API call fails
        """
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException

        # Load in-cluster config
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()

        # Create authorization API client
        auth_api = client.AuthorizationV1Api()

        # Build ResourceAttributes
        resource_attributes = client.V1ResourceAttributes(
            verb=verb,
            resource=resource,
            namespace=namespace,
            name=resource_name
        )

        # Create SelfSubjectAccessReview
        access_review = client.V1SelfSubjectAccessReview(
            spec=client.V1SelfSubjectAccessReviewSpec(
                resource_attributes=resource_attributes
            )
        )

        # Execute check
        try:
            # Run in thread to avoid blocking
            import asyncio
            response = await asyncio.to_thread(
                auth_api.create_self_subject_access_review,
                access_review
            )

            # Check if allowed
            allowed = response.status.allowed

            logger.debug(
                f"SelfSubjectAccessReview: {verb} {resource} = {allowed}",
                verb=verb,
                resource=resource,
                namespace=namespace,
                name=resource_name,
                allowed=allowed,
                reason=response.status.reason if hasattr(response.status, 'reason') else None
            )

            return allowed

        except ApiException as e:
            logger.error(
                f"SelfSubjectAccessReview failed: {e.status} - {e.reason}",
                verb=verb,
                resource=resource,
                namespace=namespace,
                exc_info=True
            )
            # Fail closed on API errors
            return False

    def _build_cache_key(
        self,
        verb: str,
        resource: str,
        namespace: Optional[str],
        resource_name: Optional[str]
    ) -> str:
        """
        Build cache key for permission check.

        Args:
            verb: Action verb
            resource: Resource type
            namespace: Namespace
            resource_name: Resource name

        Returns:
            Cache key string
        """
        parts = [verb, resource]
        if namespace:
            parts.append(f"ns:{namespace}")
        if resource_name:
            parts.append(f"name:{resource_name}")
        return ":".join(parts)

    def clear_cache(self) -> None:
        """Clear the permission cache."""
        cache_size = len(self._cache)
        self._cache.clear()
        logger.info(f"RBAC cache cleared ({cache_size} entries)")

    def get_cache_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache size and oldest entry age
        """
        if not self._cache:
            return {"size": 0, "oldest_age_seconds": 0}

        now = datetime.utcnow()
        oldest_age = max(
            (now - timestamp).total_seconds()
            for _, timestamp in self._cache.values()
        )

        return {
            "size": len(self._cache),
            "oldest_age_seconds": oldest_age,
        }

    async def verify_required_permissions(
        self,
        required_permissions: list[tuple[str, str, Optional[str]]]
    ) -> dict[str, bool]:
        """
        Verify multiple required permissions at once.

        Args:
            required_permissions: List of (verb, resource, namespace) tuples

        Returns:
            Dict mapping permission string to bool result

        Example:
            >>> perms = [
            ...     ("delete", "pod", "default"),
            ...     ("patch", "deployment", "default"),
            ... ]
            >>> results = await checker.verify_required_permissions(perms)
            >>> print(results)
            {'delete pod (default)': True, 'patch deployment (default)': False}
        """
        results = {}

        for verb, resource, namespace in required_permissions:
            key = f"{verb} {resource}"
            if namespace:
                key += f" ({namespace})"

            allowed = await self.can_i(verb, resource, namespace)
            results[key] = allowed

        return results


# Global singleton instance
_rbac_checker: Optional[RBACChecker] = None


def get_rbac_checker(mcp_registry: "MCPToolRegistry") -> RBACChecker:
    """
    Get global RBAC checker instance.

    Args:
        mcp_registry: MCP tool registry

    Returns:
        RBACChecker instance
    """
    global _rbac_checker
    if _rbac_checker is None:
        _rbac_checker = RBACChecker(mcp_registry)
    return _rbac_checker


if __name__ == "__main__":
    # Demo
    async def demo():
        from mcp_client import MCPToolRegistry

        mcp_registry = MCPToolRegistry()
        checker = RBACChecker(mcp_registry)

        # Example checks
        print("Demo RBAC checks:")
        print(f"Can delete pod in default? (would check via MCP)")
        print(f"Can patch deployment in default? (would check via MCP)")
        print(f"Can create clusterrole? (would check via MCP)")

        # Cache stats
        stats = checker.get_cache_stats()
        print(f"\nCache stats: {stats}")

    asyncio.run(demo())
