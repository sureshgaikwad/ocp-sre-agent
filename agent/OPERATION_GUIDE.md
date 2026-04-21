# SRE Agent - Operations Guide

## 🚀 Quick Start

### Minimal Deployment (5 minutes)

```bash
# 1. Set required environment variables
export MCP_OPENSHIFT_URL=http://openshift-mcp:8080/sse
export LITELLM_URL=http://llm-proxy:8080
export LITELLM_API_KEY=your-api-key

# 2. Start agent
python main.py

# 3. Verify
curl http://localhost:8000/health
```

**Result**: Agent is running with pattern analyzers + LLM + unknown tracking.

---

## 📋 Configuration Options

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `MCP_OPENSHIFT_URL` | OpenShift MCP server URL | `http://openshift-mcp:8080/sse` |

### Recommended

| Variable | Description | Default |
|----------|-------------|---------|
| `LITELLM_URL` | LiteLLM API base URL | - |
| `LITELLM_API_KEY` | LiteLLM API key | - |
| `LITELLM_MODEL` | Model to use | `openai/Llama-4-Scout-17B-16E-W4A16` |

### Optional (Enhanced Features)

| Variable | Description | Default |
|----------|-------------|---------|
| `GIT_PLATFORM` | `github`, `gitlab`, or `gitea` | - |
| `GIT_SERVER_URL` | Git server URL | - |
| `GIT_ORGANIZATION` | Git organization/group | - |
| `GIT_REPOSITORY` | Repository for issues | - |
| `GIT_TOKEN` | Git API token | - |
| `SLACK_WEBHOOK_URL` | Slack webhook for notifications | - |
| `SRE_AGENT_ROUTE_URL` | External route URL | Auto-detected |
| `REDHAT_KB_SEARCH_ENABLED` | Enable Red Hat KB search | `false` |
| `RAG_ENABLED` | Enable internal docs search | `false` |
| `KNOWLEDGE_DB_PATH` | Knowledge base path | `/data/knowledge.db` |
| `PROMETHEUS_URL` | Prometheus URL | - |

---

## 🧪 Testing After Deployment

### 1. Health Check

```bash
curl http://localhost:8000/health | jq
```

### 2. Test Graceful Degradation

```bash
chmod +x scripts/test_graceful_degradation.sh
./scripts/test_graceful_degradation.sh
```

### 3. Monitor Unknown Rate

```bash
chmod +x scripts/monitor_unknown_rate.sh
./scripts/monitor_unknown_rate.sh
```

**Target**: Unknown rate should be < 10% (ideally < 5%)

### 4. Test Feedback API

```bash
chmod +x scripts/test_feedback_api.sh
./scripts/test_feedback_api.sh
```

---

## 🎓 Teaching the Agent (Feedback Loop)

### 1. List Unknown Issues

```bash
curl http://localhost:8000/unknown-issues?min_occurrences=3 | jq
```

### 2. Get Issue Details

```bash
fingerprint="abc123..."
curl http://localhost:8000/unknown-issues/$fingerprint | jq
```

### 3. Submit Resolution

```bash
curl -X POST http://localhost:8000/unknown-issues/$fingerprint/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "root_cause": "Database connection pool exhausted",
    "fix_applied": "Increased pool size from 10 to 50",
    "fix_commands": [
      "oc set env deployment/app DB_POOL_SIZE=50"
    ],
    "works_for_similar": true,
    "sre_name": "john.doe"
  }' | jq
```

---

## 📊 Monitoring

### Key Metrics

| Metric | Endpoint | Target |
|--------|----------|--------|
| Unknown Rate | `/stats` | < 5% |
| Diagnostic Success | `/stats` | > 95% |
| Resolution Rate | `/unknown-issues/stats/summary` | Increasing |

### Continuous Monitoring

```bash
# Monitor unknown rate every 60 seconds
watch -n 60 ./scripts/monitor_unknown_rate.sh

# Or set up cron job
*/15 * * * * /path/to/scripts/monitor_unknown_rate.sh
```

---

## 📚 API Reference

### Health & Stats

- `GET /health` - Health check + configuration
- `GET /stats` - Workflow + unknown stats  
- `POST /trigger-workflow` - Manually trigger workflow

### Unknown Issues

- `GET /unknown-issues` - List unknown issues
- `GET /unknown-issues/{fingerprint}` - Get issue details
- `POST /unknown-issues/{fingerprint}/resolve` - Submit resolution
- `GET /unknown-issues/stats/summary` - Unknown issue stats

### Remediation

- `POST /approve-remediation` - Approve/reject remediation

---

## 🔧 Troubleshooting

### High unknown rate (>10%)

1. Check LLM configuration
2. Enable Red Hat KB search: `export REDHAT_KB_SEARCH_ENABLED=true`
3. Submit resolutions for recurring unknowns

### Git integration not working

Check Kubernetes events as fallback:
```bash
oc get events -A --field-selector reason=SREAgentObservation
```

---

## 🎯 Success Criteria

### Immediate (After Deployment)
- [ ] Health endpoint returns healthy
- [ ] Workflow executes successfully
- [ ] Unknown issues are tracked

### Short-term (This Week)
- [ ] Unknown rate < 10%
- [ ] Graceful degradation tested

### Medium-term (This Month)
- [ ] Unknown rate < 5%
- [ ] 10+ resolutions submitted
- [ ] Resolution rate > 20%

### Long-term (This Quarter)
- [ ] Unknown rate decreasing monthly
- [ ] Agent handles 95%+ of issues
