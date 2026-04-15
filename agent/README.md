# OpenShift SRE Agent

**Version**: 2.0.3
**Architecture**: Kubernetes Python Client + MCP Tools
**Deployment**: OpenShift/Kubernetes

Autonomous SRE agent for OpenShift cluster monitoring and remediation.

---

## 🎯 Overview

The OpenShift SRE Agent monitors your cluster and automatically:
- **Observes** cluster state (pods, events, autoscaling, operators)
- **Diagnoses** root causes (OOMKilled, CrashLoop, HPA issues, networking)
- **Remediates** problems (3-tier approach: Auto, GitOps, Notify)

### Key Features

- ✅ **9 Collectors**: Events, Pods, ClusterOperators, Routes, Builds, Networking, Autoscaling, MachineConfigPools, Proactive
- ✅ **8 Analyzers**: OOM, CrashLoop, ImagePull, SCC, Route, Liveness, Build, LLM-based
- ✅ **3 Remediation Tiers**: Auto-fix, GitOps PR, Issue notification
- ✅ **44 MCP Tools**: For cluster actions (pods_delete, resources_patch, pods_log, etc.)
- ✅ **Continuous Monitoring**: 30-300s collection intervals
- ✅ **Security**: Secret scrubbing, RBAC checks, audit logging

---

## 📋 Prerequisites

1. **OpenShift/Kubernetes Cluster** (4.12+)
2. **Cluster Admin Access** (`oc auth can-i create clusterrole`)
3. **LLM Backend**: OpenShift AI, OpenAI, Anthropic, or local LLM

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Update Configuration

```bash
vi deploy/sre-agent-deployment.yaml
```

**Update lines 65-66** (LLM endpoint):
```yaml
LITELLM_URL: "YOUR_LLM_ENDPOINT"      
LITELLM_MODEL: "openai/YOUR_MODEL"    
```

**Update line 27** (LLM API key):
```yaml
LITELLM_API_KEY: "YOUR_API_KEY"       
```

### Step 2: Deploy

```bash
oc new-project sre-agent
oc apply -f deploy/sre-agent-deployment.yaml
```

### Step 3: Verify

```bash
# Check pods (expect 2/2 Running)
oc get pods -n sre-agent

# Check MCP tools (expect 44 tools)
oc logs -n sre-agent deployment/sre-agent -c agent | grep "tools available"

# Monitor activity
oc logs -n sre-agent deployment/sre-agent -c agent -f
```

---

## 🧪 Run Demo (2 Minutes)

```bash
cd demo/
./run-demo.sh      # Deploys 3 test scenarios
./verify-demo.sh   # Verifies agent detected them
```

See [demo/README.md](demo/README.md) for details.

---

## 📊 What It Monitors

| Collector | What It Watches | Detection |
|-----------|-----------------|-----------|
| **Events** | Kubernetes Warning events | BackOff, FailedScheduling, FailedMount |
| **Pods** | Pod states | CrashLoopBackOff, OOMKilled, ImagePullBackOff |
| **ClusterOperators** | OpenShift operators | Degraded, Unavailable |
| **Routes** | OpenShift routes | 5xx errors, unavailable backends |
| **Autoscaling** | HPAs, ClusterAutoscaler | HPA at max, unable to scale |
| **Networking** | DNS, SDN, OVN | Pod connectivity issues |
| **Builds** | Tekton pipelines, BuildConfigs | Failed builds |
| **MachineConfigPools** | Node configurations | Update stuck, degraded |
| **Proactive** | Trends & anomalies | Memory/CPU trending to limits |

---

## ⚙️ Configuration

See [deploy/sre-agent-deployment.yaml](deploy/sre-agent-deployment.yaml) for all options.

**Key Settings** (ConfigMap, lines 47-147):
- `MODE`: `continuous` or `reactive`
- `ENABLE_TIER1_AUTO`: Auto-remediation (`true`/`false`)
- `POD_COLLECTION_INTERVAL`: Check interval in seconds
- `GIT_PLATFORM`: `github`/`gitlab`/`gitea` (for Tier 2/3)

