"""
GitLab adapter for issue and merge request creation.

Uses GitLab REST API v4.
API Documentation: https://docs.gitlab.com/ee/api/
"""

import httpx
from typing import Optional
from urllib.parse import quote

from sre_agent.integrations.git.base import (
    GitPlatformAdapter,
    GitIssue,
    GitPullRequest
)
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class GitLabAdapter(GitPlatformAdapter):
    """
    GitLab adapter using REST API v4.

    Supports both gitlab.com and self-hosted GitLab instances.
    """

    def __init__(
        self,
        server_url: str = "https://gitlab.com",
        organization: str = "",
        repository: str = "",
        token: str = ""
    ):
        """
        Initialize GitLab adapter.

        Args:
            server_url: GitLab server URL (default: https://gitlab.com)
                       For self-hosted: https://gitlab.company.com
            organization: Organization/group name
            repository: Repository (project) name
            token: GitLab Personal Access Token or Project Access Token
                  Requires: api scope
        """
        super().__init__(server_url, organization, repository, token)

        # GitLab API v4 endpoint
        self.api_url = f"{server_url}/api/v4"

        # GitLab uses project ID (org/repo URL-encoded)
        self.project_id = quote(f"{organization}/{repository}", safe="")

        logger.info(
            f"Initialized GitLab adapter for {self.get_repo_identifier()}",
            api_url=self.api_url,
            project_id=self.project_id
        )

    def _get_headers(self) -> dict:
        """Get headers for GitLab API requests."""
        return {
            "PRIVATE-TOKEN": self.token,
            "Content-Type": "application/json"
        }

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None
    ) -> GitIssue:
        """
        Create an issue in GitLab.

        API: POST /projects/:id/issues
        Docs: https://docs.gitlab.com/ee/api/issues.html#new-issue
        """
        url = f"{self.api_url}/projects/{self.project_id}/issues"

        payload = {
            "title": title,
            "description": body  # GitLab uses "description" instead of "body"
        }

        if labels:
            payload["labels"] = ",".join(labels)  # GitLab wants comma-separated string

        if assignees:
            # GitLab uses assignee_ids (list of user IDs)
            # For simplicity, we'll skip assignees for now
            # Would need to look up user IDs from usernames
            pass

        logger.info(
            f"Creating GitLab issue: {title}",
            repo=self.get_repo_identifier(),
            labels=labels
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

        issue = GitIssue(
            number=data["iid"],  # GitLab uses "iid" (internal ID)
            title=data["title"],
            url=data["web_url"],
            state=data["state"]
        )

        logger.info(
            f"GitLab issue created: #{issue.number}",
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
        Create a merge request in GitLab (equivalent to pull request).

        API: POST /projects/:id/merge_requests
        Docs: https://docs.gitlab.com/ee/api/merge_requests.html#create-mr
        """
        url = f"{self.api_url}/projects/{self.project_id}/merge_requests"

        payload = {
            "title": title,
            "description": body,  # GitLab uses "description"
            "source_branch": head_branch,
            "target_branch": base_branch
        }

        if draft:
            # GitLab draft MRs have "Draft: " or "WIP: " prefix
            payload["title"] = f"Draft: {title}"

        logger.info(
            f"Creating GitLab MR: {title}",
            repo=self.get_repo_identifier(),
            source_branch=head_branch,
            target_branch=base_branch
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

        pr = GitPullRequest(
            number=data["iid"],  # GitLab uses "iid"
            title=data["title"],
            url=data["web_url"],
            state=data["state"],
            head_branch=head_branch,
            base_branch=base_branch
        )

        logger.info(
            f"GitLab MR created: !{pr.number}",
            url=pr.url
        )

        return pr

    async def get_file_content(
        self,
        file_path: str,
        branch: str = "main"
    ) -> str:
        """
        Get file content from GitLab repository.

        API: GET /projects/:id/repository/files/:file_path/raw
        Docs: https://docs.gitlab.com/ee/api/repository_files.html#get-raw-file-from-repository
        """
        # URL-encode file path
        encoded_path = quote(file_path, safe="")

        url = f"{self.api_url}/projects/{self.project_id}/repository/files/{encoded_path}/raw"

        params = {"ref": branch}

        logger.debug(
            f"Fetching file from GitLab: {file_path}",
            repo=self.get_repo_identifier(),
            branch=branch
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url,
                params=params,
                headers=self._get_headers()
            )
            response.raise_for_status()
            content = response.text

        logger.debug(
            f"File content fetched: {len(content)} bytes",
            file_path=file_path
        )

        return content

    async def create_or_update_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        branch: str
    ) -> str:
        """
        Create or update a file in GitLab repository.

        API: POST /projects/:id/repository/files/:file_path (create)
             PUT /projects/:id/repository/files/:file_path (update)
        Docs: https://docs.gitlab.com/ee/api/repository_files.html#create-new-file-in-repository
        """
        # URL-encode file path
        encoded_path = quote(file_path, safe="")

        base_url = f"{self.api_url}/projects/{self.project_id}/repository/files/{encoded_path}"

        payload = {
            "branch": branch,
            "content": content,
            "commit_message": commit_message
        }

        # Check if file exists
        try:
            await self.get_file_content(file_path, branch)
            # File exists, use PUT to update
            method = "PUT"
            url = base_url
            action = "update"
        except Exception:
            # File doesn't exist, use POST to create
            method = "POST"
            url = base_url
            action = "create"

        logger.info(
            f"{action.capitalize()}ing file in GitLab: {file_path}",
            repo=self.get_repo_identifier(),
            branch=branch
        )

        async with httpx.AsyncClient(timeout=30) as client:
            if method == "POST":
                response = await client.post(
                    url,
                    json=payload,
                    headers=self._get_headers()
                )
            else:
                response = await client.put(
                    url,
                    json=payload,
                    headers=self._get_headers()
                )

            response.raise_for_status()
            data = response.json()

        # GitLab API doesn't return commit SHA in the response for file operations
        # We'll return the branch name instead
        commit_ref = data.get("branch", branch)

        logger.info(
            f"File committed to GitLab: {file_path}",
            branch=commit_ref
        )

        return commit_ref

    async def create_branch(
        self,
        branch_name: str,
        from_branch: str = "main"
    ) -> str:
        """
        Create a new branch in GitLab.

        API: POST /projects/:id/repository/branches
        Docs: https://docs.gitlab.com/ee/api/branches.html#create-repository-branch
        """
        url = f"{self.api_url}/projects/{self.project_id}/repository/branches"

        payload = {
            "branch": branch_name,
            "ref": from_branch
        }

        logger.info(
            f"Creating GitLab branch: {branch_name}",
            repo=self.get_repo_identifier(),
            from_branch=from_branch
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                params=payload,  # GitLab uses query params for branch creation
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

        branch_ref = data["name"]

        logger.info(
            f"GitLab branch created: {branch_name}",
            commit=data["commit"]["id"]
        )

        return branch_ref
