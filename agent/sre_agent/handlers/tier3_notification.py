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

                # Build enriched event message with full diagnostic reasoning
                enriched_message = self._build_enriched_event_message(
                    diagnosis=diagnosis,
                    git_configured=False
                )

                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=resource_name,
                    resource_kind=resource_kind,
                    action="ManualInterventionRequired",
                    result=enriched_message,
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

                # Build enriched event message with full diagnostic reasoning
                enriched_message = self._build_enriched_event_message(
                    diagnosis=diagnosis,
                    issue_url=issue_url
                )

                await event_creator.create_remediation_event(
                    namespace=namespace,
                    resource_name=resource_name,
                    resource_kind=resource_kind,
                    action="IssueCreated",
                    result=enriched_message,
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

            # Build enriched event message with full diagnostic reasoning
            enriched_message = self._build_enriched_event_message(
                diagnosis=diagnosis,
                failure_reason=str(e)
            )

            await event_creator.create_remediation_event(
                namespace=namespace,
                resource_name=resource_name,
                resource_kind=resource_kind,
                action="NotificationFailed",
                result=enriched_message,
                success=False
            )

        # Calculate execution time
        end_time = datetime.utcnow()
        result.execution_time_seconds = (end_time - start_time).total_seconds()

        return result

    def _build_enriched_event_message(
        self,
        diagnosis: Diagnosis,
        issue_url: str = None,
        failure_reason: str = None,
        git_configured: bool = True
    ) -> str:
        """
        Build enriched event message with full diagnostic reasoning.

        Args:
            diagnosis: The diagnosis object
            issue_url: Optional issue URL if issue was created
            failure_reason: Optional failure reason if issue creation failed
            git_configured: Whether Git is configured

        Returns:
            Enriched event message with detection, analysis, and remediation logic
        """
        # Header
        message = f"⚠️ SRE Agent detected {diagnosis.category.value.replace('_', ' ').title()}\n\n"

        # 1. DETECTION: How the problem was discovered
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "🔍 DETECTION\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"Analyzer: {diagnosis.analyzer_name}\n"
        message += f"Category: {diagnosis.category.value}\n"
        message += f"Confidence: {diagnosis.confidence.value.upper()}\n"
        message += f"Timestamp: {diagnosis.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"

        if diagnosis.error_patterns:
            message += f"\nError Patterns Matched:\n"
            for pattern in diagnosis.error_patterns:
                message += f"  • {pattern}\n"

        # 2. ANALYSIS: Diagnostic steps and evidence
        message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "🔬 ANALYSIS & EVIDENCE\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        # Show key evidence based on diagnosis type
        evidence = diagnosis.evidence

        if diagnosis.category == DiagnosisCategory.IMAGE_PULL_BACKOFF_AUTH:
            message += "Registry: Authentication failure\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. Detected ImagePullBackOff error\n"
            message += "  2. Matched 401/403 error patterns in events\n"
            message += "  3. Determined this is a credentials issue\n"

        elif diagnosis.category == DiagnosisCategory.IMAGE_PULL_BACKOFF_NOT_FOUND:
            message += "Registry: Image not found (404)\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. Detected ImagePullBackOff error\n"
            message += "  2. Matched 404 error patterns in events\n"
            message += "  3. Determined image does not exist in registry\n"

        elif diagnosis.category == DiagnosisCategory.NODE_DISK_PRESSURE:
            message += "Node: Disk pressure detected\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. Monitored node conditions\n"
            message += "  2. Detected DiskPressure condition = True\n"
            message += "  3. Analyzed disk usage patterns\n"

        elif diagnosis.category == DiagnosisCategory.CLUSTER_OPERATOR_DEGRADED:
            message += f"Cluster Operator: {evidence.get('operator_name', 'N/A')}\n"
            message += f"Status: Degraded\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. Checked ClusterOperator status conditions\n"
            message += "  2. Found Degraded=True or Available=False\n"
            message += "  3. Determined platform component needs attention\n"

        elif diagnosis.category == DiagnosisCategory.HPA_UNABLE_TO_GET_METRICS:
            message += "HPA cannot fetch metrics from metrics-server\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. Checked HPA conditions for metrics availability\n"
            message += "  2. Matched error patterns for metrics-server failures\n"
            message += "  3. Verified this is a metrics infrastructure issue\n"

        elif diagnosis.category == DiagnosisCategory.HPA_MISSING_SCALEREF:
            message += f"Scale Target: {evidence.get('target_kind', 'N/A')}/{evidence.get('target_name', 'N/A')}\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. HPA references a non-existent resource\n"
            message += "  2. Checked if deployment/statefulset was deleted\n"
            message += "  3. Determined HPA configuration needs update\n"

        elif diagnosis.category == DiagnosisCategory.APPLICATION_ERROR:
            message += "Application crashed due to code error\n"
            if evidence.get('exit_code'):
                message += f"Exit Code: {evidence.get('exit_code')}\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. Analyzed container logs for error patterns\n"
            message += "  2. Detected application-level exceptions/crashes\n"
            message += "  3. Determined root cause is in application code\n"

        else:
            # Generic evidence display
            key_evidence = [k for k in evidence.keys() if k not in ['namespace', 'resource_name', 'resource_kind']]
            if key_evidence:
                message += "Key Evidence:\n"
                for key in key_evidence[:5]:  # Limit to 5 items
                    value = evidence[key]
                    # Truncate long values
                    if isinstance(value, str) and len(value) > 100:
                        value = value[:100] + "..."
                    message += f"  • {key}: {value}\n"

        # 3. DIAGNOSIS: Root cause conclusion
        message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "💡 DIAGNOSIS\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"Root Cause: {diagnosis.root_cause}\n"

        # 4. REMEDIATION LOGIC: Why specific solutions are recommended
        message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "🔧 REMEDIATION RECOMMENDATIONS\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        # Explain why Tier 3 (Notification) approach
        message += f"Remediation Tier: {diagnosis.recommended_tier} (Notification)\n\n"
        message += "Why Manual Intervention Required:\n"
        message += "  • Issue requires human judgment or expertise\n"
        message += "  • Cannot be safely automated\n"
        message += "  • May require external system changes\n"
        message += "  • Needs domain-specific knowledge\n\n"

        # Primary recommendations
        message += "Recommended Actions (in priority order):\n"
        for i, action in enumerate(diagnosis.recommended_actions, 1):
            message += f"  {i}. {action}\n"

        # Explain why these specific actions
        message += "\nRemediation Logic:\n"

        if diagnosis.category == DiagnosisCategory.IMAGE_PULL_BACKOFF_AUTH:
            message += "  • Fix image pull secret credentials\n"
            message += "  • Alternatives:\n"
            message += "    - Make registry public: Security risk\n"
            message += "    - Use different registry: May not have image\n"
            message += "  • Why fix credentials: Maintains security while enabling access\n"

        elif diagnosis.category == DiagnosisCategory.IMAGE_PULL_BACKOFF_NOT_FOUND:
            message += "  • Verify image tag exists in registry\n"
            message += "  • Alternatives:\n"
            message += "    - Build missing image: If it should exist\n"
            message += "    - Update deployment to use correct tag\n"
            message += "  • Why verify first: Avoid deploying wrong version\n"

        elif diagnosis.category == DiagnosisCategory.NODE_DISK_PRESSURE:
            message += "  • Clean up unused images and stopped containers\n"
            message += "  • Identify and remove large log files\n"
            message += "  • Alternatives:\n"
            message += "    - Add more storage: Costly\n"
            message += "    - Cordon and drain node: Disruptive\n"
            message += "  • Why cleanup first: Non-disruptive quick fix\n"

        elif diagnosis.category == DiagnosisCategory.CLUSTER_OPERATOR_DEGRADED:
            message += "  • Check operator logs for specific errors\n"
            message += "  • Review operator conditions and status\n"
            message += "  • Alternatives:\n"
            message += "    - Restart operator: May not fix root cause\n"
            message += "    - Ignore if not critical: Risky\n"
            message += "  • Why investigate first: Platform issues need careful diagnosis\n"

        elif diagnosis.category == DiagnosisCategory.APPLICATION_ERROR:
            message += "  • Review application logs for stack traces\n"
            message += "  • Identify and fix code bugs\n"
            message += "  • Alternatives:\n"
            message += "    - Rollback to previous version: Temporary fix\n"
            message += "    - Add error handling: Masks root cause\n"
            message += "  • Why fix code: Permanent resolution\n"

        elif diagnosis.category == DiagnosisCategory.HPA_UNABLE_TO_GET_METRICS:
            message += "  • Fix metrics-server deployment\n"
            message += "  • Verify pod has resource requests defined\n"
            message += "  • Alternatives:\n"
            message += "    - Disable HPA: Loses autoscaling benefit\n"
            message += "    - Use custom metrics: More complex\n"
            message += "  • Why fix metrics-server: Required for resource-based HPA\n"

        # Add issue URL if created
        if issue_url:
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += "📋 TRACKING\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += f"Issue created: {issue_url}\n"
            message += "Please review and take action.\n"

        # Add failure reason if issue creation failed
        if failure_reason:
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += "❌ NOTIFICATION STATUS\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += f"Failed to create issue: {failure_reason}\n"
            message += "Please take manual action.\n"

        # Add note if Git not configured
        if not git_configured:
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += "⚙️ CONFIGURATION NOTE\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += "Git integration not configured.\n"
            message += "Configure GIT_TOKEN, GIT_ORGANIZATION, and GIT_REPOSITORY\n"
            message += "to enable automatic issue creation.\n"

        return message

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
