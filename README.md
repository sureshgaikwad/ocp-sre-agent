# OpenShift SRE Agent

**Version**: 3.0.10
**Architecture**: Kubernetes Python Client + MCP Tools + LLM-based Analysis
**Deployment**: OpenShift/Kubernetes
**Container Image**: `quay.io/sureshgaikwad/ocp-sre-agent:3.0.10-amd64`

Autonomous SRE agent for OpenShift cluster monitoring, diagnosis, and remediation with Kubernetes Events integration.

---

## 🎯 Overview

The OpenShift SRE Agent is an autonomous monitoring and remediation system that continuously watches your cluster and automatically:
- **Observes** cluster state (pods, events, autoscaling, operators, routes, builds)
- **Diagnoses** root causes using LLM-based analysis (OOMKilled, CrashLoop, HPA issues, networking failures)
- **Remediates** problems using a 3-tier approach (Auto-fix, GitOps PR, Notification)
- **Creates Kubernetes Events** visible in OpenShift Console and `oc get events`

### Key Features

- ✅ **9 Collectors**: Events, Pods, ClusterOperators, Routes, Builds, Networking, Autoscaling, MachineConfigPools, Proactive
- ✅ **8 Analyzers**: OOM, CrashLoop, ImagePull, SCC, Route, Liveness, Build, LLM-based fallback
- ✅ **3 Remediation Tiers**: Automated fixes, GitOps PRs, Issue notifications
- ✅ **44 MCP Tools**: For cluster actions (pods_delete, resources_patch, pods_log, create_issue, etc.)
- ✅ **Kubernetes Events**: Creates events visible in OpenShift Console with clear detection and remediation messages
- ✅ **Continuous Monitoring**: Watch-based for Pods/Events + periodic collection (30-300s intervals)
- ✅ **Security**: Secret scrubbing, RBAC checks, audit logging (SQLite + ConfigMap)
- ✅ **Multi-Git Platform**: GitHub, GitLab, Gitea support for issues and PRs

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Entry Point                       │
│          (Reactive /report-failure + Continuous Mode)        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │   Workflow Engine     │
                │  (Orchestrator)       │
                └──────────┬────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                   │
        ▼                  ▼                   ▼
   COLLECTORS         ANALYZERS           HANDLERS
   (9 types)         (8 types)           (3 tiers)
        │                  │                   │
        ▼                  ▼                   ▼
   Observations ──→  Diagnoses  ──→  Remediations
   (Watch +           (LLM +          (RBAC +
    Periodic)         Patterns)        GitOps)
                                           │
                                           ▼
                                    Kubernetes Events
                                    (OpenShift Console)
                                           │
                                           ▼
                                    Audit Logger
                                    (SQLite + ConfigMap)
