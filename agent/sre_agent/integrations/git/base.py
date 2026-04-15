"""
Base adapter interface for Git platform integrations.

Provides a unified interface for creating issues and pull requests
across GitHub, GitLab, Gitea, Azure DevOps, and Bitbucket.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class GitIssue:
    """Represents a Git issue."""
    number: int
    title: str
    url: str
    state: str  # "open", "closed"


@dataclass
class GitPullRequest:
    """Represents a Git pull request/merge request."""
    number: int
    title: str
    url: str
    state: str  # "open", "closed", "merged"
    head_branch: str
    base_branch: str


class GitPlatformAdapter(ABC):
    """
    Abstract base class for Git platform integrations.

    Provides a unified interface for creating issues and pull requests
    across different Git platforms (GitHub, GitLab, Gitea, etc.).
    """

    def __init__(
        self,
        server_url: str,
        organization: str,
        repository: str,
        token: str
    ):
        """
        Initialize Git platform adapter.

        Args:
            server_url: Git server URL (e.g., https://github.com)
            organization: Organization/owner name
            repository: Repository name
            token: Authentication token
        """
        self.server_url = server_url.rstrip('/')
        self.organization = organization
        self.repository = repository
        self.token = token

    @abstractmethod
    async def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None
    ) -> GitIssue:
        """
        Create an issue in the Git platform.

        Args:
            title: Issue title
            body: Issue description (Markdown)
            labels: Optional list of labels
            assignees: Optional list of user IDs to assign

        Returns:
            GitIssue with URL and number

        Raises:
            Exception: If issue creation fails
        """
        pass

    @abstractmethod
    async def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = False
    ) -> GitPullRequest:
        """
        Create a pull request/merge request in the Git platform.

        Args:
            title: PR title
            body: PR description (Markdown)
            head_branch: Source branch with changes
            base_branch: Target branch (default: main)
            draft: Create as draft PR

        Returns:
            GitPullRequest with URL and number

        Raises:
            Exception: If PR creation fails
        """
        pass

    @abstractmethod
    async def get_file_content(
        self,
        file_path: str,
        branch: str = "main"
    ) -> str:
        """
        Get file content from repository.

        Args:
            file_path: Path to file in repo
            branch: Branch name

        Returns:
            File content as string

        Raises:
            Exception: If file not found or fetch fails
        """
        pass

    @abstractmethod
    async def create_or_update_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        branch: str
    ) -> str:
        """
        Create or update a file in the repository.

        Args:
            file_path: Path to file
            content: New file content
            commit_message: Commit message
            branch: Branch to commit to

        Returns:
            Commit SHA

        Raises:
            Exception: If commit fails
        """
        pass

    @abstractmethod
    async def create_branch(
        self,
        branch_name: str,
        from_branch: str = "main"
    ) -> str:
        """
        Create a new branch.

        Args:
            branch_name: Name for new branch
            from_branch: Source branch

        Returns:
            Branch ref

        Raises:
            Exception: If branch creation fails
        """
        pass

    def get_repo_identifier(self) -> str:
        """
        Get repository identifier (org/repo).

        Returns:
            Repository identifier string
        """
        return f"{self.organization}/{self.repository}"