**LLM Examples**:

**OpenShift AI**:
```yaml
LITELLM_URL: "http://qwen-25-7b-predictor.models.svc.cluster.local/v1"
LITELLM_MODEL: "openai/qwen-25-7b"
LITELLM_API_KEY: "local-model-no-auth"
```

**OpenAI**:
```yaml
LITELLM_URL: "https://api.openai.com/v1"
LITELLM_MODEL: "openai/gpt-4"
LITELLM_API_KEY: "sk-..."
```

---

## 🔧 Git Integration (Optional)

For Tier 2 (GitOps PRs) and Tier 3 (Issue notifications):

1. Create a GitHub/GitLab repository (e.g., `my-org/cluster-issues`)
2. Generate Personal Access Token with `repo` scope
3. Update deploy/sre-agent-deployment.yaml:
   ```yaml
   GIT_PLATFORM: "github"
   GIT_ORGANIZATION: "my-org"
   GIT_REPOSITORY: "cluster-issues"
   GIT_TOKEN: "ghp_..."
   ENABLE_TIER2_GITOPS: "true"
   ENABLE_TIER3_NOTIFY: "true"
   ```

See [deploy/GIT_PLATFORM_CONFIGURATION.md](deploy/GIT_PLATFORM_CONFIGURATION.md) for details.

---

## 📈 Monitoring

```bash
# Health check
curl $(oc get route sre-agent -n sre-agent -o jsonpath='{.spec.host}')/health

# Live logs
oc logs -n sre-agent deployment/sre-agent -c agent -f

# Stats
curl $(oc get route sre-agent -n sre-agent -o jsonpath='{.spec.host}')/stats
```

---

## 🔄 Tier System

### Tier 1: Automated (Safe Actions)
- Restart crashlooping pods
- Delete completed/failed pods  
- Retry ImagePullBackOff
- **Safeguards**: RBAC check, 30min cooldown, max 3 attempts

### Tier 2: GitOps (PR with Fix)
- Memory/CPU limit increases
- Replica adjustments
- Config changes
- **Requires**: Git integration

### Tier 3: Notification (Issue Creation)
- Diagnostic report
- Root cause analysis
- Recommended actions
- **Requires**: Git integration

---

## 🐛 Troubleshooting

**Pod not starting?**
```bash
oc describe pod -n sre-agent -l app=sre-agent
```

**No MCP tools (0 instead of 44)?**
```bash
oc logs -n sre-agent deployment/sre-agent -c mcp-server
# Check transport is "streamable-http" in ConfigMap
```

**No observations?**
```bash
# Wait 30-60s for collection interval
oc logs -n sre-agent deployment/sre-agent -c agent | grep "observation_count"
```

---

## 📁 Files

```
agent/
├── README.md                          # This file
├── deploy/
│   ├── sre-agent-deployment.yaml      # ⭐ Main deployment manifest
│   └── GIT_PLATFORM_CONFIGURATION.md  # Git setup guide
├── demo/
│   ├── README.md                      # Demo guide
│   ├── run-demo.sh                    # Run test scenarios
│   └── verify-demo.sh                 # Verify results
├── requirements.txt                   # Python deps
├── Dockerfile                         # Container image
├── main.py                            # Entry point
└── sre_agent/                         # Source code
```

---

## ❓ FAQ

**Works on vanilla Kubernetes?**
Yes (some OpenShift-specific collectors will be skipped)

**Safe to enable Tier 1 auto-remediation?**
Yes - designed for safe actions with RBAC checks and cooldowns

**Resource usage?**
Default: 512Mi RAM, 250m CPU (scales with cluster size)

**Can I disable specific collectors?**
Yes - set collection interval to 0 in ConfigMap

---

**Image**: `quay.io/sureshgaikwad/ocp-sre-agent:2.0.3-amd64`
**Version**: 2.0.3
**Last Updated**: 2026-04-15
