# Unknown Issue Handling - Implementation Checklist

## ✅ What's Been Created

### 1. Architecture Documentation
- [x] **ARCHITECTURE_UNKNOWN_HANDLING.md** - Complete 6-layer architecture design
- [x] **QUICKSTART_UNKNOWN_HANDLING.md** - Step-by-step implementation guide
- [x] **UNKNOWN_HANDLING_SUMMARY.md** - Visual summary and lifecycle examples
- [x] **IMPLEMENTATION_CHECKLIST.md** - This file

### 2. Code Implementation
- [x] **sre_agent/analyzers/unknown_issue_handler.py** - Ultimate fallback analyzer (NEW)
  - Catches ALL observations (can_analyze → True)
  - NEVER returns None (always creates diagnosis)
  - Extracts error patterns
  - Generates investigation templates
  - Calculates severity scores
  - Gathers context (logs, events)

---

## 🚀 Next Steps: Get Started in 30 Minutes

### Step 1: Deploy Unknown Issue Handler (10 minutes)

**File**: `main.py`

**What to do**: Register UnknownIssueHandler as LAST analyzer

**Code to add**:
```python
# Import
from sre_agent.analyzers.unknown_issue_handler import UnknownIssueHandler

# In lifespan(), after LLMAnalyzer registration:
workflow_engine.register_analyzer(UnknownIssueHandler(mcp_registry))  # MUST BE LAST!
```

**Location**: Around line 121 in main.py

**Before**:
```python
# LLM analyzer is fallback - register LAST
workflow_engine.register_analyzer(LLMAnalyzer(mcp_registry))
print(f"   ✅ Registered {len(workflow_engine.analyzers)} analyzers")
```

**After**:
```python
# LLM analyzer is fallback - register second to last
workflow_engine.register_analyzer(LLMAnalyzer(mcp_registry))

# ⭐ Unknown Issue Handler - MUST BE LAST (ultimate fallback)
workflow_engine.register_analyzer(UnknownIssueHandler(mcp_registry))

print(f"   ✅ Registered {len(workflow_engine.analyzers)} analyzers")
```

### Step 2: Test It (5 minutes)

```bash
# Restart agent
python main.py

# Expected output:
# ✅ Registered 9 analyzers (one more than before)

# Trigger a workflow
curl -X POST http://localhost:8000/trigger-workflow

# Check logs
tail -f /path/to/logs | grep "Unknown issue"

# If you see unknown issues:
# ⚠️  Unknown issue detected - no analyzer matched this observation
#     observation_type: some_issue
#     fingerprint: abc123
#     severity_score: 7.5
#     total_unknowns: 3
```

### Step 3: Verify 100% Coverage (5 minutes)

```bash
# Before (with unknown issues):
# - Some observations return None from analyzers
# - Lost observations

# After (with UnknownIssueHandler):
# - ALL observations get diagnosed
# - No lost observations

# Check: All observations should produce diagnoses
# Every observation ID should have a corresponding diagnosis ID in logs
```

### Step 4: Review Unknown Issues (10 minutes)

```bash
# Unknown issues will create Tier 3 GitHub/Gitea issues
# Check your issue tracker for new issues with:
# - Title: "[LOW] Unknown - Manual Intervention Required"
# - Label: tier-3, unknown
# - Body: Investigation template with full context

# Review the investigation template:
# - Auto-detected error patterns
# - Container logs
# - Kubernetes events
# - Investigation checklist
```

**✅ Phase 1 Complete!**
You now have:
- ✅ 100% observation coverage
- ✅ Unknown issue tracking
- ✅ Investigation templates
- ✅ Foundation for learning

---

## 📈 Optional: Enable Advanced Features

### Option A: Add Dashboard (30 minutes)

**File**: `main.py`

