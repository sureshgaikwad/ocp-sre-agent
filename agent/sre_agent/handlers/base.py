"""
Base handler class.

All handlers inherit from BaseHandler and implement the handle() method.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.models.diagnosis import Diagnosis
from sre_agent.models.remediation import RemediationResult


class BaseHandler(ABC):
    """
    Abstract base class for all remediation handlers.

    Handlers execute fixes based on Diagnoses and return RemediationResults.
    They MUST respect RBAC, human-in-the-loop requirements, and GitOps patterns.
    """

    def __init__(self, mcp_registry: "MCPToolRegistry", handler_name: str, tier: int):
        """
        Initialize handler.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift/Gitea tools
            handler_name: Name of this handler (for logging and remediation metadata)
            tier: Remediation tier (1=automated, 2=GitOps PR, 3=notification)
        """
        self.mcp_registry = mcp_registry
        self.handler_name = handler_name
        self.tier = tier

    @abstractmethod
    async def handle(self, diagnosis: Diagnosis) -> RemediationResult:
        """
        Handle a diagnosis and perform remediation.

        Args:
            diagnosis: The diagnosis to remediate

        Returns:
            RemediationResult indicating what was done and the outcome

        Raises:
            Exception: If remediation fails critically (handlers should catch and log errors)
        """
        pass

    @abstractmethod
    def can_handle(self, diagnosis: Diagnosis) -> bool:
        """
        Check if this handler can handle the given diagnosis.

        This is called before handle() to route diagnoses to appropriate handlers.

        Args:
            diagnosis: The diagnosis to check

        Returns:
            True if this handler can handle this diagnosis category/tier
        """
        pass

    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}({self.handler_name}, Tier {self.tier})"