```

### Components

**Collectors** (Observation Layer):
- Watch-based: Pods, Events (real-time via Kubernetes Watch API)
- Periodic: ClusterOperators, Routes, Builds, Autoscaling, MachineConfigPools, Proactive

**Analyzers** (Diagnosis Layer):
- Pattern matching + LLM analysis
- Categorizes failures (OOMKilled, CrashLoop, ImagePull, SCC, etc.)
- Provides root cause and recommended actions

**Handlers** (Remediation Layer):
- **Tier 1**: Automated safe actions (restart pods, retry ImagePull, increase memory for OOMKilled)
- **Tier 2**: GitOps PRs with proposed fixes (memory/CPU adjustments, config changes)
- **Tier 3**: Issue notifications with diagnostic reports

**Kubernetes Events**:
- Detection events: `SREAgentOOMKilled`, `SREAgentImagePullBackOff`, etc. (Warning type)
- Remediation events: `SREAgentMemoryIncreased`, `SREAgentIssueCreated`, etc. (Normal type)
- Visible in OpenShift Console: Workloads → [Resource] → Events tab
- Visible via CLI: `oc get events -n <namespace>`

---

## 📋 Prerequisites

1. **OpenShift/Kubernetes Cluster** (4.12+)
2. **Cluster Admin Access** (`oc auth can-i create clusterrole`)
3. **LLM Backend**: OpenShift AI, OpenAI, Anthropic, or compatible LLM endpoint
4. **Podman/Docker** (for building custom images)
5. **Git Repository** (optional, for Tier 2/3 features)

---

## 🚀 Deployment

### Option 1: Quick Deployment (Pre-built Image)

#### Step 1: Create Namespace
```bash
oc new-project sre-agent
```

#### Step 2: Configure LLM Settings
```bash
vi agent/agent/deploy/sre-agent-deployment.yaml
```

Update the following in the ConfigMap section (lines 47-147):

**For OpenShift AI (local cluster LLM)**:
```yaml
LITELLM_URL: "http://qwen-25-7b-predictor.models.svc.cluster.local/v1"
LITELLM_MODEL: "openai/qwen-25-7b"
LITELLM_API_KEY: "local-model-no-auth"
```

**For OpenAI**:
```yaml
LITELLM_URL: "https://api.openai.com/v1"
LITELLM_MODEL: "openai/gpt-4"
LITELLM_API_KEY: "sk-YOUR_API_KEY_HERE"
```

**For Anthropic Claude**:
```yaml
LITELLM_URL: "https://api.anthropic.com/v1"
LITELLM_MODEL: "anthropic/claude-3-5-sonnet-20241022"
LITELLM_API_KEY: "sk-ant-YOUR_API_KEY_HERE"
```

#### Step 3: (Optional) Configure Git Integration

For Tier 2 (GitOps PRs) and Tier 3 (Issue creation):

```yaml
GIT_PLATFORM: "github"              # github, gitlab, or gitea
GIT_ORGANIZATION: "your-org"
GIT_REPOSITORY: "cluster-issues"
GIT_TOKEN: "ghp_YOUR_TOKEN"         # Update Secret at line 27
ENABLE_TIER2_GITOPS: "true"
ENABLE_TIER3_NOTIFY: "true"
```

See [agent/deploy/GIT_PLATFORM_CONFIGURATION.md](agent/deploy/GIT_PLATFORM_CONFIGURATION.md) for Git setup details.

#### Step 4: Deploy to Cluster
```bash
oc apply -f agent/deploy/sre-agent-deployment.yaml
```

#### Step 5: Verify Deployment
```bash
# Check pod status (expect 2/2 Running)
oc get pods -n sre-agent

# Should see:
# NAME                         READY   STATUS    RESTARTS   AGE
# sre-agent-xxxxx-xxxxx        2/2     Running   0          1m

# Check MCP tools loaded (expect 44 tools)
oc logs -n sre-agent deployment/sre-agent -c agent | grep "tools available"

# Check health endpoint
oc exec -n sre-agent deployment/sre-agent -c agent -- curl -s http://localhost:8000/health
```

#### Step 6: Verify Cluster-Wide Event Creation
The agent creates Kubernetes Events in **ANY namespace** where it detects issues:

```bash
# Verify agent can create events cluster-wide
oc auth can-i create events --as=system:serviceaccount:sre-agent:sre-agent --all-namespaces
# Should output: yes

# Create a test issue in any namespace to verify
oc new-project test-agent
oc apply -f agent/demo/01-oom-test.yaml -n test-agent

# Wait 1-2 minutes, then check for events
oc get events -n test-agent | grep SREAgent
# Should see both detection and remediation events
```

**Expected Output:**
```
Warning   SREAgentOOMKilled           pod/oom-test-xxx    🔍 SRE Agent detected: Pod oom-test-xxx - OOMKilled
Warning   SREAgentRemediationFailed   deployment/oom-test ❌ SRE Agent remediation: Manual fix required: increase memory from 128Mi to 256Mi
```

---

### Option 2: Build and Deploy Custom Image

#### Step 1: Clone Repository
```bash
cd /path/to/workspace
git clone <your-repo-url> ocp-sre-agent
cd ocp-sre-agent
```

#### Step 2: Build Container Image
```bash
# Navigate to agent directory
cd agent/

