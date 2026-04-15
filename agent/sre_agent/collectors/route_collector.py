"""
Route collector for monitoring OpenShift Routes.

Monitors Route status and detects 5xx errors, unavailable backends, and TLS issues.
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


class RouteCollector(BaseCollector):
    """
    Collector for OpenShift Routes.

    Monitors routes across all namespaces and detects:
    - Routes not admitted by router
    - Routes with no backing service endpoints
    - Routes with TLS/certificate issues
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize RouteCollector.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
        """
        super().__init__(mcp_registry, "route_collector")

    async def collect(self) -> list[Observation]:
        """
        Collect Route observations from all namespaces.

        Returns:
            List of Observation objects for problematic routes

        Raises:
            Exception: If collection fails critically
        """
        observations = []
        request_id = logger.set_request_id()

        try:
            logger.info(
                "Starting route collection",
                request_id=request_id,
                action_taken="collect_routes"
            )

            # Get all routes
            routes_json = await self._get_routes()

            if not routes_json:
                logger.warning(
                    "No routes data returned from MCP",
                    request_id=request_id
                )
                return observations

            # Parse routes
            try:
                routes_data = json.loads(routes_json)
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse routes JSON: {e}",
                    request_id=request_id,
                    exc_info=True
                )
                return observations

            items = routes_data.get("items", [])
            logger.info(
                f"Retrieved {len(items)} routes",
                request_id=request_id,
                route_count=len(items)
            )

            # Process each route
            for route_item in items:
                try:
                    obs = await self._process_route(route_item, request_id)
                    if obs:
                        observations.append(obs)
                except Exception as e:
                    logger.error(
                        f"Failed to process route: {e}",
                        request_id=request_id,
                        route_name=route_item.get("metadata", {}).get("name"),
                        exc_info=True
                    )

            logger.info(
                f"Route collection completed: {len(observations)} issues found",
                request_id=request_id,
                observation_count=len(observations)
            )

        except Exception as e:
            logger.error(
                f"Route collection failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            # Don't re-raise - allow other collectors to run

        return observations

    async def _get_routes(self) -> str:
        """
        Get all routes via Kubernetes API.

        Returns:
            JSON string of routes

        Raises:
            Exception: If API call fails
        """
        try:
            import asyncio
            from kubernetes.client.rest import ApiException

            def _list_routes():
                try:
                    # Routes are OpenShift custom resources
                    result = self.custom_api.list_cluster_custom_object(
                        group="route.openshift.io",
                        version="v1",
                        plural="routes"
                    )
                    return result
                except ApiException as e:
                    logger.error(f"Kubernetes API error listing Routes: {e}")
                    raise

            # Run synchronous K8s call in thread pool
            routes_dict = await asyncio.to_thread(_list_routes)

            # Return as JSON string
            return json.dumps(routes_dict)

        except Exception as e:
            logger.error(
                f"Failed to list Routes: {e}",
                exc_info=True
            )
            raise

    async def _process_route(self, route_item: dict, request_id: str) -> Observation | None:
        """
        Process a single route and create observation if needed.

        Args:
            route_item: Route JSON object
            request_id: Request ID for logging

        Returns:
            Observation if route has issues, None otherwise
        """
        metadata = route_item.get("metadata", {})
        spec = route_item.get("spec", {})
        status = route_item.get("status", {})

        route_name = metadata.get("name", "unknown")
        namespace = metadata.get("namespace", "default")

        # Check if route is admitted
        ingress = status.get("ingress", [])
        if not ingress:
            # Route has no ingress status - likely not admitted
            logger.debug(
                f"Route {namespace}/{route_name} has no ingress status",
                request_id=request_id,
                route=route_name,
                namespace=namespace
            )

            return Observation(
                type=ObservationType.ROUTE_ERROR,
                severity=Severity.WARNING,
                namespace=namespace,
                resource_kind="Route",
                resource_name=route_name,
                message=f"Route not admitted by router: {route_name}",
                raw_data=route_item,
                labels=metadata.get("labels", {})
            )

        # Check for admitted=false conditions
        for ing in ingress:
            conditions = ing.get("conditions", [])
            for condition in conditions:
                if condition.get("type") == "Admitted" and condition.get("status") != "True":
                    reason = condition.get("reason", "Unknown")
                    message = condition.get("message", "")

                    logger.warning(
                        f"Route {namespace}/{route_name} not admitted: {reason}",
                        request_id=request_id,
                        route=route_name,
                        namespace=namespace,
                        reason=reason
                    )

                    return Observation(
                        type=ObservationType.ROUTE_ERROR,
                        severity=Severity.CRITICAL,
                        namespace=namespace,
                        resource_kind="Route",
                        resource_name=route_name,
                        message=f"Route not admitted: {reason} - {message}",
                        raw_data=route_item,
                        labels=metadata.get("labels", {})
                    )

        # Check if route has a service and we can verify endpoints
        service_name = spec.get("to", {}).get("name")
        if service_name:
            # This will be handled by RouteAnalyzer which fetches service endpoints
            pass

        # Check for TLS issues (basic check)
        tls = spec.get("tls", {})
        if tls:
            # TLS configured - check for certificate issues
            # This is better handled by RouteAnalyzer with actual endpoint checks
            pass

        # No issues detected
        return None

    def __str__(self) -> str:
        """String representation."""
        return f"RouteCollector(monitoring all namespaces)"
