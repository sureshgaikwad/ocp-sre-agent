"""
Base analyzer class.

All analyzers inherit from BaseAnalyzer and implement the analyze() method.
"""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.models.observation import Observation
from sre_agent.models.diagnosis import Diagnosis


class BaseAnalyzer(ABC):
    """
    Abstract base class for all analyzers.

    Analyzers process Observations and return Diagnoses with root cause analysis.
    They may use MCP to fetch additional data (logs, events) and LLM for analysis.
    """

    def __init__(self, mcp_registry: "MCPToolRegistry", analyzer_name: str):
        """
        Initialize analyzer.

        Args:
            mcp_registry: MCP tool registry for calling OpenShift tools
            analyzer_name: Name of this analyzer (for logging and diagnosis metadata)
        """
        self.mcp_registry = mcp_registry
        self.analyzer_name = analyzer_name

    @abstractmethod
    async def analyze(self, observation: Observation) -> Optional[Diagnosis]:
        """
        Analyze an observation and produce a diagnosis.

        Args:
            observation: The observation to analyze

        Returns:
            Diagnosis if this analyzer can diagnose the issue, None otherwise

        Raises:
            Exception: If analysis fails critically (analyzers should catch and log errors)
        """
        pass

    @abstractmethod
    def can_analyze(self, observation: Observation) -> bool:
        """
        Check if this analyzer can analyze the given observation.

        This is called before analyze() to route observations to appropriate analyzers.

        Args:
            observation: The observation to check

        Returns:
            True if this analyzer can analyze this observation type
        """
        pass

    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}({self.analyzer_name})"