# Build for AMD64 (most common)
podman build -t quay.io/YOUR_USERNAME/ocp-sre-agent:3.0.10-amd64 \
  --platform linux/amd64 \
  -f Dockerfile .

# OR build for ARM64 (Apple Silicon, ARM servers)
podman build -t quay.io/YOUR_USERNAME/ocp-sre-agent:3.0.10-arm64 \
  --platform linux/arm64 \
  -f Dockerfile .
```

#### Step 3: Push to Registry
```bash
# Login to your container registry
podman login quay.io

# Push image
podman push quay.io/YOUR_USERNAME/ocp-sre-agent:3.0.10-amd64
```

#### Step 4: Update Deployment Manifest
```bash
vi agent/deploy/sre-agent-deployment.yaml
```

Change image reference (around line 186):
```yaml
containers:
- name: agent
  image: quay.io/YOUR_USERNAME/ocp-sre-agent:3.0.10-amd64  # Update this
```

#### Step 5: Deploy
```bash
oc new-project sre-agent
oc apply -f agent/deploy/sre-agent-deployment.yaml
```

---

## 🧪 Testing and Verification

### Run Demo Scenarios

The demo creates 3 test deployments with known issues:

```bash
cd agent/demo/

# Deploy test scenarios (OOMKilled, CrashLoop, ImagePullBackOff)
./run-demo.sh

# Wait 1-2 minutes for agent to detect and remediate

# Verify agent detected and handled issues
./verify-demo.sh
```

See [agent/demo/README.md](agent/demo/README.md) for detailed demo walkthrough.

### View Kubernetes Events

**Via CLI**:
```bash
# View all SRE Agent events in a namespace
oc get events -n sre-demo | grep SREAgent

# View detection events (Warning type, on Pods)
oc get events -n sre-demo --field-selector type=Warning | grep SREAgent

# View remediation events (Normal type, on Deployments)
oc get events -n sre-demo --field-selector type=Normal | grep SREAgent

# View events for specific deployment
oc get events -n sre-demo --field-selector involvedObject.kind=Deployment,involvedObject.name=oom-test
```

**Via OpenShift Console**:
1. Navigate to: Administrator → Workloads → Deployments → [deployment-name]
2. Click on **Events** tab
3. Look for events with reason starting with `SREAgent`:
   - `SREAgentOOMKilled` (detection)
   - `SREAgentMemoryIncreased` (remediation)
   - `SREAgentImagePullBackOff` (detection)
   - `SREAgentImagePullRetryWait` (remediation)

**Example Events**:
```
4m2s    Warning   SREAgentOOMKilled          pod/oom-test-556f4685c-fbssd
        🔍 SRE Agent detected: Pod oom-test-556f4685c-fbssd (container: memory-hog) -
        OOMKilled: Container terminated: OOMKilled (exit code 137)

4m2s    Normal    SREAgentMemoryIncreased    deployment/oom-test
        ✅ SRE Agent remediation: Automatically increased memory from 128Mi to 256Mi
```

### Monitor Agent Activity

```bash
# Live logs (JSON formatted)
oc logs -n sre-agent deployment/sre-agent -c agent -f

# Filter for specific activity
oc logs -n sre-agent deployment/sre-agent -c agent | grep -i "remediation"

# Check workflow execution
oc logs -n sre-agent deployment/sre-agent -c agent | grep "Workflow complete"

# View audit trail
oc exec -n sre-agent deployment/sre-agent -c agent -- sqlite3 /data/audit.db \
  "SELECT timestamp, operation_type, action, success FROM audit_log ORDER BY timestamp DESC LIMIT 10;"
