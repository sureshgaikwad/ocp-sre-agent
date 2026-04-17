# Interactive Remediation with Noise Reduction

## Overview

The SRE Agent now features intelligent event deduplication, noise filtering, and interactive Slack-based remediation approval.

## Features

### 1. Event Deduplication & Noise Reduction

The agent tracks issues over time and only alerts when:

- **Critical Issues**: OOMKilled, ClusterOperator degraded (immediate alert)
- **Persistent Issues**: Issue lasts > 5 minutes
- **Recurring Issues**: Issue occurs > 3 times

This prevents Slack notification spam by filtering transient issues.

### 2. Interactive Slack Remediation

When a real problem is detected, the agent:
1. Sends a rich Slack message with:
   - Root cause analysis
   - Diagnostic evidence
   - Recommended actions
   - Approval instructions

2. Waits for user approval before remediation

3. Remediates only if user approves

## Configuration

### Environment Variables

Add to `agent-config` ConfigMap:
```yaml
# Event Deduplication
EVENT_PERSISTENCE_THRESHOLD_MINUTES: "5"   # Alert if issue persists this long
EVENT_OCCURRENCE_THRESHOLD: "3"            # Alert if seen this many times
EVENT_TTL_MINUTES: "60"                     # Remember resolved issues for this long
```

### Slack Webhook Setup

1. Create Slack webhook:
   - Go to https://api.slack.com/messaging/webhooks
   - Create incoming webhook for your channel
   - Copy webhook URL

2. Update secret:
```bash
oc create secret generic slack-webhook-secret \
  --from-literal=SLACK_WEBHOOK_URL='https://hooks.slack.com/services/YOUR/WEBHOOK/URL' \
  -n sre-agent
```

## Usage Workflow

### Scenario: HPA at Max Replicas

#### 1. Agent Detection
Agent detects HPA at maximum replicas (seen 3 times):
```
🔁 RECURRING - Seen multiple times
Resource: models/HorizontalPodAutoscaler/qwen-25-7b-predictor
```

#### 2. Slack Notification

Message posted to Slack:
```
🤖 SRE Agent Remediation Request

🟡 Resource Quota Exceeded
🔁 RECURRING - Seen multiple times

Resource: `models/HorizontalPodAutoscaler/qwen-25-7b-predictor`
Confidence: HIGH

🔍 Root Cause:
HPA reached maximum replicas (1), consider increasing maxReplicas

🔧 Recommended Actions:
1. Increase HPA maxReplicas from 1 to 2
2. Verify cluster has capacity for additional pods
3. Consider vertical scaling (increase pod resources) instead

📊 Evidence:
• current_replicas: `1`
• max_replicas: `1`

Do you want the SRE Agent to remediate this issue?

To approve remediation:
curl -X POST http://sre-agent.sre-agent.svc:8000/approve-remediation \
  -H 'Content-Type: application/json' \
  -d '{
    "diagnosis_id": "bd8b6258-c451-4a3c-b55d-1f5459b4f315",
    "approved": true
  }'

Diagnosis ID: bd8b6258-c451-4a3c-b55d-1f5459b4f315 | 2026-04-16 14:21:53 UTC
```

#### 3. User Approval

**Option A: Approve**
```bash
curl -X POST http://sre-agent.sre-agent.svc:8000/approve-remediation \
  -H 'Content-Type: application/json' \
  -d '{
    "diagnosis_id": "bd8b6258-c451-4a3c-b55d-1f5459b4f315",
    "approved": true
  }'
```

Response:
```json
{
  "status": "success",
  "message": "✅ Remediation approved",
  "action": "Will remediate on next workflow cycle (within 1 minute)"
}
```

**Option B: Reject**
```bash
curl -X POST http://sre-agent.sre-agent.svc:8000/approve-remediation \
  -H 'Content-Type: application/json' \
  -d '{
    "diagnosis_id": "bd8b6258-c451-4a3c-b55d-1f5459b4f315",
    "approved": false
  }'
```

#### 4. Remediation Execution

If approved, agent:
1. Waits for next workflow cycle (< 1 minute)
2. Checks for approval
3. Proceeds with remediation (GitHub issue, GitOps PR, or auto-fix)

## Noise Reduction Examples

### Example 1: Transient ImagePullBackOff

```
First occurrence (10:00):
  ❌ No alert - may be transient registry issue

Second occurrence (10:01):
  ❌ No alert - still within 5-minute window, only 2 occurrences

Third occurrence (10:02):
  ✅ ALERT - Recurring issue (3 occurrences)
  📨 Slack notification sent
```

### Example 2: Persistent OOMKilled

```
First detection (10:00):
  ✅ ALERT IMMEDIATELY - Critical issue with HIGH confidence
  📨 Slack notification sent

(No duplicate alerts even if seen again within 60 minutes)
```

### Example 3: One-Time Error

```
Single occurrence (10:00):
  ❌ No alert - monitoring for persistence

Issue resolved by 10:05:
  ❌ No alert ever sent - was transient
```

## Deduplication Statistics

Check deduplication stats:
```bash
curl http://sre-agent.sre-agent.svc:8000/stats
```

Response includes:
```json
{
  "deduplication": {
    "total_tracked_issues": 5,
    "alerted_issues": 2,
    "pending_issues": 3,
    "remediation_requested": 1
  }
}
```

## Approval Workflow API

### Endpoints

**Approve Remediation**
```
POST /approve-remediation
Content-Type: application/json

{
  "diagnosis_id": "uuid",
  "approved": true|false
}
```

**Get Agent Stats**
```
GET /stats
```

## Troubleshooting

### Slack notifications not appearing

1. Check webhook URL:
```bash
oc get secret slack-webhook-secret -n sre-agent -o jsonpath='{.data.SLACK_WEBHOOK_URL}' | base64 -d
```

2. Check agent logs:
```bash
oc logs -n sre-agent deployment/sre-agent -c agent | grep -i slack
```

3. Test webhook manually:
```bash
curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
  -H 'Content-Type: application/json' \
  -d '{"text":"Test from SRE Agent"}'
```

### Too many/few alerts

Adjust thresholds in ConfigMap:
```yaml
# More alerts (lower thresholds)
EVENT_PERSISTENCE_THRESHOLD_MINUTES: "2"
EVENT_OCCURRENCE_THRESHOLD: "2"

# Fewer alerts (higher thresholds)
EVENT_PERSISTENCE_THRESHOLD_MINUTES: "10"
EVENT_OCCURRENCE_THRESHOLD: "5"
```

### Approval not working

1. Verify diagnosis_id is correct (check Slack message)
2. Check if diagnosis is too old (> 60 minutes by default)
3. Verify agent can reach approval endpoint

## Best Practices

1. **Configure Slack webhook** for best UX
2. **Start with conservative thresholds** (5 min, 3 occurrences)
3. **Monitor deduplication stats** to tune thresholds
4. **Use approval workflow** for production clusters
5. **Create Slack channel** dedicated to SRE Agent alerts

## Security Notes

- Webhook URL is sensitive - store in Kubernetes Secret
- Approval endpoint has no authentication (cluster-internal only)
- For external access, add authentication/authorization
- Secrets are scrubbed from Slack messages before sending
