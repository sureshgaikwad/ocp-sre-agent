"""
Factory for creating Git platform adapters.

Automatically selects the correct adapter based on platform configuration.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.integrations.git.base import GitPlatformAdapter
from sre_agent.integrations.git.github_adapter import GitHubAdapter
from sre_agent.integrations.git.gitlab_adapter import GitLabAdapter
from sre_agent.integrations.git.gitea_adapter import GiteaAdapter
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


def create_git_adapter(
    platform: str,
    mcp_registry: Optional["MCPToolRegistry"] = None,
    server_url: str = "",
    organization: str = "",
    repository: str = "",
    token: str = "",
    **kwargs
) -> GitPlatformAdapter:
    """
    Factory function to create the appropriate Git platform adapter.

    Args:
        platform: Platform name ("github", "gitlab", "gitea", "azuredevops", "bitbucket")
        mcp_registry: MCP tool registry (required for Gitea)
        server_url: Git server URL
            - GitHub: https://github.com (default) or https://github.company.com (Enterprise)
            - GitLab: https://gitlab.com (default) or https://gitlab.company.com (self-hosted)
            - Gitea: http://gitea.example.com
        organization: Organization/owner name
        repository: Repository name
        token: Authentication token
            - GitHub: Personal Access Token (PAT) or Fine-grained token
            - GitLab: Personal Access Token or Project Access Token
            - Gitea: API token
        **kwargs: Additional platform-specific arguments

    Returns:
        GitPlatformAdapter instance for the specified platform

    Raises:
        ValueError: If platform is unknown or required parameters missing

    Examples:
        # GitHub
        adapter = create_git_adapter(
            platform="github",
            server_url="https://github.com",
            organization="my-org",
            repository="cluster-issues",
            token="ghp_xxxxxxxxxxxx"
        )

        # GitHub Enterprise
        adapter = create_git_adapter(
            platform="github",
            server_url="https://github.company.com",
            organization="my-org",
            repository="cluster-issues",
            token="ghp_xxxxxxxxxxxx"
        )

        # GitLab
        adapter = create_git_adapter(
            platform="gitlab",
            server_url="https://gitlab.com",
            organization="my-group",
            repository="cluster-issues",
            token="glpat-xxxxxxxxxxxx"
        )

        # Gitea (requires MCP registry)
        adapter = create_git_adapter(
            platform="gitea",
            mcp_registry=mcp_registry,
            organization="my-org",
            repository="cluster-issues"
        )
    """
    platform = platform.lower().strip()

    # Validate required parameters
    if not organization:
        raise ValueError("organization parameter is required")
    if not repository:
        raise ValueError("repository parameter is required")

    logger.info(
        f"Creating Git adapter for platform: {platform}",
        organization=organization,
        repository=repository
    )

    if platform == "github":
        if not token:
            raise ValueError("token parameter is required for GitHub")

        return GitHubAdapter(
            server_url=server_url or "https://github.com",
            organization=organization,
            repository=repository,
            token=token
        )

    elif platform == "gitlab":
        if not token:
            raise ValueError("token parameter is required for GitLab")

        return GitLabAdapter(
            server_url=server_url or "https://gitlab.com",
            organization=organization,
            repository=repository,
            token=token
        )

    elif platform == "gitea":
        if not mcp_registry:
            raise ValueError("mcp_registry parameter is required for Gitea adapter")

        return GiteaAdapter(
            mcp_registry=mcp_registry,
            server_url=server_url,
            organization=organization,
            repository=repository,
            token=token
        )

    elif platform == "azuredevops" or platform == "azure-devops":
        # Azure DevOps support (future implementation)
        raise NotImplementedError(
            "Azure DevOps adapter is not yet implemented. "
            "Supported platforms: github, gitlab, gitea"
        )

    elif platform == "bitbucket":
        # Bitbucket support (future implementation)
        raise NotImplementedError(
            "Bitbucket adapter is not yet implemented. "
            "Supported platforms: github, gitlab, gitea"
        )

    else:
        raise ValueError(
            f"Unknown Git platform: '{platform}'. "
            f"Supported platforms: github, gitlab, gitea"
        )


def get_platform_display_name(platform: str) -> str:
    """
    Get human-readable display name for platform.

    Args:
        platform: Platform identifier

    Returns:
        Display name

    Examples:
        >>> get_platform_display_name("github")
        "GitHub"
        >>> get_platform_display_name("gitlab")
        "GitLab"
    """
    mapping = {
        "github": "GitHub",
        "gitlab": "GitLab",
        "gitea": "Gitea",
        "azuredevops": "Azure DevOps",
        "azure-devops": "Azure DevOps",
        "bitbucket": "Bitbucket"
    }
    return mapping.get(platform.lower(), platform.title())
