# 🎯 OpenShift SRE Agent - Demo Guide

**Version**: 2.0.3
**Date**: 2026-04-15
**Purpose**: Verify agent functionality across Observe → Diagnose → Remediate workflow

---

## 📋 Pre-Demo Checklist

Before starting the demo, verify the agent is running:

```bash
# 1. Check agent is running with 2/2 containers
oc get pods -n sre-agent

# Expected output:
# NAME                         READY   STATUS    RESTARTS   AGE
# sre-agent-xxxxxxxxx-xxxxx    2/2     Running   0          5m

# 2. Verify MCP tools are available (should show 44 tools)
oc logs -n sre-agent deployment/sre-agent -c agent | grep "tools available"

# Expected: "✅ MCP initialization complete - 44 tools available"

# 3. Check current configuration
oc get configmap agent-config -n sre-agent -o yaml | grep -E "ENABLE_TIER|MODE"

# Expected:
# ENABLE_TIER1_AUTO: "true"   (or "false" for demo)
# ENABLE_TIER2_GITOPS: "false"
# ENABLE_TIER3_NOTIFY: "false"
# MODE: "continuous"
```

---

## 🧪 Demo Scenarios

### Scenario 1: OOM Kill (Memory Exhaustion)
**Tests**: Pod monitoring, OOM detection, memory analysis

### Scenario 2: HPA at Maximum Replicas
**Tests**: Autoscaling monitoring, capacity planning alerts

### Scenario 3: CrashLoopBackOff with Exit Code 1
**Tests**: Event detection, log analysis, diagnosis

---

## 🚀 Running the Demo

### Setup

```bash
# Create demo namespace
oc new-project sre-demo

# Apply all demo resources
oc apply -f demo-scenario-1-oom.yaml
oc apply -f demo-scenario-2-hpa.yaml
oc apply -f demo-scenario-3-crashloop.yaml
```

### Monitoring Commands

Open **3 terminal windows** for real-time monitoring:

**Terminal 1 - Agent Logs (Observations)**:
```bash
oc logs -n sre-agent deployment/sre-agent -c agent -f | grep -E "observation_count|Retrieved|CRITICAL|WARNING"
```

**Terminal 2 - Agent Logs (Diagnoses)**:
```bash
oc logs -n sre-agent deployment/sre-agent -c agent -f | grep -E "Diagnosis|remediation|Tier"
```

**Terminal 3 - Demo Pods**:
```bash
watch -n 5 'oc get pods -n sre-demo'
```

---

## 📊 Verification Timeline

### T+0:30 (30 seconds) - Observations Created
Agent should detect the failing resources.

**Verify**:
```bash
# Check if observations were collected
oc logs -n sre-agent deployment/sre-agent -c agent --tail=100 | \
  grep "observation_count" | tail -5
```

**Expected Output**:
```
"observation_count": 3  # (or higher depending on timing)
```

### T+1:00 (1 minute) - Diagnoses Created
Agent should analyze and categorize the failures.

**Verify**:
```bash
# Check diagnoses
oc logs -n sre-agent deployment/sre-agent -c agent --tail=200 | \
  grep -A 5 "Diagnosis created"
```

**Expected Output**:
```
Diagnosis created: OOMKilled
Diagnosis created: HPA_AT_MAX
Diagnosis created: CrashLoopBackOff
```

### T+2:00 (2 minutes) - Remediation Attempted
Agent should attempt fixes (if Tier 1 enabled).

**Verify**:
```bash
# Check remediation actions
oc logs -n sre-agent deployment/sre-agent -c agent --tail=200 | \
  grep -E "Remediation|action_taken"
```

---

## 🔍 Detailed Scenario Verification

### Scenario 1: OOM Kill

**What Happens**:
1. Pod `oom-test` starts and allocates 300MB RAM
2. Hits 128Mi memory limit → OOMKilled
3. Kubernetes restarts pod → cycle repeats

**Agent Should**:
- ✅ Detect pod in CrashLoopBackOff state
- ✅ Identify exit code 137 (OOMKilled)
- ✅ Diagnose as "Memory limit too low"
- ✅ Suggest increasing memory limit to 512Mi

