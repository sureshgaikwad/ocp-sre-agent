"""
Base collector class.

All collectors inherit from BaseCollector and implement the collect() method.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from sre_agent.models.observation import Observation
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class BaseCollector(ABC):
    """
    Abstract base class for all collectors.

    Collectors observe cluster state and return structured Observations.
    They use Kubernetes Python client for direct API access.
    """

    # Class-level Kubernetes clients (shared across all collectors)
    _k8s_initialized = False
    _core_api: Optional[client.CoreV1Api] = None
    _apps_api: Optional[client.AppsV1Api] = None
    _custom_api: Optional[client.CustomObjectsApi] = None
    _autoscaling_api: Optional[client.AutoscalingV2Api] = None

    def __init__(self, mcp_registry: "MCPToolRegistry", collector_name: str):
        """
        Initialize collector.

        Args:
            mcp_registry: MCP tool registry (kept for backward compatibility)
            collector_name: Name of this collector (for logging)
        """
        self.mcp_registry = mcp_registry
        self.collector_name = collector_name

        # Initialize Kubernetes clients on first use
        if not BaseCollector._k8s_initialized:
            self._init_kubernetes_clients()

    @classmethod
    def _init_kubernetes_clients(cls):
        """Initialize Kubernetes API clients (called once per process)."""
        try:
            # Load in-cluster configuration
            config.load_incluster_config()

            # Initialize API clients
            cls._core_api = client.CoreV1Api()
            cls._apps_api = client.AppsV1Api()
            cls._custom_api = client.CustomObjectsApi()
            cls._autoscaling_api = client.AutoscalingV2Api()

            cls._k8s_initialized = True
            logger.info("Kubernetes API clients initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes clients: {e}", exc_info=True)
            raise

    @property
    def core_api(self) -> client.CoreV1Api:
        """Get CoreV1Api client."""
        if not self._k8s_initialized:
            self._init_kubernetes_clients()
        return self.__class__._core_api

    @property
    def apps_api(self) -> client.AppsV1Api:
        """Get AppsV1Api client."""
        if not self._k8s_initialized:
            self._init_kubernetes_clients()
        return self.__class__._apps_api

    @property
    def custom_api(self) -> client.CustomObjectsApi:
        """Get CustomObjectsApi client."""
        if not self._k8s_initialized:
            self._init_kubernetes_clients()
        return self.__class__._custom_api

    @property
    def autoscaling_api(self) -> client.AutoscalingV2Api:
        """Get AutoscalingV2Api client."""
        if not self._k8s_initialized:
            self._init_kubernetes_clients()
        return self.__class__._autoscaling_api

    @abstractmethod
    async def collect(self) -> list[Observation]:
        """
        Collect observations from the cluster.

        Returns:
            List of Observation objects

        Raises:
            Exception: If collection fails (collectors should catch and log errors)
        """
        pass

    async def _call_oc(self, args: str) -> str:
        """
        Helper to call 'oc' command via MCP.

        Args:
            args: Arguments to 'oc' command (e.g., "get pods -n default -o json")

        Returns:
            Command output as string

        Raises:
            Exception: If MCP call fails
        """
        # Assuming MCP OpenShift server has an 'exec' or similar tool
        # This is a placeholder - actual implementation depends on MCP server capabilities
        raise NotImplementedError("Subclasses must implement _call_oc or use MCP tools directly")

    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}({self.collector_name})"
