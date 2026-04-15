"""
Gitea adapter using MCP tools.

Wraps existing MCP Gitea tools for backward compatibility.
"""

import json
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.integrations.git.base import (
    GitPlatformAdapter,
    GitIssue,
    GitPullRequest
)
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class GiteaAdapter(GitPlatformAdapter):
    """
    Gitea adapter using MCP tools.

    Wraps existing MCP Gitea integration for backward compatibility.
    """

    def __init__(
        self,
        mcp_registry: "MCPToolRegistry",
        server_url: str = "",
        organization: str = "",
        repository: str = "",
        token: str = "",
        **kwargs
    ):
        """
        Initialize Gitea adapter.

        Args:
            mcp_registry: MCP tool registry (required for Gitea)
            server_url: Gitea server URL (not used, kept for interface compatibility)
            organization: Gitea owner/organization
            repository: Gitea repository
            token: Gitea API token (not used, passed via MCP config)
            **kwargs: Additional arguments (ignored)
        """
        super().__init__(
            server_url=server_url or "http://gitea",
            organization=organization,
            repository=repository,
            token=token
        )
        self.mcp_registry = mcp_registry

        logger.info(
            f"Initialized Gitea adapter for {self.get_repo_identifier()} using MCP",
            mcp_enabled=True
        )

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None
    ) -> GitIssue:
        """
        Create an issue in Gitea using MCP tool.

        Uses MCP tool: create_issue
        """
        logger.info(
            f"Creating Gitea issue via MCP: {title}",
            repo=self.get_repo_identifier(),
            labels=labels
        )

        # Call MCP Gitea tool
        result = await self.mcp_registry.call_tool("create_issue", {
            "owner": self.organization,
            "repo": self.repository,
            "title": title,
            "body": body,
            "labels": labels or []
        })

        # Parse MCP result
        # Assuming MCP returns JSON with issue data
        if isinstance(result, str):
            data = json.loads(result)
        else:
            data = result

        issue = GitIssue(
            number=data.get("number", 0),
            title=title,
            url=data.get("html_url", data.get("url", "")),
            state="open"
        )

        logger.info(
            f"Gitea issue created via MCP: #{issue.number}",
            url=issue.url
        )

        return issue

    async def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = False
    ) -> GitPullRequest:
        """
        Create a pull request in Gitea using MCP tool.

        Uses MCP tool: create_pull_request
        """
        logger.info(
            f"Creating Gitea PR via MCP: {title}",
            repo=self.get_repo_identifier(),
            head=head_branch,
            base=base_branch
        )

        # Call MCP Gitea tool
        result = await self.mcp_registry.call_tool("create_pull_request", {
            "owner": self.organization,
            "repo": self.repository,
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch
        })

        # Parse MCP result
        if isinstance(result, str):
            data = json.loads(result)
        else:
            data = result

        pr = GitPullRequest(
            number=data.get("number", 0),
            title=title,
            url=data.get("html_url", data.get("url", "")),
            state="open",
            head_branch=head_branch,
            base_branch=base_branch
        )

        logger.info(
            f"Gitea PR created via MCP: #{pr.number}",
            url=pr.url
        )

        return pr

    async def get_file_content(
        self,
        file_path: str,
        branch: str = "main"
    ) -> str:
        """
        Get file content from Gitea repository using MCP.

        Note: This assumes an MCP tool exists for getting file content.
        If not available, this will raise NotImplementedError.
        """
        logger.debug(
            f"Fetching file from Gitea via MCP: {file_path}",
            repo=self.get_repo_identifier(),
            branch=branch
        )

        try:
            result = await self.mcp_registry.call_tool("get_file", {
                "owner": self.organization,
                "repo": self.repository,
                "path": file_path,
                "ref": branch
            })

            if isinstance(result, str):
                return result
            elif isinstance(result, dict):
                return result.get("content", "")
            else:
                return str(result)

        except Exception as e:
            logger.error(
                f"Failed to get file from Gitea via MCP: {e}",
                file_path=file_path,
                exc_info=True
            )
            raise NotImplementedError(
                f"get_file MCP tool not available or failed. "
                f"Cannot fetch {file_path} from Gitea."
            )

    async def create_or_update_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        branch: str
    ) -> str:
        """
        Create or update a file in Gitea repository using MCP.

        Note: This assumes an MCP tool exists for file operations.
        """
        logger.info(
            f"Creating/updating file in Gitea via MCP: {file_path}",
            repo=self.get_repo_identifier(),
            branch=branch
        )

        try:
            result = await self.mcp_registry.call_tool("update_file", {
                "owner": self.organization,
                "repo": self.repository,
                "path": file_path,
                "content": content,
                "message": commit_message,
                "branch": branch
            })

            if isinstance(result, dict):
                return result.get("commit", {}).get("sha", branch)
            else:
                return branch

        except Exception as e:
            logger.error(
                f"Failed to create/update file in Gitea via MCP: {e}",
                file_path=file_path,
                exc_info=True
            )
            raise NotImplementedError(
                f"update_file MCP tool not available or failed. "
                f"Cannot commit {file_path} to Gitea."
            )

    async def create_branch(
        self,
        branch_name: str,
        from_branch: str = "main"
    ) -> str:
        """
        Create a new branch in Gitea using MCP.

        Note: This assumes an MCP tool exists for branch creation.
        """
        logger.info(
            f"Creating Gitea branch via MCP: {branch_name}",
            repo=self.get_repo_identifier(),
            from_branch=from_branch
        )

        try:
            result = await self.mcp_registry.call_tool("create_branch", {
                "owner": self.organization,
                "repo": self.repository,
                "branch": branch_name,
                "ref": from_branch
            })

            return branch_name

        except Exception as e:
            logger.error(
                f"Failed to create branch in Gitea via MCP: {e}",
                branch_name=branch_name,
                exc_info=True
            )
            raise NotImplementedError(
                f"create_branch MCP tool not available or failed. "
                f"Cannot create branch {branch_name} in Gitea."
            )
