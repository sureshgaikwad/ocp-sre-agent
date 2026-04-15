# Deployment Guide

Quick deployment instructions for OpenShift SRE Agent v3.0.0 (Watch-Based Real-Time Architecture)

## Files in This Directory

- **sre-agent-deployment.yaml** - Complete deployment manifest (RBAC + ConfigMap + Secrets + Deployment + Service + Route)
- **GIT_PLATFORM_CONFIGURATION.md** - Optional guide for GitHub/GitLab/Gitea integration (Tier 2/3)

## Architecture

**v3.0.0 uses Kubernetes Watch API** for true real-time, event-driven monitoring:

- **Watch Manager**: Monitors Kubernetes resources using native watch streams
  - **Pod Watcher**: Reacts immediately to CrashLoopBackOff, OOMKilled, ImagePullBackOff
  - **Event Watcher**: Processes Warning events cluster-wide in real-time
- **FastAPI Server**: Exposes `/trigger-workflow` for manual testing and `/health` for monitoring
- **Benefits**:
  - **True real-time response** (sub-second reaction time)
  - **Event-driven** (no polling overhead)
  - **Production-ready** (auto-reconnects, error handling)
  - **Observable** (watch status in /health endpoint)

## Quick Deploy

```bash
# 1. Edit configuration
vi sre-agent-deployment.yaml
# Update LITELLM_URL and LITELLM_MODEL (search for "UPDATE THIS")

# 2. Create namespace
oc new-project sre-agent

# 3. Deploy agent
oc apply -f sre-agent-deployment.yaml

# 4. Verify deployment
oc get pods -n sre-agent
# Expected: sre-agent-xxxxx 2/2 Running

oc logs -n sre-agent deployment/sre-agent -c agent | grep "Watch manager started"
# Expected: "✅ Watch manager started with 2 watchers"

# 5. Verify watchers are running
oc exec -n sre-agent deployment/sre-agent -c agent -- curl -s http://localhost:8000/health | jq '.watch_manager'
# Expected:
# {
#   "running": true,
#   "watcher_count": 2,
#   "watchers": [
#     {"type": "pod", "running": true},
#     {"type": "event", "running": true}
#   ]
# }
```

## Configuration Required

### Minimum (Required)

Update in `sre-agent-deployment.yaml`:

**LLM Endpoint** (lines 65-66):
```yaml
LITELLM_URL: "http://your-llm-endpoint/v1"
LITELLM_MODEL: "openai/your-model"
```

**LLM API Key** (line 27):
```yaml
LITELLM_API_KEY: "your-api-key-or-local-model-no-auth"
```

### Optional (Git Integration for Tier 2/3)

**Git Platform** (lines 80-98):
```yaml
GIT_PLATFORM: "github"              # or gitlab, gitea
GIT_SERVER_URL: "https://github.com"
GIT_ORGANIZATION: "your-org"
GIT_REPOSITORY: "cluster-issues"
ENABLE_TIER2_GITOPS: "true"
ENABLE_TIER3_NOTIFY: "true"
```

**Git Token** (line 40):
```yaml
GIT_TOKEN: "ghp_your_token_here"    # GitHub PAT with 'repo' scope
```

See [GIT_PLATFORM_CONFIGURATION.md](GIT_PLATFORM_CONFIGURATION.md) for detailed Git setup.

## What Gets Deployed

1. **Namespace**: `sre-agent`
2. **Secrets**: 
   - `litellm-api-secret` (LLM API key)
   - `git-api-secret` (Git token - optional)
3. **ConfigMap**: `agent-config` (all settings)
4. **ServiceAccount**: `sre-agent`
5. **RBAC**:
   - `ClusterRole`: Read-only access to pods, events, operators, routes, etc.
   - `ClusterRoleBinding`: Grants cluster-wide read access
   - `RoleBinding`: Edit access in `sre-agent` namespace only
6. **PersistentVolumeClaim**: `sre-agent-data` (10Gi for audit logs)
7. **Deployment**: `sre-agent` (2 containers: agent + mcp-server)
8. **Service**: `sre-agent` (ClusterIP on port 9080)
9. **Route**: `sre-agent` (HTTPS with edge termination)

## Verification Steps

### 1. Check Pods
```bash
oc get pods -n sre-agent

# Expected:
# NAME                        READY   STATUS    RESTARTS   AGE
# sre-agent-xxxxxxxxx-xxxxx   2/2     Running   0          1m
```

### 2. Verify MCP Tools
```bash
oc logs -n sre-agent deployment/sre-agent -c agent | grep "MCP initialization"

# Expected:
# ✅ MCP initialization complete - 44 tools available
```

### 3. Check Collectors
```bash
oc logs -n sre-agent deployment/sre-agent -c agent --tail=50 | grep "Retrieved"

# Expected (after 30-60s):
# Retrieved 229 pods
# Retrieved 133 Warning events
# Retrieved 21 ClusterOperators
```

### 4. Test Functionality
```bash
cd ../demo/
./run-demo.sh
./verify-demo.sh

# Expected:
# ✅ All tests PASSED!
```

## Troubleshooting

### Pod Stuck in ContainerCreating
```bash
oc describe pod -n sre-agent -l app=sre-agent

# Common causes:
# - PVC not bound (check storage class)
# - Image pull failure (check registry access)
```

### MCP Tools = 0 (Should be 44)
```bash
oc logs -n sre-agent deployment/sre-agent -c mcp-server

# Fix: Check ConfigMap has MCP_OPENSHIFT_TRANSPORT: "streamable-http"
oc get configmap agent-config -n sre-agent -o yaml | grep TRANSPORT
```

### No Observations Collected
```bash
# Wait for collection interval (30-60s)
sleep 60
oc logs -n sre-agent deployment/sre-agent -c agent | grep "observation_count"
```

### LLM Errors
```bash
# Verify endpoint and model name
oc get configmap agent-config -n sre-agent -o yaml | grep LITELLM

# Test endpoint manually
oc run curl-test --image=curlimages/curl -it --rm -- \
  curl -H "Authorization: Bearer $(oc get secret litellm-api-secret -n sre-agent -o jsonpath='{.data.LITELLM_API_KEY}' | base64 -d)" \
  $(oc get configmap agent-config -n sre-agent -o jsonpath='{.data.LITELLM_URL}')/models
```

## Updating Configuration

```bash
# Update LLM settings
oc set env deployment/sre-agent -n sre-agent \
  LITELLM_URL="http://new-endpoint/v1" \
  LITELLM_MODEL="openai/new-model"

# Enable/disable tiers
oc set env deployment/sre-agent -n sre-agent \
  ENABLE_TIER1_AUTO=true \
  ENABLE_TIER2_GITOPS=true \
  ENABLE_TIER3_NOTIFY=true

# Update collection intervals
oc set env deployment/sre-agent -n sre-agent \
  POD_COLLECTION_INTERVAL=60 \
  EVENT_COLLECTION_INTERVAL=120
```

## Uninstall

```bash
oc delete project sre-agent
oc delete clusterrole sre-agent-cluster-reader
oc delete clusterrolebinding sre-agent-cluster-reader-binding
oc delete clusterrolebinding sre-agent-prometheus-view
```

---

**See ../README.md for complete documentation**
