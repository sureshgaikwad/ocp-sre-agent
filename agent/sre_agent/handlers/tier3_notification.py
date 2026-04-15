"""
Tier 3 Notification Handler.

Creates Gitea issues for manual intervention.
Used for issues that require human judgment or cannot be automated.
"""

import os
from typing import TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.handlers.base import BaseHandler
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory
from sre_agent.models.remediation import RemediationResult, RemediationStatus
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.secret_scrubber import SecretScrubber
from sre_agent.utils.audit_logger import get_audit_logger, OperationType
from sre_agent.utils.event_creator import get_event_creator
from sre_agent.config.settings import get_settings
from sre_agent.integrations.git.factory import create_git_adapter
from sre_agent.integrations.git.base import GitPlatformAdapter

logger = get_logger(__name__)


class Tier3NotificationHandler(BaseHandler):
    """
    Tier 3 handler: Notification only.

    Creates Gitea issues with scrubbed diagnostic information.
    Used for:
    - Authentication issues
    - Image not found
    - Complex application errors
    - Platform issues (ClusterOperator, MachineConfigPool)
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize Tier 3 handler.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "tier3_notification", tier=3)
        self.settings = get_settings()
        self.audit_logger = get_audit_logger(self.settings.audit_db_path)

        # Check if Git integration is configured
        self.git_configured = bool(
            self.settings.git_token and
            self.settings.git_organization and
            self.settings.git_repository
        )

        # Create Git adapter only if configured
        self.git_adapter: GitPlatformAdapter | None = None
        if self.git_configured:
            self.git_adapter = create_git_adapter(
                platform=self.settings.git_platform,
                mcp_registry=mcp_registry,  # For Gitea compatibility
                server_url=self.settings.git_server_url,
                organization=self.settings.git_organization,
                repository=self.settings.git_repository,
                token=self.settings.git_token
            )
            logger.info(
                f"Tier 3 handler initialized with {self.settings.git_platform} integration",
                git_platform=self.settings.git_platform,
                git_repo=f"{self.settings.git_organization}/{self.settings.git_repository}"
            )
        else:
            logger.warning(
                "Tier 3 handler initialized WITHOUT Git integration - issues will be logged only",
                reason="Git token, organization, or repository not configured"
            )

    def can_handle(self, diagnosis: Diagnosis) -> bool:
        """
        Check if this handler can handle the diagnosis.

        Args:
            diagnosis: Diagnosis to check

        Returns:
            True if diagnosis is Tier 3
        """
        return diagnosis.recommended_tier == 3

    async def handle(self, diagnosis: Diagnosis) -> RemediationResult:
        """
        Handle diagnosis by creating a notification issue.

        Args:
            diagnosis: Diagnosis to handle

        Returns:
            RemediationResult with issue URL
        """
        start_time = datetime.utcnow()

        logger.info(
            f"Tier 3 handling diagnosis: {diagnosis.category.value}",
            diagnosis_id=diagnosis.id,
            category=diagnosis.category.value,
            action_taken="create_issue"
        )

        result = RemediationResult(
            diagnosis_id=diagnosis.id,
            tier=3,
            status=RemediationStatus.SUCCESS,
            message="",
            handler_name=self.handler_name,
        )

        try:
            # Check if Git is configured
            if not self.git_configured:
                # Log issue details without creating Git issue
                issue_summary = self._build_issue_body(diagnosis)
                scrubbed_summary = SecretScrubber.scrub(issue_summary)

                result.status = RemediationStatus.SUCCESS
                result.message = f"⚠️ Manual intervention required for {diagnosis.category.value}. Git not configured - issue logged to audit."

                result.add_action(
                    action_type="log_issue",
                    description=f"Logged {diagnosis.category.value} for manual review (Git not configured)",
                    result=scrubbed_summary[:500],  # First 500 chars
                    success=True
                )

                logger.warning(
                    f"Tier 3: Manual intervention required (Git not configured)",
                    diagnosis_id=diagnosis.id,
                    category=diagnosis.category.value,
                    namespace=diagnosis.evidence.get("namespace"),
                    resource=diagnosis.evidence.get("pod_name") or diagnosis.evidence.get("resource_name"),
                    summary=scrubbed_summary[:200]
                )

                # Audit log
                await self.audit_logger.log_operation(
                    operation_type=OperationType.CREATE_ISSUE,
                    action="log_issue_no_git",
                    success=True,
                    diagnosis_id=diagnosis.id,
                    remediation_id=result.id,
                    result_summary=f"Issue logged (Git not configured): {diagnosis.category.value}"
                )

                # Create Kubernetes Event for manual intervention needed
                event_creator = get_event_creator()
                namespace = diagnosis.evidence.get("namespace", "cluster-wide")
                resource_name = diagnosis.evidence.get("pod_name") or diagnosis.evidence.get("resource_name", "cluster")
                resource_kind = diagnosis.evidence.get("resource_kind", "Pod")

                # Build actionable remediation steps
                remediation_steps = "\n".join([f"  {i+1}. {action}" for i, action in enumerate(diagnosis.recommended_actions)])

                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=resource_name,
                    resource_kind=resource_kind,
                    action="ManualInterventionRequired",
                    result=f"⚠️ SRE Agent detected {diagnosis.category.value} but cannot auto-fix.\n\nRecommended actions:\n{remediation_steps}\n\nRoot cause: {diagnosis.root_cause}",
                    success=False
                )

            else:
                # Create Git issue
                issue_url = await self._create_issue(diagnosis)

                result.issue_url = issue_url
                result.status = RemediationStatus.SUCCESS
                result.message = f"Created issue for manual investigation: {issue_url}"

                result.add_action(
                    action_type="create_issue",
                    description=f"Created Git issue for {diagnosis.category.value}",
                    result=issue_url,
                    success=True
                )

                logger.info(
                    f"Tier 3 notification created successfully",
                    diagnosis_id=diagnosis.id,
                    issue_url=issue_url
                )

                # Audit log
                await self.audit_logger.log_operation(
                    operation_type=OperationType.CREATE_ISSUE,
                    action="create_notification_issue",
                    success=True,
                    diagnosis_id=diagnosis.id,
                    remediation_id=result.id,
                    result_summary=f"Issue created: {issue_url}"
                )

                # Create Kubernetes Event with issue link
                event_creator = get_event_creator()
                namespace = diagnosis.evidence.get("namespace", "cluster-wide")
                resource_name = diagnosis.evidence.get("pod_name") or diagnosis.evidence.get("resource_name", "cluster")
                resource_kind = diagnosis.evidence.get("resource_kind", "Pod")

                # Build actionable remediation steps
                remediation_steps = "\n".join([f"  {i+1}. {action}" for i, action in enumerate(diagnosis.recommended_actions)])

                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=resource_name,
                    resource_kind=resource_kind,
                    action="IssueCreated",
                    result=f"📋 SRE Agent detected {diagnosis.category.value} - requires manual investigation.\n\nIssue created: {issue_url}\n\nRecommended actions:\n{remediation_steps}",
                    success=True
                )

        except Exception as e:
            result.status = RemediationStatus.FAILED
            result.error = str(e)
            result.message = f"Failed to create issue: {str(e)}"

            result.add_action(
                action_type="create_issue",
                description="Attempted to create Gitea issue",
                result=str(e),
                success=False
            )

            logger.error(
                f"Tier 3 notification failed: {e}",
                diagnosis_id=diagnosis.id,
                exc_info=True
            )

            # Audit log failure
            await self.audit_logger.log_operation(
                operation_type=OperationType.CREATE_ISSUE,
                action="create_notification_issue",
                success=False,
                diagnosis_id=diagnosis.id,
                error=str(e)
            )

            # Create Kubernetes Event for failure
            event_creator = get_event_creator()
            namespace = diagnosis.evidence.get("namespace", "cluster-wide")
            resource_name = diagnosis.evidence.get("pod_name") or diagnosis.evidence.get("resource_name", "cluster")
            resource_kind = diagnosis.evidence.get("resource_kind", "Pod")

            # Build actionable remediation steps
            remediation_steps = "\n".join([f"  {i+1}. {action}" for i, action in enumerate(diagnosis.recommended_actions)])

            await event_creator.create_remediation_event(
                namespace=namespace,
                resource_name=resource_name,
                resource_kind=resource_kind,
                action="NotificationFailed",
                result=f"❌ SRE Agent detected {diagnosis.category.value} but failed to create issue: {str(e)}\n\nRecommended actions:\n{remediation_steps}\n\nRoot cause: {diagnosis.root_cause}",
                success=False
            )

        # Calculate execution time
        end_time = datetime.utcnow()
        result.execution_time_seconds = (end_time - start_time).total_seconds()

        return result

    async def _create_issue(self, diagnosis: Diagnosis) -> str:
        """
        Create issue with diagnostic information.

        Works with any configured Git platform (GitHub, GitLab, Gitea).

        Args:
            diagnosis: Diagnosis

        Returns:
            Issue URL

        Raises:
            Exception: If issue creation fails
        """
        # Build issue title
        title = self._build_issue_title(diagnosis)

        # Build issue body with scrubbed information
        body = self._build_issue_body(diagnosis)

        # CRITICAL: Scrub secrets from body
        scrubbed_body = SecretScrubber.scrub(body)

        # Determine labels based on diagnosis category
        labels = ["incident", f"tier-{self.tier}"]
        if diagnosis.category:
            labels.append(diagnosis.category.value.lower())

        # Create issue via Git adapter (works for GitHub, GitLab, Gitea)
        try:
            issue = await self.git_adapter.create_issue(
                title=title,
                body=scrubbed_body,
                labels=labels
            )

            logger.info(
                f"Issue created in {self.settings.git_platform}: #{issue.number}",
                url=issue.url,
                platform=self.settings.git_platform
            )

            return issue.url

        except Exception as e:
            logger.error(
                f"Failed to create issue in {self.settings.git_platform}: {e}",
                platform=self.settings.git_platform,
                exc_info=True
            )
            raise

    def _build_issue_title(self, diagnosis: Diagnosis) -> str:
        """
        Build issue title.

        Args:
            diagnosis: Diagnosis

        Returns:
            Issue title
        """
        category_name = diagnosis.category.value.replace("_", " ").title()
        confidence = diagnosis.confidence.value.upper()

        return f"[{confidence}] {category_name} - Manual Intervention Required"

    def _build_issue_body(self, diagnosis: Diagnosis) -> str:
        """
        Build issue body with diagnostic information.

        Args:
            diagnosis: Diagnosis

        Returns:
            Issue body (Markdown formatted)
        """
        # Build structured issue body
        body = f"""# Diagnosis: {diagnosis.category.value}

**Confidence:** {diagnosis.confidence.value.upper()}
**Tier:** {diagnosis.recommended_tier} (Notification)
**Timestamp:** {diagnosis.timestamp.isoformat()}Z
**Analyzer:** {diagnosis.analyzer_name}

## Root Cause

{diagnosis.root_cause}

## Recommended Actions

"""

        for i, action in enumerate(diagnosis.recommended_actions, 1):
            body += f"{i}. {action}\n"

        body += "\n## Evidence\n\n```json\n"
        import json
        body += json.dumps(diagnosis.evidence, indent=2, default=str)
        body += "\n```\n"

        # Add error patterns if available
        if diagnosis.error_patterns:
            body += "\n## Error Patterns Matched\n\n"
            for pattern in diagnosis.error_patterns:
                body += f"- `{pattern}`\n"

        # Add diagnostic IDs for reference
        body += f"\n---\n\n"
        body += f"**Observation ID:** `{diagnosis.observation_id}`  \n"
        body += f"**Diagnosis ID:** `{diagnosis.id}`  \n"
        body += f"\n_This issue was automatically created by the OpenShift SRE Agent._\n"

        return body
