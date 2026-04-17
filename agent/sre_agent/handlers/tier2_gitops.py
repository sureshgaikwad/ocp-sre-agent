"""
Tier 2 GitOps Handler.

Creates pull requests for configuration changes.
Falls back to issue creation if resource is not GitOps-managed.
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
from sre_agent.utils.gitops_detector import get_gitops_detector
from sre_agent.utils.secret_scrubber import SecretScrubber
from sre_agent.utils.audit_logger import get_audit_logger, OperationType
from sre_agent.utils.event_creator import get_event_creator
from sre_agent.config.settings import get_settings
from sre_agent.integrations.git.factory import create_git_adapter
from sre_agent.integrations.git.base import GitPlatformAdapter

logger = get_logger(__name__)


# Placeholder for GitOps detector
def get_gitops_detector(mcp_registry):
    """Get GitOps detector instance."""
    from sre_agent.utils.gitops_detector import GitOpsDetector
    return GitOpsDetector(mcp_registry)


class Tier2GitOpsHandler(BaseHandler):
    """
    Tier 2 handler: GitOps PR creation.

    Creates pull requests for configuration changes:
    - OOMKilled → Increase memory limit
    - Liveness probe failure → Adjust probe settings
    - SCC permission denied → Add SCC binding

    Falls back to Tier 3 (issue creation) if:
    - Resource is not GitOps-managed
    - PR creation fails
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize Tier 2 handler.

        Args:
            mcp_registry: MCP tool registry
        """
        super().__init__(mcp_registry, "tier2_gitops", tier=2)
        self.settings = get_settings()
        self.gitops_detector = get_gitops_detector(mcp_registry)
        self.audit_logger = get_audit_logger(self.settings.audit_db_path)

        # Create Git adapter based on configuration
        self.git_adapter: GitPlatformAdapter = create_git_adapter(
            platform=self.settings.git_platform,
            mcp_registry=mcp_registry,  # For Gitea compatibility
            server_url=self.settings.git_server_url,
            organization=self.settings.git_organization,
            repository=self.settings.git_repository,
            token=self.settings.git_token
        )

        logger.info(
            f"Tier 2 handler initialized with {self.settings.git_platform} integration",
            git_platform=self.settings.git_platform,
            git_repo=f"{self.settings.git_organization}/{self.settings.git_repository}"
        )

    def can_handle(self, diagnosis: Diagnosis) -> bool:
        """
        Check if this handler can handle the diagnosis.

        Args:
            diagnosis: Diagnosis to check

        Returns:
            True if diagnosis is Tier 2 and GitOps is enabled
        """
        if not self.settings.enable_tier2_gitops:
            logger.debug("Tier 2 GitOps is disabled")
            return False

        return diagnosis.recommended_tier == 2

    async def handle(self, diagnosis: Diagnosis) -> RemediationResult:
        """
        Handle diagnosis by creating GitOps PR or issue.

        Args:
            diagnosis: Diagnosis to handle

        Returns:
            RemediationResult with PR or issue URL
        """
        start_time = datetime.utcnow()

        logger.info(
            f"Tier 2 handling diagnosis: {diagnosis.category.value}",
            diagnosis_id=diagnosis.id,
            category=diagnosis.category.value,
            action_taken="gitops_or_issue"
        )

        result = RemediationResult(
            diagnosis_id=diagnosis.id,
            tier=2,
            status=RemediationStatus.PENDING,
            message="",
            handler_name=self.handler_name,
        )

        try:
            # Determine proposed fix based on diagnosis category
            proposed_fix = self._determine_proposed_fix(diagnosis)

            if not proposed_fix:
                # Cannot determine fix - fall back to notification
                await self._fallback_to_notification(diagnosis, result, "Cannot determine proposed fix")
                return result

            result.add_action(
                action_type="determine_fix",
                description=f"Determined proposed fix: {proposed_fix['description']}",
                success=True
            )

            # Check if resource is GitOps-managed
            # Note: This requires fetching the resource to check annotations
            # For now, we'll create an issue with the proposed fix
            # In a real implementation, we would:
            # 1. Fetch resource via MCP
            # 2. Check for ArgoCD/Flux annotations
            # 3. If GitOps-managed, create PR in Git repo
            # 4. If not managed, create issue

            # Simplified: Always create issue with proposed fix
            # TODO: Implement full GitOps PR creation
            await self._fallback_to_notification(
                diagnosis, result,
                "GitOps PR creation not yet implemented. Creating issue with proposed fix."
            )

        except Exception as e:
            result.status = RemediationStatus.FAILED
            result.error = str(e)
            result.message = f"Tier 2 remediation failed: {str(e)}"

            logger.error(
                f"Tier 2 GitOps handling failed: {e}",
                diagnosis_id=diagnosis.id,
                exc_info=True
            )

            # Audit log failure
            await self.audit_logger.log_operation(
                operation_type=OperationType.REMEDIATE,
                action="tier2_gitops",
                success=False,
                diagnosis_id=diagnosis.id,
                error=str(e)
            )

            # CRITICAL: Create Kubernetes Event with remediation steps even when handler fails
            # This ensures Slack notifications are sent via event-exporter
            event_creator = get_event_creator()
            namespace = diagnosis.evidence.get("namespace", "default")
            resource_name = diagnosis.evidence.get("pod_name") or diagnosis.evidence.get("resource_name", "unknown")
            resource_kind = diagnosis.evidence.get("resource_kind", "Pod")

            # Build enriched event message with full diagnostic reasoning
            enriched_message = self._build_enriched_event_message(
                diagnosis=diagnosis,
                failure_reason=str(e)[:200]
            )

            await event_creator.create_remediation_event(
                namespace=namespace,
                resource_name=resource_name,
                resource_kind=resource_kind,
                action="ManualFixRequired",
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
        failure_reason: str = None
    ) -> str:
        """
        Build enriched event message with full diagnostic reasoning.

        Args:
            diagnosis: The diagnosis object
            failure_reason: Optional failure reason if auto-fix failed

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

        if diagnosis.category == DiagnosisCategory.OOM_KILLED:
            message += f"Exit Code: {evidence.get('exit_code', 'N/A')}\n"
            message += f"Reason: {evidence.get('reason', 'N/A')}\n"
            message += f"Current Memory Limit: {evidence.get('memory_limit', 'N/A')}\n"
            message += f"Container: {evidence.get('container_name', 'N/A')}\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. Detected exit code 137 (OOMKilled)\n"
            message += "  2. Verified container exceeded memory limit\n"
            message += "  3. Analyzed resource constraints vs actual usage\n"

        elif diagnosis.category == DiagnosisCategory.RESOURCE_QUOTA_EXCEEDED:
            message += f"Current Replicas: {evidence.get('current_replicas', 'N/A')}\n"
            message += f"Maximum Replicas: {evidence.get('max_replicas', 'N/A')}\n"
            if 'current_metrics' in evidence:
                message += f"Current Metrics: {evidence.get('current_metrics', 'N/A')}\n"
            message += "\nDiagnostic Logic:\n"
            message += "  1. HPA reached maximum replica count\n"
            message += "  2. Load/metrics still indicate scaling needed\n"
            message += "  3. Determined maxReplicas is the bottleneck\n"

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

        # Explain why Tier 2 (GitOps) approach
        message += f"Remediation Tier: {diagnosis.recommended_tier} (GitOps/PR-based)\n\n"
        message += "Why This Approach:\n"
        message += "  • Requires configuration change (not transient issue)\n"
        message += "  • Change should be tracked in Git for auditability\n"
        message += "  • Needs review before applying to production\n"
        message += "  • Can be automated via GitOps PR workflow\n\n"

        # Primary recommendations
        message += "Recommended Actions (in priority order):\n"
        for i, action in enumerate(diagnosis.recommended_actions, 1):
            message += f"  {i}. {action}\n"

        # Explain why these specific actions
        message += "\nRemediation Logic:\n"

        if diagnosis.category == DiagnosisCategory.OOM_KILLED:
            message += "  • Increasing memory prevents OOMKilled failures\n"
            message += "  • Setting memory request ensures proper scheduling\n"
            message += "  • Alternative: Optimize application (long-term fix)\n"
            message += "  • Why not vertical autoscaling: Not all clusters support VPA\n"

        elif diagnosis.category == DiagnosisCategory.RESOURCE_QUOTA_EXCEEDED:
            max_replicas = evidence.get('max_replicas', 1)
            proposed = max_replicas * 2
            message += f"  • Doubling maxReplicas ({max_replicas} → {proposed}) allows scaling\n"
            message += "  • Alternatives considered:\n"
            message += "    - Vertical scaling (increase pod resources): May hit node limits\n"
            message += "    - Optimize application: Long-term solution, not immediate\n"
            message += f"  • Why doubling: Provides headroom for traffic spikes\n"

        elif diagnosis.category == DiagnosisCategory.HPA_UNABLE_TO_GET_METRICS:
            message += "  • Fixing metrics-server enables HPA to function\n"
            message += "  • Alternative: Disable HPA (loses autoscaling benefit)\n"
            message += "  • Why metrics-server: Required for resource-based HPA\n"

        elif diagnosis.category == DiagnosisCategory.LIVENESS_PROBE_FAILURE:
            message += "  • Adjusting probe timing reduces false positives\n"
            message += "  • Alternatives:\n"
            message += "    - Remove probe: Loses health check benefit\n"
            message += "    - Fix app startup: Long-term solution\n"
            message += "  • Why adjust timing: Quick fix for slow-starting apps\n"

        # Add failure reason if auto-fix failed
        if failure_reason:
            message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += "❌ AUTO-FIX STATUS\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += f"Auto-fix failed: {failure_reason}\n"
            message += "Manual intervention required.\n"

        return message

    def _determine_proposed_fix(self, diagnosis: Diagnosis) -> dict:
        """
        Determine proposed configuration fix based on diagnosis.

        Args:
            diagnosis: Diagnosis

        Returns:
            Dict with proposed fix details or None
        """
        if diagnosis.category == DiagnosisCategory.OOM_KILLED:
            # Propose memory increase
            current_limit = diagnosis.evidence.get("memory_limit", "unknown")
            # Simple heuristic: double the memory
            # In real implementation, would analyze actual memory usage
            return {
                "type": "memory_increase",
                "description": f"Increase memory limit from {current_limit} to double",
                "yaml_patch": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [{
                                    "resources": {
                                        "limits": {
                                            "memory": "512Mi"  # Example
                                        },
                                        "requests": {
                                            "memory": "256Mi"  # Example
                                        }
                                    }
                                }]
                            }
                        }
                    }
                }
            }

        elif diagnosis.category == DiagnosisCategory.LIVENESS_PROBE_FAILURE:
            # Propose probe adjustment
            return {
                "type": "liveness_probe_adjustment",
                "description": "Increase liveness probe initialDelaySeconds and timeout",
                "yaml_patch": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [{
                                    "livenessProbe": {
                                        "initialDelaySeconds": 30,
                                        "timeoutSeconds": 10,
                                        "periodSeconds": 10
                                    }
                                }]
                            }
                        }
                    }
                }
            }

        elif diagnosis.category == DiagnosisCategory.SCC_PERMISSION_DENIED:
            # Propose SCC binding
            return {
                "type": "scc_binding",
                "description": "Add SecurityContextConstraints binding",
                "recommendation": "Create RoleBinding or add SCC to ServiceAccount",
            }

        elif diagnosis.category == DiagnosisCategory.ROUTE_SERVICE_NO_ENDPOINTS:
            # Propose scaling deployment
            service_name = diagnosis.evidence.get("service", "unknown")
            return {
                "type": "scale_deployment",
                "description": f"Scale deployment for service '{service_name}' to ensure endpoints",
                "yaml_patch": {
                    "spec": {
                        "replicas": 2  # Example: ensure at least 2 replicas
                    }
                },
                "recommendation": f"Scale deployment backing service '{service_name}' to at least 2 replicas"
            }

        elif diagnosis.category == DiagnosisCategory.BUILD_RESOURCE_LIMIT:
            # Propose build resource increase
            return {
                "type": "build_resource_increase",
                "description": "Increase build container resources",
                "yaml_patch": {
                    "spec": {
                        "taskSpec": {
                            "stepTemplate": {
                                "resources": {
                                    "limits": {
                                        "memory": "2Gi",
                                        "cpu": "1000m"
                                    },
                                    "requests": {
                                        "memory": "1Gi",
                                        "cpu": "500m"
                                    }
                                }
                            }
                        }
                    }
                },
                "recommendation": "Increase memory and CPU limits for build tasks"
            }

        elif diagnosis.category == DiagnosisCategory.BUILD_TIMEOUT:
            # Propose timeout increase
            return {
                "type": "build_timeout_increase",
                "description": "Increase pipeline/task timeout",
                "yaml_patch": {
                    "spec": {
                        "timeout": "2h"  # Example: 2 hours
                    }
                },
                "recommendation": "Increase timeout value for pipeline/task"
            }

        elif diagnosis.category == DiagnosisCategory.RESOURCE_QUOTA_EXCEEDED:
            # HPA at max replicas - propose maxReplicas increase
            current_max = diagnosis.evidence.get("max_replicas", 10)
            new_max = current_max * 2

            return {
                "type": "hpa_max_replicas_increase",
                "description": f"Increase HPA maxReplicas from {current_max} to {new_max}",
                "yaml_patch": {
                    "spec": {
                        "maxReplicas": new_max
                    }
                },
                "recommendation": f"Increase HPA maxReplicas to {new_max} to allow further scaling"
            }

        elif diagnosis.category == DiagnosisCategory.PROACTIVE_MEMORY_INCREASE:
            # Proactive memory increase to prevent OOM
            increase_factor = diagnosis.evidence.get("recommended_increase_factor", 1.5)

            return {
                "type": "proactive_memory_increase",
                "description": f"Proactive memory increase ({(increase_factor - 1) * 100:.0f}% increase) to prevent predicted OOM",
                "yaml_patch": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [{
                                    "resources": {
                                        "limits": {
                                            "memory": f"{int(512 * increase_factor)}Mi"  # Example
                                        },
                                        "requests": {
                                            "memory": f"{int(256 * increase_factor)}Mi"
                                        }
                                    }
                                }]
                            }
                        }
                    }
                },
                "recommendation": f"Increase memory proactively to prevent OOM (urgency: {diagnosis.evidence.get('urgency', 'MEDIUM')})"
            }

        elif diagnosis.category == DiagnosisCategory.PROACTIVE_CPU_INCREASE:
            # Proactive CPU increase to prevent throttling
            increase_factor = diagnosis.evidence.get("recommended_increase_factor", 1.3)

            return {
                "type": "proactive_cpu_increase",
                "description": f"Proactive CPU increase ({(increase_factor - 1) * 100:.0f}% increase) to prevent throttling",
                "yaml_patch": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [{
                                    "resources": {
                                        "limits": {
                                            "cpu": f"{int(1000 * increase_factor)}m"
                                        },
                                        "requests": {
                                            "cpu": f"{int(500 * increase_factor)}m"
                                        }
                                    }
                                }]
                            }
                        }
                    }
                },
                "recommendation": f"Increase CPU proactively to prevent throttling"
            }

        elif diagnosis.category == DiagnosisCategory.PROACTIVE_SCALE_UP:
            # Proactive scaling to prevent overload
            return {
                "type": "proactive_scale_up",
                "description": "Proactive scale-up to prevent service degradation",
                "yaml_patch": {
                    "spec": {
                        "replicas": 3  # Example: scale to 3 replicas
                    }
                },
                "recommendation": "Scale up replicas proactively based on error rate trend"
            }

        elif diagnosis.category == DiagnosisCategory.POD_OVERPROVISIONED:
            # Cost optimization: reduce over-provisioning
            current_requests = diagnosis.evidence.get("requests", {})
            recommended_requests = diagnosis.evidence.get("recommended_requests", {})

            return {
                "type": "resource_right_sizing",
                "description": "Right-size resources to reduce costs",
                "yaml_patch": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [{
                                    "resources": {
                                        "requests": recommended_requests
                                    }
                                }]
                            }
                        }
                    }
                },
                "recommendation": f"Reduce resource requests to match actual usage (cost savings: {diagnosis.evidence.get('estimated_savings', 'TBD')})"
            }

        else:
            # Unknown category for Tier 2
            return None

    async def _fallback_to_notification(
        self,
        diagnosis: Diagnosis,
        result: RemediationResult,
        reason: str
    ) -> None:
        """
        Fall back to Tier 3 notification.

        Args:
            diagnosis: Diagnosis
            result: RemediationResult to populate
            reason: Reason for fallback
        """
        logger.info(
            f"Falling back to notification: {reason}",
            diagnosis_id=diagnosis.id
        )

        result.add_action(
            action_type="fallback_to_notification",
            description=f"Fallback reason: {reason}",
            success=True
        )

        # Create issue with proposed fix
        issue_url = await self._create_issue_with_fix(diagnosis)

        result.issue_url = issue_url
        result.status = RemediationStatus.SUCCESS
        result.message = f"Created issue with proposed fix (fallback from GitOps): {issue_url}"

        result.add_action(
            action_type="create_issue",
            description="Created issue with proposed configuration fix",
            result=issue_url,
            success=True
        )

        # Audit log
        await self.audit_logger.log_operation(
            operation_type=OperationType.CREATE_ISSUE,
            action="tier2_fallback_to_issue",
            success=True,
            diagnosis_id=diagnosis.id,
            remediation_id=result.id,
            result_summary=f"Issue created: {issue_url}"
        )

    async def _create_issue_with_fix(self, diagnosis: Diagnosis) -> str:
        """
        Create issue with proposed fix.

        Works with any configured Git platform (GitHub, GitLab, Gitea).

        Args:
            diagnosis: Diagnosis

        Returns:
            Issue URL

        Raises:
            Exception: If issue creation fails
        """
        # Get proposed fix
        proposed_fix = self._determine_proposed_fix(diagnosis)

        # Build issue title
        title = f"[GITOPS] {diagnosis.category.value.replace('_', ' ').title()} - Configuration Fix Required"

        # Build issue body
        body = self._build_issue_body_with_fix(diagnosis, proposed_fix)

        # Scrub secrets
        scrubbed_body = SecretScrubber.scrub(body)

        # Determine labels
        labels = ["gitops", "tier-2", "config-fix"]
        if diagnosis.category:
            labels.append(diagnosis.category.value.lower())

        # Create issue via Git adapter
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

    def _build_issue_body_with_fix(
        self,
        diagnosis: Diagnosis,
        proposed_fix: dict
    ) -> str:
        """
        Build issue body with proposed fix.

        Args:
            diagnosis: Diagnosis
            proposed_fix: Proposed fix dict

        Returns:
            Issue body (Markdown)
        """
        import json

        body = f"""# Proposed Configuration Fix

**Category:** {diagnosis.category.value}
**Confidence:** {diagnosis.confidence.value.upper()}
**Tier:** 2 (GitOps/Configuration Change)

## Root Cause

{diagnosis.root_cause}

## Proposed Fix

"""

        if proposed_fix:
            body += f"**Type:** {proposed_fix.get('type', 'Unknown')}  \n"
            body += f"**Description:** {proposed_fix.get('description', 'N/A')}  \n\n"

            if "yaml_patch" in proposed_fix:
                body += "### YAML Patch\n\n```yaml\n"
                import yaml
                body += yaml.dump(proposed_fix["yaml_patch"], default_flow_style=False)
                body += "\n```\n\n"

            if "recommendation" in proposed_fix:
                body += f"### Recommendation\n\n{proposed_fix['recommendation']}\n\n"

        body += "## Recommended Actions\n\n"
        for i, action in enumerate(diagnosis.recommended_actions, 1):
            body += f"{i}. {action}\n"

        body += "\n## Evidence\n\n```json\n"
        body += json.dumps(diagnosis.evidence, indent=2, default=str)
        body += "\n```\n"

        body += f"\n---\n\n"
        body += f"**Diagnosis ID:** `{diagnosis.id}`  \n"
        body += f"\n_This issue was created by OpenShift SRE Agent (Tier 2 GitOps Handler)._\n"
        body += f"\n**Note:** GitOps PR creation not yet fully implemented. Please apply the proposed fix manually or via GitOps workflow.\n"

        return body
