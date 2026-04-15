# 🎯 OpenShift SRE Agent - Demo

Quick demo to verify the SRE Agent's Observe → Diagnose → Remediate capabilities.

## 📁 Files

| File | Purpose |
|------|---------|
| `DEMO_GUIDE.md` | Comprehensive demo documentation |
| `run-demo.sh` | **Quick start** - Runs all scenarios automatically |
| `verify-demo.sh` | Verifies agent detected and handled all scenarios |
| `demo-scenario-1-oom.yaml` | OOM Kill test case |
| `demo-scenario-2-hpa.yaml` | HPA at max replicas test case |
| `demo-scenario-3-crashloop.yaml` | CrashLoopBackOff test case |

## 🚀 Quick Start (5 minutes)

### Option 1: Automated Demo

```bash
cd demo/
./run-demo.sh
```

This will:
1. ✅ Verify agent is running
2. ✅ Deploy all 3 test scenarios
3. ✅ Monitor agent logs in real-time
4. ✅ Show observations and diagnoses

Press `Ctrl+C` when you've seen enough activity (after 2-3 minutes).

### Option 2: Manual Demo

```bash
# 1. Deploy scenarios
oc apply -f demo-scenario-1-oom.yaml
oc apply -f demo-scenario-2-hpa.yaml
oc apply -f demo-scenario-3-crashloop.yaml

# 2. Watch test pods
watch -n 5 'oc get pods -n sre-demo'

# 3. Monitor agent (in another terminal)
oc logs -n sre-agent deployment/sre-agent -c agent -f | \
  grep -E "observation_count|Diagnosis|OOM|HPA|CrashLoop"
```

## ✅ Verification

After running the demo (wait 2-3 minutes), verify results:

```bash
./verify-demo.sh
```

**Expected Output**:
```
=== Scenario 1: OOM Kill ===
Testing: OOM pods detected... PASS (found 3 matches)
Testing: Exit code 137 identified... PASS (found 2 matches)
Testing: Memory limit diagnosis... PASS (found 1 matches)

=== Scenario 2: HPA at Max ===
Testing: HPA detected... PASS (found 5 matches)
Testing: Max replicas identified... PASS (found 2 matches)

=== Scenario 3: CrashLoop ===
Testing: CrashLoop detected... PASS (found 4 matches)
Testing: MCP pods_log called... PASS (found 1 matches)

✅ All tests PASSED!
   The SRE Agent is functioning correctly.
```

## 📊 What to Look For

### In Agent Logs

**Observations (Detection)**:
```
Retrieved 3 pods
observation_count: 3
```

**Diagnoses (Analysis)**:
```
Diagnosis created: OOMKilled
Root cause: Memory limit too low (128Mi)
Recommendation: Increase to 512Mi
```

**MCP Tool Usage**:
```
Calling MCP tool: pods_log
namespace: sre-demo
pod: crashloop-test-xxxxx
```

### In Test Pods

```bash
oc get pods -n sre-demo
```

**Expected Status**:
```
NAME                              READY   STATUS             RESTARTS      AGE
oom-test-xxxxxxxxx-xxxxx          0/1     OOMKilled          3 (1m ago)    2m
hpa-test-xxxxxxxxx-xxxxx          1/1     Running            0             2m
hpa-test-xxxxxxxxx-yyyyy          1/1     Running            0             1m
crashloop-test-xxxxxxxxx-xxxxx    0/1     CrashLoopBackOff   4 (2m ago)    2m
```

## 🧹 Cleanup

```bash
oc delete namespace sre-demo
```

## 🐛 Troubleshooting

### Issue: No observations detected

**Cause**: Collection interval not elapsed yet
**Fix**: Wait 30-60 seconds for next collection cycle

### Issue: Pods not failing

**Verify**:
```bash
oc get pods -n sre-demo
oc describe pod -n sre-demo -l app=oom-test
```

**Fix**: Check pod events for actual failure status

### Issue: MCP tools not used

**Check MCP availability**:
```bash
oc logs -n sre-agent deployment/sre-agent -c agent | grep "tools available"
```

**Expected**: "44 tools available"

## 📖 Detailed Documentation

See [DEMO_GUIDE.md](DEMO_GUIDE.md) for:
- Detailed timeline of each scenario
- Step-by-step verification
- Expected agent workflow diagrams
- Troubleshooting guide

## 🎓 Learning Objectives

After running this demo, you'll understand:

1. **How the agent detects issues**
   - Pod collectors query Kubernetes API
   - Event collectors watch for Warning events
   - Autoscaling collectors monitor HPA status

2. **How diagnosis works**
   - Pattern-based analyzers (OOM, CrashLoop)
   - MCP tool integration for log analysis
   - LLM-based root cause analysis

3. **What remediation capabilities exist**
   - Tier 1: Automated fixes (when enabled)
   - Tier 2: GitOps PRs (when configured)
   - Tier 3: Issue creation (when configured)

## ⏭️ Next Steps

After validating the demo:

1. **Enable Tier 1 Auto-Remediation**:
   ```bash
   oc set env deployment/sre-agent -n sre-agent ENABLE_TIER1_AUTO=true
   ```

2. **Configure Git Integration** (for Tier 2/3):
   - See `deploy/GIT_PLATFORM_CONFIGURATION.md`

3. **Monitor Production**:
   ```bash
   oc logs -n sre-agent deployment/sre-agent -c agent -f
   ```

---

**Version**: 2.0.3
**Last Updated**: 2026-04-15