```

---

## 📊 What It Monitors

| Collector | What It Watches | Example Detections |
|-----------|-----------------|-------------------|
| **Events** | Kubernetes Warning events | BackOff, FailedScheduling, FailedMount |
| **Pods** | Pod states (watch-based) | CrashLoopBackOff, OOMKilled, ImagePullBackOff |
| **ClusterOperators** | OpenShift operators | Degraded=True, Available=False |
| **Routes** | OpenShift routes | 5xx errors, unavailable backends |
| **Autoscaling** | HPAs, ClusterAutoscaler | HPA at max replicas, unable to scale |
| **Networking** | DNS, SDN, OVN | Pod connectivity issues |
| **Builds** | Tekton pipelines, BuildConfigs | Failed builds, pipeline errors |
| **MachineConfigPools** | Node configurations | Update stuck, degraded pools |
| **Proactive** | Resource trends | Memory/CPU trending toward limits |

---

## ⚙️ Configuration

All configuration is in [agent/deploy/sre-agent-deployment.yaml](agent/deploy/sre-agent-deployment.yaml).

### Key Settings (ConfigMap, lines 47-147)

**Operation Mode**:
```yaml
MODE: "continuous"                  # continuous (watch-based) or reactive (webhook only)
```

**Remediation Tiers**:
```yaml
ENABLE_TIER1_AUTO: "true"          # Automated safe fixes
ENABLE_TIER2_GITOPS: "true"        # GitOps PRs (requires Git integration)
ENABLE_TIER3_NOTIFY: "true"        # Issue notifications (requires Git integration)
```

**Collection Intervals** (seconds, 0=disabled):
```yaml
EVENT_COLLECTION_INTERVAL: "60"              # Warning events
POD_COLLECTION_INTERVAL: "0"                 # Pods use watch (not periodic)
CLUSTER_OPERATOR_INTERVAL: "120"             # OpenShift operators
ROUTE_COLLECTION_INTERVAL: "90"              # Routes
BUILD_COLLECTION_INTERVAL: "120"             # Builds
NETWORKING_COLLECTION_INTERVAL: "180"        # Network diagnostics
AUTOSCALING_COLLECTION_INTERVAL: "90"        # HPAs
MACHINE_CONFIG_POOL_INTERVAL: "300"          # MCPs
PROACTIVE_COLLECTION_INTERVAL: "300"         # Trend analysis
```

**Remediation Limits**:
```yaml
REMEDIATION_COOLDOWN_MINUTES: "30"     # Wait 30min before re-remediating same resource
MAX_REMEDIATION_ATTEMPTS: "3"          # Max attempts per issue
```

**Audit Trail**:
```yaml
AUDIT_STORAGE: "sqlite"                # sqlite or configmap
AUDIT_DB_PATH: "/data/audit.db"        # SQLite database path
```

---

## 🔄 Tier System

### Tier 1: Automated (Safe Actions)

**What it does**:
- Automatically fixes safe, non-destructive issues
- Creates Kubernetes Events for each action

**Examples**:
- **OOMKilled**: Increase memory limit (128Mi → 256Mi) on Deployment
- **ImagePullBackOff**: Retry-wait strategy (wait for transient registry issues)
- **CrashLoopBackOff**: Restart pod after cooldown

**Safeguards**:
- RBAC check before every action (`oc auth can-i`)
- 30-minute cooldown per resource
- Max 3 attempts per issue
- Only works on Deployments (not StatefulSets, DaemonSets)
- Creates audit log entries

**Kubernetes Events Created**:
- Detection: `SREAgentOOMKilled` (Warning, on Pod)
- Remediation success: `SREAgentMemoryIncreased` (Normal, on Deployment)
- Remediation failure: `SREAgentRBACDenied` (Warning, on Deployment)

### Tier 2: GitOps (PR with Fix)

**What it does**:
- Creates Pull Request with proposed YAML changes
- For resources managed by ArgoCD/GitOps

**Examples**:
- Memory/CPU limit increases
- Replica count adjustments
- Config changes

**Requires**:
- Git integration configured (GIT_TOKEN, GIT_ORGANIZATION, GIT_REPOSITORY)
- Resource detected as GitOps-managed (has ArgoCD annotations)

**Kubernetes Events Created**:
- `SREAgentPRCreated` (Normal, on Deployment)

### Tier 3: Notification (Issue Creation)

**What it does**:
- Creates detailed issue in GitHub/GitLab/Gitea
- Includes diagnostic report, root cause, recommended actions
- Secret scrubbing applied

**Examples**:
- Authentication failures (SCC issues)
- Image not found (404)
- Complex application errors
- Platform issues (ClusterOperator degraded)

**Requires**:
- Git integration configured

**Kubernetes Events Created**:
- Git configured: `SREAgentIssueCreated` (Normal, on resource)
- Git not configured: `SREAgentManualInterventionRequired` (Warning, on resource)

---

## 🔒 Security Features

### Secret Scrubbing
- Regex-based detection of passwords, tokens, SSH keys, API keys, base64-encoded secrets
- Applied BEFORE sending to LLM
- Applied BEFORE logging to audit trail
- Applied BEFORE creating Git issues

### RBAC Model

**Cluster-Wide Read + Event Creation:**
- ClusterRole `sre-agent-cluster-reader` grants read access to all namespaces
- **Events**: `create`, `patch`, `get`, `list`, `watch` (cluster-wide)
- **Pods, Services, Deployments, HPAs**: `get`, `list`, `watch` (read-only, cluster-wide)
- **ClusterOperators, Routes, Builds**: `get`, `list`, `watch` (read-only, cluster-wide)

**Namespace-Scoped Write (Tier 1 Auto-Remediation):**
- RoleBinding to `edit` role in `sre-agent` namespace only
- Tier 1 automated fixes (pod restarts, memory increases) work in `sre-agent` namespace
- For cluster-wide auto-remediation, grant `edit` role per namespace:
  ```bash
  oc adm policy add-role-to-user edit system:serviceaccount:sre-agent:sre-agent -n <namespace>
  ```

**RBAC Verification:**
- Every Tier 1 action checks permissions first: `oc auth can-i <verb> <resource>`
- If RBAC denied, creates remediation event with manual steps: `SREAgentRemediationFailed`
- Never bypasses Kubernetes RBAC - respects cluster security policies

### Audit Logging
- All observations, diagnoses, and remediations logged to SQLite database
- Non-blocking (won't fail workflow if audit fails)
- Queryable via SQL:
  ```bash
  oc exec -n sre-agent deployment/sre-agent -c agent -- \
    sqlite3 /data/audit.db "SELECT * FROM audit_log WHERE success=1 LIMIT 10;"
  ```

### Remediation Limits
- 30-minute cooldown per resource (prevents infinite loops)
- Max 3 attempts per unique issue
- In-memory cache with 1-hour TTL

---

## 🐛 Troubleshooting

### Pod Not Starting

**Check pod status**:
```bash
oc get pods -n sre-agent
oc describe pod -n sre-agent -l app=sre-agent
```

**Common issues**:
- PVC mount conflict: Scale down old pods first
- Image pull errors: Verify image exists and is public
- Insufficient permissions: Check ServiceAccount has ClusterRole bound

### No MCP Tools (0 instead of 44)

**Check MCP server logs**:
```bash
oc logs -n sre-agent deployment/sre-agent -c mcp-server
```

**Fix**: Ensure transport is "streamable-http" in ConfigMap:
```yaml
MCP_TRANSPORT: "streamable-http"
```

### No Observations Collected

**Wait for collection interval** (30-60 seconds).

**Check logs**:
```bash
oc logs -n sre-agent deployment/sre-agent -c agent | grep "observation_count"
```

**Verify collectors are running**:
```bash
oc logs -n sre-agent deployment/sre-agent -c agent | grep "collection complete"
```

### Kubernetes Events Not Appearing

**Check event creation logs**:
```bash
oc logs -n sre-agent deployment/sre-agent -c agent | grep "event_creator"
```

**Common issues**:
- `Failed to create event: Bad Request` → Timestamp format issue (fixed in v3.0.10)
- `Failed to create event: Conflict` → Event already exists (normal, not an error)
- `Failed to create event: Forbidden` → RBAC issue, check ClusterRole has events `create` permission

**Verify RBAC**:
```bash
oc auth can-i create events --as=system:serviceaccount:sre-agent:sre-agent -n sre-demo
```

### LLM Timeouts or Errors

**Check LLM endpoint is reachable**:
```bash
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  curl -v http://qwen-25-7b-predictor.models.svc.cluster.local/v1/models
```

**Check LLM logs** (if using OpenShift AI):
```bash
oc logs -n models deployment/qwen-25-7b-predictor
```

**Increase timeout** in ConfigMap:
```yaml
LITELLM_TIMEOUT: "120"  # seconds
```

---

## 📁 Repository Structure

```
/
├── README.md                          # This file
├── README.adoc.old                    # Old README (archived)
├── .gitignore
├── helm/                              # Helm charts (legacy)
│
└── agent/                             # Main SRE Agent application
    ├── Dockerfile                     # Container image definition
    ├── requirements.txt               # Python dependencies
    ├── main.py                        # FastAPI entry point
    ├── mcp_client.py                  # MCP tool registry client
    │
    ├── deploy/
    │   ├── sre-agent-deployment.yaml  # ⭐ Main Kubernetes manifest
    │   └── GIT_PLATFORM_CONFIGURATION.md  # Git integration guide
    │
    ├── demo/
    │   ├── README.md                  # Demo walkthrough
    │   ├── run-demo.sh                # Deploy test scenarios
    │   └── verify-demo.sh             # Verify agent responses
    │
    └── sre_agent/                     # Source code
    ├── collectors/                    # 9 observation collectors
    │   ├── base.py
    │   ├── event_collector.py
    │   ├── pod_collector.py
    │   ├── cluster_operator_collector.py
    │   ├── route_collector.py
    │   ├── build_collector.py
    │   ├── networking_collector.py
    │   ├── autoscaling_collector.py
    │   ├── machine_config_pool_collector.py
    │   └── proactive_collector.py
    │
    ├── analyzers/                     # 8 diagnostic analyzers
    │   ├── base.py
    │   ├── oom_analyzer.py
    │   ├── crashloop_analyzer.py
    │   ├── image_pull_analyzer.py
    │   ├── scc_analyzer.py
    │   ├── route_analyzer.py
    │   ├── liveness_probe_analyzer.py
    │   ├── build_analyzer.py
    │   └── llm_analyzer.py
    │
    ├── handlers/                      # 3-tier remediation
    │   ├── base.py
    │   ├── tier1_automated.py         # Auto-fix handler
    │   ├── tier2_gitops.py            # GitOps PR handler
    │   └── tier3_notification.py      # Issue notification handler
    │
    ├── models/                        # Data models (Pydantic)
    │   ├── observation.py
    │   ├── diagnosis.py
    │   ├── remediation.py
    │   └── audit.py
    │
    ├── utils/                         # Utilities
    │   ├── secret_scrubber.py         # Secret masking (CRITICAL)
    │   ├── audit_logger.py            # SQLite audit trail
    │   ├── rbac_checker.py            # RBAC verification
    │   ├── gitops_detector.py         # Detect ArgoCD resources
    │   ├── event_creator.py           # Kubernetes Events API
    │   └── json_logger.py             # Structured JSON logging
    │
    ├── orchestrator/                  # Workflow engine
    │   ├── workflow_engine.py         # Main orchestration
    │   ├── scheduler.py               # Periodic collection
    │   └── decision_engine.py         # Tier selection
    │
    ├── integrations/                  # External integrations
    │   └── git/                       # GitHub, GitLab, Gitea
    │       ├── base.py
    │       ├── github_adapter.py
    │       ├── gitlab_adapter.py
    │       ├── gitea_adapter.py
    │       └── factory.py
    │
    └── config/
        └── settings.py                # Pydantic settings (env vars)
