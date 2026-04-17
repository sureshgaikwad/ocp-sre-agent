# Quick Start Guide - OpenShift SRE Agent

Get the SRE Agent running in **5 minutes**!

## Prerequisites

- OpenShift 4.10+ cluster with cluster-admin access
- LLM endpoint (OpenShift AI, OpenAI, or Anthropic)
- `oc` CLI configured and logged in

## Step 1: Deploy (2 minutes)

```bash
# Create namespace
oc new-project sre-agent

# Deploy agent
oc apply -f deploy/sre-agent-deployment.yaml

# Wait for pod to be ready
oc wait --for=condition=Ready pod -l app=sre-agent -n sre-agent --timeout=300s
```

## Step 2: Configure LLM (1 minute)

### Option A: OpenShift AI with vLLM (Recommended for on-premises)

```bash
oc patch configmap agent-config -n sre-agent --type merge -p '
{
  "data": {
    "LITELLM_URL": "http://qwen-25-7b-predictor.models.svc.cluster.local/v1",
    "LITELLM_MODEL": "qwen-25-7b"
  }
}'

oc patch secret litellm-api-secret -n sre-agent --type merge -p '
{
  "stringData": {
    "LITELLM_API_KEY": "local-model-no-auth"
  }
}'
```

### Option B: OpenAI

```bash
oc patch configmap agent-config -n sre-agent --type merge -p '
{
  "data": {
    "LITELLM_URL": "https://api.openai.com/v1",
    "LITELLM_MODEL": "gpt-4"
  }
}'

oc patch secret litellm-api-secret -n sre-agent --type merge -p '
{
  "stringData": {
    "LITELLM_API_KEY": "sk-your-openai-api-key"
  }
}'
```

### Option C: Anthropic Claude

```bash
oc patch configmap agent-config -n sre-agent --type merge -p '
{
  "data": {
    "LITELLM_URL": "https://api.anthropic.com/v1",
    "LITELLM_MODEL": "claude-3-sonnet-20240229"
  }
}'

oc patch secret litellm-api-secret -n sre-agent --type merge -p '
{
  "stringData": {
    "LITELLM_API_KEY": "sk-ant-your-anthropic-api-key"
  }
}'
```

## Step 3: Restart and Verify (2 minutes)

```bash
# Restart to apply changes
oc rollout restart deployment/sre-agent -n sre-agent

# Wait for rollout
oc rollout status deployment/sre-agent -n sre-agent

# Verify agent is healthy
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  curl -s http://localhost:8000/health | jq .

# Expected output:
{
  "status": "healthy",
  "mode": "reactive",
  "mcp_tools": 44,
  "workflow_engine": {
    "collectors": 9,
    "analyzers": 8,
    "handlers": 3
  },
  "watch_manager": {
    "running": true,
    "watcher_count": 2
  }
}
```

## Step 4: Test It! (Optional)

Create a test pod that will crash:

```bash
# Create OOMKilled test pod
oc create namespace sre-demo || true

cat <<EOF | oc apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oom-test
  namespace: sre-demo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: oom-test
  template:
    metadata:
      labels:
        app: oom-test
    spec:
      containers:
      - name: stress
        image: polinux/stress
        resources:
          limits:
            memory: "20Mi"
          requests:
            memory: "10Mi"
        command: ["stress"]
        args: ["--vm", "1", "--vm-bytes", "50M", "--vm-hang", "1"]
EOF

# Wait 30 seconds for agent to detect and diagnose
sleep 30

# Check agent logs for diagnosis
oc logs -n sre-agent deployment/sre-agent -c agent --tail=100 | grep -A 10 "Diagnosis"
```

**Expected**: Agent detects OOMKilled, diagnoses root cause, and recommends increasing memory limit.

## Step 5: Enable Git Integration (Optional)

For automated issue creation and GitOps PRs:

```bash
# Configure GitHub
oc patch configmap agent-config -n sre-agent --type merge -p '
{
  "data": {
    "GIT_PLATFORM": "github",
    "GIT_SERVER_URL": "https://github.com",
    "GIT_ORGANIZATION": "my-org",
    "GIT_REPOSITORY": "cluster-issues"
  }
}'

# Add GitHub token
oc patch secret git-api-secret -n sre-agent --type merge -p '
{
  "stringData": {
    "GIT_TOKEN": "ghp_your_github_personal_access_token"
  }
}'

# Restart
oc rollout restart deployment/sre-agent -n sre-agent
```

**GitHub Token Requirements**:
- Personal Access Token (PAT) with `repo` scope
- Get from: https://github.com/settings/tokens

## Step 6: Enable Slack Notifications (Optional)

For interactive remediation approvals:

```bash
# Add Slack webhook
oc patch secret slack-webhook-secret -n sre-agent --type merge -p '
{
  "stringData": {
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  }
}'

# Restart
oc rollout restart deployment/sre-agent -n sre-agent
```

**Slack Webhook Setup**:
1. Go to https://api.slack.com/messaging/webhooks
2. Create new webhook for your workspace
3. Copy webhook URL

## Step 7: Enable RAG Knowledge Base (Optional)

For internal runbook search:

