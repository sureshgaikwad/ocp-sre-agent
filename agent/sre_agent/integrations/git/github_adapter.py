"""
GitHub adapter for issue and pull request creation.

Uses GitHub REST API v3.
API Documentation: https://docs.github.com/en/rest
"""

import base64
import httpx
from typing import Optional

from sre_agent.integrations.git.base import (
    GitPlatformAdapter,
    GitIssue,
    GitPullRequest
)
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class GitHubAdapter(GitPlatformAdapter):
    """
    GitHub adapter using REST API v3.

    Supports both github.com and GitHub Enterprise.
    """

    def __init__(
        self,
        server_url: str = "https://github.com",
        organization: str = "",
        repository: str = "",
        token: str = ""
    ):
        """
        Initialize GitHub adapter.

        Args:
            server_url: GitHub server URL (default: https://github.com)
                       For GitHub Enterprise: https://github.company.com
            organization: Organization or user name
            repository: Repository name
            token: GitHub Personal Access Token or Fine-grained token
                  Requires: repo scope for private repos, public_repo for public repos
        """
        super().__init__(server_url, organization, repository, token)

        # Determine API URL
        if "github.com" in server_url:
            # Public GitHub
            self.api_url = "https://api.github.com"
        else:
            # GitHub Enterprise
            self.api_url = f"{server_url}/api/v3"

        logger.info(
            f"Initialized GitHub adapter for {self.get_repo_identifier()}",
            api_url=self.api_url
        )

    def _get_headers(self) -> dict:
        """Get headers for GitHub API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None
    ) -> GitIssue:
        """
        Create an issue in GitHub.

        API: POST /repos/{owner}/{repo}/issues
        Docs: https://docs.github.com/en/rest/issues/issues#create-an-issue
        """
        url = f"{self.api_url}/repos/{self.organization}/{self.repository}/issues"

        payload = {
            "title": title,
            "body": body
        }

        if labels:
            payload["labels"] = labels

        if assignees:
            payload["assignees"] = assignees

        logger.info(
            f"Creating GitHub issue: {title}",
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
            number=data["number"],
            title=data["title"],
            url=data["html_url"],
            state=data["state"]
        )

        logger.info(
            f"GitHub issue created: #{issue.number}",
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
        Create a pull request in GitHub.

        API: POST /repos/{owner}/{repo}/pulls
        Docs: https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request
        """
        url = f"{self.api_url}/repos/{self.organization}/{self.repository}/pulls"

        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft
        }

        logger.info(
            f"Creating GitHub PR: {title}",
            repo=self.get_repo_identifier(),
            head=head_branch,
            base=base_branch
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
            number=data["number"],
            title=data["title"],
            url=data["html_url"],
            state=data["state"],
            head_branch=head_branch,
            base_branch=base_branch
        )

        logger.info(
            f"GitHub PR created: #{pr.number}",
            url=pr.url
        )

        return pr

    async def get_file_content(
        self,
        file_path: str,
        branch: str = "main"
    ) -> str:
        """
        Get file content from GitHub repository.

        API: GET /repos/{owner}/{repo}/contents/{path}
        Docs: https://docs.github.com/en/rest/repos/contents#get-repository-content
        """
        url = f"{self.api_url}/repos/{self.organization}/{self.repository}/contents/{file_path}"

        params = {"ref": branch}

        logger.debug(
            f"Fetching file from GitHub: {file_path}",
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
            data = response.json()

        # Decode base64 content
        content = base64.b64decode(data["content"]).decode("utf-8")

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
        Create or update a file in GitHub repository.

        API: PUT /repos/{owner}/{repo}/contents/{path}
        Docs: https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents
        """
        url = f"{self.api_url}/repos/{self.organization}/{self.repository}/contents/{file_path}"

        # Encode content to base64
        content_base64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        payload = {
            "message": commit_message,
            "content": content_base64,
            "branch": branch
        }

        # Check if file exists to get SHA (required for updates)
        try:
            existing_content = await self.get_file_content(file_path, branch)
            # File exists, need to get SHA
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    url,
                    params={"ref": branch},
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    existing_data = response.json()
                    payload["sha"] = existing_data["sha"]
        except Exception:
            # File doesn't exist, will create new
            pass

        logger.info(
            f"Creating/updating file in GitHub: {file_path}",
            repo=self.get_repo_identifier(),
            branch=branch
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.put(
                url,
                json=payload,
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

        commit_sha = data["commit"]["sha"]

        logger.info(
            f"File committed to GitHub: {file_path}",
            commit_sha=commit_sha
        )

        return commit_sha

    async def create_branch(
        self,
        branch_name: str,
        from_branch: str = "main"
    ) -> str:
        """
        Create a new branch in GitHub.

        API: POST /repos/{owner}/{repo}/git/refs
        Docs: https://docs.github.com/en/rest/git/refs#create-a-reference
        """
        # First, get the SHA of the source branch
        ref_url = f"{self.api_url}/repos/{self.organization}/{self.repository}/git/ref/heads/{from_branch}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                ref_url,
                headers=self._get_headers()
            )
            response.raise_for_status()
            ref_data = response.json()

        source_sha = ref_data["object"]["sha"]

        # Create new branch
        create_url = f"{self.api_url}/repos/{self.organization}/{self.repository}/git/refs"

        payload = {
            "ref": f"refs/heads/{branch_name}",
            "sha": source_sha
        }

        logger.info(
            f"Creating GitHub branch: {branch_name}",
            repo=self.get_repo_identifier(),
            from_branch=from_branch
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                create_url,
                json=payload,
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

        branch_ref = data["ref"]

        logger.info(
            f"GitHub branch created: {branch_name}",
            ref=branch_ref
        )

        return branch_ref