**Verification**:
```bash
# 1. Check pod is OOMKilled
oc describe pod -n sre-demo -l app=oom-test | grep -A 5 "Last State"

# Expected:
#   Last State:     Terminated
#     Reason:       OOMKilled
#     Exit Code:    137

# 2. Check agent detected it
oc logs -n sre-agent deployment/sre-agent -c agent --tail=500 | \
  grep -i "oom\|137\|memory"

# Expected output includes:
#   "OOMKilled detected"
#   "exit_code": 137
#   "recommended_memory": "512Mi"
```

**Success Criteria**:
- [ ] Agent logs show "OOMKilled" diagnosis
- [ ] Root cause identified as "memory limit too low"
- [ ] Recommended action: increase memory from 128Mi to 512Mi

---

### Scenario 2: HPA at Maximum

**What Happens**:
1. Deployment `hpa-test` with min=1, max=2 replicas
2. HPA tries to scale based on 50% CPU target
3. Reaches max replicas (2) but still under load

**Agent Should**:
- ✅ Detect HPA has 2 current replicas = 2 max replicas
- ✅ Diagnose as "HPA at capacity"
- ✅ Suggest increasing maxReplicas

**Verification**:
```bash
# 1. Check HPA status
oc get hpa -n sre-demo hpa-test

# Expected:
# NAME       REFERENCE            TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# hpa-test   Deployment/hpa-test  50%/50%   1         2         2          2m

# 2. Check agent detected it
oc logs -n sre-agent deployment/sre-agent -c agent --tail=500 | \
  grep -i "hpa\|autoscal\|max.*replicas"

# Expected output includes:
#   "HPA at maximum replicas"
#   "current_replicas": 2
#   "max_replicas": 2
#   "recommendation": "increase maxReplicas"
```

**Success Criteria**:
- [ ] Agent logs show "HPA_AT_MAX" or "HPA_DEGRADED"
- [ ] Observation includes current_replicas=2, max_replicas=2
- [ ] Warning severity assigned

---

### Scenario 3: CrashLoopBackOff

**What Happens**:
1. Pod `crashloop-test` exits with code 1 immediately
2. Kubernetes restarts it repeatedly
3. BackOff interval increases (10s, 20s, 40s, ...)

**Agent Should**:
- ✅ Detect Warning event "BackOff"
- ✅ Get pod logs using MCP (`pods_log` tool)
- ✅ Analyze error message: "CRITICAL: Database not available!"
- ✅ Diagnose as application error (not OOM/SCC)

**Verification**:
```bash
# 1. Check pod is crashing
oc get pods -n sre-demo -l app=crashloop-test

# Expected:
# NAME                              READY   STATUS             RESTARTS      AGE
# crashloop-test-xxxxxxxxx-xxxxx    0/1     CrashLoopBackOff   5 (2m ago)    5m

# 2. Check agent detected it
oc logs -n sre-agent deployment/sre-agent -c agent --tail=500 | \
  grep -i "crashloop\|backoff"

# Expected output includes:
#   "CrashLoopBackOff detected"
#   "restarts": 5
#   "exit_code": 1

# 3. Verify MCP tools were used for log analysis
oc logs -n sre-agent deployment/sre-agent -c agent --tail=500 | \
  grep "pods_log"

# Expected:
#   "Calling MCP tool: pods_log"
#   "namespace": "sre-demo"
#   "pod": "crashloop-test-..."
```

**Success Criteria**:
- [ ] Agent logs show "CrashLoopBackOff" detection
- [ ] MCP `pods_log` tool was called
- [ ] Error message "Database not available" identified
- [ ] Diagnosis category: APPLICATION_ERROR

---

## 📈 Expected Agent Workflow