```bash
# Enable RAG
oc patch configmap agent-config -n sre-agent --type merge -p '
{
  "data": {
    "RAG_ENABLED": "true"
  }
}'

# Restart
oc rollout restart deployment/sre-agent -n sre-agent

# Wait for pod
oc wait --for=condition=Ready pod -l app=sre-agent -n sre-agent --timeout=120s

# Create sample runbook
cat > /tmp/sample-runbook.md <<'EOF'
# OOMKilled Troubleshooting

## Symptoms
- Pod shows CrashLoopBackOff status
- Exit code 137 in pod events

## Root Cause
Container exceeded memory limit

## Remediation
```bash
oc set resources deployment/<name> -n <namespace> --limits=memory=1Gi
```

## Related
- https://access.redhat.com/solutions/4896471
EOF

# Copy to pod
POD=$(oc get pod -n sre-agent -l app=sre-agent -o name | head -1 | cut -d/ -f2)
oc exec -n sre-agent ${POD} -c agent -- mkdir -p /data/internal-runbooks
oc cp /tmp/sample-runbook.md sre-agent/${POD}:/data/internal-runbooks/sample-runbook.md -c agent

# Index documents
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  curl -X POST http://localhost:8000/index-docs

# Verify
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  curl -s http://localhost:8000/stats | jq '.kb_retriever'
```

**Expected Output**:
```json
{
  "tier1": {"enabled": true, "categories": 11},
  "tier2": {"enabled": true, "engine_available": true},
  "tier3": {"enabled": false}
}
```

## What's Next?

### Monitor Agent Activity
```bash
# Real-time logs
oc logs -f deployment/sre-agent -c agent -n sre-agent

# Filter for specific events
oc logs -f deployment/sre-agent -c agent -n sre-agent | grep "Diagnosis"
```

### Check Statistics
```bash
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  curl -s http://localhost:8000/stats | jq .
```

### View Audit Logs
```bash
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  sqlite3 /data/audit.db "SELECT operation, COUNT(*) FROM audit_logs GROUP BY operation;"
```

### Access Web UI (Optional)
```bash
# Get route URL
ROUTE=$(oc get route sre-agent -n sre-agent -o jsonpath='{.spec.host}')
echo "Access agent at: https://${ROUTE}"

# Available endpoints:
# - https://${ROUTE}/health
# - https://${ROUTE}/stats
# - https://${ROUTE}/docs (API documentation)
```

## Troubleshooting

### Pod Not Starting

```bash
# Check events
oc get events -n sre-agent --sort-by='.lastTimestamp'

# Check pod details
oc describe pod -l app=sre-agent -n sre-agent

# Common issues:
# - PVC not bound: Check storage class
# - Image pull error: Verify image exists
# - RBAC denied: Check ClusterRoleBinding
```

### LLM Connection Failed

```bash
# Test LLM endpoint
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  curl -v http://qwen-25-7b-predictor.models.svc.cluster.local/v1/models

# Check configuration
oc get configmap agent-config -n sre-agent -o yaml | grep LITELLM
```

### No Observations Collected

```bash
# Wait for collection cycle (30-60 seconds)
sleep 60

# Check logs
oc logs deployment/sre-agent -c agent -n sre-agent --tail=100 | grep "observation_count"

# If still zero, check RBAC
oc auth can-i list pods --as=system:serviceaccount:sre-agent:sre-agent
```

## Configuration Reference

### Minimal Working Configuration

**ConfigMap** (`agent-config`):
```yaml
LITELLM_URL: "http://your-llm-endpoint/v1"
LITELLM_MODEL: "your-model-name"
```

**Secret** (`litellm-api-secret`):
```yaml
LITELLM_API_KEY: "your-api-key"
```

### Full Production Configuration

**ConfigMap**:
```yaml
# LLM
LITELLM_URL: "http://qwen-25-7b-predictor.models.svc.cluster.local/v1"
LITELLM_MODEL: "qwen-25-7b"

# Git Platform
GIT_PLATFORM: "github"
GIT_SERVER_URL: "https://github.com"
GIT_ORGANIZATION: "my-org"
GIT_REPOSITORY: "cluster-issues"

# Features
RAG_ENABLED: "true"
PROMETHEUS_ENABLED: "true"
KNOWLEDGE_BASE_ENABLED: "true"

# Tiers
ENABLE_TIER1_AUTO: "true"
ENABLE_TIER2_GITOPS: "true"
ENABLE_TIER3_NOTIFY: "true"
```

**Secrets**:
```yaml
# litellm-api-secret
LITELLM_API_KEY: "local-model-no-auth"

# git-api-secret
GIT_TOKEN: "ghp_your_github_token"

# slack-webhook-secret
SLACK_WEBHOOK_URL: "https://hooks.slack.com/services/..."
```

## Documentation

- **Full README**: [../README.md](../README.md) - Complete project documentation
- **Deployment Guide**: [deploy/README.md](deploy/README.md) - Detailed deployment steps
- **KB Retrieval**: [KB_RETRIEVAL.md](KB_RETRIEVAL.md) - Knowledge base system
- **RAG Optimization**: [RAG_OPTIMIZATION.md](RAG_OPTIMIZATION.md) - RAG implementation details

## Getting Help

- **Logs**: `oc logs -f deployment/sre-agent -c agent -n sre-agent`
- **Health**: `curl https://<route>/health`
- **Stats**: `curl https://<route>/stats`
- **Issues**: Check GitHub Issues for known problems

## Clean Up (Optional)

```bash
# Delete test resources
oc delete namespace sre-demo

# Uninstall agent
oc delete project sre-agent
oc delete clusterrole sre-agent-cluster-reader
oc delete clusterrolebinding sre-agent-cluster-reader-binding sre-agent-prometheus-view
```

---

**🎉 Congratulations!** Your OpenShift SRE Agent is now monitoring your cluster and ready to help with autonomous remediation.