**Code to add**:
```python
@app.get("/api/unknowns/dashboard")
async def get_unknowns_dashboard():
    """Dashboard for viewing unknown issues."""
    if not workflow_engine:
        raise HTTPException(status_code=503, detail="Workflow engine not initialized")
    
    # Get unknown issue handler
    unknown_handler = None
    for analyzer in workflow_engine.analyzers:
        if analyzer.analyzer_name == "unknown_issue_handler":
            unknown_handler = analyzer
            break
    
    if not unknown_handler:
        return {"summary": {"total_unknowns": 0}}
    
    return {
        "summary": {
            "total_unknowns": unknown_handler.unknown_count,
            "status": "tracking_in_memory"
        }
    }
```

**Test**:
```bash
curl http://localhost:8000/api/unknowns/dashboard

# Response:
{
  "summary": {
    "total_unknowns": 12,
    "status": "tracking_in_memory"
  }
}
```

### Option B: Persistent Storage (2-4 hours)

**Create**: `sre_agent/knowledge/unknown_issue_store.py`

See QUICKSTART_UNKNOWN_HANDLING.md Phase 3 for full code.

**Benefits**:
- Persistent tracking across restarts
- Deduplication by fingerprint
- Recurrence counting
- Resolution tracking

### Option C: Human Feedback API (3 hours)

**File**: `main.py`

**Add endpoints**:
- POST `/api/feedback/resolution` - Submit resolution for unknown
- POST `/api/feedback/false-positive` - Mark as noise

See QUICKSTART_UNKNOWN_HANDLING.md Phase 4 for full code.

**Benefits**:
- Teach agent how to handle similar issues
- Build knowledge base from human expertise
- Progressive learning

---

## 🎯 Success Criteria

### Immediate (After Step 1-4)
- [ ] All observations get diagnosed (check logs)
- [ ] Unknown issues tracked (count visible)
- [ ] Investigation templates generated (check GitHub issues)
- [ ] No None returns from analyzers

### Short-term (After Option A-C)
- [ ] Dashboard shows unknown metrics
- [ ] Unknowns stored in database
- [ ] Humans can submit resolutions
- [ ] Unknown rate decreasing

### Long-term (Future phases)
- [ ] Pattern discovery finds new patterns
- [ ] Auto-promotion of validated patterns
- [ ] Agent handles more issue types
- [ ] MTTR reduced for learned issues

---

## 🐛 Troubleshooting

### Issue: Analyzer not catching unknowns

**Symptom**: Still seeing None diagnoses

**Solution**:
```python
# Verify UnknownIssueHandler is registered LAST
for analyzer in workflow_engine.analyzers:
    print(f"Analyzer: {analyzer.analyzer_name}")

# Expected output (order matters!):
# Analyzer: crashloop_analyzer
# Analyzer: image_pull_analyzer
# Analyzer: autoscaling_analyzer
# ...
# Analyzer: llm_analyzer
# Analyzer: unknown_issue_handler  ← MUST BE LAST
```

### Issue: Unknown issues not visible

**Symptom**: Unknown issues created but can't see them

**Solution**:
```bash
# Check GitHub/Gitea for new issues
# Search for: label:unknown label:tier-3

# Or check logs
grep "Unknown issue detected" /path/to/logs

# Or use dashboard (if implemented)
curl http://localhost:8000/api/unknowns/dashboard
```

### Issue: Too many unknowns

**Symptom**: 50%+ of observations are unknown

**Possible causes**:
1. Missing specific analyzers
2. LLM not configured properly
3. New cluster with new issue types

**Solution**:
```bash
# Check LLM configuration
echo $LITELLM_URL
echo $LITELLM_API_KEY
echo $LITELLM_MODEL

# Review what types are unknown
# Group by observation_type
# If one type dominates, create specific analyzer for it
```

---

## 📊 Monitoring Commands