For each scenario, the agent should execute this workflow:

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. OBSERVE (Collectors)                                          │
│    ✓ PodCollector detects CrashLoopBackOff/OOMKilled            │
│    ✓ AutoscalingCollector detects HPA at max                    │
│    ✓ EventCollector detects Warning events                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. DIAGNOSE (Analyzers)                                          │
│    ✓ OOMAnalyzer: Checks exit code 137 → recommends more RAM    │
│    ✓ CrashloopAnalyzer: Calls MCP pods_log → analyzes error     │
│    ✓ AutoscalingAnalyzer: Detects capacity limit                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. REMEDIATE (Handlers) - IF TIER 1 ENABLED                     │
│    Tier 1 (Auto):                                                │
│      - Could restart crashlooping pod (if allowed)               │
│    Tier 2 (GitOps):                                              │
│      - Would create PR with memory increase (if Git enabled)     │
│    Tier 3 (Notify):                                              │
│      - Would create issue (if Git enabled)                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Success Metrics

After running all scenarios, verify:

### Observation Layer ✅
```bash
# Should show all 3 scenarios detected
oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | \
  grep "Retrieved.*pods" | tail -5

# Expected: Pod collector showing sre-demo namespace pods
```

### Diagnosis Layer ✅
```bash
# Should show 3+ diagnoses
oc logs -n sre-agent deployment/sre-agent -c agent --since=5m | \
  grep -c "Diagnosis created"

# Expected: >= 3
```

### MCP Tool Usage ✅
```bash
# Should show MCP tools were called
oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | \
  grep "Calling MCP tool"

# Expected: At least one "pods_log" call
```

---

## 🧹 Cleanup

```bash
# Remove demo resources
oc delete project sre-demo

# Verify cleanup
oc get pods -n sre-demo
# Expected: "No resources found in sre-demo namespace." or "project not found"
```

---

## 🐛 Troubleshooting

### Issue: Agent not detecting pods

**Check**:
```bash
# Is pod collector running?
oc logs -n sre-agent deployment/sre-agent -c agent --tail=100 | \
  grep "pod_collector"

# Are pods actually failing?
oc get pods -n sre-demo
```

**Fix**: Wait 30-60 seconds for collection interval.

### Issue: No diagnoses created

**Check**:
```bash
# Did observations get created?
oc logs -n sre-agent deployment/sre-agent -c agent --tail=100 | \
  grep "observation_count"

# Are analyzers enabled?
oc get configmap agent-config -n sre-agent -o yaml | grep TIER
```

**Fix**: Ensure observations are collected first.

### Issue: MCP tools not called

**Check**:
```bash
# Are MCP tools available?
oc logs -n sre-agent deployment/sre-agent -c agent | grep "tools available"

# Expected: "44 tools available"
```

**Fix**: Verify MCP sidecar is running (2/2 containers).

---

## 📊 Demo Reporting

After completing the demo, generate a summary:

```bash
# Create demo report
cat > demo-results.txt << 'EOF'
=== SRE Agent Demo Results ===
Date: $(date)
Agent Version: 2.0.3

Scenario 1 - OOM Kill:
- Observations: $(oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | grep -c "OOMKilled")
- Diagnoses: $(oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | grep -c "exit_code.*137")
- Status: [PASS/FAIL]

Scenario 2 - HPA at Max:
- Observations: $(oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | grep -c "HPA")
- Diagnoses: $(oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | grep -c "max.*replicas")
- Status: [PASS/FAIL]

Scenario 3 - CrashLoop:
- Observations: $(oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | grep -c "CrashLoopBackOff")
- MCP Tool Calls: $(oc logs -n sre-agent deployment/sre-agent -c agent --tail=1000 | grep -c "pods_log")
- Status: [PASS/FAIL]

Overall: [PASS/FAIL]
EOF

cat demo-results.txt
```

---

## ✅ Expected Demo Outcomes

| Scenario | Observation | Diagnosis | Recommended Action |
|----------|-------------|-----------|-------------------|
| **OOM Kill** | Pod CrashLoopBackOff, Exit 137 | OOMKilled, Memory too low | Increase memory to 512Mi |
| **HPA Max** | HPA at 2/2 replicas | Capacity exhausted | Increase maxReplicas to 5 |
| **CrashLoop** | BackOff events, Restart count | Application error | Check database connection |

---

**Next Steps**: After verifying the demo, you can enable Tier 1 auto-remediation or configure Git integration for Tier 2/3.