```

---

## 📈 Monitoring and Metrics

### Health Endpoint
```bash
curl http://localhost:8000/health
```

**Response**:
```json
{
  "status": "healthy",
  "mode": "watch-based",
  "mcp_tools": 44,
  "workflow_engine": {
    "collectors": 9,
    "analyzers": 8,
    "handlers": 3,
    "remediation_cache_size": 0
  },
  "watch_manager": {
    "running": true,
    "watcher_count": 2,
    "watchers": [
      {"type": "pod", "running": true},
      {"type": "event", "running": true}
    ]
  }
}
```

### Stats Endpoint
```bash
curl http://localhost:8000/stats
```

### Audit Trail Query
```bash
oc exec -n sre-agent deployment/sre-agent -c agent -- \
  sqlite3 /data/audit.db \
  "SELECT operation_type, COUNT(*) as count, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes
   FROM audit_log
   GROUP BY operation_type;"
```

---

## ❓ FAQ

**Q: Does it work on vanilla Kubernetes?**
A: Yes. Some OpenShift-specific collectors (ClusterOperators, Routes, MachineConfigPools) will be skipped, but core functionality (Pods, Events, Autoscaling) works on any Kubernetes cluster.

**Q: Is it safe to enable Tier 1 auto-remediation in production?**
A: Yes. Tier 1 is designed for safe, non-destructive actions with multiple safeguards:
- RBAC checks before every action
- 30-minute cooldown per resource
- Max 3 attempts per issue
- Only works on Deployments (not StatefulSets/DaemonSets)
- All actions audited and create Kubernetes Events

**Q: What are the resource requirements?**
A: Default: 512Mi RAM, 250m CPU (requests), 1Gi RAM, 500m CPU (limits). Scales with cluster size. Monitor and adjust as needed.

**Q: Can I disable specific collectors?**
A: Yes. Set collection interval to `0` in ConfigMap to disable a collector.

**Q: How do I see what the agent is doing?**
A: Three ways:
1. Kubernetes Events: `oc get events -n <namespace> | grep SREAgent`
2. Live logs: `oc logs -n sre-agent deployment/sre-agent -c agent -f`
3. Audit trail: Query `/data/audit.db` SQLite database

**Q: What LLM models are supported?**
A: Any OpenAI-compatible API:
- OpenShift AI (vLLM, Hugging Face TGI)
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Local models (Ollama, LM Studio)

**Q: How much does LLM analysis cost?**
A: Depends on provider:
- OpenShift AI (local): Free
- OpenAI GPT-4: ~$0.01-0.03 per diagnosis
- Caching reduces repeated analysis of same issues

**Q: Can I customize remediation rules?**
A: Yes. Edit handlers in `sre_agent/handlers/` and rebuild the image.

---

## 🔄 Upgrade Path

### From v2.x to v3.x

**What's new in v3.0.10**:
- ✅ Kubernetes Events creation (visible in OpenShift Console)
- ✅ Timezone-aware timestamps for events
- ✅ Comprehensive event coverage (all handlers)
- ✅ Clear detection and remediation messages with emojis

**Upgrade steps**:
```bash
# 1. Update deployment manifest image tag
vi agent/deploy/sre-agent-deployment.yaml
# Change: image: quay.io/sureshgaikwad/ocp-sre-agent:3.0.10-amd64

# 2. Apply updated manifest
oc apply -f agent/deploy/sre-agent-deployment.yaml

# 3. Scale down old pods
oc scale rs <old-replicaset> --replicas=0 -n sre-agent

# 4. Verify new version
oc logs -n sre-agent deployment/sre-agent -c agent | grep "version"
```

---

## 📝 Contributing

To contribute or customize:

1. Fork repository
2. Make changes
3. Build custom image: `podman build -t quay.io/YOUR_USERNAME/ocp-sre-agent:custom .`
4. Push image: `podman push quay.io/YOUR_USERNAME/ocp-sre-agent:custom`
5. Update deployment manifest
6. Test in non-production cluster first

---

## 📄 License

[Add your license here]

---

## 🆘 Support

- **Issues**: File bugs/features in Git repository
- **Logs**: Include output from `oc logs -n sre-agent deployment/sre-agent -c agent`
- **Events**: Include output from `oc get events -n <namespace> | grep SREAgent`
- **Health check**: Include output from `curl http://localhost:8000/health`

---

**Last Updated**: 2026-04-16
**Version**: 3.0.10
**Image**: `quay.io/sureshgaikwad/ocp-sre-agent:3.0.10-amd64`