```bash
# Count unknown issues in logs
grep -c "Unknown issue detected" /path/to/logs

# Show unknown fingerprints
grep "Unknown issue detected" /path/to/logs | grep -o "fingerprint: [a-z0-9]*" | sort | uniq -c

# Show severity distribution
grep "Unknown issue detected" /path/to/logs | grep -o "severity_score: [0-9.]*" | awk '{print $2}' | sort -n

# Track unknown rate over time
grep "Unknown issue detected" /path/to/logs | awk '{print $1}' | cut -d'T' -f1 | sort | uniq -c

# Top recurring unknowns (by fingerprint)
grep "Unknown issue detected" /path/to/logs | grep -o "fingerprint: [a-z0-9]*" | sort | uniq -c | sort -rn | head -10
```

---

## 🚦 Phased Rollout Plan

### Week 1: Foundation
- [x] Create architecture docs
- [x] Implement UnknownIssueHandler
- [ ] Deploy to dev cluster
- [ ] Verify 100% coverage
- [ ] Review unknown issues

### Week 2: Observability
- [ ] Add dashboard endpoint
- [ ] Monitor unknown rate
- [ ] Classify top unknowns
- [ ] Create specific analyzers for common types

### Week 3: Persistence
- [ ] Implement UnknownIssueStore
- [ ] Migrate to database storage
- [ ] Add deduplication
- [ ] Track recurrence

### Week 4: Learning
- [ ] Implement feedback API
- [ ] Train SREs on resolution process
- [ ] Start capturing human resolutions
- [ ] Build knowledge base

### Month 2: Automation
- [ ] Implement pattern discovery
- [ ] Review pattern suggestions
- [ ] Deploy first auto-promoted patterns
- [ ] Measure unknown rate reduction

### Month 3: Scale
- [ ] Auto-promotion system
- [ ] Multi-cluster learning
- [ ] Predictive analytics
- [ ] Full automation

---

## 🎓 Training & Documentation

### For SREs
1. **Reviewing Unknown Issues**
   - How to read investigation templates
   - What to look for in logs/events
   - How to classify issues

2. **Submitting Resolutions**
   - Using feedback API
   - Writing good root cause analysis
   - Choosing appropriate tier

3. **Pattern Recognition**
   - Identifying recurring unknowns
   - Suggesting new analyzer rules
   - Reviewing pattern suggestions

### For Developers
1. **Creating Custom Analyzers**
   - When to create specific analyzer
   - How to extract patterns
   - Testing and validation

2. **Extending Unknown Handler**
   - Adding custom extractors
   - Enriching investigation templates
   - Custom severity scoring

---

## 📚 Reference

### Key Files
- `sre_agent/analyzers/unknown_issue_handler.py` - Core implementation
- `sre_agent/orchestrator/workflow_engine.py` - Analyzer registration
- `main.py` - Integration point
- `ARCHITECTURE_UNKNOWN_HANDLING.md` - Full architecture
- `QUICKSTART_UNKNOWN_HANDLING.md` - Implementation guide

### Key Concepts
- **Fingerprinting**: Deduplication by normalized error signature
- **Severity Scoring**: 0-10 scale for prioritization
- **Investigation Template**: Rich context for human review
- **Progressive Learning**: Unknown → Known → Automated
- **Human-in-the-Loop**: Safety via human validation

---

## ✨ Summary

**Minimum Viable Implementation** (30 minutes):
1. Add UnknownIssueHandler to main.py
2. Restart agent
3. Verify 100% coverage
4. ✅ Done!

**Full Implementation** (2-4 weeks):
1. Phase 1: Foundation (this checklist)
2. Phase 2: Observability (dashboard)
3. Phase 3: Persistence (database)
4. Phase 4: Learning (feedback API)
5. Phase 5+: Automation (pattern discovery, auto-promotion)

**Expected Outcomes**:
- ✅ Zero lost observations
- ✅ Unknown rate decreases over time
- ✅ Agent gets smarter continuously
- ✅ MTTR improves for learned issues
- ✅ SRE team has visibility into unknowns

---

## 🤝 Support

If you have questions or need help:
1. Review the architecture docs
2. Check this implementation checklist
3. Review the code comments in unknown_issue_handler.py
4. Check troubleshooting section above

**The agent is now ready to handle ANY issue, even ones it's never seen before!**
