# SRE Agent Deployment Guide

## Quick Deployment for Different Clusters

### Prerequisites
- OpenShift 4.10+
- `oc` CLI installed and logged in to your cluster
- Cluster-admin or sufficient RBAC permissions

---

## 🚀 One-Command Deployment (Recommended)

```bash
cd deploy
./deploy.sh
```

**This script automatically:**
- ✅ Creates the `sre-agent` namespace
- ✅ Deploys all Kubernetes resources
- ✅ **Detects your cluster's route URL dynamically** (no manual configuration needed!)
- ✅ Updates ConfigMap with the correct route URL
- ✅ Checks for Slack integration
- ✅ Shows deployment status and next steps

**Works across ANY OpenShift cluster** - no need to reconfigure route URLs!

---

## 📝 Post-Deployment Configuration

### 1. Configure Slack Integration (Required for Interactive Remediation)

**⚠️ IMPORTANT: Never commit your Slack webhook URL to git!**

```bash
# Create Slack webhook secret (your URL stays private!)
oc create secret generic slack-webhook-secret -n sre-agent \
  --from-literal=SLACK_WEBHOOK_URL='https://hooks.slack.com/services/YOUR/WEBHOOK/URL'

# Restart deployment to pick up the secret
oc rollout restart deployment/sre-agent -n sre-agent
```

**How to get a Slack webhook URL:**
1. Go to https://api.slack.com/messaging/webhooks
2. Create a Slack app (e.g., "SRE Agent")
3. Enable Incoming Webhooks
4. Add webhook to your channel (e.g., #sre-alerts)
5. Copy the webhook URL

### 2. Configure LLM Provider

**For OpenShift AI (vLLM):**
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

**For OpenAI:**
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
    "LITELLM_API_KEY": "sk-your-openai-api-key-here"
  }
}'
```

### 3. Configure Git Platform (for Issue Creation)

```bash
oc patch configmap agent-config -n sre-agent --type merge -p '
{
  "data": {
    "GIT_PLATFORM": "github",
    "GIT_SERVER_URL": "https://github.com",
    "GIT_ORGANIZATION": "your-org",
    "GIT_REPOSITORY": "cluster-issues"
  }
}'

oc patch secret git-api-secret -n sre-agent --type merge -p '
{
  "stringData": {
    "GIT_TOKEN": "ghp_your_github_token_here"
  }
}'
```

### 4. Grant Remediation Permissions (Optional)

**By default**, the agent has **read-only cluster access**. To enable auto-remediation in specific namespaces:

```bash
# Grant edit permissions to one namespace
oc adm policy add-role-to-user edit system:serviceaccount:sre-agent:sre-agent -n production

# Grant permissions to multiple namespaces
for ns in production staging dev; do
  oc adm policy add-role-to-user edit system:serviceaccount:sre-agent:sre-agent -n $ns
done
```

**What the agent can auto-remediate:**
- ✅ Increase memory/CPU limits for OOMKilled pods
- ✅ Fix ImagePullBackOff issues
- ✅ Scale HPA maxReplicas when hitting limits
- ✅ Restart pods with transient failures

**Verification:**
```bash
# Check if agent can remediate in a namespace
oc auth can-i patch deployment -n production --as=system:serviceaccount:sre-agent:sre-agent
```

### 5. Restart and Verify

```bash
# Restart deployment to apply all configuration
oc rollout restart deployment/sre-agent -n sre-agent

# Wait for pod to be ready
oc wait --for=condition=Ready pod -l app=sre-agent -n sre-agent --timeout=180s

# Check logs
oc logs -f deployment/sre-agent -c agent -n sre-agent

