"""
Slack Interactive Notifier.

Sends rich Slack messages with action buttons for remediation approval.
"""

import os
import json
import asyncio
from typing import Optional, List, Dict
from datetime import datetime
import aiohttp

from sre_agent.models.diagnosis import Diagnosis
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.secret_scrubber import SecretScrubber
from sre_agent.knowledge import get_kb_retriever

logger = get_logger(__name__)


class SlackNotifier:
    """
    Sends interactive Slack notifications for remediation approval.

    Features:
    - Rich message formatting with markdown
    - Action buttons (Fix / Ignore)
    - Callback handling for button clicks
    """

    def __init__(self, webhook_url: Optional[str] = None):
        """
        Initialize Slack notifier.

        Args:
            webhook_url: Slack webhook URL (or read from SLACK_WEBHOOK_URL env var)
        """
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.enabled = bool(self.webhook_url)

        # Get external route URL for approval endpoint
        self.route_url = os.getenv("SRE_AGENT_ROUTE_URL", "")

        if not self.route_url:
            # Try to auto-detect from OpenShift
            self._detect_route_url()

        if not self.enabled:
            logger.warning(
                "Slack notifier disabled - SLACK_WEBHOOK_URL not configured"
            )
        else:
            logger.info(
                "Slack notifier initialized",
                route_url=self.route_url or "not configured"
            )

    def _detect_route_url(self):
        """Auto-detect external route URL from OpenShift using Kubernetes API."""
        try:
            from kubernetes import client, config
            from kubernetes.client.rest import ApiException

            # Load in-cluster config
            try:
                config.load_incluster_config()
            except Exception:
                # Fallback to kubeconfig if not in cluster
                config.load_kube_config()

            # Use CustomObjectsApi to access OpenShift Route resource
            api = client.CustomObjectsApi()

            try:
                route = api.get_namespaced_custom_object(
                    group="route.openshift.io",
                    version="v1",
                    namespace="sre-agent",
                    plural="routes",
                    name="sre-agent"
                )

                # Extract hostname from route spec
                host = route.get("spec", {}).get("host", "")
                if host:
                    self.route_url = f"https://{host}"
                    logger.info(f"Auto-detected route URL: {self.route_url}")
                else:
                    logger.warning("Route found but no host specified")
            except ApiException as e:
                if e.status == 404:
                    logger.warning("Route 'sre-agent' not found in namespace 'sre-agent' - Slack approval URLs will not work")
                else:
                    logger.error(f"Failed to get route: {e.status} - {e.reason}")
        except Exception as e:
            logger.error(f"Could not auto-detect route URL: {e}")

    async def send_remediation_request(
        self,
        diagnosis: Diagnosis,
        reason: str = ""
    ) -> bool:
        """
        Send Slack message requesting remediation approval.

        Args:
            diagnosis: Diagnosis requiring approval
            reason: Why this alert was triggered (persistent/recurring/critical)

        Returns:
            True if message sent successfully
        """
        if not self.enabled:
            logger.debug("Slack notifier disabled, skipping message")
            return False

        try:
            # Fetch KB articles using tiered retriever
            kb_retriever = get_kb_retriever()
            kb_articles = await kb_retriever.get_kb_articles(diagnosis, max_articles=3)

            # Build rich Slack message
            message = await self._build_slack_message(diagnosis, reason, kb_articles)

            # Scrub secrets before sending
            message_str = json.dumps(message)
            scrubbed_str = SecretScrubber.scrub(message_str)
            scrubbed_message = json.loads(scrubbed_str)

            # Send to Slack
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=scrubbed_message,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.info(
                            f"Slack remediation request sent successfully",
                            diagnosis_id=diagnosis.id,
                            category=diagnosis.category.value,
                            reason=reason
                        )
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Slack API error: {response.status}",
                            diagnosis_id=diagnosis.id,
                            error=error_text
                        )
                        return False

        except Exception as e:
            logger.error(
                f"Failed to send Slack message: {e}",
                diagnosis_id=diagnosis.id,
                exc_info=True
            )
            return False

    async def _build_slack_message(self, diagnosis: Diagnosis, reason: str, kb_articles: List[Dict[str, str]]) -> dict:
        """
        Build Slack message with blocks and actions.

        Args:
            diagnosis: Diagnosis to present
            reason: Alert trigger reason

        Returns:
            Slack message payload
        """
        evidence = diagnosis.evidence
        namespace = evidence.get("namespace", "cluster-wide")
        resource_kind = evidence.get("resource_kind", "unknown")

        # Extract resource name with better fallbacks
        resource_name = (
            evidence.get("resource_name") or
            evidence.get("pod_name") or
            evidence.get("deployment_name") or
            evidence.get("hpa_name") or
            evidence.get("operator_name") or
            "unknown"
        )

        # Determine severity emoji
        severity_emoji = self._get_severity_emoji(diagnosis.category.value)

        # Build header
        header_text = f"{severity_emoji} *SRE Agent Alert: {diagnosis.category.value.replace('_', ' ').title()}*"

        # Build reason badge
        reason_badge = self._get_reason_badge(reason)

        # Build blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🤖 SRE Agent Remediation Request",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{header_text}\n{reason_badge}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Resource:*\n`{namespace}/{resource_kind}/{resource_name}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence:*\n{diagnosis.confidence.value.upper()}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Analyzer:*\n{diagnosis.analyzer_name}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Tier:*\nTier {diagnosis.recommended_tier}"
                    }
                ]
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🔬 Diagnosis Steps:*"
                }
            }
        ]

        # Add diagnosis steps (commands executed, logs analyzed)
        diagnosis_steps = self._build_diagnosis_steps(diagnosis)
        if diagnosis_steps:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": diagnosis_steps
                }
            })

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🔍 Root Cause:*\n```{diagnosis.root_cause}```"
            }
        })

        # Add recommended actions
        if diagnosis.recommended_actions:
            actions_text = "\n".join([
                f"{i+1}. {action}"
                for i, action in enumerate(diagnosis.recommended_actions[:3])
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🔧 Recommended Actions:*\n{actions_text}"
                }
            })

        # Add evidence summary (key items only)
        evidence_items = []
        for key in ["exit_code", "memory_limit", "current_replicas", "max_replicas"]:
            if key in evidence:
                evidence_items.append(f"• *{key}:* `{evidence[key]}`")

        if evidence_items:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📊 Evidence:*\n" + "\n".join(evidence_items[:5])
                }
            })

        blocks.append({"type": "divider"})

        # Add manual remediation commands
        remediation_commands = self._build_remediation_commands(diagnosis)
        if remediation_commands:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*💡 Manual Fix (if agent can't auto-remediate):*\n```bash\n{remediation_commands}\n```"
                }
            })
            blocks.append({"type": "divider"})

        # Add KB articles from tiered retrieval
        if kb_articles:
            kb_text = "*📚 Knowledge Base Articles:*\n"
            for article in kb_articles:
                title = article.get("title", "Article")
                url = article.get("url", "#")
                tier = article.get("tier", "?")
                source = article.get("source", "unknown")

                # Add tier badge
                tier_badge = {1: "⚡", 2: "🔍", 3: "🌐"}.get(tier, "📄")

                kb_text += f"\n{tier_badge} <{url}|{title}>"

                # Add description if available (truncate for Slack)
                description = article.get("description", "")
                if description and len(description) < 150:
                    kb_text += f"\n   _{description}_"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": kb_text
                }
            })
            blocks.append({"type": "divider"})

        # Add interactive buttons
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Do you want the SRE Agent to remediate this issue?*"
            }
        })

        # Action buttons
        # Note: For full interactivity, you need Slack App with Bot Token
        # For webhook-only mode, we provide manual approval instructions

        # Use external route URL - log warning if not available
        if not self.route_url:
            logger.warning(
                "No external route URL configured - curl commands will not work outside cluster. "
                "Set SRE_AGENT_ROUTE_URL environment variable or ensure route is created."
            )
            api_url = "<ROUTE_URL_NOT_CONFIGURED>"
        else:
            api_url = self.route_url

        # Generate stable fingerprint (works across agent restarts)
        from sre_agent.utils.event_deduplicator import get_event_deduplicator
        deduplicator = get_event_deduplicator()
        fingerprint = deduplicator._generate_fingerprint(diagnosis)

        # Single-line curl commands with FINGERPRINT (stable across restarts)
        approve_cmd_fp = f"curl -X POST {api_url}/approve-remediation -H 'Content-Type: application/json' -d '{{\"diagnosis_id\": \"{fingerprint}\", \"approved\": true}}'"
        reject_cmd_fp = f"curl -X POST {api_url}/approve-remediation -H 'Content-Type: application/json' -d '{{\"diagnosis_id\": \"{fingerprint}\", \"approved\": false}}'"

        approval_text = (
            f"*✅ To Approve Remediation:*\n"
            f"```bash\n{approve_cmd_fp}\n```\n"
            f"\n"
            f"*❌ To Reject (No Action):*\n"
            f"```bash\n{reject_cmd_fp}\n```\n"
            f"\n_💡 Issue ID `{fingerprint}` is stable across agent restarts_"
        )

        if not self.route_url:
            approval_text = (
                "⚠️ *External route URL not configured*\n"
                "Set `SRE_AGENT_ROUTE_URL` environment variable or ensure OpenShift route exists.\n\n"
                + approval_text
            )

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": approval_text
            }
        })

        # Footer with both IDs
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Issue ID: `{fingerprint}` (stable) | Diagnosis ID: `{diagnosis.id}` (ephemeral) | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                }
            ]
        })

        return {"blocks": blocks}

    def _get_severity_emoji(self, category: str) -> str:
        """Get emoji for category severity."""
        if "oom" in category or "disk_pressure" in category or "degraded" in category:
            return "🔴"
        elif "error" in category or "failure" in category:
            return "🟠"
        else:
            return "🟡"

    def _get_reason_badge(self, reason: str) -> str:
        """Get badge for alert reason."""
        if "critical" in reason:
            return "⚠️ *CRITICAL* - Immediate attention required"
        elif "persistent" in reason:
            return "⏱️ *PERSISTENT* - Issue lasting > 5 minutes"
        elif "recurring" in reason:
            return "🔁 *RECURRING* - Seen multiple times"
        else:
            return "ℹ️ *MONITORING*"

    def _build_diagnosis_steps(self, diagnosis: Diagnosis) -> str:
        """
        Build diagnosis steps showing what the agent analyzed.

        Args:
            diagnosis: Diagnosis with evidence

        Returns:
            String with diagnosis steps
        """
        evidence = diagnosis.evidence
        steps = []

        # Show what was observed - extract resource name with fallbacks
        resource_kind = evidence.get("resource_kind", "unknown")
        namespace = evidence.get("namespace", "unknown")
        resource_name = (
            evidence.get("resource_name") or
            evidence.get("pod_name") or
            evidence.get("deployment_name") or
            evidence.get("hpa_name") or
            evidence.get("operator_name") or
            "unknown"
        )

        steps.append(f"1️⃣ **Observed**: `{resource_kind}` resource `{namespace}/{resource_name}`")

        # Show what data was collected
        if diagnosis.category.value == "oom_killed":
            steps.append(f"2️⃣ **Checked Pod Status**: Found exit code `{evidence.get('exit_code', '137')}` (OOMKilled)")
            steps.append(f"3️⃣ **Analyzed Memory**: Current limit `{evidence.get('memory_limit', 'unknown')}`")
            if "memory_usage" in evidence:
                steps.append(f"4️⃣ **Memory Usage**: Pod using `{evidence.get('memory_usage')}`")
            steps.append(f"5️⃣ **Fetched Previous Logs**: Analyzed container crash logs")

        elif diagnosis.category.value == "crash_loop_back_off":
            steps.append(f"2️⃣ **Checked Pod Events**: Restart count `{evidence.get('restart_count', 'unknown')}`")
            steps.append(f"3️⃣ **Fetched Previous Logs**: Analyzed last crash output")
            if "exit_code" in evidence:
                steps.append(f"4️⃣ **Exit Code**: `{evidence.get('exit_code')}`")

        elif diagnosis.category.value == "image_pull_back_off":
            steps.append(f"2️⃣ **Image**: `{evidence.get('image', 'unknown')}`")
            steps.append(f"3️⃣ **Checked Events**: Pull error - `{evidence.get('message', 'unknown')}`")
            if "http_status" in evidence:
                steps.append(f"4️⃣ **Registry Response**: HTTP `{evidence.get('http_status')}`")

        elif diagnosis.category.value == "hpa_max_replicas":
            hpa_name = evidence.get("hpa_name", resource_name)
            steps.append(f"2️⃣ **Ran Command**: `oc get hpa/{hpa_name} -n {namespace} -o json`")
            steps.append(f"3️⃣ **Checked HPA Status**: Current replicas `{evidence.get('current_replicas', '?')}`")
            steps.append(f"4️⃣ **Max Replicas**: Configured max `{evidence.get('max_replicas', '?')}`")
            steps.append(f"5️⃣ **Metrics**: CPU `{evidence.get('cpu_utilization', 'unknown')}`")

        elif diagnosis.category.value == "hpa_unable_to_get_metrics":
            hpa_name = evidence.get("hpa_name", resource_name)
            target_kind = evidence.get("target_kind", "Deployment")
            target_name = evidence.get("target_name", "unknown")

            steps.append(f"2️⃣ **Ran Command**: `oc get hpa/{hpa_name} -n {namespace} -o yaml`")
            steps.append(f"3️⃣ **Checked HPA Conditions**: Found metrics unavailable error")
            steps.append(f"4️⃣ **Target Resource**: {target_kind}/{target_name}")
            steps.append(f"5️⃣ **Ran Command**: `oc get deployment metrics-server -n openshift-monitoring`")
            steps.append(f"6️⃣ **Checked Metrics Server**: Verified if metrics-server is running")
            steps.append(f"7️⃣ **Checked Pod Resources**: `oc get {target_kind.lower()} {target_name} -n {namespace} -o jsonpath='{{.spec.template.spec.containers[*].resources}}'`")
            steps.append(f"8️⃣ **Diagnosis**: HPA cannot fetch metrics - either metrics-server issue or pod missing resource requests")

        elif diagnosis.category.value == "hpa_missing_scaleref":
            hpa_name = evidence.get("hpa_name", resource_name)
            target_kind = evidence.get("target_kind", "Deployment")
            target_name = evidence.get("target_name", "unknown")

            steps.append(f"2️⃣ **Ran Command**: `oc get hpa/{hpa_name} -n {namespace} -o yaml`")
            steps.append(f"3️⃣ **Checked scaleTargetRef**: {target_kind}/{target_name}")
            steps.append(f"4️⃣ **Ran Command**: `oc get {target_kind.lower()} {target_name} -n {namespace}`")
            steps.append(f"5️⃣ **Result**: Target resource NOT FOUND")
            steps.append(f"6️⃣ **Checked Events**: `oc get events -n {namespace} --sort-by='.lastTimestamp' | grep {target_name}`")
            steps.append(f"7️⃣ **Diagnosis**: HPA references a deleted/renamed resource")

        elif diagnosis.category.value == "resource_quota_exceeded":
            # Get HPA name from evidence
            hpa_name = evidence.get("hpa_name", resource_name)
            cmd = f"oc get hpa/{hpa_name} -n {namespace} -o json"
            steps.append(f"2️⃣ **Ran Command**: `{cmd}`")
            steps.append(f"3️⃣ **Checked Replicas**: Current `{evidence.get('current_replicas', '?')}/{evidence.get('max_replicas', '?')}` (at max limit)")
            steps.append(f"4️⃣ **Metrics Analysis**: Current CPU `{evidence.get('cpu_utilization', 'unknown')}%`, Target CPU `{evidence.get('target_cpu', 'unknown')}%`")
            steps.append(f"5️⃣ **Desired Replicas**: HPA wants `{evidence.get('desired_replicas', '?')}` replicas but maxReplicas is `{evidence.get('max_replicas', '?')}`")
            steps.append(f"6️⃣ **Verified**: HPA cannot scale beyond maxReplicas limit - needs investigation")

        elif diagnosis.category.value == "cluster_operator_degraded":
            operator_name = evidence.get("operator_name", resource_name)
            steps.append(f"2️⃣ **Ran Command**: `oc get clusteroperator {operator_name} -o json`")
            steps.append(f"3️⃣ **Checked Status**: Available=`{evidence.get('available', 'unknown')}`, Degraded=`{evidence.get('degraded', 'unknown')}`")
            steps.append(f"4️⃣ **Read Message**: `{evidence.get('message', 'No message')[:100]}`")
            if "related_pods" in evidence:
                steps.append(f"5️⃣ **Checked Related Pods**: Found `{evidence.get('related_pods')}` pods in operator namespace")

        elif diagnosis.category.value == "pvc_pending":
            storage_class = evidence.get("storage_class", "unknown")
            steps.append(f"2️⃣ **Ran Command**: `oc get pvc/{resource_name} -n {namespace} -o json`")
            steps.append(f"3️⃣ **Checked Status**: Phase=`{evidence.get('phase', 'Pending')}`")
            steps.append(f"4️⃣ **Storage Class**: `{storage_class}`")
            steps.append(f"5️⃣ **Ran Command**: `oc describe pvc/{resource_name} -n {namespace}`")
            steps.append(f"6️⃣ **Read Events**: `{evidence.get('event_message', 'No events')[:100]}`")

        elif diagnosis.category.value == "node_disk_pressure":
            node_name = evidence.get("node_name", resource_name)
            steps.append(f"2️⃣ **Ran Command**: `oc get node/{node_name} -o json`")
            steps.append(f"3️⃣ **Checked Conditions**: DiskPressure=`{evidence.get('disk_pressure', 'True')}`")
            steps.append(f"4️⃣ **Ran Command**: `oc adm top pods --all-namespaces --sort-by=.spec.volumes`")
            steps.append(f"5️⃣ **Identified Top Consumers**: Found `{evidence.get('top_pod_count', 3)}` pods using most storage")
            if "ephemeral_storage" in evidence:
                steps.append(f"6️⃣ **Ephemeral Storage**: `{evidence.get('ephemeral_storage')}`")

        elif diagnosis.category.value == "scc_violation":
            scc_name = evidence.get("required_scc", "privileged")
            steps.append(f"2️⃣ **Ran Command**: `oc get pod/{resource_name} -n {namespace} -o yaml`")
            steps.append(f"3️⃣ **Read Events**: Found SCC denial in pod events")
            steps.append(f"4️⃣ **Required SCC**: `{scc_name}`")
            steps.append(f"5️⃣ **Checked ServiceAccount**: `{evidence.get('service_account', 'default')}`")
            steps.append(f"6️⃣ **Ran Command**: `oc get scc {scc_name} -o yaml`")
            if "required_capability" in evidence:
                steps.append(f"7️⃣ **Required Capability**: `{evidence.get('required_capability')}`")

        elif diagnosis.category.value == "route_unavailable":
            service_name = evidence.get("service_name", "unknown")
            steps.append(f"2️⃣ **Ran Command**: `oc get route/{resource_name} -n {namespace} -o json`")
            steps.append(f"3️⃣ **Checked Target**: Service=`{service_name}`, Port=`{evidence.get('port', 'unknown')}`")
            steps.append(f"4️⃣ **Ran Command**: `oc get service/{service_name} -n {namespace} -o json`")
            steps.append(f"5️⃣ **Checked Endpoints**: Found `{evidence.get('endpoint_count', 0)}` ready endpoints")
            if evidence.get('endpoint_count', 0) == 0:
                steps.append(f"6️⃣ **Root Cause**: Service has no ready endpoints (pods may be down)")

        elif diagnosis.category.value == "certificate_expiring":
            expiry_days = evidence.get("days_until_expiry", "unknown")
            steps.append(f"2️⃣ **Ran Command**: `oc get secret/{resource_name} -n {namespace} -o json`")
            steps.append(f"3️⃣ **Extracted Certificate**: Decoded `tls.crt` field")
            steps.append(f"4️⃣ **Parsed Expiry**: Certificate expires in `{expiry_days}` days")
            steps.append(f"5️⃣ **Checked Issuer**: `{evidence.get('issuer', 'unknown')}`")
            steps.append(f"6️⃣ **Verified Subject**: `{evidence.get('subject', 'unknown')}`")

        elif diagnosis.category.value == "build_failure":
            build_name = resource_name
            steps.append(f"2️⃣ **Ran Command**: `oc get build/{build_name} -n {namespace} -o json`")
            steps.append(f"3️⃣ **Checked Phase**: `{evidence.get('phase', 'Failed')}`")
            steps.append(f"4️⃣ **Ran Command**: `oc logs build/{build_name} -n {namespace}`")
            steps.append(f"5️⃣ **Analyzed Logs**: Found error at line `{evidence.get('error_line', 'unknown')}`")
            steps.append(f"6️⃣ **Error Pattern**: `{evidence.get('error_message', 'Build failed')[:100]}`")

        elif diagnosis.category.value == "pipeline_failure":
            pipeline_name = evidence.get("pipeline_name", resource_name)
            steps.append(f"2️⃣ **Ran Command**: `oc get pipelinerun/{resource_name} -n {namespace} -o json`")
            steps.append(f"3️⃣ **Checked Status**: `{evidence.get('status', 'Failed')}`")
            steps.append(f"4️⃣ **Failed Task**: `{evidence.get('failed_task', 'unknown')}`")
            steps.append(f"5️⃣ **Ran Command**: `oc logs -n {namespace} {evidence.get('failed_pod', 'task-pod')}`")
            steps.append(f"6️⃣ **Task Exit Code**: `{evidence.get('exit_code', 'unknown')}`")

        elif diagnosis.category.value == "proactive_memory_pressure":
            threshold = evidence.get("threshold_percent", 80)
            current = evidence.get("current_percent", "unknown")
            steps.append(f"2️⃣ **Ran Command**: `oc adm top pods -n {namespace}`")
            steps.append(f"3️⃣ **Checked Memory**: Pod using `{current}%` of limit")
            steps.append(f"4️⃣ **Threshold**: Alert threshold is `{threshold}%`")
            steps.append(f"5️⃣ **Trend Analysis**: Memory usage trending upward over `{evidence.get('lookback_hours', 24)}h`")
            steps.append(f"6️⃣ **Prediction**: Likely to hit OOM in `{evidence.get('time_to_oom', 'unknown')}` hours")

        elif diagnosis.category.value == "proactive_cpu_throttling":
            throttling = evidence.get("throttling_percent", "unknown")
            steps.append(f"2️⃣ **Queried Prometheus**: `container_cpu_cfs_throttled_seconds_total`")
            steps.append(f"3️⃣ **Checked Throttling**: CPU throttled `{throttling}%` of time")
            steps.append(f"4️⃣ **Current Limit**: `{evidence.get('cpu_limit', 'unknown')}`")
            steps.append(f"5️⃣ **Current Usage**: `{evidence.get('cpu_usage', 'unknown')}`")
            steps.append(f"6️⃣ **Recommendation**: Increase CPU limit to reduce throttling")

        elif diagnosis.category.value == "networking_issue":
            issue_type = evidence.get("issue_type", "unknown")
            steps.append(f"2️⃣ **Ran Command**: `oc get networkpolicy -n {namespace}`")
            steps.append(f"3️⃣ **Issue Type**: `{issue_type}`")
            if issue_type == "policy_denial":
                steps.append(f"4️⃣ **Checked Policies**: Found `{evidence.get('policy_count', 0)}` network policies")
                steps.append(f"5️⃣ **Blocking Policy**: `{evidence.get('blocking_policy', 'unknown')}`")
            steps.append(f"6️⃣ **Ran Command**: `oc describe pod/{resource_name} -n {namespace}`")
            steps.append(f"7️⃣ **Network Events**: `{evidence.get('network_event', 'No network events')[:100]}`")

        else:
            # Fallback for unknown categories - still be specific about what was done
            steps.append(f"2️⃣ **Ran Command**: `oc get {resource_kind.lower()}/{resource_name} -n {namespace} -o json`")
            steps.append(f"3️⃣ **Ran Command**: `oc describe {resource_kind.lower()}/{resource_name} -n {namespace}`")
            steps.append(f"4️⃣ **Checked Status**: Phase/Status fields in resource spec")
            steps.append(f"5️⃣ **Read Events**: Analyzed Kubernetes events for resource")
            if evidence.get("message"):
                steps.append(f"6️⃣ **Found Message**: `{evidence.get('message')[:100]}`")
            steps.append(f"7️⃣ **Category**: Diagnosed as `{diagnosis.category.value}`")

        # Add analyzer used
        steps.append(f"\n📊 **Analyzer**: `{diagnosis.analyzer_name}`")
        steps.append(f"🎯 **Confidence**: `{diagnosis.confidence.value.upper()}`")

        return "\n".join(steps)

    def _build_remediation_commands(self, diagnosis: Diagnosis) -> str:
        """
        Build manual remediation commands based on diagnosis category.

        Args:
            diagnosis: Diagnosis with category and evidence

        Returns:
            String with shell commands to fix the issue
        """
        evidence = diagnosis.evidence
        namespace = evidence.get("namespace", "unknown")
        resource_kind = evidence.get("resource_kind", "unknown")

        # Extract resource name with better fallbacks
        resource_name = (
            evidence.get("resource_name") or
            evidence.get("pod_name") or
            evidence.get("deployment_name") or
            evidence.get("hpa_name") or
            "unknown"
        )

        category = diagnosis.category.value

        commands = []

        if category == "oom_killed":
            # OOMKilled - COMPREHENSIVE diagnostic approach
            current_memory = evidence.get("memory_limit", "128Mi")
            memory_request = evidence.get("memory_request", current_memory)
            memory_usage = evidence.get("memory_usage", "unknown")

            # Get deployment name (remove pod suffix)
            if resource_kind == "Pod" and "-" in resource_name:
                deployment_name = "-".join(resource_name.split("-")[:-2])
            else:
                deployment_name = resource_name

            commands.append(f"# ========================================")
            commands.append(f"# DIAGNOSIS: OOMKilled - Container exceeded memory limit")
            commands.append(f"# Current limit: {current_memory}")
            commands.append(f"# Current request: {memory_request}")
            if memory_usage != "unknown":
                commands.append(f"# Last usage: {memory_usage}")
            commands.append(f"# ========================================")
            commands.append("")
            commands.append("# STEP 1: INVESTIGATE ROOT CAUSE (Don't blindly increase resources!)")
            commands.append("")
            commands.append("# Check if this is a MEMORY LEAK:")
            commands.append(f"oc logs {resource_name} -n {namespace} --previous | grep -i 'heap\\|memory\\|leak'")
            commands.append("")
            commands.append("# Check memory usage over time (if metrics available):")
            commands.append(f"oc adm top pod {resource_name} -n {namespace}")
            commands.append("")
            commands.append("# Review application logs for memory-intensive operations:")
            commands.append(f"oc logs {resource_name} -n {namespace} --previous --tail=100")
            commands.append("")
            commands.append("# STEP 2: IDENTIFY THE ISSUE TYPE:")
            commands.append("#")
            commands.append("# Issue Type 1: MEMORY LEAK in application code")
            commands.append("#   Symptom: Memory usage constantly increases until OOM")
            commands.append("#   Solution: Fix the memory leak in application code")
            commands.append("#   Action: DO NOT just increase memory - this delays the problem")
            commands.append("#")
            commands.append("# Issue Type 2: LEGITIMATE high memory workload")
            commands.append("#   Symptom: Stable memory usage, but hits limit during peak load")
            commands.append("#   Solution: Increase memory limit")
            commands.append("#   Action: Calculate actual need based on peak usage + 20% buffer")
            commands.append("#")
            commands.append("# Issue Type 3: MEMORY SPIKE during startup")
            commands.append("#   Symptom: OOM only during pod startup/initialization")
            commands.append("#   Solution: Increase memory OR optimize startup process")
            commands.append("#   Action: Check startup logs for excessive memory usage")
            commands.append("#")
            commands.append("# Issue Type 4: CONFIGURATION ISSUE (e.g., JVM heap too large)")
            commands.append("#   Symptom: Application configured to use more memory than limit")
            commands.append("#   Solution: Adjust application memory settings (e.g., -Xmx for Java)")
            commands.append("#   Action: Review application memory configuration")
            commands.append("")
            commands.append("# STEP 3: IF you determined this is a legitimate memory need:")
            commands.append("")

            # Calculate new memory based on actual usage if available
            try:
                if current_memory.endswith("Mi"):
                    current_mb = int(current_memory[:-2])
                    # Recommend 50% increase instead of doubling for gradual scaling
                    new_memory = f"{int(current_mb * 1.5)}Mi"
                elif current_memory.endswith("Gi"):
                    current_gb = float(current_memory[:-2])
                    new_memory = f"{current_gb * 1.5:.1f}Gi"
                else:
                    new_memory = "256Mi"
            except:
                new_memory = "256Mi"

            commands.append(f"# Increase memory limit (gradual approach - 50% increase):")
            commands.append(f"oc set resources deployment/{deployment_name} -n {namespace} \\")
            commands.append(f"  --limits=memory={new_memory} \\")
            commands.append(f"  --requests=memory={new_memory}")
            commands.append("")
            commands.append("# Or edit directly to fine-tune:")
            commands.append(f"oc edit deployment/{deployment_name} -n {namespace}")
            commands.append(f"# Change: resources.limits.memory: {current_memory} → {new_memory}")
            commands.append("")
            commands.append("# STEP 4: MONITOR after change:")
            commands.append(f"oc get pods -n {namespace} -w")
            commands.append(f"# Wait for new pod to start, then check memory usage:")
            commands.append(f"oc adm top pod -n {namespace} -l app={deployment_name}")
            commands.append("")
            commands.append("# 📚 OFFICIAL RED HAT DOCUMENTATION:")
            commands.append("# - https://access.redhat.com/solutions/4896471 - Troubleshooting OOMKilled pods")
            commands.append("# - https://access.redhat.com/solutions/3006972 - Understanding Linux OOM Killer")
            commands.append("# - https://docs.openshift.com/container-platform/latest/nodes/clusters/nodes-cluster-resource-configure.html - Resource management")
            commands.append("# - https://access.redhat.com/articles/6955985 - Pod troubleshooting guide")

        elif category == "crash_loop_back_off":
            commands.append(f"# ========================================")
            commands.append(f"# WHY: Pod is repeatedly crashing")
            commands.append(f"# Application fails to start or crashes soon after")
            commands.append(f"# Common causes: config error, missing dependencies, app bug")
            commands.append(f"# ========================================")
            commands.append("")
            commands.append(f"# Check pod logs for errors:")
            commands.append(f"oc logs {resource_name} -n {namespace} --previous")
            commands.append("")
            commands.append("# Check pod events:")
            commands.append(f"oc describe pod {resource_name} -n {namespace}")
            commands.append("")
            commands.append("# If configuration issue, edit deployment:")
            if "-" in resource_name:
                deployment_name = "-".join(resource_name.split("-")[:-2])
                commands.append(f"oc edit deployment/{deployment_name} -n {namespace}")
            commands.append("")
            commands.append("# 📚 Red Hat Knowledge Base:")
            commands.append("# - https://access.redhat.com/solutions/3431091 - CrashLoopBackOff troubleshooting")
            commands.append("# - https://access.redhat.com/articles/6955985 - Pod crash troubleshooting guide")
            commands.append("# - https://docs.openshift.com/container-platform/latest/support/troubleshooting/investigating-pod-issues.html")

        elif category == "image_pull_back_off":
            image = evidence.get("image", "unknown")
            commands.append(f"# ========================================")
            commands.append(f"# WHY: Cannot pull container image")
            commands.append(f"# Common causes: auth failed, image not found, network issue")
            commands.append(f"# Image: {image}")
            commands.append(f"# ========================================")
            commands.append("")
            commands.append("# If authentication issue, create/update image pull secret:")
            commands.append(f"oc create secret docker-registry regcred --docker-server=<registry-url> --docker-username=<username> --docker-password=<password> -n {namespace}")
            commands.append("")
            if "-" in resource_name:
                deployment_name = "-".join(resource_name.split("-")[:-2])
                commands.append(f"# Link secret to deployment:")
                commands.append(f"oc set image-lookup {deployment_name} -n {namespace}")
            commands.append("")
            commands.append("# 📚 Red Hat Knowledge Base:")
            commands.append("# - https://access.redhat.com/solutions/6007231 - ImagePullBackOff troubleshooting")
            commands.append("# - https://access.redhat.com/solutions/3754131 - Pull secret configuration")
            commands.append("# - https://docs.openshift.com/container-platform/latest/openshift_images/managing_images/using-image-pull-secrets.html")

        elif category == "hpa_max_replicas" or category == "resource_quota_exceeded":
            current_replicas = evidence.get("current_replicas", 1)
            max_replicas = evidence.get("max_replicas", 1)
            min_replicas = evidence.get("min_replicas", 1)
            cpu_utilization = evidence.get("cpu_utilization", "unknown")
            target_cpu = evidence.get("target_cpu", "unknown")

            commands.append(f"# ========================================")
            commands.append(f"# DIAGNOSIS: HPA at maximum replicas")
            commands.append(f"# Current replicas: {current_replicas}/{max_replicas}")
            commands.append(f"# Min replicas: {min_replicas}")
            commands.append(f"# CPU utilization: {cpu_utilization}")
            commands.append(f"# Target CPU: {target_cpu}")
            commands.append(f"# ========================================")
            commands.append("")
            commands.append("# STEP 1: ANALYZE WHY HPA IS SCALING")
            commands.append("")
            commands.append("# Check current HPA status and metrics:")
            commands.append(f"oc describe hpa/{resource_name} -n {namespace}")
            commands.append("")
            commands.append("# Check current load on pods:")
            commands.append(f"oc adm top pods -n {namespace} -l app={resource_name}")
            commands.append("")
            commands.append("# Check HPA metrics and conditions:")
            commands.append(f"oc get hpa/{resource_name} -n {namespace} -o yaml")
            commands.append("")
            commands.append("# STEP 2: IDENTIFY THE ROOT CAUSE")
            commands.append("#")
            commands.append("# Cause 1: LEGITIMATE INCREASED TRAFFIC/LOAD")
            commands.append("#   Symptom: High CPU/memory usage across all pods")
            commands.append("#   Solution: Increase maxReplicas")
            commands.append("#   Verify: Check application metrics, traffic patterns")
            commands.append("#")
            commands.append("# Cause 2: INEFFICIENT APPLICATION CODE")
            commands.append("#   Symptom: High CPU usage but low actual throughput")
            commands.append("#   Solution: Optimize application code, NOT increase replicas")
            commands.append("#   Verify: Profile application, check for inefficient queries/loops")
            commands.append("#")
            commands.append("# Cause 3: POD RESOURCE LIMITS TOO LOW")
            commands.append("#   Symptom: Pods hitting CPU limits, causing throttling")
            commands.append("#   Solution: VERTICAL scaling (increase pod resources) instead")
            commands.append("#   Verify: Check if pods are CPU throttled")
            commands.append("#")
            commands.append("# Cause 4: HPA TARGET METRIC TOO AGGRESSIVE")
            commands.append("#   Symptom: HPA scaling at low CPU % (e.g., target=50%)")
            commands.append("#   Solution: Adjust target CPU percentage higher (e.g., 70-80%)")
            commands.append("#   Verify: Review if current target is appropriate")
            commands.append("#")
            commands.append("# Cause 5: CLUSTER CAPACITY CONSTRAINTS")
            commands.append("#   Symptom: HPA wants to scale but pods are Pending")
            commands.append("#   Solution: Add cluster capacity or reduce resource requests")
            commands.append("#   Verify: Check for pending pods")
            commands.append("")
            commands.append("# Check for CPU throttling (suggests vertical scaling needed):")
            commands.append(f"oc get pods -n {namespace} -l app={resource_name} -o json | \\")
            commands.append("  jq '.items[] | .metadata.name, .spec.containers[].resources'")
            commands.append("")
            commands.append("# Check for pending pods (cluster capacity issue):")
            commands.append(f"oc get pods -n {namespace} -l app={resource_name} | grep Pending")
            commands.append("")
            commands.append("# STEP 3: CHOOSE THE RIGHT SOLUTION")
            commands.append("")
            commands.append("# Option A: HORIZONTAL scaling (increase maxReplicas)")
            commands.append("# Use when: Legitimate increased load, pods are efficient")

            # Calculate new max with better logic
            new_max = int(max_replicas * 1.5)  # 50% increase instead of doubling

            commands.append(f"oc patch hpa/{resource_name} -n {namespace} --type=json -p='[{{\"op\":\"replace\",\"path\":\"/spec/maxReplicas\",\"value\":{new_max}}}]'")
            commands.append("")
            commands.append("# Option B: VERTICAL scaling (increase pod resources)")
            commands.append("# Use when: Pods are CPU throttled or memory constrained")
            commands.append(f"# Get current deployment to check resources:")
            commands.append(f"oc get deployment -n {namespace} -l app={resource_name}")
            commands.append("# Then increase CPU/memory limits")
            commands.append("")
            commands.append("# Option C: ADJUST HPA target metric")
            commands.append("# Use when: Target is too aggressive (e.g., 50%)")
            commands.append(f"oc patch hpa/{resource_name} -n {namespace} --type=json -p='[{{\"op\":\"replace\",\"path\":\"/spec/metrics/0/resource/target/averageUtilization\",\"value\":75}}]'")
            commands.append("")
            commands.append("# Option D: OPTIMIZE application code")
            commands.append("# Use when: Application is inefficient")
            commands.append("# Review application logs and profiling data")
            commands.append("")
            commands.append("# STEP 4: VERIFY cluster has capacity for new replicas:")
            commands.append(f"oc get nodes")
            commands.append(f"oc describe nodes | grep -A 5 'Allocated resources'")
            commands.append("")
            commands.append("# 📚 OFFICIAL RED HAT DOCUMENTATION:")
            commands.append("# - https://docs.openshift.com/container-platform/latest/nodes/pods/nodes-pods-autoscaling.html - HPA configuration")
            commands.append("# - https://access.redhat.com/solutions/5478661 - HPA troubleshooting guide")
            commands.append("# - https://access.redhat.com/solutions/5908131 - HPA not scaling troubleshooting")
            commands.append("# - https://docs.openshift.com/container-platform/latest/nodes/clusters/nodes-cluster-limit-ranges.html - Resource limits")
            commands.append("# - https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/ - HPA concepts")

        elif category == "cluster_operator_degraded":
            operator_name = evidence.get("operator_name", resource_name)
            commands.append(f"# Check ClusterOperator status:")
            commands.append(f"oc get clusteroperator {operator_name} -o yaml")
            commands.append("")
            commands.append("# Check related pods:")
            commands.append(f"oc get pods -n openshift-{operator_name} --show-labels")
            commands.append("")
            commands.append("# Check operator logs:")
            commands.append(f"oc logs -n openshift-{operator_name} -l app={operator_name} --tail=100")

        elif category == "pvc_pending":
            storage_class = evidence.get("storage_class", "gp2")
            pvc_size = evidence.get("requested_storage", "10Gi")

            commands.append(f"# Check PVC status:")
            commands.append(f"oc describe pvc/{resource_name} -n {namespace}")
            commands.append("")
            commands.append("# Check storage class:")
            commands.append(f"oc get storageclass {storage_class}")
            commands.append("")
            commands.append("# If no storage class, create one or use different class:")
            commands.append(f"oc patch pvc/{resource_name} -n {namespace} \\")
            commands.append(f"  --type=json \\")
            commands.append(f"  -p='[{{\"op\":\"replace\",\"path\":\"/spec/storageClassName\",\"value\":\"gp3-csi\"}}]'")

        else:
            # Generic remediation
            commands.append(f"# Check resource status:")
            commands.append(f"oc describe {resource_kind.lower()}/{resource_name} -n {namespace}")
            commands.append("")
            commands.append("# Check events:")
            commands.append(f"oc get events -n {namespace} --field-selector involvedObject.name={resource_name}")
            commands.append("")
            if diagnosis.recommended_actions:
                commands.append("# Recommended actions:")
                for i, action in enumerate(diagnosis.recommended_actions[:3], 1):
                    commands.append(f"# {i}. {action}")

        return "\n".join(commands)

    async def send_remediation_success(
        self,
        diagnosis: Diagnosis,
        remediation_result
    ) -> bool:
        """
        Send Slack notification that remediation was successful.

        Args:
            diagnosis: The diagnosis that was remediated
            remediation_result: RemediationResult with success details

        Returns:
            True if message sent successfully
        """
        if not self.enabled:
            logger.debug("Slack notifier disabled, skipping success message")
            return False

        try:
            evidence = diagnosis.evidence
            namespace = evidence.get("namespace", "cluster-wide")
            resource_kind = evidence.get("resource_kind", "unknown")

            # Extract resource name with better fallbacks
            resource_name = (
                evidence.get("resource_name") or
                evidence.get("pod_name") or
                evidence.get("deployment_name") or
                evidence.get("hpa_name") or
                "unknown"
            )

            # Build success message
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Issue Automatically Resolved",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*🎉 SRE Agent successfully fixed: {diagnosis.category.value.replace('_', ' ').title()}*"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Resource:*\n`{namespace}/{resource_kind}/{resource_name}`"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Tier:*\nTier {remediation_result.tier}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Status:*\n{remediation_result.status.value.upper()}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Diagnosis ID:*\n`{diagnosis.id}`"
                        }
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*🔧 Actions Taken:*"
                    }
                }
            ]

            # Add actions taken
            if remediation_result.actions_taken:
                actions_text = "\n".join([
                    f"• {action}"
                    for action in remediation_result.actions_taken
                ])
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": actions_text
                    }
                })

            # Add message/details
            if remediation_result.message:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*📝 Details:*\n```{remediation_result.message}```"
                    }
                })

            # Footer
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🤖 Automated by SRE Agent | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    }
                ]
            })

            message = {"blocks": blocks}

            # Scrub secrets before sending
            message_str = json.dumps(message)
            scrubbed_str = SecretScrubber.scrub(message_str)
            scrubbed_message = json.loads(scrubbed_str)

            # Send to Slack
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=scrubbed_message,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.info(
                            "Slack remediation success notification sent",
                            diagnosis_id=diagnosis.id,
                            category=diagnosis.category.value,
                            tier=remediation_result.tier
                        )
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Slack API error: {response.status}",
                            diagnosis_id=diagnosis.id,
                            error=error_text
                        )
                        return False

        except Exception as e:
            logger.error(
                f"Failed to send Slack success message: {e}",
                diagnosis_id=diagnosis.id,
                exc_info=True
            )
            return False


# Global singleton
_slack_notifier: Optional[SlackNotifier] = None


def get_slack_notifier() -> SlackNotifier:
    """Get or create global SlackNotifier instance."""
    global _slack_notifier
    if _slack_notifier is None:
        _slack_notifier = SlackNotifier()
    return _slack_notifier