# Test health endpoint
ROUTE_URL=$(oc get route sre-agent -n sre-agent -o jsonpath='{.spec.host}')
curl -k https://$ROUTE_URL/health
```

---

## 🔒 Security Best Practices

### Secrets Management

**✅ DO:**
- Create secrets using `oc create secret` commands
- Store webhook URLs and API keys in OpenShift secrets
- Use `.gitignore` to prevent committing secret files
- Rotate credentials regularly

**❌ DON'T:**
- Hardcode webhook URLs or API keys in YAML files
- Commit secret values to git
- Share webhook URLs in chat or documentation
- Use production credentials in development

### Files That Should NEVER Be Committed:
```
*secret*.yaml         # Any file with "secret" in the name
*webhook*.txt         # Webhook URL files
deploy/*-secrets.yaml # Secret override files
.env.local            # Local environment overrides
```

---

## 🌐 Multi-Cluster Deployment

The deployment script **automatically detects** each cluster's route URL, so you can deploy to multiple clusters without reconfiguration:

```bash
# Cluster 1 (US East)
oc login https://api.cluster1.example.com
cd deploy && ./deploy.sh

# Cluster 2 (EU West)
oc login https://api.cluster2.example.com
cd deploy && ./deploy.sh

# Cluster 3 (AP South)
oc login https://api.cluster3.example.com
cd deploy && ./deploy.sh
```

Each cluster will automatically get the correct route URL!

---

## 🧪 Testing the Deployment

### 1. Create a Test Failure

```bash
# Create a namespace
oc create namespace sre-test

# Grant remediation permissions
oc adm policy add-role-to-user edit system:serviceaccount:sre-agent:sre-agent -n sre-test

# Create an OOMKilled pod
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: oom-test
  namespace: sre-test
spec:
  containers:
  - name: stress
    image: polinux/stress
    resources:
      limits:
        memory: "32Mi"
    command: ["stress"]
    args: ["--vm", "1", "--vm-bytes", "64M"]
  restartPolicy: Always
EOF
```

### 2. Watch the Agent Respond

```bash
# Monitor agent logs
oc logs -f deployment/sre-agent -c agent -n sre-agent | grep -E "oom-test|Slack"

# Expected flow:
# 1. Agent detects OOMKilled pod (after 3 failures or 5 minutes)
# 2. Sends Slack notification with diagnosis
# 3. You approve via curl command in Slack
# 4. Agent increases memory and restarts pod
```

### 3. Verify Slack Notification

You should receive a Slack message with:
- 🔍 Root cause analysis
- 📊 Diagnostic evidence
- 🔧 Recommended actions
- ✅ Approval curl command with **correct external route URL**

Example approval command:
```bash
curl -k -X POST https://sre-agent-sre-agent.apps.cluster.example.com/approve-remediation \
  -H 'Content-Type: application/json' \
  -d '{"diagnosis_id": "abc123", "approved": true}'
```

### 4. Clean Up

```bash
oc delete namespace sre-test
```

---

## 🐛 Troubleshooting

### Issue: Slack Notifications Not Working

**Check:**
```bash
# Verify secret exists
oc get secret slack-webhook-secret -n sre-agent

# Check webhook URL is set
oc get secret slack-webhook-secret -n sre-agent -o jsonpath='{.data.SLACK_WEBHOOK_URL}' | base64 -d

# Test webhook manually
WEBHOOK_URL=$(oc get secret slack-webhook-secret -n sre-agent -o jsonpath='{.data.SLACK_WEBHOOK_URL}' | base64 -d)
curl -X POST -H 'Content-Type: application/json' \
  -d '{"text":"✅ Test from SRE Agent"}' \
  "$WEBHOOK_URL"
```

### Issue: Wrong Route URL in Slack

**Fix:**
```bash
# Re-run deployment script to auto-detect route
cd deploy && ./deploy.sh

# Or manually update:
ROUTE_URL="https://$(oc get route sre-agent -n sre-agent -o jsonpath='{.spec.host}')"
oc patch configmap agent-config -n sre-agent --type merge -p "{\"data\":{\"SRE_AGENT_ROUTE_URL\":\"$ROUTE_URL\"}}"
oc rollout restart deployment/sre-agent -n sre-agent
```

### Issue: Remediation Not Working

**Check RBAC:**
```bash
# Verify agent has edit permissions in target namespace
oc auth can-i patch deployment -n <namespace> --as=system:serviceaccount:sre-agent:sre-agent

# Grant permissions if missing
oc adm policy add-role-to-user edit system:serviceaccount:sre-agent:sre-agent -n <namespace>
```

---

## 📚 Additional Resources

- **Full README**: [README.md](../README.md)
- **Configuration Guide**: See README.md "Configuration" section
- **API Reference**: See README.md "API Reference" section
- **Troubleshooting**: See README.md "Troubleshooting" section

---

**✨ You're all set! The agent will now monitor your cluster and send Slack notifications for issues.**
